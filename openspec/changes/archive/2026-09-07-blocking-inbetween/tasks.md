# Tasks: Blocking → In-betweening (`blocking-inbetween`)

REQ tags: PAYLOAD/CONVERT/KEY-LOCK/REMAP/DEGENERATE/ADAPTER/SCHEMA/SEED/CATALOG/PRESET/E2E/SECURITY/INVARIANT = blocking-input + inbetween-generation + node-registry specs.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~580–780 authored (P1 ~220, P2 ~130, P3 ~110, P4 ~80, P5 ~120 incl. ~100 tests) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | size:exception single PR (delivery_strategy = single-pr) |
| Delivery strategy | single-pr |
| Chain strategy | size-exception |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: size-exception
400-line budget risk: High

**Maintainer decision:** approve `size:exception` (~580–780 lines) before apply — domain model + key-lock math + adapter + registry + frontend golden cannot split below 400 without breaking converter→adapter→registry atomicity.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Domain model + converter + key-lock + remap | core PR | `pytest tests/domain/test_blocking_input.py tests/domain/test_inbetween.py -k "key_lock or remap or degenerate or blocking"` | N/A — pure domain math | Revert `blocking_input.py` + inbetween key-lock; `_resample` reverts to equal-weight |
| 2 | Adapter + registry + seed test | core PR | `pytest tests/ -k "blocking_input_node or registry or seed"` | N/A — async wrapper + registry | Revert adapter + registry seed |
| 3 | Frontend types + preset + golden | core PR | `npx vitest run` in `frontend/` | N/A — type mirror + fixture | Revert preset + golden fixture |
| 4 | E2E graph + threat model + SDD | core PR | `pytest tests/ -k "blocking_e2e or threat"` | Graph executor in-request | Revert threat tests + SDD row |

## Phase 1: Domain Model + Converter + Keypose Remap

- [x] 1.1 RED `tests/domain/test_blocking_input.py`: well-formed payload validates; unknown extra field rejected; empty keyposes rejected; skeleton mismatch rejected; weight out of range rejected; non-finite values rejected; zero-quaternion rejected; max keypose count bounded (REQ-01 SC-01–SC-06, REQ-04 SC-02/SC-03)
- [x] 1.2 GREEN `aimation_actor_core/domain/animation/blocking_input.py`: `BlockingKeyPose`/`BlockingInput` frozen models (`extra="forbid"`, `MAX_KEYPOSES=1000`, `EXACT_LOCK_MIN=0.99`) + `blocking_to_neutral_motion` converter (sparse frames sorted ascending, dup-frame reject, default skeleton, `meta.fps=24.0`, `duration_frames=max(frame)`, `validate_invariants()`) (PAYLOAD, REQ-01, REQ-02)
- [x] 1.3 RED `tests/domain/test_inbetween.py` additions: `preserve_keyposes` param exists; key-lock holds authored value at `weight=1.0`; off by default (existing byte-identical); off-grid snap to nearest in-grid frame (REQ-05 SC-01/SC-02, REQ-06 SC-01, REQ-07 SC-05)
- [x] 1.4 RED `tests/domain/test_inbetween.py` degenerate suite: 0 keys safe, 1 key safe (no div/0), duplicate keys collapsed, adjacent keys safe, keys==every output frame safe (REQ-07 SC-01–SC-04, D8)
- [x] 1.5 GREEN `aimation_actor_core/domain/animation/inbetween.py`: `InbetweenParams.preserve_keyposes: bool = False`; `_resample` key-lock for `weight∈[0.99,1.0]`; `_remap_keyposes` function (frame→nearest in-grid output frame); `enrich_motion` chains resample→rotation filter (skip locked)→tangent smooth (skip locked)→`_remap_keyposes`→`validate_invariants()` (KEY-LOCK, REMAP, DEGENERATE, D5, D9)
- [x] 1.6 GREEN `aimation_actor_core/domain/animation/neutral_motion.py` `validate_invariants`: add keypose frame-within-duration check (INVARIANT)
- [x] 1.7 `aimation_actor_core/domain/animation/__init__.py`: re-export `BlockingInput`, `BlockingKeyPose`, `blocking_to_neutral_motion`, `EXACT_LOCK_MIN`

## Phase 2: Adapter + Registry + Seed Allowlist

- [x] 2.1 RED `tests/infrastructure/test_blocking_input.py`: schema `SOURCE` + `motion:NEUTRAL_ANIMATION` output; validate rejects invalid payload; execute emits valid `NeutralMotion` with invariants; deterministic (same payload → byte-identical output) (REQ-03 SC-01–SC-04)
- [x] 2.2 GREEN `aimation_actor_core/infrastructure/ai_models/blocking_input.py`: `BlockingInputNode(INode)` — `get_schema` (type `blocking-input`, category `SOURCE`, params `[PortSpec("blocking", STRING, required=True)]`), `validate` (parse JSON → `BlockingInput.model_validate`), `execute` (`params["blocking"]` → converter → `to_thread` → `NodeOutput({"motion":})`) (ADAPTER, REQ-03)
- [x] 2.3 GREEN `aimation_actor_core/infrastructure/ai_models/inbetween_generation.py`: add `preserve_keyposes` `PortSpec` (BOOLEAN, default False) in `get_schema` params; pass through in `validate` (must be bool) and `execute` → `InbetweenParams(preserve_keyposes=...)` (SCHEMA)
- [x] 2.4 `aimation_actor_core/infrastructure/ai_models/__init__.py`: re-export `BlockingInputNode`
- [x] 2.5 RED `tests/infrastructure/test_node_registry.py`: 11 seeds present; `blocking-input` is `SOURCE` with `motion: NEUTRAL_ANIMATION` output; all seed schemas have typed ports (node-registry spec scenarios)
- [x] 2.6 GREEN `aimation_actor_core/infrastructure/virtual/node_registry.py`: import + `registry.register(BlockingInputNode())` 11th seed; docstring 10→11 (SEED)
- [x] 2.7 `tests/api/test_api.py` `test_list_node_types_lists_seed_nodes`: add `"blocking-input"` to the 11-node assertion set (SEED)

## Phase 3: Frontend Types + Preset + Golden

- [x] 3.1 `frontend/src/api/types.ts`: add typed `KeyPose` interface (`{ frame: number; weight: number }`); change `keyposes?: unknown[]` → `keyposes?: KeyPose[]`
- [x] 3.2 `frontend/src/core/presets.ts`: add `blockingToMotionPreset()` — two-node graph (`blocking-input` → `inbetween-generation` with `preserve_keyposes: true`, `target_fps: 30`); add to `presets()` array (PRESET)
- [x] 3.3 RED `frontend/src/test/presets.test.ts`: new preset exists, correct id, two nodes, `preserve_keyposes: true` in inbetween params, two edges wired (CATALOG)
- [x] 3.4 `frontend/src/test/fixtures/nodeCatalog.json`: append `blocking-input` golden entry — `SOURCE` category, `motion:NEUTRAL_ANIMATION` output, params `[blocking]` (CATALOG)
- [x] 3.5 `npx vitest run` in `frontend/` — fixture drift test green

## Phase 4: Integration E2E + Threat Model + Docs

- [x] 4.1 RED `tests/infrastructure/test_blocking_e2e.py`: graph `blocking-input → inbetween-generation` (preserve_keyposes=true) via `SynchronousGraphExecutor` → valid `NeutralMotion` with preserved key values at locked frames + remapped keypose indices (E2E)
- [x] 4.2 RED `tests/infrastructure/test_blocking_input.py` threat suite: oversized payload rejected at API boundary; max keypose count bounded; no `eval`/`exec` in adapter source (static inspection); non-finite / non-unit-norm quaternion / all-zero quaternion rejected (SECURITY, REQ-04)
- [x] 4.3 RED `tests/domain/test_inbetween.py` threat suite: `_resample` total on 0/1 keys, duplicate keys, adjacent keys, keys===every output frame, off-grid keys — never crash/non-finite (SECURITY, D4)
- [x] 4.4 `docs/SDD.md` §4.2 table: add `Blocking input (blocking-input, SOURCE; preserve_keyposes key-lock in inbetween-generation, ENRICHMENT)` row — High — bounded keypose count + frame-within-duration + weight [0,1] + quat unit-norm/all-zero reject + finite check + payload size cap + static registry + `_resample` total — no-eval scan + threat-model tests + degenerate tests + oversized-payload test (SECURITY)
- [x] 4.5 `.\\.venv\\Scripts\\python.exe -m pytest` full suite green
- [x] 4.6 `npx vitest run` in `frontend/` green — fixture no drift

## Apply Notes (deviation log — recorded during apply, 2026-09-07)

- **2.1/4.2 file rename:** adapter tests live in 	ests/infrastructure/test_blocking_input_node.py (not 	est_blocking_input.py) — the basename collided with 	ests/domain/test_blocking_input.py under pytest's module-name matching.
- **3.3 test path:** presets tests live in rontend/src/core/presets.test.ts (not rontend/src/test/presets.test.ts, which does not exist).
- **4.2 scope note:** the threat suite added MAX_BLOCKING_PAYLOAD_CHARS (4M chars) + BlockingPayloadError to the adapter — a byte/char size cap enforced *before* json.loads, matching the SDD §4.2 row added in 4.4. Only 2 of the 6 threat tests were RED (oversize cap); the rest verify pre-existing domain guards.
- **4.3 contract discovery:** _resample is upsample-only (	est_no_downsample_passthrough), so downsample key-collisions are unreachable through nrich_motion. The degenerate suite was extended with equal-fps passthrough (all keys locked) + off-grid full-pipeline tests instead; the `n_out <= n_in` branch of the key-lock math is exercised only in its identity form.
- **Full-suite result:** with a fresh pytest --basetemp, the ENTIRE backend suite passes (560 passed, 2 skipped) — including 	ests/infrastructure/test_retarget_map.py (the previously reported 45 errors and 1 env error were the Windows stale-tempdir PermissionError [WinError 5] on C:\Users\josea\AppData\Local\Temp\pytest-of-josea, not code).
