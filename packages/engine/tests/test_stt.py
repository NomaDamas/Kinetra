"""I-01a dictation. Offline: logic tests use a fake model; the fixture test runs the real pinned model only when it is in the local cache.

    uv run pytest packages/engine -q -k stt

The real-model test is skipped (and says why) on a machine that has not run `python -m kinetra_engine.stt fetch`, CI included:
the model is 462 MiB and is not fetched by tests.
"""

import io
import json
import math
import os
import struct
import wave
from pathlib import Path

import pytest
from kinetra_engine import stt
from kinetra_engine.stt import __main__ as stt_cli
from kinetra_engine.stt import score, transcriber

FIXTURES = Path(__file__).parent / "fixtures" / "stt"
ROOT = Path(__file__).resolve().parents[3]


def wav_bytes(seconds=1.0, rate=16000, freq=440.0):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(int(seconds * rate))))
    return buf.getvalue()


class Seg:
    def __init__(self, text):
        self.text = text


class FakeModel:
    def __init__(self, path, **kw):
        self.path, self.kw, self.calls = path, kw, []

    def transcribe(self, samples, **kw):
        self.calls.append((len(samples), kw))
        return iter([Seg(" 지붕 질량을 "), Seg(""), Seg("2킬로그램으로 바꿔 줘 ")]), object()


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(transcriber, "find_model", lambda model_dir=None: tmp_path)
    monkeypatch.setattr(transcriber, "verify_snapshot", lambda path: None)  # the hash check has its own tests below
    return tmp_path


def make(snapshot):
    return stt.Transcriber(loader=FakeModel)


# ---------------------------------------------------------------- DoD: voice -> text API


def test_stt_transcribe_returns_joined_text_and_metadata(snapshot):
    t = make(snapshot)
    out = t.transcribe(wav_bytes(2.0))
    assert out.text == "지붕 질량을 2킬로그램으로 바꿔 줘"
    assert (out.language, out.model) == ("ko", f"{stt.MODEL_REPO}@{stt.MODEL_REVISION}")
    assert out.duration_s == pytest.approx(2.0, abs=0.01)


def test_stt_model_is_loaded_offline_on_cpu_and_decoding_is_deterministic(snapshot):
    t = make(snapshot)
    t.transcribe(wav_bytes())
    m = t._model
    assert m.kw["local_files_only"] is True and m.kw["device"] == "cpu" and m.kw["compute_type"] == "int8"
    (n, kw), = m.calls
    assert n == 16000
    assert kw["language"] == "ko" and kw["temperature"] == 0.0 and kw["condition_on_previous_text"] is False and kw["vad_filter"] is True


def test_stt_accepts_a_file_path(snapshot, tmp_path):
    p = tmp_path / "a.wav"
    p.write_bytes(wav_bytes())
    assert make(snapshot).transcribe(p).text.startswith("지붕")
    assert make(snapshot).transcribe(str(p)).duration_s == pytest.approx(1.0, abs=0.01)


def test_stt_resamples_other_rates_to_16k(snapshot):
    t = make(snapshot)
    assert t.transcribe(wav_bytes(1.0, rate=44100)).duration_s == pytest.approx(1.0, abs=0.01)
    assert t._model.calls[0][0] == pytest.approx(16000, abs=2)


# ---------------------------------------------------------------- input limits are checked before the model runs


@pytest.mark.parametrize("bad", [b"", b"not audio at all" * 100, b"RIFF\x00\x00\x00\x00WAVE"])
def test_stt_rejects_empty_and_undecodable_audio(snapshot, bad):
    t = make(snapshot)
    with pytest.raises(stt.AudioRejected):
        t.transcribe(bad)
    assert t._model.calls == []


def test_stt_rejects_too_long_and_too_large_audio(snapshot, monkeypatch):
    t = make(snapshot)
    with pytest.raises(stt.AudioRejected, match="longer than the 60 s limit"):
        t.transcribe(wav_bytes(61.0, rate=8000))
    monkeypatch.setattr(transcriber, "MAX_AUDIO_BYTES", 1000)
    with pytest.raises(stt.AudioRejected, match="byte limit"):
        t.transcribe(wav_bytes(1.0))
    assert t._model.calls == []


def test_stt_declared_long_audio_is_refused_before_any_frame_is_decoded(snapshot, monkeypatch):
    import av

    decoded = []
    real = av.audio.resampler.AudioResampler.resample
    monkeypatch.setattr(av.audio.resampler.AudioResampler, "resample", lambda self, f: decoded.append(f) or real(self, f))
    with pytest.raises(stt.AudioRejected, match="longer than the 60 s limit"):
        make(snapshot).transcribe(wav_bytes(600.0, rate=8000))  # 600 s declared in the header
    assert decoded == []


def test_stt_decode_stops_at_the_limit_when_the_container_declares_no_duration(snapshot, monkeypatch):
    """A stream that does not declare its length (live webm) is cut off after the limit instead of being decoded whole."""
    import av

    class NoDuration:
        def __init__(self, c):
            self._c = c

        duration = None

        def __getattr__(self, name):
            return getattr(self._c, name)

        def __enter__(self):
            self._c.__enter__()
            return self

        def __exit__(self, *a):
            return self._c.__exit__(*a)

    real_open, real_resample, frames = av.open, av.audio.resampler.AudioResampler.resample, []
    monkeypatch.setattr(av, "open", lambda *a, **k: NoDuration(real_open(*a, **k)))
    monkeypatch.setattr(av.audio.resampler.AudioResampler, "resample", lambda self, f: frames.append(f) or real_resample(self, f))
    data = wav_bytes(900.0, rate=8000)  # 900 s, 14 MB
    total = 900 * 8000 // 512  # the number of 512-sample frames if everything were decoded
    with pytest.raises(stt.AudioRejected, match="longer than the 60 s limit"):
        make(snapshot).transcribe(data)
    assert 0 < len(frames) < total / 10, (len(frames), total)  # stopped near 60 s, not at 900 s


def test_stt_audio_just_under_the_limit_is_accepted(snapshot):
    assert make(snapshot).transcribe(wav_bytes(59.0, rate=8000)).duration_s == pytest.approx(59.0, abs=0.05)


def test_stt_unknown_language_is_an_stt_error(snapshot):
    t = make(snapshot)
    for bad in ("zz", "", "KO", "ko-KR"):
        with pytest.raises(stt.SttError):
            t.transcribe(wav_bytes(), language=bad)
    with pytest.raises(stt.SttError):
        t.transcribe(wav_bytes(), language=None)  # type: ignore[arg-type]
    assert t._model.calls == []
    assert t.transcribe(wav_bytes(), language="en").language == "en"


def test_stt_cli_bad_language_is_an_error_line_not_a_traceback(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(transcriber, "find_model", lambda model_dir=None: tmp_path)
    monkeypatch.setattr(transcriber, "verify_snapshot", lambda path: None)
    monkeypatch.setattr(stt_cli, "Transcriber", lambda: stt.Transcriber(loader=FakeModel))
    p = tmp_path / "a.wav"
    p.write_bytes(wav_bytes())
    assert stt_cli.main(["transcribe", str(p), "--language", "zz"]) == 1
    assert "error:" in capsys.readouterr().err


# ---------------------------------------------------------------- only local audio containers are opened (no sockets, no other files)

SDP = b"v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=x\r\nc=IN IP4 127.0.0.1\r\nt=0 0\r\nm=audio 45712 RTP/AVP 0\r\na=rtpmap:0 PCMU/8000\r\n"


@pytest.fixture
def no_network(monkeypatch):
    """Guards the two ways the decoder could reach the network. FFmpeg opens its sockets in C, so blocking Python's `socket` alone sees
    nothing: the fixture also samples the process's open file descriptors every 2 ms. At teardown the test fails if Python's socket
    functions were called or if the descriptor count ever rose above its starting value."""
    import socket
    import threading
    import time

    attempts = []

    def deny(name):
        def f(*a, **k):
            attempts.append(("python", name))
            raise OSError(f"network blocked in test: {name}")

        return f

    for name in ("connect", "bind", "sendto", "recvfrom"):
        monkeypatch.setattr(socket.socket, name, deny(name))
    monkeypatch.setattr(socket, "getaddrinfo", deny("getaddrinfo"))
    base = len(os.listdir("/dev/fd"))
    peak = [base]
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            peak[0] = max(peak[0], len(os.listdir("/dev/fd")))
            time.sleep(0.002)

    th = threading.Thread(target=sample, daemon=True)
    th.start()
    yield attempts
    stop.set()
    th.join()
    assert not attempts, f"python-level network calls: {attempts}"
    assert peak[0] <= base, f"open file descriptors rose from {base} to {peak[0]} while decoding (a socket or another file was opened)"


def run_bounded(fn, seconds=15):
    """Run `fn()` in a thread; fail the test if it does not return in time (a decoder waiting for packets never does). Returns (result, exception)."""
    import threading

    box = {}

    def target():
        try:
            box["result"] = fn()
        except BaseException as e:  # noqa: BLE001 - reported to the test
            box["error"] = e

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(seconds)
    assert not th.is_alive(), f"the decoder did not return within {seconds} s (waiting on the network?)"
    return box.get("result"), box.get("error")


def test_stt_sdp_bytes_are_rejected_without_opening_a_socket(snapshot, no_network):
    t = make(snapshot)
    _, err = run_bounded(lambda: t.transcribe(SDP))
    assert isinstance(err, stt.AudioRejected), err
    assert t._model.calls == []


def test_stt_ffconcat_bytes_are_rejected_without_reading_other_files(snapshot, no_network, tmp_path, monkeypatch):
    other = tmp_path / "other.wav"
    other.write_bytes(wav_bytes(3.0))
    monkeypatch.chdir(tmp_path)
    t = make(snapshot)
    for body in (b"ffconcat version 1.0\nfile other.wav\n", f"ffconcat version 1.0\nfile {other}\n".encode(), b"#EXTM3U\n#EXTINF:1,\nother.wav\n"):
        _, err = run_bounded(lambda body=body: t.transcribe(body))
        assert isinstance(err, stt.AudioRejected), (body, err)
    assert t._model.calls == []


def test_stt_a_path_to_an_sdp_or_url_is_rejected_too(snapshot, no_network, tmp_path):
    p = tmp_path / "x.sdp"
    p.write_bytes(SDP)
    t = make(snapshot)
    assert isinstance(run_bounded(lambda: t.transcribe(p))[1], stt.AudioRejected)
    assert isinstance(run_bounded(lambda: t.transcribe("rtp://127.0.0.1:45712"))[1], stt.AudioRejected)  # not a file path


@pytest.mark.parametrize("suffix,args", [("webm", ["-c:a", "libopus"]), ("ogg", ["-c:a", "libopus"]), ("m4a", ["-c:a", "aac"]), ("mp3", []), ("flac", [])])
def test_stt_browser_and_upload_containers_still_decode(snapshot, tmp_path, suffix, args):
    """Whitelisted containers made with PyAV from a tone: bytes and path. (Real browser output is I-01b's check.)"""
    import av
    import numpy as np

    out = tmp_path / f"a.{suffix}"
    codec = {"webm": "libopus", "ogg": "libopus", "m4a": "aac", "mp3": "mp3", "flac": "flac"}[suffix]
    rate = 48000 if codec == "libopus" else 44100
    with av.open(str(out), "w") as c:
        st = c.add_stream(codec, rate=rate)
        st.layout = "mono"
        tone = (np.sin(2 * np.pi * 440 * np.arange(rate) / rate) * 8000).astype(np.int16).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(tone, format="s16", layout="mono")
        frame.sample_rate = rate
        for pkt in st.encode(frame):
            c.mux(pkt)
        for pkt in st.encode(None):
            c.mux(pkt)
    t = make(snapshot)
    assert t.transcribe(out.read_bytes()).duration_s == pytest.approx(1.0, abs=0.1)
    assert t.transcribe(out).duration_s == pytest.approx(1.0, abs=0.1)


def test_stt_missing_file_is_rejected_without_leaking_the_path_text(snapshot, tmp_path):
    with pytest.raises(stt.AudioRejected) as e:
        make(snapshot).transcribe(tmp_path / "secret-name.wav")
    assert "secret-name" not in str(e.value)


def test_stt_no_speech_gives_empty_text(snapshot):
    class Silent(FakeModel):
        def transcribe(self, samples, **kw):
            return iter([]), object()

    assert stt.Transcriber(loader=Silent).transcribe(wav_bytes()).text == ""


# ---------------------------------------------------------------- the model: pinned, verified, never downloaded by a Transcriber


def test_stt_without_the_model_fails_instead_of_downloading(tmp_path):
    with pytest.raises(stt.ModelMissing, match="stt fetch"):
        stt.Transcriber(model_dir=tmp_path / "empty", loader=FakeModel)


def test_stt_find_model_uses_only_the_local_cache(monkeypatch, tmp_path):
    seen = {}

    def fake(repo, **kw):
        seen.update(repo=repo, **kw)
        return str(tmp_path)

    monkeypatch.setattr("faster_whisper.utils.download_model", fake)
    assert stt.find_model(tmp_path) == tmp_path
    assert seen["local_files_only"] is True and seen["revision"] == stt.MODEL_REVISION and seen["repo"] == stt.MODEL_REPO
    assert seen["cache_dir"] == str(tmp_path)


def test_stt_model_dir_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(stt.MODEL_DIR_ENV, str(tmp_path))
    assert transcriber.model_root() == tmp_path
    monkeypatch.delenv(stt.MODEL_DIR_ENV)
    assert transcriber.model_root() is None


def fake_cache(tmp_path, monkeypatch):
    """A cache whose four files hash to the (patched) pins, so the real verify_snapshot runs on it."""
    for n in transcriber.MODEL_FILES:
        (tmp_path / n).write_bytes(f"original {n}".encode())
    monkeypatch.setattr(transcriber, "MODEL_HASHES", {n: transcriber._sha256(tmp_path / n) for n in transcriber.MODEL_FILES})
    monkeypatch.setattr(transcriber, "find_model", lambda model_dir=None: tmp_path)


def test_stt_verify_snapshot_checks_files_and_hashes(tmp_path, monkeypatch):
    with pytest.raises(stt.ModelMissing, match="missing"):
        transcriber.verify_snapshot(tmp_path)
    for n in transcriber.MODEL_FILES:
        (tmp_path / n).write_bytes(b"x")
    with pytest.raises(stt.ModelMissing, match="pinned"):
        transcriber.verify_snapshot(tmp_path)
    fake_cache(tmp_path, monkeypatch)
    transcriber.verify_snapshot(tmp_path)


@pytest.mark.parametrize("name", ["model.bin", "config.json", "tokenizer.json", "vocabulary.txt"])
def test_stt_load_verifies_every_cached_file_every_time(tmp_path, monkeypatch, name):
    """An edited, truncated or emptied cached file is refused when a Transcriber loads, whichever of the four files it is."""
    fake_cache(tmp_path, monkeypatch)
    loaded = []

    def loader(*a, **k):
        loaded.append(a)
        return FakeModel(*a, **k)

    stt.Transcriber(loader=loader)
    assert len(loaded) == 1
    for damage in (b"tampered", b"orig", b""):  # edited, truncated, emptied
        (tmp_path / name).write_bytes(damage)
        with pytest.raises(stt.ModelMissing, match="pinned"):
            stt.Transcriber(loader=loader)
    assert len(loaded) == 1  # a damaged model was never handed to the loader
    (tmp_path / name).unlink()
    with pytest.raises(stt.ModelMissing, match="missing"):
        stt.Transcriber(loader=FakeModel)


def test_stt_pins_cover_all_four_files_and_match_the_documented_values():
    assert set(transcriber.MODEL_HASHES) == {"config.json", "model.bin", "tokenizer.json", "vocabulary.txt"}
    assert all(len(h) == 64 and set(h) <= set("0123456789abcdef") for h in transcriber.MODEL_HASHES.values())
    assert transcriber.MODEL_HASHES["model.bin"].startswith("3e305921")


def test_stt_a_model_the_library_cannot_read_is_model_missing_not_a_library_error(snapshot):
    def broken(*a, **k):
        raise RuntimeError("Unable to open file 'model.bin'")

    with pytest.raises(stt.ModelMissing, match="could not be loaded"):
        stt.Transcriber(loader=broken)


def test_stt_fetch_is_the_only_network_path_and_verifies(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(transcriber, "_snapshot", lambda local, d: calls.append(local) or str(tmp_path))
    with pytest.raises(stt.ModelMissing):
        stt.fetch_model()
    assert calls == [False]


def test_stt_pinned_revision_is_a_commit_hash():
    assert len(stt.MODEL_REVISION) == 40 and set(stt.MODEL_REVISION) <= set("0123456789abcdef")


def test_stt_cli_fetch_refuses_outside_the_resource_guard(monkeypatch, capsys):
    monkeypatch.delenv("KINETRA_GUARD_PASSED", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(stt_cli, "fetch_model", lambda: pytest.fail("must not download"))
    assert stt_cli.main(["fetch"]) == 2
    assert "resource guard" in capsys.readouterr().err


def test_stt_cli_transcribe_reports_errors_without_a_traceback(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(transcriber, "find_model", lambda model_dir=None: tmp_path)
    monkeypatch.setattr(transcriber, "verify_snapshot", lambda path: None)
    monkeypatch.setattr(stt_cli, "Transcriber", lambda: stt.Transcriber(loader=FakeModel))
    p = tmp_path / "a.wav"
    p.write_bytes(wav_bytes())
    assert stt_cli.main(["transcribe", str(p)]) == 0
    assert capsys.readouterr().out.strip() == "지붕 질량을 2킬로그램으로 바꿔 줘"
    assert stt_cli.main(["transcribe", str(tmp_path / "missing.wav")]) == 1
    assert "error:" in capsys.readouterr().err


# ---------------------------------------------------------------- keys: this path has none


def test_stt_path_holds_no_key_and_no_network_client():
    """The product path is local: no key variable, no HTTP client in the package (the measurement tool is under tools/stt)."""
    for p in (ROOT / "packages/engine/src/kinetra_engine/stt").glob("*.py"):
        text = p.read_text(encoding="utf-8")
        for needle in ("OPENROUTER_API_KEY", "urllib.request", "import requests", "import httpx", "Authorization"):
            assert needle not in text, f"{p.name} mentions {needle}"


def test_stt_does_not_log_or_store_audio_or_text():
    for p in (ROOT / "packages/engine/src/kinetra_engine/stt").glob("*.py"):
        text = p.read_text(encoding="utf-8")
        for needle in ("logging", ".write_bytes(", ".write_text(", 'open("w', "mkdir("):
            assert needle not in text, f"{p.name} uses {needle}"


# ---------------------------------------------------------------- scoring


def test_stt_normalize_and_error_rates():
    assert score.normalize("  지붕, 질량을!  2킬로그램… ") == "지붕 질량을 2킬로그램"
    assert score.cer("바꿔 줘", "바꿔줘") == 0.0  # spacing does not count in CER
    assert score.wer("바꿔 줘", "바꿔줘") == 1.0  # but it does in WER (the Whisper paper's word protocol)
    assert score.cer("가나다라", "가나다") == pytest.approx(0.25)
    assert score.edit_distance("kitten", "sitting") == 3
    with pytest.raises(ValueError):
        score.cer("", "x")


def test_stt_score_results_micro_averages_per_group():
    data = {
        "cases": [{"id": "a", "group": "g", "reference": "가나다라"}, {"id": "b", "group": "g", "reference": "마바"}],
        "systems": {"s": {"texts": {"a": "가나다", "b": "마바"}}},
    }
    r = score.score_results(data)["s"]["g"]
    assert r["n"] == 2 and r["exact"] == 1 and r["cer"] == pytest.approx(1 / 6)
    assert "16.7%" in score.render(data)


# ---------------------------------------------------------------- DoD: recognition result of a fixed voice fixture


def fixture_cases():
    return json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))


def test_stt_fixture_files_match_their_recorded_hashes():
    import hashlib

    for c in fixture_cases()["cases"]:
        assert hashlib.sha256((FIXTURES / c["file"]).read_bytes()).hexdigest() == c["sha256"]


def real_model_present():
    try:
        transcriber.verify_snapshot(transcriber.find_model())
        return True
    except stt.ModelMissing:
        return False


@pytest.mark.skipif(not real_model_present(), reason="pinned faster-whisper model not in the local cache (run: python -m kinetra_engine.stt fetch, under the resource guard)")
def test_stt_fixture_recognition_with_the_real_model():
    import platform

    import ctranslate2

    t = stt.Transcriber()
    rec = fixture_cases()["recorded_on"]
    here = f"{platform.system()}-{platform.machine()}"
    exact = here == rec["platform"] and ctranslate2.__version__ == rec["ctranslate2"]
    for c in fixture_cases()["cases"]:
        out = t.transcribe(FIXTURES / c["file"])
        assert score.cer(c["reference"], out.text) <= c["max_cer"], (c["file"], out.text)  # every platform
        if exact:  # the recorded text belongs to the reference platform; elsewhere only the bound above is a claim
            assert score.normalize(out.text) == score.normalize(c["recognized"]), (c["file"], out.text)
