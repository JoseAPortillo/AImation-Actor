# M9 — Wide-gap fill: diffusion init with the capture prior

Objective: close the MVP's last known quality gap — engine-filled gaps
(wider than 24 interior frames) fill with degenerate splay (M6 L23);
seed the diffusion with the capture prior (`init_image` + `skip_timesteps`,
vendored `p_sample_loop` semantics) so free rows start from a plausible
prior instead of pure noise. The user's frame: close the MVP now,
"afinar" (refine) later.

Branch: `feat/develop` · Delivery: work-unit commits, no PR slices
(user 2026-10-22, standing), pushed on request · Test runner:
`.venv\Scripts\python.exe -m pytest -q --basetemp="$env:TEMP\aim-tmp"`
(two steps: suite ignores `tests/test_ai_hmr2_adapter.py`, then that file
alone) + `.venv\Scripts\ruff.exe check .`. Random-GUI tests may run the
fake worker on this interpreter; the REAL GPU sweep runs as an
`.engine/_*` probe, never as a committed test.

## Specs

- **S1.** The fill request accepts an optional `skip_timesteps`
  (non-negative int, default/absent = 0). User (verbatim): *"vamos con la
  propuesta, quiero cerrar el mvp y luego vamos a afinarlo"* — the proposal
  being the prepared M6 remedy: *diffusion init with the capture prior
  (`init_image` + `skip_timesteps`)*.
- **S2.** Vendored semantics (read, never patched —
  `.engine/condmdi/diffusion/gaussian_diffusion.py`): with
  `skip_timesteps=k > 0` sampling runs `num_timesteps - k` steps starting at
  timestep `num_timesteps - k - 1`, and `init_image` is noised once at that
  timestep (`q_sample`). `init_image=None` with `skip>0` degrades to zeros,
  so `skip > 0` MUST carry the worker's own dense prior: the normalized
  featurized request motion (`obs_x0`: keys exact, guides stamped at their
  samples, straight lerp underneath — already built by `fill` step 4).
  `skip == 0` keeps today's behavior exactly (`skip_timesteps=0,
  init_image=None`).
- **S3.** Refusals: a `skip_timesteps` outside `0 <= skip <
  self.diffusion.num_timesteps` is a typed `_RequestError` (1000 timesteps
  in the vendored config; `utils/model_util.py` `steps = 1000`, no
  respacing).
- **S4.** Adapter policy (decision): an engine-filled gap sends
  `skip_timesteps = _CAPTURE_PRIOR_SKIP_TIMESTEPS` (measured constant,
  provisional until T3) **only when that gap's request carries at least one
  guide** — capture data exists in the gap, so the prior is the capture.
  A gap with no guides inside it (guides `None`, absent, or none landing in
  this gap) sends no skip: its prior would be a bare keys-lerp and the risk
  is trading splay for a static glide. Narrow gaps are unaffected (T9:
  fully covered gaps never reach the engine).
- **S5.** Probe (T3, real clip): keys 40/87 of JACE_REF_04
  (47 interior frames → engine track; the T9/L25 boundary case), the real
  controller guide plan, sweep `skip ∈ {0, 300, 500, 700, 850}` and measure:
  arm columns vs the L23 splay controls, keys/anchors fidelity, facing
  continuity (`facing·Δ > 0` convention, S9), latency. The chosen value is
  recorded with its evidence and becomes `_CAPTURE_PRIOR_SKIP_TIMESTEPS`.
- **S6.** Deterministic pinning: worker helper tests (validation + init
  decision) and adapter wire tests (request carries skips iff guided);
  fake-worker adapter tests stay GPU-free, like M6 T6. The real engine
  path is validated by the T3 probe, not by the suite.
- **S7.** Docs: spec.md ("Wide-gap fill quality remains model-limited"
  entry) updated in the same change set; `AGENTS.md` untouched (no
  architecture change — the worker protocol gains one optional field).

## Tasks

| ID | S#  | Route  | Status | Commit |
| -- | --- | ------ | ------ | ------ |
| T1 | S1,S2,S3,S6 | inline | done | `b2fe94b` |
| T2 | S4,S6 | inline | done | `b2fe94b` |
| T3 | S5,S4(probe evidence) | inline | done | this |
| T4 | S7 | inline | done | this |

## Log

- **L1.** User, verbatim (2026-10-26): *"vamos con la propuesta, quiero
  cerrar el mvp y luego vamos a afinarlo"*. Background decisions: M8 S9
  frame-convention fix landed earlier the same day (`c1be7ef`); the S8 GUI
  setting landed at `1497258`/`c49d1c6`; the wide-gap remedy was prepared
  but deferred in M6 L25 ("option 2 ... the prepared next probe if the
  user wants wide-gap quality chased") and the user now wants it to close
  the MVP.
- **L2.** Exploration (2026-10-26): the worker's `fill` already passes
  `skip_timesteps=0, init_image=None` to the vendored `p_sample_loop`
  (`condmdi_worker.py:615`). Vendored `p_sample_loop_progressive` (gaussian_diffusion.py):
  `indices = list(range(num_timesteps - skip_timesteps))[::-1]`; with
  `init_image` set, `img = q_sample(init_image, indices[0], img)`;
  `skip_timesteps and init_image is None` → zeros init (useless — noted in
  S2). Diffusion: `steps = 1000`, no respacing, `use_ddim` off →
  `num_timesteps == 1000`; a full fill measured ~64 s (M8 §4.13), so the
  skip also cuts latency proportionally. The obs mechanism is MDM-style
  inpainting: `obs_mask` replants the observed rows every step, so the init
  prior shapes only the FREE rows — exactly the L23 degenerate ones.
- **L3.** Sizing (2026-10-26): large — separate deliverables (deterministic
  protocol + measured default) and a GPU measurement session; tracked.
  Route: parent writes inline (no writer trigger: single behavior, shared
  files); the probe sweep runs in `.engine/_e2e_wide_gap_prior.py` reusing
  the real adapter, like `._e2e_dense_capture.py` did for T9.
- **L4.** T1+T2 done (work-unit commit `b2fe94b`): worker `_prior_init`
  (typed non-integer, negative and beyond-chain refusals; skip 0 keeps the
  noise start byte-for-byte) and the adapter policy (training gaps with
  guides carry `_CAPTURE_PRIOR_SKIP_TIMESTEPS`, provisional 300; unguided
  or guide-less payload → no field at all). RED observed on 8 new tests
  (5 worker helper + 3 adapter wire), suite green in the condmdi holders,
  ruff clean. The vendor-patch discipline held: only request fields +
  policy; `p_sample_loop` semantics read, never edited.
- **L5.** T3 first run aborted by a probe-script bug (not product code):
  `arm_cols` kept a stale `anchors` parameter; the `skip000` fill itself
  completed (135.4 s wall, guides byte-exact True) and its FBX was saved
  before the report crashed. Corrected and relaunched whole (the sweep is
  not resumable).
- **L6.** T3 measured (2026-10-26, `.engine/_e2e_wide_gap_prior.py`, sweep
  0/300/500/700/850 on keys 40/87, guides {58, 76} from the real controller
  plan, 5x guides byte-exact True): the interior content is
  **skip-insensitive within ~1.5 deg** (arm-vs-down columns; facing-delta
  positive share constant 85.1% over every run; the mean dot shrinks
  151 -> 74.7 cm because the travelling compresses toward the lerp prior).
  The prepared QUALITY premise is falsified: the per-step observation
  replant dominates the free rows, so the prior start barely moves them -
  the L23 "model's free-joint content" verdict reconfirmed at a third knob.
  What the skip DOES control is cost per wide gap: 70.6 -> 44.2 -> 31.6 ->
  19.0 -> 9.6 s (proportional to 1000-skip). Adopted default:
  `_CAPTURE_PRIOR_SKIP_TIMESTEPS = 500` (2.2x latency saving at
  stat-noise-equal content); test literal updated 300 -> 500 with the
  evidence comment. Product-visible defect the probe surfaced for the
  "afinar" phase: the anchor-vs-fill seam (~50 deg upper-arm snap between a
  captured anchor row and the model's first content row); recorded in
  spec.md as the follow-up priority, above free-row content itself.
  Random-GUI observation: first fill of the FIRST run cost 135.4 s vs 70.6
  s on the identical second run - the first-run cost is cold-cache engine
  work, not the mechanism.
