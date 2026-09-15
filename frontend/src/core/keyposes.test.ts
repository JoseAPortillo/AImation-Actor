import { describe, it, expect } from "vitest";
import { applyKeyposes } from "./keyposes";
import type { NeutralMotionDoc } from "../api/types";

function makeDoc(durationFrames: number): NeutralMotionDoc {
  return {
    meta: {
      version: "1.0",
      fps: 30,
      units: "meters",
      up_axis: "y",
      source_type: "video",
      duration_frames: durationFrames,
      style: "neutral",
      model_version: "test",
      graph_hash: "abc",
    },
    skeleton: { bones: {} },
    frames: [],
  };
}

/** Minimal pin shape used by applyKeyposes (structural compatibility with Pin). */
interface KeyposeSource {
  frame: number;
  confidence: number | null;
}

describe("core/keyposes — applyKeyposes pure merge", () => {
  it("merges in-range pins sorted by frame with weight = confidence ?? 1", () => {
    const doc = makeDoc(10);
    const pins: KeyposeSource[] = [
      { frame: 5, confidence: 0.8 },
      { frame: 2, confidence: null },
      { frame: 8, confidence: 0.5 },
    ];
    const result = applyKeyposes(doc, pins);
    expect(result.keyposes).toEqual([
      { frame: 2, weight: 1 },
      { frame: 5, weight: 0.8 },
      { frame: 8, weight: 0.5 },
    ]);
  });

  it("excludes pins with frame > duration_frames", () => {
    const doc = makeDoc(5);
    const pins: KeyposeSource[] = [
      { frame: 1, confidence: 0.9 },
      { frame: 6, confidence: 0.8 },
      { frame: 5, confidence: 0.7 },
    ];
    const result = applyKeyposes(doc, pins);
    expect(result.keyposes).toEqual([
      { frame: 1, weight: 0.9 },
      { frame: 5, weight: 0.7 },
    ]);
  });

  it("returns the doc unchanged when no pins are in range", () => {
    const doc = makeDoc(3);
    const pins: KeyposeSource[] = [
      { frame: 5, confidence: 0.9 },
      { frame: 10, confidence: 0.8 },
    ];
    const result = applyKeyposes(doc, pins);
    expect(result).toBe(doc);
    expect(result.keyposes).toBeUndefined();
  });

  it("returns the doc unchanged when pins array is empty", () => {
    const doc = makeDoc(10);
    const result = applyKeyposes(doc, []);
    expect(result).toBe(doc);
    expect(result.keyposes).toBeUndefined();
  });

  it("excludes pins with frame < 1 (frame >= 1 required)", () => {
    const doc = makeDoc(10);
    const pins: KeyposeSource[] = [
      { frame: 0, confidence: 0.9 },
      { frame: -1, confidence: 0.7 },
    ];
    const result = applyKeyposes(doc, pins);
    expect(result).toBe(doc);
    expect(result.keyposes).toBeUndefined();
  });

  it("preserves insertion order of pins at the same frame (stable sort)", () => {
    const doc = makeDoc(10);
    const pins: KeyposeSource[] = [
      { frame: 5, confidence: 0.7 },
      { frame: 5, confidence: 0.9 },
    ];
    const result = applyKeyposes(doc, pins);
    expect(result.keyposes).toHaveLength(2);
    expect(result.keyposes![0]).toEqual({ frame: 5, weight: 0.7 });
    expect(result.keyposes![1]).toEqual({ frame: 5, weight: 0.9 });
  });
});
