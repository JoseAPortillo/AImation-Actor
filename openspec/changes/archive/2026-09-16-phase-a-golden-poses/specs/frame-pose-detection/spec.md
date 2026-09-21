# frame-pose-detection Specification

## Purpose

A synchronous HTTP endpoint that detects the 2D pose of a single video frame, returning keypoints and a frame-level confidence. Detection is offloaded from the event loop; the synthetic backend makes it instant under test (decision D1).

## Requirements

### Requirement: Single-frame detection endpoint

The system MUST provide a single-frame pose detection endpoint accepting a video reference and a 1-based frame index. The endpoint MUST require authentication via `require_token`, MUST resolve the video through the shared `resolve_media_path()` allowlist utility, and MUST return the detected keypoints plus a frame-level confidence score. Detection MUST complete synchronously within the request while its blocking work runs off the event loop thread (decision D1).

#### Scenario: Valid request returns keypoints

- GIVEN an authenticated request for a valid video and frame
- WHEN the endpoint is called
- THEN the response contains named keypoints with normalized x/y and per-keypoint confidence, plus a frame-level confidence

#### Scenario: Event loop stays responsive

- GIVEN a detection request on a busy loop
- WHEN the endpoint is awaited
- THEN the blocking inference does not run inline on the loop thread

#### Scenario: Out-of-range frame rejected

- GIVEN a frame index beyond the video length
- WHEN the endpoint is called
- THEN the request fails with a client error

#### Scenario: Disallowed video path rejected

- GIVEN a video reference that is absolute or traverses outside `media_root`
- WHEN the endpoint is called
- THEN the request fails before any file read

#### Scenario: Unauthenticated request rejected

- GIVEN a request without a valid token
- WHEN the endpoint is called
- THEN the request is rejected with an authentication error

### Requirement: Deterministic synthetic response

With the synthetic backend selected, the endpoint MUST return the fixed scripted keypoint set and its fixed confidence without batch processing.

#### Scenario: Synthetic backend returns fixed output

- GIVEN the synthetic backend is selected
- WHEN a detection request is made
- THEN the response matches the scripted keypoints and confidence on every call