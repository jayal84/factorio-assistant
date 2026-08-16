"""Factorio Assistant Home Assistant services."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector

from .const import CHAT_EVENT, DOMAIN
from .coordinator import FactorioAssistantCoordinator

_SERVICE_HANDLERS: dict[str, Callable[[HomeAssistant, FactorioAssistantCoordinator, ServiceCall], Awaitable[dict[str, Any]]]] = {}


def _default_config_entry_id(hass: HomeAssistant) -> str:
    entries = list(hass.data.get(DOMAIN, {}).keys())
    if len(entries) == 1:
        return entries[0]
    if not entries:
        raise vol.Invalid("Factorio Assistant is not configured")
    raise vol.Invalid("config_entry_id is required when multiple Factorio Assistant entries exist")


def _coordinator(hass: HomeAssistant, config_entry_id: str) -> FactorioAssistantCoordinator:
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise vol.Invalid("Factorio Assistant is not configured")
    coordinator = entries.get(config_entry_id)
    if coordinator is None:
        raise vol.Invalid("Unknown Factorio Assistant config entry")
    return coordinator


def _record_chat_event(coordinator: FactorioAssistantCoordinator, message: str) -> None:
    event_data: dict[str, Any] = {
        "event": "console_chat",
        "event_type": "console_chat",
        "player": "server",
        "player_index": None,
        "message": message,
        "surface": "unknown",
        "tick": None,
    }

    if isinstance(coordinator.data, dict):
        chat_events = coordinator.data.setdefault("chat_events", {"events": []})
        if isinstance(chat_events, dict):
            events = chat_events.setdefault("events", [])
            if isinstance(events, list):
                events.append(event_data)
                if len(events) > 50:
                    del events[:-50]

    coordinator.hass.bus.async_fire(CHAT_EVENT, event_data)


def _area(data: dict[str, Any]) -> dict[str, dict[str, float]]:
    center_x = float(data.get("center_x", 0))
    center_y = float(data.get("center_y", 0))
    half_size = float(data.get("area_size", 64))
    return {
        "left_top": {"x": center_x - half_size, "y": center_y - half_size},
        "right_bottom": {"x": center_x + half_size, "y": center_y + half_size},
    }


def _json_list(value: Any, item_type: type) -> list[Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as err:
            raise vol.Invalid("Expected a JSON array") from err
    if not isinstance(value, list) or not all(isinstance(item, item_type) for item in value):
        raise vol.Invalid(f"Expected a list of {item_type.__name__} values")
    return value


def _schema(fields: dict[Any, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional("config_entry_id"): selector.ConfigEntrySelector(
                {"integration": DOMAIN}
            ),
            **fields,
        }
    )


def _service_schema(*, area: bool = False, limit: bool = False) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Optional("surface", default="nauvis"): cv.string,
    }
    if area:
        fields.update({
            vol.Optional("center_x", default=0): vol.Coerce(float),
            vol.Optional("center_y", default=0): vol.Coerce(float),
            vol.Optional("area_size", default=64): vol.All(vol.Coerce(float), vol.Range(min=1, max=256)),
        })
    if limit:
        fields[vol.Optional("limit", default=500)] = vol.All(vol.Coerce(int), vol.Range(min=1, max=5000))
    return _schema(fields)


async def _catalog(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await coordinator.async_request_get("/api/catalog", {
        "query": str(call.data["query"]),
        "kind": str(call.data["search_type"]),
        "limit": int(call.data["limit"]),
        "offset": int(call.data["offset"]),
    })


async def _catalog_entry(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await coordinator.async_request_get("/api/catalog/entry", {
        "name": str(call.data["name"]),
        "kind": str(call.data.get("kind", "")),
        "detail": str(call.data.get("detail", "full")),
    })


async def _catalog_production(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await coordinator.async_request("/api/catalog/production", {
        "items": call.data["items"],
        "known_recipes": call.data.get("known_recipes", []),
    })


async def _list_mods(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    """Return installed Factorio mods and their enabled state."""
    status = await coordinator.async_request_get("/api/status", {})
    storage = status.get("storage", {})
    mods = storage.get("mods", []) if isinstance(storage, dict) else []
    if not isinstance(mods, list):
        mods = []
    return {
        "mods": mods,
        "count": len(mods),
        "enabled_count": sum(1 for mod in mods if isinstance(mod, dict) and mod.get("enabled", False)),
        "disabled_count": sum(1 for mod in mods if isinstance(mod, dict) and not mod.get("enabled", False)),
    }


async def _query_status(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await coordinator.async_request_get("/api/status", {})


async def _query_world(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await coordinator.async_request_get("/api/world", {})


async def _query_research(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await coordinator.async_request_get("/api/research", {})


async def _query_events(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await coordinator.async_request_get("/api/telemetry/events", {
        "limit": int(call.data["limit"]),
        "event": str(call.data["event"]),
    })


async def _query_player_data(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    world = await coordinator.async_request_get("/api/world", {})
    players = world.get("players", [])
    if isinstance(players, dict):
        players = [{"name": name, **details} for name, details in players.items() if isinstance(details, dict)]
    if not isinstance(players, list):
        players = []
    player_name = str(call.data["player"]).strip()
    if player_name:
        players = [player for player in players if isinstance(player, dict) and str(player.get("name", "")) == player_name]
    return {"players": players, "count": len(players), "requested_player": player_name or None}


async def _query_resource_monitor_list(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    world = await coordinator.async_request_get("/api/world", {})
    surfaces = world.get("surfaces", [])
    if not isinstance(surfaces, list):
        surfaces = []
    requested_surface = str(call.data["surface"]).strip()
    resources: list[dict[str, Any]] = []
    for surface in surfaces:
        if not isinstance(surface, dict):
            continue
        surface_name = str(surface.get("name", ""))
        if requested_surface and surface_name != requested_surface:
            continue
        for resource in surface.get("pinned_resources", []) or []:
            if isinstance(resource, dict):
                resources.append({"surface": surface_name, **resource})
    return {"resources": resources, "count": len(resources), "surface": requested_surface or None}


async def _summarize_aai_fleet(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    world = await coordinator.async_request_get("/api/world", {})
    counts = world.get("vehicle_counts", {})
    if not isinstance(counts, dict):
        counts = {}
    kinds = counts.get("kinds", {})
    if not isinstance(kinds, dict):
        kinds = {}
    surfaces = counts.get("surfaces", {})
    if not isinstance(surfaces, dict):
        surfaces = {}

    active_kinds = [
        f"{int(value)} {name.replace('_', ' ')}"
        for name, value in sorted(kinds.items(), key=lambda item: (-int(item[1] or 0), str(item[0])))
        if int(value or 0) > 0
    ]
    surface_summary = [
        f"{name}: {int(details.get('matched', 0) or 0)} matched"
        for name, details in sorted(surfaces.items(), key=lambda item: str(item[0]))
        if isinstance(details, dict) and int(details.get("total", 0) or 0) > 0
    ]
    summary_parts = [
        f"{int(counts.get('matched', 0) or 0)} matched AAI vehicles",
        f"{int(counts.get('total', 0) or 0)} total vehicles",
    ]
    if active_kinds:
        summary_parts.append("kinds: " + ", ".join(active_kinds))
    if surface_summary:
        summary_parts.append("surfaces: " + "; ".join(surface_summary))
    return {
        "summary": ". ".join(summary_parts) if summary_parts else "No AAI vehicle telemetry reported yet.",
        "total": int(counts.get("total", 0) or 0),
        "matched": int(counts.get("matched", 0) or 0),
        "kinds": kinds,
        "surfaces": surfaces,
    }


async def _summarize_ltn(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    world = await coordinator.async_request_get("/api/world", {})
    ltn = world.get("ltn", {})
    if not isinstance(ltn, dict):
        ltn = {}
    trains = ltn.get("trains", [])
    if not isinstance(trains, list):
        trains = []
    surfaces = ltn.get("surfaces", {})
    if not isinstance(surfaces, dict):
        surfaces = {}

    if not ltn.get("installed", False):
        return {"summary": "LTN is not installed.", "installed": False, "train_count": 0, "scheduled_train_count": 0, "manual_train_count": 0, "trains": [], "surfaces": {}}

    surface_summary = [
        f"{name}: {int(details.get('train_count', 0) or 0)} trains"
        for name, details in sorted(surfaces.items(), key=lambda item: str(item[0]))
        if isinstance(details, dict) and int(details.get("train_count", 0) or 0) > 0
    ]
    summary = (
        f"LTN is installed with {int(ltn.get('train_count', 0) or 0)} trains total, "
        f"{int(ltn.get('scheduled_train_count', 0) or 0)} scheduled, "
        f"and {int(ltn.get('manual_train_count', 0) or 0)} manual."
    )
    if surface_summary:
        summary += " Surfaces: " + "; ".join(surface_summary)
    return {
        "summary": summary,
        "installed": bool(ltn.get("installed", False)),
        "train_count": int(ltn.get("train_count", 0) or 0),
        "scheduled_train_count": int(ltn.get("scheduled_train_count", 0) or 0),
        "manual_train_count": int(ltn.get("manual_train_count", 0) or 0),
        "trains": trains,
        "surfaces": surfaces,
    }


async def _inspect(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await coordinator.async_request("/api/factory/inspect", {
        "surface": call.data["surface"], "area": _area(call.data), "limit": call.data["limit"]
    })


async def _map(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await coordinator.async_request("/api/factory/map", {
        "surface": call.data["surface"], "area": _area(call.data),
        "layers": {"entities": call.data["include_entities"], "resources": call.data["include_resources"], "tiles": call.data["include_tiles"]},
        "limit": call.data["limit"],
    })


async def _production(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await coordinator.async_request("/api/factory/production", {
        "surface": call.data["surface"], "items": call.data["items"]
    })



async def _dispatch_aai_vehicle(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall, action: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": action,
        "unit_kind": str(call.data.get("unit_kind", "any")),
    }
    if call.data.get("player"):
        payload["player_name"] = str(call.data["player"])
    if call.data.get("surface"):
        payload["surface"] = str(call.data["surface"])
    if call.data.get("center_x") is not None:
        payload["center_x"] = float(call.data["center_x"])
    if call.data.get("center_y") is not None:
        payload["center_y"] = float(call.data["center_y"])
    if call.data.get("area_size") is not None:
        payload["area_size"] = float(call.data["area_size"])
    return await coordinator.async_call_mod_result("aai_dispatch", json.dumps(payload, ensure_ascii=False))


async def _follow_aai_vehicle(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await _dispatch_aai_vehicle(hass, coordinator, call, "follow_player")


async def _drive_aai_vehicle(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await _dispatch_aai_vehicle(hass, coordinator, call, "go_to_position")


async def _mine_aai_vehicle(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await _dispatch_aai_vehicle(hass, coordinator, call, "mine_area")


async def _dispatch_ltn_command(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    payload: dict[str, Any] = {"action": str(call.data["action"])}
    for key in ("name", "train_id", "old_train_id", "new_train_id", "schedule_index"):
        value = call.data.get(key)
        if value not in (None, ""):
            payload[key] = value
    return await coordinator.async_call_mod_result("ltn_command", json.dumps(payload, ensure_ascii=False))


async def _plan(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await coordinator.async_request("/api/factory/plan", {
        "surface": call.data["surface"], "goal": call.data["goal"], "area": _area(call.data), "items": call.data["items"]
    })


async def _build(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await coordinator.async_request("/api/factory/build", {
        "surface": call.data["surface"], "entities": call.data["entities"],
        "real": call.data["real"], "dry_run": call.data["dry_run"],
    })


async def _give_items(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await coordinator.async_request("/api/factory/helper", {
        "player": call.data["player"], "items": call.data["items"]
    })


async def _demolish(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    return await coordinator.async_request("/api/factory/demolish", {
        "surface": call.data["surface"], "area": _area(call.data), "limit": call.data["limit"],
        "names": call.data["names"], "resources": call.data["include_resources"], "real": call.data["real"],
    })


async def _control(hass: HomeAssistant, coordinator: FactorioAssistantCoordinator, call: ServiceCall) -> dict[str, Any]:
    data = call.data
    service = call.service
    if service == "set_pause":
        return await coordinator.async_call_mod_result("set_pause", data["paused"])
    if service == "set_daylight":
        return await coordinator.async_call_mod_result("set_daylight", data["enabled"])
    if service == "set_daytime":
        return await coordinator.async_call_mod_result("set_daytime", data["value"])
    if service == "set_game_speed":
        return await coordinator.async_call_mod_result("set_game_speed", data["speed"])
    if service == "set_map_setting":
        return await coordinator.async_call_mod_result("set_map_setting", data["setting"], data["enabled"])
    if service == "set_day_night_cycle":
        return await coordinator.async_call_mod_result("set_day_night_cycle", data["enabled"])
    if service == "save_game":
        return await coordinator.async_call_mod_result("save_game")
    if service == "send_chat":
        result = await coordinator.async_request(
            "/api/rcon",
            {"command": f"/silent-command game.print({json.dumps(str(data['message']))})"},
        )
        _record_chat_event(coordinator, str(data["message"]))
        return result
    return await coordinator.async_call_mod_result("clear_revealed_enemies")


_SERVICE_HANDLERS.update({
    "search_catalog": _catalog,
    "get_catalog_entry": _catalog_entry,
    "get_catalog_production": _catalog_production,
    "list_mods": _list_mods,
    "get_status": _query_status,
    "get_world": _query_world,
    "get_research": _query_research,
    "get_events": _query_events,
    "get_player_data": _query_player_data,
    "get_resource_monitor_list": _query_resource_monitor_list,
    "get_aai_vehicle_summary": _summarize_aai_fleet,
    "get_ltn_summary": _summarize_ltn,
    "inspect_area": _inspect,
    "inspect_map": _map,
    "get_production": _production,
    "plan_factory": _plan,
    "build_factory": _build,
    "give_items": _give_items,
    "demolish_area": _demolish,
    "follow_aai_vehicle": _follow_aai_vehicle,
    "drive_aai_vehicle": _drive_aai_vehicle,
    "mine_aai_vehicle": _mine_aai_vehicle,
    "dispatch_ltn_command": _dispatch_ltn_command,
    "set_pause": _control,
    "set_daylight": _control,
    "set_daytime": _control,
    "set_game_speed": _control,
    "set_map_setting": _control,
    "set_day_night_cycle": _control,
    "save_game": _control,
    "send_chat": _control,
    "clear_revealed_enemies": _control,
})


async def _handle(call: ServiceCall) -> dict[str, Any]:
    """Dispatch a Home Assistant service call."""
    hass = call.hass
    config_entry_id = str(call.data.get("config_entry_id") or _default_config_entry_id(hass))
    coordinator = _coordinator(hass, config_entry_id)
    handler = _SERVICE_HANDLERS[call.service]
    return await handler(hass, coordinator, call)


SERVICE_SCHEMAS: dict[str, vol.Schema] = {
    "search_catalog": _schema({vol.Required("query"): cv.string, vol.Optional("search_type", default="all"): cv.string, vol.Optional("limit", default=25): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)), vol.Optional("offset", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=10000))}),
    "get_catalog_entry": _schema({vol.Required("name"): cv.string, vol.Optional("kind", default=""): cv.string, vol.Optional("detail", default="full"): cv.string}),
    "get_catalog_production": _schema({vol.Required("items"): vol.All(lambda value: _json_list(value, dict), vol.Length(min=1, max=20)), vol.Optional("known_recipes", default=[]): vol.All(lambda value: _json_list(value, str), vol.Length(max=50))}),
    "list_mods": _schema({}),
    "get_status": _schema({}),
    "get_world": _schema({}),
    "get_research": _schema({}),
    "get_events": _schema({vol.Optional("limit", default=20): vol.All(vol.Coerce(int), vol.Range(min=1, max=200)), vol.Optional("event", default=""): cv.string}),
    "get_player_data": _schema({vol.Optional("player", default=""): cv.string}),
    "get_resource_monitor_list": _schema({vol.Optional("surface", default=""): cv.string}),
    "get_aai_vehicle_summary": _schema({}),
    "get_ltn_summary": _schema({}),
    "inspect_area": _service_schema(area=True, limit=True),
    "inspect_map": _schema({**_service_schema(area=True, limit=True).schema, vol.Optional("include_entities", default=True): cv.boolean, vol.Optional("include_resources", default=True): cv.boolean, vol.Optional("include_tiles", default=False): cv.boolean}),
    "get_production": _schema({vol.Optional("surface", default="nauvis"): cv.string, vol.Required("items"): vol.All(lambda value: _json_list(value, str), vol.Length(min=1, max=50))}),
    "plan_factory": _schema({**_service_schema(area=True).schema, vol.Required("goal"): vol.All(cv.string, vol.Length(min=1, max=512)), vol.Optional("items", default=[]): vol.All(lambda value: _json_list(value, str), vol.Length(max=20))}),
    "build_factory": _schema({vol.Optional("surface", default="nauvis"): cv.string, vol.Required("entities"): vol.All(lambda value: _json_list(value, dict), vol.Length(min=1, max=100)), vol.Optional("real", default=False): cv.boolean, vol.Optional("dry_run", default=False): cv.boolean}),
    "give_items": _schema({vol.Required("player"): cv.string, vol.Required("items"): vol.All(lambda value: _json_list(value, dict), vol.Length(min=1, max=50))}),
    "demolish_area": _schema({**_service_schema(area=True, limit=True).schema, vol.Optional("names", default=[]): vol.All(lambda value: _json_list(value, str), vol.Length(max=50)), vol.Optional("include_resources", default=False): cv.boolean, vol.Optional("real", default=False): cv.boolean}),
    "follow_aai_vehicle": _schema({vol.Required("player"): cv.string, vol.Optional("unit_kind", default="any"): vol.In(["any", "miner", "hauler", "warden", "chaingunner", "flame_tank", "flame_tumbler", "ironclad", "laser_tank"]), vol.Optional("surface", default=""): cv.string}),
    "drive_aai_vehicle": _schema({vol.Optional("unit_kind", default="any"): vol.In(["any", "miner", "hauler", "warden", "chaingunner", "flame_tank", "flame_tumbler", "ironclad", "laser_tank"]), vol.Optional("surface", default=""): cv.string, vol.Optional("center_x", default=0.0): vol.Coerce(float), vol.Optional("center_y", default=0.0): vol.Coerce(float)}),
    "mine_aai_vehicle": _schema({vol.Optional("unit_kind", default="miner"): vol.In(["any", "miner", "hauler", "warden", "chaingunner", "flame_tank", "flame_tumbler", "ironclad", "laser_tank"]), vol.Optional("surface", default=""): cv.string, vol.Optional("center_x", default=0.0): vol.Coerce(float), vol.Optional("center_y", default=0.0): vol.Coerce(float), vol.Optional("area_size", default=32.0): vol.Coerce(float)}),
    "dispatch_ltn_command": _schema({vol.Required("action"): vol.In(["clear_all_surface_connections", "exclude_from_fuel_schedule", "get_or_create_next_temp_stop", "get_next_logistic_stop", "reassign_delivery"]), vol.Optional("name", default=""): cv.string, vol.Optional("train_id", default=0): vol.Coerce(int), vol.Optional("old_train_id", default=0): vol.Coerce(int), vol.Optional("new_train_id", default=0): vol.Coerce(int), vol.Optional("schedule_index", default=0): vol.Coerce(int)}),
    "set_pause": _schema({vol.Required("paused"): cv.boolean}),
    "set_daylight": _schema({vol.Required("enabled"): cv.boolean}),
    "set_daytime": _schema({vol.Required("value"): vol.All(vol.Coerce(float), vol.Range(min=0, max=1))}),
    "set_game_speed": _schema({vol.Required("speed"): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10))}),
    "set_map_setting": _schema({vol.Required("setting"): vol.In(["enemy_evolution", "pollution"]), vol.Required("enabled"): cv.boolean}),
    "set_day_night_cycle": _schema({vol.Required("enabled"): cv.boolean}),
    "save_game": _schema({}),
    "send_chat": _schema({vol.Required("message"): vol.All(cv.string, vol.Length(min=1, max=4096))}),
    "clear_revealed_enemies": _schema({}),
}


def async_register_services(hass: HomeAssistant) -> None:
    if hass.data.get(f"{DOMAIN}_services_registered"):
        return
    for name, schema in SERVICE_SCHEMAS.items():
        hass.services.async_register(DOMAIN, name, _handle, schema=schema, supports_response=SupportsResponse.OPTIONAL)
    hass.data[f"{DOMAIN}_services_registered"] = True


def async_unregister_services(hass: HomeAssistant) -> None:
    if not hass.data.pop(f"{DOMAIN}_services_registered", False):
        return
    for name in SERVICE_SCHEMAS:
        hass.services.async_remove(DOMAIN, name)
