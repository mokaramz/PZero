/**
 * ARDEA — the PZ Associate's character: a grey heron (genus Ardea). A heron stands perfectly still in the river and
 * strikes only when it is sure — patience, discernment and selectivity, the sourcing ethic of Project Zero. Original,
 * hand-authored vector art (no generated image, no icon library); colours come from tokens so it lives in light and
 * dark. Three forms:
 *   ArdeaIllustration — the full character standing in a stream of signals (welcome / empty state)
 *   ArdeaAvatar       — head and neck in a quiet roundel, with four restrained states (assistant identity, header)
 *   ArdeaMark         — a one-colour head silhouette that stays legible at 16–24 px
 * Static by default; a state change eases the head once (no loops); reduced motion shows the final pose at once.
 */
import { useId } from "react";

import { cx } from "@/lib/format";
import type { ArdeaState } from "../model/types";
import styles from "../Ardea.module.css";

export type { ArdeaState };

/** The head: crown, eye stripe into the nape plume, eye, dagger beak. Drawn in a 240-unit space around (176, 62). */
function Head({ state }: { state: ArdeaState }) {
  return (
    <>
      <path className={styles.ivory} d="M158 64 C 158 54, 168 47, 178 47 C 188 47, 195 54, 195 62 C 195 70, 187 76, 176 76 C 166 76, 158 72, 158 64 Z" />
      {/* the plume lifts a little when uncertain */}
      <path
        className={cx(styles.ink, styles.plume)}
        data-raised={state === "uncertain" || undefined}
        d="M187 57 C 177 53, 166 54, 157 59 C 149 64, 139 67, 124 71 C 138 62, 148 56, 158 53 C 170 50, 181 52, 189 55 Z"
      />
      <path className={styles.beak} d="M193 59.5 L 235 64.5 L 193 69.5 Z" />
      <path className={styles.beakLine} d="M195 64.5 L 230 64.5" />
      <circle className={styles.ink} cx="183" cy="61.5" r="3" />
      {state === "thinking" ? (
        /* a lowered lid: concentration, not sleep */
        <path className={styles.ivory} d="M179.6 60.8 C 181 58.2, 185 58.2, 186.4 60.8 Z" />
      ) : (
        <circle className={styles.glint} cx="184.1" cy="60.4" r="1" />
      )}
    </>
  );
}

/** Head pose per state, in degrees around the top of the neck (CSS transform, so a change eases once). */
const HEAD_POSE: Record<ArdeaState, number> = {
  ready: 0,
  thinking: 13, // looking down at the water: examining the evidence
  done: -5, // a small lift: finished
  uncertain: -11, // a head tilt: not sure yet
};

function PosedHead({ state }: { state: ArdeaState }) {
  return (
    <g className={styles.headWrap}>
      <g className={styles.head} style={{ transform: `rotate(${HEAD_POSE[state]}deg)` }}>
        <Head state={state} />
      </g>
    </g>
  );
}

function Neck() {
  return (
    <>
      <path className={styles.neckBack} d="M152 146 C 140 130, 136 112, 144 98 C 150 88, 158 80, 162 72 L 172 73 C 166 84, 158 94, 154 106 C 150 120, 156 134, 166 150 C 160 152, 155 150, 152 146 Z" />
      <path className={styles.ivory} d="M166 150 C 156 134, 150 120, 154 106 C 158 94, 166 84, 172 73 L 184 74 C 180 86, 172 96, 166 106 C 160 118, 168 132, 182 150 C 176 153, 170 153, 166 150 Z" />
      <g className={styles.streaks}>
        <path d="M166 112 l2 6" />
        <path d="M165 123 l2 6" />
        <path d="M168 134 l2 5" />
      </g>
    </>
  );
}

export function ArdeaIllustration({ className, state = "ready", enter = true, title = "Ardea, the PZ Associate heron" }: { className?: string; state?: ArdeaState; enter?: boolean; title?: string }) {
  const id = useId();
  return (
    <svg className={cx(styles.svg, enter && styles.enter, className)} viewBox="0 0 240 280" role="img" aria-labelledby={`${id}-t`} data-testid="ardea-illustration">
      <title id={`${id}-t`}>{title}</title>
      {/* the stream: a few calm lines of signal */}
      <g className={styles.water}>
        <path d="M56 252 H116" />
        <path d="M136 252 H200" />
        <path d="M80 262 H176" opacity=".7" />
        <path d="M104 271 H152" opacity=".45" />
      </g>
      <g className={styles.reed}>
        <path d="M40 254 C 38 224, 42 198, 36 172" />
        <path d="M50 254 C 52 232, 48 216, 54 198" />
      </g>
      <path className={styles.cattail} d="M36 174 c-3.5 -10 0 -21 4 -27 c2 9 0 19 -4 27z" />
      <g className={styles.legs}>
        <path d="M128 206 L126 252" />
        <path d="M141 205 L157 222 L144 229" />
      </g>
      {/* body, breast, folded wing with two feather lines */}
      <path className={styles.body} d="M60 214 C 80 208, 96 196, 106 180 C 118 158, 136 142, 158 140 C 178 138, 186 158, 178 176 C 170 198, 148 210, 122 213 C 102 215, 82 216, 60 214 Z" />
      <path className={styles.breast} d="M160 142 C 176 140, 186 156, 180 174 C 176 186, 168 194, 158 200 C 166 184, 170 166, 160 142 Z" />
      <path className={styles.wing} d="M72 212 C 92 204, 106 190, 116 172 C 126 156, 140 146, 158 144 C 152 164, 140 186, 122 200 C 114 206, 104 209, 96 210 C 90 214, 84 212, 80 214 C 76 215, 74 213, 72 212 Z" />
      <g className={styles.feathers}>
        <path d="M100 202 C 112 192, 120 182, 128 170" />
        <path d="M90 208 C 102 200, 110 192, 118 182" />
      </g>
      <Neck />
      <PosedHead state={state} />
    </svg>
  );
}

const STATE_LABEL: Record<ArdeaState, string> = {
  ready: "PZ Associate",
  thinking: "PZ Associate — reading Project Zero",
  done: "PZ Associate — answer ready",
  uncertain: "PZ Associate — not certain",
};

/** Head and neck in a roundel. `decorative` hides it from screen readers when a visible name sits beside it. */
export function ArdeaAvatar({ size = 36, state = "ready", decorative = false, className }: { size?: number; state?: ArdeaState; decorative?: boolean; className?: string }) {
  const id = useId();
  return (
    <svg
      className={cx(styles.svg, styles.avatar, className)}
      width={size}
      height={size}
      viewBox="117 17 126 126"
      data-state={state}
      data-testid="ardea-avatar"
      {...(decorative ? { "aria-hidden": true } : { role: "img", "aria-labelledby": `${id}-t` })}
    >
      {!decorative && <title id={`${id}-t`}>{STATE_LABEL[state]}</title>}
      <defs>
        <clipPath id={`${id}-c`}>
          <circle cx="180" cy="80" r="62" />
        </clipPath>
      </defs>
      <circle className={styles.roundel} cx="180" cy="80" r="62" />
      <g clipPath={`url(#${id}-c)`}>
        <path className={styles.body} d="M128 160 C 138 146, 150 140, 162 140 C 182 138, 196 150, 204 168 L 128 168 Z" />
        <Neck />
        <PosedHead state={state} />
      </g>
      <circle className={styles.ring} cx="180" cy="80" r="61" />
    </svg>
  );
}

/** The one-colour mark (currentColor): head, plume and beak in a 3:1 box; `size` is its height (legible from 12 px). */
export function ArdeaMark({ size = 20, className, title }: { size?: number; className?: string; title?: string }) {
  const id = useId();
  return (
    <svg
      className={cx(styles.mark, className)}
      width={size * 3}
      height={size}
      viewBox="118 40 120 40"
      preserveAspectRatio="xMidYMid meet"
      data-testid="ardea-mark"
      {...(title ? { role: "img", "aria-labelledby": `${id}-t` } : { "aria-hidden": true })}
    >
      {title && <title id={`${id}-t`}>{title}</title>}
      <path d="M158 64 C 158 54, 168 47, 178 47 C 188 47, 195 54, 195 62 C 195 70, 187 76, 176 76 C 166 76, 158 72, 158 64 Z M158 53 C 148 56, 138 62, 124 71 C 140 64, 150 60, 160 58 Z M193 59.5 L 235 64.5 L 193 69.5 Z" />
      <circle cx="183" cy="61.5" r="2.6" className={styles.markEye} />
    </svg>
  );
}
