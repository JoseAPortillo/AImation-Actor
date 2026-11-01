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
   contains it; the capture plays on the viewer window's own timeline, and the
   tool's clock (`preview_frame`) mirrors it both ways so scrubbing there
   never touches the animator's playhead; the capture is imported through the
   legacy importer with `automatic_bone_orientation=True`, so the skeleton
   keeps the shape the animator exported instead of an inside-out bone basis.
   The viewer's own controls live inside the tool panel, directly below the
   capture list, and report whether the viewer window is open. A panel cannot
   host a `VIEW_3D` (a panel is drawn in a `UI` region; `VIEW_3D` is an *area*
   type, and areas own their regions), so the 3D view itself stays a separate
   window. A play/pause button, a second frame slider and a maximize toggle
   were all removed by user decision (L14): the viewer window's own timeline
   already plays and scrubs, and the floating window is already as large as
   the animator wants it.
   Checks: headless smoke proving the armature lands in the preview scene and
   not in the working scene, that a bone whose rest offset goes down from the
   hips ends with its tail below its head, and that the play, maximize and
   timer machinery is gone.

2. **S2 — Capture folder, import button, and listbox.** The tool lists the
   captures the animator exported and applies the selected one.
   User, verbatim: *"Dentro de la ventana de la herramienta de transposición
   podremos seleccionar el fbx a exportar, debajo del botón import capture,
   tendremos un listbox con varios fbx que hayamos podido capturar. Se aplica
   sobre el rig el que tengamos seleccionado en el listbox."*
   Acceptance: a remembered capture folder feeds a `UIList` of its `*.fbx`
   files, case-insensitively sorted; the `Import Capture` button opens a file
   picker and adds ONLY the picked file to the list, remembering its exact
   path without adopting its folder — the capture folder field is the
   whole-folder workflow; a hand-imported row survives folder refreshes and
   selecting or importing a row loads that capture; a Remove button drops the
   selected row from the list — the viewer keeps showing what is loaded, and a
   removed folder file comes back on refresh.
   Checks: pure listing/sorting tests; headless smoke of the list refresh and
   of hand-imported rows loading, surviving refresh, and failing by name when
   their file vanishes, and of removal keeping the selection and never
   scheduling a load.

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
   Interaction, chosen by the user (L16): **a searchable popup in the viewer
   window.** Clicking a capture bone opens a search field listing every control
   of the target rig (its pose bones plus every empty in the file); typing
   filters, Enter links. The alternative — clicking the control in the
   animator's own viewport — is impossible as specified: a modal operator only
   receives mouse events from the window it started in, and the skeleton and
   the rig live in different windows.
   Acceptance: `pose_position = 'REST'` while mapping (the Bind pose toggle is
   disabled for the session); per-bone custom colours (grey -> pending -> green)
   via `Bone.color.custom.normal` + `show_bone_colors`, on both the bone and the
   pose bone; an already-linked bone opens its popup with **Remove link**, which
   turns it grey again; a link is stored by source bone name and repaints on
   whichever capture armature is loaded; `Esc` / right-click ends the session and
   returns the viewer to the pose; the modal refuses, by name, to start anywhere
   but the viewer window.
   Checks: headless smoke of the activation refusals, forced REST, the colour
   transitions, the choices list (bones + an empty), link persistence across a
   capture reload, unlink, and the modal's window refusal; pure ray-picking
   tests for the click geometry.

7. **S7 — Rig-agnostic targets.** A link target may be a bone or a plain object,
   because poles are sometimes empties.
   Acceptance: the pick step (the searchable popup) resolves bones of the target
   armature and objects of type `EMPTY`; the stored reference records
   `kind` + object name + bone name; a link whose control vanished reads as
   missing in the panel instead of painting green.
   Checks: headless smoke of the choices list and of the missing-control count.

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
| T2 | S1, S9 | inline | done | `964f8ea` + `3973574` + `2a719b7` (PR #9) — Viewer controls moved into the tool panel, the viewer window's own timeline plays/scrubs the capture, `Import Capture` single-file, capture-list `Remove`. Also `dccef35` (viewer animates, panel reachable from it) and `da89a8b` (legacy importer + `automatic_bone_orientation`). The timer clock, play button, frame slider and maximize toggle were removed by user decision (L14). RED/GREEN: `clock.frame_at` tests (advance, truncate, wrap, non-zero range start, no rate, empty and single-frame ranges); smoke checks the frame range/rate binding, the working scene restored to 24 fps / 1-250 / frame 7 after an import, and that removing a row never schedules a load of the row the clamp lands on. The window itself is a manual check. |
| T3 | S4, S7 | inline | done | `a87a8a1` (PR #9) — Click-to-map surface: `picking.py` (pure ray↔segment picking, 10 RED->GREEN tests), `mapping.py` (session, grey/amber/green colours, link store, target-control choices, `map_bones`/`pick_target`/`finish_mapping`), the Mapping box + Target-rig field, the colour refresh on every capture load, and the S4/S7 acceptance rewrite. Route evidence: understood from L4 platform facts plus bounded reads; one independent piece of behavior, no Writer trigger reason. RED/GREEN: smoke 66 -> 91 checks, one mutation test per claimed hook (colour refresh on reload, pending amber, forced REST). |
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
- **L12.** User change request, verbatim: *"vamos a cambiar un par de cosas, la
  primera y mas sencilla es importar el fbx con fbx(legacy) y activar la opcion:
  automatic bone orientation."* Applied to `preview._import`. Two findings came
  out of checking it rather than just flipping a flag:
  1. **`bpy.ops.import_scene.fbx` already IS the legacy importer** in 5.2.3, and
     the new one is not usable: `bpy.ops.wmf.fbx_import` exists as a name but
     resolving its RNA raises `KeyError: get_rna_type("WMF_OT_fbx_import") not
     found`. So the request reduced to the flag, not to changing the call.
  2. **The flag changes the skeleton's shape, not just its twist** (measured on a
     synthetic capture whose Pelvis offset goes down from the hips): with the
     default the bone spans `head y=90 -> tail y=170`, i.e. pointing UP, and every
     bone's local Y is `(0,1,0)` whatever the bone does; with
     `automatic_bone_orientation=True` it spans `y=90 -> y=10` and downward bones
     get `y=(0,-1,0)`. That is the inside-out skeleton in the viewer.
  Deliberately NOT touched: the application's read bridge
  (`adapters/io/fbx/blender_import.py`) keeps the importer's defaults, because
  every documented FBX round trip (FR-IMP-01/02, FR-EXP-02) was validated against
  the armature-space basis that convention produces. The two paths now disagree
  on bone axes on purpose; **T5 (return bake) has to respect that split**, and the
  smoke pins the flag at the call site so the split cannot drift silently.
  Evidence: smoke 50 -> **52 checks** green; mutation-tested by setting the flag
  back to `False` - both new checks fail, the geometric one reporting
  `head=(0.0, 90.0, 0.0) tail=(0.0, 170.0, 0.0)`. `ruff check .` clean, full
  pytest suite green. S1 rewritten; spec.md v0.7.1; AGENTS.md records both
  findings.
- **L13.** User change request, verbatim: *"necesito que el visor este en las
  opciones de la herramienta aimation, no fuera de ella, debe de estar justo
  debajo del listado de fbx y que esta se escale al abrir mas la pestaña de la
  tool, tambien añade un boton para poder maximizarla, y aqui si, la veremos como
  la esta ahora, en un viewport aparte."*
  The literal reading is impossible, and it was measured rather than asserted: a
  panel is drawn inside a region of type `UI`, while `VIEW_3D` is an **area**
  type, and areas own their regions — so no panel can host a 3D viewport, at any
  sidebar width. `bpy.types.Panel` also has no `maximized` property. Three
  readings were put to the user with their real costs, and the chosen one is:
  **the viewer's controls move into the tool panel, the 3D view stays its own
  window.** That keeps S1's isolation promise intact.
  Implemented: a "3D viewer" box directly under the capture list that states
  `open` / `closed` (found by scanning `window_manager.windows` on every draw via
  `preview.viewer_window()`, never from a remembered reference, so closing the
  window cannot make the panel lie), `Open` / `Open viewer`, a maximize toggle,
  and the existing play/pause, Bind pose and frame slider folded into the same
  box. `open_window` now reuses `viewer_window()` instead of duplicating the scan.
  The maximize button calls `wm.window_fullscreen_toggle` under
  `temp_override(window=viewer)` — verified to exist as `WM_OT_window_fullscreen_toggle`.
  **Honest limits, both measured:** the panel's *widgets* stretch with the
  sidebar, but the 3D view does not scale with the AImation tab (it is a separate
  window — the accepted cost of this option), and `Window` exposes no readable
  fullscreen flag (`parent/scene/workspace/screen/view_layer/x/y/width/height`,
  geometry read-only), so the button is a **blind toggle**, labelled
  "Maximize / Restore" rather than showing a state.
  Evidence: smoke 52 -> **56 checks** green (`no viewer window is open headless`,
  `maximize refuses with a named reason when no viewer is open`,
  `Blender exposes no readable fullscreen state`, `the maximize operator is
  registered`). Headless can prove the refusal path only; the actual fullscreen
  flip is a manual check, like the window itself. S1 rewritten.
- **L14.** User change request, verbatim: *"el botón play no lo necesito, ya
  que puedo hacer play y ver la animación con time slider. la opción máximizar
  no sirve para nada, ya veo el la ventana flotante con el viewport 3d.
  al importar un solo fbx seleccionando import capture, no debe incluir toda
  la carpeta, ya tiene la opción justo arriba para agregar una carpeta entera.
  si el usuario solo quiere añadir un fbx de una carpeta debe poder hacerlo sin
  tener que tener varios fbx que no necesita o no ha querido cargar.
  el visor de frame en la pestaña aimation no es necesario tampoco, es
  información redundante y tiene poca utilidad para el usuario."*
  Four consequences, all applied:
  1. **Play button removed** from the panel. The viewer window's own timeline
     already plays the capture (its scene is the preview scene), so the
     `bpy.app.timers` playback machinery had no remaining caller and was
     deleted honestly: `playback.py` and `clock.py` are gone, together with
     `tests/test_blender_addon_clock.py` (12 pure tests). The clock mirror
     (`preview_frame` <-> the preview scene's `frame_current`) stays: it is
     what keeps scrubbing the viewer's timeline away from the animator's
     playhead. `preview_playing` was removed with the button.
  2. **Maximize toggle removed** (it had been added in L13); the floating
     window is already visible as-is.
  3. **The panel's frame slider removed** — redundant with the viewer window's
     own timeline. The viewer box now holds the open/closed status, `Open`,
     and the Bind pose toggle.
  4. **`Import Capture` is now a single-file path**: it adds ONLY the picked
     file to the list, remembering its exact path (`CaptureItem.path`) and
     never adopting its folder — the capture folder field stays the
     whole-folder workflow. Hand-imported rows survive folder refreshes (a
     folder refresh is the folder's truth: a hand row whose name a folder row
     covers is dropped); a hand row loads from its own path even with a broken
     folder configured, and fails by name when its file vanishes.
  Evidence: smoke 56 -> **60 checks** green; mutation-tested twice — restoring
  the folder adoption fails `Import Capture does not adopt the picked file's
  folder`, and making the refresh drop hand rows fails `a folder row replaces a
  hand-imported row for the same file`. `ruff check .` clean; full pytest suite
  green. S1 and S2 rewritten; spec.md v0.7.3; AGENTS.md pure-module list
  updated.
- **L15.** User change request, verbatim: *"ok, se me ha pasado añadir un botón
  o forma de eliminar de la lista el fbx que considere el usuario.
  y lo mas importante, no se ha implementado en ningún momento dentro la
  pestaña de la tool el esqueleto en a pose para seleccionar el bone que
  conecta con el control que el usuario decida conectar."*
  Two parts. The first is done now: a Remove button (`X` icon) beside the
  capture list drops the selected row. Removing never schedules a load (the
  whole change runs under the rebuild guard — proven by a mutation that fires
  the RNA update and fails `removing a row never schedules a load`), the
  viewer keeps whatever is loaded, the selection follows the removed row's
  neighbour, and a removed folder file is re-listed by Refresh (the folder is
  the folder's truth; only hand-imported rows are gone for good).
  The second part is T3 (S4 + S7, the mapping surface) — it was planned as PR 2
  and had not started; nothing was dropped. Before building it, one interaction
  decision was put to the user (recorded with its answer in L16): where the
  target-control pick happens, given that a modal operator only receives mouse
  events from the window it started in, and the capture skeleton and the
  animator's rig live in DIFFERENT windows.
  Evidence: smoke 60 -> **66 checks** green (mutation-tested on the guard);
  `ruff check .` clean; full pytest green (the known flaky
  `test_ai_hmr2_adapter` timeout fails on `main` too, not ours). S2 rewritten;
  spec.md v0.7.4.
- **L16.** Interaction decision for T3, put to the user verbatim in the
  conversation ("¿cómo elegís el control del rig que se le conecta?" with three
  options and their real costs), answered: **"Buscador en el visor"** —
  *"Clic en el bone de la captura (ventana del visor) → aparece un popup con
  buscador listando TODOS los controles de tu rig (bones + empties) → escribís
  'hand', Enter, listo."* Chosen over click+click+Link and over cross-window
  direct clicking, which depends on unverified modal routing (a modal only
  receives mouse events from the window it started in). T3 started, inline
  route, save point at the user's request:
  1. Pure `blender_addon/aimation_transpose/picking.py` — segment/segment
     closest-point ray-to-bone picking (Ericson RTCD ch. 5), `bpy`-free;
     RED observed, then GREEN: `tests/test_blender_addon_picking.py` 10/10.
     Two of the original test drafts were themselves wrong and were fixed as
     part of GREEN, not the code: two segments lying exactly ON the ray tie
     at distance zero (nearest must win by distance, not by order), and a
     segment parallel to the ray at `y=0.5, z=2` is 2.06 away, never 0.5.
     The code fix was real: a bone whose closest point lies behind the ray
     origin must return `inf`, and `ray_point_distance` must divide by
     `dot(d, d)`, not by its square root.
  2. Mapping RNA in `props.py`: `MappingItem` (`name` = capture bone, `kind`
     BONE|EMPTY, `object`, `target_bone`), `scene.mapping_items`,
     `mapping_active`, `mapping_pending`, `mapping_choice`, and `link_of`.
     Registered on every scene copy like the rest; the smoke passes with it
     (66 checks), `ruff check .` clean.
  Not yet written: `mapping.py` (session activate/finish, grey/pending/green
  colours, links, the `build_choices` collection for the search popup, the
  modal `aimation.map_bones`, `aimation.pick_target`, `aimation.finish_mapping`),
  the panel box and Target-rig field, the colour refresh on
  `preview.load_capture`, the smoke additions, and the S4/S7 acceptance
  rewrite with this picker flow. **Uncommitted working-tree state — the next
  session resumes here, not from scratch.**
- **L17.** T3 completed in the next session. Measured facts that shaped it:
  1. **`BoneColor.custom` is a read-only pointer**, not an assignable colour:
     `color.custom.normal = (r, g, b)` after `color.palette = "CUSTOM"`
     (`is_custom` is read-only and follows the palette; values round-trip
     through 8-bit theme storage, so 0.35 reads back as 0.3529). Both the
     `Bone` and the `PoseBone` side are painted.
  2. **The search popup pattern is Blender's own**: `bl_property` +
     `EnumProperty(items=<dynamic callback>)` + `window_manager.invoke_search_popup(self)`
     returning `RUNNING_MODAL` (read from the bundled
     `addons_core/ui_translate/update_addon.py`, not guessed). One builder
     (`_targets`) feeds both the popup list and the identifier→target table, so
     confirming a choice never parses the identifier back into parts.
  3. **A modal cannot be invoked headless**: `bpy.ops.aimation.map_bones("INVOKE_DEFAULT")`
     prints *"Invalid operator call"* and returns `{'PASS_THROUGH'}` without
     ever reaching `invoke` (no window manager in `--background`). The window
     condition is therefore a plain function, `_refusal(context)`, exercised
     directly by the smoke; the popup and the click gestures stay manual checks,
     like the window itself.
  Design as built: `mapping.py` holds the session (`activate` refusing by name
  without a capture or a rig, forcing `preview_rest` and `show_bone_colors`,
  `finish` returning the viewer to POSE), the colour refresh (grey / amber
  pending / green linked, repainted from links keyed by source bone name), the
  link store (`MappingItem`: kind BONE|EMPTY, object name, target bone), the
  choice builder (target rig pose bones + every EMPTY), and the three operators
  (`aimation.map_bones` modal: click → pending → `aimation.pick_target`
  `INVOKE_DEFAULT`; Esc/right-click or the panel's Finish ends it;
  `aimation.finish_mapping`). The panel gained a Mapping box (target rig field,
  linked count, missing-control count, pending status) and disables the Bind
  pose toggle for the duration of a session; `preview._bind_clock` refreshes
  the colours after every capture load, so a link survives a reload and repaints
  on whichever armature is showing.
  Evidence: smoke 66 -> **90 checks** green, `ruff check .` clean, full pytest
  suite green (including the flaky `test_ai_hmr2_adapter` this run).
  Mutation-tested three ways in one run — removing the `_bind_clock` colour
  refresh, painting pending bones grey, and not forcing REST each failed its
  exact check (`a link repaints green on the reloaded skeleton`, `the bone
  awaiting its control turns amber`, `mapping forces the bind pose`).

