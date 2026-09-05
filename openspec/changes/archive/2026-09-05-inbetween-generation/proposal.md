# Proposal: §12.5 In-between Generation and Enrichment

## Context

The AImation Actor pipeline currently produces a `NeutralMotion` through five stages:
1. `video-source` → frames
2. `pose-2d` → 2D keypoints
3. `pose-3d` → 3D keypoints
4. `video-to-motion` → neutral animation (local offsets)
5. `temporal-cleanup` → cleaned neutral animation (smoothing, foot lock, ground clamp, root normalization)

After cleanup, the motion is ready for export but lacks **inter-frame enrichment**: the pipeline produces one frame per input frame (typically 30fps), with no interpolation, easing, or euler angle correction. This results in mechanical, linear motion that lacks the natural acceleration/deceleration and smooth transitions expected in professional animation.

## Problem Statement

The current pipeline produces **per-frame motion** without:
- Frame interpolation (upsampling to higher fps)
- Easing curves (natural acceleration/deceleration)
- Euler angle filtering (gimbal lock prevention, discontinuity correction)
- Tangent smoothing (smoother joint trajectories)

This makes the output feel robotic and requires manual cleanup in DCC tools, defeating the purpose of automated video-to-animation.

## Proposed Solution

Add a new **`inbetween-generation`** node as the 9th seed node in the pipeline, positioned after `temporal-cleanup`:

```
... → temporal-cleanup → inbetween-generation → output
```

### Scope (MVP)

Implement four core techniques as a single node:

1. **Spline interpolation** (cubic Hermite, stdlib-only in `domain/`)
   - Upsample from source fps to target fps (e.g., 30→60fps)
   - Preserve keyframes exactly
   - Smooth interpolation between frames

2. **Easing curves**
   - `ease-in`: slow start, fast middle, fast end
   - `ease-out`: fast start, fast middle, slow end
   - `ease-in-out`: slow start, slow end
   - Applied globally or per-bone

3. **Euler filter**
   - Detect and correct angle discontinuities (>180° jumps)
   - Prevent gimbal lock artifacts
   - Ensure continuous rotation trajectories

4. **Tangent smoothing** (optional, parametrized 0-1)
   - Smooth joint trajectory tangents
   - Reduce jitter in joint angles
   - Configurable intensity

### Out of Scope (Deferred to Later Phases)

Per the product plan §12.5, these techniques are deferred:
- Arcs (natural curved trajectories)
- Procedural overlap (secondary motion delay between joints)
- IK/FK blending (requires full IK system)
- Procedural secondary motion (hair, cloth, tail)

These can be added as follow-up changes once the core in-between infrastructure is stable.

## Architecture

### Node Schema

```python
type: "inbetween-generation"
category: NodeCategory.ENRICHMENT  # new category
inputs: [motion: NEUTRAL_ANIMATION]
outputs: [motion: NEUTRAL_ANIMATION]
params:
  - interpolation_method: "linear" | "cubic" (default: "cubic")
  - target_fps: number (default: 30)
  - easing: "none" | "ease-in" | "ease-out" | "ease-in-out" (default: "none")
  - euler_filter: boolean (default: true)
  - tangent_smoothing: number 0-1 (default: 0.0)
```

### Module Structure

- **`domain/animation/inbetween.py`**: Pure math (stdlib + numpy only)
  - `InbetweenParams` (frozen dataclass)
  - `enrich_motion(motion, params) -> NeutralMotion`
  - Internal stages: upsample → easing → euler filter → tangent smooth

- **`infrastructure/ai_models/inbetween_generation.py`**: INode adapter
  - `InbetweenGenerationNode(INode)`
  - Follows the temporal-cleanup pattern (dict coercion, asyncio.to_thread)

- **`infrastructure/virtual/node_registry.py`**: Add 9th seed node

### Dependency Constraints

- **NO scipy in `domain/`** (guardrail violation)
- Cubic Hermite interpolation implemented manually (~50 lines)
- numpy allowed in `domain/` for math operations
- All math in `domain/`, only INode adaptation in `infrastructure/`

## Integration with Existing Pipeline

**Order**: cleanup FIRST, in-between AFTER
- `temporal-cleanup` cleans raw motion (removes noise, locks feet, stabilizes root)
- `inbetween-generation` enriches cleaned motion (interpolates, eases, filters euler)

No conflicts. Complementary stages.

## Testing Strategy

1. **Unit tests** with synthetic `NeutralMotion` (3-5 keyframes)
2. **Interpolation**: verify keyframes preserved, intermediate frames interpolated correctly
3. **Easing**: verify acceleration/deceleration curves applied
4. **Euler filter**: verify discontinuity correction (e.g., 179° → -179° becomes 179° → 181°)
5. **Tangent smoothing**: verify trajectory smoothness increases with parameter
6. **Snapshot tests**: deterministic output for regression detection

## Risks

1. **Euler filter complexity**: Correct gimbal lock prevention is non-trivial. May require more time than estimated.
   - **Mitigation**: Start with simple discontinuity detection (>180° jumps), defer full gimbal lock solution.

2. **Performance**: Upsampling to 60fps doubles frame count. For long videos (5min = 9000 frames → 18000 frames), may be slow.
   - **Mitigation**: Profile early. Consider chunked processing if needed.

3. **Scope creep**: Plan lists 9 techniques. MVP scope is 4.
   - **Mitigation**: Strict scope enforcement. Deferred techniques are separate changes.

## Estimated Effort

- **Lines of code**: ~400-500 (similar to temporal-cleanup)
  - `domain/animation/inbetween.py`: ~250 lines
  - `infrastructure/ai_models/inbetween_generation.py`: ~150 lines
  - `tests/`: ~100 lines
- **Tasks**: ~20-25 (similar to temporal-cleanup)
- **Time**: 1-2 days (assuming euler filter is straightforward)

## Open Questions

None. The scope, architecture, and integration are clear. Proceed to spec phase.

## Recommendation

**Proceed with spec → design → tasks → apply → verify → archive** for the MVP scope (4 techniques). Deferred techniques (arcs, overlap, IK/FK, secondary motion) can be addressed in follow-up changes once this infrastructure is stable.
