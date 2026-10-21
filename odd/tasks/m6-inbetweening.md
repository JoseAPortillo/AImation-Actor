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
| T3 | S1, S2 | inline | done, app side (2026-10-20) | C18: the adapter-side bridge lives and is fake-tested end to end. `CondMDIAdapter` (typed `CondMDIEngineError`; lazy validation: engine python, worker script, official repo dir, checkpoint; subprocess bridge mirrored from `hmr2_adapter`), wire contract pinned by tests: bootstrap {engine_root, repo_dir, checkpoint, mean_path, std_path, half_precision} / ready {status, gpu, vram_total_mib, motion_fps, max_frames} / request {span_frames, keys (domain quats+heights), bind_offsets} / response {status, poses[{frame, pose}]} | error {message, fatal}. Orchestration per gap: pre-spawn refusal for gaps over the model window (single-window MVP; splitting deferred to T5 with its measurements), keys enter at rounded motion-sample indices of the engine's clock (`motion_fps` from ready), the reply's dense motion resamples through `core.resampling` anchored at the left key, `fill_gap_synthetically` guarantees S1. `tests/fake_condmdi_worker.py`: modes ok/ready_error/fill_error/die_mid_request/die_once/hang + a request-count file. De-coupled finding: the core's extras rule now ignores poses landing on keyed endpoints (keys win) rather than rejecting them. RED observed; suite **225/0/0/0** junitxml, ruff clean. The REAL worker (263 conversion on the vendored official stack, its own venv) moved to T5 — it is exactly the onbox engine work (Log L8) |
| T4 | S1, S2, S3 | inline | done (2026-10-20) | C19: `InbetweeningRunner` (`adapters/ai/inbetween_runner.py`, the `PoseExtractionRunner` pattern verbatim: QThread job, batch-1 refusals, non-fatal failures) + `CaptureController.fill_inbetweens` (claims against the clip generation like extraction: ≥2 keys, no engine, busy and stale replacement all typed, then adoption via `timeline_changed`+`pose_changed` — the generated timeline reaches the viewport through the wiring that already exists, no new widget work) + `MainWindow.action_fill_inbetweens` (`G`, in the new Inbetweens menu; `closeEvent` shuts both runners) + `main.py` wired through the Model Factory for BOTH engines (`capture_engine("hmr2")`, `inbetweening_engine()` MVP default). New tests: `test_ai_inbetween_runner.py` (8), `test_gui_inbetweening.py` (7), window and factory wiring pins. Suite **243/0/0/0** junitxml (one pre-existing flaky HMR2 timeout test failed once in a full run and passed alone and in re-runs — timing, not the diff), ruff clean |
| T5 | S1, S3 | inline | ▶ conversion half done (2026-10-21) | `condmdi_worker.py` conversion layer validated on-box by `.engine/_probe_condmdi_conversion.py` with the engine interpreter (P0-P1b-P2-P3): P1 round trip interior 0.001 mm / edge 4.7 mm; P1b fast-turn 584 mm documented, no gate; P2 template rig 5.9-40.1 cm bones + router identity 3e-5 mm; **P3 chain decode interior 0.001 mm / edge 9.2 mm and Maya-threaded wire rebuilds the engine chain to ~2e-17 quat gap**. The probe caught a real worker bug: `Skeleton`'s chain convention RESTARTS the accumulated rotation at the root quat per `kinematic_tree` chain (arm collars are pelvis-local, never threaded through Spine_3), so `_frame_to_wire` now re-expresses the decoded locals as Maya parent-relative locals (only collars move); pinned by `tests/test_ai_condmdi_worker_wire.py` (RED observed, then GREEN). Decode-side fixes verified by the probe: contiguous 6D layout + `_quat_from_matrix` right-branches, and `_featurize_abs`'s defensive copy (official `extract_features` mutates its input). Remaining: real-checkpoint bootstrap (model load, minimal fill), VRAM/latency measurement, window-split decision with evidence, `AGENTS.md` tech-stack row if figures warrant |

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
- L8. T3 scope split (2026-10-20): the adapter-side bridge shipped fake-tested (commit C18); the REAL worker (263 conversion on the vendored code, condmdi-venv) moved into T5 because it is exactly the on-box engine work and its conventions need measured evidence, not speculation. Two redesigns during the task: (1) the user's checkpoint dir is .engine/condmdi_random_joints with model000750000.pt and args.json confirming abs_3d=true + keyframe_conditioned + random_joints - no Mean/Std files ship with it, so T5 must source HumanML3D's mean/std (dataset download, user-supplied like the weights); (2) core fill_gap_synthetically now IGNORES generated poses landing on keyed endpoints (keys win per S1) instead of rejecting them, so an anchored resample can be passed untrimmed. Wire contract pinned in tests: keys travel in DOMAIN form (quats + heights); every engine-native conversion is worker-side (M6 L6). Follow-up refactor noted: both adapters now carry ~120 lines of the same subprocess bridge; extract a shared worker-bridge module after T4/T5 once the second engine stabilizes.
- L9. Native review (2026-10-20): assess risk high (process_boundary) -> user consented (granted); first START exceeded the reviewer's context budget because the provider paired the base at d6f24571 (last acknowledgeed boundary, the whole M5+M6 surface), so the candidate was re-scoped to the maintained boundary e7960b2..ecfcbd8 (22 files / 2447 lines, lineage review-14a1a34f6c4791f1) and completed: both lenses (resilience, reliability) admitted, verdict approved with only non-blocking findings, acknowledgement burned (authority: burned; next reviewed boundary = ecfcbd8). Advisory findings recorded for T4/T5: engine stderr discarded (ready-path failures undiagnosable; same class as M5 R4-3), malformed lookup-ok replies surface as untyped errors (assert stripped under -O; bare ValueError from resampling), request-side wire contract not asserted by tests (fake consumes span_frames only), the hang/timeout path of the fill bridge is unproved, gaps at clip fps >= 40 can round one sample past the lock span (refuses a fillable gap; 24 fps default unaffected), the reply's frame numbering is trusted after sorting, and the model constant/_prespawn defaults (20 fps / 196) do not follow a configured engine's ready line.
- L10. T4 (2026-10-20): the GUI generation path exists. Wiring decisions: the controller rejects before the engine when no engine is configured, fewer than two keys are marked, or a fill is already running; a landing result is adopted only when its clip generation still matches (_inbetween_generation mirrors _extraction_generation), and adopting replaces the whole state and emits both timeline and pose changes so the viewport and the bar follow without new widget code. Honest scope note: the plan's 'viewport preview of the generated timeline' required no new adapter — current_pose() resolves any now-keyed frame, so scrubbing a filled timeline previews it everywhere the playhead goes. TimelineState.replace is not a method on the model; composition goes through dataclasses.replace (as _on_media_loaded already does). Follow-up: the two runner modules are now near-identical mirrors, as are the two adapter subprocess bridges — one shared worker-bridge/runner extraction after T5 once both engine's lifecycles have stabilized (parked in favor of minimal diffs now).
- L10b. T4 assess (2026-10-20): risk medium (executable_change), review_due=false (under_budget) — the boundary stays pending in the slice until a later commit reaches the budget or the user asks for review.
- L11. T5 conversion half (2026-10-21): the probe P3 failure after the decode/layout fixes had a structural root cause — `Skeleton.forward/inverse_kinematics` re-seed the accumulated chain rotation at the ROOT quat for every `kinematic_tree` chain (`paramUtil.t2m_kinematic_chain` = legs [0,1,4,7,10]/[0,2,5,8,11], spine [0,3,6,9,12,15], arms [9,13,16,18,20]/[9,14,17,19,21]), so an L/R collar (chain head child of joint 9) is local to the pelvis frame and its Maya parent Spine_3's quat NEVER multiplies in. Empirically: stored rot cols == cont6d(IK(dense)) bitwise (0 diff); official Skeleton FK on decoded locals reproduces dense AND recover_from_ric exactly (0.0 mm interior); per-joint divergence started at L_Collar (~1615 mm only on arm chains + a parent-frame offset rotation error for legs). Worker fix: `_MOTION_CHAINS` + Maya-local re-expression `qinv(acc[parent])⊗acc[joint]` in `_frame_to_wire` (only collars change; all other locals round trip raw); RED→GREEN in `tests/test_ai_condmdi_worker_wire.py`; probe P3 gates: chain decode vs recover_from_ric interior <1 mm / edge <20 mm, wire Maya threading quat gap ~2e-17. The probe stays in `.engine/` (untracked evidence, runs only on the engine venv). Suite 246/0/0/0 green (junitxml), ruff clean. Remaining T5: real-checkpoint bootstrap + VRAM/latency + window-split decision.
