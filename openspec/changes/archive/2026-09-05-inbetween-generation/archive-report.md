# Archive Report: inbetween-generation

**Change**: inbetween-generation (§12.5 In-Between Generation and Enrichment)
**Archived**: 2026-09-05
**Archived to**: `openspec/changes/archive/2026-09-05-inbetween-generation/`
**Store**: hybrid (openspec + Engram)

## Task Completion Gate

- **Tasks checked**: 30/30 `[x]`
- **Unchecked tasks**: 0
- **Gate result**: PASS

## Verification

- **Verdict**: PASS WITH WARNINGS
- **Backend test suite**: 369 passed, 2 skipped, exit 0 (no regression vs PR3 baseline 365+2)
- **Frontend test suite**: 123 passed, 22 files, exit 0
- **Mypy strict**: 0 errors
- **Ruff lint + import-linter**: clean (4/4 contracts kept)
- **numpy guardrail**: 0 matches in `domain/`
- **Spec requirements**: 7/7 PASS
- **Spec scenarios**: 22/22 compliant (18 inbetween-generation + 4 node-registry)
- **Verify report**: `openspec/changes/archive/2026-09-05-inbetween-generation/verify-report.md`

## Security Champion Sign-Off (§3.2)

- **Status**: SIGNED
- **Signed by**: Maintainer (user)
- **Date**: 2026-09-05
- **Scope**: New `ENRICHMENT` node category (threat-model entry in `docs/SDD.md` §4.2)
- **Commit**: `49d73bb` (verify-report.md updated with sign-off record)

## Specs Synced

| Domain | Action | Details |
|--------|--------|---------|
| node-registry | MERGED | Seed nodes requirement updated: 8→9 seeds, added `inbetween-generation` scenario (category ENRICHMENT, in-between generation + enrichment). 1 requirement modified, 1 scenario added, 0 removed. |
| inbetween-generation | CREATED | New full spec copied mechanically to `openspec/specs/inbetween-generation/spec.md`. 6 requirements (RESAMPLE, EASING, ROT, SMOOTH, VALIDATE, ORDER), 18 scenarios. |

## Archive Contents

- `proposal.md` ✅
- `specs/node-registry/spec.md` ✅ (delta)
- `specs/inbetween-generation/spec.md` ✅ (full spec)
- `design.md` ✅
- `tasks.md` ✅ (30/30 tasks complete)
- `apply-progress.md` ✅ (4 slices, all attempts `complete` in ledger)
- `verify-report.md` ✅ (PASS WITH WARNINGS, sign-off SIGNED)

## Source of Truth Updated

The following main specs now reflect the new behavior:
- `openspec/specs/node-registry/spec.md` — seed nodes = 9 (was 8), ENRICHMENT category documented
- `openspec/specs/inbetween-generation/spec.md` — NEW: in-between generation requirements (resample, easing, rotation continuity, tangent smoothing, validation, processing order)

## Implementation Summary

- **Domain math**: `aimation_actor_core/domain/animation/inbetween.py` — pure stdlib (no numpy/scipy), deterministic, stateless
  - Resample: Hermite/linear upsample with eased timing (`u=ease(ξ)` fused)
  - Rotation filter: quaternion sign canonicalization + shortest-arc slerp + nlerp fallback (anti-NaN)
  - Tangent smoothing: centered box filter (odd width), translation axes only
- **Adapter**: `aimation_actor_core/infrastructure/ai_models/inbetween_generation.py` — mirrors `TemporalCleanupNode` pattern (dict coercion, `asyncio.to_thread`, validation)
- **Registry**: 9th seed registered after `temporal-cleanup`, `NodeCategory.ENRICHMENT` additive
- **Frontend sync**: `types.ts` (NodeCategory), `handles.ts` (color `#0ea5e9`), `Palette.tsx` (label/order), `nodeCatalog.json` (golden fixture)
- **Threat model**: `docs/SDD.md` §4.2 row "Enrichment Nodes" (Low severity)
- **Tests**: 67 new tests across 3 files (domain, adapter, registry)

## Delivery Status

- **Implementation**: Complete (4 slices, 4 PRs in feature-branch chain)
- **Branches**: `feat/inbetween-generation-pr2` ← `pr3` ← `pr4` (all from `feat/Develop`)
- **Push/PR**: NOT done (human decision, ordinary repository policy)
- **Chain strategy**: feature-branch chain (4 PRs, decided by user)

## Open Follow-Ups

- **WARNING 1 (optional)**: `ruff format --check` non-green on 2 files (`inbetween.py`, `test_inbetween.py`) — whitespace-only, created in PR1/PR2, never formatter-gated. Fix: `ruff format` on those 2 files (trivial, no spec/design impact).
- **SUGGESTION 1**: No coverage tool configured (`pytest-cov` absent) — same gap as temporal-cleanup.
- **SUGGESTION 2**: SMOOTH monotonicity is empirical (100×100 grid), not analytic — acceptable for MVP.
- **SUGGESTION 3**: Explicit `None` params pass `validate()` but crash `execute()` — mirrors `TemporalCleanupNode` convention, decide centrally.
- **SUGGESTION 4**: 60fps performance unmeasured at real-data scale — profile before relying on long clips.
- **SUGGESTION 5**: contacts/keyposes/tracking stale after upsample — pass-through per MVP, remap deferred.

## Not Archived

- `media/Video_30fps.mp4` — media asset, not part of the SDD change.

## SDD Cycle Complete

The change has been fully planned, implemented, verified, and archived. Delivery (push/PR) is a human decision under ordinary repository policy.
