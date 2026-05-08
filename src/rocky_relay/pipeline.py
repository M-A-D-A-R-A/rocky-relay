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
from rocky_relay.backends.stt import build_stt
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
    conversation_id: str | None = None
    input_audio_path: str | None = None
    stt_backend: str | None = None
    stt_metadata: dict[str, object] | None = None
    llm_metadata: dict[str, object] | None = None

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
        if self.conversation_id is not None:
            data["conversation_id"] = self.conversation_id
        if self.input_audio_path is not None:
            data["input_audio_path"] = self.input_audio_path
        if self.stt_backend is not None:
            data["stt_backend"] = self.stt_backend
        if self.stt_metadata is not None:
            data["stt_metadata"] = self.stt_metadata
        if self.llm_metadata is not None:
            data["llm_metadata"] = self.llm_metadata
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
    conversation_id: str | None = None,
    log_scope: str = "conversation",
) -> TurnResult:
    if not text.strip():
        raise ValueError("Input text is required.")

    request_id = uuid.uuid4().hex[:12]
    return _run_reply_turn(
        text.strip(),
        config,
        request_id=request_id,
        llm_backend=llm_backend,
        tts_backend=tts_backend,
        persona=persona,
        conversation_id=conversation_id,
        log_scope=log_scope,
    )


def run_audio_turn(
    audio_path: str | Path,
    config: Config,
    *,
    request_id: str | None = None,
    stt_backend: str | None = None,
    llm_backend: str | None = None,
    tts_backend: str | None = None,
    persona: str | None = None,
    conversation_id: str | None = None,
    log_scope: str = "conversation",
) -> TurnResult:
    resolved_audio_path = Path(audio_path)
    if not resolved_audio_path.is_absolute():
        resolved_audio_path = config.resolve(resolved_audio_path)
    if not resolved_audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {resolved_audio_path}")

    request_id = request_id or uuid.uuid4().hex[:12]
    turn_start = perf_counter()
    timer = TurnTimer()
    selected_stt = stt_backend or config.stt_backend

    with timer.measure("stt_transcription_ms"):
        stt_result = build_stt(config, selected_stt).transcribe(resolved_audio_path)

    result = _run_reply_turn(
        stt_result.text,
        config,
        request_id=request_id,
        llm_backend=llm_backend,
        tts_backend=tts_backend,
        persona=persona,
        timer=timer,
        turn_start=turn_start,
        input_audio_path=str(resolved_audio_path),
        stt_backend=selected_stt,
        stt_metadata=stt_result.metadata,
        conversation_id=conversation_id,
        log_scope=log_scope,
    )
    return result


def _run_reply_turn(
    text: str,
    config: Config,
    *,
    request_id: str,
    llm_backend: str | None = None,
    tts_backend: str | None = None,
    persona: str | None = None,
    timer: TurnTimer | None = None,
    turn_start: float | None = None,
    input_audio_path: str | None = None,
    stt_backend: str | None = None,
    stt_metadata: dict[str, object] | None = None,
    conversation_id: str | None = None,
    log_scope: str = "conversation",
) -> TurnResult:
    if timer is None:
        timer = TurnTimer()
    if turn_start is None:
        turn_start = perf_counter()

    selected_llm = llm_backend or config.llm_backend
    selected_tts = tts_backend or config.tts_backend
    selected_persona = persona or config.persona
    llm = build_llm(config, selected_llm, persona=selected_persona)

    with timer.measure("llm_full_response_ms"):
        reply_text = llm.reply(
            text,
            conversation_id=conversation_id,
        )
    llm_metadata = getattr(llm, "last_metadata", None)

    with timer.measure("persona_transform_ms"):
        spoken_text = apply_persona(
            reply_text,
            selected_persona,
            config.resolve(config.rocky_say_path),
        )

    with timer.measure("tts_generation_ms"):
        wav_bytes = build_tts(config, selected_tts).synthesize(spoken_text)

    output_dir = config.resolve(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = output_dir / f"{request_id}.wav"
    audio_path.write_bytes(wav_bytes)
    trigger_to_audio_ready_ms = round((perf_counter() - turn_start) * 1000, 2)
    timer.timings_ms["trigger_to_audio_ready_ms"] = trigger_to_audio_ready_ms
    # Backwards-compatible alias for older docs/log readers.
    timer.timings_ms["total_turn_ms"] = trigger_to_audio_ready_ms

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
        conversation_id=conversation_id,
        input_audio_path=input_audio_path,
        stt_backend=stt_backend,
        stt_metadata=stt_metadata,
        llm_metadata=llm_metadata if isinstance(llm_metadata, dict) else None,
    )
    _log_turn(config, result, log_scope=log_scope)
    return result


def _log_turn(config: Config, result: TurnResult, *, log_scope: str) -> None:
    record = result.as_dict(include_audio=False)
    record["created_at"] = datetime.now(timezone.utc).isoformat()
    append_jsonl(_log_dir_for_scope(config, log_scope) / "turns.jsonl", record)


def _log_dir_for_scope(config: Config, log_scope: str) -> Path:
    if log_scope == "conversation":
        return config.resolve(config.conversation_log_dir)
    if log_scope == "benchmark":
        return config.resolve(config.benchmark_log_dir)
    return config.resolve(config.log_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one typed Rocky Relay turn locally.")
    parser.add_argument("text", nargs="?", help="Typed prompt to send through the pipeline.")
    parser.add_argument("--audio", help="Audio file to transcribe before running the reply pipeline.")
    parser.add_argument("--config", help="Path to config.json.")
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
    parser.add_argument("--conversation-id", help="Optional conversation id to write into logs.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON result.")
    args = parser.parse_args()

    config = load_config(args.config)
    try:
        if args.audio:
            result = run_audio_turn(
                args.audio,
                config,
                stt_backend=args.stt,
                llm_backend=args.llm,
                tts_backend=args.tts,
                persona=args.persona,
                conversation_id=args.conversation_id,
            )
        else:
            text = args.text or input("Prompt: ").strip()
            result = run_typed_turn(
                text,
                config,
                llm_backend=args.llm,
                tts_backend=args.tts,
                persona=args.persona,
                conversation_id=args.conversation_id,
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
