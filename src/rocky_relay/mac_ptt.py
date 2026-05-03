from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import perf_counter
import uuid

from rocky_relay.client.audio import send_audio_turn, write_audio
from rocky_relay.config import Config, load_config
from rocky_relay.logging import append_jsonl
from rocky_relay.mac_record import (
    ActiveCapture,
    CaptureResult,
    default_capture_path,
    start_mac_audio_capture,
    stop_mac_audio_capture,
)
from rocky_relay.playback import PlaybackResult, play_audio_timed


ACCESSIBILITY_HINT = (
    "macOS may require Accessibility permission for global push-to-talk. "
    "Grant it to your terminal app in System Settings -> Privacy & Security -> Accessibility."
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a macOS global hold-to-talk Rocky Relay client.")
    parser.add_argument("--config", help="Path to config.json.")
    parser.add_argument("--server", default="http://127.0.0.1:8765", help="Server base URL.")
    parser.add_argument("--device", help='AVFoundation input device, e.g. ":1" for MacBook Pro Microphone.')
    parser.add_argument("--sample-rate", type=int, help="Recorded WAV sample rate.")
    parser.add_argument("--channels", type=int, help="Recorded WAV channel count.")
    parser.add_argument(
        "--hotkey",
        default="option",
        help="Hold key: option, left_option, right_option, space, f1-f20, or a single character.",
    )
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
    parser.add_argument(
        "--conversation-only",
        action="store_true",
        help="Print only You/Rocky conversation lines; still writes full JSONL logs.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON without embedded audio bytes.")
    args = parser.parse_args()

    config = load_config(args.config)
    conversation_id = args.conversation_id or f"conv_{uuid.uuid4().hex[:12]}"
    run_mac_ptt(
        config=config,
        server_url=args.server,
        device=args.device,
        sample_rate=args.sample_rate,
        channels=args.channels,
        hotkey=args.hotkey,
        stt_backend=args.stt,
        llm_backend=args.llm,
        tts_backend=args.tts,
        persona=args.persona,
        conversation_id=conversation_id,
        play_response=not args.no_play,
        print_json=args.json,
        conversation_only=args.conversation_only,
    )


def run_mac_ptt(
    *,
    config: Config,
    server_url: str,
    device: str | None,
    sample_rate: int | None,
    channels: int | None,
    hotkey: str,
    stt_backend: str | None,
    llm_backend: str | None,
    tts_backend: str | None,
    persona: str | None,
    conversation_id: str,
    play_response: bool,
    print_json: bool,
    conversation_only: bool,
) -> None:
    keyboard = _load_keyboard()
    hotkey_keys = _resolve_hotkey(keyboard, hotkey)
    active_capture: ActiveCapture | None = None
    trigger_start: float | None = None

    print(f"Conversation id: {conversation_id}")
    print(f"Hold {hotkey} to talk. Release to send. Press Ctrl-C to quit.")

    def on_press(key: object) -> None:
        nonlocal active_capture, trigger_start
        if key not in hotkey_keys or active_capture is not None:
            return
        try:
            trigger_start = perf_counter()
            active_capture = start_mac_audio_capture(
                ffmpeg_bin=config.ffmpeg_bin,
                device=device or config.mac_audio_device,
                output_path=default_capture_path(config, prefix="mac-ptt"),
                sample_rate=sample_rate or config.mac_record_sample_rate,
                channels=channels or config.mac_record_channels,
            )
            print("Recording...")
        except Exception as exc:
            trigger_start = None
            active_capture = None
            print(f"Error starting capture: {exc}", file=sys.stderr)

    def on_release(key: object) -> None:
        nonlocal active_capture, trigger_start
        if key not in hotkey_keys or active_capture is None:
            return
        capture_start = trigger_start or perf_counter()
        active = active_capture
        active_capture = None
        trigger_start = None
        try:
            capture = stop_mac_audio_capture(active)
            _send_and_play_turn(
                config=config,
                server_url=server_url,
                capture=capture,
                trigger_start=capture_start,
                stt_backend=stt_backend,
                llm_backend=llm_backend,
                tts_backend=tts_backend,
                persona=persona,
                conversation_id=conversation_id,
                play_response=play_response,
                print_json=print_json,
                conversation_only=conversation_only,
            )
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)

    try:
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()
    except KeyboardInterrupt:
        if active_capture is not None:
            try:
                stop_mac_audio_capture(active_capture)
            except Exception:
                pass
        print("\nStopped.")
    except Exception as exc:
        print(f"Error starting global hotkey listener: {exc}", file=sys.stderr)
        print(ACCESSIBILITY_HINT, file=sys.stderr)
        raise SystemExit(1) from exc


def _send_and_play_turn(
    *,
    config: Config,
    server_url: str,
    capture: CaptureResult,
    trigger_start: float,
    stt_backend: str | None,
    llm_backend: str | None,
    tts_backend: str | None,
    persona: str | None,
    conversation_id: str,
    play_response: bool,
    print_json: bool,
    conversation_only: bool,
) -> None:
    network_start = perf_counter()
    result = send_audio_turn(
        capture.audio_path,
        server_url,
        stt_backend=stt_backend,
        llm_backend=llm_backend,
        tts_backend=tts_backend,
        persona=persona,
        conversation_id=conversation_id,
    )
    network_roundtrip_ms = round((perf_counter() - network_start) * 1000, 2)
    response_path = _response_path(config, result)
    write_audio(result, response_path)

    timings = _result_timings(result)
    timings["capture_duration_ms"] = capture.duration_ms
    timings["network_roundtrip_ms"] = network_roundtrip_ms
    timings["trigger_to_audio_ready_with_capture_ms"] = round((perf_counter() - trigger_start) * 1000, 2)

    playback: PlaybackResult | None = None
    if play_response:
        playback = play_audio_timed(response_path, wait=True)
        timings["playback_startup_ms"] = playback.startup_ms
        if playback.return_code is not None:
            timings["playback_return_code"] = playback.return_code
        if playback.playback_finished_ms is not None:
            timings["playback_finished_ms"] = playback.playback_finished_ms
        if playback.return_code == 0:
            timings["trigger_to_first_audible_ms"] = round(
                timings["trigger_to_audio_ready_with_capture_ms"] + playback.startup_ms,
                2,
            )

    result["timings_ms"] = timings
    result["client_audio_path"] = str(response_path)
    _log_recorded_server_turn(config, capture, result, playback)
    _print_result(
        capture,
        result,
        response_path,
        playback,
        as_json=print_json,
        conversation_only=conversation_only,
    )


def _load_keyboard() -> object:
    try:
        from pynput import keyboard
    except ImportError as exc:
        print("Missing optional dependency: pynput.", file=sys.stderr)
        print('Install it with: pip install -e ".[mac]"', file=sys.stderr)
        raise SystemExit(1) from exc
    return keyboard


def _resolve_hotkey(keyboard: object, value: str) -> set[object]:
    normalized = value.strip().lower().replace("-", "_")
    key_enum = keyboard.Key
    key_code = keyboard.KeyCode
    option_keys = _available_keys(key_enum, "alt", "alt_l", "alt_r")
    aliases: dict[str, set[object]] = {
        "option": option_keys,
        "alt": option_keys,
        "left_option": _available_keys(key_enum, "alt_l"),
        "left_alt": _available_keys(key_enum, "alt_l"),
        "right_option": _available_keys(key_enum, "alt_r"),
        "right_alt": _available_keys(key_enum, "alt_r"),
        "space": _available_keys(key_enum, "space"),
    }
    if normalized in aliases and aliases[normalized]:
        return aliases[normalized]
    if normalized.startswith("f") and normalized[1:].isdigit():
        key = getattr(key_enum, normalized, None)
        if key is not None:
            return {key}
    if len(normalized) == 1:
        return {key_code.from_char(normalized)}
    raise ValueError(f"Unsupported hotkey: {value}")


def _available_keys(key_enum: object, *names: str) -> set[object]:
    return {key for name in names if (key := getattr(key_enum, name, None)) is not None}


def _result_timings(result: dict[str, object]) -> dict[str, float]:
    timings = result.get("timings_ms")
    if not isinstance(timings, dict):
        return {}
    return {str(key): value for key, value in timings.items() if isinstance(value, int | float)}


def _response_path(config: Config, result: dict[str, object]) -> Path:
    request_id = str(result.get("request_id") or uuid.uuid4().hex[:12])
    return config.resolve(config.output_dir) / f"client-{request_id}.wav"


def _log_recorded_server_turn(
    config: Config,
    capture: CaptureResult,
    result: dict[str, object],
    playback: PlaybackResult | None,
) -> None:
    record = {k: v for k, v in result.items() if k != "audio_wav_base64"}
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
    append_jsonl(config.resolve(config.conversation_log_dir) / "recorded_turns.jsonl", record)


def _print_result(
    capture: CaptureResult,
    result: dict[str, object],
    response_path: Path,
    playback: PlaybackResult | None,
    *,
    as_json: bool,
    conversation_only: bool,
) -> None:
    if as_json:
        printable = {k: v for k, v in result.items() if k != "audio_wav_base64"}
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

    if conversation_only:
        print(f"You: {result.get('input_text')}")
        print(f"Rocky: {result.get('spoken_text')}")
        return

    print(f"Captured: {capture.audio_path}")
    print(f"Transcript: {result.get('input_text')}")
    print(f"Reply: {result.get('reply_text')}")
    print(f"Spoken: {result.get('spoken_text')}")
    print(f"Response WAV: {response_path}")
    print(f"Timings: {result.get('timings_ms')}")


if __name__ == "__main__":
    main()
