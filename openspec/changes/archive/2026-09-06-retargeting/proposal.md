# Proposal: Retargeting (§14)

## Intent

Map a `NeutralMotion` to a target rig via a `RetargetMap` (user YAML/JSON preset) and a `retarget-map` node. The skeleton's `L`/`R` names (`LShoulder`) diverge from the plan's §14.2 canonical `Left…`/`Right…` names presets key on — reconcile first (ADR + versioned migration), then land deterministic retarget math + safe preset ingestion.

## Scope

### In Scope
- **Bone rename (Decision A)**: `L/R` → canonical `Left`/`Right` across `skeleton_presets.py`, `mapping.py`, `cleanup.py`, `motion_conversion`, frontend fixtures/tests. ADR + `NeutralMotion` migration (SDD §5.3).
- **Domain math**: new `domain/retargeting/` — `RetargetMap` model (`extra="forbid"`) + pure-stdlib position/scale remap and rotation/axis/offset machinery (height-ratio root scaling, ground reference, per-bone rotation offset). Rotation tested on synthetic rigs (Decision C).
- **Quat helpers**: promote `_quat_*` → shared `domain/animation/quat.py`.
- **Node + presets**: `retarget-map` adapter, `RIGGING`, `NEUTRAL_ANIMATION` in/out (no new DataType), 10th seed; YAML/JSON under `media/presets/`, `safe_load`/`json.load` (never eval).
- **Tests**: Strict TDD (math + node + negatives). **Catalog**: golden append.

### Out of Scope
- Rotational IK, joint limits, facial/blendshape retarget (§14.1).
- Style model (§13), generative enhancement.
- DCC shadow-rig plugins (Maya/Blender §15-16).

## Capabilities
- **New `retargeting`**: RetargetMap, remap math, preset format, `retarget-map` node.
- **Modified `node-registry`**: seed 9→10 (`retarget-map`, `RIGGING`).
- Rename/quat promotion = ADR/design concern (no spec-delta; `NeutralMotion` unspec'd).

## Approach
Rename (ADR + `meta.version` bump + migration), then pure-stdlib `domain/retargeting/` → thin adapter → 10th seed → safe loader → catalog golden, mirroring `model_copy(update=…)` + `validate_invariants()`.

## Affected Areas
`domain/retargeting/` (New), `domain/animation/quat.py` (New), `domain/animation/{skeleton_presets,mapping,cleanup,inbetween}.py` (Mod), `infrastructure/ai_models/retarget_map.py` (New), `infrastructure/virtual/node_registry.py` (Mod), `media/presets/` (New), `frontend/src/test/fixtures/nodeCatalog.json` (Mod), `docs/adr/<NN>-neutral-bone-names.md` (New).

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Bone-rename blast radius | Med | ADR + versioned migration; sweep |
| YAML injection/billion-laughs | Med | `safe_load` + size cap + allowlist + `extra="forbid"` |
| glTF/FBX forward-axis trap | Med | Axis-correction tests |
| Rotation has no upstream source | Low | Decision C: rig-tested, not runtime-fed |
| Pure-stdlib constraint | Low | `math` only in domain; linter guard |

## Rollback Plan
1. Revert rename + `meta.version` (backward-compat migration).
2. Unregister `retarget-map` (9 seeds); delete adapter + `domain/retargeting/`.
3. Restore `_quat_*` in `inbetween.py`; remove `quat.py`.
4. Restore `nodeCatalog.json`; remove presets.
5. `pytest` + `import-linter` green baseline.

## Dependencies
PyYAML (infra) `safe_load`; stdlib `json`; Pydantic v2. No new domain deps.

## Success Criteria
- [ ] Canonical `Left…/Right…` bones; migration + ADR recorded.
- [ ] `retarget-map` registered (10 seeds); `GET /nodes/types` returns it.
- [ ] Retarget math passes Strict-TDD tests (deterministic, invariants ok).
- [ ] Rotation/axis/offset exercised on synthetic rigs.
- [ ] Malformed/unknown/unmapped-bone presets rejected; no eval path.
- [ ] Catalog golden in sync (contract green).
- [ ] All tests green; quat helpers shared.
