# Proposal: Temporal Cleanup (§12.4)

## Intent

Raw motion conversion produces jitter, foot sliding, and root drift that make the animation look robotic. This change adds a dedicated temporal cleanup stage to smooth jitter, detect and lock foot contacts, clamp feet to ground, and normalize root drift — the final stage before the motion is ready for rendering.

## Scope

### In Scope
- New `temporal-cleanup` CleanupNode (category CLEANUP) consuming and emitting `NEUTRAL_ANIMATION`
- Pure-stdlib math layer in `domain/animation/cleanup.py` (no numpy — domain guardrail)
- Thin INode wrapper in `infrastructure/ai_models/temporal_cleanup.py` (dict coercion, asyncio.to_thread, param validation)
- Algorithms: One-Euro jitter filter (deterministic, stateless), velocity/height foot-contact detection, translation-only foot locking (XZ clamp at contact), ground penetration clamp (Y=0), root drift normalization
- Register as 8th seed node in `infrastructure/virtual/node_registry.py`
- Populate existing `NeutralMotion.contacts` field (no schema change, no ADR)
- Strict TDD: domain tests for math, infrastructure tests for node wrapper

### Out of Scope
- Rotational IK (deferred per design D5)
- Savitzky-Golay filter (scipy not installed, Py3.14 wheel risk)
- NumPy in domain (guardrail: stdlib only)
- NeutralMotion schema changes (requires ADR)

## Capabilities

### New Capabilities
- `temporal-cleanup`: Dedicated post-processing stage for motion smoothing, foot contact detection/locking, ground clamping, and root drift normalization over a NeutralMotion document.

### Modified Capabilities
- `node-registry`: Seed nodes requirement changes from 7 to 8 nodes (adds `temporal-cleanup`).

## Approach

A single new node type `temporal-cleanup` inserted after `video-to-motion` in the pipeline. The node receives a `NeutralMotion` document, walks its `frames` list and `skeleton`, and applies a deterministic, stateless filter chain:
1. **Jitter smoothing** (One-Euro adaptive filter per joint translation)
2. **Foot contact detection** (velocity + height heuristic on LFoot/RFoot)
3. **Foot locking** (clamp XZ at contact frame — translation only, no rotation)
4. **Ground clamp** (Y ≥ 0, push hips up if needed)
5. **Root normalization** (subtract cumulative drift from root translation)

All math is pure-Python stdlib in `domain/animation/cleanup.py`. The INode wrapper is a thin async adapter mirroring the existing pattern (VideoToMotionNode).

Pipeline: `video-source → pose-2d → pose-3d → video-to-motion → temporal-cleanup`

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `aimation_actor_core/domain/animation/cleanup.py` | New | Pure-stdlib cleanup algorithms |
| `aimation_actor_core/infrastructure/ai_models/temporal_cleanup.py` | New | CleanupNode INode wrapper |
| `aimation_actor_core/infrastructure/ai_models/__init__.py` | Modified | Re-export new node |
| `aimation_actor_core/infrastructure/virtual/node_registry.py` | Modified | Register 8th seed node |
| `aimation_actor_core/domain/animation/__init__.py` | Modified | Re-export new domain types |
| `tests/domain/test_cleanup.py` | New | Domain math unit tests |
| `tests/infrastructure/test_temporal_cleanup.py` | New | Node integration tests |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Full rotational IK balloons scope | High | Strictly scoped to translation-only foot locking; rotation stays identity |
| scipy unavailable on Py3.14 | High | Avoid scipy; One-Euro is pure-Python and deterministic |
| Foot-contact flakiness at boundaries | Medium | Hysteresis in contact detection; pin test thresholds |
| Root normalization hides intentional drift | Low | Params overridable; defaults conservative; test with known drift signal |
| Pre-existing pytest collection errors (19) | Low | Unrelated env issue (PermissionError); note for CI hygiene |

## Rollback Plan

1. Remove `temporal-cleanup` from `node_registry.py` (back to 7 seed nodes)
2. Delete `infrastructure/ai_models/temporal_cleanup.py` and `domain/animation/cleanup.py`
3. Remove test files
4. Remove re-exports from `__init__.py` files
5. Run `pytest` — all 248 existing tests pass (pre-change baseline)

## Dependencies

- No new external dependencies (pure-Python stdlib only)
- Depends on existing `NeutralMotion` document structure (no schema change)
- Depends on `NodeCategory.CLEANUP` enum value (already exists)

## Success Criteria

- [ ] `temporal-cleanup` node registered and returned by `GET /nodes/types`
- [ ] Pipeline `video-source → pose-2d → pose-3d → video-to-motion → temporal-cleanup` executes end-to-end
- [ ] Output NeutralMotion has populated `contacts` field with foot contact samples
- [ ] Jitter reduction measurable: output joint trajectory variance < input variance (synthetic test)
- [ ] Foot-lock: detected contact frames show zero XZ drift in locked joints
- [ ] Ground clamp: no foot Y < 0 in output
- [ ] All new tests pass; all 248 existing tests remain green
- [ ] No numpy import in `domain/` (linter guardrail)
