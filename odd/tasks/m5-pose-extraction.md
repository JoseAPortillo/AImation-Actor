# M5 — Pose extraction pipeline (`AIPort` + captured frame + `QThread`)

**Objective:** give `K` a real extraction pipeline — capture the frame the
animator marked, run a pose engine **off the UI thread**, and write the
*remapped* production pose onto the timeline.
**Branch:** `feat/develop`, local delivery only (the user confirmed there will be
no pull requests, so the P/R-size heuristic and the chained-PR strategy do not
apply here).
**Runner:** `.\.venv\Scripts\python.exe -m pytest` · lint: `.\.venv\Scripts\ruff.exe check .`

**Scope note — what this unit does NOT deliver.** The real pose-engine adapter is
a separate, bounded task: it needs an external research repo plus multi-GB
checkpoints and `torchvision`, none of which are present. Ship the *contract*
now and the engine behind it later, so the engine lands as one file with no
caller changes (`O` in SOLID). That also means **FP16** and
`torch.cuda.empty_cache()` stay open: they are engine internals, not pipeline
behavior. `AIPort`, the frame capture, the single-frame `QThread` runner and the
remap all land here, verified with a deterministic engine.

**The engine changed after this unit shipped** (2026-10-16): it is **HMR2.0**, not
the plan's GVHMR — see S14-S16 and L19 below, and «Pose engine decision» in
`AGENTS.md`. The adapter's own tasks are **T10-T13**.

## Specs

- **S1.** `ports/ai_port.py` declares `AIPort`, the AI-engine seam: one abstract
  operation, `extract_pose(image, *, frame_index) -> WorldPose`. The module
  imports the standard library and the domain (`core`) only — never an adapter,
  never a third-party package (NFR-01).
- **S2.** The engine's input is **one decoded RGB frame**: `FrameImage` in
  `core/models.py`, carrying `width`, `height` and `rgb` (row-major RGB888
  `bytes`, top-left first). A pure domain type, because the port layer must never
  hand a Qt object to an engine.
- **S3.** `K` runs the engine on **only** the playhead frame — batch size 1 — and
  **never blocks the UI**: the request returns immediately and the result arrives
  through a signal (FR-CAP-05, NFR-02).
- **S4.** **At most one extraction runs at a time.** A `K` while an extraction is
  in flight is refused with an actionable message and marks nothing (NFR-03).
- **S5.** On success the extracted `WorldPose` is remapped with
  `build_production_pose(pose, skeleton)` and written with
  `mark_pose(state, frame, pose)` **at the frame it was extracted for**, even if
  the playhead has moved meanwhile (FR-CAP-06, FR-CAP-07).
- **S6.** A failed extraction is **non-fatal**: prior keys survive, the failure
  is reported with an actionable message, and **no key is written** at that frame
  (FR-CAP-07).
- **S7.** Marking with **no engine configured** reports and marks nothing. The
  neutral-pose placeholder M4 wrote is retired (FR-CAP-07, NFR-03).
- **S8.** The player exposes the frame **at the playhead** as an image on demand,
  so only a single frame buffer is ever held (plan §4: *"The AI only accesses a
  temporary bitmap when the capture key is pressed"*; FR-CAP-02).
- **S9.** Playback keeps streaming while the player renders the sink's frames
  itself: peak memory still does not scale with clip length (FR-CAP-02).
- **S10.** The frame handed to the engine **is** the frame at the playhead. A
  seek is asynchronous, so (a) a seek targets the middle of the frame's time slot,
  because a slot boundary resolves to the *previous* frame, and (b) a delivered
  frame that does not cover the requested position is **refused**, not extracted —
  capturing a neighbouring frame would silently write a pose the animator never
  looked at, and nothing downstream could detect it (S3, FR-CAP-05).
- **S11.** Opening a clip makes its **first frame capturable without playing it**:
  a freshly loaded player decodes nothing until playback starts once, so opening
  primes exactly one frame. The nudge is not reported as playback — it must not
  move the playhead or flip the transport (FR-CAP-04, NFR-03).
- **S12.** The captured frame **carries the frame index it belongs to**, and the
  key is written there — not at the playhead. S10's guard covers scrubs only;
  while the player plays, the timeline follows the backend's position events,
  which arrive far less often than frames, so the playhead can lag the pane by
  one to three frames. `grab_frame(fps) -> CapturedFrame(image, frame_index)`
  derives the index from the frame's own clip timestamps
  (`frame_index_of(start_us, fps)`), and `K` keys that frame and moves the
  playhead onto it, so the timeline catches up with what the animator sees. The
  playhead moves onto the captured frame *before* the request is admitted, so a
  refused `K` (S4) still leaves the playhead on the frame the pane shows: the
  playhead follows the pane, and only the *key* depends on the request being
  served (L17, advisory 1). A source that cannot establish the index (no
  timestamps, unknown frame rate) reports `None` and the capture keeps the
  playhead — degrade, never refuse (M5 L8's rule; S3, S5, FR-CAP-05, FR-CAP-07).
- **S13.** While the player plays, the playhead follows **the frame that was
  delivered**, not the backend's position: `frame_shown(int)` carries the index
  the source proved, and once a source has proved it can index a frame of the
  current clip, `position_changed` stops moving the playhead. Otherwise the
  number and the pane can disagree — measured on a real clip, a position event
  for an older frame still arrived after the pause and walked the timeline back
  behind the frame on screen, leaving a key at 16 with the playhead at 15 and
  `Delete` removing nothing. A frame delivered while paused (a seek, or the
  priming nudge of S11) never moves the playhead: the animator's own navigation
  owns it then. A clip that cannot be indexed keeps the old
  position-driven behavior (S3, FR-CAP-03, FR-CAP-04).

### Adapter specs (added 2026-10-16, after the backend decision in L19)

- **S14.** The engine behind `AIPort` is **HMR2.0**, not the plan's GVHMR, and it
  stays behind the port **unchanged**: the adapter lands as one module with no
  caller edits (`O` in SOLID), and `extract_pose(image, *, frame_index)` keeps its
  current signature. It runs **outside the application process**, in its own
  Python 3.10 environment, because its stack pins versions this interpreter does
  not carry — the same shape and the same reasons as the Blender read path
  (`FR-IMP-03`). Nothing on this side of the boundary imports the engine.
- **S15.** Before the adapter is specified in detail, its two **unmeasured**
  properties are measured on the real box, because either can change the design:
  **(a) hip-height stability** — the absolute hip height `build_production_pose`
  consumes comes from a weak-perspective estimate, so monocular scale is a learned
  guess rather than a measurement, and an unstable height is immediately visible in
  the viewport; **(b) cost** — no VRAM or per-frame latency figure is published for
  HMR2.0, and the target is ≤ 10 GB at batch 1. Measured, not assumed
  (`spec.md` §4.13).
- **S16.** Weights and the body model are **user-supplied and never vendored**: the
  HMR2.0 checkpoint and the SMPL `.pkl` are downloaded and registered by the user,
  and no weight file is tracked in this repository. A missing engine, environment,
  checkpoint or body model is an **actionable non-fatal failure** through the
  existing typed path (S6, S7) — never a crash and never a silent placeholder.
  The licensing posture this implies is recorded in `spec.md` §4.14, not assumed.

## Tasks

| ID | Spec | Route | Status | Evidence |
| -- | ---- | ----- | ------ | -------- |
| T1 | S2 | inline | ✅ done | `FrameImage` in `core/models.py` (C1) + `tests/test_core_models.py` |
| T2 | S1 | inline | ✅ done | `AIPort` in `ports/ai_port.py` (C1); `tests/test_layering.py` covers the port (`rglob` over `ports/`); `tests/test_ports_ai.py` |
| T3 | S3,S4,S6 | inline | ✅ done | `adapters/ai/pose_runner.py` (C2) + `tests/test_ai_pose_runner.py` |
| T4 | S8,S9,S10,S11 | inline | ✅ done | `video_player.py` `QVideoSink` + `grab_frame` + priming (C3) + `tests/test_gui_video_player.py`; real-clip probe |
| T5 | S5,S6,S7 | inline | ✅ done | controller wiring (C4) + `tests/test_gui_capture_controller.py` |
| T6 | S3 | inline | ✅ done | `engine=` injection + `closeEvent` shutdown (C4) + `tests/test_gui_main_window.py` |
| T7 | S3,S5 | inline | ✅ done | `tests/test_ai_extraction_pipeline.py` (C4) — real `QThread`, real fade, real remap |
| T8 | — | inline | ✅ done | this document + `spec.md` statuses + the M4 log entry (C5) |
| T9 | S12,S13 | inline | ✅ done | `CapturedFrame` (`core/models.py`), `frame_index_of`/`frame_shown`/`grab_frame(fps)` (`video_player.py`), the key and playhead fix (`capture_controller.py`) (C6); regression tests in `tests/test_gui_capture_controller.py` and `tests/test_gui_video_player.py` (C7, the 7 independent pins); real-clip probe (L16); independent verification (L17); native review approved, authority burned (L18) |
| T10 | S15 | inline | ✅ done | **Measurement gate — shut 2026-10-19** (L23). Python **3.10.20** via `uv`; torch 2.14.1+cu130 sees the GPU; the explicit inference set installed — `detectron2` skipped (it is only an `extras_require`), **`chumpy` IS required** and only the `mattloper/chumpy` git fork works (PyPI 0.70 cannot import under numpy 2), plus `webdataset` added for `hmr2.datasets`; **both** checkpoints fetched and measured on **RTX 3080, 10,240 MiB**: **VRAM 2.67 GB allocated / 2.74 GB reserved at batch 1, identical for `a` and `b`** (26% of the target — FP16 not required for it); **warm per-frame 81.0-94.4 ms end-to-end for `b`** (median 83.9; `a` 83.0-85.8; ≈ 40 ms of it CPU preprocessing, ≈ 44 ms GPU); cold ≈ 330 ms both. **Hip height: the per-frame estimate is NOT keyable raw** (0.59-0.99 m within one person on gymnast footage); **the betas=0 SMPL template pelvis→contact = 0.9385 m is the constant anchor** — anchor decision parked for T12. Measurement note: first pass used the wrong joint indices (the wrapper's joints are OpenPose BODY_25 ordered: 0=Nose, 8=MidHip, 19-24 feet) and was corrected before these numbers were recorded (L23); persisted to `.engine/t10_measurements_{a,b}.json` (untracked, `.engine/` is gitignored) |
| T11 | S14,S16 | inline | ✅ done | **Landed 2026-10-19** (L24, C12): `adapters/ai/hmr2_worker.py` (engine-side half, runs in `.engine/venv` 3.10) + `adapters/ai/hmr2_adapter.py` (`AIPort` impl, app-side, stdlib only) — line-JSON stdin/stdout protocol, **persistent worker** (2.7 GB checkpoint loads once; ~84 ms/`K` after), FP16 default + `empty_cache()` per request, the four Windows loader fixes baked in (`HOME`=engine root, `torch.load weights_only=False`, `init_renderer=False`, `PYOPENGL_PLATFORM=win32`, plus the `webdataset` import). Typed actionable failures for a missing interpreter/checkpoint/body-model/GPU and worker death; idempotent `shutdown()`, wired into `PoseExtractionRunner.shutdown`. Route: inline (one understood unit, no writer-trigger reason). CI proves the bridge against a faithful fake worker (`tests/fake_hmr2_worker.py`); the real engine stays manual-probe-only (the Blender read path's discipline) |
| T12 | S5,S14 | inline | ✅ done | **Landed 2026-10-19** (L24, C12, with T11 — one coherent behavior; conversion tests included). Engine result → `WorldPose`: hip height = **template anchor** (the worker computes the betas=0 template's pelvis-to-contact distance at startup; T10 found the per-frame estimate not keyable), per-joint local quaternions = SMPL's `global_orient`→`Pelvis` + the 23 `body_pose` rotations **named with SMPL's canonical names** (the production skeleton mirrors SMPL's chain under `Main`), re-expressed **Y-up→Z-up** by `conjugate_y_up_to_z_up` (`R_x(+90)⊗q⊗R_x(-90)` — the exact inverse of the FBX writer's `q_fbx = A⊗q_domain⊗A⁻¹` with `A = R_x(-90)`, verified numerically incl. the writer round trip); world displacement dropped (`x=y=0`) |
| T13 | S14, S16 | inline | done (2026-10-19) | C13: window wiring — `build_window` injects the real `Hmr2Adapter` plus a rig source over its bind offsets; `core/production_skeleton.py` (the SMPL chain mirrored under `Main`: 23 canonical names + kintree parents) builds the rig from bind offsets the worker computes from the body model's template buffers and rides on the ready line; the `CaptureController` adopts it at the first extraction (missing/broken offsets = typed failure, nothing marked; pane stays blank until then). FP16 holds as the default via **autocast** around the backbone, the SMPL recovery and the template anchor call (plain fp16 weights raise dtype mismatches — probe-verified three ways). Real-engine e2e evidence (manual probe): ready ~12 s, VRAM flat 1328.1 MiB across 6 keys (growth 0.0; 2.66 GB fp32), fp16 vs fp32 mean 0.84 mm / max 3.68 mm per joint, bridge round trip ~130 ms per key; the probe caught a double SMPL-to-domain conversion (the worker now reports SMPL-frame offsets; the adapter owns the conversion) and the pre-ready fp16 template crash. 124 tests green, ruff clean. Spec 0.4.8 + open question 10 resolved. (L26) |

> Note (2026-10-19): T11 and T12 shipped as **one work unit** (commit C12) rather
> than two: the bridge without the conversion could not satisfy
> `AIPort.extract_pose`'s contract, and the conversion could not be tested
> against the real result shape without the bridge. The ~400-lines heuristic
> yields two tasks' worth; the smallest-coherent-behavior rule wins. T13 has since
> landed as its own work unit (C13).

## Log

- **L1.** User, verbatim: *"haz merge a main y continua trabajando en develop
  después"* — after the M4 merge, keep working on `feat/develop`.
- **L2.** User, verbatim (standing constraint): *"estamos solos, no habrá PR"*.
- **L3.** User chose, verbatim: *"Pipeline completo con motor falso"* — build
  `AIPort` + frame capture + `QThread` batch 1 + remap, verified end-to-end with
  a deterministic engine; the real GVHMR adapter stays a separate bounded task
  behind a typed error (the `BlenderFbxAdapter` precedent).
- **L4.** Ground truth established before writing (see Engram
  `milestone/m5-pose-extraction`): `ports/ai_port.py` and both `adapters/ai/*`
  files are one-line docstrings; GVHMR is not vendored and no weights are
  tracked; `torch` **is** installed in `.venv` but `torchvision` is **not**;
  `QVideoWidget` cannot yield frames, so capturing a marked frame requires the
  player to move to `QVideoSink` and render the frames itself — a deliberate
  change to code M4 already verified.
- **L5.** Accepted requirement change (from L3): `K` no longer writes a neutral
  placeholder. Per FR-CAP-07 a failed extraction must *"keep prior keys and
  report"*, so a frame whose pose was never extracted must not gain a key. M4's
  placeholder had no spec backing of its own — it was explicitly documented as
  temporary ("until GVHMR extracts a real pose (M5)").
- **L6.** Gates at the end of the implementation pass: **140 tests, 0 failures,
  0 errors, 0 skipped**; `ruff check .` clean. Mutation check on the stride
  handling: reading the `RGB888` buffer flat (instead of row-by-row) broke
  `test_a_frame_becomes_a_flat_rgb_buffer` and the odd-width stride test
  (`b'\x00\x00\x00' != b'\x00\xff\x00'`), proving those tests have teeth; the
  mutation was reverted.
- **L7.** **Real-clip verification found two real bugs**, which is exactly why
  the manual probe exists — the unit tests could not see either, because both are
  properties of a live media backend:

  1. **A seek landed on the wrong frame.** `seek_frame` targeted
     `round(frame / fps * 1000)`, which is the frame's *slot start*. A boundary
     resolves to the previous frame: on this 24 fps clip, asking for frame 5
     (208 ms) delivered the frame that ends at 208.33 ms — frame 4.
  2. **The capture raced the seek.** `setPosition` returns before the decoder
     delivers anything, so `grab_frame()` right after a scrub returned the frame
     still on screen: the **previous** position's. Measured on the real clip, the
     engine received the frame for a neighbouring position, and nothing
     downstream could tell — the animator would see the right pose and capture
     the wrong one.

  Measured ground truth that made both provable: `QVideoFrame.startTime()` /
  `endTime()` are populated by this backend and exact — the frame answering a
  seek to `P` ms has `end_us == P * 1000`. `ffmpeg` independently confirmed the
  clip is not static (four distinct MD5s at 0/208/500/1250 ms), so an identical
  fingerprint at two positions could only mean a stale frame.

- **L8.** Fixes, added as specs S10 and S11 rather than as silent patches:
  `seek_frame` now targets the **middle** of the slot (`frame_time_ms`, with a
  test over 200 frames asserting the target is strictly inside the slot), and
  `grab_frame` hands a frame over only when its span covers the requested
  position — a frame without usable timestamps is passed through rather than
  blocked, so an unusual backend degrades instead of refusing everything.
  Separately, opening a clip **primes** one frame (S11): measured,
  `frames_before_any_play == 0`, so without priming the animator's very first
  `K` — after opening and scrubbing, never pressing Space — found nothing to
  grab. The nudge is suppressed from `playback_changed`, so it cannot move the
  playhead off frame 0.
- **L9.** Verification after the fixes, on real clips through the real window,
  the real player and the real `QThread` runner with a deterministic engine:

  - **The primary workflow works**: open → scrub → `K`, never pressing play.
    `frame_available_without_playing: true`, `playhead_after_open: 0`,
    `playback_reported_during_priming: []`.
  - **The capture is tied to its position and is deterministic**: frame 12
    captured, then frames 30 and 5, then frame 12 again — the two frame-12
    captures share a fingerprint (`d376db8fc33b`) and all three frames differ
    (`same_frame_repeats_itself: true`, `different_frames_differ: true`).
  - **The race is closed, not narrowed**: 15 captures with delays of
    0/10/30/60/120 ms after a scrub. At 0 ms all three were refused; at 10 ms two
    were refused and one was correct; from 30 ms on all landed. **Every capture
    that landed was the correct frame** (`race_never_wrong: true`). The refusals
    surfaced as `Could not read the frame at the playhead.` — the session reports
    honestly instead of writing a plausible wrong pose.
  - **FR-CAP-02 holds with the sink in the path**: peak working set
    **272.0 MiB for the 2 s clip vs 275.1 MiB for the 60 s clip** — 30× the
    length and 30× the frames scanned (47 → 1404) for **+3.1 MiB**. Buffering
    would have cost ~332 MB.
  - **Domain invariants hold end to end**: `main_untouched == [0.0, 0.0, 1.0]`
    (the capture never writes the animator's world control), and the deterministic
    engine's hip height of 140 with a Pelvis bind of 100 produced a Pelvis offset
    of exactly `40.0` — the offset-from-bind convention, measured.
  - `failures: []` in the clean pass; all four marks keyed with no `_BUSY`
    refusal.

- **L10.** Gates after the fixes: **150 tests, 0 failures, 0 errors, 0 skipped**;
  `ruff check .` clean. The suite grew by 10 tests, all pinning S10 and S11.

- **L11.** Work units on `feat/develop` (local delivery only, nothing pushed),
  with the **per-commit isolation evidence** — each one was checked out into its
  own detached worktree and run there with `PYTHONPATH` pointing at that
  worktree, so a green run could not come from importing the repository instead:

  | unit | commit | contents | suite there |
  | ---- | ------ | -------- | ----------- |
  | C1 | `1f78a6b` | `FrameImage` + `AIPort` + their tests | 123 ✅ |
  | C2 | `2d19f8b` | `PoseExtractionRunner` + its tests | 129 ✅ |
  | C3 | `0d0f1f9` | `QVideoSink` capture, priming, playhead attribution + its tests | 142 ✅ |
  | C4 | `a028f17` | controller/window wiring + end-to-end tests | 150 ✅ |
  | C5 | this document | spec statuses, this file, the M4 log entry | — |

  Every step: `failures: 0`, `errors: 0`, `skipped: 0`, `ruff` exit 0. C5's own
  hash cannot be written here, because a commit cannot contain its identity.

- **L12.** Still open, deliberately: `torchvision` is not installed and no
  checkpoints are vendored, so the real GVHMR adapter cannot be built or verified
  yet. ProRes (S10 of the M4 document) was never exercised — only H.264 — and
  that limitation carries over unchanged. FP16 and `torch.cuda.empty_cache()`
  remain engine internals (see the scope note above).
- **L13.** How this evidence was gathered, because it changed mid-milestone. The
  shell in this session has been unreliable: `git commit` printed a complete,
  perfectly formatted success line — a new hash and `2 files changed` — while the
  repository never received the commit, and `git log` proved only two of the four
  units existed. An earlier "C3 isolated: 23 tests, 0 failures" was also worthless
  without my noticing it: the stash had stripped the new tests, so that was the
  *old* player against the *old* suite (12 + 11 = 23), a green run of the wrong
  code. Every claim in this document is therefore now read back from a file the
  tool itself wrote — pytest's `--junitxml`, git answers serialised to JSON by a
  script, per-commit runs in detached worktrees — never from the rendered
  terminal. The commit step now asserts, against `git`'s own output, that HEAD
  actually moved and that the commit contains exactly the intended files; had it
  been used from the start, the lost C3 would have been caught immediately. This
  repeats the lesson already recorded as L22 of the M4 document (the `end.y`
  phantom): bytes over console, every time.

- **L14.** Reopened by the user, verbatim: *"vamos a ver el siguiente paso del
  proyecto"*, and on the choice offered for the next step,
  *"Arreglar el blocker de M5"*. The blocker was the one recorded by the
  independent verification of this milestone (Engram #1091 / #1093): play →
  pause → `K` wrote the pose of a frame **1-3 positions early**, silently. This
  document had marked T1-T8 done without recording that finding at all, which is
  the real defect in the record: a milestone whose verification reported a blocker
  is not finished, and the verification belongs in this log, not only in Engram.

- **L15.** The fix, in two specs rather than one patch, because the probe found
  two distinct violations of the same invariant (image ↔ frame index):

  1. **S12 — the key belongs to the frame that was captured.** Root cause
     confirmed at line level: `play()` (`video_player.py:206`) sets
     `_wanted_us = None` ("live playback means live frames") and `pause()`
     never re-arms it, so `grab_frame`'s coverage guard — the S10 protection
     against extracting a neighbouring frame — was **dead after any playback**;
     `capture_controller.py` then keyed the delivered image at `self._frame`, the
     position-derived playhead. The frame now carries its own index, proved from
     its clip timestamps (`CapturedFrame`, `frame_index_of(start_us, fps)` =
     `round(start_us * fps / 1e6)`), and `K` keys that frame and moves the
     playhead onto it. A source that cannot prove the index reports `None` and
     the capture keeps the playhead: degrade, never refuse (L8's rule).

  2. **S13 — the playhead belongs to the frame, not to the position event.** This
     one was found by this log's own re-run of the real-clip probe, not by the
     unit tests: with only S12 in place, 2 of 12 rounds left the key at 16 with
     the playhead at 15. A position event for an older position still arrives
     after the pause, and while the controller still believed it was playing it
     walked the timeline back behind the frame on screen — `Delete` would then
     remove nothing and the number would lie about where the key is. So the
     player now emits `frame_shown(int)` for a frame it can index, and once a
     source has proved that for the current clip, `position_changed` stops moving
     the playhead. A clip that cannot be indexed keeps the old behavior.

  Both were written test-first. RED was observed for the real defect, not only
  for an import: `tests/test_gui_capture_controller.py::
  test_a_mark_after_playback_keys_the_frame_on_screen` failed with
  `assert (40,) == (43,)` — the playhead's frame keyed instead of the pane's —
  before the controller was touched.

- **L16.** Verification, in the same shape that found the blocker. Gates: **161
  tests, 0 failures, 0 errors, 0 skipped** (`--junitxml` readback, not the
  console), `ruff check .` clean. Real backend, real clips, the real window and
  the real `K` path, driving `play → pause → K` six times per clip
  (`clip.mp4` 48 frames, `long_clip.mp4` 1440, both 24 fps):

  | clip | key mismatches | playhead lag per round | key == pane | image == pane | playhead on the key |
  | ---- | -------------- | ---------------------- | ----------- | ------------- | ------------------- |
  | `clip.mp4` | **0 / 6** | 0,0,0,0,0,0 | 6/6 | 6/6 | 6/6 |
  | `long_clip.mp4` | **0 / 6** | 0,0,0,0,0,0 | 6/6 | 6/6 | 6/6 |

  Before the fix the same probe measured `key_mismatches` with the playhead
  behind by 1-3 frames in most rounds (the verifier's independent run: 70
  captures, 29 agreeing keys). The probe itself is **not committed**: it needs a
  display, a media backend and a clip, exactly like the Blender read path
  (NFR-04), so it stays a manual check; the regression coverage that CI can run
  is the new fake-driven tests for S12 and S13.

- **L17.** The fix was then verified by an **independent verifier** — a fresh
  agent with no memory of this work, given only this document, the baseline
  commit `187b822` and the probe command shapes, working in its own scratch copy
  (`mktemp -d`) so nothing it ran could reach the repository.

  **Verdict: no blockers, S1-S13 all met.** It also reproduced the blocker by
  itself, which is the part that matters — the finding is not this log agreeing
  with itself:

  | run | clip | key != pane | key != engine image | rounds |
  | --- | ---- | ----------- | ------------------- | ------ |
  | baseline `187b822` | `clip.mp4` | **6 / 6** | 0 | 6 |
  | baseline `187b822` | `long_clip.mp4` | **6 / 6** | 0 | 6 |
  | candidate | `clip.mp4` | **0 / 6** | 0 | 6 |
  | candidate | `long_clip.mp4` | **0 / 6** | 0 | 6 |

  `engine_sha_eq_pane: true` in **every** baseline round, while the key was wrong
  in all twelve, nails the diagnosis to the index and not the pixels: S10's guard
  was still handing over the frame the animator saw, and only the *frame number*
  the key was written at was wrong. So this was never a capture bug — it was an
  attribution bug, exactly as L15 recorded it.

  Both specs are load-bearing, and the verifier's numbers show it rather than
  asserting it: in candidate `long_clip.mp4` round 5 the playhead sat at 130 with
  the pane on 131 (`playhead_at_k: 130`, `pane_frame_ffmpeg: 131`), and `K` wrote
  `key_frame: 131`. S13 keeps the playhead on the delivered frame while playing,
  but a frame can still arrive while paused (S13 explicitly does not move the
  playhead then), and S12 is what keeps the *key* honest at that boundary. Either
  spec alone would have left a hole.

  The verifier delivered **7 durable regression pins**, which CI can run where
  the manual probe cannot (it needs a display, a media backend and a clip):
  four in `tests/test_gui_capture_controller.py` (clamping an out-of-range
  captured index; indexing re-proved per clip; a proved index owning the
  playhead; a refused `K` writing no key and issuing no request) and three in
  `tests/test_gui_video_player.py` (`frame_index_of`'s boundaries and its
  no-answer cases; the S10 seek targets unchanged from the baseline;
  a frame without a frame rate degrading to `None`). They were committed in C7
  **byte-for-byte** as delivered: the verifier's files were checked to be the
  workspace files plus a tail (2713 B and 1325 B, verified byte-identical after
  the append), so no part of them was paraphrased, reformatted or "improved" in
  transit. The last of these pins the previous behavior the fix shares code with
  — `frame_time_ms` — which the test-first policy requires.

  Gates after C7, read back from `--junitxml`: **168 tests, 0 failures, 0 errors,
  0 skipped**; `ruff check .` exit 0. That is L16's 161 plus the 7 pins, and the
  7 are the only thing that changed in the suite.

  **The four advisories, and what was done with each** — all recorded here rather
  than quietly fixed, because two of them are *deliberate* behavior and the other
  two are not defects:

  1. **A busy-refused `K` moves the playhead** onto the captured frame, where the
     baseline left it alone. This is intended, and S12 now says so. The playhead
     tracks the *pane*; the key is what depends on the request being served. The
     alternative would leave the playhead lying about what is on screen precisely
     when the animator is about to retry — and the retry would then key the frame
     they were not looking at. The verifier rated it an advisory, not a blocker,
     and `test_a_refused_mark_writes_no_key_and_leaves_the_timeline_intact` now
     pins the part that must hold: no key is written and no request is issued.
  2. **L16's `playhead lag 0,0,0,0,0,0` is a post-`K` figure.** The verifier
     measured a pre-`K` lag of -1 in one candidate round, which S12 then
     corrected at `K`. L16's table must not be read as "the pre-`K` playhead never
     lags" — that is false, and this entry is the correction.
  3. **FR-CAP-02 was not re-measured this pass.** The fix adds one `int | None` to
     a frozen dataclass and one signal, so it cannot move peak memory; L9's
     measurement (272.0 MiB vs 275.1 MiB across a 30x clip-length difference) was
     taken through the same sink path and stands. Not re-running it is a gap in
     this pass's evidence, not a disagreement with it.
  4. **`frame_index_of` inherits Python's `round()`** — half-to-even, so a
     timestamp landing exactly on a half-slot would round to the even frame. The
     verifier could not reach it: a real slot start never falls exactly on a half
     slot. Left as documented rather than "fixed" into a third unrequested
     behavior change; the boundaries that *are* reachable are pinned by the first
     of the seven tests.

- **L18.** The last step before this task can be called done: the **native review**
  (RDD on, global), over the whole slice `187b822..7e22c5e` — four commits, 9
  paths, 700 changed lines — and not over one file of it. Lenses
  `resilience,readability,reliability`, chosen because the change touches the
  capture path's async ordering, its frame attribution and the `VideoSource`
  contract; `risk` was left out deliberately (no stored data, no credentials, no
  irreversible effect — the keys are in-session UI state, and the changed protocol
  has a single implementer updated in the same change). The tier was escalated to
  `high` on item 4 (async signal ordering across the play/pause boundary) rather
  than accepted as `medium`: a wider range diluted by tests and docs must not
  lower a candidate already known to be high risk.

  Consent was relayed losslessly and **granted**. `review-080c6543e28c6cbe` froze
  the three lenses with a 200-line correction budget.

  **Verdict: approved, authority burned** (`gentle-ai.review-acknowledged/v1`).
  No blocker, and **no finding opened a correction** — the correction budget was
  never touched. Ten advisory findings, all `disposition: informational`. Three
  distinct follow-ups come out of them, and none of the three is a defect in what
  was specified here:

  1. **The caller-supplied `fps` seam** (`R4-1`, `R2-fps-provenance`, `R3-2`, all
     WARNING). `grab_frame` derives the index from the rate the *caller* passes,
     and the controller only ever passes `self._state.fps` — the default-24
     fallback when the backend reported none (FR-CAP-03). So the degradation S12
     documents ("unknown frame rate -> `frame_index` `None`") cannot fire on the
     real call path: it needs `fps <= 0.0`, which the controller has no path to
     pass. The player's signal path and its grab path can also disagree about one
     and the same frame's index. Three lenses found one seam, not three bugs.
  2. **The one-way `_frames_are_indexed` latch** (`R4-2`, `R3-4`, WARNING). The
     latch is set on the first delivered frame — *before* the `not self._playing`
     return — and re-armed only by a new clip load, and it is not scoped to the
     clip it was proved for. Once set, `position_changed` stops moving the
     playhead for the rest of that clip with no watchdog, timeout or re-arm, so a
     backend that stops delivering usable timestamps mid-playback freezes the
     playhead instead of falling back. `R3-4` rates it a gap rather than a
     regression: the baseline's `position_changed` path was unguarded in the same
     way.
  3. **Test and observability hygiene** (`R3-1` WARNING; `R3-3`,
     `R2-duplicate-index-pins`, `R2-divergent-fake-contract`, `R4-3`,
     SUGGESTION). The metadata -> `_fps` -> `frame_shown` link is pinned only
     through the private attribute, so a regression that stops assigning `_fps`
     would leave every pin green while S13 dies in the real player; the refusal
     pin never asserts the playhead, so the documented refusal path where the
     index *is* known and the playhead *does* move has no fake-driven test;
     `frame_index_of`'s boundaries are pinned three times over; and the
     `_FakeSource` copies model `VideoSource` two mutually exclusive ways (one
     wraps a possibly-`None` frame even though `CapturedFrame.image` is
     non-optional).

  All ten are carried forward in `spec.md` §6 as follow-ups, not fixed here: none
  is a defect in the specified behavior, and amending the candidate to chase them
  would have invalidated the very review that found them.
- **L19.** **The pose engine changed: it is HMR2.0, not GVHMR.** User decisions,
  verbatim, in order:
  1. *"no se va a distribuir, es uso propio, al menos por ahora, pero si va a
     complicar el uso y funcionalidad buscamos otra alternativa similar de que sea
     libre de uso."*
  2. *"Necesito que la captura sea lo mas precisa posible, MedaPipe BlazePose me
     dará resultados similares a BVHMR?"*
  3. *"vamos con la primera opción pero haz un estudio mas exaustivo porfavor y
     dame conclusión de lo que encuentres y que encaje en el proyecto."*
  4. *"Confirmo HMR2.0 y sigo"*.

  **The premise this unit shipped under was false.** FR-CAP-05 said *"GVHMR
  processes **only** that isolated frame"*. GVHMR is **sequence-native**: its world
  trajectory starts at `[0,0,0]` and is a cumulative sum of per-frame root
  velocities, its foot-locking updates frame by frame, and its camera frame comes
  from visual odometry. At `F=1` — exactly what a Golden Pose mark produces —
  those mechanisms are not weakened, they are **undefined** (`compute_cam_angvel`
  returns shape `(0,6)`), and the shipped demos accept video only. The plan's
  "batch 1, one frame" was a requirement written for the wrong class of model.

  **GVHMR's advantage is the world, not the joints.** Its own ablation (RICH) is
  the proof: removing foot-locking leaves local `PA-MPJPE`/`MPJPE` **identical**
  (`39.5`/`66.0`) while only the world metrics move (`WA-MPJPE100` `78.8 → 89.3`,
  foot-sliding `3.0 → 6.8`). This tool discards world placement by design —
  `Main` ships in place at `(0,0,0)` — so the machinery that makes GVHMR GVHMR is
  unreachable here, and it costs ViTPose (2.55 GB) plus a detector to carry.

  **HMR2.0 is GVHMR's own backbone**, single-image by design. On 3DPW, `PA-MPJPE`:
  GVHMR `36.2 mm` **with 120 frames of context**, against HMR2.0a `44.5 mm` with
  **one** — and the released checkpoint is the `b` variant at **`54.3 mm`** on that
  same column. *(L22 corrects my first reading of this: 3DPW `PA-MPJPE` is one of
  seven reported columns, `b` wins the other six, and the authors call it the more
  robust model — see L22.)* So the switch costs 8–18 mm *that the single-frame
  path could not have had anyway*, in exchange for a lighter pipeline. Honest
  limits recorded with it: `PCK@0.05` on `LSP-Ext` is `0.53` — which is the
  **best** figure reported at that threshold (*"1.6× better than the second
  best"*), not a shortcoming; the real limit is that **absolute** accuracy still
  warrants an animator cleanup pass per Golden Pose.

  **Two corrections to the survey that drove this**, both verified against primary
  artifacts rather than restated: 4D-Humans is **MIT** (not Apache-2.0) with a
  **2.7 GB** checkpoint (not 27 GB), and it does **not** need `detectron2` at
  inference — that package only produces bounding boxes, and the animator already
  chooses the frame, so the largest install blocker dissolves.

  **The licence did not improve, and that is recorded rather than glossed.** HMR2.0
  inherits GVHMR's constraint through the SMPL body model and `smplx`: code MIT,
  model non-commercial-only and non-redistributable. Since the user's position is
  personal use, this is acceptable — but the consequence (distribution needs a
  Meshcapade licence) is written down in `spec.md` §4.14, not left implicit. Every
  body-model estimator surveyed inherits the same terms; only landmark models
  (MediaPipe BlazePose, Apache-2.0) avoid them, at the price of no body model and
  **no published 3D accuracy metric at all**.

  **What changed in the tree** (C10): FR-CAP-05 corrected, §4.12–4.14 opened (the
  decision, the two unmeasured properties, the licensing posture), the pose engine
  added to the supersessors list in `AGENTS.md` with its own decision section
  mirroring the FBX precedent. *(At the time of C10 the plan was left untouched,
  exactly as the FBX SDK supersession had done; **L20 reverses that** — the user
  asked for the plan to be annotated in place, so a reader who lands mid-document
  cannot walk away with a rejected technology. The rest of L19 stands.)* Five
  docstrings that named a
  swappable engine in *generic* layers (`ai_port`, `pose_runner`, `main`,
  `main_window`, `neutral_pose`) were made engine-neutral instead, and the orphan
  stub `gvhmr_adapter.py` became `hmr2_adapter.py` — nothing imported it, so the
  rename is inert.

  **Plan for the adapter: T10 gates everything.** Two properties are unmeasured and
  either can change the design (hip-height stability under monocular scale, and
  VRAM/latency against the ≤ 10 GB target), so they are measured **before** the
  adapter is specified in detail — T10 — and only then do T11–T13 get their route
  and their detail.
- **L20.** **The plan is now annotated in place, and that replaces the old
  "leave the plan untouched" convention.** User instruction, verbatim: *"modifica
  el plan para que no haya confusiones en el futuro con respecto a FBX SDK de
  autodesk y arranca con T10"*.

  **Why the old convention was wrong.** L19 recorded the plan as deliberately
  untouched, on the reasoning that the FBX SDK supersession had done the same.
  That reasoning was circular: the FBX precedent was not a decision, it was an
  omission that had already been sitting there unnoticed — the plan named
  *Autodesk FBX Python SDK* at two places and never said it was rejected. Copying
  it propagated the defect instead of fixing it. A reader who opens the plan
  mid-document (which is what people and agents actually do) had no way to learn
  that either technology was dead.

  **Scope note — I extended past what was asked, deliberately.** The user named
  the Autodesk FBX SDK. The identical defect existed for GVHMR, whose
  supersession was decided *in this same unit* (L19): the plan recommended GVHMR
  as the technology stack, asserted the false single-frame premise, and repeated
  the name four more times. Annotating one and not the other would have been
  strictly worse than annotating neither, because it would have implied the
  unmarked one was still current. Both are marked. Easy to revert if the user
  wants only FBX.

  **What landed.** The plan (192 → 220 lines) gained: a **top notice** with a
  table naming both supersessions, their replacement, and the authority in
  `AGENTS.md`; and **inline markers on every affected sentence** — the two
  technology-stack bullets and the sparse-keyframe paragraph struck through
  (`~~…~~`) so the original wording stays visible and auditable, and the
  remaining references corrected in place. The false premise at §2 keeps its
  **why**: GVHMR is sequence-native, so one frame is undefined rather than
  weakened. The unverified *"GVHMR requires at least 6 GB of VRAM"* is now
  labelled as an unverified community figure rather than a requirement.
  `AGENTS.md` gained the source-of-truth clause, the corrected exceptions list,
  and a new **Superseded-plan discipline** convention codifying the three-part
  shape (decision section + notice row + inline marker) for the next time.

  **Rule this establishes:** a supersession is never recorded by omission. The
  plan keeps its history in plain sight, struck through and pointed at.

  **T10 started in the same turn.** Machine survey, before any install: GPU is an
  **RTX 3080 with 10,240 MiB** — the ≤ 10 GB target is the actual hardware, not a
  hypothetical. `torch 2.14.1+cu130` already works in the repo venv, so the cu130
  index is proven on this box. **No usable Python 3.10 as a base:** `E:\Python310`
  exists but has no `python.exe` (only `Lib`, `Scripts`, `Tools`), and
  `E:\Python310_old\python.exe` is a stray 3.10.4 install not to be depended on.
  The chosen path is **`uv` (0.11.32, already installed)** managing a standalone
  CPython 3.10 — reproducible and independent of the user's ad-hoc interpreters.
- **L21.** **T10 execution — the engine is installed, imports, and sees the GPU.
  It is now blocked on exactly one thing: the user-supplied SMPL body model.**

  **What was built.** `uv` fetched **CPython 3.10.20** into `.engine\venv`.
  4D-Humans was cloned shallow to `.engine\hmr2`, pinned at
  **`efe18deff163b29dff87ddbd575fa29b716a356c`**. The inference set went in from the
  **cu130** index: `torch 2.14.1+cu130`, `torchvision 0.29.1+cu130`, plus
  `pytorch-lightning 2.6.6`, `smplx 0.1.28`, `timm 1.0.30`, `yacs`, `einops`,
  `opencv-python`, `scikit-image`, `dill 0.4.1`, `pandas`, `pyrender`, `trimesh`.
  `numpy 2.2.6` throughout. Resolution reported **zero conflicts**.
  `.engine/` was added to `.gitignore` with a comment saying why, because that
  directory now holds a venv and a 2.5 GB checkpoint.

  **Verified, not assumed.** `torch.cuda.is_available()` is **True**,
  `torch.cuda.get_device_name(0)` is **NVIDIA GeForce RTX 3080**, compute
  capability **(8, 6)**. The ≤ 10 GB VRAM target in the plan is literally this
  card (10,240 MiB), so T10 measures the real target rather than a proxy.

  **Windows blocker 1 — `HOME`.** `hmr2/configs/__init__.py:5` builds
  `CACHE_DIR` from `os.environ.get("HOME")`, which Windows does not define; the
  result is `os.path.join(None, ".cache")` and a `TypeError` before anything else
  runs. Fixed by defining `HOME` in the subprocess environment. Nothing on Windows
  supplies it, so the adapter must own this.

  **Windows blocker 2 — EGL.** `hmr2/utils/renderer.py:1-3` sets
  `PYOPENGL_PLATFORM='egl'` **only if it is not already set**, and EGL does not
  exist on Windows, so `import pyrender` dies with
  `ImportError: ('Unable to load EGL library', ...)`. That guard is the escape
  hatch: pre-setting the variable stops the override. Tested values —
  **`win32` works**, `wgl` works, `pyglet` works, **`osmesa` fails** (needs an
  OSMesa DLL). `win32` is the native choice. Again: no line of vendored code was
  modified, and the adapter must own this too.

  **Why the renderers are a hard dependency even though we never render.**
  `hmr2/models/hmr2.py:7` does `from ..utils import SkeletonRenderer,
  MeshRenderer`, and `hmr2/utils/__init__.py` pulls the renderer modules, so
  `pyrender` and `trimesh` are import-time requirements of merely *loading the
  model*. Worth recording: `hmr2/__init__.py` is **empty**, so `import hmr2`
  itself costs nothing — the entire cost sits in the submodule chain we choose
  to import, which is why our own entry point controls it.

  **Correction to my own earlier claim: `chumpy` is NOT avoidable.** The T10 row
  said "no `chumpy`" and it was wrong — corrected here and in that row. (L19 never
  mentioned `chumpy`; its `detectron2` claim is a separate one and it held up.)
  `setup.py` pins `chumpy @ git+https://github.com/mattloper/chumpy` as a **hard**
  `install_requires`, and the reason is real: `convert_pkl()` un-pickles the SMPL
  body model, which contains `chumpy.ch.Ch` objects, so `chumpy` must be
  importable — and because `convert_pkl` re-pickles those objects unchanged,
  `smplx` needs `chumpy` importable at *load* time too. It is a runtime
  dependency, not a one-time conversion tool. The PyPI release **0.70 builds but
  cannot import** under numpy 2 (`chumpy/__init__.py:11` does
  `from numpy import bool, int, float, ...` and `np.int` was removed in numpy
  1.24). The **git fork installs and imports cleanly** — `chumpy 0.71` from
  `mattloper/chumpy@580566eafc9ac68b2614b64d6f7aaa84eebb70da`. It needs
  `pip` in the environment plus `--no-build-isolation`, because it declares no
  build dependency on pip. **Install the fork, not PyPI.** My "no chumpy" claim
  came from reading `setup.py` and assuming the git URL was incidental; it was
  the whole fix.
  **`detectron2` really is avoidable**, and this one held up: it sits in
  `extras_require['all']`, and it only produces bounding boxes, which the
  animator supplies by choosing the frame. `demo.py` does import it directly, so
  our entry point must not be `demo.py`.

  **The checkpoint downloaded and extracted** — `hmr2_data.tar.gz`, 2,710,589,440
  bytes (2585 MB), auto-fetched by the project's own `download_models()`. It
  yields `data/smpl_mean_params.npz`, `data/SMPL_to_J19.pkl`, and the HMR2.0b
  checkpoint at
  `logs/train/multiruns/hmr2/0/checkpoints/epoch=35-step=1000000.ckpt`
  (**2584 MB**), beside its `model_config.yaml` and `dataset_config.yaml`.
  **`data/smpl/` extracts empty.** The body model is deliberately not in the
  tarball and is not on this machine (searched the user profile, the ComfyUI
  tree and the project drive).

  **The one thing only the user can do.** `check_smpl_exists()` accepts either
  `{CACHE_DIR_4DHUMANS}/data/smpl/SMPL_NEUTRAL.pkl` or
  `data/basicModel_neutral_lbs_10_207_0_v1.0.0.pkl`, and converting the second
  into the first is exactly what `convert_pkl` is for. The file requires
  registering at **<https://smplify.is.tue.mpg.de/>** — that URL is the one in
  the code's own `FileNotFoundError`, and it supersedes the `smpl.is.tue.mpg.de`
  I first quoted. Registration approval can take a day, so it went to the user
  immediately rather than after the rest of the work. `spec.md` §4.14 already
  records the licence posture this implies.

  **Trap found while reading the downloader — do not lose this.**
  `cache_url()` returns early when the destination **exists at all**
  (`download.py:58`), and `download_models()` wraps both the download *and* the
  extraction in `if not os.path.exists(output_path)`. So a **partial or 0-byte
  `hmr2_data.tar.gz` silently skips both steps**, leaving no checkpoint and no
  error. Any retry after an interrupted download must delete the leftover file
  first.

  **Checkpoint choice — my first framing here was WRONG, corrected in L22.**
  The tarball ships HMR2.0**b**; the README says HMR2.0**a** is a separate
  download (`hmr2a_model.tar.gz`, 2,709,514,240 bytes). Both were fetched. What
  I first wrote in this spot — that `a` is "the accuracy lever", an 18 % error
  reduction "on the standard metric" — **cherry-picked one metric out of five
  and drew the opposite conclusion from the paper's own.** L22 has the full
  table and the correction.

  **Nothing measured yet.** VRAM, latency and hip-height stability all still
  require the body model, so no number in this log is a measurement. The
  measurement gate is still shut.
- **L22.** **Checkpoint `a` vs `b`: I checked the paper instead of trusting my
  own note, and my note was misleading. `b` is the authors' recommended model.**
  Both tarballs are now downloaded and extracted; the extraction is *additive*
  (they land in different directories, so neither clobbers the other):

  | variant | path under `.engine/.cache/4DHumans` | size |
  | ------- | ------------------------------------ | ---- |
  | `b` | `logs/train/multiruns/hmr2/0/checkpoints/epoch=35-step=1000000.ckpt` | 2584 MB |
  | `a` | `logs/train/multiruns/hmr2a/0/checkpoints/epoch=10-step=25000.ckpt` | 2584 MB |

  `load_hmr2(checkpoint_path=...)` selects between them; `DEFAULT_CHECKPOINT` is
  hardcoded to the `b` path, and each checkpoint's own `model_config.yaml` sits
  where `load_hmr2` looks for it (`Path(checkpoint_path).parent.parent /`),
  which is why the `a` variant could not simply be dropped into `hmr2/`.
  **Why I checked.** The `a` checkpoint is `epoch=10`, step 25 000, against
  `b`'s step 1 000 000 — a 40× shorter run. A shorter run scoring better is not
  impossible, but it is exactly the kind of claim worth a source. The README has
  **no metrics table** at all (it only names `b` as the default), so the numbers
  were re-read from the paper's own tables: *Humans in 4D* (Goel et al., ICCV
  2023), **arXiv:2305.20091v3**, Table 1 (3D, mm — lower better) and Table 2
  (2D PCK — higher better).

  | model | 3DPW MPJPE | 3DPW PA-MPJPE | H36M MPJPE | H36M PA-MPJPE | LSP-Ext @0.05 | COCO @0.05 | PoseTrack @0.05 |
  | ----- | ---------- | ------------- | ---------- | ------------- | ------------- | ---------- | --------------- |
  | HMR 2.0 **a** | **70.0** | **44.5** | **44.8** | 33.6 | 0.38 | 0.79 | 0.86 |
  | HMR 2.0 **b** | 81.3 | 54.3 | 50.0 | **32.4** | **0.53** | **0.86** | **0.90** |

  So the two numbers I had recorded (`a` 44.5, `b` 54.3) are real — they are
  simply **one column of seven**. `a` wins 3DPW MPJPE, 3DPW PA-MPJPE and H36M
  MPJPE; `b` wins H36M PA-MPJPE and **every single 2D column**, by a wide margin
  on the hard ones. My "18 % error reduction on the standard metric" line
  promoted a single saturated benchmark to "the standard" and silently dropped
  the six that disagree.

  **The paper's own reading, which decides this.** Verbatim:

  > *"we observe that by a small compromise of the performance on 3DPW, our
  > HMR 2.0b model, which trains for longer on more data (AVA, AI Challenger,
  > and InstaVariety), achieves results that perform better on **more unusual
  > poses**... Furthermore, we observe that HMR 2.0b is a **more robust model
  > and use it for evaluation in the rest of the paper**."*

  and, on the benchmarks `a` wins:

  > *"we believe that these benchmarks are very saturated and these smaller
  > differences in pose metrics tend to not be very significant."*

  The authors made the trade **deliberately** and then chose `b` for everything
  downstream. On LSP-Extended — the dataset built for unusual poses — `b`'s
  `PCK@0.05` of `0.53` is described as *"1.6× better than the second best"*,
  against `a`'s `0.38`.

  **Why this lands on this project specifically.** Production animation footage
  is *by definition* the unusual-pose case: action, combat, dance, extreme
  contortion. That is LSP-Extended's regime, not 3DPW's. And the 2D PCK columns
  measure reprojection alignment against the image — which is the fidelity the
  animator actually **sees in the viewport** while deciding whether a Golden Pose
  is usable. The 3D columns `a` wins are Procrustes-aligned, i.e. with global
  orientation and scale removed, and this tool discards world placement anyway.

  **The configs independently corroborate that `a` is not a "better `b`".**
  They are two different training recipes, not two lengths of the same one:
  `a` is `exp_name: 3001d` with **`BACKBONE.FREEZE: true`** (only the head is
  trained, which is why it converges in 25 k steps) on the classic HMR data mix
  (H36M/MPII/COCO/MPI-INF, `BATCH_SIZE: 512`, `LR: 1e-4`); `b` is full
  fine-tuning on that mix **plus AVA, AI Challenger and InstaVariety**
  (`BATCH_SIZE: 48`, `LR: 1e-5`, 1 M steps). Freezing the backbone in training
  changes nothing at *inference* — both load the same ViT — so VRAM and latency
  should be close, but that is a thing to **measure**, not to assume.

  **Decision.** Default to **`b`**: it is the released checkpoint, the one the
  README's own code path uses, and the one the authors say is more robust for
  exactly the poses this tool exists to capture. Both are kept on disk so T10
  can still measure them against each other for VRAM and latency — and **note
  what cannot be measured here**: accuracy has no ground truth on this box, so
  the paper is the *only* accuracy evidence available and it points at `b`. The
  earlier framing of `a` as the accuracy pick is withdrawn.

- **L23. (2026-10-19) T10 measurements — the measurement gate is shut, T11-T13
  are unblocked.** The user's SMPL body model arrived at
  `.engine/.cache/4DHumans/data/smpl/SMPL_NEUTRAL.pkl` (86,955,594 bytes) on
  2026-10-16 16:25, exactly the path `check_smpl_exists()` expects.

  **What ran.** Two instruments under `.engine/` (untracked, gitignored):
  `measure_t10.py` (VRAM + latency + hip-height stability per checkpoint, one
  process per variant so every cold figure is honest) and
  `t10_template_hip.py` (the betas=0 template's metric geometry). The batch is
  prepared by the engine's own `ViTDetDataset` given a fixed centre box (the
  animator already chose the frame), 10 decodable frames from the bundled
  `gymnasts.mp4`, batch 1. Raw results persisted to
  `.engine/t10_measurements_{a,b}.json`.

  **Windows loader findings owned by the future adapter (S14, S16) — no vendored
  engine line modified:**
  1. `hmr2/configs/__init__.py:5` builds `CACHE_DIR` from `HOME/.cache`, so the
     adapter process must set `HOME=<repo>/.engine` (recorded in L21).
  2. torch ≥ 2.6 defaults `torch.load(weights_only=True)` and the checkpoint
     carries `omegaconf.DictConfig` objects, while `load_hmr2` does not pass the
     flag: our process overrides `torch.load` to force `weights_only=False`
     (the models are user-supplied and trusted, S16).
  3. `pyrender.OffscreenRenderer` supports only `egl`/`osmesa` offscreen —
     **`win32` satisfies the *import* but not the renderer constructor**, so
     `HMR2.__init__`'s `MeshRenderer` raises on Windows. `HMR2.__init__
     supports `init_renderer=False`, and we never render: our entry point
     replicates `load_hmr2`'s last mile with that flag instead of monkeypatching.
     (The L21 note "win32 works" was correct for the import and is now
     corrected: it does not work for the OffscreenRenderer path.)
  4. `hmr2.datasets` needed `webdataset`; installed (pure Python).
  5. Launching `HMR2.load_from_checkpoint` upgrades the v1.8.1 checkpoint in
     memory to lightning 2.6.6 on every process start. Note for latency: the
     **cold** figure is dominated by first-use kernel/alloc work, not by the
     engine itself.

  **The joint-index trap — corrected before these numbers count.** The wrapper
  (`smpl_wrapper.py:19-20`) reorders the SMPL joints into **OpenPose BODY_25
  order** and appends 19 extra joints: **0=Nose, 8=MidHip (the pelvis),
  19-24=toes/heels**, vertical axis y. My first pass used joints[0] as pelvis
  and joints[7..11] as feet — that 0.44 m "hip" was the *nose-to-ankle*
  distance. All numbers below (and in `t10_measurements_*.json`) were produced
  **after** the correction; the corrupted first run was discarded, not reported.

  **VRAM — S15(b) answered.** Peak allocated **2,672.1 MiB**, peak reserved
  **2,736.0 MiB** at batch 1; **identical for `a` and `b`**. 26% of the
  10 GB target. The 10 GB test never came close; **FP16 stops being required by
  it** and stays open purely as an optional speedup. Not measured: multi-frame
  batches and the CondMDI inbetweening engine (FR-GEN-03 measures its own).

  **Latency — S15(b) answered.** Each variant in its own process, GPU-synced,
  3 warmup + 10 timed iterations:
  - `b`: cold 334.4 ms; warm end-to-end 81.0–94.4 ms, **median 83.9 ms**.
  - `a`: cold 330.4 ms; warm 83.0–85.8 ms (earlier contaminated colds — 79.4,
    538.4 — came from a shared process and are withdrawn).
  - Preprocessing alone: ≈ **40.5 ms** CPU (the engine's own resize/crop/blur +
    normalization is nearly half of the end-to-end time); GPU inference ≈
    **44 ms**. `b` is not slower than `a` — **no cost reason against the L22
    choice of `b`**.

  **Hip height — S15(a) answered, with a design consequence for T12.** Two
  distinct quantities, kept apart:
  - **The betas=0 SMPL neutral template** (checkpoint-independent, deterministic):
    standing height 1.745 m arm-span / 1.717 m vertical; **pelvis→vertex-floor =
    0.9385 m**, pelvis→foot-joint = 0.9312 m — *constant by construction*.
  - **The per-frame estimate** (what `pred_smpl_params`' betas produce under a
    fixed centre box over the gymnast clip): pelvis→foot magnitudes within one
    person ranged **0.59–0.99 m** (`a` all-negative sign, `b` sign-mixed — the
    per-frame axis is chosen per frame and gymnasts invert; the *magnitude* is
    what varies). Part of that spread is genuine pose (tucked legs shorten
    pelvis-to-foot), part is per-frame betas noise — that split cannot be
    separated on this material, so the honest conclusion stands: **the raw
    per-frame height is not keyable blind**, and the production rig needs a
    *deliberate* anchor. The template constant 0.9385 m is the obvious
    candidate, but **the anchor decision belongs to T12 and is parked there**.
    Material caveat: gymnasts + a fixed box. The real input is a standing
    full-body Golden Pose frame — precisely the paper's unusual-pose regime,
    where a per-frame estimate is weakest and where the template anchor
    protects.

  **Route record (tracking trigger rule):** all inline — one understood task,
  small per its `Task Size` tests, no product decision needed; the instruments
  live untracked under `.engine/`, like the manual probes before them. C11 is
  the docs-only work unit that records it. **Native assessment after C11**
  (`gentle-ai review assess --base-ref 7e22c5e --committed-only`): risk
  `medium` (executable_change, `.gitignore`), `review_due: false`,
  `under_budget` — the review stays pending in the slice until a later commit
  reaches the budget; the boundary (`7e22c5e`) has not advanced.

- **L24. (2026-10-19) T11 + T12 landed as one work unit (commit C12 on
  `feat/develop`) - the real HMR2.0 adapter now sits behind `AIPort`.**

  **Shape.** `adapters/ai/hmr2_worker.py` = the engine-side half, run by the
  engine's own interpreter in its own process (S14, the Blender read path's
  isolation). It owns every Windows fix from L23 as *code, not notes*:
  `HOME`=<engine root> before any engine import, `PYOPENGL_PLATFORM=win32`
  (import-only; the model still loads with `init_renderer=False`), a
  `torch.load` override forcing `weights_only=False`, and the `webdataset`
  import satisfied by the T10 install. `adapters/ai/hmr2_adapter.py` = the
  app-side `Hmr2Adapter` - the `AIPort` implementation, **standard library
  only** (CI never imports torch), talking a line-JSON stdin/stdout protocol.

  **The persistent-worker decision.** One process per `K` would reload the
  2.7 GB checkpoint every time - unusable next to T10's 84 ms warm inference.
  The worker instead loads the checkpoint once and answers requests for its
  whole lifetime; `empty_cache()` runs after every request so VRAM does not
  grow across keys (FR-CAP-05); `Hmr2Adapter.shutdown()` (idempotent) ends the
  worker, wired into `PoseExtractionRunner.shutdown()` so the window's close
  event tears everything down without the window knowing about processes.
  Failure paths stay typed and non-fatal (S6/S7): a missing interpreter,
  checkpoint, body model, GPU, or a dead/mid-request worker each raise
  `Hmr2EngineError` with a message naming the path and the fix, and the next
  `K` respawns cleanly after a death.

  **The conversion (T12).** Hip height = the `betas=0` template anchor
  (§4.13, decided here: the worker computes the template's own
  pelvis-to-contact distance at startup; the per-frame estimate is still
  computed and returned as diagnostics - the T10 verdict stands). Rotations =
  `global_orient`?`Pelvis` plus the 23 `body_pose` 3x3 matrices **named
  with SMPL's canonical joint names** (L_Hip, Spine_1, ...), converted to
  quaternions and re-expressed **Y-up → Z-up** by `conjugate_y_up_to_z_up`
  (`R_x(+90) q R_x(-90)`). Verified numerically, not by assertion: an
  X-rotation passes through unchanged, a 90-degree Y rotation becomes exactly
  the same 90-degree rotation about the domain's Z, and **the FBX writer's
  conjugation (`q_fbx = A q_domain A_inv`, `A = R_x(-90)`) returns the
  engine's own rotation** - the whole domain chain closes. World displacement
  is dropped (`x = y = 0`; `Main` ships in place).

  **A real bug was caught before any real number relied on it: the first `conjugate_y_up_to_z_up` used the full-angle quaternion
  (`cos(90)`) instead of the half-angle (`cos(45)`); the numeric tests
  caught it in RED, and the writer round trip pins it permanently.

  **Evidence.** RED observed (import failure), then 14 new tests green -
  missing-path typing, ready-failure, worker-reuse (same pid), death typing,
  shutdown termination, matrix → quat, the two conjugation invariants, the
  writer round trip, and the full request?`WorldPose` path - plus 2 new
  runner tests (`shutdown` releases the injected engine, with and without
  work in flight). 182 tests green, `ruff check` clean, all with
  `--basetemp` because the user's `%TEMP%\\pytest-of-josea` directory has
  broken ACLs no tool can repair without elevation (environmental, unrelated
  to this change; a reboot or `takeown` as admin clears it).

  **Docs in the same change set:** § open question 1 resolved (no start-time
  VRAM pre-check - the app is usable without the engine, so the first `K`
  reports one typed actionable failure instead; the worker self-reports GPU +
  total VRAM on its ready line), §4.13 anchor decision recorded, FR-CAP-05
  rewritten for the landed adapter (still 🞡 because the **real** engine has
  not run end-to-end yet), change log 0.4.7, session state updated.

  **Fruit opens into T13 (the last M5 task):** the end-to-end probe on the
  real engine (VRAM stability across keys, FP16 numerics vs FP32) and the
  window wiring - `build_window` instantiates the real adapter and a real
  production skeleton (SMPL-named body joints + `Main`) so the whole M5
  pipeline can be verified by hand on the box, like M4 was.

- **L25 (2026-10-19) — native review of the T11+T12 slice (55e0994..01fea0a),
  granted, one bounded correction, approved.** Reviewer lenses (risk,
  resilience, reliability) corroborated two deterministic candidate-caused
  blockers, both real: (1) a stale `_ready` blocked the promised respawn
  after a worker death — the next `K` died on an untyped `AssertionError`
  forever; (2) a timed-out worker was never terminated — an orphan holding
  ~2.67 GB of VRAM that `shutdown()` could no longer reach. Correction
  (commit `e7960b2`, +79/18-, within the 45-line forecast): one
  `_discard_worker()` helper terminates the process (wait -> terminate ->
  kill) and clears `_worker`/`_lines`**/**`_ready` on every failure path;
  `shutdown()` shares it; the death test now proves the second extraction
  is served by a fresh worker (die-once fake, different pid) and a new pin
  proves a hung worker is terminated when the request times out. Gates: 183
  tests green, ruff clean. Targeted validation confirmed the fix; review
  **approved + acknowledged** (authority burned, lineage
  `review-e40ba83315e51a38`). All 8 remaining findings are **advisory
  non-blocking** follow-ups; `R4-3` (worker stderr discarded -> undiagnosable
  real-engine crashes) folds directly into T13's probe; the rest are
  deferred: R1 (pin checkpoint sha256 before the `weights_only=False`
  load), R3-protocol-doc-drift (worker docstring promises `hip_height_cm`
  the real worker never emits; the fake does), R3-silent-malformed-ok
  (broken `ok` responses convert to empty poses instead of a typed
  protocol failure), R3-recovery-paths-untested (no corrupt-`FrameImage`
  or stray-non-JSON-line test), R3-windows-only-test-unguarded (the
  `OpenProcess` pin needs a POSIX skipif), R4-4 (template hip computation
  outside try/except blames the checkpoint on unrelated deaths), R4-5
  (`empty_cache` skipped on failed requests).

- **L26 (2026-10-19) — T13: the window runs the real engine and
  adopts the real rig; the real-engine end-to-end is verified.**
  `build_window` injects `Hmr2Adapter` (real engine, spawn-free at open —
  `ready` costs the first `K`, per open question 1's lazy posture) and a
  `skeleton_source` that builds `core/production_skeleton.py`'s SMPL
  chain mirrored under `Main` from `Hmr2Adapter.bind_offsets()`;
  `CaptureController` adopts it at the first successful extraction and
  keeps it for the session. Bind offsets are real body-model data: the
  worker derives them at startup from the wrapper's own buffers
  (`J_regressor @ v_template`; parents/kintree straight from the wrapper
  — measured identical to the OpenPose pelvis row of the anchor call),
  and ride the ready line. **Two real defects the fake cannot see,
  caught by the e2e probe and fixed:** (1) `half()` weights made the
  template anchor call (and per-request forward) raise dtype mismatches
  before/instead of ready — the fp16 recipe is now `autocast` around the
  backbone forward, the SMPL recovery and the template anchor call, with
  half inputs; FR-CAP-05 keeps FP16 with measured numerics (mean 0.84
  mm, max 3.68 mm vs fp32; FP16's real win measured too: 1328 MiB vs
  2.66 GB resident); (2) the offsets were double-converted (worker sent
  already-domain values and the adapter converted again) — the protocol
  now carries **SMPL-frame** offsets like the rotations do (engine
  speaks its frame, the adapter owns the conversion; the fake and CI
  already encoded that rule). The e2e probe (real adapter, real worker,
  real frame from `gymnasts.mp4`): ready ~12 s, 6 keys with VRAM flat
  1328.1 MiB (growth 0.0 — `empty_cache()` contract holds through the
  bridge), quaternions normal, Pelvis bind (-0.18, -2.82, 93.87) cm in
  the domain. Also folded in: **R4-4 fixed** (the template section is
  fatal-typed and does not blame the checkpoint — proven live when probe
  run one hit it), **R3-protocol-doc-drift fixed** (the response doc no
  longer promises `hip_height_cm`; it is `per_frame_hip_height_m`).
  Spec synced (0.4.8): FR-CAP-05 verified end-to-end, FR-CAP-06 the real
  rig, open question 10 resolved. Gates: 124 tests green, ruff clean.
  Still-open advisories (unchanged): R1, R3-silent-malformed-ok,
  R3-recovery-paths-untested, R3-windows-only-test-unguarded, R4-5.
  M5 has one remaining manual check for FR-CAP-05's UI half: pressing
  `K` in the real window on a real clip and seeing the rig+pose in the
  pane (the probe exercised the adapter path headlessly). Native assess on the slice
  e7960b2..df409be: **under_budget** — the review stays pending in the slice
  until a later commit reaches the budget; passive tier not claimed.
