# Tasks: In-Between Generation and Enrichment (§12.5)

REQ tags: RESAMPLE/EASING/ROT/SMOOTH/VALIDATE/ORDER = inbetween spec; SEED = node-registry spec.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~800–940 authored (PR1 ~230, PR2 ~230, PR3 ~250, PR4 ~150 incl. ~60 golden) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | 4 chained PRs (feature-branch chain) |
| Delivery strategy | ask-on-risk |
| Chain strategy | feature-branch-chain |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

**Decision for user:** approve the 4-PR feature-branch chain (PR1→PR4 below, each ≤ ~270 lines) or size:exception single PR (temporal-cleanup precedent).

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Domain params+resample+easing | PR 1 (base=tracker) | `pytest tests/domain/test_inbetween.py -v` | N/A — pure math | Revert PR1 (internals, no callers) |
| 2 | Domain rotation+smoothing+`enrich_motion` | PR 2 (base=PR1) | `pytest tests/domain/test_inbetween.py -v` | N/A — pure math | Revert PR2 (PR1 intact) |
| 3 | Adapter+adapter tests | PR 3 (base=PR2) | `pytest tests/infrastructure/test_inbetween_generation.py -v` | N/A — async wrapper | Delete adapter+test files |
| 4 | Registry wiring, count→9, TS, golden | PR 4 (base=PR3) | `pytest tests/ -k "seed or registry" -v`, `npm test` | `npm test` — vitest + MSW fixture | Revert PR4 (schema/registry/TS) |

## Phase 1: Domain Timing Math (params, resample, easing) — TDD

- [x] 1.1 RED `tests/domain/test_inbetween.py`: enums `spline`/`bounce`, smoothing 1.5/-0.1, fps 0/-30 → `ValueError`; defaults valid (VALIDATE)
- [x] 1.2 GREEN `aimation_actor_core/domain/animation/inbetween.py`: frozen `InbetweenParams` + `__post_init__` + `DEFAULT_*` (VALIDATE)
- [x] 1.3 RED: 30fps/3fr→60fps/5fr, keys exact, first/last equal, cubic C1 vs linear C0; fps⩽fps and 1-frame passthrough; meta updated (RESAMPLE)
- [x] 1.4 GREEN `_resample`: Hermite basis + Catmull-Rom tangents, one-sided ends, linear mode; upsample-only (RESAMPLE)
- [x] 1.5 RED: ease-in/out half-asymmetry, in-out midpoint peak, monotonic f(0)=0 f(1)=1 (EASING)
- [x] 1.6 GREEN: `t²`, `1-(1-t)²`, `3t²-2t³` fused `u=ease(ξ)` in `_resample` (EASING)
- [x] 1.7 Re-export `InbetweenParams` in `aimation_actor_core/domain/animation/__init__.py`

## Phase 2: Domain Trajectory Math (rotation, smoothing, pipeline) — TDD

- [x] 2.1 RED: q/-q → positive dot; shortest arc = canonicalized slerp; disabled passthrough; near-antipodal nlerp no-NaN (ROT)
- [x] 2.2 GREEN `_apply_rotation_filter`: sign canonicalization on resampled seq, slerp flips far endpoint, nlerp if `|dot|>1-1e-6`/`sinθ<1e-6`; **canonicalize pre+post interpolation** (ROT)
- [x] 2.3 RED: identity at 0; translation variance non-increasing for a<b in (0,1] (SMOOTH)
- [x] 2.4 GREEN `_apply_tangent_smooth`: centered box `1+round(intensity*9)`; **translation axes only, rotations untouched** (SMOOTH)
- [x] 2.5 RED: stage-spy order, run-twice byte-identical, invariants; new frames `confidence=None`; **`tracking`/`contacts`/`keyposes` passthrough (MVP)** (ORDER)
- [x] 2.6 GREEN `enrich_motion`: resample→ease→rotation→smooth, meta updated, `validate_invariants()` last (ORDER)
- [x] 2.7 Re-export `enrich_motion` in `aimation_actor_core/domain/animation/__init__.py`

## Phase 3: INode Adapter — TDD

- [x] 3.1 RED `tests/infrastructure/test_inbetween_generation.py`: type `inbetween-generation`, ENRICHMENT, **explicit ports `motion: NEUTRAL_ANIMATION`→`motion: NEUTRAL_ANIMATION`**, 5 params+defaults, execute `to_thread`→NeutralMotion, validate rejects bad enum/range/fps/bool (VALIDATE)
- [x] 3.2 GREEN `aimation_actor_core/infrastructure/ai_models/inbetween_generation.py`: `InbetweenGenerationNode(INode)` — schema, coercion, execute, validate; mirrors `TemporalCleanupNode` (VALIDATE)

## Phase 4: Schema, Registry Wiring, Seed Counts

- [x] 4.1 `aimation_actor_core/domain/pipeline/schema.py`: additive `NodeCategory.ENRICHMENT = "enrichment"` (SEED)
- [ ] 4.2 RED `tests/infrastructure/test_inbetween_generation_registry.py`: 9 seeds, ENRICHMENT, NEUTRAL_ANIMATION ports (SEED)
- [ ] 4.3 GREEN `aimation_actor_core/infrastructure/virtual/node_registry.py`: register 9th seed after temporal-cleanup; docstring 8→9 (SEED)
- [ ] 4.4 Re-export `InbetweenGenerationNode` in `aimation_actor_core/infrastructure/ai_models/__init__.py`
- [ ] 4.5 Seed sets 8→9: `tests/infrastructure/test_executor.py`, `tests/infrastructure/test_temporal_cleanup_registry.py`, `tests/api/test_api.py` (SEED)

## Phase 5: Frontend TS Sync + Golden Fixture

- [ ] 5.1 `frontend/src/api/types.ts`: `NodeCategory` += `"enrichment"` (SEED)
- [ ] 5.2 `frontend/src/core/handles.ts`: `CATEGORY_COLORS` += enrichment (SEED)
- [ ] 5.3 `frontend/src/components/palette/Palette.tsx`: `CATEGORY_LABEL` + `CATEGORY_ORDER` after "cleanup" (SEED)
- [ ] 5.4 `frontend/src/test/fixtures/nodeCatalog.json`: golden entry — `enrichment` category, motion ports, 5 params (SEED)

## Phase 6: Integration Verify

- [ ] 6.1 `.\\.venv\\Scripts\\python.exe -m pytest` full suite green
- [ ] 6.2 Grep `import numpy|from numpy` in `aimation_actor_core/domain/` → zero matches
- [ ] 6.3 `npm test` in `frontend/` green — fixture no drift
- [ ] 6.4 Chain `video-source→pose-2d→pose-3d→video-to-motion→temporal-cleanup→inbetween-generation` valid DAG (SEED)
- [ ] 6.5 §3.2: threat-model entry + Security Champion sign-off before archive

Deferred (NOT tasks): arcs, procedural overlap, IK/FK blending, secondary motion, per-bone easing, downsampling, full gimbal-lock fix, contacts/keyposes/tracking remap — future changes.