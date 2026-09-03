import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { App } from "../app/App";

describe("App shell", () => {
  it("renders the application title", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "AImation Flow" })).toBeInTheDocument();
  });

  it("lands on Simple Mode by default and switches to the Advanced canvas (AR-3)", async () => {
    render(<App />);
    // Default view is Simple Mode (presets launcher), not the node editor.
    expect(screen.getByTestId("simple-mode")).toBeInTheDocument();
    expect(screen.queryByTestId("canvas-host")).not.toBeInTheDocument();

    // Switch to Advanced to reveal the node editor.
    fireEvent.click(screen.getByTestId("mode-advanced"));
    await waitFor(() => {
      expect(screen.queryByTestId("simple-mode")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("canvas-host")).toBeInTheDocument();
    expect(screen.getByTestId("flow-canvas")).toBeInTheDocument();

    // And back to Simple.
    fireEvent.click(screen.getByTestId("mode-simple"));
    await waitFor(() => {
      expect(screen.queryByTestId("canvas-host")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("simple-mode")).toBeInTheDocument();
  });
});
