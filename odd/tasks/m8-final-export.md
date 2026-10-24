# M8 — Final Generative Export (FR-GEN-04)

Branch: feat/develop
Delivery: work-unit commits, no PR; test runner:
`.venv/Scripts/python.exe -m pytest -q --basetemp="$env:TEMP/aim-tmp"`

## Specs

1. **S1 — Export the approved timeline.** The GUI exposes a File-menu export
   action (Ctrl+E) that writes the currently approved timeline (keys and
   generated fills, whichever exist) with the same binary FBX conventions as
   the blocking export, preserving `frame_start`/`frame_end`.
   Acceptance: the wired exporter receives the controller's timeline and the
   user-chosen path; the writer path itself is already CI-covered.
   Checks: window tests + main-composition test.
2. **S2 — Honest refusals.** An empty timeline exports nothing and says why; a
   failed write is reported non-fatally with the session still usable; a
   cancelled file dialog saves nothing; a window without a writer reports the
   gap. Checks: window tests.
3. **S3 — Real composition.** The production window is wired to the real
   FBX writer adapter. Checks: `tests/test_main.py`.

## Tasks

| ID | Spec | Route | Status | Commit |
| -- | ---- | ----- | ------ | ------ |
| T1 | S1-S3 | inline | done | 7f883dc |
| T2 | S1 | inline | pending | Blender round-trip validation of the exported final file (manual, in .engine). |

## Log

- **L1.** User, verbatim: *"siguiente paso del roadmap."* The spec §4 roadmap
  lists **M8 — final generative export (FR-GEN-04)** as the step after the
  closed M7; the FBX writer exists and is tested, but no GUI export action
  exists yet. (Naming note: the root-motion feature doc `m8-root-motion.md`
  borrowed the M8 name; the spec's milestone M8 is this export.)
- **L2.** T1 (2026-10-24): `MainWindow` grew an `exporter: IOPort | None`
  dependency (`build_window` injects the real `BlenderFbxAdapter()`);
  `action_export` ("Export &FBX…", Ctrl+E) lives in the File menu and calls
  `export_fbx()`, which refuses honestly in the status bar (NFR-03 pattern):
  empty timeline ("no Golden Pose yet"), no writer configured, cancelled
  dialog; a failed write reports the error and the session stays usable.
  Success writes through the adapter with the default filename from the
  clip's stem. Seven new RED-first window tests + one production-composition
  test. Focused, full suite and Ruff green.

