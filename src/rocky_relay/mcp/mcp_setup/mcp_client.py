from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse
import webbrowser

try:
    from mcp import ClientSession
    from mcp.client.auth import OAuthClientProvider, TokenStorage
    from mcp.client.streamable_http import streamablehttp_client
    from mcp.shared.auth import (
        OAuthClientInformationFull,
        OAuthClientMetadata,
        OAuthToken,
    )
except ImportError as exc:  # pragma: no cover - exercised only without extras installed.
    ClientSession = None
    OAuthClientProvider = None
    OAuthClientInformationFull = None
    OAuthClientMetadata = None
    OAuthToken = None
    streamablehttp_client = None
    _MCP_IMPORT_ERROR: ImportError | None = exc

    class TokenStorage:  # type: ignore[no-redef]
        pass
else:
    _MCP_IMPORT_ERROR = None


@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    service: str

    def as_ollama_tool(self) -> dict[str, Any]:
        parameters = _sanitize_schema(self.input_schema or {"type": "object"})
        parameters.setdefault("type", "object")
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


class FileTokenStorage(TokenStorage):
    """Stores OAuth tokens and dynamic client info in a local JSON file."""

    def __init__(self, path: Path):
        self._path = path
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, default=str), encoding="utf-8")

    async def get_tokens(self) -> Any | None:
        raw = self._data.get("tokens")
        if raw and OAuthToken is not None:
            return OAuthToken(**raw)
        return None

    async def set_tokens(self, tokens: Any) -> None:
        self._data["tokens"] = _model_dump(tokens)
        self._save()

    async def get_client_info(self) -> Any | None:
        raw = self._data.get("client_info")
        if raw and OAuthClientInformationFull is not None:
            return OAuthClientInformationFull(**raw)
        return None

    async def set_client_info(self, client_info: Any) -> None:
        self._data["client_info"] = _model_dump(client_info)
        self._save()


class OAuthCallbackReceiver:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        path: str,
        provider_name: str,
    ):
        self.host = host
        self.port = port
        self.path = path if path.startswith("/") else f"/{path}"
        self.provider_name = provider_name
        self.redirect_uri = f"http://{host}:{port}{self.path}"
        self._code: str | None = None
        self._state: str | None = None
        self._event = threading.Event()

    async def redirect_handler(self, auth_url: str) -> None:
        print(f"\nOpening {self.provider_name} login in your browser.")
        print(f"If it does not open automatically, go to:\n{auth_url}\n")
        webbrowser.open(auth_url)

    async def callback_handler(self) -> tuple[str, str | None]:
        self._code = None
        self._state = None
        self._event.clear()

        handler_cls = self._make_handler()
        server = HTTPServer((self.host, self.port), handler_cls)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(f"Waiting for {self.provider_name} login callback on {self.redirect_uri} ...")

        loop = asyncio.get_event_loop()
        received = await loop.run_in_executor(None, self._event.wait, 120)
        server.shutdown()
        server.server_close()

        if not received:
            raise RuntimeError(f"Timed out waiting for the {self.provider_name} OAuth callback.")
        if not self._code:
            raise RuntimeError("OAuth callback did not receive an authorization code.")
        return self._code, self._state

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        receiver = self

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path != receiver.path:
                    self.send_response(404)
                    self.end_headers()
                    return

                params = parse_qs(parsed.query)
                code = params.get("code", [None])[0]
                state = params.get("state", [None])[0]

                if code:
                    receiver._code = code
                    receiver._state = state
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    html = (
                        "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
                        f"<h2>{receiver.provider_name} login successful.</h2>"
                        "<p>You can close this tab and return to Rocky Relay.</p>"
                        "</body></html>"
                    )
                    self.wfile.write(html.encode("utf-8"))
                else:
                    error = params.get("error", ["unknown"])[0]
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(
                        f"<html><body><h2>{receiver.provider_name} login failed: {error}</h2></body></html>".encode(
                            "utf-8"
                        )
                    )
                receiver._event.set()

            def log_message(self, format: str, *args: object) -> None:
                return

        return CallbackHandler


class StreamableHTTPMCPClient:
    def __init__(
        self,
        *,
        provider_name: str,
        endpoints: dict[str, str],
        oauth_server_url: str,
        client_name: str,
        token_file: Path,
        callback_host: str,
        callback_port: int,
        callback_path: str,
        request_timeout_s: int,
        read_timeout_s: int,
        scope: str = "mcp:tools mcp:resources mcp:prompts",
    ):
        _require_mcp()
        self.provider_name = provider_name
        self.endpoints = endpoints
        self.oauth_server_url = oauth_server_url
        self.client_name = client_name
        self.token_file = token_file
        self.callback_host = callback_host
        self.callback_port = callback_port
        self.callback_path = callback_path
        self.request_timeout_s = request_timeout_s
        self.read_timeout_s = read_timeout_s
        self.scope = scope
        self._stack = AsyncExitStack()
        self._sessions: dict[str, Any] = {}
        self._tool_sessions: dict[str, Any] = {}
        self._tools: list[MCPTool] | None = None

    async def __aenter__(self) -> StreamableHTTPMCPClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        if self._sessions:
            return

        auth = self._create_oauth_provider()
        for service, url in self.endpoints.items():
            streams = await self._stack.enter_async_context(
                streamablehttp_client(
                    url=url,
                    timeout=timedelta(seconds=self.request_timeout_s),
                    sse_read_timeout=timedelta(seconds=self.read_timeout_s),
                    auth=auth,
                )
            )
            session = await self._stack.enter_async_context(
                ClientSession(
                    streams[0],
                    streams[1],
                    read_timeout_seconds=timedelta(seconds=self.read_timeout_s),
                )
            )
            await session.initialize()
            self._sessions[service] = session

    async def disconnect(self) -> None:
        self._tools = None
        self._tool_sessions.clear()
        self._sessions.clear()
        await self._stack.aclose()
        self._stack = AsyncExitStack()

    async def list_tools(self) -> list[MCPTool]:
        if self._tools is not None:
            return self._tools
        if not self._sessions:
            raise RuntimeError(f"{self.provider_name} MCP client is not connected.")

        seen_names: set[str] = set()
        tools: list[MCPTool] = []
        for service, session in self._sessions.items():
            result = await session.list_tools()
            for tool in result.tools:
                if tool.name in seen_names:
                    continue
                seen_names.add(tool.name)
                self._tool_sessions[tool.name] = session
                tools.append(
                    MCPTool(
                        name=tool.name,
                        description=tool.description or "",
                        input_schema=tool.inputSchema or {"type": "object"},
                        service=service,
                    )
                )

        self._tools = tools
        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if not self._tool_sessions:
            await self.list_tools()
        session = self._tool_sessions.get(tool_name)
        if session is None:
            raise ValueError(f"Unknown {self.provider_name} MCP tool: {tool_name}")
        result = await session.call_tool(tool_name, arguments or {})
        return _tool_result_to_text(result)

    def _create_oauth_provider(self) -> Any:
        receiver = OAuthCallbackReceiver(
            host=self.callback_host,
            port=self.callback_port,
            path=self.callback_path,
            provider_name=self.provider_name,
        )
        storage = FileTokenStorage(self.token_file)
        metadata = OAuthClientMetadata(
            redirect_uris=[receiver.redirect_uri],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            client_name=self.client_name,
            scope=self.scope,
        )
        return OAuthClientProvider(
            server_url=self.oauth_server_url,
            client_metadata=metadata,
            storage=storage,
            redirect_handler=receiver.redirect_handler,
            callback_handler=receiver.callback_handler,
            timeout=120.0,
        )


def _sanitize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {"type": "object"}

    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if isinstance(value, dict):
            cleaned[key] = _sanitize_schema(value)
        elif key == "type" and isinstance(value, list):
            cleaned[key] = value[0] if len(value) == 1 else "string"
        elif key == "enum" and isinstance(value, list):
            cleaned[key] = [str(item) for item in value]
        else:
            cleaned[key] = value

    return cleaned


def _tool_result_to_text(result: Any) -> str:
    parts: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(str(text))
        else:
            parts.append(json.dumps(_model_dump(item), ensure_ascii=True))

    payload: dict[str, Any] = {"content": parts}
    if getattr(result, "isError", False):
        payload["is_error"] = True
    if len(parts) == 1:
        return parts[0]
    return json.dumps(payload, ensure_ascii=True)


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return value
    return {"value": str(value)}


def _require_mcp() -> None:
    if _MCP_IMPORT_ERROR is None:
        return
    raise RuntimeError(
        "MCP support requires the optional 'mcp' package. "
        "Install Rocky Relay with the provider extras, for example: pip install -e '.[swiggy]'"
    ) from _MCP_IMPORT_ERROR
