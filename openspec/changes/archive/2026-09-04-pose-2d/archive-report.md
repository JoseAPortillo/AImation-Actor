# Archive Report: 2D Pose Estimation (pose-2d)

- **Change**: pose-2d
- **Archived**: 2026-09-04
- **Archive path**: `openspec/changes/archive/2026-09-04-pose-2d/`
- **Artifact store**: openspec (files) + Engram (hybrid)
- **Mode**: Strict TDD (enabled)

## Status

- **Status**: success
- **Task Completion Gate**: PASS — all 8/8 tasks checked (`[x]`), 0 unchecked in `tasks.md`.
- **Verification**: PASS — 267 tests green, 0 CRITICAL / 0 WARNING, 10/10 spec scenarios compliant.
  (Final-state fact from orchestrator, per `verify-report.md` validated and admitted at verify time.)

## Final-State Facts (authoritative, outrank intermediate snapshots)

1. **Verification PASS**: 267 tests green, 0 CRITICAL / 0 WARNING, all 10 spec scenarios compliant. Report admitted at `openspec/changes/pose-2d/verify-report.md`.
2. **Seed-node count evolution**: The project has evolved to **7 seed nodes** in `node_registry` (`pass-through`, `merge`, `frame-range`, `video-source`, `pose-2d`, `pose-3d`, `video-to-motion`). The pose-2d spec's MODIFIED node-registry delta originally specified **five** seed nodes (at the time it was planned). Later-archived changes (3D lifting / motion conversion) added the extra nodes. This is expected evolution, not a pose-2d defect. When syncing the node-registry delta, the count discrepancy was reconciled/annotated so the source of truth is not falsely pinned to five.
3. **tasks.md** uses `- [x]` for all 8 tasks — all complete, no stale unchecked tasks.
4. **`media/Video_30fps.mp4`** untracked file at repo top-level is NOT part of the pose-2d change; ignored for archival.

## Specs Synced

| Domain | Action | Details |
|--------|--------|---------|
| pose-estimation | Created (full spec copy) | 4 requirements added, 0 modified, 0 removed. Contains the MODIFIED node-registry "Seed nodes" delta inline. |
| node-registry | Updated (MODIFIED merge) | "Seed nodes" requirement merged: added `pose-2d` (category AI) and reconciled count to seven with annotation. Other requirements preserved unchanged (Allowlist-only lookup, Static registration, Node types endpoint). |

### pose-estimation

- Created `openspec/specs/pose-estimation/spec.md` via mechanical shell copy (byte-identical to delta; verified by `git diff --no-index` returning empty).
- Requirements: Pose estimation node contract, Typed keypoint value object, Swappable estimator backend, Backend availability surfaced in health.

### node-registry

- MODIFIED the "Seed nodes" requirement in `openspec/specs/node-registry/spec.md` (previously four nodes: `pass-through`, `merge`, `frame-range`, `video-source`; delta adds `pose-2d`).
- Reconciled the seed-node count to the current seven-node state (`pass-through`, `merge`, `frame-range`, `video-source`, `pose-2d`, `pose-3d`, `video-to-motion`) with an explicit annotation that the pose-2d delta originally specified five and later-archived changes added the extra nodes. The source of truth is not pinned to five.
- All other requirements preserved unchanged.

## Archive Contents

- proposal.md ✅
- specs/pose-estimation/spec.md ✅
- design.md ✅
- tasks.md ✅ (8/8 tasks complete)
- verify-report.md ✅
- exploration.md ✅
- archive-report.md ✅ (this file — additive, excluded from the source/destination diff)

## Source of Truth Updated

The following specs now reflect the new behavior:

- `openspec/specs/pose-estimation/spec.md` (created)
- `openspec/specs/node-registry/spec.md` (updated)

## Mechanical Copy Verification

File content was moved/copied exclusively with native shell commands (`git mv`, `Move-Item`, `robocopy`); no artifact bytes passed through the model's Read/Write path.

**Mandatory readback** — recursive byte-level `diff -r`-equivalent, snapshot (pre-move source) vs archived destination:

```
=== READBACK: recursive byte-level diff -r (snapshot source vs archive destination) ===
(EMPTY DIFF — source and archived destination are byte-identical)
DIFF_STATUS=PASS
GitMvUsed=True
```

**Result: PASS** — empty recursive diff (byte-identical). The tree was moved via `git mv` (5 tracked files, all staged as `R100` 100%-similarity renames) plus the materialized untracked `verify-report.md`, with no alteration.

The `archive-report.md` is additive and excluded from the source/destination comparison.

## Archive Rationale

- `openspec/changes/pose-2d/` moved to `openspec/changes/archive/2026-09-04-pose-2d/`.
- Date prefix `2026-09-04` (ISO) per OpenSpec convention.
- The archive is an audit trail and will not be modified or deleted.
- No destructive deltas were merged (node-registry MODIFIED preserved all non-delta requirements), so the `rules.archive` warning about destructive merges is not triggered.

## SDD Cycle Complete

The `pose-2d` change has been fully proposed, specified, designed, implemented (8/8 tasks, TDD), verified (PASS), and archived. Ready for the next change.
