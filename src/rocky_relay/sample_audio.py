from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import wave


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate repeatable WAV prompts with macOS say.")
    parser.add_argument("text", help="Text to synthesize into a test audio prompt.")
    parser.add_argument("--output", required=True, type=Path, help="Output WAV path.")
    parser.add_argument("--voice", help="Optional macOS voice name.")
    parser.add_argument("--sample-rate", type=int, default=16000, help="Output sample rate.")
    args = parser.parse_args()

    if sys.platform != "darwin":
        print("Error: rocky-relay-make-sample-audio currently uses macOS say/afconvert.", file=sys.stderr)
        raise SystemExit(1)

    with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as handle:
        aiff_path = Path(handle.name)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        say_cmd = ["say", "-o", str(aiff_path)]
        if args.voice:
            say_cmd.extend(["-v", args.voice])
        say_cmd.append(args.text)
        subprocess.run(say_cmd, check=True)
        subprocess.run(
            [
                "afconvert",
                "-f",
                "WAVE",
                "-d",
                f"LEI16@{args.sample_rate}",
                str(aiff_path),
                str(args.output),
            ],
            check=True,
        )
        if _wav_frame_count(args.output) <= 0:
            raise RuntimeError(
                "Generated WAV contains no audio frames. In this shell, macOS say may not "
                "be producing offline audio; use a recorded WAV or an existing TTS output instead."
            )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        aiff_path.unlink(missing_ok=True)

    print(args.output)


def _wav_frame_count(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as wav:
            return wav.getnframes()
    except wave.Error:
        return 0


if __name__ == "__main__":
    main()
