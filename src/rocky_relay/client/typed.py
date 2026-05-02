from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request


def send_typed_turn(
    text: str,
    server_url: str,
    *,
    llm_backend: str | None = None,
    tts_backend: str | None = None,
    persona: str | None = None,
) -> dict[str, object]:
    payload = {
        "text": text,
        "llm_backend": llm_backend,
        "tts_backend": tts_backend,
        "persona": persona,
    }
    body = json.dumps({k: v for k, v in payload.items() if v is not None}).encode("utf-8")
    request = urllib.request.Request(
        f"{server_url.rstrip('/')}/chat",
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


def write_audio(result: dict[str, object], output: Path) -> None:
    audio = result.get("audio_wav_base64")
    if not isinstance(audio, str) or not audio:
        raise RuntimeError("Server response did not include audio_wav_base64.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(base64.b64decode(audio))


def play_audio(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["afplay", str(path)], check=False)
        return
    if sys.platform.startswith("linux"):
        subprocess.run(["aplay", str(path)], check=False)
        return
    raise RuntimeError(f"Playback is not implemented for platform: {sys.platform}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a typed prompt to a Rocky Relay server.")
    parser.add_argument("text", nargs="?", help="Typed prompt.")
    parser.add_argument("--server", default="http://127.0.0.1:8765", help="Server base URL.")
    parser.add_argument("--llm", help="Override LLM backend, e.g. echo or ollama.")
    parser.add_argument("--tts", help="Override TTS backend, e.g. silent, tone, macos_say, or piper.")
    parser.add_argument("--persona", help="Override persona, e.g. none, rocky_basic, rocky_say.")
    parser.add_argument("--output", type=Path, help="Where to write the returned WAV.")
    parser.add_argument("--play", action="store_true", help="Play the returned WAV.")
    parser.add_argument("--json", action="store_true", help="Print the server JSON without audio.")
    args = parser.parse_args()

    text = args.text or input("Prompt: ").strip()
    result = send_typed_turn(
        text,
        args.server,
        llm_backend=args.llm,
        tts_backend=args.tts,
        persona=args.persona,
    )

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
        print(json.dumps(printable, indent=2))
    else:
        print(f"Reply: {result.get('reply_text')}")
        print(f"Spoken: {result.get('spoken_text')}")
        print(f"Timings: {result.get('timings_ms')}")
        if output is not None:
            print(f"WAV: {output}")

    if args.play and output is not None:
        play_audio(output)

    if temp_path is not None:
        temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
