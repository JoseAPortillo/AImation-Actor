# Feature: Integrate MIB In-Between Model (Motion In-Betweening via Two-stage Transformers)

## Objective
Replace AutoKeyframe as the optional generative backend in the Phase C wizard with a real Motion In-Betweening (MIB) model that naturally interpolates motion between authored golden poses, while keeping the existing fidelity gate and procedural fallback.

## Problem
AutoKeyframe is a keyframe generator, not an MIB model. The current pipeline only accepts its output when it stays within 40cm of the authored joints — and even when accepted, it does not produce natural motion through the authored poses. A real MIB model generates plausible in-between frames conditioned on start/target poses.

## Why
User selected the MIB strategy (decision session 2026-09-21): "vamos con la estrategia MIB". Chosen model: **Two-stage Transformers MIB** (`victorqin/motion_inbetweening`, TOG 2022, LAFAN1, MIT license, pre-trained weights in Releases).

## Scope
- Add a subprocess-bound MIB backend following the AutoKeyframe adapter pattern (torch stays out of core).
- Helper script (cache-local child process) that loads Context + Detail transformers and generates a transition between authored keyframes.
- Endpoint routing: try MIB backend → fidelity gate → fallback to procedural (existing behavior preserved).
- Config: new `motion_backend` value + MIB root/timeout settings.
- Tests: focused adapter tests + endpoint routing tests, following existing test_generate.py patterns.

## Constraints
- `domain/` stays pure (no torch/numpy there). `api/` never imports `infrastructure/` directly.
- No new hard dependency in core pyproject; model runtime lives in the cache-local venv (same as AutoKeyframe).
- LaFAN axis conventions already owned by `autokeyframe.py` (`_scene_to_model_coordinates`, `_model_to_scene_coordinates`) are the single boundary transform.
- Fidelity gate (40cm authored-keyframe check) stays as the safety net; MIB output must pass it to be accepted.
- The endpoint must keep responding with `backend: "procedural"` (plus sanitized `fallback_reason`) when the model is unavailable/malformed.

## Authorized scope
- Add `aimation_actor_core/infrastructure/ai_models/mib_backend.py` (or shared adapter module).
- Add `tools/mib_helper.py` (child process, mirrors autokeyframe_helper.py).
- Modify `aimation_actor_core/shared/config.py`, `aimation_actor_core/main.py`, `aimation_actor_core/api/routers/generate.py`.
- Add tests under `tests/api/test_generate.py` or `tests/infrastructure/test_mib_backend.py` as applicable.
- No changes to NeutralMotion schema, domain math, frontend, or DCC plugins.

## Acceptance criteria
- [ ] With the model cache present and `motion_backend=mib`, the generate endpoint returns `backend: "mib"` and a NeutralMotion whose frames pass `validate_invariants()`.
- [ ] MIB output honoring authored joints passes the fidelity gate; a pathological output fails it and falls back to procedural with sanitized reason.
- [ ] Without the model cache, the endpoint still returns procedural motion (no crash).
- [ ] All existing tests still pass; focused new tests cover axis conversion and routing.

## Tasks (stable IDs)

### T1 — Spike: verify MIB model assets and contract (DONE)
- [x] Inspect `tools/.cache/autokeyframe` assets and confirm what is already cached vs what MIB needs.
- [x] Clone/download `victorqin/motion_inbetweening` source + pre-trained zip (v1.0.0 release) into the cache dir (`tools/.cache/mib/`).
- [x] Identify the exact entrypoint/format: `train/context_model.py::evaluate` + `train/detail_model.py::evaluate` consume start-centered local positions `(1, W, 22, 3)` and rotations `(1, W, 22, 3, 3)`, plus attention mask and foot contact `(1, W, 4)`; emit `pos_new`/`rot_new` of the same shape. Window = `context_len + trans_len + 2` (post-process needs one extra frame after target).
- [x] Decide dataset dependency: **NOT required**. `get_train_stats(..., use_cache=True)` loads `train_stats_*.pkl` shipped inside the pretrained zip (`lafan1_context_model_release/`, `lafan1_detail_model_release/`). `mean`/`std` are (135,) per model. Full synthetic forward (context → detail, CPU, existing autokeyframe venv torch) completed: `SPIKE OK`.
- [x] Record the verdict and final integration design in this doc.

**T1 verdict / integration design**
- Assets cached at: `tools/.cache/mib/source` + `tools/.cache/mib/pretrained/{lafan1_context_model_release,lafan1_detail_model_release}` (checkpoint_*.pth + train_stats_*.pkl).
- Reuse the existing autokeyframe venv Python (`tools/.cache/autokeyframe/venv/Scripts/python.exe`) — it already has the torch version the release checkpoints load under (verified in spike).
- Scale: model stats live in cm-like LaFAN units (root std ≈ 64/28/34), consistent with `l_position.npy` and the existing scene↔raw-LaFAN adapter boundary.
- Two-stage flow per transition: `ctx_mdl.evaluate(context_model, ...)` first, then `det_mdl.evaluate(detail_model, context_model, ..., foot_contact, ...)` which internally reuses the context output.
- Conditioning puzzle (documented in T2): COCO 2D → authored ext-joint global positions (raw LaFAN cm) → local positions via `_PARENTS`/offsets and local rotations via per-frame look-at along parent→child bones. mid-transition frames between authored keyframes are placeholders (identity rotations) and the model fills them; authored target frames stay as constraints.
  - **REVISED (E2E finding):** look-at rotations are replaced by the "deformed-offset" representation. `get_model_input` feeds the models only root position + local rotations (6D); non-root local positions never enter the model. Setting `R_local = I` and `lpos_j = pose[j] - pose[parent]` (parent-frame deltas) makes the LaFAN FK (`gp_j = gp_parent + gr_parent @ lpos_j`) reproduce each authored pose with 0.00 cm error — verified end-to-end. The look-at approach reconstructed non-rigid torsos ~70 cm off and failed the fidelity gate; this representation is simpler and exact.
- Output contract mirrors the AutoKeyframe helper: `{keyframes: [...], global_positions: [[22×3], ...]}`, one entry per window transition frame (including the authored target frames), so the 40cm fidelity gate (`_validate_authored_fidelity`) works unchanged if we return the target indices.

### T2 — Helper: cache-local MIB child process
- [x] Write `tools/mib_helper.py` mirroring `tools/autokeyframe_helper.py`: reads bounded JSON from stdin, loads Context+Detail transformers, generates a transition, prints bounded JSON.
- [x] Implement axis conversions using the proven LaFAN conventions (scene <-> raw LaFAN).
- [x] Validate the helper alone with a small fixture (a couple of authored keyframes) before wiring the backend.
- Note: `_uncenter_global_positions` must undo `to_start_centered_data` exactly (root_pos_offset applies only to X/Z — `pos[..., ::2] -= offset` — and the root yaw is undone with `root_rot_offset.transpose()`).

### T3 — Backend adapter + config
- [x] Add the MIB backend class implementing the `MotionBackend` protocol (same shape as `AutoKeyframeBackend`): resolve cache root, bounded payload, subprocess run, fidelity gate, motion assembly.
- [x] Add config `motion_backend: "mib"` + `mib_root` + `mib_timeout_seconds`.
- [x] Wire `main.py` composition root to instantiate MIB backend.
- [x] Update `generate.py` routing to use the MIB backend when configured (keep AutoKeyframe value for backward compat or deprecate cleanly): `response["backend"] = getattr(backend, "name", "autokeyframe")` so test stubs without `name` stay valid; `MibBackend.name = "mib"`.

### T4 — Tests + verification
- [x] Add focused tests: axis round-trip, conditioning normalization bounds, fidelity gate on MIB-shaped output, endpoint routing with fake backend.
- [x] Run pytest (focus: tests/api/test_generate.py + new module), Ruff, and import-linter to confirm no layer violation.
- [x] Bring up the backend and hit the endpoint with MIB configured to confirm end-to-end: status 200, `backend: "mib"`, `source_type: "mib"`, 76 frames, no `fallback_reason`; authored fidelity 0.00 cm through the 40 cm gate (E2E script `mib_e2e.py`).
- [x] Commit each work unit with Conventional Commits; record commit identities here: `575d662` (helper + doc + AGENTS.md + .gitignore), `0a552fb` (adapter + config + wiring + tests). Both on `feat/golden-poses-timeslider`.

### T5 — Fix deformed in-between preview (root cause: rest-pose placeholders) (DONE)
- [x] Diagnose: the frontend preview kept the first authored pose but deformed/stretched the in-between skeleton. Root cause confirmed in `motion_inbetween/train/utils.py`:
  - `get_new_positions(positions, y, indices, seq_slice)` clones the input `positions` and overwrites **only joint 0 (root)** inside `seq_slice`; non-root joints of in-between frames come verbatim from the input window.
  - `_build_window` used to fill those non-root joints with the LaFAN **rest pose** (`np.repeat(l_position)`) — so the in-between FK (`gp_j = gp_parent + gr_parent @ lpos_j`) rendered the raw LaFAN T-pose geometry (head displaced down, skeleton stretched/scaled) instead of the authored pose, while context/target frames rendered exactly because `get_new_positions`/`get_new_rotations` leave them untouched.
  - MIB only predicts rotations + root position (state = 132 rot + 3 root); all non-root geometry comes from the input local positions.
- [x] Fix in `_build_window`: fill the in-between frames with **linearly interpolated local deltas A→B for ALL 22 joints** (root included, same formula), keeping the deformed-offset representation for context/target (fidelity gate unchanged).
- [x] Verify: authored fidelity still 0.00 cm through the gate; in-between frames now follow the linear global interpolation A→B with max deviation ≤ 7.2 cm (head stable, no rest-pose artifacts); E2E via API still 200 / `backend: "mib"` / 76 frames / no fallback. No server restart needed (helper runs as a fresh child process per request).
- [x] Commit: fix in `tools/mib_helper.py` + this doc.

## Verification evidence
- [x] T1 verdict recorded with asset paths and exact model input/output contract.
- [x] Per-task outcomes and commit hashes recorded as each task closes.

## Progress
- T1: done (spike passed: checkpoints+stats load from zip, CPU forward works, no LAFAN1 dataset)
- T2: done (`tools/mib_helper.py`; validated with real checkpoints — 70 frames emitted, authored preserved at 0.00/1.14/2.28 cm vs 40 cm tolerance; orchestrator re-ran the validator independently; simplified to deformed-offset conditioning after the E2E finding)
- T3: done (`aimation_actor_core/infrastructure/ai_models/mib_backend.py`, config `mib` values, `main.py` branch, `generate.py` getattr routing)
- T4: done (5 focused tests in `tests/infrastructure/test_mib_backend.py`; E2E real chain OK: backend=mib, no fallback, 0.00 cm fidelity; ruff clean on MIB files)
- T5: done (root cause: rest-pose placeholders in in-between frames overwritten by `get_new_positions`; fixed by interpolating all 22 joints A→B; gate still 0.00 cm; in-betweens ≤7.2 cm from linear interpolation; E2E still OK; running server picks the fix without restart)
- Environmental (pre-existing, not caused): `PermissionError` tmp_path pytest-asyncio, `test_pinned_rest_offsets` (-8.0 != 0.0), mypy `main.py:131` import-untyped.

## Next step
Have the user generate once more from the frontend to confirm the in-between frames now look like their motion (no skeleton deformation). Optional follow-up: feed the model more realistic local rotations (per-bone look-at) in context/target frames so the predicted in-between rotations carry more "action"; keep the deformed offsets for the exact fidelity gate.