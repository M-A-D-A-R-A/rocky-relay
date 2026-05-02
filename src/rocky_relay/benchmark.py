from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

from rocky_relay.config import load_config
from rocky_relay.pipeline import run_typed_turn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TTS benchmark turns and append to BENCHMARK.md.")
    parser.add_argument(
        "--text",
        default="hello",
        help="Prompt text to benchmark. Defaults to a tiny prompt for TTS isolation.",
    )
    parser.add_argument("--llm", default="echo", help="LLM backend. Use echo to isolate TTS.")
    parser.add_argument("--persona", default="rocky_basic", help="Persona backend.")
    parser.add_argument(
        "--tts",
        action="append",
        required=True,
        help="TTS backend to benchmark. Repeat this flag for multiple backends.",
    )
    parser.add_argument("--config", help="Path to config.json.")
    parser.add_argument("--benchmark-file", default="BENCHMARK.md", help="Markdown file to append rows to.")
    args = parser.parse_args()

    config = load_config(args.config)
    benchmark_path = Path(args.benchmark_file)

    for tts_backend in args.tts:
        try:
            result = run_typed_turn(
                args.text,
                config,
                llm_backend=args.llm,
                tts_backend=tts_backend,
                persona=args.persona,
            )
        except Exception as exc:
            print(f"{tts_backend}: ERROR {exc}", file=sys.stderr)
            continue

        timings = result.timings_ms
        row = (
            f"| {date.today().isoformat()} | `{args.text}` | `{tts_backend}` | "
            f"{timings.get('llm_full_response_ms', '')} | "
            f"{timings.get('persona_transform_ms', '')} | "
            f"{timings.get('tts_generation_ms', '')} | "
            f"{timings.get('total_turn_ms', '')} | "
            f"`{result.audio_path}` | benchmark command |\n"
        )
        with benchmark_path.open("a", encoding="utf-8") as handle:
            handle.write(row)

        print(
            f"{tts_backend}: "
            f"llm={timings.get('llm_full_response_ms')}ms "
            f"persona={timings.get('persona_transform_ms')}ms "
            f"tts={timings.get('tts_generation_ms')}ms "
            f"total={timings.get('total_turn_ms')}ms "
            f"wav={result.audio_path}"
        )


if __name__ == "__main__":
    main()
