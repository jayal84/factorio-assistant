"""Factorio server action buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, FACTORIO_MANUFACTURER
from .coordinator import FactorioAssistantCoordinator


class ResumeDayNightCycleButton(CoordinatorEntity[FactorioAssistantCoordinator], ButtonEntity):
    """Resume Factorio's day/night cycle."""

    def __init__(self, coordinator: FactorioAssistantCoordinator) -> None:
        super().__init__(coordinator)
        prefix = coordinator.entry.entry_id
        self._attr_unique_id = f"{prefix}_server_day_night_cycle_resume"
        self._attr_name = "Resume Day/Night Cycle"
        self._attr_icon = "mdi:weather-sunny-clock"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{prefix}_server")},
            "name": "Factorio",
            "manufacturer": FACTORIO_MANUFACTURER,
            "model": "Factorio Headless Server",
            "via_device": (DOMAIN, prefix),
        }

    async def async_press(self) -> None:
        await self.coordinator.async_call_mod("set_day_night_cycle", True)
        await self.coordinator.async_request_refresh()


class SaveGameButton(CoordinatorEntity[FactorioAssistantCoordinator], ButtonEntity):
    """Save the Factorio game through the assistant mod."""

    def __init__(self, coordinator: FactorioAssistantCoordinator) -> None:
        super().__init__(coordinator)
        prefix = coordinator.entry.entry_id
        self._attr_unique_id = f"{prefix}_server_save"
        self._attr_name = "Save Game"
        self._attr_icon = "mdi:content-save-outline"
        self._attr_device_info = {"identifiers": {(DOMAIN, f"{prefix}_server")}, "name": "Factorio", "manufacturer": FACTORIO_MANUFACTURER, "model": "Factorio Headless Server", "via_device": (DOMAIN, prefix)}

    async def async_press(self) -> None:
        await self.coordinator.async_call_mod("save_game")
        await self.coordinator.async_request_refresh()


class ClearRevealedEnemiesButton(CoordinatorEntity[FactorioAssistantCoordinator], ButtonEntity):
    """Clear revealed enemy units through the assistant mod."""

    def __init__(self, coordinator: FactorioAssistantCoordinator) -> None:
        super().__init__(coordinator)
        prefix = coordinator.entry.entry_id
        self._attr_unique_id = f"{prefix}_server_clear_revealed_enemies"
        self._attr_name = "Clear Revealed Enemies"
        self._attr_icon = "mdi:skull-crossbones"
        self._attr_device_info = {"identifiers": {(DOMAIN, f"{prefix}_server")}, "name": "Factorio", "manufacturer": FACTORIO_MANUFACTURER, "model": "Factorio Headless Server", "via_device": (DOMAIN, prefix)}

    async def async_press(self) -> None:
        await self.coordinator.async_call_mod("clear_revealed_enemies")
        await self.coordinator.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: FactorioAssistantCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ResumeDayNightCycleButton(coordinator), SaveGameButton(coordinator), ClearRevealedEnemiesButton(coordinator)])
