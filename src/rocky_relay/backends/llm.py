from __future__ import annotations

from dataclasses import dataclass
import json
import urllib.error
import urllib.request

from rocky_relay.config import Config


class LLMBackend:
    def reply(self, text: str) -> str:
        raise NotImplementedError


@dataclass
class EchoLLM(LLMBackend):
    max_reply_sentences: int = 2

    def reply(self, text: str) -> str:
        return f"You said: {text.strip()}"


@dataclass
class OllamaLLM(LLMBackend):
    base_url: str
    model: str
    max_reply_sentences: int = 2
    timeout_s: int = 120

    def reply(self, text: str) -> str:
        prompt = (
            "You are a concise low-latency voice assistant. "
            f"Reply in at most {self.max_reply_sentences} short sentences.\n\n"
            f"User: {text.strip()}\n"
            "Assistant:"
        )
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 80, "temperature": 0.5},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc

        reply = str(data.get("response", "")).strip()
        if not reply:
            raise RuntimeError(f"Ollama returned no response for model {self.model!r}")
        return reply


def build_llm(config: Config, override: str | None = None) -> LLMBackend:
    name = override or config.llm_backend
    if name == "echo":
        return EchoLLM(max_reply_sentences=config.max_reply_sentences)
    if name == "ollama":
        return OllamaLLM(
            base_url=config.ollama_url,
            model=config.ollama_model,
            max_reply_sentences=config.max_reply_sentences,
        )
    raise ValueError(f"Unknown LLM backend: {name}")
