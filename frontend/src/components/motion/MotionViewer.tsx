/**
 * Stick-figure 2D motion viewer.
 *
 * Renders a neutral-motion skeleton as lines on a <canvas>.  The drawing
 * logic is extracted into the exported `renderFrame` function so it can be
 * tested independently of React and the canvas DOM (see MotionViewer.test.tsx).
 *
 * **Canvas guard**: In jsdom (and other non-browser environments)
 * `HTMLCanvasElement.prototype.getContext` may return `null`.  The component
 * handles this gracefully — it renders the controls but simply skips drawing.
 * This avoids introducing a global canvas mock that would be fragile across
 * the test suite.
 *
 * **Playback**: Uses `setInterval` at the motion's declared fps.  Chose
 * `setInterval` over `requestAnimationFrame` because the latter couples
 * playback speed to the display refresh rate (144 Hz ≠ 24 fps) and would
 * require manual dt bookkeeping.  `setInterval` gives frame-accurate timing
 * for offline motion data.  No loop: playback stops on the last frame.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { NeutralMotionDoc, Vec3 } from "../../api/types";
import { absolutePositions, drawBones } from "../../core/motionView";

/* ── canvas drawing (exported for testability) ───────────────────────────── */

/**
 * Draw a single frame of the stick figure onto `ctx`.
 *
 * Pure function — no side effects beyond what `ctx` draws.  Exported so
 * integration tests can call it directly if needed, while the component
 * test suite validates controls instead of pixels.
 */
export function renderFrame(
  ctx: CanvasRenderingContext2D,
  motion: NeutralMotionDoc,
  frameIndex: number,
): void {
  const { width, height } = ctx.canvas;
  const abs = absolutePositions(motion, frameIndex);
  const keys = Object.keys(abs);
  if (keys.length === 0) return;

  // Compute bounding box.
  let xmin = Infinity, xmax = -Infinity;
  let ymin = Infinity, ymax = -Infinity;
  for (const k of keys) {
    const p = abs[k] as Vec3;
    if (p[0] < xmin) xmin = p[0];
    if (p[0] > xmax) xmax = p[0];
    if (p[1] < ymin) ymin = p[1];
    if (p[1] > ymax) ymax = p[1];
  }

  const spanX = xmax - xmin || 1;
  const spanY = ymax - ymin || 1;
  const padding = 40;
  const drawW = width - padding * 2;
  const drawH = height - padding * 2;
  const scale = Math.min(drawW / spanX, drawH / spanY, 4);

  const cx = width / 2;
  const cy = height / 2;
  const midX = (xmin + xmax) / 2;
  const midY = (ymin + ymax) / 2;

  const project = (p: Vec3): [number, number] => {
    const sx = cx + (p[0] - midX) * scale;
    const sy = cy - (p[1] - midY) * scale; // invert Y
    return [sx, sy];
  };

  const pairs = drawBones(motion);
  ctx.clearRect(0, 0, width, height);

  ctx.strokeStyle = "#60a5fa";
  ctx.lineWidth = 2;
  ctx.lineCap = "round";

  for (const { parent, child } of pairs) {
    const pp = abs[parent];
    const cp = abs[child];
    if (!pp || !cp) continue;
    const [x1, y1] = project(pp);
    const [x2, y2] = project(cp);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  }

  // Draw joints as small dots.
  ctx.fillStyle = "#f59e0b";
  for (const k of keys) {
    const [jx, jy] = project(abs[k] as Vec3);
    ctx.beginPath();
    ctx.arc(jx, jy, 3, 0, Math.PI * 2);
    ctx.fill();
  }
}

/* ── React component ─────────────────────────────────────────────────────── */

interface MotionViewerProps {
  motion: NeutralMotionDoc;
}

export function MotionViewer({ motion }: MotionViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const totalFrames = motion.frames.length;
  const fps = motion.meta?.fps ?? 24;

  // Draw whenever `frame` changes.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return; // jsdom / SSR guard
    renderFrame(ctx, motion, frame);
  }, [motion, frame]);

  // Playback timer.
  useEffect(() => {
    if (!playing) {
      if (timerRef.current != null) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }

    timerRef.current = setInterval(() => {
      setFrame((prev) => {
        if (prev >= totalFrames - 1) {
          setPlaying(false);
          return totalFrames - 1; // stop at last frame
        }
        return prev + 1;
      });
    }, 1000 / fps);

    return () => {
      if (timerRef.current != null) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [playing, fps, totalFrames]);

  const togglePlay = useCallback(() => {
    setPlaying((prev) => {
      // If at the end, restart from 0.
      if (!prev && frame >= totalFrames - 1) {
        setFrame(0);
      }
      return !prev;
    });
  }, [frame, totalFrames]);

  const onScrub = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setPlaying(false);
      setFrame(Number(e.target.value));
    },
    [],
  );

  // Empty state.
  if (totalFrames === 0) {
    return (
      <div
        data-testid="motion-empty"
        style={{
          padding: 32,
          textAlign: "center",
          color: "#9ca3af",
          fontSize: 13,
        }}
      >
        No frames to display
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <canvas
        ref={canvasRef}
        width={400}
        height={150}
        style={{
          width: "100%",
          background: "#121212",
          border: "1px solid #333",
          borderRadius: 8,
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
          data-testid="motion-play"
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
        <span data-testid="motion-frame-label">
          {frame + 1} / {totalFrames}
        </span>
        <input
          type="range"
          data-testid="motion-scrub"
          min={0}
          max={totalFrames - 1}
          value={frame}
          onChange={onScrub}
          style={{ flex: 1 }}
        />
      </div>
    </div>
  );
}
