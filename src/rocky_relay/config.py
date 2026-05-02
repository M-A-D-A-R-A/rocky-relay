from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Config:
    root_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765
    log_dir: Path = Path("logs")
    output_dir: Path = Path("outputs")
    llm_backend: str = "echo"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:1b"
    tts_backend: str = "silent"
    piper_bin: str = "piper"
    piper_model: Path = Path("models/piper/default.onnx")
    rocky_tts_path: Path = Path("../rocky-pi/rocky/rocky_say")
    rocky_tts_server_url: str = "http://127.0.0.1:59720"
    rocky_tts_speed: float = 1.2
    rocky_tts_agree_cpml: bool = True
    smallest_api_key_env: str = "SMALLEST_API_KEY"
    smallest_tts_url: str = "https://api.smallest.ai/waves/v1/lightning-v3.1/get_speech"
    smallest_voice_id: str = "magnus"
    smallest_sample_rate: int = 24000
    smallest_speed: float = 1.0
    smallest_language: str = "en"
    smallest_output_format: str = "wav"
    persona: str = "none"
    rocky_say_path: Path = Path("vendor/rocky-say/rocky_say")
    max_reply_sentences: int = 2

    def resolve(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        return (self.root_dir / path).resolve()


def load_config(path: str | Path | None = None) -> Config:
    config_path = _find_config_path(path)
    raw: dict[str, Any] = {}
    root_dir = Path.cwd()

    if config_path:
        root_dir = config_path.parent.resolve()
        with config_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)

    def read_path(name: str, default: str) -> Path:
        return Path(str(raw.get(name, default)))

    return Config(
        root_dir=root_dir,
        host=str(raw.get("host", Config.host)),
        port=int(raw.get("port", Config.port)),
        log_dir=read_path("log_dir", "logs"),
        output_dir=read_path("output_dir", "outputs"),
        llm_backend=str(raw.get("llm_backend", Config.llm_backend)),
        ollama_url=str(raw.get("ollama_url", Config.ollama_url)),
        ollama_model=str(raw.get("ollama_model", Config.ollama_model)),
        tts_backend=str(raw.get("tts_backend", Config.tts_backend)),
        piper_bin=str(raw.get("piper_bin", Config.piper_bin)),
        piper_model=read_path("piper_model", "models/piper/default.onnx"),
        rocky_tts_path=read_path("rocky_tts_path", "../rocky-pi/rocky/rocky_say"),
        rocky_tts_server_url=str(raw.get("rocky_tts_server_url", Config.rocky_tts_server_url)),
        rocky_tts_speed=float(raw.get("rocky_tts_speed", Config.rocky_tts_speed)),
        rocky_tts_agree_cpml=bool(raw.get("rocky_tts_agree_cpml", Config.rocky_tts_agree_cpml)),
        smallest_api_key_env=str(raw.get("smallest_api_key_env", Config.smallest_api_key_env)),
        smallest_tts_url=str(raw.get("smallest_tts_url", Config.smallest_tts_url)),
        smallest_voice_id=str(raw.get("smallest_voice_id", Config.smallest_voice_id)),
        smallest_sample_rate=int(raw.get("smallest_sample_rate", Config.smallest_sample_rate)),
        smallest_speed=float(raw.get("smallest_speed", Config.smallest_speed)),
        smallest_language=str(raw.get("smallest_language", Config.smallest_language)),
        smallest_output_format=str(raw.get("smallest_output_format", Config.smallest_output_format)),
        persona=str(raw.get("persona", Config.persona)),
        rocky_say_path=read_path("rocky_say_path", "vendor/rocky-say/rocky_say"),
        max_reply_sentences=int(raw.get("max_reply_sentences", Config.max_reply_sentences)),
    )


def _find_config_path(path: str | Path | None) -> Path | None:
    explicit = path or os.environ.get("ROCKY_RELAY_CONFIG")
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.exists():
            raise FileNotFoundError(f"Config file not found: {candidate}")
        return candidate.resolve()

    default = Path.cwd() / "config.json"
    if default.exists():
        return default.resolve()
    return None
