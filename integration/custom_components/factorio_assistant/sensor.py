"""Sensor entities for Factorio Assistant phase 1."""

from __future__ import annotations

from typing import Any, Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, FACTORIO_MANUFACTURER, SERVER_MODEL
from .coordinator import FactorioAssistantCoordinator


def _world(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("world", {})


def _players(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    value = _world(data).get("players", {})
    if isinstance(value, dict):
        return {str(name): details for name, details in value.items() if isinstance(details, dict)}
    if isinstance(value, list):
        return {str(row.get("name")): row for row in value if isinstance(row, dict) and row.get("name")}
    return {}


def _player_value(data: dict[str, Any], username: str, key: str, default: Any = None) -> Any:
    player = _players(data).get(username, {})
    if not isinstance(player, dict) or not player.get("connected", False):
        return default
    return player.get(key, default)


def _player_health_percentage(data: dict[str, Any], username: str) -> float | None:
    player = _players(data).get(username, {})
    if not isinstance(player, dict) or not player.get("connected", False):
        return None
    try:
        health = float(player.get("health", 0) or 0)
        maximum = float(player.get("max_health", 0) or 0)
    except (TypeError, ValueError):
        return None
    return round(health / maximum * 100, 3) if maximum > 0 else None


def _player_health_attributes(data: dict[str, Any], username: str) -> dict[str, Any]:
    player = _players(data).get(username, {})
    if not isinstance(player, dict):
        return {}
    return {
        "health": player.get("health"),
        "max_health": player.get("max_health"),
    }


def _player_inventory_percentage(data: dict[str, Any], username: str) -> float | None:
    inventory = _player_value(data, username, "inventory", {})
    if not isinstance(inventory, dict):
        return None
    try:
        total = float(inventory.get("total_slots", 0) or 0)
        used = float(inventory.get("used_slots", 0) or 0)
    except (TypeError, ValueError):
        return None
    return round(used / total * 100, 3) if total > 0 else 0.0


def _player_object_value(data: dict[str, Any], username: str, field: str, nested: str) -> Any:
    value = _player_value(data, username, field, {})
    return value.get(nested) if isinstance(value, dict) else None


def _player_position(data: dict[str, Any], username: str) -> str | None:
    position = _player_value(data, username, "position", {})
    if not isinstance(position, dict):
        return None
    try:
        return f"({float(position.get('x', 0)):.3f}, {float(position.get('y', 0)):.3f})"
    except (TypeError, ValueError):
        return None


def _player_attributes(data: dict[str, Any], username: str) -> dict[str, Any]:
    player = _players(data).get(username, {})
    if not isinstance(player, dict):
        return {}
    inventory = player.get("inventory", {})
    armor = player.get("armor", {})
    position = player.get("position", {})
    return {
        "connected": player.get("connected"),
        "surface": player.get("surface"),
        "position": position,
        "position_x": position.get("x") if isinstance(position, dict) else None,
        "position_y": position.get("y") if isinstance(position, dict) else None,
        "health": player.get("health"),
        "max_health": player.get("max_health"),
        "deaths": player.get("deaths"),
        "armor_name": armor.get("name") if isinstance(armor, dict) else None,
        "armor_count": armor.get("equipment_count") if isinstance(armor, dict) else None,
        "inventory_used_slots": inventory.get("used_slots") if isinstance(inventory, dict) else None,
        "inventory_total_slots": inventory.get("total_slots") if isinstance(inventory, dict) else None,
    }


def _status(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("status", {})


def _installed_mod_attributes(data: dict[str, Any]) -> dict[str, Any]:
    mods = _status(data).get("storage", {}).get("mods", [])
    if not isinstance(mods, list):
        mods = []
    return {
        "mods": mods,
        "enabled_count": sum(1 for mod in mods if isinstance(mod, dict) and mod.get("enabled", False)),
        "disabled_count": sum(1 for mod in mods if isinstance(mod, dict) and not mod.get("enabled", False)),
    }


def _ltn(data: dict[str, Any]) -> dict[str, Any]:
    value = _world(data).get("ltn", {})
    return value if isinstance(value, dict) else {}


def _ltn_attributes(data: dict[str, Any]) -> dict[str, Any]:
    snapshot = _ltn(data)
    trains = snapshot.get("trains", [])
    surfaces = snapshot.get("surfaces", {})
    if not isinstance(trains, list):
        trains = []
    if not isinstance(surfaces, dict):
        surfaces = {}
    return {
        "installed": snapshot.get("installed", False),
        "train_count": snapshot.get("train_count", 0),
        "scheduled_train_count": snapshot.get("scheduled_train_count", 0),
        "manual_train_count": snapshot.get("manual_train_count", 0),
        "trains": trains,
        "surfaces": surfaces,
    }


def _ltn_device(coordinator: FactorioAssistantCoordinator) -> dict[str, Any]:
    prefix = coordinator.entry.entry_id
    return {
        "identifiers": {(DOMAIN, f"{prefix}_ltn")},
        "name": "Factorio LTN",
        "manufacturer": FACTORIO_MANUFACTURER,
        "model": "Logistic Train Network",
        "via_device": (DOMAIN, f"{prefix}_server"),
    }


def _vehicle_counts(data: dict[str, Any]) -> dict[str, Any]:
        counts = _world(data).get("vehicle_counts", {})
        return counts if isinstance(counts, dict) else {}


def _vehicle_counts_attributes(data: dict[str, Any]) -> dict[str, Any]:
        counts = _vehicle_counts(data)
        kinds = counts.get("kinds", {}) if isinstance(counts, dict) else {}
        if not isinstance(kinds, dict):
                kinds = {}
        return {
                "total": counts.get("total", 0),
                "matched": counts.get("matched", 0),
                "kinds": kinds,
                "surfaces": counts.get("surfaces", {}),
        }


def _resource_sites(data: dict[str, Any]) -> list[dict[str, Any]]:
    sites: list[dict[str, Any]] = []
    for surface in _world(data).get("surfaces", []) or []:
        pinned = surface.get("pinned_resources", []) if isinstance(surface, dict) else []
        if not isinstance(pinned, list):
            continue
        for resource in pinned:
            if isinstance(resource, dict):
                sites.append(resource)
    return sites


def _resource_site_attributes(data: dict[str, Any]) -> dict[str, Any]:
    sites = _resource_sites(data)
    return {
        "site_count": len(sites),
        "site_names": [str(site.get("name") or site.get("type_name") or site.get("id") or "") for site in sites if isinstance(site, dict)],
        "surface_names": sorted({
            str(surface.get("name") or "unknown")
            for surface in _world(data).get("surfaces", []) or []
            if isinstance(surface, dict) and any(isinstance(resource, dict) for resource in surface.get("pinned_resources", []) or [])
        }),
        "total_extraction_rate": round(sum(float(site.get("rate", 0) or 0) for site in sites), 3),
    }


def _hours(value: Any) -> float | None:
    try:
        return round(float(value) / 3600, 3) if value is not None else None
    except (TypeError, ValueError):
        return None


def _percentage(value: Any) -> float | None:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _research_attributes(data: dict[str, Any]) -> dict[str, Any]:
    world = _world(data)
    queue = world.get("research_queue", {})
    return {
        "research_progress": world.get("research_progress"),
        "research_queue": queue,
        "research_localized_name": world.get("research_localized_name"),
        "research_queue_localized_names": world.get("research_queue_localized_names", []),
        "technologies_researched": world.get("technologies_researched"),
        "technologies_total": world.get("technologies_total"),
    }


def _research_queue_value(data: dict[str, Any]) -> str:
    localized_queue = _world(data).get("research_queue_localized_names", [])
    if isinstance(localized_queue, list) and localized_queue:
        return ", ".join(str(item) for item in localized_queue)
    queue = _world(data).get("research_queue", {})
    if isinstance(queue, dict):
        return ", ".join(str(name) for name in queue) or "Empty"
    if isinstance(queue, list):
        return ", ".join(str(item) for item in queue) or "Empty"
    return str(queue or "Empty")


def _world_attributes(data: dict[str, Any]) -> dict[str, Any]:
    world = _world(data)
    progress = world.get("research_progress")
    try:
        progress_percent = round(float(progress or 0) * 100, 2)
    except (TypeError, ValueError):
        progress_percent = None
    return {
        "tick": world.get("tick"),
        "game_day": world.get("game_day"),
        "game_time": world.get("game_time"),
        "players_online": world.get("players_online"),
        "current_research": world.get("research"),
        "current_research_localized_name": world.get("research_localized_name"),
        "research_progress": world.get("research_progress"),
        "research_progress_percent": progress_percent,
        "research_queue": world.get("research_queue"),
        "technologies_researched": world.get("technologies_researched"),
        "technologies_total": world.get("technologies_total"),
        "vehicle_counts": world.get("vehicle_counts"),
        "ltn": world.get("ltn"),
    }


def _device(coordinator: FactorioAssistantCoordinator, suffix: str, name: str, model: str) -> dict[str, Any]:
    return {"identifiers": {(DOMAIN, f"{coordinator.entry.entry_id}_{suffix}")}, "name": name, "manufacturer": FACTORIO_MANUFACTURER, "model": model, "via_device": (DOMAIN, coordinator.entry.entry_id)}


def _server_device(coordinator: FactorioAssistantCoordinator) -> dict[str, Any]:
    factorio = _status(coordinator.data).get("factorio", {})
    device = _device(coordinator, "server", "Factorio", SERVER_MODEL)
    if factorio.get("version"):
        device["sw_version"] = str(factorio["version"])
    return device


def _safe(value: object) -> str:
    return "_".join("".join(c if c.isalnum() else "_" for c in str(value)).split("_")) or "unknown"


def _site(data: dict[str, Any], site_id: str) -> dict[str, Any]:
    for surface in _world(data).get("surfaces", []) or []:
        for resource in surface.get("pinned_resources", []) or []:
            if str(resource.get("id")) == site_id:
                return resource
    return {}


def _resource_attributes(data: dict[str, Any], site_id: str) -> dict[str, Any]:
    resource = _site(data, site_id)
    estimated_ticks = resource.get("estimated_depletion")
    try:
        estimated_seconds = round(float(estimated_ticks) / 60, 3) if estimated_ticks is not None else None
    except (TypeError, ValueError):
        estimated_seconds = None
    surface_name = next(
        (
            surface.get("name")
            for surface in _world(data).get("surfaces", []) or []
            if any(str(site.get("id")) == site_id for site in surface.get("pinned_resources", []) or [])
        ),
        None,
    )
    return {
        "surface": surface_name,
        "site_name": resource.get("name"),
        "ore_type": resource.get("type_name") or resource.get("type"),
        "ore_type_id": resource.get("type"),
        "initial_amount": resource.get("initial_amount"),
        "remaining_amount": resource.get("amount"),
        "remaining_percent": round(float(resource.get("percent", 0) or 0) * 100, 3),
        "extraction_rate": round(float(resource.get("rate", 0) or 0), 3),
        "estimated_depletion_ticks": estimated_ticks,
        "estimated_depletion_seconds": estimated_seconds,
        "position": resource.get("position"),
    }


def _site_estimated_depletion_seconds(data: dict[str, Any], site_id: str) -> float | None:
    estimated_ticks = _site(data, site_id).get("estimated_depletion")
    try:
        return round(float(estimated_ticks) / 60, 3) if estimated_ticks is not None else None
    except (TypeError, ValueError):
        return None


def _pollution_rate(data: dict[str, Any], surface_name: str) -> float | None:
    return (data.get("derived", {}).get("pollution_rates", {}) or {}).get(surface_name)


def _signal(data: dict[str, Any], unit: str, name: str, network: str | None) -> Any:
    for monitor in _world(data).get("combinators", []) or []:
        if str(monitor.get("unit_number")) == unit:
            for value in monitor.get("signals", []) or []:
                if value.get("name") == name and value.get("network") == network:
                    return value.get("count", 0)
    return 0


def _monitor_slot(data: dict[str, Any], unit: str, field: str, network: str, slot: str) -> int:
    for monitor in _world(data).get("combinators", []) or []:
        if str(monitor.get("unit_number")) != unit:
            continue
        values = monitor.get(field, {})
        if isinstance(values, dict):
            values = values.get(network, {})
            if isinstance(values, dict):
                try:
                    return int(values.get(slot, 0) or 0)
                except (TypeError, ValueError):
                    return 0
    return 0


class SnapshotSensor(CoordinatorEntity[FactorioAssistantCoordinator], SensorEntity):
    def __init__(self, coordinator: FactorioAssistantCoordinator, unique_id: str, name: str, value_fn: Callable[[dict[str, Any]], Any], device_info: dict[str, Any], **attributes: Any) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = unique_id
        self._attr_name = name
        self._value_fn = value_fn
        self._attr_device_info = device_info
        self._attributes_fn: Callable[[dict[str, Any]], dict[str, Any] | None] | None = attributes.pop("attributes_fn", None)
        for key, value in attributes.items():
            setattr(self, f"_attr_{key}", value)

    @property
    def native_value(self) -> Any:
        return self._value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if callable(self._attributes_fn):
            result = self._attributes_fn(self.coordinator.data)
            return result if isinstance(result, dict) else None
        return getattr(self, "_attr_extra_state_attributes", None)


def _server_sensors(coordinator: FactorioAssistantCoordinator) -> list[SensorEntity]:
    prefix = coordinator.entry.entry_id
    device = _server_device(coordinator)
    definitions = [("tick", "World Tick", lambda d: _world(d).get("tick"), None, "total_increasing", "mdi:counter"), ("speed", "Game Speed", lambda d: _world(d).get("speed"), None, "measurement", "mdi:speedometer"), ("players_online", "Active Players", lambda d: _world(d).get("players_online"), None, "measurement", "mdi:account-group"), ("research", "Current Research", lambda d: _world(d).get("research_localized_name") or _world(d).get("research"), None, None, "mdi:flask"), ("research_level", "Current Research Level", lambda d: _world(d).get("research_level"), "levels", "measurement", "mdi:format-list-numbered"), ("research_progress", "Research Progress", lambda d: _percentage(float(_world(d).get("research_progress", 0) or 0) * 100), PERCENTAGE, "measurement", "mdi:progress-clock"), ("evolution_factor", "Evolution Factor", lambda d: _percentage(float(_world(d).get("evolution_factor", 0) or 0) * 100), PERCENTAGE, "measurement", "mdi:biohazard"), ("evolution_progress", "Evolution Progress", lambda d: _percentage(_world(d).get("evolution_progress", 0)), PERCENTAGE, "measurement", "mdi:chart-line"), ("rockets_launched", "Rockets Launched", lambda d: _world(d).get("rockets_launched"), None, "total_increasing", "mdi:rocket-launch"), ("technologies_researched", "Technologies Researched", lambda d: _world(d).get("technologies_researched"), None, "measurement", "mdi:check-circle-outline"), ("technologies_total", "Technologies Total", lambda d: _world(d).get("technologies_total"), None, "measurement", "mdi:flask-outline"), ("game_day", "Day", lambda d: _world(d).get("game_day"), None, "measurement", "mdi:calendar-range"), ("game_time", "Game Time", lambda d: _world(d).get("game_time"), "s", "measurement", "mdi:clock-outline"), ("surface_count", "Surface Count", lambda d: _world(d).get("surface_count"), None, "measurement", "mdi:map-marker-multiple"), ("surfaces", "Surfaces", lambda d: _world(d).get("surface_names"), None, None, "mdi:map-marker-multiple")]
    gameplay_keys = {"speed", "players_online", "research", "research_level", "research_progress", "evolution_factor", "evolution_progress", "rockets_launched", "technologies_researched", "technologies_total", "game_day", "game_time", "surface_count"}
    entities = [SnapshotSensor(coordinator, f"{prefix}_server_{key}", name, fn, device, native_unit_of_measurement=unit, state_class=state, icon=icon, entity_category=None if key in gameplay_keys else EntityCategory.DIAGNOSTIC, attributes_fn=_world_attributes) for key, name, fn, unit, state, icon in definitions]
    entities.append(SnapshotSensor(coordinator, f"{prefix}_server_ups", "UPS", lambda data: _world(data).get("ups"), device, native_unit_of_measurement="updates/s", state_class="measurement", icon="mdi:chart-line", entity_category=EntityCategory.DIAGNOSTIC, attributes_fn=_world_attributes))
    vehicle_definitions = [
        ("vehicle_total", "Vehicles", lambda data: _vehicle_counts(data).get("total", 0), None, "mdi:truck"),
        ("vehicle_matched", "AAI Vehicles", lambda data: _vehicle_counts(data).get("matched", 0), None, "mdi:truck-fast"),
        ("vehicle_miner", "Mining Vehicles", lambda data: (_vehicle_counts(data).get("kinds", {}) or {}).get("miner", 0), None, "mdi:pickaxe"),
        ("vehicle_hauler", "AAI Haulers", lambda data: (_vehicle_counts(data).get("kinds", {}) or {}).get("hauler", 0), None, "mdi:truck-delivery"),
        ("vehicle_warden", "AAI Wardens", lambda data: (_vehicle_counts(data).get("kinds", {}) or {}).get("warden", 0), None, "mdi:shield-car"),
        ("vehicle_chaingunner", "AAI Chaingunners", lambda data: (_vehicle_counts(data).get("kinds", {}) or {}).get("chaingunner", 0), None, "mdi:gun"),
        ("vehicle_flame_tank", "AAI Flame Tanks", lambda data: (_vehicle_counts(data).get("kinds", {}) or {}).get("flame_tank", 0), None, "mdi:fire-truck"),
        ("vehicle_ironclad", "AAI Ironclads", lambda data: (_vehicle_counts(data).get("kinds", {}) or {}).get("ironclad", 0), None, "mdi:shield-tank"),
        ("vehicle_laser_tank", "AAI Laser Tanks", lambda data: (_vehicle_counts(data).get("kinds", {}) or {}).get("laser_tank", 0), None, "mdi:laser-pointer"),
    ]
    entities.extend(SnapshotSensor(coordinator, f"{prefix}_server_{key}", name, fn, device, native_unit_of_measurement=unit, state_class="measurement", icon=icon, entity_category=None if key == "vehicle_miner" else EntityCategory.DIAGNOSTIC, attributes_fn=_vehicle_counts_attributes if key == "vehicle_total" else None) for key, name, fn, unit, icon in vehicle_definitions)
    entities.append(SnapshotSensor(coordinator, f"{prefix}_server_resource_sites", "Tracked Resource Sites", lambda data: len(_resource_sites(data)), device, state_class="measurement", icon="mdi:pickaxe", entity_category=EntityCategory.DIAGNOSTIC, attributes_fn=_resource_site_attributes))
    diagnostics = [
        ("save_file", "Save File", lambda data: _status(data).get("diagnostics", {}).get("save_file"), None, "mdi:file"),
        ("save_size", "Save Size", lambda data: _status(data).get("diagnostics", {}).get("save_size"), "B", "mdi:database"),
        ("cpu_usage", "CPU Usage", lambda data: _status(data).get("diagnostics", {}).get("cpu_usage"), PERCENTAGE, "mdi:cpu-64-bit"),
        ("mem_usage", "Memory Usage", lambda data: _status(data).get("diagnostics", {}).get("mem_usage"), PERCENTAGE, "mdi:memory"),
        ("uptime", "Uptime", lambda data: _hours(_status(data).get("diagnostics", {}).get("uptime")), "h", "mdi:timer-outline"),
        ("version", "Version", lambda data: _status(data).get("factorio", {}).get("version"), None, "mdi:information-outline"),
        ("difficulty", "Difficulty", lambda data: _world(data).get("difficulty"), None, "mdi:gamepad-variant-outline"),
        ("mod_count", "Installed Mods", lambda data: _status(data).get("storage", {}).get("mod_count"), "mods", "mdi:puzzle"),
    ]
    entities.extend(SnapshotSensor(coordinator, f"{prefix}_server_{key}", name, fn, device, native_unit_of_measurement=unit, device_class=SensorDeviceClass.DURATION if key == "uptime" else None, state_class="measurement" if unit else None, icon=icon, entity_category=EntityCategory.DIAGNOSTIC, attributes_fn=_installed_mod_attributes if key == "mod_count" else None) for key, name, fn, unit, icon in diagnostics)
    entities.append(SnapshotSensor(coordinator, f"{prefix}_server_research_queue", "Research Queue", _research_queue_value, device, icon="mdi:format-list-bulleted", attributes_fn=_research_attributes))
    entities.append(SnapshotSensor(coordinator, f"{prefix}_server_research_completion", "Research Completion Estimate", lambda data: _hours(data.get("derived", {}).get("research_completion_seconds")), device, native_unit_of_measurement="h", device_class=SensorDeviceClass.DURATION, icon="mdi:timer-sand-complete", attributes_fn=_research_attributes))

    bridge = {
        "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
        "name": "Factorio Assistant Bridge",
        "manufacturer": "Factorio Assistant",
        "model": "Home Assistant Add-on",
    }
    bridge_diagnostics = [
        ("bridge_running", "Bridge Running", lambda data: _status(data).get("bridge", {}).get("running"), "mdi:bridge"),
        ("rcon_password_present", "RCON Password Configured", lambda data: _status(data).get("bridge", {}).get("rcon_password_present"), "mdi:key-chain"),
        ("watchdog_available", "Watchdog Available", lambda data: _status(data).get("watchdog", {}).get("available"), "mdi:heart-pulse"),
        ("watchdog_healthy", "Watchdog Healthy", lambda data: _status(data).get("watchdog", {}).get("healthy"), "mdi:shield-check"),
        ("watchdog_monitor_count", "Watchdog Monitor Count", lambda data: len(_status(data).get("watchdog", {}).get("monitors", []) or []), "mdi:format-list-numbered"),
        ("watchdog_checked_at", "Watchdog Checked At", lambda data: _status(data).get("watchdog", {}).get("checked_at"), None),
    ]
    entities.extend(SnapshotSensor(coordinator, f"{prefix}_{key}", name, fn, bridge, icon=icon, entity_category=EntityCategory.DIAGNOSTIC) for key, name, fn, icon in bridge_diagnostics)
    return entities


def _ltn_sensors(coordinator: FactorioAssistantCoordinator) -> list[SensorEntity]:
    prefix = coordinator.entry.entry_id
    device = _ltn_device(coordinator)
    return [
        SnapshotSensor(
            coordinator,
            f"{prefix}_ltn_train_count",
            "Train Count",
            lambda data: _ltn(data).get("train_count", 0),
            device,
            icon="mdi:train",
            entity_category=EntityCategory.DIAGNOSTIC,
            attributes_fn=_ltn_attributes,
        ),
        SnapshotSensor(
            coordinator,
            f"{prefix}_ltn_scheduled_train_count",
            "Scheduled Trains",
            lambda data: _ltn(data).get("scheduled_train_count", 0),
            device,
            icon="mdi:train-car",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
    ]


def _dynamic_sensors(coordinator: FactorioAssistantCoordinator) -> list[SensorEntity]:
    data = coordinator.data
    prefix = coordinator.entry.entry_id
    entities: list[SensorEntity] = []
    server = _server_device(coordinator)
    for username in _players(data):
        device = _device(coordinator, f"player_{username}", f"Factorio Player: {username}", "Factorio Player")
        device["via_device"] = (DOMAIN, f"{prefix}_server")
        base = f"{prefix}_player_{_safe(username)}"
        entities.extend([SnapshotSensor(coordinator, f"{base}_health", "Health", lambda d, u=username: _player_health_percentage(d, u), device, native_unit_of_measurement=PERCENTAGE, state_class="measurement", icon="mdi:heart-pulse", attributes_fn=lambda d, u=username: _player_health_attributes(d, u)), SnapshotSensor(coordinator, f"{base}_deaths", "Deaths", lambda d, u=username: _player_value(d, u, "deaths"), device, state_class="total_increasing", icon="mdi:skull"), SnapshotSensor(coordinator, f"{base}_surface", "Surface", lambda d, u=username: _player_value(d, u, "surface"), device, icon="mdi:layers-outline"), SnapshotSensor(coordinator, f"{base}_armor", "Armor", lambda d, u=username: _player_object_value(d, u, "armor", "name"), device, icon="mdi:shield", attributes_fn=lambda d, u=username: _player_attributes(d, u)), SnapshotSensor(coordinator, f"{base}_inventory", "Inventory", lambda d, u=username: _player_inventory_percentage(d, u), device, native_unit_of_measurement=PERCENTAGE, state_class="measurement", icon="mdi:package-variant", attributes_fn=lambda d, u=username: _player_attributes(d, u)), SnapshotSensor(coordinator, f"{base}_position", "Position", lambda d, u=username: _player_position(d, u), device, icon="mdi:map-marker", attributes_fn=lambda d, u=username: _player_attributes(d, u))])
    for surface in _world(data).get("surfaces", []) or []:
        if not isinstance(surface, dict):
            continue
        name = str(surface.get("name", "unknown"))
        display_name = name.title()
        # Create a per-surface device so surface-related sensors are grouped in HA device view
        surface_device = _device(coordinator, f"surface_{_safe(name)}", f"Factorio Surface: {display_name}", "Factorio Surface")
        surface_device["via_device"] = (DOMAIN, f"{prefix}_server")
        # Use concise friendly names when sensors are attached to a per-surface device
        entities.append(SnapshotSensor(coordinator, f"{prefix}_surface_{_safe(name)}_pollution", "Pollution", lambda d, n=name: next((s.get("pollution", 0) for s in d.get("world", {}).get("surfaces", []) if s.get("name") == n), 0), surface_device, state_class="measurement", icon="mdi:smog"))
        entities.append(SnapshotSensor(coordinator, f"{prefix}_surface_{_safe(name)}_pollution_rate", "Pollution Rate", lambda d, n=name: _pollution_rate(d, n), surface_device, state_class="measurement", icon="mdi:chart-line"))
        for resource in surface.get("pinned_resources", []) or []:
            if not isinstance(resource, dict) or resource.get("id") is None:
                continue
            site_id = str(resource["id"])
            device = _device(coordinator, f"site_{site_id}", f"Factorio Resource Site: {resource.get('name') or resource.get('type_name') or site_id}", "Pinned Resource Site")
            device["via_device"] = (DOMAIN, f"{prefix}_server")
            base = f"{prefix}_site_{site_id}"
            attributes = lambda d, sid=site_id: _resource_attributes(d, sid)
            entities.extend([
                SnapshotSensor(coordinator, f"{base}_type", "Ore Type", lambda d, sid=site_id: _site(d, sid).get("type_name") or _site(d, sid).get("type"), device, icon="mdi:pickaxe", attributes_fn=attributes),
                SnapshotSensor(coordinator, f"{base}_initial_amount", "Initial Amount", lambda d, sid=site_id: _site(d, sid).get("initial_amount"), device, state_class="measurement", icon="mdi:counter", attributes_fn=attributes),
                SnapshotSensor(coordinator, f"{base}_amount", "Remaining Amount", lambda d, sid=site_id: _site(d, sid).get("amount", 0), device, icon="mdi:counter", attributes_fn=attributes),
                SnapshotSensor(coordinator, f"{base}_remaining", "Remaining", lambda d, sid=site_id: round(float(_site(d, sid).get("percent", 0) or 0) * 100, 3), device, native_unit_of_measurement=PERCENTAGE, state_class="measurement", icon="mdi:percent", attributes_fn=attributes),
                SnapshotSensor(coordinator, f"{base}_rate", "Extraction Rate", lambda d, sid=site_id: round(float(_site(d, sid).get("rate", 0) or 0), 3), device, state_class="measurement", icon="mdi:pickaxe", attributes_fn=attributes),
                SnapshotSensor(coordinator, f"{base}_estimated_depletion", "Estimated Depletion", lambda d, sid=site_id: _hours(_site_estimated_depletion_seconds(d, sid)), device, native_unit_of_measurement="h", device_class=SensorDeviceClass.DURATION, icon="mdi:timer-sand", attributes_fn=attributes),
            ])
    for monitor in _world(data).get("combinators", []) or []:
        if not isinstance(monitor, dict) or monitor.get("unit_number") is None:
            continue
        unit = str(monitor["unit_number"])
        device = _device(coordinator, f"monitor_{unit}", f"Signal Monitor: {monitor.get('name') or f'Unit {unit}'}", "Factorio Assistant Signal Monitor")
        device["via_device"] = (DOMAIN, f"{prefix}_server")
        device["serial_number"] = unit
        for value in monitor.get("signals", []) or []:
            if isinstance(value, dict) and value.get("name"):
                network = value.get("network")
                key = _safe(f"{network}_{value['name']}")
                entities.append(SnapshotSensor(coordinator, f"{prefix}_monitor_{unit}_{key}", f"{value['name']} ({str(network or 'unknown').title()})", lambda d, u=unit, n=value["name"], net=network: _signal(d, u, n, net), device, state_class="measurement", icon="mdi:signal", entity_category=EntityCategory.DIAGNOSTIC))
        for network in ("red", "green"):
            for slot in ("A", "B", "C", "D"):
                mapped_name = monitor.get("slot_mapping", {}).get(slot, f"signal-{slot}")
                for field, label in (("input_signals", "Input"), ("control_signals", "Control")):
                    entities.append(SnapshotSensor(coordinator, f"{prefix}_monitor_{unit}_{network}_{field}_{slot}", f"{label} {network.title()} {mapped_name}", lambda d, u=unit, f=field, n=network, s=slot: _monitor_slot(d, u, f, n, s), device, state_class="measurement", icon="mdi:transit-connection-variant", entity_category=EntityCategory.DIAGNOSTIC, extra_state_attributes={"factorio_slot": slot, "preferred_signal": mapped_name}))
    return entities


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: FactorioAssistantCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = _server_sensors(coordinator) + _ltn_sensors(coordinator) + _dynamic_sensors(coordinator)
    registered = {entity.unique_id for entity in entities}
    async_add_entities(entities)

    def add_new_entities() -> None:
        new_entities = [
            entity
            for entity in _dynamic_sensors(coordinator)
            if entity.unique_id not in registered
        ]
        if not new_entities:
            return
        registered.update(entity.unique_id for entity in new_entities)
        async_add_entities(new_entities)

"""

from __future__ import annotations

from typing import Any, Callable

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, FACTORIO_MANUFACTURER, SERVER_MODEL
from .coordinator import FactorioAssistantCoordinator


def _world(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("world", {})


def _status(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("status", {})


def _server_device(coordinator: FactorioAssistantCoordinator) -> dict[str, Any]:
    factorio = _status(coordinator.data).get("factorio", {})
    device: dict[str, Any] = {
        "identifiers": {(DOMAIN, f"{coordinator.entry.entry_id}_server")},
        "name": str(factorio.get("name") or "Factorio"),
        "manufacturer": FACTORIO_MANUFACTURER,
        "model": SERVER_MODEL,
        "via_device": (DOMAIN, coordinator.entry.entry_id),
    }
    if factorio.get("version"):
        device["sw_version"] = str(factorio["version"])
    return device


def _safe(value: object) -> str:
    return "_".join("".join(char if char.isalnum() else "_" for char in str(value)).split("_")) or "unknown"


def _site(data: dict[str, Any], site_id: str) -> dict[str, Any]:
    for surface in _world(data).get("surfaces", []) or []:
        for resource in surface.get("pinned_resources", []) or []:
            if str(resource.get("id")) == site_id:
                return resource
    return {}


def _monitor_signal(data: dict[str, Any], unit: str, name: str, network: str | None) -> Any:
    for monitor in _world(data).get("combinators", []) or []:
        if str(monitor.get("unit_number")) != unit:
            continue
        for signal in monitor.get("signals", []) or []:
            if signal.get("name") == name and signal.get("network") == network:
                return signal.get("count", 0)
    return 0


class SnapshotSensor(CoordinatorEntity[FactorioAssistantCoordinator], SensorEntity):
    def __init__(self, coordinator: FactorioAssistantCoordinator, unique_id: str, name: str, value_fn: Callable[[dict[str, Any]], Any], device_info: dict[str, Any], **attributes: Any) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = unique_id
        self._attr_name = name
        self._value_fn = value_fn
        self._attr_device_info = device_info
        for key, value in attributes.items():
            setattr(self, f"_attr_{key}", value)

    @property
    def native_value(self) -> Any:
        return self._value_fn(self.coordinator.data)


def _server_sensors(coordinator: FactorioAssistantCoordinator) -> list[SensorEntity]:
    prefix = coordinator.entry.entry_id
    device = _server_device(coordinator)
    definitions = [
        ("tick", "World Tick", lambda data: _world(data).get("tick"), None, "total_increasing", "mdi:counter"),
        ("speed", "Game Speed", lambda data: _world(data).get("speed"), None, "measurement", "mdi:speedometer"),
        ("players_online", "Active Players", lambda data: _world(data).get("players_online"), None, "measurement", "mdi:account-group"),
        ("research", "Current Research", lambda data: _world(data).get("research"), None, None, "mdi:flask"),
        ("research_progress", "Research Progress", lambda data: _world(data).get("research_progress"), PERCENTAGE, "measurement", "mdi:progress-clock"),
        ("evolution", "Enemy Evolution", lambda data: float(_world(data).get("evolution", 0) or 0) * 100, PERCENTAGE, "measurement", "mdi:biohazard"),
        ("rockets_launched", "Rockets Launched", lambda data: _world(data).get("rockets_launched"), None, "total_increasing", "mdi:rocket-launch"),
        ("save_count", "Save Count", lambda data: _status(data).get("storage", {}).get("save_count"), None, "measurement", "mdi:content-save"),
        ("mod_count", "Installed Mod Count", lambda data: _status(data).get("storage", {}).get("mod_count"), None, "measurement", "mdi:puzzle"),
        ("technologies_researched", "Technologies Researched", lambda data: _world(data).get("technologies_researched"), None, "measurement", "mdi:check-circle-outline"),
        ("technologies_total", "Technologies Total", lambda data: _world(data).get("technologies_total"), None, "measurement", "mdi:flask-outline"),
        ("game_day", "Day", lambda data: _world(data).get("game_day"), None, "measurement", "mdi:calendar-range"),
        ("game_time", "Game Time", lambda data: _world(data).get("game_time"), "s", "measurement", "mdi:clock-outline"),
        ("surface_count", "Surface Count", lambda data: _world(data).get("surface_count"), None, "measurement", "mdi:map-marker-multiple"),
    ]
    return [SnapshotSensor(coordinator, f"{prefix}_server_{key}", name, value_fn, device, native_unit_of_measurement=unit, state_class=state_class, icon=icon) for key, name, value_fn, unit, state_class, icon in definitions]


def _dynamic_sensors(coordinator: FactorioAssistantCoordinator) -> list[SensorEntity]:
    data = coordinator.data
    prefix = coordinator.entry.entry_id
    entities: list[SensorEntity] = []
    server = _server_device(coordinator)
    for username, player in (_world(data).get("players") or {}).items():
        if not isinstance(player, dict):
            continue
        player_id = _safe(username)
        device = {"identifiers": {(DOMAIN, f"{prefix}_player_{username}")}, "name": f"Factorio Player: {username}", "manufacturer": FACTORIO_MANUFACTURER, "model": "Factorio Player", "via_device": (DOMAIN, f"{prefix}_server")}
        base = f"{prefix}_player_{player_id}"
        name="Rockets Launched",
        icon="mdi:rocket-launch",
        value_fn=lambda data: _world(data).get("rockets_launched"),
    ),
    FactorioSensorDescription(
        key="save_count",

def _ltn_sensors(coordinator: FactorioAssistantCoordinator) -> list[SensorEntity]:
    prefix = coordinator.entry.entry_id
    device = _ltn_device(coordinator)
    return [
        SnapshotSensor(
            coordinator,
            f"{prefix}_ltn_train_count",
            "Train Count",
            lambda data: _ltn(data).get("train_count", 0),
            device,
            icon="mdi:train",
            entity_category=EntityCategory.DIAGNOSTIC,
            attributes_fn=_ltn_attributes,
        ),
        SnapshotSensor(
            coordinator,
            f"{prefix}_ltn_scheduled_train_count",
            "Scheduled Trains",
            lambda data: _ltn(data).get("scheduled_train_count", 0),
            device,
            icon="mdi:train-car",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
    ]
        name="Save Count",
        icon="mdi:content-save",
        value_fn=lambda data: data.get("status", {}).get("storage", {}).get("save_count"),
    entities = _server_sensors(coordinator) + _ltn_sensors(coordinator) + _dynamic_sensors(coordinator)
    FactorioSensorDescription(
        key="mod_count",
        name="Installed Mod Count",
        icon="mdi:puzzle",
        value_fn=lambda data: data.get("status", {}).get("storage", {}).get("mod_count"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: FactorioAssistantCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(FactorioSensor(coordinator, description) for description in SENSORS)


class FactorioSensor(CoordinatorEntity[FactorioAssistantCoordinator], SensorEntity):

    entity_description: FactorioSensorDescription

    def __init__(self, coordinator: FactorioAssistantCoordinator, description: FactorioSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        status = coordinator.data.get("status", {})
        factorio = status.get("factorio", {}) if isinstance(status, dict) else {}
        server_name = str(factorio.get("name") or "Factorio").strip()
        server_version = str(factorio.get("version") or "").strip() or None
        device_info = {
            "identifiers": {(DOMAIN, f"{coordinator.entry.entry_id}_server")},
            "name": server_name,
            "manufacturer": FACTORIO_MANUFACTURER,
            "model": SERVER_MODEL,
            "via_device": (DOMAIN, coordinator.entry.entry_id),
        }
        if server_version:
            device_info["sw_version"] = server_version
        self._attr_device_info = device_info

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)
"""