"""Writable Factorio server switches."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, FACTORIO_MANUFACTURER
from .coordinator import FactorioAssistantCoordinator


class FactorioSwitch(CoordinatorEntity[FactorioAssistantCoordinator], SwitchEntity):
    """A writable Factorio server switch."""

    def __init__(self, coordinator: FactorioAssistantCoordinator, key: str, name: str, icon: str, method: str, method_arguments: tuple[object, ...] = ()) -> None:
        super().__init__(coordinator)
        prefix = coordinator.entry.entry_id
        self._key = key
        self._method = method
        self._method_arguments = method_arguments
        self._attr_unique_id = f"{prefix}_server_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{prefix}_server")},
            "name": "Factorio",
            "manufacturer": FACTORIO_MANUFACTURER,
            "model": "Factorio Headless Server",
            "via_device": (DOMAIN, prefix),
        }

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("world", {}).get(self._key, False))

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_call_mod(self._method, *self._method_arguments, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_call_mod(self._method, *self._method_arguments, False)
        await self.coordinator.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: FactorioAssistantCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        FactorioSwitch(coordinator, "tick_paused", "Pause Game", "mdi:pause-circle-outline", "set_pause"),
        FactorioSwitch(coordinator, "daylight", "Daylight", "mdi:white-balance-sunny", "set_daylight"),
        FactorioSwitch(coordinator, "enemy_evolution_enabled", "Enemy Evolution", "mdi:chart-line-variant", "set_map_setting", ("enemy_evolution",)),
        FactorioSwitch(coordinator, "pollution_enabled", "Pollution", "mdi:smog", "set_map_setting", ("pollution",)),
    ])
