import { describe, it, expect, beforeEach } from "vitest";
import { useUiStore } from "./useUiStore";

describe("useUiStore banner (HTTP-3)", () => {
  beforeEach(() => {
    useUiStore.setState({ banner: null });
  });

  it("setBanner stores a non-fatal error banner without crashing the store", () => {
    useUiStore.getState().setBanner("core is down", "error");
    const { banner } = useUiStore.getState();
    expect(banner?.message).toBe("core is down");
    expect(banner?.kind).toBe("error");
  });

  it("setBanner defaults kind to error", () => {
    useUiStore.getState().setBanner("timeout");
    expect(useUiStore.getState().banner?.kind).toBe("error");
  });

  it("dismissBanner clears the banner", () => {
    useUiStore.getState().setBanner("boom");
    useUiStore.getState().dismissBanner();
    expect(useUiStore.getState().banner).toBeNull();
  });
});
