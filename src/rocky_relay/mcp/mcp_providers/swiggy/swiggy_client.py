from __future__ import annotations

import argparse
import asyncio
import json
from typing import TypeAlias

from rocky_relay.config import Config, load_config
from rocky_relay.mcp.mcp_setup.mcp_client import MCPTool, StreamableHTTPMCPClient


SWIGGY_MCP_ENDPOINTS = {
    "swiggy-food": "https://mcp.swiggy.com/food",
    "swiggy-instamart": "https://mcp.swiggy.com/im",
    "swiggy-dineout": "https://mcp.swiggy.com/dineout",
}

SwiggyTool: TypeAlias = MCPTool


class SwiggyMCPClient(StreamableHTTPMCPClient):
    @classmethod
    def from_config(cls, config: Config) -> SwiggyMCPClient:
        return cls(config)

    def __init__(self, config: Config):
        super().__init__(
            provider_name="Swiggy",
            endpoints=SWIGGY_MCP_ENDPOINTS,
            oauth_server_url="https://mcp.swiggy.com",
            client_name="Rocky Relay Swiggy Assistant",
            token_file=config.resolve(config.swiggy_mcp_token_file),
            callback_host=config.swiggy_mcp_callback_host,
            callback_port=config.swiggy_mcp_callback_port,
            callback_path=config.swiggy_mcp_callback_path,
            request_timeout_s=config.swiggy_mcp_request_timeout_s,
            read_timeout_s=config.swiggy_mcp_read_timeout_s,
        )


async def login_and_list_tools(config: Config) -> list[SwiggyTool]:
    async with SwiggyMCPClient.from_config(config) as client:
        return await client.list_tools()


def main() -> None:
    parser = argparse.ArgumentParser(description="Login to Swiggy MCP and list available tools.")
    parser.add_argument("--config", help="Path to config.json.")
    parser.add_argument("--json", action="store_true", help="Print tools as JSON.")
    args = parser.parse_args()

    config = load_config(args.config)
    tools = asyncio.run(login_and_list_tools(config))
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "service": tool.service,
                        "input_schema": tool.input_schema,
                    }
                    for tool in tools
                ],
                indent=2,
            )
        )
        return

    print(f"Swiggy MCP login OK. Found {len(tools)} tools:")
    for tool in tools:
        print(f"- {tool.name} ({tool.service})")


if __name__ == "__main__":
    main()
