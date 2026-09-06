# In-Between Generation Specification

## Purpose

An enrichment stage (`inbetween-generation`, `NodeCategory.ENRICHMENT` — a new additive category) that consumes a cleaned `NeutralMotion` (`NEUTRAL_ANIMATION`) and emits an enriched `NeutralMotion`: frame resampling (upsample), easing curves, rotation-continuity filtering, and optional tangent smoothing. Positioned after `temporal-cleanup` in the pipeline. Reuses `NeutralMotion` unchanged (no schema change, no ADR). Math lives in `domain/animation/inbetween.py` as pure stdlib (no scipy, no numpy), mirroring the temporal-cleanup precedent.

## Requirements

### Requirement: Keyframe-exact resampling

When `target_fps > meta.fps`, the system MUST resample the frame list onto the target-fps grid using the configured interpolation method (`cubic` cubic-Hermite or `linear`). The resampled output MUST preserve every source frame value exactly at its timeline position, MUST set `meta.fps` to `target_fps`, MUST set `duration_frames` to the output frame count, and MUST keep frames strictly increasing (invariants pass). When `target_fps <= meta.fps`, the system MUST NOT resample (downsampling is out of MVP scope) and MUST pass frames and `meta.fps` through unchanged. A single-frame motion MUST pass through unchanged.

#### Scenario: Upsample preserves keys

- GIVEN a 30fps NeutralMotion with 3 frames and `target_fps=60`
- WHEN the resampling stage runs with `cubic`
- THEN the output has 5 frames on the 60fps grid
- AND first/last output frames equal first/last source frames
- AND the interior source frame value appears exactly at its timeline position

#### Scenario: Cubic is C1-continuous

- GIVEN a curved source trajectory across 3 keyframes
- WHEN resampling runs with `cubic`
- THEN left/right derivatives match at each interior source frame (C1)
- AND with `linear` the same input stays piecewise-linear (C0 only)

#### Scenario: No downsampling in MVP

- GIVEN a 30fps motion with `target_fps=24`
- WHEN the resampling stage runs
- THEN the frame list and `meta.fps` are unchanged

#### Scenario: Single-frame motion

- GIVEN a NeutralMotion with exactly one frame
- WHEN the resampling stage runs
- THEN the output equals the input

### Requirement: Easing curves

When `easing` is not `none`, the system MUST apply the easing curve to each keyframe interval's timing so that motion speed follows the curve: `ease-in` accelerates toward the interval end, `ease-out` decelerates toward the interval end, `ease-in-out` accelerates then decelerates. Each curve MUST be monotonic over [0,1] with f(0)=0 and f(1)=1, keeping keyframe values exact at their positions. With `easing=none`, timing MUST be uniform.

#### Scenario: ease-in slows the interval start

- GIVEN a constant-velocity source with `easing=ease-in`
- WHEN the easing stage runs
- THEN speed in the first half of each interval is lower than in the second half

#### Scenario: ease-out slows the interval end

- GIVEN a constant-velocity source with `easing=ease-out`
- WHEN the easing stage runs
- THEN speed in the second half of each interval is lower than in the first half

#### Scenario: ease-in-out slows both ends

- GIVEN a constant-velocity source with `easing=ease-in-out`
- WHEN the easing stage runs
- THEN speed at each interval's midpoint exceeds speed near both interval ends

### Requirement: Rotation continuity filter

When `euler_filter=true` (default), the system MUST canonicalize each joint's rotation trajectory so consecutive normalized quaternions have positive dot product (no sign flips) and rotation interpolation between source frames follows the shortest arc. When `euler_filter=false`, the system MUST leave rotation samples unchanged.

#### Scenario: Quaternion sign flips removed

- GIVEN a joint whose consecutive source rotations alternate between q and -q
- WHEN the filter runs with `euler_filter=true`
- THEN every consecutive output quaternion pair has positive dot product

#### Scenario: Shortest-arc interpolation

- GIVEN two source rotations whose quaternions have negative dot product
- WHEN interpolation runs with the filter enabled
- THEN the trajectory follows the short arc, equivalent to interpolating the sign-canonicalized pair

#### Scenario: Filter disabled passes rotations through

- GIVEN alternating q / -q source rotations with `euler_filter=false`
- WHEN the stage runs
- THEN output rotation samples equal the input samples

### Requirement: Tangent smoothing

When `tangent_smoothing > 0`, the system MUST smooth per-joint trajectory tangents so that high-frequency jitter is reduced (per-joint variance does not increase). When `tangent_smoothing = 0` (default), the system MUST return trajectories unchanged (identity). Smoothing intensity MUST be non-decreasing with the parameter.

#### Scenario: Zero intensity is identity

- GIVEN `tangent_smoothing=0`
- WHEN the smoothing stage runs
- THEN joint trajectories are identical to the input

#### Scenario: Higher intensity does not add jitter

- GIVEN a jittered trajectory and intensities a < b in (0, 1]
- WHEN each runs on the same input
- THEN the b-output has no more high-frequency variance than the a-output

### Requirement: Node parameter validation

The `inbetween-generation` node MUST validate parameters before execution: `interpolation_method` in {"linear","cubic"} (default "cubic"), `easing` in {"none","ease-in","ease-out","ease-in-out"} (default "none"), `euler_filter` boolean (default true), `tangent_smoothing` number in [0,1] (default 0.0), `target_fps` positive number (default 30).

#### Scenario: Invalid enums rejected

- GIVEN `interpolation_method="spline"` or `easing="bounce"`
- WHEN node validation runs
- THEN validation fails and no execution occurs

#### Scenario: Out-of-range smoothing rejected

- GIVEN `tangent_smoothing=1.5` or `tangent_smoothing=-0.1`
- WHEN node validation runs
- THEN validation fails

#### Scenario: Non-positive fps rejected

- GIVEN `target_fps=0` or `target_fps=-30`
- WHEN node validation runs
- THEN validation fails

#### Scenario: Defaults are valid

- GIVEN no parameters provided
- WHEN node validation runs
- THEN validation passes with defaults (cubic, 30, none, true, 0.0)

### Requirement: Processing order and determinism

The system MUST apply the enrichment stages in fixed order: resample, easing, rotation filter, tangent smoothing. The stage MUST be stateless and deterministic: identical inputs yield byte-identical outputs on repeated runs, and the output MUST pass `NeutralMotion.validate_invariants()`.

#### Scenario: Fixed stage order

- GIVEN a valid NeutralMotion with all stages active
- WHEN the enrichment stage completes
- THEN each sub-stage consumed the previous one's output without reordering

#### Scenario: Repeated runs are identical

- GIVEN the same input and parameters
- WHEN the stage runs twice
- THEN both outputs are byte-identical

## Constraints (Non-Requirements)

- `domain/animation/inbetween.py` MUST stay pure stdlib (`math` only): no scipy, no numpy — AGENTS.md §3.1 hard constraint, mirroring the temporal-cleanup spec ("pure-stdlib for determinism"). Cubic Hermite implemented manually (~50 lines per proposal).
- `NeutralMotion` schema is unchanged — no versioned migration, no ADR. `NodeCategory` gains the additive member `ENRICHMENT` (new category; soft constraint: threat model + Security Champion sign-off per AGENTS.md §3.2, plus TypeScript catalog sync per `schema.py` contract).
- Node adapter `infrastructure/ai_models/inbetween_generation.py` follows the `TemporalCleanupNode` pattern: INode schema, dict coercion, `asyncio.to_thread`, param validation. Math lives in domain only; infrastructure owns no math.
- MVP leaves `contacts`/`keyposes` untouched (frame references may become stale after resampling; remapping is future work).
- Future scope (deferred, NOT requirements): arcs, procedural overlap, IK/FK blending, procedural secondary motion, per-bone easing, downsampling, full Euler/gimbal-lock correction.