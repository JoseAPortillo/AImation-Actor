# Exploration: Retargeting (§14)

> Planning-stage change trail for change `retargeting` (plan §14). Not a
> committed spec. Produced by the `sdd-explore` phase.

## Status

Ready for proposal — scoped to a deterministic `retarget-map` node
(`NEUTRAL_ANIMATION → NEUTRAL_ANIMATION`) backed by a pure-stdlib retargeting
domain, with safe YAML/JSON preset parsing. Several decisions (below) need
orchestrator/user confirmation before spec.

## Executive Summary

The neutral skeleton pipeline (§12) already outputs a `NeutralMotion` whose
`Skeleton` matches the §14.2 topology (22 bones, T-pose, up-Y, local rest
offsets). But the motion carries **identity rotation only** (rotation/IK were
deferred — `_build_frame` D5) and the bone **names are abbreviated**
(`LShoulder`/`LArm`/…), not the §14.2 canonical `LeftShoulder`/`LeftArm`/… names
the plan's own presets reference. `domain/retargeting/` exists but is an empty
placeholder; there is no retarget math, no preset type, and no `retarget-map`
node. The node infra, registry, catalog sync, and pure-stdlib-domain-math
precedents (temporal-cleanup, inbetween-generation) are all well-established and
reusable as-is. The genuinely new surface is (a) a bone-name convention
reconciliation, (b) safe YAML/JSON preset ingestion, and (c) rotation/axis/
offset math in `domain/retargeting/` — none of which require changing
`NeutralMotion` or the `INode` contract.

## Findings

### 1. Current state of the neutral pipeline

- `NeutralMotion` (`domain/animation/neutral_motion.py`) is the immutable,
  versioned contract (SDD §5.3): `meta`, `skeleton`, `frames`, `contacts`,
  `keyposes`, `tracking`. It already carries a `Skeleton` hierarchy, so the
  retarget *source* skeleton is embedded in every document.
- `Skeleton` (`domain/animation/skeleton.py`) + `Bone` (name, parent,
  rest_position, rest_rotation, quaternion `(w,x,y,z)`). `hierarchy.validate()`
  enforces a single rooted tree. `DEFAULT_NEUTRAL_SKELETON`
  (`skeleton_presets.py`) defines the 22-bone §14.2 topology in T-pose, up-Y,
  with **local** rest offsets in cm.
- Motion output: `convert_keypoints_to_motion` → `video-to-motion` node
  (`POSE_3D → NEUTRAL_ANIMATION`). It computes **translation-only** transforms;
  every `Transform3D.rotation` is the identity quaternion `(1,0,0,0)` —
  "rotational IK is deferred" (`_build_frame` comment, D5). So retargeting
  today can meaningfully remap **translation**; rotation remapping has no
  upstream rotation to consume yet (see Risks #4).
- `cleanup_motion` (temporal-cleanup) and `enrich_motion` (inbetween-generation)
  are the established pure-stdlib domain-math precedents producing a new
  `NeutralMotion` by `model_copy(update=...)` + `validate_invariants()`.

### 2. Neutral skeleton: bone-name gap vs §14.2

| Plan §14.2 canonical | Implementation (`DEFAULT_NEUTRAL_SKELETON`) |
|---|---|
| `LeftShoulder` / `RightShoulder` | `LShoulder` / `RShoulder` |
| `LeftArm` / `RightArm` | `LArm` / `RArm` |
| `LeftForeArm` / `RightForeArm` | `LForeArm` / `RForeArm` |
| `LeftHand` / `RightHand` | `LHand` / `RHand` |
| `LeftUpLeg` / `RightUpLeg` | `LUpLeg` / `RUpLeg` |
| `LeftLeg` / `RightLeg` | `LLeg` / `RLeg` |
| `LeftFoot` / `RightFoot` | `LFoot` / `RFoot` |
| `LeftToeBase` / `RightToeBase` | `LToeBase` / `RToeBase` |

- The **topology is identical** (Root/Hips/Spine/Chest/Neck/Head + shoulders off
  Chest + forearms + hands + upLeg/leg/foot/toeBase legs). Only the
  L/R-prefixed **names** differ from the plan's `Left…`/`Right…` canonical
  spelling.
- The plan's own §14.3 preset example (`mapping: LeftArm: l_arm_ctrl,
  LeftUpLeg: l_thigh_ctrl, …`) references **canonical** names — i.e. the plan
  expects retarget presets to key on `LeftArm` etc., which do not match the
  current `LArm` keys. This is the single most consequential ambiguity; it must
  be resolved **before** spec (see Decision A).
- `meta.up_axis` defaults to `"Y"` and `meta.units` to `"cm"`; no axis/units
  conversion is needed for the neutral skeleton itself, but §14.4 asks for
  per-bone "axis correction" and "rotation offset" on the **target** side — the
  target rig's axes/proportions differ, which is the retarget node's job.

### 3. `retarget-map` node shape

Node infra is mature and reusable unchanged:
- `domain/pipeline/node.py` — `INode` protocol: `get_schema()`, async
  `execute(inputs, params, context) → NodeOutput`, async `validate(params) →
  ValidationResult`. `NodeCategory.RIGGING = "rigging"` **already exists** in
  `schema.py` — no new category needed (contrast: inbetween-generation had to
  add `ENRICHMENT`). No `INode`/`NodeSchema`/`PortSpec` change required.
- Adapter pattern (`infrastructure/ai_models/{temporal_cleanup,inbetween_generation,video_to_motion}.py`):
  stateless node owns **no math**; it coerces the job-store serialized dict path
  (`NeutralMotion.model_validate`), validates params, and offloads blocking
  math via `asyncio.to_thread`. Retarget is in-memory stdlib math (like
  inbetween) so no model probe/`/health` key.
- Registration: `infrastructure/virtual/node_registry.py`
  `seeded_node_registry()` (currently 9 seeds) → register a 10th `retarget-map`.
  **New node type will be ADDITIVE; map_provider is nil for now.**
- Catalog sync (frontend): `src/api/types.ts` (mirror of `DataType`/
  `NodeCategory`), `src/core/handles.ts` (color maps), `src/test/fixtures/
  nodeCatalog.json` (golden, drift-detected by a contract test), `Palette.tsx`
  (schema-driven, reads `GET /nodes/types` at runtime). A 10th node only requires
  appending to `nodeCatalog.json`; **no `types.ts` change** if we reuse existing
  `DataType`.

Proposed schema:
- type `"retarget-map"`, category `NodeCategory.RIGGING`, title "Retarget Map".
- inputs: `motion: NEUTRAL_ANIMATION`.
- outputs: `motion: NEUTRAL_ANIMATION` (retargeted motion).
- params: `mapping_preset` (STRING — name of a built-in preset OR a
  file/URL ref; see Finding 5), `use_root_translation` (BOOLEAN, §14.3),
  `foot_ik` (BOOLEAN), `scale_source_height` (BOOLEAN), `preserve_keyframes`
  (BOOLEAN), plus optional per-bone overrides (axis, offset) for advanced use.

### 4. Data types

- `DataType` (`schema.py`) **already has** `NEUTRAL_ANIMATION`,
  `NEUTRAL_POSE`, `ANY`. A `retarget-map` node consumes/emits
  `NEUTRAL_ANIMATION`, so **no new `DataType` member is required**.
- A dedicated `RETARGET_MAP`/`BONE_HIERARCHY` type is **not warranted**: the
  mapping is a node *param* (config), not a port value flowing between nodes in
  the MVP. Intro the mapping as a validated Pydantic model in `domain/
  retargeting/`, referenced by the node's `mapping_preset` param, rather than a
  new port `DataType` (which would ripple through `types.ts` + `handles.ts`).
  Decision B.

### 5. YAML/JSON mapping preset — where and how

- **Storage**: no preset dir exists today. Recommend `media/presets/` (the
  repo already ships a `media/` root used to allowlist video paths) or a new
  `config/presets/` sibling. Follow the `video-source` media_root pattern
  (path allowlist, SDD §4.3) so presets are loaded only from an allowlisted
  preset root, never arbitrary user paths.
- **Parsing safety (hard constraint: no eval/exec)**: the AGENTS.md guardrail
  forbids `eval`/`exec`/`pickle.loads` on untrusted input. The mapping preset is
  user-authored config to be *parsed*, not executed. Use a controlled loader:
  YAML → shallow dict via `yaml.safe_load` (PyYAML — an infra-layer dep, NOT in
  domain), or JSON via stdlib `json.load`. The retarget **domain** consumes an
  already-typed Pydantic `RetargetMap` model; parsing happens in the adapter
  (infra), matching "domain is pure, no heavy deps" (SDD §2.3). This preserves
  the stdin/stdout boundary cleanly.
- Built-in presets (e.g. a Mixamo-like or identity preset) would be checked-in
  YAML/JSON under `media/presets/` and referenced by name; user presets by
  allowlisted path or name.

### 6. Risks and scope

1. **Bone-name convention** (Decision A) — highest risk. Renaming existing
   `LShoulder`→`LeftShoulder` etc. touches `skeleton_presets.py`, `mapping.py`
   (COCO_TO_NEUTRAL values), `cleanup.py` (`_FOOT_BONES`), `motion_conversion`,
   frontend `types.ts`/`handles.ts`/fixtures, tests, and every stored document —
   a **versioned migration + ADR** (soft constraint, `NeutralMotion` immutable,
   SDD §5.3). Alternative: keep abbreviated names as canonical and word presets
   in that key space (no migration, but deviates from plan §14.3 wording).
2. **Axis conversions (§14.4)** — per-bone axis correction/rotation offset is
   quaternion math; the domain needs public quaternion helpers. Today they are
   **private** in `inbetween.py` (`_quat_dot/_quat_negate/_quat_normalize/_slerp`).
   Decide: promote to a shared `domain/animation/quat.py` (reused by both) or
   keep private + new helpers in `domain/retargeting/`. Duplication is a
   maintainability smell; promotion is the cleaner SRP choice.
3. **IK/FK flags and foot_ik** — foot contact/locking already exists in
   `cleanup.py` (translation-only XZ clamp). Retarget `foot_ik` can reuse that
   concept but must be clear about scope: translation-only foot lock (existing)
   vs. true rotational IK (deferred). Don't reimplement `temporal-cleanup`.
4. **Rotation-only vs position+rotation MVP** — the upstream pipeline emits
   identity rotation, so a rotation-retarget MVP has nothing to rotate yet.
   Realistic MVP: **position (translation)+scale remap + axis correction on
   translation, with rotation-offset machinery in place but exercised on
   test rigs**; OR gate rotation behind `preserve_keyframes`-style opts. Must be
   an explicit product decision.
5. **Preset file security** — YAML `safe_load`, path allowlist, size cap; align
   with the existing `video-source` media_root pattern and the enriched-node
   threat-model row (SDD §4.2). Cover malformed preset / unknown bone /
   unmapped bone negative tests.
6. **Testing strategy** — retarget math is pure stdlib on
   `NeutralMotion`/`Transform3D`; test it exactly like `test_inbetween.py` /
   `test_cleanup.py`: build documents directly, assert remapped bones, axis
   corrections, scale, invariants (frozen, deterministic, `validate_invariants`
   passes). `hypothesis` guarded in `[ai]` optional group only. No GPU/network.

## Affected Areas

- `aimation_actor_core/domain/retargeting/` — empty package today; home of the
  pure retarget math (`RetargetMap`, bone mapping application, axis/offset/scale)
  and the `RetargetMap` Pydantic model.
- `aimation_actor_core/domain/animation/{skeleton_presets,entities,neutral_motion}.py`
  — neutral skeleton + `Transform3D`/`NeutralMotion` the retarget consumes
  (unchanged unless Decision A renames bones).
- `aimation_actor_core/infrastructure/ai_models/retarget_map.py` — new
  `retarget-map` node adapter (INode schema, dict coercion, `asyncio.to_thread`,
  param + preset validation, safe YAML/JSON preset loader).
- `aimation_actor_core/infrastructure/virtual/node_registry.py` — register the
  10th seed node.
- `media/presets/` (new) — checked-in YAML/JSON mapping presets.
- `frontend/src/test/fixtures/nodeCatalog.json` — append `retarget-map` schema
  (golden, contract-tested). `types.ts`/`handles.ts` unchanged unless a new
  `DataType` is introduced (not recommended).
- `openspec/specs/node-registry/spec.md` + new `retargeting` domain spec — delta
  requirements (registry 10th seed; retarget math; preset safety).

## Approaches

1. **Domain-math + adapter + additive registry (recommended)** — pure-stdlib
   `domain/retargeting/` (RetargetMap → LocalTransform application) + a thin
   `retarget-map` node adapter that parses an allowlisted YAML/JSON preset via
   `yaml.safe_load` into a `RetargetMap`. Register as 10th seed (`RIGGING`).
   MVP = position+scale remap with axis/rotation-offset machinery, foot_ik
   reusing the translation-only contact-lock concept. Tests mirror
   `test_inbetween.py`. Effort: Medium-High.
2. **Preset-config-only, no rotation** — a `retarget-map` node that only remaps
   translation (child-parent local offsets re-rooted to the target skeleton) and
   renames/reorders bones, deferring all rotation/axis/IK. Smallest, fastest,
   but skips §14.4's core value and risks rework. Effort: Low-Medium.
3. **Full IK/FK hybrid in MVP** — includes true rotational IK/FK and full joint
   limits per §14.4. Highest value but complex; upstream path has no rotation to
   feed it, and it would block on unbuilt pieces. Effort: High — not MVP.

## Recommendation

**Approach 1**, scoped to a deterministic position+scale retarget with the
rotation/axis/offset machinery built and unit-tested (on test rigs) but not
reliant on upstream rotation, `foot_ik` reusing the existing translation-only
contact-lock semantics, and the map delivered as an allowlisted YAML/JSON preset
(`safe_load`, never `eval`). This delivers the §14 node end-to-end on the graph
with deterministic, dependency-free math, keeps `domain/retargeting/` pure, and
preserves the established node-adapter + catalog-sync + pure-stdlib precedents.
The orchestrator must first resolve Decision A (bone naming) and Decision B
(DataType reuse) with the user.

## Open Decisions / Risks

- **Decision A — bone-name convention**: rename to canonical `Left…/Right…`
  (needs migration + ADR, wide blast radius) vs. keep `L…/R…` as canonical
  (deviates from plan §14.3). **Must be decided before spec.**
- **Decision B — DataType**: reuse `NEUTRAL_ANIMATION` (recommended) vs. a new
  `RETARGET_MAP` type (ripples TS).
- **Decision C — rotation scope in MVP**: position-only vs. position+rotation
  machinery (rotation has no upstream source yet).
- **Decision D — quaternion helpers**: promote `inbetween.py` private helpers to
  a shared `domain/animation/quat.py` vs. duplicate in `domain/retargeting/`.
- **Decision E — preset storage/lookup**: `media/presets/` by name vs. path,
  and whether a built-in identity/Mixamo-like preset ships in MVP.

## Non-Goals (first slice)

- No true rotational IK/FK, no joint-limit solvers, no blendshapes/facial
  retarget (§14.1 "facial rigs — future").
- No DCC plugin / shadow-rig push (plan §15) — out of scope.
- No change to `NeutralMotion` schema or to the `INode` contract.
- No real/animated rotation source until the upstream rotation stage lands.

## Ready for Proposal

Yes — but the proposal should lead with Decision A (bone naming) and Decision B
(DataType), then confirm the MVP rotation scope (Decision C). The
`domain/retargeting/` package, the `RIGGING` category, the node-adapter pattern,
and the registry/catalog/spec mechanics are all confirmed reusable and need no
contract changes.
