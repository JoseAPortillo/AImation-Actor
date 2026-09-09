import { describe, it, expect } from "vitest";
import { quatToEulerZXY, neutralToBvh } from "./bvh";
import type { NeutralMotionDoc, Vec4 } from "../api/types";

/* ── quatToEulerZXY ──────────────────────────────────────────────────────── */

describe("quatToEulerZXY", () => {
  it("returns zero angles for identity quaternion", () => {
    const result = quatToEulerZXY([1, 0, 0, 0]);
    expect(result.xRot).toBeCloseTo(0, 10);
    expect(result.yRot).toBeCloseTo(0, 10);
    expect(result.zRot).toBeCloseTo(0, 10);
  });

  it("converts a 45-degree Z rotation correctly", () => {
    const angle = Math.PI / 4; // 45 degrees
    const halfAngle = angle / 2;
    const q: Vec4 = [Math.cos(halfAngle), 0, 0, Math.sin(halfAngle)];

    const result = quatToEulerZXY(q);
    expect(result.zRot).toBeCloseTo(angle, 6);
    expect(result.xRot).toBeCloseTo(0, 6);
    expect(result.yRot).toBeCloseTo(0, 6);
  });

  it("converts a pure X rotation correctly", () => {
    const angle = Math.PI / 6; // 30 degrees
    const halfAngle = angle / 2;
    const q: Vec4 = [Math.cos(halfAngle), Math.sin(halfAngle), 0, 0];

    const result = quatToEulerZXY(q);
    expect(result.xRot).toBeCloseTo(angle, 6);
    expect(result.yRot).toBeCloseTo(0, 6);
    expect(result.zRot).toBeCloseTo(0, 6);
  });

  it("converts a pure Y rotation correctly", () => {
    const angle = Math.PI / 3; // 60 degrees
    const halfAngle = angle / 2;
    const q: Vec4 = [Math.cos(halfAngle), 0, Math.sin(halfAngle), 0];

    const result = quatToEulerZXY(q);
    expect(result.yRot).toBeCloseTo(angle, 6);
    expect(result.xRot).toBeCloseTo(0, 6);
    expect(result.zRot).toBeCloseTo(0, 6);
  });
});

/* ── neutralToBvh ────────────────────────────────────────────────────────── */

describe("neutralToBvh", () => {
  function makeTestMotion(): NeutralMotionDoc {
    const angle = Math.PI / 4; // 45 degrees
    const halfAngle = angle / 2;
    const zRotQuat: Vec4 = [Math.cos(halfAngle), 0, 0, Math.sin(halfAngle)];

    return {
      meta: {
        version: "1.0",
        fps: 24,
        units: "m",
        up_axis: "Y",
        source_type: "neutral",
        duration_frames: 2,
        style: "default",
        model_version: "0.1",
        graph_hash: "abc",
      },
      skeleton: {
        bones: {
          Root: { name: "Root", parent: null, rest_position: [0, 0, 0] },
          Head: { name: "Head", parent: "Root", rest_position: [0, 10, 0] },
        },
      },
      frames: [
        {
          frame: 1,
          time: 0,
          pose: {
            transforms: {
              Root: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
              Head: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
            },
          },
        },
        {
          frame: 2,
          time: 0.041667,
          pose: {
            transforms: {
              Root: { translation: [5, 0, 0], rotation: zRotQuat, scale: [1, 1, 1] },
              Head: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
            },
          },
        },
      ],
    };
  }

  it("contains required BVH header elements", () => {
    const bvh = neutralToBvh(makeTestMotion());

    expect(bvh).toContain("HIERARCHY");
    expect(bvh).toContain("ROOT Root");
    expect(bvh).toContain("JOINT Head");
    expect(bvh).toContain("CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation");
    expect(bvh).toContain("CHANNELS 3 Zrotation Xrotation Yrotation");
  });

  it("formats Head offset correctly", () => {
    const bvh = neutralToBvh(makeTestMotion());

    // Head rest_position is [0, 10, 0] → formatted as "0 10 0"
    expect(bvh).toContain("OFFSET 0 10 0");
  });

  it("contains correct frame count and time", () => {
    const bvh = neutralToBvh(makeTestMotion());

    expect(bvh).toContain("Frames: 2");
    expect(bvh).toContain("Frame Time: 0.041667");
  });

  it("frame 1 root line has 6 numbers starting with identity rotation", () => {
    const bvh = neutralToBvh(makeTestMotion());
    const lines = bvh.split("\n");

    const dataLines = lines.filter(
      (l) => !l.startsWith("HIERARCHY") && !l.startsWith("ROOT") && !l.startsWith("JOINT") &&
             !l.startsWith("OFFSET") && !l.startsWith("CHANNELS") && !l.startsWith("MOTION") &&
             !l.startsWith("Frames:") && !l.startsWith("Frame Time:") && !l.startsWith("{") &&
             !l.startsWith("}") && l.trim().length > 0 && !l.startsWith("\t")
    );

    // Frame 1: root has 6 numbers, Head has 3
    expect(dataLines).toHaveLength(2);
    const frame1 = dataLines[0].trim().split(/\s+/);
    expect(frame1).toHaveLength(9); // 6 (root) + 3 (head)
    // Root position should be [0, 0, 0]
    expect(frame1[0]).toBe("0");
    expect(frame1[1]).toBe("0");
    expect(frame1[2]).toBe("0");
    // Root rotation should be 0 (identity)
    expect(frame1[3]).toBe("0");
    expect(frame1[4]).toBe("0");
    expect(frame1[5]).toBe("0");
  });

  it("frame 2 root position begins with 5 0 0", () => {
    const bvh = neutralToBvh(makeTestMotion());
    const lines = bvh.split("\n").filter(
      (l) => !l.startsWith("HIERARCHY") && !l.startsWith("ROOT") && !l.startsWith("JOINT") &&
             !l.startsWith("OFFSET") && !l.startsWith("CHANNELS") && !l.startsWith("MOTION") &&
             !l.startsWith("Frames:") && !l.startsWith("Frame Time:") && !l.startsWith("{") &&
             !l.startsWith("}") && l.trim().length > 0 && !l.startsWith("\t")
    );

    const frame2 = lines[1].trim().split(/\s+/);
    expect(frame2[0]).toBe("5");
    expect(frame2[1]).toBe("0");
    expect(frame2[2]).toBe("0");
    // Root z-rotation should be ~45 degrees (0.785398 rad)
    expect(parseFloat(frame2[3])).toBeCloseTo(Math.PI / 4, 4);
  });

  it("handles bone missing from frame transforms by using identity rotation", () => {
    const motion = makeTestMotion();
    // Remove Head from frame 1
    delete motion.frames[0].pose.transforms.Head;

    const bvh = neutralToBvh(motion);
    const lines = bvh.split("\n").filter(
      (l) => !l.startsWith("HIERARCHY") && !l.startsWith("ROOT") && !l.startsWith("JOINT") &&
             !l.startsWith("OFFSET") && !l.startsWith("CHANNELS") && !l.startsWith("MOTION") &&
             !l.startsWith("Frames:") && !l.startsWith("Frame Time:") && !l.startsWith("{") &&
             !l.startsWith("}") && l.trim().length > 0 && !l.startsWith("\t")
    );

    // Should still have 2 frame lines
    expect(lines).toHaveLength(2);
    // Frame 1 should not throw
    expect(() => neutralToBvh(motion)).not.toThrow();
  });

  it("formats numbers correctly (strip trailing zeros)", () => {
    const motion: NeutralMotionDoc = {
      meta: {
        version: "1.0",
        fps: 24,
        units: "m",
        up_axis: "Y",
        source_type: "neutral",
        duration_frames: 1,
        style: "default",
        model_version: "0.1",
        graph_hash: "abc",
      },
      skeleton: {
        bones: {
          Root: { name: "Root", parent: null, rest_position: [0, 0, 0] },
        },
      },
      frames: [
        {
          frame: 1,
          time: 0,
          pose: {
            transforms: {
              Root: { translation: [1, 0.5, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
            },
          },
        },
      ],
    };

    const bvh = neutralToBvh(motion);
    // Check formatting: 1.000000 → "1", 0.500000 → "0.5"
    const lines = bvh.split("\n");
    const frameLine = lines.find((l) => l.startsWith("1 0.5 0")) || lines.find((l) => l.startsWith("1 0.5"));
    expect(frameLine).toBeTruthy();
  });
});
