# Archive Report — inbetween-generation (§12.5)

| Field | Value |
|-------|-------|
| Change | `inbetween-generation` — In-Between Generation and Enrichment (§12.5) |
| Archived | 2026-09-17 |
| Store | hybrid (openspec files + Engram observations) |
| Verdict at close | **PASS WITH WARNINGS** (0 blockers, 0 critical) |
| Task completion | **30/30** |
| Verification | **7/7 requirements, 22/22 scenarios, 450 backend tests passed** |

## Final-State Authority

Facts at close, ranked per the SDD archive contract:

1. **Persisted tasks artifact** (`tasks.md`, archived copy) — all 30 implementation tasks marked `[x]` (Phases 1–6). Authoritative completion visibility.
2. **Orchestrator launch facts** — verify PASS WITH WARNINGS, 0 blockers, 0 critical, 7/7 requirements, 22/22 scenarios compliant, 450 tests passing; archive authorized.
3. **Intermediate snapshots** — `verify-report.md` (Engram obs #790) and `apply-progress.md` (Engram obs #784) are consistent with the final state: no later commits changed test counts, and no pending item was later claimed done other than the Security Champion sign-off, which remains pending (recorded below, not silently closed).

No contradiction between sources; no stale snapshot claim is echoed as current fact.

## Task Completion Gate

All 30 tasks (Phases 1–6: domain math, adapter, registry wiring, seed-count sync, frontend TS sync, integration verify) are `[x]` in the archived `tasks.md`. No unchecked implementation tasks — standard archive, no stale-checkbox reconciliation performed.

## Spec Sync (delta → main specs)

| Domain | Action | Details |
|--------|--------|---------|
| node-registry | MODIFIED — 1 requirement | `### Requirement: Seed nodes` replaced: eight-node registry → **nine-node** registry including `inbetween-generation` (category `ENRICHMENT`, additive `NodeCategory` member); `Seed nodes are present` scenario updated; 1 scenario added (`inbetween-generation is the ENRICHMENT node`). All other requirements preserved byte-for-byte (verified by diff). |
| inbetween-generation | CREATED — full spec (7 requirements) | Main spec did not exist; the delta IS a full spec. Mechanically copied (`cp` + `diff -r` readback, both empty/exit 0) to `openspec/specs/inbetween-generation/spec.md`. |

**Native composition invocation:**
```
gentle-ai sdd-archive-compose \
  --canonical openspec/specs/node-registry/spec.md \
  --delta openspec/changes/inbetween-generation/specs/node-registry/spec.md \
  --output openspec/specs/node-registry/spec.md.compose-tmp
```

**CRLF workaround (recorded for transparency):** `gentle-ai sdd-archive-compose` v2.9.1 rejects CRLF-marked delta headings with a false-negative error (`DELTA: delta spec declares no ADDED, MODIFIED, REMOVED, or RENAMED requirements`) — Go regexp `$`-anchoring cannot match `## MODIFIED Requirements\r`. Proven empirically: an LF copy of the identical delta composes (exit 0), a CRLF copy of a delta that previously composed is refused. Composition therefore ran through the native command on LF-normalized byte copies, and the composed output was re-normalized to CRLF (repo convention). The merge logic ran 100% through the native tool — no model-driven Read/Edit merge. Final main spec verified byte-identical to the native compose output (diff exit 0) and semantically scoped (diff shows only the Seed-nodes block changing).

## Files Changed (per verify-report / apply-progress evidence)

**Domain (pure stdlib):**
- `aimation_actor_core/domain/animation/inbetween.py` — new; `InbetweenParams` (frozen, `__post_init__` validation, `DEFAULT_*`), `_resample` (Hermite/Catmull-Rom, upsample-only), `_ease` (fused `u=ease(ξ)`), `_apply_rotation_filter` (sign canonicalization, slerp/nlerp), `_apply_tangent_smooth` (centered box), `enrich_motion` (fixed stage order)
- `aimation_actor_core/domain/animation/__init__.py` — re-exports `InbetweenParams`, `enrich_motion`
- `aimation_actor_core/domain/pipeline/schema.py` — additive `NodeCategory.ENRICHMENT = "enrichment"`

**Infrastructure:**
- `aimation_actor_core/infrastructure/ai_models/inbetween_generation.py` — new; `InbetweenGenerationNode(INode)`, mirrors `TemporalCleanupNode` (dict coercion, `asyncio.to_thread`, validate-before-execute)
- `aimation_actor_core/infrastructure/ai_models/__init__.py` — re-export `InbetweenGenerationNode`
- `aimation_actor_core/infrastructure/virtual/node_registry.py` — 9th seed registered; docstring 8→9

**Tests:**
- `tests/domain/test_inbetween.py` — new (50 tests: VALIDATE/RESAMPLE/EASING/ROT/SMOOTH/ORDER)
- `tests/infrastructure/test_inbetween_generation.py` — new (16 tests: adapter contract)
- `tests/infrastructure/test_inbetween_generation_registry.py` — new (5 tests incl. 5-param cross-lineage guard + DAG chain)
- `tests/infrastructure/test_executor.py`, `tests/infrastructure/test_temporal_cleanup_registry.py`, `tests/api/test_api.py` — seed sets 8→9

**Frontend TS sync:**
- `frontend/src/api/types.ts` (`NodeCategory` += `"enrichment"`), `frontend/src/core/handles.ts` (`CATEGORY_COLORS`), `frontend/src/components/palette/Palette.tsx` (`CATEGORY_LABEL`/`CATEGORY_ORDER`), `frontend/src/test/fixtures/nodeCatalog.json` (golden entry)

**Docs:**
- `docs/SDD.md` §4.2 — threat-model row for the `ENRICHMENT` category (lineage preserved per `rules.archive`)

**Specs:**
- `openspec/specs/node-registry/spec.md` — MODIFIED (composed)
- `openspec/specs/inbetween-generation/spec.md` — created

## Verification Summary at Close

- **Requirements**: 7/7 compliant; **scenarios**: 22/22 compliant (full compliance matrix in `verify-report.md`)
- **Backend tests**: 450 passed / 0 failed (full pytest suite) — 1 warning
- **Import contracts**: 4 kept / 0 broken (`lint-imports.exe`)
- **Type check**: mypy `--strict` clean on change files (inbetween.py, inbetween_generation.py, node_registry.py, ai_models/__init__.py)
- **Lint**: ruff clean on the change's own footprint (18 pre-existing repo-wide findings outside footprint)
- **Numpy guardrail**: zero `import numpy` matches in `aimation_actor_core/domain/` (27 files)
- **Frontend**: 171 passed / 2 failed (`App.test.tsx`, pre-existing at HEAD, wizard lineage, zero diff vs HEAD); `tsc -b` — 1 pre-existing error in untouched `WizardStep2Poses.tsx`; golden fixture no-drift proven
- **Coverage**: not required (config `coverage_threshold: 0`)

## Warnings at Close (all pre-existing baseline or documented risk — NONE blocking)

1. Frontend `npm test` not fully green at HEAD: 2 `App.test.tsx` failures + 1 pre-existing `tsc` error (`WizardStep2Poses.tsx(195,25)` unused `e`) — wizard-commit lineage, zero diff vs HEAD; fixing is a separate work unit.
2. Ruff repo-wide: 18 pre-existing findings in files untouched by this change; the change's own files are ruff-clean (single touched-file F401 `io` in `test_api.py` confirmed pre-existing at HEAD).
3. `python -m importlinter` is not a valid invocation in this environment — `lint-imports.exe` console script used instead (same linter, 4/4 contracts kept); `verify.build_command` in `openspec/config.yaml` may need updating to the working form.
4. **Security Champion sign-off pending** for the new `ENRICHMENT` category — see dedicated section below.
5. `execute` coerces `euler_filter`/numerics via `bool()`/`float()` — a JSON string `"false"` would coerce to `True`; gated by validate-before-execute in the real flow (established `TemporalCleanupNode` contract).
6. contacts/keyposes/tracking frame references become stale after upsample — MVP pass-through, remap deferred (spec-sanctioned).
7. SMOOTH variance monotonicity is empirically verified (3 parametrized pairs), not generally proven — documented design risk.

## Security Champion Sign-off — PENDING (open gate, not a verification blocker)

AGENTS.md §3.2 requires Security Champion sign-off for new categories. The `ENRICHMENT` `NodeCategory` member's threat-model entry **is in place** (`docs/SDD.md` §4.2 — retained in the repo; threat-model lineage preserved per `openspec/config.yaml` `rules.archive`). The sign-off itself remains **pending at close** and was flagged by both apply and verify phases as an archive-time gate. Archive proceeded per the orchestrator's explicit final-state facts with this warning recorded; the sign-off must be completed as follow-up before the category is considered fully vetted.

## Archive Integrity

- Mechanical move: `git mv` staged the 6 tracked renames and refused on the untracked `verify-report.md`; the skill's documented plain-`mv` fallback ran after source-unchanged verification (snapshot diff empty) and completed the move.
- Mandatory readback: `diff -r <pre-move snapshot> <archive destination>` → **empty output, exit 0** (byte-identical).
- Active changes directory no longer contains `inbetween-generation`.
- The archive is an audit trail — contents were not modified after the move (this report is additive-only).

## Engram Traceability

Observations actually read this phase:
- **#790** `sdd/inbetween-generation/verify-report` (architecture)
- **#784** `sdd/inbetween-generation/apply-progress` (architecture)

Proposal, spec delta, design, and tasks exist **only as filesystem artifacts** — `mem_search` found no Engram observations for them. Archive report persisted as topic key `sdd/inbetween-generation/archive-report`.

## Archive Contents

- proposal.md ✅
- specs/inbetween-generation/spec.md ✅ (delta)
- specs/node-registry/spec.md ✅ (delta)
- design.md ✅
- tasks.md ✅ (30/30 complete)
- apply-progress.md ✅
- verify-report.md ✅

## SDD Cycle Complete

The change has been fully planned, implemented (30/30 tasks), verified (PASS WITH WARNINGS, 7/7 requirements, 22/22 scenarios, 450 tests), and archived on 2026-09-17. Open follow-up: §3.2 Security Champion sign-off for the `ENRICHMENT` category.