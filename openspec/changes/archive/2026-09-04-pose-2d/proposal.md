# Proposal: 2D Pose Estimation (pose-2d)

## Intent

Ship the next stage of the AI pipeline (plan §12.2): a real **2D pose-estimation node** (`pose-2d`, category `AI`) that consumes the `FRAMES` produced by `video-source` and emits typed `KEYPOINTS_2D`. Today the pipeline stops at frames — `DataType.KEYPOINTS_2D` exists but nothing produces it. This change makes `video-source → pose-2d` a working, typed video-to-keypoints stage.

The stack is fixed by decision D2 (from the ai-processors proposal): **ONNX / torch only — no MediaPipe, no TensorFlow**. The estimator is an ONNX RTMPose model (production backend), with a deterministic synthetic backend so the graph e2e and CI stay stable.

## Current-state Gap

The `graph-executor` and `ai-processors` changes are archived and live. `FrameExtractorNode` (`video-source`) reliably decodes video → `FRAMES` + `fps`, allowlist-validated and offloaded via `asyncio.to_thread`. But:
- Nothing produces `KEYPOINTS_2D`; `infrastructure/ai_models/` is empty.
- `DataType.KEYPOINTS_2D` is string-only — there is no concrete domain container to type the flow or cross the domain boundary (raw tensors must never reach domain).
- `GET /health` reports `"models": "none"`.

## Scope

In scope (all TDD, RED-first per phase):

1. **Domain value object `Keypoints2D`** — pure Pydantic container for one frame's 2D pose: a list of named keypoints (label + `x`/`y` normalized [0,1] + confidence). No tensors at the domain boundary. Types the `KEYPOINTS_2D` output.

2. **`pose-2d` node with a swappable estimator backend** (`infrastructure/ai_models/pose_2d.py`):
   - `Pose2DNode` (`INode`): schema type `pose-2d`, category `AI`; input port `frames` (`FRAMES`), output port `keypoints` (`KEYPOINTS_2D` = list of `Keypoints2D`); params `model` (STRING, optional — selects backend) and optional scale/confidence thresholds.
   - `PoseEstimator` protocol with two backends:
     - **Synthetic deterministic backend** — emits one fixed, scripted keypoint set per input frame (so graph e2e asserts exact counts/tuples, deterministic in CI).
     - **ONNX RTMPose backend** — wraps an `onnxruntime.InferenceSession` over a bundled/pointed RTMPose `.onnx`; runs per frame off the event loop (`asyncio.to_thread`, D1).
   - Backend selection by `model` param; unknown value falls back to synthetic (with a WARNING-style log) or is rejected per design.

3. **Wiring** — register `pose-2d` in `seeded_node_registry`; `GET /nodes/types` now lists 5 types (`pass-through`, `merge`, `frame-range`, `video-source`, `pose-2d`); `GET /health` surfaces pose backend availability (`"pose": "synthetic"` / `"onnx"`).

4. **Dependency** — add `onnxruntime` to `[project.optional-dependencies] ai` (alongside `opencv-python-headless`, `numpy`). Heavy dep stays in infra; core stays importable without it.

5. **E2E graph** — integration test: `video-source → pose-2d` through `SynchronousGraphExecutor`, asserting the output is a bounded list of `Keypoints2D` (deterministic backend). Note the job-store serialization fix from ai-processors (`_json_safe`/`_coerce` in `stores.py`) already handles non-primitive outputs — `Keypoints2D` Pydantic values must remain JSON-safe.

## Non-goals (first slice)

- No 3D lifting (2D→3D, §12.3), no temporal cleanup/IK (§12.4), no in-betweening/enrichment (§12.5), no SMPL/body-model fitting.
- No model download/caching/verification pipeline (deferred to the 3D-lifting slice). The ONNX backend reads a model path/asset the operator provides; asset acquisition is out of scope here.
- No MediaPipe / TensorFlow / GPU. No executor/job-lifecycle/graph-model/schema change (all enums/contracts already exist).
- The ONNX RTMPose weight file itself is not committed.

## Impact

- **New**: `domain/animation/keypoints.py` (or `domain/pipeline/`) — `Keypoints2D`; `infrastructure/ai_models/pose_2d.py`, `infrastructure/ai_models/estimators.py` (protocol + synthetic + onnx backends).
- **Modified**: `infrastructure/virtual/node_registry.py` (register `pose-2d`), `infrastructure/virtual/__init__.py` (re-export), `main.py` (health pose status), `pyproject.toml` (ai deps + onnxruntime).
- **Tests**: `tests/domain/test_keypoints.py`, `tests/infrastructure/test_pose_2d.py`, `tests/api/test_api.py` additions.
- **Blast radius**: bounded. No change to executor, job store, graph model, or schema enums. Existing 84 tests stay green.

## Edge cases & risks

- **onnxruntime wheel for Python 3.14** — must verify availability before committing; if unavailable on this environment, the ONNX import stays lazy/localized so tests and synthetic path never require it (documented fallback).
- **Determinism** — synthetic backend is fixed/scripted; real ONNX is non-deterministic and NOT asserted numerically in CI (only that it runs and emits the right shape when a model is present).
- **Event-loop blocking** — inference offloaded via `asyncio.to_thread` (D1); synthetic backend is trivially fast.
- **JSON-safety of `Keypoints2D`** — Pydantic models are already JSON-serializable; verify the stores `_json_safe`/`_coerce` path still works (it handles non-primitive outputs).

## Success criteria

- `/nodes/types` lists 5 types incl. `pose-2d`; `/health` shows pose backend.
- `video-source → pose-2d` graph executes; output is a list of `Keypoints2D` (deterministic count/shape).
- All quality gates pass: pytest (existing 84 + new), mypy, ruff check/format, import-linter (4 kept, 0 broken).
- New tests are RED-first (TDD), no committed binary model asset.

## Delivery

- Single work unit (~equivalent to ai-processors scale), within the 300-line review budget (test-heavy: value object + node + backends + wiring + e2e).
- Artifact store both (openspec + Engram), mode interactive, delivery ask-on-risk.
