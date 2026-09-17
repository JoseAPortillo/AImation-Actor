# Apply Progress — In-Between Generation and Enrichment (§12.5)

Change: `inbetween-generation`
Slice: **PR4** (feature-branch-chain, slice 4 of 4) — Phase 4 remainder + Phase 5 + Phase 6, tasks 4.2–4.5, 5.1–5.4, 6.1–6.5
Mode: **Strict TDD** (openspec/config.yaml `apply.tdd: true`)
Store: hybrid (openspec file + Engram observation)
Test runner: `.venv\Scripts\python.exe -m pytest --basetemp %TEMP%\opencode\pytest-basetemp` (user `%TEMP%\pytest-of-josea` corrupt)

## Scope of this batch (COMPLETE)

PR4 — registry wiring + frontend TS sync + integration verify. Tasks 4.2–4.5 (9th seed registration, package re-export, seed-count sync), 5.1–5.4 (TS catalog sync + golden fixture), 6.1–6.5 (full-suite verify, numpy grep, npm test, DAG chain, threat-model entry). PR1–PR3 (tasks 1.1–4.1) previously complete.

## TDD Cycle Evidence

### Slice 1 (PR1) — Phase 1, tasks 1.1–1.7

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `tests/domain/test_inbetween.py` | Unit | N/A (new) | ✅ Written (ImportError) | ✅ 10 cases pass | ✅ 4-param/reject sets | ✅ Clean |
| 1.2 | `tests/domain/test_inbetween.py` | Unit | N/A (new) | ✅ Written | ✅ 16 pass | ✅ 4 valid + defaults | ✅ Clean |
| 1.3 | `tests/domain/test_inbetween.py` | Unit | N/A (new) | ✅ Written (ImportError `_resample`) | ✅ 7 pass | ✅ 3→5, 4-key, C1/C0 | ✅ Clean |
| 1.4 | `tests/domain/test_inbetween.py` | Unit | N/A (new) | ✅ Written | ✅ pass | ✅ 7 cases | ✅ Extracted tangents/hermite |
| 1.5 | `tests/domain/test_inbetween.py` | Unit | N/A (new) | ✅ Written (ImportError `_ease`) | ✅ 5 pass | ✅ 3 curves + none | ✅ Clean |
| 1.6 | `tests/domain/test_inbetween.py` | Unit | N/A (new) | ✅ Written | ✅ pass | ✅ fused `u=ease(ξ)` | ✅ Clean |
| 1.7 | — (re-export) | — | N/A | — | ✅ import smoke | ➖ Single | ✅ Clean |

### Slice 2 (PR2) — Phase 2, tasks 2.1–2.7

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.1 | `tests/domain/test_inbetween.py` | Unit | ✅ 29/29 (PR1 baseline) | ✅ Written (ImportError `_apply_rotation_filter`) | ✅ 36 pass | ✅ 7 cases (flips, disabled, short arc, near-antipodal, endpoints, resample arc, composition) | ✅ Clean |
| 2.2 | `tests/domain/test_inbetween.py` | Unit | ✅ 29/29 | ✅ Written | ✅ 36 pass | ✅ same 7 cases enforce real slerp logic | ✅ Extracted `_nlerp` (dedup anti-NaN branch) |
| 2.3 | `tests/domain/test_inbetween.py` | Unit | ✅ 36/36 | ✅ Written (ImportError `_apply_tangent_smooth`) | ✅ 42 pass | ✅ identity + variance + parametrized (a,b) + rotations untouched | ✅ Clean |
| 2.4 | `tests/domain/test_inbetween.py` | Unit | ✅ 36/36 | ✅ Written | ✅ 42 pass | ✅ 6 cases incl. 3 parametrized monotonic pairs | ✅ Precomputed per-axis tracks (O(n²)→O(n)) |
| 2.5 | `tests/domain/test_inbetween.py` | Unit | ✅ 42/42 | ✅ Written (ImportError `enrich_motion`) | ✅ 49 pass | ✅ 7 cases (order spy, byte-identical, invariants, meta, confidence, passthrough, filter-off) | ✅ Clean |
| 2.6 | `tests/domain/test_inbetween.py` | Unit | ✅ 42/42 | ✅ Written | ✅ 49 pass | ✅ 7 cases cover pipeline contract end to end | ➖ None needed (design-exact) |
| 2.7 | `tests/domain/test_inbetween.py` | Unit | ✅ 49/49 | ✅ Written (ImportError from package `__init__`) | ✅ 50 pass | ➖ Single (structural re-export) | ✅ Clean |

### Slice 3 (PR3) — Phase 3, tasks 3.1–3.2 (+ 4.1 dependency)

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 3.1 | `tests/infrastructure/test_inbetween_generation.py` | Unit | ✅ 77/77 (inbetween domain + pipeline + temporal-cleanup infra) | ✅ Written (ModuleNotFoundError `inbetween_generation`) | — (covered by 3.2 GREEN) | ✅ 16 cases: schema type/category/ports/5 params+defaults; execute object-in, dict-in, passthrough, to_thread spy; validate empty/valid/enum/range/fps/bool | ➖ None needed (spec-scenario mirror) |
| 3.2 | `aimation_actor_core/infrastructure/ai_models/inbetween_generation.py` | Unit | ✅ 77/77 | ✅ 3.1 RED first | ✅ 16/16 pass | ✅ 4 execute paths exercise real `enrich_motion` (6-frame upsample, dict coercion branch, passthrough branch, to_thread offload) | ➖ None needed (design-exact `TemporalCleanupNode` mirror; `DEFAULT_*` from domain, `_coerce_motion` dedup) |
| 4.1 | `aimation_actor_core/domain/pipeline/schema.py` | Unit | ✅ 77/77 | **not TDD-able alone** (additive enum member, no behavior) | ✅ exercised via 3.1 RED→GREEN | ➖ Single (structural; palette position after CLEANUP per task 5.3) | ✅ Clean |

### Slice 4 (PR4) — Phase 4 remainder + Phase 5 + Phase 6, tasks 4.2–6.5

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 4.2 | `tests/infrastructure/test_inbetween_generation_registry.py` | Unit | ✅ 450/450 backend; npm 171/173 | ✅ Written → **5 failed** (missing node, 8≠9, ImportError re-export, unknown node type) | — (covered by 4.3/4.4 GREEN) | ✅ 5 cases: ENRICHMENT+ports, **5-param cross-lineage guard**, nine seeds, package re-export, DAG chain | ➖ None needed (spec-scenario mirror, `test_temporal_cleanup_registry.py` pattern) |
| 4.3 | `aimation_actor_core/infrastructure/virtual/node_registry.py` | Unit | ✅ 450/450 | ✅ 4.2 RED first | ✅ registry tests pass (5/5) | ✅ same 5 cases force real registration | ✅ Clean (docstring 8→9) |
| 4.4 | `aimation_actor_core/infrastructure/ai_models/__init__.py` | Unit | ✅ 450/450 | ✅ import-smoke RED (ImportError) | ✅ re-export test passes | ➖ Single (structural re-export) | ✅ Clean (ruff-sorted imports) |
| 4.5 | `tests/infrastructure/test_executor.py`, `tests/infrastructure/test_temporal_cleanup_registry.py`, `tests/api/test_api.py` | Unit | ✅ 450/450 | ✅ **3 failed** (8-seed asserts vs 9-seed registry) | ✅ 54 pass (focused 4-file run) | ➖ Structural count sync (single set each) | ✅ Clean |
| 5.1 | `frontend/src/api/types.ts` | — | ✅ npm 171/173; tsc baseline 1 pre-existing error | N/A structural (type union member) | ✅ tsc: zero new errors | ➖ Single | ✅ Clean |
| 5.2 | `frontend/src/core/handles.ts` | — | ✅ npm 171/173 | N/A structural (color map key) | ✅ tsc: zero new errors | ➖ Single | ✅ Clean |
| 5.3 | `frontend/src/components/palette/Palette.tsx` | — | ✅ npm 171/173 | N/A structural (label + order after cleanup) | ✅ Palette suite green | ➖ Single | ✅ Clean |
| 5.4 | `frontend/src/test/fixtures/nodeCatalog.json` | — | ✅ npm 171/173 | N/A golden fixture | ✅ all fixture-consuming tests green (no drift) | ➖ Single (mirrors adapter schema exactly) | ✅ Clean |
| 6.1 | full pytest suite | Integration | ✅ 450 baseline | — | ✅ **450 passed** | — | — |
| 6.2 | grep numpy in `domain/` | — | — | — | ✅ **ZERO** matches (27 files) | — | — |
| 6.3 | `npm test` + `npx tsc -b` | Integration | ✅ 171/173 | — | ⚠️ 171 pass + **2 pre-existing `App.test.tsx` failures** (identical at baseline, unrelated wizard lineage); tsc: **only 1 pre-existing error** in untouched `WizardStep2Poses.tsx`; fixture no-drift PROVEN | — | — |
| 6.4 | `test_inbetween_generation_registry.py::TestInbetweenPipelineChain` | Integration | — | ✅ RED first (`unknown node type: inbetween-generation`) | ✅ valid connected DAG (e5 cleanup→enrich) | — | — |
| 6.5 | `docs/SDD.md` §4.2 table | — | — | N/A documentation | ✅ threat-model row added | — | — |

**Triangulation notes (PR4)**: 4.2's five tests map directly to the node-registry delta spec — `inbetween-generation` present (9 seeds), category `ENRICHMENT`, both ports `NEUTRAL_ANIMATION`, and the six-node DAG `video-source→pose-2d→pose-3d→video-to-motion→temporal-cleanup→inbetween-generation` validated through the real registry. The five-params/defaults assertion is a deliberate **cross-lineage guard**: the archived `feat/Develop` adapter carries a 6th `preserve_keyposes` param that does not exist on this chain; a wrong-lineage cherry-pick would fail this test. All defaults asserted exactly (cubic, 30.0, none, True, 0.0). Frontend tasks are structural syncs (one possible output each) — triangulation skipped with reason; the existing 171-test frontend suite plus `tsc -b` are the contract gate.

## Work Unit Evidence

| Evidence | PR1 (slice 1) | PR2 (slice 2) | PR3 (slice 3) | PR4 (slice 4) |
|---|---|---|---|---|
| Focused test command & result | `pytest tests/domain/test_inbetween.py -v` → **29 passed** | `.\.venv\Scripts\python.exe -m pytest tests/domain/test_inbetween.py -v` → **50 passed** (29 + 21) | `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/test_inbetween_generation.py -v` → **16 passed**; post-format re-run + inbetween/pipeline/temporal-cleanup: **90 passed** | `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/test_inbetween_generation_registry.py tests/infrastructure/test_executor.py tests/infrastructure/test_temporal_cleanup_registry.py tests/api/test_api.py -q` → **54 passed**; full suite → **450 passed** (445 + 5 new) |
| Runtime harness command & result | N/A — pure domain math | N/A — pure domain math | N/A — async wrapper; `asyncio.to_thread` spy proves offload path | `npm test` (vitest + MSW fixture) → **171 passed**, 2 pre-existing `App.test.tsx` fails (unchanged vs baseline); `npx tsc -b` → only 1 pre-existing error in untouched wizard file; chain DAG validated through real registry (`validate_graph`) |
| Rollback boundary | Revert PR1 internals | Revert PR2 additions; PR1 intact | Delete `inbetween_generation.py` + `test_inbetween_generation.py`; revert schema.py `ENRICHMENT` member | Revert registry wiring (`node_registry.py`, `ai_models/__init__.py`), TS sync (`types.ts`, `handles.ts`, `Palette.tsx`, `nodeCatalog.json`), seed-count updates (3 test files), delete `test_inbetween_generation_registry.py`, revert `docs/SDD.md` row; PR1–PR3 intact |

## Verification (gate)

1. Focused PR4 tests: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure/test_inbetween_generation_registry.py tests/infrastructure/test_executor.py tests/infrastructure/test_temporal_cleanup_registry.py tests/api/test_api.py -q --basetemp C:\Users\josea\AppData\Local\Temp\opencode\pytest-basetemp` → **54 passed**
2. Full suite: `.\.venv\Scripts\python.exe -m pytest --basetemp C:\Users\josea\AppData\Local\Temp\opencode\pytest-basetemp` → **450 passed** (PR3 baseline 445 + 5 new registry tests; no regression)
3. `ruff check` on all touched Python files → **All checks passed**; `ruff format --check` → 5/5 files clean. (`test_api.py` F401 `io` + format drift confirmed **pre-existing at HEAD** via `git show`, not touched.)
4. `mypy --strict` on `node_registry.py` + `ai_models/__init__.py` → **Success: no issues found in 2 source files**
5. `lint-imports --show-timings` → **4 contracts kept, 0 broken**; domain stays pure
6. 6.2 numpy grep in `aimation_actor_core/domain/` (27 files) → **ZERO matches**
7. 6.3 frontend: `npm test` → **171 passed / 2 failed** — the 2 failures (`App.test.tsx`: expects "AImation Flow" heading + `simple-mode`, app renders "AImation Actor" wizard) are **pre-existing at HEAD** (frontend was clean before this slice; wizard commit lineage), unrelated to this change; every fixture-consuming test passes → **fixture no-drift**. `npx tsc -b` → exactly 1 error, `WizardStep2Poses.tsx(195,25)` unused `e`, **zero diff vs HEAD** → pre-existing; no new type errors from the TS sync.

## Completed Tasks (cumulative)

### Phase 1 (PR1)

- [x] 1.1 RED `tests/domain/test_inbetween.py`: enums `spline`/`bounce`, smoothing 1.5/-0.1, fps 0/-30 → `ValueError`; defaults valid (VALIDATE)
- [x] 1.2 GREEN `aimation_actor_core/domain/animation/inbetween.py`: frozen `InbetweenParams` + `__post_init__` + `DEFAULT_*` (VALIDATE)
- [x] 1.3 RED: 30fps/3fr→60fps/5fr, keys exact, first/last equal, cubic C1 vs linear C0; fps⩽fps and 1-frame passthrough; meta updated (RESAMPLE)
- [x] 1.4 GREEN `_resample`: Hermite basis + Catmull-Rom tangents, one-sided ends, linear mode; upsample-only (RESAMPLE)
- [x] 1.5 RED: ease-in/out half-asymmetry, in-out midpoint peak, monotonic f(0)=0 f(1)=1 (EASING)
- [x] 1.6 GREEN: `t²`, `1-(1-t)²`, `3t²-2t³` fused `u=ease(ξ)` in `_resample` (EASING)
- [x] 1.7 Re-export `InbetweenParams` in `aimation_actor_core/domain/animation/__init__.py`

### Phase 2 (PR2)

- [x] 2.1 RED: q/-q → positive dot; shortest arc = canonicalized slerp; disabled passthrough; near-antipodal nlerp no-NaN (ROT)
- [x] 2.2 GREEN `_apply_rotation_filter`: sign canonicalization on resampled seq, slerp flips far endpoint, nlerp if `|dot|>1-1e-6`/`sinθ<1e-6`; **canonicalize pre+post interpolation** (ROT)
- [x] 2.3 RED: identity at 0; translation variance non-increasing for a<b in (0,1] (SMOOTH)
- [x] 2.4 GREEN `_apply_tangent_smooth`: centered box `1+round(intensity*9)`; **translation axes only, rotations untouched** (SMOOTH)
- [x] 2.5 RED: stage-spy order, run-twice byte-identical, invariants; new frames `confidence=None`; **`tracking`/`contacts`/`keyposes` passthrough (MVP)** (ORDER)
- [x] 2.6 GREEN `enrich_motion`: resample→ease→rotation→smooth, meta updated, `validate_invariants()` last (ORDER)
- [x] 2.7 Re-export `enrich_motion` in `aimation_actor_core/domain/animation/__init__.py`

### Phase 3 (PR3)

- [x] 3.1 RED `tests/infrastructure/test_inbetween_generation.py`: type `inbetween-generation`, ENRICHMENT, **explicit ports `motion: NEUTRAL_ANIMATION`→`motion: NEUTRAL_ANIMATION`**, 5 params+defaults, execute `to_thread`→NeutralMotion, validate rejects bad enum/range/fps/bool (VALIDATE)
- [x] 3.2 GREEN `aimation_actor_core/infrastructure/ai_models/inbetween_generation.py`: `InbetweenGenerationNode(INode)` — schema, coercion, execute, validate; mirrors `TemporalCleanupNode` (VALIDATE)

### Phase 4 (PR4)

- [x] 4.1 `aimation_actor_core/domain/pipeline/schema.py`: additive `NodeCategory.ENRICHMENT = "enrichment"` (SEED) — done early with PR3 (3.1/3.2 compile dependency)
- [x] 4.2 RED `tests/infrastructure/test_inbetween_generation_registry.py`: 9 seeds, ENRICHMENT, NEUTRAL_ANIMATION ports (SEED)
- [x] 4.3 GREEN `aimation_actor_core/infrastructure/virtual/node_registry.py`: register 9th seed after temporal-cleanup; docstring 8→9 (SEED)
- [x] 4.4 Re-export `InbetweenGenerationNode` in `aimation_actor_core/infrastructure/ai_models/__init__.py`
- [x] 4.5 Seed sets 8→9: `tests/infrastructure/test_executor.py`, `tests/infrastructure/test_temporal_cleanup_registry.py`, `tests/api/test_api.py` (SEED)

### Phase 5 (PR4)

- [x] 5.1 `frontend/src/api/types.ts`: `NodeCategory` += `"enrichment"` (SEED)
- [x] 5.2 `frontend/src/core/handles.ts`: `CATEGORY_COLORS` += enrichment (SEED)
- [x] 5.3 `frontend/src/components/palette/Palette.tsx`: `CATEGORY_LABEL` + `CATEGORY_ORDER` after "cleanup" (SEED)
- [x] 5.4 `frontend/src/test/fixtures/nodeCatalog.json`: golden entry — `enrichment` category, motion ports, 5 params (SEED)

### Phase 6 (PR4)

- [x] 6.1 `.\\.venv\\Scripts\\python.exe -m pytest` full suite green — **450 passed**
- [x] 6.2 Grep `import numpy|from numpy` in `aimation_actor_core/domain/` → **zero matches** (27 files)
- [x] 6.3 `npm test` in `frontend/` — **171 passed**, fixture no-drift proven; 2 `App.test.tsx` failures **pre-existing at HEAD** (see Risks)
- [x] 6.4 Chain `video-source→pose-2d→pose-3d→video-to-motion→temporal-cleanup→inbetween-generation` valid DAG (SEED)
- [x] 6.5 §3.2: threat-model entry added to `docs/SDD.md` §4.2; **Security Champion sign-off still pending — required before archive**

## Next / Resume Point

- **Next phase: sdd-verify** — independent verification of PR4 evidence against specs/design/tasks (the executor does not self-verify). After verify passes: **sdd-archive** must confirm the §3.2 Security Champion sign-off and threat-model entry before merging the ENRICHMENT category delta.

## Deviations from Design

PR4 — none beyond the documented frontend-baseline findings:
- **Frontend baseline is not fully green at HEAD** (pre-existing): `App.test.tsx` (2 tests — expects "AImation Flow"/simple-mode; app renders "AImation Actor"/wizard) and `WizardStep2Poses.tsx` tsc unused-`e` error. Both trace to the wizard-replacement commit lineage, zero diff vs HEAD. **Not fixed** (out of scope; strict-TDD report-don't-fix rule). 6.3 gate met for the change's own footprint: fixture no-drift + zero new TS errors.
- 4.5's RED was the natural consequence of 4.3 (existing 8-seed asserts failed against the 9-seed registry) — tests updated to the new contract, which is the intended seed-count sync.
- Cross-lineage guard embedded in the registry test (exact 5-param list) — the archived `feat/Develop` 6-param adapter would fail it.

PR3 note (unchanged): 4.1 pulled into PR3 as a compile dependency for 3.1/3.2.
PR1/PR2 notes (unchanged, retained): pre+post rotation canonicalization; nlerp thresholds; centered-box parity; SMOOTH variance on tangent track; `confidence=None`/passthrough MVP.

## Risks

- **Security Champion sign-off pending** for the new `ENRICHMENT` category (AGENTS.md §3.2): threat-model entry is in place; sign-off is an archive gate — sdd-archive must enforce it.
- **Frontend baseline failures** (pre-existing, wizard lineage): `npm test` and `npx tsc -b` will not report "green" for the whole repo until `App.test.tsx` and `WizardStep2Poses.tsx` are fixed. Fixing them is a separate work unit outside this change.
- Contacts/keyposes/tracking become stale after upsample — pass-through per MVP (deferred remap, design risk).
- `execute` coerces `bool(params.get("euler_filter", ...))` — a JSON string `"false"` would coerce to `True`; established `TemporalCleanupNode` coercion contract (validate-before-execute gates it in the real flow).
- SMOOTH variance monotonicity is empirically verified, not proven generally.
- **Cross-lineage**: the archived `feat/Develop` adapter carries later-state features (`preserve_keyposes`, `migrate_neutral_motion`) that do not exist on this chain — do NOT cherry-pick that file; the 5-param registry test enforces this.

## Verification gate status

Slice 4 verified locally (focused + full suite + ruff/mypy/import-linter + TS). Independent SDD verification is the next phase per the SDD lifecycle — apply does not self-verify.