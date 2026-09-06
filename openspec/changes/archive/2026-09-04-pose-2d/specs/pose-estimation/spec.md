# pose-estimation Specification

## Purpose

A real 2D pose-estimation node (`pose-2d`) that consumes the `FRAMES` produced by `video-source` and emits typed `KEYPOINTS_2D`. This is the second genuine stage of the AI pipeline (plan §12.2). The stack is fixed by decision D2: ONNX / torch only (no MediaPipe, no TensorFlow). It conforms to the existing `INode` contract and runs through the current graph executor unchanged.

## Requirements

### Requirement: Pose estimation node contract

The system MUST provide `Pose2DNode` with schema type `pose-2d` and category `AI`. It MUST declare an input port `frames` of `DataType.FRAMES` and an output port `keypoints` of `DataType.KEYPOINTS_2D`. It MUST declare params `model` (STRING, optional — selects the estimator backend) and `confidence` (NUMBER, optional, [0,1]). The node MUST run through the unchanged graph executor.

#### Scenario: Node declares its catalog schema

- GIVEN the `Pose2DNode` type
- WHEN `get_schema()` is called
- THEN `type` is `pose-2d`, `category` is `AI`, the `frames` input port is typed `FRAMES`, and the `keypoints` output port is typed `KEYPOINTS_2D`

#### Scenario: Node runs through the executor

- GIVEN a graph with `video-source` feeding `pose-2d`
- WHEN the graph is executed
- THEN `pose-2d` consumes the produced frames and contributes `keypoints` output

### Requirement: Typed keypoint value object

The system MUST define a pure-domain value object `Keypoints2D` that types the `KEYPOINTS_2D` output. It MUST NOT expose raw tensors at the domain boundary. Each `Keypoints2D` MUST describe the 2D pose for one frame: a list of named keypoints, each with a label, normalized `x` and `y` in `[0,1]`, and a confidence in `[0,1]`.

#### Scenario: Keypoints2D carries normalized coordinates

- GIVEN a `Keypoints2D` instance for a frame
- WHEN its keypoints are inspected
- THEN each keypoint has a label and normalized `x`/`y` in `[0,1]`, and a confidence in `[0,1]`

#### Scenario: No tensor leaks to the domain boundary

- GIVEN the `Keypoints2D` container
- WHEN inspecting its value types
- THEN it contains only serializable primitives (labels, floats), no ndarray/tensor

### Requirement: Swappable estimator backend

The node MUST select an estimator backend through the `model` param. A deterministic **synthetic** backend MUST be available for testing and graph e2e. An **ONNX RTMPose** backend MUST be available for production, wrapping an `onnxruntime.InferenceSession`. Backend inference MUST be offloaded from the asyncio event loop (decision D1).

#### Scenario: Synthetic backend emits deterministic keypoints

- GIVEN the synthetic backend
- WHEN it estimates keypoints for a frame
- THEN it emits a fixed, scripted keypoint set (same count/labels each run)

#### Scenario: Inference does not run inline on the event loop

- GIVEN a video being processed by `pose-2d`
- WHEN the node estimates keypoints
- THEN the blocking estimation does not run inline on the loop thread

#### Scenario: Unknown model falls back safely

- GIVEN a `model` param value that is not a known ONNX model
- WHEN the node selects a backend
- THEN it falls back to the synthetic backend (or is rejected per design) without crashing

### Requirement: Backend availability surfaced in health

The system MUST expose the pose backend availability via `GET /health` (e.g. `"pose": "synthetic"` or `"pose": "onnx"`), so operators know whether a real model is loaded.

#### Scenario: Health reports pose backend

- GIVEN the application is built
- WHEN `GET /health` is called
- THEN the response includes the pose backend status

## MODIFIED Requirements (node-registry)

### Requirement: Seed nodes

The composition root MUST seed the registry with **five** nodes: `pass-through`, `merge`, `frame-range`, `video-source`, and `pose-2d`. `pose-2d` MUST be the 2D pose-estimation node (category `AI`).

#### Scenario: Seed nodes are present

- GIVEN the application's DI container is built
- WHEN the registry's schemas are listed
- THEN `pass-through`, `merge`, `frame-range`, `video-source`, and `pose-2d` are present

#### Scenario: Seed nodes declare typed ports

- GIVEN each seed node's `NodeSchema`
- WHEN the schema is inspected
- THEN every input/output port carries a `DataType`
