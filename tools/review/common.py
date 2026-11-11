"""리뷰 봇 공용 도우미 (P0-06). 표준 라이브러리만 쓴다.

gh 호출과 비밀 마스킹이 여기 모여 있다. 사람이 읽는 출력(표준출력, 표준오류, PR 코멘트)에 들어가는
문자열은 전부 `redact()` 를 거친다. 키는 환경변수 `OPENROUTER_API_KEY` 로만 받는다.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY_ENV = "OPENROUTER_API_KEY"

# Bearer 뒤는 비밀 모양(충분히 긴 토큰 문자열)일 때만 가린다. `{self._key}`, `$TOKEN`, `os.environ[...]` 같은 코드 표현식은
# 문자 집합(`{`, `$`, `[`, `(` 가 없다)과 길이로 걸러진다. 문자 집합에 맞는 20자 이상 토큰은 숫자가 없어도 가린다.
# 예외는 `self.` 같은 객체 이름으로 시작하는 속성 접근 하나뿐이다(_is_code). 구분자는 같은 줄의 공백·탭이라 한 곳이 줄을 넘지 않는다.
BEARER_MIN = 20
_BEARER = re.compile(r"(?i)\bBearer[ \t]+([A-Za-z0-9._~+/=\-]{%d,})" % BEARER_MIN)
_ATTR_ACCESS = re.compile(r"(?:self|cls|this|os|config|cfg|settings|secrets)(?:\.[A-Za-z_][A-Za-z0-9_]*)+")

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),  # OpenRouter / OpenAI 형태
    _BEARER,
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),  # GitHub 토큰(classic, OAuth, 앱 등)
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),  # GitHub fine-grained PAT
)


class ReviewError(Exception):
    """리뷰 봇이 사용자에게 보여 줄 오류. 메시지는 이미 마스킹돼 있다."""


def _is_code(token: str) -> bool:
    """`self._openrouter_api_key` 처럼 알려진 객체 이름에서 시작하는 속성 접근 하나만 소스 표현식으로 본다."""
    return _ATTR_ACCESS.fullmatch(token) is not None


def _spans(text: str) -> list[tuple[int, int]]:
    """가릴 구간(겹치면 합친다). 원문 기준 오프셋이라 줄 번호가 정확하다."""
    found: list[tuple[int, int]] = []
    key = os.environ.get(KEY_ENV, "")
    if len(key) >= 4:
        found += [(m.start(), m.end()) for m in re.finditer(re.escape(key), text)]
    for pat in _SECRET_PATTERNS:
        for m in pat.finditer(text):
            if pat is _BEARER and _is_code(m.group(1)):
                continue
            found.append((m.start(), m.end()))
    found.sort()
    merged: list[tuple[int, int]] = []
    for a, b in found:
        if merged and a < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def redact_report(text: str) -> tuple[str, int, list[int]]:
    """(가린 글, 가린 곳 수, 가린 곳이 있는 줄 번호들). 줄 번호는 **가린 글** 기준 1부터다(모델이 보는 글과 같다).
    한 곳이 여러 줄에 걸쳐 `***` 하나로 줄어도 번호가 어긋나지 않게, 가린 글의 개행 수를 누적해 센다."""
    spans = _spans(text)
    if not spans:
        return text, 0, []
    out: list[str] = []
    lines: list[int] = []
    pos = 0
    newlines = 0  # 지금까지 출력(out)에 쓴 개행 수
    for a, b in spans:
        chunk = text[pos:a]
        out += [chunk, "***"]
        newlines += chunk.count("\n")
        pos = b
        if not lines or lines[-1] != newlines + 1:
            lines.append(newlines + 1)
    out.append(text[pos:])
    return "".join(out), len(spans), lines


def redact(text: str) -> str:
    """환경변수의 키 값과 키처럼 생긴 문자열을 가린다."""
    return redact_report(text)[0]


def redact_obj(obj):
    """JSON 으로 만들 값의 모든 문자열(키 이름 포함)을 직렬화 **전에** 가린다. 직렬화하면 따옴표·역슬래시·개행이
    이스케이프돼 키가 문자열 검색으로 안 잡힐 수 있어서다."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {redact(k) if isinstance(k, str) else k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v) for v in obj]
    return obj


def api_key() -> str:
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise ReviewError(f"{KEY_ENV} 환경변수가 없다. 키는 환경변수로만 받는다.")
    return key


def run(argv: list[str], *, input: str | None = None, timeout: float | None = None) -> str:
    """명령을 실행해 표준출력을 돌려준다. 실패하면 마스킹한 ReviewError."""
    try:
        p = subprocess.run(argv, input=input, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as e:
        raise ReviewError(f"{argv[0]} 를 찾을 수 없다") from e
    except subprocess.TimeoutExpired as e:
        raise ReviewError(f"{argv[0]} 가 {timeout}초 안에 끝나지 않았다") from e
    if p.returncode != 0:
        detail = redact((p.stderr or p.stdout or "").strip())[:500]
        raise ReviewError(f"{' '.join(argv[:3])} 실패(종료 코드 {p.returncode}): {detail}")
    return p.stdout


def gh(*args: str, input: str | None = None) -> str:
    return run(["gh", *args], input=input, timeout=120)


def default_repo() -> str:
    return gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner").strip()
