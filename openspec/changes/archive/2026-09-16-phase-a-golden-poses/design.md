# Design: Phase A — Golden Poses + Timeslider

## Technical Approach

Three token-protected endpoints (`/media/frame`, `/media/upload`, `/detect/...`) plus a shared `resolve_media_path()` allowlist (D3) enable frame serving, upload, and synchronous single-frame pose detection (D1). A frontend-only Zustand pin store (D2) drives `VideoTimeslider`; after job success, pins merge onto the result's `NeutralMotionDoc.keyposes`. All blocking cv2/inference work runs via `asyncio.to_thread` (existing `FrameExtractorNode` pattern). Because import-linter forbids `api → infrastructure`, both new endpoint capabilities are exposed as **domain protocols injected on `app.state`** (mirroring `NodeRegistry`/`JobStore`).

## Architecture Decisions

| Option | Tradeoff | Decision |
|---|---|---|
| **D1** Sync detection in-request | Batch/async vs latency ~50-200ms | `asyncio.to_thread` decode+infer; loop stays free; synthetic backend instant |
| **D2** Pins frontend-only | Schema change/persistence vs demo speed | Pin state in Zustand per node; `video-source` schema untouched; backend never stores pins |
| **D3** Shared path resolver | Inline checks per call site vs one boundary | `resolve_media_path(media_root, path)` in `shared/`; used by `FrameExtractorNode` **and** all new endpoints |
| Endpoint↔infra wiring | Router imports estimators (breaks lint) vs DI | Domain protocols `FrameProvider` (JPEG) + `SingleFramePoseDetector`; impls in `infrastructure/`, wired in `main.py` via `app.state` |
| Pin storage | Inside `useFlowStore` (undo/redo history pollution) vs dedicated store | New `usePinsStore` keyed by `nodeId` — matches `useUiStore`/`usePaletteStore`/`useJobStore` multi-store pattern |
| Keypose merge point | Display-level vs result-level | Pure `applyKeyposes(result, pins)` called in `useJobStore` when status→`succeeded` |
| Frame count for slider | New `/media/info` endpoint vs header | `X-Frame-Count` header on every frame response (no extra route) |
| Upload naming | Original name (clobbers fixtures) vs unique | `uploads/{uuid4[:12]}_{basename}` — no collisions, never overwrites |

## Data Flow

```
SchemaNode(video-source)
   │ params.video_path
   ▼
VideoTimeslider ── GET /media/frame?video_path&frame_index → img blob + X-Frame-Count
   │  mark pin → usePinsStore.addPin ── GET /detect/{video_path}/{frame_index}
   │                                    (resolve_media_path → to_thread decode → to_thread estimate)
   ▼
PoseRouter ── FrameProvider ── resolve_media_path (reject absolute/traversal before open)
              └ asyncio.to_thread(cv2 decode + JPEG)

animate: useJobStore.submit → poll → succeeded
         └ applyKeyposes(result, usePinsStore.getState()) → NeutralMotionDoc.keyposes
```

## File Changes

| File | Action | Description |
|---|---|---|
| `aimation_actor_core/shared/media_security.py` | Create | `MediaPathError` + `resolve_media_path(media_root, relative_path, *, must_exist=True)` |
| `aimation_actor_core/domain/media/frame_provider.py` | Create | `FrameProvider` protocol: `get_frame_jpeg`, `get_frame_count` |
| `aimation_actor_core/domain/animation/pose_detection.py` | Create | `SingleFramePose` + `SingleFramePoseDetector` protocol |
| `aimation_actor_core/infrastructure/video/frame_provider.py` | Create | `OpenCvFrameProvider` (to_thread decode/encode, resolver-guarded) |
| `aimation_actor_core/infrastructure/ai_models/detection.py` | Create | `SingleFramePoseDetectorImpl` — decode + `backend.estimate_single` |
| `aimation_actor_core/api/routers/media.py` | Create | `GET /media/frame`, `POST /media/upload` (`require_token`) |
| `aimation_actor_core/api/routers/pose.py` | Create | `GET /detect/{video_path:path}/{frame_index}` (`require_token`) |
| `aimation_actor_core/api/deps.py` | Modify | `get_frame_provider`, `get_pose_detector`, `get_settings` deps |
| `aimation_actor_core/main.py` | Modify | Wire providers on `app.state`; `include_router(media.router)`, `(pose.router)` |
| `aimation_actor_core/infrastructure/video/frame_extractor.py` | Modify | `_resolve_video_path` delegates to shared resolver (keep `VideoPathError` compat subclass) |
| `aimation_actor_core/infrastructure/ai_models/estimators.py` | Modify | `estimate_single(frame) -> SingleFramePose` on both backends; `confidence` on synthetic (0.95) |
| `frontend/src/api/ApiClient.ts` | Modify | `fetchFrameJpeg` (blob), `uploadVideo` (FormData), `detectPose` |
| `frontend/src/api/types.ts` | Modify | `DetectedKeypoint`, `SingleFramePose` |
| `frontend/src/state/usePinsStore.ts` | Create | Pin CRUD, per-pin ⏳→✓/✗, single-in-flight guard |
| `frontend/src/state/useJobStore.ts` | Modify | Merge pins on success (`applyKeyposes`) |
| `frontend/src/state/useFlowStore.ts` | Modify | `removeNode` also clears node pins |
| `frontend/src/core/keyposes.ts` | Create | Pure merge helper (frame≥1, weight∈[0,1]=confidence??1) |
| `frontend/src/core/skeletonOverlay.ts` | Create | Normalized keypoints × display size, COCO bones |
| `frontend/src/components/canvas/VideoTimeslider.tsx` | Create | Scrub/play/pins/overlay/hover-thumbnail/upload placeholder |
| `frontend/src/components/canvas/SchemaNode.tsx` | Modify | Render `VideoTimeslider` for `video-source` nodes |
| Tests | ~7 new, 4 modified | See Testing Strategy |

## Interfaces / Contracts

```python
# shared/media_security.py
def resolve_media_path(media_root: Path, relative_path: str, *, must_exist: bool = True) -> Path:
    """Reject absolute + traversal; require resolved path under media_root
    (and existing file when must_exist). Raises MediaPathError."""
```

```python
# domain protocols (implemented in infrastructure, injected via app.state)
class FrameProvider(Protocol):
    async def get_frame_jpeg(self, video_path: str, frame_index: int, width: int | None = None) -> tuple[bytes, int]: ...  # (jpeg, frame_count)
class SingleFramePoseDetector(Protocol):
    async def detect(self, video_path: str, frame_index: int) -> SingleFramePose: ...
class SingleFramePose(BaseModel):  # domain.animation.pose_detection
    keypoints: list[Keypoint]   # reuses existing domain model
    confidence: float = Field(..., ge=0.0, le=1.0)
```

```typescript
// frontend/src/state/usePinsStore.ts
type PinStatus = "processing" | "success" | "error";
interface Pin { id: string; label: string; frame: number; status: PinStatus;
                confidence: number | null; detection: DetectedKeypoint[] | null; }
interface PinState { pinsByNode: Record<string, Pin[]>;
  addPin(nodeId: string, frame: number): void;   // label = G{maxSuffix+1}; guarded detect
  movePin(nodeId: string, pinId: string, frame: number): void;
  removePin(nodeId: string, pinId: string): void; removeNodePins(nodeId: string): void; }
```

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit (py) | `resolve_media_path` | absolute/traversal/escape rejected, missing file, `must_exist=False`, non-file — never opens |
| Integration (py) | Endpoints in `tests/api/test_api.py` | `TestClient` + `Settings(media_root=tmp_path)`: frame OK + `X-Frame-Count`, out-of-range/traversal → 400, upload OK + oversize rejected, 401s; detect returns scripted synthetic keypoints+0.95 deterministically |
| Unit (py) | `estimate_single` backends, extractor delegation | synthetic fixed output; resolver shared across call sites |
| Unit (ts) | `usePinsStore`, `applyKeyposes`, `skeletonOverlay` | add/move/delete/labels; no-pins → unchanged doc; weight=confidence; normalized mapping |
| Component (ts) | `VideoTimeslider` | placeholder issues no request; scrub updates blob; toggle; per-pin ⏳→✓/✗; no overlapping detection |
| E2E (ts) | `useJobStore` success merge; `SchemaNode` gating | result gains `keyposes`; video-source renders timeslider |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary. Media path validation is a file-access boundary enforced by the shared allowlist resolver with RED tests above.

## Migration / Rollout

No migration required. Revert = unregister routers, drop `media_security.py`, restore inline `_resolve_video_path()`, revert `SchemaNode`.

## Open Questions

- [ ] Multi `video-source` graphs: Phase A merges ALL in-range pins (frame ≤ `duration_frames`) sorted by frame into one doc — confirm acceptable until Phase C keys keyposes per source.