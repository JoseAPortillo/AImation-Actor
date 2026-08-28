# Proposal: Real AI Processors (ai-processors)

## Intent

Ship the first genuine stage of the AI pipeline (plan §12): a real OpenCV video-preprocessing node that decodes a video into frames. Today the "AI" is absent — the three seed nodes are deterministic logic nodes, `infrastructure/video/` is empty, and `/health` hardcodes `"models": "none"`. This change adds one real node that conforms to `INode` and runs through the existing graph executor unchanged, unblocking every downstream stage.

## Scope

### In Scope
- `FrameExtractorNode` (type `video-source`, category `SOURCE`, `VIDEO_PATH → FRAMES`), params `start`/`end`/`resize`, FPS detection via `cv2.VideoCapture`.
- Register in `seeded_node_registry()`; surfaced via `GET /nodes/types`.
- `/health` reports `"video": "loaded"`.
- CPU-only, GPU-free; `opencv-python-headless` (+ `numpy`).
- Offload blocking decode with `asyncio.to_thread` inside the node (decision D1).

### Out of Scope
- No pose estimation (2D/3D), no SMPL/body fitting, no cleanup/IK, no in-betweening.
- No GPU; no model download/caching/verification.
- No executor/job-lifecycle/graph-model change.

## Capabilities

### New Capabilities
- `video-preprocessing`: a real OpenCV frame-extraction node (`video-source`) decoding `VIDEO_PATH → FRAMES`.

### Modified Capabilities
- `node-registry`: "Seed nodes" requirement gains a fourth seed node; `/nodes/types` now lists it.

## Approach

New `infrastructure/video/frame_extractor.py`: `FrameExtractorNode` implements the existing `INode` protocol (`get_schema`/`execute`/`validate`). `execute` offloads the blocking `cv2.VideoCapture` read loop via `asyncio.to_thread` so the job store's `asyncio.run(...)` does not stall the event loop (ADR-002 scope: CPU-bound nodes offload internally). Node class and OpenCV/numpy stay in `infrastructure`; only schema type strings/`DataType`/`NodeCategory` are visible in `domain`. Register the node in `seeded_node_registry()`; no executor changes.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `infrastructure/video/frame_extractor.py` | New | `FrameExtractorNode` (OpenCV decode) |
| `infrastructure/virtual/node_registry.py` | Modified | Seed + register `video-source` |
| `main.py` | Modified | `/health` adds `"video": "loaded"` |
| `pyproject.toml` | Modified | `[project.optional-dependencies] ai` adds `opencv-python-headless`, `numpy` |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Event-loop stall on decode | Med | `asyncio.to_thread` inside node (D1) |
| Arbitrary file read via `VIDEO_PATH` | Med | Validate/allowlist source path; no external-code exec (SDD §4.3) |
| Dependency footprint | Low | Isolate in `ai` optional group; core stays importable |

## Threat Model

`VIDEO_PATH` is user-supplied input. The node MUST validate/allowlist the source path (e.g., resolved under an allowlisted media root) before `cv2.VideoCapture` opens it, MUST NOT read arbitrary filesystem paths outside the defined contract, and MUST NOT execute any external code or shell. Registration remains static at import time. (SDD §4.3)

## Rollback Plan

Revert the feature branch commits for `frame_extractor.py`, `node_registry.py`, `main.py`, and `pyproject.toml`. No migration or data to roll back — removal returns the app to the three-seed-node state; `/nodes/types` and `/health` revert automatically.

## Dependencies

- `opencv-python-headless` and `numpy` in `[project.optional-dependencies] ai`.
- Note D1 (event-loop offload) and D2 (pose-2D stays torch/ONNX, not MediaPipe) as recorded posture for later slices.

## Success Criteria

- [ ] `GET /nodes/types` lists `video-source` / frame-extractor.
- [ ] Graph execution with a tiny synthetic video fixture extracts the correct frame count and FPS.
- [ ] `/health` reports `video: loaded`.
- [ ] import-linter passes (domain stays pure; api does not import infrastructure).
