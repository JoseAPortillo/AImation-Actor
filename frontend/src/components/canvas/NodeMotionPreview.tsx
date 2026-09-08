/**
 * Compact motion preview for inline display inside a node card.
 *
 * Reuses `renderFrame` from MotionViewer — no duplicated drawing logic.
 * Playback uses the same `setInterval` approach (frame-accurate for offline
 * motion data).  No scrub slider — the 260px card is too narrow.
 *
 * Timer discipline: the interval only runs while `playing` is true, so many
 * nodes with previews do not spin timers simultaneously.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { NeutralMotionDoc } from "../../api/types";
import { renderFrame } from "../motion/MotionViewer";

interface NodeMotionPreviewProps {
  motion: NeutralMotionDoc;
}

export function NodeMotionPreview({ motion }: NodeMotionPreviewProps) {
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

  // Playback timer — only active while playing.
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
          return totalFrames - 1;
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
      if (!prev && frame >= totalFrames - 1) {
        setFrame(0);
      }
      return !prev;
    });
  }, [frame, totalFrames]);

  // Empty state.
  if (totalFrames === 0) {
    return (
      <div
        data-testid="node-preview-empty"
        style={{
          fontSize: 10,
          color: "#9ca3af",
          textAlign: "center",
          padding: 12,
          marginBottom: 4,
        }}
      >
        No frames to display
      </div>
    );
  }

  return (
    <div
      data-testid="node-preview"
      style={{ marginBottom: 4 }}
    >
      <canvas
        ref={canvasRef}
        width={240}
        height={80}
        data-testid="node-preview-canvas"
        style={{
          width: "100%",
          display: "block",
          background: "#121212",
          border: "1px solid #333",
          borderRadius: 6,
        }}
      />
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginTop: 2,
          fontSize: 10,
          color: "#e0e0e0",
        }}
      >
        <button
          type="button"
          data-testid="node-preview-play"
          onClick={togglePlay}
          style={{
            background: "#1a1a1a",
            border: "1px solid #333",
            borderRadius: 4,
            color: "#e0e0e0",
            padding: "2px 8px",
            cursor: "pointer",
            fontSize: 10,
          }}
        >
          {playing ? "Pause" : "Play"}
        </button>
        <span data-testid="node-preview-frame">
          {frame + 1} / {totalFrames}
        </span>
      </div>
    </div>
  );
}
