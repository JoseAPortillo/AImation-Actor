# M8 Root Motion
Branch: feat/develop
Delivery: direct work-unit commits, no PR; test runner: `.venv/Scripts/python.exe -m pytest -q --basetemp="$env:TEMP/aim-tmp"`

## Specs

1. **S1 — Capture root displacement.** The application must capture root
   displacement in horizontal, depth, and vertical axes when the pose engine
   can estimate it.
   Acceptance: HMR2 responses provide a pelvis/root world translation; the
   first captured frame of a session is the origin `(0, 0, 0)`; later poses
   carry relative displacement on `Main` without changing original key
   ordering or key ownership. Checks: adapter protocol tests, mapping tests,
   controller extraction tests.
2. **S2 — Preserve body-local height.** Root displacement and local body pose
   height must not be double-counted.
   Acceptance: `Main` carries relative root motion; `Pelvis` carries only the
   residual local height relative to the session origin/bind convention.
   Checks: pure mapping tests and FK assertions.
3. **S3 — Fill and export continuity.** Generated rows and exported FBX must
   retain the captured root trajectory.
   Acceptance: inbetween requests carry `Main` translation, guide anchors and
   keys preserve it, and the binary FBX contains stepped `Main` translation
   channels. Checks: inbetween wire tests and FBX document tests.
4. **S4 — Honest fallback.** If the engine cannot estimate root translation,
   the application keeps the previous in-place behavior and reports no fake
   trajectory.
   Acceptance: missing/invalid translation is zero-relative and non-fatal.
   Checks: adapter fallback tests and full suite.
5. **S5 — Reduce root-jitter noise.** The captured root trajectory is too
   noisy for the animator ("tiene ruido el movimiento demasiado"). Interior
   filled/captured rows must have their `Main` translation jitter-reduced
   while original keyframes keep their exact captured values.
   Acceptance: a robust temporal filter on interior `Main` translations
   dampens frame-to-frame jitter, preserves linear motion exactly, never
   touches original key frames, and runs before foot contact detection so
   pinning sees the smoothed root. Checks: core smoothing tests and fill
   adoption tests.
6. **S6 — Planted feet stay pinned under root motion.** A foot kept in place
   ("deberían quedarse clavados en el sitio") must not be un-pinned just
   because the captured root trajectory moved between the bounding keys.
   Acceptance: contact detection measures the foot against the body's root
   displacement (root-invariant planting read), so captured root motion and
   its noise cannot hide a planted foot; the pin pass still holds the world
   target. Checks: contact detection tests with displaced roots and
   unchanged zero-root behavior.

## Tasks

| ID | Spec | Route | Status | Commit |
| -- | ---- | ----- | ------ | ------ |
| T1 | S1, S2 | inline | done | HMR2 response now returns pelvis/root camera translation; adapter converts camera `(x,y,z)` to domain `(x,-z,y)`; `WorldPose.root_translation`; controller subtracts the first captured frame; `build_production_pose` carries relative X/Y/Z on `Main` and removes root Z from the local Pelvis offset. Tests cover mapping and controller origin. |
| T2 | S1, S3 | inline | done | CondMDI worker carries root translation through FK, decoded root positions, canonical-yaw restoration, and `_frame_to_wire`; `Main.trans` is no longer forced to zero. Wire regression covers decoded translation. |
| T3 | S3, S4 | inline | done | Missing HMR root translation falls back to zero-relative behavior; existing fake engines remain compatible through the default `WorldPose.root_translation`. |
| T6 | S6 | inline | done | `_planting_read` in `core/foot_contacts.py`: contact detection subtracts the root's horizontal displacement so captured root motion cannot fake drift; probe re-run on the real clip: detection {(40,55): {'L_Foot'}}, pin corrected 14 rows, no clamps, hold within 0.5 cm, FBX regenerated with the planted foot held. |
| T5 | S5 | inline | done | `smooth_root_path`/`smooth_root_trajectory` in `core/services.py` (median-3 ×2 + quarter-half-quarter average, anchor-padded windows); wired into `_on_inbetweens_filled` before the pin pass; keys always kept by object identity. Real 48-frame probe: successive-root jitter mean 1.77→1.06 cm, max 8.05→3.46 cm. Shortcut fill adoption test plus ramp/zigzag/outlier core tests. |
| T4 | S1-S4 | inline | partial | Real 48-frame probe 40..87 completed and wrote `.engine/_e2e_jace_root_motion_40_87.fbx`. HMR2 produced finite relative root X ≈ −32 cm and Z ≈ −0.23 cm over the range, but depth was invalid on some rows and fell back to zero; no planted contact met the 4 cm threshold after root motion, so foot pinning was not claimed. Subject crop/detector or temporal root source remains required for full acceptance. |

## Log

- **L1.** User, verbatim: *"la app también tiene que capturar el desplazamiento del root, fallo mio y además batante importante."*
- **L2.** User clarification, verbatim: *"espera, tiene que capturar desplazamiento horizontal, altura y profundidad, en la medida de lo posible."*
- **L3.** User decision, verbatim: *"si"* — the first captured frame is the root-motion origin.
- **L4.** Implementation (2026-10-23): HMR2's `pred_cam_t` plus the SMPL
  pelvis joint now crosses the worker protocol as `root_translation`. The
  application converts it to domain axes, captures the first successful value
  as the session origin, and maps the relative trajectory to `Main`; the
  residual Pelvis Z reconstructs the measured hip height without double
  counting. CondMDI receives the root through `Main.trans` and restores it in
  decoded output. T4 remains pending: real GPU extraction and FBX readback over
  a moving clip must prove scale/axis quality and long-range continuity.
- **L5.** First real 48-frame probe (2026-10-23) exposed the honest limitation:
  HMR2's full-frame manual crop produced invalid depth on some rows and noisy
  horizontal displacement. The adapter now preserves finite axes independently
  and zero-falls back only invalid components; it never emits NaN. The 40..87
  probe completed safely but did not meet the existing 4 cm planted-contact
  threshold after root motion was applied, so it did not claim a pinned span.
  T4 stays pending until a subject crop/detector or temporal root-motion source
  makes the trajectory reliable enough for a moving-contact validation.
- **L6.** T4 partial result (2026-10-24): the 48-frame real probe completed
  safely after the finite-axis fallback. It measured relative root X ≈ −32 cm
  and Z ≈ −0.23 cm across 40..87; invalid depth remained zero rather than
  becoming NaN. The exported review artifact is
  `.engine/_e2e_jace_root_motion_40_87.fbx`. Because the resulting world foot
  readings no longer met the 4 cm planting threshold, the probe deliberately
  applied no foot pinning. This proves the safety/fallback path, not full root
  trajectory quality; T4 remains partial pending a reliable subject crop or
  temporal root estimator.
- **L7.** User feedback, verbatim: *"mejor pinta, tiene ruido el movimiento
  demasiado para mi gusto, pero como punto de partida esta bastante bien."*
  Accepted as the starting point, but noise reduction is now requested (S5).
- **L8.** T5 (2026-10-24): a pure, anchor-padded robust filter
  (`core/services.py`: two median-3 passes, then a quarter-half-quarter
  average) damps the interior rows' `Main` translation exactly where the fill
  is adopted, before foot-contact detection; original keys keep their exact
  captured value objects. Unit proofs: linear motion preserved exactly, one
  20 cm outlier deleted (>99.99%), period-2 alternation halved at the window
  edges and near-zeroed in the interior. Real 48-frame probe on the JACE clip:
  successive-root delta mean 1.77→1.06 cm, max 8.05→3.46 cm, regenerated
  `.engine/_e2e_jace_root_motion_40_87.fbx` smoothed. Full suite and Ruff
  green (HMR adapter tests run separately as usual).
- **L9.** User feedback, verbatim: *"hay ruido y desplazamientos en los pies
  que deberían quedarse clavados en el sitio."* Diagnosis: with M8 root
  motion applied, the HMR2 root noise inflated the world toe drift between
  the bounding keys (L ≈ 4.94 cm, R ≈ 8.68 cm, both above the 4 cm plant
  tolerance), so `contact_spans` found nothing planted and the pin pass
  never ran — the FBX shipped sliding feet. Fix (T6): the planting read must
  be invariant to the root's own displacement.
- **L10.** T6 evidence (2026-10-24): with root-relative detection the real
  48-frame probe again flags `(40, 55): {'L_Foot'}` (it was empty before the
  fix). The pin pass then corrected 14 rows with **no clamped feet**, and the
  hold check reads every pinned toe within 0.5 cm across 40..55. Root jitter
  stays at the T5 smoothed levels (mean 1.06 cm, max 3.46 cm per step);
  worst toe drift across the un-pinned R_Foot remains ~7.75 cm — its 8.68 cm
  body-relative drift exceeds the 4 cm plant tolerance, i.e. that foot is
  genuinely moving in the capture, not a detection artifact. The regenerated
  `.engine/_e2e_jace_root_motion_40_87.fbx` now carries the pinned planted
  foot.

