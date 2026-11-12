"""Compile and run (X-02a): a project to an engine model, stepped into the run stream of `client-adapter.md` 3.3."""

from .platform_tag import PlatformUnknown, compute_settings, platform_tag
from .preview import (
    FRAME_RATE_CEILING_HZ,
    CompiledModel,
    PreviewRun,
    commands_at,
    compile_project,
    default_frame_every_ticks,
    end_tick,
    environment_labels,
)

__all__ = [
    "FRAME_RATE_CEILING_HZ",
    "CompiledModel",
    "PlatformUnknown",
    "PreviewRun",
    "commands_at",
    "compile_project",
    "compute_settings",
    "default_frame_every_ticks",
    "end_tick",
    "environment_labels",
    "platform_tag",
]
