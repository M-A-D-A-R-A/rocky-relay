from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import json
import threading
from typing import Any, Protocol
import urllib.error
import urllib.request

from rocky_relay.config import Config


@dataclass(frozen=True)
class ToolCallPlan:
    name: str
    arguments: dict[str, Any]
    route: str


@dataclass
class MCPAgentRuntime:
    metadata: dict[str, Any]
    call_tool: Callable[[str, dict[str, Any]], Awaitable[str]]
    remember: Callable[[str, str], None]


class MCPTool(Protocol):
    name: str

    def as_ollama_tool(self) -> dict[str, Any]:
        ...


class MCPClient(Protocol):
    async def __aenter__(self) -> MCPClient:
        ...

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        ...

    async def list_tools(self) -> list[MCPTool]:
        ...

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        ...


class MCPProvider(Protocol):
    name: str
    backend_name: str
    safe_refusal: str
    redirect: str

    def create_client(self, config: Config) -> MCPClient:
        ...

    def max_tool_rounds(self, config: Config) -> int:
        ...

    def history_turns(self, config: Config) -> int:
        ...

    def initial_metadata(self, *, model: str) -> dict[str, Any]:
        ...

    def is_request(self, text: str) -> bool:
        ...

    def has_pending_context(self, state_key: str) -> bool:
        ...

    def system_prompt(
        self,
        *,
        max_reply_sentences: int,
        persona: str,
    ) -> str:
        ...

    def pending_action(
        self,
        text: str,
        state_key: str,
        tool_names: list[str],
    ) -> dict[str, Any] | None:
        ...

    async def handle_pending_action(
        self,
        action: dict[str, Any],
        runtime: MCPAgentRuntime,
        *,
        state_key: str,
        user_text: str,
    ) -> str:
        ...

    def pending_tool_call(
        self,
        text: str,
        state_key: str,
        tool_names: list[str],
    ) -> ToolCallPlan | None:
        ...

    def planned_tool_call(
        self,
        text: str,
        tool_names: list[str],
    ) -> ToolCallPlan | None:
        ...

    def remember_tool_result(
        self,
        state_key: str,
        user_text: str,
        tool_name: str,
        arguments: dict[str, Any],
        result_text: str,
    ) -> None:
        ...

    def metadata_for_tool_result(
        self,
        tool_name: str,
        result_text: str,
    ) -> dict[str, Any]:
        ...

    def summarize_tool_result(self, tool_name: str, result_text: str) -> str | None:
        ...

    def fallback_reply(self) -> str:
        ...


_MCP_HISTORY_LOCK = threading.Lock()
_MCP_HISTORIES: dict[tuple[str, str], list[dict[str, str]]] = {}


@dataclass
class MCPAgentLLM:
    provider: MCPProvider
    config: Config
    base_url: str
    model: str
    max_reply_sentences: int = 2
    persona: str = "none"
    timeout_s: int = 180

    def __post_init__(self) -> None:
        self.last_metadata: dict[str, Any] = {}

    def reply(self, text: str, *, conversation_id: str | None = None) -> str:
        return run_async(self._reply_async(text, conversation_id=conversation_id))

    async def _reply_async(self, text: str, *, conversation_id: str | None) -> str:
        self.last_metadata = self.provider.initial_metadata(model=self.model)
        self.last_metadata.setdefault("backend", self.provider.backend_name)
        self.last_metadata.setdefault("mcp_provider", self.provider.name)
        self.last_metadata.setdefault("tool_attempt_count", 0)
        self.last_metadata.setdefault("called_tool_names", [])
        self.last_metadata.setdefault("tool_events", [])
        self.last_metadata.setdefault("no_tool_retry", False)
        self.last_metadata.setdefault("no_tool_refusal", False)
        self.last_metadata.setdefault("out_of_scope_redirect", False)

        state_key = conversation_id or "default"
        history_key = (self.provider.name, state_key)
        has_pending = self.provider.has_pending_context(state_key)
        self.last_metadata["pending_context"] = has_pending

        if not self.provider.is_request(text) and not has_pending:
            self.last_metadata["out_of_scope_redirect"] = True
            self.last_metadata["route"] = "out_of_scope_redirect"
            return self.provider.redirect

        messages = self._initial_messages(text, history_key)

        async with self.provider.create_client(self.config) as client:
            tools = await client.list_tools()
            tool_names = [tool.name for tool in tools]
            self.last_metadata["available_tool_count"] = len(tool_names)
            ollama_tools = [tool.as_ollama_tool() for tool in tools]
            runtime = MCPAgentRuntime(
                metadata=self.last_metadata,
                call_tool=lambda name, arguments: self._call_tool_for_messages(
                    client,
                    name,
                    arguments,
                ),
                remember=lambda user, reply: self._remember(history_key, user, reply),
            )

            pending_action = self.provider.pending_action(text, state_key, tool_names)
            if pending_action is not None:
                self.last_metadata["route"] = pending_action.get("kind", "pending_action")
                reply = await self.provider.handle_pending_action(
                    pending_action,
                    runtime,
                    state_key=state_key,
                    user_text=text,
                )
                return reply

            for planned in (
                self.provider.pending_tool_call(text, state_key, tool_names),
                self.provider.planned_tool_call(text, tool_names),
            ):
                if planned is None:
                    continue
                reply = await self._call_planned_tool(
                    client,
                    messages,
                    planned,
                    state_key=state_key,
                    history_key=history_key,
                    user_text=text,
                )
                return reply

            for _ in range(max(1, self.provider.max_tool_rounds(self.config))):
                response = self._chat(messages, tools=ollama_tools)
                message = response.get("message", {})
                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    if int(self.last_metadata.get("tool_attempt_count", 0)) > 0:
                        reply = str(message.get("content", "")).strip()
                        if reply:
                            self._remember(history_key, text, reply)
                            return reply
                    if not self.last_metadata["no_tool_retry"]:
                        self.last_metadata["no_tool_retry"] = True
                        self.last_metadata["route"] = "no_tool_retry"
                        messages.extend(_no_tool_retry_messages(self.provider.name, message))
                        continue
                    self.last_metadata["no_tool_refusal"] = True
                    self.last_metadata["route"] = "no_tool_refusal"
                    self._remember(history_key, text, self.provider.safe_refusal)
                    return self.provider.safe_refusal

                self.last_metadata["route"] = "llm_tool_call"
                messages.append(_ollama_message(message))
                for tool_call in tool_calls:
                    name, arguments = _parse_tool_call(tool_call)
                    result_text = await self._call_tool_for_messages(client, name, arguments)
                    self.last_metadata.update(
                        self.provider.metadata_for_tool_result(name, result_text)
                    )
                    self.provider.remember_tool_result(
                        state_key,
                        text,
                        name,
                        arguments,
                        result_text,
                    )
                    messages.append(_tool_result_message(name, result_text))

            final_response = self._chat(messages, tools=[])
            reply = str(final_response.get("message", {}).get("content", "")).strip()
            if reply:
                self._remember(history_key, text, reply)
                return reply

        fallback = self.provider.fallback_reply()
        self._remember(history_key, text, fallback)
        return fallback

    async def _call_planned_tool(
        self,
        client: MCPClient,
        messages: list[dict[str, Any]],
        planned: ToolCallPlan,
        *,
        state_key: str,
        history_key: tuple[str, str],
        user_text: str,
    ) -> str:
        self.last_metadata["route"] = planned.route
        result_text = await self._call_tool_for_messages(client, planned.name, planned.arguments)
        self.last_metadata.update(self.provider.metadata_for_tool_result(planned.name, result_text))
        self.provider.remember_tool_result(
            state_key,
            user_text,
            planned.name,
            planned.arguments,
            result_text,
        )
        summary = self.provider.summarize_tool_result(planned.name, result_text)
        if summary is not None:
            self._remember(history_key, user_text, summary)
            return summary

        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": planned.name, "arguments": planned.arguments}}
                    ],
                },
                _tool_result_message(planned.name, result_text),
            ]
        )
        final_response = self._chat(messages, tools=[])
        reply = str(final_response.get("message", {}).get("content", "")).strip()
        if not reply:
            reply = _brief_tool_result(self.provider, planned.name, result_text)
        self._remember(history_key, user_text, reply)
        return reply

    async def _call_tool_for_messages(
        self,
        client: MCPClient,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        self.last_metadata["tool_attempt_count"] = int(
            self.last_metadata.get("tool_attempt_count", 0)
        ) + 1
        called = list(self.last_metadata.get("called_tool_names", []))
        called.append(tool_name)
        self.last_metadata["called_tool_names"] = called

        event: dict[str, Any] = {
            "name": tool_name,
            "argument_keys": sorted(str(key) for key in arguments.keys()),
        }
        try:
            result_text = await client.call_tool(tool_name, arguments)
            event["status"] = "error" if tool_result_is_error(result_text) else "ok"
            event["result_chars"] = len(result_text)
            return result_text
        except Exception as exc:
            event["status"] = "exception"
            event["error_type"] = type(exc).__name__
            event["error"] = str(exc)[:240]
            return json.dumps(
                {"is_error": True, "error": str(exc)},
                ensure_ascii=True,
            )
        finally:
            events = list(self.last_metadata.get("tool_events", []))
            events.append(event)
            self.last_metadata["tool_events"] = events

    def _initial_messages(
        self,
        text: str,
        history_key: tuple[str, str],
    ) -> list[dict[str, Any]]:
        with _MCP_HISTORY_LOCK:
            history = list(_MCP_HISTORIES.get(history_key, []))
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self.provider.system_prompt(
                    max_reply_sentences=self.max_reply_sentences,
                    persona=self.persona,
                ),
            },
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": text.strip()})
        return messages

    def _remember(self, history_key: tuple[str, str], text: str, reply: str) -> None:
        keep_messages = max(2, self.provider.history_turns(self.config) * 2)
        with _MCP_HISTORY_LOCK:
            history = _MCP_HISTORIES.setdefault(history_key, [])
            history.extend(
                [
                    {"role": "user", "content": text.strip()},
                    {"role": "assistant", "content": reply},
                ]
            )
            del history[:-keep_messages]

    def _chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": self._options(),
        }
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Ollama {self.provider.name} request failed: {exc}"
            ) from exc

    def _options(self) -> dict[str, object]:
        return {"num_predict": 180, "temperature": 0.2}


def run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:  # pragma: no cover - defensive for embedded runtimes.
            result["error"] = exc

    thread = threading.Thread(target=runner)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _parse_tool_call(tool_call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    function = tool_call.get("function") or {}
    name = str(function.get("name", "")).strip()
    if not name:
        raise RuntimeError(f"Ollama returned a malformed tool call: {tool_call}")
    arguments = function.get("arguments") or {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {"value": arguments}
    if not isinstance(arguments, dict):
        arguments = {"value": arguments}
    return name, arguments


def _no_tool_retry_messages(provider_name: str, message: dict[str, Any]) -> list[dict[str, str]]:
    content = str(message.get("content", "")).strip()
    retry_messages: list[dict[str, str]] = []
    if content:
        retry_messages.append({"role": "assistant", "content": content})
    retry_messages.append(
        {
            "role": "user",
            "content": (
                f"The previous response is invalid because {provider_name} data requires "
                "MCP tool calls. Do not answer with prose, code, fake APIs, or examples. "
                "Call the best matching MCP tool now. If an address or location is required, "
                "call the address/location tool first."
            ),
        }
    )
    return retry_messages


def _tool_result_message(tool_name: str, result_text: str) -> dict[str, str]:
    return {
        "role": "tool",
        "content": result_text,
        "tool_name": tool_name,
    }


def _brief_tool_result(provider: MCPProvider, tool_name: str, result_text: str) -> str:
    summary = provider.summarize_tool_result(tool_name, result_text)
    if summary is not None:
        return summary
    if not result_text.strip():
        return f"I called {tool_name}, but the MCP provider returned no details."
    if len(result_text) <= 220:
        return f"I called {tool_name}. The MCP provider returned: {result_text}"
    return f"I called {tool_name}. The MCP provider returned details, but I need a follow-up to summarize them."


def tool_result_is_error(result_text: str) -> bool:
    lowered = result_text.lower()
    return (
        '"is_error": true' in lowered
        or '"status": "error"' in lowered
        or '"success": false' in lowered
    )


def _ollama_message(message: dict[str, Any]) -> dict[str, Any]:
    allowed = {"role", "content", "tool_calls"}
    return {key: value for key, value in message.items() if key in allowed}
