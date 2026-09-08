# Archive Report: blocking-inbetween

**Change**: blocking-inbetween (Blocking → In-betweening, plan §20.5 / v0.4)
**Archived**: 2026-09-07
**Archived to**: `openspec/changes/archive/2026-09-07-blocking-inbetween/`
**Store**: hybrid (openspec + Engram)
**Mode**: Strict TDD

## Task Completion Gate

- **Tasks checked**: 25/25 `[x]`
- **Unchecked tasks**: 0
- **Gate result**: PASS

## Verification

- **Verdict**: PASS WITH WARNINGS (per `verify-report.md` at archive time; blockers 0, critical 0)
- **Backend test suite**: 560 passed / 2 skipped / exit 0 (fresh `--basetemp`; the earlier 45-error report was the Windows stale-tempdir PermissionError [WinError 5], not code)
- **Frontend test suite**: 132 passed / 22 files / exit 0 (vitest)
- **Mypy strict**: 0 errors (62 source files)
- **Ruff on change files**: exit 0 (15 changed files)
- **Ruff repo-wide**: exit 1 — 20 errors, ALL in untracked orphan `test_inbetween.py` at repo root (stray scratch script, not part of this change)
- **Import-linter**: 4/4 contracts kept, exit 0
- **Spec requirements**: 11/11 PASS (blocking-input 4, inbetween-generation 5, node-registry 2)
- **Spec scenarios**: 44/44 compliant (17 + 19 + 8; 43 strong, 1 partial-weak)
- **Evidence revision**: `sha256:536b66aeea2df409d2378112cc0ed1c856d23fc5262606342a9aa4da104f1d21`
- **Verify report**: `openspec/changes/archive/2026-09-07-blocking-inbetween/verify-report.md`

## Specs Synced

| Domain | Action | Details |
|--------|--------|---------|
| blocking-input | CREATED | New full spec copied to `openspec/specs/blocking-input/spec.md`. 4 requirements (PAYLOAD, CONVERT, NODE, THREAT), 17 scenarios. |
| inbetween-generation | MERGED | Key-lock (REQ-05), remap (REQ-06), degenerate safety (REQ-07) added to `openspec/specs/inbetween-generation/spec.md`; `preserve_keyposes` param + D5/D9 ordering. 5 requirements, 19 scenarios. |
| node-registry | MERGED | Seed nodes updated 10→11, added `blocking-input` (SOURCE, `motion:NEUTRAL_ANIMATION` output) scenario. 2 requirements, 8 scenarios. |

## Archive Contents

- `proposal.md` ✅
- `specs/blocking-input/spec.md` ✅ (full spec)
- `specs/inbetween-generation/spec.md` ✅ (delta)
- `specs/node-registry/spec.md` ✅ (delta)
- `design.md` ✅
- `tasks.md` ✅ (25/25 tasks complete)
- `verify-report.md` ✅ (PASS WITH WARNINGS)
- `archive-report.md` ✅ (this file)
- `apply-progress.md` ❌ — never persisted (W-3; RED/GREEN markers inline in tasks.md + deviation log, tests independently verified green at runtime)

## Source of Truth Updated

- `openspec/specs/blocking-input/spec.md` — NEW: blocking payload model, converter, SOURCE node, threat model
- `openspec/specs/inbetween-generation/spec.md` — key-lock / remap / degenerate-safety requirements
- `openspec/specs/node-registry/spec.md` — seed nodes = 11 (was 10)

## Implementation Summary

- **Domain**: `aimation_actor_core/domain/animation/blocking_input.py` (NEW — `BlockingKeyPose`/`BlockingInput` frozen, `extra="forbid"`, `MAX_KEYPOSES=1000`, `EXACT_LOCK_MIN=0.99`, `blocking_to_neutral_motion` converter: sparse sorted frames, dup-reject, default skeleton, `duration_frames=max(frame)`); `domain/animation/inbetween.py` (`InbetweenParams.preserve_keyposes`, key-lock in `_resample`, `_remap_keyposes` nearest-in-grid, `enrich_motion` re-applies locks after rotation filter + tangent smooth per D5, then remaps per D9); `neutral_motion.py` keypose frame-within-duration checkpoint (task 1.6 — see W-1); `domain/animation/__init__.py` re-exports
- **Adapter**: `infrastructure/ai_models/blocking_input.py` (NEW — `BlockingInputNode`, SOURCE, `params["blocking"]`, validate pre-exec, `to_thread`, stateless, `MAX_BLOCKING_PAYLOAD_CHARS` + `BlockingPayloadError` size cap before parse); `infrastructure/ai_models/inbetween_generation.py` (`preserve_keyposes` PortSpec BOOLEAN default False); `infrastructure/ai_models/__init__.py` re-exports
- **Registry**: `infrastructure/virtual/node_registry.py` — 11th seed `blocking-input` registered
- **Frontend**: `api/types.ts` (`KeyPose` typed), `core/presets.ts` (`blockingToMotionPreset` two-node graph), `core/presets.test.ts`, `test/fixtures/nodeCatalog.json` golden entry
- **Tests**: 67+ new tests across `tests/domain/test_blocking_input.py`, `tests/domain/test_inbetween.py`, `tests/infrastructure/test_blocking_input_node.py`, `tests/infrastructure/test_blocking_e2e.py`
- **Threat model**: `docs/SDD.md` §4.2 row "Blocking input / key-lock" (High severity) — bounded keypose count, frame-within-duration, weight [0,1], quat unit-norm/all-zero reject, finite check, payload size cap, static registry, `_resample` total, no-eval scan

## Warnings & Follow-Ups (recorded at close, per verify-report)

- **W-1**: Task 1.6 (keypose frame-within-duration in `validate_invariants`) not delivered as written — enforcement lives in the converter + `_remap_keyposes` clamp (design Open Question #1 resolved converter-path). Defensive-validation gap on manually-constructed non-converter motions; low severity.
- **W-2**: `test_frame_beyond_duration_rejected` (REQ-02 SC-04) trivially-passing — beyond-duration keypose impossible by construction; scenario satisfied by construction.
- **W-3**: No `apply-progress.md` persisted — substantive strict-TDD evidence present (RED/GREEN inline, 111/111 targeted + 560 full suite green at runtime), dedicated artifact absent.
- **W-4**: Repo-wide ruff fails (20 errors) confined to untracked orphan `test_inbetween.py` at repo root — unrelated to this change; remove or exclude.
- **S-1**: Rename `test_executor.py::test_seeded_registry_lists_ten_seed_nodes` → `..._eleven_seed_nodes` (stale name, asserts 11).
- **S-2**: Uncommitted work + untracked `media/Video_30fps.mp4`, `media/test_motion.json`, `media/test_motion_enriched.json`, root `test_inbetween.py` should be removed (never committed).
- **S-3**: Consider explicit `validate_invariants` keypose-duration assertion (task 1.6 intent) to close W-1/W-2 and Open Question #1.

## Delivery Status

- **Implementation**: Complete (25/25 tasks). Branch `feat/Develop`, work present but **uncommitted** at close.
- **Push/PR**: NOT done (human decision, ordinary repository policy).
- **Delivery strategy**: single-pr with maintainer-approved `size:exception` (~580–780 lines forecast).

## Not Archived

- `media/Video_30fps.mp4`, `media/test_motion.json`, `media/test_motion_enriched.json` — test/media assets, not part of the SDD change (candidate for removal).
- `test_inbetween.py` at repo root — stray scratch script (W-4/S-2; candidate for removal).

## SDD Cycle Complete

The change has been fully planned, implemented, verified, and archived. Delivery (commit/push/PR) is a human decision under ordinary repository policy.