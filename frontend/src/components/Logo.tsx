/** The Project Zero mark — "origin signal": the zero ring, opened, with one point leaving it (a hidden signal becoming
 *  visible at the origin). One colour (currentColor), no gradient; legible from 16px. Usage: docs/design-system.md. */
export const LOGO_PATH = "M18.05 10.43A7.5 7.5 0 1 1 12.3 5.61";

export function Logo({ size = 24, title = "Project Zero" }: { size?: number; title?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" role="img" aria-label={title} data-testid="pz-logo">
      <path d={LOGO_PATH} fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" />
      <circle cx="18.4" cy="4.2" r="2.1" fill="currentColor" />
    </svg>
  );
}
