import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { App } from "../app/App";

describe("App shell", () => {
  it("renders the application title", () => {
    render(<App />);
    // The shell header is the page banner; the wizard renders its own
    // inner title, so scope the assertion to the shell header.
    expect(within(screen.getByRole("banner")).getByRole("heading", { name: "AImation Actor" })).toBeInTheDocument();
  });

  it("lands on the wizard by default and switches to the Advanced canvas (AR-3)", async () => {
    render(<App />);
    // Default view is the wizard, not the node editor.
    expect(screen.getByTestId("mode-wizard")).toBeInTheDocument();
    expect(screen.queryByTestId("canvas-host")).not.toBeInTheDocument();

    // Switch to Advanced to reveal the node editor.
    fireEvent.click(screen.getByTestId("mode-advanced"));
    await waitFor(() => {
      expect(screen.getByTestId("canvas-host")).toBeInTheDocument();
    });
    expect(screen.getByTestId("flow-canvas")).toBeInTheDocument();

    // And back to the wizard.
    fireEvent.click(screen.getByTestId("mode-wizard"));
    await waitFor(() => {
      expect(screen.queryByTestId("canvas-host")).not.toBeInTheDocument();
    });
  });
});
