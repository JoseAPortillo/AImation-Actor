# Blender Transposition Tool

Branch: feat/blender-transpose
Delivery: one PR per work unit (viewer -> mapping -> retarget -> return bake); test runner: `.venv/Scripts/python.exe -m pytest -q --basetemp="$env:TEMP/aim-tmp"`
Contract: production joint names (`core/production_skeleton.py`), FBX conventions (`AGENTS.md`), `anim_offset = 0.0` on every capture import.

## Specs

1. **S1 — Isolated capture viewer.** The selected capture must be visible on its
   own, never inside the animator's working viewport.
   User, verbatim: *"podemos tener un visor 3d en el UI de la tool para poder
   visualizar el esqueleto importado aislando este a ese ventana 3d con un
   botón play/pause un timeslider que el usuario pueda ver la animación y el
   esqueleto no moleste en el viewport."*
   Acceptance: the source armature lives in its own scene (`AImation Capture`)
   and is shown in a secondary Blender window; the working scene never
   contains it; playback is driven by the tool's own clock (`preview_frame`),
   never by the animator's timeline; play/pause and a frame slider live in the
   tool panel.
   Checks: pure clock tests; headless smoke proving the armature lands in the
   preview scene and not in the working scene.

2. **S2 — Capture folder, import button, and listbox.** The tool lists the
   captures the animator exported and applies the selected one.
   User, verbatim: *"Dentro de la ventana de la herramienta de transposición
   podremos seleccionar el fbx a exportar, debajo del botón import capture,
   tendremos un listbox con varios fbx que hayamos podido capturar. Se aplica
   sobre el rig el que tengamos seleccionado en el listbox."*
   Acceptance: a remembered capture folder feeds a `UIList` of its `*.fbx`
   files, case-insensitively sorted; the `Import Capture` button opens a file
   picker and adopts its directory; selecting a row loads that capture.
   Checks: pure listing/sorting tests; headless smoke of the list refresh.

3. **S3 — Reload without duplication.** Changing the listbox row updates the
   existing skeleton instead of stacking a second one.
   User, verbatim: *"se cargará el fbx y cuando cambiemos en el listbox el fbx
   se actualizara en el esqueleto si ya existe, sino, lo carga como nuevo."*
   Acceptance: when the incoming capture has the same bone set, its Action is
   swapped onto the existing source armature and the duplicate is deleted;
   otherwise the old source is replaced. Exactly one source armature exists at
   any time.
   Checks: headless smoke with two synthetic captures (same bones -> one
   armature, action swapped).

4. **S4 — A-pose, grey/green mapping surface.** The skeleton is shown in rest
   pose with unmapped bones grey; clicking a bone asks for its control;
   a completed link turns that bone green.
   User, verbatim: *"de forma visual, tendremos un esqueleto en a-pose dentro
   de la ventana de la tool, el usuario marcara las parte del esqueleto que
   quiere transponer, el esqueleto aparece gris si pulsa un bone de ese
   esqueleto te pedirá que selecciones el control que corresponda a ese hueso.
   ej: si pulso el hueso de la mano en el UI tendría que seleccionar el control
   de la mano en el rig. una vez seleccionado este hueso se tornará verde si la
   conexión se ha realizado."*
   Acceptance: `pose_position = 'REST'` while mapping; per-bone custom colours
   (grey -> pending -> green) via `Bone.color` + `show_bone_colors`; a link is
   stored by name and survives capture reloads.
   Checks: headless smoke of colour state transitions; pure map-serialisation
   tests.

5. **S5 — Transpose.** One button moves the capture's animation onto the mapped
   controls of the selected rig.
   User, verbatim: *"Finalmente tendremos un botón Transpose o similar que
   indique al usuario que con ese botón se pasa la animación del esqueleto a
   los controles del rig seleccionado."*
   Acceptance: each mapped pair is applied with the constant rest offset
   `O = R_source⁻¹ · R_target`; the bake writes keys only at the source's keyed
   frames (sparse, BEZIER); unmapped controls are untouched.
   Checks: pure `retarget_math` tests (rest-offset round trip, sparse frame
   selection).

6. **S6 — Per-link mode with IK detection.** A link transfers rotation,
   position, or both, because a control rig mixes FK and IK.
   User decision: *IK en extremidades, FK en el resto.*
   Acceptance: `ROTATION` (default), `POSITION`, `FULL`; a target bone carrying
   an `IK` constraint preselects `FULL`; root/COG mapping defaults to
   `POSITION` so captured root motion is not lost.
   Checks: pure mode-resolution tests; headless smoke with a stubbed IK
   constraint.

7. **S7 — Rig-agnostic targets.** A link target may be a bone or a plain object,
   because poles are sometimes empties.
   Acceptance: the pick step resolves bones of the target armature and objects
   of type `EMPTY`; the stored reference records kind + name.
   Checks: pure resolution tests.

8. **S8 — The same table runs backwards.** The return bake writes the rig's
   edited animation back onto the production skeleton, so the application can
   import the refined sparse FBX.
   Acceptance: `S = T_pose · O⁻¹` over the same links; the production skeleton
   keeps its names, hierarchy, and `Main` root; export stays the app's FBX
   writer conventions.
   Checks: pure inverse round-trip tests; headless smoke of the baked action's
   channel names.

9. **S9 — Honest limits.** Anything the tool cannot do must be visible, not
   silent.
   Acceptance: an unmapped bone, a missing capture, a failed import, an empty
   frame range, or a bake over zero links reports a named reason in the panel
   and never leaves a half-built state.
   Checks: pure guard tests; headless smoke of the empty-folder path.

## Tasks

| ID | Spec | Route | Status | Commit |
| -- | ---- | ----- | ------ | ------ |
| T1 | S1, S2, S9 | inline | done | `f840ac3` (PR #9) — Add-on package: extension manifest, preferences, capture listing, preview scene, import/refresh into it, panel + UIList. RED/GREEN: pure `captures`/`clock` tests; `headless_smoke.py` checks the preview scene owns the only armature, the working scene owns none, and a missing folder/capture fails named. |
| T2 | S1, S9 | inline | done | `f840ac3` (PR #9) — Secondary window, play/pause, frame slider, independent clock mirrored into the preview scene. RED/GREEN: `clock.frame_at` tests (advance, truncate, wrap, non-zero range start, no rate, empty and single-frame ranges); smoke checks the frame range/rate binding and that the working scene comes back at 24 fps / 1-250 / frame 7 after an import. The window itself is a manual check. |
| T3 | S4 | inline | pending | Mapping `CollectionProperty`, click-to-map modal picking (bones and empties), grey/pending/green colours, persistence. |
| T4 | S5, S6 | inline | pending | Pure `retarget_math`, `Transpose` operator, sparse bake, root motion. |
| T5 | S8 | inline | pending | Return bake onto the production skeleton + export. |

## Log

- **L1.** User, verbatim: *"vamos con la transposición.
  Dentro de la ventana de la herramienta de transposición podremos seleccionar
  el fbx a exportar, debajo del botón import capture, tendremos un listbox con
  varios fbx que hayamos podido capturar. Se aplica sobre el rig el que
  tengamos seleccionado en el listbox.
  de forma visual, tendremos un esqueleto en a-pose dentro de la ventana de la
  tool, el usuario marcara las parte del esqueleto que quiere transponer, el
  esqueleto aparece gris si pulsa un bone de ese esqueleto te pedirá que
  selecciones el control que corresponda a ese hueso. ej: si pulso el hueso de
  la mano en el UI tendría que seleccionar el control de la mano en el rig.
  una vez seleccionado este hueso se tornará verde si la conexión se ha
  realizado.
  Finalmente tendremos un botón Transpose o similar que indique al usuario que
  con ese botón se pasa la animación del esqueleto a los controles del rig
  seleccionado.
  Visualización del esqueleto importado del fbx, este lo veremos en el propio
  viewport de blender, se cargará el fbx y cuando cambiemos en el listbox el
  fbx se actualizara en el esqueleto si ya existe, sino, lo carga como nuevo."*
- **L2.** User correction/extension, verbatim: *"podemos tener un visor 3d en
  el UI de la tool para poder visualizar el esqueleto importado aislando este a
  esa ventana 3d con un botón play/pause un timeslider que el usuario pueda ver
  la animación y el esqueleto no moleste en el viewport. Añade esto al plan"*
  — accepted: the source lives in its own scene shown in a secondary window, so
  isolation is architectural, not a viewport toggle.
- **L3.** User decision, verbatim: *"IK en extremidades, FK en el resto"* —
  the link mode is resolved per bone, with `FULL` preselected when the target
  carries an IK constraint.
- **L4.** Platform findings (2026-10-30, Blender 5.2.3 LTS, verified by
  `--background` introspection): `Bone.color.is_custom` + `custom` exist
  (per-bone grey/green is real), `Armature.show_bone_colors` exists,
  `PoseBone.matrix` is writable, `nla.bake` exposes `visual_keying` /
  `bake_types`, `wm.window_new` exists, `Window.scene` and `Area.type` are
  writable, `app.timers.register` exists. A UI panel cannot host a 3D view, so
  the viewer is a secondary window — stated to the user before the plan closed.
- **L5.** Scope decisions: the add-on ships inside this repository (the joint
  names and FBX conventions are the contract and must not drift); the pure
  retarget math stays `bpy`-free so it runs under the repository's pytest, and
  the `bpy` shell is validated with a headless smoke script - the same policy
  as the FBX read bridge.
- **L6.** Import-context finding (2026-10-30, measured, Blender 5.2.3 LTS): the
  FBX importer must **not** run under `bpy.context.temp_override(scene=...)`.
  The override puts the objects in the right scene, but the importer builds the
  armature by entering edit mode through an operator, and that operator resolves
  the active object against the *real* context - the result is an armature with
  **zero bones** and a `KeyError: 'bpy_prop_collection[key]: key "Main" not
  found'` in `set_pose_matrix_and_custom_props`. Probe: plain import produced
  `bones=['Main','Pelvis','L_Ankle']`, the overridden import produced `bones=[]`
  while the objects did land in the overridden scene. Fix: import plainly into
  the working scene, then move the created objects into the preview scene, and
  restore the working scene's `render.fps`, `render.fps_base`, `frame_start`,
  `frame_end` and `frame_current` (assigned, never `frame_set`, so no handler
  runs). The importer rewrites `render.fps` from the file's `CustomFrameRate` -
  that rewritten value is exactly the capture's frame rate, and is read before
  the restore.
- **L7.** Verification evidence for T1/T2 (2026-10-30):
  `tests/test_blender_addon_captures.py` + `tests/test_blender_addon_clock.py`
  (22 tests) pass; `ruff check .` clean; `headless_smoke.py` passes 27 checks -
  preview scene owns exactly one armature, working scene owns none, the source
  is marked and in REST, range (0, 30) and 30 fps bound from a 30 fps capture,
  same-bone reload reuses the same object pointer and rebinds to (0, 20), a
  different bone set replaces it under the normalised name with the new bone
  present, a missing capture returns a named reason, a 0-byte capture fails the
  import and leaves the working scene untouched (the S9 cleanup), and a missing
  folder lists zero captures with the selection reset. The full pytest suite was
  green on a clean run; an unrelated `test_ai_hmr2_adapter` timeout test is flaky
  in this environment and fails on `main` too (verified in a worktree at
  `c55edad`). Not verified, by design: opening the secondary window
  (`--background` has no window manager).
- **L8.** Delivery (2026-10-30): T1+T2 committed as `f840ac3` on
  `feat/blender-transpose`, pushed, and opened as **PR #9** against `main`
  (1723 added lines). Delivery strategy `ask-on-risk` resolved by the user at
  **one PR with `size:exception`**: the viewer does not function split in half
  (without the import there is nothing for the panel to show), so a pure-modules
  PR would be dead code. The label `size:exception` was created on this repo for
  that reason, with the description *"Knowingly larger than a review slice:
  splitting it would ship code that cannot run"*. Slice boundary: PR #9 holds
  `f840ac3` only. The next slice is T3 (FR-RET-04/06/07, click-to-map), then T4
  (FR-RET-05/06, Transpose), then T5 (FR-RET-08, return bake).
- **L9.** User bug report on PR #9, verbatim: *"el listado de fbx esta bastante
  bien resuelto, pero al abrir la vista se abre una ventana nueva con el
  esqueleto que tiene las claves pero no el movimiento y al abrir ese visor la
  tool aimation transpose desaparece del menu de blender"*. Three defects found,
  two of them mine, all three measured before being fixed:
  1. **Frozen skeleton (mine).** `preview_rest` defaulted to `True`, and
     `pose_position = 'REST'` does not evaluate animation at all — the skeleton
     shows in bind pose with its keys sitting right there. The default is now
     `False` (POSE); bind pose became an explicit, opt-in toggle labelled "Bind
     pose", and the panel says outright that it freezes the animation.
  2. **Panel disappears in the viewer window (mine).** `poll` hid the panel
     whenever `context.scene` was the preview scene — which is exactly what the
     viewer window's context scene is. All tool state lives on the *animator's*
     scene, and RNA properties registered on `bpy.types.Scene` exist as empty
     copies on every scene, so drawing them in the viewer window would have
     driven nothing. The preview scene now records its owner in a real
     `preview_owner` PointerProperty (auto-cleared when that scene goes away,
     which a name-based lookup is not), and `props.tool_scene` / `owner_of`
     resolve it for the panel, every operator and the preferences update
     callback. The tool is now reachable from either window.
  3. **Invented in-between poses (Blender's importer, not our writer).** The
     file is genuinely stepped (`KeyAttrFlags = 24836` = CONSTANT), but the
     importer never reads that field: `import_fbx.py:716` says *"Currently,
     linear interpolation is assumed, but FBX does store how keyframes should be
     interpolated"*. `preview._make_stepped` re-asserts CONSTANT on every loaded
     keyframe. Mutation-tested: with that call deleted the sample between keys
     comes back `(0.4714, 0.8047, 0, 0)` — a quaternion the animator never
     keyed — and the interpolation set is `{'LINEAR'}`; with the fix it holds the
     previous key and the set is `{'CONSTANT'}`.
  Handled in the same pass: the viewer tags its windows for redraw (the clock
  advances from a timer while another window is active, so nothing else would
  repaint it), and `_configure_viewports` / `_frame_armature` refuse to touch a
  `Screen` shared with another window — areas belong to the Screen, not to the
  window, so framing or shading the viewer would have rewritten the animator's
  own viewport. `bpy.data.screens.new` and `Screen.copy` do not exist in 5.2.3
  (measured), so a private layout is not something the tool can create.
- **L10.** Smoke evidence after L9: 41 checks (was 27), all green, `ruff check .`
  clean, 22 pure tests green, full suite green. L9+L10 landed as `dccef35` on
  `feat/blender-transpose` (362 insertions), pushed into PR #9. The capture
  builders now rotate about the domain X
  axis, because the first version wrote identity rotations for every key and
  therefore **could not have caught a viewer that shows a frozen pose** — that
  blind spot is why this report reached a human instead of the smoke. Reading the
  evaluated pose of a *non-active* scene proved unreliable in background mode
  (the first read lags, later reads can freeze), so motion is pinned on the
  fcurves with `FCurve.evaluate`, which is deterministic; "the skeleton visibly
  moves in the viewport" now joins the window and the panel drawing as a manual
  check.
- **L11.** Second user report, verbatim: *"error de blender: Python: Traceback
  (most recent call last): ... operators.py, line 126, in execute /
  ok, message = preview.open_window() ... preview.py, line 320, in open_window /
  window.width = _PREVIEW_WINDOW_WIDTH ... AttributeError: bpy_struct: attribute
  "width" from "Window" is read-only"*. Root cause: the viewer sized its window
  through `Window.width` / `Window.height`, both read-only in 5.2, and there is
  no resize operator — so window geometry is simply not something the tool may
  set. Removed with the constants. The traceback also proved `wm.window_new()`
  itself works interactively (it reached the next line), which no headless run
  can show, and that their installed copy at
  `%APPDATA%\...\extensions\user_default\aimation_transpose` was the pre-fix
  build.
  Response to the class of bug, not just the instance: the smoke now pins the
  **whole write surface** the viewer uses. `Window.scene` and `Window.view_layer`
  must be writable; `width/height/x/y` must be read-only (the reason we do not
  set them); `View3DShading.type`, `View3DOverlay.show_relationship_lines` and
  the three `RegionView3D` framing properties must be writable; `tag_redraw()`
  must exist on a real `Area`. Because headless `window_new` fails its poll
  **before** any of those lines run, an extra pin reads `open_window`'s own
  source and rejects any `window.<attr> =` assignment whose RNA property is not
  writable — matched generically, not against a fixed list, so a future
  assignment cannot slip past. Mutation-tested: re-adding
  `window.width = 1000` fails that pin immediately; the committed code passes.
  Also found while measuring this: the type names are `View3DShading` /
  `View3DOverlay`, not `SpaceShading` / `SpaceOverlay` — my first draft of these
  very checks crashed on the wrong name, which is why they now look types up by
  RNA id instead of hardcoding class names.
  `open_window` now also binds `window.view_layer` to the preview scene's own
  view layer, so the viewer's timeline and viewport belong to its scene.
  Smoke: 41 -> **50 checks**, all green; `ruff check .` clean; full suite green.

