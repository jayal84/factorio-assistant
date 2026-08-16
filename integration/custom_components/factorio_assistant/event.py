"""Factorio Assistant event entities."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, FACTORIO_MANUFACTURER, SERVER_MODEL
from .coordinator import FactorioAssistantCoordinator


def _latest_event(data: dict[str, Any]) -> dict[str, Any] | None:
    events = data.get("events", {}).get("events", [])
    if not isinstance(events, list):
        return None
    for event in reversed(events):
        if isinstance(event, dict) and isinstance(event.get("event"), str):
            return event
    return None


def _event_identity(event: dict[str, Any]) -> str:
    return "|".join(
        str(event.get(field, ""))
        for field in ("tick", "event", "player_index", "player", "surface", "message", "technology", "entity")
    )


class FactorioEventStream(CoordinatorEntity[FactorioAssistantCoordinator], EventEntity):
    """Expose the most recent structured Factorio telemetry event."""

    _attr_event_types = [
        "surface_attack",
        "player_joined",
        "player_left",
        "player_died",
        "player_changed_surface",
        "player_respawned",
        "console_chat",
        "research_finished",
        "rocket_launched",
        "entity_died",
        "state_snapshot",
        "combinator_snapshot",
        "combinator_reader_changed",
    ]

    def __init__(self, coordinator: FactorioAssistantCoordinator) -> None:
        super().__init__(coordinator)
        prefix = coordinator.entry.entry_id
        self._attr_unique_id = f"{prefix}_latest_event"
        self._attr_name = "Factorio Events"
        self._attr_icon = "mdi:playlist-star"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{prefix}_server")},
            "name": "Factorio",
            "manufacturer": FACTORIO_MANUFACTURER,
            "model": SERVER_MODEL,
            "via_device": (DOMAIN, prefix),
        }
        self._last_event_identity: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        latest_event = _latest_event(self.coordinator.data)
        if latest_event is not None:
            self._last_event_identity = _event_identity(latest_event)
            self._trigger_event(
                str(latest_event.get("event")),
                {
                    key: value for key, value in latest_event.items() if key != "event"
                },
            )
            self.async_write_ha_state()
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))

    @callback
    def _handle_coordinator_update(self) -> None:
        event = _latest_event(self.coordinator.data)
        if not event:
            return
        identity = _event_identity(event)
        if identity == self._last_event_identity:
            return
        self._last_event_identity = identity
        self._trigger_event(
            str(event.get("event")),
            {
                key: value for key, value in event.items() if key != "event"
            },
        )
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: FactorioAssistantCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([FactorioEventStream(coordinator)])
