# golden-poses-ux Specification

## Purpose

Frontend experience for marking golden poses on a video: timeslider playback, draggable pins, a live 2D skeleton overlay, per-pin detection states, and pin merge onto the pipeline output. Pin state is frontend-only in Phase A (decision D2).

## Requirements

### Requirement: Video timeslider

For a `video-source` node, the frontend MUST render a video timeslider with scrub and play controls, showing frames served by the media API. Scrubbing MUST update the displayed frame, play MUST advance frames over time, and hovering SHOULD show a frame thumbnail. When no video is selected, the timeslider MUST show a placeholder without errors.

#### Scenario: Scrubbing updates the displayed frame

- GIVEN a `video-source` node with a selected video
- WHEN the user scrubs to a frame
- THEN the displayed frame updates to match

#### Scenario: Hover shows thumbnail

- GIVEN a loaded video
- WHEN the user hovers over a timeslider position
- THEN a thumbnail preview of that frame is shown

#### Scenario: No video shows placeholder

- GIVEN a `video-source` node without a selected video
- WHEN the timeslider renders
- THEN a placeholder is shown and no frame request is issued

### Requirement: Golden pins

The user MUST be able to mark a pin at the current frame (G1…Gn), drag a pin to another frame, and delete a pin. Pins MUST be frontend-only state in Phase A: the `video-source` schema MUST NOT change and pin data MUST NOT be sent to the backend for persistence.

#### Scenario: Marking a pin at the current frame

- GIVEN a frame displayed on the timeslider
- WHEN the user marks a pin
- THEN a pin is added at that frame with the next sequential label

#### Scenario: Dragging repositions a pin

- GIVEN an existing pin
- WHEN the user drags it to another frame
- THEN the pin's frame updates

#### Scenario: Deleting a pin

- GIVEN an existing pin
- WHEN the user deletes it
- THEN the pin is removed and remaining pins keep their labels

### Requirement: Per-pin detection state

When a pin is marked, the frontend MUST request single-frame detection and MUST show per-pin state ⏳ processing → ✓ with confidence, or ✗ on failure. The frontend MUST NOT issue overlapping detection requests for the same pin (decision D1 debounce).

#### Scenario: Detection succeeds

- GIVEN a pin marked on a valid frame
- WHEN detection returns keypoints and confidence
- THEN the pin shows ✓ with the confidence value

#### Scenario: Detection fails

- GIVEN a pin whose detection request fails
- WHEN the failure occurs
- THEN the pin shows ✗ and remains editable

### Requirement: 2D skeleton overlay

The frontend MUST render the detected skeleton over the video by mapping normalized keypoints to display size, and MUST provide a toggle to show or hide the overlay.

#### Scenario: Overlay shows detected skeleton

- GIVEN a completed detection for the current frame
- WHEN the overlay is visible
- THEN the skeleton is drawn aligned with the video frame

#### Scenario: Overlay toggle

- GIVEN a visible overlay
- WHEN the user toggles it off then on
- THEN the overlay hides and restores on re-enable

### Requirement: Keypose merge after job success

After a graph job succeeds, the frontend MUST merge the pins onto the pipeline result's `NeutralMotionDoc.keyposes` as `KeyPose` entries (frame >= 1, weight in [0,1]). The backend MUST NOT populate keyposes in Phase A.

#### Scenario: Pins merged onto result

- GIVEN a successful job run with pins
- WHEN the result document is produced
- THEN `keyposes` contains one `KeyPose` per pin at the pin's frame

#### Scenario: No pins leaves keyposes absent

- GIVEN a successful job run without pins
- WHEN the result document is produced
- THEN `keyposes` is absent or empty without error