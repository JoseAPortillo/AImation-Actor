# Design: 2D Pose Estimation (pose-2d)

## Technical Approach

Add the second genuine AI-pipeline stage: `Pose2DNode` (type `pose-2d`, category `AI`), a real node conforming to the `INode` contract that consumes `FRAMES` and emits typed `KEYPOINTS_2D`. The stack is fixed by D2 (ONNX/torch only, no MediaPipe/TF). The node delegates actual estimation to a swappable `PoseEstimator` backend so the graph e2e and CI stay deterministic (synthetic backend) while production can run a real ONNX RTMPose model (onnx backend). This mirrors the `FrameExtractorNode` pattern: only the typed contract (`Keypoints2D`, `DataType`) is visible in `domain`; the ONNX runtime and numpy never reach `domain`.

No executor, job-store, graph-model, or schema-enum change. `pose-2d` is just another allowlisted `INode` registration (SDD §4.3 static registration).

## Module Layout (respects layers)

```
domain/animation/keypoints.py        # Keypoints2D + Keypoint (pure Pydantic, no tensors)
domain/animation/__init__.py         # re-export Keypoints2D
domain/pipeline/schema.py            # unchanged (KEYPOINTS_2D already exists)
infrastructure/ai_models/estimators.py  # PoseEstimator protocol + SyntheticBackend + OnnxBackend
infrastructure/ai_models/pose_2d.py     # Pose2DNode (INode)
infrastructure/ai_models/__init__.py    # re-export Pose2DNode
infrastructure/virtual/node_registry.py # register pose-2d (fifth seed node)
infrastructure/virtual/__init__.py      # re-export Pose2DNode
main.py                                # health: pose backend status, DI wiring
pyproject.toml                         # [project.optional-dependencies] ai += onnxruntime
```

- **domain** stays pure (stdlib + Pydantic): `Keypoints2D`/`Keypoint` live here. No numpy/torch/onnx import.
- **infrastructure** owns heavy deps: ONNX Runtime session, estimator backends, numpy frames. Localizes imports so the synthetic-only path and tests never require onnxruntime installed.

## Domain Value Object

`Keypoints2D` — pure Pydantic container for one frame's 2D pose:

```python
class Keypoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    label: str  # e.g. "nose", "left_wrist"
    x: float = Field(ge=0.0, le=1.0)  # normalized
    y: float = Field(ge=0.0, le=1.0)  # normalized
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Keypoints2D(BaseModel):
    model_config = ConfigDict(frozen=True)
    frame_index: int = Field(ge=0)
    keypoints: list[Keypoint] = Field(default_factory=list)
```

- Normalized `x`,`y` in `[0,1]` and confidence in `[0,1]` enforced by `Field` constraints; Pydantic validates on construction.
- Frozen (immutable), mirroring the existing pure animation entities.
- JSON-serializable by construction → safe for the job-store `_json_safe`/`_coerce` path (ai-processors fix) which already handles non-primitive Pydantic outputs.

## Estimator Backend (protocol)

```python
class PoseEstimator(Protocol):
    def estimate(self, frames: list[Any]) -> list[Keypoints2D]:
        """Estimate one Keypoints2D per input frame. Synchronous (blocking)."""

class SyntheticBackend(PoseEstimator):
    # deterministic: a fixed scripted keypoint set per frame, frame_index = i

class OnnxBackend(PoseEstimator):
    # wraps onnxruntime.InferenceSession over an RTMPose .onnx; runs per frame;
    # returns normalized (x,y,confidence) keypoints
```

- `estimate` is **synchronous/blocking** by contract; `Pose2DNode.execute` offloads it via `asyncio.to_thread` (D1), same as `FrameExtractorNode._decode_blocking`.
- Running per-frame preprocessing (resize to model input, BGR→RGB) happens inside the backend; the node stays thin.
- `OnnxBackend` requires `onnxruntime`; imported lazily (inside the class/factory) so importing `estimators`/`pose_2d` never fails when onnxruntime is absent (Python 3.14 wheel availability is unverified).

## Node: Pose2DNode

```python
class Pose2DNode(INode):
    def __init__(self, model_dir: Path = Path("models")): self._model_dir = model_dir
    @staticmethod
    def get_schema() -> NodeSchema:
        # type="pose-2d", category=AI,
        # inputs=[frames(FRAMES)], outputs=[keypoints(KEYPOINTS_2D)],
        # params=[model(STRING, optional), confidence(NUMBER, default...)]
    async def execute(self, inputs, params, context) -> NodeOutput:
        frames = inputs["frames"]
        backend = self._build_backend(params)          # synthetic default
        per_frame = await asyncio.to_thread(backend.estimate, frames)
        # apply confidence threshold filter
        return NodeOutput(values={"keypoints": kps})
    def _build_backend(self, params) -> PoseEstimator:  # model param → OnnxBackend | SyntheticBackend
    async def validate(self, params) -> ValidationResult:  # model non-empty if provided
```

- Backend selection: `model` param names an ONNX asset under a models dir; if absent/unknown/unloadable → fall back to `SyntheticBackend` (never crash; no user-controlled path execution — SDD §4.3). The exact fallback-vs-reject behavior is pinned in tests.
- Output `keypoints` is `list[Keypoints2D]` (one per frame).

## Wiring & Health

- `seeded_node_registry(media_root=..., model_dir=...)` registers `Pose2DNode(model_dir=...)` as the fifth seed node.
- `GET /health` adds `"pose": "synthetic" | "onnx"` derived from whether an ONNX backend can be constructed (e.g. onnxruntime importable and model file present); defaults to `"synthetic"`.
- `GET /nodes/types` lists 5 types.

## Dependency

- `pyproject.toml`: `[project.optional-dependencies] ai = ["opencv-python-headless", "numpy", "onnxruntime"]`.
- Onnx import stays lazy/localized inside `OnnxBackend` so the synthetic path and CI never require the wheel.

## Tests (TDD, RED-first)

- `tests/domain/test_keypoints.py` — `Keypoints2D`/`Keypoint` normalization + confidence constraints; rejects out-of-range values.
- `tests/infrastructure/test_pose_2d.py` — schema (type/category/ports/params); synthetic backend determinism (same count/labels across runs); `execute` returns one `Keypoints2D` per frame; confidence filter; unknown `model` param falls back to synthetic; inference offloaded (patch `asyncio.to_thread`); path validation for `model` if any.
- `tests/infrastructure/test_executor.py` / `tests/api/test_api.py` — graph `video-source → pose-2d` e2e asserts bounded `list[Keypoints2D]`; `/nodes/types` lists 5 types; `/health` reports pose backend.

## Deviations / Gotchas (from ai-processors)

- Job-store serialization already fixed (`_json_safe`/`_coerce` in `stores.py`) — `Keypoints2D` must remain JSON-safe (it is, pure Pydantic).
- Environment is Python 3.14; mypy/ruff pinned to 3.14. Verify `onnxruntime` has a cp314 wheel before relying on it in production; the synthetic path works regardless.
- Local `import cv2` precedent: heavy deps imported inside methods/factory to keep module import cheap and dependency-optional.
