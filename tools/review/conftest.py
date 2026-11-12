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
    for name in ("KINETRA_REVIEW_ENDPOINT", "KINETRA_REVIEW_MODEL", "KINETRA_REVIEW_EFFORT"):
        monkeypatch.delenv(name, raising=False)  # 바깥 셸의 끝점 설정이 테스트에 새지 않게
    return state


@pytest.fixture
def pr101_dir(tmp_path):
    dst = tmp_path / "pr101"
    shutil.copytree(FIXTURES / "pr101", dst)
    return dst


@pytest.fixture
def curl_queue(tmp_path, monkeypatch):
    """가짜 curl 의 응답 큐. 사용: q = curl_queue("ok.json", "http_429.json"). 호출 기록은 q.log()."""
    import json

    qdir = tmp_path / "curlq"
    qdir.mkdir()
    log = tmp_path / "curl_log.jsonl"
    monkeypatch.setenv("FAKE_CURL_QUEUE", str(qdir))
    monkeypatch.setenv("FAKE_CURL_LOG", str(log))

    class Q:
        def __call__(self, *names):
            for i, name in enumerate(names, 1):
                shutil.copy(FIXTURES / "responses" / name, qdir / f"{i}.json")
            return self

        def log(self):
            return [json.loads(ln) for ln in log.read_text().splitlines()] if log.exists() else []

        @property
        def count(self):
            return len(self.log())

    return Q()
