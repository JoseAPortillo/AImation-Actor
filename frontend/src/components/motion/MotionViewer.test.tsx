/**
 * MotionViewer component tests.
 *
 * **Canvas strategy**: jsdom does not implement `HTMLCanvasElement.getContext`.
 * Rather than adding a global mock that could leak into other tests, we:
 *   1. Mock `getContext` to return `null` for this test file only.
 *   2. Validate CONTROLS (play, pause, frame label, scrub) and the empty state.
 *   3. Do NOT assert pixel content — that lives in `motionView.test.ts` via
 *      pure-function tests of `absolutePositions` / `drawBones`, plus a
 *      standalone `renderFrame` call if needed.
 *
 * The `getContext` null guard in MotionViewer.tsx ensures the component never
 * crashes even when canvas is unavailable (SSR, jsdom, etc.).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MotionViewer } from "./MotionViewer";
import type { NeutralMotionDoc } from "../../api/types";

/* ── canvas mock (file-scoped, restored after each test) ─────────────────── */

const originalGetContext = HTMLCanvasElement.prototype.getContext;

beforeEach(() => {
  // Return null so the component skips drawing but renders controls.
  HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as never;
});

afterEach(() => {
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

/* ── fixture ─────────────────────────────────────────────────────────────── */

function makeMotion(frameCount = 3): NeutralMotionDoc {
  const frames = Array.from({ length: frameCount }, (_, i) => ({
    frame: i + 1,
    time: (i + 1) * 0.041,
    pose: {
      transforms: {
        Root: { translation: [0, 0, 0] as [number, number, number], rotation: [1, 0, 0, 0] as [number, number, number, number], scale: [1, 1, 1] as [number, number, number] },
        Hips: { translation: [0, 0.5 + i * 0.1, 0] as [number, number, number], rotation: [1, 0, 0, 0] as [number, number, number, number], scale: [1, 1, 1] as [number, number, number] },
      },
    },
  }));

  return {
    meta: {
      version: "1.0",
      fps: 24,
      units: "m",
      up_axis: "Y",
      source_type: "neutral",
      duration_frames: frameCount,
      style: "default",
      model_version: "0.1",
      graph_hash: "abc",
    },
    skeleton: {
      bones: {
        Root: { name: "Root", parent: null, rest_position: [0, 0, 0] },
        Hips: { name: "Hips", parent: "Root", rest_position: [0, 1, 0] },
      },
    },
    frames,
  };
}

/* ── tests ───────────────────────────────────────────────────────────────── */

describe("MotionViewer", () => {
  it("renders play button, frame label, and scrub on mount", () => {
    render(<MotionViewer motion={makeMotion()} />);
    expect(screen.getByTestId("motion-play")).toHaveTextContent("Play");
    expect(screen.getByTestId("motion-frame-label")).toHaveTextContent("1 / 3");
    expect(screen.getByTestId("motion-scrub")).toBeInTheDocument();
  });

  it("toggles to Pause when play is clicked", () => {
    render(<MotionViewer motion={makeMotion()} />);
    fireEvent.click(screen.getByTestId("motion-play"));
    expect(screen.getByTestId("motion-play")).toHaveTextContent("Pause");
  });

  it("returns to Play when paused again", () => {
    render(<MotionViewer motion={makeMotion()} />);
    fireEvent.click(screen.getByTestId("motion-play"));
    fireEvent.click(screen.getByTestId("motion-play"));
    expect(screen.getByTestId("motion-play")).toHaveTextContent("Play");
  });

  it("displays empty state when frames array is empty", () => {
    const motion = makeMotion(0);
    render(<MotionViewer motion={motion} />);
    expect(screen.getByTestId("motion-empty")).toHaveTextContent("No frames to display");
    expect(screen.queryByTestId("motion-play")).not.toBeInTheDocument();
    expect(screen.queryByTestId("motion-scrub")).not.toBeInTheDocument();
  });

  it("scrub input has correct max attribute", () => {
    render(<MotionViewer motion={makeMotion(5)} />);
    expect(screen.getByTestId("motion-scrub")).toHaveAttribute("max", "4");
  });
});
