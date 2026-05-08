from __future__ import annotations

from pathlib import Path
import unittest

from rocky_relay.backends import llm as llm_mod
from rocky_relay.config import Config
from rocky_relay.mcp.mcp_setup.mcp_agent import _MCP_HISTORIES
from rocky_relay.mcp.mcp_providers.swiggy import swiggy_agent as swiggy_mod


class FakeTool:
    def __init__(self, name: str):
        self.name = name

    def as_ollama_tool(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": f"Fake {self.name}",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }


class FakeClient:
    calls: list[tuple[str, dict[str, object]]] = []
    entered = False

    @classmethod
    def from_config(cls, config: Config) -> FakeClient:
        return cls()

    async def __aenter__(self) -> FakeClient:
        type(self).entered = True
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def list_tools(self) -> list[FakeTool]:
        return [
            FakeTool("get_addresses"),
            FakeTool("get_cart"),
            FakeTool("search_products"),
            FakeTool("update_cart"),
            FakeTool("search_restaurants_dineout"),
        ]

    async def call_tool(self, name: str, arguments: dict[str, object]) -> str:
        type(self).calls.append((name, arguments))
        if name == "search_restaurants_dineout":
            return '{"data": [{"name": "Taj Palace"}, {"name": "The Coffee Club"}]}'
        if name == "get_addresses":
            return (
                "Found 2 saved addresses:\n"
                "1. [Home] Redacted address (ID: home-address-id)\n"
                "2. [Office] Redacted address (ID: office-address-id)\n"
                "Ask the user which address to use for delivery."
            )
        if name == "search_products":
            return (
                '{"success": true, "data": {"products": ['
                '{"displayName": "Amul Shakti Milk", "variations": ['
                '{"spinId": "spin-shakti-500", "displayName": "Amul Shakti Milk", '
                '"quantityDescription": "500 ml", "price": {"offerPrice": 31}, '
                '"isInStockAndAvailable": true}'
                ']},'
                '{"displayName": "Amul Gold Milk", "variations": ['
                '{"spinId": "spin-gold-500", "displayName": "Amul Gold Milk", '
                '"quantityDescription": "500 ml", "price": {"offerPrice": 34}, '
                '"isInStockAndAvailable": true}'
                ']}'
                ']}}'
            )
        if name == "get_cart":
            return '{"success": true, "data": {"items": []}}'
        if name == "update_cart":
            return '{"success": true, "data": {"cart": {"items": []}}}'
        return f"{name} result"


class ScriptedSwiggyLLM(llm_mod.OllamaSwiggyLLM):
    def __init__(self, responses: list[dict[str, object]]):
        super().__init__(
            config=Config(root_dir=Path.cwd()),
            base_url="http://ollama.invalid",
            model="fake-tool-model",
            persona="none",
        )
        self.responses = responses
        self.chat_calls: list[dict[str, object]] = []

    def _chat(
        self,
        messages: list[dict[str, object]],
        *,
        tools: list[dict[str, object]],
    ) -> dict[str, object]:
        self.chat_calls.append({"messages": list(messages), "tool_count": len(tools)})
        if not self.responses:
            raise AssertionError("Unexpected extra chat call")
        return self.responses.pop(0)


class OllamaSwiggyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_client = swiggy_mod.SwiggyMCPClient
        self.original_fetch_geocode = swiggy_mod._fetch_geocode
        swiggy_mod.SwiggyMCPClient = FakeClient
        swiggy_mod._fetch_geocode = self._fake_fetch_geocode
        swiggy_mod._GEOCODE_CACHE.clear()
        swiggy_mod._SWIGGY_PENDING_CONTEXTS.clear()
        _MCP_HISTORIES.clear()
        FakeClient.calls = []
        FakeClient.entered = False

    def tearDown(self) -> None:
        swiggy_mod.SwiggyMCPClient = self.original_client
        swiggy_mod._fetch_geocode = self.original_fetch_geocode
        swiggy_mod._GEOCODE_CACHE.clear()
        swiggy_mod._SWIGGY_PENDING_CONTEXTS.clear()
        _MCP_HISTORIES.clear()

    def _fake_fetch_geocode(
        self,
        location: str,
        config: Config,
    ) -> tuple[float, float] | None:
        if location == "ahmedabad":
            return 23.0225, 72.5714
        if location == "gandhinagar":
            return 23.2156, 72.6369
        return None

    def test_retries_prose_then_calls_tool(self) -> None:
        backend = ScriptedSwiggyLLM(
            [
                {"message": {"role": "assistant", "content": "Here is a fake API."}},
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "search_restaurants_dineout",
                                    "arguments": {"query": "Ahmedabad"},
                                }
                            }
                        ],
                    }
                },
                {"message": {"role": "assistant", "content": "I found real restaurants."}},
            ]
        )

        reply = backend.reply("order biryani tonight", conversation_id="test")

        self.assertEqual(reply, "I found real restaurants.")
        self.assertEqual(FakeClient.calls, [("search_restaurants_dineout", {"query": "Ahmedabad"})])
        self.assertEqual(backend.last_metadata["called_tool_names"], ["search_restaurants_dineout"])
        self.assertEqual(backend.last_metadata["tool_attempt_count"], 1)
        self.assertTrue(backend.last_metadata["no_tool_retry"])
        self.assertFalse(backend.last_metadata["no_tool_refusal"])

    def test_restaurant_search_routes_to_dineout_tool(self) -> None:
        backend = ScriptedSwiggyLLM([])

        reply = backend.reply("find restaurants in Ahmedabad", conversation_id="test")

        self.assertEqual(reply, "I found restaurants in Swiggy Dineout: Taj Palace, The Coffee Club.")
        self.assertEqual(
            FakeClient.calls,
            [
                (
                    "search_restaurants_dineout",
                    {"query": "restaurants", "latitude": 23.0225, "longitude": 72.5714},
                )
            ],
        )
        self.assertEqual(backend.last_metadata["called_tool_names"], ["search_restaurants_dineout"])
        self.assertFalse(backend.last_metadata["no_tool_retry"])

    def test_restaurant_search_routes_gandhinagar_typo_to_coordinates(self) -> None:
        backend = ScriptedSwiggyLLM([])

        reply = backend.reply("find me all the restraunt in gandhinager", conversation_id="test")

        self.assertEqual(reply, "I found restaurants in Swiggy Dineout: Taj Palace, The Coffee Club.")
        self.assertEqual(
            FakeClient.calls,
            [
                (
                    "search_restaurants_dineout",
                    {"query": "restaurants", "latitude": 23.2156, "longitude": 72.6369},
                )
            ],
        )

    def test_restaurant_search_routes_stt_kandinagar_to_coordinates(self) -> None:
        backend = ScriptedSwiggyLLM([])

        reply = backend.reply("Rocky find me all the restaurants in Kandinagar.", conversation_id="test")

        self.assertEqual(reply, "I found restaurants in Swiggy Dineout: Taj Palace, The Coffee Club.")
        self.assertEqual(
            FakeClient.calls,
            [
                (
                    "search_restaurants_dineout",
                    {"query": "restaurants", "latitude": 23.2156, "longitude": 72.6369},
                )
            ],
        )

    def test_instamart_product_search_fetches_addresses_first(self) -> None:
        backend = ScriptedSwiggyLLM([])

        reply = backend.reply("find Amul milk on Instamart", conversation_id="test")

        self.assertEqual(reply, "Which saved address would you like to use for delivery?")
        self.assertEqual(FakeClient.calls, [("get_addresses", {})])
        self.assertEqual(backend.last_metadata["called_tool_names"], ["get_addresses"])

    def test_instamart_address_selection_continues_product_search(self) -> None:
        backend = ScriptedSwiggyLLM([])

        first_reply = backend.reply("find Amul milk on Instamart", conversation_id="test")
        second_reply = backend.reply("home", conversation_id="test")

        self.assertEqual(first_reply, "Which saved address would you like to use for delivery?")
        self.assertEqual(
            second_reply,
            "I found Instamart products: Amul Shakti Milk 500 ml, Amul Gold Milk 500 ml. Which one should I add?",
        )
        self.assertEqual(
            FakeClient.calls,
            [
                ("get_addresses", {}),
                (
                    "search_products",
                    {"addressId": "home-address-id", "query": "amul milk", "offset": 0},
                ),
            ],
        )
        self.assertEqual(backend.last_metadata["called_tool_names"], ["search_products"])
        self.assertEqual(backend.last_metadata["route"], "pending_tool_call:instamart_address")
        tool_events = backend.last_metadata["tool_events"]
        self.assertEqual(len(tool_events), 1)
        self.assertEqual(tool_events[0]["name"], "search_products")
        self.assertEqual(tool_events[0]["argument_keys"], ["addressId", "offset", "query"])
        self.assertEqual(tool_events[0]["status"], "ok")
        self.assertGreater(tool_events[0]["result_chars"], 0)
        self.assertEqual(
            backend.last_metadata["suggestions"],
            [
                {
                    "number": 1,
                    "title": "Amul Shakti Milk",
                    "subtitle": "500 ml - Rs 31",
                    "price": "Rs 31",
                    "available": True,
                },
                {
                    "number": 2,
                    "title": "Amul Gold Milk",
                    "subtitle": "500 ml - Rs 34",
                    "price": "Rs 34",
                    "available": True,
                },
            ],
        )

    def test_instamart_suggestion_selection_updates_cart(self) -> None:
        backend = ScriptedSwiggyLLM([])

        backend.reply("find Amul milk on Instamart", conversation_id="test")
        backend.reply("home", conversation_id="test")
        reply = backend.reply("add suggestion 2 to cart", conversation_id="test")

        self.assertEqual(reply, "Added Amul Gold Milk 500 ml to your Instamart cart.")
        self.assertEqual(
            FakeClient.calls,
            [
                ("get_addresses", {}),
                (
                    "search_products",
                    {"addressId": "home-address-id", "query": "amul milk", "offset": 0},
                ),
                ("get_cart", {}),
                (
                    "update_cart",
                    {
                        "selectedAddressId": "home-address-id",
                        "items": [{"spinId": "spin-gold-500", "quantity": 1}],
                    },
                ),
            ],
        )
        self.assertEqual(backend.last_metadata["called_tool_names"], ["get_cart", "update_cart"])
        self.assertEqual(backend.last_metadata["suggestions"], [])

    def test_two_prose_responses_refuse_safely(self) -> None:
        backend = ScriptedSwiggyLLM(
            [
                {"message": {"role": "assistant", "content": "Here is a script."}},
                {"message": {"role": "assistant", "content": "Use this fake API."}},
            ]
        )

        reply = backend.reply("order biryani tonight", conversation_id="test")

        self.assertEqual(reply, llm_mod.SWIGGY_SAFE_REFUSAL)
        self.assertEqual(FakeClient.calls, [])
        self.assertTrue(backend.last_metadata["no_tool_retry"])
        self.assertTrue(backend.last_metadata["no_tool_refusal"])

    def test_direct_tool_prompt_calls_named_tool(self) -> None:
        backend = ScriptedSwiggyLLM([])

        reply = backend.reply("call get_addresses tool", conversation_id="test")

        self.assertEqual(reply, "Which saved address would you like to use for delivery?")
        self.assertEqual(FakeClient.calls, [("get_addresses", {})])
        self.assertEqual(backend.last_metadata["called_tool_names"], ["get_addresses"])
        self.assertEqual(backend.chat_calls, [])

    def test_out_of_scope_redirect_does_not_connect_to_mcp(self) -> None:
        backend = ScriptedSwiggyLLM([])

        reply = backend.reply("what is the capital of France?", conversation_id="test")

        self.assertEqual(reply, llm_mod.SWIGGY_REDIRECT)
        self.assertFalse(FakeClient.entered)
        self.assertTrue(backend.last_metadata["out_of_scope_redirect"])


if __name__ == "__main__":
    unittest.main()
