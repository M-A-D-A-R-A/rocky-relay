from __future__ import annotations

from dataclasses import dataclass
import json
import urllib.error
import urllib.request

from rocky_relay.config import Config
from rocky_relay.mcp.mcp_setup.mcp_agent import MCPAgentLLM
from rocky_relay.mcp.mcp_providers.swiggy.swiggy_agent import (
    SWIGGY_REDIRECT,
    SWIGGY_SAFE_REFUSAL,
    SwiggyProvider,
)


class LLMBackend:
    def reply(self, text: str, *, conversation_id: str | None = None) -> str:
        raise NotImplementedError


@dataclass
class EchoLLM(LLMBackend):
    max_reply_sentences: int = 2

    def reply(self, text: str, *, conversation_id: str | None = None) -> str:
        return f"You said: {text.strip()}"


@dataclass
class OllamaLLM(LLMBackend):
    base_url: str
    model: str
    max_reply_sentences: int = 2
    persona: str = "none"
    timeout_s: int = 120

    def reply(self, text: str, *, conversation_id: str | None = None) -> str:
        prompt = self._prompt(text)
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": self._options(),
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

    def _prompt(self, text: str) -> str:
        if self.persona == "rocky_say_llm":
            return (
                "Write the final assistant reply as text for Rocky from Project Hail Mary to speak. "
                "Answer only the current user message. Do not copy examples. Do not explain these rules.\n"
                "Rules:\n"
                "- Use very short concrete sentences.\n"
                "- Use simple broken English.\n"
                "- Avoid polished assistant phrases like 'I'm here to help', 'please stand by', or 'as an AI'.\n"
                "- Include useful concrete information from the answer.\n"
                "- Do not answer only with praise or emotion words.\n"
                "- Do not repeat filler words like question, amaze, or good.\n"
                "- Avoid using 'amaze' unless something is truly surprising.\n"
                "- Use normal question marks; do not write the word question.\n"
                "- Rocky is the speaker. Do not say you help Rocky; say you help the user.\n"
                "- Do not mention Rocky unless the user asks about Rocky.\n"
                "- Stay useful; do not become nonsense.\n"
                f"- Reply in at most {self.max_reply_sentences} short sentences.\n\n"
                f"Current user message: {text.strip()}\n"
                "Final reply:"
            )
        return (
            "You are a concise low-latency voice assistant. "
            f"Reply in at most {self.max_reply_sentences} short sentences.\n\n"
            f"User: {text.strip()}\n"
            "Assistant:"
        )

    def _options(self) -> dict[str, object]:
        if self.persona == "rocky_say_llm":
            return {"num_predict": 60, "temperature": 0.1}
        return {"num_predict": 80, "temperature": 0.5}


class OllamaSwiggyLLM(MCPAgentLLM, LLMBackend):
    def __init__(
        self,
        *,
        config: Config,
        base_url: str,
        model: str,
        max_reply_sentences: int = 2,
        persona: str = "none",
        timeout_s: int = 180,
    ):
        super().__init__(
            provider=SwiggyProvider(config),
            config=config,
            base_url=base_url,
            model=model,
            max_reply_sentences=max_reply_sentences,
            persona=persona,
            timeout_s=timeout_s,
        )


def build_llm(
    config: Config,
    override: str | None = None,
    *,
    persona: str = "none",
) -> LLMBackend:
    name = override or config.llm_backend
    if name == "echo":
        return EchoLLM(max_reply_sentences=config.max_reply_sentences)
    if name == "ollama":
        return OllamaLLM(
            base_url=config.ollama_url,
            model=config.ollama_model,
            max_reply_sentences=config.max_reply_sentences,
            persona=persona,
        )
    if name in {"ollama_swiggy", "swiggy_ollama"}:
        return OllamaSwiggyLLM(
            config=config,
            base_url=config.ollama_url,
            model=config.swiggy_ollama_model or config.ollama_model,
            max_reply_sentences=config.max_reply_sentences,
            persona=persona,
        )
    raise ValueError(f"Unknown LLM backend: {name}")
