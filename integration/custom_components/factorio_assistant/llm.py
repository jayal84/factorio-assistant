"""LLM tools for Factorio Assistant."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.llm import LLMTools, LLM_API_ASSIST
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.helpers.llm import LLMContext, ToolInput
from homeassistant.util.json import JsonObjectType

from .const import DOMAIN
from .services import SERVICE_SCHEMAS


def _llm_schema(fields: dict[object, object]) -> vol.Schema:
    return vol.Schema(fields)


LLM_SERVICE_SCHEMAS: dict[str, vol.Schema] = {
    "search_catalog": _llm_schema(
        {
            vol.Optional("query"): str,
            vol.Optional("search_type", default="all"): str,
            vol.Optional("limit", default=25): int,
            vol.Optional("offset", default=0): int,
        }
    ),
    "get_catalog_entry": _llm_schema(
        {
            vol.Required("name"): str,
            vol.Optional("kind", default=""): str,
            vol.Optional("detail", default="full"): str,
        }
    ),
    "get_catalog_production": _llm_schema(
        {
            vol.Required("items"): [
                {
                    vol.Required("name"): str,
                    vol.Optional("rate", default=1.0): float,
                }
            ],
            vol.Optional("known_recipes", default=[]): [str],
        }
    ),
    "list_mods": _llm_schema({}),
    "get_status": _llm_schema({}),
    "get_world": _llm_schema({}),
    "get_research": _llm_schema({}),
    "get_events": _llm_schema(
        {
            vol.Optional("limit", default=20): int,
            vol.Optional("event", default=""): str,
        }
    ),
    "get_player_data": _llm_schema({vol.Optional("player", default=""): str}),
    "get_resource_monitor_list": _llm_schema({vol.Optional("surface", default=""): str}),
    "get_aai_vehicle_summary": _llm_schema({}),
    "get_ltn_summary": _llm_schema({}),
    "inspect_area": _llm_schema(
        {
            vol.Optional("surface", default="nauvis"): str,
            vol.Optional("center_x", default=0.0): float,
            vol.Optional("center_y", default=0.0): float,
            vol.Optional("area_size", default=64.0): float,
            vol.Optional("limit", default=500): int,
        }
    ),
    "inspect_map": _llm_schema(
        {
            vol.Optional("surface", default="nauvis"): str,
            vol.Optional("center_x", default=0.0): float,
            vol.Optional("center_y", default=0.0): float,
            vol.Optional("area_size", default=64.0): float,
            vol.Optional("limit", default=500): int,
            vol.Optional("include_entities", default=True): bool,
            vol.Optional("include_resources", default=True): bool,
            vol.Optional("include_tiles", default=False): bool,
        }
    ),
    "get_production": _llm_schema(
        {
            vol.Optional("surface", default="nauvis"): str,
            vol.Required("items"): [str],
        }
    ),
    "plan_factory": _llm_schema(
        {
            vol.Optional("surface", default="nauvis"): str,
            vol.Optional("center_x", default=0.0): float,
            vol.Optional("center_y", default=0.0): float,
            vol.Optional("area_size", default=64.0): float,
            vol.Required("goal"): str,
            vol.Optional("items", default=[]): [str],
        }
    ),
    "build_factory": _llm_schema(
        {
            vol.Optional("surface", default="nauvis"): str,
            vol.Required("entities"): [
                {
                    vol.Required("name"): str,
                    vol.Required("position"): {
                        vol.Required("x"): float,
                        vol.Required("y"): float,
                    },
                    vol.Optional("direction", default=0): int,
                }
            ],
            vol.Optional("real", default=False): bool,
            vol.Optional("dry_run", default=False): bool,
        }
    ),
    "give_items": _llm_schema(
        {
            vol.Required("player"): str,
            vol.Required("items"): [dict],
        }
    ),
    "dispatch_ltn_command": _llm_schema(
        {
            vol.Required("action"): vol.In(["clear_all_surface_connections", "exclude_from_fuel_schedule", "get_or_create_next_temp_stop", "get_next_logistic_stop", "reassign_delivery"]),
            vol.Optional("name", default=""): str,
            vol.Optional("train_id", default=0): int,
            vol.Optional("old_train_id", default=0): int,
            vol.Optional("new_train_id", default=0): int,
            vol.Optional("schedule_index", default=0): int,
        }
    ),
    "demolish_area": _llm_schema(
        {
            vol.Optional("surface", default="nauvis"): str,
            vol.Optional("center_x", default=0.0): float,
            vol.Optional("center_y", default=0.0): float,
            vol.Optional("area_size", default=64.0): float,
            vol.Optional("limit", default=500): int,
            vol.Optional("names", default=[]): [str],
            vol.Optional("include_resources", default=False): bool,
            vol.Optional("real", default=False): bool,
        }
    ),
    "set_pause": _llm_schema({vol.Required("paused"): bool}),
    "set_daylight": _llm_schema({vol.Required("enabled"): bool}),
    "set_daytime": _llm_schema({vol.Required("value"): float}),
    "set_game_speed": _llm_schema({vol.Required("speed"): float}),
    "set_map_setting": _llm_schema({vol.Required("setting"): str, vol.Required("enabled"): bool}),
    "set_day_night_cycle": _llm_schema({vol.Required("enabled"): bool}),
    "save_game": _llm_schema({}),
    "send_chat": _llm_schema({vol.Required("message"): str}),
    "clear_revealed_enemies": _llm_schema({}),
}


class FactorioServiceTool(llm.Tool):
    """Expose one Factorio Assistant service as an LLM tool."""

    def __init__(self, name: str, description: str, service: str) -> None:
        self.name = name
        self.description = description
        self.service = service
        self.parameters = LLM_SERVICE_SCHEMAS.get(service, SERVICE_SCHEMAS[service])

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: ToolInput,
        llm_context: LLMContext,
    ) -> JsonObjectType:
        """Call the existing service and return its structured response."""
        service_data = dict(tool_input.tool_args)
        if "config_entry_id" not in service_data:
            entries = hass.data.get(DOMAIN, {})
            if entries:
                service_data["config_entry_id"] = next(iter(entries))
        try:
            response = await hass.services.async_call(
                DOMAIN,
                self.service,
                service_data,
                blocking=True,
                return_response=True,
                context=llm_context.context,
            )
        except Exception as err:
            raise HomeAssistantError(
                f"Factorio Assistant action {self.service} failed: {err}"
            ) from err
        if not isinstance(response, dict):
            return {"result": response}
        return response


def _tools() -> list[llm.Tool]:
    """Build the tools offered to the conversation agent."""
    definitions = [
        ("GetFactorioStatus", "Get current Factorio server, bridge, storage, and diagnostic status.", "get_status"),
        ("GetFactorioWorld", "Get the current Factorio world, players, surfaces, research, resources, and Signal Monitors.", "get_world"),
        ("GetFactorioResearch", "Get current Factorio research, queue, researched technologies, and progress.", "get_research"),
        ("GetFactorioEvents", "Get recent structured Factorio telemetry events, optionally filtered by event type.", "get_events"),
        ("GetFactorioPlayerData", "Get detailed telemetry for one Factorio player or all players.", "get_player_data"),
        ("GetFactorioResources", "Get pinned Factorio resource monitor sites, amounts, rates, and depletion estimates.", "get_resource_monitor_list"),
        ("GetAAIVehicleSummary", "Get a compact summary of AAI vehicle counts by kind and surface.", "get_aai_vehicle_summary"),
        ("GetLTNSummary", "Get a compact summary of Logistic Train Network counts and surfaces.", "get_ltn_summary"),
        ("SearchFactorioCatalog", "Search the Factorio prototype catalog for items, entities, recipes, or technologies.", "search_catalog"),
        ("GetFactorioCatalogEntry", "Get one Factorio catalog entry by name and kind, with a compact summary or full data.", "get_catalog_entry"),
        ("PlanFactorioProduction", "Plan production ratios for requested Factorio items using catalog recipes and machines.", "get_catalog_production"),
        ("ListFactorioMods", "List installed Factorio mods and whether each mod is enabled.", "list_mods"),
        ("InspectFactorioArea", "Inspect Factorio entities and resources in a specified area.", "inspect_area"),
        ("InspectFactorioMap", "Inspect Factorio map layers in a specified area.", "inspect_map"),
        ("GetFactorioProduction", "Get Factorio production statistics for selected items.", "get_production"),
        ("PlanFactorioFactory", "Generate a Factorio factory plan for a requested goal. This does not build anything.", "plan_factory"),
        ("BuildFactorioFactory", "Validate or place explicit Factorio entities in an area.", "build_factory"),
        ("GiveFactorioItems", "Give specific items to a Factorio player.", "give_items"),
        ("ControlLTNNetwork", "Run a limited Logistic Train Network control action such as clearing connections, reassigning deliveries, or excluding locomotives from fuel schedules.", "dispatch_ltn_command"),
        ("DemolishFactorioArea", "Inspect or demolish entities in a Factorio area.", "demolish_area"),
        ("SetFactorioPause", "Pause or resume the Factorio game when explicitly requested.", "set_pause"),
        ("SetFactorioGameSpeed", "Change the Factorio game speed when explicitly requested.", "set_game_speed"),
        ("SetFactorioDaylight", "Change permanent Factorio daylight when explicitly requested.", "set_daylight"),
        ("SetFactorioDaytime", "Set the Factorio daytime position when explicitly requested.", "set_daytime"),
        ("SetFactorioMapSetting", "Enable or disable Factorio pollution or enemy evolution when explicitly requested.", "set_map_setting"),
        ("SetFactorioDayNightCycle", "Enable or disable the Factorio day-night cycle when explicitly requested.", "set_day_night_cycle"),
        ("SaveFactorioGame", "Save the active Factorio game when explicitly requested.", "save_game"),
        ("SendFactorioChat", "Send a chat message to Factorio players when explicitly requested.", "send_chat"),
        ("ClearFactorioRevealedEnemies", "Clear revealed enemy units when explicitly requested.", "clear_revealed_enemies"),
    ]
    return [FactorioServiceTool(name, description, service) for name, description, service in definitions]


@callback
def async_get_tools(
    hass: HomeAssistant,
    llm_context: LLMContext,
    api_id: str,
) -> LLMTools | None:
    """Return Factorio tools for Home Assistant's LLM APIs."""
    if api_id != LLM_API_ASSIST:
        return None

    return LLMTools(
        tools=_tools(),
        prompt=(
            "Factorio Assistant tools provide live Factorio data and controls. "
            "Use read-only tools to answer questions about the factory. "
            "Only use control, build, chat, save, or destructive tools when the user "
            "clearly requested that action. Planning does not build anything."
        ),
    )
