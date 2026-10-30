# spec.md — AImation Actor (MVP working spec)

> SDD working spec: **only** numbered requirements with testable acceptance
> criteria. Nothing here restates the architecture, hierarchy, data model or FBX
> conventions — those live in [`AGENTS.md`](AGENTS.md) and
> [`docs/Plan_AImation_Actor_EN.md`](docs/Plan_AImation_Actor_EN.md). Where this
> file and the plan disagree on behavior, **the plan wins**.

Status: Draft · v0.7.1 · Scope: MVP only

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
| FR-CAP-01 | Must | ✅ | Open a reference video (`.mp4`/`.mov`, H.264/ProRes). | Opens the file; corrupt input errors out and leaves the app usable. *(A missing or unreadable file fails immediately with a message, and a clip already loaded is kept. ProRes itself was exercised 2026-10-27: the animator opened a 6 s ProRes 422 HQ 1080p30 clip — `ffmpeg -c:v prores_ks -profile:v 3` from the real JACE reference — with no issue; H.264-only had been the standing gap since the MVP.)* |
| FR-CAP-02 | Must | ✅ | Video streams; never fully decoded into RAM. | No path reads all frames; peak RAM does not scale with clip length. *(Measured through the FFmpeg backend: a 48-frame clip and a 1440-frame clip both peak ≈ 8 MiB above the window-only baseline.)* |
| FR-CAP-03 | Must | ✅ | Frame-accurate timeline (current/total frames; clip fps on state). | Position changes by ±1 per step; `fps` matches the clip (default 24). *(Frame 0 is the first frame — the range is 0-based, matching FBX time; a 2 s / 24 fps clip reports 48 frames. While the clip plays, the playhead follows the frame the decoder delivered, not the backend's rarer position events, so the number and the video pane cannot disagree.)* |
| FR-CAP-04 | Must | ✅ | Shortcuts: `Space` play/pause, `←`/`→` ±1 frame, `K` mark, `Delete` remove, `Shift+←/→` jump between keys. | Each shortcut behaves as described, clamped to the frame range. *(`Ctrl+O` opens a clip; `Delete` removes the key at the playhead, the MVP having no separate selection.)* |
| FR-CAP-05 | Must | 🟡 | `K` runs the pose engine on **only** that frame (batch 1) in a `QThread`, FP16, releasing CUDA cache after. | One frame inferred; UI stays responsive; cache does not grow across keys. *(The stand-in is retired: the engine behind the port is now the **real HMR2.0 adapter** (backend decision at §4.12) — an out-of-process, persistent worker (FR-IMP-03 shape) whose 2.7 GB checkpoint loads once, then answers each `K` with one inference (~84 ms measured, §4.13); it runs FP16 and calls `empty_cache()` after every request by construction, and carries every Windows loader fix recorded during T10 (`HOME`, `weights_only=False`, `init_renderer=False`, `PYOPENGL_PLATFORM`, `webdataset`). The bridge, the typed actionable failures (missing interpreter, checkpoint, body model, GPU) and the conversion to `WorldPose` (template anchor 93.85 cm, per-joint quaternions named for the production skeleton, world displacement dropped) are CI-verified against a faithful fake worker on the plain interpreter. The **real-engine end-to-end is verified (T13 probe, 2026-10-19):** the worker reaches ready only under a baked **autocast** recipe - plain fp16 weights raise dtype mismatches in both the ViTDet forward and the template anchor call, caught by the probe as a typed fatal failure (the R4-4 guard in action); per-key `vram_allocated_mib` through the real bridge is flat across 6 sequential keys - 1328.1 MiB under fp16-autocast versus 2.66 GB fp32 (FP16 halves the resident engine), growth 0.0 MiB per key, confirming the `empty_cache()` contract - and the autocast fp16 pipeline differs from fp32 by **mean 0.84 mm / max 3.68 mm** per joint (model-level probe), inside the per-pose cleanup the animator already budgets. Per-key bridge round trip ~ 130 ms (PNG + preprocessing + inference). The extracted frame carries its own frame index from the clip's timestamps, the key is written there, and the playhead moves onto it - measured on real clips.) |
| FR-CAP-06 | Must | ✅ | Extracted pose is remapped to the production hierarchy (per AGENTS.md). | Result matches the documented skeleton naming/hierarchy. *(`build_production_pose` performs the mapping and every extraction now goes through it, verified end to end on a real clip: a stand-in hip height of 140 with a Pelvis bind of 100 wrote an offset of exactly 40.0, and `Main` came back at `(0, 0, 0)` with identity rotation. The mapping is engine-independent. The **real production rig** is built by `core/production_skeleton.py` - SMPL's chain mirrored under `Main`, the 23 canonical body names and their kintree parents - from **bind offsets the engine reports with its ready line** (`J_regressor @ v_template` of the user-supplied body model, in SMPL's frame; the adapter converts them to the domain). The controller adopts the rig at the first successful extraction and keeps it for the session (open question 10 resolved); until then the pane stays honestly blank.)* |
| FR-CAP-07 | Should | ✅ | At most one key per frame; extraction failure is non-fatal. | Re-marking a frame does not duplicate; a failed `K` keeps prior keys and reports. *(Re-marking overwrites by frame; a failure keeps every prior key and writes none; a second `K` while an engine runs is refused instead of queued; a late answer from a clip that is no longer open is discarded. M4's neutral placeholder is retired — it would have passed a failure off as a capture.)* |
| FR-CAP-08 | Must | ✅ | Show the captured skeleton over the reference video with side colors, joint dots, and stepped snapshots between captures. | The overlay uses the engine's full-frame projection; left/right bones are red/blue, trunk/head bones yellow, joints have dark/light gray dots, the latest capture holds until the next key, and the legacy 3D viewport stays hidden while this preview is active. *(The HMR2 worker projects the SMPL joints and refines visible limb landmarks with COCO Keypoint R-CNN plus MediaPipe PoseLandmarker hands/feet; the application receives only pixel snapshots. The user validated three real captures on 2026-10-28. A capture refreshes immediately without slider motion.)* |
| FR-CAP-09 | Should | ✅ | File ▸ Recent Files lists the last five video clips the animator opened, most recent first, and each entry reopens its clip. | A clip is recorded only when its media actually loaded (a failed open never pollutes the list); reopening a known clip moves it to the top instead of duplicating; the list is capped at five and persists across sessions through `QSettings`; an empty list shows a disabled placeholder; paths display verbatim (ampersands escaped, never swallowed as mnemonics). *(`core/recent_files.push_recent` holds the pure rule; `adapters/gui/recent_files.QSettingsRecentFilesStore` is the injected seam.)* |

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
| FR-IMP-04 | Must | ✅ | File ▸ Import FBX… (`Ctrl+I`) adopts the imported timeline as the session (plan §3 step 2). | The imported keys, rig, fps and range replace the session's; an open clip stays loaded for reference, and **importing without a loaded video warns instead of importing blind**. Replacing a session that holds captured keys asks for confirmation first (the user's decision, 2026-10-28); an empty session imports without asking. Capture-only state (overlay snapshots, depth calibration) resets; an in-flight fill refuses the import and says why; a failed read leaves the session untouched and reports. *(`CaptureController.adopt_imported` owns the swap (generation bump retires late extractions, playhead clamps); `MainWindow.import_fbx` runs the read BEFORE the confirmation question — a rejected file must not cost a dialog. Imported keys carry no camera, so each keyed frame gets the front-view **preview** of its refined pose (`core.pose_preview`: bind reach fills ~85 % of the frame height, the pose's lowest point at 95 %, the root's own `x` walking across the clip) — an honest approximation that shows the refinement over the video, explicitly NOT an S1 capture alignment; degenerate inputs draw nothing.)* |

### Generative inbetweening, IK & delivery

| ID | Pri | Status | Requirement | Acceptance criteria |
| -- | --- | ------ | ----------- | ------------------- |
| FR-GEN-01 | Must | ✅ | Human keys are locked as hard constraints; only gaps are filled. | Output equals input at every human key (within tolerance); nothing outside the first/last key. *(Landed in M6: `core/resampling.py`'s `fill_gap_synthetically` leaves keys byte-untouched by construction and refuses to write outside the locked span; guide frames are reasserted byte-exact at their video frames (T7/T8), and a gap whose capture covers every interior frame is filled straight from the capture with no engine request (T9). End-to-end on real capture keys 46/71: reassertion 0 mismatches across 26 captured frames. M8 exception, user-approved 2026-10-24: the per-foot grounding cleanup may correct only the detected planted leg chains at their boundary keys; it never changes `Main` or frames outside a planted span. Default pinning remains byte-untouched.)* |
| FR-GEN-02 | Must | 🟡 | Engine behind a Model Factory selectable from the GUI; MVP = CondMDI. | Swapping the engine needs no `core/` edits; CondMDI is the default. *(Landed in M6 T1/T4: `InbetweeningPort` + `model_factory.py` with typed `UnknownEngineError`; `main.py` builds BOTH engines through the factory (`capture_engine("hmr2")`, `inbetweening_engine()` → CondMDI default), so a swap needs no `core/` edit. 🟡 honest split: the factory + default are done; the factory call site still names the engine in code — no in-app picker yet, deferred while the MVP has exactly one inbetweening engine.)* |
| FR-GEN-03 | Must | ✅ | Generation runs in a `QThread`, batch 1, FP16, cache released; stays ≤ 10 GB VRAM. | Same constraints as FR-CAP-05; long spans complete on target hardware. *(M6 T4/T5: `InbetweeningRunner` on a `QThread` with batch-1 refusals; the CondMDI bootstrap carries `half_precision`; measured on the real RTX 3080 with the real checkpoint: VRAM peak **1831–1832 MiB** per fill (10 GB budget met with ~5× headroom), **~64 s warm per fill** (~78 s first call incl. kernel warmup) at both span 64 and the near-full 193-sample window; typed non-fatal failures à la `PoseExtractionRunner`. The engine is out-of-process, isolated like the capture engine.)* |
| FR-IK-01 | Must | ✅ | Detect planted feet in the original keys; IK pins contacts (no sliding/penetration) before final export. | Foot position stays constant across a contact span within tolerance. *(Landed in M7 (2026-10-23): threshold question 8 resolved at the balanced option (4.0 cm between keys, 6.0 cm above ground); M7 T4 real-clip e2e on JACE_REF_04 span 40..87: planted span detected, 14 rows pinned, toe hold ≤ 0.5 cm, zero clamps. M8 root-motion follow-up (2026-10-24): planting detection reads each toe against the body's frame (`_planting_read` subtracts the root's horizontal displacement) so captured root motion cannot fake drift — without it, an empty detection shipped sliding feet; same real clip re-detected the span, 14 rows pinned, hold ≤ 0.5 cm. Q8 amendment (2026-10-24, the animator's decision): the production detection crop moved the standing subject's planted readings ~1 cm (5.24 cm drift, 6.5 cm toe z on the real clip); thresholds re-tuned 4.0/6.0 → 5.5/8.0 cm, keeping the genuinely moving foot (10.86 cm) excluded.)* |
| FR-GEN-04 | Must | ✅ | Export the approved final FBX (same conventions as blocking), preserving the frame range. | Output is a valid FBX; `frame_start`/`frame_end` match the import. *(Landed in M8 (2026-10-24): `Ctrl+E` / File-menu "Export FBX." in `MainWindow` calls `export_fbx()`, which feeds the controller's approved timeline — keys and adopted fills, since fills live as `Keyframe`s in the adopted state — to the real `BlenderFbxAdapter` binary writer (identical path to the blocking export, `frame_start`/`frame_end` declared exactly at KTime in the file); honest status-bar refusals (NFR-03): empty timeline, no writer configured, cancelled dialog, failed writes reported with the session usable. T2 round-trip validation on the real final file (Blender 5.2, `anim_offset=0`): 48 frames come back keyed with the hierarchy intact, worst local-translation delta 3.4e-05 cm, worst quaternion component 1.6e-06 (float32 margin), planted-foot hold 0.000 cm after read. Blender's importer itself derives its scene range from fcurve extents and ignores the declared TimeSpan — the file carries the approved range, which Maya/Autodesk honor; a range wider than the keyframes is therefore not a Blender-visible setting.)* |
| FR-GEN-05 | Must | ⏳ | The gap fill acts on the ANIMATOR'S REFINED keys — the imported post-Blender timeline — never on the raw pre-refinement captures. | A session holding imported keys fills its gaps with the engine; a capture-only session offers no fill entry at all. *(Position decision, user 2026-10-29 — and it is the plan's own order, §Pipeline steps 4→5: M6 wired `G` to the captures as an integration convenience, and between RAW keys the fill is work refinement rewrites anyway, its video guides would condition the engine on poses the refined keys no longer hold. Today: the `G` action and Inbetweens menu are RETIRED from the window; the whole machine — controller `fill_inbetweens`, runner, adapter, worker, guides, pinning, progress wiring — stays injected and green (pinned by `tests/test_gui_inbetween_retirement.py`). Landing it needs the retarget/refinement tool (the missing link: connect the imported sparse skeleton to the animator's control rig, bake the edited animation back onto the production skeleton) — that tool is the next feature to design.)* |

### Transposition tool (Blender add-on)

The capture → control-rig retarget step the pipeline needs between the refined
re-import and the gap fill (FR-GEN-05). It ships as a Blender extension inside
this repository (`blender_addon/aimation_transpose/`) so the joint names and FBX
conventions stay the repository's, not a copy's. Feature document:
`odd/tasks/blender-transpose.md`.

| ID | Pri | Status | Requirement | Acceptance criteria |
| -- | --- | ------ | ----------- | ------------------- |
| FR-RET-01 | Must | ✅ | The selected capture is shown in its **own scene and its own window**, with play/pause and a frame slider, so the skeleton never disturbs the animator's viewport. | The working scene never contains the source armature; playback advances the tool's own clock and never the animator's playhead; an import restores the working scene's frame rate and frame range exactly; the tool's controls stay reachable from the viewer window; and the viewer shows the same motion the file holds. *(`preview.py` owns the `AImation Capture` scene, the source armature found by a custom property (a rename cannot lose it) and the secondary window; `playback.py` drives `preview_frame` from `clock.frame_at` on a `bpy.app.timers` clock; `props` mirrors it into the preview scene both ways, so dragging the preview timeline scrubs the same clock. Measured platform facts, each of which shaped the code: a UI panel cannot host a 3D view, so the viewer is a `wm.window_new()` window; the FBX importer must NOT run under `temp_override` (its edit-mode operator resolves the active object against the real context, yielding an armature with **zero bones**), so the import runs plainly and the objects are moved afterwards; the importer rewrites the importing scene's `render.fps` from the file's `CustomFrameRate` — that value is the capture's rate, read before the working scene is restored; the importer **discards stepped tangents** (`import_fbx.py:716` assumes LINEAR although FBX stores the mode), so `_make_stepped` re-asserts `CONSTANT` or the viewer would invent in-between poses the animator never keyed; `bpy.data.screens.new` does not exist, so the viewer cannot be given a private layout and the tool instead refuses to touch a `Screen` shared with another window (areas belong to the Screen, so framing or shading the viewer would hijack the animator's viewport); and bind pose is **opt-in** because `pose_position = 'REST'` does not evaluate animation at all; and the capture is imported through the **legacy importer** with `automatic_bone_orientation=True`, because at its default the importer keeps the FBX-authored axes and draws the skeleton inside-out (measured: the `Pelvis` bone spans y 90 → 170 with the flag off, y 90 → 10 with it on). Verified by `blender_addon/tests/headless_smoke.py` (50 checks, mutation-tested twice: deleting `_make_stepped` turns the between-key sample into an interpolated quaternion and fails, and re-adding a `window.width` assignment fails the source-level "assigns only writable Window properties" pin): one armature in the preview scene, none in the working scene, frame range and rate bound, working scene restored to 24 fps / 1-250 / frame 7, rotation channels that differ at keyed frames and hold between them, interpolation `CONSTANT`, `preview_owner` binding so the panel and operators resolve the tool state from the viewer window. `Window.width`, `height`, `x` and `y` are **read-only** and there is no resize operator, so the tool does not size the window — geometry is the animator's. Opening the window itself is a manual check: `--background` has no window manager (`window_new` fails its poll), and neither is the evaluated pose of a non-active scene readable reliably there.)* |
| FR-RET-02 | Must | ✅ | A remembered capture folder, an `Import Capture` button, and a listbox of that folder's FBX captures; the selected row is the capture the tool uses. | Only `.fbx` files are listed, case-insensitively sorted; `Import Capture` adopts the picked file's folder; selecting a row loads it. *(Pure `captures.py`; the folder lives in the add-on preferences because it describes the machine, not the `.blend`.)* |
| FR-RET-03 | Must | ✅ | Changing the listbox row updates the existing skeleton instead of stacking a second one. | A capture with the same bone set swaps its Action onto the existing armature and the duplicate is deleted; a different bone set replaces it; exactly one source armature exists at any time. *(Measured by the smoke: same-bone reload keeps the same object pointer and rebinds the frame range, a different bone set replaces it under the normalised name.)* |
| FR-RET-04 | Must | ⏳ | The skeleton is shown in A-pose grey; clicking a bone asks for its matching control and turns that bone green; clicking a mapped bone unmaps it. | `pose_position = 'REST'` **while mapping**, entered through the viewer's opt-in Bind pose toggle (REST never evaluates animation, so it cannot be the viewer's default); per-bone colours via `Bone.color` + `Armature.show_bone_colors`; a link is stored by bone name and survives capture reloads. |
| FR-RET-05 | Must | ⏳ | One `Transpose` button transfers the capture's animation onto the mapped controls of the selected rig. | Each link applies the constant rest offset `O = R_source⁻¹ · R_target`; keys are written only at the source's keyed frames, BEZIER; unmapped controls are untouched. |
| FR-RET-06 | Must | ⏳ | A link transfers rotation, position, or both, because a control rig mixes IK and FK (user decision: *IK en extremidades, FK en el resto*). | `ROTATION` by default, `POSITION`, `FULL`; a target carrying an `IK` constraint preselects `FULL`; the root/COG link defaults to `POSITION` so captured root motion is not lost. |
| FR-RET-07 | Must | ⏳ | A link target may be a bone or a plain empty, because poles are sometimes empties. | The pick step resolves bones of the target armature and objects of type `EMPTY`; the stored link records kind + name. |
| FR-RET-08 | Must | ⏳ | The same link table runs backwards to bake the rig's edited animation back onto the production skeleton for the application's import. | `S = T_pose · O⁻¹` over the same links; the production skeleton keeps its names, hierarchy and `Main` root; the exported file keeps the application's FBX conventions. |
| FR-RET-09 | Must | ✅ | Anything the tool cannot do is visible in the panel, never silent. | An unmapped bone, a missing capture, a failed import, a folder that does not exist, an empty frame range or a bake over zero links reports a named reason and never leaves a half-built state. *(Measured: a missing capture returns `capture not found`, a missing folder lists zero captures and resets the selection to none, and a failed import removes every object it created before returning. That last part is load-bearing: an import can fail after creating the armature — the zero-bone case FR-RET-01 documents — and the leftover must never be adopted as the source.)* |

## 3. Non-functional requirements

| ID | Pri | Status | Requirement | Acceptance criteria |
| -- | --- | ------ | ----------- | ------------------- |
| NFR-01 | Must | ✅ | `core/` and `ports/` stay free of third-party imports. | Enforced by a test/lint check on import surfaces. *(`tests/test_layering.py` reads the imports of every domain module and also rejects an adapter import.)* |
| NFR-02 | Must | ✅ | No blocking of the UI on AI/IO work. | No frozen window during extraction/generation. *(Both halves landed: extraction through `PoseExtractionRunner` and generation through `InbetweeningRunner` each run on their own `QThread` worker — the same pattern — and tests assert the UI does not wait on either engine.)* |
| NFR-03 | Must | ✅ | Errors are explicit and actionable; state stays recoverable. | Failures report a message; no silent failures. *(A damaged clip, a mark with nothing loaded, a missing rig and an unusable GL driver each name what happened; the loaded clip and its keys survive a failure.)* |
| NFR-04 | Should | ✅ | Blender read path is manual-test-only (needs a Blender install). | Documented as manual; not required in CI. |
| NFR-05 | Should | ✅ | Dark visual identity: warm dark base, orange for action/golden-pose accents, teal for active state, off-white for reading, clean 2 px panel borders with rounded corners, a taller timeline track with a round playhead knob, slightly enlarged reading text, rounded chrome on menus and the video viewer. | The approved palette (`#1E1813` / `#2D2620` / `#FF6B00` / `#EDE8E0` / `#007CA3`, user decision 2026-10-29) lives as named tokens in `adapters/gui/theme.py`; `apply_theme` puts Fusion + palette + stylesheet on the application before any window builds. Corners share one radius (6 px); the timeline groove is 10 px tall and the playhead is an 18 px round knob (unsaturated orange fill `#E08A4C`, light-gray rim `#C6C0B6` — user tuning). Reading text lifts to 10 pt Segoe UI (Windows default is 9 pt), timeline readouts to 16/14 px Rajdhani. Menu entries inset and round their selection bars; the video viewer paints its own rounded frame (clip + rim) because it draws the picture itself. Custom painters (e.g. `KeyStrip`) read the palette roles, so golden-pose markers and state colors follow the theme with no per-widget colors. Rajdhani (SIL OFL) ships in `assets/fonts` so the display look does not depend on installed fonts. Dark-only — no theme toggle for MVP. *(Fine visual tuning — hover tones, spacing — is a manual check, not CI.)* |

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
5. Project persistence (session file) or export-only? *(MVP assumption: export-only. Overlay pixel snapshots and temporary refinement observations are session-local display data; they are not persisted or included in FBX export.)*
6. One reference video per session or a list? *(MVP: one.)*
7. `AIPort` method signatures for extraction and inbetweening.
8. *(Resolved 2026-10-23, M7 planning — the animator chose the balanced
   option; amended 2026-10-24 — the animator approved re-tuning after the
   M8 S7 detection crop moved planted readings ~1 cm: drift 5.24, toe z 6.5
   on the real JACE clip, while the genuinely moving foot measured 10.86;
   amended again 2026-10-27 at R5 — the animator approved 12.0 after the
   rotating-camera clip measured planted-key drift at body-relative medians
   6.9–8.2 (max 23.9): the 5.5 bar found only 5/15 planted spans and the
   animator read the rest as sliding; at 12.0 the grounded pin found 9/15
   with key-boundary jumps cut from 4.5 to 1.7 cm, accepting the one
   step-like span ((77,93) R_Foot, 7.3 cm z travel) whose pinned output
   the animator preferred on the eye test.)*
   **Planting** = a foot's world position differs ≤ **12.0 cm**
   between the two bounding ORIGINAL keys of a span AND sits at ground contact
   (world z ≤ ground + **8.0 cm**) at both; the IK then pins the toe across
   each continuous planted run to that run's componentwise-median contact
   reading (M8: one stable target, not the first key's noisy one), holding
   it within **0.5 cm** across the whole pinned span; since M8's grounding
   mode the adoption pass also corrects the span's contact KEYS through
   each leg's own IK (FR-GEN-01's byte-exact keys survive only on
   non-planted spans — an explicit, measured trade against slide).
   Calibrated against the measured HMR2 per-frame noise (M6 T8:
   guide hits mean 3.1–6.3 cm; original balanced option 4.0/6.0 cm); the three
   numbers live as named constants in `core/foot_contacts.py` /
   `core/foot_ik.py`, adjustable without logic
   changes (`pin_foot_contacts` gained the two detection pass-throughs at
   R5, so re-tuning the PIN path needs no code either). Evidence in
   `odd/tasks/m7-ik-foot-pinning.md` S4/L4 and `odd/tasks/r5-foot-slide.md`.*
9. *(Superseded by M8 root motion, 2026-10-23.)* "Offset calculation" in
    `core/services.py`: `build_production_pose` maps a raw `WorldPose` onto the
    production hierarchy — `Main` carries the session-relative root
    displacement on X/Y/Z and keeps identity rotation; the first captured
    frame is the origin. `Pelvis` carries the residual local height after the
    root displacement, with local x/y pinned to `0`; every other joint carries
    rotation only. Translations are offsets from each joint's
    `rest_translation`, the convention the FBX writer adds back. This
    supersedes the former in-place decision and restores the plan's §5.B
    assignment of AI scene displacement to `Main`, with an honest zero-root
    fallback when the engine cannot estimate translation.
10. *(Resolved 2026-10-19, M5 T13.)* The capture GUI has no rig to preview: the rig is neither provisional nor invented - the engine reports the template's real bind offsets (`J_regressor @ v_template` of the user-supplied body model, pelvis = the 93.85 cm anchor) on its ready line, `core/production_skeleton.py` builds the SMPL chain mirrored under `Main` from them, and the `CaptureController` adopts the rig at the first successful extraction (missing offsets = typed failure, no mark). Before that the pane keeps naming the reason it is blank.
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
| 0.4.8   | 2026-10-19 | T13 closed M5: `build_window` injects the real `Hmr2Adapter` and a rig source over its bind offsets; the production skeleton is real body-model data the controller adopts at the first extraction (FR-CAP-06, open question 10 resolved). The real-engine end-to-end probe verified FR-CAP-05: VRAM flat across keys (1328.1 MiB fp16-autocast, growth 0.0; 2.66 GB fp32), fp16 numerics mean 0.84 mm / max 3.68 mm vs fp32; the fp16 recipe is autocast around the whole pipeline (plain fp16 weights fail; a double frame conversion between worker and adapter was caught and fixed by the probe). |
| 0.5.0   | 2026-10-23 | **M6 generative inbetweening landed (T1-T9, 2026-10-20..22)**: `InbetweeningPort` + Model Factory (T1), engine-agnostic sampling clock in `core/resampling.py` (T2), fake-tested `CondMDIAdapter` wire bridge (T3), `InbetweeningRunner` + `CaptureController.fill_inbetweens` + `G` action (T4), real out-of-process CondMDI worker on the vendored stack with measured VRAM/latency (T5), guide track S6 through worker/port/adapter/core/controller (T6-T8), and anchor-dense capture for narrow gaps (T9). FR-GEN-01 ✅, FR-GEN-02 🟡 (no in-app engine picker yet), FR-GEN-03 ✅ (1831 MiB / ~64 s per fill, real RTX 3080), NFR-02 ✅. Roadmap: **M7 (IK foot pinning) → M8 (final generative export)**. |
| 0.6.0   | 2026-10-23 | **M7 IK foot pinning landed**: contact spans detected in the original keys (balanced thresholds: 4.0 cm between keys, 6.0 cm above ground), analytic two-bone pin holds planted toes within 0.5 cm with zero clamps, wired at fill adoption. FR-IK-01 ✅. |
| 0.6.1   | 2026-10-24 | **M8 root-motion iteration**: captured HMR2 root trajectory on `Main` (first captured frame as origin, `Pelvis` residual height) + anchor-padded root-jitter smoothing at fill adoption + root-invariant planted-foot detection (`_planting_read`) — the last one fixed real sliding feet the root noise had un-detected (real e2e restored: (40,55) detected, 14 rows pinned, hold ≤ 0.5 cm). |
| 0.6.3   | 2026-10-28 | **Pose video overlay**: engine-side full-frame projection, stepped colored skeleton overlay, hidden legacy viewport, COCO limb refinement, and MediaPipe PoseLandmarker hand/foot refinement. |
| 0.6.4   | 2026-10-28 | **Recent videos (FR-CAP-09)**: File ▸ Recent Files keeps the last five clips that actually loaded, most recent first, reopened by selecting the entry; persists through `QSettings`; pure rule in `core/recent_files`. |
| 0.6.5   | 2026-10-28 | **FBX import action (FR-IMP-04)**: File ▸ Import FBX… (`Ctrl+I`) adopts the refined FBX as the session timeline — requires a loaded video, confirms before discarding captured keys, resets capture-only state, and previews each refined pose front-view over the clip (honest approximation, no engine needed). |
| 0.6.6   | 2026-10-29 | **Dark theme (NFR-05)**: warm dark identity — Fusion + palette + QSS in `adapters/gui/theme.py`, approved tokens (`#1E1813`/`#2D2620`/`#FF6B00`/`#EDE8E0`/`#007CA3`), 2 px borders with rounded corners (6 px), taller timeline track with a round orange playhead knob, reading text at 10 pt, menus and the video viewer rounded, bundled Rajdhani for display readouts. |
| 0.6.7   | 2026-10-29 | **Inbetween UI retired (FR-GEN-05)**: the `G` action and Inbetweens menu leave the window — the fill belongs AFTER the animator's refined re-import (the plan's own step order), not between raw captures. The entire machine (controller, runner, adapter, worker, guides, pinning, progress) stays injected and tested; re-positioning it is one menu line once the retarget tool exists. |
| 0.6.2   | 2026-10-24 | **M8 final generative export landed**: File-menu "Export FBX…" / `Ctrl+E` writes the approved timeline (keys + fills) through the real binary FBX writer with the approved KTime range declared; honest status-bar refusals; real-file round-trip through Blender verified 48 frames / float32-exact / pinned foot held (FR-GEN-04 ✅). Feature doc: `odd/tasks/m8-final-export.md`. |
| 0.7.1   | 2026-10-30 | **Viewer import corrected**: captures are imported through the legacy importer with `automatic_bone_orientation=True`, because at its default the importer keeps the FBX-authored axes and drew the skeleton inside-out (measured: `Pelvis` spans y 90 → 170 with the flag off, y 90 → 10 with it on). The application's read bridge deliberately keeps the importer's defaults — every validated FBX round trip (FR-IMP-01/02, FR-EXP-02) is against the basis that convention produces, so PR 4's return bake must respect the split instead of flattening it. Also recorded: `bpy.ops.wmf.fbx_import` is a name without a registered operator in 5.2.3. Smoke 50 → 52 checks, mutation-tested. |
| 0.7.0   | 2026-10-30 | **Transposition tool opened (FR-RET-01..09)**: the retarget step the pipeline was missing. Ships as a Blender extension inside this repository. PR 1 = the isolated viewer — source armature in its own `AImation Capture` scene, its own window, its own `bpy.app.timers` clock with play/pause and a frame slider, capture folder + `Import Capture` + listbox, and same-bone reload that swaps the Action instead of stacking a skeleton (FR-RET-01..03, 09 ✅; 04..08 ⏳). Platform findings that shaped the code: the FBX importer must NOT run under `temp_override` — its edit-mode operator resolves the active object against the real context, so an overridden scene yields an armature with zero bones; the importer **discards stepped tangents** (`import_fbx.py:716` assumes LINEAR), so the viewer re-asserts `CONSTANT` or it would show poses the animator never keyed; `bpy.data.screens.new` does not exist, so the tool refuses to touch a `Screen` shared with another window rather than hijacking the animator's viewport; and bind pose is opt-in because `pose_position = 'REST'` does not evaluate animation at all. Feature doc: `odd/tasks/blender-transpose.md`. |

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

- M5 T13 (2026-10-19, `feat/develop`): the real production skeleton and the real
  wiring. `core/production_skeleton.py` mirrors SMPL's chain under `Main` (the 23
  canonical names + kintree parents), built from bind offsets the worker computes
  from the body model's template buffers and rides on the ready line; the
  `CaptureController` adopts it at the first extraction (typed failure when the
  offsets are missing or broken; the pane stays blank until then). The worker now
  runs fp16 correctly (autocast around both the backbone and the SMPL recovery,
  plus the template anchor call) - the end-to-end probe on the real engine showed
  ready in ~12 s, flat 1328.1 MiB across 6 keys, fp16 vs fp32 mean 0.84 mm, and
  caught two real defects the fake cannot see: a template call that crashed on
  fp16 weights before ready, and a double SMPL-to-domain conversion of the
  offsets. 124 tests green, `ruff check` clean.

- **M6 generative inbetweening (2026-10-20..22, `feat/develop`, T1-T9 done;
  evidence in `odd/tasks/m6-inbetweening.md`):**
  - Factory + port (T1): `InbetweeningPort` (timeline in, timeline out, keys
    untouched) and `model_factory.py` with typed `UnknownEngineError`;
    `main.py` builds both engines through the factory.
  - Engine-agnostic sampling clock (T2): `core/resampling.py` — slerp,
    `interpolate_pose`, `resample_dense_poses`, and `fill_gap_synthetically`
    (the S1 rule materialized: keys byte-untouched, every gap frame filled or
    raised, no writes outside the locked span).
  - Adapter + worker (T3/T5): `CondMDIAdapter` subprocess bridge over the
    official vendored stack in its own venv (`.engine/condmdi-venv`); the real
    checkpoint validated on the RTX 3080 — VRAM peak 1831-1832 MiB, ~64 s warm
    per fill, span up to the 193-sample window. Two runtime conditioning bugs
    and a bind-conjugation bug were found by animator reports and fixed
    worker-side (vendored code never patched): metric retarget offsets,
    abs-3d canonical yaw, and per-joint minimal-rotation bind conjugation
    (worst wrist error 98.8 cm → 5.1 cm).
  - GUI path (T4): `InbetweeningRunner` (`QThread`, batch-1) +
    `CaptureController.fill_inbetweens` + `G` in the Inbetweens menu; the fill
    adopts through the existing `timeline_changed` wiring.
  - Guide track S6 (T6-T8): captured video frames between the gap's keys enter
    the engine as observation rows (HMR2 per-frame extraction every ~12 engine
    samples, cap 8/gap), reasserted byte-exact through core anchors; the
    controller gathers them through the same batch-1 extraction machinery,
    degrading to keys-only on any capture problem. GPU-validated (probe 8:
    the fill follows the capture's phase where keys-only stood flat).
  - Anchor-dense narrow gaps (T9, user decision L24): a gap spanning ≤ 25
    timeline frames anchors EVERY interior frame via HMR2 and is filled
    straight from the capture — no engine request, lazy worker spawn. Real
    e2e (JACE_REF_04, keys 46/71): 26 frames captured, coverage complete,
    byte-exact reassertion 0 mismatches; the arm columns follow the capture
    where every keys-only/guided control splayed. A latent batch-1 race in the
    dense gather was found and fixed (busy start now waits for the runner's
    `busy_changed(False)`).
  - Suite 282/0/0/0, ruff clean. Delivery: work-unit commits straight to
    `feat/develop` (user 2026-10-22, no PR slices), pushed on request.

**Next**

1. ✅ **M7 — IK foot pinning (FR-IK-01) landed (2026-10-23).** Threshold
   question 8 resolved at the balanced option (4.0 cm between keys, 6.0 cm
   above the ground); real-clip e2e verified on JACE_REF_04 (span 40..87).
   Feature doc: `odd/tasks/m7-ik-foot-pinning.md`.
2. ✅ **M8 — final generative export (FR-GEN-04) landed (2026-10-24).** The
   approved timeline (keys + fills) exported from the GUI with the blocking
   FBX conventions, frame range preserved. Feature doc:
   `odd/tasks/m8-final-export.md`. The M8 root-motion iteration (captured
   trajectory on `Main`, root-jitter smoothing, root-invariant contact
   detection) rode this milestone: `odd/tasks/m8-root-motion.md`.
3. ✅ **M9 — wide-gap fill cost (init-prior + skip_timesteps) landed
   (2026-10-26).** The M6 remedy landed and measured; the wide-gap quality
   premise was falsified with evidence (content skip-insensitive, ~1.5 deg
   over the whole sweep) and the measured default halves fill latency
   (70.6 -> 31.6 s). Feature doc: `odd/tasks/m9-wide-gap-prior.md`. The
   MVP tracks as closed here; the remaining quality follow-ups (anchor
   seam, ruido de captura, bent-knee, refactors) are the "afinar" phase,
   to be scheduled by task with the animator.
4. ✅ **Refinement R1 — capture progress bar landed (2026-10-26).** The
   controller reports the guide gather through `guide_progress(done, total)`
   and exposes `fill_active` / `extraction_busy`; the capture window maps
   that onto one `QProgressBar` on its own strip directly below the time
   slider: determinate while
   guides are collected between Golden Poses, indeterminate while the
   engine generates or a solo `K` extraction runs, and hidden whenever
   nothing is in flight (a new clip ends an in-flight fill at once). While
   any of that is in flight **the process survives user input — it does not
   block it**: scrubbing, stepping, key jumps and playback stay fully live.
   The gather is interruption-proof by construction: every guide retry
   re-seeks its own target (so a mid-gather scrub delays that guide rather
   than stealing the pane's frame from it), a frame that proves a different
   index is never adopted as a guide, every extraction answer is attributed
   to the frame it started from, and the hand-off returns the decoder to
   the animator's playhead. Only the two mutations that would genuinely
   break the started process are refused at the controller boundary, each
   as a reported non-fatal message (NFR-03): `mark_current` (K steals the
   batch-1 slot between guides, or a new key collides with the guide plan
   the worker rejects) and `remove_current` (the hand-off reads the keys
   again and the adoption would silently overwrite a mid-fill deletion).
   Export (a read) and opening a new clip (the deliberate restart/escape
   hatch) stay unlocked.
   The status bar keeps its text; the bar answers "is it working?" at a glance.
5. Parked: FR-GEN-02's in-app engine picker — the factory call site suffices
   while the MVP has exactly one inbetweening engine; revisit with the second
   engine.

**Known follow-ups**

- **Wide-gap fill quality (M6 carry-forward, M9 measured).** Gaps WIDER than
  ~24 interior frames still go through the model and keep the free-row splay
  diagnosed in L23 (`odd/tasks/m6-inbetweening.md`): rows not covered by an
  observation condition weakly and drift toward a degenerate prior. M9 (2026-10-26)
  landed the prepared remedy and MEASURED it (`odd/tasks/m9-wide-gap-prior.md`):
  the fill request accepts `skip_timesteps`, the worker seeds the diffusion's
  `init_image` with the request's own dense capture prior (keys exact, guides
  stamped, lerp underneath) and starts `p_sample_loop` partway down the
  1000-step chain; guided engine gaps carry the measured constant
  `_CAPTURE_PRIOR_SKIP_TIMESTEPS = 500`. The probe sweep (keys 40/87 of the
  real clip, skips 0/300/500/700/850) showed the interior content is
  **skip-insensitive within ~1.5 deg** (the per-step observation replant
  dominates the free rows — the L23 verdict reconfirmed at the init level),
  while latency scales with the skip (70.6 -> 31.6 s at 500; facing
  positive-share constant 85.1%). So M9's value is cost per wide gap, not
  content. Remaining, for the "afinar" phase in priority order: (1) the
  **anchor-vs-fill seam — feathered (R2, 2026-10-26)**: captured anchors sat
  far from the model's content in joint space (mean 78.8 deg L+R arm jump at
  the six anchor-boundary rows on the real clip), so boundary rows snapped.
  Adoption now runs `core/seam.py::feather_anchor_seams` (after root
  smoothing, before pinning): free rows within `window` of the nearest
  anchor blend toward it along `slerp`, alpha decaying with distance,
  continuous rows under a 30 deg threshold untouched, anchor rows byte-exact
  by construction. The measured grid (one real fill, window 2/4/6 x strength
  0.6/0.8/1.0) adopted the middle setting `window=4, strength=0.8`: mean
  boundary jump 78.8 -> 42.0 deg (-47%) with 24 of ~47 interior rows eased
  and worst single-joint motion 96.9 deg; the aggressive `w6/s1.0` reached
  30.1 deg but pushed some joints 130 deg off the model's content — trading
  the pop for an anchor-hugging glide, rejected on evidence. Feature doc:
  `odd/tasks/r2-anchor-seam.md`. (2) the **generated-row tremor — damped
  (R3, 2026-10-27)**: the user's matiz relocated the old "residual capture
  noise" label — the Golden Poses are clean; the frame-to-frame vibration
  lives in the engine's free rows. Adoption now runs
  `core/jitter.py::damp_generated_jitter` (after feathering, before
  pinning): each free row's joint rotations blend by
  `slerp(original, kernel_mean, strength)` toward a sign-aligned binomial
  neighbourhood mean (`[1 4 6 4 1]` at radius 2, renormalised at sequence
  edges, >=3 samples required); anchors byte-exact, `Main` never filtered,
  translations never move. The measured grid (one real fill, feathered
  first — production order — radius 1/2/3 x strength 0.5/0.75/1.0) adopted
  `radius=2, strength=0.75`: mean tremor signature (a free row's angle off
  the slerp-midpoint of its neighbours, 968 row-joint samples) 2.55 ->
  1.70 deg (-33%) with worst single-joint motion 9.0 deg; `r2/s1.0`
  reached -40.6% but moved joints 12.0 deg, and `r3` bought nothing over
  `r2`. Residual boundary pop and (3) free-row content itself remain
  model-limited (a different checkpoint/backbone, e.g. sequence-native
  models, is the prepared direction — see §4.12's superseded GVHMR
  analysis for why single-image engines cannot fix it alone). Feature
  doc: `odd/tasks/r3-generated-jitter.md`. (4) the **planted-foot slide —
  re-tuned (R5, 2026-10-27)**: the user's app test reported the feet
  sliding "bastante" whenever they should be planted, worst when the
  camera rotates — and in the KEYS-ONLY export too, which no pass ever
  processed. The `.engine/_diag_foot_slide.py` probe over the user's own
  pair measured planted-key drift at body-relative medians 6.9-8.2 cm
  (max 23.9): M8's grounding pin was ON but its 5.5 cm planting bar saw
  only 5/15 spans on this clip. `pin_foot_contacts` gained the two
  detection pass-throughs (OQ8's "adjustable without logic changes" is
  now true on the pin path too), and the grounding sweep showed the
  clamp-snap artefacts of a raised bar under plain pinning do NOT
  reproduce with grounding (key-boundary jumps 4.5 -> 1.7 cm at every
  bar). The animator chose the bar at **12.0** by eye (9/15 planted,
  accepting the one step-like span (77,93) whose pinned output they
  preferred); the residual is clip-dependent by nature — a quieter clip
  may over-freeze at 12, which the pass-throughs exist to re-tune
  without code. Feature doc: `odd/tasks/r5-foot-slide.md`.
- **Root trajectory quality remains model-limited.** M8 now captures the HMR2
  pelvis/camera translation where available, makes the first captured frame the
  origin, carries relative X/Y/Z through `Main`, preserves it through the
  inbetween wire, and exports it; the fill adoption applies a robust jitter
  filter (median-3 ×2, then a quarter-half-quarter average, anchor-padded) to
  interior rows' `Main` translation while original keys keep their exact
  captured values. Two M8 fixes made forward motion real (2026-10-24): the
  worker no longer feeds HMR2 a full-frame box but auto-detects the largest
  qualifying person per frame (torchvision Faster R-CNN MobileNetV3, COCO
  weights, honest full-frame fallback), and the half-precision focal-length
  overflow that had made **every** root depth `+inf` (hence silently zero) is
  fixed (fp32; the detector costs ~0.03 s and ~100 MB of resident VRAM per
  frame on an RTX 3080). Camera-space depth still carries the engine's telephoto focal
  assumption, so the controller calibrates the relative depth once per clip by
  `subject_distance_m / tz_first` (default 3 m, the animator's real distance
  to the subject at the first key — lateral and vertical channels
  self-calibrate through the projection). The GUI setting landed
  (2026-10-26): the capture window ships a "Subject distance" control beside
  the timeline writing `controller.subject_distance_m`; it stays editable
  until the first Golden Pose locks the clip's calibration
  (`CaptureController.depth_calibrated`) and re-enables on the next clip
  load, because a mid-clip change would be a silent no-op. **Measured frame conventions (2026-10-26, S9).** The engine's
  root translation lives in the camera's Y-down frame: domain depth is
  `+tz` (a person in front of the camera sits at positive depth, facing the
  canonical `-Y` front) and height is `-ty`; the earlier `(x, -tz, +ty)`
  reading mirrored depth/height and made a person advancing toward the
  camera walk backward in the export (facing settled at `-Y` while `Main`
  moved `+Y`). The depth calibration reads `tz_first = origin.y / 100`.
  HMR2 remains a single-image weak-perspective estimator, so
  absolute scale and camera-motion separation are best-effort; validate long
  clips against the reference video.
- **Bent-knee prior on webcam footage (crop hypothesis tested and falsified,
  2026-10-24).** The animator reported Golden Poses exported with knees deeply
  flexed (~40–55°), toes off the ground, and hip-forward offsets on a clip of
  a clearly standing subject (JACE_REF_04). Hypothesis: the worker's
  full-frame box (`hmr2_worker._run_request`) is out-of-distribution; a tight
  box should fix it. Measured on the real frames with a clean-room probe
  (canonical SMPL-24 FK, engine examples as positive controls): a visually
  verified tight crop (subject ≈77% of the input) reproduces the same bent
  knees (f46: tight 50.9/38.7° vs full 46.0/41.6°), on both checkpoint
  variants — the crop changes little; the flexion is HMR2's prior on
  full-body wide-angle footage, not a box or export defect. The export path
  was independently proven faithful (FR-GEN-04 T2 byte-exact round trip).
  Candidate remedies (unresolved, product decision): grounding the root Z so
  planted feet meet the floor at fill adoption; a landmark-based lifting
  engine (Apache-2.0 path, new adapter behind the existing factory); or
  treating cleanup as the animator's refine pass, which the pipeline already
  budgets for.
- **Do not "connect" imported bones in Blender.** Measured on the exported
  file with a three-way headless import (default vs `automatic_bone_orientation`
  + `force_connect_children` vs a manual edit-mode connect script): the default
  import reproduces the FBX faithfully, while either connect variant rewrites
  the rest bone geometry (head/tail/roll) without remapping the animation
  curves, displacing the ankle up to ~55 cm and the knee ~13–16 cm. Our rig is
  pure joints with identity bind, so the animator should import the FBX as-is
  and change only viewport display settings, never rest positions.
- **AIPort has both implementations landed** (T11/T12/T13 for capture,
  T3/T5/T9 for inbetweening). The refactor M6 L8/L10 parked — "the two
  adapters carry ~120 duplicated subprocess-bridge lines and the two
  runners are near-mirrors" — **landed as R4 (2026-10-27)**:
  `adapters/ai/engine_bridge.py` now owns the JSON-lines worker lifecycle
  both adapters repeated (Popen flags, reader thread, protocol-line
  filter, ready handshake, request round trip, the teardown that must
  never orphan a CUDA context), with the engine-specific timeouts,
  validation, bootstrap payload and typed error composed in — every
  user-visible message byte-identical. `adapters/ai/thread_runner.py`
  owns the batch-1 QThread lifecycle both runners mirrored; the concrete
  runners keep their typed `start(...)` and outcome signals. Pure
  refactor: suites green with zero assertion edits except the one test
  pin that followed the mechanics (`_worker` -> `_bridge.worker`).
  Feature doc: `odd/tasks/r4-aiport-bridge.md`.
- **ProRes (FR-CAP-01) — verified 2026-10-27.** Until the R5 close-out
  only H.264 had been played. A real ProRes clip was produced with the
  tooling already in the pipeline (`ffmpeg -c:v prores_ks -profile:v 3`
  = ProRes 422 HQ, 1920x1080, 30 fps, 6 s from the JACE reference) and
  the animator opened it in the app with no issue. No code change was
  needed — QtMultimedia's FFmpeg backend decodes it through the same
  streaming path as H.264. The test clip is disposable
  (`.engine/jace_prores_6s.mov`, 164 MB, untracked).
- A mark pressed immediately after a scrub can be refused with "Could not read
  the frame at the playhead." — refusing is deliberate (the alternative is
  extracting a neighbouring frame silently), but the capture could instead wait
  for the pending frame and then proceed. Add that only if real use shows the
  refusal is common.
- Failure reporting is non-modal (status bar). Worth revisiting for a failed
  *open*, where the animator picked the bad file and a line of text is easy to
  miss. *(Opened as open question 11.)*
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
