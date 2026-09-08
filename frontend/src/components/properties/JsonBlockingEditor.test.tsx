import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { JsonBlockingEditor } from "./JsonBlockingEditor";
import { buildBlockingTemplate } from "../../core/blockingTemplate";

describe("JsonBlockingEditor (blocking JSON widget)", () => {
  it("renders the overlay, textarea and review for a valid template, with no issue strip", () => {
    render(<JsonBlockingEditor value={buildBlockingTemplate()} onChange={() => {}} />);
    expect(screen.getByTestId("json-editor-overlay")).toBeInTheDocument();
    expect(screen.getByTestId("json-editor-textarea")).toBeInTheDocument();
    expect(screen.getByTestId("json-editor-review")).toBeInTheDocument();
    expect(screen.queryByTestId("json-editor-issues")).not.toBeInTheDocument();
  });

  it("collapses each keypose review by default and shows the skeleton summary", () => {
    render(<JsonBlockingEditor value={buildBlockingTemplate()} onChange={() => {}} />);
    const review = screen.getByTestId("json-editor-review");
    expect(review).toHaveTextContent("Skeleton: default neutral (22 bones)");
    const kp0 = screen.getByTestId("json-editor-keypose-0");
    const kp1 = screen.getByTestId("json-editor-keypose-1");
    expect(kp0).not.toHaveAttribute("open");
    expect(kp1).not.toHaveAttribute("open");
    expect(kp0).toHaveTextContent("Keypose 1");
    expect(kp0).toHaveTextContent("valid");
  });

  it("shows a count and L-prefixed rows in the issue strip for a broken payload", () => {
    render(<JsonBlockingEditor value={'{"keyposes": [], "foo": "bar"}'} onChange={() => {}} />);
    const strip = screen.getByTestId("json-editor-issues");
    expect(strip).toHaveTextContent("2 issues");
    expect(strip).toHaveTextContent("L1");
    expect(screen.getByTestId("json-editor-issue-0")).toHaveTextContent(
      "unknown top-level field: foo",
    );
    expect(screen.getByTestId("json-editor-issue-1")).toHaveTextContent(
      "keyposes must contain at least 1 keypose",
    );
  });

  it("highlights the error line in the overlay", () => {
    render(<JsonBlockingEditor value={'{\n  "keyposes": [}'} onChange={() => {}} />);
    expect(screen.getByTestId("json-editor-line-2")).toHaveStyle({
      backgroundColor: "rgba(220, 38, 38, 0.15)",
    });
  });

  it("clicking an issue row focuses the textarea with the selection at that line", () => {
    render(<JsonBlockingEditor value={'{\n  "keyposes": [}'} onChange={() => {}} />);
    const textarea = screen.getByTestId("json-editor-textarea") as HTMLTextAreaElement;
    fireEvent.click(screen.getByTestId("json-editor-issue-0"));
    expect(document.activeElement).toBe(textarea);
    expect(textarea.selectionStart).toBe(2);
  });

  it("forwards edits to onChange", () => {
    const onChange = vi.fn();
    render(<JsonBlockingEditor value="{}" onChange={onChange} />);
    fireEvent.change(screen.getByTestId("json-editor-textarea"), {
      target: { value: "[]" },
    });
    expect(onChange).toHaveBeenCalledWith("[]");
  });

  it("shows a custom skeleton line in the review when parsed", () => {
    const payload = JSON.stringify({
      skeleton: { bones: { A: {}, B: {} } },
      keyposes: [
        {
          frame: 1,
          pose: {
            A: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
            B: { translation: [0, 0, 0], rotation: [1, 0, 0, 0], scale: [1, 1, 1] },
          },
          weight: 1,
        },
      ],
    });
    render(<JsonBlockingEditor value={payload} onChange={() => {}} />);
    expect(screen.getByTestId("json-editor-review")).toHaveTextContent("Skeleton: custom (2 bones)");
  });
});