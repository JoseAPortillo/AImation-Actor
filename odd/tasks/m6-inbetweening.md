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
| T1 | S2 | inline | ⬜ | `InbetweeningPort` (timeline in → timeline out) + `ModelFactory` in `adapters/ai/`, RED-first with fakes, no `core/` edits when swapping |
| T2 | S1 | inline | ⬜ | Pure-core conversion: domain `TimelineState` ↔ HumanML3D-263 (positions+rotations, root handling, hands assumption (a)); property tests: keys survive round trip to tolerance |
| T3 | S1, S2 | inline | ⬜ | `CondMDIWorker` out-of-process line-JSON protocol + `FakeCondMDIWorker` tests (bootstrap → ready → request → response); chunking per (b), resample per (c) |
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
