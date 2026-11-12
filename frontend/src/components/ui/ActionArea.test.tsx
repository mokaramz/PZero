import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ActionArea, MoreMenu } from "./index";

const details = () => screen.getByTestId("more-actions") as HTMLDetailsElement;

describe("ActionArea / MoreMenu", () => {
  it("renders the More menu before the one primary", () => {
    render(<ActionArea primary={<button type="button">Record outcome</button>} more={[{ label: "Record a miss", onClick: () => {}, testId: "record-miss" }]} />);
    const area = document.querySelector("[data-action-area]")!;
    expect(area.firstElementChild).toBe(details());
    expect(area.lastElementChild).toHaveTextContent("Record outcome");
    expect(screen.getByText("More", { selector: "summary" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "More" })).toContainElement(screen.getByTestId("record-miss"));
  });

  it("closes before the chosen item runs", () => {
    const run = vi.fn(() => expect(details().open).toBe(false));
    render(<MoreMenu items={[{ label: "Do it", onClick: run, testId: "do" }]} />);
    details().setAttribute("open", "");
    fireEvent.click(screen.getByTestId("do"));
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("a disabled item stays in the menu with its hint and never runs", () => {
    const run = vi.fn();
    render(<MoreMenu items={[{ label: "Record a miss", onClick: run, testId: "record-miss", disabled: true, hint: "Not yet" }]} />);
    const item = screen.getByTestId("record-miss");
    expect(item).toBeDisabled();
    expect(item).toHaveAttribute("title", "Not yet");
    fireEvent.click(item);
    expect(run).not.toHaveBeenCalled();
  });

  it("Escape and a click outside close it", () => {
    render(
      <div>
        <p>outside</p>
        <MoreMenu items={[{ label: "x", onClick: () => {} }]} />
      </div>,
    );
    details().setAttribute("open", "");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(details().open).toBe(false);
    details().setAttribute("open", "");
    fireEvent.mouseDown(screen.getByText("More", { selector: "summary" }));
    expect(details().open).toBe(true);
    fireEvent.mouseDown(screen.getByText("outside"));
    expect(details().open).toBe(false);
  });

  it("renders nothing without items or children; no More without `more`", () => {
    const { container } = render(<MoreMenu items={[]} />);
    expect(container).toBeEmptyDOMElement();
    render(<ActionArea primary={<span>only</span>} />);
    expect(screen.queryByTestId("more-actions")).toBeNull();
  });
});
