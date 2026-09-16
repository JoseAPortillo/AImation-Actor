# Archive Report — phase-a-golden-poses

**Archived**: 2026-09-16
**From**: `openspec/changes/phase-a-golden-poses/`
**To**: `openspec/changes/archive/2026-09-16-phase-a-golden-poses/`
**Verdict at close**: PASS WITH WARNINGS — 0 blockers, 0 critical (per `verify-report`, Engram observation #910).

## Final State (at close)

- **Tasks**: 34/34 complete — every implementation task in `tasks.md` is marked `[x]` (all phases 1–5). Task Completion Gate passed.
- **Verification**: PASS WITH WARNINGS. Backend 18 targeted tests passed (1.16s), import-linter 4/4 contracts kept, mypy clean. Upload traversal fix (reject filenames containing `/`, `\`, `..` before write, defense-in-depth alongside `resolve_media_path`) applied and verified; 2 new traversal tests in `tests/api/test_api.py`. Confirmed by both the orchestrator launch prompt and the persisted verify report — no contradiction between sources.
- **Warnings** (recorded in `verify-report` observation #910 at verification time 2026-09-16 09:21:47; pre-existing, non-blocking):
  1. 501 contract unreachable in `pose.py` (`NotImplementedError` caught by `detection.py` → 400).
  2. ruff B904 in the get_frame endpoint.
  3. "Out-of-range frame" untested at HTTP layer (impl correct, no covering test).

## Engineered Artifacts Read (traceability)

| Artifact | Location | Observation ID (Engram) |
|----------|----------|-------------------------|
| proposal | `openspec/changes/phase-a-golden-poses/proposal.md` | — (file) |
| specs (5 deltas) | `openspec/changes/phase-a-golden-poses/specs/{domain}/spec.md` | — (files) |
| design | `openspec/changes/phase-a-golden-poses/design.md` | — (file) |
| tasks | `openspec/changes/phase-a-golden-poses/tasks.md` | — (file) |
| verify-report | Engram topic `sdd/phase-a-golden-poses/verify-report` | **#910** |

## Spec Sync (delta → main specs)

| Domain | Action | Details |
|--------|--------|---------|
| `frame-pose-detection` | Created | New capability — full-spec delta copied to `openspec/specs/frame-pose-detection/spec.md` (2 requirements) |
| `golden-poses-ux` | Created | New capability — copied to `openspec/specs/golden-poses-ux/spec.md` (5 requirements) |
| `video-media-serving` | Created | New capability — copied to `openspec/specs/video-media-serving/spec.md` (3 requirements) |
| `pose-estimation` | Updated | Native `sdd-archive-compose`: MODIFIED "Swappable estimator backend" (single-frame + frame-level confidence contract added); 4 unrelated requirements preserved byte-for-byte |
| `video-preprocessing` | Updated | Native `sdd-archive-compose`: MODIFIED "Source path validation" (shared `resolve_media_path` boundary, D3); 4 unrelated requirements preserved byte-for-byte |

Composition commands (native, zero exit):

```bash
gentle-ai sdd-archive-compose --canonical "openspec/specs/pose-estimation/spec.md" --delta "<LF-normalized temp delta>" --output "openspec/specs/pose-estimation/spec.md.compose-tmp" && mv ... spec.md
gentle-ai sdd-archive-compose --canonical "openspec/specs/video-preprocessing/spec.md" --delta "<LF-normalized temp delta>" --output "openspec/specs/video-preprocessing/spec.md.compose-tmp" && mv ... spec.md
```

### Compose Workaround Note

`sdd-archive-compose` (gentle-ai 2.9.1) rejected the as-authored delta files with `DELTA: delta spec declares no ADDED, MODIFIED, REMOVED, or RENAMED requirements`. Root cause isolated experimentally: the parser's line-anchored section regex does not tolerate CRLF line endings (RE2 `$` does not match before a trailing `\r`). The deltas in this change are CRLF. Workaround: the delta content was line-ending-normalized to LF into a **temp copy** for composition only; the original CRLF delta files were moved into the archive byte-identical (verified by empty `diff -r`). A future change whose deltas are written CRLF will hit the same compose refusal if the tool is not patched.

## Mechanical Copy Verification

- New main specs (`frame-pose-detection`, `golden-poses-ux`, `video-media-serving`): copy via `Copy-Item` → `diff -r` (GNU diffutils 3.12) → `Move-Item`. Empty diff = byte-identical. PASSED.
- Archive move: recursive snapshot → `git mv` → source absence confirmed → `diff -r <snapshot> <destination>`. Empty diff (status 0). PASSED — verbatim output in orchestrator result.
- `archive-report.md` is additive-only and excluded from the readback (did not exist in the source snapshot).

## Archive Contents

- proposal.md ✅
- specs/ (5 delta specs) ✅
- design.md ✅
- tasks.md ✅ (34/34 tasks complete)
- exploration.md ✅ (carried from explore phase)
- archive-report.md ✅ (this file, additive)

## Source of Truth Updated

The following main specs now reflect the new behavior:

- `openspec/specs/frame-pose-detection/spec.md`
- `openspec/specs/golden-poses-ux/spec.md`
- `openspec/specs/video-media-serving/spec.md`
- `openspec/specs/pose-estimation/spec.md`
- `openspec/specs/video-preprocessing/spec.md`

## SDD Cycle Complete

The change has been fully planned, implemented, verified, and archived. No CRITICAL issues blocked archive. Active changes directory no longer contains `phase-a-golden-poses`.