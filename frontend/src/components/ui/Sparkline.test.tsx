import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Sparkline, sparkPoints } from "./index";

describe("Sparkline", () => {
  it("needs at least 3 finite observations", () => {
    expect(sparkPoints([1, 2])).toBeNull();
    expect(sparkPoints([1, null, undefined, Number.NaN, 2])).toBeNull();
    const { container } = render(<Sparkline values={[1, null, 2]} label="x" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("spans the box: the lowest value at the bottom, the highest at the top", () => {
    expect(sparkPoints([0, 5, 10])!.points).toEqual([
      [2, 27],
      [60, 15],
      [118, 3],
    ]);
    // a flat series sits on the bottom line (no division by zero)
    expect(sparkPoints([4, 4, 4])!.points.map(([, y]) => y)).toEqual([27, 27, 27]);
  });

  it("is a labelled image of its real values, drawn once, ending in a dot", () => {
    render(<Sparkline values={[3, null, 7, 5]} label="first seen this month" testId="s" />);
    const svg = screen.getByRole("img", { name: "first seen this month: 3, 7, 5" });
    expect(svg).toHaveAttribute("viewBox", "0 0 120 30");
    expect(svg).toHaveAttribute("data-testid", "s");
    const path = svg.querySelector("path")!;
    expect(path).toHaveClass("pz-trace");
    expect(path.getAttribute("d")).toBe("M2.0 27.0 L60.0 3.0 L118.0 15.0");
    expect(path).toHaveAttribute("pathLength", "1");
    const dot = svg.querySelector("circle")!;
    expect([dot.getAttribute("cx"), dot.getAttribute("cy"), dot.getAttribute("r")]).toEqual(["118", "15", "2.4"]);
  });
});
