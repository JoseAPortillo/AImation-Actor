# Pose video overlay

Draw the captured skeleton overlaid on the video pane, side-colored, with
stepped (held) frames between keys, while the old 3D viewport stays hidden.

Branch: `feat/pose-overlay` (from main). Delivery: single PR to main when the
feature closes (the convention the user set with PRs #1/#2). Test runner:
`.\.venv\Scripts\python.exe -m pytest -q --basetemp="$env:TEMP\aim-tmp"` — full
suite two-step with `tests/test_ai_hmr2_adapter.py` apart; ruff clean.

## Specs

- **S1**: "El esqueleto debe verse sobre la imagen, ajustandose a la persona
  capturada." — the skeleton renders on top of the video pane, projected onto
  the image the pose was captured from, aligned with the captured person at
  that frame. Alignment source: the HMR2 worker's full-frame perspective
  projection (pinhole, per-frame focal), reconstructed from the same engine
  data the adapter already consumes — no invented camera. Without engine
  camera data the overlay reports its unavailability instead of drawing a
  wrong guess. Between captures the skeleton is the last capture's projection
  (see S4's step semantics; a camera/subject move between keys leaves the
  frozen figure behind until the next capture — that IS the requested step
  behavior, documented as an accepted tradeoff).
- **S2**: "las extremidades izquierdas del esqueleto deben verse en color
  rojo, las derechas en azul y el tronco y cabeza amarillo." — bone color by
  the CHILD joint's name: `L_` red, `R_` blue, every other joint (Main,
  Pelvis, Spine_1..3, Neck, Head, and the `L_/R_Collar` bones) follows the
  prefix rule and those without a side prefix fall to the trunk/head yellow.
  The `Main` ground bone is not drawn (it is not on the person).
- **S3**: "la base de los bones deben verse con un dot con el borde gris
  oscuro y el centro gris claro." — at every drawn joint position a dot with
  a dark-gray outline and a light-gray fill.
- **S4**: "si capturo una pose debe verse el esqueleto pero los frames
  siguientes desde esa pose hasta la siguiente se mantienen en la pose justo
  anterior, solo cambia cuando capture la siguiente o lleguemos a la siguiente
  capturada, como si estuviese en step las curvas de animación." — the overlay
  shows the projection of the last captured frame at or before the playhead;
  it snaps to a new projection only on a capture (or re-capture of that key).
  Before the first capture the overlay draws nothing.
- **S5**: "la vista que tenemos ahora mismo, la ocultamos hasta que esta
  funcione correctamente." — the existing `SkeletonViewport` pane is hidden
  while this overlay is being built and verified; its code stays untouched
  for later re-enable.

## Tasks

- T1 (S1, S2, S3, core) — **DONE**, commit `1d5dca1`: the overlay's color rule
  (`L_` red / `R_` blue / trunk-head yellow, dots pinned), later reworked in
  T2 to consume the engine's own pixels.
- T2 (S1, S4, data path) — **DONE**: `WorldPose.projected`
  (`Mapping[str, tuple[float, float]] | None`) carries the engine's own
  projection; `core/overlay.py` reworked to lay out that pixel mapping
  (`overlay_items` → colored segments + dots); the HMR2 worker projects its
  SMPL joints with the vendored `perspective_projection` + `cam_crop_to_full`
  translation + scaled focal + frame centre and reports `projected_joints`;
  the adapter normalizes the JSON lists to float tuples (missing → `None`);
  the controller stores a per-key `(segments, dots)` snapshot at capture
  (guides never snapshot), clears it on clip reload, and serves
  `overlay_snapshot_at` (latest key ≤ playhead, `None` before the first —
  S4's stepping) plus `overlay_availability()`. RED/GREEN:
  `tests/test_core_overlay.py` 5/5, 4 controller tests in
  `tests/test_ai_extraction_pipeline.py`, 2 adapter tests in
  `tests/test_ai_hmr2_adapter.py` (fake worker mode `projected`). Full
  two-step suite + ruff green.
- T3 (S1, S2, S3, S4, widget) — **DONE**, commit `6b5c5ba`: `PoseOverlay`
  (`adapters/gui/pose_overlay.py`) — a mouse-transparent widget over the video
  surface that maps the engine's full-frame pixels with the surface's own
  letterbox rule (`display_transform`, tested pure), paints the pinned side
  colors and dots, and draws nothing it cannot map honestly (no snapshot, or
  unknown native frame size). The surface owns it (child, resized with it,
  fed the frame's native size on every delivered frame); `VideoPlayer.overlay`
  exposes it; `MainWindow` replays `controller.overlay_snapshot_at` per
  `frame_changed` and clears on `media_changed` (headless source panes skip
  it). RED/GREEN: `tests/test_gui_pose_overlay.py` 9/9 (real rendering into
  QImage, pixel-sampled), wiring tests in `tests/test_main.py` 2.
- T4 (S5) — **DONE**, commit `c41b4dd`: `SkeletonViewport` composed in the
  splitter but `setVisible(False)`; qtbot test pins it and pins that the
  code stays composed for re-enable.
- Docs: update this doc per task; update `spec.md` (GUI section + OQ5 nota)
  at closure; AGENTS.md summary if interfaces change.

## Verification

- RED observed for every behavior rule before its implementation.
- Full two-step suite + ruff after each unit.
- Real-app visual verification by animator at closure (S1 alignment, S2/S3
  look, S4 stepping) — the projector is validated against the HMR2 demo
  weight first, but the eye has the verdict.
- Optionally grepped: `.engine/hmr2` demo projection convention (read-only,
  never patched) to pin the pinhole formula exactly.

## Log

- L1 (2026-10-28): "me gustaría hacer un cambio en la forma en que vemos en
  esqueleto en la app: El esqueleto debe verse sobre la imagen, ajustandose a
  la persona capturada. las extremidades izquierdas del esqueleto deben verse
  en color rojo, las derechas en azul y el tronco y cabeza amarillo. la base
  de los bones deben verse con un dot con el borde gris oscuro y el centro
  gris claro. si capturo una pose debe verse el esqueleto pero los frames
  siguientes desde esa pose hasta la siguiente se mantienen en la pose justo
  anterior, solo cambia cuando capture la siguiente o lleguemos a la siguiente
  capturada, como si estuviese en step las curvas de animación. la vista que
  tenemos ahora mismo, la ocultamos hasta que esta funcione correctamente.
  recuerda trabajar esto en una nueva feature."
- L2 (2026-10-28, T2 design change): T1's client-side `ProjectionCamera` /
  `position_to_pixels` is **superseded and deleted**. Reconstructing the
  projection in the app from the controller's production pose would misplace
  the figure vertically: `build_production_pose` decouples pelvis height from
  root depth (M8 S8 calibration) and couples it to the anchor, so the domain
  pose is no longer the geometry the camera saw. The projection now happens
  WHERE the truth lives — inside the HMR2 worker, reusing the vendored
  `perspective_projection` (import, never patch) with `pred_cam_t_full`
  (from `cam_crop_to_full`, already computed), the scaled focal, and the
  frame centre — verified against `.engine/hmr2/demo.py`'s full-frame
  overlay path (`renderer.py::cam_crop_to_full` + `geometry.py:64`). Raw
  `smpl_output.joints` keep the network's baked camera flip; projecting with
  the full-frame K needs NO extra flip and NO x-negation (those belong to
  the demo's pyrender mesh path). `WorldPose.camera` → `WorldPose.projected`
  (name → full-frame `(x, y)` pixels). S4's stepping comes free from
  per-key frozen snapshots. Test-harness gotchas recorded: after
  `waitUntil(has_key)`, the runner's `busy` release may still be queued, so a
  second capture in one test must wait `not controller.extraction_busy`; and
  `_load`'s default 1000 ms clip clamps to 24 frames (use a longer
  `duration_ms` for captures past frame 24).
- L3 (2026-10-28, T3/T4): widget and hide-out done (`6b5c5ba`, `c41b4dd`).
  `PoseOverlay` consumes `(segments, dots)` directly — the controller already
  froze `overlay_items` per key, so the widget owns only the letterbox
  mapping and painting. The overlay is owned by `_VideoSurface` (fed the
  native frame size on every delivered frame, resized with the surface), so
  its pixels land on the video's pixels by construction. Test-harness
  notes: QWidget tests need `qtbot` for the QApplication; the letterbox
  paint is verified by rendering into a transparent QImage and sampling
  pixels (midpoint of a bone must be pure RED — no palette guessing).
- PENDING (user): the eye test on real clips — S1 alignment with the
  captured person, S2/S3 look, S4 stepping during playback. Then `spec.md`
  (GUI section + OQ5) and the single PR to main.
- L4 (2026-10-28, user-authorized refinement): the real HMR2 projection was
  mathematically correct but the single-image pose estimate was anatomically
  unreliable across three captures. Added an optional engine-side COCO
  Keypoint R-CNN refinement: confident limb observations replace HMR2's
  `L_/R_Hip`, `Knee`, `Ankle`, `Shoulder`, `Elbow`, and `Wrist` pixels;
  `Pelvis` is recomputed from confident hips; spine/head/feet remain HMR2.
  Missing weights, CUDA, or low confidence preserve the HMR2 result. The
  application still has no cv2/torch dependency. The real engine probe
  downloaded the model into the engine cache and returned
  `keypoint_refinement: True`.
- L5 (2026-10-28, follow-up capture verification): the snapshot now refreshes
  immediately on `timeline_changed`, so capturing the current frame no longer
  requires slider motion. Confident shoulders and hips also rebuild the 2D
  torso chain (`Pelvis`, `Spine_1..3`, `Neck`, `L_/R_Collar`) so HMR2's
  unreliable 3D torso cannot pull otherwise-correct COCO limb points into
  crossed connections. Full two-step tests, ruff, and the real engine probe
  pass; the probe reports `keypoint_refinement: True`.
