from __future__ import annotations

import argparse
import json
import mimetypes
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
import uuid


DEFAULT_URL = "https://api.smallest.ai/waves/v1/voice-cloning"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Smallest AI instant voice clone.")
    parser.add_argument("--file", required=True, type=Path, help="5-15s clean audio sample, under 5 MB.")
    parser.add_argument("--display-name", required=True, help="Display name for the voice clone.")
    parser.add_argument("--language", default="en", help="Target language code.")
    parser.add_argument("--accent", default="general", help="Accent label.")
    parser.add_argument("--tags", default="rocky-relay,benchmark", help="Comma-separated tags.")
    parser.add_argument("--description", default="", help="Optional clone description.")
    parser.add_argument("--api-key-env", default="SMALLEST_API_KEY", help="Environment variable with API key.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Smallest AI voice-cloning endpoint.")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        print(f"Error: missing API key. Set it with: export {args.api_key_env}=...", file=sys.stderr)
        raise SystemExit(1)

    audio_path = args.file.expanduser()
    if not audio_path.exists():
        print(f"Error: audio file not found: {audio_path}", file=sys.stderr)
        raise SystemExit(1)
    if audio_path.stat().st_size > 5 * 1024 * 1024:
        print("Error: Smallest instant clone expects an audio sample under 5 MB.", file=sys.stderr)
        raise SystemExit(1)

    fields = {
        "displayName": args.display_name,
        "language": args.language,
        "accent": args.accent,
        "tags": args.tags,
    }
    if args.description:
        fields["description"] = args.description

    body, content_type = _build_multipart(fields, "file", audio_path)
    request = urllib.request.Request(
        args.url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": content_type,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"Error: Smallest clone failed with HTTP {exc.code}: {detail}", file=sys.stderr)
        raise SystemExit(1) from exc
    except urllib.error.URLError as exc:
        print(f"Error: Smallest clone request failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(json.dumps(payload, indent=2))
    voice_id = payload.get("data", {}).get("voiceId") if isinstance(payload.get("data"), dict) else None
    if voice_id:
        print(f"\nUse in config.json: \"smallest_voice_id\": \"{voice_id}\"")


def _build_multipart(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = f"----rocky-relay-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_path.name}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


if __name__ == "__main__":
    main()
