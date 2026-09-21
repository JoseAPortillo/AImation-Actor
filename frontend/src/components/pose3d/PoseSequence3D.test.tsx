/**
 * PoseSequence3D component tests.
 *
 * Same canvas strategy as MotionViewer.test.tsx: `getContext` is mocked to
 * return null for this test file only, so the component renders its controls
 * without drawing. Assertions cover the controls (play/pause, scrub, reset
 * view, pose label), the empty state, playback label advance with fake
 * timers, and prop-change re-renders. NO pixel assertions — drawing lives in
 * the exported `renderScene` (core `pose3d.test.ts` covers the math).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { PoseSequence3D } from "./PoseSequence3D";
import type { DetectedKeypoint3D } from "../../api/types";

/* ── canvas mock (file-scoped, restored after each test) ─────────────────── */

const originalGetContext = HTMLCanvasElement.prototype.getContext;

beforeEach(() => {
  // Return null so the component skips drawing but renders controls.
  HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as never;
});

afterEach(() => {
  HTMLCanvasElement.prototype.getContext = originalGetContext;
  vi.useRealTimers();
});

/* ── fixture ─────────────────────────────────────────────────────────────── */

function kp(
  label: string,
  x: number,
  y: number,
  z = 0.5,
  confidence = 0.9,
): DetectedKeypoint3D {
  return { label, x, y, z, confidence };
}

/** A lifted COCO pose whose keypoints drift slightly per frame. */
function makeFrames(count: number): DetectedKeypoint3D[][] {
  return Array.from({ length: count }, (_, i) => [
    kp("nose", 0.5, 0.25 + i * 0.05, 0.5 + i * 0.05),
    kp("left_shoulder", 0.4, 0.35, 0.6),
    kp("right_shoulder", 0.6, 0.35, 0.4),
  ]);
}

/* ── tests ───────────────────────────────────────────────────────────────── */

describe("PoseSequence3D", () => {
  it("renders play, reset view, scrub and the pose label on mount", () => {
    render(<PoseSequence3D frames={makeFrames(3)} />);
    expect(screen.getByTestId("pose3d-play")).toHaveTextContent("Play");
    expect(screen.getByTestId("pose3d-reset")).toHaveTextContent("Reset view");
    expect(screen.getByTestId("pose3d-pose-label")).toHaveTextContent("Pose 1/3");
    expect(screen.getByTestId("pose3d-scrub")).toBeInTheDocument();
  });

  it("toggles to Pause when play is clicked and back to Play when paused again", () => {
    render(<PoseSequence3D frames={makeFrames(3)} />);
    fireEvent.click(screen.getByTestId("pose3d-play"));
    expect(screen.getByTestId("pose3d-play")).toHaveTextContent("Pause");
    fireEvent.click(screen.getByTestId("pose3d-play"));
    expect(screen.getByTestId("pose3d-play")).toHaveTextContent("Play");
  });

  it("displays the empty state when frames is empty", () => {
    render(<PoseSequence3D frames={[]} />);
    expect(screen.getByTestId("pose3d-empty")).toHaveTextContent("No poses marked yet");
    expect(screen.queryByTestId("pose3d-play")).not.toBeInTheDocument();
    expect(screen.queryByTestId("pose3d-reset")).not.toBeInTheDocument();
    expect(screen.queryByTestId("pose3d-scrub")).not.toBeInTheDocument();
  });

  it("scrub input has the correct max attribute", () => {
    render(<PoseSequence3D frames={makeFrames(5)} />);
    expect(screen.getByTestId("pose3d-scrub")).toHaveAttribute("max", "4");
  });

  it("scrubbing updates the pose label and stops playback", () => {
    render(<PoseSequence3D frames={makeFrames(3)} />);
    fireEvent.click(screen.getByTestId("pose3d-play"));
    expect(screen.getByTestId("pose3d-play")).toHaveTextContent("Pause");
    fireEvent.change(screen.getByTestId("pose3d-scrub"), { target: { value: "1" } });
    expect(screen.getByTestId("pose3d-pose-label")).toHaveTextContent("Pose 2/3");
    expect(screen.getByTestId("pose3d-play")).toHaveTextContent("Play");
  });

  it("play advances the pose label over time and loops (fake timers)", async () => {
    vi.useFakeTimers();
    render(<PoseSequence3D frames={makeFrames(3)} />);
    fireEvent.click(screen.getByTestId("pose3d-play"));

    // ~2000ms per segment: after one segment the label advanced one pose.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByTestId("pose3d-pose-label")).toHaveTextContent("Pose 2/3");

    // Past the end of the sequence it loops back to the first pose.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.getByTestId("pose3d-pose-label")).toHaveTextContent("Pose 1/3");
  });

  it("re-renders when the frames prop changes", () => {
    const { rerender } = render(<PoseSequence3D frames={makeFrames(2)} />);
    expect(screen.getByTestId("pose3d-pose-label")).toHaveTextContent("Pose 1/2");
    expect(screen.getByTestId("pose3d-scrub")).toHaveAttribute("max", "1");

    rerender(<PoseSequence3D frames={makeFrames(4)} />);
    expect(screen.getByTestId("pose3d-pose-label")).toHaveTextContent("Pose 1/4");
    expect(screen.getByTestId("pose3d-scrub")).toHaveAttribute("max", "3");
  });

  it("reset view survives a drag and restores the default orbit (controls smoke)", () => {
    render(<PoseSequence3D frames={makeFrames(3)} />);
    const canvas = screen.getByTestId("pose3d-canvas");

    fireEvent.pointerDown(canvas, { clientX: 10, clientY: 10 });
    fireEvent.pointerMove(window, { clientX: 60, clientY: 40 });
    fireEvent.pointerUp(window);

    fireEvent.click(screen.getByTestId("pose3d-reset"));
    expect(screen.getByTestId("pose3d-reset")).toHaveTextContent("Reset view");
    // Controls keep working after orbiting and resetting.
    fireEvent.click(screen.getByTestId("pose3d-play"));
    expect(screen.getByTestId("pose3d-play")).toHaveTextContent("Pause");
  });
});