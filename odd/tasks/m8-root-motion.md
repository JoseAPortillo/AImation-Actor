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

## Tasks

| ID | Spec | Route | Status | Commit |
| -- | ---- | ----- | ------ | ------ |
| T1 | S1, S2 | inline | done | HMR2 response now returns pelvis/root camera translation; adapter converts camera `(x,y,z)` to domain `(x,-z,y)`; `WorldPose.root_translation`; controller subtracts the first captured frame; `build_production_pose` carries relative X/Y/Z on `Main` and removes root Z from the local Pelvis offset. Tests cover mapping and controller origin. |
| T2 | S1, S3 | inline | done | CondMDI worker carries root translation through FK, decoded root positions, canonical-yaw restoration, and `_frame_to_wire`; `Main.trans` is no longer forced to zero. Wire regression covers decoded translation. |
| T3 | S3, S4 | inline | done | Missing HMR root translation falls back to zero-relative behavior; existing fake engines remain compatible through the default `WorldPose.root_translation`. |
| T4 | S1-S4 | inline | pending | — |

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
