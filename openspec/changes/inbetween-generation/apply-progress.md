# Apply Progress — In-Between Generation and Enrichment (§12.5)

Change: `inbetween-generation`
Slice: **PR1** (feature-branch-chain, slice 1 of 4) — Phase 1, tasks 1.1–1.7
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

## Next / Resume Point

- **Next slice: PR2** — Phase 2, tasks 2.1–2.7 (Domain Trajectory Math): rotation filter (`_apply_rotation_filter`, slerp/nlerp canonicalization), tangent smoothing (`_apply_tangent_smooth`, centered box), `enrich_motion` pipeline (resample→ease→rotation→smooth, `validate_invariants()` last), re-export `enrich_motion`. `InbetweenParams`/`_resample`/`_ease` already land in PR1 and will be consumed by PR2.
- PR3: Phase 3 (adapter tests + `InbetweenGenerationNode`).
- PR4: Phase 4–6 (registry wiring, count 8→9, TS sync, golden, integration verify).

## Deviations from Design

None — implementation matches `design.md`. Notes on interpretation:
- `_resample` computes `n_out = int(span * target_fps) + 1` with `span = (n_in-1)/meta.fps`; output grid starts at the first source frame's `time`, aligning snapped fences so every source key value lands at its timeline position.
- Easing is fused at `u = _ease(local, easing)` inside the per-interval evaluation (`_interp_value`), per design "`u=ease(ξ)` inside resample".
- New frames get `confidence=None`; rotation/scale copied per bone; `contact`s/keyposes/tracking untouched (pass-through, MVP), consistent with design.

## Risks

- Contacts/keyposes/tracking reference old frame numbers and become stale after upsample — pass-through per MVP (design risk, already tracked); remap is deferred future work.
- `duration_frames` on the source fixture is `0` in tests (default); passthrough leaves meta untouched, resample writes `duration_frames = n_out`. Verified.
- 60fps doubling is a performance concern (design risk); `to_thread` offload lands with the adapter (PR3).
