# R2 — Anchor-vs-fill seam feathering

Objective: kill the visible pop where the engine's generated rows meet the
captured anchors (measured ~50 deg upper-arm jump at an anchor's neighbour
row, M9 probe). Blend the FREE rows adjacent to each anchor toward that
anchor over a short window, at adoption. Keys and guides stay byte-exact
(FR-GEN-01 is untouchable).

Branch: `feat/develop` · Delivery: work-unit commits, no PR slices
(user standing), push on request · Test runner:
`.venv\Scripts\python.exe -m pytest -q --basetemp="$env:TEMP\aim-tmp"`
(two steps: suite ignores `tests/test_ai_hmr2_adapter.py`, then that file
alone) + `.venv\Scripts\ruff.exe check .`. GPU validation is an
`.engine/_*` probe, never a committed test.

## Specs

- **S1.** The defect (spec.md, verbatim): *"the **anchor-vs-fill seam** —
  captured anchors can sit far from the model's content in joint space
  (measured: ~50 deg upper-arm jump at an anchor's neighbor row on the
  real clip), so boundary rows snap; the pipeline's cleanup pass owns
  smoothing today"*. R2 makes the tool own it at adoption.
- **S2.** Keys and guides are never rewritten: every anchor frame's pose
  objects survive byte-identical (same guarantee `pin_foot_contacts` and
  `smooth_root_trajectory` already keep).
- **S3.** Only NON-anchor rows within `window` frames of a boundary anchor
  change, and only joints whose rotation differs from that anchor by more
  than `threshold_deg` (already-continuous content must not twitch). The
  blend is `slerp(content, anchor_pose, alpha)` with alpha decaying with
  distance (`strength` at the first row, less deeper in); a row blends
  toward its nearest boundary anchor.
- **S4.** The root joint `Main` is not rotated (its rotation is identity
  by domain invariant); translations are untouched (root smoothing owns
  them, pinning owns feet).
- **S5.** Adoption order: root smoothing → seam feathering → foot pinning
  (pinning keeps the final word on contact rows). The adoption status note
  reports the corrected-frame count, NFR-03 style.
- **S6.** Window/strength/threshold are MEASURED defaults (T3 probe on
  JACE_REF_04 keys 40/87, guides {58,76}, skip 500): report the boundary
  jump before/after feathering per joint class, the max deviation the
  blend introduces mid-window, and confirm anchors byte-exact; produce the
  before/after FBX for animator inspection. Constants adopted from that
  evidence.
- **S7.** Docs: spec.md wide-gap follow-up updated in the same change set
  (the seam entry moves from "the pipeline's cleanup pass owns smoothing"
  to the landed mechanism with its measured effect).

## Tasks

| ID | S#  | Route  | Status  | Commit |
| -- | --- | ------ | ------- | ------ |
| T1 | S2,S3,S4 | inline | done | `bff7704` |
| T2 | S5   | inline | done | `bff7704` |
| T3 | S6   | inline | done | this |
| T4 | S7   | inline | done | this |

## Log

- **L1.** User, verbatim (2026-10-26): *"dale"* — approving starting the
  refinement agenda at priority 1 (the seam), proposed by the parent after
  R1 (progress bar + survival, `564f2b4`) was confirmed working.
- **L2.** Exploration (2026-10-26): adoption is
  `capture_controller._on_inbetweens_filled` (root smoothing then
  `_pin_filled`); `slerp` in `core/resampling.py` (clamped, short-arc,
  nlerp near-identity guard) is the reusable blend; anchors at adoption =
  `self._fill_original_keys` + `self._guides` keys (both reasserted
  byte-exact by the fill contract — the adapter tests already pin it).
  M9's probe numbers to beat: anchor row L 164.8 deg vs first content row
  L 114.5 (jump ~50.3); interior range 101.7..118.2.
- **L3.** Sizing (2026-10-26): large (pure mechanism + wiring + measured
  constants via GPU probe + docs). Route: parent inline (no writer
  trigger — shared files, one behavior); probe runs in background.
- **L4.** T1+T2 landed (`bff7704`): `core/seam.py` `feather_anchor_seams`
  (pure; slerp along the short arc, nearest boundary wins, alpha decays
  `strength*(1 - d/(window+1))`, threshold skips continuous joints,
  untouched rows keep Keyframe object identity, `(timeline, 0)` returned
  unchanged when nothing moved) wired into adoption between root smoothing
  and pinning, with a status note. RED observed on 7 core + 2 wiring tests;
  full suite green in two steps, ruff clean. Provisional constants
  `SEAM_WINDOW_FRAMES=4`, `SEAM_BLEND_STRENGTH=0.8`, `SEAM_THRESHOLD_DEG=30`
  await the T3 grid.
- **L5.** T3 probe running (`.engine/_e2e_seam_feather.py`): ONE real fill
  (keys 40/87, guides {58,76}, skip 500) feeds the whole
  window {2,4,6} x strength {0.6,0.8,1.0} grid (feathering is pure CPU);
  per combo: boundary arm jumps (L23 metric) before/after, rewritten count,
  anchor survival, worst angular motion the blend introduces; raw and
  default (w4/s0.8) FBXs for animator inspection.
- **L6.** T3 measured (2026-10-26, `.engine/_e2e_seam_feather.py`): ONE
  real fill (keys 40/87, guides {58,76}, skip 500, 42.3 s, anchors
  reasserted byte-exact True) fed the pure-CPU grid window {2,4,6} x
  strength {0.6,0.8,1.0} at threshold 30. Raw mean boundary arm jump
  (L+R, FK): 78.8 deg over the six neighbour rows (range 51.3..95.8).
  After: w2s8 48.1 (12 rows), w4s8 42.0 (24 rows, worst joint motion
  96.9 deg), w4s1.0 33.1, w6s8 39.4, w6s1.0 30.1 but 129.8 deg worst
  motion — evidence of the pop becoming an anchor-hugging glide. ALL 9
  combos kept anchor rows byte-exact. ADOPTED: window 4, strength 0.8,
  threshold 30 — the middle setting that halves the pop while leaving
  ~40% of the gap content untouched; constants now carry their measured
  rationale in seam.py. FBX pair for the animator: raw vs w4s8 feathered.
- **L7.** T4: spec.md wide-gap follow-up entry rewritten — the seam moves
  from "the pipeline's cleanup pass owns smoothing" to the landed feather
  with the grid numbers, the rejected aggressive setting, and the honest
  residual (the boundary still eases TO the capture, and the interior
  content disagreement remains model-limited).
