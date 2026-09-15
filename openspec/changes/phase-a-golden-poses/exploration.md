## Exploration: Phase A — Golden Poses + Timeslider

### Current State

The system has a working AI pipeline for video-to-motion conversion: `video-source` (OpenCV decode) → `pose-2d` (COCO keypoints) → `pose-3d` (normalized 3D) → `video-to-motion` (NeutralMotion). The pipeline runs as a graph job via `POST /jobs/graph/execute`.

**What exists and is reusable:**
- `NeutralMotion.keyposes: list[KeyPose]` (Python, `neutral_motion.py:97`) with `KeyPose { frame: int ≥1, weight: float [0,1] }` — the contract is already in NeutralMotion v0.3, no version bump needed.
- TypeScript mirror `NeutralMotionDoc.keyposes?: KeyPose[]` (types.ts:130) already typed.
- `neutralMotionToBlocking.ts` already reads `doc.keyposes` and resolves frame positions (lines 66-85).
- `FrameExtractorNode._resolve_video_path()` (frame_extractor.py:75-101) is a tested security boundary that validates against `media_root` allowlist.
- `Pose2DNode` + `SyntheticBackend.estimate()` works for single-batch inference, offloaded via `asyncio.to_thread`.
- `require_token` dependency (deps.py:25-45) is reusable for any new router.
- `nodeCatalog.json` fixture (frontend/src/test/fixtures/) serves as implicit schema drift detector — tests fail if fixture doesn't match API.
- `media/` directory exists with test videos (Video_30fps.mp4, vtest.avi, vtest_short.mp4).

**What does NOT exist (gaps):**
| Gap | Layer | Impact |
|-----|-------|--------|
| **(a) No frame-serving endpoint** | Core API | No way to serve individual JPEG frames for timeslider preview. No `StaticFiles` mount, no `FileResponse`, no `/media/` route. |
| **(b) No per-frame pose-2d detection** | Core API | `Pose2DNode.execute()` only runs batch inference over `list[np.ndarray]`. No endpoint to detect a single frame's keypoints for a pin. |
| **(c) No timeslider/overlay component** | Frontend | `NodeMotionPreview` shows 3D stick figures only. No video rendering, no frame scrubber, no skeleton overlay on video, no pin UI. |
| **(d) No `keyposes` on video-source schema** | Core domain | `FrameExtractorNode.get_schema()` params: `video_path, start, end, resize`. No `keyposes` param — keyposes are output-side (`NeutralMotion.keyposes`), not source-side. |
| **(e) No video upload endpoint** ⭐ NEW | Core API | `FileParam` in SchemaNode.tsx stores only the filename (line 183: `onChange(file.name)`), never sends the file to backend. Videos must be manually placed in `media/`. The `config.py` `max_video_bytes` exists but has no upload route to enforce it. |
| **(f) Keyposes never auto-populated** ⭐ NEW | Core infra | `convert_keypoints_to_motion()` (motion_conversion.py:125-129) creates `NeutralMotion(meta=..., skeleton=..., frames=...)` without setting `keyposes`. The output NeutralMotion never carries user pins. |
| **(g) nodeCatalog.json is not a real contract test** ⭐ NEW | Frontend | The fixture is consumed as test data by `schema.test.ts`, `useJobStore.test.ts`, `roundtrip.test.ts` — but there is no explicit assertion comparing fixture against live API. Drift = implicit test failure when fixture doesn't match API. |

---

### Affected Areas

| File | Why |
|------|-----|
| `aimation_actor_core/api/routers/` | New router(s) for frame serving and single-frame detection |
| `aimation_actor_core/main.py` | Register new media router |
| `aimation_actor_core/infrastructure/video/frame_extractor.py` | Extract `_resolve_video_path` into shared security utility |
| `aimation_actor_core/infrastructure/ai_models/motion_conversion.py` | Consider populating keyposes in NeutralMotion output |
| `aimation_actor_core/domain/animation/neutral_motion.py` | **No change** — KeyPose contract already exists |
| `aimation_actor_core/domain/pipeline/schema.py` | **No change** — DataType and PortSpec already sufficient |
| `frontend/src/components/canvas/SchemaNode.tsx` | Replace `NodeMotionPreview` with `VideoTimeslider` for video-source nodes |
| `frontend/src/components/canvas/NodeMotionPreview.tsx` | **No change** — still used for non-video-source nodes |
| `frontend/src/api/ApiClient.ts` | Add `fetchFrame()` method for JPEG frame fetching |
| `frontend/src/api/types.ts` | **No change** — `KeyPose` and `NeutralMotionDoc.keyposes` already typed |
| `frontend/src/state/useFlowStore.ts` | Add pin state management (positions, processing status) |
| `frontend/src/test/fixtures/nodeCatalog.json` | Update only if `video-source` schema params change (D2) |

---

### Approaches

#### Approach 1: Sync Single-Frame Endpoint + Frontend-Only Pin State

Create `GET /media/frame?video=<name>&frame=<n>&width=<w>` returning JPEG bytes, and `POST /nodes/pose-2d/single` accepting a single frame index (resolved server-side from video) and returning keypoints synchronously. Pin positions stored in Zustand (`useFlowStore` or dedicated `usePinStore`). Keyposes merge onto the pipeline result's `NeutralMotionDoc.keyposes` in the frontend after job success.

- Pros: Simplest, fastest pin feedback (single round-trip), no async complexity
- Cons: Single-threaded inference blocks for slow models; N concurrent pin marks share the CPU
- Effort: Medium

#### Approach 2: Async Job for Detection + Frontend-Only Pin State

Create `POST /jobs/pin-detect` returning a job, frontend polls for result. Reuses existing `JobStore` infrastructure.

- Pros: Consistent with existing job system, handles slow inference gracefully
- Cons: 4+ round trips per pin (submit → poll → result → update), pin UX feels sluggish; requires new `JobKind`
- Effort: Medium-High

#### Approach 3: WebSocket Stream for Pin Detection

WebSocket endpoint streams detection results as pins are marked.

- Pros: Near-instant UX, single connection for all pins
- Cons: Significant infrastructure change, WebSocket auth complexity, out of scope for Phase A
- Effort: High

---

### Decision Resolutions

#### D1: Sync vs async per-frame detection → **SYNCHRONOUS (Approach 1)**

**Evidence:** `Pose2DNode.execute()` runs `asyncio.to_thread(backend.estimate, frames)` (pose_2d.py:118). `SyntheticBackend.estimate()` is instant (fixed output). `OnnxBackend.estimate()` is the expensive path (~50-200ms on CPU for a single frame). The UX spec describes pin detection as "silenciosa" happening "en segundo plano" — the "background" here means the UI doesn't block, not that detection must be async job.

**Rationale:** Single-frame ONNX inference ~50-200ms. User clicks "Marcar pose" → one POST → skeleton overlay updates in-place within one frame render cycle. An async job adds 3+ extra round trips (submit/poll/result/update). The endpoint is `async def` wrapping `asyncio.to_thread(backend.estimate, [single_frame])` — event loop stays responsive. If many pins are added rapidly, frontend debounce limits in-flight requests to 1.

#### D2: Pin storage → **FRONTEND-ONLY for Phase A**

**Evidence:** `video-source` is a SOURCE node with no input edges (frame_extractor.py:57-58). Keyposes are user-authored pin data, not node configuration. `neutralMotionToBlocking.ts` (lines 66-85) already resolves pins by matching `kp.frame` to `f.frame` in `NeutralMotionDoc.frames`. The existing flow: run graph → get NeutralMotionDoc → frontend merges pins → downstream nodes consume via BlockingInput.

**Rationale:** Phase A scope is timeslider + overlay, not generative pipeline. Keyposes need to flow to Phase C's generative node, but that node doesn't exist yet. Storing pins in Zustand is correct — they're UI state until committed. The `video-source` schema stays unchanged (no `keyposes` param drift), `nodeCatalog.json` fixture stays in sync. When Phase C adds the generative node, keyposes flow either via: (a) merged NeutralMotionDoc output (frontend merges pins onto pipeline result), or (b) a new output port. Avoid coupling source config to generative input.

#### D3: Frame endpoint security → **EXTRACT shared utility + new `/media/frame` router**

**Evidence:** `FrameExtractorNode._resolve_video_path()` (frame_extractor.py:75-101) contains the allowlist logic: reject absolute paths, reject traversal, check `is_relative_to(root)`, check exists, check is_file. The endpoint needs identical validation.

**Rationale:** Extract `resolve_media_path(media_root: Path, relative_path: str) -> Path` into `shared/media_security.py`. Both `FrameExtractorNode._resolve_video_path()` and the new `GET /media/frame` endpoint call the same utility. Security boundary stays in one place, tested once. New router: `GET /media/frame?video=<name>&frame=<n>&width=<w>` → `StreamingResponse(content_type="image/jpeg")`. Auth: reuse `require_token` dependency.

---

### Additional Risks

1. **No upload endpoint means "Cargar video" UX is broken** — `FileParam` stores only the filename locally; the file never reaches `media_root`. For Phase A to be end-to-end usable, a `POST /media/upload` multipart endpoint is needed. This may be a prerequisite for Phase A, or it may be acceptable if videos are placed manually in `media/` during development. **Recommend: include upload as a Phase A task.**

2. **`convert_keypoints_to_motion()` never populates keyposes** — Even if the backend eventually receives pin data, the pipeline result NeutralMotionDoc won't carry keyposes. Phase A can work around this (frontend merges), but for Phase C the generative node needs keyposes in the NeutralMotion output. **Recommend: add an optional `keyposes: list[KeyPose]` parameter to `convert_keypoints_to_motion()` in Phase C.**

3. **nodeCatalog.json contract test is implicit** — No explicit fixture-vs-API assertion. If the video-source schema changes (D2), the fixture must be manually updated. Tests using the fixture will fail, but the error message won't say "schema drift" — it'll say "expected X, got Y". **Recommend: add an explicit E2E contract test (pytest hits `/nodes/types`, compares against a Python-side golden).**

4. **Pin processing confidence indicator** — The plan specifies `⏳ procesando → ✓ confianza` or `✗` for each pin. The single-frame detection endpoint must return both keypoints AND a confidence score. `SyntheticBackend` always returns `confidence=0.95`; `OnnxBackend` will need to aggregate per-keypoint confidence into a frame-level score.

5. **Overlay coordinate mapping** — Skeleton overlay on video requires mapping normalized keypoints `[0,1]` to video pixel coordinates. The existing `Keypoint.x/y` is normalized. The overlay renderer must know the video display size to compute `px = x * display_width`.

---

### Ready for Proposal

Yes. The exploration is complete. Key decisions are resolved:
- **D1:** Synchronous per-frame endpoint (not async job)
- **D2:** Frontend-only pin state, no video-source schema change
- **D3:** Shared security utility + new `/media/frame` router

**Additional prerequisite identified:** A `POST /media/upload` endpoint is needed for end-to-end Phase A usability.

**Recommended scope for proposal:**
1. Backend: frame-serving endpoint, single-frame pose detection endpoint, video upload endpoint, shared security utility
2. Frontend: VideoTimeslider component (video preview + pin UI + skeleton overlay), pin state store, ApiClient extensions
3. Fixture: nodeCatalog.json update if schema changes (no change if D2 holds)
