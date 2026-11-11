import { PATHS, type IconName } from "./paths";

type IconProps = { name: IconName; size?: number; className?: string };

/** One stroke icon, decorative (aria-hidden): the label next to it carries the meaning. */
export function Icon({ name, size = 16, className }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
