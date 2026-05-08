from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
import urllib.error
import urllib.request

from rocky_relay.playback import play_audio


def send_audio_turn(
    audio_path: Path,
    server_url: str,
    *,
    stt_backend: str | None = None,
    llm_backend: str | None = None,
    tts_backend: str | None = None,
    persona: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, object]:
    resolved_audio_path = audio_path.expanduser()
    if not resolved_audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {resolved_audio_path}")
    payload = {
        "audio_wav_base64": base64.b64encode(resolved_audio_path.read_bytes()).decode("ascii"),
        "stt_backend": stt_backend,
        "llm_backend": llm_backend,
        "tts_backend": tts_backend,
        "persona": persona,
        "conversation_id": conversation_id,
    }
    return _post_json(server_url, "/audio", payload)


def write_audio(result: dict[str, object], output: Path) -> None:
    audio = result.get("audio_wav_base64")
    if not isinstance(audio, str) or not audio:
        raise RuntimeError("Server response did not include audio_wav_base64.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(base64.b64decode(audio))


def _post_json(server_url: str, path: str, payload: dict[str, object | None]) -> dict[str, object]:
    body = json.dumps({k: v for k, v in payload.items() if v is not None}).encode("utf-8")
    request = urllib.request.Request(
        f"{server_url.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Server returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach server at {server_url}: {exc}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Send an audio WAV to a Rocky Relay server.")
    parser.add_argument("audio", type=Path, help="WAV file to send.")
    parser.add_argument("--server", default="http://127.0.0.1:8765", help="Server base URL.")
    parser.add_argument("--stt", help="Override STT backend, e.g. smallest_ai or whisper_cpp.")
    parser.add_argument("--llm", help="Override LLM backend, e.g. echo, ollama, or ollama_swiggy.")
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
    parser.add_argument("--conversation-id", help="Optional conversation id to write into server logs.")
    parser.add_argument("--output", type=Path, help="Where to write the returned WAV.")
    parser.add_argument("--play", action="store_true", help="Play the returned WAV.")
    parser.add_argument("--json", action="store_true", help="Print the server JSON without audio.")
    args = parser.parse_args()

    started = perf_counter()
    try:
        result = send_audio_turn(
            args.audio,
            args.server,
            stt_backend=args.stt,
            llm_backend=args.llm,
            tts_backend=args.tts,
            persona=args.persona,
            conversation_id=args.conversation_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    network_roundtrip_ms = round((perf_counter() - started) * 1000, 2)

    output = args.output
    temp_path: Path | None = None
    if output is None and args.play:
        handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        handle.close()
        temp_path = Path(handle.name)
        output = temp_path

    if output is not None:
        write_audio(result, output)

    if args.json:
        printable = {k: v for k, v in result.items() if k != "audio_wav_base64"}
        printable["client_timings_ms"] = {"network_roundtrip_ms": network_roundtrip_ms}
        print(json.dumps(printable, indent=2))
    else:
        print(f"Transcript: {result.get('input_text')}")
        print(f"Reply: {result.get('reply_text')}")
        print(f"Spoken: {result.get('spoken_text')}")
        print(f"Timings: {result.get('timings_ms')}")
        print(f"Network roundtrip: {network_roundtrip_ms}ms")
        if output is not None:
            print(f"WAV: {output}")

    if args.play and output is not None:
        play_audio(output)

    if temp_path is not None:
        temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
