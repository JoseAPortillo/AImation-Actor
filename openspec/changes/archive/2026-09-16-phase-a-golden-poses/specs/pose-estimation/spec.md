# Delta for pose-estimation

## MODIFIED Requirements

### Requirement: Swappable estimator backend

The node MUST select an estimator backend through the `model` param. A deterministic **synthetic** backend MUST be available for testing and graph e2e. An **ONNX RTMPose** backend MUST be available for production, wrapping an `onnxruntime.InferenceSession`. Backend inference MUST be offloaded from the asyncio event loop (decision D1). Each backend MUST support single-frame estimation and MUST produce a frame-level confidence score in [0,1] for a single frame (the ONNX backend MAY aggregate per-keypoint confidences).
(Previously: backends served batched estimation over frame lists without a frame-level confidence contract.)

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

#### Scenario: Single-frame estimate reports confidence

- GIVEN a backend estimating one frame
- WHEN the estimation completes
- THEN the result includes a frame-level confidence score in [0,1]