# Archive Report — Real AI Processors (ai-processors)

**Change**: ai-processors (Real AI Processors — Video Preprocessing)
**Archived**: 2026-08-28
**Artifact store**: hybrid (OpenSpec files + Engram memories)

## Final State

- Tasks: 4/4 complete (Phases 1–4), single work unit
- Verification: PASS — 84/84 tests, 0 critical findings, 0 open blockers
- Deliverable: `FrameExtractorNode` (`video-source`, category `SOURCE`) — a real OpenCV video-decoding node conforming to the existing `INode` contract, running through the current graph executor unchanged.
- Delivery: single PR (within ~300-line review budget); applied inline (no subagents — billing blocked in this session).

## Scope Delivered

1. **Config & media root** — `Settings.media_root` setting; `seeded_node_registry(media_root=...)` registers `video-source`; `main.py` passes `settings.media_root`, `/health` reports `video: loaded`; `[project.optional-dependencies] ai = ["opencv-python-headless", "numpy"]`.
2. **FrameExtractorNode** — schema type `video-source`, category `SOURCE`; outputs `frames` (FRAMES) + `fps` (NUMBER); params `video_path` (VIDEO_PATH, required), `start`/`end`/`resize` (NUMBER, optional); FPS detection via `cv2.Capture`; decode offloaded via `asyncio.to_thread`.
3. **Path allowlist (SDD §4.3)** — rejects absolute / `..`-traversal / missing / non-file paths BEFORE `cv2.VideoCapture` via `VideoPathError`; static registration only; no shell/exec.
4. **E2E integration** — graph with `video-source` runs through `SynchronousGraphExecutor`; asserts `fps` + `len(frames)` (frames are np.ndarray, not JSON-serializable).

## Specs Promoted to openspec/specs/

- `openspec/specs/node-registry/spec.md` — MODIFIED: seed nodes now four (added `video-source`), delta applied to the archived spec.
- `openspec/specs/video-preprocessing/spec.md` — NEW capability spec promoted from the change folder.

## Deviations (deliberate, gatekeeper-approved)

1. **Job-store JSON serialization fix (design defect)**: `NodeOutput` carries `numpy.ndarray` frames; `stores.py` `_submit_graph` previously stored raw outputs → `PydanticSerializationError` on graph-execute. Fixed with `_json_safe`/`_coerce` flattening in `stores.py` (infrastructure). Design said "assert fps+len not pixels" but did not handle store serialization — resolved in apply.
2. **Python-version config sync (environment)**: venv is Python 3.14 + numpy 2.5.2 (cp314); `pyproject.toml` mypy/ruff pointed at 3.11, and mypy now fails parsing the numpy stub (3.12+ `type` syntax). Synced mypy `python_version` → 3.14 and ruff `target-version` → py314 (user-approved). Gates now run without manual flag.

## Non-Goals (remain for later slices)

- No pose estimation (2D/3D), no SMPL, no cleanup/IK, no GPU, no model download/caching/verification.
- No executor/job-lifecycle/graph-model change.
- D2 recorded: pose slice stays **torch/ONNX only** (MediaPipe excluded per stack guardrail).

## Relevant Files

- `aimation_actor_core/infrastructure/video/frame_extractor.py` — FrameExtractorNode
- `aimation_actor_core/infrastructure/virtual/{node_registry,stores,__init__}.py` — registry wiring + serialization fix
- `aimation_actor_core/shared/config.py` — media_root setting
- `aimation_actor_core/main.py` — DI wiring + health video:loaded
- `pyproject.toml` — ai optional deps + Python 3.14 target sync
- `tests/infrastructure/test_frame_extractor.py`, `tests/api/test_api.py` — coverage
