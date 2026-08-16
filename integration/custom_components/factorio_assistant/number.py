"""Writable Signal Monitor controls."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, FACTORIO_MANUFACTURER
from .coordinator import FactorioAssistantCoordinator


class SignalMonitorNumber(CoordinatorEntity[FactorioAssistantCoordinator], NumberEntity):
    """A writable red or green Signal Monitor control slot."""

    def __init__(self, coordinator: FactorioAssistantCoordinator, unit: str, network: str, slot: str, name: str) -> None:
        super().__init__(coordinator)
        prefix = coordinator.entry.entry_id
        self._unit = unit
        self._network = network
        self._slot = slot
        self._attr_unique_id = f"{prefix}_monitor_{unit}_{network}_control_{slot}"
        self._attr_name = name
        self._attr_native_min_value = -2147483648
        self._attr_native_max_value = 2147483647
        self._attr_native_step = 1
        self._attr_mode = "box"
        self._attr_icon = "mdi:signal-variant"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{prefix}_monitor_{unit}")},
            "name": f"Signal Monitor: {unit}",
            "manufacturer": FACTORIO_MANUFACTURER,
            "model": "Factorio Assistant Signal Monitor",
            "serial_number": unit,
            "via_device": (DOMAIN, f"{prefix}_server"),
        }

    @property
    def native_value(self) -> float:
        monitors = self.coordinator.data.get("world", {}).get("combinators", [])
        for monitor in monitors if isinstance(monitors, list) else []:
            if str(monitor.get("unit_number")) != self._unit:
                continue
            controls = monitor.get("control_signals", {})
            try:
                return float(controls.get(self._network, {}).get(self._slot, 0))
            except (AttributeError, TypeError, ValueError):
                break
        return 0

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_combinator_signal(
            self._unit, self._network, self._slot, int(value)
        )
        await self.coordinator.async_request_refresh()


class TimeOfDayNumber(CoordinatorEntity[FactorioAssistantCoordinator], NumberEntity):
    """Set Factorio time of day from 0 (midnight) through 1 (next midnight)."""

    def __init__(self, coordinator: FactorioAssistantCoordinator) -> None:
        super().__init__(coordinator)
        prefix = coordinator.entry.entry_id
        self._attr_unique_id = f"{prefix}_server_time_of_day"
        self._attr_name = "Time of Day"
        self._attr_native_min_value = 0.0
        self._attr_native_max_value = 1.0
        self._attr_native_step = 0.0001
        self._attr_mode = "slider"
        self._attr_icon = "mdi:weather-sunny"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{prefix}_server")},
            "name": "Factorio",
            "manufacturer": FACTORIO_MANUFACTURER,
            "model": "Factorio Headless Server",
            "via_device": (DOMAIN, prefix),
        }

    @property
    def native_value(self) -> float:
        try:
            return float(self.coordinator.data.get("world", {}).get("daytime", 0.0))
        except (TypeError, ValueError):
            return 0.0

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_call_mod("set_daytime", float(value))
        await self.coordinator.async_request_refresh()


class GameSpeedNumber(CoordinatorEntity[FactorioAssistantCoordinator], NumberEntity):
    """Set Factorio game speed."""

    def __init__(self, coordinator: FactorioAssistantCoordinator) -> None:
        super().__init__(coordinator)
        prefix = coordinator.entry.entry_id
        self._attr_unique_id = f"{prefix}_server_game_speed"
        self._attr_name = "Game Speed"
        self._attr_native_min_value = 0.1
        self._attr_native_max_value = 10.0
        self._attr_native_step = 0.1
        self._attr_mode = "slider"
        self._attr_icon = "mdi:speedometer-medium"
        self._attr_device_info = {"identifiers": {(DOMAIN, f"{prefix}_server")}, "name": "Factorio", "manufacturer": FACTORIO_MANUFACTURER, "model": "Factorio Headless Server", "via_device": (DOMAIN, prefix)}

    @property
    def native_value(self) -> float:
        try:
            return float(self.coordinator.data.get("world", {}).get("speed", 0.0))
        except (TypeError, ValueError):
            return 0.0

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_call_mod("set_game_speed", float(value))
        await self.coordinator.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: FactorioAssistantCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[NumberEntity] = []
    entities.extend([TimeOfDayNumber(coordinator), GameSpeedNumber(coordinator)])
    monitors = coordinator.data.get("world", {}).get("combinators", [])
    for monitor in monitors if isinstance(monitors, list) else []:
        if not isinstance(monitor, dict) or monitor.get("unit_number") is None:
            continue
        unit = str(monitor["unit_number"])
        mapping = monitor.get("slot_mapping", {})
        for network in ("red", "green"):
            for slot in ("A", "B", "C", "D"):
                preferred = mapping.get(slot, f"signal-{slot}") if isinstance(mapping, dict) else f"signal-{slot}"
                entities.append(SignalMonitorNumber(coordinator, unit, network, slot, f"Control {network.title()} {preferred}"))
    registered = {entity.unique_id for entity in entities}
    async_add_entities(entities)

    def add_new_entities() -> None:
        current: list[NumberEntity] = []
        monitors = coordinator.data.get("world", {}).get("combinators", [])
        for monitor in monitors if isinstance(monitors, list) else []:
            if not isinstance(monitor, dict) or monitor.get("unit_number") is None:
                continue
            unit = str(monitor["unit_number"])
            mapping = monitor.get("slot_mapping", {})
            for network in ("red", "green"):
                for slot in ("A", "B", "C", "D"):
                    preferred = mapping.get(slot, f"signal-{slot}") if isinstance(mapping, dict) else f"signal-{slot}"
                    current.append(SignalMonitorNumber(coordinator, unit, network, slot, f"Control {network.title()} {preferred}"))
        new_entities = [entity for entity in current if entity.unique_id not in registered]
        if new_entities:
            registered.update(entity.unique_id for entity in new_entities)
            async_add_entities(new_entities)

    coordinator.async_add_listener(add_new_entities)