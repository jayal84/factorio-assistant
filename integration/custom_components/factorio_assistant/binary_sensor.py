"""Binary sensors for Factorio Assistant phase 1."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BRIDGE_VERSION,
    BRIDGE_DEVICE_NAME,
    BRIDGE_MODEL,
    DOMAIN,
    FACTORIO_MANUFACTURER,
    SERVER_MODEL,
)
from .coordinator import FactorioAssistantCoordinator


def _players(coordinator: FactorioAssistantCoordinator) -> dict[str, dict]:
    value = coordinator.data.get("world", {}).get("players", {})
    if isinstance(value, dict):
        return {str(username): player for username, player in value.items() if isinstance(player, dict)}
    if isinstance(value, list):
        return {
            str(player["name"]): player
            for player in value
            if isinstance(player, dict) and str(player.get("name", "")).strip()
        }
    return {}


def _surfaces(coordinator: FactorioAssistantCoordinator) -> list[dict]:
    value = coordinator.data.get("world", {}).get("surfaces", [])
    if isinstance(value, list):
        return [surface for surface in value if isinstance(surface, dict) and surface.get("name")]
    if isinstance(value, dict):
        return [
            {"name": name, **details}
            for name, details in value.items()
            if isinstance(details, dict)
        ]
    return []


def _safe(value: object) -> str:
    return "_".join("".join(c if c.isalnum() else "_" for c in str(value)).split("_")) or "unknown"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: FactorioAssistantCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [FactorioServerRunning(coordinator), FactorioBridgeHealthy(coordinator), FactorioWatchdogHealthy(coordinator), FactorioRconStatus(coordinator)]
    entities.extend(FactorioSurfaceAttack(coordinator, str(surface["name"])) for surface in _surfaces(coordinator))
    registered = {entity.unique_id for entity in entities}

    for username in _players(coordinator):
        if not str(username).strip():
            continue
        entities.extend(_player_entities(coordinator, username))
    registered.update(entity.unique_id for entity in entities)
    async_add_entities(entities)

    def add_new_entities() -> None:
        new_entities: list[BinarySensorEntity] = []
        for username in _players(coordinator):
            if not str(username).strip():
                continue
            new_entities.extend(
                entity for entity in _player_entities(coordinator, username)
                if entity.unique_id not in registered
            )
        for surface in _surfaces(coordinator):
            candidate = FactorioSurfaceAttack(coordinator, str(surface["name"]))
            if candidate.unique_id not in registered:
                new_entities.append(candidate)
        if not new_entities:
            return
        registered.update(entity.unique_id for entity in new_entities)
        async_add_entities(new_entities)

    coordinator.async_add_listener(add_new_entities)


def _player_entities(
    coordinator: FactorioAssistantCoordinator, username: str
) -> list[BinarySensorEntity]:
    return [
        FactorioPlayerConnected(coordinator, username),
        FactorioPlayerState(coordinator, username, "injured", "Injured", "mdi:bandage"),
        FactorioPlayerState(coordinator, username, "motion", "Motion", "mdi:run-fast"),
        FactorioPlayerState(coordinator, username, "active", "Active", "mdi:account-check"),
    ]


class _FactorioBinarySensor(CoordinatorEntity[FactorioAssistantCoordinator], BinarySensorEntity):
    def __init__(self, coordinator: FactorioAssistantCoordinator, key: str, name: str, icon: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        status = coordinator.data.get("status", {})
        factorio = status.get("factorio", {}) if isinstance(status, dict) else {}
        server_name = "Factorio"
        server_version = str(factorio.get("version") or "").strip() or None
        is_bridge_entity = key in {"bridge_healthy", "watchdog_healthy", "rcon_status"}
        device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": BRIDGE_DEVICE_NAME if is_bridge_entity else server_name,
            "manufacturer": "Factorio Assistant" if is_bridge_entity else FACTORIO_MANUFACTURER,
            "model": BRIDGE_MODEL if is_bridge_entity else SERVER_MODEL,
        }
        if is_bridge_entity:
            device_info["sw_version"] = BRIDGE_VERSION
        else:
            device_info.update(
                {
                    "identifiers": {(DOMAIN, f"{coordinator.entry.entry_id}_server")},
                    "via_device": (DOMAIN, coordinator.entry.entry_id),
                }
            )
            if server_version:
                device_info["sw_version"] = server_version
        self._attr_device_info = device_info


class FactorioServerRunning(_FactorioBinarySensor):
    def __init__(self, coordinator: FactorioAssistantCoordinator) -> None:
        super().__init__(coordinator, "server_running", "Factorio Server Running", "mdi:server")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("status", {}).get("factorio", {}).get("running", False))


class FactorioBridgeHealthy(_FactorioBinarySensor):
    def __init__(self, coordinator: FactorioAssistantCoordinator) -> None:
        super().__init__(coordinator, "bridge_healthy", "Factorio Assistant Bridge", "mdi:heart-pulse")

    @property
    def is_on(self) -> bool:
        status = self.coordinator.data.get("status", {})
        return bool(
            status.get("bridge", {}).get("running", False)
            and status.get("watchdog", {}).get("healthy", False)
        )


class FactorioWatchdogHealthy(_FactorioBinarySensor):
    """Report whether the bridge watchdog is healthy."""

    def __init__(self, coordinator: FactorioAssistantCoordinator) -> None:
        super().__init__(coordinator, "watchdog_healthy", "Watchdog Status", "mdi:heart-pulse")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("status", {}).get("watchdog", {}).get("healthy", False))


class FactorioRconStatus(_FactorioBinarySensor):
    """Report whether the coordinator's RCON-backed telemetry is connected."""

    def __init__(self, coordinator: FactorioAssistantCoordinator) -> None:
        super().__init__(coordinator, "rcon_status", "RCON Status", "mdi:lan-connect")
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("rcon", {}).get("connected", False))


class FactorioSurfaceAttack(CoordinatorEntity[FactorioAssistantCoordinator], BinarySensorEntity):
    """Report whether a Factorio surface is currently under attack."""

    def __init__(self, coordinator: FactorioAssistantCoordinator, surface_name: str) -> None:
        super().__init__(coordinator)
        prefix = coordinator.entry.entry_id
        self._surface_name = surface_name
        safe_name = _safe(surface_name)
        display = surface_name.title()
        self._attr_unique_id = f"{prefix}_surface_{safe_name}_under_attack"
        # Use concise entity name when attached to the surface device
        self._attr_name = "Under Attack"
        self._attr_icon = "mdi:alert-octagon"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        # Attach this binary sensor to the per-surface device so surface entities are grouped
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{prefix}_surface_{safe_name}")},
            "name": f"Factorio Surface: {display}",
            "manufacturer": FACTORIO_MANUFACTURER,
            "model": "Factorio Surface",
            "via_device": (DOMAIN, prefix),
        }

    @property
    def is_on(self) -> bool:
        return any(
            str(surface.get("name")) == self._surface_name and bool(surface.get("under_attack", False))
            for surface in _surfaces(self.coordinator)
        )


class FactorioPlayerConnected(
    CoordinatorEntity[FactorioAssistantCoordinator], BinarySensorEntity
):
    """Report the connection state of a Factorio player."""

    def __init__(self, coordinator: FactorioAssistantCoordinator, username: str) -> None:
        super().__init__(coordinator)
        self._username = username
        self._attr_unique_id = f"{coordinator.entry.entry_id}_player_{username}_connected"
        self._attr_name = "Connected"
        self._attr_icon = "mdi:account-check"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{coordinator.entry.entry_id}_player_{username}")},
            "name": f"Factorio Player: {username}",
            "manufacturer": FACTORIO_MANUFACTURER,
            "model": "Factorio Player",
            "via_device": (DOMAIN, f"{coordinator.entry.entry_id}_server"),
        }

    @property
    def is_on(self) -> bool:
        player = _players(self.coordinator).get(self._username, {})
        return bool(player.get("connected", False)) if isinstance(player, dict) else False


class FactorioPlayerState(CoordinatorEntity[FactorioAssistantCoordinator], BinarySensorEntity):
    """Expose a boolean player telemetry state."""

    def __init__(self, coordinator: FactorioAssistantCoordinator, username: str, key: str, name: str, icon: str) -> None:
        super().__init__(coordinator)
        prefix = coordinator.entry.entry_id
        self._username = username
        self._key = key
        self._attr_unique_id = f"{prefix}_player_{username}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = {"identifiers": {(DOMAIN, f"{prefix}_player_{username}")}, "name": f"Factorio Player: {username}", "manufacturer": FACTORIO_MANUFACTURER, "model": "Factorio Player", "via_device": (DOMAIN, f"{prefix}_server")}

    @property
    def is_on(self) -> bool:
        player = _players(self.coordinator).get(self._username, {})
        if not isinstance(player, dict):
            return False
        if self._key == "injured":
            try:
                return bool(player.get("connected", False) and float(player.get("health_percent", 100) or 0) < 100)
            except (TypeError, ValueError):
                return False
        if self._key == "active":
            return bool(player.get("connected", False) and not player.get("idle", False))
        return bool(player.get(self._key, False))


