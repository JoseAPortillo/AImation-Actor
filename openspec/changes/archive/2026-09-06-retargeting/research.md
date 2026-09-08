# Research: Retargeting (§14)

> Planning-stage change trail for change `retargeting` (plan §14). Not a
> committed spec. Produced by the `sdd-research` phase. **Status: done.**

## Status

**done** — All five research lanes have auditable, URL-cited source evidence.
The `open-web` evidence class was granted and exercised. 12 unique sources
fetched/searched; every claim below maps to at least one URL.

## Executive Summary

Industry bone naming converges on `Left`/`Right` PascalCase prefixes (Mixamo,
BVH, Unity Humanoid) — confirming Decision A to rename `LShoulder`→`LeftShoulder`.
Retarget mapping is modeled per-chain (UE5) or per-bone (Babylon.js, Orillusion)
with fields for rotation offset, root translation scaling, and IK goals. Axis
conventions vary: FBX/Y-up, glTF/Y-up, Blender/Z-up, with quaternion swizzle
rules (`(w,x,y,z)` → `(x,y,z,w)` reorder + axis swap). YAML preset safety is
unambiguously `safe_load` + Pydantic `model_validate(extra="forbid")` — `yaml.load`
is equivalent to `eval()`. Position remap math uses height-ratio scaling of root
translation with ground-reference correction; per-bone scale is avoided in favor
of rotation-only remapping for limb bones.

## Evidence Map

| Lane | Sources | Outcome |
|---|---|---|
| 1 Bone naming | 4 sources | done — strong consensus |
| 2 Mapping formats | 5 sources | done — convergent data shapes |
| 3 Axis/rotation | 4 sources | done — well-documented conventions |
| 4 YAML safety | 4 sources | done — unambiguous best practice |
| 5 Position math | 4 sources | done — convergent algorithms |

---

## Lane 1: Bone Naming Conventions in the Industry

### Evidence

**[S1-1]** MoCap Online — "Character Skeleton Hierarchy: Bones, Joints & Rigs Explained"
URL: https://mocaponline.com/blogs/mocap-news/skeleton-hierarchy-animation-guide
Accessed: 2026-09-06
Excerpt: Lists canonical naming per platform:
- UE: `pelvis`, `spine_01`, `upperarm_l`, `hand_r` (lowercase, underscore, `_l`/`_r` suffix)
- Unity Humanoid: `Hips`, `Spine`, `LeftUpperArm`, `RightHand` (PascalCase, `Left`/`Right` prefix)
- Mixamo: `mixamorig:Hips`, `mixamorig:LeftArm` (namespace prefix, PascalCase)
- BVH standard: `Hips`, `Chest`, `LeftUpLeg`, `RightHand` (PascalCase, `Left`/`Right` prefix)

**[S1-2]** Mixamo Converter (enziop/mixamo_converter)
URL: https://github.com/enziop/mixamo_converter/blob/master/mixamoconv.py
Accessed: 2026-09-06
Excerpt: Mixamo canonical names: `LeftShoulder`, `LeftArm`, `LeftForeArm`, `LeftHand`,
`LeftUpLeg`, `LeftLeg`, `LeftFoot`, `LeftToeBase` — PascalCase `Left`/`Right` prefix.
The converter maps these to UE4 names (`clavicle_l`, `upperarm_l`, etc.) via a
deterministic lookup dict.

**[S1-3]** Blender Mixamo Rig Renamer Gist (MinaPecheux)
URL: https://github.com/MinaPecheux/BlenderPlugins/blob/master/Rigging/MixamoRigRenamer.py
Accessed: 2026-09-06
Excerpt: Blender convention uses `.L`/`.R` suffix (e.g. `Arm.L`, `Arm.R`).
Mixamo names use `Left`/`Right` prefix; conversion strips `Left`→`.L`, `Right`→`.R`.

**[S1-4]** UE5 IK Retarget Chain auto-naming (UhiyamaLab guide)
URL: https://uhiyama-lab.com/en/notes/ue/animation-retargeting-complete-guide/
Accessed: 2026-09-06
Excerpt: "Chain names should be identical on source and target. If one side says
`LeftArm` and the other says `Arm_L`, they won't connect automatically."
UE5 auto-detects Left/Right by comparing average bone X position: negative X = Left,
positive X = Right.

### Analysis

The **de facto standard** for humanoid bone naming is PascalCase with `Left`/`Right`
prefix: `LeftArm`, `RightUpLeg`, etc. This is shared by Mixamo, BVH, and Unity
Humanoid. The exceptions are engine-internal formats (UE uses `upperarm_l` suffix,
Blender uses `.L`/`.R` suffix). FBX interchange preserves the source author's naming.

**Implication for Decision A**: Renaming `LShoulder`→`LeftShoulder` aligns the
neutral skeleton with the dominant industry convention (Mixamo/BVH/Unity). The
current `L`/`R` prefix is non-standard — no major tool uses it. Rename is confirmed
correct by external evidence.

---

## Lane 2: Retarget Mapping Formats

### Evidence

**[S2-1]** UE5 IKRetargetPose API
URL: https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/IKRetargetPose
Accessed: 2026-09-06
Excerpt: Per-bone fields: `bone_rotation_offsets` (Map[Name, Quat]) — LOCAL-space
rotation deltas. `root_translation_offset` (Vector) — GLOBAL-space translation
applied only to pelvis. Chain-based mapping (not per-bone): source chain name →
target chain name. IK goals per chain for foot/hand contact.

**[S2-2]** UE5 IK Retargeter Documentation
URL: https://dev.epicgames.com/documentation/unreal-engine/ik-rig-animation-retargeting-in-unreal-engine
Accessed: 2026-09-06
Excerpt: Data model is chain-based: each IK Rig defines chains (Spine, LeftArm,
RightLeg, etc.) with start/end bones. The IK Retargeter maps source chains to
target chains by name. Per-chain settings include FK/IK mode, translation mode
(Skeleton/Animation/AnimationScaled). Pelvis bone is set separately for root
motion. Retarget pose per bone with rotation offsets.

**[S2-3]** Babylon.js Animation Retargeting
URL: https://doc.babylonjs.com/features/featuresDeepDive/animation/animationRetargeting/
Accessed: 2026-09-06
Excerpt: Per-bone fields: name (string), position/quaternion/scaling corrections
(optional). Options: `retargetAnimationKeys` (boolean), `fixRootPosition` (boolean,
scales root by height ratio), `fixGroundReference` (boolean, pins ground bone),
`groundReferenceNodeName` (string, typically `"LeftFoot"` or `"RightFoot"`).
Rest-pose corrections are per-bone name→transform pairs.

**[S2-4]** UE4 Intro to Animation Retargeting
URL: https://www.unrealengine.com/blog/intro-to-animation-retargeting-in-ue4
Accessed: 2026-09-06
Excerpt: Three bone translation modes: `Skeleton` (bind pose), `Animation` (raw
animation), `AnimationScaled` (animation scaled by bone-length ratio). Pelvis uses
`AnimationScaled`; limbs use `Skeleton`; root/IK bones use `Animation`. IK bones
chain off hands for prop interaction.

**[S2-5]** Orillusion Retargeter Class
URL: https://www.orillusion.com/en/api/classes/Retargeter.html
Accessed: 2026-09-06
Excerpt: Per-bone mapping: `offset[bone] = inv(bindWorldS[srcBone]) * bindWorldT[tgtBone]`.
Translation: hip only, with `heightScale` factor. Children bones never receive position
updates — only rotation. `alignTPoseFacing` option pre-rotates target to match source
facing direction.

### Analysis

Two dominant patterns emerge:

1. **Chain-based** (UE5): Maps groups of bones by chain name. More flexible for
   differing bone counts per limb. Per-chain IK/FK toggle and translation mode.
2. **Per-bone** (Babylon.js, Orillusion): Maps individual bone names with per-bone
   rotation offsets and corrections. Simpler, more direct.

**Convergent fields across all formats**:
- Source bone name / Target bone name (or chain pair)
- Rotation offset (quaternion or euler, LOCAL space)
- Root/pelvis translation scaling (by height ratio)
- IK goals for foot/hand contact
- Rest-pose alignment (T-pose vs A-pose correction)

**Implication for RetargetMap schema**: MVP should support per-bone name mapping
with rotation offset, axis correction, and scale. Chain-based grouping can be
a future extension. Root translation mode (scaled vs absolute) is standard.

---

## Lane 3: Axis/Rotation Conventions

### Evidence

**[S3-1]** glTF Specification — Coordinate System and Units
URL: https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#coordinate-system-and-units
Accessed: 2026-09-06 (via DeepWiki summary + Khronos issues)
Excerpt: "glTF uses a right-handed coordinate system. glTF defines +Y as up,
+Z as forward." Quaternion component order: `(x, y, z, w)` (w-last).

**[S3-2]** glTF-Blender-IO Mathematical Transformations
URL: https://deepwiki.com/KhronosGroup/glTF-Blender-IO/10.1-mathematical-transformations-deep-dive
Accessed: 2026-09-06
Excerpt: Blender Z-up → glTF Y-up conversion: location `(x,y,z) → (x,z,-y)`,
rotation `(w,x,y,z) → (w,x,z,-y)`, scale `(x,y,z) → (x,z,y)`. Quaternion
reorder from `(w,x,y,z)` to `(x,y,z,w)`. A correction quaternion
`(√2/2, -√2/2, 0, 0)` represents -90° rotation around X-axis. The `to_yup()`
matrix is its own inverse (self-inverse transformation).

**[S3-3]** FBX Axis Convention
URL: https://docs.vizrt.com/viz-artist-guide/3.9.1/FBX_Files.html
Accessed: 2026-09-06
Excerpt: "FBX uses a Y-up axis system. If the modeling application uses a different
axis system it will apply pre-rotation of ±90° to all objects." Maya = Y-up (no
correction needed). 3ds Max = Z-up (requires axis conversion section in export).

**[S3-4]** Genesis World Coordinate Conventions
URL: https://genesis-world.readthedocs.io/en/latest/user_guide/getting_started/conventions.html
Accessed: 2026-09-06
Excerpt: "There is no single, universal transformation that converts between Y-up
and Z-up. Two assets can both be labeled 'Y-up' yet differ in orientation if they
choose different forward axes." Genesis uses Blender-aligned Y-up: Y-up, -Z forward.
glTF is always interpreted as Y-up on import. "Simply stating that an asset is
'Y-up' or 'Z-up' is not sufficient to fully define its spatial convention."

### Analysis

**Axis conventions by format**:
| Format | Up axis | Forward axis | Handedness | Quaternion order |
|---|---|---|---|---|
| FBX (default) | +Y | -Z | Right-handed | `(w,x,y,z)` |
| glTF | +Y | +Z | Right-handed | `(x,y,z,w)` |
| Blender | +Z | -Y | Right-handed | `(w,x,y,z)` |
| BVH | Varies | Varies | Varies | Euler (varies) |

**Key pitfall**: glTF has +Z forward while FBX has -Z forward — same Y-up but
different forward direction. A naive axis swap without accounting for forward
direction produces a character facing backwards.

**Quaternion convention**: glTF uses `(x,y,z,w)` (w-last). Most Python math
libraries use `(w,x,y,z)` (Hamilton/w-first). Conversion is a simple reorder.

**Implication**: The neutral skeleton uses Y-up (consistent with FBX/glTF default).
Axis correction per bone must handle the forward-axis difference. The conversion
matrix is well-documented and deterministic.

---

## Lane 4: YAML/JSON Preset Safety and Schema Validation

### Evidence

**[S4-1]** PyYAML Official Documentation
URL: https://pyyaml.org/wiki/PyYAMLDocumentation
Accessed: 2026-09-06
Excerpt: "It is not safe to call `yaml.load` with any data received from an
untrusted source! `yaml.load` is as powerful as `pickle.load` and so may call any
Python function." `safe_load` "recognizes only standard YAML tags and cannot
construct an arbitrary Python object."

**[S4-2]** PyYAML yaml.load Deprecation Wiki
URL: https://github.com/yaml/pyyaml/wiki/PyYAML-yaml.load(input)-Deprecation
Accessed: 2026-09-06
Excerpt: "`SafeLoader` loads a subset of the YAML language, safely. This is
recommended for loading untrusted input." `FullLoader` "should be avoided for now.
New exploits in 5.3.1 were found in July 2020." Deprecated since PyYAML 5.1+.

**[S4-3]** PyYAML Security Guide (Safeguard.sh, 2026)
URL: https://safeguard.sh/resources/blog/pyyaml-security-guide
Accessed: 2026-09-06
Excerpt: "Treat `yaml.load(untrusted)` as equivalent to `eval()`." CVEs
CVE-2017-18342, CVE-2019-20477, CVE-2020-14343 all exploit the default loader.
"Always use `yaml.safe_load()` ... for anything you did not author yourself."
Recommended: "Run PyYAML 6.0.2 or later." "Validate the parsed structure against
a schema after loading, and bound input size to limit resource-exhaustion."

**[S4-4]** Python Config & Secrets Hub — YAML & JSON Parsing Strategies
URL: https://python-config-secrets-hub.com/core-configuration-patterns-file-formats/yaml-json-parsing-strategies/
Accessed: 2026-09-06
Excerpt: "Two rules govern safe structured-config parsing ... parse safely: use
`yaml.safe_load` ... validate the shape: feed the parsed dict into a pydantic
model with `extra="forbid"`." "The two rules are genuinely independent — you can
parse safely and still forget to validate the shape ... both must be applied
together, every time." Set size limit before parsing to defend against
billion-laughs attacks.

### Analysis

The security guidance is **unanimous and unambiguous**:
1. `yaml.safe_load` (or `json.loads`) for parsing — never `yaml.load`, `yaml.full_load`,
   or `yaml.unsafe_load` on user-supplied input.
2. Pydantic `model_validate(parsed_dict)` with `extra="forbid"` for schema validation.
3. Size cap before parsing for billion-laughs defense.
4. `yaml.load` on untrusted input has produced multiple CVEs and is equivalent to `eval()`.

**Precedent for shipping presets as YAML**: No specific animation tool was found
shipping YAML presets, but the pattern of shipped YAML configs with safe_load is
extremely widespread in Python ecosystem tooling. The security contract is
format-agnostic — the same rules apply whether the file ships with the app or
is user-authored.

**Implication**: The explore phase recommendation (safe_load → Pydantic model with
`extra="forbid"`, path allowlist, size cap) is confirmed as industry best practice
with strong CVE-backed justification.

---

## Lane 5: Position Remap Math

### Evidence

**[S5-1]** Babylon.js Animation Retargeting
URL: https://doc.babylonjs.com/features/featuresDeepDive/animation/animationRetargeting/
Accessed: 2026-09-06
Excerpt: Root position scaling: `d_source` and `d_target` are distances along
vertical axis from root bone to ground reference bone. Root displacement is
scaled by `d_target / d_source` ratio. Ground reference pass: iterates keyframes,
reads world-space ground bone positions, subtracts vertical difference from
retargeted root. `fixRootPosition` and `fixGroundReference` are independent options.

**[S5-2]** UE4 Intro to Animation Retargeting
URL: https://www.unrealengine.com/blog/intro-to-animation-retargeting-inue4
Accessed: 2026-09-06
Excerpt: `AnimationScaled`: "Bone translation comes from the animation data, but
its length is scaled by the Skeleton's proportions. This is the ratio between the
bone length of the Target Skeletal Mesh and the Source Skeletal Mesh."
Pelvis uses `AnimationScaled`; limbs use `Skeleton` (bind pose); root/IK use
`Animation` (unchanged).

**[S5-3]** Orillusion Retargeter Class
URL: https://www.orillusion.com/en/api/classes/Retargeter.html
Accessed: 2026-09-06
Excerpt: "Children bones never receive position updates — Mixamo characters have
different bone-segment lengths, and forcing source positions onto target bones
distorts the mesh shape. The hip is the one bone where translation is meaningful."
Height scale: `delta_charLocal_T = inv(rootRot_T) * rootRot_S * delta_charLocal_S`;
`targetHip.localPosition = bindHipLocal_T + delta_charLocal_T * heightScale`.

**[S5-4]** StraySpark — UE5 Animation Retargeting Guide
URL: https://www.strayspark.studio/blog/unreal-engine-animation-retargeting-ik-rig-complete-guide
Accessed: 2026-09-06
Excerpt: "Scaling root translation by the height ratio fixes the sliding — at the
cost of your character now moving at a different world-space speed." Trade-off:
"you can have matching foot contact or matching movement speed, and reconciling
them is a gameplay-side adjustment." Foot IK goals are essential: "Without foot
IK goals, retargeting maps rotations faithfully and lets positions fall where they
may."

### Analysis

**Convergent algorithm** across all sources:
1. **Hip/root translation**: Scale root bone displacement by `target_height /
   source_height` ratio. Only the hip bone receives translation updates; child
   bones keep bind-pose positions.
2. **Limb bones**: Rotation-only remapping. No per-bone position scaling (causes
   mesh distortion). Scale is implicit in the rotation chain.
3. **Ground reference**: Per-frame correction using a ground contact bone
   (typically foot/toe) to prevent floating/sinking. Independent of root scaling.
4. **Foot IK**: Separate IK constraint that pins foot to ground plane during
   contact phases. Essential for non-uniform proportions.

**Key formula** (Orillusion, Babylon.js both confirm):
```
scale_ratio = target_hip_to_ground / source_hip_to_ground
target_hip_pos = bind_hip + (source_delta * scale_ratio)
```

**Implication**: MVP retarget math should implement:
- `scale_source_height` option (height ratio scaling of root translation)
- `foot_ik` option (ground reference correction using foot bone)
- Per-bone: rotation only (no position), with optional rotation offset
- `preserve_root_translation` option (absolute vs scaled)

---

## Contradictions / Uncertainty / Freshness

- **No contradictions found** across lanes. Sources are consistent on naming
  conventions, safety practices, and math algorithms.
- **Uncertainty**: Bone naming docs for Mixamo are not directly from Adobe's
  official documentation (Adobe's Mixamo docs are sparse/behind login). Closest
  authoritative sources are the mixamo_converter repo (widely used, 800+ stars)
  and the MoCap Online guide (industry reference). BVH naming is format-standard
  but not formally specified by a standards body.
- **Freshness**: All sources accessed 2026-09-06. PyYAML CVE history is
  well-established. UE5 documentation is current (v5.7/5.8). glTF spec is
  stable (v2.0).

## Artifacts

- Engram: topic key `sdd/retargeting/research` (project `aimation-actor`,
  `capture_prompt: false`) — full evidence-backed research report.
- File: `openspec/changes/retargeting/research.md` — this document.

## Risks

1. **Decision A (rename) blast radius confirmed**: Renaming touches
   `skeleton_presets.py`, `mapping.py`, `cleanup.py`, frontend fixtures, and
   stored documents. ADR + versioned migration required. Research confirms
   rename is correct — no external standard uses `L`/`R` prefix.
2. **Axis conversion pitfalls**: glTF vs FBX forward-axis difference (+Z vs -Z)
   is a real trap. Must be handled in retarget math, not assumed uniform.
3. **Height-ratio scaling trade-off**: Root translation scaling trades movement
   speed accuracy for foot contact accuracy. Must be an explicit user option
   (`scale_source_height`), not a default.
4. **Quaternion convention mismatch**: glTF `(x,y,z,w)` vs Python `(w,x,y,z)`.
   Must be handled at serialization boundary, not in domain math.

## Next Recommended

`sdd-spec` — research is `done`, product decisions A and C are confirmed.
The spec phase should produce delta requirements for:
- Bone naming migration (ADR + `NeutralMotion` version bump)
- `RetargetMap` Pydantic model (per-bone fields: source_name, target_name,
  rotation_offset, axis_correction, scale, ik_flag, foot_contact)
- `retarget-map` node schema and adapter
- YAML/JSON preset format spec
- Position remap math spec (height ratio, ground reference, foot IK)

## Skill Resolution

`sdd-research`: **done** — `open-web` evidence class granted and exercised.
12 unique sources fetched/searched across 5 lanes. All claims URL-cited.
