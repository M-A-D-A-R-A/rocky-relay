from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter
import shutil
import subprocess
import sys

from rocky_relay.config import Config, load_config
from rocky_relay.logging import append_jsonl
from rocky_relay.pipeline import TurnResult, run_audio_turn
from rocky_relay.playback import PlaybackResult, play_audio_timed


@dataclass
class CaptureResult:
    audio_path: Path
    duration_ms: float
    command: list[str]


def list_avfoundation_devices(ffmpeg_bin: str) -> str:
    _ensure_ffmpeg(ffmpeg_bin)
    result = subprocess.run(
        [
            ffmpeg_bin,
            "-hide_banner",
            "-f",
            "avfoundation",
            "-list_devices",
            "true",
            "-i",
            "",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    # ffmpeg exits non-zero for AVFoundation device listing because the empty
    # input is not a real capture source. Treat the printed device list as the
    # useful result instead of surfacing the trailing "Error opening input".
    lines = [
        line
        for line in output.splitlines()
        if not line.startswith("[in#")
        and not line.startswith("Error opening input file")
        and not line.startswith("Error opening input files")
    ]
    return "\n".join(lines)


def record_mac_audio(
    *,
    ffmpeg_bin: str,
    device: str,
    output_path: Path,
    duration_s: float,
    sample_rate: int,
    channels: int,
) -> CaptureResult:
    _ensure_ffmpeg(ffmpeg_bin)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "avfoundation",
        "-i",
        device,
        "-t",
        _format_float(duration_s),
        "-vn",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "-acodec",
        "pcm_s16le",
        str(output_path),
    ]

    started = perf_counter()
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    duration_ms = round((perf_counter() - started) * 1000, 2)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            "Mac microphone capture failed. If this is the first run, grant microphone "
            f"permission to your terminal/Codex app and retry. ffmpeg said: {detail}"
        )
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"Mac microphone capture produced no audio: {output_path}")
    return CaptureResult(audio_path=output_path, duration_ms=duration_ms, command=command)


def run_recorded_turn(
    config: Config,
    *,
    capture_path: Path | None = None,
    duration_s: float | None = None,
    device: str | None = None,
    sample_rate: int | None = None,
    channels: int | None = None,
    stt_backend: str | None = None,
    llm_backend: str | None = None,
    tts_backend: str | None = None,
    persona: str | None = None,
    play_response: bool = False,
) -> tuple[CaptureResult, TurnResult, PlaybackResult | None]:
    trigger_start = perf_counter()
    capture = record_mac_audio(
        ffmpeg_bin=config.ffmpeg_bin,
        device=device or config.mac_audio_device,
        output_path=capture_path or _default_capture_path(config),
        duration_s=duration_s if duration_s is not None else config.mac_record_duration_s,
        sample_rate=sample_rate or config.mac_record_sample_rate,
        channels=channels or config.mac_record_channels,
    )
    result = run_audio_turn(
        capture.audio_path,
        config,
        stt_backend=stt_backend,
        llm_backend=llm_backend,
        tts_backend=tts_backend,
        persona=persona,
    )
    result.timings_ms["capture_duration_ms"] = capture.duration_ms
    result.timings_ms["trigger_to_audio_ready_with_capture_ms"] = round(
        (perf_counter() - trigger_start) * 1000,
        2,
    )
    playback: PlaybackResult | None = None
    if play_response:
        playback = play_audio_timed(result.audio_path, wait=True)
        result.timings_ms["playback_startup_ms"] = playback.startup_ms
        if playback.return_code is not None:
            result.timings_ms["playback_return_code"] = playback.return_code
        if playback.playback_finished_ms is not None:
            result.timings_ms["playback_finished_ms"] = playback.playback_finished_ms
        if playback.return_code == 0:
            result.timings_ms["trigger_to_first_audible_ms"] = round(
                result.timings_ms["trigger_to_audio_ready_with_capture_ms"] + playback.startup_ms,
                2,
            )
    _log_recorded_turn(config, capture, result, playback)
    return capture, result, playback


def main() -> None:
    parser = argparse.ArgumentParser(description="Record from the Mac mic and run one Rocky Relay turn.")
    parser.add_argument("--config", help="Path to config.json.")
    parser.add_argument("--list-devices", action="store_true", help="List macOS AVFoundation devices.")
    parser.add_argument("--device", help='AVFoundation input device, e.g. ":1" for MacBook Pro Microphone.')
    parser.add_argument("--duration", type=float, help="Recording duration in seconds.")
    parser.add_argument("--sample-rate", type=int, help="Recorded WAV sample rate.")
    parser.add_argument("--channels", type=int, help="Recorded WAV channel count.")
    parser.add_argument("--capture-output", type=Path, help="Where to write the captured mic WAV.")
    parser.add_argument("--record-only", action="store_true", help="Only record the mic WAV; skip STT/LLM/TTS.")
    parser.add_argument("--stt", help="Override STT backend, e.g. smallest_ai or whisper_cpp.")
    parser.add_argument("--llm", help="Override LLM backend, e.g. echo or ollama.")
    parser.add_argument(
        "--tts",
        help=(
            "Override TTS backend, e.g. silent, tone, macos_say, piper, "
            "rocky_xtts, rocky_xtts_cli, rocky_yourtts, or smallest_ai."
        ),
    )
    parser.add_argument(
        "--persona",
        help="Override persona, e.g. none, rocky_basic, rocky_say, or rocky_say_llm.",
    )
    parser.add_argument("--play", action="store_true", help="Play the generated response WAV with afplay.")
    parser.add_argument("--json", action="store_true", help="Print JSON without embedded audio bytes.")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.list_devices:
        try:
            print(list_avfoundation_devices(config.ffmpeg_bin))
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return

    capture_path = args.capture_output or _default_capture_path(config)
    try:
        if args.record_only:
            capture = record_mac_audio(
                ffmpeg_bin=config.ffmpeg_bin,
                device=args.device or config.mac_audio_device,
                output_path=capture_path,
                duration_s=args.duration if args.duration is not None else config.mac_record_duration_s,
                sample_rate=args.sample_rate or config.mac_record_sample_rate,
                channels=args.channels or config.mac_record_channels,
            )
            print(f"Captured: {capture.audio_path}")
            print(f"Capture duration: {capture.duration_ms}ms")
            return

        capture, result, playback = run_recorded_turn(
            config,
            capture_path=capture_path,
            duration_s=args.duration,
            device=args.device,
            sample_rate=args.sample_rate,
            channels=args.channels,
            stt_backend=args.stt,
            llm_backend=args.llm,
            tts_backend=args.tts,
            persona=args.persona,
            play_response=args.play,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if args.json:
        printable = result.as_dict(include_audio=False)
        printable["capture"] = {
            "audio_path": str(capture.audio_path),
            "duration_ms": capture.duration_ms,
        }
        if playback is not None:
            printable["playback"] = {
                "command": playback.command,
                "startup_ms": playback.startup_ms,
                "playback_finished_ms": playback.playback_finished_ms,
                "return_code": playback.return_code,
                "error": playback.error,
            }
        print(json.dumps(printable, indent=2))
        return

    print(f"Captured: {capture.audio_path}")
    print(f"Transcript: {result.input_text}")
    print(f"Reply: {result.reply_text}")
    print(f"Spoken: {result.spoken_text}")
    print(f"Response WAV: {result.audio_path}")
    print(f"Timings: {result.timings_ms}")


def _default_capture_path(config: Config) -> Path:
    capture_dir = config.resolve(config.capture_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return capture_dir / f"mac-mic-{stamp}.wav"


def _log_recorded_turn(
    config: Config,
    capture: CaptureResult,
    result: TurnResult,
    playback: PlaybackResult | None = None,
) -> None:
    record = result.as_dict(include_audio=False)
    record["created_at"] = datetime.now(timezone.utc).isoformat()
    record["capture"] = {
        "audio_path": str(capture.audio_path),
        "duration_ms": capture.duration_ms,
        "command": capture.command,
    }
    if playback is not None:
        record["playback"] = {
            "command": playback.command,
            "startup_ms": playback.startup_ms,
            "playback_finished_ms": playback.playback_finished_ms,
            "return_code": playback.return_code,
            "error": playback.error,
        }
    append_jsonl(config.resolve(config.log_dir) / "recorded_turns.jsonl", record)


def _ensure_ffmpeg(ffmpeg_bin: str) -> None:
    if shutil.which(ffmpeg_bin) is None:
        raise FileNotFoundError(
            f"ffmpeg executable not found: {ffmpeg_bin}. Install ffmpeg or set ffmpeg_bin in config.json."
        )


def _format_float(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


if __name__ == "__main__":
    main()
