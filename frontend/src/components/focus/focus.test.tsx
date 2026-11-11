import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { DisclosureGroup } from "../attention";
import { DecisionCard, Disclosure, fieldFor, HighlightStrip, initials, PathTrace } from "./index";

describe("focus primitives", () => {
  it("fieldFor picks the first matching field, neutral otherwise", () => {
    expect(fieldFor("Quantum sensing for grids")).toBe("frontier");
    expect(fieldFor(null, "Battery recycling")).toBe("energy");
    expect(fieldFor("Warehouse robots")).toBe("industrial");
    expect(fieldFor("B2B invoicing")).toBe("neutral");
  });

  it("initials skip legal forms and punctuation", () => {
    expect(initials("Acme GmbH")).toBe("AC");
    expect(initials("Northern Light Labs")).toBe("NL");
    expect(initials("")).toBe("?");
  });

  it("the editorial decision card caps lists and shows one move", () => {
    render(
      <MemoryRouter>
        <DecisionCard
          variant="editorial"
          why={["a", "b", "c"]}
          risks={[]}
          unknowns={["u"]}
          pzView="Worth a look"
          move={{ label: "Open", to: "/x", why: "Read the deck" }}
        />
      </MemoryRouter>,
    );
    const card = screen.getByTestId("operator-view");
    expect(card).toHaveAttribute("data-variant", "editorial");
    expect(screen.getByText("Key takeaways")).toBeInTheDocument();
    expect(screen.getByText("+ 1 more")).toBeInTheDocument();
    expect(screen.getByText("None on record.")).toBeInTheDocument();
    expect(screen.getByText("Read the deck")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute("href", "/x");
  });

  it("a highlight strip with only empty values renders nothing", () => {
    const { container } = render(<HighlightStrip items={[{ icon: "funding", label: "Funding", value: "" }]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("inside a DisclosureGroup only one disclosure is open", async () => {
    render(
      <DisclosureGroup>
        <Disclosure title="One" groupKey="one" defaultOpen>
          body one
        </Disclosure>
        <Disclosure title="Two" groupKey="two" defaultOpen>
          body two
        </Disclosure>
      </DisclosureGroup>,
    );
    // both ask to start open in the same commit; the group keeps exactly one (the last claim, as in the old app)
    expect(screen.queryAllByText(/body (one|two)/)).toHaveLength(1);
    fireEvent.click(screen.getByText("One"));
    expect(await screen.findByText("body one")).toBeInTheDocument();
    expect(screen.queryByText("body two")).not.toBeInTheDocument();
  });

  it("a path trace draws a real chain of two or more names, and nothing otherwise", () => {
    const { container, rerender } = render(<PathTrace nodes={["Smooth Operator", " ", "Founder"]} />);
    expect(screen.getByTestId("path-trace")).toHaveAttribute("data-signature", "data");
    expect(screen.getByRole("img", { name: "Introduction path: Smooth Operator → Founder" })).toBeInTheDocument();
    expect(container.querySelectorAll("circle")).toHaveLength(2);
    rerender(<PathTrace nodes={["Smooth Operator", "An introducer with a long name", "Founder"]} testId="intro-path" />);
    expect(screen.getByTestId("intro-path")).toHaveTextContent("An introducer wit…");
    rerender(<PathTrace nodes={["Founder", ""]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
