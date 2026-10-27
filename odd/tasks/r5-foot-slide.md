# R5 — planted-foot sliding on the real clip (diagnosed: capture noise vs the 5.5 cm bar)

Objective: fix the defect the user reported from the app test (2026-10-27,
verbatim): *"el resultado es mas o menos estable, aunque tanto exportando
goldenpose como exportando generando enbetween los pies resvalan bastante
cuando deben estar clavandos en el suelo, esto se ve bantante cuando la
pelis rota, al menos aparentemente."* The `.engine/_diag_foot_slide.py`
probe measured the user's two real exports and located the cause. The
fill-export remedy runs through the tool's own pin pass; the keys-only
slide is capture-domain and gets an honest report, not a fake fix.

Branch: `feat/develop` · Delivery: work-unit commits, no PR slices
(user standing), push on request · Test runner:
`.venv\Scripts\python.exe -m pytest -q --basetemp="$env:TEMP\aim-tmp"`
(two steps: suite ignores `tests/test_ai_hmr2_adapter.py`, then that file
alone) + `.venv\Scripts\ruff.exe check .`. Real-clip work is
`.engine/_*` probes, never committed tests.

## Specs

- **S1.** The measured diagnosis (probe, the user's own files):
  - golden export (16 keys): low-foot drift/SPAN median 6.5 cm
    (L) / 4.8 (R), p90 13.2/9.5, max 23.9/22.8; body-relative
    (M8 S6 reading, root-motion-proof) median 6.9/8.2 — captures of a
    planted foot disagree by MORE than the 5.5 cm planting bar, on most
    spans;
  - fill export (203 rows): per-frame low-foot body drift median ~1 cm —
    continuous slow slide;
  - `Main` rotation worst |angle| = 0.00 deg on both (invariant holds);
  - root step/span in the golden export median 6.6 cm — the clip's camera
    genuinely rotates/moves, matching the user's observation.
  Conclusion: pinning never fired on this clip (detection bar below the
  capture noise), and the golden-only export has no post-processing pass
  at all by design (pinning needs the dense rows a fill creates).
- **S2.** `pin_foot_contacts` gains pass-through re-tune arguments
  (`position_tolerance_cm`, `ground_height_cm`, keyword-only, defaults =
  the named constants). Without arguments the pass behaves EXACTLY as
  today (byte-identical output on the existing suites); with them, the
  detection bar the pass applies is the caller's. This makes OQ8's
  standing claim ("adjustable without logic changes") true on the pin
  path, not just on `contact_spans`.
- **S3.** A sweep probe over the user's real pair (golden keys + filled
  state) reports, per tolerance {5.5, 8, 12, 16, 20, 25}: spans detected
  planted, frames corrected, the residual body-drift per span INSIDE
  pinned runs before/after, and the false-positive evidence — spans whose
  drift at that bar plausibly contains real steps (a frozen walking foot
  is a worse artifact than a sliding planted one). Emits pinned FBX
  variants for the animator's eye.
- **S4.** The production default is NOT changed by the tool alone.
  Re-tuning `PLANT_POSITION_TOLERANCE_CM` (or wiring a GUI knob) is an
  animator decision — OQ8's precedent was exactly that. The report hands
  the user the numbers and one focused question.
- **S5.** Docs sync (after the user's decision): spec.md OQ8 entry + the
  R-agenda note, and this file's log.

## Tasks

| ID | S#  | Route  | Status  | Commit |
| -- | --- | ------ | ------- | ------ |
| T1 | S2  | inline | done    | see log |
| T2 | S3  | inline | done    | probe |
| T3 | S4  | user   | done    | this |
| T4 | S5  | inline | done    | this |

## Log

- **L1.** User, verbatim (2026-10-27): the app-test verdict quoted in the
  objective, naming the two export files at the repository root.
- **L2.** Measurement (`.engine/_diag_foot_slide.py`): numbers above.
  Key insight: sliding is visible in the KEYS-ONLY export, which no pin
  pass ever processes — so the capture itself is the source; the 5.5 cm
  bar calibrated in M7 against per-frame guide noise (3.1-6.3 cm) sits
  BELOW the real span-to-span drift on this rotating-camera clip
  (body-relative median 6.9-8.2).
- **L3.** Sizing: medium (one additive API extension with preserved
  defaults, one sweep probe, then a user decision). Route: parent inline
  (no writer trigger; the probe is the deliverable's evidence).
- **L4.** Sweep (T2, `.engine/_sim_pin_sweep.py`, user's real fill, the 16
  golden keys, ground_z=0 like the app; per-bar `pin_foot_contacts` via the
  new pass-throughs): tol 5.5 finds 5/15 spans already planted - the app's
  adoption pin DID fire on the low-noise spans (their inside-slide is
  0.29 cm/frame, effectively straight). The visible slide lives in the
  OTHER spans: not planted because the bar is below the capture noise.
- **L5.** Raised bars: tol=8 catches 3 more spans (8/15), inside-slide
  p90 3.53 -> 2.06 cm/frame, max slightly up (7.27->8.28, feet clamped on
  reach); tol=12 first frozen-step evidence (1 pinned span with >6 cm
  key-to-key z travel = a step misdetected as a plant); tol 16-25 produce
  a 34.65 cm/frame AFTER-pin max (median target beyond leg reach -> clamp
  snap) and 3 step-like false plants. Rejected on evidence: 12+.
  Defensible: 8 (modest real gain, no new artifacts class).
- **L6.** The structural residual the bar cannot fix: FR-GEN-01 keeps the
  KEYS byte-exact, and the keys themselves disagree 6.9-23.9 cm on this
  clip (diag). Pinning straightens interior rows to the run median but the
  key rows stay noisy -> a step at every planted key boundary remains.
  Correcting that means grounding mode (preserve_original_keys=False, the
  opt-in trial M8 already implements) - it rewrites captured golden poses,
  which is a product decision (T3), not a threshold retune. The
  keys-only export has no interior rows: no pass runs there by design
  today; grounding on a sparse timeline would also need a new mode.
- **L7. CORRECTION to the product framing (honest one).** "Option 2"
  (grounding) was NOT missing from the app: since M8 (`e23308e`,
  "ground planted feet with per-leg IK correction")
  `CaptureController._pin_filled` already calls pin with
  preserve_original_keys=False + ground_contacts=True - the user's own
  fill export was grounded on its 5 detected spans. The only real gap is
  the DETECTION BAR. The parent's A/B/C question was partially stale;
  S4's decision reduces to the bar retune (option 1), which stands.
- **L8.** Grounding sweep (T2b, `.engine/_sim_ground_sweep.py`, user's
  fill, per-bar re-ground): the plain-pin clamp-snap artifact (34.65
  cm/frame at 16+) does NOT reproduce under grounding - key-boundary
  jumps fall from ~4.3-4.5 max to ~1.75 cm at every bar; ~13 planted keys
  rewritten at 8/12. Freeze risk is the discriminator: bar 8 = 0, bar 12
  = 1 - the span (77,93), R_Foot z-travel 7.3 cm between keys (a step,
  not a plant) gets pinned to the run median. Bar 16 catches 10/15 with
  the same single risk. Eye-test variants on the Desktop
  (fill_ground_tol{5.5,8,12}.fbx; 5.5 = today's app output).
- **T3 decision (pending user): bar 8 (evidence-safe, recommended) vs 12
  (animator eye preferred among plain variants; freezes key span
  77->93).** Awaiting: the user's answer after viewing the ground files.
- **L9.** User decision (2026-10-27, verbatim): *"me sigue convenciendo
  mas el resultado del 12"* - after viewing the GROUNDING variants, the
  animator approved PLANT_POSITION_TOLERANCE_CM = 12.0 (the OQ8 precedent:
  the animator's eye sets the number). The honest caveat was delivered
  and weighed by them: the (77,93) R_Foot span (7.3 cm key-to-key z
  travel - step-LIKE by the >6 cm heuristic, possibly capture noise)
  gets pinned; their eye preferred the pinned output.
- **L10.** Retune landed: constant 5.5 -> 12.0 with its full evidence
  chain in the comment; OQ8 record test updated (asserts 12.0/8.0, names
  both amendments); the T1 pass-through fixture drift raised 8 -> 14 so
  it still straddles the CURRENT bar (8 would now be inside 12 - the
  suite was green because no fixture sat in (5.5,12]); spec.md OQ8 entry
  rewritten (12.0, grounding history, pass-throughs, residual
  clip-dependence) and the afinar agenda gains item (4) closed. Full
  suite two-step green, ruff clean. R5 closed.
