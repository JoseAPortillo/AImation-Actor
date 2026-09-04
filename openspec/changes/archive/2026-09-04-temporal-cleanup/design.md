# Design: Temporal Cleanup (§12.4)

## Technical Approach

A single new `temporal-cleanup` CleanupNode (category CLEANUP) inserted after `video-to-motion` in the pipeline. It receives a `NeutralMotion`, walks its `frames` list, and applies a fixed five-stage deterministic, stateless filter chain: (1) One-Euro jitter smoothing, (2) foot-contact detection with hysteresis, (3) translation-only foot locking, (4) ground clamping, (5) root drift normalization. All math lives in `domain/animation/cleanup.py` (pure stdlib, no numpy). A thin INode wrapper in `infrastructure/ai_models/temporal_cleanup.py` mirrors the existing `VideoToMotionNode` pattern: dict coercion, `asyncio.to_thread`, and param validation.

Pipeline: `video-source → pose-2d → pose-3d → video-to-motion → temporal-cleanup`

## Architecture Decisions

| Decision | Options | Tradeoff | Decision |
|----------|---------|----------|----------|
| Math location | domain/cleanup.py vs infrastructure/ | Domain guardrail: no numpy; pure stdlib only. Keeps domain testable without IO. | `domain/animation/cleanup.py` |
| One-Euro vs Savitzky-Golay | One-Euro: pure-Python, stateless per-frame pass. Savitzky-Golay: needs scipy (unavailable on Py3.14). | scipy wheels risk; One-Euro is deterministic and parameterizable. | One-Euro filter |
| Contact heuristic | velocity+height vs pressure-based | Pressure not available from neutral motion data. Velocity+height is sufficient for post-hoc detection. | velocity + height with hysteresis |
| Foot lock scope | translation-only (XZ clamp) vs full 6-DOF IK | Rotational IK is deferred per design D5; scope control. | Translation-only XZ clamp at contact frames |
| INode pattern | async wrapper with asyncio.to_thread | Consistent with pose-3d and video-to-motion nodes (D7). | Same pattern |

## Data Flow

```
video-source → pose-2d → pose-3d → video-to-motion → temporal-cleanup
                                                     (NEW)
                                              ┌─────────────────┐
                                              │ 1. One-Euro      │  smooth per-joint jitter
                                              │ 2. Detect        │  velocity+height → contacts
                                              │ 3. Lock          │  XZ clamp at contact frames
                                              │ 4. Clamp         │  Y ≥ 0, raise hips if needed
                                              │ 5. Root norm     │  subtract cumulative drift
                                              └────────┬────────┘
                                                       │
                                              NeutralMotion (contacts populated)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `aimation_actor_core/domain/animation/cleanup.py` | Create | Pure-stdlib cleanup algorithms: one-euro, contact detection, foot lock, ground clamp, root normalization |
| `aimation_actor_core/infrastructure/ai_models/temporal_cleanup.py` | Create | TemporalCleanupNode INode wrapper (dict coercion, asyncio.to_thread, param validation) |
| `aimation_actor_core/infrastructure/virtual/node_registry.py` | Modify | Import + register TemporalCleanupNode as 8th seed |
| `aimation_actor_core/infrastructure/ai_models/__init__.py` | Modify | Re-export TemporalCleanupNode |
| `aimation_actor_core/domain/animation/__init__.py` | Modify | Re-export cleanup public API (cleanup_motion + defaults) |
| `tests/domain/test_cleanup.py` | Create | Unit tests for all five cleanup sub-stages |
| `tests/infrastructure/test_temporal_cleanup.py` | Create | INode integration tests (schema, execute, validate, asyncio.to_thread) |

## Interfaces / Contracts

### Domain — `domain/animation/cleanup.py`

```python
# Defaults (nominal thresholds for 172cm person at 24fps)
DEFAULT_MIN_CUTOFF: float = 1.0
DEFAULT_BETA: float = 0.5
DEFAULT_VELOCITY_THRESHOLD: float = 5.0    # cm/frame — below = potential contact
DEFAULT_HEIGHT_THRESHOLD: float = 10.0     # cm — foot Y above ground plane (local chain)
DEFAULT_HYSTERESIS_FRAMES: int = 4          # min frames to hold contact state

@dataclass(frozen=True)
class CleanupParams:
    min_cutoff: float = DEFAULT_MIN_CUTOFF
    beta: float = DEFAULT_BETA
    velocity_threshold: float = DEFAULT_VELOCITY_THRESHOLD
    height_threshold: float = DEFAULT_HEIGHT_THRESHOLD
    hysteresis_frames: int = DEFAULT_HYSTERESIS_FRAMES

def cleanup_motion(motion: NeutralMotion, params: CleanupParams | None = None) -> NeutralMotion:
    """Apply the five-stage deterministic cleanup chain. Returns a new NeutralMotion (frozen copy)."""
    ...
```

### Infrastructure — `infrastructure/ai_models/temporal_cleanup.py`

```python
class TemporalCleanupNode(INode):
    @staticmethod
    def get_schema() -> NodeSchema:
        # type="temporal-cleanup", category=NodeCategory.CLEANUP
        # input: motion (NEUTRAL_ANIMATION), output: motion (NEUTRAL_ANIMATION)
        # params: min_cutoff, beta, velocity_threshold, height_threshold, hysteresis_frames

    async def execute(self, inputs, params, context) -> NodeOutput:
        # dict coercion (NeutralMotion from job-store), asyncio.to_thread(cleanup_motion, ...)

    async def validate(self, params) -> ValidationResult:
        # positive numbers for thresholds, positive int for hysteresis_frames
```

## Default Threshold Values

| Parameter | Default | Rationale |
|-----------|---------|-----------|
| `min_cutoff` | 1.0 Hz | One-Euro low-pass cutoff; 1.0 preserves intentional motion while smoothing jitter at 24fps |
| `beta` | 0.5 | One-Euro speed coefficient; moderate responsiveness — higher beta = more lag reduction for fast motion |
| `velocity_threshold` | 5.0 cm/frame | Below ~120 cm/s at 24fps suggests stationary foot; conservative to avoid false contacts |
| `height_threshold` | 10.0 cm | Foot Y within 10cm of computed ground level = potential contact (accounts for shoe/ankle offset) |
| `hysteresis_frames` | 4 | At 24fps = ~167ms; prevents flicker at contact boundaries without masking real lift-offs |

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit (domain) | One-Euro: jitter reduction, no-jitter passthrough, determinism | Build NeutralMotion with synthetic jittered trajectories; assert variance reduced; assert byte-identical re-runs |
| Unit (domain) | Contact detection: velocity+height marks, hysteresis holds | Synthetic foot trajectory crossing threshold; assert contact persists N frames; assert no flicker |
| Unit (domain) | Foot lock: XZ zero drift at contact, rotation unchanged, non-contact free | Assert locked frames have XZ == contact XZ; quaternion untouched |
| Unit (domain) | Ground clamp: Y ≥ 0, hips raised by delta | Inject Y < 0 foot; assert Y ≥ 0 output; assert Hips translation adjusted |
| Unit (domain) | Root normalization: drift removed, relative motion preserved | Known linear drift; assert root drift == 0; assert child offsets relative to root preserved |
| Unit (domain) | Processing order: stages apply sequentially | Spy/assert each stage consumes previous output |
| Infrastructure | Schema type/category/ports/params | Mirror test_video_to_motion schema tests |
| Infrastructure | Execute: returns NeutralMotion, dict coercion, asyncio.to_thread | Mirror test_video_to_motion execute tests |
| Infrastructure | Validate: param type/range enforcement | Mirror test_video_to_motion validate tests |
| Infrastructure | Node registered as 8th seed | Assert `temporal-cleanup` in seeded_node_registry().list_schemas() |

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary.

## Migration / Rollout

No migration required. The node is new capability (flagged in registry). It is bypassable — graphs that don't include `temporal-cleanup` are unaffected. Existing 248 tests remain green. No NeutralMotion schema change.

## Open Questions

None.
