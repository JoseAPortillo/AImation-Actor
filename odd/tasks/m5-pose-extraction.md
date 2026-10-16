# M5 — Pose extraction pipeline (`AIPort` + captured frame + `QThread`)

**Objective:** give `K` a real extraction pipeline — capture the frame the
animator marked, run a pose engine **off the UI thread**, and write the
*remapped* production pose onto the timeline.
**Branch:** `feat/develop`, local delivery only (the user confirmed there will be
no pull requests, so the P/R-size heuristic and the chained-PR strategy do not
apply here).
**Runner:** `.\.venv\Scripts\python.exe -m pytest` · lint: `.\.venv\Scripts\ruff.exe check .`

**Scope note — what this unit does NOT deliver.** The real GVHMR adapter is a
separate, bounded task: it needs an external research repo plus multi-GB
checkpoints and `torchvision`, none of which are present. Ship the *contract*
now and the engine behind it later, so the engine lands as one file with no
caller changes (`O` in SOLID). That also means **FP16** and
`torch.cuda.empty_cache()` stay open: they are engine internals, not pipeline
behavior. `AIPort`, the frame capture, the single-frame `QThread` runner and the
remap all land here, verified with a deterministic engine.

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
  playhead onto it, so the timeline catches up with what the animator sees. A
  source that cannot establish the index (no timestamps, unknown frame rate)
  reports `None` and the capture keeps the playhead — degrade, never refuse
  (M5 L8's rule; S3, S5, FR-CAP-05, FR-CAP-07).
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
| T9 | S12,S13 | inline | ✅ done | `CapturedFrame` (`core/models.py`), `frame_index_of`/`frame_shown`/`grab_frame(fps)` (`video_player.py`), the key and playhead fix (`capture_controller.py`) (C6); regression tests in `tests/test_gui_capture_controller.py` and `tests/test_gui_video_player.py`; real-clip probe (L16) |

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
