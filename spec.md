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
| FR-CAP-03 | Must | ✅ | Frame-accurate timeline (current/total frames; clip fps on state). | Position changes by ±1 per step; `fps` matches the clip (default 24). *(Frame 0 is the first frame — the range is 0-based, matching FBX time; a 2 s / 24 fps clip reports 48 frames. While the clip plays, the playhead follows the frame the decoder delivered, not the backend's rarer position events, so the number and the video pane cannot disagree.)* |
| FR-CAP-04 | Must | ✅ | Shortcuts: `Space` play/pause, `←`/`→` ±1 frame, `K` mark, `Delete` remove, `Shift+←/→` jump between keys. | Each shortcut behaves as described, clamped to the frame range. *(`Ctrl+O` opens a clip; `Delete` removes the key at the playhead, the MVP having no separate selection.)* |
| FR-CAP-05 | Must | 🟡 | `K` runs the pose engine on **only** that frame (batch 1) in a `QThread`, FP16, releasing CUDA cache after. | One frame inferred; UI stays responsive; cache does not grow across keys. *(The stand-in is retired: the engine behind the port is now the **real HMR2.0 adapter** (backend decision at §4.12) — an out-of-process, persistent worker (FR-IMP-03 shape) whose 2.7 GB checkpoint loads once, then answers each `K` with one inference (~84 ms measured, §4.13); it runs FP16 and calls `empty_cache()` after every request by construction, and carries every Windows loader fix recorded during T10 (`HOME`, `weights_only=False`, `init_renderer=False`, `PYOPENGL_PLATFORM`, `webdataset`). The bridge, the typed actionable failures (missing interpreter, checkpoint, body model, GPU) and the conversion to `WorldPose` (template anchor 93.85 cm, per-joint quaternions named for the production skeleton, world displacement dropped) are CI-verified against a faithful fake worker on the plain interpreter. **Still open:** the end-to-end run against the real engine — VRAM stability across keys and FP16's numerics are engine internals only the real box can prove (manual probe, like the Blender read path). The extracted frame carries its own frame index from the clip's timestamps, the key is written there, and the playhead moves onto it — measured on real clips after play → pause → `K`.)* |
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

1. VRAM pre-check (≥ 6 GB): hard block or warning? *(Resolved 2026-10-19, M5
   T11: **no app-start pre-check.** The app stays fully usable without the
   engine — 100% of FR-CAP-01..04 — so an entry-time modal would gate features
   the user may not need. Instead the engine is validated lazily on the first
   `K`: the worker self-reports its GPU and total VRAM on its ready line, and a
   GPU-less or unconfigured machine gets one typed, actionable failure naming
   the missing piece and its fix (S6/S7 shape). NFR-03's explicit-error rule
   carries the "warning" role; the height of the wall does not change the
   behaviour measured in T10 (2.67 GB at batch 1).)*
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
    hierarchy and proportions come from the pose engine (M5), and the app will not invent
    joint data behind the production mapping. Options: leave the pane saying "no
    rig loaded yet" until M5 (current), or ship a provisional production rig now.
    *(Current choice is the honest empty pane; a provisional rig would have to
    guess the hierarchy M5 must match.)*
11. *(Opened 2026-10-15, M4.)* A failed **open** is reported in the status bar.
    Non-modal suits a failed mark (the session continues), but a clip the
    animator just picked is easy to miss in a line of text. A dialog for that one
    case is a candidate.
12. *(Opened 2026-10-16, M5 — supersedes the plan's GVHMR choice.)* **The pose
    engine is HMR2.0**, behind `AIPort`, in a dedicated Python 3.10 environment
    outside the app process — the same shape as the Blender read path (FR-IMP-03),
    and for the same reason: the research stack pins versions this project's
    interpreter does not carry. Why not the plan's GVHMR: it is sequence-native
    (its trajectory starts at `[0,0,0]` and accumulates per-frame velocities, and
    its foot-locking and camera odometry are cumulative too), so at one frame
    those mechanisms are undefined; and its licence is non-commercial-only, a
    constraint HMR2.0 inherits anyway via the SMPL body model, so picking GVHMR
    buys no freedom. Measured on the same benchmark (3DPW, PA-MPJPE): GVHMR
    **36.2 mm with 120 frames** against HMR2.0's **44.5 mm with one** — and the
    **released** checkpoint is the `b` variant at **54.3 mm** on that one column.
    That column is not the whole picture, and it is not the deciding one: across
    the paper's other reported columns `b` wins — Human3.6M PA-MPJPE (`32.4`
    against `33.6`) and **every 2D PCK column**, by `0.53` against `0.38` on
    LSP-Extended, the unusual-pose benchmark. The authors call `b` the *"more
    robust model"* and *"use it for evaluation in the rest of the paper"*, and
    call the 3DPW gap a *"small compromise"*. So the price of the switch is
    ~8-18 mm on one saturated benchmark, and it is not reachable at `F=1`
    regardless.
    `docs/Plan_AImation_Actor_EN.md` names GVHMR throughout and needs the same
    correction when it is next revised; **this entry is the authority until then**.
13. *(Opened 2026-10-16, M5; **answered 2026-10-19 by T10** — both measured on
    the real box, RTX 3080 / 10240 MiB; evidence in
    `odd/tasks/m5-pose-extraction.md` L23.)* Two HMR2.0 properties were
    unmeasured, and both could change the adapter's design:
    1. **Monocular scale.** `pred_cam_t` is a weak-perspective estimate, so the
       absolute **hip height** `build_production_pose` consumes is a learned
       guess, not a measurement. *Measured: the per-frame estimate is **not**
       keyable raw — on uneven footage the pelvis-to-foot estimate ranged
       ≈ 0.59-0.99 m within one person. There is a rock-stable anchor instead:
       the betas=0 SMPL neutral template's own pelvis-to-contact distance,
       **0.9385 m** (constant by construction). The adapter should not consume
       the per-frame height blindly; T12 decides the anchor. *(Decided in
       T12, 2026-10-19: the **template constant is the anchor** — the engine
       worker computes the betas=0 template's own pelvis-to-contact distance
       at startup and the adapter writes it as `Pelvis` height, so a crouched
       or elevated pose ships at a stable, body-metric height the animator
       trims in one cleanup pass. The per-frame distance is still computed,
       returned as diagnostic information, and available to a future
       per-frame-height feature.)*
    2. **Cost.** No VRAM or per-frame latency figure is published for HMR2.0.
       The target is ≤ 10 GB, batch 1. *Measured on the real box: **VRAM 2.67 GB**
       peak allocated (2.74 GB reserved) at batch 1 — 26% of the target, and
       identical for both checkpoints; **warm per-frame latency 81-94 ms
       end-to-end** (≈ 40 ms of it CPU-side preprocessing, ≈ 44 ms GPU
       inference), cold first frame ≈ 330 ms. FP16 is therefore not required to
       meet the VRAM target; it stays open as an optional speedup.*
14. *(Opened 2026-10-16, M5.)* **Licensing posture, recorded rather than assumed.**
    The code is MIT, but the runtime needs `smplx` and the **SMPL body model**,
    both non-commercial (research/education/artistic), and the model forbids
    redistribution. The user's position, verbatim: *"no se va a distribuir, es uso
    propio, al menos por ahora"*. So personal use is covered and the tool may be
    built — but **distributing or selling it later requires a commercial licence
    from Meshcapade/Max-Planck**, and no permissively-licensed body-model
    estimator exists (every one surveyed — HybrIK, OSX, SMPLer-X, TokenHMR,
    Multi-HMR, VideoPose3D — inherits the same terms). Only landmark models
    (MediaPipe BlazePose, Apache-2.0) avoid it, and they publish no 3D accuracy
    metric at all.

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
| 0.4.2   | 2026-10-16 | M5 verification blocker fixed: the captured frame carries its own index (`K` keys it, the playhead moves there) and the playhead follows the delivered frame while playing (FR-CAP-03/05). |
| 0.4.3   | 2026-10-16 | M5 fix independently verified: the blocked case reproduced 6/6 rounds per clip at baseline and 0/6 after; 7 regression pins committed (FR-CAP-03/05). |
| 0.4.4   | 2026-10-16 | M5 fix reviewed (native review, 3 lenses): approved, no blockers, 10 advisories carried as follow-ups (FR-CAP-03/05). |
| 0.4.5   | 2026-10-16 | Backend decision: the pose engine is **HMR2.0**, not the plan's GVHMR (sequence-native and undefined at one frame; its licence buys no freedom HMR2.0 does not already have). FR-CAP-05 corrected; §4.12-4.14 opened (engine + out-of-process boundary, the two unmeasured properties, the licensing posture). |
| 0.4.6   | 2026-10-19 | T10 measurement gate shut: VRAM 2.67 GB / warm 81-94 ms at batch 1 on the real box (≤ 10 GB met, FP16 no longer required for the target); per-frame hip height not keyable raw, SMPL template anchor 0.9385 m (§4.13 answered). |
| 0.4.7   | 2026-10-19 | The real HMR2.0 adapter landed behind `AIPort` (FR-CAP-05 stays 🟡): out-of-process persistent worker (checkpoint loads once, FP16 + `empty_cache()` per request), typed actionable failures, template-anchored `WorldPose` conversion (§4.13 anchor decided); open question 1 resolved (no start-time VRAM pre-check, typed per-request failure). Real-engine end-to-end probe remains. |

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
- M5 fix (2026-10-16, `feat/develop`): the blocker the independent verification of
  M5 reported — play → pause → `K` keyed the pose of a frame 1-3 positions early,
  silently — is closed. The captured frame now carries the frame index it belongs
  to, proved from its own clip timestamps (`CapturedFrame`, `frame_index_of`), so
  `K` keys the frame the animator is looking at and the playhead moves onto it;
  and while the clip plays, the playhead follows the delivered frame instead of
  the backend's rarer position events, so the number and the pane cannot
  disagree. Measured on real clips through the real window: play → pause → `K`
  six times per clip, **0 key mismatches, 0 playhead lag**, key == pane and
  image == pane on all 12 rounds. 161 tests green, `ruff check` clean.
  **Independently verified** by a fresh agent against baseline `187b822`: the
  blocked case reproduced **6/6 rounds on each clip** before the fix and **0/6**
  after, while the engine's image matched the pane in *every* baseline round —
  the frame *number* was wrong, never the pixels, so the guard against extracting
  a neighbouring frame was working and only the attribution was not. The
  verifier's 7 regression pins are committed, so this coverage no longer depends
  on the manual probe. 168 tests green, `ruff check` clean.
  **Reviewed** (native review, three lenses: resilience, readability,
  reliability) over the whole slice `187b822..7e22c5e`: **approved, no blockers**,
  the correction budget untouched, and ten advisory findings carried forward as
  follow-ups below rather than fixed inside this candidate.
- M5 backend decision (2026-10-16, `feat/develop`): the pose engine is **HMR2.0**,
  not the plan's GVHMR, and `FR-CAP-05` now says so. The premise it carried —
  "batch 1, one frame" for a video model — was false, and it was corrected from
  primary sources rather than left standing: GVHMR is sequence-native (trajectory
  starts at `[0,0,0]` and accumulates, foot-locking and camera odometry are
  cumulative), its licence is non-commercial-only, and HMR2.0 inherits the same
  body-model constraint, so the switch costs nothing in freedom. The one real
  price is per-joint accuracy — 36.2 mm (GVHMR, 120 frames) against 44.5/54.3 mm
  (HMR2.0, one) on 3DPW PA-MPJPE — and it is unreachable at `F=1` anyway. The
  install also loses `detectron2`, which only produced bounding boxes, but
  **keeps `chumpy`** — the SMPL body model is chumpy-pickled and `smplx` must be
  able to unpickle it, so the fork 4D-Humans pins is a real runtime dependency
  (PyPI 0.70 cannot even import under numpy 2). Recorded
  as §4.12 (the decision), §4.13 (the two unmeasured properties) and §4.14 (the
  licensing posture).

**Next**

1. **The real HMR2.0 adapter** - the remaining half of M5. **(a) Environment and
   measurement: done (T10, 2026-10-19)** - the dedicated Python 3.10 venv works
   on Windows, both checkpoints load and infer on the real GPU, and §4.13's two
   unmeasured properties are measured (VRAM 2.67 GB at batch 1, warm 81-94 ms,
   hip height needs an anchor - the template constant 0.9385 m). **(b) The
   adapter remains:** the `AIPort` implementation - SMPL parameters to hip
   height in centimetres plus per-joint local quaternions named for the
   production skeleton - plus FP16 and the CUDA-cache release, out-of-process,
   with the Windows loader fixes the session recorded. Weights are
   user-supplied and never vendored. *(Landed T11/T12, 2026-10-19: `hmr2_adapter`
   + `hmr2_worker` - persistent out-of-process protocol, typed failures,
   template-anchored conversion. **Remaining:** the end-to-end probe on the real
   engine (VRAM stability across keys, FP16 numerics) and wiring the window to
   the real engine + production skeleton for manual verification.)*
2. Then M6 (CondMDI + Model Factory) → M7 (IK) → M8 (generative export).

**Known follow-ups**

- `AIPort` has one implementation to write: the real HMR2.0 adapter (§4.12). The
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
  from the pose engine (M5), so the 3D pane reports "no rig loaded yet" instead
  of inventing one (§4.10).
- Failure reporting is non-modal (status bar). Worth revisiting for a failed
  *open*, where the animator picked the bad file and a line of text is easy to
  miss.
- **Native-review advisories from the M5 fix** (L18 in
  `odd/tasks/m5-pose-extraction.md`). None is a defect in the behavior that was
  specified or delivered; all were left out of the reviewed candidate on purpose:
  - **The caller-supplied `fps` seam.** `VideoSource.grab_frame` computes the
    frame index from the rate the caller passes, and the controller can only pass
    `self._state.fps` — the default-24 fallback when the backend reported none. So
    the documented "unknown frame rate → `frame_index` `None`" degradation cannot
    fire on the real call path, and the player's grab path and its `frame_shown`
    path can disagree about one frame's index. Fix by giving the player one
    authority for the index instead of two.
  - **The one-way `_frames_are_indexed` latch.** The latch is set before the
    `not self._playing` return, re-armed only by a new clip load, and not scoped
    to the clip it was proved for; once set, `position_changed` can never move the
    playhead again for that clip, so a backend that stops supplying timestamps
    mid-playback freezes the playhead with no fallback. Needs a re-arm or a
    watchdog.
  - **Test and observability hygiene.** The metadata → `_fps` → `frame_shown` link
    is pinned only through the private attribute; the refusal pin never asserts
    the playhead; `frame_index_of`'s boundaries are pinned three times over; the
    `_FakeSource` doubles model `VideoSource` two incompatible ways; and the
    playhead-source switch is silent (nothing reports which source owns the
    playhead, or that a frame could not be indexed).
