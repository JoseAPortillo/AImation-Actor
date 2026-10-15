# spec.md — AImation Actor (MVP working spec)

> SDD working spec: **only** numbered requirements with testable acceptance
> criteria. Nothing here restates the architecture, hierarchy, data model or FBX
> conventions — those live in [`AGENTS.md`](AGENTS.md) and
> [`docs/Plan_AImation_Actor_EN.md`](docs/Plan_AImation_Actor_EN.md). Where this
> file and the plan disagree on behavior, **the plan wins**.

Status: Draft · v0.3.2 · Scope: MVP only

## How to use (SDD)

- **Spec first, code second.** Any behavior/interface change updates this file in
  the *same change set* as the code.
- Every requirement has an ID and testable acceptance criteria; code must be
  traceable to one, and its tests reference that ID.
- Priority (MoSCoW): `Must` = MVP blocker · `Should` = gap acceptable ·
  `Could` = in-scope nice-to-have.
- **Status:** ✅ done · 🟡 partial · ⬜ open. Flip it in the same change that
  moves the requirement.
- Done = criteria pass (`pytest`, or *manual* when it needs Blender), docs in
  sync, `ruff`/`pytest` green. Open points go to §4, not guessed in code.

## 1. Scope

**In:** one reference video · manual key marking · per-frame pose extraction ·
skeleton-only sparse/stepped `.fbx` export · refine-and-reimport round trip ·
generative inbetweening · IK cleanup · final export.

**Out (MVP):** meshes/skinning · character retargeting · multi-actor · network ·
non-Windows · MDM/LAFAN1 engines · automatic key suggestion (see plan §7).

## 2. Functional requirements

### Capture — media, marking, extraction, preview

| ID | Pri | Status | Requirement | Acceptance criteria |
| -- | --- | ------ | ----------- | ------------------- |
| FR-CAP-01 | Must | ✅ | Open a reference video (`.mp4`/`.mov`, H.264/ProRes). | Opens the file; corrupt input errors out and leaves the app usable. *(A missing or unreadable file fails immediately with a message, and a clip already loaded is kept.)* |
| FR-CAP-02 | Must | ✅ | Video streams; never fully decoded into RAM. | No path reads all frames; peak RAM does not scale with clip length. *(Measured through the FFmpeg backend: a 48-frame clip and a 1440-frame clip both peak ≈ 8 MiB above the window-only baseline.)* |
| FR-CAP-03 | Must | ✅ | Frame-accurate timeline (current/total frames; clip fps on state). | Position changes by ±1 per step; `fps` matches the clip (default 24). *(Frame 0 is the first frame — the range is 0-based, matching FBX time; a 2 s / 24 fps clip reports 48 frames.)* |
| FR-CAP-04 | Must | ✅ | Shortcuts: `Space` play/pause, `←`/`→` ±1 frame, `K` mark, `Delete` remove, `Shift+←/→` jump between keys. | Each shortcut behaves as described, clamped to the frame range. *(`Ctrl+O` opens a clip; `Delete` removes the key at the playhead, the MVP having no separate selection.)* |
| FR-CAP-05 | Must | 🟡 | `K` runs GVHMR on **only** that frame (batch 1) in a `QThread`, FP16, releasing CUDA cache after. | One frame inferred; UI stays responsive; cache does not grow across keys. *(The pipeline landed: batch 1 is enforced by the runner itself, the engine runs off the UI thread, and one `K` sends exactly one frame. The engine behind the port is still a deterministic stand-in — GVHMR needs an external repo, multi-GB weights and `torchvision`, none of which are present — so FP16 and the CUDA-cache release are not exercised yet.)* |
| FR-CAP-06 | Must | ✅ | Extracted pose is remapped to the production hierarchy (per AGENTS.md). | Result matches the documented skeleton naming/hierarchy. *(`build_production_pose` performs the mapping and every extraction now goes through it, verified end to end on a real clip: a stand-in hip height of 140 with a Pelvis bind of 100 wrote an offset of exactly 40.0, and `Main` came back at `(0, 0, 0)` with identity rotation. The mapping is engine-independent.)* |
| FR-CAP-07 | Should | ✅ | At most one key per frame; extraction failure is non-fatal. | Re-marking a frame does not duplicate; a failed `K` keeps prior keys and reports. *(Re-marking overwrites by frame; a failure keeps every prior key and writes none; a second `K` while an engine runs is refused instead of queued; a late answer from a clip that is no longer open is discarded. M4's neutral placeholder is retired — it would have passed a failure off as a capture.)* |

### Blocking export

| ID | Pri | Status | Requirement | Acceptance criteria |
| -- | --- | ------ | ----------- | ------------------- |
| FR-EXP-01 | Must | ✅ | Write binary FBX with keys **only** at marked frames, stepped/constant tangents, skeleton only. | Keys for {15,42} exist exactly at 15 and 42; re-import shows Constant, no baked frames. |
| FR-EXP-02 | Must | ✅ | Follow the documented transforms & conventions (Main global, Pelvis height-only, quaternions, axes/time). | Matches AGENTS.md «Domain invariants»; round trip validates with `anim_offset = 0.0`. |

### Refined import

| ID | Pri | Status | Requirement | Acceptance criteria |
| -- | --- | ------ | ----------- | ------------------- |
| FR-IMP-01 | Must | ✅ | Import a Refined FBX; validate hierarchy (must include `Main`). | Hand-edited file loads; missing/renamed critical bone → clear error, no silent import. |
| FR-IMP-02 | Must | ✅ | Only keyed frames become snapshots; interpolation types ignored; each snapshot is a full pose. | Bézier/Linear inputs yield the same set as Constant. |
| FR-IMP-03 | Must | ✅ | Read via Blender subprocess only; never `import bpy` in-process. | No `bpy` in the app; a subprocess crash does not kill the app. |

### Generative inbetweening, IK & delivery

| ID | Pri | Status | Requirement | Acceptance criteria |
| -- | --- | ------ | ----------- | ------------------- |
| FR-GEN-01 | Must | ⬜ | Human keys are locked as hard constraints; only gaps are filled. | Output equals input at every human key (within tolerance); nothing outside the first/last key. |
| FR-GEN-02 | Must | ⬜ | Engine behind a Model Factory selectable from the GUI; MVP = CondMDI. | Swapping the engine needs no `core/` edits; CondMDI is the default. |
| FR-GEN-03 | Must | ⬜ | Generation runs in a `QThread`, batch 1, FP16, cache released; stays ≤ 10 GB VRAM. | Same constraints as FR-CAP-05; long spans complete on target hardware. |
| FR-IK-01 | Must | ⬜ | Detect planted feet in the original keys; IK pins contacts (no sliding/penetration) before final export. | Foot position stays constant across a contact span within tolerance. |
| FR-GEN-04 | Must | ⬜ | Export the approved final FBX (same conventions as blocking), preserving the frame range. | Output is a valid FBX; `frame_start`/`frame_end` match the import. |

## 3. Non-functional requirements

| ID | Pri | Status | Requirement | Acceptance criteria |
| -- | --- | ------ | ----------- | ------------------- |
| NFR-01 | Must | ✅ | `core/` and `ports/` stay free of third-party imports. | Enforced by a test/lint check on import surfaces. *(`tests/test_layering.py` reads the imports of every domain module and also rejects an adapter import.)* |
| NFR-02 | Must | 🟡 | No blocking of the UI on AI/IO work. | No frozen window during extraction/generation. *(Extraction runs on a worker thread, and a test asserts the UI is not waiting on the engine. Inbetweening (FR-GEN-03) has no implementation yet, so its half of the requirement is unverified.)* |
| NFR-03 | Must | ✅ | Errors are explicit and actionable; state stays recoverable. | Failures report a message; no silent failures. *(A damaged clip, a mark with nothing loaded, a missing rig and an unusable GL driver each name what happened; the loaded clip and its keys survive a failure.)* |
| NFR-04 | Should | ✅ | Blender read path is manual-test-only (needs a Blender install). | Documented as manual; not required in CI. |

## 4. Open questions

1. VRAM pre-check (≥ 6 GB): hard block or warning?
2. Import behavior when Blender is not installed?
3. `fps` source: clip metadata, user setting, or project setting?
   *(MVP answered in M4: clip metadata, defaulting to 24 when the clip does not
   report one. Revisit if a project/session setting arrives.)*
4. Re-marking an existing frame: overwrite or refuse? *(service layer: overwrite.)*
5. Project persistence (session file) or export-only? *(MVP assumption: export-only.)*
6. One reference video per session or a list? *(MVP: one.)*
7. `AIPort` method signatures for extraction and inbetweening.
8. Numeric threshold defining "no foot sliding".
9. *(Resolved 2026-10-15.)* "Offset calculation" in `core/services.py`:
   `build_production_pose` maps a raw `WorldPose` onto the production
   hierarchy — `Main` stays **clean** (`(0,0,0)`, identity rotation), because it
   is the animator's world control and the export ships "in place"; the captured
   horizontal displacement is deliberately **not** exported. `Pelvis` carries the
   hip **height** only, with local x/y pinned to `0`; every other joint carries
   rotation only. Translations are offsets from each joint's `rest_translation`,
   the convention the FBX writer adds back. This supersedes the plan's §5.B
   assignment of the AI scene displacement to `Main`.
10. *(Opened 2026-10-15, M4.)* The capture GUI has no rig to preview: the joint
    hierarchy and proportions come from GVHMR (M5), and the app will not invent
    joint data behind the production mapping. Options: leave the pane saying "no
    rig loaded yet" until M5 (current), or ship a provisional production rig now.
    *(Current choice is the honest empty pane; a provisional rig would have to
    guess the hierarchy M5 must match.)*
11. *(Opened 2026-10-15, M4.)* A failed **open** is reported in the status bar.
    Non-modal suits a failed mark (the session continues), but a clip the
    animator just picked is easy to miss in a line of text. A dialog for that one
    case is a candidate.

## 5. Change log

| Version | Date       | Change                                                |
| ------- | ---------- | ----------------------------------------------------- |
| 0.1.0   | 2026-10-15 | Initial draft from the plan and AGENTS.md.            |
| 0.2.0   | 2026-10-15 | Synthesized: removed content duplicating AGENTS.md.   |
| 0.3.0   | 2026-10-15 | Added per-requirement status column and legend.       |
| 0.3.1   | 2026-10-15 | Core keyframe-management services landed (FR-CAP-07). |
| 0.3.2   | 2026-10-15 | Resume notes + open question on "offset calculation". |
| 0.3.3   | 2026-10-15 | "Offset calculation" landed: plan §5.B split, §4.9 resolved. |
| 0.3.4   | 2026-10-15 | `Main` reserved for the animator; blocking export ships in place. |
| 0.4.0   | 2026-10-15 | M4 capture GUI landed (FR-CAP-01..04 ✅, NFR-01/03 ✅); frame range is 0-based. |
| 0.4.1   | 2026-10-15 | M5 pose-extraction pipeline landed (`AIPort`, frame capture, `QThread` batch 1, remap): FR-CAP-06/07 ✅, FR-CAP-05/NFR-02 🟡 (the engine is a stand-in). |

## 6. Session state (resume here)

**Done**

- Docs/SDD: `AGENTS.md` at repo root (engineering principles: SOLID, SDD, good
  practices) and this `spec.md` with per-requirement status.
- FBX I/O committed (`binary`, `document`, `transform`, `blender_import`,
  `fbx_adapter`) and hardened: object-type counts fixed, integer ranges
  validated, duplicate frames rejected.
- `core/services.py`: pure keyframe management (mark/remove/find/navigation/
  clamp) with tests. 46 tests green, `ruff check` clean.
- `core/services.py` offset calculation (M3 part 2): `WorldPose` +
  `build_production_pose` map a raw world pose onto the production hierarchy —
  `Main` stays clean (`(0,0,0)`, identity) for the animator and `Pelvis` takes
  the hip height as an offset from its bind (§4.9). 52 tests green,
  `ruff check` clean.
- M4 capture GUI (`feat/develop`): `CaptureController` owns the timeline and the
  playhead; `VideoPlayer` streams through Qt Multimedia (FFmpeg backend);
  `TimelineBar` is the scrubber with Golden-Pose markers; `SkeletonViewport`
  draws the pose in a fixed orthographic front view; `MainWindow` composes the
  split view and the plan's §3.A shortcuts; `main.py` is the entry point.
  FR-CAP-01..04 verified by hand against a real 2 s / 24 fps H.264 clip (24 fps
  read from the clip, 48 frames, ±1 per step, `K` marking, `Shift+←` jumping
  back to the key, playback and pause). FR-CAP-02 measured: 48-frame and
  1440-frame clips both peak ≈ 8 MiB above baseline. `tests/test_layering.py`
  enforces NFR-01. 118 tests green, `ruff check` clean.
- M5 pose-extraction pipeline (`feat/develop`): `AIPort` is the single-operation
  engine seam; `FrameImage` is the pure-domain RGB frame it consumes; the player
  moved to `QVideoSink` and renders the frames itself, so the frame at the
  playhead is available on demand (FR-CAP-02/05); `PoseExtractionRunner` runs one
  frame per request on a `QThread`; `K` writes the remapped pose at the frame it
  was extracted from, refuses a second request while one runs, discards a late
  answer for a clip that is no longer open, and writes no key when extraction
  fails (FR-CAP-06/07). Verified by hand against real clips through the real
  window: the primary workflow (open → scrub → `K`, never pressing play) works;
  a frame captured twice with others in between gives the identical fingerprint
  while distinct frames differ; 15 captures at 0/10/30/60/120 ms after a scrub
  never produced a wrong frame; FR-CAP-02 re-measured with the sink in the path
  (272.0 MiB for a 2 s clip vs 275.1 MiB for a 60 s one, 30× the frames scanned).
  150 tests green, `ruff check` clean.

**Next**

1. **The real GVHMR adapter** — the remaining half of M5: the `AIPort`
   implementation plus FP16 and the CUDA-cache release, which needs an external
   repo, multi-GB weights and `torchvision`.
2. Then M6 (CondMDI + Model Factory) → M7 (IK) → M8 (generative export).

**Known follow-ups**

- `AIPort` has one implementation to write: the real GVHMR adapter (§4.7). The
  contract and the whole pipeline around it are in place, so the adapter lands as
  one file with no caller changes.
- **ProRes (FR-CAP-01) was never exercised** — only H.264 has been played. The
  requirement says `.mp4`/`.mov` with H.264/ProRes, and ProRes is common on real
  workstations, so this needs a real ProRes clip before FR-CAP-01 can be called
  fully verified.
- A mark pressed immediately after a scrub can be refused with "Could not read
  the frame at the playhead." — refusing is deliberate (the alternative is
  extracting a neighbouring frame silently), but the capture could instead wait
  for the pending frame and then proceed. Add that only if real use shows the
  refusal is common.
- M4 has no production rig to preview: the joint hierarchy and proportions come
  from GVHMR (M5), so the 3D pane reports "no rig loaded yet" instead of
  inventing one (§4.10).
- Failure reporting is non-modal (status bar). Worth revisiting for a failed
  *open*, where the animator picked the bad file and a line of text is easy to
  miss.
