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

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),  # OpenRouter / OpenAI 형태
    re.compile(r"(?i)\bBearer\s+[^\s\"']+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),  # GitHub 토큰(classic, OAuth, 앱 등)
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),  # GitHub fine-grained PAT
)


class ReviewError(Exception):
    """리뷰 봇이 사용자에게 보여 줄 오류. 메시지는 이미 마스킹돼 있다."""


def redact(text: str) -> str:
    """환경변수의 키 값과 키처럼 생긴 문자열을 가린다."""
    key = os.environ.get(KEY_ENV, "")
    if len(key) >= 4:
        text = text.replace(key, "***")
    for pat in _SECRET_PATTERNS:
        text = pat.sub("***", text)
    return text


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
