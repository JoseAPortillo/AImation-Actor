# Verification Report: Real AI Processors — Video Preprocessing (ai-processors)

**Phase**: verify (inline — no subagents, interactive session)
**Status**: ✅ PASS

## Evidence

- Test suite: `84 passed` (`.\.venv\Scripts\python.exe -m pytest tests/ -q`)
- Static typing: `mypy` — Success: no issues in 40 source files
- Lint: `ruff check` — All checks passed; `ruff format --check` — 76 files formatted
- Layer contracts: `lint-imports.exe` — 4 kept, 0 broken (domain pure, api↛infrastructure)

## Requirement coverage (spec: video-preprocessing)

| Requirement | Verdict | Evidence |
|---|---|---|
| Frame extraction node contract (schema) | ✅ | `TestSchema.test_catalog_schema` — type video-source, SOURCE, video_path param VIDEO_PATH, outputs frames/fps |
| Params govern decode window and scale | ✅ | `TestDecode.test_decode_reports_fps_frame_count_slice_and_resize` — [1,5)→4 frames, resize→16x16 |
| FPS detection | ✅ | `fps=cap.get(cv2.CAP_PROP_FPS)`; fps≈25 in unit + e2e |
| Non-blocking decode offload (D1) | ✅ | `await asyncio.to_thread(_decode_blocking, ...)` |
| Source path validation | ✅ | `TestPathAllowlist` — abs/.. traversal/missing/non-file rejected; `test_reject_happens_before_videocapture` (monkeypatch no read) |
| No external code execution | ✅ | no shell/exec; static registration; strict path-string handling |

## Requirement coverage (delta: node-registry)

| Requirement | Verdict | Evidence |
|---|---|---|
| Seed nodes = 4 (incl. video-source) | ✅ | `test_seeded_registry_lists_three_seed_nodes` + `TestNodes.test_list_node_types_lists_seed_nodes` assert 4 types |
| Seed nodes declare typed ports | ✅ | `TestSchema.test_catalog_schema` + existing pinned port-type tests |

## Design conformance

- `video_path` is a **param** (not input port) — spec corrected to match; schema `params[0].name == "video_path"`, `required is True`.
- `fps` as dedicated **output port** (NUMBER) — present in `schema.outputs`.
- Path validation in `execute()` (executor never calls `validate()`); `validate()` kept as defense-in-depth.
- `asyncio.to_thread` offload (D1) confirmed.
- media_root wiring: `Settings.media_root` → `seeded_node_registry(media_root=...)` → FrameExtractorNode; `/health` reports `video: loaded`.

## Deviations from design (all deliberate, gatekeeper-approved)

1. **Job-store JSON serialization fix (design defect)**: `NodeOutput` carries `numpy.ndarray` frames; `stores.py` `_submit_graph` previously stored raw outputs → `PydanticSerializationError` on response. Fixed with `_json_safe`/`_coerce` flattening in `stores.py` (infrastructure). Without this, `/jobs/graph/execute` with `video-source` fails. Design said "e2e asserts fps+len not pixels" but did not handle store serialization — resolved.
2. **Python-version config sync (environment)**: venv is Python 3.14 + numpy 2.5.2 (cp314); `pyproject.toml` mypy/ruff pointed at 3.11. Now numpy is imported, mypy default parses the numpy stub (3.12+ `type` syntax) and fails under 3.11. Synced mypy `python_version` → 3.14 and ruff `target-version` → py314 (user-approved). Gates now run without manual flag.

## Acceptance

- Integration e2e verified via `/jobs/graph/execute` with `video-source`: `status succeeded`, `len(frames)==5`, `fps≈25`.
- No CRITICAL or WARNING findings. 0 open blockers.

## Artifacts

- Change: `openspec/changes/ai-processors/`
- Impl: `aimation_actor_core/infrastructure/video/frame_extractor.py`, `.../virtual/{node_registry,stores,__init__}.py`, `shared/config.py`, `main.py`, `pyproject.toml`
- Tests: `tests/infrastructure/test_frame_extractor.py`, `tests/api/test_api.py`

**Next recommended**: archive
