#!/usr/bin/env python3
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psutil
except Exception:  # pragma: no cover - optional dependency
    psutil = None

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from rcon_client import RCONClient
from telemetry_models import normalize_player_health

TRACE_LEVEL = 5
NOTICE_LEVEL = 25
FATAL_LEVEL = 60
RCON_STARTUP_DELAY = 15
logging.addLevelName(TRACE_LEVEL, "TRACE")
logging.addLevelName(NOTICE_LEVEL, "NOTICE")
logging.addLevelName(FATAL_LEVEL, "FATAL")

LOG_LEVELS = {
    "trace": TRACE_LEVEL,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": NOTICE_LEVEL,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "fatal": FATAL_LEVEL,
}


class ColoredFormatter(logging.Formatter):
    COLORS = {
        "TRACE": "\033[90m",
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "NOTICE": "\033[34m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
        "FATAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


logger = logging.getLogger("FactorioAssistantService")
configured_log_level = os.environ.get("LOG_LEVEL", "info").strip().lower()
logger.setLevel(LOG_LEVELS.get(configured_log_level, logging.INFO))
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logger.level)
handler.setFormatter(ColoredFormatter("[%(levelname)s] %(asctime)s [Factorio Assistant][Service] - %(message)s", datefmt="%H:%M:%S"))
logger.addHandler(handler)


def log_trace(message: str) -> None:
    """Emit trace output for startup and runtime diagnostics."""
    logger.log(TRACE_LEVEL, message)


def log_notice(message: str) -> None:
    """Emit an important normal-priority service message."""
    logger.log(NOTICE_LEVEL, message)


def log_fatal(message: str) -> None:
    """Emit a message for an unrecoverable service failure."""
    logger.log(FATAL_LEVEL, message)


class FactorioAssistantService:

    def __init__(self):
        self.running = True
        self.factorio_ready = threading.Event()
        self.threads = {}
        self.thread_heartbeats = {}
        self._heartbeat_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._persistence_lock = threading.Lock()
        self._known_players_dirty = False

        self.options_path = Path("/data/options.json")
        self.load_options()

        self.share_dir = Path("/share/factorio")
        self.runtime_dir = Path(os.environ.get("FACTORIO_RUNTIME_DIR") or "/config/runtime")
        self.config_dir = Path(os.environ.get("CONFIG_DIR") or "/config")
        self.known_players_path = Path(
            os.environ.get("FACTORIO_PLAYER_PROFILES_PATH") or "/config/player_profiles.json"
        )
        self.telemetry_events_path = self.share_dir / "script-output" / "factorio_assistant_events.jsonl"
        self.installed_mods = self._load_installed_mods()
        self.known_players = self.load_known_players()

        self._configure_mqtt_client()

        log_notice(f"MQTT bridge initialized for broker {self.mqtt_host}:{self.mqtt_port}")
        self.rcon_client = RCONClient(
            host="127.0.0.1",
            port=self.rcon_port,
            password=self.rcon_password,
            logger=logger,
        )
        self.discovered_players = set()
        self.discovered_surfaces = set()
        self._discovered_resource_sites = {}
        self.discovered_combinators = set()
        self.combinator_signals = {}
        self.combinator_control_signals = {}
        self._combinator_state = {}
        self._combinator_discovery_topics = {}
        self._last_player_positions = {}
        try:
            self._telemetry_events_offset = self.telemetry_events_path.stat().st_size
        except OSError:
            self._telemetry_events_offset = 0
        self._surface_attack_until = {}
        self._last_server_state = {}
        self._last_server_diagnostics = {}
        self._last_stats = None
        self._last_mod_snapshot = None
        self._pause_command_state = None
        self._last_ups_sample = None
        self._telemetry_source = "RCON"
        self._entity_attribute_topics = {}
        self._entity_state_topics = {}
        self._entity_command_topics = {}
        self._last_entity_attributes = {}
        self._server_sensor_attributes = {}
        self.mqtt_client.publish(
            f"{self.mqtt_prefix}/sensor/factorio_world/factorio_world_pollution/config",
            "",
            retain=True,
        )
        self.mqtt_client.username_pw_set(self.mqtt_user, self.mqtt_password or "")
        self.mqtt_client.will_set(self._bridge_availability_topic(), "offline", retain=True)
        self.mqtt_client.enable_logger(logger)
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
        self.mqtt_client.on_message = self.on_mqtt_message

    def _configure_mqtt_client(self):
        """Create and configure the Paho MQTT client after options are loaded."""
        self.mqtt_client = mqtt.Client(CallbackAPIVersion.VERSION2)

    def _resolve_rcon_password(self, opts):
        """Resolve the RCON password from explicit options or the runtime environment."""
        password = str(opts.get("rcon_password", "") or "").strip()
        if password:
            return password

        env_password = os.environ.get("RCON_PASS", "").strip()
        if env_password:
            return env_password
        return ""

    def load_options(self):
        """Load runtime options from the Home Assistant add-on config."""
        opts = {}
        if self.options_path.exists():
            try:
                with open(self.options_path, "r") as handle:
                    opts = json.load(handle)
            except Exception as exc:
                logger.warning(f"Failed to load options.json, using defaults: {exc}")

        self._apply_mqtt_options(opts)
        self._apply_topic_settings(opts.get("mqtt_prefix"))
        telemetry_option = opts.get("enable_telemetry_mod", False)
        self.enable_telemetry_mod = telemetry_option is True or str(telemetry_option).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.rcon_port = int(os.environ.get("RCON_PORT") or opts.get("rcon_port") or 27015)
        self.rcon_password = self._resolve_rcon_password(opts)

        profile_name = opts.get("refresh_rate_profile", "medium")
        profiles = {
            "debug": {"fast": 1, "medium": 2, "slow": 10, "pollution_stride": 5},
            "high": {"fast": 10, "medium": 30, "slow": 120, "pollution_stride": 60},
            "fast": {"fast": 15, "medium": 60, "slow": 300, "pollution_stride": 120},
            "medium": {"fast": 30, "medium": 120, "slow": 600, "pollution_stride": 300},
            "slow": {"fast": 60, "medium": 300, "slow": 900, "pollution_stride": 600},
        }
        self.profile = profiles.get(profile_name, profiles["medium"])
        logger.info(f"Loaded configuration profile '{profile_name}': {self.profile}")

    def _apply_mqtt_options(self, opts):
        """Apply the MQTT connection settings from the add-on options with sensible defaults."""
        self.mqtt_host = str(opts.get("mqtt_host") or "").strip() or "core-mosquitto"
        self.mqtt_port = int(opts.get("mqtt_port") or 1883)
        self.mqtt_user = str(opts.get("mqtt_user") or "").strip()
        self.mqtt_password = str(opts.get("mqtt_password") or "").strip()

    def _apply_topic_settings(self, raw_prefix):
        """Configure the single public MQTT prefix used by discovery and entity topics."""
        mqtt_prefix = str(raw_prefix or "homeassistant").strip().strip("/")
        if not mqtt_prefix:
            mqtt_prefix = "homeassistant"
        self.mqtt_prefix = mqtt_prefix

    def _sanitize_discovery_value(self, value):
        """Convert arbitrary usernames into a safe MQTT discovery token."""
        sanitized = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip()).strip("_")
        sanitized = re.sub(r"_+", "_", sanitized).lower()
        return sanitized or "unknown"

    def _bridge_availability_topic(self):
        """Return the MQTT bridge LWT topic."""
        public_base = getattr(self, "mqtt_prefix", "homeassistant")
        return f"{public_base}/sensor/factorio_server/availability"

    def _rcon_availability_topic(self):
        """Return the Factorio server availability topic controlled by RCON telemetry."""
        public_base = getattr(self, "mqtt_prefix", "homeassistant")
        return f"{public_base}/sensor/factorio_server/rcon_availability"

    def _watchdog_state_topic(self):
        """Return the discovered watchdog binary sensor state topic."""
        public_base = getattr(self, "mqtt_prefix", "homeassistant")
        return f"{public_base}/binary_sensor/factorio_server/factorio_server_watchdog/state"

    def _watchdog_attributes_topic(self):
        """Return the discovered watchdog attributes topic."""
        public_base = getattr(self, "mqtt_prefix", "homeassistant")
        return f"{public_base}/binary_sensor/factorio_server/factorio_server_watchdog/attributes"

    def _player_availability_topic(self, username):
        """Return the public availability topic for a player."""
        public_base = getattr(self, "mqtt_prefix", "homeassistant")
        safe_username = self._sanitize_discovery_value(username)
        return f"{public_base}/sensor/factorio_{safe_username}/availability"

    def _is_valid_player_name(self, username):
        """Reject parser placeholders that are not real player names."""
        return bool(str(username or "").strip()) and str(username).strip() != "0"

    def load_known_players(self):
        """Load previously persisted player state."""
        if self.known_players_path.exists():
            try:
                with open(self.known_players_path, "r") as handle:
                    data = json.load(handle)
                    if isinstance(data, dict):
                        cleaned_data = {
                            username: player_data
                            for username, player_data in data.items()
                            if self._is_valid_player_name(username)
                        }
                        if cleaned_data != data:
                            self.known_players = cleaned_data
                            data = cleaned_data
                            self._known_players_dirty = True
                            self.save_known_players()
                    logger.info(f"Loaded known players state for: {list(data.keys())}")
                    return data
            except Exception as exc:
                logger.warning(f"Could not parse player_profiles.json: {exc}")
        return {}

    def save_known_players(self):
        """Persist player state to disk."""
        try:
            with self._state_lock:
                if not self._known_players_dirty:
                    return
                player_state = dict(self.known_players)
            self.known_players_path.parent.mkdir(parents=True, exist_ok=True)
            with self._persistence_lock:
                temporary_path = self.known_players_path.with_suffix(".tmp")
                with open(temporary_path, "w") as handle:
                    json.dump(player_state, handle, indent=2)
                temporary_path.replace(self.known_players_path)
            with self._state_lock:
                self._known_players_dirty = False
            logger.debug("Successfully flushed player_profiles.json state to disk.")
        except Exception as exc:
            logger.error(f"Failed to save known_players.json: {exc}")

    def save_player_snapshot(self, players):
        """Cache the latest player telemetry for local consumers such as the web UI."""
        snapshot_path = self.runtime_dir / "player_snapshot.json"
        temporary_path = snapshot_path.with_suffix(".tmp")
        try:
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"generated_at": time.time(), "players": players}
            with temporary_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"))
            temporary_path.replace(snapshot_path)
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Failed to cache player snapshot: %s", exc)

    def _load_installed_mods(self):
        """Load the installed mod status once when the bridge starts."""
        mod_list_path = self.share_dir / "mods" / "mod-list.json"
        try:
            with mod_list_path.open("r", encoding="utf-8") as handle:
                mod_data = json.load(handle)
            if not isinstance(mod_data, dict):
                raise ValueError("top-level mod list must be an object")
            mods = mod_data.get("mods", [])
            if not isinstance(mods, list):
                raise ValueError("mods must be a list")
            return {
                str(mod.get("name")): bool(mod.get("enabled", False))
                for mod in mods
                if isinstance(mod, dict) and mod.get("name")
            }
        except FileNotFoundError:
            logger.info("Mod list not found at %s", mod_list_path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Failed to parse %s: %s", mod_list_path, exc)
        return {}

    def _update_heartbeat(self, name):
        """Record a worker heartbeat without racing watchdog snapshots."""
        heartbeat_lock = getattr(self, "_heartbeat_lock", None)
        if heartbeat_lock is None:
            self.thread_heartbeats[name] = time.time()
            return
        with heartbeat_lock:
            self.thread_heartbeats[name] = time.time()

    def _remove_heartbeat(self, name):
        """Remove a heartbeat for a worker that completed intentionally."""
        heartbeat_lock = getattr(self, "_heartbeat_lock", None)
        if heartbeat_lock is None:
            self.thread_heartbeats.pop(name, None)
            return
        with heartbeat_lock:
            self.thread_heartbeats.pop(name, None)

    def _heartbeat_snapshot(self):
        """Return a consistent heartbeat snapshot for watchdog evaluation."""
        heartbeat_lock = getattr(self, "_heartbeat_lock", None)
        if heartbeat_lock is None:
            return dict(self.thread_heartbeats)
        with heartbeat_lock:
            return dict(self.thread_heartbeats)

    def _process_snapshot(self):
        """Check supervised child PIDs and verify their command lines."""
        expected_processes = {
            "web": ("web.pid", "web_server.py"),
            "web_api": ("web-api.pid", "web_server.py"),
            "factorio": ("factorio.pid", "/opt/factorio/bin/x64/factorio"),
        }
        snapshot = {}
        for name, (pid_name, command_fragment) in expected_processes.items():
            pid_path = self.runtime_dir / pid_name
            try:
                pid = int(pid_path.read_text(encoding="utf-8").strip())
            except FileNotFoundError:
                snapshot[name] = {"state": "starting"}
                continue
            except (OSError, ValueError):
                snapshot[name] = {"state": "invalid_pid"}
                continue
            try:
                command = (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\x00", b" ").decode()
            except (OSError, UnicodeDecodeError):
                snapshot[name] = {"state": "stopped", "pid": pid}
                continue
            snapshot[name] = {
                "state": "running" if command_fragment in command else "unexpected_command",
                "pid": pid,
            }
        return snapshot

    def publish_players_offline(self):
        """Declare persisted players offline until telemetry confirms a connection."""
        players = set(getattr(self, "known_players", {}).keys())
        players.update(getattr(self, "discovered_players", set()))
        for username in sorted(players):
            if not self._is_valid_player_name(username):
                continue
            self._publish_if_changed(self._player_availability_topic(username), "offline")
            self._publish_if_changed(f"{self.mqtt_prefix}/players/{username}/connected", "false")
            self._publish_if_changed(f"{self.mqtt_prefix}/players/{username}/active", "false")
        if players:
            log_notice(f"Declared {len(players)} known player(s) offline at bridge startup")

    def build_stats_command(self):
        """Create a player-aware Factorio 2.0.77-compatible RCON script that returns server and player state."""
        return r'''/silent-command local ok, payload = pcall(function()
  local players_online = 0
  local player_rows = {}
    local pollution_total = 0
  local surface_names = {}
  local surface_count = 0
    local active_entity_count = 0
  local surface_metrics = {}
  local game_tick = 0
  local game_speed = 0
    local game_tick_paused = false
  local tick_ok, tick_value = pcall(function()
    return game.tick
  end)
  if tick_ok and tick_value ~= nil then
    game_tick = tick_value or 0
  end
  local speed_ok, speed_value = pcall(function()
    return game.speed
  end)
  if speed_ok and speed_value ~= nil then
    game_speed = speed_value or 0
  end
    local paused_ok, paused_value = pcall(function()
        return game.tick_paused
    end)
    if paused_ok and paused_value ~= nil then
        game_tick_paused = paused_value
    end
  for _, surface in pairs(game.surfaces or {}) do
    surface_count = surface_count + 1
    table.insert(surface_names, surface.name)
    surface_metrics[surface.name] = {
    }
  end
  for _, player in pairs(game.players) do
    local connected = player.connected
    if connected then
      players_online = players_online + 1
    end
    local health = 0
    local max_health = 100
    local surface_name = "unknown"
    local x = 0
    local y = 0
    local afk = false

    local success, player_afk = pcall(function()
      return player.afk_time or 0
    end)
    if success then
      afk = (tonumber(player_afk or 0) or 0) > 3600
    end

    local character = nil
    local char_ok, char_value = pcall(function()
      return player.character
    end)
    if char_ok and char_value and char_value.valid then
      character = char_value
    end

    if character then
            local max_health_ok, max_health_value = pcall(function()
                return character.get_max_health()
            end)
            if max_health_ok and tonumber(max_health_value) then
                max_health = tonumber(max_health_value)
            end
      local health_ok, health_value = pcall(function()
        return character.health
      end)
      if health_ok then
        health = health_value or 0
      end

    end

    local position_ok, position_value = pcall(function()
      return player.position
    end)
    if position_ok and position_value then
      local x_ok, x_value = pcall(function()
        return position_value.x
      end)
      if x_ok then
        x = x_value or 0
      end

      local y_ok, y_value = pcall(function()
        return position_value.y
      end)
      if y_ok then
        y = y_value or 0
      end
    end

    local surface_ok, surface_value = pcall(function()
      return player.surface
    end)
    if surface_ok and surface_value and surface_value.name then
      local surface_name_ok, surface_name_value = pcall(function()
        return surface_value.name
      end)
      if surface_name_ok then
        surface_name = surface_name_value or "unknown"
      end
    end

        local deaths = 0

        local armor_name = "none"
        local armor_count = 0
        local armor_ok, armor_inventory = pcall(function()
            return player.get_inventory(defines.inventory.character_armor)
        end)
        if armor_ok and armor_inventory then
            for armor_index = 1, #armor_inventory do
                local armor_stack = armor_inventory[armor_index]
                if armor_stack and armor_stack.valid_for_read then
                    armor_name = armor_stack.name or "none"
                    armor_count = armor_stack.count or 0
                    break
                end
            end
        end

        local inventory_used = 0
        local inventory_total = 0
        local inventory_ok, inventory = pcall(function()
            return player.get_main_inventory()
        end)
        if inventory_ok and inventory then
            inventory_total = #inventory
            for inventory_index = 1, inventory_total do
                local inventory_stack = inventory[inventory_index]
                if inventory_stack and inventory_stack.valid_for_read then
                    inventory_used = inventory_used + 1
                end
            end
        end

        table.insert(player_rows, string.format("%s|%s|%s|%.2f|%.2f|%s|%s|%s|%s|%s|%s|%s|%s", player.name, tostring(connected), surface_name, health, max_health, tostring(afk), tostring(x), tostring(y), tostring(deaths), armor_name, tostring(armor_count), tostring(inventory_used), tostring(inventory_total)))
  end
  local research_name = ""
  local research_progress = 0
    local research_level = 0
    local research_queue = {}
    local technologies_researched = 0
    local technologies_total = 0
    local rockets_launched = 0
  local evolution_factor = 0
  local game_day = 0
  local game_time = 0
  local difficulty = ""
  local map_settings = ""
    local day_night_cycle = false
    local daylight = false
    local daytime = 0
  local force = nil
  local force_ok, force_value = pcall(function()
    return game.forces["player"]
  end)
  if force_ok and force_value ~= nil then
    force = force_value
  end
  if force then
    local current_research = nil
    local queue_ok, queue_value = pcall(function()
            return force.research_queue
    end)
        if queue_ok and queue_value then
            for queue_index, technology in ipairs(queue_value) do
                if technology and technology.name then
                    table.insert(research_queue, technology.name)
                    if queue_index == 1 then
                        current_research = technology
                    end
                end
            end
    end
    if current_research then
      research_name = current_research.name or ""
            research_level = current_research.level or 0
    end
    local research_ok, research_value = pcall(function()
      return force.research_progress
    end)
    if research_ok and research_value ~= nil then
      research_progress = research_value or 0
    end
    local evolution_ok, evolution_value = pcall(function()
            return force.get_evolution_factor()
    end)
    if evolution_ok and evolution_value ~= nil then
      evolution_factor = evolution_value or 0
    end
        local technology_ok, technology_value = pcall(function()
            for _, technology in pairs(force.technologies or {}) do
                technologies_total = technologies_total + 1
                if technology.researched then
                    technologies_researched = technologies_researched + 1
                end
            end
        end)
        if not technology_ok then
            technologies_researched = 0
            technologies_total = 0
        end
        local rockets_ok, rockets_value = pcall(function()
            return force.rockets_launched
        end)
        if rockets_ok and rockets_value ~= nil then
            rockets_launched = rockets_value or 0
        end
  end
  local day_ok, day_value = pcall(function()
    return game.tick
  end)
  if day_ok and day_value ~= nil then
    game_time = day_value or 0
    game_day = math.floor((game_time / 25000) + 1)
  end
    local played_ok, played_value = pcall(function()
        return game.ticks_played
    end)
    if played_ok and played_value ~= nil then
        game_time = math.floor((played_value or 0) / 60)
    end
  local difficulty_ok, difficulty_value = pcall(function()
    return game.difficulty_settings.recipe_difficulty
  end)
  if difficulty_ok and difficulty_value ~= nil then
    difficulty = tostring(difficulty_value or "")
  end
  local map_ok, map_value = pcall(function()
    return game.map_settings
  end)
  if map_ok and map_value ~= nil then
    local enemy_ok, enemy_value = pcall(function()
      return map_value.enemy_evolution.enabled
    end)
    local pollution_ok, pollution_value = pcall(function()
      return map_value.pollution.enabled
    end)
                local surface = game.surfaces.nauvis
                if surface then
                    local freeze_ok, freeze_value = pcall(function() return surface.freeze_daytime end)
                    local daytime_ok, daytime_value = pcall(function() return surface.daytime end)
                    day_night_cycle = freeze_ok and freeze_value ~= true or false
                    daytime = daytime_ok and tonumber(daytime_value) or 0
                    daylight = daytime_ok and daytime_value ~= nil and (daytime_value <= 0.25 or daytime_value >= 0.75) or false
                end
                map_settings = string.format("enemy_evolution=%s; pollution=%s; day_night_cycle=%s; daylight=%s; daytime=%.6f", tostring(enemy_ok and enemy_value ~= nil and enemy_value or false), tostring(pollution_ok and pollution_value ~= nil and pollution_value or false), tostring(day_night_cycle), tostring(daylight), daytime)
  end
  return {
    tick = game_tick,
    speed = game_speed,
    tick_paused = game_tick_paused,
    players_online = players_online,
    pollution = pollution_total,
    research = research_name,
    research_progress = research_progress * 100,
    research_level = research_level,
    research_queue = research_queue,
    technologies_researched = technologies_researched,
    technologies_total = technologies_total,
    rockets_launched = rockets_launched,
    evolution_factor = evolution_factor,
    evolution_progress = evolution_factor * 100,
    game_day = game_day,
    game_time = game_time,
    surface_count = surface_count,
    surface_names = table.concat(surface_names, ","),
    active_entity_count = active_entity_count,
    surfaces = surface_metrics,
    difficulty = difficulty,
    map_settings = map_settings,
    day_night_cycle = day_night_cycle,
    daylight = daylight,
    daytime = daytime,
    players = player_rows
  }
end)
if ok then
    local rendered = payload.tick .. "|" .. payload.speed .. "|" .. payload.players_online .. "|" .. #payload.players .. "|" .. tostring(payload.pollution) .. "|" .. tostring(payload.research) .. "|" .. tostring(payload.research_progress) .. "|" .. tostring(payload.evolution_factor) .. "|" .. tostring(payload.evolution_progress) .. "|" .. tostring(payload.game_day) .. "|" .. tostring(payload.game_time) .. "|" .. tostring(payload.surface_count) .. "|" .. tostring(payload.surface_names) .. "|" .. tostring(payload.active_entity_count) .. "|" .. tostring(payload.difficulty) .. "|" .. tostring(payload.map_settings) .. "|" .. tostring(payload.research_level) .. "|" .. table.concat(payload.research_queue, ",") .. "|" .. tostring(payload.technologies_researched) .. "|" .. tostring(payload.technologies_total) .. "|" .. tostring(payload.rockets_launched) .. "|"
  local surface_entries = {}
  for surface_name, surface_data in pairs(payload.surfaces or {}) do
    table.insert(surface_entries, "")
  end
  rendered = rendered .. table.concat(surface_entries, ";")
  for _, row in ipairs(payload.players) do
    rendered = rendered .. "|" .. row
  end
  rcon.print(rendered)
else
  rcon.print("ERROR|" .. tostring(payload))
end'''

    def build_pollution_command(self):
        """Create a low-frequency RCON query for per-surface pollution."""
        return r'''/silent-command local entries = {} for _, surface in pairs(game.surfaces or {}) do local value = 0 local ok, result = pcall(function() return surface.get_total_pollution() end) if ok and result ~= nil then value = result or 0 end table.insert(entries, string.format("%s:%s", surface.name, value)) end rcon.print(table.concat(entries, ";"))'''

    def read_telemetry_events(self):
        """Consume structured events emitted by the optional companion mod."""
        if not self.enable_telemetry_mod:
            return
        try:
            file_size = self.telemetry_events_path.stat().st_size
            if file_size < self._telemetry_events_offset:
                self._telemetry_events_offset = 0
            with self.telemetry_events_path.open("r", encoding="utf-8") as handle:
                handle.seek(self._telemetry_events_offset)
                lines = handle.readlines()
                self._telemetry_events_offset = handle.tell()
        except FileNotFoundError:
            lines = []
        except OSError as exc:
            logger.warning("Unable to read telemetry event stream: %s", exc)
            lines = []

        self._rotate_telemetry_events()

        for line in lines:
            if len(line.encode("utf-8")) > 256 * 1024:
                logger.warning("Ignoring oversized telemetry event record")
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("Ignoring incomplete telemetry event: %r", line.rstrip())
                continue
            if not isinstance(event.get("event"), str) or not event["event"]:
                logger.debug("Ignoring telemetry record without an event name: %r", line.rstrip())
                continue
            if event["event"] == "state_snapshot":
                snapshot = event.get("server"), event.get("world"), event.get("players")
                if all(isinstance(value, dict) for value in snapshot):
                    self._last_mod_snapshot = {
                        "server": event["server"],
                        "world": event["world"],
                        "players": event["players"],
                        "received_monotonic": time.monotonic(),
                    }
            if event["event"] in {"combinator_snapshot", "combinator_reader_changed"}:
                self._handle_combinator_event(event)
            event["bridge_received_at"] = datetime.now(timezone.utc).isoformat()
            event_payload = json.dumps(event, separators=(",", ":"), ensure_ascii=False)
            try:
                self.mqtt_client.publish(
                    f"{self.mqtt_prefix}/event/factorio",
                    event_payload,
                    retain=False,
                )
                if event.get("event") == "console_chat":
                    self.mqtt_client.publish(
                        f"{self.mqtt_prefix}/event/factorio_console_chat",
                        event_payload,
                        retain=False,
                    )
            except Exception as exc:
                logger.warning("Unable to publish Factorio telemetry event: %s", exc)
            if event.get("event") != "surface_attack":
                continue
            surface_name = str(event.get("surface") or "unknown")
            attack_until = time.monotonic() + 30
            self._surface_attack_until[surface_name] = attack_until
            self.publish_surface_discovery([surface_name])
            self._publish_if_changed(
                f"{self.mqtt_prefix}/world/surfaces/{surface_name}/under_attack",
                "ON",
            )

        now = time.monotonic()
        for surface_name, attack_until in list(self._surface_attack_until.items()):
            if attack_until <= now:
                self._publish_if_changed(
                    f"{self.mqtt_prefix}/world/surfaces/{surface_name}/under_attack",
                    "OFF",
                )
                del self._surface_attack_until[surface_name]

    def _combinator_device_name(self, event):
        label = str(event.get("name") or "").strip()
        unit_number = str(event.get("unit_number") or "unknown")
        return f"Factorio Assistant Sender: {label or unit_number}"

    def _combinator_signal_name(self, signal):
        signal_type = str(signal.get("type") or "virtual")
        name = str(signal.get("name") or "signal")
        quality = str(signal.get("quality") or "normal")
        network = str(signal.get("network") or "unknown")
        return f"{network}_{signal_type}_{name}_{quality}"

    def _combinator_signal_display_name(self, signal):
        name = self._localized_signal_name(signal)
        network = str(signal.get("network") or "unknown").capitalize()
        display_name = f"{name} ({network})"
        return display_name if signal.get("quality", "normal") == "normal" else f"{display_name} ({signal['quality']})"

    def _combinator_control_slots(self):
        return (("red", "Red"), ("green", "Green"))

    def _combinator_control_names(self):
        return tuple(
            (network, label, slot)
            for network, label in self._combinator_control_slots()
            for slot in "ABCD"
        )

    def _localized_signal_name(self, signal):
        """Resolve signal labels from the boot-generated Factorio catalog."""
        name = str(signal.get("name") or "Signal")
        catalog_path = Path("/tmp/factorio-assistant/catalog.json")
        try:
            cache = getattr(self, "_signal_catalog", None)
            if cache is None:
                catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
                cache = {
                    (str(record.get("kind")), str(record.get("name"))): str(record.get("localized_name"))
                    for record in catalog.get("records", [])
                    if isinstance(record, dict) and record.get("localized_name")
                }
                self._signal_catalog = cache
            for kind in (str(signal.get("type") or "virtual"), "item", "fluid", "virtual-signal"):
                localized = cache.get((kind, name))
                if localized:
                    return localized
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
        return name.replace("-", " ").title()

    def _localized_signal_slot_name(self, slot):
        return self._localized_signal_name({"type": "virtual", "name": f"signal-{slot}"})

    def _handle_combinator_event(self, event):
        unit_number = str(event.get("unit_number") or "").strip()
        if not unit_number:
            return
        if event.get("action") == "removed":
            device_id = f"factorio_combinator_{unit_number}"
            for discovery_topic in self._combinator_discovery_topics.pop(unit_number, set()):
                self.mqtt_client.publish(discovery_topic, "", retain=True)
            for key in set(self.combinator_signals.pop(unit_number, {})):
                topic = f"{self.mqtt_prefix}/combinators/{unit_number}/signals/{key}"
                self.mqtt_client.publish(topic, "", retain=True)
                self.mqtt_client.publish(f"{topic}/attributes", "", retain=True)
                self._combinator_state.pop(topic, None)
            for network, _, slot in self._combinator_control_names():
                topic = f"{self.mqtt_prefix}/combinators/{unit_number}/control_signals/{network}/{slot}"
                self.mqtt_client.publish(topic, "", retain=True)
                self.mqtt_client.publish(f"{topic}/attributes", "", retain=True)
                self._combinator_state.pop(topic, None)
                input_topic = f"{self.mqtt_prefix}/combinators/{unit_number}/input_signals/{network}/{slot}"
                self.mqtt_client.publish(input_topic, "", retain=True)
                self.mqtt_client.publish(f"{input_topic}/attributes", "", retain=True)
                self._combinator_state.pop(input_topic, None)
            self.combinator_control_signals.pop(unit_number, None)
            self._publish_combinator_availability(unit_number, "offline")
            self.discovered_combinators.discard(unit_number)
            return
        self._publish_combinator_discovery(event)
        control_signals = event.get("control_signals", {})
        if not isinstance(control_signals, dict):
            control_signals = {}
        current_controls = {}
        for network, _, slot in self._combinator_control_names():
            try:
                value = int(control_signals.get(network, {}).get(slot, 0))
            except (TypeError, ValueError):
                value = 0
            current_controls[f"{network}_{slot}"] = value
            topic = f"{self.mqtt_prefix}/combinators/{unit_number}/control_signals/{network}/{slot}"
            if self._combinator_state.get(topic) != value:
                self.mqtt_client.publish(topic, str(value), retain=True)
                self._combinator_state[topic] = value
            self.mqtt_client.publish(
                f"{topic}/attributes",
                json.dumps({
                    "Signal": f"{network}-signal-{slot}",
                    "Wire network": network,
                    "Signal slot": slot,
                    "Factorio unit number": unit_number,
                    "Surface": event.get("surface", "unknown"),
                    "Position": event.get("position", {}),
                    "Source": "MOD",
                }, separators=(",", ":")),
                retain=True,
            )
        self.combinator_control_signals[unit_number] = current_controls
        input_signals = event.get("input_signals", {})
        if not isinstance(input_signals, dict):
            input_signals = {}
        for network, _, slot in self._combinator_control_names():
            try:
                value = int(input_signals.get(network, {}).get(slot, 0))
            except (TypeError, ValueError):
                value = 0
            topic = f"{self.mqtt_prefix}/combinators/{unit_number}/input_signals/{network}/{slot}"
            if self._combinator_state.get(topic) != value:
                self.mqtt_client.publish(topic, str(value), retain=True)
                self._combinator_state[topic] = value
        current = {}
        for signal in event.get("signals", []) or []:
            if not isinstance(signal, dict) or not signal.get("name"):
                continue
            key = self._combinator_signal_name(signal)
            current[key] = signal
            topic = f"{self.mqtt_prefix}/combinators/{unit_number}/signals/{key}"
            value = signal.get("count", 0)
            if self._combinator_state.get(topic) != value:
                self.mqtt_client.publish(topic, str(value), retain=True)
                self._combinator_state[topic] = value
            attributes = {
                "Signal": signal.get("name"),
                "Signal type": signal.get("type", "virtual"),
                "Quality": signal.get("quality", "normal"),
                "Network": signal.get("network", "unknown"),
                "Placed by": event.get("placed_by", ""),
                "Surface": event.get("surface", "unknown"),
                "Position": event.get("position", {}),
                "Factorio unit number": unit_number,
                "Source": "MOD",
            }
            self.mqtt_client.publish(
                f"{topic}/attributes",
                json.dumps(attributes, separators=(",", ":")),
                retain=True,
            )
        for key in set(self.combinator_signals.get(unit_number, {})) - set(current):
            topic = f"{self.mqtt_prefix}/combinators/{unit_number}/signals/{key}"
            self.mqtt_client.publish(topic, "0", retain=True)
            self._combinator_state[topic] = 0
        self.combinator_signals[unit_number] = current
        self._publish_combinator_availability(unit_number, "online")

    def _publish_combinator_availability(self, unit_number, state):
        self.mqtt_client.publish(
            f"{self.mqtt_prefix}/combinators/{unit_number}/availability",
            state,
            retain=True,
        )

    def _publish_combinator_discovery(self, event):
        unit_number = str(event.get("unit_number") or "").strip()
        if not unit_number:
            return
        device_id = f"factorio_combinator_{unit_number}"
        device = {
            "identifiers": [device_id],
            "name": self._combinator_device_name(event),
            "model": "Factorio Assistant Sender",
            "manufacturer": "Factorio Assistant",
            "via_device": "factorio_space_age_server",
        }
        for signal in event.get("signals", []) or []:
            if not isinstance(signal, dict) or not signal.get("name"):
                continue
            key = self._combinator_signal_name(signal)
            object_id = f"factorio_combinator_{unit_number}_{key}"
            config = {
                "name": self._combinator_signal_display_name(signal),
                "object_id": object_id,
                "unique_id": object_id,
                "state_topic": f"{self.mqtt_prefix}/combinators/{unit_number}/signals/{key}",
                "json_attributes_topic": f"{self.mqtt_prefix}/combinators/{unit_number}/signals/{key}/attributes",
                "state_class": "measurement",
                "icon": "mdi:resistor-nodes",
                "device": device,
                "availability": [
                    {"topic": self._bridge_availability_topic()},
                    {"topic": self._rcon_availability_topic()},
                    {"topic": f"{self.mqtt_prefix}/combinators/{unit_number}/availability"},
                ],
                "availability_mode": "all",
            }
            discovery_topic = f"{self.mqtt_prefix}/sensor/{device_id}/{object_id}/config"
            self.mqtt_client.publish(discovery_topic, json.dumps(config), retain=True)
            self._combinator_discovery_topics.setdefault(unit_number, set()).add(discovery_topic)
        for network, label, slot in self._combinator_control_names():
            object_id = f"factorio_combinator_{unit_number}_{network}_input_{slot.lower()}"
            config = {
                "name": f"{self._localized_signal_slot_name(slot)} ({label}) Input",
                "object_id": object_id,
                "unique_id": object_id,
                "state_topic": f"{self.mqtt_prefix}/combinators/{unit_number}/input_signals/{network}/{slot}",
                "state_class": "measurement",
                "icon": "mdi:transit-connection-variant",
                "device": device,
                "availability": [
                    {"topic": self._bridge_availability_topic()},
                    {"topic": self._rcon_availability_topic()},
                    {"topic": f"{self.mqtt_prefix}/combinators/{unit_number}/availability"},
                ],
                "availability_mode": "all",
            }
            discovery_topic = f"{self.mqtt_prefix}/sensor/{device_id}/{object_id}/config"
            self.mqtt_client.publish(discovery_topic, json.dumps(config), retain=True)
            self._combinator_discovery_topics.setdefault(unit_number, set()).add(discovery_topic)
        for network, label, slot in self._combinator_control_names():
            object_id = f"factorio_combinator_{unit_number}_{network}_signal_{slot.lower()}"
            command_topic = f"{self.mqtt_prefix}/control/combinator/{unit_number}/{network}/signal/{slot}/set"
            config = {
                "name": f"{label} Signal {slot}",
                "object_id": object_id,
                "unique_id": object_id,
                "state_topic": f"{self.mqtt_prefix}/combinators/{unit_number}/control_signals/{network}/{slot}",
                "command_topic": command_topic,
                "json_attributes_topic": f"{self.mqtt_prefix}/combinators/{unit_number}/control_signals/{network}/{slot}/attributes",
                "min": -2147483648,
                "max": 2147483647,
                "step": 1,
                "mode": "box",
                "icon": "mdi:resistor-nodes",
                "device": device,
                "availability": [
                    {"topic": self._bridge_availability_topic()},
                    {"topic": self._rcon_availability_topic()},
                    {"topic": f"{self.mqtt_prefix}/combinators/{unit_number}/availability"},
                ],
                "availability_mode": "all",
            }
            discovery_topic = f"{self.mqtt_prefix}/number/{device_id}/{object_id}/config"
            self.mqtt_client.publish(discovery_topic, json.dumps(config), retain=True)
            self._combinator_discovery_topics.setdefault(unit_number, set()).add(discovery_topic)
            self._entity_command_topics[command_topic] = command_topic
        self.discovered_combinators.add(unit_number)

    def read_mod_stats(self, max_age=45):
        """Return the latest MOD snapshot while it is fresh enough for live state."""
        snapshot = self._last_mod_snapshot
        if not self.enable_telemetry_mod or not snapshot:
            return None
        if time.monotonic() - snapshot.get("received_monotonic", 0) > max_age:
            return None

        server = dict(snapshot.get("server", {}))
        server.setdefault("speed_available", True)
        world = dict(snapshot.get("world", {}))
        surfaces = world.get("surfaces", {})
        if not isinstance(surfaces, dict):
            surfaces = {}
        world["surfaces"] = surfaces
        world["pollution"] = sum(
            float(surface.get("pollution", 0) or 0)
            for surface in surfaces.values()
            if isinstance(surface, dict)
        )
        players = {}
        for username, value in snapshot.get("players", {}).items():
            if not isinstance(value, dict) or not self._is_valid_player_name(username):
                continue
            position = value.get("position", {})
            if not isinstance(position, dict):
                position = {}
            health = normalize_player_health(value)
            players[username] = {
                **value,
                "connected": bool(value.get("connected", False)),
                **health,
                "health": health["current_health"],
                "position": {
                    "x": float(position.get("x", 0) or 0),
                    "y": float(position.get("y", 0) or 0),
                    "surface": str(value.get("surface", "unknown")),
                    "connected": bool(value.get("connected", False)),
                },
                "surface": str(value.get("surface", "unknown")),
            }
        self._telemetry_source = "MOD"
        return {"server": server, "world": world, "players": players}

    def _rotate_telemetry_events(self):
        """Bound the append-only event file while preserving one prior archive."""
        maximum_bytes = 5 * 1024 * 1024
        archive_path = self.telemetry_events_path.with_suffix(".jsonl.1")
        try:
            if self.telemetry_events_path.stat().st_size <= maximum_bytes:
                return
            if archive_path.exists():
                archive_path.unlink()
            self.telemetry_events_path.replace(archive_path)
            self._telemetry_events_offset = 0
            logger.info("Rotated telemetry event stream at %d bytes", maximum_bytes)
        except OSError as exc:
            logger.warning("Unable to rotate telemetry event stream: %s", exc)

    def build_catalog_command(self, query, kind, limit, offset):
        """Create a Factorio 2.0.77-compatible bounded item and recipe catalog query."""
        query_literal = json.dumps(str(query or "").strip().lower())
        kind_literal = json.dumps(kind)
        return f'''/silent-command local query = {query_literal} local kind = {kind_literal} local limit = {int(limit)} local offset = {int(offset)} local function quote(value) local text = tostring(value or "") text = string.gsub(text, "\\\\", "\\\\\\\\") text = string.gsub(text, '"', '\\\\"') text = string.gsub(text, string.char(10), "\\\\n") text = string.gsub(text, string.char(13), "\\\\r") text = string.gsub(text, string.char(9), "\\\\t") return '"' .. text .. '"' end local function boolean(value) return value and "true" or "false" end local function number(value) if value == nil then return "null" end return tostring(value) end local function ref(value) if value then return quote(value.name) end return "null" end local function list(values, include_amount) local encoded = {{}} for _, value in ipairs(values or {{}}) do local entry = '{{"type":' .. quote(value.type) .. ',"name":' .. quote(value.name) .. ',"amount":' .. number(value.amount) if value.amount_min ~= nil then entry = entry .. ',"amount_min":' .. number(value.amount_min) end if value.amount_max ~= nil then entry = entry .. ',"amount_max":' .. number(value.amount_max) end if value.probability ~= nil then entry = entry .. ',"probability":' .. number(value.probability) end if value.temperature ~= nil then entry = entry .. ',"temperature":' .. number(value.temperature) end if value.minimum_temperature ~= nil then entry = entry .. ',"minimum_temperature":' .. number(value.minimum_temperature) end if value.maximum_temperature ~= nil then entry = entry .. ',"maximum_temperature":' .. number(value.maximum_temperature) end entry = entry .. '}}' table.insert(encoded, entry) end return '[' .. table.concat(encoded, ',') .. ']' end local function item_record(prototype) return '{{"kind":"item","name":' .. quote(prototype.name) .. ',"type":' .. quote(prototype.type) .. ',"order":' .. quote(prototype.order) .. ',"group":' .. ref(prototype.group) .. ',"subgroup":' .. ref(prototype.subgroup) .. ',"hidden":' .. boolean(prototype.hidden) .. ',"hidden_in_factoriopedia":' .. boolean(prototype.hidden_in_factoriopedia) .. ',"stack_size":' .. number(prototype.stack_size) .. ',"fuel_category":' .. quote(prototype.fuel_category) .. ',"fuel_value":' .. number(prototype.fuel_value) .. ',"place_result":' .. ref(prototype.place_result) .. ',"burnt_result":' .. ref(prototype.burnt_result) .. ',"spoil_result":' .. ref(prototype.spoil_result) .. '}}' end local function recipe_record(prototype) return '{{"kind":"recipe","name":' .. quote(prototype.name) .. ',"type":' .. quote(prototype.type) .. ',"order":' .. quote(prototype.order) .. ',"group":' .. ref(prototype.group) .. ',"subgroup":' .. ref(prototype.subgroup) .. ',"category":' .. quote(prototype.category) .. ',"additional_categories":' .. list(prototype.additional_categories, false) .. ',"enabled":' .. boolean(prototype.enabled) .. ',"hidden_from_flow_stats":' .. boolean(prototype.hidden_from_flow_stats) .. ',"hidden_from_player_crafting":' .. boolean(prototype.hidden_from_player_crafting) .. ',"energy":' .. number(prototype.energy) .. ',"ingredients":' .. list(prototype.ingredients, true) .. ',"products":' .. list(prototype.products, true) .. '}}' end local function matches(name) return query == "" or string.find(string.lower(name), query, 1, true) ~= nil end local function collect(source, builder) local entries = {{}} for name, prototype in pairs(source) do if matches(name) then table.insert(entries, {{name=name, json=builder(prototype)}}) end end table.sort(entries, function(left, right) return left.name < right.name end) return entries end local items = {{}} local recipes = {{}} if kind == "all" or kind == "item" then items = collect(prototypes.item, item_record) end if kind == "all" or kind == "recipe" then recipes = collect(prototypes.recipe, recipe_record) end local total = #items + #recipes local results = {{}} local skipped = 0 local function append(entries) for _, entry in ipairs(entries) do if skipped < offset then skipped = skipped + 1 elseif #results < limit then table.insert(results, entry.json) end end end append(items) append(recipes) local item_count = 0 for _, entry in ipairs(items) do item_count = item_count + 1 end local recipe_count = 0 for _, entry in ipairs(recipes) do recipe_count = recipe_count + 1 end rcon.print('{{"query":' .. quote(query) .. ',"kind":' .. quote(kind) .. ',"total":' .. tostring(total) .. ',"item_total":' .. tostring(item_count) .. ',"recipe_total":' .. tostring(recipe_count) .. ',"count":' .. tostring(#results) .. ',"offset":' .. tostring(offset) .. ',"limit":' .. tostring(limit) .. ',"results":[' .. table.concat(results, ',') .. ']}}')'''

    def _localized_name(self, localization_prefix, name):
        """Resolve a Factorio localization key while preserving missing values."""
        return ""

    def _localized_resource_name(self, name):
        """Resolve a resource ID from the generated Factorio catalog."""
        resource_name = str(name or "").strip()
        if not resource_name:
            return "Resource"
        known_names = {
            "angels-ore1": "Saphirite",
            "angels-ore2": "Jivolite",
            "angels-ore3": "Stiratite",
            "angels-ore4": "Crotinnium",
            "angels-ore5": "Rubyte",
            "angels-ore6": "Bobmonium",
        }
        if resource_name in known_names:
            return known_names[resource_name]
        try:
            cache = getattr(self, "_resource_catalog", None)
            if cache is None:
                catalog = json.loads(Path("/tmp/factorio-assistant/catalog.json").read_text(encoding="utf-8"))
                cache = {
                    str(record.get("name")): str(record.get("localized_name"))
                    for record in catalog.get("records", [])
                    if isinstance(record, dict)
                    and record.get("kind") == "resource"
                    and record.get("localized_name")
                }
                self._resource_catalog = cache
            localized = cache.get(resource_name)
            if localized and localized != resource_name:
                return localized
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
        return resource_name

    def _research_attributes(self, world):
        """Build localized attributes for the current research and research queue."""
        research_id = str(world.get("research", "") or "")
        queue_ids = [str(item) for item in world.get("research_queue", []) or [] if str(item)]

        def technology_record(technology_id):
            record = {
                "id": technology_id,
                "localization_key": f"technology-name.{technology_id}",
            }
            localized_name = self._localized_name("technology-name", technology_id)
            if localized_name:
                record["localized_name"] = localized_name
            return record

        return {
            "id": research_id,
            "localization_key": f"technology-name.{research_id}" if research_id else "",
            "localized_name": self._localized_name("technology-name", research_id),
            "queue": [technology_record(technology_id) for technology_id in queue_ids],
            "Source": getattr(self, "_telemetry_source", "RCON"),
        }

    def read_pollution_stats(self):
        """Read pollution separately so expensive calculations do not block fast telemetry."""
        payload = self.rcon_client.send_command(self.build_pollution_command())
        if not payload:
            return None
        try:
            surfaces = {}
            for entry in payload.strip().split(";"):
                if not entry or ":" not in entry:
                    continue
                surface_name, value = entry.split(":", 1)
                surfaces[surface_name] = {"pollution": float(value)}
            return {"surfaces": surfaces}
        except (TypeError, ValueError):
            logger.warning("Failed to parse pollution telemetry response: %r", payload)
            return None

    def read_factorio_stats(self, update_ups=True):
        """Read Factorio telemetry over RCON."""
        command = self.build_stats_command()
        log_trace("Querying Factorio server state over RCON")
        payload = self.rcon_client.send_command(command)
        if payload and "Using Lua console commands will disable achievements" in payload:
            log_notice("Factorio requested confirmation for Lua telemetry; retrying the stats command")
            payload = self.rcon_client.send_command(command)
        if not payload:
            log_trace("No RCON response received for Factorio state query")
            return None

        if getattr(self, "_telemetry_source", "RCON") != "RCON":
            log_notice("Telemetry source changed to RCON fallback")
        self._telemetry_source = "RCON"

        text_payload = payload.strip()
        server_data = {}
        normalized_players = {}

        try:
            raw = json.loads(text_payload)
            server_data = raw.get("server", {})
            world_data = raw.get("world", {}) or {}
            player_data = raw.get("players", {})
            for username, pdata in player_data.items():
                if not self._is_valid_player_name(username):
                    log_trace(f"Ignoring invalid RCON player name: {username!r}")
                    continue
                connected = bool(pdata.get("connected", False))
                pos = pdata.get("position", {"x": 0, "y": 0})
                health = normalize_player_health(pdata)
                normalized_players[username] = {
                    "connected": connected,
                    "deaths": int(pdata.get("deaths", 0)),
                    **health,
                    "health": health["current_health"],
                    "idle": bool(pdata.get("idle", False)),
                    "position": {
                        "x": pos.get("x", 0),
                        "y": pos.get("y", 0),
                        "surface": str(pdata.get("surface", "unknown")),
                        "connected": connected,
                    },
                    "surface": str(pdata.get("surface", "unknown")),
                }
        except Exception:
            parts = [item.strip() for item in text_payload.split("|")]
            if parts and parts[-1] == "":
                parts = parts[:-1]
            if len(parts) >= 4:
                try:
                    server_data = {
                        "tick": int(parts[0]),
                        "speed": float(parts[1]),
                        "players_online": int(parts[2]),
                    }
                    player_count = int(parts[3])
                    world_data = {
                        "pollution": 0.0,
                        "research": "",
                        "research_progress": 0.0,
                        "research_level": 0,
                        "research_queue": [],
                        "technologies_researched": 0,
                        "technologies_total": 0,
                        "rockets_launched": 0,
                        "evolution_factor": 0.0,
                        "evolution_progress": 0.0,
                        "game_day": 0,
                        "game_time": "",
                        "surface_count": 0,
                        "surface_names": "",
                        "active_entity_count": 0,
                        "difficulty": "",
                        "map_settings": "",
                        "daytime": 0.0,
                        "surfaces": {},
                    }

                    def _coerce_float(value, default=0.0):
                        try:
                            return float(value)
                        except (TypeError, ValueError):
                            return default

                    def _coerce_int(value, default=0):
                        try:
                            return int(value)
                        except (TypeError, ValueError):
                            return default

                    def _is_number(value):
                        try:
                            float(value)
                            return True
                        except (TypeError, ValueError):
                            return False

                    has_extended_world_payload = (
                        len(parts) >= 21
                        and _is_number(parts[16])
                        and _is_number(parts[18])
                        and _is_number(parts[19])
                        and _is_number(parts[20])
                    )
                    world_candidate = parts[4:21] if has_extended_world_payload else parts[4:16]
                    looks_like_world_payload = (
                        len(parts) >= 16
                        and _is_number(parts[4])
                        and _is_number(parts[6])
                        and _is_number(parts[7])
                        and _is_number(parts[8])
                        and _is_number(parts[9])
                        and _is_number(parts[11])
                        and _is_number(parts[13])
                        and (
                            not parts[15]
                            or parts[15].startswith("enemy_evolution=")
                            or parts[15].startswith("pollution=")
                        )
                    )
                    if looks_like_world_payload:
                        try:
                            world_data = {
                                "pollution": _coerce_float(world_candidate[0]) if len(world_candidate) > 0 else 0.0,
                                "research": world_candidate[1] if len(world_candidate) > 1 else "",
                                "research_progress": _coerce_float(world_candidate[2]) if len(world_candidate) > 2 else 0.0,
                                "research_level": _coerce_int(world_candidate[12]) if has_extended_world_payload and len(world_candidate) > 12 else 0,
                                "research_queue": [item for item in (world_candidate[13].split(",") if has_extended_world_payload and len(world_candidate) > 13 else []) if item],
                                "technologies_researched": _coerce_int(world_candidate[14]) if has_extended_world_payload and len(world_candidate) > 14 else 0,
                                "technologies_total": _coerce_int(world_candidate[15]) if has_extended_world_payload and len(world_candidate) > 15 else 0,
                                "rockets_launched": _coerce_int(world_candidate[16]) if has_extended_world_payload and len(world_candidate) > 16 else 0,
                                "evolution_factor": _coerce_float(world_candidate[3]) if len(world_candidate) > 3 else 0.0,
                                "evolution_progress": _coerce_float(world_candidate[4]) if len(world_candidate) > 4 else 0.0,
                                "game_day": _coerce_int(world_candidate[5]) if len(world_candidate) > 5 else 0,
                                "game_time": world_candidate[6] if len(world_candidate) > 6 else "",
                                "surface_count": _coerce_int(world_candidate[7]) if len(world_candidate) > 7 else 0,
                                "surface_names": world_candidate[8] if len(world_candidate) > 8 else "",
                                "active_entity_count": _coerce_int(world_candidate[9]) if len(world_candidate) > 9 else 0,
                                "difficulty": world_candidate[10] if len(world_candidate) > 10 else "",
                                "map_settings": world_candidate[11] if len(world_candidate) > 11 else "",
                                "surfaces": {},
                            }
                            for setting_name in ("day_night_cycle", "daylight"):
                                setting_match = re.search(
                                    rf"(?:^|;\s*){setting_name}=(true|false)",
                                    world_data["map_settings"],
                                    re.IGNORECASE,
                                )
                                if setting_match:
                                    world_data[setting_name] = setting_match.group(1).lower() == "true"
                            daytime_match = re.search(r"(?:^|;\s*)daytime=([0-9]+(?:\.[0-9]+)?)", world_data["map_settings"], re.IGNORECASE)
                            if daytime_match:
                                world_data["daytime"] = _coerce_float(daytime_match.group(1))
                        except ValueError as exc:
                            logger.warning(f"Failed to parse world fields in plain-text RCON payload: {exc}")

                    offset = 4
                    if looks_like_world_payload:
                        offset = 21 if has_extended_world_payload else 16
                        surface_payload = parts[offset] if len(parts) > offset else ""
                        if len(parts) > offset:
                            offset += 1
                        if surface_payload and ":" in surface_payload:
                            pass
                        else:
                            surface_payload = ""
                    else:
                        surface_payload = ""

                    if surface_payload:
                        surface_map = {}
                        for entry in surface_payload.split(";"):
                            if not entry:
                                continue
                            entry_parts = entry.split(":")
                            if len(entry_parts) >= 2:
                                surface_name = entry_parts[0]
                                try:
                                    surface_map[surface_name] = {"pollution": float(entry_parts[1])}
                                    if len(entry_parts) >= 3:
                                        surface_map[surface_name]["active_entity_count"] = int(entry_parts[2])
                                except ValueError:
                                    continue
                        world_data["surfaces"] = surface_map

                    for _ in range(player_count):
                        if offset + 12 > len(parts):
                            break
                        row_parts = parts[offset:offset + 13]
                        offset += len(row_parts)
                        try:
                            username = row_parts[0]
                            if not self._is_valid_player_name(username):
                                log_trace(f"Ignoring invalid RCON player row name: {username!r}")
                                continue
                            connected = str(row_parts[1]).lower() == "true"
                            surface = row_parts[2] if len(row_parts) > 2 else "unknown"
                            current_health = float(row_parts[3]) if len(row_parts) > 3 else 0.0
                            max_health = float(row_parts[4]) if len(row_parts) > 4 else 100.0
                            health_percent = round((current_health / max_health * 100.0) if max_health > 0 else 0.0, 2)
                            normalized_players[username] = {
                                "connected": connected,
                                "deaths": int(row_parts[8]) if len(row_parts) > 8 else 0,
                                "position": {
                                    "x": float(row_parts[6]) if len(row_parts) > 6 else 0.0,
                                    "y": float(row_parts[7]) if len(row_parts) > 7 else 0.0,
                                    "surface": surface,
                                    "connected": connected,
                                },
                                "surface": surface,
                                "health": current_health,
                                "current_health": current_health,
                                "max_health": max_health,
                                "health_percent": health_percent,
                                "armor": {
                                    "name": row_parts[9] if len(row_parts) > 9 else "none",
                                    "equipment_count": int(row_parts[10]) if len(row_parts) > 10 else 0,
                                },
                                "inventory": {
                                    "used_slots": int(row_parts[11]) if len(row_parts) > 11 else 0,
                                    "total_slots": int(row_parts[12]) if len(row_parts) > 12 else 0,
                                },
                                "idle": str(row_parts[5]).lower() == "true" if len(row_parts) > 5 else False,
                            }
                        except (IndexError, TypeError, ValueError) as exc:
                            logger.warning(f"Skipping malformed player row {row_parts!r}: {exc}")
                            continue
                except ValueError as exc:
                    logger.warning(f"Failed to parse plain-text RCON payload: {exc}")
                    return None
            else:
                logger.warning(f"Failed to parse RCON state payload: {text_payload!r}")
                return None

        current_tick = int(server_data.get("tick", 0) or 0)
        measured_ups = 0.0
        if update_ups:
            current_time = time.monotonic()
            previous_sample = self._last_ups_sample
            if previous_sample is not None:
                previous_tick, previous_time = previous_sample
                elapsed = current_time - previous_time
                tick_delta = current_tick - previous_tick
                if elapsed > 0 and tick_delta >= 0:
                    measured_ups = round(tick_delta / elapsed, 2)
            self._last_ups_sample = (current_tick, current_time)

        world_data = {
            "pollution": float(server_data.get("pollution", world_data.get("pollution", 0.0))),
            "research": str(server_data.get("research", world_data.get("research", ""))),
            "research_progress": float(server_data.get("research_progress", world_data.get("research_progress", 0.0))),
            "research_level": int(server_data.get("research_level", world_data.get("research_level", 0))),
            "research_queue": list(server_data.get("research_queue", world_data.get("research_queue", [])) or []),
            "technologies_researched": int(server_data.get("technologies_researched", world_data.get("technologies_researched", 0))),
            "technologies_total": int(server_data.get("technologies_total", world_data.get("technologies_total", 0))),
            "rockets_launched": int(server_data.get("rockets_launched", world_data.get("rockets_launched", 0))),
            "evolution_factor": float(server_data.get("evolution_factor", world_data.get("evolution_factor", 0.0))),
            "evolution_progress": float(server_data.get("evolution_progress", world_data.get("evolution_progress", 0.0))),
            "game_day": int(server_data.get("game_day", world_data.get("game_day", 0))),
            "game_time": str(server_data.get("game_time", world_data.get("game_time", ""))),
            "surface_count": int(server_data.get("surface_count", world_data.get("surface_count", 0))),
            "surface_names": str(server_data.get("surface_names", world_data.get("surface_names", ""))),
            "active_entity_count": int(server_data.get("active_entity_count", world_data.get("active_entity_count", 0))),
            "has_active_entity_count": any(
                "active_entity_count" in surface_data
                for surface_data in (world_data.get("surfaces", {}) or {}).values()
                if isinstance(surface_data, dict)
            ),
            "surfaces": dict(world_data.get("surfaces", {}) or {}),
            "difficulty": str(server_data.get("difficulty", world_data.get("difficulty", "unknown")) or "unknown"),
            "map_settings": str(server_data.get("map_settings", world_data.get("map_settings", ""))),
        }

        if not world_data:
            world_data = {
                "pollution": float(server_data.get("pollution", 0.0)),
                "research": str(server_data.get("research", "")),
                "research_progress": float(server_data.get("research_progress", 0.0)),
                "research_level": int(server_data.get("research_level", 0)),
                "research_queue": list(server_data.get("research_queue", []) or []),
                "technologies_researched": int(server_data.get("technologies_researched", 0)),
                "technologies_total": int(server_data.get("technologies_total", 0)),
                "rockets_launched": int(server_data.get("rockets_launched", 0)),
                "evolution_factor": float(server_data.get("evolution_factor", 0.0)),
                "evolution_progress": float(server_data.get("evolution_progress", 0.0)),
                "game_day": int(server_data.get("game_day", 0)),
                "game_time": str(server_data.get("game_time", "")),
                "surface_count": int(server_data.get("surface_count", 0)),
                "surface_names": str(server_data.get("surface_names", "")),
                "active_entity_count": int(server_data.get("active_entity_count", 0)),
                "has_active_entity_count": False,
                "surfaces": {},
                "difficulty": str(server_data.get("difficulty", "")),
                "map_settings": str(server_data.get("map_settings", "")),
            }

        return {
            "server": {
                "ups": measured_ups,
                "speed": round(float(server_data.get("speed", 0.0)), 2),
                "speed_available": True,
                "tick_paused": bool(server_data.get("tick_paused", False)),
                "players_online": int(server_data.get("players_online", 0)),
                "tick": int(server_data.get("tick", 0)),
                "difficulty": str(server_data.get("difficulty", world_data.get("difficulty", ""))),
                "map_settings": str(server_data.get("map_settings", world_data.get("map_settings", ""))),
            },
            "world": world_data,
            "players": normalized_players,
        }

    def call_mod_command(self, method, *arguments):
        """Invoke a validated Factorio Assistant command through the mod interface."""
        if not self.enable_telemetry_mod:
            return None

        def lua_literal(value):
            if isinstance(value, bool):
                return "true" if value else "false"
            if isinstance(value, (int, float)):
                return str(value)
            return json.dumps(str(value), ensure_ascii=False)

        argument_text = ",".join(lua_literal(value) for value in arguments)
        command = (
            "/silent-command local ok,result=pcall(remote.call,"
            f"{json.dumps('factorio_assistant')},{json.dumps(str(method))}"
            f"{',' if argument_text else ''}{argument_text});"
            "rcon.print(helpers.table_to_json({ok=ok,result=result}))"
        )
        response = self.rcon_client.send_command(command)
        if response is None:
            return None
        try:
            result = json.loads(response.strip())
        except (TypeError, json.JSONDecodeError):
            return None
        return result if isinstance(result, dict) else None

    def execute_mod_control(self, method, arguments, fallback_command):
        """Use the structured mod command, falling back only when the interface is unavailable."""
        mod_result = self.call_mod_command(method, *arguments)
        if mod_result is not None:
            return bool(mod_result.get("ok")), "MOD", mod_result
        rcon_result = self.rcon_client.send_command(fallback_command)
        return rcon_result is not None, "RCON", rcon_result

    def on_mqtt_connect(self, client, userdata, flags, rc, properties=None):
        """Handle MQTT connect events."""
        if rc == 0:
            logger.info("Connected to MQTT broker successfully.")
            log_trace(f"MQTT connect success: host={self.mqtt_host}:{self.mqtt_port}, user={self.mqtt_user or '<anonymous>'}, flags={flags}")
            client.subscribe(f"{getattr(self, 'mqtt_prefix', 'homeassistant')}/+/+/+/set")
            client.subscribe(f"{getattr(self, 'mqtt_prefix', 'homeassistant')}/control/combinator/+/+/signal/+/set")
            log_trace(f"MQTT subscribed to entity command topics {getattr(self, 'mqtt_prefix', 'homeassistant')}/+/+/+/set")
            client.publish(self._bridge_availability_topic(), "online", retain=True)
            log_trace(f"MQTT published availability topic {self._bridge_availability_topic()}=online")
            try:
                self.publish_discovery()
            except Exception as exc:
                logger.error(f"MQTT discovery publish failed after broker connection: {exc}")
        else:
            logger.error(f"Failed to connect to MQTT broker with code {rc}")
            log_trace(f"MQTT connect failed: host={self.mqtt_host}:{self.mqtt_port}, rc={rc}, flags={flags}")

    def on_mqtt_disconnect(self, client, userdata, disconnect_flags, rc, properties=None):
        """Record broker disconnects while allowing Paho to retry the connection."""
        if rc == 0:
            logger.info("MQTT client disconnected cleanly")
        else:
            logger.warning(f"MQTT broker disconnected unexpectedly with code {rc}; retry will be attempted")
        log_trace(f"MQTT disconnect details: flags={disconnect_flags}, rc={rc}, properties={properties}")

    def on_mqtt_message(self, client, userdata, msg):
        """Receive MQTT control messages."""
        payload = msg.payload.decode("utf-8", errors="ignore").strip()
        log_trace(f"Received MQTT message on {msg.topic}: {payload}")

        internal_topic = getattr(self, "_entity_command_topics", {}).get(msg.topic)
        if not internal_topic:
            logger.warning(f"Ignoring MQTT message outside discovered entity commands: {msg.topic}")
            return

        control_prefix = f"{self.mqtt_prefix}/control/"
        control_name = internal_topic[len(control_prefix):].removesuffix("/set")
        command_topic = f"{self.mqtt_prefix}/control/{control_name}/set"
        if internal_topic != command_topic:
            logger.warning(f"Unknown MQTT control topic: {msg.topic}")
            return

        combinator_match = re.fullmatch(r"combinator/([^/]+)/(red|green)/signal/([A-D])", control_name)
        if combinator_match:
            unit_number, network, slot = combinator_match.groups()
            try:
                value = float(payload)
            except (TypeError, ValueError):
                logger.warning(f"Invalid combinator signal payload: {payload!r}; expected an integer")
                return
            if not value.is_integer() or value < -2147483648 or value > 2147483647:
                logger.warning(f"Invalid combinator signal payload: {payload!r}; expected a signed 32-bit integer")
                return
            result = self.call_mod_command("set_combinator_signal", unit_number, network, slot, int(value))
            if not result or not result.get("ok"):
                logger.error(f"Failed to set combinator {unit_number} signal {slot}: {result}")
                return
            state_topic = f"{self.mqtt_prefix}/combinators/{unit_number}/control_signals/{network}/{slot}"
            self._publish_if_changed(state_topic, int(value), source="MOD")
            self.mqtt_client.publish(
                f"{state_topic}/attributes",
                json.dumps({"Signal": f"{network}-signal-{slot}", "Signal slot": slot, "Wire network": network, "Source": "MOD"}, separators=(",", ":")),
                retain=True,
            )
            logger.info(f"Set combinator {unit_number} signal {slot} to {int(value)} through MOD")
            return

        if control_name == "day_night_cycle_resume":
            if payload.upper() not in {"PRESS", "ON", "TRUE", "1"}:
                logger.warning(f"Invalid day/night cycle button payload: {payload!r}; expected PRESS")
                return
            success, source, result = self.execute_mod_control(
                "set_day_night_cycle",
                (True,),
                "/silent-command for _, surface in pairs(game.surfaces or {}) do surface.freeze_daytime = false end",
            )
            if success:
                self._publish_if_changed(f"{self.mqtt_prefix}/settings/day_night_cycle", "ON", source=source)
                self._publish_source_attribute(f"{self.mqtt_prefix}/settings/day_night_cycle", source)
                logger.info("Resumed the Factorio day/night cycle through %s", source)
            else:
                logger.error("Failed to resume the Factorio day/night cycle")
            return

        if control_name == "daytime":
            try:
                daytime = float(payload)
            except (TypeError, ValueError):
                logger.warning(f"Invalid daytime payload: {payload!r}; expected 0 through 1")
                return
            if not 0 <= daytime <= 1:
                logger.warning(f"Invalid daytime payload: {payload!r}; expected 0 through 1")
                return
            success, source, result = self.execute_mod_control(
                "set_daytime",
                (daytime,),
                f"/silent-command for _, surface in pairs(game.surfaces or {{}}) do surface.daytime = {daytime:g} end",
            )
            if success:
                self._publish_if_changed(f"{self.mqtt_prefix}/world/daytime", daytime, source=source)
                logger.info("Set Factorio time of day to %.3f through %s", daytime, source)
            else:
                logger.error("Failed to set Factorio time of day to %.3f", daytime)
            return

        if control_name == "save":
            success, source, result = self.execute_mod_control(
                "save_game",
                (),
                "/server-save",
            )
            if success:
                logger.info("Triggered Factorio save through %s", source)
            else:
                logger.error("Failed to trigger Factorio save")
            return

        if control_name == "broadcast_chat":
            if not payload:
                logger.warning("Ignoring empty broadcast chat message")
                return
            success, source, result = self.execute_mod_control(
                "broadcast_chat",
                (payload,),
                f"/silent-command game.print({json.dumps(payload)})",
            )
            if success:
                self._publish_if_changed(f"{self.mqtt_prefix}/chat/last_broadcast", payload)
                self._publish_source_attribute(f"{self.mqtt_prefix}/chat/last_broadcast", source)
                logger.info("Broadcast Factorio chat message through %s", source)
            else:
                logger.error("Failed to broadcast Factorio chat message")
            return

        if control_name == "game_speed":
            try:
                speed = float(payload)
            except (TypeError, ValueError):
                logger.warning(f"Invalid game speed payload: {payload!r}; expected 0.1 through 10.0")
                return
            if not 0.1 <= speed <= 10.0:
                logger.warning(f"Invalid game speed payload: {payload!r}; expected 0.1 through 10.0")
                return
            success, source, result = self.execute_mod_control(
                "set_game_speed",
                (speed,),
                f"/silent-command game.speed = {speed:g}",
            )
            if success:
                self._publish_if_changed(f"{self.mqtt_prefix}/world/speed", speed, source=source)
                self._publish_if_changed(
                    f"{self.mqtt_prefix}/settings/pause",
                    "OFF",
                    source=source,
                )
                logger.info("Set Factorio game speed to %s through %s", speed, source)
            else:
                logger.error(f"Failed to set Factorio game speed to {speed:g}")
            return

        if control_name == "pause":
            normalized_payload = payload.upper()
            if normalized_payload not in {"ON", "OFF"}:
                logger.warning(f"Invalid pause payload: {payload!r}; expected ON or OFF")
                return
            paused = normalized_payload == "ON"
            success, source, result = self.execute_mod_control(
                "set_pause",
                (paused,),
                f"/silent-command game.tick_paused = {'true' if paused else 'false'}",
            )
            if success:
                self._pause_command_state = normalized_payload
                self._publish_if_changed(f"{self.mqtt_prefix}/settings/pause", normalized_payload, source=source)
                self._publish_source_attribute(f"{self.mqtt_prefix}/settings/pause", source)
                logger.info("Set Factorio pause to %s through %s", normalized_payload, source)
            else:
                logger.error(f"Failed to set Factorio pause to {normalized_payload}")
            return

        switch_commands = {
            "enemy_evolution": ("set_map_setting", "game.map_settings.enemy_evolution.enabled"),
            "pollution": ("set_map_setting", "game.map_settings.pollution.enabled"),
            "daylight": ("set_daylight", "game.surfaces.nauvis.daytime <= 0.25 or game.surfaces.nauvis.daytime >= 0.75"),
        }
        if control_name not in switch_commands:
            logger.warning(f"Unknown MQTT control topic: {msg.topic}")
            return

        normalized_payload = payload.upper()
        if normalized_payload not in {"ON", "OFF", "TRUE", "FALSE", "1", "0"}:
            logger.warning(f"Invalid payload for {msg.topic}: {payload!r}; expected ON or OFF")
            return

        enabled = normalized_payload in {"ON", "TRUE", "1"}
        method, setting_path = switch_commands[control_name]
        if control_name == "daylight":
            command = f"/silent-command for _, surface in pairs(game.surfaces or {{}}) do surface.daytime = {'0' if enabled else '0.5'}; surface.freeze_daytime = true end; rcon.print('{control_name}=' .. tostring(game.surfaces.nauvis.daytime <= 0.25 or game.surfaces.nauvis.daytime >= 0.75))"
        else:
            command = f"/silent-command {setting_path} = {'true' if enabled else 'false'}; rcon.print('{control_name}=' .. tostring({setting_path}))"
        arguments = (control_name, enabled) if method == "set_map_setting" else (enabled,)
        success, source, result = self.execute_mod_control(method, arguments, command)
        if not success:
            logger.error(f"Failed to apply Factorio control {control_name}={enabled}")
            return

        self._publish_if_changed(
            f"{self.mqtt_prefix}/settings/{control_name}",
            "ON" if enabled else "OFF",
            source=source,
        )
        self._publish_source_attribute(f"{self.mqtt_prefix}/settings/{control_name}", source)
        logger.info("Applied Factorio control %s=%s through %s", control_name, "ON" if enabled else "OFF", source)

    def _register_entity_attributes(self, entity, object_id, component=None, device_id=None):
        """Assign entity-scoped public topics while retaining internal routing keys."""
        public_base = getattr(self, "mqtt_prefix", "homeassistant")
        state_topic = entity.get("state_topic")
        entity_prefix = f"{public_base}/{component}/{device_id}/{object_id}" if component and device_id else f"{public_base}/entity/{object_id}"
        public_state_topic = f"{entity_prefix}/state"
        if state_topic:
            if not hasattr(self, "_entity_state_topics"):
                self._entity_state_topics = {}
            self._entity_state_topics.setdefault(state_topic, set()).add(public_state_topic)
            entity["state_topic"] = public_state_topic

        attributes_topic = entity.get("json_attributes_topic")
        if attributes_topic is None:
            attributes_topic = f"{self.mqtt_prefix}/entity_attributes/{object_id}"
        public_attributes_topic = f"{entity_prefix}/attributes"
        if not hasattr(self, "_entity_attribute_topics"):
            self._entity_attribute_topics = {}
        self._entity_attribute_topics.setdefault(attributes_topic, set()).add(public_attributes_topic)
        if state_topic:
            self._entity_attribute_topics.setdefault(state_topic, set()).add(public_attributes_topic)
        entity["json_attributes_topic"] = public_attributes_topic

        command_topic = entity.get("command_topic")
        if command_topic:
            if not hasattr(self, "_entity_command_topics"):
                self._entity_command_topics = {}
            self._entity_command_topics[f"{entity_prefix}/set"] = command_topic
            entity["command_topic"] = f"{entity_prefix}/set"
        return entity

    def _publish_source_attribute(self, topic, source=None):
        """Publish the source of the latest value for a discovered entity."""
        attributes_topic = getattr(self, "_entity_attribute_topics", {}).get(topic)
        if attributes_topic:
            source = source or getattr(self, "_telemetry_source", "RCON")
            payload = {"Source": source}
            if topic in getattr(self, "_server_sensor_attributes", {}):
                payload.update(self._server_sensor_attributes[topic])
            attribute_topics = attributes_topic if isinstance(attributes_topic, (list, set, tuple)) else [attributes_topic]
            for topic in attribute_topics:
                self.mqtt_client.publish(
                    topic,
                    json.dumps(payload),
                    retain=True,
                )

    def _publish_server_sensor_attributes(self, server, world, diagnostics):
        """Publish attributes specific to each server sensor."""
        rcon_client = self.rcon_client
        rcon_attributes = {
            "host": rcon_client.host,
            "port": rcon_client.port,
            "connected": rcon_client.sock is not None,
            "authentication_configured": bool(rcon_client.password),
            "response_timeout_seconds": rcon_client.response_timeout,
            "last_success_at": rcon_client.last_success_at,
            "last_error": rcon_client.last_error,
            "availability_topic": self._rcon_availability_topic(),
        }
        sensor_attributes = {
            f"{self.mqtt_prefix}/server/ups": {
                "metric": "Factorio updates per second",
                "tick": server.get("tick", 0),
                "speed_available": server.get("speed_available", True),
            },
            f"{self.mqtt_prefix}/server/players_online": {
                "metric": "Connected Factorio players",
                "known_player_count": len(self.known_players),
            },
            f"{self.mqtt_prefix}/server/rcon_status": rcon_attributes,
            f"{self.mqtt_prefix}/server/save_file": {
                "save_directory": "/share/factorio/saves",
                "save_exists": bool(diagnostics.get("save_file")),
                "save_size_bytes": diagnostics.get("save_size", 0),
            },
            f"{self.mqtt_prefix}/server/save_size": {
                "save_file": diagnostics.get("save_file", ""),
                "save_directory": "/share/factorio/saves",
                "save_exists": bool(diagnostics.get("save_file")),
            },
            f"{self.mqtt_prefix}/server/cpu_usage": {
                "process": "factorio",
                "measurement": "Factorio process CPU percentage",
            },
            f"{self.mqtt_prefix}/server/mem_usage": {
                "process": "factorio",
                "measurement": "Factorio process memory percentage",
            },
            f"{self.mqtt_prefix}/server/uptime": {
                "process": "factorio",
                "measurement": "Factorio process uptime seconds",
            },
            f"{self.mqtt_prefix}/server/version": {
                "version": diagnostics.get("version", "unknown"),
                "source": str(self.config_dir / "factorio-current-version.txt"),
            },
            f"{self.mqtt_prefix}/server/mod_count": {
                **self.installed_mods,
            },
            f"{self.mqtt_prefix}/server/difficulty": {
                "difficulty": world.get("difficulty", server.get("difficulty", "")),
                "map_settings": world.get("map_settings", server.get("map_settings", "")),
            },
        }
        self._server_sensor_attributes = {
            topic: attributes
            for topic, attributes in sensor_attributes.items()
            if topic in getattr(self, "_entity_attribute_topics", {})
        }
        source = getattr(self, "_telemetry_source", "RCON")
        for topic, attributes in self._server_sensor_attributes.items():
            self._publish_entity_attributes(topic, json.dumps({"Source": source, **attributes}))

    def _publish_rcon_status_attributes(self, status):
        """Explain the current RCON status on its dedicated entity."""
        rcon_client = self.rcon_client
        attributes = {
            "status": status,
            "host": rcon_client.host,
            "port": rcon_client.port,
            "connected": rcon_client.sock is not None,
            "authentication_configured": bool(rcon_client.password),
            "response_timeout_seconds": rcon_client.response_timeout,
            "last_success_at": rcon_client.last_success_at,
            "last_error": rcon_client.last_error,
            "availability_topic": self._rcon_availability_topic(),
            "Source": getattr(self, "_telemetry_source", "RCON"),
        }
        self._publish_entity_attributes(
            f"{self.mqtt_prefix}/server/rcon_status",
            json.dumps(attributes),
        )

    def _publish_entity_attributes(self, topic, payload):
        """Copy JSON state payloads to the entity-scoped attributes topics."""
        attributes_topic = getattr(self, "_entity_attribute_topics", {}).get(topic)
        if not attributes_topic:
            logger.warning("Skipping unregistered MQTT entity attributes topic: %s", topic)
            return
        attribute_topics = attributes_topic if isinstance(attributes_topic, (list, set, tuple)) else [attributes_topic]
        for target_topic in attribute_topics:
            if self._last_entity_attributes.get(target_topic) == payload:
                continue
            self.mqtt_client.publish(target_topic, payload, retain=True)
            self._last_entity_attributes[target_topic] = payload

    def _wait_for_factorio_ready(self, timeout=1):
        """Wait for startup readiness without blocking lightweight test instances."""
        ready_event = getattr(self, "factorio_ready", None)
        return ready_event is None or ready_event.wait(timeout=timeout)

    def publish_discovery(self):
        """Publish Home Assistant discovery payloads for the server, world surfaces, and known players."""
        logger.info("Publishing Home Assistant MQTT discovery configs...")

        # Rebuild dynamic registrations on every reconnect because the topic
        # maps below are reset before retained discovery is republished.
        self.discovered_surfaces = set()
        self._discovered_resource_sites = {}
        self.discovered_players = set()
        self.known_players = getattr(self, "known_players", {})
        self._last_stats = getattr(self, "_last_stats", None)
        self._entity_attribute_topics = {}
        self._entity_state_topics = {}
        self._entity_command_topics = {}
        self._last_entity_attributes = {}

        server_device = {
            "identifiers": ["factorio_space_age_server"],
            "name": "Factorio Server",
            "model": "Headless Multiplayer",
            "manufacturer": "Wube Software",
        }

        game_device = {
            "identifiers": ["factorio_space_age_game"],
            "name": "Factorio Game",
            "model": "World State",
            "manufacturer": "Wube Software",
            "via_device": "factorio_space_age_server",
        }

        server_sensors: list[dict[str, Any]] = [
            {
                "object_id": "factorio_server_ups",
                "name": "UPS",
                "unique_id": "factorio_server_ups",
                "state_topic": f"{self.mqtt_prefix}/server/ups",
                "unit_of_measurement": "updates/s",
                "state_class": "measurement",
                "icon": "mdi:speedometer",
                "component": "sensor",
            },
            {
                "object_id": "factorio_server_players_online",
                "name": "Active Players",
                "unique_id": "factorio_server_players_online",
                "state_topic": f"{self.mqtt_prefix}/server/players_online",
                "unit_of_measurement": "players",
                "state_class": "measurement",
                "icon": "mdi:account-group",
                "component": "sensor",
            },
            {
                "object_id": "factorio_server_watchdog",
                "name": "Watchdog Status",
                "unique_id": "factorio_server_watchdog",
                "state_topic": self._watchdog_state_topic(),
                "json_attributes_topic": self._watchdog_attributes_topic(),
                "payload_on": "problem",
                "payload_off": "ok",
                "device_class": "problem",
                "icon": "mdi:heart-pulse",
                "component": "binary_sensor",
            },
            {
                "object_id": "factorio_server_rcon_status",
                "name": "RCON Status",
                "unique_id": "factorio_server_rcon_status",
                "state_topic": f"{self.mqtt_prefix}/server/rcon_status",
                "payload_on": "ok",
                "payload_off": "error",
                "device_class": "connectivity",
                "icon": "mdi:lan-connect",
                "component": "binary_sensor",
            },
            {
                "object_id": "factorio_server_save_file",
                "name": "Save File",
                "unique_id": "factorio_server_save_file",
                "state_topic": f"{self.mqtt_prefix}/server/save_file",
                "icon": "mdi:file-cog-outline",
                "entity_category": "diagnostic",
                "component": "sensor",
            },
            {
                "object_id": "factorio_server_save_size",
                "name": "Save Size",
                "unique_id": "factorio_server_save_size",
                "state_topic": f"{self.mqtt_prefix}/server/save_size",
                "unit_of_measurement": "B",
                "state_class": "measurement",
                "icon": "mdi:harddisk",
                "device_class": "data_size",
                "entity_category": "diagnostic",
                "component": "sensor",
            },
            {
                "object_id": "factorio_server_cpu_usage",
                "name": "CPU Usage",
                "unique_id": "factorio_server_cpu_usage",
                "state_topic": f"{self.mqtt_prefix}/server/cpu_usage",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "icon": "mdi:cpu-64-bit",
                "entity_category": "diagnostic",
                "component": "sensor",
            },
            {
                "object_id": "factorio_server_mem_usage",
                "name": "Memory Usage",
                "unique_id": "factorio_server_mem_usage",
                "state_topic": f"{self.mqtt_prefix}/server/mem_usage",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "icon": "mdi:memory",
                "entity_category": "diagnostic",
                "component": "sensor",
            },
            {
                "object_id": "factorio_server_uptime",
                "name": "Uptime",
                "unique_id": "factorio_server_uptime",
                "state_topic": f"{self.mqtt_prefix}/server/uptime",
                "unit_of_measurement": "s",
                "state_class": "measurement",
                "icon": "mdi:timer-outline",
                "device_class": "duration",
                "entity_category": "diagnostic",
                "component": "sensor",
            },
            {
                "object_id": "factorio_server_version",
                "name": "Version",
                "unique_id": "factorio_server_version",
                "state_topic": f"{self.mqtt_prefix}/server/version",
                "value_template": "{{ value }}",
                "icon": "mdi:information-outline",
                "component": "sensor",
            },
            {
                "object_id": "factorio_server_mod_count",
                "name": "Installed Mods",
                "unique_id": "factorio_server_mod_count",
                "default_entity_id": "sensor.factorio_server_installed_mods",
                "state_topic": f"{self.mqtt_prefix}/server/mod_count",
                "unit_of_measurement": "mods",
                "state_class": "measurement",
                "icon": "mdi:puzzle",
                "entity_category": "diagnostic",
                "component": "sensor",
            },
            {
                "object_id": "factorio_server_difficulty",
                "name": "Difficulty",
                "unique_id": "factorio_server_difficulty",
                "state_topic": f"{self.mqtt_prefix}/server/difficulty",
                "value_template": "{{ value }}",
                "icon": "mdi:gamepad-variant-outline",
                "component": "sensor",
            },
        ]

        server_switches: list[dict[str, Any]] = [
            {
                "object_id": "factorio_server_enemy_evolution",
                "name": "Enemy Evolution",
                "unique_id": "factorio_server_enemy_evolution",
                "state_topic": f"{self.mqtt_prefix}/settings/enemy_evolution",
                "command_topic": f"{self.mqtt_prefix}/control/enemy_evolution/set",
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:chart-line-variant",
                "component": "switch",
            },
            {
                "object_id": "factorio_server_pollution",
                "name": "Pollution",
                "unique_id": "factorio_server_pollution",
                "state_topic": f"{self.mqtt_prefix}/settings/pollution",
                "command_topic": f"{self.mqtt_prefix}/control/pollution/set",
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:smog",
                "component": "switch",
            },
            {
                "object_id": "factorio_server_pause",
                "name": "Pause Game",
                "unique_id": "factorio_server_pause",
                "state_topic": f"{self.mqtt_prefix}/settings/pause",
                "command_topic": f"{self.mqtt_prefix}/control/pause/set",
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:pause-circle-outline",
                "component": "switch",
            },
            {
                "object_id": "factorio_server_daylight",
                "name": "Daylight",
                "unique_id": "factorio_server_daylight",
                "state_topic": f"{self.mqtt_prefix}/settings/daylight",
                "command_topic": f"{self.mqtt_prefix}/control/daylight/set",
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:white-balance-sunny",
                "component": "switch",
            },
        ]

        server_buttons: list[dict[str, Any]] = [
            {
                "object_id": "factorio_server_save",
                "name": "Save Game",
                "unique_id": "factorio_server_save",
                "command_topic": f"{self.mqtt_prefix}/control/save/set",
                "payload_press": "PRESS",
                "icon": "mdi:content-save-outline",
                "component": "button",
            },
            {
                "object_id": "factorio_server_day_night_cycle_resume",
                "name": "Resume Day/Night Cycle",
                "unique_id": "factorio_server_day_night_cycle_resume",
                "command_topic": f"{self.mqtt_prefix}/control/day_night_cycle_resume/set",
                "payload_press": "PRESS",
                "icon": "mdi:weather-sunny-clock",
                "component": "button",
            },
        ]

        server_numbers: list[dict[str, Any]] = [
            {
                "object_id": "factorio_server_game_speed",
                "name": "Game Speed",
                "unique_id": "factorio_server_game_speed",
                "state_topic": f"{self.mqtt_prefix}/world/speed",
                "command_topic": f"{self.mqtt_prefix}/control/game_speed/set",
                "min": 0.1,
                "max": 10.0,
                "step": 0.1,
                "mode": "slider",
                "icon": "mdi:speedometer-medium",
                "component": "number",
            },
            {
                "object_id": "factorio_server_time_of_day",
                "name": "Time of Day",
                "unique_id": "factorio_server_time_of_day",
                "state_topic": f"{self.mqtt_prefix}/world/daytime",
                "command_topic": f"{self.mqtt_prefix}/control/daytime/set",
                "min": 0.0,
                "max": 1.0,
                "step": 0.01,
                "mode": "slider",
                "icon": "mdi:weather-sunny",
                "component": "number",
            },
        ]

        server_texts: list[dict[str, Any]] = [
            {
                "object_id": "factorio_server_broadcast_chat",
                "name": "Broadcast Chat",
                "unique_id": "factorio_server_broadcast_chat",
                "command_topic": f"{self.mqtt_prefix}/control/broadcast_chat/set",
                "state_topic": f"{self.mqtt_prefix}/chat/last_broadcast",
                "mode": "text",
                "icon": "mdi:message-text-outline",
                "component": "text",
            },
        ]

        world_sensors: list[dict[str, Any]] = [
            {
                "object_id": "factorio_world_tick",
                "name": "Tick",
                "unique_id": "factorio_world_tick",
                "state_topic": f"{self.mqtt_prefix}/world/tick",
                "unit_of_measurement": "ticks",
                "state_class": "measurement",
                "icon": "mdi:clock-outline",
                "component": "sensor",
            },
            {
                "object_id": "factorio_world_speed",
                "name": "Speed",
                "unique_id": "factorio_world_speed",
                "state_topic": f"{self.mqtt_prefix}/world/speed",
                "state_class": "measurement",
                "icon": "mdi:speedometer-medium",
                "component": "sensor",
            },
            {
                "object_id": "factorio_world_players_online",
                "name": "Players Online",
                "unique_id": "factorio_world_players_online",
                "state_topic": f"{self.mqtt_prefix}/world/players_online",
                "unit_of_measurement": "players",
                "state_class": "measurement",
                "icon": "mdi:account-group-outline",
                "component": "sensor",
            },
            {
                "object_id": "factorio_world_research",
                "name": "Research",
                "unique_id": "factorio_world_research",
                "state_topic": f"{self.mqtt_prefix}/world/research",
                "icon": "mdi:flask-empty-outline",
                "component": "sensor",
            },
            {
                "object_id": "factorio_world_research_progress",
                "name": "Research Progress",
                "unique_id": "factorio_world_research_progress",
                "state_topic": f"{self.mqtt_prefix}/world/research_progress",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "icon": "mdi:progress-check",
                "component": "sensor",
            },
            {
                "object_id": "factorio_world_research_level",
                "name": "Current Research Level",
                "unique_id": "factorio_world_research_level",
                "state_topic": f"{self.mqtt_prefix}/world/research_level",
                "unit_of_measurement": "levels",
                "state_class": "measurement",
                "icon": "mdi:flask-plus-outline",
                "component": "sensor",
            },
            {
                "object_id": "factorio_world_research_queue",
                "name": "Research Queue",
                "unique_id": "factorio_world_research_queue",
                "state_topic": f"{self.mqtt_prefix}/world/research_queue",
                "icon": "mdi:format-list-bulleted",
                "component": "sensor",
            },
            {
                "object_id": "factorio_world_technologies_researched",
                "name": "Technologies Researched",
                "unique_id": "factorio_world_technologies_researched",
                "state_topic": f"{self.mqtt_prefix}/world/technologies_researched",
                "unit_of_measurement": "technologies",
                "state_class": "measurement",
                "icon": "mdi:check-circle-outline",
                "component": "sensor",
            },
            {
                "object_id": "factorio_world_technologies_total",
                "name": "Technologies Total",
                "unique_id": "factorio_world_technologies_total",
                "state_topic": f"{self.mqtt_prefix}/world/technologies_total",
                "unit_of_measurement": "technologies",
                "state_class": "measurement",
                "icon": "mdi:flask-outline",
                "component": "sensor",
            },
            {
                "object_id": "factorio_world_rockets_launched",
                "name": "Rockets Launched",
                "unique_id": "factorio_world_rockets_launched",
                "state_topic": f"{self.mqtt_prefix}/world/rockets_launched",
                "unit_of_measurement": "rockets",
                "state_class": "total_increasing",
                "icon": "mdi:rocket-launch-outline",
                "component": "sensor",
            },
            {
                "object_id": "factorio_world_evolution_factor",
                "name": "Evolution Factor",
                "unique_id": "factorio_world_evolution_factor",
                "state_topic": f"{self.mqtt_prefix}/world/evolution_factor",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "icon": "mdi:chart-bell-curve-cumulative",
                "component": "sensor",
            },
            {
                "object_id": "factorio_world_evolution_progress",
                "name": "Evolution Progress",
                "unique_id": "factorio_world_evolution_progress",
                "state_topic": f"{self.mqtt_prefix}/world/evolution_progress",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "icon": "mdi:progress-wrench",
                "component": "sensor",
            },
            {
                "object_id": "factorio_world_day",
                "name": "Day",
                "unique_id": "factorio_world_day",
                "state_topic": f"{self.mqtt_prefix}/world/game_day",
                "unit_of_measurement": "days",
                "state_class": "measurement",
                "icon": "mdi:calendar-range",
                "component": "sensor",
            },
            {
                "object_id": "factorio_world_time",
                "name": "Time",
                "unique_id": "factorio_world_time",
                "state_topic": f"{self.mqtt_prefix}/world/game_time",
                "unit_of_measurement": "s",
                "device_class": "duration",
                "state_class": "measurement",
                "icon": "mdi:clock-time-eight-outline",
                "component": "sensor",
            },
            {
                "object_id": "factorio_world_surface_count",
                "name": "Surface Count",
                "unique_id": "factorio_world_surface_count",
                "state_topic": f"{self.mqtt_prefix}/world/surface_count",
                "unit_of_measurement": "surfaces",
                "state_class": "measurement",
                "icon": "mdi:map-marker-multiple",
                "component": "sensor",
            },
            {
                "object_id": "factorio_world_surfaces",
                "name": "Surfaces",
                "unique_id": "factorio_world_surfaces",
                "state_topic": f"{self.mqtt_prefix}/world/surface_names",
                "icon": "mdi:layers-outline",
                "component": "sensor",
            },
        ]

        surface_sensors: list[dict[str, Any]] = []
        surfaces = {}
        if self._last_stats and isinstance(self._last_stats, dict):
            surfaces = self._last_stats.get("world", {}).get("surfaces", {}) or {}
        if isinstance(surfaces, dict):
            for surface_name in sorted(surfaces.keys()):
                safe_surface = self._sanitize_discovery_value(surface_name)
                display_surface = str(surface_name).replace("_", " ").title()
                surface_sensors.extend([
                    {
                        "object_id": f"factorio_surface_{safe_surface}_pollution",
                        "name": f"{display_surface}: Pollution",
                        "unique_id": f"factorio_surface_{safe_surface}_pollution",
                        "state_topic": f"{self.mqtt_prefix}/world/surfaces/{surface_name}/pollution",
                        "unit_of_measurement": "pollution",
                        "state_class": "measurement",
                        "icon": "mdi:smog",
                        "component": "sensor",
                    },
                    {
                        "object_id": f"factorio_surface_{safe_surface}_under_attack",
                        "name": f"{display_surface}: Under Attack",
                        "unique_id": f"factorio_surface_{safe_surface}_under_attack",
                        "state_topic": f"{self.mqtt_prefix}/world/surfaces/{surface_name}/under_attack",
                        "payload_on": "ON",
                        "payload_off": "OFF",
                        "device_class": "problem",
                        "icon": "mdi:alert-octagon",
                        "component": "binary_sensor",
                    },
                ])

        for sensor in surface_sensors:
            component = sensor.pop("component")
            object_id = sensor.pop("object_id")
            self._register_entity_attributes(sensor, object_id, component, "factorio_world")
            discovery_topic = f"{self.mqtt_prefix}/{component}/factorio_world/{object_id}/config"
            sensor["device"] = game_device
            sensor["availability"] = [
                {"topic": self._bridge_availability_topic()},
                {"topic": self._rcon_availability_topic()},
            ]
            sensor["availability_mode"] = "all"
            payload = json.dumps(sensor)
            log_trace(f"Publishing surface discovery payload to {discovery_topic}: {payload}")
            self.mqtt_client.publish(discovery_topic, payload, retain=True)
            log_trace(f"Published surface discovery config to {discovery_topic}")

        for sensor in server_sensors:
            component = sensor.pop("component")
            object_id = sensor.pop("object_id")
            self._register_entity_attributes(sensor, object_id, component, "factorio_server")
            discovery_topic = f"{self.mqtt_prefix}/{component}/factorio_server/{object_id}/config"
            sensor["device"] = server_device
            sensor["availability"] = [
                {"topic": self._bridge_availability_topic()},
                {"topic": self._rcon_availability_topic()},
            ]
            sensor["availability_mode"] = "all"
            payload = json.dumps(sensor)
            log_trace(f"Publishing server discovery payload to {discovery_topic}: {payload}")
            self.mqtt_client.publish(discovery_topic, payload, retain=True)
            log_trace(f"Published server discovery config to {discovery_topic}")

        for switch in server_switches:
            component = switch.pop("component")
            object_id = switch.pop("object_id")
            self._register_entity_attributes(switch, object_id, component, "factorio_server")
            discovery_topic = f"{self.mqtt_prefix}/{component}/factorio_server/{object_id}/config"
            switch["device"] = server_device
            switch["availability"] = [
                {"topic": self._bridge_availability_topic()},
                {"topic": self._rcon_availability_topic()},
            ]
            switch["availability_mode"] = "all"
            payload = json.dumps(switch)
            log_trace(f"Publishing server switch discovery payload to {discovery_topic}: {payload}")
            self.mqtt_client.publish(discovery_topic, payload, retain=True)
            log_trace(f"Published server switch discovery config to {discovery_topic}")

        for control in server_buttons + server_numbers + server_texts:
            component = control.pop("component")
            object_id = control.pop("object_id")
            self._register_entity_attributes(control, object_id, component, "factorio_server")
            discovery_topic = f"{self.mqtt_prefix}/{component}/factorio_server/{object_id}/config"
            control["device"] = server_device
            base_availability = [
                {"topic": self._bridge_availability_topic()},
                {"topic": self._rcon_availability_topic()},
            ]
            custom_availability = control.get("availability", [])
            control["availability"] = base_availability + (custom_availability if isinstance(custom_availability, list) else [])
            control["availability_mode"] = "all"
            payload = json.dumps(control)
            log_trace(f"Publishing server {component} discovery payload to {discovery_topic}: {payload}")
            self.mqtt_client.publish(discovery_topic, payload, retain=True)
            if "state_topic" not in control:
                self.mqtt_client.publish(
                    control["json_attributes_topic"],
                    json.dumps({"Source": "RCON"}),
                    retain=True,
                )
            log_trace(f"Published server {component} discovery config to {discovery_topic}")

        for sensor in world_sensors:
            component = sensor.pop("component")
            object_id = sensor.pop("object_id")
            self._register_entity_attributes(sensor, object_id, component, "factorio_world")
            discovery_topic = f"{self.mqtt_prefix}/{component}/factorio_world/{object_id}/config"
            sensor["device"] = game_device
            sensor["availability"] = [
                {"topic": self._bridge_availability_topic()},
                {"topic": self._rcon_availability_topic()},
            ]
            sensor["availability_mode"] = "all"
            payload = json.dumps(sensor)
            log_trace(f"Publishing world discovery payload to {discovery_topic}: {payload}")
            self.mqtt_client.publish(discovery_topic, payload, retain=True)
            log_trace(f"Published world discovery config to {discovery_topic}")

        for username in list(self.known_players.keys()):
            self.publish_player_discovery(username)

        surface_names = []
        if self._last_stats and isinstance(self._last_stats, dict):
            surfaces = self._last_stats.get("world", {}).get("surfaces", {}) or {}
            if isinstance(surfaces, dict):
                surface_names = sorted(surfaces.keys())
        self.publish_surface_discovery(surface_names)

        legacy_topics = [
            f"{self.mqtt_prefix}/sensor/factorio_world/factorio_world_active_entities/config",
            f"{self.mqtt_prefix}/switch/factorio_server/factorio_server_day_night_cycle/config",
        ]
        for surface_name in surface_names:
            safe_surface = self._sanitize_discovery_value(surface_name)
            legacy_topics.append(
                f"{self.mqtt_prefix}/sensor/factorio_world/factorio_surface_{safe_surface}_entities/config"
            )
        for topic in legacy_topics:
            self.mqtt_client.publish(topic, "", retain=True)

    def publish_surface_discovery(self, surface_names):
        """Publish discovery configs for any newly seen world surfaces."""
        if not surface_names:
            return

        for surface_name in sorted(set(surface_names)):
            safe_surface = self._sanitize_discovery_value(surface_name)
            state_topic = f"{self.mqtt_prefix}/world/surfaces/{surface_name}/pollution"
            self.mqtt_client.publish(
                f"{self.mqtt_prefix}/sensor/factorio_world/factorio_surface_{safe_surface}_entities/config",
                "",
                retain=True,
            )
            if (
                surface_name in self.discovered_surfaces
                and state_topic in getattr(self, "_entity_state_topics", {})
            ):
                continue

            display_surface = str(surface_name).replace("_", " ").title()
            sensors: list[dict[str, Any]] = [
                {
                    "object_id": f"factorio_surface_{safe_surface}_pollution",
                    "name": f"{display_surface}: Pollution",
                    "unique_id": f"factorio_surface_{safe_surface}_pollution",
                    "state_topic": state_topic,
                    "unit_of_measurement": "pollution",
                    "state_class": "measurement",
                    "icon": "mdi:smog",
                    "component": "sensor",
                },
                {
                    "object_id": f"factorio_surface_{safe_surface}_under_attack",
                    "name": f"{display_surface}: Under Attack",
                    "unique_id": f"factorio_surface_{safe_surface}_under_attack",
                    "state_topic": f"{self.mqtt_prefix}/world/surfaces/{surface_name}/under_attack",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "device_class": "problem",
                    "icon": "mdi:alert-octagon",
                    "component": "binary_sensor",
                },
            ]

            for sensor in sensors:
                component = sensor.pop("component")
                object_id = sensor.pop("object_id")
                self._register_entity_attributes(sensor, object_id, component, "factorio_world")
                discovery_topic = f"{self.mqtt_prefix}/{component}/factorio_world/{object_id}/config"
                sensor["device"] = {
                    "identifiers": ["factorio_space_age_game"],
                    "name": "Factorio Game",
                    "model": "World State",
                    "manufacturer": "Wube Software",
                    "via_device": "factorio_space_age_server",
                }
                sensor["availability"] = [
                    {"topic": self._bridge_availability_topic()},
                    {"topic": self._rcon_availability_topic()},
                ]
                sensor["availability_mode"] = "all"
                payload = json.dumps(sensor)
                log_trace(f"Publishing surface discovery payload to {discovery_topic}: {payload}")
                self.mqtt_client.publish(discovery_topic, payload, retain=True)
                log_trace(f"Published surface discovery config to {discovery_topic}")

            self.discovered_surfaces.add(surface_name)

    def publish_pinned_resource_discovery(self, surface_name, resources):
        """Publish separate Home Assistant sensors for each pinned DQOL site."""
        if not isinstance(resources, list):
            resources = []
        safe_surface = self._sanitize_discovery_value(surface_name)
        device_id = f"factorio_resource_monitor_{safe_surface}"
        device = {
            "identifiers": [device_id],
            "name": f"Factorio Resource Monitor: {str(surface_name).replace('_', ' ').title()}",
            "model": "Pinned Resource Sites",
            "manufacturer": "Factorio Assistant",
            "via_device": "factorio_space_age_server",
        }
        current_ids = set()
        for resource in resources:
            if not isinstance(resource, dict) or resource.get("id") is None:
                continue
            site_id = str(resource["id"])
            safe_site = self._sanitize_discovery_value(site_id)
            resource_prefix = f"{self.mqtt_prefix}/resource_monitor/{surface_name}/{site_id}"
            display_name = str(resource.get("name") or resource.get("type") or site_id)
            ore_type = resource.get("type_name") or resource.get("type", "")
            if isinstance(ore_type, (list, tuple)) or str(ore_type).startswith("entity-name"):
                ore_type = ""
            if not isinstance(ore_type, str) or not ore_type.strip():
                ore_type = resource.get("type", "")
            ore_type = self._localized_resource_name(resource.get("type") or ore_type)
            position = resource.get("position", {}) or {}
            location = f"{surface_name} ({position.get('x', 0)}, {position.get('y', 0)})"
            attributes = {
                "Site": display_name,
                "Ore type": ore_type,
                "Resource ID": resource.get("type", ""),
                "Initial amount": resource.get("initial_amount", 0),
                "Amount": resource.get("amount", 0),
                "Rate": resource.get("rate", 0),
                "Estimated depletion": None if resource.get("estimated_depletion") is None else float(resource["estimated_depletion"]) / 60,
                "Position": position,
                "Location": location,
                "Source": "MOD",
            }
            for metric in ("amount", "ore_type", "percent_remaining", "location", "estimated_depletion", "rate"):
                legacy_object_id = f"factorio_resource_{safe_surface}_{safe_site}_{metric}"
                legacy_discovery_topic = f"{self.mqtt_prefix}/sensor/{device_id}/{legacy_object_id}/config"
                self.mqtt_client.publish(legacy_discovery_topic, "", retain=True)
            object_id = f"factorio_resource_{safe_surface}_{safe_site}"
            state_topic = f"{resource_prefix}/percent_remaining"
            config = {
                "name": f"{display_name} % Remaining",
                "object_id": object_id,
                "unique_id": object_id,
                "state_topic": state_topic,
                "json_attributes_topic": f"{resource_prefix}/attributes",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "icon": "mdi:percent",
                "device": device,
                "availability": [
                    {"topic": self._bridge_availability_topic()},
                    {"topic": self._rcon_availability_topic()},
                ],
                "availability_mode": "all",
            }
            discovery_topic = f"{self.mqtt_prefix}/sensor/{device_id}/{object_id}/config"
            self.mqtt_client.publish(discovery_topic, json.dumps(config), retain=True)
            self._entity_state_topics[state_topic] = state_topic
            self.mqtt_client.publish(state_topic, str(float(resource.get("percent", 0) or 0) * 100), retain=True)
            attributes_topic = f"{resource_prefix}/attributes"
            self.mqtt_client.publish(attributes_topic, json.dumps(attributes, separators=(",", ":")), retain=True)
            current_ids.add(site_id)

        previous_ids = self._discovered_resource_sites.get(surface_name, set())
        for site_id in previous_ids - current_ids:
            safe_site = self._sanitize_discovery_value(site_id)
            resource_prefix = f"{self.mqtt_prefix}/resource_monitor/{surface_name}/{site_id}"
            for metric in ("amount", "ore_type", "percent_remaining", "location", "estimated_depletion", "rate"):
                object_id = f"factorio_resource_{safe_surface}_{safe_site}_{metric}"
                discovery_topic = f"{self.mqtt_prefix}/sensor/{device_id}/{object_id}/config"
                self.mqtt_client.publish(discovery_topic, "", retain=True)
                state_topic = f"{resource_prefix}/{metric}"
                self.mqtt_client.publish(state_topic, "", retain=True)
                self._entity_state_topics.pop(state_topic, None)
            object_id = f"factorio_resource_{safe_surface}_{safe_site}"
            self.mqtt_client.publish(f"{self.mqtt_prefix}/sensor/{device_id}/{object_id}/config", "", retain=True)
            self._entity_state_topics.pop(f"{resource_prefix}/percent_remaining", None)
            self.mqtt_client.publish(f"{resource_prefix}/attributes", "", retain=True)
        self._discovered_resource_sites[surface_name] = current_ids

    def publish_player_discovery(self, username):
        """Publish discovery config for one player."""
        if not self._is_valid_player_name(username):
            logger.warning(f"Skipping discovery for invalid player name: {username!r}")
            return
        if username in self.discovered_players:
            return

        safe_username = self._sanitize_discovery_value(username)
        device = {
            "identifiers": [f"factorio_player_{safe_username}"],
            "name": f"Factorio Player: {username}",
            "model": "Headless Multiplayer",
            "manufacturer": "Wube Software",
            "via_device": "factorio_space_age_server",
        }

        sensors: list[dict[str, Any]] = [
            {
                "object_id": f"factorio_{safe_username}_connected",
                "name": "Connected",
                "unique_id": f"factorio_{safe_username}_connected",
                "state_topic": f"{self.mqtt_prefix}/players/{username}/connected",
                "payload_on": "true",
                "payload_off": "false",
                "device_class": "connectivity",
                "component": "binary_sensor",
            },
            {
                "object_id": f"factorio_{safe_username}_health",
                "name": "Health",
                "unique_id": f"factorio_{safe_username}_health",
                "state_topic": f"{self.mqtt_prefix}/players/{username}/health",
                "value_template": "{{ value_json.health_percent }}",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "json_attributes_topic": f"{self.mqtt_prefix}/players/{username}/health",
                "icon": "mdi:heart-pulse",
                "component": "sensor",
            },
            {
                "object_id": f"factorio_{safe_username}_injured",
                "name": "Injured",
                "unique_id": f"factorio_{safe_username}_injured",
                "state_topic": f"{self.mqtt_prefix}/players/{username}/injured",
                "payload_on": "true",
                "payload_off": "false",
                "device_class": "problem",
                "icon": "mdi:bandage",
                "component": "binary_sensor",
            },
            {
                "object_id": f"factorio_{safe_username}_motion",
                "name": "Motion",
                "unique_id": f"factorio_{safe_username}_motion",
                "state_topic": f"{self.mqtt_prefix}/players/{username}/motion",
                "payload_on": "true",
                "payload_off": "false",
                "device_class": "motion",
                "icon": "mdi:run-fast",
                "component": "binary_sensor",
            },
            {
                "object_id": f"factorio_{safe_username}_deaths",
                "name": "Deaths",
                "unique_id": f"factorio_{safe_username}_deaths",
                "state_topic": f"{self.mqtt_prefix}/players/{username}/deaths",
                "unit_of_measurement": "deaths",
                "state_class": "total_increasing",
                "icon": "mdi:skull",
                "component": "sensor",
            },
            {
                "object_id": f"factorio_{safe_username}_armor",
                "name": "Armor",
                "unique_id": f"factorio_{safe_username}_armor",
                "state_topic": f"{self.mqtt_prefix}/players/{username}/armor",
                "json_attributes_topic": f"{self.mqtt_prefix}/players/{username}/armor_attributes",
                "icon": "mdi:shield",
                "component": "sensor",
            },
            {
                "object_id": f"factorio_{safe_username}_inventory",
                "name": "Inventory",
                "unique_id": f"factorio_{safe_username}_inventory",
                "state_topic": f"{self.mqtt_prefix}/players/{username}/inventory",
                "json_attributes_topic": f"{self.mqtt_prefix}/players/{username}/inventory_attributes",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "icon": "mdi:package-variant",
                "component": "sensor",
            },
            {
                "object_id": f"factorio_{safe_username}_active",
                "name": "Active",
                "unique_id": f"factorio_{safe_username}_active",
                "state_topic": f"{self.mqtt_prefix}/players/{username}/active",
                "payload_on": "true",
                "payload_off": "false",
                "icon": "mdi:account-check",
                "component": "binary_sensor",
            },
            {
                "object_id": f"factorio_{safe_username}_surface",
                "name": "Surface",
                "unique_id": f"factorio_{safe_username}_surface",
                "state_topic": f"{self.mqtt_prefix}/players/{username}/surface",
                "icon": "mdi:layers-outline",
                "component": "sensor",
            },
        ]

        availability = [
            {"topic": self._bridge_availability_topic()},
            {"topic": self._rcon_availability_topic()},
            {"topic": self._player_availability_topic(username)},
        ]

        for sensor in sensors:
            component = sensor.pop("component")
            object_id = str(sensor.pop("object_id"))
            self._register_entity_attributes(sensor, object_id, component, f"factorio_{safe_username}")
            discovery_topic = f"{self.mqtt_prefix}/{component}/factorio_{safe_username}/{object_id}/config"
            sensor["device"] = device
            # The connected binary sensor must remain available while its state is false.
            if object_id.endswith("_connected"):
                sensor["availability"] = availability[:2]
                sensor["availability_mode"] = "all"
            else:
                sensor["availability"] = availability
                sensor["availability_mode"] = "all"
            payload = json.dumps(sensor)
            log_trace(f"Publishing player discovery payload to {discovery_topic}: {payload}")
            self.mqtt_client.publish(discovery_topic, payload, retain=True)
            log_trace(f"Published player discovery config to {discovery_topic}")

        tracker_config: dict[str, Any] = {
            "name": "Location",
            "object_id": f"factorio_{safe_username}_location",
            "unique_id": f"factorio_{safe_username}_location",
            "state_topic": f"{self.mqtt_prefix}/players/{username}/tracker_state",
            "json_attributes_topic": f"{self.mqtt_prefix}/players/{username}/location",
            "icon": "mdi:map-marker",
            "device": device,
            "availability": availability,
            "availability_mode": "all",
            "component": "sensor",
        }
        tracker_component = tracker_config.pop("component")
        tracker_object_id = tracker_config.pop("object_id")
        self._register_entity_attributes(tracker_config, tracker_object_id, tracker_component, f"factorio_{safe_username}")
        tracker_topic = f"{self.mqtt_prefix}/{tracker_component}/factorio_{safe_username}/{tracker_object_id}/config"
        tracker_payload = json.dumps(tracker_config)
        log_trace(f"Publishing location sensor discovery to {tracker_topic}: {tracker_payload}")
        self.mqtt_client.publish(tracker_topic, tracker_payload, retain=True)
        log_trace(f"Published location sensor discovery to {tracker_topic}")

        self.discovered_players.add(username)
        logger.info(f"Published MQTT discovery configs and tracker for player: {username}")

    def _publish_if_changed(self, topic, value, retain=True, source=None):
        """Publish a changed public topic, using internal keys only for routing."""
        if not hasattr(self, "_last_server_state"):
            self._last_server_state = {}
        previous = self._last_server_state.get(topic)
        if previous != value:
            public_topics = getattr(self, "_entity_state_topics", {}).get(topic, set())
            if not public_topics and (
                topic.endswith("/availability")
                or topic == self._rcon_availability_topic()
                or topic == f"{self.mqtt_prefix}/settings/day_night_cycle"
            ):
                public_topics = {topic}
            if not public_topics:
                registered_public_topics = {
                    public_topic
                    for topics in getattr(self, "_entity_state_topics", {}).values()
                    for public_topic in topics
                }
                if topic in registered_public_topics:
                    public_topics = {topic}
            if not public_topics:
                logger.warning("Skipping unregistered MQTT entity state topic: %s", topic)
                return False
            for public_topic in public_topics:
                self.mqtt_client.publish(public_topic, str(value), retain=retain)
            self._publish_source_attribute(topic, source=source)
            if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
                self._publish_entity_attributes(topic, value)
            self._last_server_state[topic] = value
            return True
        return False

    def _collect_server_diagnostics(self):
        """Collect optional local diagnostics for the Factorio server process and save directory."""
        diagnostics = {
            "save_file": "",
            "save_size": 0,
            "cpu_usage": 0.0,
            "mem_usage": 0.0,
            "uptime": 0,
            "version": "unknown",
            "mod_count": len(self.installed_mods),
        }

        # Prefer the explicit add-on save location provided by the environment.
        candidate_dirs = [Path("/share/factorio/saves")]
        save_files = []
        checked_dir = None
        for candidate in candidate_dirs:
            try:
                if candidate.exists():
                    checked_dir = candidate
                    save_files = sorted(candidate.glob("*.zip")) + sorted(candidate.glob("*.save")) + sorted(candidate.glob("*.dat"))
                    if save_files:
                        break
            except Exception:
                # If any OS-level error happens when inspecting a path, skip it
                continue

        if checked_dir is None:
            logger.debug("No save directory found among candidates: %s", [str(p) for p in candidate_dirs])
        else:
            logger.debug("Checked save directory %s, found %d candidate save files", checked_dir, len(save_files))

        if save_files:
            latest = max(save_files, key=lambda path: path.stat().st_mtime)
            diagnostics["save_file"] = latest.name
            try:
                diagnostics["save_size"] = latest.stat().st_size
            except OSError:
                diagnostics["save_size"] = 0

        if psutil is not None:
            try:
                for proc in psutil.process_iter(["name", "cmdline", "cpu_percent", "memory_percent", "create_time"]):
                    try:
                        name = (proc.info.get("name") or "").lower()
                        cmdline = " ".join(proc.info.get("cmdline") or [])
                        if "factorio" in name or "factorio" in cmdline.lower():
                            diagnostics["cpu_usage"] = round(proc.info.get("cpu_percent") or 0.0, 1)
                            diagnostics["mem_usage"] = round(proc.info.get("memory_percent") or 0.0, 1)
                            diagnostics["uptime"] = int(time.time() - (proc.info.get("create_time") or time.time()))
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        version_response = self.rcon_client.send_command("/version")
        if version_response:
            version_match = re.search(r"\b(\d+\.\d+\.\d+)\b", version_response)
            if version_match:
                diagnostics["version"] = version_match.group(1)

        if diagnostics["version"] == "unknown":
            version_file = self.config_dir / "factorio-current-version.txt"
            if version_file.exists():
                try:
                    diagnostics["version"] = version_file.read_text(encoding="utf-8").strip() or "unknown"
                except Exception:
                    diagnostics["version"] = "unknown"

        return diagnostics

    def fast_telemetry_loop(self, interval):
        while self.running:
            try:
                self._update_heartbeat("fast_telemetry")
                if not self._wait_for_factorio_ready():
                    time.sleep(interval)
                    continue
                self.read_telemetry_events()
                stats = self.read_mod_stats() or self.read_factorio_stats()
                if stats:
                    self._last_stats = stats
                    self.save_player_snapshot(stats.get("players", {}))
                    self._publish_if_changed(self._rcon_availability_topic(), "online")
                log_trace("Fast telemetry cycle started")

                active_player_names = set()
                if stats:
                    active_player_names = {
                        username
                        for username, pdata in stats.get("players", {}).items()
                        if self._is_valid_player_name(username) and bool(pdata.get("connected", False))
                    }

                if stats:
                    server = stats.get("server", {})
                    if server.get("speed_available", True):
                        self._publish_if_changed(f"{self.mqtt_prefix}/server/ups", server.get("ups", 0.0))
                        log_trace(f"Published telemetry topic {self.mqtt_prefix}/server/ups={server.get('ups', 0.0)}")
                    self._publish_if_changed(f"{self.mqtt_prefix}/server/players_online", server.get("players_online", 0))
                    log_trace(f"Published telemetry topic {self.mqtt_prefix}/server/players_online={server.get('players_online', 0)}")
                    self._publish_if_changed(f"{self.mqtt_prefix}/server/rcon_status", "ok")
                    self._publish_rcon_status_attributes("ok")
                    log_trace(f"Published telemetry topic {self.mqtt_prefix}/server/rcon_status=ok")
                    self._publish_if_changed(f"{self.mqtt_prefix}/world/tick", server.get("tick", 0))
                    log_trace(f"Published telemetry topic {self.mqtt_prefix}/world/tick={server.get('tick', 0)}")
                    if server.get("speed_available", True):
                        self._publish_if_changed(f"{self.mqtt_prefix}/world/speed", server.get("speed", 0.0))
                        log_trace(f"Published telemetry topic {self.mqtt_prefix}/world/speed={server.get('speed', 0.0)}")
                        try:
                            game_speed = float(server.get("speed", 0.0) or 0.0)
                        except (TypeError, ValueError):
                            game_speed = 0.0
                        pause_state = self._pause_command_state or (
                            "ON" if server.get("tick_paused", False) else "OFF"
                        )
                        self._publish_if_changed(f"{self.mqtt_prefix}/settings/pause", pause_state)
                    self._publish_if_changed(f"{self.mqtt_prefix}/world/players_online", server.get("players_online", 0))
                    log_trace(f"Published telemetry topic {self.mqtt_prefix}/world/players_online={server.get('players_online', 0)}")

                    world = stats.get("world", {})
                    if world.get("daytime") is not None:
                        self._publish_if_changed(f"{self.mqtt_prefix}/world/daytime", float(world.get("daytime", 0.0) or 0.0))
                    research_attributes = self._research_attributes(world)
                    research_state = research_attributes.get("localized_name") or research_attributes.get("id") or "None"
                    queue_records = research_attributes.get("queue", [])
                    queue_state = ", ".join(
                        record.get("localized_name") or record.get("id", "None")
                        for record in queue_records
                    ) or "Empty"
                    self._publish_if_changed(f"{self.mqtt_prefix}/world/research", research_state)
                    self._publish_if_changed(f"{self.mqtt_prefix}/world/research_progress", world.get("research_progress", 0.0))
                    self._publish_if_changed(f"{self.mqtt_prefix}/world/research_level", world.get("research_level", 0))
                    self._publish_if_changed(f"{self.mqtt_prefix}/world/research_queue", queue_state)
                    self._publish_entity_attributes(
                        f"{self.mqtt_prefix}/world/research",
                        json.dumps(research_attributes, separators=(",", ":")),
                    )
                    self._publish_entity_attributes(
                        f"{self.mqtt_prefix}/world/research_queue",
                        json.dumps(
                            {
                                "queue": research_attributes["queue"],
                                "Source": getattr(self, "_telemetry_source", "RCON"),
                            },
                            separators=(",", ":"),
                        ),
                    )
                    self._publish_if_changed(f"{self.mqtt_prefix}/world/technologies_researched", world.get("technologies_researched", 0))
                    self._publish_if_changed(f"{self.mqtt_prefix}/world/technologies_total", world.get("technologies_total", 0))
                    self._publish_if_changed(f"{self.mqtt_prefix}/world/rockets_launched", world.get("rockets_launched", 0))

                    surfaces = world.get("surfaces", {}) or {}
                    if isinstance(surfaces, dict):
                        self.publish_surface_discovery(list(surfaces.keys()))
                        for surface_name, surface_data in surfaces.items():
                            if isinstance(surface_data, dict):
                                self.publish_pinned_resource_discovery(
                                    surface_name,
                                    surface_data.get("pinned_resources", []),
                                )
                            surface_topic_base = f"{self.mqtt_prefix}/world/surfaces/{surface_name}"
                            self._publish_if_changed(f"{surface_topic_base}/pollution", float(surface_data.get("pollution", 0.0)))

                    for username, pdata in stats.get("players", {}).items():
                        if not self._is_valid_player_name(username):
                            logger.warning(f"Skipping telemetry for invalid player name: {username!r}")
                            continue
                        if username not in self.known_players:
                            self.known_players[username] = {"deaths": 0}
                            self._known_players_dirty = True
                        if username not in self.discovered_players:
                            self.publish_player_discovery(username)

                        connected = str(pdata.get("connected", False)).lower()
                        player_availability = "online" if pdata.get("connected", False) else "offline"
                        self._publish_if_changed(
                            self._player_availability_topic(username),
                            player_availability,
                        )
                        self._publish_if_changed(f"{self.mqtt_prefix}/players/{username}/connected", connected)
                        log_trace(f"Published player topic {self.mqtt_prefix}/players/{username}/connected={connected}")

                        position_payload = {
                            "x": pdata.get("position", {}).get("x", 0),
                            "y": pdata.get("position", {}).get("y", 0),
                            "surface": pdata.get("surface", "unknown"),
                            "connected": pdata.get("connected", False),
                            "Source": getattr(self, "_telemetry_source", "RCON"),
                        }
                        self._publish_entity_attributes(f"{self.mqtt_prefix}/players/{username}/location", json.dumps(position_payload))
                        log_trace(f"Published player topic {self.mqtt_prefix}/players/{username}/location={json.dumps(position_payload)}")
                        location_state = f"({position_payload['x']}, {position_payload['y']})"
                        self._publish_if_changed(f"{self.mqtt_prefix}/players/{username}/tracker_state", location_state)
                        log_trace(f"Published player topic {self.mqtt_prefix}/players/{username}/tracker_state={location_state}")
                        self._publish_if_changed(
                            f"{self.mqtt_prefix}/players/{username}/surface",
                            str(position_payload["surface"]),
                        )
                        log_trace(f"Published player topic {self.mqtt_prefix}/players/{username}/surface={position_payload['surface']}")

                        connected = bool(pdata.get("connected", False))
                        health = normalize_player_health(pdata)
                        current_health = health["current_health"]
                        max_health = health["max_health"]
                        health_percent = health["health_percent"]
                        position_key = (
                            position_payload["surface"],
                            position_payload["x"],
                            position_payload["y"],
                        )
                        previous_position = self._last_player_positions.get(username)
                        player_moving = connected and previous_position is not None and position_key != previous_position
                        if connected:
                            self._last_player_positions[username] = position_key
                        else:
                            self._last_player_positions.pop(username, None)
                        player_injured = connected and health_percent < 100.0
                        armor_payload = pdata.get("armor") or {"name": "none", "equipment_count": 0}
                        inventory_payload = pdata.get("inventory") or {"used_slots": 0, "total_slots": 0}
                        known_profile = {
                            "deaths": int(pdata.get("deaths", 0) or 0),
                            "surface": str(position_payload["surface"]),
                            "x": position_payload["x"],
                            "y": position_payload["y"],
                            "health": current_health,
                            "max_health": max_health,
                            "health_percent": health_percent,
                            "idle": bool(pdata.get("idle", False)),
                            "motion": player_moving,
                            "injured": player_injured,
                            "armor": {
                                "name": str(armor_payload.get("name") or "none"),
                                "equipment_count": int(armor_payload.get("equipment_count", 0) or 0),
                            },
                            "inventory": {
                                "used_slots": int(inventory_payload.get("used_slots", 0) or 0),
                                "total_slots": int(inventory_payload.get("total_slots", 0) or 0),
                            },
                        }
                        existing_profile = self.known_players.get(username, {})
                        if any(existing_profile.get(key) != value for key, value in known_profile.items()):
                            self.known_players[username] = {**existing_profile, **known_profile}
                            self._known_players_dirty = True
                        self._publish_if_changed(
                            f"{self.mqtt_prefix}/players/{username}/motion",
                            str(player_moving).lower(),
                        )
                        self._publish_if_changed(
                            f"{self.mqtt_prefix}/players/{username}/injured",
                            str(player_injured).lower(),
                        )
                        health_payload = {
                            "current_health": current_health,
                            "max_health": max_health,
                            "health_percent": health_percent,
                            "surface": pdata.get("surface", "unknown"),
                            "status": "offline" if not connected else ("alive" if current_health > 0 else "dead"),
                            "Source": getattr(self, "_telemetry_source", "RCON"),
                        }
                        self._publish_if_changed(f"{self.mqtt_prefix}/players/{username}/health", json.dumps(health_payload))
                        log_trace(f"Published player topic {self.mqtt_prefix}/players/{username}/health={json.dumps(health_payload)}")

                        self._publish_if_changed(f"{self.mqtt_prefix}/players/{username}/deaths", str(pdata.get("deaths", 0)))
                        log_trace(f"Published player topic {self.mqtt_prefix}/players/{username}/deaths={pdata.get('deaths', 0)}")
                        armor_payload = {**armor_payload, "Source": getattr(self, "_telemetry_source", "RCON")}
                        armor_state = str(armor_payload.get("name") or "none")
                        if armor_payload.get("equipment_count", 0) == 0:
                            armor_state = "none"
                        self._publish_if_changed(f"{self.mqtt_prefix}/players/{username}/armor", armor_state)
                        self._publish_entity_attributes(f"{self.mqtt_prefix}/players/{username}/armor_attributes", json.dumps(armor_payload))
                        log_trace(f"Published player topic {self.mqtt_prefix}/players/{username}/armor={armor_state}")

                        inventory_payload = {**inventory_payload, "Source": getattr(self, "_telemetry_source", "RCON")}
                        total_slots = max(int(inventory_payload.get("total_slots", 0) or 0), 1)
                        used_slots = int(inventory_payload.get("used_slots", 0) or 0)
                        inventory_percent = round((used_slots / total_slots) * 100.0, 1) if total_slots else 0.0
                        inventory_state = round(inventory_percent, 1)
                        if total_slots <= 0:
                            inventory_state = 0.0
                        self._publish_if_changed(f"{self.mqtt_prefix}/players/{username}/inventory", inventory_state)
                        self._publish_entity_attributes(f"{self.mqtt_prefix}/players/{username}/inventory_attributes", json.dumps(inventory_payload))
                        log_trace(f"Published player topic {self.mqtt_prefix}/players/{username}/inventory={inventory_state}")
                        # Publish active state (not idle) so ON means player is active
                        active_state = not bool(pdata.get("idle", False))
                        self._publish_if_changed(f"{self.mqtt_prefix}/players/{username}/active", str(active_state).lower())
                        log_trace(f"Published player topic {self.mqtt_prefix}/players/{username}/active={str(active_state).lower()}")

                if stats:
                    for known_username in list(self.known_players.keys()):
                        if known_username in active_player_names:
                            self._publish_if_changed(self._player_availability_topic(known_username), "online")
                        else:
                            self._publish_if_changed(self._player_availability_topic(known_username), "offline")

                self.save_known_players()
                if not stats:
                    self._publish_if_changed(self._rcon_availability_topic(), "offline")
            except Exception as exc:
                self._publish_if_changed(self._rcon_availability_topic(), "offline")
                self._publish_if_changed(f"{self.mqtt_prefix}/server/rcon_status", "error")
                self._publish_rcon_status_attributes("error")
                logger.error(f"Error in fast telemetry loop: {exc}")
            time.sleep(interval)

    def medium_telemetry_loop(self, interval, pollution_stride):
        """Publish lower-frequency telemetry and keep state fresh."""
        while self.running:
            try:
                self._update_heartbeat("medium_telemetry")
                if not self._wait_for_factorio_ready():
                    time.sleep(interval)
                    continue
                stats = None
                if hasattr(self, "_last_stats") and self._last_stats:
                    stats = self._last_stats
                elif hasattr(self, "read_factorio_stats") and hasattr(self, "rcon_client"):
                    stats = self.read_factorio_stats(update_ups=False)
                if stats:
                    self._last_stats = stats
                    world = stats.get("world", {}) or {}
                    server = stats.get("server", {}) or {}
                    self._publish_if_changed(f"{self.mqtt_prefix}/world/game_day", world.get("game_day", 0))
                    self._publish_if_changed(f"{self.mqtt_prefix}/world/game_time", world.get("game_time", ""))
                    daytime = world.get("daytime")
                    if daytime is None:
                        daytime_match = re.search(r"(?:^|;\s*)daytime=([0-9]+(?:\.[0-9]+)?)", str(world.get("map_settings", "")), re.IGNORECASE)
                        daytime = float(daytime_match.group(1)) if daytime_match else None
                    if daytime is not None:
                        self._publish_if_changed(f"{self.mqtt_prefix}/world/daytime", float(daytime))
                    self._publish_if_changed(f"{self.mqtt_prefix}/world/surface_count", world.get("surface_count", 0))
                    self._publish_if_changed(f"{self.mqtt_prefix}/world/surface_names", world.get("surface_names", ""))
                    surfaces = world.get("surfaces", {}) or {}
                    if isinstance(surfaces, dict):
                        self.publish_surface_discovery(list(surfaces.keys()))
                        for surface_name, surface_data in surfaces.items():
                            surface_topic_base = f"{self.mqtt_prefix}/world/surfaces/{surface_name}"
                            self._publish_if_changed(f"{surface_topic_base}/pollution", float(surface_data.get("pollution", 0.0)))
                    # Convert evolution factor (0..1) to percent for Home Assistant
                    try:
                        ef = float(world.get("evolution_factor", 0.0) or 0.0)
                    except Exception:
                        ef = 0.0
                    self._publish_if_changed(f"{self.mqtt_prefix}/world/evolution_factor", round(ef * 100.0, 2))
                    self._publish_if_changed(f"{self.mqtt_prefix}/world/evolution_progress", world.get("evolution_progress", 0.0))
                    difficulty = str(world.get("difficulty", server.get("difficulty", "")) or "unknown")
                    self._publish_if_changed(f"{self.mqtt_prefix}/server/difficulty", difficulty)
                    map_settings = str(world.get("map_settings", server.get("map_settings", "")))
                    for setting_name in ("enemy_evolution", "pollution", "day_night_cycle", "daylight"):
                        setting_value = world.get(setting_name)
                        if setting_value is None:
                            setting_match = re.search(rf"(?:^|;\s*){setting_name}=(true|false)", map_settings, re.IGNORECASE)
                            if setting_match:
                                setting_value = setting_match.group(1).lower() == "true"
                        if setting_value is not None:
                            self._publish_if_changed(
                                f"{self.mqtt_prefix}/settings/{setting_name}",
                                "ON" if bool(setting_value) else "OFF",
                            )

                diagnostics = self._collect_server_diagnostics()
                self._publish_if_changed(f"{self.mqtt_prefix}/server/save_file", diagnostics["save_file"], source="RCON diagnostics")
                self._publish_if_changed(f"{self.mqtt_prefix}/server/save_size", diagnostics["save_size"], source="RCON diagnostics")
                self._publish_if_changed(f"{self.mqtt_prefix}/server/cpu_usage", diagnostics["cpu_usage"], source="RCON diagnostics")
                self._publish_if_changed(f"{self.mqtt_prefix}/server/mem_usage", diagnostics["mem_usage"], source="RCON diagnostics")
                self._publish_if_changed(f"{self.mqtt_prefix}/server/uptime", diagnostics["uptime"], source="RCON diagnostics")
                self._publish_if_changed(f"{self.mqtt_prefix}/server/version", diagnostics["version"], source="RCON diagnostics")
                self._publish_if_changed(f"{self.mqtt_prefix}/server/mod_count", diagnostics["mod_count"], source="RCON diagnostics")
                self._publish_server_sensor_attributes(server, world, diagnostics)
                self.save_known_players()
            except Exception as exc:
                logger.error(f"Error in medium telemetry loop: {exc}")
            time.sleep(interval)

    def bootstrap_loop(self):
        """Run one-time startup checks and confirm the server is reachable over RCON."""
        while self.running:
            try:
                self._update_heartbeat("bootstrap")
                logger.info(f"Waiting {RCON_STARTUP_DELAY}s before probing Factorio RCON")
                time.sleep(RCON_STARTUP_DELAY)
                if not self.running:
                    return
                logger.info("Waiting for Factorio RCON port to become available")
                response = self.rcon_client.send_command("/version")
                if response is not None:
                    self.factorio_ready.set()
                    logger.info(f"Factorio RCON port is ready; starting telemetry collection (version response: {response.strip()!r})")
                    self._remove_heartbeat("bootstrap")
                    return
                logger.warning(
                    "Factorio RCON is unavailable; telemetry remains paused (%s)",
                    self.rcon_client.last_error or "no response",
                )
            except Exception as exc:
                logger.error(f"Error in bootstrap loop: {exc}")
                self.factorio_ready.clear()
            time.sleep(2)

    def slow_telemetry_loop(self, interval):
        """Run infrequent environmental telemetry and lightweight background work."""
        while self.running:
            try:
                self._update_heartbeat("slow_telemetry")
                if self._wait_for_factorio_ready():
                    pollution_stats = self.read_pollution_stats()
                    if pollution_stats:
                        surfaces = pollution_stats.get("surfaces", {})
                        if isinstance(surfaces, dict):
                            self.publish_surface_discovery(list(surfaces.keys()))
                            for surface_name, surface_data in surfaces.items():
                                surface_topic_base = f"{self.mqtt_prefix}/world/surfaces/{surface_name}"
                                self._publish_if_changed(
                                    f"{surface_topic_base}/pollution",
                                    float(surface_data.get("pollution", 0.0)),
                                )
            except Exception as exc:
                logger.error(f"Error in slow telemetry loop: {exc}")
            time.sleep(interval)

    def maintenance_loop(self, interval):
        """Keep the maintenance worker alive without relying on any optional mod integration."""
        while self.running:
            try:
                self._update_heartbeat("maintenance")
            except Exception as exc:
                logger.error(f"Error in maintenance loop: {exc}")
            time.sleep(interval)

    def watchdog_loop(self, interval):
        """Monitor worker heartbeat freshness and publish watchdog state."""
        thread_limits = {
            "bootstrap": self.profile["slow"] * 3,
            "fast_telemetry": self.profile["fast"] * 4,
            "medium_telemetry": self.profile["medium"] * 4,
            "slow_telemetry": self.profile["slow"] * 3,
            "maintenance": 3600 * 2,
            "watchdog": interval * 4,
        }
        previous_unhealthy_threads = set()
        previous_unhealthy_processes = set()

        def publish_watchdog_state(unhealthy_threads, process_snapshot, unhealthy_processes):
            heartbeat_snapshot = self._heartbeat_snapshot()
            heartbeat_age_seconds = {
                name: round(max(0.0, time.time() - last_beat), 1)
                for name, last_beat in heartbeat_snapshot.items()
            }
            heartbeat_limits_seconds = {
                name: thread_limits.get(name, 60)
                for name in heartbeat_snapshot
            }
            if unhealthy_threads or unhealthy_processes:
                self._publish_if_changed(self._watchdog_state_topic(), "problem")
                attributes_payload = json.dumps({
                    "healthy": False,
                    "stale_threads": unhealthy_threads,
                    "stale_processes": unhealthy_processes,
                    "processes": process_snapshot,
                    "heartbeat_age_seconds": heartbeat_age_seconds,
                    "heartbeat_limits_seconds": heartbeat_limits_seconds,
                    "worker_count": len(heartbeat_snapshot),
                    "checked_at": time.time(),
                    "Source": "RCON diagnostics",
                })
            else:
                self._publish_if_changed(self._watchdog_state_topic(), "ok")
                attributes_payload = json.dumps({
                    "healthy": True,
                    "stale_threads": [],
                    "stale_processes": [],
                    "processes": process_snapshot,
                    "heartbeat_age_seconds": heartbeat_age_seconds,
                    "heartbeat_limits_seconds": heartbeat_limits_seconds,
                    "worker_count": len(heartbeat_snapshot),
                    "checked_at": time.time(),
                    "Source": "RCON diagnostics",
                })
            self._publish_entity_attributes(self._watchdog_attributes_topic(), attributes_payload)
            try:
                snapshot_path = self.runtime_dir / "watchdog_snapshot.json"
                snapshot_path.write_text(attributes_payload, encoding="utf-8")
            except OSError:
                pass

        while self.running:
            try:
                self._update_heartbeat("watchdog")
                now = time.time()
                unhealthy_threads = []
                for name, last_beat in self._heartbeat_snapshot().items():
                    limit = thread_limits.get(name, 60)
                    if now - last_beat > limit:
                        unhealthy_threads.append(name)
                unhealthy_thread_set = set(unhealthy_threads)
                for name in sorted(unhealthy_thread_set - previous_unhealthy_threads):
                    last_beat = self._heartbeat_snapshot().get(name, now)
                    logger.warning(f"Worker thread '{name}' appears frozen (no heartbeat for {int(now - last_beat)}s).")
                for name in sorted(previous_unhealthy_threads - unhealthy_thread_set):
                    logger.info(f"Worker thread '{name}' heartbeat recovered.")
                previous_unhealthy_threads = unhealthy_thread_set
                process_snapshot = self._process_snapshot()
                unhealthy_process_set = {
                    name for name, status in process_snapshot.items()
                    if status.get("state") not in {"starting", "running"}
                }
                for name in sorted(unhealthy_process_set - previous_unhealthy_processes):
                    logger.warning("Supervised process '%s' is %s.", name, process_snapshot[name]["state"])
                for name in sorted(previous_unhealthy_processes - unhealthy_process_set):
                    logger.info("Supervised process '%s' is running again.", name)
                previous_unhealthy_processes = unhealthy_process_set
                publish_watchdog_state(unhealthy_threads, process_snapshot, sorted(unhealthy_process_set))
            except Exception as exc:
                logger.error(f"Error in watchdog loop: {exc}")
                publish_watchdog_state(["watchdog"], {}, ["watchdog"])
            time.sleep(interval)

    def start(self):
        """Start the MQTT connection, launch worker threads, and keep the bridge running."""
        logger.info("Starting Factorio RCON bridge service...")

        logger.info("Connecting to MQTT broker...")
        log_trace(f"Attempting MQTT connect to {self.mqtt_host}:{self.mqtt_port} with user={self.mqtt_user or '<anonymous>'}")
        try:
            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, 60)
        except Exception as exc:
            logger.error(f"Initial MQTT connection failed; continuing with RCON readiness and retry loop: {exc}")
        log_trace(f"MQTT connect call completed for {self.mqtt_host}:{self.mqtt_port}")
        self.mqtt_client.loop_start()
        log_trace("MQTT loop started")
        self.mqtt_client.publish(self._bridge_availability_topic(), "online", retain=True)
        log_trace(f"Published bridge availability topic {self._bridge_availability_topic()}=online")
        self.publish_discovery()
        watchdog_state_topic = self._watchdog_state_topic()
        watchdog_attributes_topic = self._watchdog_attributes_topic()
        self._publish_if_changed(watchdog_state_topic, "ok")
        log_trace(f"Published bridge watchdog state {watchdog_state_topic}=ok")
        self._publish_entity_attributes(
            watchdog_attributes_topic,
            json.dumps({"healthy": True, "stale_threads": [], "Source": "RCON diagnostics"}),
        )
        log_trace(f"Published bridge watchdog attributes {watchdog_attributes_topic}={{healthy: true, stale_threads: []}}")
        self._publish_if_changed(self._rcon_availability_topic(), "offline")
        mod_count_topic = f"{self.mqtt_prefix}/server/mod_count"
        self._publish_if_changed(mod_count_topic, len(self.installed_mods), source="mod-list.json")
        self.publish_players_offline()

        loops = [
            ("bootstrap", lambda: self.bootstrap_loop()),
            ("fast_telemetry", lambda: self.fast_telemetry_loop(self.profile["fast"])),
            ("medium_telemetry", lambda: self.medium_telemetry_loop(self.profile["medium"], self.profile["pollution_stride"])),
            ("slow_telemetry", lambda: self.slow_telemetry_loop(self.profile["slow"])),
            ("maintenance", lambda: self.maintenance_loop(3600)),
            ("watchdog", lambda: self.watchdog_loop(15)),
        ]

        for name, target_func in loops:
            logger.info(f"Starting worker thread: {name}")
            thread = threading.Thread(target=target_func, daemon=True)
            self.threads[name] = thread
            self._update_heartbeat(name)
            thread.start()
            logger.debug(f"Worker thread started: {name} (daemon={thread.daemon})")

        log_notice("All bridge worker threads started; watchdog monitoring is active")

        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        """Stop the bridge cleanly and publish an offline availability message."""
        logger.info("Stopping Factorio RCON bridge service...")
        self.running = False
        self.save_known_players()
        if hasattr(self, "rcon_client") and self.rcon_client:
            close_method = getattr(self.rcon_client, "close", None)
            if callable(close_method):
                close_method()
        try:
            known_players = set(getattr(self, "known_players", {}).keys())
            discovered_players = set(getattr(self, "discovered_players", set()))
            for username in sorted(known_players | discovered_players):
                self.mqtt_client.publish(self._player_availability_topic(username), "offline", retain=True)
            self.mqtt_client.publish(self._bridge_availability_topic(), "offline", retain=True)
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        except Exception as exc:
            logger.warning(f"Failed to complete MQTT shutdown cleanup: {exc}")
        logger.info("Factorio RCON bridge stopped successfully.")


if __name__ == "__main__":
    try:
        service = FactorioAssistantService()
        service.start()
    except Exception as exc:
        log_fatal(f"Factorio RCON bridge terminated unexpectedly: {exc}")
        raise
