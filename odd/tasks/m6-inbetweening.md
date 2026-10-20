# M6 — Generative Inbetweening (CondMDI + Model Factory)

- **Objective**: fill the gaps between locked Golden Pose keys with CondMDI
  (out-of-process), behind an `InbetweeningPort` + Model Factory selectable
  from the GUI; the generated timeline is previewable in the viewport. Export
  of the approved FBX stays in M8, IK foot-pinning in M7 (spec.md roadmap :298).
- **Branch**: `feat/develop` · **Delivery strategy**: `ask-on-risk` (default).
- **Test runner**: `pytest` with `--basetemp="$env:TEMP\aim-tmp"`, junitxml
  schema verification; `ruff check .`.

## Specs

Requirements verbatim from `spec.md` §2 (:62-70) — all Must:

- **S1. (FR-GEN-01)** *"Human keys are locked as hard constraints; only gaps are
  filled."* Acceptance: *"Output equals input at every human key (within
  tolerance); nothing outside the first/last key."*
- **S2. (FR-GEN-02)** *"Engine behind a Model Factory selectable from the GUI;
  MVP = CondMDI."* Acceptance: *"Swapping the engine needs no `core/` edits;
  CondMDI is the default."* The existing single-frame `AIPort` keeps its
  contract untouched; inbetweening gets its own port (ports/ai_port.py:8-12).
- **S3. (FR-GEN-03)** *"Generation runs in a `QThread`, batch 1, FP16, cache
  released; stays ≤ 10 GB VRAM."* Same isolation constraints as FR-CAP-05;
  non-fatal typed failures surfaced like `PoseExtractionRunner` does.

Authorized scope of M6 = S1-S3 plus the domain/research facts below. **Out of
scope**: FR-GEN-04 (final FBX export, M8), FR-IK-01 (foot pinning, M7),
text-prompt conditioning UI (the engine supports it; no product ask yet —
shipped with an empty prompt), LAFAN1/MDM engines (post-MVP, plan :194-196).

**Engine facts (researched 2026-10-20, sources: arXiv 2405.11126, project page
setareh c.github.io/CondMDI/, official repo setarehc/diffusion-motion-inbetweening)**:

- Official code **MIT**; keyframe-conditioned checkpoint (randomly sampled
  frames *and* joints) on Google Drive; trained on **HumanML3D at 20 fps** in
  the 263-dim HumanML3D representation with GMD's absolute-root modification.
- Conditioning = joint **positions** at key frames + observation mask;
  partial-joint keyframes supported. Max generated length ≈ 9.8 s / 196 frames.
- Stack pins Python 3.7-era / PyTorch 1.13 / CLIP → **out-of-process worker**
  (same pattern as HMR2's `.engine/venv`, AGENTS.md "Pose engine decision").
- **Assumptions (mine, marked as such, subject to user correction)**:
  - (a) `L_Hand`/`R_Hand` are outside HumanML3D's 22-joint body: the generator
    produces them by copy-of-wrist/interpolation, never by the model.
  - (b) Gaps longer than the model window are generated in overlapping
    windows, human keys always re-asserted (S1 wins over smoothness).
  - (c) The 24 fps timeline is resampled 24→20→24 around the model call;
    human keys land exactly on their original frames after resample-back.
  - (d) Weights are user-supplied and never vendored (same posture as HMR2,
    spec.md §4.14 precedent), even though the engine's code is MIT.

## Tasks

| ID | Spec | Route | Status | Evidence |
| -- | ---- | ----- | ------ | -------- |
| T1 | S2 | inline | done (2026-10-20) | C16 = commit `62b53b5`: `InbetweeningPort` (ports/ai_port.py — timeline in, timeline out, keys untouched contract) + `model_factory.py` (`capture_engine`/`inbetweening_engine`, lazy constructors, `UnknownEngineError` typed) + `CondMDIAdapter` registered ahead of its implementation (refuses loudly until T3/T4). RED observed (modules missing), then factory test file RED (NameError fix), suite **204/0/0/0** from junitxml, ruff clean. Native assess against base `e7960b2`: risk medium (executable_change), `review_due: false` / under_budget — boundary unchanged. (Log L5) |
| T2 | S1 | inline | done (2026-10-20) | C17: `core/resampling.py` — the engine-agnostic sampling-clock bridge: `slerp` (short-arc, double-cover-safe, NLERP above 0.9995 dot, endpoints clamped), `interpolate_pose`, `resample_dense_poses` (dense[i] at source fps → per-target-frame poses anchored at any `frame_start`, never extrapolates past the dense span), `fill_gap_synthetically` (the S1 rule materialized: keys byte-untouched, every gap frame filled or raised, no writes outside the locked span). REDESIGNED during the task (Log L6): the 263-dim HumanML3D conversion moved to T3's worker using the official vendored code, so this module is pure stdlib domain math. RED observed (module missing + 4 honest test-side fixes: Quaternion has no default fields, a wrong expected set, per-field quaternion approx). Suite **218/0/0/0** junitxml, ruff clean (Log L7) |
| T3 | S1, S2 | inline | ⬜ | `CondMDIWorker` out-of-process line-JSON protocol + `FakeCondMDIWorker` tests (bootstrap → ready → request → response); the worker performs the HumanML3D-263 conversion with the official vendored code (`.engine/condmdi`, repo cloned), matching `humanml_motion_abs` (`abs_3d=True`); chunking per (b), resample per (c) |
| T4 | S1, S2, S3 | inline | ⬜ | `CondMDIAdapter` (typed non-fatal failures, FP16, `empty_cache`) + GUI runner on a `QThread` + factory wiring in `main.py`; viewport preview of the generated timeline |
| T5 | S1, S3 | inline | ⬜ | On-box e2e with the real checkpoint: keys respected within tolerance, VRAM/latency measured and recorded; `AGENTS.md` tech-stack row updated if figures warrant |

## Log

- **L1.** User, verbatim: *"he probado con un video mas simple, con una sola
  persona y la captura es correcta, aunque no del todo precisa. Continua"*
  (2026-10-20) — and, when asked how to proceed, chose **"M6: CondMDI"** over a
  precision round on the capture.
- **L2.** Pre-M6 context: the capture imprecision the user noticed is a
  documented engine limit (HMR2.0 `b`: ~54 mm PA-MPJPE 3DPW, LSP-Ext
  PCK@0.05 = 0.53); the plan already assigns the cleanup to the animator over
  the exported FBX (plan §5 pipeline step 2) — no M6 work item on it.
- **L3.** Research (2026-10-20): CondMDI identified — Cohan et al., SIGGRAPH
  2024 (arXiv 2405.11126), official MIT implementation
  `setarehc/diffusion-motion-inbetweening`, keyframe-conditioned checkpoint
  (random frames+joints) on Google Drive, HumanML3D 20 fps / 263-dim
  representation with absolute root (GMD variant), position+mask conditioning,
  partial joints supported, ~9.8 s / 196-frame max window. Old pinned stack →
  out-of-process worker like HMR2. VRAM/latency unpublished → T5 measures.
- **L4.** Repo state (exploration, 2026-10-20): no inbetweening port exists
  (ports/ai_port.py:8-12 reserves it); no Model Factory (`main.py:30-31`
  hardwires `Hmr2Adapter`); `condmdi_adapter.py` is a 1-line stub;
  `requirements-ai.txt` has only `torch>=2.14`. M5 patterns to reuse:
  line-JSON worker protocol, typed actionable failures, `PoseExtractionRunner`
  QThread batch-1 pattern, `bind_offsets()` domain conversion. spec.md open
  question 7 (port signatures) resolves with T1.
- L5. T1 done (2026-10-20): the commit message says 206/0/0/0 but junitxml's authoritative count is 204/0/0/0 - the doc wins; console dot-counts are not evidence (standing convention). Factory tests reuse the fake worker's canned bind offsets to build a valid production skeleton (production_skeleton refuses partial rigs by design). Next: T2 domain<->HumanML3D-263 conversion.
- L6. T2 redesign decision (2026-10-20): the HumanML3D-263 conversion is an ENGINE convention, not domain logic. Reimplementing its layout by hand is how the T15 flip class of bug is born, so the conversion lives in the out-of-process worker built on the official vendored code (.engine/condmdi cloned from setarehc/diffusion-motion-inbetweening; representation confirmed: 263 dims = 1 root rot velocity + 2 root lin velocity + 1 root height + 63 ric + 126 sixd + 66 velocities + 4 foot contacts, with the abs_3d/GMD variant selected by dataset config). T2 therefore delivered the CLOCK BRIDGE in core/ (slerp, interpolate_pose, resample_dense_poses, fill_gap_synthetically) and T3 absorbs the 263 conversion.
- L7. Test craft (2026-10-20): pytest.approx aimed at a slots dataclass does not compare fields numerically and gave a false negative at 1e-16 relative difference; tests compare Quaternion field-wise via a fixed _almost helper now. The slerp endpoint contract returns the origin/target objects unmodified at t=0/1 so composed interpolation stays bit-exact at anchored frames.
