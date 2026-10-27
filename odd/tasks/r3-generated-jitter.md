# R3 — high-frequency jitter damping on generated rows

Objective: kill the frame-to-frame tremor the user sees in the engine's
generated rows ("tengo que matizar antes de que haga nada. el ruido ocurre
cuando genero inbetween con las golden pose no ocurre." → confirmed as
option 1: temblor). Golden Poses are fine; the fill's free rows vibrate.
Add the rotational analog of M8's root smoothing at adoption: a binomial
low-pass over each joint's quaternion series that rewrites ONLY free
(non-anchor) rows. Anchors stay byte-exact, translations stay untouched.

Branch: `feat/develop` · Delivery: work-unit commits, no PR slices
(user standing), push on request · Test runner:
`.venv\Scripts\python.exe -m pytest -q --basetemp="$env:TEMP\aim-tmp"`
(two steps: suite ignores `tests/test_ai_hmr2_adapter.py`, then that file
alone) + `.venv\Scripts\ruff.exe check .`. GPU validation is an
`.engine/_*` probe, never a committed test.

## Specs

- **S1.** The defect (user, verbatim 2026-10-27): *"el ruido ocurre cuando
  genero inbetween con las golden pose no ocurre"*, sharpened to option
  1 — *"Temblor — articulaciones que vibran frame a frame (la misma pose
  pero sacudiéndose)"*. Capture is innocent; the fill's free rows carry
  high-frequency vibration.
- **S2.** Keys and guides (anchors) are never rewritten: every anchor
  frame's pose objects survive byte-identical — the FR-GEN-01 guarantee
  R2 and M8 already keep.
- **S3.** Only free rows change. Each free row's joint rotation blends
  toward a binomial kernel (`[1 4 6 4 1]/16`-shape for radius 2) of its
  ±`radius` neighbour frames' rotations — anchors and free rows alike
  serve as filter context — with quaternions sign-aligned to the center
  before averaging (q and −q are the same rotation; a naive mean
  cancels). The blend is `slerp(original, kernel_mean, strength)`. The
  kernel's weights renormalise over the neighbours actually present (an
  edge row still dampens); a row with fewer than three samples — itself
  plus two neighbours holding that joint — has no trend and is left
  untouched. Already-smooth motion barely moves: the symmetric binomial
  mean of a constant-velocity arc is the center exactly.
- **S4.** `Main`'s rotation is never filtered (identity by domain
  invariant) and no translation ever changes (root smoothing owns
  translations, pinning owns feet).
- **S5.** Adoption order: root smoothing → seam feathering (R2) → jitter
  damping → foot pinning (pinning keeps the final word on contact rows).
  The status note reports the damped-frame count, NFR-03 style.
- **S6.** Radius/strength are MEASURED defaults (probe on JACE_REF_04
  keys 40/87, guides {58,76}, skip 500 — same span as R2): one real fill
  feeds a radius {1,2,3} × strength {0.5,0.75,1.0} grid. Report per
  combo: mean per-row jitter (angle of a free row off the slerp-midpoint
  of its neighbours, all non-root joints) before/after, the max angular
  motion the filter introduces anywhere (ease cost), and anchor
  byte-exact survival. Produce raw vs adopted-FBX pair for animator
  inspection. Constants adopted from that evidence.
- **S7.** Docs: spec.md "afinar" agenda updated in the same change set —
  the residual-jitter entry moves to the landed mechanism with measured
  effect.

## Tasks

| ID | S#        | Route  | Status  | Commit   |
| -- | --------- | ------ | ------- | -------- |
| T1 | S2,S3,S4  | inline | done    | `5d4498e` |
| T2 | S5        | inline | done    | `5d4498e` |
| T3 | S6        | inline | done    | this |
| T4 | S7        | inline | done    | this |

## Log

- **L1.** User, verbatim (2026-10-27): *"seguimos con la agenda"* then
  the matiz *"el ruido ocurre cuando genero inbetween con las golden
  pose no ocurre"* and the answer *"1"* (temblor frame a frame) —
  authorizing R3 as the jitter item, re-framed from the agenda's old
  "residual capture noise" label: the noise is in GENERATED rows, not in
  the capture.
- **L2.** Exploration (2026-10-27): M8's `smooth_root_trajectory` /
  `_smooth_series` (services.py:167-274) is the pattern — anchor-bounded
  runs, median-3 + quarter-half-quarter, linear motion preserved, keys
  byte-exact. The rotation analog cannot reuse per-axis medians (SO(3)
  has no componentwise median that respects equivalence of ±q); the
  binomial kernel + sign-aligned nlerp-mean + slerp blend does. R2's
  `feather_anchor_seams` (core/seam.py) already pins the row-rewrite and
  identity conventions this mirrors.
- **L3.** Sizing (2026-10-27): large (pure mechanism + wiring + measured
  constants via GPU probe + docs). Route: parent inline (no writer
  trigger — same adoption files R2 just touched, one behavior). Probe in
  background.
- **L4.** Design pivot while writing T1: the first draft pinned "window
  not fully present -> untouched", but that exempts exactly the rows
  beside the sequence edge, which in a real fill sit beside an anchor and
  DO tremor. Adopted instead: binomial weights renormalised over present
  neighbours, minimum 3 samples (centre + 2). Cost measured in tests:
  constant-velocity rows with a full symmetric window move 0.0 deg; the
  two one-sided edge rows drift under one frame's step. S3 rewritten to
  match before any commit.
- **L5.** T1+T2 landed (`5d4498e`): `core/jitter.py`
  `damp_generated_jitter` (pure; sign-aligned kernel mean via nlerp,
  `slerp(original, mean, strength)` blend, epsilon 0.01 deg keeps
  unchanged rows byte-identical by Keyframe object, Main skipped,
  translations never touched) wired into adoption after feathering and
  before pinning, status note `Damped N jitter frame(s).`. RED observed:
  module-absent collection failure for the 9 core tests, then the 2
  wiring tests failing on the undamped adoption; GREEN full suite in two
  steps, ruff clean. Provisional constants `JITTER_KERNEL_RADIUS=2`,
  `JITTER_DAMP_STRENGTH=0.75` await the T3 grid.
- **L6.** T3 probe running (`.engine/_e2e_jitter_damp.py`): ONE real fill
  (keys 40/87, guides {58,76}, skip 500) -> feathered first at the landed
  R2 defaults (production order), then the pure-CPU grid radius {1,2,3} x
  strength {0.5,0.75,1.0}. Metric: mean tremor angle of every free row
  off the slerp-midpoint of its neighbours over all non-root joints; plus
  worst single-joint motion introduced, rewritten count, anchor survival.
  FBX pair `_e2e_jace_jitter_raw.fbx` vs `_e2e_jace_jitter_damped.fbx`.
- **L7.** T3 measured (2026-10-27, `.engine/_e2e_jitter_damp.py`): one real
  fill (109.8 s), feathered first at R2 defaults (24 rows, anchors exact),
  baseline tremor mean 2.55 deg over 968 free-row joint samples. Grid
  radius {1,2,3} x strength {0.5,0.75,1.0}: every combo rewrote the same
  44 rows and kept anchors byte-exact. Tremor: r1s50 -21.2% (worst motion
  5.3), r2s75 -33.3% (9.0), r2s1.0 -40.6% (12.0), r3s1.0 -39.5% (13.6);
  r3 mirrors r2 within 0.02 deg at higher cost. ADOPTED: radius 2,
  strength 0.75 (the provisional defaults, confirmed on evidence -
  constants' comments now carry the numbers). FBX pair for the animator:
  _e2e_jace_jitter_raw.fbx (feathered) vs _e2e_jace_jitter_damped.fbx.
- **L8.** T4: spec.md afinar agenda rewritten - generated-row tremor lands
  as item (2) with the user's verbatim matiz (Golden Poses clean, vibration
  in the engine's free rows), the mechanism, the grid numbers and the
  honest residual: boundary pop and free-row CONTENT (item 3) stay
  model-limited; damping trades a third of the tremor for <=9 deg of
  single-joint ease.
