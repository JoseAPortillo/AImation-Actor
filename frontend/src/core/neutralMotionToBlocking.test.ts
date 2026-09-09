import { describe, it, expect } from "vitest";
import type { NeutralMotionDoc, Transform3D, MotionFrame } from "../api/types";
import {
  isNeutralMotionDoc,
  convertNeutralMotionToBlockingInput,
  neutralMotionToBlockingJson,
  BLOCKING_FPS,
  MAX_CONVERTED_KEYPOSES,
} from "./neutralMotionToBlocking";

const identity: Transform3D = {
  translation: [0, 0, 0],
  rotation: [1, 0, 0, 0],
  scale: [1, 1, 1],
};

function makeSkeleton() {
  return {
    bones: {
      Root: { name: "Root", parent: null, rest_position: [0, 0, 0] as [number, number, number] },
      Head: { name: "Head", parent: "Root", rest_position: [0, 1, 0] as [number, number, number] },
    },
  };
}

function makeFrame(frameNum: number, time: number): MotionFrame {
  return {
    frame: frameNum,
    time,
    pose: {
      transforms: {
        Root: { ...identity },
        Head: { ...identity },
      },
    },
  };
}

function makeDoc(
  overrides: Partial<NeutralMotionDoc> & { frames: MotionFrame[] },
): NeutralMotionDoc {
  return {
    meta: {
      version: "1.0",
      fps: 24,
      units: "meters",
      up_axis: "Y-up",
      source_type: "video",
      duration_frames: 3,
      style: "neutral",
      model_version: "v1",
      graph_hash: "abc",
    },
    skeleton: makeSkeleton(),
    contacts: {},
    keyposes: [],
    tracking: { confidence_per_frame: [] },
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// isNeutralMotionDoc
// ---------------------------------------------------------------------------
describe("isNeutralMotionDoc", () => {
  it("returns true for a doc with frames + skeleton + meta", () => {
    expect(isNeutralMotionDoc(makeDoc({ frames: [] }))).toBe(true);
  });

  it("returns false for a plain BlockingInput payload", () => {
    expect(isNeutralMotionDoc({ keyposes: [{ frame: 1, pose: {} }] })).toBe(false);
  });

  it("returns false for null", () => {
    expect(isNeutralMotionDoc(null)).toBe(false);
  });

  it("returns false for a number", () => {
    expect(isNeutralMotionDoc(42)).toBe(false);
  });

  it("returns false for a string", () => {
    expect(isNeutralMotionDoc("hello")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// convertNeutralMotionToBlockingInput — sampling (empty keyposes)
// ---------------------------------------------------------------------------
describe("convertNeutralMotionToBlockingInput", () => {
  it("samples ALL frames when keyposes empty and frames <= MAX_CONVERTED_KEYPOSES", () => {
    const frames = [makeFrame(1, 0), makeFrame(2, 0.5), makeFrame(3, 1.0)];
    const doc = makeDoc({ frames });
    const result = convertNeutralMotionToBlockingInput(doc)!;

    expect(result).not.toBeNull();
    expect(result.keyposes).toHaveLength(3);
    // time 0 → max(1, round(0)) = 1
    expect(result.keyposes[0].frame).toBe(1);
    expect(result.keyposes[0].weight).toBe(1.0);
    expect(result.keyposes[0].pose).toEqual(frames[0].pose.transforms);

    // time 0.5 → max(1, round(12)) = 12
    expect(result.keyposes[1].frame).toBe(12);
    expect(result.keyposes[1].weight).toBe(1.0);

    // time 1.0 → max(1, round(24)) = 24
    expect(result.keyposes[2].frame).toBe(24);
    expect(result.keyposes[2].weight).toBe(1.0);
  });

  it("FPS rebase: time 1.0 → blocking frame 24", () => {
    const doc = makeDoc({ frames: [makeFrame(1, 1.0)] });
    const result = convertNeutralMotionToBlockingInput(doc)!;
    expect(result.keyposes).toHaveLength(1);
    expect(result.keyposes[0].frame).toBe(24);
  });

  it("returns null when all candidates have empty poses", () => {
    const frame: MotionFrame = {
      frame: 1,
      time: 0,
      pose: { transforms: {} },
    };
    const doc = makeDoc({ frames: [frame] });
    expect(convertNeutralMotionToBlockingInput(doc)).toBeNull();
  });

  it("returns null when frames array is empty", () => {
    expect(convertNeutralMotionToBlockingInput(makeDoc({ frames: [] }))).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// convertNeutralMotionToBlockingInput — authored keyposes
// ---------------------------------------------------------------------------
describe("convertNeutralMotionToBlockingInput (authored keyposes)", () => {
  it("uses authored keyposes when present", () => {
    const frames = [makeFrame(1, 0), makeFrame(2, 0.04), makeFrame(3, 0.5)];
    const doc = makeDoc({
      frames,
      keyposes: [{ frame: 2, weight: 0.5 }],
    });
    const result = convertNeutralMotionToBlockingInput(doc)!;

    expect(result.keyposes).toHaveLength(1);
    // frame 2 has time 0.04 → max(1, round(0.96)) = 1
    expect(result.keyposes[0].frame).toBe(1);
    expect(result.keyposes[0].weight).toBe(0.5);
    expect(result.keyposes[0].pose).toEqual(frames[1].pose.transforms);
  });

  it("skips authored keyposes whose frame is not found in doc.frames", () => {
    const frames = [makeFrame(1, 0), makeFrame(2, 0.5)];
    const doc = makeDoc({
      frames,
      keyposes: [{ frame: 99, weight: 1.0 }],
    });
    expect(convertNeutralMotionToBlockingInput(doc)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// convertNeutralMotionToBlockingInput — collision dedupe
// ---------------------------------------------------------------------------
describe("convertNeutralMotionToBlockingInput (collision dedupe)", () => {
  it("dedupes frames rounding to the same blocking frame, keeping the later one", () => {
    // time 0.02 → round(0.48) = 0 → max(1, 0) = 1
    // time 0.04 → round(0.96) = 1 → max(1, 1) = 1
    // Both map to blocking frame 1. The later (0.04) should win.
    const frame1 = makeFrame(1, 0.02);
    const frame2 = makeFrame(2, 0.04);
    const doc = makeDoc({ frames: [frame1, frame2] });
    const result = convertNeutralMotionToBlockingInput(doc)!;

    expect(result.keyposes).toHaveLength(1);
    expect(result.keyposes[0].frame).toBe(1);
    expect(result.keyposes[0].pose).toEqual(frame2.pose.transforms);
  });
});

// ---------------------------------------------------------------------------
// convertNeutralMotionToBlockingInput — dense doc sampling
// ---------------------------------------------------------------------------
describe("convertNeutralMotionToBlockingInput (dense doc sampling)", () => {
  it("samples exactly MAX_CONVERTED_KEYPOSES including first and last", () => {
    const total = MAX_CONVERTED_KEYPOSES + 500;
    const frames: MotionFrame[] = [];
    for (let i = 0; i < total; i++) {
      // Whole-second times so the 24fps rebase produces distinct blocking
      // frames (no dedupe collisions) — isolates the sampling behavior.
      frames.push(makeFrame(i + 1, i));
    }
    const doc = makeDoc({ frames });
    const result = convertNeutralMotionToBlockingInput(doc)!;

    expect(result.keyposes).toHaveLength(MAX_CONVERTED_KEYPOSES);

    // First frame should be sampled (time 0 → blocking frame 1).
    expect(result.keyposes[0].frame).toBe(1);
    // Last frame should be sampled (time total-1 → blocking frame (total-1)*24).
    expect(result.keyposes[result.keyposes.length - 1].frame).toBe((total - 1) * 24);
  });
});

// ---------------------------------------------------------------------------
// convertNeutralMotionToBlockingInput — skeleton passthrough
// ---------------------------------------------------------------------------
describe("convertNeutralMotionToBlockingInput (skeleton passthrough)", () => {
  it("includes skeleton when doc has one", () => {
    const doc = makeDoc({ frames: [makeFrame(1, 0)] });
    const result = convertNeutralMotionToBlockingInput(doc)!;
    expect(result.skeleton).toBeDefined();
    expect(result.skeleton!.bones).toHaveProperty("Root");
  });

  it("omits skeleton when doc lacks one", () => {
    const doc = makeDoc({ frames: [makeFrame(1, 0)], skeleton: undefined as unknown as never });
    const result = convertNeutralMotionToBlockingInput(doc)!;
    expect(result.skeleton).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// neutralMotionToBlockingJson
// ---------------------------------------------------------------------------
describe("neutralMotionToBlockingJson", () => {
  it("converts a doc JSON string with a note mentioning keypose count and fps", () => {
    const doc = makeDoc({ frames: [makeFrame(1, 0), makeFrame(2, 0.5), makeFrame(3, 1.0)] });
    const result = neutralMotionToBlockingJson(JSON.stringify(doc));

    expect(result.json).not.toBeNull();
    expect(result.note).toContain("3 keyposes");
    expect(result.note).toContain(`${BLOCKING_FPS} fps`);
  });

  it("returns json null + note null for a plain blocking payload", () => {
    const payload = { keyposes: [{ frame: 1, pose: {} }] };
    const result = neutralMotionToBlockingJson(JSON.stringify(payload));
    expect(result.json).toBeNull();
    expect(result.note).toBeNull();
  });

  it("returns json null + unconvertible note for a doc with empty frames and keyposes", () => {
    const doc = makeDoc({ frames: [], keyposes: [] });
    const result = neutralMotionToBlockingJson(JSON.stringify(doc));
    expect(result.json).toBeNull();
    expect(result.note).toContain("no usable frames or keyposes");
  });

  it("returns json null + note null for invalid JSON text", () => {
    const result = neutralMotionToBlockingJson("{not valid json");
    expect(result.json).toBeNull();
    expect(result.note).toBeNull();
  });
});
