"""`assets/LEDGER.csv` 에서 `CREDITS.md` 를 만든다 (P0-05a). 표준 라이브러리만 쓴다.

    uv run python tools/assets/credits.py            # CREDITS.md 를 쓴다
    uv run python tools/assets/credits.py --check    # 쓰지 않고, 디스크의 CREDITS.md 가 원장과 같은지만 본다

원장은 출처와 라이선스가 기록된 것만 제품에 들인다는 V5 의 단일 원본이다.

열 (순서 고정, 머리글이 정확히 같아야 한다)
    에셋 ID, 경로, 원본 URL, 저작자, 라이선스(SPDX), 받은 날짜, 원본 해시, 변경 내역, 용도, 표기 문구, 확인자, kind

`kind` 는 행이 무엇인지 나눈다.
    asset       제품에 들어가는 파일(모델, 텍스처, HDRI, 소리 등). `경로` 는 저장소 안의 그 파일이다.
                `원본 해시` 는 받은 원본 파일의 `sha256:<hex>`.
    dependency  실행·개발 도구 의존성(PyPI 패키지 등). `경로` 는 그것을 쓰는 저장소 안의 파일이다.
                `원본 해시` 는 확인한 배포본(sdist)의 `sha256:<hex>`. 버전은 에셋 ID에 넣는다.

여러 URL 은 공백으로 구분한다. 줄바꿈은 허용하지 않는다. 같은 입력이면 같은 출력이다(행 순서는
kind(asset 먼저), 에셋 ID 순). 라이선스가 비었거나 NC 계열이거나 NOASSERTION 이면 거부한다.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = ROOT / "assets" / "LEDGER.csv"
DEFAULT_OUT = ROOT / "CREDITS.md"

COLUMNS = [
    "에셋 ID",
    "경로",
    "원본 URL",
    "저작자",
    "라이선스(SPDX)",
    "받은 날짜",
    "원본 해시",
    "변경 내역",
    "용도",
    "표기 문구",
    "확인자",
    "kind",
]
KINDS = ("asset", "dependency")
SECTIONS = {"asset": "에셋 (asset)", "dependency": "의존성 (dependency)"}
HASH_RE = re.compile(r"sha256:[0-9a-f]{64}")
BAD_LICENSE_RE = re.compile(r"NOASSERTION|UNKNOWN|NONE|(^|[-\s(])NC([-\s).]|$)", re.IGNORECASE)

HEADER = (
    "# CREDITS\n"
    "\n"
    "<!-- 이 파일은 `tools/assets/credits.py`가 `assets/LEDGER.csv`에서 생성한다. 직접 고치지 않는다. -->\n"
)


class LedgerError(ValueError):
    pass


def read_ledger(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise LedgerError(f"{path}: 비어 있다") from None
        if header != COLUMNS:
            raise LedgerError(f"{path}: 머리글이 다르다. 기대 {COLUMNS}, 실제 {header}")
        rows = []
        for line_no, cells in enumerate(reader, start=2):
            if not cells:
                continue
            if len(cells) != len(COLUMNS):
                raise LedgerError(f"{path}:{line_no}: 열이 {len(cells)}개다. {len(COLUMNS)}개여야 한다")
            row = dict(zip(COLUMNS, cells))
            _validate(row, f"{path}:{line_no}")
            rows.append(row)
    seen: set[str] = set()
    for row in rows:
        if row["에셋 ID"] in seen:
            raise LedgerError(f"{path}: 에셋 ID 중복: {row['에셋 ID']}")
        seen.add(row["에셋 ID"])
    return rows


def _validate(row: dict[str, str], where: str) -> None:
    for col, value in row.items():
        if not value.strip():
            raise LedgerError(f"{where}: '{col}'이 비었다 (변경 내역이 없으면 '없음'이라고 적는다)")
        if "\n" in value or "\r" in value:
            raise LedgerError(f"{where}: '{col}'에 줄바꿈이 있다")
        if value != value.strip():
            raise LedgerError(f"{where}: '{col}'의 앞뒤에 공백이 있다")
    if row["kind"] not in KINDS:
        raise LedgerError(f"{where}: kind는 {KINDS} 중 하나여야 한다: {row['kind']!r}")
    if BAD_LICENSE_RE.search(row["라이선스(SPDX)"]):
        raise LedgerError(f"{where}: 허용하지 않는 라이선스: {row['라이선스(SPDX)']!r}")
    if not HASH_RE.fullmatch(row["원본 해시"]):
        raise LedgerError(f"{where}: 원본 해시는 'sha256:<소문자 hex 64자>'여야 한다: {row['원본 해시']!r}")
    try:
        date.fromisoformat(row["받은 날짜"])
    except ValueError:
        raise LedgerError(f"{where}: 받은 날짜는 YYYY-MM-DD여야 한다: {row['받은 날짜']!r}") from None


def render(rows: list[dict[str, str]]) -> str:
    out = [HEADER]
    for kind in KINDS:
        out.append(f"\n## {SECTIONS[kind]}\n")
        section = sorted((r for r in rows if r["kind"] == kind), key=lambda r: r["에셋 ID"])
        if not section:
            out.append("\n(없음)\n")
        for r in section:
            out.append(
                f"\n### {r['에셋 ID']}\n"
                "\n"
                f"- 표기: {r['표기 문구']}\n"
                f"- 저작자: {r['저작자']}\n"
                f"- 라이선스: {r['라이선스(SPDX)']}\n"
                f"- 원본: {r['원본 URL']}\n"
                f"- 경로: `{r['경로']}`\n"
                f"- 용도: {r['용도']}\n"
                f"- 변경 내역: {r['변경 내역']}\n"
                f"- 받은 날짜: {r['받은 날짜']}\n"
                f"- 원본 해시: `{r['원본 해시']}`\n"
                f"- 확인자: {r['확인자']}\n"
            )
    return "".join(out)


def generate(ledger: Path = DEFAULT_LEDGER) -> str:
    return render(read_ledger(ledger))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true", help="쓰지 않고 --out 이 원장과 같은지만 확인한다")
    args = ap.parse_args(argv)
    try:
        text = generate(args.ledger)
    except (LedgerError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else None
        if current != text:
            print(f"error: {args.out}이 {args.ledger}과 다르다. credits.py를 다시 실행한다", file=sys.stderr)
            return 1
        print(f"ok: {args.out}")
        return 0
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
