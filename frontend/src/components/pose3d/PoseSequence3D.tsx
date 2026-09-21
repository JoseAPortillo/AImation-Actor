/**
 * Stick-figure 3D sequence viewer for marked golden poses.
 *
 * Renders EVERY marked pose as a COCO skeleton on a <canvas>, with
 * progressive per-pose coloring (first pose → last pose hue ramp) so the
 * whole sequence reads as a single motion, a ground grid at the scene floor,
 * and a subtle alpha/size depth cue by z (heuristic lift depth: larger z =
 * closer to the camera). Playback interpolates between consecutive poses with
 * `interpolatePose` and loops at the end of the sequence.
 *
 * The drawing logic is extracted into the exported `renderScene` function so
 * it can be exercised independently of React and the canvas DOM (mirrors the
 * MotionViewer `renderFrame` pattern). The component test suite validates
 * controls — play/pause, scrub, reset view, pose label, empty state — and
 * makes NO pixel assertions.
 *
 * **Canvas guard**: in jsdom (and other non-browser environments)
 * `HTMLCanvasElement.prototype.getContext` may return `null`. The component
 * then renders the controls but skips drawing (same discipline as
 * MotionViewer), so no global canvas mock is needed.
 *
 * **Playback**: `setInterval` at TICK_MS while playing. Each tick advances a
 * float `progress` by `TICK_MS / SEGMENT_MS`, so a full keyframe segment
 * lasts ~SEGMENT_MS (2000ms) and intermediate poses are drawn interpolated
 * for a smooth preview; `progress` wraps to 0 at the end (loop). Chose
 * `setInterval` over `requestAnimationFrame` for the same reason as
 * MotionViewer: deterministic, frame-accurate timing without display
 * refresh-rate coupling.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { DetectedKeypoint3D } from "../../api/types";
import { COCO_BONES } from "../../core/skeletonOverlay";
import {
  SCENE_HALF_EXTENT,
  interpolatePose,
  normalizeScene,
  projectOrthographic,
  sceneBounds,
  type ScreenPoint,
  type Vec3,
} from "../../core/pose3d";

/** Duration of one keyframe segment while playing (~2000ms per pose). */
const SEGMENT_MS = 2000;
/** Playback tick; 50 fps keeps the interpolated preview smooth. */
const TICK_MS = 40;
/** Orbit sensitivity in radians per dragged pixel. */
const ROTATION_SPEED = 0.01;
/** Pitch is clamped to ±90°; yaw is unbounded. */
const PITCH_LIMIT = Math.PI / 2;
/** Default orbit: a slight yaw + tilt so the depth axis reads. */
const DEFAULT_YAW = 0.6;
const DEFAULT_PITCH = -0.35;
/** Opacity of the ghost (non-current) keyframe skeletons. */
const GHOST_ALPHA = 0.3;

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

/** The pose to display at `progress`: interpolated between consecutive keyframes. */
function poseAt(progress: number, frames: DetectedKeypoint3D[][]): DetectedKeypoint3D[] {
  const n = frames.length;
  if (n === 0) return [];
  const i = Math.floor(progress);
  if (i >= n - 1) return frames[n - 1];
  return interpolatePose(frames[i], frames[i + 1], progress - i);
}

/** Progressive hue: first pose → last pose across a blue → red ramp. */
function hueFor(index: number, count: number): number {
  return count > 1 ? 210 - (index / (count - 1)) * 210 : 210;
}

/** Min/max z over the whole sequence, for the depth cue (span 0 → degenerate). */
function zRange(frames: DetectedKeypoint3D[][]): { min: number; max: number; span: number } {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const frame of frames) {
    for (const kp of frame) {
      if (kp.z < min) min = kp.z;
      if (kp.z > max) max = kp.z;
    }
  }
  if (!Number.isFinite(min)) return { min: 0.5, max: 0.5, span: 0 };
  return { min, max, span: max - min };
}

function traceLine(ctx: CanvasRenderingContext2D, a: ScreenPoint, b: ScreenPoint): void {
  ctx.beginPath();
  ctx.moveTo(a.x, a.y);
  ctx.lineTo(b.x, b.y);
  ctx.stroke();
}

/**
 * Draw one pose's skeleton (COCO bones + joint dots) onto `ctx`.
 *
 * Opacity and joint radius scale subtly with the keypoint depth so nearer
 * joints read stronger than farther ones against the ground grid.
 */
function drawSkeleton(
  ctx: CanvasRenderingContext2D,
  keypoints: DetectedKeypoint3D[],
  toScene: (kp: DetectedKeypoint3D) => Vec3,
  project: (p: Vec3) => ScreenPoint,
  depthOf: (z: number) => number,
  hue: number,
  alpha: number,
  lineWidth: number,
  jointRadius: number,
): void {
  const byLabel = new Map(keypoints.map((k) => [k.label, k]));
  ctx.lineCap = "round";
  for (const [a, b] of COCO_BONES) {
    const pa = byLabel.get(a);
    const pb = byLabel.get(b);
    if (!pa || !pb) continue;
    const da = depthOf(pa.z);
    const db = depthOf(pb.z);
    const boneAlpha = alpha * (0.8 + 0.2 * ((da + db) / 2));
    ctx.strokeStyle = `hsla(${hue}, 75%, 65%, ${boneAlpha})`;
    ctx.lineWidth = lineWidth;
    const p1 = project(toScene(pa));
    const p2 = project(toScene(pb));
    traceLine(ctx, p1, p2);
  }
  for (const k of keypoints) {
    const d = depthOf(k.z);
    const jointAlpha = alpha * (0.75 + 0.25 * d);
    ctx.fillStyle = `hsla(${hue}, 85%, 70%, ${jointAlpha})`;
    ctx.beginPath();
    const p = project(toScene(k));
    ctx.arc(p.x, p.y, jointRadius * (0.75 + 0.25 * d), 0, Math.PI * 2);
    ctx.fill();
  }
}

/* ── canvas drawing (exported for testability) ───────────────────────────── */

/**
 * Draw the whole 3D sequence onto `ctx` at the given playback position.
 *
 * Pure function — no side effects beyond what `ctx` draws (mirrors
 * MotionViewer's exported `renderFrame`). Ghost keyframes show the full
 * motion in progressive colors; the current (interpolated) pose is drawn on
 * top at full opacity.
 */
export function renderScene(
  ctx: CanvasRenderingContext2D,
  frames: DetectedKeypoint3D[][],
  progress: number,
  yaw: number,
  pitch: number,
): void {
  const { width, height } = ctx.canvas;
  ctx.clearRect(0, 0, width, height);
  if (frames.length === 0) return;

  const bounds = sceneBounds(frames);
  const targetSize = SCENE_HALF_EXTENT * 2;
  const depth = zRange(frames);
  const depthOf = (z: number): number => (depth.span > 0 ? (z - depth.min) / depth.span : 0.5);

  const toScene = (kp: DetectedKeypoint3D): Vec3 =>
    normalizeScene({ x: kp.x, y: kp.y, z: kp.z }, bounds, targetSize);
  const project = (p: Vec3): ScreenPoint => projectOrthographic(p, yaw, pitch, width, height);

  // Ground grid at the scene floor (minimum z of the normalized cube).
  const floor = normalizeScene({ x: 0, y: 0, z: bounds.min.z }, bounds, targetSize).z;
  ctx.strokeStyle = "rgba(96, 165, 250, 0.16)";
  ctx.lineWidth = 1;
  for (let t = -1; t <= 1.00001; t += 0.5) {
    const a = project({ x: t, y: -1, z: floor });
    const b = project({ x: t, y: 1, z: floor });
    traceLine(ctx, a, b);
    const c = project({ x: -1, y: t, z: floor });
    const d = project({ x: 1, y: t, z: floor });
    traceLine(ctx, c, d);
  }

  // Ghost keyframes: every marked pose, progressive color, low alpha.
  frames.forEach((frame, i) => {
    drawSkeleton(
      ctx,
      frame,
      toScene,
      project,
      depthOf,
      hueFor(i, frames.length),
      GHOST_ALPHA,
      1.5,
      2.5,
    );
  });

  // Current pose on top (interpolated while playing or scrubbing mid-segment).
  const current = poseAt(progress, frames);
  const currentIndex = Math.min(Math.floor(progress), frames.length - 1);
  drawSkeleton(
    ctx,
    current,
    toScene,
    project,
    depthOf,
    hueFor(currentIndex, frames.length),
    0.95,
    3,
    4,
  );
}

/* ── React component ─────────────────────────────────────────────────────── */

interface PoseSequence3DProps {
  /** Lifted 3D keypoints per marked pose, in sequence order (length 0..n). */
  frames: DetectedKeypoint3D[][];
}

export function PoseSequence3D({ frames }: PoseSequence3DProps) {
  const n = frames.length;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const dragStartRef = useRef<{ x: number; y: number } | null>(null);

  const [progress, setProgress] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [yaw, setYaw] = useState(DEFAULT_YAW);
  const [pitch, setPitch] = useState(DEFAULT_PITCH);
  const [dragging, setDragging] = useState(false);

  // Clamp the progress when the sequence shrinks (prop change).
  useEffect(() => {
    if (n === 0) return;
    setProgress((prev) => (prev > n - 1 ? Math.max(0, n - 1) : prev));
  }, [n]);

  // Redraw on mount, prop change, orbit changes, and playback ticks.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || n === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return; // jsdom / SSR guard
    renderScene(ctx, frames, progress, yaw, pitch);
  }, [frames, progress, yaw, pitch, n]);

  // Playback timer: advance progress by one tick, loop at the end.
  useEffect(() => {
    if (!playing) {
      if (timerRef.current != null) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }
    if (n < 2) {
      setPlaying(false);
      return;
    }
    timerRef.current = setInterval(() => {
      setProgress((prev) => {
        const next = prev + TICK_MS / SEGMENT_MS;
        return next >= n - 1 ? 0 : next; // loop
      });
    }, TICK_MS);
    return () => {
      if (timerRef.current != null) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [playing, n]);

  const togglePlay = useCallback(() => {
    setPlaying((prev) => !prev);
  }, []);

  const resetView = useCallback(() => {
    setYaw(DEFAULT_YAW);
    setPitch(DEFAULT_PITCH);
  }, []);

  const onScrub = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setPlaying(false);
    setProgress(Number(e.target.value));
  }, []);

  // Orbit: pointer drag rotates yaw (unbounded) and pitch (clamped to ±90°).
  const onPointerDown = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    e.currentTarget.setPointerCapture?.(e.pointerId);
    dragStartRef.current = { x: e.clientX, y: e.clientY };
    setDragging(true);
  }, []);

  useEffect(() => {
    if (!dragging) return;
    const onPointerMove = (e: PointerEvent) => {
      const last = dragStartRef.current;
      if (!last) return;
      const dx = e.clientX - last.x;
      const dy = e.clientY - last.y;
      dragStartRef.current = { x: e.clientX, y: e.clientY };
      setYaw((prev) => prev + dx * ROTATION_SPEED);
      setPitch((prev) => clamp(prev + dy * ROTATION_SPEED, -PITCH_LIMIT, PITCH_LIMIT));
    };
    const endDrag = () => {
      dragStartRef.current = null;
      setDragging(false);
    };
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", endDrag);
    window.addEventListener("pointercancel", endDrag);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", endDrag);
      window.removeEventListener("pointercancel", endDrag);
    };
  }, [dragging]);

  // Empty state.
  if (n === 0) {
    return (
      <div
        data-testid="pose3d-empty"
        style={{
          padding: 32,
          textAlign: "center",
          color: "#9ca3af",
          fontSize: 13,
        }}
      >
        No poses marked yet
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <canvas
        ref={canvasRef}
        data-testid="pose3d-canvas"
        width={480}
        height={320}
        onPointerDown={onPointerDown}
        style={{
          width: "100%",
          background: "#121212",
          border: "1px solid #333",
          borderRadius: 8,
          touchAction: "none",
          cursor: "grab",
        }}
      />
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          fontSize: 13,
          color: "#e0e0e0",
        }}
      >
        <button
          type="button"
          data-testid="pose3d-play"
          onClick={togglePlay}
          style={{
            background: "#1a1a1a",
            border: "1px solid #333",
            borderRadius: 6,
            color: "#e0e0e0",
            padding: "4px 12px",
            cursor: "pointer",
            fontSize: 13,
          }}
        >
          {playing ? "Pause" : "Play"}
        </button>
        <button
          type="button"
          data-testid="pose3d-reset"
          onClick={resetView}
          style={{
            background: "#1a1a1a",
            border: "1px solid #333",
            borderRadius: 6,
            color: "#e0e0e0",
            padding: "4px 12px",
            cursor: "pointer",
            fontSize: 13,
          }}
        >
          Reset view
        </button>
        <span data-testid="pose3d-pose-label">
          Pose {Math.min(Math.floor(progress), n - 1) + 1}/{n}
        </span>
        <input
          type="range"
          data-testid="pose3d-scrub"
          min={0}
          max={n - 1}
          step={0.01}
          value={progress}
          onChange={onScrub}
          style={{ flex: 1 }}
        />
      </div>
    </div>
  );
}