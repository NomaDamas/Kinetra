"""PR 본문이 `.github/pull_request_template.md` 의 앞부분 규칙을 지키는지 검사한다 (P0-04c). 표준 라이브러리만 쓴다.

    python3 scripts/ci/check_pr_body.py --body-file body.md
    PR_BODY="$text" python3 scripts/ci/check_pr_body.py          # CI: 본문은 환경 변수로 받는다

실패하는 경우 (모두 템플릿 순서 `## 대목표` → `## 핵심 가치` → `Closes #N`/`Refs #N` 를 따른다)
    - `## 대목표` 제목이 없거나 내용이 비었다.
    - `## 핵심 가치` 제목이 없거나, 그 절에 `docs/plan/values.md` 의 V1~V5 문장 하나가 원문 그대로
      인용(`> ` 줄)돼 있지 않다. `**` 강조 표시와 공백 개수는 무시하고 글자는 그대로 비교한다.
    - `Closes #N` 또는 `Refs #N` 만 있는 줄이 `## 핵심 가치` 뒤에 없다. `Closes` 는 잎 이슈 하나만 쓴다.
    - 순서가 다르다.
코드 블록(```)과 HTML 주석(<!-- -->) 안의 내용은 본문으로 치지 않는다. 템플릿 자리표시자(`Closes #<잎 이슈 하나>`)는 통과하지 못한다.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VALUES = ROOT / "docs" / "plan" / "values.md"

GOAL_HEADING = "## 대목표"
VALUES_HEADING = "## 핵심 가치"
VALUE_LINE_RE = re.compile(r"^- (\*\*V[1-5] [^*]+\*\* — .+)$")
LINK_RE = re.compile(r"^(Closes|Refs) #([0-9]+)$")
FENCE_RE = re.compile(r"^ {0,3}(```|~~~)")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def normalize(text: str) -> str:
    """`**` 와 줄 앞의 `> ` 를 걷고 공백을 하나로 줄인다. 글자는 바꾸지 않는다."""
    return " ".join(text.replace("**", "").split())


def load_values(path: Path = DEFAULT_VALUES) -> list[str]:
    """values.md 의 V1~V5 한 줄씩(정규화됨)."""
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = VALUE_LINE_RE.match(line)
        if m:
            values.append(normalize(m.group(1)))
    if len(values) != 5:
        raise ValueError(f"{path}: V1~V5 줄이 5개여야 한다. {len(values)}개를 읽었다")
    return values


def body_lines(body: str) -> list[str]:
    """HTML 주석과 코드 블록을 지운 줄 목록."""
    body = COMMENT_RE.sub("", body.replace("\r\n", "\n").replace("\r", "\n"))
    lines, fence = [], None
    for line in body.split("\n"):
        m = FENCE_RE.match(line)
        if m:
            if fence is None:
                fence = m.group(1)
            elif m.group(1) == fence:
                fence = None
            continue
        if fence is None:
            lines.append(line.rstrip())
    return lines


def check(body: str, values: list[str]) -> list[str]:
    """위반 목록. 비어 있으면 통과."""
    lines = body_lines(body or "")
    headings = [i for i, line in enumerate(lines) if line.startswith("## ")]

    def section(title: str) -> tuple[int, list[str]] | None:
        for i in headings:
            if lines[i] == title:
                end = next((j for j in headings if j > i), len(lines))
                return i, lines[i + 1 : end]
        return None

    errors: list[str] = []
    goal = section(GOAL_HEADING)
    vals = section(VALUES_HEADING)

    if goal is None:
        errors.append(f"`{GOAL_HEADING}` 제목이 없다")
    elif not any(line.strip() for line in goal[1]):
        errors.append(f"`{GOAL_HEADING}` 절이 비었다. 대목표(G0~G5)를 적는다")

    if vals is None:
        errors.append(f"`{VALUES_HEADING}` 제목이 없다")
    else:
        quote = normalize(" ".join(line[1:] for line in vals[1] if line.startswith(">")))
        if not any(v in quote for v in values):
            errors.append(
                f"`{VALUES_HEADING}` 절에 docs/plan/values.md 의 V1~V5 문장이 `> ` 인용으로 원문 그대로 있어야 한다"
            )

    links = [(i, m) for i, line in enumerate(lines) if (m := LINK_RE.match(line))]
    if not links:
        errors.append("`Closes #N` 또는 `Refs #N` 만 있는 줄이 없다 (이슈 번호는 숫자, 예: `Closes #13`)")
    elif sum(m.group(1) == "Closes" for _, m in links) > 1:
        errors.append("`Closes #N` 은 잎 이슈 하나만 쓴다")

    if goal and vals and goal[0] > vals[0]:
        errors.append(f"순서가 다르다: `{GOAL_HEADING}` 가 `{VALUES_HEADING}` 보다 앞에 와야 한다")
    if vals and links and links[0][0] < vals[0]:
        errors.append(f"순서가 다르다: `Closes #N`/`Refs #N` 은 `{VALUES_HEADING}` 뒤에 와야 한다")
    if goal and links and links[0][0] < goal[0]:
        errors.append(f"순서가 다르다: `Closes #N`/`Refs #N` 은 `{GOAL_HEADING}` 뒤에 와야 한다")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--body-file", type=Path, help="없으면 환경 변수 PR_BODY 를 읽는다")
    ap.add_argument("--values", type=Path, default=DEFAULT_VALUES)
    args = ap.parse_args(argv)
    if args.body_file:
        body = args.body_file.read_text(encoding="utf-8")
    elif "PR_BODY" in os.environ:
        body = os.environ["PR_BODY"]
    else:
        print("error: --body-file 이나 환경 변수 PR_BODY 가 필요하다", file=sys.stderr)
        return 2
    try:
        errors = check(body, load_values(args.values))
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if errors:
        print("PR 본문이 규칙을 어겼다 (.github/pull_request_template.md 순서: 대목표 → 핵심 가치 → 문제 `Closes #N`):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("ok: PR 본문이 대목표, 핵심 가치 원문 인용, Closes/Refs 규칙을 지킨다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
