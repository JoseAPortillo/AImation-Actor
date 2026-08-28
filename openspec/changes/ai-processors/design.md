# Design: Real AI Processors — Video Preprocessing (ai-processors)

## Technical Approach

Add the first genuine AI-pipeline stage: `FrameExtractorNode` (type `video-source`, category `SOURCE`), a real OpenCV node conforming to the existing `INode` protocol. It decodes a video file into a list of frames and reports FPS, registered statically alongside the three seed nodes and driven by the unchanged `SynchronousGraphExecutor`. CPU-only; `opencv-python-headless` + `numpy` land in the `ai` optional group.

## Architecture Decisions

| Decision | Option | Tradeoff | Choice |
|---|---|---|---|
| `video_path`: port vs param | Input port | No input-value channel exists on `GraphNode`; executor feeds inputs only via edges | **Param** (required) |
| FPS exposure | output port vs metadata | separate port is edge-consumable + typeable | **`fps` output port (`NUMBER`)** |
| Path validation location | `validate()` vs `execute()` | executor never calls `validate()`; security must not rely on it | **`execute()` (with `validate()` as defense-in-depth)** |
| Offload | `asyncio.to_thread` (D1) vs bare `cv2` | bare read blocks the loop harness in `stores.py` `asyncio.run` | **`asyncio.to_thread`** |

### Decision: `video_path` is a PARAM, not an input port

**Choice**: required param `video_path` (`DataType.VIDEO_PATH`).
**Alternatives**: input port (per the spec's first wording).
**Rationale**: `GraphNode` (`domain/pipeline/graph.py`) exposes only `{id, type, params}` — there is no graph-level channel to inject an input-port *value* without a feeding edge. The executor (`virtual/executor.py:84`) resolves `inputs` solely from edges, so a SOURCE node's seed value cannot arrive as an input. The SOURCE precedent (`FrameRangeNode`) carries params with zero inputs. This deviates from the video-preprocessing spec's "input port `video_path`" sentence — **the spec delta must be corrected to "param" in tasks/archive**.

### Decision: FPS as a dedicated output port

**Choice**: two outputs — `frames` (`DataType.FRAMES`, `list[np.ndarray]` BGR uint8) and `fps` (`DataType.NUMBER`, float).
**Alternatives**: embed fps inside the FRAMES value (rejected — FRAMES is an opaque frame list; a scalar can't live there cleanly).
**Rationale**: an edge-consumable, typed port lets downstream nodes read fps; `fps = cap.get(cv2.CAP_PROP_FPS)`.

## Data Flow

```
POST /jobs/graph/execute
  → InMemoryJobStore.submit(GRAPH_EXECUTE)
    → asyncio.run(executor.run(graph, registry))
      → video-source.execute(inputs={}, params={video_path,start,end,resize}, ctx)
         1. resolve/validate path under media_root (reject BEFORE any read)
         2. await asyncio.to_thread(_decode_blocking, path, start, end, resize)
              cv2.VideoCapture(path) → fps → read [start:end] → resize → frames
         3. NodeOutput(values={"frames": [...], "fps": fps})
      → job.result.outputs[<node>] = {frames, fps}
```

`_decode_blocking` is a plain sync function; `execute` stays an async coroutine that releases the loop across the decode. The executor's `asyncio.wait_for` timeout still bounds the whole `execute`.

## Path Allowlist (SDD §4.3)

- `Settings` gains `media_root: Path` (default `Path("media")`); DI passes `settings.media_root` into `seeded_node_registry(media_root=...)`.
- Resolution in the node: `candidate = (media_root / video_path).resolve()`, `root = media_root.resolve()`.
- Reject (raise before `cv2.VideoCapture`) if: `video_path` absolute, or `not candidate.is_relative_to(root)` (catches `..` escapes), or `not candidate.exists()`, or `candidate.is_file()` is False.
- No shell/exec; `video_path` treated strictly as a path string.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `aimation_actor_core/infrastructure/video/frame_extractor.py` | Create | `FrameExtractorNode` (schema, validate, execute + `_decode_blocking`) |
| `aimation_actor_core/infrastructure/virtual/node_registry.py` | Modify | import + register `video-source` in `seeded_node_registry()` |
| `aimation_actor_core/infrastructure/virtual/__init__.py` | Modify | re-export `FrameExtractorNode` |
| `aimation_actor_core/main.py` | Modify | `/health` adds `"video": "loaded"`; pass `media_root` |
| `aimation_actor_core/shared/config.py` | Modify | add `media_root: Path` setting |
| `pyproject.toml` | Modify | `[project.optional-dependencies] ai` = `opencv-python-headless`, `numpy` |

## Interfaces / Contracts

```python
class FrameExtractorNode(INode):
    def __init__(self, media_root: Path = Path("media")) -> None: ...
    @staticmethod
    def get_schema() -> NodeSchema:
        return NodeSchema(
            type="video-source",
            category=NodeCategory.SOURCE,
            title="Frame Extractor",
            description="Decodes a video file into frames (OpenCV).",
            inputs=[],
            outputs=[
                PortSpec(name="frames", data_type=DataType.FRAMES),
                PortSpec(name="fps", data_type=DataType.NUMBER),
            ],
            params=[
                PortSpec(name="video_path", data_type=DataType.VIDEO_PATH, required=True),
                PortSpec(name="start", data_type=DataType.NUMBER, default=0),
                PortSpec(name="end", data_type=DataType.NUMBER, default=None),
                PortSpec(name="resize", data_type=DataType.NUMBER, default=None),
            ],
        )

    async def execute(self, inputs, params, context) -> NodeOutput: ...
    async def validate(self, params) -> ValidationResult: ...
```

Layer rules (import-linter): OpenCV/numpy import lives in `infrastructure/video/frame_extractor.py`; `domain` sees only `DataType`/`NodeCategory` strings; `api` imports neither. All contracts in `pyproject.toml` hold.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | schema type/category/ports; param `validate()` | `tests/infrastructure/test_frame_extractor.py` |
| Unit | path allowlist (abs, `..`, missing, ok) | parametrized `tmp_path` cases |
| Unit | decode: frame count + fps + slice + resize | synthetic video via `cv2.VideoWriter` in `tmp_path` fixture (MJPG `.avi`) |
| Integration | `video-source` in graph-execute yields `frames`+`fps` | executor run, assert outputs |
| Integration | `/health` `video: loaded`; `/nodes/types` lists 4 types | extend `tests/api/test_api.py` |
| RED | disallowed path → no `VideoCapture` open (monkeypatch) | assert rejected before read |

Note: `frames` (numpy arrays) are in-memory `NodeOutput.values`; JSON serialization of pixel payload is deferred — e2e asserts `fps` + `len(frames)`, not raw pixels.

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary. The arbitrary-file-read boundary is covered by the Path Allowlist requirement above (carried unchanged into tasks with RED tests).

## Migration / Rollout

No migration. Rollback = revert branch commits (proposal's plan). Feature has no data to migrate.

## Open Questions

- [x] Q1 resolved: `video_path` is a **param** — spec delta ("input port") must be corrected in archive.
- [x] Q2 resolved: `fps` is a dedicated output port; FRAMES = `list[np.ndarray]`.
- [x] Q3 resolved: path validation in `execute()` (executor never calls `validate()`).
- [x] Q4 resolved: `asyncio.to_thread` wraps a sync `_decode_blocking`.
- [ ] Whether to commit a binary fixture vs generate at test time — leaning generate-at-test-time (reproducible, no binary in VCS).
