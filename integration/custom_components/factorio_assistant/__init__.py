"""Home Assistant integration for Factorio Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import PLATFORMS
from .coordinator import FactorioAssistantCoordinator
from .services import async_register_services
from .api import FactorioPushView


def _remove_stale_monitor_entities(hass: HomeAssistant, entry: ConfigEntry, coordinator: FactorioAssistantCoordinator) -> None:
    current_units = {
        str(monitor.get("unit_number"))
        for monitor in coordinator.data.get("world", {}).get("combinators", [])
        if isinstance(monitor, dict) and monitor.get("unit_number") is not None
    }
    registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    stale_devices: set[str] = set()
    for entity in list(registry.entities.values()):
        if entity.config_entry_id != entry.entry_id or "_monitor_" not in entity.unique_id:
            continue
        unit = entity.unique_id.split("_monitor_", 1)[1].split("_", 1)[0]
        if unit not in current_units:
            if entity.device_id:
                stale_devices.add(entity.device_id)
            registry.async_remove(entity.entity_id)
    for device_id in stale_devices:
        if not any(entity.device_id == device_id for entity in registry.entities.values()):
            device_registry.async_remove_device(device_id)


async def async_setup(hass: HomeAssistant, config: dict[str, object]) -> bool:
    """Set up integration-level services before config entries load."""
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = FactorioAssistantCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    _remove_stale_monitor_entities(hass, entry, coordinator)
    hass.data.setdefault("factorio_assistant", {})[entry.entry_id] = coordinator
    # register push endpoint (single global endpoint shared by all entries)
    try:
        hass.http.register_view(FactorioPushView(hass))
    except Exception:
        pass
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_add_listener(lambda: _remove_stale_monitor_entities(hass, entry, coordinator))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator = hass.data.get("factorio_assistant", {}).pop(entry.entry_id, None)
        if coordinator is not None:
            try:
                await coordinator.async_stop()
            except Exception:
                pass
    return unloaded