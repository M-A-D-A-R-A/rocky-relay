from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter
import sys
import uuid

from rocky_relay.backends.llm import build_llm
from rocky_relay.backends.tts import build_tts
from rocky_relay.config import Config, load_config
from rocky_relay.logging import append_jsonl
from rocky_relay.persona import apply_persona
from rocky_relay.timing import TurnTimer


@dataclass
class TurnResult:
    request_id: str
    input_text: str
    reply_text: str
    spoken_text: str
    audio_path: Path
    audio_wav_base64: str
    timings_ms: dict[str, float]
    tts_backend: str
    llm_backend: str
    persona: str

    def as_dict(self, include_audio: bool = True) -> dict[str, object]:
        data: dict[str, object] = {
            "request_id": self.request_id,
            "input_text": self.input_text,
            "reply_text": self.reply_text,
            "spoken_text": self.spoken_text,
            "audio_path": str(self.audio_path),
            "timings_ms": self.timings_ms,
            "tts_backend": self.tts_backend,
            "llm_backend": self.llm_backend,
            "persona": self.persona,
        }
        if include_audio:
            data["audio_wav_base64"] = self.audio_wav_base64
        return data


def run_typed_turn(
    text: str,
    config: Config,
    *,
    llm_backend: str | None = None,
    tts_backend: str | None = None,
    persona: str | None = None,
) -> TurnResult:
    if not text.strip():
        raise ValueError("Input text is required.")

    request_id = uuid.uuid4().hex[:12]
    turn_start = perf_counter()
    timer = TurnTimer()
    selected_llm = llm_backend or config.llm_backend
    selected_tts = tts_backend or config.tts_backend
    selected_persona = persona or config.persona

    with timer.measure("llm_full_response_ms"):
        reply_text = build_llm(config, selected_llm).reply(text)

    with timer.measure("persona_transform_ms"):
        spoken_text = apply_persona(
            reply_text,
            selected_persona,
            config.resolve(config.rocky_say_path),
        )

    with timer.measure("tts_generation_ms"):
        wav_bytes = build_tts(config, selected_tts).synthesize(spoken_text)

    timer.timings_ms["total_turn_ms"] = round((perf_counter() - turn_start) * 1000, 2)

    output_dir = config.resolve(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = output_dir / f"{request_id}.wav"
    audio_path.write_bytes(wav_bytes)

    result = TurnResult(
        request_id=request_id,
        input_text=text,
        reply_text=reply_text,
        spoken_text=spoken_text,
        audio_path=audio_path,
        audio_wav_base64=base64.b64encode(wav_bytes).decode("ascii"),
        timings_ms=timer.timings_ms,
        tts_backend=selected_tts,
        llm_backend=selected_llm,
        persona=selected_persona,
    )
    _log_turn(config, result)
    return result


def _log_turn(config: Config, result: TurnResult) -> None:
    record = result.as_dict(include_audio=False)
    record["created_at"] = datetime.now(timezone.utc).isoformat()
    append_jsonl(config.resolve(config.log_dir) / "turns.jsonl", record)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one typed Rocky Relay turn locally.")
    parser.add_argument("text", nargs="?", help="Typed prompt to send through the pipeline.")
    parser.add_argument("--config", help="Path to config.json.")
    parser.add_argument("--llm", help="Override LLM backend, e.g. echo or ollama.")
    parser.add_argument(
        "--tts",
        help=(
            "Override TTS backend, e.g. silent, tone, macos_say, piper, "
            "rocky_xtts, rocky_xtts_cli, rocky_yourtts, or smallest_ai."
        ),
    )
    parser.add_argument("--persona", help="Override persona, e.g. none, rocky_basic, rocky_say.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON result.")
    args = parser.parse_args()

    text = args.text or input("Prompt: ").strip()
    config = load_config(args.config)
    try:
        result = run_typed_turn(
            text,
            config,
            llm_backend=args.llm,
            tts_backend=args.tts,
            persona=args.persona,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if args.json:
        print(json.dumps(result.as_dict(include_audio=False), indent=2))
    else:
        print(f"Reply: {result.reply_text}")
        print(f"Spoken: {result.spoken_text}")
        print(f"WAV: {result.audio_path}")
        print(f"Timings: {result.timings_ms}")


if __name__ == "__main__":
    main()
