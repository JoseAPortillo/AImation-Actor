# Apply Progress — Retargeting (§14)

**Change**: retargeting
**Mode**: Strict TDD
**Delivery**: single-pr, `size:exception` (maintainer-approved, ~850–1050 lines)
**Store**: hybrid (openspec file + engram observation, topic `sdd/retargeting/apply-progress`)

## Phase 1 — Foundation: ADR + Migration + Bone Rename (COMPLETE)

### TDD Cycle Evidence

| Task | RED (test first) | GREEN (impl passes) | REFACTOR |
|------|------------------|---------------------|----------|
| 1.1 ADR-001 status Accepted | n/a (read-only verify) | n/a | n/a |
| 1.2 skeleton test canonical + map | `pytest tests/domain/test_skeleton_presets.py` → 5 failed (map missing, legacy names) | `test_skeleton_presets.py` → 11 passed | ruff clean |
| 1.3 skeleton_presets.py rename + map | covered by 1.2 RED | `test_skeleton_presets.py` → 11 passed | ruff E501 fixed (2 lines wrapped) |
| 1.4 mapping test canonical | `pytest tests/domain/test_mapping.py` → 3 failed | `test_mapping.py` → 12 passed | ruff clean |
| 1.5 mapping.py COCO values | covered by 1.4 RED | `test_mapping.py` → 12 passed | ruff clean |
| 1.6 cleanup.py `_FOOT_BONES` | contract encoded via `test_cleanup.py` sweep (fixtures canonical): RED run → 20 failed | `test_cleanup.py` → 23 passed | ruff clean |
| 1.7 neutral_motion migration tests | new `test_neutral_motion.py` → collection ImportError (API absent) → RED confirmed | `test_neutral_motion.py` → 16 passed | 2 test bugs fixed (helper KeyError, Root-prefix assertion) |
| 1.8 `migrate_neutral_motion` + 0.3 default | covered by 1.7 RED | `test_neutral_motion.py` → 16 passed | migration `dict.get` bug fixed (parent → None default) |
| 1.9 adapters → `migrate_neutral_motion` | covered by existing adapter tests (behavior preserved) | `test_temporal_cleanup.py` + `test_inbetween_generation.py` → green | F401 unused `NeutralMotion` import removed |
| 1.10 test sweep | 3 listed files + `test_cleanup.py` swept: RED run → 32 failed total | full suite → 391 passed | ruff clean |

RED gate run (all files above, sources still legacy): **32 failed, 54 passed**.
GREEN gate: focused **149 passed**; full suite **391 passed, 2 skipped**.

### Work Unit Evidence

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `pytest tests/domain/test_skeleton_presets.py tests/domain/test_mapping.py tests/domain/test_neutral_motion.py tests/domain/test_cleanup.py tests/domain/test_inbetween.py tests/infrastructure/test_temporal_cleanup.py tests/infrastructure/test_inbetween_generation.py tests/infrastructure/test_motion_conversion.py` → **149 passed** |
| Runtime harness command/scenario and exact result | N/A — pure data rename + domain migration; no runtime/service boundary crossed in this unit |
| Rollback boundary | Revert rename + migration (skeleton_presets.py, mapping.py, cleanup.py, neutral_motion.py, adapters, swept tests); ADR-001 stays |

### Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `docs/adr/001-neutral-bone-names.md` | Verified (read-only) | ADR-001 status Accepted — 16-entry explicit rename, 0.2→0.3 migration, read policy |
| `aimation_actor_core/domain/animation/skeleton_presets.py` | Modified | 16 L/R bones renamed to canonical `Left…/Right…`; added `LEGACY_BONE_RENAME_MAP` (explicit 16 entries, no prefix rewrite) |
| `aimation_actor_core/domain/animation/mapping.py` | Modified | `COCO_TO_NEUTRAL` values canonical (LeftShoulder…RightFoot) |
| `aimation_actor_core/domain/animation/cleanup.py` | Modified | `_FOOT_BONES` → (`LeftFoot`, `RightFoot`); `_world_y_for` call sites |
| `aimation_actor_core/domain/animation/neutral_motion.py` | Modified | `meta.version` default `"0.3"`; added `UnsupportedNeutralVersionError`; added `migrate_neutral_motion(raw)` (0.2 rename+bump+validate, 0.3 passthrough, else reject; missing version on serialized docs rejected) |
| `aimation_actor_core/infrastructure/ai_models/temporal_cleanup.py` | Modified | `_coerce_motion` → `migrate_neutral_motion` (task 1.9) |
| `aimation_actor_core/infrastructure/ai_models/inbetween_generation.py` | Modified | `_coerce_motion` → `migrate_neutral_motion` (task 1.9) |
| `tests/domain/test_skeleton_presets.py` | Modified | Canonical expectations; `TestLegacyBoneRenameMap` (16 entries, bijective, Root guard) |
| `tests/domain/test_mapping.py` | Modified | Canonical values; canonical-bone + spec-scenario assertions |
| `tests/domain/test_neutral_motion.py` | Created | 16 tests: default 0.3; migrate keys/parents/Bone.name/transforms; passthrough; unknown/missing version rejected; Root never prefix-rewritten; deterministic |
| `tests/domain/test_cleanup.py` | Modified | Fixture skeletons + assertions to canonical names (ADR blast radius) |
| `tests/infrastructure/test_motion_conversion.py` | Modified | Canonical names in assertions/docstrings |
| `tests/infrastructure/test_temporal_cleanup.py` | Modified | `_motion` fixture foot keys canonical |
| `tests/infrastructure/test_inbetween_generation.py` | Modified | `_motion` fixture foot keys canonical |

### Deviations from Design

- **Task 1.10 scope +1 file**: swept `tests/domain/test_cleanup.py` beyond the three listed test files. Required: the `_FOOT_BONES` semantics change (1.6) makes `migrate_neutral_motion`/cleanup operate on canonical names; `test_cleanup.py`'s legacy fixture skeletons would have skipped ground-clamp/lock paths and broken 20+ tests. File is in the ADR-001 blast radius list. No design conflict — the tasks list was a subset.
- **Missing version rejected (stricter than literal task text)**: `migrate_neutral_motion` raises `UnsupportedNeutralVersionError("<missing>")` for a serialized dict with no `meta.version`, instead of letting Pydantic's `"0.3"` default silently accept it. Rationale: the ADR makes the version field the authority; a doc that omits it must not be treated as post-rename 0.3 (that would silently corrupt legacy skeletons). Consistent with "never silently corrupt" (ADR-001 Decision 3).
- **1.3 map placement**: `LEGACY_BONE_RENAME_MAP` lives in `skeleton_presets.py` (per ADR-001), imported by `neutral_motion.py` — no import cycle (skeleton_presets imports skeleton only).

### Issues Found

- **My `dict.get` bug (fixed before GREEN)**: `rename.get(bone.parent)` returned `None` for unmapped parents (`Root`, `Hips`) → migrated skeleton had 4 roots. Fixed with `rename.get(bone.parent, bone.parent)`; caught by `validate_invariants()` — the invariant gate worked as designed.
- **Test helper bugs (fixed)**: `_zero_three_canonical_doc` popped non-existent transform keys (`KeyError`); `test_no_legacy_bone_names_remain` naively asserted no name starts with `L`/`R` — `Root` starts with `R`. Replaced with a legacy-map-key membership check.
- `./test_inbetween.py` (repo root, untracked) is a WIP leftover script — NOT part of this change, not committed.

## Phase 2 — Quat Promotion + Retarget Domain (COMPLETE)

### TDD Cycle Evidence

| Task | RED (test first) | GREEN (impl passes) | REFACTOR |
|------|------------------|---------------------|----------|
| 2.1 quat tests | new `test_quat.py` → collection ImportError (module absent) → RED confirmed | `test_quat.py` → 16 passed | test data bug fixed (q_neg negation: `(cos60,0,0,-sin60)` was the *positive* 120° quat — negated via `quat_negate`) |
| 2.2 `quat.py` promote + `quat_multiply` | covered by 2.1 RED | `test_quat.py` → 16 passed; `test_inbetween.py` still 51 passed (privates intact) | ruff/mypy clean |
| 2.3 inbetween.py import-from-quat | existing `test_inbetween.py` RED → 3 failed (`_slerp` NameError) | `test_inbetween.py` → 51 passed (behavior preserved) | `_slerp` → `slerp` import in test file; docstring ref updated |
| 2.4 animation `__init__` re-exports | n/a (re-export only) | domain suite green | ruff clean |
| 2.5 RetargetMap model tests | new `test_retarget.py` → collection ImportError → RED confirmed | `test_retarget.py` → 13 passed | unused imports pruned (F401 ×9) + E501 wrapped |
| 2.6 `domain/retargeting/map.py` | covered by 2.5 RED | `test_retarget.py` → 13 passed | shorthand promotion via `model_validator(mode="before")` |
| 2.7 retarget math tests | new `test_retarget_math.py` → collection ImportError → RED confirmed | `test_retarget_math.py` → 19 passed | E501 + fixture tuning |
| 2.8 `domain/retargeting/retarget.py` | covered by 2.7 RED | `test_retarget_math.py` → 19 passed | unused constant pruned |
| 2.9 rotation rig tests | new `test_retarget_rotation.py` → collection ImportError → RED confirmed | `test_retarget_rotation.py` → 16 passed | 2 hand-arithmetic test references corrected (see Issues) |
| 2.10 `domain/retargeting/rotation.py` | covered by 2.9 RED | `test_retarget_rotation.py` → 16 passed | identity guard (+1,0,0,0) tuple-equality |
| 2.11 retargeting `__init__` re-exports | n/a (re-export only) | full domain suite → 240 passed | import-linter 4 contracts kept |

GREEN gate: full domain suite **240 passed**; full suite **455 passed, 2 skipped**; ruff + mypy + import-linter clean.

### Work Unit Evidence

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `pytest tests/domain/test_quat.py tests/domain/test_inbetween.py tests/domain/test_retarget.py tests/domain/test_retarget_math.py tests/domain/test_retarget_rotation.py tests/domain/test_skeleton_presets.py tests/domain/test_neutral_motion.py` → **204 passed** |
| Runtime harness command/scenario and exact result | N/A — pure domain math; no runtime/service boundary crossed in this unit |
| Rollback boundary | Revert `quat.py` + `domain/retargeting/` + the 4 test files; restore inbetween.py privates (or re-import from quat); animation `__init__` re-exports revert |

### Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `aimation_actor_core/domain/animation/quat.py` | Created | Promoted `quat_dot`/`quat_negate`/`quat_normalize`/`slerp` (verbatim, `_SLERP_EPS` private) + new Hamilton `quat_multiply` |
| `aimation_actor_core/domain/animation/inbetween.py` | Modified | Imports `quat_dot`/`quat_negate`/`slerp` from quat.py; private helpers deleted; docstring updated — no behavior change |
| `aimation_actor_core/domain/animation/__init__.py` | Modified | Re-exports quat API + `migrate_neutral_motion` + `UnsupportedNeutralVersionError` |
| `aimation_actor_core/domain/retargeting/map.py` | Created | Frozen `RetargetEntry`/`RetargetMap`, `extra="forbid"`, string→entry shorthand, `validate_against(source, target=None)` |
| `aimation_actor_core/domain/retargeting/retarget.py` | Created | `retarget_motion`: ①root×ratio ②rotation ③scale ④foot_ik ground pass; `validate_invariants()`; byte-deterministic |
| `aimation_actor_core/domain/retargeting/rotation.py` | Created | `apply_rotation` (identity-in→identity-out guard), `axis_correction_quat` (documented forward-axis pairs) |
| `aimation_actor_core/domain/retargeting/__init__.py` | Created | Re-exports RetargetEntry/RetargetMap/retarget_motion/apply_rotation/axis_correction_quat |
| `tests/domain/test_quat.py` | Created | 16 tests: normalize unit invariant + zero-quat; dot symmetry + reference; Hamilton multiply refs; slerp endpoints + short-arc + nlerp no-NaN |
| `tests/domain/test_retarget.py` | Created | 13 model tests: well-formed, defaults, shorthand promotion, extra field (top+per-bone), frozen, `validate_against` source/target, unknown bones |
| `tests/domain/test_retarget_math.py` | Created | 19 math tests: height-ratio ×2/×0.5/inert/root-opt-out; passthrough; determinism; child positions untouched; per-bone scale; identity guard; foot ground pass (5) |
| `tests/domain/test_retarget_rotation.py` | Created | 16 rig tests: LOCAL offset post-multiplied, FBX→glTF half-turn, yup↔zup, unknown pair, identity never fabricated, unit outputs |
| `tests/domain/test_inbetween.py` | Modified | `_slerp` import → public `slerp` from quat (4 call sites + comment) |

### Deviations from Design

- **Execution order 2.9/2.10 before 2.8 GREEN (implementation dependency)**: `retarget_motion`'s rotation pass (②) consumes `apply_rotation` from `rotation.py`; under Strict TDD the rotation tests (2.9) and implementation (2.10) had to land before `retarget.py` could be written. Task numbering in tasks.md is unchanged — this is an ordering note, not a scope change.
- **2.7 +4 foot ground-pass tests (beyond the listed assertions)**: task 2.7 names height-ratio/determinism/invariants/child-position/scale but the design's pass ④ (`foot_ik` ground pass on Hips Y) is part of `retarget_motion`'s contract. Strict TDD forbids implementing it without tests, so 5 focused ground-pass tests (disabled keeps penetration / lowest-foot lift / grounded no-op / contact-track override / missing-feet no-op) were added to the math batch.
- **`axis_correction_quat` same-convention → identity**: the design table lists only the four cross pairs; same-token pairs (`"fbx","fbx"`) return identity rather than raising — deterministic no-op for no-op conventions.

### Issues Found

- **My hand-arithmetic test references (fixed, implementation was correct)**: (1) `test_axis_correction_pre_multiplied` expected `(0, s, s, s)` but `Q_Y180=(0,0,1,0)` has z=0, so `(0,0,1,0)·(s,0,0,s) = (0, s, s, 0)`; (2) its compose companion expected `w==0` — the actual `(0,s,s,0)·(s,s,0,0) = (−½,½,½,−½)`; (3) `test_foot_ik_no_lift_when_grounded` used `hips_y=9`, but the right chain (−15) still penetrates → lowest-foot lift; the truly grounded case is `hips_y=15` (right foot at 0). All three were reference/expectation errors in the test data, caught by running GREEN — the invariant/unit-norm assertions held.
- **Unused imports in `test_retarget.py` (fixed by REFACTOR)**: I over-imported the motion model fixtures; ruff F401 flagged 9, pruned to only what the model tests use.
- **`test_inbetween.py` residual private references**: after the import switched to `slerp`, 4 call sites + 1 comment still said `_slerp` (NameError → the RED for 2.3) — replaced all.

### Remaining Tasks
- [ ] Phase 3 (3.1–3.9): adapter + presets + registry + catalog
- [ ] Phase 4 (4.1–4.5): integration verify + docs

### Workload / PR Boundary
- Mode: single-pr, `size:exception`
- Units landed: Unit 1 (Phase 1) + Unit 2 (Phase 2 — quat promotion + retarget domain)
- Boundary: base `feat/Develop @ 0d28204` + dependency merge `025c495`; Phase 2 ends with full suite **455 passed, 2 skipped**; ruff + mypy + import-linter clean
- Estimated review budget impact: P1 ~190 + P2 ~160 authored lines (forecast matches)

### Status
21/35 tasks complete. Ready for Phase 3 (adapter + presets + registry + catalog).