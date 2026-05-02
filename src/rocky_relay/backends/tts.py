from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
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
