from __future__ import annotations

import argparse
import json
from time import perf_counter
import sys
import uuid

from rocky_relay.config import load_config
from rocky_relay.mac_record import (
    CaptureResult,
    default_capture_path,
    log_recorded_turn,
    start_mac_audio_capture,
    stop_mac_audio_capture,
)
from rocky_relay.pipeline import TurnResult, run_audio_turn
from rocky_relay.playback import PlaybackResult, play_audio_timed


def run_interaction_turn(
    *,
    config_path: str | None = None,
    device: str | None = None,
    sample_rate: int | None = None,
    channels: int | None = None,
    stt_backend: str | None = None,
    llm_backend: str | None = None,
    tts_backend: str | None = None,
    persona: str | None = None,
    conversation_id: str | None = None,
    play_response: bool = True,
) -> tuple[CaptureResult, TurnResult, PlaybackResult | None]:
    config = load_config(config_path)
    input("Press Enter to start recording...")
    trigger_start = perf_counter()
    active = start_mac_audio_capture(
        ffmpeg_bin=config.ffmpeg_bin,
        device=device or config.mac_audio_device,
        output_path=default_capture_path(config, prefix="interaction"),
        sample_rate=sample_rate or config.mac_record_sample_rate,
        channels=channels or config.mac_record_channels,
    )
    input("Recording. Press Enter to stop and send...")
    capture = stop_mac_audio_capture(active)
    result = run_audio_turn(
        capture.audio_path,
        config,
        stt_backend=stt_backend,
        llm_backend=llm_backend,
        tts_backend=tts_backend,
        persona=persona,
        conversation_id=conversation_id,
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

    log_recorded_turn(config, capture, result, playback)
    return capture, result, playback


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an Enter-to-talk Rocky Relay interaction loop.")
    parser.add_argument("--config", help="Path to config.json.")
    parser.add_argument("--device", help='AVFoundation input device, e.g. ":1" for MacBook Pro Microphone.')
    parser.add_argument("--sample-rate", type=int, help="Recorded WAV sample rate.")
    parser.add_argument("--channels", type=int, help="Recorded WAV channel count.")
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
    parser.add_argument("--conversation-id", help="Optional conversation id. Defaults to one id per session.")
    parser.add_argument("--no-play", action="store_true", help="Do not play the generated response.")
    parser.add_argument("--once", action="store_true", help="Run one interaction turn and exit.")
    parser.add_argument("--json", action="store_true", help="Print JSON without embedded audio bytes.")
    args = parser.parse_args()
    conversation_id = args.conversation_id or f"conv_{uuid.uuid4().hex[:12]}"
    print(f"Conversation id: {conversation_id}")

    while True:
        try:
            capture, result, playback = run_interaction_turn(
                config_path=args.config,
                device=args.device,
                sample_rate=args.sample_rate,
                channels=args.channels,
                stt_backend=args.stt,
                llm_backend=args.llm,
                tts_backend=args.tts,
                persona=args.persona,
                conversation_id=conversation_id,
                play_response=not args.no_play,
            )
        except KeyboardInterrupt:
            print("\nStopped.")
            return
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            if args.once:
                raise SystemExit(1) from exc
            continue

        _print_result(capture, result, playback, as_json=args.json)
        if args.once:
            return

        again = input("Press Enter for another turn, or type q then Enter to quit: ").strip().lower()
        if again in {"q", "quit", "exit"}:
            return


def _print_result(
    capture: CaptureResult,
    result: TurnResult,
    playback: PlaybackResult | None,
    *,
    as_json: bool,
) -> None:
    if as_json:
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


if __name__ == "__main__":
    main()
