# Tasks: Retargeting (§14)

REQ tags: RENAME/MIGRATE/QUAT/MAP/MATH/ROTATE/PRESET/LOAD/SCHEMA/SEED/CATALOG/SECURITY = retargeting spec + node-registry spec.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~850–1050 authored (P1 ~190, P2 ~160, P3 ~130, P4 ~80, P5 ~290 incl. ~250 tests) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | size:exception single PR (delivery_strategy = single-pr) |
| Delivery strategy | single-pr |
| Chain strategy | size-exception |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: size-exception
400-line budget risk: High

**Maintainer decision:** approve `size:exception` (~850–1050 lines) before apply — rename blast radius + domain math + security tests cannot split below 400 without breaking migration-contract atomicity.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | ADR + migration + rename sweep | core PR | `pytest tests/ -k "skeleton_presets or mapping or cleanup or migration"` | N/A — pure data rename | Revert rename+migration; ADR stays |
| 2 | Quat promotion + retarget domain | core PR | `pytest tests/domain/test_quat.py tests/domain/test_retarget.py` | N/A — pure math | Revert quat.py + domain/retargeting |
| 3 | Adapter + presets + registry + golden | core PR | `pytest tests/ -k "retarget_map or registry or seed"` | N/A — async wrapper | Revert adapter+registry+catalog |
| 4 | Security tests + threat row | core PR | `pytest tests/ -k "preset_security or path_traversal"` | N/A — negative tests | Revert security tests only |

## Phase 1: Foundation — ADR + Migration + Bone Rename

- [x] 1.1 `docs/adr/001-neutral-bone-names.md` (read-only) — verify ADR-001 status Accepted (RENAME)
- [x] 1.2 RED `tests/domain/test_skeleton_presets.py`: canonical `LeftShoulder`/`RightArm`/`LeftUpLeg`/`RightFoot`/`RightToeBase`; 16-entry `LEGACY_BONE_RENAME_MAP`; topology unchanged (RENAME)
- [x] 1.3 GREEN `aimation_actor_core/domain/animation/skeleton_presets.py`: rename 16 L/R bones; add map — explicit entries, NO prefix-replace (`Root` starts with R!) (RENAME)
- [x] 1.4 RED `tests/domain/test_mapping.py`: `left_shoulder→LeftShoulder`, `right_hip→RightUpLeg` (RENAME)
- [x] 1.5 GREEN `aimation_actor_core/domain/animation/mapping.py`: COCO values canonical (RENAME)
- [x] 1.6 GREEN `aimation_actor_core/domain/animation/cleanup.py`: `_FOOT_BONES` → {`LeftFoot`,`RightFoot`} (RENAME)
- [x] 1.7 RED `tests/domain/test_neutral_motion.py`: default `"0.3"`; `migrate_neutral_motion` renames keys/parents/`Bone.name`/transforms from 0.2; 0.3 passthrough; unknown version rejected; legacy `Root` NOT corrupted (MIGRATE)
- [x] 1.8 GREEN `neutral_motion.py`: `migrate_neutral_motion(raw) -> NeutralMotion` (0.2 rename+bump+validate; 0.3 passthrough; else `UnsupportedNeutralVersionError`); default `meta.version="0.3"` (MIGRATE)
- [x] 1.9 `_coerce_motion` → `migrate_neutral_motion` in `infrastructure/ai_models/{temporal_cleanup,inbetween_generation}.py` (MIGRATE)
- [x] 1.10 Sweep `tests/`: canonical names in `test_motion_conversion.py`, `test_temporal_cleanup.py`, `test_inbetween_generation.py` (RENAME)

## Phase 2: Quat Promotion + Retarget Domain

- [x] 2.1 RED `tests/domain/test_quat.py`: norm unit invariant; multiply identity; dot symmetry; slerp endpoints; nlerp near-parallel no-NaN (QUAT)
- [x] 2.2 GREEN `aimation_actor_core/domain/animation/quat.py`: promote `_quat_dot/_negate/_normalize/_slerp` + `quat_multiply` (Hamilton), stdlib-only (QUAT)
- [x] 2.3 GREEN `aimation_actor_core/domain/animation/inbetween.py`: import from quat.py, delete privates; existing `test_inbetween.py` green, no behavior change (QUAT)
- [x] 2.4 Re-export quat + `migrate_neutral_motion` in `domain/animation/__init__.py`
- [x] 2.5 RED `tests/domain/test_retarget.py`: well-formed validates; extra field (top+per-bone) rejected; unknown bone rejected; string→entry shorthand promotion (MAP)
- [x] 2.6 GREEN `domain/retargeting/map.py`: frozen `RetargetEntry`/`RetargetMap` (`extra="forbid"`, 4 bools, `target_root_to_ground_cm`); `validate_against(source, target=None)` (MAP)
- [x] 2.7 RED (math): height-ratio doubling; disabled passthrough; run-twice byte-identical; invariants; child positions untouched; per-bone scale (MATH)
- [x] 2.8 GREEN `domain/retargeting/retarget.py`: `retarget_motion` — ①root×ratio ②rotation ③scale ④foot_ik ground pass; `model_copy` + `validate_invariants` (MATH)
- [x] 2.9 RED (rotation rigs): LOCAL offset on non-identity source; FBX→glTF no backwards flip; identity NOT fabricated (ROTATE)
- [x] 2.10 GREEN `domain/retargeting/rotation.py`: `apply_rotation`, `axis_correction_quat` (forward-axis pairs); identity-in→identity-out guard (ROTATE)
- [x] 2.11 `domain/retargeting/__init__.py`: re-export map/model/math (MAP)

## Phase 3: Adapter + Presets + Registry + Catalog

- [ ] 3.1 RED `tests/infrastructure/test_retarget_map.py`: schema RIGGING + `motion: NEUTRAL_ANIMATION` in/out; validate rejects nonexistent preset; e2e execute → invariants ok; deterministic (SCHEMA)
- [ ] 3.2 GREEN `infrastructure/ai_models/retarget_map.py`: `RetargetMapNode(INode)` — allowlisted path resolve (reject absolute/`..`/symlink-escape), size cap 262_144 → `yaml.safe_load`/`json.load`, `_coerce_motion`, `asyncio.to_thread` (LOAD)
- [ ] 3.3 RED `tests/infrastructure/test_preset_security.py`: `../secret.yaml`/absolute/symlink escape/oversized (>262 KiB)/malformed rejected; static scan: no `eval`/`exec`/`yaml.load|full_load|unsafe_load` reachable (SECURITY)
- [ ] 3.4 Re-export `RetargetMapNode` in `infrastructure/ai_models/__init__.py`
- [ ] 3.5 `media/presets/identity.yaml`: identity preset — every bone→itself, identity offset, no axis_correction, scale (1,1,1), `use_root_translation: true` (PRESET)
- [ ] 3.6 RED `tests/infrastructure/test_retarget_registry.py`: 10 seeds, RIGGING, NEUTRAL ports; seed counts 9→10 in `test_executor.py` + `test_temporal_cleanup_registry.py` (SEED)
- [ ] 3.7 GREEN `infrastructure/virtual/node_registry.py`: register `RetargetMapNode()` 10th; docstring 9→10 (SEED)
- [ ] 3.8 `frontend/src/test/fixtures/nodeCatalog.json`: append `retarget-map` golden — RIGGING, motion ports, 5 params (CATALOG)
- [ ] 3.9 `openspec/specs/temporal-cleanup/spec.md` (read-only): `LFoot/RFoot` → `LeftFoot/RightFoot` wording

## Phase 4: Integration Verify + Docs

- [ ] 4.1 `.\\.venv\\Scripts\\python.exe -m pytest` full suite green
- [ ] 4.2 Grep `import numpy|from numpy` in `aimation_actor_core/domain/` → zero matches
- [ ] 4.3 `npm test` in `frontend/` green — fixture no drift
- [ ] 4.4 `docs/SDD.md` §4.2 row: `Retarget presets (retarget-map, RIGGING)` — High — safe_load + extra="forbid" + size cap + allowlist + no eval — no-eval scan + negative tests (SECURITY)
- [ ] 4.5 `pyproject.toml`: add `pyyaml>=6.0` to `[project.dependencies]`; §3.2 soft-constraint flag for maintainer

Deferred (NOT tasks): rotational IK/FK, joint limits, facial/blendshape retarget, DCC shadow-rig plugins, target skeleton graph input, style-model interaction.