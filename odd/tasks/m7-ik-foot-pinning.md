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
- **S3. (design shape, decided at planning 2026-10-23)** The pass is pure
  domain math in `core/` and consumes the FK `core/kinematics.py` already
  exposes (`joint_world_positions`; its docstring anticipates M7). Detection
  reads the FOOT world positions (L/R_Ankle + L/R_Foot) at the two bounding
  ORIGINAL keys of each span; a foot is "planted" across a span when both
  readings sit at ground contact (world z ≤ tol ground) and their positions
  agree within the key-side tolerance (both values pend the user's OQ8 answer,
  S4). Pinning then corrects every non-original frame of that span — generated
  engine rows AND capture-anchored rows (T9 fills included, uniform rule per
  S1/S2 wording) — with a two-bone analytic IK that only rewrites
  L/R_Hip + L/R_Knee rotations to land the ANKLE at the first key's contact
  position (the ankle's own rotation is preserved, so foot roll stays exactly
  as captured/created); the original key poses stay byte-untouched (the S1
  pattern of M6). When BOTH feet are planted in the same span, the pelvis
  height is kept within the feasibility band the two leg chains impose
  (clamped between the two solvable heights, never below the highest ground
  pin); a single planted foot never moves the pelvis. Ground z = 0 (the
  `Pelvis` height convention: height is ground-to-hip). Penetration (a foot's
  world z below 0) resolves inside the same pin pass. The pass runs at FILL
  ADOPTION time (controller-side), so the animator scrubs an already-pinned
  timeline in the viewport; the final export (M8) simply writes it. The
  pre-fill original keys are known exactly there (after adoption the dense
  keyframes are indistinguishable from generated ones, `core/resampling.py`
  L230).
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
| T1 | S1, S3, S4 | inline | pending | `core/foot_contacts.py`: `planted_feet(...)` — pure detection over a dense timeline + original-key frame list + named thresholds; unit-tested RED first (planted / swing / one-foot-on-ground-only / penetration-data cases) |
| T2 | S1, S2, S3, S4 | inline | pending | `core/foot_ik.py`: two-bone analytic IK + `pin_foot_contacts(timeline, original_key_frames)`: rewrites only Hip/Knee rotations of pinned spans, keys byte-untouched, both-feet pelvis clamp, penetration fix, post-pin hold ≤ 0.5 cm; RED first |
| T3 | S1, S3 | inline | pending | Controller wiring: detection + pinning run in the fill-adoption path where the pre-fill keys are known; typed degradation without a rig; status line names the pinned spans |
| T4 | S1, S2 | inline | pending | GPU validation on the real clip (JACE_REF_04, keys 46/71 standing contact + 46/58/71): foot world drift across detected contact spans < S4 hold; FBX readback via the app's writer; keys reassertion intact |

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
  (SDD rule). T1 starts right after with its RED first.
