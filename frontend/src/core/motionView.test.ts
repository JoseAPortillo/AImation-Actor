import { describe, it, expect } from "vitest";
import {
  extractMotion,
  extractNodeMotion,
  isNeutralMotionDoc,
  absolutePositions,
  drawBones,
} from "./motionView";
import type { NeutralMotionDoc } from "../api/types";

/* ── fixtures ────────────────────────────────────────────────────────────── */

/**
 * Minimal skeleton: Root → Hips → Spine
 *
 * Root:  rest [0, 0, 0], parent null
 * Hips:  rest [0, 1, 0], parent Root
 * Spine: rest [0, 2, 0], parent Hips
 */
function miniSkeleton(): NeutralMotionDoc {
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
        Hips: { name: "Hips", parent: "Root", rest_position: [0, 1, 0] },
        Spine: { name: "Spine", parent: "Hips", rest_position: [0, 2, 0] },
      },
    },
    frames: [
      {
        frame: 1,
        time: 0.041,
        pose: {
          transforms: {
            Root: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
            Hips: { translation: [0, 0.5, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
            Spine: { translation: [0, 0.3, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
          },
        },
        confidence: 0.9,
      },
      {
        frame: 2,
        time: 0.083,
        pose: {
          transforms: {
            Root: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
            Hips: { translation: [1, 0.5, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
            Spine: { translation: [0, 0.3, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
          },
        },
        confidence: 0.85,
      },
    ],
  };
}

/* ── extractMotion ───────────────────────────────────────────────────────── */

describe("extractMotion", () => {
  it("returns NeutralMotionDoc from a well-formed result", () => {
    const result = {
      outputs: {
        "video-to-motion": {
          motion: miniSkeleton(),
        },
      },
    };
    const motion = extractMotion(result);
    expect(motion).not.toBeNull();
    expect(motion!.meta.fps).toBe(24);
    expect(Object.keys(motion!.skeleton.bones)).toHaveLength(3);
  });

  it("returns null for null input", () => {
    expect(extractMotion(null)).toBeNull();
  });

  it("returns null when outputs key is missing", () => {
    expect(extractMotion({})).toBeNull();
  });

  it("returns null when video-to-motion key is missing", () => {
    expect(extractMotion({ outputs: {} })).toBeNull();
  });

  it("returns null when motion sub-key is missing", () => {
    expect(extractMotion({ outputs: { "video-to-motion": {} } })).toBeNull();
  });

  it("returns null when motion is missing required fields", () => {
    const result = {
      outputs: {
        "video-to-motion": {
          motion: { meta: {}, skeleton: {} }, // missing frames
        },
      },
    };
    expect(extractMotion(result)).toBeNull();
  });

  it("extracts motion from an arbitrary node id wrapping { motion: doc }", () => {
    const result = {
      outputs: {
        "n_ab12cd": {
          motion: miniSkeleton(),
        },
      },
    };
    const motion = extractMotion(result);
    expect(motion).not.toBeNull();
    expect(motion!.meta.fps).toBe(24);
  });

  it("extracts motion when an output value IS the doc directly", () => {
    const result = {
      outputs: {
        "n_ef34gh": miniSkeleton(),
      },
    };
    const motion = extractMotion(result);
    expect(motion).not.toBeNull();
    expect(Object.keys(motion!.skeleton.bones)).toHaveLength(3);
  });

  it("returns the FIRST valid motion when multiple outputs exist", () => {
    const first = miniSkeleton();
    first.meta = { ...first.meta, fps: 30 };
    const second = miniSkeleton();
    second.meta = { ...second.meta, fps: 60 };
    const result = {
      outputs: {
        "n_first": first,
        "n_second": { motion: second },
      },
    };
    const motion = extractMotion(result);
    expect(motion).not.toBeNull();
    expect(motion!.meta.fps).toBe(30);
  });

  it("returns null when outputs exist but none contains a motion-shaped value", () => {
    const result = {
      outputs: {
        "n_one": { frames: "yes" },
        "n_two": { something: 1 },
      },
    };
    expect(extractMotion(result)).toBeNull();
  });

  it("still works through the legacy video-to-motion path", () => {
    const result = {
      outputs: {
        "video-to-motion": {
          motion: miniSkeleton(),
        },
      },
    };
    const motion = extractMotion(result);
    expect(motion).not.toBeNull();
    expect(motion!.meta.fps).toBe(24);
  });
});

/* ── extractNodeMotion ───────────────────────────────────────────────────── */

describe("extractNodeMotion", () => {
  it("returns the doc from a { motion: doc } wrapper for the given node", () => {
    const result = {
      outputs: {
        "blocking-input_ab12cd": { motion: miniSkeleton() },
      },
    };
    const motion = extractNodeMotion(result, "blocking-input_ab12cd");
    expect(motion).not.toBeNull();
    expect(motion!.meta.fps).toBe(24);
  });

  it("returns the doc when the node output value IS the doc directly", () => {
    const result = {
      outputs: {
        "n_ef34gh": miniSkeleton(),
      },
    };
    const motion = extractNodeMotion(result, "n_ef34gh");
    expect(motion).not.toBeNull();
    expect(Object.keys(motion!.skeleton.bones)).toHaveLength(3);
  });

  it("returns null for a missing node id", () => {
    const result = {
      outputs: {
        "other-node": miniSkeleton(),
      },
    };
    expect(extractNodeMotion(result, "blocking-input_ab12cd")).toBeNull();
  });

  it("returns null when the node id exists but its output is not motion-shaped", () => {
    const result = {
      outputs: {
        "blocking-input_ab12cd": { frames: "yes" },
      },
    };
    expect(extractNodeMotion(result, "blocking-input_ab12cd")).toBeNull();
  });

  it("returns null when the wrapper motion is missing required fields", () => {
    const result = {
      outputs: {
        "blocking-input_ab12cd": { motion: { meta: {}, skeleton: {} } },
      },
    };
    expect(extractNodeMotion(result, "blocking-input_ab12cd")).toBeNull();
  });

  it("returns null for a null result", () => {
    expect(extractNodeMotion(null, "blocking-input_ab12cd")).toBeNull();
  });

  it("returns null when outputs key is missing", () => {
    expect(extractNodeMotion({}, "blocking-input_ab12cd")).toBeNull();
  });

  it("returns null when the node value is a non-motion primitive", () => {
    const result = {
      outputs: {
        "blocking-input_ab12cd": 42,
      },
    };
    expect(extractNodeMotion(result, "blocking-input_ab12cd")).toBeNull();
  });
});

/* ── isNeutralMotionDoc ──────────────────────────────────────────────────── */

describe("isNeutralMotionDoc", () => {
  it("returns true for a well-formed doc", () => {
    expect(isNeutralMotionDoc(miniSkeleton())).toBe(true);
  });

  it("returns false for null / primitives / non-motion objects", () => {
    expect(isNeutralMotionDoc(null)).toBe(false);
    expect(isNeutralMotionDoc(undefined)).toBe(false);
    expect(isNeutralMotionDoc(42)).toBe(false);
    expect(isNeutralMotionDoc({ meta: {}, skeleton: {} })).toBe(false);
    expect(isNeutralMotionDoc({ frames: "yes" })).toBe(false);
  });
});

/* ── absolutePositions ───────────────────────────────────────────────────── */

describe("absolutePositions", () => {
  it("computes correct absolute positions for frame 0", () => {
    const motion = miniSkeleton();
    const abs = absolutePositions(motion, 0);

    // Root: rest [0,0,0] + local [0,0,0] = [0,0,0]
    expect(abs.Root).toEqual([0, 0, 0]);
    // Hips: RootAbs [0,0,0] + local [0,0.5,0] = [0,0.5,0]
    expect(abs.Hips).toEqual([0, 0.5, 0]);
    // Spine: HipsAbs [0,0.5,0] + local [0,0.3,0] = [0,0.8,0]
    expect(abs.Spine).toEqual([0, 0.8, 0]);
  });

  it("accumulates correctly when translations change across frames", () => {
    const motion = miniSkeleton();
    const abs = absolutePositions(motion, 1);

    // Root: [0,0,0]
    expect(abs.Root).toEqual([0, 0, 0]);
    // Hips: RootAbs + [1,0.5,0] = [1, 0.5, 0]
    expect(abs.Hips).toEqual([1, 0.5, 0]);
    // Spine: HipsAbs + [0,0.3,0] = [1, 0.8, 0]
    expect(abs.Spine).toEqual([1, 0.8, 0]);
  });

  it("returns empty object when frames array is empty", () => {
    const motion = miniSkeleton();
    motion.frames = [];
    expect(absolutePositions(motion, 0)).toEqual({});
  });

  it("clamps frameIndex to last frame when out of range", () => {
    const motion = miniSkeleton();
    const abs = absolutePositions(motion, 999);
    // Should match frame 1 (index 1, the last frame).
    expect(abs.Hips).toEqual([1, 0.5, 0]);
  });

  it("uses rest_position as fallback when bone is missing from transforms", () => {
    const motion = miniSkeleton();
    // Remove Spine from frame 0 transforms.
    delete motion.frames[0].pose.transforms.Spine;
    const abs = absolutePositions(motion, 0);

    // Spine should use rest_position [0,2,0] as local offset.
    // HipsAbs = [0, 0.5, 0], SpineAbs = [0, 0.5, 0] + [0, 2, 0] = [0, 2.5, 0]
    expect(abs.Spine).toEqual([0, 2.5, 0]);
  });

  it("returns empty object when frameIndex is negative", () => {
    const motion = miniSkeleton();
    const abs = absolutePositions(motion, -5);
    // Should clamp to 0 and return valid positions.
    expect(abs.Root).toEqual([0, 0, 0]);
  });
});

/* ── drawBones ───────────────────────────────────────────────────────────── */

describe("drawBones", () => {
  it("returns parent-child pairs excluding Root as child", () => {
    const motion = miniSkeleton();
    const pairs = drawBones(motion);

    // Hips → Root (child Hips), Spine → Hips (child Spine).
    // Root has no parent so it's skipped. Root is never a child (filtered).
    expect(pairs).toEqual([
      { parent: "Root", child: "Hips" },
      { parent: "Hips", child: "Spine" },
    ]);
  });

  it("returns empty array for a single-bone skeleton", () => {
    const motion = miniSkeleton();
    motion.skeleton.bones = {
      Root: { name: "Root", parent: null, rest_position: [0, 0, 0] },
    };
    expect(drawBones(motion)).toEqual([]);
  });

  it("handles a skeleton where a bone has parent that is not Root", () => {
    const motion = miniSkeleton();
    motion.skeleton.bones = {
      Root: { name: "Root", parent: null, rest_position: [0, 0, 0] },
      L_Hand: { name: "L_Hand", parent: "Spine", rest_position: [0, 0, 0] },
      Spine: { name: "Spine", parent: "Root", rest_position: [0, 0, 0] },
    };
    const pairs = drawBones(motion);
    expect(pairs).toContainEqual({ parent: "Root", child: "Spine" });
    expect(pairs).toContainEqual({ parent: "Spine", child: "L_Hand" });
    expect(pairs).toHaveLength(2);
  });
});
