/**
 * Shared UI primitives. Features compose these; they do not restyle them.
 * Every primitive forwards `className` and native props so features can add layout without forking styles.
 */
export { ActionArea, MoreMenu, type MoreItem } from "./ActionArea";
export { Badge, type Tone } from "./Badge";
export { Button, ConfirmButton, type ButtonProps } from "./Button";
export { Chip, Segmented, type SegmentedOption } from "./chips";
export { KeyValue, Stat } from "./data";
export { Async, EmptyState, ErrorBox, Spinner, type AsyncQuery } from "./feedback";
export { Field } from "./Field";
export { FocusTabs, type FocusTab } from "./FocusTabs";
export { Drawer, Modal } from "./overlays";
export { PageHeader, Toolbar } from "./page";
export { Sparkline } from "./Sparkline";
export { sparkPoints } from "./sparkPoints";
export { Callout, Card, Panel, type PanelProps } from "./surfaces";
