import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useMedia } from "./useMedia";

afterEach(() => vi.unstubAllGlobals());

describe("useMedia", () => {
  it("is false without matchMedia (the narrow layout)", () => {
    vi.stubGlobal("matchMedia", undefined);
    const { result } = renderHook(() => useMedia("(min-width: 1240px)"));
    expect(result.current).toBe(false);
  });

  it("follows the query as it changes and stops listening on unmount", () => {
    let matches = true;
    const listeners = new Set<() => void>();
    vi.stubGlobal(
      "matchMedia",
      vi.fn((media: string) => ({
        media,
        get matches() {
          return matches;
        },
        addEventListener: (_: string, f: () => void) => listeners.add(f),
        removeEventListener: (_: string, f: () => void) => listeners.delete(f),
      })),
    );
    const { result, unmount } = renderHook(() => useMedia("(min-width: 1240px)"));
    expect(result.current).toBe(true);
    act(() => {
      matches = false;
      listeners.forEach((f) => f());
    });
    expect(result.current).toBe(false);
    unmount();
    expect(listeners.size).toBe(0);
  });
});
