# M7 — IK Foot Pinning (FR-IK-01)

- **Objective**: detect planted feet from the ORIGINAL human keys and pin
  contacts (no sliding / no ground penetration) in the filled timeline with an
  analytic two-bone IK pass, before the final generative export (M8 consumes
  the already-pinned timeline).
- **Branch**: `feat/develop` · **Delivery strategy**: `exception-ok` (user
  2026-10-22: no PR slicing; work-unit commits straight to the branch, pushed
  on request).
- **Test runner**: `pytest` with `--basetemp="$env:TEMP\aim-tmp"`, junitxml
  schema verification; `ruff check .`.

## Specs

Requirements verbatim from `spec.md` §2 (FR-IK-01, :69) and the plan
(`docs/Plan_AImation_Actor_EN.md` §5.B, :198-203) — all Must:

- **S1. (FR-IK-01)** *"Detect planted feet in the original keys; IK pins
  contacts (no sliding/penetration) before final export."* Acceptance: *"Foot
  position stays constant across a contact span within tolerance."*
- **S2. (plan §5.B, cleaned motion contract)** *"Regardless of the AI model
  selected by the user, the system will run a final automatic cleanup step to
  resolve contact imperfections (foot sliding or ground penetration)"* and
  *"an analytical/numerical IK solver will correct the AI-generated spans frame
  by frame to mathematically pin the feet to the ground during calculated
  contacts, eliminating foot sliding entirely before writing the final `.fbx`
  file."*
- **S3. (design shape, decided at planning 2026-10-23; refined the same day
  during T1/T2 geometry review — Log L5, exact-solve truth in L6)** The pass
  is pure domain math in `core/` and consumes the FK `core/kinematics.py`
  already exposes (`joint_world_positions`, now standing on the public
  `joint_transforms`). Detection reads the FOOT world positions (L/R_Foot toe balls) at the two bounding ORIGINAL keys
  of each span; a foot is "planted" across a span when both readings sit at
  ground contact and their positions agree within the key-side tolerance (S4).
  Pinning then corrects every non-original frame of that span — generated
  engine rows AND capture-anchored rows (T9 fills included, uniform rule per
  S1/S2 wording). **The pinned point is the FOOT (toe ball) — the same joint
  detection reads —** landed at the first key's world contact position; a key
  whose reading penetrates the ground (toe z below it) has its target lifted
  to the ground plane, which is the pass's penetration correction. The leg
  solve is analytic two-bone IK (hip + knee rotations, law-of-cosines angles,
  knee pole taken from the frame's own knee direction so a bent leg bends the
  way it already bends); the ankle's own local rotation is ALWAYS preserved,
  so foot roll stays exactly as captured in every case. When BOTH feet are
  planted in the same span, the
  pelvis is lowered only as far as both leg chains require to reach their
  pinned positions (never moved for a single planted foot), and never past the
  point where an ankle would sink under its ground pin. An unreachable target
  (the frame's own pelvis pose puts the contact beyond the leg's reach) is
  clamped along the target direction to full leg reach and named in the
  pass's report instead of failing the fill. The original key poses stay
  byte-untouched (the S1 pattern of M6): the ≤ 4.0 cm detection tolerance is
  the amount of drift the animator accepts at the far key by construction.
  Ground z = 0 (the `Pelvis` height convention: height is ground-to-hip). The
  pass runs at FILL ADOPTION time (controller-side), so the animator scrubs an
  already-pinned timeline in the viewport; the final export (M8) simply writes
  it. The pre-fill original keys are known exactly there (after adoption the
  dense keyframes are indistinguishable from generated ones,
  `core/resampling.py` L230).
- **S4. (thresholds — open question 8 of `spec.md` §4, RESOLVED with the user
  2026-10-23: the balanced option)** Planting tolerance between the two
  bounding keys: **4.0 cm**
  on the foot's world position; ground-contact height: **6.0 cm** above the
  ground plane; post-pin hold: **0.5 cm max** across the pinned span
  (prior heal, exact pin). Assumption basis: the measured HMR2 per-frame
  noise on identical guides is mean 3.1–6.3 cm (M6 T8 evidence); OQ8's
  "numeric threshold defining no foot sliding" is these two detection values.
  Values live as named module constants, adjustable without touching logic.
- **Authorization & scope**: M6's S3/S6 machinery is the surface this pass
  corrects; no engine, wire, or vendored-code change (`Never patch vendored
  CondMDI code` stands). **Out of scope**: FR-GEN-04 (final FBX export, M8),
  foot-roll animation editing (depth of the toe pass), per-foot manual
  override UI, and detection beyond the original keys' bounding span.

## Tasks

| ID | Spec | Route | Status | Evidence |
| -- | ---- | ----- | ------ | -------- |
| T1 | S1, S3, S4 | inline | done | commit `35329a8`: `core/foot_contacts.py` `contact_spans(...)` + 11 tests (`tests/test_core_foot_contacts.py`); RED observed (ModuleNotFoundError), GREEN 11/11 first implementation, ruff clean |
| T2 | S1, S2, S3, S4 | inline | done | commit `aa895a2`: `core/foot_ik.py` `pin_foot_contacts(...)` + `PinReport`; 11 tests RED first; exact toe solve GREEN, full suite green, ruff clean. `core/kinematics.py` grew public `compose`/`inverse`/`quaternion_between_directions`/`rotate_about_axis`/`joint_transforms` (additive, no behavior change) |
| T3 | S1, S3 | inline | done | commit `a37c480`: `_pin_filled(...)` — pre-fill key frames stashed at `fill_inbetweens()` (`_fill_original_keys`), detection + `pin_foot_contacts` run at adoption (`_on_inbetweens_filled`) before the state lands; typed degradation without leg chains (fill adopted unpinned, note stays non-fatal); status line names pinned frames/spans/feet (and reach-clamped feet); stash cleared on failed/abandoned/stale paths. 3 controller tests RED first (`tests/test_gui_foot_pinning.py`), GREEN; M6 inbetween tests untouched; full suite green, ruff clean |
| T4 | S1, S2 | inline | done | probe `.engine/_e2e_foot_pinning.py` (real checkpoint, RTX 3080, JACE_REF_04.mov 30 fps): **A** keys 46/71 read NO contact (key-A toes L z 3.00 / R z 7.34, key drift 25.06/23.12 cm > 4 cm) -> detection empty, pass leaves the fill untouched - the negative control honest; **B** a real planted span IS found in the captured window 40..80: frames 40..55 with L_Foot planted; dense capture fill (14 anchors, no engine); BEFORE pin worst L toe drift 5.30 cm -> PinReport(1 span, 14 frames corrected, 0 clamp) -> AFTER pin 0.00 cm (exact), hold within POST_PIN_HOLD_CM asserted; keys byte-intact asserted; FBX `_e2e_jace_foot_pinned_40_55.fbx` for review |

## Log

- **L1.** User, verbatim (2026-10-23): *"sincroniza primero el spec y luego
  arranca con M7"*. Spec sync landed first (commit `6d29421`: FR-GEN-01/03 ✅,
  FR-GEN-02 🟡 honest split, NFR-02 ✅, changelog v0.5.0, §6 Next → M7 → M8,
  follow-ups rewritten). M7 planning started the same day.
- **L2.** Terrain (2026-10-23, codegraph): FK already in `core/kinematics.py`
  (`joint_world_positions`, used by the 3D viewport; docstring anticipates the
  IK pass). Foot bones: `L_Foot`/`R_Foot` hang from `L_Ankle`/`R_Ankle`
  (`production_skeleton.py`). Post-fill, generated gap frames enter
  `TimelineState.keyframes` indistinguishable from human keys
  (`core/resampling.py` L220-232), so pinning must run where the pre-fill
  original keys are still known — the controller's fill-adoption path. Plan
  §5.B's contract: analytic IK, frame by frame on the AI-generated spans,
  before writing the final `.fbx`.
- **L3.** Design decision (2026-10-23): pin at fill ADOPTION, not hidden at
  export time — the animator sees (and can scrub) the pinned result while
  working; M8's export writes the already-pinned timeline. The plan's
  "before writing the final .fbx" ordering still holds because M8 comes later
  on the same branch. Ankle-only target (MVP): the toe keeps its
  captured/created rotation; foot-roll correction is not attempted.
- **L4.** Open question 8 resolved (2026-10-23): the animator chose the
  balanced thresholds with the question tool — 4.0 cm between the bounding
  keys, ≤ 6.0 cm above ground, 0.5 cm post-pin hold ("Balanceado 4 cm / 6 cm",
  the recommended option). spec.md §4 OQ8 rewritten in the same change set
  (SDD rule). T1 starts right after with its RED first. T1 landed: RED observed
  (ModuleNotFoundError, 11 tests), GREEN 11/11 on the first implementation,
  ruff clean; suite-neighbours green (kinematics + resampling).
- **L5.** S3 refinement (T2 design, 2026-10-23): the PINNED point is the FOOT
  (toe ball), not the ankle as first drafted. Reason, in one line: pinning the
  ankle gives the pass only two rotational DOF against a three-DOF contact
  target, so penetration ("resolve it", FR-IK-01) would be unfixable, and
  the acceptance's "foot position stays constant" is exactly what the
  toe measures. Locked in: the ankle's local roll stays byte-identical;
  hip + knee rotate via the analytic two-bone solution; unreachable targets
  clamp along the target direction to full reach and are NAMED in the pass
  report, never failures.
- **L6.** T2 geometry truth (2026-10-23, RED-to-GREEN debugging): the first
  implementation ran a fixed-point loop (solve ankle two-bone, move the
  provisional ankle by the toe residual, repeat) and it DIVERGED on the
  standing case — a planted leg sits at the two-bone singularity (the ankle
  target at full thigh+shank reach, knee straight), where each provisional
  step amplifies (~2.5x) instead of contracting, and a pole recomputed from
  the moving knee spins the thigh direction pass to pass. The exact repair:
  with the ankle's roll FROZEN, the toe hangs off the KNEE's frame through
  one effective rigid vector — shin offset + q3-rotated toe offset — so the
  leg is a textbook two-bone chain whose END IS THE TOE. One closed-form
  solve per frame per foot: no iteration, no singularity (the standing case
  solves at d=101.1 against a 101.85 reach - strictly inside), roll always
  preserved, penetration handled purely by the lifted target. The earlier
  "penetration reorients the ankle" note in L5 is superseded: the exact
  solve needs no reorientation. Evidence: `tests/test_core_foot_ik.py`, 11
  tests; full suite green (pytest, 0 failures), ruff clean. T2 recorded in
  commit `aa895a2`, T1 in `35329a8`. Next: T3 (controller wiring at fill
  adoption) then T4 (GPU validation).
- **L7.** T3 wiring decision (2026-10-23): the wire point is adoption —
  `fill_inbetweens()` stashes the pre-fill key frame list (`_fill_original_keys`:
  post-fill the generated rows are keyed indistinguishably, so the list cannot
  be recovered later), and `_on_inbetweens_filled` runs `_pin_filled(...)` on
  the engine's result BEFORE adopting it. Pinning never blocks a fill: a
  skeleton without the four foot/ankle joints (pre-checked names) or with an
  incomplete leg chain (`ValueError` from `_chain`) degrades TYPED — the fill
  is adopted unpinned and the status note says why; a failed/abandoned/stale
  fill clears the stash. The adoption status keeps the M6 sentence and appends
  the pin note (`Pinned N contact frame(s) across M span(s) (feet))`, reach
  clamps named). Flaky note: `test_ai_hmr2_adapter.py::test_a_timed_out_worker…`
  failed twice mid-day under full-suite load and passed on base, alone, and in
  the final full run — environmental timing, not coupled to this change. T3
  committed; next T4 (GPU validation on the real clip).
- **L8.** T4 closed (2026-10-23, probe `.engine/_e2e_foot_pinning.py`, real
  checkpoint, RTX 3080, JACE_REF_04.mov): the planning assumption "keys 46/71
  standing contact" is FALSE on the real clip — measured first-hand: key-A
  toes L (0.99,-2.08,3.00), R (-25.46,-7.80,7.34), key drift 25.06/23.12 cm,
  so detection correctly reads NO contact (A: the negative control, pin leaves
  the dense fill untouched). A real planted contact WAS found in the captured
  window (40..80): span 40..55, L_Foot planted the way the thresholds define
  it; the dense-capture fill (14 anchor rows, no engine request) wobbled the
  toe UP TO 5.30 cm BEFORE pin, and pin_foot_contacts corrected 14 frames with
  zero clamping to 0.00 cm worst drift (the exact solve), held within the 0.5
  cm budget end to end, keys byte-intact (asserted in the probe). The swing
  foot (R) is untouched, as S2 mandates. FBX review artifact:
  `.engine/_e2e_jace_foot_pinned_40_55.fbx`. Honest honest limiter: this clip
  never settles longer than ~15 frames, so the validated span is short; a
  longer held pose pins just the same (the mechanism is per interior row, not
  span-length-dependent — the unit rig proves 24-row spans).
- **L9.** Follow-up animator test (2026-10-23) found constant foot trembling.
  The analytic solve was not unstable: a real-capture diagnostic measured
  natural toe steps of 1.997 cm mean / 6.137 cm max and, with keys every 3-5
  frames, the old left-key target policy jumped 1.228-3.246 cm at each planted
  span. Fix: a continuous run of planted spans now shares one coordinate-wise
  median target across all its original-key readings (`_stable_targets`),
  while penetration still lifts the median z to ground. Diagnostic after the
  fix: every consecutive span target step is 0.000 cm, every within-span hold
  remains 0.000 cm, and the full suite plus ruff are green. Regression test:
  `test_pin_uses_one_stable_target_across_a_noisy_contact_run`.
- **L10.** Follow-up measurement after L9 (2026-10-23): target stabilization
  fixed positional jitter, but visual vibration remained because the generated
  rows carried noisy local ankle roll. The solve now also uses one median knee
  pole per continuous contact run; regression coverage proves noisy generated
  knee rows produce identical hip/knee rotations. Real-cache measurement after
  this change: planted toe displacement remains 0.000 cm, but local ankle
  rotation still varies about 0.75 degrees per row (maximum 1.38 degrees).
  The remaining product decision is whether to smooth captured ankle roll for
  planted contacts, which would reduce vibration but could erase intentional
  foot-roll animation; the current S3 contract preserves that roll exactly.
