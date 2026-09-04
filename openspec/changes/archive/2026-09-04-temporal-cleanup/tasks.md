# Tasks: Temporal Cleanup (§12.4)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 580–700 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Single PR — 3 concerns cross domain+infra but all are tightly coupled |
| Delivery strategy | ask-on-risk |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: stacked-to-main
400-line budget risk: Medium

> Line estimate: ~280 lines domain (cleanup.py), ~80 lines infra (temporal_cleanup.py), ~120 lines domain tests, ~120 lines infra tests, ~10 lines wiring mods. Crosses domain+infra+tests but the sub-stages are deeply interdependent — splitting a PR would mean deploying half a cleanup pipeline that does nothing. Single PR is the right review unit despite the budget. Delivery strategy `ask-on-risk` means the orchestrator will ask the user whether to accept a size:exception. **Maintainer accepted size:exception — single PR.**

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Domain cleanup algorithms + tests | PR 1 | `pytest tests/domain/test_cleanup.py -v` | N/A — pure deterministic math, no runtime/service boundary | Delete `cleanup.py` + `test_cleanup.py`; domain layer fully reversible |
| 2 | INode wrapper + tests | PR 1 | `pytest tests/infrastructure/test_temporal_cleanup.py -v` | N/A — async node wrapper, no live services | Delete `temporal_cleanup.py` + `test_temporal_cleanup.py` |
| 3 | Registry wiring + re-exports | PR 1 | `pytest tests/ -k "seed" -v` | N/A — registry import, no service boundary | Remove imports from 3 `__init__`/registry files |

## Phase 1: Domain Cleanup Math + RED Tests (TDD)

### 1.1 RED — Write `tests/domain/test_cleanup.py` for One-Euro jitter

- [x] 1.1.1 Create `tests/domain/test_cleanup.py` with test `test_one_euro_reduces_jitter`: build NeutralMotion with synthetic high-variance joint trajectories, run `cleanup_motion()`, assert output translation variance < input variance.
- [x] 1.1.2 Add `test_one_euro_determinism`: run `cleanup_motion()` twice on same input, assert byte-identical output (same order of floats).
- [x] 1.1.3 Add `test_one_euro_passthrough`: build NeutralMotion with already-smooth trajectories, assert output materially unchanged (no added artifacts).

### 1.2 GREEN — Implement One-Euro jitter filter in `domain/animation/cleanup.py`

- [x] 1.2.1 Create `aimation_actor_core/domain/animation/cleanup.py` with `CleanupParams` frozen dataclass (defaults: min_cutoff=1.0, beta=0.5, velocity_threshold=5.0, height_threshold=10.0, hysteresis_frames=4) and `DEFAULT_*` constants.
- [x] 1.2.2 Implement `cleanup_motion(motion: NeutralMotion, params: CleanupParams | None = None) -> NeutralMotion` stub returning a copy.
- [x] 1.2.3 Implement One-Euro filter per joint: stateless per-frame pass using frame-to-frame delta time; smooth translation channels (X/Y/Z) of each joint in skeleton. Run: `pytest tests/domain/test_cleanup.py -v`.

### 1.3 RED — Write tests for foot-contact detection with hysteresis

- [x] 1.3.1 Add `test_contact_detection_marks_frames`: build NeutralMotion where LFoot velocity < threshold and height < threshold for a window of frames; assert `contacts["left_foot"]` is populated with contact indices.
- [x] 1.3.2 Add `test_hysteresis_prevents_flicker`: build NeutralMotion with foot velocity oscillating at boundary; assert contact state does not flip on every frame — persists at least `hysteresis_frames` once entered.

### 1.4 GREEN — Implement foot-contact detection + hysteresis

- [x] 1.4.1 Implement contact detection: per-frame velocity (frame-to-frame Euclidean distance of translation) and height check against `height_threshold`; write contact samples to `NeutralMotion.contacts["left_foot"]` / `["right_foot"]`. Run: `pytest tests/domain/test_cleanup.py -v`.

### 1.5 RED — Write tests for foot locking + ground clamp + root normalization

- [x] 1.5.1 Add `test_foot_lock_xz_clamp`: build NeutralMotion with detected contact; assert locked frames have XZ == contact-frame XZ and rotation quaternion unchanged.
- [x] 1.5.2 Add `test_non_contact_foot_free`: assert non-contact foot XZ is not clamped.
- [x] 1.5.3 Add `test_ground_clamp_y_gte_zero`: inject frame with foot Y < 0; assert output Y >= 0 and hips raised by penetration delta.
- [x] 1.5.4 Add `test_root_normalization_removes_drift`: build NeutralMotion with known cumulative root drift; assert root drift == 0 in output and child joint relative offsets preserved.

### 1.6 GREEN — Implement foot locking, ground clamp, root normalization

- [x] 1.6.1 Implement translation-only foot locking (XZ clamp at contact frames, rotation untouched).
- [x] 1.6.2 Implement ground clamp (foot Y >= 0, raise hips translation Y by penetration delta).
- [x] 1.6.3 Implement root drift normalization (subtract cumulative drift from root translation, preserve relative child offsets). Run: `pytest tests/domain/test_cleanup.py -v`.

### 1.7 RED — Write test for processing order + determinism

- [x] 1.7.1 Add `test_processing_order`: assert the five sub-stages ran sequentially (each consumed previous stage output). Add `test_full_cleanup_determinism`: identical inputs produce byte-identical outputs end-to-end.

### 1.8 GREEN — Finalize `cleanup_motion()` pipeline ordering

- [x] 1.8.1 Wire sub-stages in fixed order inside `cleanup_motion()`: one-euro → contact detect → foot lock → ground clamp → root normalize. Run: `pytest tests/domain/test_cleanup.py -v` — all green.

## Phase 2: INode Wrapper + Tests (TDD)

### 2.1 RED — Write `tests/infrastructure/test_temporal_cleanup.py`

- [x] 2.1.1 Create `tests/infrastructure/test_temporal_cleanup.py` mirroring `test_video_to_motion` pattern: test `test_schema_type_and_category` — assert `TemporalCleanupNode.get_schema()` returns type="temporal-cleanup", category=NodeCategory.CLEANUP, input NEUTRAL_ANIMATION, output NEUTRAL_ANIMATION.
- [x] 2.1.2 Add `test_execute_returns_neutral_motion`: mock dict inputs, assert execute returns NodeOutput with NeutralMotion payload.
- [x] 2.1.3 Add `test_execute_uses_to_thread`: assert `asyncio.to_thread` is called with `cleanup_motion`.
- [x] 2.1.4 Add `test_validate_rejects_negative_thresholds`: assert validate returns error for negative velocity_threshold, height_threshold, min_cutoff, beta, or zero/negative hysteresis_frames.

### 2.2 GREEN — Implement `infrastructure/ai_models/temporal_cleanup.py`

- [x] 2.2.1 Create `aimation_actor_core/infrastructure/ai_models/temporal_cleanup.py` with `TemporalCleanupNode(INode)`: `get_schema()` returns CLEANUP schema, `execute()` does dict coercion + `asyncio.to_thread(cleanup_motion, ...)`, `validate()` checks param ranges. Run: `pytest tests/infrastructure/test_temporal_cleanup.py -v`.

## Phase 3: Registry Wiring + Re-exports

### 3.1 Register TemporalCleanupNode as 8th seed

- [x] 3.1.1 Modify `aimation_actor_core/infrastructure/virtual/node_registry.py`: import `TemporalCleanupNode` and add it to the seed list after `video-to-motion`.
- [x] 3.1.2 Verify 8 seed nodes present: `pytest tests/ -k "seed or registry" -v`.

### 3.2 Re-export from `__init__.py` files

- [x] 3.2.1 Modify `aimation_actor_core/infrastructure/ai_models/__init__.py`: add `TemporalCleanupNode` to re-exports.
- [x] 3.2.2 Modify `aimation_actor_core/domain/animation/__init__.py`: re-export `CleanupParams`, `cleanup_motion`, and default constants from `domain.animation.cleanup`.

## Phase 4: Integration Verify

### 4.1 Full test suite verification

- [x] 4.1.1 Run `pytest tests/ -v` with `--basetemp C:\Users\josea\AppData\Local\Temp\opencode\pytest-basetemp` — all new + existing 248 tests pass.
- [x] 4.1.2 Verify no numpy import in `domain/` layer: grep `import numpy` / `from numpy` in `aimation_actor_core/domain/` returns zero matches.

### 4.2 Seed count and pipeline contract

- [x] 4.2.1 Assert `temporal-cleanup` is in `seeded_node_registry().list_schemas()` and its port types are `NEUTRAL_ANIMATION` in and out.
- [x] 4.2.2 Assert pipeline chain `video-source → pose-2d → pose-3d → video-to-motion → temporal-cleanup` is a valid connected graph (no port mismatch).
