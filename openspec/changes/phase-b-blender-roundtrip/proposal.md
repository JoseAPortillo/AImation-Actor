# Proposal: Phase B — Round-trip Blender

## Intent

Phase B of plan v0.3 (§2.3): the animator sends golden poses to Blender, edits them in pose mode, and sends them back to the app. Today: `push_result` is a stub that returns `{"accepted": True}` without delivery; the addon has no receiver or pose-capture operator; the frontend has no round-trip buttons.

## Scope

### In Scope

1. **Core push delivery**: wire `push_result` to queue payloads; add `GET /sessions/{id}/pending` for addon to poll.
2. **Core pull endpoint**: `POST /sessions/{id}/submit_edited_poses` receives edited NeutralMotion from addon.
3. **Addon push receiver**: modal operator polls core, creates armature from NeutralMotion skeleton + keyposes.
4. **Addon pose capture**: operator reads bone transforms in pose mode, serializes to NeutralMotion, POSTs back.
5. **Frontend buttons**: "Enviar a Blender" and "Volver a la app" triggers.

### Out of Scope

- Blender pose-mode editing UX (standard Blender, not our code)
- Shadow rig baking (Phase D)
- Generative model (Phase C)
- WebSocket transport (long-poll for MVP)

## Technical Approach

### Communication Pattern

**Long-poll polling** (simplest for Blender's `bpy.app.timers`):
- Core queues payloads per session
- Addon polls `GET /sessions/{id}/pending` every 2s
- Core returns `200` with payload or `204` if empty

### Data Flow

```
Frontend → Core → Addon → Blender → Addon → Core → Frontend
   │         │       │        │        │       │       │
   │ push    │ queue │ poll   │ edit   │ capture│ store │ display
   └─────────┴───────┴────────┴────────┴───────┴───────┘
```

### Schema

```python
# Core: domain/dcc/push_payload.py
class PushPayload(BaseModel):
    kind: Literal["golden_poses", "edited_poses"]
    motion: NeutralMotion  # The full motion data
    source_frame_range: tuple[int, int] | None = None
```

### Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `POST /sessions/{id}/push_result` | `push_result()` | Queue payload for addon |
| `GET /sessions/{id}/pending` | `get_pending()` | Addon polls for payloads |
| `POST /sessions/{id}/submit_edited_poses` | `submit_edited_poses()` | Addon sends edited poses back |

### Addon Operators

| Operator | ID | Purpose |
|---|---|---|
| `AIM_OT_poll_pending` | `aim.poll_pending` | Modal: polls core for payloads |
| `AIM_OT_receive_poses` | `aim.receive_poses` | Creates armature from NeutralMotion |
| `AIM_OT_submit_edited` | `aim.submit_edited` | Captures pose mode edits, sends to core |

## Success Criteria

1. Animator clicks "Enviar a Blender" in frontend → armature appears in Blender with golden poses as keyframes.
2. Animator edits poses in pose mode → clicks "Volver a la app" → edited poses appear in app.
3. Round-trip preserves all joint transforms accurately.

## Risks

| Risk | Mitigation |
|---|---|
| Polling latency (2s) | Acceptable for MVP; WebSocket upgrade later if needed |
| Large NeutralMotion payloads | Phase A already handles frame-level data; no new size issues |
| Addon not running when push sent | Core queues; addon receives on next poll |

## Files to Change

### Core (Python)
- `aimation_actor_core/domain/dcc/push_payload.py` (NEW)
- `aimation_actor_core/domain/dcc/session.py` (add queue methods)
- `aimation_actor_core/infrastructure/virtual/stores.py` (implement queue)
- `aimation_actor_core/api/routers/sessions.py` (wire push_result, add pending/submit endpoints)

### Addon (Python, from feat/Develop)
- `blender_addon/core/client.py` (add poll_pending, submit_edited_poses)
- `blender_addon/ui/operators.py` (add 3 new operators)
- `blender_addon/ui/panel.py` (add round-trip buttons)

### Frontend (TypeScript)
- `frontend/src/components/canvas/VideoNode.tsx` (add "Enviar a Blender" button)
- `frontend/src/api/client.ts` (add submitEditedPoses call)

## Verification

- pytest: new tests for push payload, queue storage, pending endpoint, submit endpoint
- vitest: frontend button interactions
- Manual: Blender addon smoke test with round-trip
