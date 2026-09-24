# Feature: 3D sequence preview in the golden-poses step (wizard)

## Objective
In the wizard step where the user marks golden poses (Step 2), add a dependency-free orthographic 3D viewport showing ALL marked poses as a playable, orbitable motion, so the animator can inspect the sequence from every angle BEFORE launching motion generation.

## Problem
Step 2 (`WizardStep2Poses`) renders only the 2D video frame + COCO skeleton overlay. Marked pins carry only 2D keypoints (x, y, confidence) — there is no z at that point, so the marked "motion" cannot be inspected spatially. The user must launch generation to see anything moving.

## Why
User request (decision session 2026-09-21): see the movement of the marked poses in 3D, from all angles, before computing the animation. Chosen options: full sequence mode (play/scrub over all marked poses) + hand-rolled orthographic canvas renderer (no new dependencies).

## Scope
- Backend: deterministic 3D lift endpoint reusing the existing heuristic lifting backend (no new model, no ONNX).
- Frontend: pure 3D projection module + canvas sequence viewer + wizard integration.
- Depth is a deterministic heuristic preview (normalized z in [0,1]); NOT a real 3D reconstruction (that needs the ONNX lifting model — out of scope).

## Constraints
- `api/` must never import `infrastructure/` directly; injection goes through `api/deps.py` (pattern: `get_pose_detector`).
- `domain/` stays pure; no changes to domain lifting heuristics.
- No new frontend dependencies (no three.js); keep pure-function + canvas pattern (`renderFrame`, `drawSkeleton`).
- Frontend calls the backend via `ApiClient`; `frontend/src/core/pose3d.ts` stays pure and unit-testable (no DOM).
- Layer rules from AGENTS.md: Conventional Commits, no AI attribution, work-unit commits, tests mirrored in `tests/` / `frontend/src/**/*.test.*`.

## Authorized scope
- `aimation_actor_core/api/routers/pose.py` (add POST /pose/lift)
- `aimation_actor_core/api/deps.py` (get_lifting_backend)
- `aimation_actor_core/main.py` (composition root wiring)
- `tests/api/test_pose.py` (new)
- frontend: `api/types.ts`, `api/ApiClient.ts`, `core/pose3d.ts` (new), `core/pose3d.test.ts` (new), `components/pose3d/PoseSequence3D.tsx` (new), `components/pose3d/PoseSequence3D.test.tsx` (new), `components/wizard/steps/WizardStep2Poses.tsx`
- No changes to generate.py behavior, NeutralMotion schema, domain math, DCC plugins.

## Acceptance criteria
- [ ] `POST /pose/lift` accepts `{frames: [[{label,x,y,confidence}]]}` and returns `{frames: [[{label,x,y,z,confidence}]]}` with deterministic z in [0,1], same order/shape; empty input frames safe.
- [ ] `ApiClient.liftPose3D` posts the bulk frames and parses the 3D response.
- [ ] `core/pose3d.ts`: stable scene bounds across the full sequence, orthographic projection (yaw/pitch), linear preview interpolation between consecutive poses, COCO bones reused.
- [ ] `PoseSequence3D` renders marked poses on canvas with per-pose progressive color, ground grid, depth cue, drag-to-orbit (yaw/pitch clamped), reset view, play/pause + scrub; empty state when no poses.
- [ ] Step 2 gains a collapsible "Vista 3D de las poses" panel fed by successful pins (single bulk lift POST when ≥1 pose).
- [ ] Backend: pytest (new module + tests/api), ruff clean on touched files, mypy strict on touched files, import-linter contracts kept.
- [ ] Frontend: vitest (new core + component tests green), `npm run build` (tsc -b) clean.
- [ ] Full suites green (pytest repo-wide, vitest repo-wide) before close.

## Tasks (stable IDs)

### T1 — Backend: POST /pose/lift (bulk 2D→3D lift)
- [ ] Add `LiftPose3DRequest`/keypoint pydantic models + `POST /lift` in `aimation_actor_core/api/routers/pose.py` reusing `HeuristicLiftingBackend`.
- [ ] Add `get_lifting_backend` dep in `api/deps.py`; wire `app.state.lifting_backend` in `main.py` (pattern of `pose_detector`).
- [ ] New `tests/api/test_pose.py`: deterministic z, z range, empty frame list/inner frame, shape/order preserved.
- [ ] Run pytest (new module + tests/api), ruff, mypy (touched files), import-linter.

### T2 — Frontend API + types
- [ ] `DetectedKeypoint3D {label,x,y,z,confidence}` + lift response type in `api/types.ts`.
- [ ] `ApiClient.liftPose3D(frames)` → `POST /pose/lift`; parse bulk response.

### T3 — Frontend core 3D math (pure)
- [ ] `frontend/src/core/pose3d.ts`: `sceneBounds`, `projectOrthographic(points, yaw, pitch, w, h)`, `interpolatePoses(a, b, t)`, bones from `core/skeletonOverlay.ts` COCO_BONES.
- [ ] `core/pose3d.test.ts`: bounds math, projection sanity (yaw/pitch extremes), interpolation endpoints/clamp.

### T4 — PoseSequence3D component
- [ ] `frontend/src/components/pose3d/PoseSequence3D.tsx`: canvas renderer (progressive pose colors, grid, depth cue), drag orbit with pitch clamp, reset view, play/pause + scrub, frame label, empty state.
- [ ] `PoseSequence3D.test.tsx` (controls, not pixels — MotionViewer.test.tsx pattern).

### T5 — Wizard integration
- [ ] `WizardStep2Poses.tsx`: collapsible "Vista 3D de las poses" panel fed by successful pins; lift via `ApiClient.liftPose3D` on open (or when pins change ≥1) and render `PoseSequence3D`.

### T6 — Verification + delivery
- [ ] Full backend suite + ruff + mypy + import-linter; full frontend vitest; `npm run build`.
- [ ] Work-unit commits with Conventional Commits; record identities here.

## Verification evidence
- [ ] T1: pytest/ruff/mypy/import-linter results recorded.
- [ ] T3/T4: vitest results recorded.
- [ ] T6: full suites + build results recorded; commit hashes recorded.

## Progress
- Pending: branch `feature/pose3d-preview` (from `fix/ci-red`, which carries the CI-green fixes 2f36f6e + 1f6f274).

## Next step
- T1 backend delegate → verify → commit; then T2–T5 frontend delegate(s); then T6.