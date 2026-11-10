import type { ButtonHTMLAttributes, ReactElement } from "react";

// Approved board: design/exports/design-system/source/ValueBadges.dc.html (brief 4절). Five kinds, always
// label + glyph + border shape, never colour alone. A badge is a focusable button; it is never disabled
// (reading the evidence must never be blocked, V1), so `disabled` is not part of the props.

export const VALUE_BADGE_KINDS = ["sim", "cite", "default", "declared", "estimate"] as const;
export type ValueBadgeKind = (typeof VALUE_BADGE_KINDS)[number];

export const VALUE_BADGE_LABELS: Readonly<Record<ValueBadgeKind, string>> = {
  sim: "시뮬",
  cite: "인용",
  default: "기본값",
  declared: "사용자 선언",
  estimate: "추정",
};

// 12x12 glyph paths copied from the board: waveform, quotes, empty circle, pencil, approx.
const GLYPHS: Readonly<Record<ValueBadgeKind, ReactElement>> = {
  sim: <path d="M1 6q1.25-5 2.5 0t2.5 0t2.5 0t2.5 0" />,
  cite: <path d="M2.5 8.5v-3a2.5 2.5 0 0 1 2.5-2.5M7 8.5v-3a2.5 2.5 0 0 1 2.5-2.5" />,
  default: <circle cx="6" cy="6" r="3.5" />,
  declared: <path d="M2 10l.6-2.6 5.6-5.6 2 2-5.6 5.6z" />,
  estimate: <path d="M2 4.5q2-2 4 0t4 0M2 8q2-2 4 0t4 0" />,
};

type CommonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type" | "disabled" | "children" | "className"> & {
  /** Prefix such as `카탈로그 밖`; rendered `카탈로그 밖 · 사용자 선언` (brief 4절 수식어). */
  modifier?: string;
};

export type ValueBadgeProps = CommonProps &
  (
    | {
        kind: "sim";
        /** Engine link lost, the `시뮬` value could not be recomputed (brief 4절 오래됨): dashed border + `· 오래됨`. */
        stale?: boolean;
      }
    | { kind: Exclude<ValueBadgeKind, "sim">; stale?: never }
  );

export function ValueBadge({ kind, stale = false, modifier, ...rest }: ValueBadgeProps): ReactElement {
  // The types already omit `disabled`; strip it (and `aria-disabled`) at runtime too, so a spread props object or an
  // `as any` can never make a badge inert: reading the evidence is never blocked (V1).
  const { disabled: _disabled, "aria-disabled": _ariaDisabled, ...button } = rest as ButtonHTMLAttributes<HTMLButtonElement>;
  const label = [modifier, VALUE_BADGE_LABELS[kind], stale ? "오래됨" : undefined].filter(Boolean).join(" · ");
  const className = ["kin-value-badge", `kin-value-badge--${kind}`, stale ? "kin-value-badge--stale" : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <button {...button} type="button" className={className}>
      <span className="kin-value-badge__pill">
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          {GLYPHS[kind]}
        </svg>
        {label}
      </span>
    </button>
  );
}
