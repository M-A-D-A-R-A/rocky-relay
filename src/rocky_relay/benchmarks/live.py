from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path
import sys

from rocky_relay.benchmarks.doc import append_markdown_table_row
from rocky_relay.config import Config, load_config
from rocky_relay.mac_record import record_mac_audio
from rocky_relay.pipeline import run_audio_turn
from rocky_relay.playback import play_audio_timed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record once from the Mac mic, benchmark multiple STT backends, and append to BENCHMARK.md."
    )
    parser.add_argument("--config", help="Path to config.json.")
    parser.add_argument("--device", help='AVFoundation input device, e.g. ":1" for MacBook Pro Microphone.')
    parser.add_argument("--duration", type=float, help="Recording duration in seconds.")
    parser.add_argument("--sample-rate", type=int, help="Recorded WAV sample rate.")
    parser.add_argument("--channels", type=int, help="Recorded WAV channel count.")
    parser.add_argument("--capture-output", type=Path, help="Where to write the captured mic WAV.")
    parser.add_argument(
        "--stt",
        action="append",
        help="STT backend to benchmark. Repeat this flag. Defaults to smallest_ai and whisper_cpp.",
    )
    parser.add_argument("--llm", default="ollama", help="LLM backend. Use echo to isolate STT.")
    parser.add_argument("--persona", default="rocky_say", help="Persona backend.")
    parser.add_argument("--tts", default="smallest_ai", help="TTS backend. Use silent to isolate STT.")
    parser.add_argument("--play", action="store_true", help="Play each response and measure playback startup.")
    parser.add_argument("--benchmark-file", default="BENCHMARK.md", help="Markdown file to append rows to.")
    args = parser.parse_args()

    config = load_config(args.config)
    stt_backends = args.stt or ["smallest_ai", "whisper_cpp"]
    capture_path = args.capture_output or _default_live_capture_path(config)

    try:
        capture = record_mac_audio(
            ffmpeg_bin=config.ffmpeg_bin,
            device=args.device or config.mac_audio_device,
            output_path=capture_path,
            duration_s=args.duration if args.duration is not None else config.mac_record_duration_s,
            sample_rate=args.sample_rate or config.mac_record_sample_rate,
            channels=args.channels or config.mac_record_channels,
        )
    except Exception as exc:
        print(f"capture: ERROR {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Captured once: {capture.audio_path}")
    print(f"Capture duration: {capture.duration_ms}ms")

    benchmark_path = Path(args.benchmark_file)
    for stt_backend in stt_backends:
        try:
            result = run_audio_turn(
                capture.audio_path,
                config,
                stt_backend=stt_backend,
                llm_backend=args.llm,
                tts_backend=args.tts,
                persona=args.persona,
                log_scope="benchmark",
            )
        except Exception as exc:
            print(f"{stt_backend}: ERROR {exc}", file=sys.stderr)
            continue

        timings = result.timings_ms
        audio_ready_ms = timings.get("trigger_to_audio_ready_ms", timings.get("total_turn_ms", ""))
        with_capture_ms = _with_capture(capture.duration_ms, audio_ready_ms)
        playback_startup_ms: float | str = ""
        first_audible_ms: float | str = ""
        if args.play:
            playback = play_audio_timed(result.audio_path, wait=True)
            playback_startup_ms = playback.startup_ms
            if playback.return_code == 0:
                first_audible_ms = _with_capture(with_capture_ms, playback_startup_ms)
            timings["playback_startup_ms"] = playback.startup_ms
            if playback.return_code is not None:
                timings["playback_return_code"] = playback.return_code
            if playback.playback_finished_ms is not None:
                timings["playback_finished_ms"] = playback.playback_finished_ms
            if first_audible_ms != "":
                timings["trigger_to_first_audible_ms"] = first_audible_ms
        row = (
            f"| {date.today().isoformat()} | `{capture.audio_path}` | `{stt_backend}` | "
            f"{timings.get('stt_transcription_ms', '')} | "
            f"{timings.get('llm_full_response_ms', '')} | "
            f"{timings.get('persona_transform_ms', '')} | "
            f"{timings.get('tts_generation_ms', '')} | "
            f"{audio_ready_ms} | "
            f"{with_capture_ms} | "
            f"{playback_startup_ms} | "
            f"{first_audible_ms} | "
            f"`{result.input_text}` | `{result.audio_path}` | live benchmark command |\n"
        )
        append_markdown_table_row(benchmark_path, "Mac Mic Live Turn:", row)

        print(
            f"{stt_backend}: "
            f"stt={timings.get('stt_transcription_ms')}ms "
            f"llm={timings.get('llm_full_response_ms')}ms "
            f"persona={timings.get('persona_transform_ms')}ms "
            f"tts={timings.get('tts_generation_ms')}ms "
            f"audio_ready={audio_ready_ms}ms "
            f"with_capture={with_capture_ms}ms "
            f"playback_startup={playback_startup_ms}ms "
            f"first_audible={first_audible_ms}ms "
            f"playback_return_code={timings.get('playback_return_code', '')} "
            f"transcript={result.input_text!r} "
            f"wav={result.audio_path}"
        )


def _default_live_capture_path(config: Config) -> Path:
    capture_dir = config.resolve(config.capture_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return capture_dir / f"benchmark-live-{stamp}.wav"


def _with_capture(capture_duration_ms: object, audio_ready_ms: object) -> float | str:
    try:
        return round(float(capture_duration_ms) + float(audio_ready_ms), 2)
    except (TypeError, ValueError):
        return ""


if __name__ == "__main__":
    main()
