# ADR-001: Canonical `Left…/Right…` neutral bone names with versioned NeutralMotion migration

**Status**: Accepted (change `retargeting`, §14)

**Date**: 2026-09-06

## Context

The neutral skeleton (`DEFAULT_NEUTRAL_SKELETON`, `domain/animation/skeleton_presets.py`) uses abbreviated `L…/R…` bone names (`LShoulder`, `LArm`, `LUpLeg`, …) while the product plan §14.2/§14.3 and the retarget presets key on canonical `Left…/Right…` names (`LeftShoulder`, `LeftArm`, `LeftUpLeg`, …). Industry convention (Mixamo, BVH, Unity Humanoid) is PascalCase `Left`/`Right` prefix — no major tool uses `L`/`R` prefix (research lane 1, 4 sources). The retarget-map presets cannot work against the abbreviated key space; the plan expects `mapping: LeftArm: l_arm_ctrl`.

`NeutralMotion` is the immutable, versioned bridge contract between Core, Tauri, and DCC plugins (SDD §5.3); its `meta.version` is "0.2" today. Any skeletal contract change requires a versioned migration strategy and an ADR (AGENTS.md §3.2 soft constraint).

## Decision

1. **Rename** the 16 L/R bones to canonical form across the whole codebase: `skeleton_presets.py` (skeleton + `LEGACY_BONE_RENAME_MAP`), `mapping.py` (COCO_TO_NEUTRAL values), `cleanup.py` (`_FOOT_BONES`), and the referencing tests. Topology, rest offsets, and parent structure are unchanged — names only. Unpaired bones (`Root`, `Hips`, `Spine`, `Chest`, `Neck`, `Head`) are untouched. The mapping is an explicit 16-entry table; a naive `L→Left`, `R→Right` prefix rewrite is forbidden because `Root` starts with `R`.
2. **Version the contract**: `NeutralMeta.version` default bumps `"0.2"` → `"0.3"`. Producers write `0.3` with canonical names.
3. **Read policy (backward-compatible)**: accept and migrate `0.2` documents on read via `migrate_neutral_motion()` (renames `skeleton.bones` keys, `Bone.name`, `parent` references, and `frame.pose.transforms` keys; bumps `meta.version`; validates invariants); accept `0.3` as-is; reject any other version with a clear `UnsupportedNeutralVersionError`. The migration lives at the coercion boundary (`_coerce_motion` in the NeutralMotion-consuming node adapters), keeping the `NeutralMotion` value object pure. Stored documents are never silently corrupted: a `0.2` skeleton stays internally consistent only until it is read through the migration, which is deterministic.

## Consequences

- Retarget presets key on the plan §14.2 canonical names and match external tools' naming (research-validated).
- Existing stored `0.2` documents remain loadable; they migrate to `0.3` at the read boundary. Rollback of this rename is a version-default revert plus name sweep (migration stays inert for `0.3` docs).
- Blast radius: `skeleton_presets.py`, `mapping.py`, `cleanup.py`, neutral-motion-consuming adapters, tests (`test_skeleton_presets.py`, `test_mapping.py`, `test_cleanup.py`, `test_motion_conversion.py`, `test_temporal_cleanup.py`, `test_inbetween_generation.py`), `openspec/specs/temporal-cleanup/spec.md` wording (referential), and any retarget presets.
- A `0.2`-versioned document that carries canonical names out-of-band is indistinguishable from a pre-rename doc; accept as intended — the version field is the authority.