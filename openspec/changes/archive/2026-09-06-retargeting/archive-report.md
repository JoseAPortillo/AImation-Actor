# Archive Report — §14 Retargeting

## Summary

**Change**: `retargeting` (§14 Retargeting)  
**Archived**: 2026-09-06  
**Branch**: `feat/retargeting` (12 commits, HEAD `9527adc`)  
**Status**: ✅ COMPLETE — 35/35 tasks, verify PASS (7/7 req, 27/27 scenarios, 0 CRITICAL)

## What was delivered

### Domain
- **ADR-001** (`docs/adr/001-neutral-bone-names.md`): canonical `Left…/Right…` bone rename + `NeutralMotion` migration `meta.version` 0.2→0.3
- **`domain/retargeting/`**: `map.py` (RetargetMap Pydantic model, frozen, `extra="forbid"`), `retarget.py` (position/scale remap, height-ratio root scaling, foot_ik ground pass), `rotation.py` (LOCAL rotation offset, axis correction, FBX↔glTF forward-axis handling)
- **`domain/animation/quat.py`**: promoted quaternion helpers (slerp, quat_dot, quat_negate, quat_normalize, quat_multiply) — reused by inbetween + retargeting
- **Migration**: `migrate_neutral_motion()` at coercion boundaries, explicit 16-entry rename map (naive prefix rewrite forbidden — `Root` never corrupted)

### Infrastructure
- **`infrastructure/ai_models/retarget_map.py`**: RetargetMapNode adapter (RIGGING, NEUTRAL_ANIMATION in/out), safe preset loader (allowlist `media/presets/`, 262 KiB size cap before parse, `yaml.safe_load`/`json.loads`, path-traversal + symlink-escape rejection, `extra="forbid"`, no eval/exec)
- **`media/presets/identity.yaml`**: example preset (22-bone self-map)
- **10th seed**: `retarget-map` registered in `node_registry.py`

### Frontend
- **`nodeCatalog.json`**: golden entry for retarget-map (10th seed, RIGGING, motion ports, 5 params)

### Dependencies
- **`pyproject.toml`**: `pyyaml>=6.0` (base), `types-PyYAML` (dev) — maintainer-approved soft constraint §3.2 (infra-only, MIT license)

### Documentation
- **Threat-model row §4.2**: Retarget presets (malicious YAML/JSON, path traversal, arbitrary code) — High severity, controls: safe_load, extra="forbid", size cap, allowlist, no eval
- **Spec wording**: temporal-cleanup contact wording aligned with ADR-001 (LFoot→LeftFoot)

## Verification

### Test counts
- **Backend**: 494 passed / 2 skipped (exit 0)
- **Frontend**: 123 passed / 22 files (exit 0)
- **Lint**: ruff clean (committed scope), mypy 60 files clean, import-linter 4/4 contracts kept
- **Coverage**: pytest-cov not installed (informational only)

### Requirements / Scenarios
- **retargeting spec**: 6 requirements, 22 scenarios — ALL PASS
- **node-registry delta**: 1 requirement (MODIFIED), 5 scenarios — ALL PASS
- **Total**: 7 requirements, 27 scenarios — 100% compliant

### Security
- ✅ `yaml.safe_load`/`json.loads` only (no eval/exec reachable)
- ✅ Size cap 262 KiB before parse (billion-laughs defense)
- ✅ Path allowlist + traversal rejection (absolute, `..`, symlink-escape)
- ✅ Pydantic `extra="forbid"` + unknown-bone rejection
- ✅ Migration safety: 0.2→0.3 canonical, unknown versions → `UnsupportedNeutralVersionError`

## Maintainer sign-offs

1. **WARNING 1 RESOLVED**: `target_root_to_ground_cm` spec-extension option ADOPTED (implemented, tested, verified)
2. **WARNING 2 RESOLVED**: target-rig validation deferral ACCEPTED as MVP scope (map_provider nil until target skeleton input exists; rig tests cover it)
3. **WARNING 3 RESOLVED**: PyYAML §3.2 soft-constraint sign-off RECORDED (maintainer explicitly approved `pyyaml>=6.0` infra-only after reviewing consequences)
4. **size:exception APPROVED**: ~850–1050 lines, single PR (exceeds 400-line budget; migration atomicity prevents clean split)

## Observations (non-blocking)

### Strict-TDD deviations
- **2.9/2.10 ordering**: rotation tests ran before retarget_motion GREEN (necessary because retarget_motion consumes apply_rotation)
- **3.3 approval-style RED**: rationale documented
- **3.6 +2 seed files**: `test_api.py` included alongside registry tests
- **4.5 pyproject early**: dependency added before adapter implementation

All deviations documented in apply-progress, non-breaking, and verified not to compromise spec compliance.

## Future work (SUGGESTIONs)

- **pytest-cov**: add coverage tooling to track test coverage
- **Scratch cleanup**: remove/relocate untracked `test_inbetween.py` + `media/` test artifacts
- **Keypose/contacts contract**: add name-references test for future producers
- **SEED_NODE_IDS constant**: extract shared constant for seed node IDs

## Delivery state

- **Branch**: `feat/retargeting` @ `9527adc`
- **Commits**: 12 (4 foundation + 8 implementation + verify report)
- **PR**: pending (single-pr, size:exception)
- **Merge target**: `feat/Develop`

## Artifacts

- `openspec/changes/archive/2026-09-06-retargeting/` — all change artifacts (proposal, specs/, design, tasks, apply-progress, verify-report, archive-report)
- `openspec/specs/retargeting/spec.md` — live spec (6 req, 22 scenarios)
- `openspec/specs/node-registry/spec.md` — updated (9→10 seeds)
- `docs/adr/001-neutral-bone-names.md` — ADR-001
- Engram: `sdd/retargeting/*` (explore, research, proposal, spec, design, tasks, apply-progress, verify-report, archive-report)
