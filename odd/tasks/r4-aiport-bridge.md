# R4 — shared AI-adapter bridge and runner extraction (the parked refactor)

Objective: delete the duplication the M6 notes parked and spec.md still
lists verbatim: "the two adapters carry ~120 duplicated subprocess-bridge
lines and the two runners are near-mirrors — one shared
worker-bridge/runner extraction after the MVP" (spec.md, after-MVP
notes). A pure refactor: no behavior, message, protocol or wire change —
the existing suites are the safety net, and every surviving message is
byte-identical by construction.

Branch: `feat/develop` · Delivery: work-unit commits, no PR slices
(user standing), push on request · Test runner:
`.venv\Scripts\python.exe -m pytest -q --basetemp="$env:TEMP\aim-tmp"`
(two steps: suite ignores `tests/test_ai_hmr2_adapter.py`, then that file
alone) + `.venv\Scripts\ruff.exe check .`.

## Specs

- **S1.** New `adapters/ai/engine_bridge.py`: an `EngineWorkerBridge`
  owning the subprocess JSON-lines mechanics both adapters repeat —
  Popen flags (no-window, utf-8, bufsize 1, stderr DEVNULL), the reader
  daemon thread, the protocol-line filter (skip stray prints, empty
  lines; require a dict with `"status"`), the ready handshake, the
  request round trip, and the discard/shutdown teardown (close stdin,
  grace-wait, terminate, grace-wait, kill) that guards against orphaned
  VRAM. Timeouts differ per engine (120 s vs 600 s) and are constructor
  arguments, read at construction — the hmr2 timeout test patches the
  adapter module constant BEFORE constructing, and must keep working.
- **S2.** Messages raised through the bridge are byte-identical to the
  current ones: engine label ("HMR2.0"/"CondMDI"), the activity noun in
  the stopped-responding message ("extraction"/"fill") and the
  checkpoint path in the exit-before-ready message are constructor
  parameters; the typed error classes stay the adapters' own (passed in
  as factories). Worker scripts and the wire protocol are untouched;
  `.engine/` is never patched.
- **S3.** Each adapter keeps what is genuinely engine-specific: path
  discovery, `_validate`, the bootstrap payload, and its port methods —
  composing the bridge instead of repeating it. The known micro-difference
  (hmr2's `_request` asserts, condmdi's raises "worker is not running")
  unifies to the typed error: an unreachable programmer-error path,
  never a production or test observable.
- **S4.** New `adapters/ai/thread_runner.py`: a `ThreadedEngineRunner`
  base owning the batch-1 lifecycle both runners mirror — busy state,
  the job-onto-thread wiring (started→run, outcome→relay+quit,
  finished→cleanup, job reference retention), shutdown with engine
  release, `busy_changed`. The concrete runners keep their typed
  `start(...)` signatures, jobs and outcome signals; their test suites
  touch only the public surface, which does not change.
- **S5.** Behavior-preservation gates: both adapter suites and both
  runner suites pass with ZERO assertion edits except the one test line
  that reads `adapter._worker` (pinned lifecycle state moves with the
  mechanics — it becomes `adapter._bridge.worker`). Full two-step suite
  + ruff clean on every work-unit commit.
- **S6.** Docs: spec.md's parked-refactor sentence updated to the landed
  extraction in the same change set (the "after the MVP" condition is
  met — MVP closed, R1-R3 landed).

## Tasks

| ID | S#       | Route  | Status  | Commit |
| -- | -------- | ------ | ------- | ------ |
| T1 | S1,S2,S3 | inline | pending | — |
| T2 | S1,S2,S3 | inline | pending | — |
| T3 | S4       | inline | pending | — |
| T4 | S6       | inline | pending | — |

## Log

- **L1.** User, verbatim (2026-10-27): *"vamos con refactor del AIport"* —
  starting agenda item 4 (the parked AIPort refactor) after R3 (seam
  jitter damping, `1281182`) landed with measured constants.
- **L2.** Exploration (2026-10-27): the duplication is real and measured
  — condmdi's `_discard_worker`/`shutdown`/`_spawn` Popen block/
  `_read_lines`/`_next_protocol_line`/`_request`/`_ensure_worker` are a
  verbatim mirror of hmr2's (~110 lines; the adapter's own comment
  admits it: "mirrors the HMR2.0 adapter's subprocess lifecycle"),
  differing only in engine label, activity noun and timeout values
  (300/120 vs 300/600). The runner pair (`pose_runner.py`/
  `inbetween_runner.py`) repeats ~45 lines of batch-1 thread lifecycle
  verbatim; its suites are public-API only. Test coupling found: one
  monkeypatch of `hmr2_adapter._REQUEST_TIMEOUT_S` before construction
  (constructor-read timeouts survive it) and one read of
  `adapter._worker` after mid-request death (S5's single allowed edit).
- **L3.** Sizing (2026-10-27): medium (mechanical extraction, two parts,
  message byte-preservation demands diff-level care). Route: parent
  inline — no writer trigger (one behavior across shared files, and the
  whole verification is the parent running the suites between edits).
