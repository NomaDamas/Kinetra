"""Local Korean dictation: audio bytes or a file in, text out (I-01a).

    t = Transcriber()                       # loads the pinned model from the local cache, never downloads
    out = t.transcribe(webm_bytes)          # Transcript(text=..., language="ko", duration_s=..., model=...)

Why local: the decision and its evidence are in `docs/decisions/stt.md`. The recording never leaves the machine, there is no
key and no per-minute cost, and it works offline.

Rules:
    - The model is fetched only by `fetch_model()` (`python -m kinetra_engine.stt fetch`, under the resource guard). A
      `Transcriber` loads with `local_files_only=True`, so a missing model is an error (`ModelMissing`), never a silent download.
    - The model is pinned to a Hugging Face revision. All four files (`MODEL_HASHES`) are checked against a sha256 after the
      download and again on every `Transcriber` load (about a second for 462 MiB). A missing, edited or truncated file is
      `ModelMissing`; a file that passes the hash but still cannot be loaded is also `ModelMissing`, never a bare library error.
    - The decoder opens only local audio containers. PyAV hands the bytes to FFmpeg, which picks the format from the content, so a
      body that looks like an SDP file or an `ffconcat` list would otherwise open network sockets or read other files. `av.open` is
      therefore given `format_whitelist` (`AUDIO_FORMATS`) and `protocol_whitelist=file`; anything else is `AudioRejected`.
    - Nothing is written: the audio is decoded in memory and not stored; the transcript is returned, not logged.
    - The transcript is untrusted text, the same as typed text. It must go through the confirmation step and the Command
      validator (I-01b); this module neither interprets nor acts on it.
    - Input limits (`MAX_AUDIO_BYTES`, `MAX_AUDIO_SECONDS`) are checked before the model runs; the length limit stops the decode itself.
"""

from __future__ import annotations

import hashlib
import io
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Callable

SAMPLE_RATE = 16000  # Whisper's input rate; _decode resamples to it
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # same cap OpenRouter puts on a multipart upload; a push-to-talk command is a few hundred kB
MAX_AUDIO_SECONDS = 60.0  # `기본값`: a spoken command is seconds long; longer input is refused instead of occupying the model
MODEL_DIR_ENV = "KINETRA_STT_MODEL_DIR"  # optional Hugging Face cache root; unset = the Hugging Face default (~/.cache/huggingface)

# FFmpeg demuxer names that a browser recording or an uploaded voice note can be: wav, flac, mp3, ogg (opus/vorbis), webm (matroska),
# mp4/m4a (the mov family), raw AAC. Nothing else is opened: no SDP, no ffconcat, no image or playlist formats.
AUDIO_FORMATS = "wav,flac,mp3,ogg,matroska,webm,mov,mp4,m4a,3gp,3g2,mj2,aac"
OPEN_OPTIONS = {"format_whitelist": AUDIO_FORMATS, "protocol_whitelist": "file"}

# One pinned model: the repo and revision the files are downloaded from, and the sha256 of every file.
MODEL_REPO = "Systran/faster-whisper-small"  # MIT (model card), CTranslate2 conversion of openai/whisper-small
MODEL_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
MODEL_HASHES = {
    "config.json": "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828",  # 2,370 bytes
    "model.bin": "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",  # 483,546,902 bytes; equals the Hugging Face LFS oid
    "tokenizer.json": "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",  # 2,203,239 bytes
    "vocabulary.txt": "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",  # 459,861 bytes
}
MODEL_FILES = tuple(MODEL_HASHES)


class SttError(Exception):
    """Base class. Messages never contain audio or transcript text."""


class ModelMissing(SttError):
    """The pinned model is not in the local cache. Run `python -m kinetra_engine.stt fetch` (it needs the network once)."""


class AudioRejected(SttError):
    """The input is empty, too large, too long, not an allowed audio container, or cannot be decoded as audio."""


class UnsupportedLanguage(SttError):
    """`language` is not one of the codes the model knows."""


@dataclass(frozen=True)
class Transcript:
    text: str  # "" when no speech was found
    language: str
    duration_s: float  # length of the decoded audio
    model: str  # "<repo>@<revision>"


def model_root(model_dir: Path | str | None = None) -> Path | None:
    """The cache root for the model: the argument, else `KINETRA_STT_MODEL_DIR`, else None (the Hugging Face default)."""
    chosen = model_dir if model_dir is not None else os.environ.get(MODEL_DIR_ENV)
    return Path(chosen) if chosen else None


def _snapshot(local_files_only: bool, model_dir: Path | str | None) -> str:
    from faster_whisper.utils import download_model

    root = model_root(model_dir)
    return download_model(
        MODEL_REPO,
        local_files_only=local_files_only,
        cache_dir=None if root is None else str(root),
        revision=MODEL_REVISION,
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_snapshot(path: Path | str) -> None:
    """Every expected file exists and has its pinned sha256. Raises ModelMissing otherwise."""
    p = Path(path)
    missing = [n for n in MODEL_FILES if not (p / n).is_file()]
    if missing:
        raise ModelMissing(f"model files missing in {p}: {', '.join(missing)}")
    for name, pinned in MODEL_HASHES.items():
        try:
            actual = _sha256(p / name)
        except OSError as e:
            raise ModelMissing(f"cannot read {name} ({type(e).__name__})") from None
        if actual != pinned:
            raise ModelMissing(f"{name} sha256 {actual} is not the pinned {pinned}; delete {p} and fetch again")


def fetch_model(model_dir: Path | str | None = None) -> Path:
    """Download the pinned model (about 462 MiB) into the cache and verify it. This is the only function that uses the network."""
    path = Path(_snapshot(False, model_dir))
    verify_snapshot(path)
    return path


def find_model(model_dir: Path | str | None = None) -> Path:
    """The local snapshot of the pinned model, or ModelMissing. Never touches the network."""
    try:
        return Path(_snapshot(True, model_dir))
    except Exception as e:  # huggingface_hub raises its own LocalEntryNotFoundError subclass of OSError
        raise ModelMissing(f"the pinned model {MODEL_REPO}@{MODEL_REVISION[:8]} is not in the local cache ({type(e).__name__}); run `python -m kinetra_engine.stt fetch`") from None


def _decode(audio: bytes | bytearray | memoryview | str | os.PathLike) -> Any:
    """Audio -> float32 mono 16 kHz array. Decodes with PyAV (bundled FFmpeg): wav, flac, mp3, ogg, webm/opus, m4a.

    The size limit is checked before anything is opened. The length limit is enforced twice: a container that declares a duration
    over the limit is refused before a frame is decoded, and the decode itself stops as soon as it has produced more than the
    limit, so a file that under-declares (or declares nothing, as live webm does) cannot make us decode its whole length.
    """
    import av
    import numpy as np

    src: str | BinaryIO
    if isinstance(audio, (bytes, bytearray, memoryview)):
        size = memoryview(audio).nbytes  # not len(): a memoryview of 4-byte items has len() == nbytes / 4
        if size == 0:
            raise AudioRejected("audio is empty")
        if size > MAX_AUDIO_BYTES:
            raise AudioRejected(f"audio is {size} bytes, over the {MAX_AUDIO_BYTES} byte limit")
        src = io.BytesIO(memoryview(audio).tobytes())
    else:
        path = Path(audio)
        try:
            size = path.stat().st_size
        except OSError as e:
            raise AudioRejected(f"cannot read audio file ({type(e).__name__})") from None
        if size == 0:
            raise AudioRejected("audio is empty")
        if size > MAX_AUDIO_BYTES:
            raise AudioRejected(f"audio is {size} bytes, over the {MAX_AUDIO_BYTES} byte limit")
        src = str(path)
    limit = int(MAX_AUDIO_SECONDS * SAMPLE_RATE)
    too_long = AudioRejected(f"audio is longer than the {MAX_AUDIO_SECONDS:.0f} s limit")
    chunks: list[Any] = []
    total = 0
    try:
        with av.open(src, mode="r", metadata_errors="ignore", options=OPEN_OPTIONS) as container:
            declared = container.duration  # microseconds (av.time_base), None when the container does not say
            if declared is not None and declared > MAX_AUDIO_SECONDS * 1_000_000:
                raise too_long
            resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(audio=0):
                for out in resampler.resample(frame):
                    pcm = out.to_ndarray().reshape(-1)
                    total += len(pcm)
                    if total > limit:
                        raise too_long
                    chunks.append(pcm)
            for out in resampler.resample(None):  # flush
                pcm = out.to_ndarray().reshape(-1)
                total += len(pcm)
                if total > limit:
                    raise too_long
                chunks.append(pcm)
    except AudioRejected:
        raise
    except Exception as e:  # PyAV raises av.error.* subclasses (InvalidDataError, ...) for anything that is not audio
        raise AudioRejected(f"cannot decode audio ({type(e).__name__})") from None
    if total == 0:
        raise AudioRejected("audio has no samples")
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def _languages() -> frozenset[str]:
    from faster_whisper.tokenizer import _LANGUAGE_CODES

    return frozenset(_LANGUAGE_CODES)


class Transcriber:
    """Loads the pinned model once and transcribes one recording at a time (calls are serialised: one model, one CPU job).

    `transcribe` is blocking and has no progress or cancel: a few seconds for a spoken command (docs/decisions/stt.md 4.3), and the
    caller (I-01b) must run it off the request path and show its own progress and cancel.
    """

    def __init__(
        self,
        *,
        model_dir: Path | str | None = None,
        cpu_threads: int = 0,
        loader: Callable[..., Any] | None = None,
    ):
        """`loader` replaces `faster_whisper.WhisperModel` (tests inject a recorder); it is called as `loader(snapshot_path, ...)`."""
        snapshot = find_model(model_dir)
        verify_snapshot(snapshot)  # every load, not only after a fetch: a cached file that was edited or truncated is refused
        if loader is None:
            from faster_whisper import WhisperModel

            loader = WhisperModel
        # cpu + int8: the measured configuration (docs/decisions/stt.md). `auto` would pick the same on this machine but not on a CUDA one.
        try:
            self._model = loader(str(snapshot), device="cpu", compute_type="int8", cpu_threads=cpu_threads, local_files_only=True)
        except Exception as e:  # CTranslate2 raises RuntimeError and friends for a model it cannot read
            raise ModelMissing(f"the model could not be loaded ({type(e).__name__}); delete the cache and run `python -m kinetra_engine.stt fetch`") from None
        self._lock = threading.Lock()
        self.model_id = f"{MODEL_REPO}@{MODEL_REVISION}"

    def transcribe(self, audio: bytes | bytearray | memoryview | str | os.PathLike, *, language: str = "ko") -> Transcript:
        """Recognise one recording. Greedy-ish decoding (beam 5, the library default), voice-activity filter on, no previous-text conditioning."""
        if not isinstance(language, str) or language not in _languages():
            raise UnsupportedLanguage(f"unsupported language code {language[:12]!r}" if isinstance(language, str) else "language must be a string")
        samples = _decode(audio)
        with self._lock:
            segments, info = self._model.transcribe(
                samples,
                language=language,
                task="transcribe",
                beam_size=5,
                temperature=0.0,  # deterministic: no sampling fallback, so the same audio gives the same text on the same build
                vad_filter=True,
                condition_on_previous_text=False,
            )
            text = " ".join(s.text.strip() for s in segments if s.text.strip())  # segments is a generator: the model runs here
        return Transcript(text=text, language=language, duration_s=len(samples) / SAMPLE_RATE, model=self.model_id)
