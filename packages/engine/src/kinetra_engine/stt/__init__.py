"""Voice dictation (I-01a): local faster-whisper, Korean. See `transcriber.py` and `docs/decisions/stt.md`."""

from .transcriber import (
    MAX_AUDIO_BYTES,
    MAX_AUDIO_SECONDS,
    MODEL_DIR_ENV,
    MODEL_REPO,
    MODEL_REVISION,
    AudioRejected,
    ModelMissing,
    SttError,
    Transcriber,
    Transcript,
    fetch_model,
    find_model,
)

__all__ = [
    "MAX_AUDIO_BYTES", "MAX_AUDIO_SECONDS", "MODEL_DIR_ENV", "MODEL_REPO", "MODEL_REVISION",
    "AudioRejected", "ModelMissing", "SttError", "Transcriber", "Transcript", "fetch_model", "find_model",
]  # fmt: skip
