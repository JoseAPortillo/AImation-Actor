# M4 — Capture GUI (split view, video, timeline, shortcuts)

Objective: ship the reference-video capture UI — open/stream a clip, a
frame-accurate timeline, Golden-Pose marking, and keyboard shortcuts — wired to
the existing pure `core/` logic.

Branch: `feat/develop` · Delivery: **single branch** (chosen explicitly by the
user) · Runner: `pytest` (+ `pytest-qt` for widgets), `.venv` Python 3.14

## Specs

Scope: the capture milestone only. Pose extraction (GVHMR) is M5; the viewport
renders what the timeline already holds.

- **S1 — FR-CAP-01.** Open a reference video: "Open a reference video
  (`.mp4`/`.mov`, H.264/ProRes)." Acceptance: "Opens the file; corrupt input
  errors out and leaves the app usable."
- **S2 — FR-CAP-02.** Streaming: "Video streams; never fully decoded into RAM."
  Acceptance: "No path reads all frames; peak RAM does not scale with clip
  length."
- **S3 — FR-CAP-03.** Frame accuracy: "Frame-accurate timeline (current/total
  frames; clip fps on state)." Acceptance: "Position changes by ±1 per step;
  `fps` matches the clip (default 24)."
- **S4 — FR-CAP-04.** Shortcuts: "Shortcuts: `Space` play/pause, `←`/`→` ±1
  frame, `K` mark, `Delete` remove, `Shift+←/→` jump between keys." Acceptance:
  "Each shortcut behaves as described, clamped to the frame range."
- **S5 — FR-CAP-07 + NFR-03.** One key per frame, failures non-fatal: "At most
  one key per frame; extraction failure is non-fatal." Acceptance: "Re-marking a
  frame does not duplicate; a failed `K` keeps prior keys and reports." NFR-03:
  "Errors are explicit and actionable; state stays recoverable."
- **S6 — NFR-02.** No UI blocking: "No blocking of the UI on AI/IO work."
  Acceptance: "No frozen window during extraction/generation."
- **S7 — NFR-01.** Layering: "`core/` and `ports/` stay free of third-party
  imports."
- **S8 — plan §3.A.** Shortcut semantics, verbatim:
  - "**`Space`:** Play / pause the background reference video."
  - "**`Right Arrow` / `Left Arrow`:** Advance or rewind exactly **1 frame** for
    frame-accurate tracking of kinetic contacts."
  - "**`K` (Keyframe):** Capture the current frame's pose, send it to the GVHMR
    engine, and draw a key marker on the timeline."
  - "**`Delete`:** Remove the selected Golden Pose from the application timeline."
  - "**`Shift + Right Arrow / Left Arrow`:** Jump directly between captured
    Golden Poses on the timeline."
- **S9 — plan §3.B split view.** Verbatim:
  - "**Temporal Synchronization:** The video player and 3D viewer are
    dynamically linked to the same time indicator."
  - "**Display on Empty Frames:** When positioned on a frame without a Golden
    Pose, the 3D viewer displays the skeleton in a neutral pose (or the last
    pose, faded). This clearly and visually indicates that this timeline region
    has no keys."
- **S10 — plan §5.A video input.** Verbatim: "**Supported Formats:** `.mp4` and
  `.mov` using H.264 or ProRes encoding." and "The application does not decode
  the entire video into RAM; instead, it extracts a flat RGB image buffer only
  for the exact frame at which the animator presses `K` to run inference."
  (The frame buffer itself is M5; M4 must not introduce any whole-clip decode.)
- **S11 — AGENTS.md stack.** The 3D viewport is "`QOpenGLWidget` + PyOpenGL (or
  QtQuick3D)".
- **S12 — milestone definition** (spec §6): "**M4 (GUI)**: split view, video,
  timeline, shortcuts — the largest remaining pillar; `core/services.py` already
  provides its key logic."

### Assumptions (authorized as assumptions, not requirements)

- **A1.** Until GVHMR exists (M5), `K` marks the frame with the plan's *neutral
  pose*; M5 replaces it with the extracted pose on the same frame, which
  `mark_pose` already does by overwrite (S5). The key marker appears either way.
- **A2.** The playhead (current frame) is transient view state and lives in the
  GUI controller, not in `TimelineState`: the core API already takes the frame as
  a parameter (`clamp_frame`, `next_key_frame`, …).
- **A3.** `fps` comes from the clip metadata when the backend exposes it, and
  falls back to `TimelineState.fps` (default 24) otherwise — S3's "(default 24)".
- **A4.** Jump-to-key with no key left in that direction keeps the playhead where
  it is (it does not run to the end of the clip).
- **A5.** The viewport draws an orthographic skeleton with fixed-function OpenGL
  lines and a runtime capability probe; no orbit/zoom controls, because no
  requirement asks for them.
- **A6.** `Delete` removes the Golden Pose **at the playhead**. §3.A says "remove
  the selected Golden Pose", and the MVP has no separate selection: the playhead
  is the only cursor the animator has.
- **A7.** `Ctrl+O` opens a clip. FR-CAP-01 needs a way in and §3.A reserves no key
  for it; every other binding in §3.A is implemented exactly as written.

## Tasks

Route is `inline` unless noted; there is no Writer trigger here — the units
interlock through shared interfaces, and none of them is heavier than the
coordination a delegation would cost.

| ID | Specs | Route | Status | Evidence |
| -- | ----- | ----- | ------ | -------- |
| T1 | S7, S9 | inline | done | `da0ddfd` — 6 kinematics tests + 2 neutral-pose tests, RED first |
| T2 | S3, S4, S5 | inline | done | `75065da` + `c670736` fix — 18 controller tests over a fake source, RED first |
| T3 | S1, S2, S6, S10 | inline | done | `ac40a0b` + `6926b9c` fix — 7 player tests (seam, boundaries, metadata) |
| T4 | S3, S4, S8, S9 | inline | done | `3aea43e` — 8 timeline tests, RED first (module missing) |
| T5 | S9, S11 | inline | done | `2870f72` + `973b2a3` — 7 viewport tests + a real-driver pixel probe |
| T6 | S4, S6, S8, S9, S12 | inline | done | `740bf54` — 10 window tests, mutation-checked |
| T7 | S1, S12 | inline | done | `65ac11e` — 3 entry-point tests + a real end-to-end run |
| T8 | all | inline | done | spec.md statuses + session state; `tests/test_layering.py` |

Planned units (one work-unit commit each, tests with the behavior)

- **T1** `core/kinematics.py` (`rotate`, `joint_world_positions`,
  `bone_segments`) + `neutral_pose` in `core/services.py`.
- **T2** `adapters/gui/capture_controller.py` — playhead, marking, shortcuts
  logic, media-loaded handling, over a small video-source seam.
- **T3** `adapters/gui/video_player.py` — `QMediaPlayer`/`QVideoWidget`
  streaming wrapper, clip fps, duration → frames, seek by frame, errors.
- **T4** `adapters/gui/timeline_bar.py` — scrubber, frame readouts, key marker.
- **T5** `adapters/gui/viewport_3d.py` — `QOpenGLWidget` skeleton renderer with
  the neutral pose on empty frames and a capability probe.
- **T6** `adapters/gui/main_window.py` — split view, actions/shortcuts, status
  bar, error reporting.
- **T7** `aimation_actor/main.py` — real entry point.
- **T8** Docs: spec.md requirement statuses + session state, and this document.

## Log

- **L1 (user, verbatim).** "haz commit y luego implementa M4 en una nueva rama:
  feat/develop"
- **L2.** Committed the M3 offset-calculation work unit on `main` first
  (`e24d845` chore ignore local tooling state, `210df96` feat(core) split world
  poses into production offsets), then branched `feat/develop` from it.
- **L3.** Explored before writing: `core/` exposes keyframe services with the
  frame as a *parameter* (no playhead in the domain), the three `adapters/gui/`
  modules are one-line stubs, PySide6 6.12.0 + pytest-qt are installed, and the
  plan's §3 defines shortcut and split-view semantics (S8, S9).
- **L4.** Probed OpenGL on this box before planning the viewport: `QOpenGLWidget`
  yields a valid 4.6 **compatibility** context (NVIDIA RTX 3080), `glBegin` is
  usable and PyOpenGL's `shaders` imports. The documented stack is viable, so
  the viewport stays in M4.
- **L5.** Delivery note: the authored-line forecast for M4 (~900 lines plus
  tests) is above the ~400-line heuristic, which would normally trigger the
  one-time chain-strategy question. The user explicitly named the delivery shape
  ("en una nueva rama: feat/develop"), so that is the recorded strategy: one
  branch for M4. If the branch later needs a PR and turns out unreviewable, the
  slicing decision is revisited then, with the user.
- **L6.** Planned placement (decided before writing, so the widgets stay free of
  domain math — S7): the *neutral pose* is a domain concept (S9, and S8's `K`
  before M5 exists), so it belongs in `core/services.py` rather than inline in a
  widget; and forward kinematics to world positions is pure math that both the
  viewport and M7's IK need, so it goes to a new `core/kinematics.py`.
- **L7.** T1 and T2 landed with RED observed first, 77 tests green, `ruff check`
  clean. Two of my own test expectations were wrong and were corrected, not the
  code: `timeline_changed` also fires when a clip's range arrives, and the
  controller deliberately does not emit a status during construction (a signal
  emitted before the window connects would be lost — the window pulls `status()`).
- **L8.** RDD assessment after T1 (`--base-ref main --committed-only`) returned
  `risk: medium`, `review_due: false`, `review_due_reason: under_budget`: the
  slice stays pending until a later commit reaches the budget.
- **L9.** Frame base (assumption, not a requirement): the playhead is **0-based**,
  so frame `0` is the clip's first frame and a range of `N` frames spans
  `0 .. N-1`. This matches FBX time (`AGENTS.md`: FBX time 0 = frame 0) and
  avoids mixing bases; a 1-based *display* would be a separate, small change.
- **L10.** A second clip starts a fresh timeline (keys are cleared) because the
  keys belong to the clip they were marked on, and the MVP is one reference video
  per session (spec §4.6). The rig is not clip data and survives.
- **L11.** T3 slip, recorded honestly: the `VideoPlayer` module was written
  *before* its tests (an order error), so its tests were not a RED-then-GREEN
  pair. They still earned their place immediately — they caught two real defects:
  `QMediaPlayer.positionChanged` carries a `qlonglong` and cannot be connected
  straight to the seam's `Signal(int)`, and driving the real widget through the
  controller exposed that `CaptureController(source)` crashed because
  `TimelineState()` requires a skeleton. The state is now a required argument.
  Both fixes are committed with their tests.
- **L12.** Tooling incident, logged because it cost real time and could have
  shipped silently: three file edits (`media_player`, the `positionChanged` fix,
  `_on_position`) were present, then reverted on disk before the next command ran,
  so the suite failed with an already-fixed error. Mitigation adopted: read a file
  back after editing it, and re-check the edited lines after a run. Nothing was
  lost in the final state — the source was re-verified line by line.
- **L13.** Qt Multimedia on this box runs on the FFmpeg 9.0.1 backend (reported
  by Qt itself in the test run), which matters for the manual playback check.
- **L14.** T4 landed (`3aea43e`): `TimelineBar` with `frame_x`, `KeyStrip` and the
  scrubber, 8 tests, RED first (the module did not exist). Writing the tests first
  caught a latent ordering defect in the widget's own range/value handling: the
  range must be set before the value, or the value is clamped against the stale
  range. 93 tests green, `ruff check` clean.
- **L15.** T5 landed (`2870f72`): `fit_view` + `SkeletonViewport` over
  `QOpenGLWidget`, 5 tests, RED observed first (ImportError on the missing
  module). Because a widget test cannot prove that anything is *rasterised*, the
  draw path was probed against the real driver as well: 879 bone-coloured pixels
  with a rig, 0 without it, and no fallback notice — so the check discriminates
  rather than passing on a blank frame either way.
- **L16.** T5 follow-up (`973b2a3`), found by looking at the real app rather than
  the tests: with no rig loaded — which is *every* session until M5 — the pane was
  blank with no explanation, exactly the silent failure NFR-03 forbids. It now
  distinguishes "this driver cannot draw" from "there is no rig yet" and clears
  the notice when a skeleton arrives. The window also shows the starting pose on
  construction instead of only after the first event.
- **L17.** T6 landed (`740bf54`): `MainWindow` composes the player, the panes and
  the §3.A shortcuts over one controller, 10 tests. Because all 10 passed on the
  first run after the implementation, they were **mutation-checked**: renaming
  `K` to `J` and reversing one step broke 5 of them, and all 10 passed again once
  the source was restored. `Ctrl+O` and the `Delete` target are assumptions A7/A6.
- **L18.** T7 landed (`65ac11e`): the real entry point plus 3 tests, then a real
  end-to-end run against a generated 2 s / 24 fps H.264 clip through the FFmpeg
  backend. Observed: `state_fps = 24.0` (read from the clip, S3), `total_frames =
  48`, timeline 48, 3 viewport segments; `→` moved the playhead 0→2 with the
  timeline at 2 (S9); `K` marked frame 2 and the status read "clip.mp4 — frame 2 /
  48 · 24 fps · 1 golden pose · keyed"; `Shift+←` jumped back to that key; the
  window rendered 48 distinct colours. A second, focused probe checked the
  play/pause link: `is_playing` is still `False` immediately after `play()` (the
  player reports asynchronously), `True` at 800 ms with the playhead at frame 15,
  and `False` again after the second `Space`, with the playhead frozen for the
  next 600 ms.
- **L19.** FR-CAP-02 measured rather than assumed, since "peak RAM does not scale
  with clip length" is a measurement, not an inspection. Process peak working set,
  one process per clip: 2 s / 48 frames → 167.8 MiB idle, 175.7 after load, 176.5
  after seeking to the end; 60 s / 1440 frames → 167.4, 175.5, 176.3. Thirty times
  the frames, the same ≈ 8 MiB, so the decode is streamed. The first attempt at
  this probe printed `peak=0.0 MiB` because a ctypes call was failing silently; it
  was fixed and re-run rather than reported.
- **L20.** T8 landed: spec.md statuses (FR-CAP-01..04 ✅, FR-CAP-06 🟡 for the
  unwired mapping, NFR-01/03 ✅), changelog 0.4.0, session state, and §4.10/§4.11
  opened for the two decisions M4 raises. `tests/test_layering.py` now enforces
  NFR-01 by reading every domain module's imports and rejecting third-party ones
  and adapter imports alike.
- **L21.** Limits of this evidence, stated rather than implied: only H.264 was
  played (ProRes is required by S10 but no ProRes file was available); the memory
  measurement covers load and seek, not a long playback session; the GL probe
  covers this box's compatibility context only; `K` marks the neutral pose, since
  GVHMR is M5 (A1); and the real app shows the empty-rig pane until M5, which is
  the M4/M5 seam reported to the user.
- **L22.** Reviewing my own risk line before reporting turned up a real gap: the
  axis convention (`(x, z, -y)`) lived inline in `paintGL`, where no test could
  see it. A **mirror** — `(x, z, y)` — leaves the figure upright and entirely
  plausible while swapping left and right, so an animator would read the skeleton
  backwards with nothing looking wrong. The earlier pixel probe could not have
  caught it either: it counted coloured pixels, and a mirrored figure rasterises
  just as many. `to_view` now owns the convention with two tests (the rotation,
  and the invariant that +Z in the domain is +Y on screen). Mutation-checked:
  mirroring the mapping fails both new tests, restoring passes all 118.
  This also cost a detour worth recording: chasing the change through the shell
  produced mangled output that appeared to show a *pre-existing* `end.y` typo in
  the committed code, and only a programmatic read of the bytes settled it. HEAD
  was correct all along (`end.x, end.z, -end.y`), no bug was ever committed, and
  the lesson is to verify this kind of claim from the bytes rather than from the
  rendered console.
- **L23.** Delivered: `feat/develop` fast-forwarded into `main` (`210df96` →
  `53b251c`), so `main` now carries all of M4 and the branch continues from that
  same commit. **Not pushed** — the user keeps delivery local ("estamos solos, no
  habrá PR"), which takes the PR-size heuristic and the chained-PR question off
  the table for this repo, now recorded as a project constraint. Verified after
  the merge: `main` and `feat/develop` both point at `53b251c` with a clean tree.
