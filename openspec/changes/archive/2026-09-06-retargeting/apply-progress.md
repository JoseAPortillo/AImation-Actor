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
- [x] Phase 3 (3.1–3.9): adapter + presets + registry + catalog
- [x] Phase 4 (4.1–4.5): integration verify + docs

### Workload / PR Boundary
- Mode: single-pr, `size:exception`
- Units landed: Unit 1 (Phase 1) + Unit 2 (Phase 2 — quat promotion + retarget domain) + Unit 3 (Phase 3, 3.1–3.9) + Unit 4 (Phase 3.6 extension + Phase 4, 4.1–4.4 + test_api seed bump)
- Boundary: base `feat/Develop @ 0d28204` + dependency merge `025c495`; Phase 4 ends with full suite **494 passed, 2 skipped**; ruff (committed scope) + mypy (60 files) + import-linter (4/4 contracts) clean; frontend **123 passed** + `tsc -b` exit 0
- Estimated review budget impact: P1 ~190 + P2 ~160 + P3 ~500 + P4 ~40 authored lines (forecast matches `size:exception`; review budget 400-line exception pre-approved, single-pr retained)

### Status
**35/35 tasks complete.** Ready for sdd-verify.

---

## Phase 3 — Adapter + Presets + Registry + Catalog (COMPLETE)

### TDD Cycle Evidence

| Task | RED (test first) | GREEN (impl passes) | REFACTOR |
|------|------------------|---------------------|----------|
| 3.1 test_retarget_map.py | new `test_retarget_map.py` → collection ImportError (ModuleNotFoundError: retarget_map) → RED confirmed | — (RED lands with 3.2) | — |
| 3.2 `retarget_map.py` | covered by 3.1 RED | `test_retarget_map.py` → 14 passed (+1 expect-fail: shipped-identity test = 3.5's RED) | ruff: import order + E501 wraps |
| 3.3 test_preset_security.py | approval-style negative suite (controls shipped by 3.2 per design; spec-mandated verification) | `test_preset_security.py` → 20 passed on first complete run | 2 test-data fixes (padding arithmetic in at-cap test, unused `type: ignore`) |
| 3.4 re-export in `__init__.py` | n/a (re-export only) | `test_retarget_map.py` → 15 passed (with 3.5 file in place) | ruff clean |
| 3.5 `media/presets/identity.yaml` | `test_execute_shipped_identity_preset_is_passthrough` RED (PresetError: file absent) — carried as the 3.5 RED | identity test GREEN; suite → 15 passed | — |
| 3.6 registry RED | new `test_retarget_registry.py` + 9→10 bumps (test_executor, test_temporal_cleanup_registry, test_inbetween_generation_registry) + `test_api.py::test_list_node_types_lists_seed_nodes` → **7 failed** (retarget-map missing) | — | see deviation below |
| 3.7 register 10th seed | covered by 3.6 RED | focused 7/7 passed; registry suite green | docstring nine→ten seeds |
| 3.8 nodeCatalog golden | n/a (fixture append mirrors backend schema) | `npm test` → 123 passed; `tsc -b` exit 0 | — |
| 3.9 spec wording | n/a (read-only one-word edit) | n/a | — |

GREEN gate: focused **35 passed** (test_retarget_map + test_preset_security); full suite **494 passed, 2 skipped**.

### Work Unit Evidence

| Evidence | Required value |
|---|---|
| Focused test command and exact result | `pytest tests/infrastructure/test_retarget_map.py tests/infrastructure/test_preset_security.py` → **35 passed**; RED gate (3.6): `test_retarget_registry.py` + 9→10 bumps → **7 failed** |
| Runtime harness command/scenario and exact result | N/A — `RetargetMapNode` execute is covered by direct async tests (`to_thread` mocked). Preset loader exercised via allowlisted `media/presets/identity.yaml` at runtime (shipped-identity passthrough test reads the real file). |
| Rollback boundary | Revert `retarget_map.py`, `test_retarget_map.py`, `test_preset_security.py`, `__init__.py` re-export, `media/presets/` (new dir), `node_registry.py` registration, registry test bumps, nodeCatalog append, spec wording edit; keep ADR-001 |

### Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `aimation_actor_core/infrastructure/ai_models/retarget_map.py` | Created | `RetargetMapNode(INode)`: schema RIGGING, `motion: NEUTRAL_ANIMATION` in/out, 5 params (mapping_preset string required + 4 bools required=False default=None); `_resolve_preset_path` (allowlist: non-str/empty, absolute, extension `.yaml/.yml/.json`, `resolve()`+`is_relative_to` symlink-safe, nonexistent, non-file → `PresetError(code="preset_error")`); `_read_preset` (MAX_PRESET_BYTES=262_144 stat cap BEFORE parse → `json.loads`/`yaml.safe_load`, dict required); `_build_retarget_map` (`RetargetMap.model_validate` + `validate_against(DEFAULT_NEUTRAL_SKELETON)` + `model_copy(update=overrides)` — precedence node > preset > model default); `execute` (`migrate_neutral_motion` → `asyncio.to_thread(self._retarget_blocking)` → NodeOutput); `validate` (PresetError/yaml.ValidationError/ValueError/OSError → invalid, bool coercion checks, preset probed in-thread) |
| `aimation_actor_core/infrastructure/ai_models/__init__.py` | Modified | Re-export `RetargetMapNode` (task 3.4) |
| `media/presets/identity.yaml` | Created | 22-bone self-map preset + `media/presets/` dir (first preset root content) |
| `aimation_actor_core/infrastructure/virtual/node_registry.py` | Modified | `RetargetMapNode()` registered 10th; docstring ten seeds (task 3.7) |
| `tests/infrastructure/test_retarget_map.py` | Created | IDENTITY_PRESET/SCALE_PRESET fixtures; `_motion()` (Root/Hips/LeftUpLeg/LeftFoot/RightFoot, 2 frames); schema/execute/validate classes incl. shipped-identity passthrough vs real file |
| `tests/infrastructure/test_preset_security.py` | Created | 20 negatives: traversal (dotdot/deep/backslash/absolute/symlink-escape w/ skip-guard + inside-symlink positive, non-str), size cap (oversized malformed → PresetError proves pre-parse; byte-exact at-cap allowed), malformed YAML/JSON/empty/list/unknown-field/unknown-bone, static no-eval scan + safe-loader positive control |
| `tests/infrastructure/test_executor.py` | Modified | `test_seeded_registry_lists_nine_seed_nodes` → ten + retarget-map (9→10) |
| `tests/infrastructure/test_temporal_cleanup_registry.py` | Modified | `test_registry_has_nine_seeds` → ten + retarget-map |
| `tests/infrastructure/test_inbetween_generation_registry.py` | Modified | `test_registry_has_nine_seeds` → ten + retarget-map |
| `tests/infrastructure/test_retarget_registry.py` | Created | 10 seeds, RIGGING category, NEUTRAL ports, 7-node chain through retarget-map validates as connected DAG |
| `tests/api/test_api.py` | Modified | `/nodes/types` seed set 9→10 (4th seed assertion beyond tasks.md 3.6's three named files — see deviation) |
| `frontend/src/test/fixtures/nodeCatalog.json` | Modified | Appended `retarget-map` golden (10th entry): rigging, motion ports, mapping_preset + 4 bools (null defaults; descriptions mirror backend schema) |
| `openspec/specs/temporal-cleanup/spec.md` | Modified | `LFoot/RFoot` → `LeftFoot/RightFoot` (ADR-001 wording) |
| `pyproject.toml` | Modified | `[project.dependencies]` + `pyyaml>=6.0` (with §4.2 sign-off comment); `dev` + `types-PyYAML>=6.0` |

### Deviations from Design

- **Dependency inversion 3.1/3.2 + file-after-tests 3.5**: `_coerce_motion` concerns were designed in §4.1 but folded into `execute` via `migrate_neutral_motion` in 3.2 (no separate `_coerce_motion` symbol; the adapter contract is the coercion). The shipped-identity test (3.1 file) stays RED until 3.5 creates `media/presets/identity.yaml` — carried deliberately as 3.5's RED rather than committed red.
- **3.3 approval-style RED (n/a)**: task 3.2's own text ships the security controls (allowlist, cap, safe_load) — the design bundles loader security INTO 3.2. The 3.3 security suite is the spec-mandated negative verification of those controls; it passed on first complete run (2 test-data fixes only, no production change). Recorded honestly: no RED possible for controls already mandated by 3.2's task text.
- **3.6 scope +2 files**: tasks.md names only `test_executor.py` + `test_temporal_cleanup_registry.py`; full-suite run surfaced TWO more 9-seed assertions — `test_inbetween_generation_registry.py::test_registry_has_nine_seeds` and (API contract level) `tests/api/test_api.py::test_list_node_types_lists_seed_nodes`. All four bumped; the API one failed the 4.1 verify run and was fixed post-GREEN (see Issues).
- **4.5 pyproject moved earlier**: `pyyaml>=6.0` + `types-PyYAML>=6.0` landed with the 3.1–3.5 commit (the loader imports yaml; mypy strict requires stubs — the slice could not be lint-green without the entry). 4.5's remaining verification = installed env matches (pyyaml 6.0.3, types-PyYAML 6.0.12 in venv → confirmed).
- **4.4 severity matched task text (High)**: initial draft used Medium; task 4.4 explicitly prescribes High — table row set to High, consistent with the existing Video/Input malicious-file row.

### Issues Found

- **Padding arithmetic bug in the at-cap security test (test-data fix)**: the append-loop overshot the cap (262141 ≠ 262144). Replaced with byte-exact `raw + b"#" + b" "*(cap-len(raw)-1)`; test now asserts st_size == MAX_PRESET_BYTES precisely.
- **`idempotent` ruff/mypy cleanup**: `test_preset_security.py` had an unused `type: ignore[list-item]` (heterogeneous tuple infers object) — removed; import order fixed by ruff.
- **`test_api.py` missed by the "nine" grep**: the API seed test's name is `test_list_node_types_lists_seed_nodes` (no "nine"/"9") so the phase-2 sweep did not flag it; only the FULL 4.1 suite run caught it. Lesson: seed-count greps must search the set contents, not just test names.
- **Untracked leftover `test_inbetween.py`** (repo root, WIP scratch, pre-existing) is NOT part of this change; it is the ONLY source of the 20 ruff repo-wide findings (committed scope ruff is clean). Left untouched, never committed.