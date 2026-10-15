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

## Tasks

Route is `inline` unless noted; there is no Writer trigger here — the units
interlock through shared interfaces, and none of them is heavier than the
coordination a delegation would cost.

| ID | Specs | Route | Status | Evidence |
| -- | ----- | ----- | ------ | -------- |
| T1 | S7, S9 | inline | done | `da0ddfd` — 6 kinematics tests + 2 neutral-pose tests, RED first |
| T2 | S3, S4, S5 | inline | done | `75065da` — 17 controller tests over a fake source, RED first |
| T3 | S1, S2, S6, S10 | inline | pending | |
| T4 | S3, S4, S8, S9 | inline | pending | |
| T5 | S9, S11 | inline | pending | |
| T6 | S4, S6, S8, S9, S12 | inline | pending | |
| T7 | S1, S12 | inline | pending | |
| T8 | all | inline | pending | |

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
