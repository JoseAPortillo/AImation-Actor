# Design: Retargeting (§14)

## Technical Approach

Rename neutral bones to canonical `Left…/Right…` (ADR-001 + `meta.version` 0.2→0.3 versioned migration), promote the private quaternion helpers to shared `domain/animation/quat.py`, then land pure-stdlib retarget math in `domain/retargeting/` (`RetargetMap` → `retarget_motion`) behind a thin `retarget-map` adapter (`RIGGING`, `NEUTRAL_ANIMATION` in/out, no new `DataType`) that safely ingests allowlisted YAML/JSON presets (`yaml.safe_load`/`json.load`, size cap, `extra="forbid"`, never `eval`). MVP = position+scale remap with rotation/axis/offset machinery rig-tested, never fabricated from identity input (Decision C). Registry grows to 10 seeds; catalog golden appends.

## Architecture Decisions

| Decision | Options | Tradeoff | Decision |
|---|---|---|---|
| D1 Bone naming | rename to canonical vs keep `L/R` | Canonical matches plan §14.3 + Mixamo/BVH/Unity (research L1); rename needs ADR + migration | **Rename** (ADR-001, version bump) |
| D2 Read policy | migrate-on-read vs reject-0.2 | Backward-compat keeps stored docs usable; explicit mapping means no silent corruption | **Accept 0.2 (migrate) + 0.3; write 0.3 always** |
| D3 Migration site | `migrate_neutral_motion()` at coercion vs Pydantic before-validator | Central helper keeps value object pure; adapters own the read boundary | **Helper in `neutral_motion.py`, called by `_coerce_motion`** |
| D4 Quat helpers | promote to `domain/animation/quat.py` vs duplicate | SRP; inbetween + retarget share; no behavior change | **Promote + add `quat_multiply`** |
| D5 Map format | per-bone dict with shorthand string promotion | Plan §14.3 `mapping: {LeftArm: l_arm_ctrl}` must validate; full fields need object form | **`mapping: dict[str, RetargetEntry]`, string→entry promotion** |
| D6 Root scale source | `target_root_to_ground_cm` preset option vs node param vs new port | No target skeleton on the graph; node params fixed by spec; new port ripples TS | **Preset document option (extension)** |
| D7 Preset safety | safe_load + Pydantic + size cap + allowlist (mirror `video-source`) | CVE-backed (research L4); `extra="forbid"` rejects unknowns | **Full chain, in the adapter (infra)** |
| D8 YAML dep | add `pyyaml>=6.0` base dep | §3.2 soft constraint: MIT, maintained; infra-only (import-linter keeps domain pure) | **Add to `[project.dependencies]`; flag for review** |
| D9 Target validation | source-only at node; optional target param for rigs | Target rig absent from graph (map_provider nil) | **`validate_against(source, target=None)`; target checked on rigs in tests** |

## Data Flow

```
preset file (media/presets/*.yaml|json)
   │  resolve allowlist → stat size cap → yaml.safe_load/json.load
   ▼
RetargetMap.model_validate (frozen, extra="forbid") → validate_against(source skeleton)
   ▼
motion (0.2→migrate→0.3) ──► retarget_motion ──► validate_invariants ──► motion (0.3)
   ① Hips translation × height ratio (if scale_source_height)   ② per-bone rotation
   (offset·axis, non-identity source only)   ③ per-bone scale   ④ foot_ik ground pass
```

## File Changes

| File | Action | Description |
|---|---|---|
| `docs/adr/001-neutral-bone-names.md` | Create | ADR-001 (new `docs/adr/` registry, SDD §3.4) |
| `domain/animation/skeleton_presets.py` | Modify | Canonical names + `LEGACY_BONE_RENAME_MAP` (16 entries) |
| `domain/animation/mapping.py` | Modify | COCO values → canonical |
| `domain/animation/cleanup.py` | Modify | `_FOOT_BONES` → `LeftFoot/RightFoot` |
| `domain/animation/neutral_motion.py` | Modify | `meta.version` default "0.3"; `migrate_neutral_motion` |
| `domain/animation/quat.py` | Create | Promoted helpers + `quat_multiply` (public API) |
| `domain/animation/inbetween.py` | Modify | Import from quat.py; delete private helpers (no behavior change) |
| `domain/animation/__init__.py` | Modify | Re-export quat + migration API |
| `domain/retargeting/map.py` | Create | `RetargetEntry`, `RetargetMap` (frozen, `extra="forbid"`) |
| `domain/retargeting/retarget.py` | Create | `retarget_motion`, root/rotation/scale/foot_ik passes |
| `domain/retargeting/rotation.py` | Create | `apply_rotation`, `axis_correction_quat` (forward-axis pairs) |
| `domain/retargeting/__init__.py` | Modify | Re-exports |
| `infrastructure/ai_models/retarget_map.py` | Create | `RetargetMapNode` + allowlisted preset loader |
| `infrastructure/virtual/node_registry.py` | Modify | 10th seed `retarget-map` |
| `infrastructure/ai_models/temporal_cleanup.py`, `inbetween_generation.py` | Modify | `_coerce_motion` → `migrate_neutral_motion` |
| `infrastructure/ai_models/__init__.py` | Modify | Re-export `RetargetMapNode` |
| `media/presets/identity.yaml` | Create | Built-in identity preset |
| `frontend/src/test/fixtures/nodeCatalog.json` | Modify | Append `retarget-map` golden (contract-tested) |
| `tests/` (domain+infra) | Modify/Create | See Testing Strategy; seed-count tests 8/9→10 |
| `openspec/specs/temporal-cleanup/spec.md` | Modify | Wording `LFoot/RFoot` → `LeftFoot/RightFoot` (referential) |

`frontend/src/api/types.ts`, `handles.ts`, `Palette.tsx`: **unchanged** — `RIGGING` and `neutral_animation` already present (verified).

## Interfaces / Contracts

```python
# domain/animation/quat.py — pure math, stdlib only
def quat_dot(qa: Vec4, qb: Vec4) -> float
def quat_negate(q: Vec4) -> Vec4
def quat_normalize(q: Vec4) -> Vec4
def quat_multiply(qa: Vec4, qb: Vec4) -> Vec4      # Hamilton product (new; offset application)
def slerp(q0: Vec4, q1: Vec4, t: float) -> Vec4    # short-arc; nlerp near-parallel (eps 1e-6)

# domain/animation/neutral_motion.py
LEGACY_BONE_RENAME_MAP  # 16-entry explicit table (NEVER prefix-replace: "Root" starts with R!)
def migrate_neutral_motion(raw: Any) -> NeutralMotion  # 0.2→rename+bump+validate; 0.3 passthrough; else UnsupportedNeutralVersionError

# domain/retargeting/map.py
class RetargetEntry(BaseModel):      # frozen, extra="forbid"
    target_name: str
    rotation_offset: Vec4 = (1,0,0,0)      # LOCAL space
    axis_correction: Vec4 | None = None
    scale: Vec3 = (1,1,1)
    # mode="before": plain str → {"target_name": v}   (plan §14.3 shorthand)
class RetargetMap(BaseModel):        # frozen, extra="forbid"
    mapping: dict[str, RetargetEntry]
    use_root_translation: bool = True
    foot_ik: bool = False
    scale_source_height: bool = False
    preserve_keyframes: bool = False
    target_root_to_ground_cm: float | None = None   # ratio source; None → scaling inert
    def validate_against(self, source: Skeleton, target: Skeleton | None = None) -> None

# domain/retargeting/rotation.py
def apply_rotation(rotation: Vec4, entry: RetargetEntry) -> Vec4
    # identity source → identity out (MVP: never fabricate)
    # else q' = normalize(axis_correction · rotation · rotation_offset)
def axis_correction_quat(source_forward: str, target_forward: str) -> Vec4
    # 'fbx'(-Z)→'gltf'(+Z): 180° about Y (0,0,1,0); 'yup'↔'zup': ±90° about X (√2/2, ∓√2/2, 0, 0)

# domain/retargeting/retarget.py
def retarget_motion(motion: NeutralMotion, retarget_map: RetargetMap) -> NeutralMotion
    # ① root: Hips translation ×= target/source root→ground ratio (scale_source_height
    #   and target height present; use_root_translation=False → untouched)
    # ②/③ per-bone: rotation (non-identity source) + scale elementwise
    # ④ foot_ik: ground-reference pass on Hips Y (contact tracks, else lowest-foot)
    # model_copy(update=...) → validate_invariants(); byte-deterministic

# infrastructure/ai_models/retarget_map.py
class RetargetMapNode(INode):
    def __init__(self, preset_root: Path = Path("media/presets")) -> None
    # schema: type "retarget-map", category RIGGING; motion:NEUTRAL_ANIMATION in/out
    # params: mapping_preset STRING required; use_root_translation/foot_ik/scale_source_height/preserve_keyframes BOOL
    # validate: mapping_preset resolvable inside preset_root; bools typed; preset parses +
    #   RetargetMap.model_validate + validate_against(DEFAULT_NEUTRAL_SKELETON)
    # execute: _coerce_motion (migrate) → load preset → param overrides (node > preset > default)
    #   → asyncio.to_thread(retarget_motion)
```

Preset loader (`_resolve_preset_path`/`_load_preset`, mirroring `FrameExtractorNode._resolve_video_path`): reject absolute/`..`/non-str; `resolve()` + `is_relative_to(preset_root)` (symlink-safe); size cap `MAX_PRESET_BYTES = 262_144` BEFORE parse (billion-laughs); extensions `{.yaml,.yml,.json}` → `json.load`/`yaml.safe_load`; `yaml.YAMLError`/`JSONDecodeError`/`ValidationError` → invalid. `eval`/`exec`/`yaml.load|full_load|unsafe_load` never used.

## Testing Strategy (Strict TDD)

| Layer | What | Approach |
|---|---|---|
| Unit | quat.py: norm/short-arc/multiply/endpoints/nlerp | Unit-quat invariants + reference values |
| Unit | RetargetMap: well-formed, extra field (top+per-bone), unknown source bone, shorthand promotion | Model tests, `extra="forbid"` negatives |
| Unit | retarget_motion: height-ratio doubling, passthrough, determinism (run-twice byte-identical), invariants, child positions untouched, per-bone scale | Synthetic motions, mirror `test_inbetween.py` |
| Unit | rotation rigs: LOCAL offset, FBX→glTF forward flip (no backwards), identity-not-fabricated | Synthetic rigs with non-identity source |
| Unit | migration: 0.2→0.3 renames keys/parents/Bone.name/transforms+version; 0.3 passthrough; unknown version rejected; **`Root` not corrupted** | Legacy doc fixtures; naive-prefix regression |
| Infra | node: schema RIGGING/ports, execute e2e, validate rejects missing preset, coercion, to_thread | Mirror `test_temporal_cleanup.py` |
| Sec | loader: `../`, absolute, symlink escape, oversized, malformed YAML, no-eval static source scan | Negative tests + source inspection |
| Infra | registry 10 seeds incl. `retarget-map`; update 8/9-seed tests | Registry citizen test |

## Threat Matrix

Routing/shell/VCS/process rows: **N/A** — no such boundary in this change.

Preset ingestion (§4.2 new row, spec-mandated): threat = malicious YAML/JSON preset / path traversal / arbitrary code; severity **High**; control = `yaml.safe_load`/`json.load`, `extra="forbid"`, size cap before parse, preset-root allowlist + traversal rejection, no `eval`/`exec`; verification = no-eval static inspection + path-traversal/oversized/malformed tests (above — propagate verbatim to tasks).

## Migration / Rollout

Rename, ADR-001, version bump, and `migrate_neutral_motion` ship in one change. Producers (default `meta.version`) write 0.3 canonical; readers accept 0.2 (migrate) and 0.3. Sweep: skeleton_presets/mapping/cleanup/adapters/tests + `temporal-cleanup` spec wording. Rollback (proposal): revert rename + default; migration fn is inert for 0.3 docs; unregister node; restore `_quat_*`; `pytest`+import-linter green.

## Open Questions

- [ ] Target-rig definition: absent from graph (map_provider nil) — target-side bone existence stays rig-test-only until a target skeleton input exists.
- [ ] `target_root_to_ground_cm` is a spec-extension preset option (not a node param) — confirm before archive.
- [ ] PyYAML base-dep addition needs §3.2 soft-constraint sign-off.