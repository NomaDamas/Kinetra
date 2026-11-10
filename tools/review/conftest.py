"""리뷰 봇 테스트 공용 픽스처. 네트워크는 쓰지 않는다: gh 는 tests/fakes/gh, OpenRouter 는 가짜 curl 이다."""

import shutil
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FAKES = HERE / "tests" / "fakes"
FIXTURES = HERE / "tests" / "fixtures"

FAKE_KEY = "sk-or-v1-FAKEKEYFORTESTS0123456789abcdef"


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    """PATH 앞에 가짜 gh(/curl)를 둔다. 반환: 상태 파일 경로. 진짜 키는 절대 쓰지 않는다."""
    monkeypatch.setenv("PATH", f"{FAKES}:{__import__('os').environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_DIR", str(FIXTURES / "pr101"))
    state = tmp_path / "gh_state.json"
    monkeypatch.setenv("FAKE_GH_STATE", str(state))
    monkeypatch.setenv("FAKE_GH_LOG", str(tmp_path / "gh_log.jsonl"))
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    return state


@pytest.fixture
def pr101_dir(tmp_path):
    dst = tmp_path / "pr101"
    shutil.copytree(FIXTURES / "pr101", dst)
    return dst
