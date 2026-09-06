# Delta for node-registry

## MODIFIED Requirements

### Requirement: Seed nodes

The composition root MUST seed the registry with the built-in nodes. `pose-2d` (added by the pose-2d change) MUST be the 2D pose-estimation node (category `AI`). `video-source` MUST be the OpenCV frame-extraction node (category `SOURCE`). Since this change was planned, later-archived changes (3D lifting and motion conversion) added more seed nodes to the registry; the pose-2d delta originally specified a five-node registry, and the registry subsequently evolved to seven nodes: `pass-through`, `merge`, `frame-range`, `video-source`, `pose-2d`, `pose-3d`, and `video-to-motion`. The temporal-cleanup change added an eighth seed node, and the inbetween-generation change adds a ninth. The registry MUST seed nine nodes: `pass-through`, `merge`, `frame-range`, `video-source`, `pose-2d`, `pose-3d`, `video-to-motion`, `temporal-cleanup`, and `inbetween-generation` (the enrichment node, category `ENRICHMENT` — a new additive `NodeCategory` member introduced by this change). Each MUST declare a valid `NodeSchema` (typed input/output ports).
(Previously: the registry seeded eight nodes without `inbetween-generation`.)

#### Scenario: Seed nodes are present

- GIVEN the application's DI container is built
- WHEN the registry's schemas are listed
- THEN `pass-through`, `merge`, `frame-range`, `video-source`, `pose-2d`, `pose-3d`, `video-to-motion`, `temporal-cleanup`, and `inbetween-generation` are present

#### Scenario: Seed nodes declare typed ports

- GIVEN each seed node's `NodeSchema`
- WHEN the schema is inspected
- THEN every input/output port carries a `DataType`

#### Scenario: temporal-cleanup is the CLEANUP node

- GIVEN the `temporal-cleanup` node in the registry
- WHEN its category and port types are inspected
- THEN its category is `CLEANUP` and it consumes/emits `NEUTRAL_ANIMATION`

#### Scenario: inbetween-generation is the ENRICHMENT node

- GIVEN the `inbetween-generation` node in the registry
- WHEN its category and port types are inspected
- THEN its category is `ENRICHMENT` and it consumes/emits `NEUTRAL_ANIMATION`