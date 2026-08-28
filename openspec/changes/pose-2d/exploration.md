# Exploration: 2D Pose Estimation (pose-2d)

## Current State

AImation Actor Core is a FastAPI modular monolith (`api/`, `domain/`, `infrastructure/`, `shared/`, `main.py`) on Python 3.14 (mypy/ruff now pinned to 3.14) / Pydantic v2, wired by DI at the composition root in `main.py`. Two SDD changes are archived and live: `graph-executor` (a real topological node-graph executor) and `ai-processors` (the first genuine AI stage — `FrameExtractorNode`, type `video-source`, category `SOURCE`).

The `graph-executor` change is archived: a real topological `SynchronousGraphExecutor` already runs synchronously inside `POST /jobs/graph/execute`, with job lifecycle `QUEUED → RUNNING → terminal` and per-node result collection.

The `ai-processors` change is archived: `FrameExtractorNode` (`infrastructure/video/frame_extractor.py`) decodes a video file into a list of frames (`FRAMES`) and reports `fps` (`NUMBER`). It validates `video_path` against an allowlisted `media_root` *before* `cv2.VideoCapture` (path allowlist, SDD §4.3) and offloads the blocking decode via `asyncio.to_thread` (decision D1). It is registered in `seeded_node_registry`.

Today the pipeline STOPS at frames. There is no pose estimation: `DataType.KEYPOINTS_2D` exists in `domain/pipeline/schema.py` but nothing produces it. `infrastructure/ai_models/` is an empty package (only `__init__.py`). `GET /health` reports `"models": "none"`.

### Decision D2 already resolved (from ai-processors proposal)

The pose-estimation stack MUST stay on **PyTorch / ONNX Runtime only — no MediaPipe, no TensorFlow**. MediaPipe ships `.tflite` + its own runtime and is excluded by the documented stack guardrail. The 2D-pose stage therefore uses an **ONNX/torch pose estimator** (e.g. RTMPose/ONNX). No ADR is required — the guardrail is kept intact (recorded in the ai-processors proposal as D2).

## Affected Areas

- `domain/pipeline/schema.py` — `DataType.KEYPOINTS_2D` exists; **no enum change needed**. `NodeCategory.AI` exists for the node's category.
- `domain/animation/entities.py` / `frame.py` / `skeleton.py` — pure animation entities (`Frame`, `Pose`, `Skeleton`, `Transform3D`). The terminal pipeline output (`NeutralMotion`) already has a home.
- `domain/pipeline/node.py` — `INode`/`NodeOutput`/`ValidationResult`/`ExecutionContext`; a real AI node conforms to this. **No contract change needed.**
- `infrastructure/ai_models/` — empty; the destination for the ONNX session + pose estimator.
- `infrastructure/virtual/node_registry.py` — `seeded_node_registry()`; the new `pose-2d` node registers here (or a parallel registry builder) and gets wired in `main.py`.
- `infrastructure/virtual/executor.py` + `stores.py` — `SynchronousGraphExecutor` drives `node.execute(...)` via `asyncio.wait_for`; `InMemoryJobStore._submit_graph` calls `asyncio.run(...)`. CPU-bound inference will block the event loop unless offloaded (see Risks; D1 already mandates `asyncio.to_thread`).
- `infrastructure/video/frame_extractor.py` — frame extraction done; its `FRAMES` output feeds `pose-2d`.

## The Node Execution Contract (how pose-2d plugs in)

`pose-2d` is just another `INode`:

```python
class Pose2DNode(INode):
    @staticmethod
    def get_schema() -> NodeSchema: ...  # type="pose-2d", category=AI, FRAMES→KEYPOINTS_2D
    async def execute(self, inputs, params, context) -> NodeOutput: ...  # run estimator per frame
    async def validate(self, params) -> ValidationResult: ...
```

- `execute` is **async**, called with topologically-produced `inputs: dict[str, Any]`, validated `params`, and a frozen `ExecutionContext`. Output is `NodeOutput(values: dict[str, Any])` keyed by output-port name (here `keypoints` of `DataType.KEYPOINTS_2D`).
- Registration is **static at import time** (`StaticNodeRegistry.register`), never from user input (SDD §4.3).
- The executor already knows how to run nodes in order with per-node timeouts — **the executor itself does not change**.

## Gap Analysis

1. **No concrete domain value object for keypoints.** `KEYPOINTS_2D` is only a `DataType` enum string; there is no domain container (e.g. `Keypoints2D` / `Keypoints2DFrame`) to type the flow. The terminal `NeutralMotion` conversion boundary defines `KEYPOINTS_2D → … → NeutralMotion`; this stage should introduce a typed container so downstream stages have a real contract. Per `entities.py`'s docstring, raw tensors are NEVER exposed at the domain boundary — keypoints must be concrete pure-domain value objects.
2. **No model runtime/wiring.** `infrastructure/ai_models/` empty — no ONNX session manager, model loader, caching, or `models` status surfaced in health.
3. **Model asset strategy undefined.** RTMPose weights (ONNX) — size, license, download/verification, and deterministic-test strategy are open. Models are internal infra assets, never fetched from user input.
4. **Blocking event loop.** CPU-bound inference (seconds) must be offloaded via `asyncio.to_thread` (D1), consistent with `FrameExtractorNode`.
5. **Testing determinism.** Real RTMPose inference is numeric and non-deterministic across platforms; CI needs either a deterministic test backend or a tiny fixed ONNX model, with tolerance-based assertions. The path-allowlist style parametrized tests will not apply the same way.

## Approaches

1. **Real ONNX RTMPose node with a swappable estimator backend (recommended)** — `infrastructure/ai_models/pose_2d.py` defines `Pose2DNode` (FRAMES→KEYPOINTS_2D) backed by a `PoseEstimator` protocol. Two backends: a **deterministic synthetic backend** (fixed, scripted keypoints — used for graph e2e and CI determinism) and the **real ONNX RTMPose backend** (production). Deps: add `onnxruntime` to `[project.optional-dependencies] ai`. Value object `Keypoints2D` in `domain`. Model asset optional at this slice (deferred download pipeline). Effort: Medium.
2. **Real ONNX node, single backend, mock in tests** — `Pose2DNode` directly consumes an `OnnxSession`. Tests mock the session with a tiny stub. Fewer moving parts but couples the node to a concrete runtime and makes the deterministic e2e graph harder. Effort: Medium.
3. **Contract-first plumbing (no ONNX yet)** — add `Keypoints2D` domain value object + `pose-2d` node wired `FRAMES → KEYPOINTS_2D` with a stub/synthetic output only. Zero heavy deps, but not real pose estimation; risks rework when the real model lands. Effort: Low.

## Recommendation

**Approach 1** — a real `pose-2d` node with a **swappable `PoseEstimator` backend** in `infrastructure/ai_models/`:

- Domain value object `Keypoints2D` (pure Pydantic, no tensors at the boundary) typing the `KEYPOINTS_2D` output.
- `infrastructure/ai_models/pose_2d.py` — `Pose2DNode` (`FRAMES → KEYPOINTS_2D`, category `AI`), `PoseEstimator` protocol, deterministic synthetic backend (test/CI) + ONNX RTMPose backend (production).
- Wire `pose-2d` into `seeded_node_registry`; `/health` surfaces pose model availability.
- Register `pose-2d` in `/nodes/types` (5 types with `video-source`).

Rationale: delivers a genuine, typed 2D-pose stage (the next eslabón of plan §12) that the graph e2e can run deterministically, keeps the ONNX/torch-only guardrail, respects layers (only `Keypoints2D` in domain; ONNX/session in infra), and defers the model-download/verification asset pipeline to the 3D-lifting slice (where the same mechanism is reused).

## Risks

1. **onnxruntime dependency weight / installation** — must stay in `[project.optional-dependencies] ai` so core stays importable; version pin + Python 3.14 wheel availability must be verified.
2. **Model asset/licensing + determinism** — RTMPose weight license and checksum verification are deferred, but the backend seam must be designed so the real model plugs in without rework. Tests use the deterministic backend, not fragile numeric tolerance on the real model.
3. **Event-loop blocking** — CPU-bound inference offloaded via `asyncio.to_thread` (D1); any per-frame/resize cost must not run on the loop.
4. **`DataType` is string-only** — fixed by the new `Keypoints2D` domain value object; `KEYPOINTS_2D` output carries a list of these.
5. **Dependency creep** — isolate `onnxruntime` in the `ai` optional group (mirrors "heavy deps in infrastructure only").

## Non-Goals (first slice)

- No 3D lifting (2D→3D, §12.3), no temporal cleanup/IK (§12.4), no in-betweening/enrichment (§12.5). No SMPL/body-model fitting.
- No model download/caching/verification infrastructure (deferred to the 3D-lifting slice).
- No MediaPipe / TensorFlow / GPU. No executor/job-lifecycle/graph-model change.

## Ready for Proposal

Yes — scoped to a real `pose-2d` node (FRAMES→KEYPOINTS_2D) with a swappable estimator backend, deterministic synthetic backend for CI, ONNX RTMPose backend for production, and a `Keypoints2D` domain value object. The proposal should confirm the product/scope decision: the synthetic-vs-real default in the first slice and whether `onnxruntime` is added now or deferred.
