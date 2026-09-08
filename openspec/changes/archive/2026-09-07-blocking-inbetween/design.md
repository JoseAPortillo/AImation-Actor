# Design: Blocking → In-betweening (`blocking-inbetween`)

## Technical Approach

Deliver the animator-facing "blocking → in-betweening" flow (§20.5 / v0.4) end-to-end: a lightweight DCC-friendly blocking payload (D1b) is modeled + validated in pure domain, converted to a sparse `NeutralMotion` with populated `keyposes` by a domain converter, emitted by a new `SOURCE` `BlockingInput` node (reusing `NEUTRAL_ANIMATION`, **no new DataType**), and consumed by the existing `inbetween-generation` enrichment node extended with a `preserve_keyposes` param that locks key pose values/timing exact in `_resample` and remaps keypose frame indices post-upsample (D2a). The path is a two-node graph `blocking-input → inbetween-generation` run through the in-request executor (ADR-002) — **no background worker**; the `blocking-to-motion` endpoint stays a documented stub routed via graph (spec leaves the choice to design; graph is chosen because `useJobStore`/presets already drive graph-execute and no new transport is needed). MVP scope per D3: converter, exact-lock (`weight∈[0.99,1.0]`), remap, node registration, preset, threat model, tests. Foot-lock/contacts, partial weights, DCC capture, MotionEnhancer, worker deferred.

## Architecture Decisions

| Decision | Options | Tradeoff | Decision |
|---|---|---|---|
| D1 Payload shape | `neutral_animation` passthrough vs minimal `{skeleton?, keyposes:[{frame,pose,weight}]}` (D1b) | Full doc forces DCC to build skeleton+meta; minimal payload is DCC-friendly but needs a converter | **Minimal payload → domain converter (D1b)** |
| D2 `_resample` integration | extend existing `inbetween-generation` (D2a) vs new dedicated node (D2b) | Math is identical; only the lock rule differs → clean param/path in `_resample` | **Extend existing node (D2a)** |
| D3 Payload param carrier | node `param` dict vs new input port | SOURCE nodes have empty `inputs` (`video-source`); `GraphNode.params` already carries payload | **`params["blocking"]` on the node** |
| D4 Exact-lock semantics | value+timing hard-lock for `weight∈[0.99,1.0]` vs blend weight<1 | Exact-lock is the MVP contract (D3); partial weights deferred | **weight∈[0.99,1.0] → exact**; below → pass through interpolation |
| D5 Lock placement | inside `_resample` only vs post-pass after `enrich_motion` | Downstream tangent-smooth/rotation-filter (post-resample) can distort locked values; locking must outrank them | **Locked frames re-applied after full `enrich_motion` chain** |
| D6 Off-grid key snap | nearest in-grid output frame vs floor | Spec REQ-07 SC-05 mandates nearest | **Nearest in-grid frame (deterministic)** |
| D7 Endpoint | make `blocking-to-motion` real vs document graph route | Real endpoint duplicates graph-execute and needs its own payload path; graph already flows `neutral_animation` | **Document graph route; keep endpoint stub + add graph e2e test** |
| D8 Degenerate safety | `_resample` total (no div/0) vs guard at adapter | Spec REQ-07 mandates total `_resample` | **Total in-domain; adapter maps errors to `ValueError`** |
| D9 Keypose remap | remap within `_resample` vs in `enrich_motion` | Remap must track final output grid; do it where frames grid is finalized | **In `enrich_motion` after `_resample`** |

## Data Flow

```
BlockingInput payload (DCC / preset)  —  {skeleton?, keyposes:[{frame, pose, weight}]}
   │  Pydantic BlockingInput (frozen, extra="forbid", bounded)  [domain]
   ▼
blocking_to_neutral_motion(payload)  —  sparse Frames + keyposes + default skeleton (24fps)
   │  validate_invariants(); reject dup/out-of-duration frames   [domain]
   ▼
BlockingInputNode  —  SOURCE, output motion:NEUTRAL_ANIMATION    [infra adapter]
   │  params["blocking"] validated → converter → to_thread
   ▼
inbetween-generation  —  ENRICHMENT, preserve_keyposes bool      [infra adapter]
   │
   ▼  enrich_motion(motion, InbetweenParams(preserve_keyposes=True))
  _resample  → upsample grid; key-lock exact at locked positions   [domain]
  _apply_rotation_filter → tangent_smoothing (skip locked frames)  [domain]
  _remap_keyposes  → keyposes[i].frame = nearest in-grid out frame  [domain]
  validate_invariants()                                          [domain]
   ▼
motion (NEUTRAL_ANIMATION) — keyposes preserved + remapped
```

## File Changes

| File | Action | Description |
|---|---|---|
| `domain/animation/blocking_input.py` | Create | `BlockingInput`/`BlockingKeyPose` models + `blocking_to_neutral_motion` converter + bounded validation (REQ-01/02/04) |
| `domain/animation/inbetween.py` | Modify | `InbetweenParams.preserve_keyposes`; key-lock in `_resample`; `_remap_keyposes`; locked-frame guards on smooth/filter; degenerate safety |
| `domain/animation/__init__.py` | Modify | Re-export blocking API |
| `infrastructure/ai_models/blocking_input.py` | Create | `BlockingInputNode` (SOURCE, `motion:NEUTRAL_ANIMATION`, `params["blocking"]` → converter → `to_thread`) |
| `infrastructure/ai_models/inbetween_generation.py` | Modify | `preserve_keyposes` param in `get_schema`, `validate`, `execute` |
| `infrastructure/ai_models/__init__.py` | Modify | Re-export `BlockingInputNode` |
| `infrastructure/virtual/node_registry.py` | Modify | 11th seed `blocking-input` |
| `tests/api/test_api.py` | Modify | seed allowlist 10→11 |
| `domain/animation/neutral_motion.py` | Modify (minimal) | `validate_invariants` keypose-duration bounds (spec probe) — see Risks |
| `frontend/src/api/types.ts` | Modify | `KeyPose` typed; `keyposes?: KeyPose[]` |
| `frontend/src/core/presets.ts` | Modify | "Blocking to Motion" preset |
| `frontend/src/test/fixtures/nodeCatalog.json` | Modify | Golden append `blocking-input` (contract-tested) |
| `docs/SDD threats / SDD §4.2` | Modify | Blocking-input threat row (D4) |

`MotionViewer`, `SimpleMode`, `handles.ts`, `Palette.tsx`: **unchanged** — `SOURCE` and `neutral_animation` already present.

## Interfaces / Contracts

```python
# domain/animation/blocking_input.py — pure stdlib + Pydantic
DEFAULT_BLOCKING_FPS: float = 24.0
MAX_KEYPOSES: int = 1000            # D4 bound (unbounded-resample prevention)

class BlockingKeyPose(BaseModel):   # frozen, extra="forbid"
    frame: int = Field(ge=1)
    pose: dict[str, Transform3D]    # full per-bone set for the resolved skeleton
    weight: float = Field(default=1.0, ge=0.0, le=1.0)

class BlockingInput(BaseModel):     # frozen, extra="forbid"
    skeleton: Skeleton | None = None
    keyposes: list[BlockingKeyPose] = Field(min_length=1, max_length=MAX_KEYPOSES)
    # model_validator: every keypose.pose addresses exactly the resolved
    #   skeleton bone set; quats unit-norm (tol 1e-3) & non-zero; no NaN/Inf
    def resolved_skeleton(self) -> Skeleton: ...   # default if omitted

EXACT_LOCK_MIN: float = 0.99        # weight band for exact-lock (D4)

def blocking_to_neutral_motion(input_: BlockingInput) -> NeutralMotion
    # sparse frames (strictly increasing, dup rejected), keyposes populated,
    # meta.fps=DEFAULT_BLOCKING_FPS, duration_frames=max(frame),
    # skeleton default if omitted; validate_invariants(); keypose frame
    #   within duration_frames enforced.

# domain/animation/inbetween.py — stdlib only
@dataclass(frozen=True)
class InbetweenParams:
    # ... existing fields ...
    preserve_keyposes: bool = DEFAULT_PRESERVE_KEYPOSES   # default False

def _resample(motion, target_fps, method, easing, preserve_keyposes=False) -> NeutralMotion
    # upsample as today; then, when preserve_keyposes, for each keypose with
    #   weight in [0.99, 1.0]: output frame at key position := authored value
    #   exactly (translation/rotation/scale copied); rotation filter +
    #   tangent-smooth are applied to non-locked frames only (D5).

def _remap_keyposes(motion_in, frames_out, target_fps) -> list[KeyPose]
    # NEW: each keypose.frame mapped to nearest in-grid output frame
    #   (xi = (frame-1)/(duration_in-1)*(n_out-1) → round); within out duration.

def enrich_motion(motion, params=None) -> NeutralMotion
    # resample → rotation filter → tangent smooth (locked frames protected)
    # → _remap_keyposes → validate_invariants(); total on degenerate inputs.

# infrastructure/ai_models/blocking_input.py
class BlockingInputNode(INode):
    def get_schema(self) -> NodeSchema:
        # type "blocking-input", category SOURCE, title "Blocking Input"
        # inputs=[] ; outputs=[PortSpec("motion", NEUTRAL_ANIMATION)]
        # params=[PortSpec("blocking", data_type=STRING, required=True)]  # JSON payload
    async def validate(self, params):  # params["blocking"] parses → BlockingInput.model_validate
    async def execute(self, inputs, params, context):
        # hmm see threading note; parse+validate+convert via to_thread → NodeOutput({"motion": motion})
```

## Testing Strategy (Strict TDD)

| Layer | What | Approach |
|---|---|---|
| Unit | `BlockingInput` model: well-formed, unknown extra field, empty keyposes, skeleton-mismatch pose, weight out of range, non-finite, zero-quat, max-count | Model tests, `extra="forbid"` negatives |
| Unit | converter: sparse frames produced, default skeleton, duplicate-frame reject, frame-beyond-duration reject, sorted ascending | Synthetic payloads |
| Unit | `_resample` key-lock: exact value at locked frame, off-default passthrough, off-grid snap, single key no div/0, duplicate keys collapsed, adjacent keys, key==every out frame | Mirror `test_inbetween.py`; run-twice byte-identical |
| Unit | `_remap_keyposes`: upsample remap, passthrough when no resample, in-duration | Round-trip frame index |
| Unit | `enrich_motion` total: empty keys, 1 key, dup, adjacent, all-frames, off-grid — never crash/non-finite | Degenerate suite (REQ-07) |
| Infra | node schemas + registry 11 seeds; `GET /nodes/types` lists `blocking-input` | Registry citizen + `test_api.py` update |
| Infra | e2e: `blocking-input → inbetween-generation` graph via executor → valid motion | Mirror `test_inbetween_generation_registry.py` |
| Sec | oversized payload cap, max-keypose, no-eval static scan, non-finite/unit-norm/quat/all-zero rejections | Negative boundary + source inspection |
| Frontend | `KeyPose` typing + "Blocking to Motion" preset graph | `presets.test.ts` + golden fixture drift |

## Threat Matrix

Routing/shell/VCS/process rows: **N/A** — no such boundary in this change.

New §4.2 row (spec-mandated, D4): threat = out-of-bounds pose/frame, out-of-range weight, non-unit/invalid quaternion, NaN/Inf, oversized payload, eval-like injection via params, unbounded resample; severity **High**; control = bounded keypose count + frame-within-duration + weight `[0,1]` + quat unit-norm/all-zero reject + finite-value check + payload size cap at API boundary + static-seed registry (no user param/payload interpretation) + `_resample` total on dup/1-key/off-grid keys; verification = no-eval static inspection + threat-model tests + degenerate key-lock tests + oversized-payload test (propagated verbatim to tasks).

## Migration / Rollout

No `NeutralMotion` schema change, no version bump, no data migration (keyposes field already exists). `preserve_keyposes` defaults `False`, so existing inbetween-generation behavior is unchanged. Rollback (proposal): remove `BlockingInputNode` + registry seed + converter + preset; `_resample` key-lock guarded by param (inert when `False`); `pytest` + import-linter green.

## Open Questions

- [ ] `validate_invariants` — spec REQ-04/SC-04 ("keypose frame within duration") implies adding a keypose-duration check to `NeutralMotion.validate_invariants`; the blocking-input spec's Constraint says "NeutralMotion schema is unchanged" (no new field), but adds validation. Confirm the invariant check is acceptable as a validation-only (non-schema) change, or keep the enforce in the converter to avoid touching the shared contract.
- [ ] Payload transport — carried as a single JSON `params["blocking"]` string on the graph node (mirrors `video_path`). If a structured binary/large payload transport is preferred later, it becomes an input port; not needed for v0.4 (payload is text JSON under the D4 cap).
- [ ] Tangent-smooth lock interaction — locked-frame values are re-applied after the box filter so smoothing never corrupts them; confirm down-stream rotation-filter sign flips (±q) are acceptable "exact value" for the invariant (physical rotation identical).
