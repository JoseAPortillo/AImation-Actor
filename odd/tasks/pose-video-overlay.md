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

- T1 (S1, S2, S3, core) — **DONE**, commit `T1`: `core/overlay.py` — joint/bone
  color rule and world→pixel projection (domain Z-up cm → engine Y-down m →
  pinhole); the camera record (`focal_px`, frame size) as an optional, additive
  field on the domain `WorldPose`. RED/GREEN in `tests/test_core_overlay.py`.
- T2 (S1, data path): the worker returns the full-frame focal it already
  computes (`scaled_focal_length`); the adapter stamps `camera` on the pose;
  the controller keeps a per-key pixel snapshot at capture time, clears it on
  clip reload, and refuses nothing if the camera data is absent (S1's typed
  unavailability). Tests in the adapter suite and the controller suite.
- T3 (S1, S2, S3, S4, widget): a transparent `PoseOverlay` widget over the
  video pane, wired to the controller: snapshot at-or-before the playhead,
  colored segments, joint dots. Tests with the existing `_Fake*` harness.
- T4 (S5): hide the old viewport pane in `MainWindow` (qtbot test); code
  unchanged for later re-enable.
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
