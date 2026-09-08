# blocking-input — Delta Specs

== Capability: blocking-input (NEW) ==

## Purpose

A source stage that ingests a lightweight, DCC-friendly blocking payload (decision D1b) and converts it into a sparse `NeutralMotion` (`NEUTRAL_ANIMATION`) with populated `keyposes`. Delivers the animator-facing "blocking → in-betweening" flow (plan §20.5, §11.3): the client sends concrete key poses at concrete frames; the `BlockingInput` node turns them into a shared neutral document that downstream `inbetween-generation` preserves. No new `DataType` is introduced (output reuses `NEUTRAL_ANIMATION`, decision D1b). The node is a `SOURCE`-category producer; math and validation live in the domain, with a converter that never trusts client input (decision D4).

## Requirements

### Requirement: REQ-01 — Blocking payload model

The system MUST define a `BlockingInput` Pydantic model (frozen, `extra="forbid"`) accepting the wire shape `{ skeleton (optional), keyposes: [{frame, pose, weight}] }`. The `skeleton` field MUST be optional and, when provided, MUST validate as a conforming `Skeleton`; when omitted, the converter MUST use the default neutral skeleton. Each `keypose` MUST carry a positive integer `frame` (`>= 1`), a `pose` (a full per-bone transform set naming every bone in the resolved skeleton), and a `weight` float in `[0, 1]` (Pydantic `Field(ge=0, le=1)`, default `1.0`). Unknown fields MUST be rejected; a keypose whose `pose` omits or adds bones relative to the resolved skeleton MUST fail validation. The model MUST reject a keyposes list that is empty.

#### Scenario: SC-01 — Well-formed payload validates

- GIVEN a payload with `skeleton` omitted and three `keyposes`, each carrying a full pose matching the default neutral skeleton and `weight` in `[0,1]`
- WHEN it is parsed and `model_validate`d
- THEN validation succeeds and the model holds the three keyposes

#### Scenario: SC-02 — Unknown extra field rejected

- GIVEN a payload with an unexpected top-level or per-keypose key
- WHEN it is validated
- THEN validation fails (no field silently ignored)

#### Scenario: SC-03 — Empty keyposes rejected

- GIVEN a payload whose `keyposes` list is empty
- WHEN it is validated
- THEN validation fails

#### Scenario: SC-04 — Skeleton mismatch rejected

- GIVEN a keypose whose `pose` cannot address every bone of the resolved skeleton
- WHEN it is validated against the skeleton
- THEN validation fails

#### Scenario: SC-05 — Weight out of range rejected

- GIVEN a keypose with `weight < 0` or `weight > 1`
- WHEN it is validated
- THEN validation fails

#### Scenario: SC-06 — Non-finite values rejected

- GIVEN a keypose whose `pose` contains a `NaN` or `Inf` translation or quaternion component
- WHEN it is validated
- THEN validation fails (no non-finite value is accepted)

### Requirement: REQ-02 — Blocking → NeutralMotion converter

The system MUST provide a converter that builds a `NeutralMotion` from a validated `BlockingInput`. The produced document MUST have one `Frame` per keypose (`frame` number copied from the keypose), `frames` strictly increasing, `keyposes` populated with the source frame/weight pairs, `meta.fps` defaulting to a blocking-friendly rate (e.g. `24.0`) unless overridden, and `meta.duration_frames` set to the highest keypose frame. When `skeleton` was omitted, the produced document MUST use the default neutral skeleton. The document MUST satisfy `NeutralMotion.validate_invariants()` after construction; keypose frames beyond `duration_frames` MUST be rejected at conversion. Keys MUST be sorted ascending by `frame`; duplicate frames MUST be rejected.

#### Scenario: SC-01 — Sparse frames and keyposes produced

- GIVEN a validated blocking payload with keyposes at frames 1, 5, 13
- WHEN the converter runs
- THEN the resulting `NeutralMotion` has 3 frames (1, 5, 13), `keyposes` lists all three, and `meta.duration_frames` equals 13

#### Scenario: SC-02 — Default skeleton used when omitted

- GIVEN a blocking payload with no `skeleton`
- WHEN the converter runs
- THEN the produced `NeutralMotion` carries the default neutral skeleton and satisfies the invariants

#### Scenario: SC-03 — Duplicate frames rejected

- GIVEN a blocking payload with two keyposes at the same `frame`
- WHEN the converter runs
- THEN conversion fails and no `NeutralMotion` is produced

#### Scenario: SC-04 — Keypose frame beyond duration rejected

- GIVEN a keypose at `frame` strictly greater than the intended `duration_frames`
- WHEN the converter runs
- THEN conversion fails (threat: frame index out of bounds never yields a document)

### Requirement: REQ-03 — BlockingInput node

The `BlockingInput` node MUST be a `SOURCE`-category node that validates parameters **or** a structured payload input before execution, coerces a validated `BlockingInput` to a `NeutralMotion` via the converter, and emits it on a single output port `motion: NEUTRAL_ANIMATION`. It MUST be stateless and deterministic: identical inputs yield byte-identical outputs, and the emitted `NeutralMotion` MUST pass `validate_invariants()`. The node MUST be registered in the core node registry (seed count 10 → 11) and surfaced by `GET /nodes/types` and the React Flow palette. The adapter MUST offload blocking work (e.g. via `asyncio.to_thread`) and MUST NOT interpret params or payload as code in any way.

#### Scenario: SC-01 — Emits valid NEUTRAL_ANIMATION

- GIVEN a validated blocking payload
- WHEN the node executes
- THEN it returns a single output `motion` carrying a `NeutralMotion` that satisfies `validate_invariants()`

#### Scenario: SC-02 — Invalid payload fails before execution

- GIVEN a payload with an out-of-range `weight` or non-finite value
- WHEN the node validates the input
- THEN validation fails and no conversion or execution occurs

#### Scenario: SC-03 — Deterministic and stateless

- GIVEN the same validated payload
- WHEN the node executes twice
- THEN both outputs are byte-identical

#### Scenario: SC-04 — Registered and listed

- GIVEN the seeded composition root
- WHEN the registry schemas and `GET /nodes/types` are inspected
- THEN `blocking-input` is present with category `SOURCE` and output `motion: NEUTRAL_ANIMATION`

### Requirement: REQ-04 — Blocking-input validation threat model

The system MUST apply bounded validation to blocking input per decision D4: a maximum keypose count (unbounded resample is prevented); every keypose `frame` within `duration_frames`; `weight` in `[0, 1]`; quaternions unit-norm within tolerance and not all-zero; all numeric components finite (no `NaN`/`Inf`); a maximum serialized payload size enforced at the API boundary; and no `eval`/`exec`-like interpretation of any user-supplied node parameter or payload content. `BlockingInput` validation MUST be reachable from the public API path so oversized or malicious payloads are rejected before any node runs.

#### Scenario: SC-01 — Payload size cap enforced

- GIVEN a blocking payload exceeding the configured size limit
- WHEN it is submitted at the API boundary
- THEN it is rejected before validation or node execution

#### Scenario: SC-02 — Zero-quaternion rejected

- GIVEN a keypose whose rotation quaternion is all zeros (not a unit quaternion)
- WHEN it is validated
- THEN validation fails

#### Scenario: SC-03 — Max keypose count bounded

- GIVEN a payload whose `keyposes` exceeds the configured maximum count
- WHEN it is validated
- THEN validation fails (unbounded resample is prevented)

## Constraints (Non-Requirements)

- The converter and payload model MUST live in the domain layer (pure stdlib + Pydantic); the node adapter (infrastructure) owns no conversion math.
- `NeutralMotion` schema is unchanged — no new field, no versioned migration, no ADR. `NEUTRAL_ANIMATION` is reused on output (decision D1b); no new `DataType` in `DataType`/`NodeCategory` or the TypeScript mirror.
- Keypose capture/marking UI, Maya/DCC-side capture, foot lock and partial-weight shape control are out of scope for this change (deferred post-v0.4, decision D3).
- Foot contact tracks (`contacts`) and `tracking` are unmodified by the converter (empty/default) for this MVP.
