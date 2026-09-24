/**
 * Pure-function tests for the 3D preview math (core/pose3d.ts).
 *
 * Deterministic, no DOM, no canvas — every assertion is on numbers and
 * plain objects computed from fixed fixtures (mirrors the backend pose-lift
 * fixture shape from tests/api/test_pose.py).
 */

import { describe, it, expect } from "vitest";
import {
  SCENE_HALF_EXTENT,
  VIEWPORT_MARGIN,
  interpolatePose,
  normalizeScene,
  projectOrthographic,
  sceneBounds,
  type SceneBounds,
} from "./pose3d";
import type { DetectedKeypoint3D } from "../api/types";

/** A lifted keypoint shortcut: normalized coords + heuristic depth. */
function kp3d(
  label: string,
  x: number,
  y: number,
  z: number,
  confidence = 0.9,
): DetectedKeypoint3D {
  return { label, x, y, z, confidence };
}

/** Two COCO frames with distinct geometry (mirrors the backend fixture). */
function twoFrames(): DetectedKeypoint3D[][] {
  return [
    [
      kp3d("nose", 0.5, 0.25, 0.5, 0.98),
      kp3d("left_shoulder", 0.4, 0.35, 0.6, 0.95),
      kp3d("right_shoulder", 0.6, 0.35, 0.4, 0.95),
    ],
    [
      kp3d("nose", 0.5, 0.3, 0.55, 0.97),
      kp3d("left_wrist", 0.3, 0.5, 0.45, 0.9),
    ],
  ];
}

describe("core/pose3d — sceneBounds", () => {
  it("covers every x/y/z across all frames (stable full-sequence framing)", () => {
    const bounds = sceneBounds(twoFrames());
    expect(bounds.min).toEqual({ x: 0.3, y: 0.25, z: 0.4 });
    expect(bounds.max).toEqual({ x: 0.6, y: 0.5, z: 0.6 });
  });

  it("returns a degenerate zero cube for an empty sequence (no Infinity/NaN)", () => {
    const zero = { min: { x: 0, y: 0, z: 0 }, max: { x: 0, y: 0, z: 0 } };
    expect(sceneBounds([])).toEqual(zero);
    expect(sceneBounds([[], []])).toEqual(zero);
  });
});

describe("core/pose3d — normalizeScene", () => {
  const bounds: SceneBounds = {
    min: { x: 0.3, y: 0.25, z: 0.4 },
    max: { x: 0.6, y: 0.5, z: 0.6 },
  };

  it("maps the bounds center to the cube center (0, 0, 0)", () => {
    const center = normalizeScene({ x: 0.45, y: 0.375, z: 0.5 }, bounds, 2);
    expect(center.x).toBeCloseTo(0, 10);
    expect(center.y).toBeCloseTo(0, 10);
    expect(center.z).toBeCloseTo(0, 10);
  });

  it("maps bounds edges to the cube faces (±targetSize/2)", () => {
    const edge = normalizeScene({ x: 0.6, y: 0.25, z: 0.4 }, bounds, 2);
    // x at max → +1; raw y at min (frame top) → +1 (y-up); z at min → -1.
    expect(edge).toEqual({ x: 1, y: 1, z: -1 });
  });

  it("keeps y mathematically up: frame top (small raw y) maps to +y", () => {
    const top = normalizeScene({ x: 0.45, y: 0.25, z: 0.5 }, bounds, 2);
    const bottom = normalizeScene({ x: 0.45, y: 0.5, z: 0.5 }, bounds, 2);
    expect(top.y).toBeCloseTo(1, 10);
    expect(bottom.y).toBeCloseTo(-1, 10);
    expect(top.y).toBeGreaterThan(bottom.y);
  });

  it("falls back to 0 on a degenerate zero-range axis, any value", () => {
    const degenerate: SceneBounds = {
      min: { x: 0.3, y: 0.25, z: 0.5 },
      max: { x: 0.6, y: 0.5, z: 0.5 }, // z never varies across the sequence
    };
    const p = normalizeScene({ x: 0.45, y: 0.375, z: 0.5 }, degenerate, 2);
    expect(p.x).toBeCloseTo(0, 10);
    expect(p.y).toBeCloseTo(0, 10);
    expect(p.z).toBeCloseTo(0, 10);
    // Even an out-of-range value collapses to 0 on the flat axis.
    expect(normalizeScene({ x: 0.45, y: 0.375, z: 0.2 }, degenerate, 2).z).toBe(0);
  });

  it("scales with the requested targetSize", () => {
    const p = normalizeScene({ x: 0.6, y: 0.5, z: 0.4 }, bounds, 4);
    expect(p).toEqual({ x: 2, y: -2, z: -2 });
  });
});

describe("core/pose3d — projectOrthographic", () => {
  const width = 400;
  const height = 300;
  const cx = width / 2;
  const cy = height / 2;

  it("maps the scene center to the canvas center for any yaw/pitch", () => {
    expect(projectOrthographic({ x: 0, y: 0, z: 0 }, 0, 0, width, height)).toEqual({ x: cx, y: cy });
    expect(
      projectOrthographic({ x: 0, y: 0, z: 0 }, Math.PI / 2, Math.PI / 2, width, height),
    ).toEqual({ x: cx, y: cy });
  });

  it("keeps every unit-cube corner inside the canvas at yaw=0/pitch=0", () => {
    for (const x of [-1, 1]) {
      for (const y of [-1, 1]) {
        for (const z of [-1, 1]) {
          const p = projectOrthographic({ x, y, z }, 0, 0, width, height);
          expect(p.x).toBeGreaterThanOrEqual(0);
          expect(p.x).toBeLessThanOrEqual(width);
          expect(p.y).toBeGreaterThanOrEqual(0);
          expect(p.y).toBeLessThanOrEqual(height);
        }
      }
    }
  });

  it("fits the cube inside min(width,height)/2 minus the margin", () => {
    const p = projectOrthographic({ x: 1, y: 1, z: 1 }, 0, 0, width, height);
    const fitHalf = Math.min(width, height) / 2 - VIEWPORT_MARGIN;
    expect(p.x).toBeCloseTo(cx + (fitHalf / SCENE_HALF_EXTENT), 10);
    expect(p.y).toBeCloseTo(cy - (fitHalf / SCENE_HALF_EXTENT), 10);
  });

  it("rotating by π/2 stays finite and moves both screen axes", () => {
    const point = { x: 1, y: 0.5, z: 0.75 };
    const identity = projectOrthographic(point, 0, 0, width, height);
    const rotated = projectOrthographic(point, Math.PI / 2, Math.PI / 2, width, height);
    expect(Number.isFinite(rotated.x)).toBe(true);
    expect(Number.isFinite(rotated.y)).toBe(true);
    expect(Math.abs(rotated.x - identity.x)).toBeGreaterThan(1);
    expect(Math.abs(rotated.y - identity.y)).toBeGreaterThan(1);
  });
});

describe("core/pose3d — interpolatePose", () => {
  const prev = [
    kp3d("nose", 0.5, 0.25, 0.5, 0.98),
    kp3d("left_shoulder", 0.4, 0.35, 0.6, 0.95),
  ];
  const next = [
    kp3d("nose", 0.6, 0.3, 0.55, 0.97),
    kp3d("left_shoulder", 0.45, 0.4, 0.65, 0.9),
  ];

  it("returns exact prev values at t=0 and next values at t=1", () => {
    const at0 = interpolatePose(prev, next, 0);
    expect(at0).toEqual(prev);
    const at1 = interpolatePose(prev, next, 1);
    expect(at1.map((k) => k.label)).toEqual(["nose", "left_shoulder"]);
    at1.forEach((k, i) => {
      expect(k.x).toBeCloseTo(next[i].x, 10);
      expect(k.y).toBeCloseTo(next[i].y, 10);
      expect(k.z).toBeCloseTo(next[i].z, 10);
      expect(k.confidence).toBeCloseTo(next[i].confidence, 10);
    });
  });

  it("returns the per-label average at t=0.5", () => {
    const mid = interpolatePose(prev, next, 0.5);
    expect(mid).toHaveLength(2);
    expect(mid[0].label).toBe("nose");
    expect(mid[0].x).toBeCloseTo(0.55, 10);
    expect(mid[0].y).toBeCloseTo(0.275, 10);
    expect(mid[0].z).toBeCloseTo(0.525, 10);
    expect(mid[0].confidence).toBeCloseTo(0.975, 10);
    expect(mid[1].label).toBe("left_shoulder");
    expect(mid[1].x).toBeCloseTo(0.425, 10);
    expect(mid[1].y).toBeCloseTo(0.375, 10);
    expect(mid[1].z).toBeCloseTo(0.625, 10);
    expect(mid[1].confidence).toBeCloseTo(0.925, 10);
  });

  it("clamps t into [0, 1]", () => {
    expect(interpolatePose(prev, next, -3)).toEqual(prev);
    // t > 1 is bit-identical to t = 1 (same deterministic expression).
    expect(interpolatePose(prev, next, 7)).toEqual(interpolatePose(prev, next, 1));
  });

  it("returns only labels present in BOTH poses, in prev order", () => {
    const nextMissingA = [
      kp3d("nose", 0.6, 0.3, 0.55, 0.97),
      kp3d("right_shoulder", 0.65, 0.35, 0.4, 0.9),
    ];
    const partial = interpolatePose(prev, nextMissingA, 0.5);
    expect(partial.map((k) => k.label)).toEqual(["nose"]);
    expect(interpolatePose(prev, [], 0.5)).toEqual([]);
    expect(interpolatePose([], nextMissingA, 0.5)).toEqual([]);
  });
});