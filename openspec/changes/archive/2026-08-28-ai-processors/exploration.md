# Exploration: Real AI Processors (ai-processors)

## Current State

AImation Actor Core is a FastAPI modular monolith (`api/`, `domain/`, `infrastructure/`, `shared/`, `main.py`) on Python 3.11 (mypy pinned 3.11) / Pydantic v2, wired by DI at the composition root in `main.py`. The `graph-executor` change is archived: a real topological node-graph executor already runs synchronously inside `POST /jobs/graph/execute`.

Today the "AI" is absent. The three seed nodes in `infrastructure/virtual/nodes.py` (`pass-through`, `merge`, `frame-range`) are deterministic logic nodes. `infrastructure/ai_models/` and `infrastructure/video/` are empty packages (only `__init__.py`). `pyproject.toml` lists no heavy ML/video deps. `GET /health` hardcodes `"models": "none"`.

## Affected Areas

- `domain/pipeline/node.py` — `INode` protocol (`get_schema`, `async execute`, `async validate`) + `ExecutionContext`/`NodeOutput`/`ValidationResult`. A real AI node conforms to this; **no change needed**.
- `domain/pipeline/schema.py` — `NodeCategory` already has `AI`/`CLEANUP`/`SOURCE`/`OUTPUT`; `DataType` already has `FRAMES`, `FRAME_STREAM`, `KEYPOINTS_2D`, `POSE_3D`, `VIDEO_PATH`, `NEUTRAL_ANIMATION`. **No enum change needed for the first slice.**
- `infrastructure/virtual/node_registry.py` — `seeded_node_registry()`; new AI nodes register here (or a parallel registry builder) and get wired in `main.py`.
- `infrastructure/virtual/executor.py` + `stores.py` — `SynchronousGraphExecutor` drives `node.execute(...)` via `asyncio.wait_for`; `InMemoryJobStore._submit_graph` calls `asyncio.run(...)`. CPU-bound AI nodes will block the event loop (see Risks).
- `infrastructure/video/`, `infrastructure/ai_models/` — empty; the destinations for OpenCV preprocessing and torch/onnx models.
- `domain/animation/` — `NeutralMotion`/`Frame`/`Pose`/`Skeleton`/`Transform3D` exist and are pure; the *terminal* pipeline output (a `NeutralMotion` doc) already has a home.
- `pyproject.toml` — no heavy deps; `[tool.importlinter]` has `include_external_packages = false`, so external deps in `infrastructure` will not trip the layer linter.

## The Node Execution Contract (how a real AI node plugs in)

An AI node is just another `INode`:

```python
class Pose2DNode(INode):
    @staticmethod
    def get_schema() -> NodeSchema: ...  # type, category=AI, inputs/outputs/params
    async def execute(self, inputs, params, context) -> NodeOutput: ...  # real work
    async def validate(self, params) -> ValidationResult: ...
```

- `execute` is **async**, called with topologically-produced `inputs: dict[str, Any]`, validated `params`, and a frozen `ExecutionContext(trace_id, session_id, timeout_s)`.
- Output is `NodeOutput(values: dict[str, Any])` keyed by output-port name. Values are `Any` — in-memory NumPy arrays (frames) or dicts (keypoints) can flow through today because there is no serialization in the in-memory path.
- Registration is **static at import time** (`StaticNodeRegistry.register`), never from user input (SDD §4.3). `validate_graph` allowlists node types and checks port-type compatibility via `ports_compatible` (equal type or `ANY`).

## Layer Rules (what lives where)

- **domain** is pure: Python stdlib + Pydantic v2 only. It holds the contracts (`INode`, `NodeSchema`, `DataType`), the graph model/validation, and the pure animation entities (`NeutralMotion`, `Pose`, `Frame`, `Skeleton`). import-linter forbids `domain → infra/api`.
- **api** cannot import `infrastructure`.
- **infrastructure** may hold heavy deps (torch, onnxruntime, opencv, numpy). All ML/video work — model loading, inference, tensor→domain conversion — happens here and crosses back as pure domain entities (per `entities.py` docstring: "Tensors from infrastructure are NEVER exposed here").

**Consequence:** the AI node *classes* live in `infrastructure/ai_models/` and `infrastructure/video/`; only their *contract* (schema type strings, `DataType`, `NodeCategory`) is visible in `domain`. No heavy dep reaches `domain`.

## The Graph-Executor Architecture (how it runs real work)

`SynchronousGraphExecutor.run` validates → topologically sorts → iterates nodes, resolving each node's inputs from prior `outputs[node_id]`, constructing an `ExecutionContext`, and `await asyncio.wait_for(node.execute(...), timeout)` per node. `InMemoryJobStore._submit_graph` wraps this in `asyncio.run(...)` and maps exceptions → `JobStatus.FAILED`, output → `JobStatus.SUCCEEDED` with `result={"outputs": ...}`.

A real AI pipeline is therefore expressed as a **graph**: `video-source` (VIDEO_PATH→FRAMES) → `frame-extract`/preprocess → `pose-2d` (FRAMES→KEYPOINTS_2D) → `pose-3d` (KEYPOINTS_2D→POSE_3D) → … → a converter node producing a `NeutralMotion` (`NEUTRAL_ANIMATION`). Each is an allowlisted `INode`; the executor already knows how to run them in order with per-node timeouts. **The executor itself does not change** — AI processors are new node types, not a new execution model.

## Gap Analysis (what's missing for a real AI pipeline)

1. **No heavy deps.** `torch`, `onnxruntime`, `numpy`, `opencv-python-headless`, `mediapipe` all absent. Must be added to `[project]` dependencies or a new optional group (e.g. `[project.optional-dependencies] ai`).
2. **No video layer.** ffmpeg/OpenCV frame extraction, FPS detection, crop/resize live in `infrastructure/video/` — currently empty.
3. **No model runtime/wiring.** `infrastructure/ai_models/` empty; no model loader, caching, ONNX session management, or `models` status surfaced (health returns hardcoded `"none"`).
4. **Blocking event loop.** `execute` is `async` but `InMemoryJobStore` runs the whole graph via `asyncio.run(...)`. CPU/GPU-bound inference (seconds–minutes) will block the single event loop for the entire request. ADR-002 (synchronous in-request) is fine for seed logic nodes but does not scale to AI. First slice must either accept blocking (documented MVP limit) or offload via `asyncio.to_thread` inside the node.
5. **No concrete intermediate value objects in domain.** `KEYPOINTS_2D` / `POSE_3D` / `FRAMES` exist only as `DataType` enum strings; there is no domain container (e.g. `Keypoints2D`, `Pose3DSequence`, `FrameBatch`) to type the flow. Nodes can use infra-internal types for now, but the terminal `NeutralMotion` conversion boundary needs definition.
6. **Model asset strategy undefined.** Which pose model files, where they live, licensing, and download/verification are open. No `HashVerifier` integration is wired to `GET /health` "Model integrity" path despite `ModelIntegrityError` existing.
7. **Constraint conflict (⚠️ needs product decision).** Plan §12 names **MediaPipe Pose** as the MVP 2D estimator, but the documented ML-stack guardrail is "**only PyTorch / ONNX Runtime, no TensorFlow**". MediaPipe is neither torch nor ONNX (it ships `.tflite` + its own runtime). This must be resolved before any pose node: either adopt MediaPipe (amending the stack guardrail) or use a torch/ONNX pose estimator (e.g. RTMPose/RTMo via mmpose, or a plain ONNX pose model).

## Approaches

1. **First slice = real video preprocessing node (OpenCV)**
   - New `infrastructure/video/frame_extractor.py`: `FrameExtractorNode` (category `SOURCE`, `VIDEO_PATH → FRAMES`, params `start`/`end`/`resize`), decoding with `cv2.VideoCapture`, FPS detection. Registered in `seeded_node_registry`, health surfaces a "video: loaded" capability.
   - Pros: true first stage of the documented pipeline (§12); CPU-only, GPU-free, deterministic, testable with a tiny synthetic AVI/MP4 fixture; `opencv-python-headless` is the cheapest heavy dep (~50 MB, no display stack); zero model-asset/licensing risk; directly exercises the "real node" path exactly where `pass-through` used to be.
   - Cons: not "AI" yet (no ML); still leaves the blocking-executor question open (but frame extraction is I/O-ish, threads well).
   - Effort: Low.

2. **First slice = real 2D pose node (ONNX/torch)**
   - `infrastructure/ai_models/pose_2d.py`: load a small pose ONNX model via `onnxruntime`, `FRAMES/IMAGE → KEYPOINTS_2D`.
   - Pros: delivers actual AI; proves model loading/inference/session lifecycle.
   - Cons: requires choosing + bundling a model asset (size, license, determinism), `onnxruntime` dep, more test flakiness (numeric tolerance), and is blocked by the MediaPipe-vs-torch/onnx conflict above.
   - Effort: Medium.

3. **First slice = contract-first plumbing, no heavy deps**
   - Add domain value objects (`Keypoints2D`, `Pose3DSequence`, `FrameBatch`) + a stub `pose-2d` node emitting valid structures, wiring `KEYPOINTS_2D → POSE_3D → NeutralMotion` end-to-end.
   - Pros: zero new deps; clarifies the data-typing boundary before any ML lands.
   - Cons: not "real AI" (contradicts the stated goal); risks rework once real types/arrays land.
   - Effort: Medium.

## Recommendation

**Approach 1** — a real **video preprocessing node (`video-source` / `frame-extractor`) in `infrastructure/video/`**, implemented with `opencv-python-headless`, `VIDEO_PATH → FRAMES`, GPU-free and CPU-only. Register it in the static registry and surface it via `/nodes/types` and health.

Rationale: it is the genuine first stage of the documented §12 pipeline, it unblocks every downstream stage (pose can only run on extracted frames), it is "real" (writes to disk-adjacent frames, detects FPS) rather than a mock, it respects the layer rules cleanly (only the `SOURCE`/`FRAMES` contract sits in domain; OpenCV stays in infrastructure), and it adds exactly one heavy dep that is the smallest possible ML boundary crossing. The blocking-executor and MediaPipe-vs-torch/onnx questions are deferred to the pose-model slice, where they belong — but both MUST be resolved in the proposal (see Risks).

## Risks

1. **Event-loop blocking.** Running ROI-scale CPU inference inside `asyncio.run(...)` will stall the whole server. First slice is I/O-bound so it's tolerable, but the proposal must state the posture (accept for MVP vs. `asyncio.to_thread`/worker offload) before pose nodes land.
2. **MediaPipe vs. "torch/onnx only" conflict.** §12 MVP names MediaPipe Pose, which contradicts the documented ML-stack guardrail. Unresolved, this blocks the 2D pose slice and any dependency forecast.
3. **Model asset/licensing + determinism.** Any real pose slice needs a pinned model file, license review, checksum verification, and numeric-tolerance test strategy. Deferring keeps the first slice clean but it is a real cost on the horizon.
4. **`DataType` typing is currently string-only.** Frames/keypoints flowing as `Any` through `NodeOutput` is fine in-memory but has no schema enforcement; the converter boundary to `NeutralMotion` needs a concrete domain value object eventually (Approach 3 material).
5. **Dependency footprint creep.** Even "minimal" OpenCV/onnx adds heavy wheels and install surface; should be isolated in an `[project.optional-dependencies] ai` group so the core stays importable without them (mirrors the "heavy deps in infrastructure only" rule).

## Non-Goals (for the first slice)

- No pose estimation (2D or 3D), no SMPL/body-model fitting, no temporal cleanup/IK, no in-betweening.
- No GPU support; CPU-only.
- No model download/caching/verification infrastructure.
- No change to the executor, job lifecycle, or graph model.
- No MediaPipe decision — that stays a proposal/ADR question.

## Ready for Proposal

Yes — scoped to the video-preprocessing first slice. The orchestrator should tell the user: (a) the recommended first slice is a real OpenCV frame-extraction node (SOURCE, `VIDEO_PATH → FRAMES`), GPU-free and within the 300-line budget; and (b) two decisions must be resolved in or before the proposal: the event-loop blocking posture for CPU-bound nodes, and the MediaPipe-vs-torch/onnx stack conflict that blocks the pose-model slice.
