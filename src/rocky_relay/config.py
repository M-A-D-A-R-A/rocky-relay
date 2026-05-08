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
    conversation_log_dir: Path = Path("logs/conversations")
    benchmark_log_dir: Path = Path("logs/benchmarks")
    output_dir: Path = Path("outputs")
    capture_dir: Path = Path("captures")
    ffmpeg_bin: str = "ffmpeg"
    mac_audio_device: str = ":1"
    mac_record_sample_rate: int = 16000
    mac_record_channels: int = 1
    mac_record_duration_s: float = 3.0
    stt_backend: str = "smallest_ai"
    whisper_cpp_bin: str = "whisper-cli"
    whisper_cpp_model: Path = Path("models/whisper/ggml-base.en.bin")
    whisper_cpp_language: str = "en"
    whisper_cpp_no_gpu: bool = True
    llm_backend: str = "echo"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:1b"
    swiggy_ollama_model: str | None = None
    swiggy_mcp_token_file: Path = Path(".swiggy_tokens.json")
    swiggy_mcp_callback_host: str = "localhost"
    swiggy_mcp_callback_port: int = 8767
    swiggy_mcp_callback_path: str = "/callback"
    swiggy_mcp_request_timeout_s: int = 30
    swiggy_mcp_read_timeout_s: int = 300
    swiggy_mcp_max_tool_rounds: int = 4
    swiggy_mcp_history_turns: int = 8
    geocoder_url: str = "https://nominatim.openstreetmap.org/search"
    geocoder_user_agent: str = "rocky-relay/0.1 local-dev"
    geocoder_countrycodes: str = "in"
    geocoder_timeout_s: int = 5
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
    smallest_stt_url: str = "https://api.smallest.ai/waves/v1/pulse/get_text"
    smallest_stt_language: str = "en"
    smallest_stt_word_timestamps: bool = False
    smallest_stt_diarize: bool = False
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
    root_dir = _find_project_root()

    if config_path:
        root_dir = config_path.parent.resolve()
        with config_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)

    _load_dotenv(root_dir / ".env")

    def read_path(name: str, default: str) -> Path:
        return Path(str(raw.get(name, default)))

    return Config(
        root_dir=root_dir,
        host=str(raw.get("host", Config.host)),
        port=int(raw.get("port", Config.port)),
        log_dir=read_path("log_dir", "logs"),
        conversation_log_dir=read_path("conversation_log_dir", "logs/conversations"),
        benchmark_log_dir=read_path("benchmark_log_dir", "logs/benchmarks"),
        output_dir=read_path("output_dir", "outputs"),
        capture_dir=read_path("capture_dir", "captures"),
        ffmpeg_bin=str(raw.get("ffmpeg_bin", Config.ffmpeg_bin)),
        mac_audio_device=str(raw.get("mac_audio_device", Config.mac_audio_device)),
        mac_record_sample_rate=int(
            raw.get("mac_record_sample_rate", Config.mac_record_sample_rate)
        ),
        mac_record_channels=int(raw.get("mac_record_channels", Config.mac_record_channels)),
        mac_record_duration_s=float(
            raw.get("mac_record_duration_s", Config.mac_record_duration_s)
        ),
        stt_backend=str(raw.get("stt_backend", Config.stt_backend)),
        whisper_cpp_bin=str(raw.get("whisper_cpp_bin", Config.whisper_cpp_bin)),
        whisper_cpp_model=read_path("whisper_cpp_model", "models/whisper/ggml-base.en.bin"),
        whisper_cpp_language=str(raw.get("whisper_cpp_language", Config.whisper_cpp_language)),
        whisper_cpp_no_gpu=bool(raw.get("whisper_cpp_no_gpu", Config.whisper_cpp_no_gpu)),
        llm_backend=str(raw.get("llm_backend", Config.llm_backend)),
        ollama_url=str(raw.get("ollama_url", Config.ollama_url)),
        ollama_model=str(raw.get("ollama_model", Config.ollama_model)),
        swiggy_ollama_model=_optional_config_str(raw.get("swiggy_ollama_model")),
        swiggy_mcp_token_file=read_path("swiggy_mcp_token_file", ".swiggy_tokens.json"),
        swiggy_mcp_callback_host=str(
            raw.get("swiggy_mcp_callback_host", Config.swiggy_mcp_callback_host)
        ),
        swiggy_mcp_callback_port=int(
            raw.get("swiggy_mcp_callback_port", Config.swiggy_mcp_callback_port)
        ),
        swiggy_mcp_callback_path=str(
            raw.get("swiggy_mcp_callback_path", Config.swiggy_mcp_callback_path)
        ),
        swiggy_mcp_request_timeout_s=int(
            raw.get("swiggy_mcp_request_timeout_s", Config.swiggy_mcp_request_timeout_s)
        ),
        swiggy_mcp_read_timeout_s=int(
            raw.get("swiggy_mcp_read_timeout_s", Config.swiggy_mcp_read_timeout_s)
        ),
        swiggy_mcp_max_tool_rounds=int(
            raw.get("swiggy_mcp_max_tool_rounds", Config.swiggy_mcp_max_tool_rounds)
        ),
        swiggy_mcp_history_turns=int(
            raw.get("swiggy_mcp_history_turns", Config.swiggy_mcp_history_turns)
        ),
        geocoder_url=str(raw.get("geocoder_url", Config.geocoder_url)),
        geocoder_user_agent=str(raw.get("geocoder_user_agent", Config.geocoder_user_agent)),
        geocoder_countrycodes=str(
            raw.get("geocoder_countrycodes", Config.geocoder_countrycodes)
        ),
        geocoder_timeout_s=int(raw.get("geocoder_timeout_s", Config.geocoder_timeout_s)),
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
        smallest_stt_url=str(raw.get("smallest_stt_url", Config.smallest_stt_url)),
        smallest_stt_language=str(raw.get("smallest_stt_language", Config.smallest_stt_language)),
        smallest_stt_word_timestamps=bool(
            raw.get("smallest_stt_word_timestamps", Config.smallest_stt_word_timestamps)
        ),
        smallest_stt_diarize=bool(raw.get("smallest_stt_diarize", Config.smallest_stt_diarize)),
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

    for candidate_root in _candidate_roots():
        default = candidate_root / "config.json"
        if default.exists():
            return default.resolve()
    return None


def _optional_config_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _find_project_root() -> Path:
    explicit = os.environ.get("ROCKY_RELAY_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve()

    for candidate_root in _candidate_roots():
        if (candidate_root / ".env").exists() or (candidate_root / "pyproject.toml").exists():
            return candidate_root.resolve()
    return Path.cwd().resolve()


def _candidate_roots() -> list[Path]:
    cwd = Path.cwd().resolve()
    roots = [cwd, *cwd.parents]
    source_root = Path(__file__).resolve().parents[2]
    if source_root not in roots:
        roots.append(source_root)
    return roots


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip("\"'")
        if name:
            os.environ.setdefault(name, value)
