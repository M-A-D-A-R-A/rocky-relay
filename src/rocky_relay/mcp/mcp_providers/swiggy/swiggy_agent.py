from __future__ import annotations

from dataclasses import dataclass
import json
import re
import threading
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from rocky_relay.config import Config
from rocky_relay.mcp.mcp_setup.mcp_agent import (
    MCPAgentRuntime,
    ToolCallPlan,
    tool_result_is_error,
)
from rocky_relay.mcp.mcp_providers.swiggy.swiggy_client import SwiggyMCPClient


SWIGGY_SAFE_REFUSAL = (
    "I could not reach Swiggy tools for that. I will not make up results."
)
SWIGGY_REDIRECT = (
    "I can help with Swiggy food delivery, Instamart groceries, or Dineout bookings."
)

_SWIGGY_PENDING_LOCK = threading.Lock()
_SWIGGY_PENDING_CONTEXTS: dict[str, dict[str, Any]] = {}

_SWIGGY_INTENT_TERMS = {
    "address",
    "addresses",
    "book",
    "booking",
    "biryani",
    "breakfast",
    "burger",
    "cart",
    "checkout",
    "coupon",
    "coupons",
    "delivery",
    "dineout",
    "dinner",
    "dish",
    "food",
    "grocery",
    "groceries",
    "instamart",
    "lunch",
    "menu",
    "milk",
    "order",
    "orders",
    "pizza",
    "product",
    "products",
    "reservation",
    "restaurant",
    "restaurants",
    "restraunt",
    "restraunts",
    "swiggy",
    "table",
    "track",
    "tool",
}
_GEOCODE_CACHE_LOCK = threading.Lock()
_GEOCODE_CACHE: dict[tuple[str, str, str], tuple[float, float] | None] = {}
_GEOCODE_ACCEPTED_TYPES = {
    "administrative",
    "borough",
    "city",
    "city_district",
    "county",
    "municipality",
    "neighbourhood",
    "quarter",
    "state",
    "suburb",
    "town",
    "village",
}


@dataclass
class SwiggyProvider:
    config: Config
    name: str = "swiggy"
    backend_name: str = "ollama_swiggy"
    safe_refusal: str = SWIGGY_SAFE_REFUSAL
    redirect: str = SWIGGY_REDIRECT

    def create_client(self, config: Config) -> Any:
        return SwiggyMCPClient.from_config(config)

    def max_tool_rounds(self, config: Config) -> int:
        return config.swiggy_mcp_max_tool_rounds

    def history_turns(self, config: Config) -> int:
        return config.swiggy_mcp_history_turns

    def initial_metadata(self, *, model: str) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "mcp_provider": self.name,
            "model": model,
            "tool_attempt_count": 0,
            "called_tool_names": [],
            "tool_events": [],
            "no_tool_retry": False,
            "no_tool_refusal": False,
            "out_of_scope_redirect": False,
        }

    def is_request(self, text: str) -> bool:
        return _is_swiggy_request(text)

    def has_pending_context(self, state_key: str) -> bool:
        with _SWIGGY_PENDING_LOCK:
            return state_key in _SWIGGY_PENDING_CONTEXTS

    def system_prompt(
        self,
        *,
        max_reply_sentences: int,
        persona: str,
    ) -> str:
        style = (
            "Write short voice-friendly replies. Use at most "
            f"{max_reply_sentences} short sentences unless confirming an order."
        )
        if persona == "rocky_say_llm":
            style += (
                " Rocky will speak the final answer, so use simple concrete English "
                "and avoid polished assistant phrases."
            )
        return (
            "You are Rocky Relay with Swiggy MCP tools. Help the user order food, "
            "buy groceries from Instamart, or book tables through Dineout. "
            "For any Swiggy-related request, you must call at least one Swiggy tool "
            "before writing the final answer. Use the tools for real restaurants, "
            "menus, addresses, products, carts, prices, availability, orders, and "
            "bookings. Never invent Swiggy data, APIs, URLs, code, restaurant names, "
            "prices, menus, or addresses. If the user asks you to call a named tool, "
            "call that tool instead of explaining how to call it. If a tool fails or "
            "returns nothing, say that clearly and ask for a useful next step. Ask for "
            "one missing detail at a time. Fetch saved addresses before asking the user "
            "to say a full delivery address. Always confirm explicitly before checkout, "
            f"placing an order, or booking a table. {style}"
        )

    def pending_action(
        self,
        text: str,
        state_key: str,
        tool_names: list[str],
    ) -> dict[str, Any] | None:
        if "update_cart" not in tool_names:
            return None

        with _SWIGGY_PENDING_LOCK:
            pending = _SWIGGY_PENDING_CONTEXTS.get(state_key)

        if not pending or pending.get("kind") != "instamart_products":
            return None

        suggestions = pending.get("suggestions")
        if not isinstance(suggestions, list):
            return None

        selected = _match_product_suggestion(text, suggestions)
        if selected is None:
            return None
        if selected.get("available") is False:
            return {
                "kind": "instamart_unavailable",
                "suggestion": selected,
            }

        with _SWIGGY_PENDING_LOCK:
            _SWIGGY_PENDING_CONTEXTS.pop(state_key, None)

        return {
            "kind": "instamart_add",
            "address_id": pending.get("address_id"),
            "suggestion": selected,
            "can_read_cart": "get_cart" in tool_names,
        }

    async def handle_pending_action(
        self,
        action: dict[str, Any],
        runtime: MCPAgentRuntime,
        *,
        state_key: str,
        user_text: str,
    ) -> str:
        if action.get("kind") == "instamart_unavailable":
            suggestion = action.get("suggestion")
            label = _suggestion_label(suggestion) if isinstance(suggestion, dict) else "that item"
            reply = f"{label} is not available right now. Pick another number."
            runtime.remember(user_text, reply)
            return reply

        if action.get("kind") != "instamart_add":
            reply = "I need one more clear detail before I can continue."
            runtime.remember(user_text, reply)
            return reply

        suggestion = action.get("suggestion")
        address_id = action.get("address_id")
        if not isinstance(suggestion, dict) or not isinstance(address_id, str):
            reply = "I could not match that product selection."
            runtime.remember(user_text, reply)
            return reply

        spin_id = str(suggestion.get("spin_id", "")).strip()
        if not spin_id:
            reply = "I could not add that product because Swiggy did not return a product ID."
            runtime.remember(user_text, reply)
            return reply

        existing_items: list[dict[str, Any]] = []
        if action.get("can_read_cart"):
            cart_text = await runtime.call_tool("get_cart", {})
            if not tool_result_is_error(cart_text):
                existing_items = _extract_instamart_cart_items(cart_text)

        items = _merge_instamart_cart_items(existing_items, spin_id, quantity=1)
        result_text = await runtime.call_tool(
            "update_cart",
            {"selectedAddressId": address_id, "items": items},
        )
        runtime.metadata["suggestions"] = []

        label = _suggestion_label(suggestion)
        if tool_result_is_error(result_text):
            reply = "Swiggy returned an error while updating the Instamart cart."
        else:
            reply = f"Added {label} to your Instamart cart."

        runtime.remember(user_text, reply)
        return reply

    def pending_tool_call(
        self,
        text: str,
        state_key: str,
        tool_names: list[str],
    ) -> ToolCallPlan | None:
        if "search_products" not in tool_names:
            return None

        with _SWIGGY_PENDING_LOCK:
            pending = _SWIGGY_PENDING_CONTEXTS.get(state_key)

        if not pending or pending.get("kind") != "instamart_search":
            return None

        addresses = pending.get("addresses")
        if not isinstance(addresses, list):
            return None

        selected = _match_saved_address(text, addresses)
        if selected is None:
            return None

        address_id = selected.get("address_id")
        query = pending.get("query")
        if not isinstance(address_id, str) or not address_id:
            return None
        if not isinstance(query, str) or not query:
            return None

        with _SWIGGY_PENDING_LOCK:
            _SWIGGY_PENDING_CONTEXTS.pop(state_key, None)

        return ToolCallPlan(
            name="search_products",
            arguments={"addressId": address_id, "query": query, "offset": 0},
            route="pending_tool_call:instamart_address",
        )

    def planned_tool_call(self, text: str, tool_names: list[str]) -> ToolCallPlan | None:
        direct_tool_name = _direct_tool_request(text, tool_names)
        if direct_tool_name is not None:
            return ToolCallPlan(
                name=direct_tool_name,
                arguments={},
                route="planned_tool_call:direct_tool",
            )

        restaurant_arguments = _restaurant_search_arguments(text, self.config)
        if restaurant_arguments is not None and "search_restaurants_dineout" in tool_names:
            return ToolCallPlan(
                name="search_restaurants_dineout",
                arguments=restaurant_arguments,
                route="planned_tool_call:dineout_search",
            )

        instamart_arguments = _instamart_search_arguments(text)
        if instamart_arguments is not None:
            if "get_addresses" in tool_names:
                return ToolCallPlan(
                    name="get_addresses",
                    arguments={},
                    route="planned_tool_call:instamart_address_first",
                )
            if "search_products" in tool_names:
                return ToolCallPlan(
                    name="search_products",
                    arguments=instamart_arguments,
                    route="planned_tool_call:instamart_search",
                )

        return None

    def remember_tool_result(
        self,
        state_key: str,
        user_text: str,
        tool_name: str,
        arguments: dict[str, Any],
        result_text: str,
    ) -> None:
        if tool_name == "search_products":
            suggestions = _extract_product_suggestions(result_text)
            address_id = str(arguments.get("addressId") or "").strip()
            if suggestions and address_id:
                with _SWIGGY_PENDING_LOCK:
                    _SWIGGY_PENDING_CONTEXTS[state_key] = {
                        "kind": "instamart_products",
                        "address_id": address_id,
                        "suggestions": suggestions,
                    }
            return

        if tool_name != "get_addresses":
            return

        instamart_arguments = _instamart_search_arguments(user_text)
        if instamart_arguments is None:
            return

        addresses = _extract_saved_addresses(result_text)
        if not addresses:
            return

        with _SWIGGY_PENDING_LOCK:
            _SWIGGY_PENDING_CONTEXTS[state_key] = {
                "kind": "instamart_search",
                "query": instamart_arguments["query"],
                "addresses": addresses,
            }

    def metadata_for_tool_result(
        self,
        tool_name: str,
        result_text: str,
    ) -> dict[str, Any]:
        if tool_name != "search_products":
            return {}
        suggestions = _extract_product_suggestions(result_text)
        return {"suggestions": _public_suggestions(suggestions)}

    def summarize_tool_result(self, tool_name: str, result_text: str) -> str | None:
        if tool_result_is_error(result_text):
            return "Swiggy returned an error for that request. I will not make up results."

        if tool_name == "get_addresses":
            addresses = _extract_saved_addresses(result_text)
            if addresses:
                return "Which saved address would you like to use for delivery?"
            return "I called Swiggy, but I could not find saved delivery addresses."

        if tool_name == "search_products":
            suggestions = _extract_product_suggestions(result_text)
            if suggestions:
                visible = ", ".join(_suggestion_label(suggestion) for suggestion in suggestions[:3])
                if len(suggestions) > 3:
                    return f"I found Instamart products including {visible}. Which one should I add?"
                return f"I found Instamart products: {visible}. Which one should I add?"
            return "I called Instamart, but it did not return product names."

        if tool_name == "search_restaurants_dineout":
            names = _extract_names(result_text)
            if names:
                visible = ", ".join(names[:3])
                if len(names) > 3:
                    return f"I found restaurants in Swiggy Dineout, including {visible}."
                return f"I found restaurants in Swiggy Dineout: {visible}."
            return "I called Swiggy Dineout, but it did not return restaurant names."

        return None

    def fallback_reply(self) -> str:
        return "I checked Swiggy, but I need one more clear detail before I can continue."


def _is_swiggy_request(text: str) -> bool:
    normalized = text.lower()
    tokens = set(re.findall(r"[a-z_]+", normalized))
    if tokens & _SWIGGY_INTENT_TERMS:
        return True
    return any(term in normalized for term in ("get_", "search_", "food_", "dineout"))


def _direct_tool_request(text: str, tool_names: list[str]) -> str | None:
    normalized = text.lower()
    commandish = any(term in normalized for term in ("call", "run", "use", "execute", "tool"))
    if not commandish:
        return None
    for tool_name in sorted(tool_names, key=len, reverse=True):
        if tool_name.lower() in normalized:
            return tool_name
    return None


def _restaurant_search_arguments(text: str, config: Config) -> dict[str, Any] | None:
    normalized = text.lower()
    if not any(term in normalized for term in ("restaurant", "restaurants", "restraunt", "restraunts")):
        return None

    location_match = re.search(
        r"\b(?:in|near|around)\s+([a-z][a-z\s]+?)(?:\s+for\b|\s+with\b|\s+that\b|[.?!,]*$)",
        normalized,
    )
    if location_match:
        query = location_match.group(1).strip(" .?!,")
        if query:
            arguments: dict[str, Any] = {"query": query.title()}
            coordinates = _geocode_location(query, config)
            if coordinates is not None:
                latitude, longitude = coordinates
                arguments["query"] = "restaurants"
                arguments["latitude"] = latitude
                arguments["longitude"] = longitude
            return arguments
    return {"query": "restaurants"}


def _instamart_search_arguments(text: str) -> dict[str, Any] | None:
    normalized = text.lower()
    if not any(
        term in normalized
        for term in ("instamart", "grocery", "groceries", "product", "products", "milk", "bread", "eggs")
    ):
        return None
    if any(term in normalized for term in ("cart", "checkout", "order", "track", "clear")):
        return None

    query = normalized
    query = re.sub(r"\b(?:rocky|find|search|show|me|for|on|from|instamart|grocery|groceries)\b", " ", query)
    query = " ".join(re.findall(r"[a-z0-9]+", query)).strip()
    return {"query": query or "groceries"}


def _extract_saved_addresses(result_text: str) -> list[dict[str, Any]]:
    addresses: list[dict[str, Any]] = []
    for match in re.finditer(
        r"(?m)^\s*(\d+)\.\s+\[([^\]]+)\].*?\(ID:\s*([^)]+)\)",
        result_text,
    ):
        index = int(match.group(1))
        label = match.group(2).strip()
        address_id = match.group(3).strip()
        if label and address_id:
            addresses.append(
                {
                    "index": index,
                    "label": label,
                    "address_id": address_id,
                }
            )
    return addresses


def _match_saved_address(
    text: str,
    addresses: list[Any],
) -> dict[str, Any] | None:
    normalized = _normalize_selection_text(text)
    if not normalized:
        return addresses[0] if len(addresses) == 1 and isinstance(addresses[0], dict) else None

    tokens = set(normalized.split())
    for token, index in _ORDINAL_MATCHES.items():
        if token in tokens:
            return _entry_by_index(addresses, index)

    best: dict[str, Any] | None = None
    best_score = 0
    for address in addresses:
        if not isinstance(address, dict):
            continue
        label = str(address.get("label", ""))
        label_normalized = _normalize_selection_text(label)
        if not label_normalized:
            continue
        label_tokens = set(label_normalized.split())
        score = len(tokens & label_tokens)
        if label_normalized in normalized or normalized in label_normalized:
            score += 2
        if score > best_score:
            best = address
            best_score = score

    return best if best_score > 0 else None


def _match_product_suggestion(
    text: str,
    suggestions: list[Any],
) -> dict[str, Any] | None:
    normalized = _normalize_selection_text(text)
    tokens = set(normalized.split())
    for token, index in _ORDINAL_MATCHES.items():
        if token in tokens:
            return _entry_by_index(suggestions, index)

    best: dict[str, Any] | None = None
    best_score = 0
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            continue
        label = f"{suggestion.get('title', '')} {suggestion.get('quantity', '')}"
        label_normalized = _normalize_selection_text(label)
        if not label_normalized:
            continue
        label_tokens = set(label_normalized.split())
        score = len(tokens & label_tokens)
        if label_normalized in normalized:
            score += 2
        if score > best_score:
            best = suggestion
            best_score = score

    return best if best_score > 0 else None


_ORDINAL_MATCHES = {
    "1": 1,
    "one": 1,
    "first": 1,
    "2": 2,
    "two": 2,
    "second": 2,
    "3": 3,
    "three": 3,
    "third": 3,
    "4": 4,
    "four": 4,
    "fourth": 4,
    "5": 5,
    "five": 5,
    "fifth": 5,
    "6": 6,
    "six": 6,
    "sixth": 6,
    "7": 7,
    "seven": 7,
    "seventh": 7,
    "8": 8,
    "eight": 8,
    "eighth": 8,
    "9": 9,
    "nine": 9,
    "ninth": 9,
    "10": 10,
    "ten": 10,
    "tenth": 10,
}


def _entry_by_index(entries: list[Any], index: int) -> dict[str, Any] | None:
    for entry in entries:
        if isinstance(entry, dict) and entry.get("index") == index:
            return entry
    return None


def _normalize_selection_text(text: str) -> str:
    stop_words = {
        "use",
        "select",
        "choose",
        "my",
        "the",
        "address",
        "delivery",
        "location",
        "add",
        "suggestion",
        "item",
        "product",
        "cart",
        "to",
    }
    return " ".join(
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in stop_words
    )


def _geocode_location(location: str, config: Config) -> tuple[float, float] | None:
    normalized_location = _normalize_location(location)
    if not normalized_location or not config.geocoder_url.strip():
        return None

    cache_key = (
        normalized_location,
        config.geocoder_url,
        config.geocoder_countrycodes,
    )
    with _GEOCODE_CACHE_LOCK:
        if cache_key in _GEOCODE_CACHE:
            return _GEOCODE_CACHE[cache_key]

    result: tuple[float, float] | None = None
    for candidate in _location_candidates(normalized_location):
        result = _fetch_geocode(candidate, config)
        if result is not None:
            break

    with _GEOCODE_CACHE_LOCK:
        _GEOCODE_CACHE[cache_key] = result
    return result


def _normalize_location(location: str) -> str:
    return " ".join(re.findall(r"[a-z]+", location.lower()))


def _location_candidates(location: str) -> list[str]:
    candidates: list[str] = []
    pending = [location]
    while pending:
        candidate = pending.pop(0)
        if not candidate or candidate in candidates:
            continue
        candidates.append(candidate)

        transformed = _location_spelling_variants(candidate)
        for variant in transformed:
            if variant not in candidates and variant not in pending:
                pending.append(variant)
    return candidates


def _location_spelling_variants(location: str) -> list[str]:
    variants: list[str] = []
    words = location.split()

    nager_corrected = " ".join(
        f"{word[:-5]}nagar" if word.endswith("nager") else word
        for word in words
    )
    variants.append(nager_corrected)

    k_to_g = " ".join(
        f"g{word[1:]}" if word.startswith("k") and len(word) > 1 else word
        for word in words
    )
    variants.append(k_to_g)
    variants.append(location.replace("dinagar", "dhinagar"))

    return [variant for variant in variants if variant and variant != location]


def _fetch_geocode(location: str, config: Config) -> tuple[float, float] | None:
    params = {
        "q": f"{location}, India",
        "format": "jsonv2",
        "featureType": "settlement",
        "limit": "5",
    }
    countrycodes = config.geocoder_countrycodes.strip()
    if countrycodes:
        params["countrycodes"] = countrycodes

    url = f"{config.geocoder_url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": config.geocoder_user_agent},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.geocoder_timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None

    if not isinstance(data, list):
        return None
    for item in data:
        if not isinstance(item, dict):
            continue
        if not _is_usable_geocode_result(item):
            continue
        try:
            return float(item["lat"]), float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _is_usable_geocode_result(item: dict[str, Any]) -> bool:
    addresstype = str(item.get("addresstype", "")).lower()
    place_type = str(item.get("type", "")).lower()
    category = str(item.get("category", "")).lower()
    if addresstype in _GEOCODE_ACCEPTED_TYPES or place_type in _GEOCODE_ACCEPTED_TYPES:
        return True
    return category == "boundary"


def _extract_names(result_text: str) -> list[str]:
    names: list[str] = []
    decoded = result_text.encode("utf-8").decode("unicode_escape", errors="ignore")
    for candidate in (result_text, decoded):
        for match in re.finditer(r'"name"\s*:\s*"([^"]+)"', candidate):
            name = match.group(1).strip()
            if name and name not in names:
                names.append(name)
    return names


def _extract_product_suggestions(result_text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(result_text)
    except json.JSONDecodeError:
        return []

    products: Any = None
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, dict):
            products = inner.get("products")
        elif isinstance(inner, list):
            products = inner
    if not isinstance(products, list):
        return []

    suggestions: list[dict[str, Any]] = []
    seen_spin_ids: set[str] = set()
    for product in products:
        if not isinstance(product, dict):
            continue
        product_name = str(product.get("displayName") or product.get("name") or "").strip()
        variations = product.get("variations") or product.get("variants") or []
        if not isinstance(variations, list):
            variations = []
        for variation in variations:
            if not isinstance(variation, dict):
                continue
            spin_id = str(variation.get("spinId") or "").strip()
            if not spin_id or spin_id in seen_spin_ids:
                continue
            seen_spin_ids.add(spin_id)
            title = str(variation.get("displayName") or product_name).strip()
            quantity = str(variation.get("quantityDescription") or "").strip()
            suggestions.append(
                {
                    "index": len(suggestions) + 1,
                    "title": title,
                    "quantity": quantity,
                    "price": _format_price(variation.get("price")),
                    "available": bool(
                        variation.get("isInStockAndAvailable")
                        if "isInStockAndAvailable" in variation
                        else product.get("isAvail", True)
                    ),
                    "spin_id": spin_id,
                }
            )
    return suggestions


def _public_suggestions(suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public: list[dict[str, Any]] = []
    for suggestion in suggestions:
        subtitle_parts = [
            str(part).strip()
            for part in (suggestion.get("quantity"), suggestion.get("price"))
            if str(part or "").strip()
        ]
        public.append(
            {
                "number": suggestion.get("index"),
                "title": suggestion.get("title"),
                "subtitle": " - ".join(subtitle_parts),
                "price": suggestion.get("price"),
                "available": suggestion.get("available", True),
            }
        )
    return public


def _suggestion_label(suggestion: dict[str, Any]) -> str:
    title = str(suggestion.get("title") or "").strip()
    quantity = str(suggestion.get("quantity") or "").strip()
    if title and quantity:
        return f"{title} {quantity}"
    return title or "an item"


def _format_price(value: Any) -> str:
    price: Any = value
    if isinstance(value, dict):
        price = value.get("offerPrice")
        if price in (None, ""):
            price = value.get("mrp")
    if price in (None, ""):
        return ""
    try:
        amount = float(price)
    except (TypeError, ValueError):
        return str(price)
    if amount.is_integer():
        return f"Rs {int(amount)}"
    return f"Rs {amount:.2f}"


def _extract_instamart_cart_items(result_text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(result_text)
    except json.JSONDecodeError:
        return []

    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            spin_id = value.get("spinId")
            quantity = value.get("quantity")
            if isinstance(spin_id, str) and spin_id and spin_id not in seen:
                seen.add(spin_id)
                items.append({"spinId": spin_id, "quantity": _int_or_default(quantity, 1)})
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data)
    return items


def _merge_instamart_cart_items(
    items: list[dict[str, Any]],
    spin_id: str,
    *,
    quantity: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    found = False
    for item in items:
        item_spin_id = str(item.get("spinId") or "").strip()
        if not item_spin_id:
            continue
        item_quantity = _int_or_default(item.get("quantity"), 1)
        if item_spin_id == spin_id:
            item_quantity += quantity
            found = True
        merged.append({"spinId": item_spin_id, "quantity": item_quantity})
    if not found:
        merged.append({"spinId": spin_id, "quantity": quantity})
    return merged


def _int_or_default(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)
