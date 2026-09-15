# Tasks: Phase A — Golden Poses + Timeslider

Endpoints accept 1-based frames; decode converts to 0-based (cv2) at the interface boundary.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1450–1650 authored total (per PR: 300–350 / 380–440 / 300–360 / 380–460) |
| 400-line budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 → PR 3 → PR 4 (stacked to main) |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Medium

Each PR merges to main in order and lands independently, leaving main green: additive + refactor only, no behavior change inside one PR. PR 4 delivers the runnable Phase A demo.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Backend foundation: resolver + protocols + estimate_single + delegation (~300–350) | PR 1 → main | `pytest` `tests/shared/test_media_security.py` (read-only) `tests/infrastructure/test_estimators.py` (read-only) `tests/infrastructure/test_frame_extractor.py` (read-only) | N/A — unit + `tmp_path` fs | Revert `media_security.py` + delegation + `estimate_single`; additive only |
| 2 | Media + detect endpoints: OpenCvFrameProvider, detector, routers, DI wiring (~380–440) | PR 2 → main | `pytest` `tests/api/test_api.py` (read-only) -k "media or upload or detect" | TestClient + tmp `media_root` + `media/videos/fixture_walk.mp4` (read-only) | Unregister routers + deps + `main.py` wiring |
| 3 | Frontend core: types, ApiClient, pins, keyposes merge, overlay (~300–360) | PR 3 → main | `npx vitest run` `src/core/keyposes.test.ts` (read-only) `src/core/skeletonOverlay.test.ts` (read-only) `src/state/usePinsStore.test.ts` (read-only) | jsdom + MSW (`frontend/src/test/server.ts` (read-only)) | Revert additive helpers/stores |
| 4 | UI + merge wiring + full verify: timeslider, SchemaNode gating, job merge, cleanup (~380–460) | PR 4 → main | `npx vitest run` `src/components/canvas/VideoTimeslider.test.tsx` (read-only) `src/state/useJobStore.test.ts` (read-only) `src/components/canvas/FlowCanvas.gating.test.tsx` (read-only) then `.\.venv\Scripts\python.exe` (read-only) -m pytest + importlinter (5.1–5.4) | jsdom + MSW frame/detect mocks | Revert `VideoTimeslider` + `SchemaNode` + merge hook |

> One-pass slice estimate: PR 2 and PR 4 sit ~±50 of 400. If either exceeds ~400 at diff time, request a `size:exception` for that PR only — no further slicing pass.

### PR dependency diagram (stacked-to-main)

```
main ◄── 📍 PR 1  backend foundation (1.1–1.7)                    ← current — merges first
main ◄── PR 2  media + detect endpoints (2.1–2.8)                 ← after PR 1
main ◄── PR 3  frontend core (3.1–3.8)                            ← after PR 2
main ◄── PR 4  UI + merge wiring + verify (4.1–4.7, 5.1–5.4)     ← after PR 3 — runnable demo
```

Each PR targets `main` directly; the diagram shows merge order and logical dependency. Main stays green after every merge.

## Phase 1: Foundation

- [x] 1.1 RED `tests/shared/test_media_security.py`: absolute path, `../` (read-only) traversal, escape outside root, missing/non-file, `must_exist=False` — never opens
- [x] 1.2 GREEN `aimation_actor_core/shared/media_security.py`: `MediaPathError` + `resolve_media_path(media_root, relative_path, *, must_exist=True)` — allowlist, files-only (D3)
- [x] 1.3 `aimation_actor_core/domain/media/frame_provider.py`: `FrameProvider` protocol (`get_frame_jpeg`, `get_frame_count`); docstrings mark 1-based→0-based contract
- [x] 1.4 `aimation_actor_core/domain/animation/pose_detection.py`: `SingleFramePose` (reuses `Keypoint`) + `SingleFramePoseDetector` protocol
- [x] 1.5 RED `tests/infrastructure/test_estimators.py`: `estimate_single` on both backends; synthetic fixed 17 keypoints + 0.95 every call
- [x] 1.6 GREEN `aimation_actor_core/infrastructure/ai_models/estimators.py`: `estimate_single(frame)` on `SyntheticBackend`; `OnnxBackend` stays lazy (`NotImplementedError`, Phase C)
- [x] 1.7 `aimation_actor_core/infrastructure/video/frame_extractor.py`: `_resolve_video_path` → `resolve_media_path`; `VideoPathError` as `MediaPathError` subclass

## Phase 2: Core

- [x] 2.1 `aimation_actor_core/infrastructure/video/frame_provider.py`: `OpenCvFrameProvider` — `to_thread`, 1-based→0-based index, out-of-range reject, `(jpeg, frame_count)`
- [x] 2.2 `aimation_actor_core/infrastructure/ai_models/detection.py`: `SingleFramePoseDetectorImpl` — guard decode + `estimate_single` via `to_thread`; `NotImplementedError` → `PoseDetectionUnavailableError`
- [x] 2.3 `aimation_actor_core/api/routers/media.py`: `GET /media/frame` (`require_token`, 1-based `frame_index`, `width`?) → JPEG + `X-Frame-Count`; out-of-range/traversal → 400
- [x] 2.4 `aimation_actor_core/api/routers/media.py`: `POST /media/upload` — oversize `max_video_bytes` → 413; store `uploads/{uuid4[:12]}_{basename}`; return reference
- [x] 2.5 `aimation_actor_core/api/routers/pose.py`: `GET /detect/{video_path:path}/{frame_index}` — `require_token`, resolver + `to_thread`; unavailable → 501
- [x] 2.6 `aimation_actor_core/api/deps.py`: add `get_frame_provider`, `get_pose_detector`, `get_settings`
- [x] 2.7 `aimation_actor_core/main.py`: wire providers on `app.state`; register `media`/`pose` routers; 400/501 handlers
- [x] 2.8 RED `tests/api/test_api.py`: 200 JPEG + `X-Frame-Count`; 1-based boundary; out-of-range/traversal → 400; upload stored+name; oversize → 413; 401s

## Phase 3: Frontend Core

- [x] 3.1 `frontend/src/api/types.ts`: `DetectedKeypoint` (label, normalized x/y, confidence) + `SingleFramePose`
- [x] 3.2 `frontend/src/api/ApiClient.ts`: `fetchFrameJpeg` (Blob + `X-Frame-Count`), `uploadVideo`, `detectPose`
- [x] 3.3 RED `frontend/src/core/keyposes.test.ts`: merges ALL in-range pins (frame ≤ `duration_frames`) sorted; empty → doc unchanged; weight = confidence ?? 1
- [x] 3.4 GREEN `frontend/src/core/keyposes.ts`: pure `applyKeyposes(result, pins)`
- [x] 3.5 RED `frontend/src/state/usePinsStore.test.ts`: addPin G{n+1} + ⏳; movePin; removePin keeps labels; removeNodePins
- [x] 3.6 GREEN `frontend/src/state/usePinsStore.ts`: keyed by `nodeId`, ⏳→✓/✗, single-in-flight guard (D1)
- [x] 3.7 RED `frontend/src/core/skeletonOverlay.test.ts`: normalized × display size; COCO bones present
- [x] 3.8 GREEN `frontend/src/core/skeletonOverlay.ts`: `drawSkeleton` + `COCO_BONES`

## Phase 4: Integration

- [ ] 4.1 `frontend/src/components/canvas/VideoTimeslider.tsx`: scrub/play, range from `X-Frame-Count`, hover thumbnail, pin CRUD, overlay toggle, per-pin detect
- [ ] 4.2 `frontend/src/components/canvas/SchemaNode.tsx`: render `VideoTimeslider` for `video-source`; placeholder, no request without video
- [ ] 4.3 `frontend/src/state/useJobStore.ts`: on `succeeded`, `applyKeyposes(result, usePinsStore.getState())` before `set({ result })`
- [ ] 4.4 `frontend/src/state/useFlowStore.ts`: `removeNode` also calls `removeNodePins`
- [ ] 4.5 RED `frontend/src/components/canvas/VideoTimeslider.test.tsx`: scrub updates blob; ⏳→✓/✗; no overlapping detect; toggle; placeholder
- [ ] 4.6 Extend `frontend/src/state/useJobStore.test.ts`: merged `keyposes` with pins, unchanged without
- [ ] 4.7 Extend `frontend/src/components/canvas/FlowCanvas.gating.test.tsx`: `video-source` renders timeslider

## Phase 5: Verification + Cleanup

- [ ] 5.1 `.\.venv\Scripts\python.exe` (read-only) -m pytest full suite green
- [ ] 5.2 `npx vitest run` in `frontend/` — nodeCatalog fixture no drift (D2)
- [ ] 5.3 `.\.venv\Scripts\python.exe` (read-only) -m importlinter --show-timings — api→infrastructure ban holds
- [ ] 5.4 No `video-source` schema change; no temp artifacts left