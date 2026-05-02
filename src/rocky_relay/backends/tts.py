from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import urllib.error
import urllib.request
import wave

from rocky_relay.config import Config


class TTSBackend:
    def synthesize(self, text: str) -> bytes:
        raise NotImplementedError


@dataclass
class SilentTTS(TTSBackend):
    duration_s: float = 0.35
    sample_rate: int = 16000

    def synthesize(self, text: str) -> bytes:
        return _make_tone_wav(
            duration_s=self.duration_s,
            sample_rate=self.sample_rate,
            frequency_hz=0,
        )


@dataclass
class ToneTTS(TTSBackend):
    duration_s: float = 0.45
    sample_rate: int = 16000
    frequency_hz: int = 440

    def synthesize(self, text: str) -> bytes:
        return _make_tone_wav(
            duration_s=self.duration_s,
            sample_rate=self.sample_rate,
            frequency_hz=self.frequency_hz,
        )


@dataclass
class MacOSSayTTS(TTSBackend):
    voice: str | None = None
    timeout_s: int = 120

    def synthesize(self, text: str) -> bytes:
        if shutil.which("say") is None or shutil.which("afconvert") is None:
            raise FileNotFoundError("macos_say requires /usr/bin/say and /usr/bin/afconvert.")

        with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as aiff_handle:
            aiff_path = Path(aiff_handle.name)
        wav_path = aiff_path.with_suffix(".wav")

        try:
            say_cmd = ["say", "-o", str(aiff_path)]
            if self.voice:
                say_cmd.extend(["-v", self.voice])
            say_cmd.append(text)

            say_result = subprocess.run(
                say_cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
            )
            if say_result.returncode != 0:
                detail = say_result.stderr.strip() or say_result.stdout.strip()
                raise RuntimeError(f"macOS say failed: {detail}")

            convert_result = subprocess.run(
                ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", str(aiff_path), str(wav_path)],
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
            )
            if convert_result.returncode != 0:
                detail = convert_result.stderr.strip() or convert_result.stdout.strip()
                raise RuntimeError(f"afconvert failed: {detail}")
            return wav_path.read_bytes()
        finally:
            aiff_path.unlink(missing_ok=True)
            wav_path.unlink(missing_ok=True)


@dataclass
class PiperTTS(TTSBackend):
    piper_bin: str
    model_path: Path
    timeout_s: int = 120

    def synthesize(self, text: str) -> bytes:
        if shutil.which(self.piper_bin) is None:
            raise FileNotFoundError(
                f"Piper executable not found: {self.piper_bin}. "
                "Install Piper or use --tts silent for scaffold testing."
            )
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Piper model not found: {self.model_path}. "
                "Download a Piper .onnx voice into models/piper/ or use --tts silent."
            )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            output_path = Path(handle.name)
        try:
            result = subprocess.run(
                [
                    self.piper_bin,
                    "--model",
                    str(self.model_path),
                    "--output_file",
                    str(output_path),
                ],
                input=text,
                text=True,
                capture_output=True,
                timeout=self.timeout_s,
                check=False,
            )
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip()
                raise RuntimeError(f"Piper failed: {detail}")
            return output_path.read_bytes()
        finally:
            output_path.unlink(missing_ok=True)


@dataclass
class RockySayTTS(TTSBackend):
    rocky_say_path: Path
    model: str
    speed: float = 1.2
    agree_cpml: bool = True
    timeout_s: int = 180

    def synthesize(self, text: str) -> bytes:
        if not self.rocky_say_path.exists():
            raise FileNotFoundError(f"rocky_say not found: {self.rocky_say_path}")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            output_path = Path(handle.name)

        command = [
            "python3",
            str(self.rocky_say_path),
            "--raw",
            "-m",
            self.model,
            "-s",
            str(self.speed),
            "-o",
            str(output_path),
        ]
        if self.agree_cpml:
            command.append("--agree-cpml")
        command.append(text)

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
                raise RuntimeError(f"rocky_say {self.model} failed: {detail}")
            if not output_path.exists() or output_path.stat().st_size == 0:
                detail = result.stderr.strip() or result.stdout.strip()
                raise RuntimeError(f"rocky_say {self.model} produced no audio: {detail}")
            return output_path.read_bytes()
        finally:
            output_path.unlink(missing_ok=True)


@dataclass
class RockyXTTSHttpTTS(TTSBackend):
    server_url: str
    timeout_s: int = 120

    def synthesize(self, text: str) -> bytes:
        base_url = self.server_url.rstrip("/")
        try:
            urllib.request.urlopen(f"{base_url}/health", timeout=2).close()
        except urllib.error.URLError as exc:
            raise RuntimeError(
                "Rocky XTTS server is not running. Start it with: "
                "python3 ../rocky-pi/rocky/rocky_say --server start --agree-cpml"
            ) from exc

        payload = json.dumps({"text": text}).encode("utf-8")
        request = urllib.request.Request(
            base_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                wav = response.read()
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Rocky XTTS server request failed: {exc}") from exc

        if not wav:
            raise RuntimeError("Rocky XTTS server returned empty audio.")
        return wav


@dataclass
class SmallestAITTS(TTSBackend):
    api_key_env: str
    url: str
    voice_id: str
    sample_rate: int = 24000
    speed: float = 1.0
    language: str = "en"
    output_format: str = "wav"
    timeout_s: int = 60

    def synthesize(self, text: str) -> bytes:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Smallest AI API key is missing. Set it with: export {self.api_key_env}=..."
            )

        payload = {
            "text": text,
            "voice_id": self.voice_id,
            "sample_rate": self.sample_rate,
            "speed": self.speed,
            "language": self.language,
            "output_format": self.output_format,
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "audio/wav",
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                audio = response.read()
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Smallest AI TTS failed with HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Smallest AI TTS request failed: {exc}") from exc

        if not audio:
            raise RuntimeError("Smallest AI returned empty audio.")
        if "json" in content_type.lower():
            detail = audio.decode("utf-8", errors="replace")
            raise RuntimeError(f"Smallest AI returned JSON instead of audio: {detail}")
        return audio


def build_tts(config: Config, override: str | None = None) -> TTSBackend:
    name = override or config.tts_backend
    if name == "silent":
        return SilentTTS()
    if name == "tone":
        return ToneTTS()
    if name == "macos_say":
        return MacOSSayTTS()
    if name == "piper":
        return PiperTTS(
            piper_bin=config.piper_bin,
            model_path=config.resolve(config.piper_model),
        )
    if name == "rocky_xtts":
        return RockyXTTSHttpTTS(server_url=config.rocky_tts_server_url)
    if name == "rocky_xtts_cli":
        return RockySayTTS(
            rocky_say_path=config.resolve(config.rocky_tts_path),
            model="xtts",
            speed=config.rocky_tts_speed,
            agree_cpml=config.rocky_tts_agree_cpml,
        )
    if name == "rocky_yourtts":
        return RockySayTTS(
            rocky_say_path=config.resolve(config.rocky_tts_path),
            model="yourtts",
            speed=config.rocky_tts_speed,
            agree_cpml=config.rocky_tts_agree_cpml,
        )
    if name == "smallest_ai":
        return SmallestAITTS(
            api_key_env=config.smallest_api_key_env,
            url=config.smallest_tts_url,
            voice_id=config.smallest_voice_id,
            sample_rate=config.smallest_sample_rate,
            speed=config.smallest_speed,
            language=config.smallest_language,
            output_format=config.smallest_output_format,
        )
    raise ValueError(f"Unknown TTS backend: {name}")


def _make_tone_wav(duration_s: float, sample_rate: int, frequency_hz: int) -> bytes:
    frame_count = int(duration_s * sample_rate)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        path = Path(handle.name)

    try:
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            for index in range(frame_count):
                if frequency_hz <= 0:
                    value = 0
                else:
                    angle = 2 * math.pi * frequency_hz * (index / sample_rate)
                    value = int(math.sin(angle) * 12000)
                wav.writeframesraw(struct.pack("<h", value))
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)
