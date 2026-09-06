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

### Remaining Tasks
- [ ] Phase 2 (2.1–2.11): quat promotion + retarget domain
- [ ] Phase 3 (3.1–3.9): adapter + presets + registry + catalog
- [ ] Phase 4 (4.1–4.5): integration verify + docs

### Workload / PR Boundary
- Mode: single-pr, `size:exception`
- Current work unit: Unit 1 — ADR + migration + rename sweep
- Boundary: starts at base `feat/Develop @ 0d28204` + dependency merge `025c495`; ends with Phase 1 fully green (391 passed, 2 skipped; ruff + mypy + import-linter clean)
- Estimated review budget impact: P1 forecast ~190 authored lines (matches; sweep tests included)

### Status
10/35 tasks complete. Ready for Phase 2.