# Quality Metrics (plan §21 Phase 1)

Deterministic, pure-domain scores for validating generated motion — the
automated half of the Phase 1 validation metrics (temporal stability, foot
sliding, approximate pose error, processing time) in
`docs/Plan_AImation_Actor_EXT.md` §21.

Implementation: `aimation_actor_core/domain/animation/metrics.py` (pure domain
— pydantic + domain types only, no I/O).

## Definitions

### jitter_score

Mean per-bone translation delta between consecutive frames:

```
mean( ||translation(bone, f+1) − translation(bone, f)||₂ )
```

over every bone present in both frames. Units: document units per frame
(typically cm/frame). A stable pose has a low score; high-frequency camera/pose
noise pushes it up. Returns `0.0` for motions with fewer than 2 frames.

### foot_sliding_score

Mean horizontal (x, z) displacement of the foot bones **while they are in
contact**:

```
mean( ||(x, z)(foot, f+1) − (x, z)(foot, f)||₂ )
```

Contact frames come from `motion.contacts` (`left_foot` / `right_foot` tracks
with `contact=True`); when no contact data exists, a deterministic fallback
flags frames whose foot bones sit at or below 20% of the global minimum foot
height. A planted foot should not move horizontally, so healthy clips stay
near zero. Returns `0.0` when there is no data.

### root_drift

Euclidean distance between the `Root` bone at the first and last frame:

```
||translation(Root, last) − translation(Root, first)||₂
```

Global locomotion drift in document units. A walk-in-place clip keeps this
small; a true walk shows the expected per-cycle displacement. Returns `0.0`
with fewer than 2 frames or when `Root` is missing.

## Usage

```console
aimation-eval report --motion motion.json [--out report.json]
```

- Reads a NeutralMotion JSON document (0.2 is migrated to canonical 0.3
  automatically, ADR-001).
- Prints a table with `jitter_score`, `foot_sliding_score`, `root_drift`,
  `frames`, and `duration_frames`.
- `--out` writes the same values as pretty JSON.
- Exit code 1 on unreadable input, invalid JSON, or an unsupported document
  version.

## Relation to plan §21 Phase 1 validation

| Plan metric | Automated proxy | Notes |
|---|---|---|
| Temporal stability | `jitter_score` | Per-bone translation deltas between consecutive frames |
| Foot sliding | `foot_sliding_score` | Horizontal foot velocity during contact windows |
| Approximate pose error | — | Needs a ground-truth pose source; reserved for the validation harness |
| Perceived quality | — | Human review pass, out of scope for the automated report |
| Processing time | — | Measured by the job runner, not the report |

The report covers the two scores that can be derived from the motion document
alone; pose error and processing time remain pipeline-level measurements.