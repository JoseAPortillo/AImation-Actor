# Tasks: Real AI Processors — Video Preprocessing (ai-processors)

> TDD throughout: each phase opens with a RED test, then GREEN production. Test runner: `.\.venv\Scripts\python.exe -m pytest`.

## Phase 1 — Config & Media Root (1 task)

### 1.1 Configure media_root and register video-source
- [ ] `shared/config.py`: add `media_root: Path = Path("media")` setting.
- [ ] `infrastructure/virtual/node_registry.py`: `seeded_node_registry(media_root: Path = ...)` registers the new `video-source` node; `infrastructure/virtual/__init__.py` re-exports `FrameExtractorNode`.
- [ ] `main.py`: pass `settings.media_root` into `seeded_node_registry(...)`; `/health` adds `"video": "loaded"`.
- [ ] `pyproject.toml`: `[project.optional-dependencies] ai = ["opencv-python-headless", "numpy"]`.
- Tests: `/health` reports `video: loaded`; `/nodes/types` lists `video-source` (4 types). RED first.

## Phase 2 — FrameExtractorNode (1 task)

### 2.1 Implement FrameExtractorNode (deps)
- [ ] `infrastructure/video/frame_extractor.py`: `FrameExtractorNode(INode)`.
  - Schema: type `video-source`, category `SOURCE`; outputs `frames` (FRAMES) + `fps` (NUMBER); params `video_path` (VIDEO_PATH, required), `start`/`end`/`resize` (NUMBER, optional).
  - `execute()`: resolve/validate `video_path` under `media_root` (reject BEFORE `cv2.VideoCapture`), then `await asyncio.to_thread(self._decode_blocking, ...)`.
  - `_decode_blocking()`: `cv2.VideoCapture`, FPS detection (`cap.get(cv2.CAP_PROP_FPS)`), slice `[start:end]`, resize, return `frames, fps`.
  - `validate()`: defense-in-depth param validation (video_path non-empty).
- Tests: `tests/infrastructure/test_frame_extractor.py` — schema/type/ports/params; param `validate()`. RED first, then GREEN.

## Phase 3 — Security: Path Allowlist (1 task)

### 3.1 Path allowlist enforcement (SDD §4.3)
- [ ] In `execute()`: reject if `video_path` absolute, or `not candidate.is_relative_to(media_root.resolve())` (catches `..`), or `not candidate.exists()`, or `candidate.is_file()` is False. Raise before any `cv2.VideoCapture` open. No shell/exec; strict path-string handling.
- Tests: parametrized `tmp_path` cases — allowed path decodes; absolute/`..`/missing/non-file rejected before read (monkeypatch `cv2.VideoCapture` to assert not opened). RED first.

## Phase 4 — Integrate into executor graph (1 task)

### 4.1 Automate graph execution end-to-end
- [ ] Integration test: build a graph with `video-source` (param `video_path` + `start`/`end`), run through `SynchronousGraphExecutor`, assert output `fps` + `len(frames)` (assert FPS and frame count, not raw pixel payload — frames are np.ndarray, not JSON-serializable).
- [ ] Requires a synthetic video fixture generative at test time via `cv2.VideoWriter` (MJPG `.avi`) in `tmp_path`; do NOT commit a binary.
- Tests: `tests/infrastructure/test_frame_extractor.py` + `tests/api/test_api.py` additions. RED first, then GREEN.

## Quality gates (run after each phase)
- [ ] `.\.venv\Scripts\python.exe -m pytest` (full suite stays green)
- [ ] `.\.venv\Scripts\python.exe -m mypy aimation_actor_core`
- [ ] `.\.venv\Scripts\python.exe -m ruff check .` + `ruff format --check`
- [ ] `.\.venv\Scripts\lint-imports.exe` (4 kept, 0 broken; domain pure, api↛infrastructure)

## Non-goals (this change)
- No pose estimation (2D/3D), no SMPL, no cleanup/IK, no GPU, no model download/caching.
- No executor/job-lifecycle/graph-model change. No MediaPipe (D2: pose stays torch/ONNX, recorded for a later slice).

---

## Review Workload Forecast

- Estimated changed lines: ~260–340 additions (node ~90, config ~10, registry ~15, main ~5, pyproject ~2, tests ~180).
- 300-line budget risk: **Medium** — near the 300-line budget; test-heavy (synthetic video fixture + path allowlist parametrized cases dominate).
- Chained PRs recommended: **No** — single focused work unit (ONE slice, video preprocessing only, no executor change).
- Delivery strategy: ask-on-risk → single PR acceptable if ≤ 300; if it crosses, a small size:exception or minor test trimming.
- Decision needed before apply: **No** (unlikely to exceed budget materially; if it does, we confirm a small size:exception).

```
Decision needed before apply: No (conditional on ~300-line estimate)
Chained PRs recommended: No (single work unit)
400-line budget risk: Low-Medium
```
