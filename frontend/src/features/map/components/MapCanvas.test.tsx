import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { applyFilters, DEFAULT_FILTERS } from "../model/filter";
import { TEXT } from "../model/text";
import { pins, PINS_NOW } from "../test/fixtures";
import { FakeMap, fakeMapLibre } from "../test/maplibre";
import { loadMapLibre } from "./loadMapLibre";
import { MapCanvas } from "./MapCanvas";
import { PLAIN, TILE_TIMEOUT_MS } from "./mapStyle";

vi.mock("./loadMapLibre", () => ({ loadMapLibre: vi.fn() }));

function mount() {
  const d = pins();
  const onSelect = vi.fn();
  const onReady = vi.fn();
  const view = render(
    <ToastProvider>
      <MapCanvas data={d} visible={applyFilters(d, DEFAULT_FILTERS, PINS_NOW)} onSelect={onSelect} onReady={onReady} />
    </ToastProvider>,
  );
  return { onSelect, onReady, ...view };
}

beforeEach(() => {
  FakeMap.reset();
  vi.mocked(loadMapLibre).mockResolvedValue(fakeMapLibre);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("MapCanvas (MapLibre mocked: jsdom has no WebGL)", () => {
  it("without base tiles after 9 s, the pins move to the plain canvas, with a toast", async () => {
    vi.useFakeTimers();
    FakeMap.autoLoad = false;
    const { onReady } = mount();
    await act(() => vi.advanceTimersByTimeAsync(0)); // MapLibre "loaded"
    expect(FakeMap.instances).toHaveLength(1);
    await act(() => vi.advanceTimersByTimeAsync(TILE_TIMEOUT_MS - 1));
    expect(FakeMap.last.style).toBe("https://tiles.openfreemap.org/styles/positron");
    expect(screen.getByRole("status")).not.toHaveTextContent(TEXT.tilesTimeout);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(FakeMap.last.style).toBe(PLAIN);
    expect(screen.getByRole("status")).toHaveTextContent(TEXT.tilesTimeout);
    await act(() => vi.advanceTimersByTimeAsync(1)); // the plain style loads (no network)
    expect(screen.getByTestId("map-canvas")).toHaveAttribute("data-ready", "true");
    expect(onReady).toHaveBeenCalledTimes(1);
    expect(TILE_TIMEOUT_MS).toBe(9000);
  });

  it("tiles in time: no fallback; pins and circles select; a cluster click zooms in; unmount removes the map", async () => {
    vi.useFakeTimers();
    const { onSelect, onReady, unmount } = mount();
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByTestId("map-canvas")).toHaveAttribute("data-ready", "true");
    await act(() => vi.advanceTimersByTimeAsync(TILE_TIMEOUT_MS * 2));
    expect(FakeMap.last.style).toBe("https://tiles.openfreemap.org/styles/positron");
    expect(screen.getByRole("status")).toBeEmptyDOMElement();

    const m = FakeMap.last;
    await act(() => m.click("ev-pt", { id: "forge-demo-day" }));
    await act(() => m.click("ppl-pt", { id: "p-jonah-weller" }));
    await act(() => m.click("org-pt", { name: "Forge Hub" }));
    await act(() => m.click("eco-c", { city: "Munich" }));
    expect(onSelect.mock.calls.map(([s]) => s)).toEqual([
      { kind: "event", id: "forge-demo-day" },
      { kind: "person", id: "p-jonah-weller" },
      { kind: "org", id: "Forge Hub" },
      { kind: "eco", id: "Munich" },
    ]);
    FakeMap.rendered = [{ properties: { cluster_id: 3 }, geometry: { coordinates: [11.5, 48.1] } }];
    await act(() => m.fire("click", "st-cl", { point: { x: 1, y: 1 } }));
    expect(m.eases).toEqual([{ center: [11.5, 48.1], zoom: 7.5 }]);
    // the camera the page drives
    onReady.mock.calls[0][0].flyTo(8.5, 47.3);
    expect(m.flights).toEqual([{ center: [8.5, 47.3], zoom: 9 }]);
    // the startup pins carry the stage colour and the Manager ring
    expect(m.props("startups").find((p) => p.slug === "skylark-freight")).toEqual({ slug: "skylark-freight", score: 65, color: "#4A90D9", omar: true });
    unmount();
    expect(m.removed).toBe(true);
  });
});
