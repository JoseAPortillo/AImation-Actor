import { describe, it, expect } from "vitest";
import { COCO_BONES, drawSkeleton } from "./skeletonOverlay";
import type { DetectedKeypoint } from "../api/types";

/** A keypoint shortcut: normalized coords + confidence. */
function kp(label: string, x: number, y: number, confidence = 0.95): DetectedKeypoint {
  return { label, x, y, confidence };
}

/** Whether a bone connecting `a` and `b` exists regardless of direction. */
function hasBone(
  segments: { from: { label: string }; to: { label: string } }[],
  a: string,
  b: string,
): boolean {
  return segments.some(
    (s) =>
      (s.from.label === a && s.to.label === b) ||
      (s.from.label === b && s.to.label === a),
  );
}

/** The full COCO-17 standing-person set (mirrors the synthetic backend). */
function fullCoco(): DetectedKeypoint[] {
  const defs: Array<[string, number, number]> = [
    ["nose", 0.5, 0.2],
    ["left_eye", 0.48, 0.18],
    ["right_eye", 0.52, 0.18],
    ["left_ear", 0.45, 0.2],
    ["right_ear", 0.55, 0.2],
    ["left_shoulder", 0.4, 0.35],
    ["right_shoulder", 0.6, 0.35],
    ["left_elbow", 0.35, 0.5],
    ["right_elbow", 0.65, 0.5],
    ["left_wrist", 0.3, 0.65],
    ["right_wrist", 0.7, 0.65],
    ["left_hip", 0.45, 0.6],
    ["right_hip", 0.55, 0.6],
    ["left_knee", 0.45, 0.75],
    ["right_knee", 0.55, 0.75],
    ["left_ankle", 0.45, 0.9],
    ["right_ankle", 0.55, 0.9],
  ];
  return defs.map(([label, x, y]) => kp(label, x, y));
}

describe("core/skeletonOverlay — drawSkeleton mapping", () => {
  it("maps normalized keypoint coordinates to display size (x × width, y × height)", () => {
    const keypoints = [kp("nose", 0.5, 0.25), kp("left_ankle", 0.45, 0.9)];
    const overlay = drawSkeleton(keypoints, 800, 400);
    expect(overlay.points).toHaveLength(2);
    expect(overlay.points[0]).toMatchObject({ label: "nose", x: 400, y: 100 });
    expect(overlay.points[1]).toMatchObject({ label: "left_ankle", x: 360, y: 360 });
  });

  it("maps the full COCO set to 17 display points preserving labels", () => {
    const overlay = drawSkeleton(fullCoco(), 640, 360);
    expect(overlay.points).toHaveLength(17);
    expect(new Set(overlay.points.map((p) => p.label)).size).toBe(17);
  });

  it("handles a zero-size display without crashing (all points at origin)", () => {
    const overlay = drawSkeleton([kp("nose", 0.5, 0.5)], 0, 0);
    expect(overlay.points[0]).toMatchObject({ x: 0, y: 0 });
  });
});

describe("core/skeletonOverlay — COCO bones", () => {
  it("COCO_BONES lists the standard 16 bone pairs over 17 joints", () => {
    expect(COCO_BONES).toHaveLength(16);
    const labels = new Set(COCO_BONES.flat());
    expect(labels.size).toBe(17);
    expect(COCO_BONES).toContainEqual(["left_shoulder", "right_shoulder"]);
    expect(COCO_BONES).toContainEqual(["left_hip", "left_knee"]);
    expect(COCO_BONES).toContainEqual(["left_knee", "left_ankle"]);
  });

  it("draws every COCO bone when all 17 keypoints are present (16 segments)", () => {
    const overlay = drawSkeleton(fullCoco(), 640, 360);
    expect(overlay.segments).toHaveLength(16);
    expect(hasBone(overlay.segments, "nose", "left_eye")).toBe(true);
    expect(hasBone(overlay.segments, "right_shoulder", "right_elbow")).toBe(true);
    expect(hasBone(overlay.segments, "left_hip", "right_hip")).toBe(true);
  });

  it("omits bones whose endpoint keypoints are missing", () => {
    const partial = fullCoco().filter((p) => p.label !== "left_elbow");
    const overlay = drawSkeleton(partial, 640, 360);
    expect(overlay.points).toHaveLength(16);
    // left_shoulder↔left_elbow and left_elbow↔left_wrist both need left_elbow.
    expect(hasBone(overlay.segments, "left_shoulder", "left_elbow")).toBe(false);
    expect(hasBone(overlay.segments, "left_elbow", "left_wrist")).toBe(false);
    // Unrelated bones remain.
    expect(hasBone(overlay.segments, "left_shoulder", "right_shoulder")).toBe(true);
  });

  it("draws bone segments at mapped display coordinates", () => {
    const keypoints = [
      kp("left_shoulder", 0.5, 0.5, 0.95),
      kp("right_shoulder", 0.25, 0.75, 0.9),
    ];
    const overlay = drawSkeleton(keypoints, 640, 360);
    expect(overlay.segments).toHaveLength(1);
    const seg = overlay.segments[0];
    expect(seg.from).toMatchObject({ label: "left_shoulder", x: 320, y: 180 });
    expect(seg.to).toMatchObject({ label: "right_shoulder", x: 160, y: 270 });
  });
});