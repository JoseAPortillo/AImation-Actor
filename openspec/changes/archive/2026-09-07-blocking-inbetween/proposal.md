# Proposal: Blocking → In-betweening (`blocking-inbetween`)

## Intent

Professional animators need to author key poses in a DCC and have the tool generate preserved-key in-betweens — the "most valuable flow" per plan §20.5. Today the `blocking-to-motion` endpoint is a stub, `keyposes` is declared but unused, and `_resample` treats every source frame equally with no locking semantics. This change delivers the functional blocking-to-motion pipeline end-to-end.

## Scope

### In Scope

- **Blocking input model**: lightweight DCC-friendly payload `{ skeleton (optional), keyposes: [{frame, pose, weight}] }` — decision D1b.
- **Converter**: blocking payload → `NeutralMotion` (sparse frames + populated `keyposes`).
- **`BlockingInput` node**: source node in core registry + React Flow palette; emits `NEUTRAL_ANIMATION` (no new DataType — D1b decision).
- **Keypose-preserving interpolation**: extend `inbetween-generation` with `preserve_keyposes` param + key-lock in `_resample` + keypose frame-index remap after resampling — decision D2a.
- **Graph path**: `BlockingInput → inbetween-generation` functional via in-request executor (ADR-002); no background worker.
- **"Blocking to Motion" preset** in `core/presets.ts` + SimpleMode.
- **SpecSecDev / threat model**: new entry for blocking input (pose/frame bounds, weight range, quaternion validity, NaN/Inf guard, payload size, eval-injection, `_resample` total on degenerate inputs) — decision D4.
- **Tests**: converter, key-lock interpolation, node registration, preset graph path, threat-model validation.

### Out of Scope (deferred post-v0.4)

- Foot lock / contact constraints (§11.3 step 8 is a distinct cleanup stage).
- Partial-weight keyposes affecting segment shape (start with `weight ≈ 1.0` exact-lock).
- Maya/DCC-side capture UI (plugin territory, v0.3+).
- `MotionEnhancer` generative pass (Phase 8).
- Background worker for blocking-to-motion (graph executor is in-request for MVP).

## Capabilities

### New Capabilities

- `blocking-input`: Blocking payload model, converter to `NeutralMotion`, `BlockingInput` source node, SpecSecDev validation.

### Modified Capabilities

- `inbetween-generation`: Add `preserve_keyposes` param, key-lock interpolation in `_resample`, keypose frame-index remap, degenerate-input safety.

## Approach

`BlockingInput` node accepts the lightweight payload, converts it to a sparse `NeutralMotion` with populated `keyposes`, and emits `NEUTRAL_ANIMATION`. The `inbetween-generation` node gains a `preserve_keyposes` boolean param; when true, `_resample` locks key frames to authored values/timing per weight and remaps `keypose` frame indices post-resample. A "Blocking to Motion" preset wires the two-node graph.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `domain/animation/neutral_motion.py` | Modified | Keypose validation in `validate_invariants` |
| `domain/animation/inbetween.py` | Modified | `InbetweenParams.preserve_keyposes`, `_resample` key-lock, remap |
| `domain/animation/` (new converter) | New | Blocking payload → `NeutralMotion` |
| `infrastructure/ai_models/blocking_input.py` | New | `BlockingInput` node adapter |
| `infrastructure/virtual/node_registry.py` | Modified | Register `BlockingInput` (10→11 seeds) |
| `tests/api/test_api.py` | Modified | Update seed-node allowlist assertion |
| `frontend/src/core/presets.ts` | Modified | "Blocking to Motion" preset |
| `frontend/src/api/types.ts` | Modified | `KeyPose` typed fields |
| Threat model / SpecSecDev §4.2 | New | Blocking-input threat entry (D4) |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Key-lock interpolation discontinuities (weights < 1, adjacent/duplicate keys) | High | Start with `weight ≈ 1.0` exact-lock; comprehensive edge-case tests |
| Keypose frame-index remap stale after resample | Medium | Ship remap as part of the same change; test round-trip |
| Scope creep into foot-lock / DCC capture | Medium | D3 partitioning; explicit out-of-scope list |
| 10→11 node allowlist test breakage | Low | Explicit test update in scope |

## Rollback Plan

Revert to 10-node registry, remove `blocking_input.py`, remove `preserve_keyposes` from `InbetweenParams`/`_resample`, remove preset. Existing inbetween-generation behavior is unchanged when `preserve_keyposes=False` (default). No data migration needed — `NeutralMotion.keyposes` field already exists.

## Dependencies

- Existing `inbetween-generation` node and `_resample` math (stable base).
- `NeutralMotion` immutable contract (ADR-001) — no schema change, only new producer.
- Graph executor in-request mode (ADR-002) — no background worker required.

## Success Criteria

- [ ] `BlockingInput` node registered, listed in palette, emits valid `NEUTRAL_ANIMATION`.
- [ ] Graph `BlockingInput → inbetween-generation` produces in-betweened motion preserving key values.
- [ ] Keypose frame indices remapped correctly after resampling.
- [ ] `_resample` total on degenerate inputs (1 key, duplicate keys, keys == every output frame).
- [ ] SpecSecDev threat entry covers all D4 attack surfaces.
- [ ] All tests pass including updated seed-node allowlist.
