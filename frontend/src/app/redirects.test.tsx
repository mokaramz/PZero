import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { scoutIntakeTarget } from "./legacyLinks";
import { ScoutBridgeRedirect, ScoutIntakeRedirect } from "./redirects";

function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}

function landOn(url: string): string {
  const router = createMemoryRouter(
    [
      { path: "/scout-intake", element: <ScoutIntakeRedirect /> },
      { path: "/scout-bridge", element: <ScoutBridgeRedirect /> },
      { path: "/deal-flow", element: <Where /> },
    ],
    { initialEntries: [url] },
  );
  render(<RouterProvider router={router} />);
  return screen.getByTestId("where").textContent ?? "";
}

describe("retired-view redirects", () => {
  it("Scout Intake carries ?item as ?candidate in the scout_intake namespace", () => {
    expect(landOn("/scout-intake?item=c-42")).toBe("/deal-flow?candidate=c-42&ns=scout_intake");
  });
  it("Scout Intake without an item opens Deal Flow", () => {
    expect(landOn("/scout-intake?tab=queue")).toBe("/deal-flow");
  });
  it("Scout Bridge opens Deal Flow", () => {
    expect(landOn("/scout-bridge?job=7")).toBe("/deal-flow");
  });
  it("encodes the id", () => {
    expect(scoutIntakeTarget(new URLSearchParams({ item: "a b&c" }))).toBe("/deal-flow?candidate=a+b%26c&ns=scout_intake");
  });
});
