import type { RouteObject } from "react-router-dom";

import { Layout } from "./layout/Layout";
import { ALL_ITEMS, type NavItem } from "./nav";
import { NotPorted } from "./NotPorted";
import { ScoutBridgeRedirect, ScoutIntakeRedirect } from "./redirects";

function viewElement({ page: Page, label }: NavItem) {
  return Page ? <Page /> : <NotPorted label={label} />;
}

/** Every route lives inside the shell: the navigation views, the retired-view redirects and "Page not found.". */
export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      ...ALL_ITEMS.map((item) => ({ path: item.path, element: viewElement(item) })),
      { path: "/scout-intake", element: <ScoutIntakeRedirect /> },
      { path: "/scout-bridge", element: <ScoutBridgeRedirect /> },
      { path: "*", element: <p className="muted">Page not found.</p> },
    ],
  },
];
