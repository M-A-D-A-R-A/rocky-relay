from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
import subprocess
import sys


@dataclass
class PlaybackResult:
    command: list[str]
    startup_ms: float
    playback_finished_ms: float | None
    return_code: int | None
    error: str | None = None


def play_audio(path: Path) -> None:
    play_audio_timed(path, wait=True)


def play_audio_timed(path: Path, *, wait: bool = True) -> PlaybackResult:
    command = _playback_command(path)
    started = perf_counter()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    startup_ms = round((perf_counter() - started) * 1000, 2)

    finished_ms: float | None = None
    return_code: int | None = None
    error: str | None = None
    if wait:
        _stdout, stderr = process.communicate()
        return_code = process.returncode
        error = stderr.strip() or None
        finished_ms = round((perf_counter() - started) * 1000, 2)
    return PlaybackResult(
        command=command,
        startup_ms=startup_ms,
        playback_finished_ms=finished_ms,
        return_code=return_code,
        error=error,
    )


def _playback_command(path: Path) -> list[str]:
    if sys.platform == "darwin":
        return ["afplay", str(path)]
    if sys.platform.startswith("linux"):
        return ["aplay", str(path)]
    raise RuntimeError(f"Playback is not implemented for platform: {sys.platform}")
