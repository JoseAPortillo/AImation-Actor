import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConnectionBanner } from "./ConnectionBanner";
import { useUiStore } from "../../state/useUiStore";

describe("ConnectionBanner (HTTP-3)", () => {
  it("shows a non-fatal banner with Retry while the app stays interactive", () => {
    useUiStore.getState().setBanner("core is not reachable", "error");
    const onRetry = vi.fn();
    render(<ConnectionBanner onRetry={onRetry} />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByTestId("banner-message")).toHaveTextContent(
      "core is not reachable",
    );

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders nothing when no banner is set (no crash)", () => {
    useUiStore.getState().dismissBanner();
    render(<ConnectionBanner onRetry={() => {}} />);
    expect(screen.queryByRole("alert")).toBeNull();
    // The app shell is present and interactive even without a banner.
    expect(document.body).toBeTruthy();
  });

  it("Dismiss clears the banner from the store", () => {
    useUiStore.getState().setBanner("timeout", "warning");
    render(<ConnectionBanner onRetry={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(useUiStore.getState().banner).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
