# Temporal Cleanup Specification

## Purpose

A dedicated post-processing stage (`temporal-cleanup`) that smooths jitter, detects and locks foot contacts, clamps feet to the ground, and normalizes root drift over a `NeutralMotion` document. It consumes and emits `NEUTRAL_ANIMATION` (NodeCategory.CLEANUP) and reuses the existing `NeutralMotion.contacts` and `tracking` fields (no schema change, no ADR). All math is pure-stdlib (no numpy/scipy) for determinism.

## Requirements

### Requirement: Deterministic jitter smoothing (One-Euro)

The system MUST smooth per-joint translation jitter using a deterministic, stateless one-euro filter (pure stdlib, NO scipy, NO numpy). The filter MUST NOT retain state across calls.

- GIVEN a NeutralMotion with jittered joint trajectories (variance > threshold)
- WHEN the cleanup stage runs the one-euro filter
- THEN the output joint translation variance is lower than the input variance
- AND running the same input twice produces byte-identical output

#### Scenario: No-jitter passthrough

- GIVEN a NeutralMotion with already-smooth trajectories
- WHEN the one-euro filter runs
- THEN output trajectories are materially unchanged (no added artifacts)

### Requirement: Foot-contact detection with hysteresis

The system MUST detect foot contact frames for LFoot/RFoot using a velocity + height heuristic and MUST write results to `NeutralMotion.contacts["left_foot"]` / `["right_foot"]`. Detection MUST use hysteresis to prevent flicker at contact boundaries.

- GIVEN a frame where a foot's translation velocity is below threshold AND height is near the ground
- WHEN contact is evaluated
- THEN the frame is marked a contact sample in the corresponding `contacts` entry
- AND contact persists at least N frames once entered (hysteresis) before re-evaluating exit

#### Scenario: Contact boundary flicker suppressed

- GIVEN a foot hovering at the velocity/height threshold
- WHEN contact state is evaluated across consecutive frames
- THEN the marked contact state does not flip on every frame (hysteresis holds)

### Requirement: Translation-only foot locking

The system MUST lock a detected-contact foot by clamping its XZ translation at the contact frame. Rotation MUST NOT be modified (rotational IK is deferred).

- GIVEN a foot in contact state during a frame
- WHEN the lock applies
- THEN the foot's XZ translation equals the contact-frame XZ (zero drift)
- AND the foot's rotation quaternion is unchanged

#### Scenario: Non-contact foot stays free

- GIVEN a foot not in contact state
- WHEN the lock stage runs
- THEN the foot's XZ translation is not clamped

### Requirement: Ground clamp

The system MUST clamp every foot's Y coordinate to the floor (Y >= 0) and SHOULD translate the root hips upward by the correction delta when a foot penetrates below the floor.

- GIVEN an output frame containing a foot with Y < 0
- WHEN the ground-clamp stage runs
- THEN no foot has Y < 0 in the output
- AND when penetration occurred, the hips are raised by the corresponding delta

#### Scenario: Already-above-floor unchanged

- GIVEN feet all with Y >= 0
- WHEN the ground-clamp stage runs
- THEN foot positions are unchanged

### Requirement: Root drift normalization

The system MUST subtract the cumulative root translation drift while preserving relative motion between joints.

- GIVEN a NeutralMotion with cumulative root drift over its frames
- WHEN the root-normalization stage runs
- THEN the accumulated drift is removed from the root translation
- AND the relative offsets between root and child joints are preserved

#### Scenario: Zero-drift passthrough

- GIVEN a NeutralMotion with no cumulative root drift
- WHEN root normalization runs
- THEN root translation is unchanged

### Requirement: Processing order and determinism

The system MUST apply the cleanup stage in the fixed order: one-euro smoothing, foot-contact detection, foot locking, ground clamp, root normalization. The whole stage MUST be stateless and deterministic, producing reproducible output for a given input.

- GIVEN a valid NeutralMotion
- WHEN the cleanup stage completes
- THEN the five sub-stages ran in the specified order
- AND identical inputs yield identical output on repeated runs

#### Scenario: Order invariance of pipeline contract

- GIVEN the defined processing order
- WHEN the stage is invoked
- THEN each sub-stage consumes the output of the previous one without reordering
