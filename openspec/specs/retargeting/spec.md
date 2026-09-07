# Retargeting Specification

## Purpose

A rigging stage (`retarget-map`, `NodeCategory.RIGGING`) that maps a `NeutralMotion` (`NEUTRAL_ANIMATION`) to a target rig via a user YAML/JSON `RetargetMap` preset and emits a retargeted `NeutralMotion` (`NEUTRAL_ANIMATION`). Before the map applies, the neutral skeleton's abbreviated `L/R` bone names are canonicalized to the plan §14.2 `Left…/Right…` names via a versioned `NeutralMotion` migration (ADR; `meta.version` bump). Math lives in `domain/retargeting/` as pure stdlib; rotation/axis/offset machinery is exercised on synthetic test rigs (MVP scope — the upstream pipeline emits identity rotation, Decision C). Reuses `NEUTRAL_ANIMATION` in/out — no new `DataType` (Decision B). Presets load only from an allowlisted root via `yaml.safe_load`/`json.load`, never `eval`.

## Requirements

### Requirement: Canonical neutral bone names

The neutral skeleton MUST use the plan §14.2 canonical names: `LeftShoulder`, `RightShoulder`, `LeftArm`, `RightArm`, `LeftForeArm`, `RightForeArm`, `LeftHand`, `RightHand`, `LeftUpLeg`, `RightUpLeg`, `LeftLeg`, `RightLeg`, `LeftFoot`, `RightFoot`, `LeftToeBase`, `RightToeBase` (replacing `LShoulder`/`LArm`/…). The rename MUST be applied consistently across the neutral skeleton, the COCO→neutral mapping, cleanup foot-bone references, and motion conversion, and MUST be delivered as a versioned migration: `meta.version` bumps from `0.2` to `0.3`, an ADR records the change (SDD §5.3), and reading a pre-migration document MUST either migrate its bone names or be rejected with a clear message (backward-compat or explicit breaking policy). A `NeutralMotion` produced after the change MUST satisfy `validate_invariants()`.

#### Scenario: Canonical names in the constructed skeleton

- GIVEN `DEFAULT_NEUTRAL_SKELETON`
- WHEN its bone names are inspected
- THEN every L/R-prefixed bone appears under its canonical `Left…`/`Right…` name and the topology is unchanged

#### Scenario: COCO mapping uses canonical names

- GIVEN the COCO→neutral mapping table
- WHEN `left_shoulder` and `right_hip` are looked up
- THEN they resolve to `LeftShoulder` and `RightUpLeg` respectively

#### Scenario: Version bump recorded

- GIVEN a `NeutralMotion` built by the new pipeline
- WHEN its `meta.version` is read
- THEN it equals `"0.3"` and the change is documented in an ADR

#### Scenario: Pre-migration document handled

- GIVEN a stored `NeutralMotion` carrying `meta.version="0.2"` and legacy `L…` bone names
- WHEN the system reads it
- THEN it either migrates the legacy bone names to canonical form or rejects with a clear unsupported-version message (never silently corrupts the skeleton)

### Requirement: RetargetMap preset model

The system MUST define a `RetargetMap` Pydantic model (frozen, `extra="forbid"`) describing per-bone mapping. Per mapped bone it MUST carry: `source_name` (neutral skeleton bone), `target_name` (target rig bone), `rotation_offset` (quaternion `(w,x,y,z)`, LOCAL space, default identity), `axis_correction` (optional per-bone reorientation), and `scale` (optional `(x,y,z)`, default `(1,1,1)`). It MUST also carry document-level options: `use_root_translation`, `foot_ik`, `scale_source_height`, and `preserve_keyframes` (all boolean). Unknown fields MUST be rejected, and mapping a source or target bone name that is not present in the corresponding skeleton MUST fail validation.

#### Scenario: Well-formed preset validates

- GIVEN a YAML preset mapping `LeftArm: arm_r` with `use_root_translation: true`
- WHEN it is parsed and `model_validate`d
- THEN validation succeeds and the model holds the source/target pair and options

#### Scenario: Unknown extra field rejected

- GIVEN a preset with an unexpected top-level or per-bone key
- WHEN it is validated
- THEN validation fails (no field silently ignored)

#### Scenario: Unknown bone rejected

- GIVEN a preset whose `source_name` is not in the neutral skeleton or `target_name` references an absent bone
- WHEN it is validated against the skeleton
- THEN validation fails

### Requirement: Position/scale remap math

The retarget MUST remap translation following the height-ratio root rule: when `scale_source_height` is enabled, the root (hips) translation is scaled by `target_height / source_height`, where source/target heights are measured from the root to a ground reference bone; when disabled, root translation passes through unchanged. Child bones MUST NOT receive per-bone position updates — their motion is expressed through rotation (and optional per-bone `scale`); scale is never applied to a bone's position except via the root height ratio. The output MUST be deterministic (identical inputs yield byte-identical outputs) and MUST pass `validate_invariants()`.

#### Scenario: Root scaled by height ratio

- GIVEN a motion and a target twice the source height with `scale_source_height=true`
- WHEN the retarget runs
- THEN the root translation displacement doubles and child bone world relationships stay consistent

#### Scenario: Height scaling disabled passes root through

- GIVEN the same motion with `scale_source_height=false`
- WHEN the retarget runs
- THEN root translation is unchanged

#### Scenario: Deterministic and invariant-satisfying

- GIVEN the same input motion and map
- WHEN the retarget runs twice
- THEN both outputs are byte-identical and satisfy `NeutralMotion.validate_invariants()`

### Requirement: Rotation/axis/offset machinery

The system MUST provide shared quaternion helpers in `domain/animation/quat.py` (promoted from `inbetween.py`'s private `_quat_*`/`_slerp`) covering normalize, dot, negate, multiply, and shortest-arc slerp, reused by both in-between generation and retargeting. The retarget MUST apply per-bone `rotation_offset` in LOCAL space and per-bone `axis_correction` to reorient a bone from the source to the target axis convention, including the forward-axis distinction (e.g. glTF +Z vs FBX −Z). The rotation material runs and is unit-tested against synthetic rigs in the MVP; it MUST NOT fabricate rotation when the source carries identity rotation (Decision C).

#### Scenario: Quat helpers shared and correct

- GIVEN the promoted `quat.py` helpers
- WHEN normalize/slerp/multiply are exercised on unit quaternions
- THEN results match the reference shortest-arc and unit-norm invariants

#### Scenario: LOCAL rotation offset applied

- GIVEN a target bone with a `rotation_offset` quaternion
- WHEN the retarget runs on a bone with a non-identity source rotation
- THEN the output rotation is the offset applied in the bone's LOCAL frame

#### Scenario: Axis correction handles forward-axis difference

- GIVEN a source with FBX −Z forward and a target with glTF +Z forward
- WHEN the retarget applies `axis_correction`
- THEN the character faces the same direction (no backwards flip)

#### Scenario: Identity rotation not fabricated

- GIVEN a source bone carrying identity rotation and a non-identity `rotation_offset`
- WHEN the retarget runs in MVP mode
- THEN it leaves rotation at identity (no invented orientation) rather than emitting a spurious rotation

### Requirement: Safe preset ingestion

The `retarget-map` node MUST load mapping presets from an allowlisted preset root (`media/presets/`) only, resolving names within that root and rejecting any path traversal (`..`, absolute paths, symlink escapes). YAML MUST be parsed with `yaml.safe_load` and JSON with stdlib `json.load`; `eval`, `exec`, and unsafe YAML loaders MUST NEVER be used. Parsed content MUST be capped at a maximum size before parsing (billion-laughs defense) and validated through the `RetargetMap` model with `extra="forbid"`. The node MUST validate `mapping_preset`, `use_root_translation`, `foot_ik`, `scale_source_height`, and `preserve_keyframes` parameters before execution.

#### Scenario: Path traversal rejected

- GIVEN a `mapping_preset` of `../secret.yaml` or an absolute path
- WHEN the node resolves the preset path
- THEN loading is rejected and no file outside the allowlisted root is read

#### Scenario: Oversized preset rejected

- GIVEN a preset file exceeding the size cap
- WHEN the node attempts to parse it
- THEN parsing is rejected before any content is consumed

#### Scenario: Malformed YAML rejected

- GIVEN a preset file that is not valid YAML/JSON
- WHEN the node parses it
- THEN the node reports a validation error and does not execute

#### Scenario: No eval path exists

- GIVEN the preset loader implementation
- WHEN it is inspected
- THEN no `eval`, `exec`, or `yaml.load`/`full_load`/`unsafe_load` call is reachable from any untrusted preset input

### Requirement: retarget-map node schema

The `retarget-map` node MUST declare category `NodeCategory.RIGGING`, a single input port `motion: NEUTRAL_ANIMATION`, a single output port `motion: NEUTRAL_ANIMATION` (no new `DataType`, Decision B), and params `mapping_preset` (STRING), `use_root_translation` (BOOLEAN), `foot_ik` (BOOLEAN), `scale_source_height` (BOOLEAN), and `preserve_keyframes` (BOOLEAN). The node MUST be stateless, validate params before execution, load the preset safely, and offload blocking work (e.g. via `asyncio.to_thread`). Math MUST live in `domain/retargeting/`; the adapter owns no math.

#### Scenario: Schema declares RIGGING and NEUTRAL_ANIMATION in/out

- GIVEN the `retarget-map` node schema
- WHEN its category, inputs, and outputs are inspected
- THEN category is `RIGGING`, input is `motion: NEUTRAL_ANIMATION`, output is `motion: NEUTRAL_ANIMATION`

#### Scenario: Invalid params rejected

- GIVEN a `mapping_preset` pointing to a non-existent preset
- WHEN node validation runs
- THEN validation fails and no execution occurs

#### Scenario: Valid preset executes end-to-end

- GIVEN a valid preset and a `NeutralMotion`
- WHEN the node executes
- THEN it returns a retargeted `NeutralMotion` that satisfies the invariants

#### Scenario: Stateless and deterministic

- GIVEN the same input and params
- WHEN the node executes twice
- THEN both outputs are byte-identical

## Constraints (Non-Requirements)

- `domain/retargeting/` and `domain/animation/quat.py` MUST stay pure stdlib (`math` only): no numpy, no scipy — AGENTS.md §3.1, mirroring the in-between generation and temporal-cleanup specs.
- PyYAML (`yaml.safe_load`) is an infra-layer dependency only (SDD §2.3); the domain consumes an already-typed `RetargetMap`.
- `NeutralMotion` schema shape is unchanged except the `meta.version` value (`0.2`→`0.3`); the bone-name change is a versioned migration delivered with an ADR (SDD §5.3, AGENTS.md §3.2 soft constraint).
- `foot_ik` reuses the translation-only contact-lock semantics from temporal-cleanup; rotational IK is out of MVP scope.
- No true rotational IK/FK, no joint-limit solvers, no facial/blendshape retarget, no DCC shadow-rig plugins (plan §15), no change to the `INode` contract.

## Threat Model (SpecSecDev)

Adds one row to the §4.2 table: `Retarget presets (retarget-map, RIGGING)` — threat `malicious YAML/JSON preset / path traversal / arbitrary code` — severity `High` — control `yaml.safe_load`/`json.load`, `extra="forbid"` Pydantic model, size cap before parse, preset-root path allowlist with traversal rejection, no `eval`/`exec` — verification `no-eval static inspection` + `path-traversal tests` + `oversized-preset test` + `malformed-preset test`.
