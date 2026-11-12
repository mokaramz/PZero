import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { FocusTabs, type FocusTab } from "./index";

const TABS: FocusTab[] = [
  { id: "a", label: "Alpha", content: <p>alpha body</p> },
  { id: "b", label: "Beta", count: 3, content: <p>beta body</p> },
  { id: "c", label: "Gamma", hidden: true, content: <p>gamma body</p> },
];

function Harness({ initial = "a", tabs = TABS }: { initial?: string; tabs?: FocusTab[] }) {
  const [v, setV] = useState(initial);
  return <FocusTabs tabs={tabs} value={v} onChange={setV} label="Question" testId="q" />;
}

describe("FocusTabs", () => {
  it("shows the visible tabs, one tabpanel, and only the chosen area mounted", () => {
    render(<Harness />);
    expect(screen.getByRole("tablist", { name: "Question" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Alpha", "Beta3"]);
    expect(screen.getByRole("tab", { name: "Alpha" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Alpha" })).toHaveAttribute("data-tab", "a");
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
    expect(screen.getByText("alpha body")).toBeInTheDocument();
    expect(screen.queryByText("beta body")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: /^Beta/ }));
    expect(screen.getByRole("tab", { name: /^Beta/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("beta body")).toBeInTheDocument();
    expect(screen.queryByText("alpha body")).toBeNull();
    expect(screen.getByTestId("q")).toBeInTheDocument();
  });

  it("an unknown or hidden value falls back to the first shown tab", () => {
    render(<Harness initial="c" />);
    expect(screen.getByRole("tab", { name: "Alpha" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText("gamma body")).toBeNull();
  });

  it("renders nothing when no tab is shown; the default test id is focus-tabs", () => {
    const { container } = render(<Harness tabs={[{ id: "x", label: "X", hidden: true, content: null }]} />);
    expect(container).toBeEmptyDOMElement();
    render(<FocusTabs tabs={TABS} value="a" onChange={() => {}} label="L" />);
    expect(screen.getByTestId("focus-tabs")).toBeInTheDocument();
  });
});
