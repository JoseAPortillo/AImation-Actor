/**
 * NodeMotionPreview component tests.
 *
 * Same canvas strategy as MotionViewer.test.tsx: jsdom has no canvas
 * implementation, so `getContext` is mocked to return null for this file.
 * We validate controls (play/pause toggle, frame label advance) and the empty
 * state rather than pixel content.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { NodeMotionPreview } from "./NodeMotionPreview";
import type { NeutralMotionDoc } from "../../api/types";

const originalGetContext = HTMLCanvasElement.prototype.getContext;

beforeEach(() => {
  HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as never;
  vi.useFakeTimers();
});

afterEach(() => {
  HTMLCanvasElement.prototype.getContext = originalGetContext;
  vi.useRealTimers();
});

function makeMotion(frameCount = 3): NeutralMotionDoc {
  const frames = Array.from({ length: frameCount }, (_, i) => ({
    frame: i + 1,
    time: (i + 1) * 0.041,
    pose: {
      transforms: {
        Root: {
          translation: [0, 0, 0] as [number, number, number],
          rotation: [1, 0, 0, 0] as [number, number, number, number],
          scale: [1, 1, 1] as [number, number, number],
        },
        Hips: {
          translation: [0, 0.5 + i * 0.1, 0] as [number, number, number],
          rotation: [1, 0, 0, 0] as [number, number, number, number],
          scale: [1, 1, 1] as [number, number, number],
        },
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

describe("NodeMotionPreview", () => {
  it("renders canvas, play button, and frame label", () => {
    render(<NodeMotionPreview motion={makeMotion()} />);
    expect(screen.getByTestId("node-preview")).toBeInTheDocument();
    expect(screen.getByTestId("node-preview-canvas")).toBeInTheDocument();
    expect(screen.getByTestId("node-preview-play")).toHaveTextContent("Play");
    expect(screen.getByTestId("node-preview-frame")).toHaveTextContent("1 / 3");
  });

  it("toggles to Pause when Play is clicked", () => {
    render(<NodeMotionPreview motion={makeMotion()} />);
    fireEvent.click(screen.getByTestId("node-preview-play"));
    expect(screen.getByTestId("node-preview-play")).toHaveTextContent("Pause");
  });

  it("returns to Play when paused again", () => {
    render(<NodeMotionPreview motion={makeMotion()} />);
    fireEvent.click(screen.getByTestId("node-preview-play"));
    fireEvent.click(screen.getByTestId("node-preview-play"));
    expect(screen.getByTestId("node-preview-play")).toHaveTextContent("Play");
  });

  it("advances the frame label while playing (fake timers)", () => {
    const fps = 24;
    const step = Math.ceil(1000 / fps);
    render(<NodeMotionPreview motion={makeMotion()} />);
    fireEvent.click(screen.getByTestId("node-preview-play"));
    expect(screen.getByTestId("node-preview-frame")).toHaveTextContent("1 / 3");
    act(() => {
      vi.advanceTimersByTime(step);
    });
    expect(screen.getByTestId("node-preview-frame")).toHaveTextContent("2 / 3");
    act(() => {
      vi.advanceTimersByTime(step);
    });
    expect(screen.getByTestId("node-preview-frame")).toHaveTextContent("3 / 3");
  });

  it("stops at the last frame while playing", () => {
    const fps = 24;
    const step = Math.ceil(1000 / fps);
    render(<NodeMotionPreview motion={makeMotion(3)} />);
    fireEvent.click(screen.getByTestId("node-preview-play"));
    act(() => {
      vi.advanceTimersByTime(step * 10);
    });
    expect(screen.getByTestId("node-preview-frame")).toHaveTextContent("3 / 3");
    expect(screen.getByTestId("node-preview-play")).toHaveTextContent("Play");
  });

  it("shows empty placeholder when frames array is empty", () => {
    render(<NodeMotionPreview motion={makeMotion(0)} />);
    expect(screen.getByTestId("node-preview-empty")).toHaveTextContent(
      "No frames to display",
    );
    expect(screen.queryByTestId("node-preview-play")).not.toBeInTheDocument();
    expect(screen.queryByTestId("node-preview-canvas")).not.toBeInTheDocument();
  });
});
