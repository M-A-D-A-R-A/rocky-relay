from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

from rocky_relay.config import load_config
from rocky_relay.pipeline import run_audio_turn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run STT/audio-turn benchmarks and append to BENCHMARK.md.")
    parser.add_argument("--audio", required=True, type=Path, help="Audio file to transcribe.")
    parser.add_argument(
        "--stt",
        action="append",
        required=True,
        help="STT backend to benchmark. Repeat this flag for multiple backends.",
    )
    parser.add_argument("--llm", default="echo", help="LLM backend. Use echo to isolate STT.")
    parser.add_argument("--persona", default="none", help="Persona backend.")
    parser.add_argument("--tts", default="silent", help="TTS backend. Use silent to isolate STT.")
    parser.add_argument("--config", help="Path to config.json.")
    parser.add_argument("--benchmark-file", default="BENCHMARK.md", help="Markdown file to append rows to.")
    args = parser.parse_args()

    config = load_config(args.config)
    benchmark_path = Path(args.benchmark_file)

    for stt_backend in args.stt:
        try:
            result = run_audio_turn(
                args.audio,
                config,
                stt_backend=stt_backend,
                llm_backend=args.llm,
                tts_backend=args.tts,
                persona=args.persona,
            )
        except Exception as exc:
            print(f"{stt_backend}: ERROR {exc}", file=sys.stderr)
            continue

        timings = result.timings_ms
        row = (
            f"| {date.today().isoformat()} | `{args.audio}` | `{stt_backend}` | "
            f"{timings.get('stt_transcription_ms', '')} | "
            f"{timings.get('llm_full_response_ms', '')} | "
            f"{timings.get('persona_transform_ms', '')} | "
            f"{timings.get('tts_generation_ms', '')} | "
            f"{timings.get('total_turn_ms', '')} | "
            f"`{result.input_text}` | `{result.audio_path}` | benchmark command |\n"
        )
        with benchmark_path.open("a", encoding="utf-8") as handle:
            handle.write(row)

        print(
            f"{stt_backend}: "
            f"stt={timings.get('stt_transcription_ms')}ms "
            f"llm={timings.get('llm_full_response_ms')}ms "
            f"persona={timings.get('persona_transform_ms')}ms "
            f"tts={timings.get('tts_generation_ms')}ms "
            f"total={timings.get('total_turn_ms')}ms "
            f"transcript={result.input_text!r} "
            f"wav={result.audio_path}"
        )


if __name__ == "__main__":
    main()
