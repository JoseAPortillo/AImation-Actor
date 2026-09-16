# Proposal: Phase A — Golden Poses + Timeslider

## Intent

Phase A of plan v0.3 (§2.1): an animator marks golden poses G1…Gn on a timeslider with a live 2D skeleton overlay. Today: no frame serving, no per-frame detection, no upload path, no video UI in frontend — the Phase A demo is impossible.

## Scope

### In Scope
- Backend: `GET /media/frame` (JPEG), `POST /media/upload` (multipart, `max_video_bytes`), sync single-frame pose endpoint (`asyncio.to_thread`) returning keypoints + confidence
- Shared `media_security.py`: `resolve_media_path()` from `FrameExtractorNode._resolve_video_path()`; one allowlist boundary for extractor + media router (D3)
- Frontend: `VideoTimeslider` (scrub/play, pins mark/drag/delete, live overlay + toggle, per-pin ⏳→✓/✗, hover thumbnail), Zustand pin store, `ApiClient` fetchFrame/upload/detect
- Pins merged onto pipeline result `NeutralMotionDoc.keyposes` after job success (gap f)
- Tests: media security (traversal/allowlist), endpoint, component/store

### Out of Scope
- No `video-source` schema change; `nodeCatalog.json` untouched (D2)
- No backend keyposes population — Phase C
- No Blender round-trip (Phase B), generative node (Phase C), WebSocket streaming
- Explicit nodeCatalog contract test (gap g) deferred

## Capabilities

### New Capabilities
- `video-media-serving`: frame + upload endpoints, shared security utility (gaps a, e)
- `golden-poses-ux`: timeslider, golden pins, overlay, per-pin detection UX (gaps c, d)
- `frame-pose-detection`: single-frame synchronous pose-2d endpoint (gap b)

### Modified Capabilities
- `video-preprocessing`: frame-serving endpoint + shared security utility (delta)
- `pose-estimation`: single-frame detection endpoint (delta)

## Approach

- New `api/routers/media.py` + `pose.py` registered in `main.py`; auth via `require_token`
- Path validation honors SDD §4.3 threat model: reject absolute/traversal paths, enforce `media_root` allowlist
- Frame decode and inference offloaded via `asyncio.to_thread`; JPEG via `StreamingResponse`; frontend debounce limits in-flight detection to 1 (D1)
- Overlay maps normalized keypoints × display size; schema unchanged (D2)

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `aimation_actor_core/api/routers/media.py` | New | frame + upload endpoints |
| `aimation_actor_core/api/routers/pose.py` | New | single-frame detection |
| `aimation_actor_core/shared/media_security.py` | New | allowlist path resolver |
| `aimation_actor_core/main.py` | Modified | register routers |
| `aimation_actor_core/infrastructure/video/frame_extractor.py` | Modified | use shared resolver |
| `frontend/src/components/canvas/VideoTimeslider.tsx` | New | video + pins + overlay |
| `frontend/src/components/canvas/SchemaNode.tsx` | Modified | timeslider for `video-source` |
| `frontend/src/state/useFlowStore.ts` | Modified | pin state |
| `frontend/src/api/ApiClient.ts` | Modified | fetchFrame/upload/detect |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| ONNX per-frame latency (50-200ms) | Med | `to_thread` offload + frontend debounce |
| Path traversal / size abuse | Low | shared allowlist (D3) + `max_video_bytes` |
| Overlay misalignment | Med | normalized coords × display size; hide toggle |
| Fixture drift if schema changes | Low | D2 forbids schema change |

## Rollback Plan

Revert the merge: remove `media.py`/`pose.py` routers + `media_security.py`, unregister from `main.py`, restore inline `_resolve_video_path()` in `frame_extractor.py`, revert `SchemaNode` to `NodeMotionPreview`. No migration, no schema change, no fixture drift. Uploads land only under `media_root`.

## Dependencies

Existing: `media_root`, `require_token`, `Pose2DNode` backends, OpenCV, pytest/vitest.

## Success Criteria

- [ ] `GET /media/frame` returns a JPEG for any frame of an uploaded video; traversal/absolute paths rejected
- [ ] Single-frame detection returns keypoints + confidence; event loop stays responsive (synthetic backend)
- [ ] Animator marks G1…Gn, scrubs, drags pins, toggles overlay, sees ✓/✗ per pin
- [ ] Pins merge onto `NeutralMotionDoc.keyposes` after job success
- [ ] pytest, vitest, mypy, ruff, import-linter all green