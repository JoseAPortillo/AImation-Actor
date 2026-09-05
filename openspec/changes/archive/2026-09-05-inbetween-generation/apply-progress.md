# Apply Progress — In-Between Generation and Enrichment (§12.5)

Change: `inbetween-generation`
Slices recorded: **PR1** (Phase 1, tasks 1.1–1.7), **PR2** (Phase 2, tasks 2.1–2.7), **PR3** (Phase 3, tasks 3.1–3.2 + dependency task 4.1) and **PR4** (Phase 4, tasks 4.2–4.5 + Phases 5–6) — feature-branch-chain, slices 1–4 of 4
Mode: **Strict TDD** (openspec/config.yaml `apply.tdd: true`)
Store: hybrid (openspec file + Engram observation)
Test runner: `.venv\Scripts\python.exe -m pytest --basetemp %TEMP%\opencode\pytest-basetemp` (user `%TEMP%\pytest-of-josea` corrupt)

## Scope of this batch (COMPLETE)

Phase 1 — Domain Timing Math (params, resample, easing). Tasks 1.1–1.7 all done.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `tests/domain/test_inbetween.py` | Unit | N/A (new) | ✅ Written (ImportError) | ✅ 10 cases pass | ✅ 4-param/reject sets | ✅ Clean |
| 1.2 | `tests/domain/test_inbetween.py` | Unit | N/A (new) | ✅ Written | ✅ 16 pass | ✅ 4 valid + defaults | ✅ Clean |
| 1.3 | `tests/domain/test_inbetween.py` | Unit | N/A (new) | ✅ Written (ImportError `_resample`) | ✅ 7 pass | ✅ 3→5, 4-key, C1/C0 | ✅ Clean |
| 1.4 | `tests/domain/test_inbetween.py` | Unit | N/A (new) | ✅ Written | ✅ pass | ✅ 7 cases | ✅ Extracted tangents/hermite |
| 1.5 | `tests/domain/test_inbetween.py` | Unit | N/A (new) | ✅ Written (ImportError `_ease`) | ✅ 5 pass | ✅ 3 curves + none | ✅ Clean |
| 1.6 | `tests/domain/test_inbetween.py` | Unit | N/A (new) | ✅ Written | ✅ pass | ✅ fused `u=ease(ξ)` | ✅ Clean |
| 1.7 | — (re-export) | — | N/A | — | ✅ import smoke | ➖ Single | ✅ Clean |

**Triangulation note**: 1.2 (pure dataclass validation) has multiple branches -> triangulated with parametrized invalid sets; 1.7 is a structural re-export -> tracked in 1.1's import smoke, no separate file.

## Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command & result | `.\.venv\Scripts\python.exe -m pytest tests/domain/test_inbetween.py -v --basetemp C:\Users\josea\AppData\Local\Temp\opencode\pytest-basetemp` → **29 passed** |
| Runtime harness command & result | N/A — pure domain math, no runtime/IO boundary (resampler is pure stdlib) |
| Rollback boundary | Revert PR1 slice: delete `aimation_actor_core/domain/animation/inbetween.py`, revert `aimation_actor_core/domain/animation/__init__.py`, delete `tests/domain/test_inbetween.py`. No callers yet (`enrich_motion` ships in PR2). |

## Verification (gate)

1. `.\.venv\Scripts\python.exe -m pytest tests/domain/test_inbetween.py -v --basetemp C:\Users\josea\AppData\Local\Temp\opencode\pytest-basetemp` → **29 passed**
2. Full suite: `.\.venv\Scripts\python.exe -m pytest --basetemp C:\Users\josea\AppData\Local\Temp\opencode\pytest-basetemp` → **330 passed, 2 skipped** (no regression)
3. `ruff check` on touched files → **All checks passed**; `mypy --strict` on touched files → **Success: no issues found**
4. `lint-imports` → **4 contracts kept, 0 broken** (domain is pure; no numpy imported — grep for `from numpy|import numpy` in `inbetween.py` → 0 matches)

## Completed Tasks (cumulative)

- [x] 1.1 RED `tests/domain/test_inbetween.py`: enums `spline`/`bounce`, smoothing 1.5/-0.1, fps 0/-30 → `ValueError`; defaults valid (VALIDATE)
- [x] 1.2 GREEN `aimation_actor_core/domain/animation/inbetween.py`: frozen `InbetweenParams` + `__post_init__` + `DEFAULT_*` (VALIDATE)
- [x] 1.3 RED: 30fps/3fr→60fps/5fr, keys exact, first/last equal, cubic C1 vs linear C0; fps⩽fps and 1-frame passthrough; meta updated (RESAMPLE)
- [x] 1.4 GREEN `_resample`: Hermite basis + Catmull-Rom tangents, one-sided ends, linear mode; upsample-only (RESAMPLE)
- [x] 1.5 RED: ease-in/out half-asymmetry, in-out midpoint peak, monotonic f(0)=0 f(1)=1 (EASING)
- [x] 1.6 GREEN: `t²`, `1-(1-t)²`, `3t²-2t³` fused `u=ease(ξ)` in `_resample` (EASING)
- [x] 1.7 Re-export `InbetweenParams` in `aimation_actor_core/domain/animation/__init__.py`

## Slice 2 (PR2) — Phase 2, tasks 2.1–2.7 (COMPLETE)

Phase 2 — Domain Trajectory Math (rotation filter, tangent smoothing, enrichment pipeline). Tasks 2.1–2.7 all done.

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.1 | `tests/domain/test_inbetween.py` | Unit | ✅ 29 pass (PR1) | ✅ Written (ImportError `_apply_rotation_filter`/`_slerp`) | ✅ 6 pass | ✅ shortest-arc 60°, antipodal nlerp, resample composition | ✅ Clean |
| 2.2 | `tests/domain/test_inbetween.py` | Unit | ✅ 29 pass | ✅ (—) | ✅ 35 pass | ✅ pre+post canonicalize; `_slerp` fused into `_resample` | ✅ Clean |
| 2.3 | `tests/domain/test_inbetween.py` | Unit | ✅ 35 pass | ✅ Written (ImportError `_apply_tangent_smooth`) | ✅ metric iteration | ✅ tangent (first-difference) variance; jittered axes | ✅ Clean |
| 2.4 | `tests/domain/test_inbetween.py` | Unit | ✅ 35 pass | ✅ (—) | ✅ odd-window box | ✅ dense 100×100 grid, 0 violations; windows 3/5/7/9 | ✅ Clean |
| 2.5 | `tests/domain/test_inbetween.py` | Unit | ✅ 41 pass | ✅ Written (ImportError `enrich_motion`) | ✅ 7 pass | ✅ byte-identical rerun, stage-spy order | ✅ Clean |
| 2.6 | `tests/domain/test_inbetween.py` | Unit | ✅ 41 pass (RED: collection error) | ✅ (—) | ✅ 48 pass | ✅ order+determinism+invariants+passthrough | ✅ Clean |
| 2.7 | — (re-export) | — | ✅ 48 pass | — | ✅ import smoke (`__all__` size 27) | ➖ Single | ✅ Clean |

**Triangulation note**: 2.3's original metric (raw position variance) failed the design guarantee — SMOOTH is defined over the trajectory **tangents** (first differences): "per-joint variance does not increase" == tangent-track variance. Even-width centered boxes are asymmetric and broke monotonicity in the differenced domain, so windows round down to the nearest odd width (centered boxes are odd by nature). Verified over a dense 100×100 intensity-pair grid × 3 axes: **0 monotonicity violations**.

### Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command & result | `.\.venv\Scripts\python.exe -m pytest tests/domain/test_inbetween.py -v --basetemp C:\Users\josea\AppData\Local\Temp\opencode\pytest-basetemp` → **48 passed** (29 PR1 + 6 ROT + 6 SMOOTH + 7 ORDER) |
| Runtime harness command & result | N/A — pure domain math, no runtime/IO boundary (stdlib only) |
| Rollback boundary | Revert PR2 slice: `git revert` of the PR2 commit(s) on `feat/inbetween-generation-pr2` (restores `inbetween.py`, `__init__.py`, `test_inbetween.py` to PR1 state `4bdb3c0`). PR1 intact; no callers yet — adapter ships in PR3. |

### Verification (gate)

1. Focused → **48 passed**
2. Full suite → **349 passed, 2 skipped** (PR1 baseline 330+2; +19 new, no regression)
3. `ruff check` on touched files → **All checks passed**; `mypy --strict` on touched files → **Success: no issues found**
4. `lint-imports` → **4 contracts kept, 0 broken**; numpy/scipy grep in `inbetween.py` → 0 import matches (guardrail comments only)
5. Dense-grid SMOOTH monotonicity (100×100 intensity pairs × 3 axes) → **0 violations**

### Completed Tasks (cumulative, this slice)

- [x] 2.1 RED: q/-q → positive dot; shortest arc = canonicalized slerp; disabled passthrough; near-antipodal nlerp no-NaN (ROT)
- [x] 2.2 GREEN `_apply_rotation_filter`: sign canonicalization on resampled seq, slerp flips far endpoint, nlerp if `|dot|>1-1e-6`/`sinθ<1e-6`; **canonicalize pre+post interpolation** (ROT)
- [x] 2.3 RED: identity at 0; translation variance non-increasing for a<b in (0,1] (SMOOTH)
- [x] 2.4 GREEN `_apply_tangent_smooth`: centered box `1+round(intensity*9)`; **translation axes only, rotations untouched** (SMOOTH)
- [x] 2.5 RED: stage-spy order, run-twice byte-identical, invariants; new frames `confidence=None`; **`tracking`/`contacts`/`keyposes` passthrough (MVP)** (ORDER)
- [x] 2.6 GREEN `enrich_motion`: resample→ease→rotation→smooth, meta updated, `validate_invariants()` last (ORDER)
- [x] 2.7 Re-export `enrich_motion` in `aimation_actor_core/domain/animation/__init__.py`

## Slice 3 (PR3) — Phase 3 adapter + Phase 4 task 4.1 (COMPLETE)

Phase 3 — INode Adapter (tasks 3.1–3.2) plus dependency-handled task 4.1. Tasks 3.1–3.2 and 4.1 all done.

**Dependency note (as instructed)**: `NodeCategory.ENRICHMENT` did NOT exist in `schema.py` (it is task 4.1, Phase 4). Neither 3.1 nor 3.2 could compile without that additive member, so 4.1 was implemented inside this slice as its own work-unit commit (`ef91edb`) with a mini test (`test_node_category_enrichment_member`). Nothing else from Phase 4 was implemented — registry 9th seed, seed counts 8→9, and re-exports remain for slice 4/PR4.

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 4.1 | `tests/domain/test_pipeline.py` | Unit | ✅ 8 pass | ✅ Written → AttributeError (verified by stashing schema edit) | ✅ 1 pass | ➖ Single (additive enum member) | ✅ Clean |
| 3.1 | `tests/infrastructure/test_inbetween_generation.py` | Unit | ✅ 349+2 (PR2) | ✅ Written → ModuleNotFoundError | ✅ 15 pass | ✅ 15 cases (schema 5, execute 3, validate 7) | ✅ Clean |
| 3.2 | (same file, GREEN side) | Unit | ✅ 15 pass | ✅ (—) | ✅ 15 pass | ✅ covers all VALIDATE scenarios | ✅ Clean |

**Triangulation note**: validate scenarios cover both bad-value rejection (invalid enums `spline`/`bounce`, out-of-range `tangent_smoothing` 1.5/−0.1, non-positive `target_fps` 0/−30, bool-as-number, non-bool `euler_filter`) AND valid-params acceptance plus empty/defaults — so each rejection path is triangulated against a passing path. Execute is triangulated across NeutralMotion object input, raw dict (job-store serialized) coercion, and the `asyncio.to_thread` mock that asserts the offloaded function is `enrich_motion`.

### Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command & result | `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/test_inbetween_generation.py -v --basetemp C:\Users\josea\AppData\Local\Temp\opencode\pytest-basetemp` → **15 passed** |
| Runtime harness command & result | N/A — adapter is an async wrapper with no IO boundary (runtime is pure in-memory math; `asyncio.to_thread` verified via the monkeypatched mock asserting the offloaded callable is `enrich_motion`) |
| Rollback boundary | Revert PR3 slice: `git revert` of `ef91edb` + the adapter commit on `feat/inbetween-generation-pr3` (restores `schema.py`, `test_pipeline.py`, removes `inbetween_generation.py` + `test_inbetween_generation.py`). PR1/PR2 intact; the adapter has no registry/catalog callers yet — wiring ships in PR4. |

### Verification (gate)

1. Focused → **15 passed**
2. Full suite → **365 passed, 2 skipped** (PR2 baseline 349+2; +16 new — 15 adapter + 1 schema — no regression)
3. `ruff check` on touched files → **All checks passed**; `ruff format --check` → clean; `mypy --strict` on touched files → **Success: no issues found in 2 source files**
4. `lint-imports` → **4 contracts kept, 0 broken**

### Completed Tasks (cumulative, this slice)

- [x] 3.1 RED `tests/infrastructure/test_inbetween_generation.py`: type `inbetween-generation`, ENRICHMENT, **explicit ports `motion: NEUTRAL_ANIMATION`→`motion: NEUTRAL_ANIMATION`**, 5 params+defaults, execute `to_thread`→NeutralMotion, validate rejects bad enum/range/fps/bool (VALIDATE)
- [x] 3.2 GREEN `aimation_actor_core/infrastructure/ai_models/inbetween_generation.py`: `InbetweenGenerationNode(INode)` — schema, coercion, execute, validate; mirrors `TemporalCleanupNode` (VALIDATE)
- [x] 4.1 `aimation_actor_core/domain/pipeline/schema.py`: additive `NodeCategory.ENRICHMENT = "enrichment"` (SEED) — pulled into this slice per dependency note

## Slice 4 (PR4) — Phase 4 remainder + Phases 5–6 (COMPLETE — apply complete)

Phase 4 registry wiring + seed counts (4.2–4.5), Phase 5 frontend TS sync + golden (5.1–5.4), Phase 6 integration verify (6.1–6.5). All tasks done; 6.5 threat-model entry applied, Security Champion sign-off pending (human gate).

### TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 4.2 | `tests/infrastructure/test_inbetween_generation_registry.py` | Infra | ✅ 365+2 (PR3) | ✅ Written → 4 failed (KeyError / unknown node type) | ✅ 4 pass | ✅ 9 seeds, ports, category, DAG 4 cases | ✅ Clean (ruff format) |
| 4.3 | (same file, GREEN side) | Infra | ✅ 4 pass | ✅ (—) | ✅ 4 pass | ✅ registry + docstring 8→9 | ✅ Import sorted (ruff I001) |
| 4.4 | — (re-export) | — | ✅ 4 pass | — | ✅ import smoke `InbetweenGenerationNode` | ➖ Single | ✅ `__all__` sorted |
| 4.5 | `test_executor.py`, `test_temporal_cleanup_registry.py`, `test_api.py` | Infra | ✅ 27 pass (31 incl. api) | ✅ (count mismatch RED) | ✅ 31 pass | ✅ seed sets 8→9 in 3 files | ✅ Clean |
| 5.1 | — (TS union) | — | ✅ `npm test` baseline | — | ✅ tsc/vitest green | ➖ Single | ✅ Clean |
| 5.2 | — (handles map) | — | ✅ 123 pass | — | ✅ 123 pass | ➖ Single (Record member) | ✅ Clean |
| 5.3 | — (palette) | — | ✅ 123 pass | — | ✅ 123 pass | ➖ Single (label/order) | ✅ Clean |
| 5.4 | — (golden fixture) | — | `npm test` | — | ✅ 123 pass | ✅ full catalog shape exercised | ✅ No drift |
| 6.1–6.5 | full suite + greps + DAG | — | ✅ 369+2 | — | ✅ see verification gate | — | — |

**Triangulation note**: 4.2/4.3 triangulate across three registry citizenship aspects (9-seed set equality, ENRICHMENT category, NEUTRAL_ANIMATION ports) plus a 6-node connected DAG (`test_enrichment_chain_is_valid_connected_graph`) — the set-equality test would not catch a node registered under the wrong category or wrong ports, so the category/port assertions stand alone. 4.5 is triangulated across three independent seed-set assertions (executor registry, cleanup-registry, API `/nodes/types`), guarding the count from three different layers. 5.4's fixture is exercised by the existing catalog consumers (`schema.test.ts`, `roundtrip.test.ts`, properties/flow-canvas/graph-io tests) whose 123-test suite passes untouched — no drift.

### Work Unit Evidence

| Evidence | Value |
|---|---|
| Focused test command & result | `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/test_inbetween_generation_registry.py -v --basetemp C:\Users\josea\AppData\Local\Temp\opencode\pytest-basetemp` → **4 passed**; updated seed-set files: `test_executor.py + test_temporal_cleanup_registry.py + test_api.py` → **31 passed** |
| Runtime harness command & result | `npm test` (frontend, vitest + MSW fixture) → **123 passed / 22 files** — runtime catalog path (`GET /nodes/types` → palette) exercised via the golden fixture; backend `/nodes/types` covered by `test_api.py::test_list_node_types_lists_seed_nodes` in the full suite |
| Rollback boundary | Revert PR4: `git revert` of the PR4 commits (`3ef2cda`, `1d03f62`, `43342e8`, docs commit) on `feat/inbetween-generation-pr4` (restores registry to 8 seeds, TS union, palette, and fixture to pre-enrichment state). PR1/PR2/PR3 intact; the adapter stays but loses its registry/catalog presence. `media/`, `.atl/*` never committed. |

### Verification (gate)

1. Full backend suite → **369 passed, 2 skipped** (PR3 baseline 365+2; +4 new registry tests, no regression) — command `6.1`
2. `npm test` in `frontend/` → **123 passed (22 files)** — fixture without drift — command `6.3`
3. numpy guardrail → grep `import numpy|from numpy` in `aimation_actor_core/domain/` → **0 matches** — `6.2`
4. DAG `video-source→pose-2d→pose-3d→video-to-motion→temporal-cleanup→inbetween-generation` → **valid connected graph** (`test_enrichment_chain_is_valid_connected_graph` PASSED) — `6.4`
5. `ruff check` on touched files → **All checks passed**; `ruff format --check` → **5 files already formatted**; `mypy --strict` on touched files → **Success: no issues found in 5 source files**; `lint-imports` → **4 contracts kept, 0 broken**
6. **6.5 §3.2**: threat-model entry applied in repo — new row `Enrichment Nodes (inbetween-generation, ENRICHMENT category)` added to `docs/SDD.md` §4.2 Primary Threat Model (threat: malformed params / unbounded work; severity Low; controls: node `validate()` before execute, static allowlist registration SDD §4.3, pure in-memory stdlib math no IO, `asyncio.to_thread`; verification: invalid-param rejection tests, registry citizenship tests, DAG connection validation). **Security Champion sign-off is a human gate — PENDING maintainer before archive; does not block this slice.**

### Completed Tasks (cumulative, this slice)

- [x] 4.2 RED `tests/infrastructure/test_inbetween_generation_registry.py`: 9 seeds, ENRICHMENT, NEUTRAL_ANIMATION ports (SEED)
- [x] 4.3 GREEN `aimation_actor_core/infrastructure/virtual/node_registry.py`: register 9th seed after temporal-cleanup; docstring 8→9 (SEED)
- [x] 4.4 Re-export `InbetweenGenerationNode` in `aimation_actor_core/infrastructure/ai_models/__init__.py`
- [x] 4.5 Seed sets 8→9: `tests/infrastructure/test_executor.py`, `tests/infrastructure/test_temporal_cleanup_registry.py`, `tests/api/test_api.py` (SEED)
- [x] 5.1 `frontend/src/api/types.ts`: `NodeCategory` += `"enrichment"` (SEED)
- [x] 5.2 `frontend/src/core/handles.ts`: `CATEGORY_COLORS` += enrichment (SEED)
- [x] 5.3 `frontend/src/components/palette/Palette.tsx`: `CATEGORY_LABEL` + `CATEGORY_ORDER` after "cleanup" (SEED)
- [x] 5.4 `frontend/src/test/fixtures/nodeCatalog.json`: golden entry — `enrichment` category, motion ports, 5 params (SEED)
- [x] 6.1 `.\.venv\Scripts\python.exe -m pytest` full suite green
- [x] 6.2 Grep `import numpy|from numpy` in `aimation_actor_core/domain/` → zero matches
- [x] 6.3 `npm test` in `frontend/` green — fixture no drift
- [x] 6.4 Chain `video-source→pose-2d→pose-3d→video-to-motion→temporal-cleanup→inbetween-generation` valid DAG (SEED)
- [x] 6.5 §3.2: threat-model entry applied (docs/SDD.md §4.2 row); **Security Champion sign-off PENDING — human gate, recorded for maintainer before archive**

## Next / Resume Point (FINAL)

- **Apply COMPLETE**: all tasks 1.1–6.5 done. Change is at the verify/archive boundary. **Blocking pre-archive gate: Security Champion sign-off for the new ENRICHMENT node category (§3.2)** — maintainer action, documented above.
- Next: `sdd-verify` (upon orchestrator confirmation), then PR4 open on `feat/inbetween-generation-pr4` (targets `feat/inbetween-generation-pr3`), then archive once sign-off is recorded.

## Deviations from Design (PR1 — slice 1)

None — implementation matches `design.md`. Notes on interpretation:
- `_resample` computes `n_out = int(span * target_fps) + 1` with `span = (n_in-1)/meta.fps`; output grid starts at the first source frame's `time`, aligning snapped fences so every source key value lands at its timeline position.
- Easing is fused at `u = _ease(local, easing)` inside the per-interval evaluation (`_interp_value`), per design "`u=ease(ξ)` inside resample".
- New frames get `confidence=None`; rotation/scale copied per bone; `contact`s/keyposes/tracking untouched (pass-through, MVP), consistent with design.

## Deviations from Design (PR2 — slice 2)

None — implementation matches `design.md`. Notes on interpretation:
- PR1's `_resample` rotation stub (copy frame-0 rotation) is replaced by true slerp between bracketing source frames; slerp flips the far endpoint when `dot(q0,q1) < 0` and falls back to nlerp near-antipodal (`|dot| > 1 - 1e-6`, `sinθ < 1e-6`).
- SMOOTH guarantee is measured on first-difference (tangent) variance; window is `1 + round(intensity*9)`, even results rounded down to the nearest odd width; edge frames repeat the edge sample so every output is the mean of exactly `window` inbound samples.
- `enrich_motion(motion, params=None)` is stateless/deterministic; `params or InbetweenParams()`; `validate_invariants()` runs last, so the returned document always satisfies the neutral-motion invariants; `contacts`/`keyposes`/`tracking` pass through unmodified (MVP).

## Deviations from Design (PR3 — slice 3)

None — implementation matches `design.md`. Notes on interpretation:
- Task 4.1 (additive `NodeCategory.ENRICHMENT = "enrichment"`) was pulled into this slice because 3.1/3.2 cannot compile without it (explicit dependency handle per the apply brief); it ships as its own work-unit commit `ef91edb`. The member is placed after `CLEANUP` in the enum (palette order insertion "after cleanup" per task 5.3).
- `execute` coercion mirrors `TemporalCleanupNode` exactly: `str()`/`float()`/`bool()` on the raw params with DEFAULT_* fallbacks, relying on validate-before-execute; `InbetweenParams.__post_init__` re-validates as the final defense even if validate were bypassed.
- The `PortSpec.default` for the two NUMBER params is the domain float (`30.0`, `0.0`); the STRING defaults use the domain constants (`"cubic"`, `"none"`), keeping the adapter and domain defaults in lockstep.

## Deviations from Design (PR4 — slice 4)

None — implementation matches `design.md`. Notes on interpretation:
- Registry registration order: `InbetweenGenerationNode()` is registered immediately after `TemporalCleanupNode()` (spec: "after temporal-cleanup"); docstring updated to "nine seeds total".
- New category color `enrichment: "#0ea5e9"` (sky-500) — distinct from cleanup (`#059669` emerald) and ai (`#7c3aed` violet); design specifies only that the color map gains the member, not the value.
- The fixture entry mirrors the adapter's `PortSpec` defaults exactly (defaults `"cubic"`, `30.0`, `"none"`, `true`, `0.0`) so the golden stays in lockstep with the backend `/nodes/types` output.
- 6.5: the §3.2 threat-model entry was applied to the repo (`docs/SDD.md` §4.2 — new Low-severity row for ENRICHMENT nodes: malformed params / unbounded work, controls = validate-before-execute, static allowlist SDD §4.3, pure stdlib no IO, `asyncio.to_thread`). The Security Champion sign-off is a human gate and is recorded as PENDING for the maintainer — it does not block this slice.

## Risks

- Contacts/keyposes/tracking reference old frame numbers and become stale after upsample — pass-through per MVP (design risk, already tracked); remap is deferred future work.
- `duration_frames` on the source fixture is `0` in tests (default); passthrough leaves meta untouched, resample writes `duration_frames = n_out`. Verified.
- 60fps doubling is a performance concern (design risk); `to_thread` offload landed with the adapter (PR3) but is unmeasured at real-data scale — profile early.
- PR2: SMOOTH variance monotonicity is verified empirically (100×100 grid on jittered trajectories), not proven for arbitrary inputs — documented caveat; rotation slerp per resample interval adds negligible stdlib cost at fixture scale. No numpy/scipy (domain guardrail).
- PR3: adapter is not yet wired into the registry/catalog — `enrich_motion` has no INode caller until PR4; the re-export (task 4.4) also lands in PR4. → **RESOLVED in PR4**: registry 9th seed, re-export, and TS catalog sync are all live.
- **OPEN — §3.2 human gate**: Security Champion sign-off for the new `ENRICHMENT` node category is PENDING maintainer before archive. Threat-model entry is in place; the sign-off itself cannot be fabricated by apply.
