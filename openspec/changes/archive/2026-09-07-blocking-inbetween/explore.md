# Exploration: Blocking → In-betweening (`blocking-inbetween`)

SDD exploration for change **`blocking-inbetween`** (Blocking → In-betweening, plan §20.5 / v0.4). Scope: the most valuable flow for professional animators — the animator creates key poses and the tool generates intermediates while preserving the keys.

Store mode: **openspec**. Change name: `blocking-inbetween`. Artifact type: `architecture`.
Committed source of truth for requirements: `docs/Plan_AImation_Actor_EXT.md` §6.2 (Use Case 2), §8.3 (node catalog incl. `BlockingInput`, `InBetweenGenerator`), §10 (neutral format incl. `keyposes`), §11.3 (blocking-to-motion flow), §13 (motion representation / style separation), §20.5 (MVP Phase 4), plan table row for v0.4.

---

## Current State

### 1. `BlockingInput` node — does not exist in the runtime
The plan (§8.3 line 367) defines **BlockingInput** as a Source node: *"Receives poses from DCC … outputs **neutral keyposes**"*. There is **no** `BlockingInput` node registered anywhere:

- `infrastructure/virtual/node_registry.py::seeded_node_registry` registers 10 seeds: `pass-through`, `merge`, `frame-range`, `video-source`, `pose-2d`, `pose-3d`, `video-to-motion`, `temporal-cleanup`, `inbetween-generation`, `retarget-map`. **No blocking node.**
- No `blocking_input.py` / `blocking.py` module in `aimation_actor_core/infrastructure/ai_models/` or elsewhere.
- `tests/api/test_api.py::TestNodes::test_list_node_types_lists_seed_nodes` asserts the exact 10-node set — adding a node requires updating this test.
- React Flow palette/node-type layer has no `BlockingInput` (`grep -i blocking` in `frontend/src` only matches unrelated "blocking Run" / "non-blocking warning" copy).

### 2. `POST /jobs/blocking-to-motion` — endpoint exists, dispatch is a stub, no covering tests
- `api/routers/jobs.py:38-49` defines `POST /blocking-to-motion` → `_submit(store, JobKind.BLOCKING_TO_MOTION, payload)`.
- `JobKind.BLOCKING_TO_MOTION = "blocking-to-motion"` exists (`domain/job/job.py:31`).
- **Who processes it:** `InMemoryJobStore.submit` (`infrastructure/virtual/stores.py:98`) routes any kind that is *not* `GRAPH_EXECUTE` to `_submit_stub` (`stores.py:117`), which immediately returns `SUCCEEDED` with:
  ```json
  {"kind": "blocking-to-motion", "note": "stub execution — AI pipeline not yet connected", "echo": payload}
  ```
  So the endpoint is a **no-op stub**: the `payload` (poses) is never validated, never converted to a `NeutralMotion`, and no in-between math runs. There is **no** dedicated job runner/worker for `BLOCKING_TO_MOTION` — dispatch is a single in-memory switch inside `InMemoryJobStore`.
- **Tests:** `grep blocking` across `tests/` finds only unrelated "blocking node" executor calls in `test_job_lifecycle.py`. `tests/api/test_api.py::TestJobs` covers `video-to-motion`, `graph/execute`, and 404 — **`/blocking-to-motion` has no covering test** (`⚠️ no covering tests`), confirming the prompt's claim.

### 3. `KeyPose` / `keyposes` — the model field exists; it is never populated or honored
- `domain/animation/neutral_motion.py:53-59` defines `KeyPose(frame: int ≥1, weight: float 0..1 default 1.0)`.
- `NeutralMotion.keyposes: list[KeyPose] = default_factory=list` (`neutral_motion.py:97`). Field is `frozen`; part of the immutable contract.
- **Never populated by any producer.** `grep keypose` in `aimation_actor_core/**/*.py` finds only the model declaration and the passthrough comment in `inbetween.py:418`. No node writes `keyposes`.
- **In-between generation ignores it.** `enrich_motion` (`domain/animation/inbetween.py:398-427`) explicitly passes `contacts`, `keyposes`, `tracking` **through unmodified** (`inbetween.py:416-418`), with a documented MVP note that frame references may be stale after upsample — **remapping is deferred future work**. Test `tests/domain/test_inbetween.py::test_tracking_contacts_keyposes_passthrough` (line 600) locks in this passthrough behavior. So keyposes do **not** constrain resampling today.
- `NeutralMotion.validate_invariants` (`neutral_motion.py:100-116`) validates frames/order/duration but **does not validate keyposes** (no check that keypose frames fall within `duration_frames`, no weight bounds beyond Pydantic `Field(ge=0,le=1)`).
- Frontend mirror: `frontend/src/api/types.ts:123` types `keyposes?: unknown[]` (untyped). `NeutralMotionDoc` in `api/types.ts:118`.

### 4. Resample/interpolation mechanics that blocking would reuse
`domain/animation/inbetween.py` implements the deterministic enrichment chain `resample → rotation filter → tangent smooth` (`enrich_motion`, line 398):

- `_resample` (line 177): **upsample-only** onto `target_fps`; no-op when `target_fps <= meta.fps` or ≤1 frame. Uses per-bone Catmull-Rom tangents for cubic Hótic interpolation, slerped rotations, easing fused into per-interval timing (`_ease`, line 106).
- **Key limitation for blocking:** resampling consumes the existing `motion.frames` as the key grid and interpolates every *source* frame. It does **not** have a notion of "these frames are keys that may not move." For blocking input at sparse key frames, the natural flow is: sparse keys at concrete frames → `keyposes`-aware interpolation producing dense in-betweens **while keeping value and/or timing of the key frames exact.**
- `_resample` treats all source frames as equally movable — **no `weight`/`preserve` semantics**. This is the core math gap for §20.5 "preserve key poses" (line 1344) and `InBetweenGenerator.preserve_keyposes` plan param (line 380).
- Schema: `needs` — the node `inbetween-generation` is `ENRICHMENT` (`infrastructure/ai_models/inbetween_generation.py`, adapter over `enrich_motion`), output `NEUTRAL_ANIMATION`. It passes `params` (interpolation_method, target_fps, easing, euler_filter, tangent_smoothing). **No `preserve_keyposes` param exists yet** in `InbetweenParams` / the node schema.

### 5. Graph executor — synchronous in-request topological driver
- `domain/pipeline/executor.py::GraphExecutor` is a domain Protocol (`run(graph, registry) → GraphExecutionResult`).
- Concrete adapter `infrastructure/virtual/executor.py::SynchronousGraphExecutor` (ADR-002): `validate_graph` → `topological_sort` → run each node's `execute` coroutine in dependency order with per-node timeout, aggregating outputs + logs. `InMemoryJobStore._submit_graph` kicks it via `asyncio.run` synchronously in the request.
- **Implication for blocking:** a `BlockingInput` + `InBetweenGenerator` graph runs inline; no background worker needed for MVP. The pipeline "graph executor" already flows `neutral_animation` between nodes, so a blocking node just needs to emit a `NeutralMotion`.
- `DataType` (`domain/pipeline/schema.py:28`) has `NEUTRAL_POSE = "neutral_pose"` and `NEUTRAL_ANIMATION = "neutral_animation"` but **no dedicated `NEUTRAL_KEYPOSES` / `BLOCKING` data type**. `BlockingInput`'s plan output is "neutral keyposes" — today the nearest representable type is `neutral_animation` (a full `NeutralMotion` with sparse `frames` + `keyposes`), or a new type.

### 6. Frontend — viewer and simple-mode
- `MotionViewer` (`components/motion/MotionViewer.tsx`): canvas 2D stick-figure playback + scrub; `renderFrame` draws from `NeutralMotionDoc`. **Does not visualize keyposes** (no marker for key frames), no pose-level editing/capturing.
- `SimpleMode` (`components/simple/SimpleMode.tsx`): preset launcher cards; merges a canonical `.aimgraph` into the canvas, runs via `useJobStore`, renders a `MotionViewer` result. No blocking-specific preset exists.
- `core/presets.ts`: 2 presets — "Video to Motion" and "Video to Motion (Enriched)". **No "Blocking to Motion" preset.**
- `useJobStore.submit` (`state/useJobStore.ts`) always calls `api.graphExecute(graph)` → `POST /jobs/graph/execute`. It does **not** use `POST /jobs/blocking-to-motion`. So even if the endpoint worked, the UI has no path to submit blocking directly; blocking goes through a graph with a future `BlockingInput` node.

### 7. Plan alignment (verified requirements)
- **§6.2 Use Case 2:** animator creates key poses in DCC → tool captures poses, identifies keyframes, generates intermediate animation, **respects the main poses**, smoothing/contacts, returns editable animation. ← the core contract.
- **§11.3 Blocking-to-Motion Flow:** select controls → mark key poses → capture → convert to neutral → send keyposes to core (or `BlockingInput` node) → generate in-betweens → **respect key poses** → cleanup + foot lock → return.
- **§8.3:** `BlockingInput` (output `neutral keyposes`), `InBetweenGenerator` (param `preserve_keyposes`, `method`).
- **§20.5 v0.4:** capture pose at current frame, mark key poses, generate segment between poses, **preserve key poses**, smoothing, bake. "Probably the most valuable for professional animators."
- **§13:** Motion representation separates structure from style; input is "blocking or video" → Neutral Motion Representation → Style/Enhancer → Retarget. Blocking lands as Neutral Motion (the shared document).
- **§10:** `keyposes: [{"frame": 1, "weight": 1.0}, …]` document shape.

---

## Findings

1. **The `blocking-to-motion` endpoint is a stub with no worker and no tests.** `InMemoryJobStore` returns an immediate `SUCCEEDED` stub; there is no job runner, no real conversion, and no test exercising the route. (Verified: `jobs.py:38`, `stores.py:98/117`, grep of `tests/`.)
2. **`keyposes` is a declared-but-unused contract field.** Declared on `NeutralMotion`, never written by any producer, never honored by interpolation (passthrough, `inbetween.py:416`), untyped on the frontend, un-validated by `validate_invariants`.
3. **`inbetween-generation` re-maps every source frame as an equal key** — it has no weighting/locking semantics. This is the central math gap for "preserve key poses."
4. **No `BlockingInput` node** in core, registry (10-node allowlist), or React Flow palette; no `Blocking` data type in `DataType`.
5. **Frontend has no blocking surface** — no keypose capture/marking UI, no blocking preset, `useJobStore` only drives graph-execute.
6. **Graph executor is in-request and inline** (ADR-002); a blocking flow can be delivered as a graph (`BlockingInput → InBetweenGenerator`) with no background worker for MVP.
7. **`NeutralMotion` is a full document, not just poses** — takes `skeleton` + `meta` too. "Blocking input" must be coerced into a full `NeutralMotion` (sparse `frames` + populated `keyposes`), which means the input format decision is really "what shape does the client send, and how do we build a `NeutralMotion` from it."
8. **`preserve_keyposes` is already a planned `InBetweenGenerator` param** (§8.3) — the design intent exists; only the wiring is missing.
9. **`migrate_neutral_motion` / versioning** is the established read-boundary pattern for `NeutralMotion`-consuming nodes (ADR-001); a new blocking→motion producer should follow it on any persisted read.

---

## Gaps (what the flow §20.5 needs but doesn't have)

- **G1 — Input representation for blocking:** there is no defined format for "poses at concrete frames" sent to the core (endpoint payload shape) or emitted by a `BlockingInput` node. Decision needed (see Decision Options D1).
- **G2 — A real conversion** from blocking input → `NeutralMotion` (sparse frames + `keyposes`). Nothing builds a `NeutralMotion` from user-authored poses today; all producers derive from video.
- **G3 — Keypose-preserving interpolation:** `_resample` treats all keys equally; it must learn to hold key frames to their authored values (and timing) per `weight`, and to **remap/keep `keyposes` frame indices** consistent after resampling (currently passthrough → stale). This extends `InbetweenParams` + `_resample` (and likely `enrich_motion` ordering).
- **G4 — `BlockingInput` node** in core registry + React Flow palette + the 10-node allowlist assertion.
- **G5 — Keypose capture/marking UI** (mark key pose at current frame, capture pose), per §20.5 "capture pose at current frame / mark key poses."
- **G6 — Functional `blocking_to_motion`** (either the endpoint or a graph path) — currently a stub.
- **G7 — Validation/threat model for blocking input** (pose bounds, frame bounds, quaternion validity, far-from-identity inputs, oversized payloads) — no SpecSecDev entry exists.

---

## Decision Options (to resolve — not decided here)

### D1 — How blocking input is modeled & its wire format
- **D1a — Sparse `NeutralMotion` directly:** client sends a full `NeutralMotion` (skeleton + sparse frames + `keyposes`). Pro: reuses the immutabom contract, versioning, `migrate_neutral_motion`; the `BlockingInput` node passes it through (emitting `neutral_animation`). Con: client must build skeleton + meta (heavier contract for a DCC plugin).
- **D1b — New minimal blocking payload (poses only):** a Pydantic model `{ skeleton (or bone subset), keyposes: [{frame, pose, weight}] }` converted to `NeutralMotion` by a converter. Pro: lighter, DCC-friendly, matches plan "neutral keyposes"; Con: new schema + conversion logic + its own versioning story; new `DataType` or reuse `NEUTRAL_ANIMATION`?
- **D1c — Pose keypoint/lift-agnostic poses (reuse `Pose` + a frame index):** minimal `{frame, pose}` list → built into a `NeutralMotion` via existing `Frame`/`Pose`. Con: no skeleton yet; needs default neutral `Skeleton`.
- **Recommendation signal (not a decision):** the plan's own language ("neutral keyposes" output, "convert to neutral representation" §11.3 step 4) points to the *converter lives in the flow* — i.e. a `BlockingInput` node that accepts a lightweight client payload and **produces** `NEUTRAL_ANIMATION`. This favors D1b/D1c for the input wire + a `NeutralMotion`-emitting node.

### D2 — Interaction with existing `inbetween-generation`
- **D2a — Extend the existing `inbetween-generation` node** to honor `preserve_keyposes` (add param + remap + key-lock in `_resample`). Fits the plan's `InBetweenGenerator.preserve_keyposes` (§8.3), minimal surface, reuses the ENRICHMENT category. Field remap (keypose frame indices after upsample) is needed either way.
- **D2b — New `BlockingInput` + dedicated `blocking-inbetween` node** separate from the video-oriented `inbetween-generation`. More explicit, but duplicates the math and muddies the enrichment contract.
- **Recommendation signal:** D2a (extend existing) + a separate *input* node (`BlockingInput`) is the coherent split: input produces `NeutralMotion`; enrichment preserves keys. Rationale: the math (resample/slerp/ease) is identical; only the "lock keys" rule differs, and that's cleanly a new param/path inside `_resample`.

### D3 — MVP scope for v0.4 (what ships vs. deferred)
Candidate in-scope (blocks, verified against plan §20.5):
- Model blocking input (D1), blocking→`NeutralMotion` converter, key-lock interpolation + keypose remap, `BlockingInput` node in core registry + React Flow + preset, functional path (endpoint OR graph), SpecSecDev/threat entry, real tests.
Candidate deferred (out of §20.5 MVP, belongs to later phases):
- Foot lock / contact constraints (§20.5 lists them but they're separate §10 `contacts` concern, and §11.3 step 8 "cleanup and foot lock" is a distinct cleanup stage), bite/mark-only keyposes with partial weights affecting segment shape (start with weight≈1.0 exact-lock), Maya/DCC-side capture (v0.4 plan says "in Maya"; the plugin is 0.3 territory — decide whether the UI capture is core-only for first cut), generative `MotionEnhancer` (Phase 8).

### D4 — Threat model / SpecSecDev for blocking input
Explicit new threat-model row + SpecSecDev coverage for: pose count / frame count bounds (avoid unbounded resample), frame indices within `duration_frames`, weight range, quaternion unit-norm/validity, finite numeric values (no NaN/Inf), JSON payload size limits on the endpoint, and ensuring no path/eval-like injection via node params (consistent with the domain guardrails). The `_resample` math must be total (no divide-by-zero on duplicate keys or 1-key input). A new `DataType` (if D1b/D1c introduces one) also touches the connection-validity gating in the React Flow palette.

---

## Affected Areas

- `aimation_actor_core/domain/animation/inbetween.py` — extend `_resample`/`InbetweenParams` for key-locking + (likely) new ordering; the heart of D2a.
- `aimation_actor_core/domain/animation/neutral_motion.py` — possibly extend `KeyPose`/`validate_invariants` (keypose frame bounds) if the model grows; or only a new keyposes-writer helper.
- `aimation_actor_core/domain/animation/` (new) — a blocking→`NeutralMotion` converter (D1).
- `aimation_actor_core/infrastructure/ai_models/` (new `blocking_input.py` or similar) — `BlockingInput` node adapter (D2).
- `aimation_actor_core/infrastructure/virtual/node_registry.py` + `tests/api/test_api.py::test_list_node_types_lists_seed_nodes` — register the node; update the 10-node allowlist assertion.
- `aimation_actor_core/api/routers/jobs.py` + `infrastructure/virtual/stores.py` — make `BLOCKING_TO_MOTION` real (or document it routes through graph).
- `aimation_actor_core/domain/pipeline/schema.py` + `frontend/src/api/types.ts` — `DataType` addition if D1b/D1c introduces a blocking type; `KeyPose` frontend typing.
- `frontend/src/core/presets.ts` — new "Blocking to Motion" preset.
- `frontend/src/components/...` (new or SimpleMode/PropertiesPanel) — keypose capture/marking UI, blocking result viewer.
- Threat model / SpecSecDev section (SDD §4.2/4.4) — new blocking-input entry (D4).

---

## Risks

1. **Schema churn on the immutable `NeutralMotion` contract** — if the input format is added as a new root field/type, it must follow the versioned migration + ADR path (SDD §5.3 / ADR-001). High.
2. **Interpolation correctness with key-locking** — blending "hold exact keys with weight" against Catmull-Rom/slerp can introduce discontinuities if weights <1 are treated as hard locks; needs precise semantics and tests (duplicate/adjacent keys, 1-key input, keys == every output frame, keys not on the upsample grid). High.
3. **Keypose frame-index remap** after resampling — currently passthrough/stale; shipping key-lock without remap mislabels which frames are keys. Medium.
4. **`BlockingInput` data type vs. `NEUTRAL_ANIMATION` reuse** — a new type touches both the core `DataType` and the frontend connection gating; wrong choice complicates the palette. Medium.
5. **10-node allowlist test rigidity** — adding a node is a small, explicit test update, but forgetting it breaks CI. Low.
6. **Scope creep from §20.5** — foot lock / contacts / bake-in-DCC are adjacent but distinct; shoehorning them into this change inflates review (400-line budget). Mitigate by partitioning (D3).

---

## Ready for Proposal

**Yes.** Enough is verified to write a proposal. Tell the orchestrator/user: the exploration confirms `blocking-to-motion` is a stub with no worker/tests, `keyposes` is a declared-but-unused field that `inbetween-generation` passes through (re-mapping all frames equally), and no `BlockingInput` node or frontend capture surface exists. The architecture is ready for a `BlockingInput` node emitting `NeutralMotion` + a keypose-preserving extension of `_resample`, but three decisions must be resolved first: D1 (blocking input wire format), D2 (extend existing node vs. new node), and D3 (MVP boundary — specifically whether foot-lock/contacts and DCC-side capture are in or out for v0.4).
