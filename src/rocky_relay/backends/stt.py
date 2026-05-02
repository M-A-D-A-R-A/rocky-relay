from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import urlencode
import urllib.error
import urllib.request

from rocky_relay.config import Config


@dataclass
class STTResult:
    text: str
    metadata: dict[str, object]


class STTBackend:
    def transcribe(self, audio_path: Path) -> STTResult:
        raise NotImplementedError


@dataclass
class SmallestAISTT(STTBackend):
    api_key_env: str
    url: str
    language: str = "en"
    word_timestamps: bool = False
    diarize: bool = False
    timeout_s: int = 120

    def transcribe(self, audio_path: Path) -> STTResult:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Smallest AI API key is missing. Set it with: export {self.api_key_env}=..."
            )
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        query_params = {"language": self.language}
        if self.word_timestamps:
            query_params["word_timestamps"] = _bool_query(self.word_timestamps)
        if self.diarize:
            query_params["diarize"] = _bool_query(self.diarize)
        query = urlencode(query_params)
        request = urllib.request.Request(
            f"{self.url}?{query}",
            data=audio_path.read_bytes(),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/octet-stream",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Smallest AI STT failed with HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Smallest AI STT request failed: {exc}") from exc

        text = str(payload.get("transcription", "")).strip()
        if not text:
            raise RuntimeError(f"Smallest AI STT returned no transcription: {payload}")
        return STTResult(text=text, metadata=payload)


@dataclass
class WhisperCppSTT(STTBackend):
    whisper_bin: str
    model_path: Path
    language: str = "en"
    no_gpu: bool = True
    timeout_s: int = 180

    def transcribe(self, audio_path: Path) -> STTResult:
        if shutil.which(self.whisper_bin) is None:
            raise FileNotFoundError(
                f"whisper.cpp executable not found: {self.whisper_bin}. "
                "Install whisper.cpp or use --stt smallest_ai."
            )
        if not self.model_path.exists():
            raise FileNotFoundError(f"whisper.cpp model not found: {self.model_path}")
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
            output_base = Path(handle.name).with_suffix("")
        txt_path = output_base.with_suffix(".txt")

        command = [
            self.whisper_bin,
            "-m",
            str(self.model_path),
            "-f",
            str(audio_path),
            "-l",
            self.language,
            "-otxt",
            "-of",
            str(output_base),
        ]
        if self.no_gpu:
            command.append("--no-gpu")
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
            )
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip()
                raise RuntimeError(f"whisper.cpp failed: {detail}")
            text = txt_path.read_text(encoding="utf-8").strip()
            if not text:
                raise RuntimeError("whisper.cpp produced an empty transcript.")
            return STTResult(text=text, metadata={"backend": "whisper_cpp"})
        finally:
            txt_path.unlink(missing_ok=True)


def build_stt(config: Config, override: str | None = None) -> STTBackend:
    name = override or config.stt_backend
    if name == "smallest_ai":
        return SmallestAISTT(
            api_key_env=config.smallest_api_key_env,
            url=config.smallest_stt_url,
            language=config.smallest_stt_language,
            word_timestamps=config.smallest_stt_word_timestamps,
            diarize=config.smallest_stt_diarize,
        )
    if name == "whisper_cpp":
        return WhisperCppSTT(
            whisper_bin=config.whisper_cpp_bin,
            model_path=config.resolve(config.whisper_cpp_model),
            language=config.whisper_cpp_language,
            no_gpu=config.whisper_cpp_no_gpu,
        )
    raise ValueError(f"Unknown STT backend: {name}")


def _bool_query(value: bool) -> str:
    return "true" if value else "false"
