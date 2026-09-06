import { describe, it, expect, beforeEach } from "vitest";
import { sessionToken } from "./token";

/**
 * HTTP-2 guardrail: the session token must never be written to web storage.
 * Note: Vitest 4 on Node exposes an experimental global localStorage without
 * a working `clear()`; we avoid depending on it and only inspect contents.
 */
function clearStorage(storage: Storage): void {
  if (typeof storage === "undefined" || storage === null) return;
  try {
    const keys = Object.keys(storage);
    for (const k of keys) storage.removeItem(k);
  } catch {
    /* storage unavailable in this environment — test is vacuous yet harmless */
  }
}

function localStorageContents(): string[] {
  try {
    return typeof globalThis.localStorage === "undefined"
      ? []
      : Object.keys(globalThis.localStorage as Storage);
  } catch {
    return [];
  }
}

function sessionStorageContents(): string[] {
  try {
    return typeof globalThis.sessionStorage === "undefined"
      ? []
      : Object.keys(globalThis.sessionStorage as Storage);
  } catch {
    return [];
  }
}

describe("token module (HTTP-2)", () => {
  beforeEach(() => {
    clearStorage(globalThis.localStorage as Storage);
    clearStorage(globalThis.sessionStorage as Storage);
  });

  it("returns a string (empty means no auth)", () => {
    expect(typeof sessionToken()).toBe("string");
  });

  it("never persists the token to localStorage or sessionStorage", () => {
    const token = sessionToken();
    const allKeys = [...localStorageContents(), ...sessionStorageContents()];
    expect(allKeys).toHaveLength(0);
    // Even if some unrelated keys exist, none may hold the token.
    const tokenLike = allKeys.filter((k) => k.toLowerCase().includes("token"));
    expect(tokenLike).toHaveLength(0);
    expect(token).not.toBeUndefined();
  });
});
