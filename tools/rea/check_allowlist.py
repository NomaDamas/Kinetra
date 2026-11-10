"""`tools/rea/allowlist.txt` 형식 검사 (A0-06a). 표준 라이브러리만 쓴다.

    uv run python tools/rea/check_allowlist.py   (저장소 루트에서, 오류가 있으면 종료 코드 1)

형식은 `docs/process/rea-policy.md`의 "목록 파일 형식"이 정한다.
"""

from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent / "allowlist.txt"
SEP = " | "
FIELDS = 7
# 종류 -> 허용되는 구분. 허용적 라이선스와 우리 빌드만 allow, 나머지는 조건부.
KIND_TO_CLASS = {
    "own-build": "allow",
    "oss-permissive": "allow",
    "oss-copyleft": "conditional",
    "public-web": "conditional",
}
# 금지 대상(독점 게임)은 목록에 있을 수 없다. 이름이 대상 칸에 보이면 거부한다.
FORBIDDEN = ("ksp", "kerbal", "space engineers", "spaceengineers", "juno", "besiege")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def check_text(text: str) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    rows = 0
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        rows += 1
        f = raw.split(SEP)
        if len(f) != FIELDS:
            errors.append(f"{n}: 필드가 {len(f)}개다(기대 {FIELDS}개, 구분자는 '{SEP}')")
            continue
        cls, kind, target, lic, url, date, _note = (x.strip() for x in f)
        if kind not in KIND_TO_CLASS:
            errors.append(f"{n}: 종류 '{kind}'는 {sorted(KIND_TO_CLASS)} 중 하나여야 한다")
        elif cls != KIND_TO_CLASS[kind]:
            errors.append(f"{n}: 종류 '{kind}'의 구분은 '{KIND_TO_CLASS[kind]}'여야 한다(받은 값 '{cls}')")
        if not target or not lic:
            errors.append(f"{n}: 대상과 라이선스는 비어 있을 수 없다")
        if not url.startswith("https://"):
            errors.append(f"{n}: 확인 URL은 https:// 로 시작해야 한다")
        try:
            if not DATE.fullmatch(date):
                raise ValueError
            datetime.date.fromisoformat(date)
        except ValueError:
            errors.append(f"{n}: 확인 날짜 '{date}'는 실존하는 YYYY-MM-DD여야 한다")
        low = target.lower()
        for name in FORBIDDEN:
            if name in low:
                errors.append(f"{n}: 금지 대상('{name}')은 목록에 쓸 수 없다")
        if target in seen:
            errors.append(f"{n}: 대상 '{target}'이 중복이다")
        seen.add(target)
    if rows == 0:
        errors.append("목록에 대상이 하나도 없다")
    return errors


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    errors = check_text(path.read_text(encoding="utf-8"))
    for e in errors:
        print(f"{path}:{e}", file=sys.stderr)
    if not errors:
        print(f"OK {path}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
