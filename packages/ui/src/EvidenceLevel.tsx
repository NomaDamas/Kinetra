import type { ReactElement } from "react";

// Approved board: design/exports/design-system/source/Evidence.dc.html (brief 5절). The colour states how
// strong the evidence is, never whether the result is good (5.2): same level, same colour, whatever the
// probability or the verdict code. Strength is also carried by the code (L0..L3), the number of filled bars
// and the fixed phrase, so it never rests on colour alone.

export const L2_VERDICTS = ["FEASIBLE_FOUND", "INFEASIBLE_NECESSARY_CONDITION", "NOT_FOUND_IN_BUDGET"] as const;
export type L2Verdict = (typeof L2_VERDICTS)[number];

export type EvidenceLevelProps = (
  | { level: "L0" }
  | {
      level: "L1";
      /** Narrow variant `1회 실행 · 판정 아님`. The phrase itself can never be hidden (brief 5.1). */
      narrow?: boolean;
    }
  | { level: "L2"; verdict: L2Verdict }
  /** L3 is always shown. Real-world measurements are 0 today, so only the empty state exists (brief 5.1). */
  | { level: "L3" }
  | {
      level: "none";
      /** `invalid`: design or planet changed, old verdict is void. `out-of-model`: the model does not cover it. */
      reason: "invalid" | "out-of-model";
    }
) & {
  /** Announce changes to screen readers (`role="status"`), for the top bar badge (brief 8절). */
  announce?: boolean;
};

const LEVEL_CODE = { L0: "L0", L1: "L1", L2: "L2", L3: "L3" } as const;
const STRENGTH = { L0: 1, L1: 2, L2: 3, L3: 0, none: 0 } as const;

const NAMES = { L0: "조립", L1: "미리보기", L2: "판정", L3: "실측" } as const;
const PHRASES = {
  L0: "질량, 무게중심, 정역학 경고",
  L1: "1회 실행. 판정이 아닙니다",
  L1Narrow: "1회 실행 · 판정 아님",
  L3: "실물 검증 없음",
  invalid: "무효: 다시 판정해야 합니다",
  outOfModel: "모델 밖: 판정할 수 없습니다",
  weak: "약한 증거",
} as const;

/** Four bars, `strength` filled from the left; empty bars are outlined (same geometry as the board; the board closes the first two bars with an absolute `H`, here every bar uses `h-6`). */
function StrengthBars({ strength, weak }: { strength: number; weak: boolean }): ReactElement {
  const filled = [];
  const empty = [];
  for (let i = 0; i < 4; i += 1) {
    const x = i * 8;
    if (i < strength) filled.push(`M${x} 0h6v12h-6z`);
    else empty.push(`M${x === 0 ? "" : x}.5.5h5v11h-5z`); // `M.5.5`, `M8.5.5`, … as on the board
  }
  return (
    <svg
      width="30"
      height="12"
      viewBox="0 0 30 12"
      role="img"
      aria-label={`증거 강도 ${strength}/4${weak ? ", 약한 증거" : ""}`}
    >
      {filled.length > 0 && <path d={filled.join("")} fill="currentColor" />}
      {empty.length > 0 && <path d={empty.join("")} fill="none" stroke="currentColor" />}
    </svg>
  );
}

function VerdictGlyph({ verdict }: { verdict: L2Verdict | "OUT_OF_MODEL" }): ReactElement {
  const common = { width: 12, height: 12, viewBox: "0 0 12 12", "aria-hidden": true } as const;
  switch (verdict) {
    case "FEASIBLE_FOUND":
      return (
        <svg {...common}>
          <circle cx="6" cy="6" r="4.5" fill="currentColor" />
        </svg>
      );
    case "INFEASIBLE_NECESSARY_CONDITION":
      return (
        <svg {...common} fill="none" stroke="currentColor" strokeWidth="1.4">
          <circle cx="6" cy="6" r="4.5" />
          <path d="M2.8 9.2l6.4-6.4" />
        </svg>
      );
    case "NOT_FOUND_IN_BUDGET":
      return (
        <svg {...common} fill="none" stroke="currentColor" strokeWidth="1.4" strokeDasharray="2 2">
          <circle cx="6" cy="6" r="4.5" />
        </svg>
      );
    case "OUT_OF_MODEL":
      return (
        <svg {...common} fill="none" stroke="currentColor" strokeWidth="1.4">
          <path d="M1.5 1.5h9v9h-9z" />
        </svg>
      );
  }
}

export function EvidenceLevel(props: EvidenceLevelProps): ReactElement {
  const weak = props.level === "L2" && props.verdict === "NOT_FOUND_IN_BUDGET";
  // `L3` with zero measurements and `none` share the `none` colour tokens (brief 5.1: 0건인 동안 color.evidence.none).
  const tone = props.level === "L3" || props.level === "none" ? "none" : props.level.toLowerCase();
  const className = ["kin-evidence", `kin-evidence--${tone}`, weak ? "kin-evidence--weak" : ""].filter(Boolean).join(" ");

  let body: ReactElement;
  switch (props.level) {
    case "L0":
      body = (
        <>
          <span className="kin-evidence__code">{LEVEL_CODE.L0}</span>
          <span>{NAMES.L0}</span>
          <span>{PHRASES.L0}</span>
        </>
      );
      break;
    case "L1":
      body = props.narrow ? (
        <>
          <span className="kin-evidence__code">{LEVEL_CODE.L1}</span>
          <span>{PHRASES.L1Narrow}</span>
        </>
      ) : (
        <>
          <span className="kin-evidence__code">{LEVEL_CODE.L1}</span>
          <span>{NAMES.L1}</span>
          <span>{PHRASES.L1}</span>
        </>
      );
      break;
    case "L2":
      body = (
        <>
          <span className="kin-evidence__code">{LEVEL_CODE.L2}</span>
          <span>{NAMES.L2}</span>
          <VerdictGlyph verdict={props.verdict} />
          <span className="kin-evidence__code">{props.verdict}</span>
          {weak && <span>{PHRASES.weak}</span>}
        </>
      );
      break;
    case "L3":
      body = (
        <>
          <span className="kin-evidence__code">{LEVEL_CODE.L3}</span>
          <span>{NAMES.L3}</span>
          <span>{PHRASES.L3}</span>
        </>
      );
      break;
    case "none":
      body =
        props.reason === "out-of-model" ? (
          <>
            <VerdictGlyph verdict="OUT_OF_MODEL" />
            <span>{PHRASES.outOfModel}</span>
          </>
        ) : (
          <span>{PHRASES.invalid}</span>
        );
      break;
  }

  return (
    <span className={className} data-level={props.level} role={props.announce ? "status" : undefined}>
      <StrengthBars strength={STRENGTH[props.level]} weak={weak} />
      {body}
    </span>
  );
}
