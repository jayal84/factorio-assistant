#!/usr/bin/env python3
"""Small operations web app for the Home Assistant ingress."""

import json
import html
import hmac
import ipaddress
import logging
import math
import mimetypes
import os
import sys
import time
import shutil
import signal
import socket
import sqlite3
import threading
import zipfile
import psutil
import psutil
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from rcon_client import RCONClient
import catalog_db

WEB_LOG_LEVELS = {
    "trace": logging.DEBUG,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "fatal": logging.CRITICAL,
}

HOST = os.environ.get("WEB_HOST", "0.0.0.0")
PORT = int(os.environ.get("WEB_PORT", "8099"))
WEB_ROLE = os.environ.get("WEB_ROLE", "all").strip().lower()
SHARE_DIR = Path(os.environ.get("FACTORIO_DATA_DIR", "/share/factorio"))
FACTORIO_INSTALL_DIR = Path(os.environ.get("FACTORIO_INSTALL_DIR", "/opt/factorio"))
WEB_DIR = Path(os.environ.get("WEB_DIR", "/app/web"))
WEB_ASSET_DIR = WEB_DIR / "assets"
CATALOG_PATH = catalog_db.CATALOG_PATH
INGRESS_PROXY_IP = "172.30.32.2"
HA_INTERNAL_NETWORK = ipaddress.ip_network(os.environ.get("HA_INTERNAL_NETWORK", "172.30.32.0/23"))
API_TOKEN = os.environ.get("FACTORIO_API_TOKEN", "").strip()
MOD_ENABLED = True
SERVER_SETTINGS_PATH = Path(os.environ.get("CONFIG_DIR") or "/config") / "server-settings.json"
RUNTIME_DIR = Path(os.environ.get("FACTORIO_RUNTIME_DIR") or "/config/runtime")
SAVE_BACKUP_SETTINGS_PATH = RUNTIME_DIR / "save-backup.json"
RESTORE_REQUEST_PATH = RUNTIME_DIR / "restore-request.json"
RESTORE_STATUS_PATH = RUNTIME_DIR / "restore-status.json"
SAVE_BACKUP_PREFIX = "factorio-backup-"
DEFAULT_BACKUP_MODE = "interval"
DEFAULT_BACKUP_INTERVAL_HOURS = 12
DEFAULT_BACKUP_DAILY_TIME = "00:00"
DEFAULT_BACKUP_MAX_SAVES = 14
DEFAULT_BACKUP_MAX_TOTAL_SIZE_MB = 0
SAVE_LOCK = threading.Lock()
logger = logging.getLogger("FactorioWeb")
logger.setLevel(WEB_LOG_LEVELS.get(os.environ.get("LOG_LEVEL", "info").strip().lower(), logging.INFO))
logger.propagate = False
log_handler = logging.StreamHandler(sys.stdout)
log_handler.setLevel(logger.level)
log_handler.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s [Factorio Assistant][Web] - %(message)s", datefmt="%H:%M:%S"))
logger.addHandler(log_handler)

RCON_CLIENT = RCONClient(
    host="127.0.0.1",
    port=int(os.environ.get("RCON_PORT", "27015")),
    response_timeout=10.0,
    logger=logger.getChild("RCON"),
)


def rcon_password() -> str:
    return os.environ.get("RCON_PASS", "").strip()


def addon_options() -> dict[str, object]:
    try:
        options = json.loads(Path("/data/options.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return options if isinstance(options, dict) else {}


def configured_port(name: str, default: int) -> int:
    environment_name = {"server_port": "GAME_PORT", "rcon_port": "RCON_PORT", "rest_api_port": "REST_API_PORT"}.get(name, "")
    value = addon_options().get(name, os.environ.get(environment_name, default))
    try:
        return max(1, min(65535, int(value)))
    except (TypeError, ValueError):
        return default


def connection_summary(request_host: str = "") -> dict[str, object]:
    host = request_host.split(",", 1)[0].strip()
    if host:
        try:
            host = urlparse(f"//{host}").hostname or host
        except ValueError:
            host = host.split(":", 1)[0]
    host = host or os.environ.get("FACTORIO_HOST", "") or socket.gethostname()
    address = host
    try:
        address = socket.gethostbyname(host)
    except (OSError, socket.gaierror):
        if host in {"localhost", socket.gethostname()}:
            address = "127.0.0.1"
    return {
        "hostname": host,
        "ip": address,
        "game_port": configured_port("server_port", 34197),
        "rcon_port": configured_port("rcon_port", 27015),
        "rest_api_port": configured_port("rest_api_port", 8100),
    }


CATALOG = catalog_db.Catalog()
BUILTIN_MOD_NAMES = {"base", "core", "space-age", "quality", "elevated-rails"}
ICON_FALLBACK = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" fill="#667f55"/><path d="M16 16h32v32H16z" fill="#dce8d2"/><path d="M22 22h20v20H22z" fill="#667f55"/></svg>'


def _query_value(query: dict[str, list[str]], key: str, default: str = "") -> str:
    return str(query.get(key, [default])[0] or default).strip()


def catalog_search(query: dict[str, list[str]]) -> dict[str, object]:
    metadata = CATALOG.metadata()
    header = {
        "schema_version": metadata.get("schema_version", catalog_db.SCHEMA_VERSION_FALLBACK),
        "factorio_version": metadata.get("factorio_version", "unknown"),
        "factorio_data_ref": metadata.get("factorio_data_ref", "unknown"),
        "data_source": metadata.get("data_source", ""),
        "data_source_url": metadata.get("data_source_url", ""),
        "changelog_url": metadata.get("changelog_url", ""),
        "modules": metadata.get("modules", []),
        "kinds": metadata.get("kinds", {}),
        "kind_labels": catalog_db.KIND_LABELS,
    }
    kind = _query_value(query, "kind").casefold()
    if _query_value(query, "facets"):
        return {**header, "kind": kind, "facets": CATALOG.facets(kind)}

    name = _query_value(query, "name")
    if name:
        record = CATALOG.entry(name, kind)
        if record is None:
            return {**header, "name": name, "found": False,
                    "suggestions": CATALOG.suggestions(name)}
        return {**header, "name": name, "found": True, "result": record}

    text = _query_value(query, "query")
    try:
        limit = max(1, min(200, int(_query_value(query, "limit", "25"))))
        offset = max(0, int(_query_value(query, "offset", "0")))
    except ValueError as exc:
        raise ValueError("limit and offset must be integers.") from exc
    total, results = CATALOG.search(
        query=text,
        kind=kind,
        group=_query_value(query, "category") or _query_value(query, "group"),
        subgroup=_query_value(query, "subcategory") or _query_value(query, "subgroup"),
        limit=limit,
        offset=offset,
        include_hidden=_query_value(query, "hidden") in {"1", "true", "yes"},
    )
    if _query_value(query, "detail", "summary") != "full":
        results = [catalog_db.summarize(record) for record in results]
    payload = {
        **header,
        "query": text,
        "kind": kind,
        "total": total,
        "offset": offset,
        "limit": limit,
        "results": results,
    }
    if not total and text:
        payload["suggestions"] = CATALOG.suggestions(text)
    return payload


def catalog_entry(query: dict[str, list[str]]) -> dict[str, object]:
    metadata = CATALOG.metadata()
    name = _query_value(query, "name")
    kind = _query_value(query, "kind").casefold()
    if not name:
        raise ValueError("name is required.")
    record = CATALOG.entry(name, kind)
    if record is None:
        return {
            "schema_version": metadata.get("schema_version", catalog_db.SCHEMA_VERSION_FALLBACK),
            "factorio_version": metadata.get("factorio_version", "unknown"),
            "factorio_data_ref": metadata.get("factorio_data_ref", "unknown"),
            "found": False,
            "name": name,
            "kind": kind,
            "suggestions": CATALOG.suggestions(name),
        }
    detail = _query_value(query, "detail", "full")
    return {
        "schema_version": metadata.get("schema_version", catalog_db.SCHEMA_VERSION_FALLBACK),
        "factorio_version": metadata.get("factorio_version", "unknown"),
        "factorio_data_ref": metadata.get("factorio_data_ref", "unknown"),
        "found": True,
        "name": name,
        "kind": kind,
        "result": record if detail == "full" else catalog_db.summarize(record),
    }


def catalog_production(payload: dict[str, object]) -> dict[str, object]:
    metadata = CATALOG.metadata()
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise ValueError("items must be an array.")
    targets: list[dict[str, object]] = []
    for item in items:
        if isinstance(item, str):
            targets.append({"name": item, "rate": 1.0})
            continue
        if not isinstance(item, dict):
            raise ValueError("each item must be a string or object.")
        name = str(item.get("name") or "").strip()
        if not name:
            raise ValueError("each item must include a name.")
        targets.append({"name": name, "rate": float(item.get("rate", item.get("amount", 1.0)))})
    plan = CATALOG.production_plan(targets, set(str(value) for value in payload.get("known_recipes", []) or []))
    return {
        "schema_version": metadata.get("schema_version", catalog_db.SCHEMA_VERSION_FALLBACK),
        "factorio_version": metadata.get("factorio_version", "unknown"),
        "factorio_data_ref": metadata.get("factorio_data_ref", "unknown"),
        "items": targets,
        **plan,
    }


def localized_resource_name(name: object) -> str:
    resource_name = str(name or "").strip()
    if not resource_name:
        return "Resource"
    try:
        return CATALOG.localized_name(resource_name, "resource")
    except (OSError, sqlite3.Error):
        return resource_name


def localized_technology_name(name: object) -> str:
    technology_name = str(name or "").strip()
    if not technology_name:
        return ""
    try:
        return CATALOG.localized_name(technology_name, "technology")
    except (OSError, sqlite3.Error):
        return technology_name.replace("-", " ").title()


def resolve_icon_path(raw_path: str) -> Path | None:
    path = raw_path.strip().replace("\\", "/")
    if not path or path.startswith("/") or ".." in Path(path).parts:
        return None
    if not path.startswith("__") or "/" not in path[2:]:
        return None
    namespace, member = path[2:].split("/", 1)
    if not namespace.endswith("__") or not member:
        return None
    mod_name = namespace[:-2]
    if mod_name not in BUILTIN_MOD_NAMES:
        return None
    roots = [FACTORIO_INSTALL_DIR / "data", Path("/factorio") / "data", SHARE_DIR]
    for root in roots:
        mod_root = root / mod_name
        candidate = mod_root / member
        try:
            resolved = candidate.resolve()
            if resolved.is_file() and resolved.is_relative_to(mod_root.resolve()):
                return resolved
        except OSError:
            continue
    return None


def read_icon_asset(raw_path: str) -> tuple[bytes, str] | None:
    path = raw_path.strip().replace("\\", "/")
    if not path or path.startswith("/") or ".." in Path(path).parts or not path.startswith("__") or "/" not in path[2:]:
        return None
    if path.startswith("__"):
        icon_path = resolve_icon_path(path)
        if icon_path is not None:
            try:
                return icon_path.read_bytes(), mimetypes.guess_type(icon_path.name)[0] or "application/octet-stream"
            except OSError:
                return None
    namespace, member = path[2:].split("/", 1)
    if not namespace.endswith("__") or not member:
        return None
    mod_name = namespace[:-2]
    if not mod_name or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in mod_name):
        return None
    for archive in sorted(SHARE_DIR.joinpath("mods").glob(f"{mod_name}_*.zip")):
        try:
            with zipfile.ZipFile(archive) as bundle:
                match = next((name for name in bundle.namelist() if name == member or name.endswith(f"/{member}")), None)
                if match is not None:
                    return bundle.read(match), mimetypes.guess_type(member)[0] or "application/octet-stream"
        except (OSError, zipfile.BadZipFile, KeyError):
            continue
    if mod_name in BUILTIN_MOD_NAMES:
        return ICON_FALLBACK, "image/svg+xml"
    return None


def execute_rcon(command: str) -> tuple[str | None, int, str]:
    RCON_CLIENT.password = rcon_password()
    response = RCON_CLIENT.send_command(command)
    if response is not None:
        return response, 200, ""
    error = RCON_CLIENT.last_error or "RCON is unavailable."
    status = 504 if "timed out" in error.lower() else 503
    return None, status, error


def execute_mod_command(method: str, arguments: str) -> dict[str, object] | None:
    """Call the required structured Factorio Assistant mod interface."""
    call_arguments = f",{arguments}" if arguments else ""
    command = (
        "/silent-command local ok,result=pcall(remote.call,"
        f"{_lua_string('factorio_assistant')},{_lua_string(method)}{call_arguments});"
        "rcon.print(helpers.table_to_json({ok=ok,result=result}))"
    )
    response, _, _ = execute_rcon(command)
    if response is None:
        return None
    try:
        envelope = json.loads(response.strip())
    except json.JSONDecodeError:
        return None
    return envelope if isinstance(envelope, dict) else None


def _lua_string(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=True)


def _lua_value(value: object) -> str:
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("numeric values must be finite")
        return str(value)
    if isinstance(value, str):
        return _lua_string(value)
    if isinstance(value, list):
        return "{" + ",".join(_lua_value(item) for item in value) + "}"
    if isinstance(value, dict):
        entries = []
        for key, item in value.items():
            if not isinstance(key, str) or not key.isidentifier():
                raise ValueError("Lua option keys must be identifiers")
            entries.append(f"{key}={_lua_value(item)}")
        return "{" + ",".join(entries) + "}"
    raise ValueError("unsupported Lua option value")


def _factory_mod_arguments(operation: str, payload: dict[str, object]) -> str:
    surface = str(payload.get("surface", "nauvis") or "nauvis").strip()
    if not surface or len(surface) > 64:
        raise ValueError("surface must be a non-empty name of at most 64 characters")
    options: dict[str, object] = {"surface": surface}
    if operation != "production":
        _, area = _factory_area(payload)
        options["area"] = {"left_top": {"x": area["left"], "y": area["top"]}, "right_bottom": {"x": area["right"], "y": area["bottom"]}}
    if operation in {"inspect", "map", "demolish"}:
        options["limit"] = _factory_limit(payload, 1000 if operation == "map" else 500)
    if operation == "demolish":
        names = payload.get("names", [])
        if not isinstance(names, list) or len(names) > 50 or any(not isinstance(name, str) or not name.strip() or len(name) > 128 for name in names):
            raise ValueError("names must contain at most 50 non-empty entity names")
        options.update({"names": [name.strip() for name in names], "resources": bool(payload.get("resources", False)), "real": _factory_bool(payload, "real", False)})
    if operation == "map":
        layers = payload.get("layers", {})
        if not isinstance(layers, dict):
            raise ValueError("layers must be an object")
        options.update({"tiles": bool(layers.get("tiles", False)), "resources": bool(layers.get("resources", True)), "entities": bool(layers.get("entities", True))})
    if operation in {"production", "plan"}:
        items = _factory_item_names(payload, 50 if operation == "production" else 20)
        if operation == "production" and not items:
            raise ValueError("items must contain between 1 and 50 item names")
        options["items"] = items
    if operation == "plan":
        goal = str(payload.get("goal", "") or "").strip()
        if not goal or len(goal) > 512:
            raise ValueError("goal must be between 1 and 512 characters")
        options["goal"] = goal
    if operation == "build":
        entities = payload.get("entities", [])
        if not isinstance(entities, list) or not 1 <= len(entities) <= 100:
            raise ValueError("entities must contain between 1 and 100 placements")
        placements = []
        for entity in entities:
            if not isinstance(entity, dict) or not isinstance(entity.get("position"), dict):
                raise ValueError("each entity placement must contain a position object")
            name = entity.get("name")
            position = entity["position"]
            try:
                x, y = float(position["x"]), float(position["y"])
                direction = int(entity.get("direction", 0))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("entity position and direction must be numeric") from exc
            if not isinstance(name, str) or not name.strip() or len(name) > 128 or not all(math.isfinite(value) for value in (x, y)) or not 0 <= direction <= 7:
                raise ValueError("entity name, position, or direction is invalid")
            placements.append({"name": name.strip(), "x": x, "y": y, "direction": direction})
        options.update({"entities": placements, "dry_run": _factory_bool(payload, "dry_run", False), "real": _factory_bool(payload, "real", False)})
    return f"{_lua_string(operation)},{_lua_value(options)}"


def _factory_area(payload: dict[str, object]) -> tuple[str, dict[str, float]]:
    area = payload.get("area", {})
    if not isinstance(area, dict):
        raise ValueError("area must be an object")
    left_top = area.get("left_top", {})
    right_bottom = area.get("right_bottom", {})
    if not isinstance(left_top, dict) or not isinstance(right_bottom, dict):
        raise ValueError("area must contain left_top and right_bottom objects")
    try:
        left = float(left_top["x"])
        top = float(left_top["y"])
        right = float(right_bottom["x"])
        bottom = float(right_bottom["y"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("area coordinates must be numbers") from exc
    if not all(math.isfinite(value) for value in (left, top, right, bottom)):
        raise ValueError("area coordinates must be finite numbers")
    if right <= left or bottom <= top:
        raise ValueError("area must have positive width and height")
    if right - left > 512 or bottom - top > 512:
        raise ValueError("area dimensions must not exceed 512 tiles")
    area_literal = (
        f"{{left_top={{x={left:g},y={top:g}}},"
        f"right_bottom={{x={right:g},y={bottom:g}}}}}"
    )
    return area_literal, {"left": left, "top": top, "right": right, "bottom": bottom}


def _factory_limit(payload: dict[str, object], default: int = 500) -> int:
    raw_limit = payload.get("limit", default)
    if isinstance(raw_limit, bool) or not isinstance(raw_limit, (int, float, str)):
        raise ValueError("limit must be an integer")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    return limit


def _factory_lua_prefix() -> str:
    return r'''local function quote(value)
  if value == nil then return "null" end
  local text = tostring(value)
  text = string.gsub(text, "\\", "\\\\")
  text = string.gsub(text, '"', '\\"')
  text = string.gsub(text, string.char(10), "\\n")
  text = string.gsub(text, string.char(13), "\\r")
  text = string.gsub(text, string.char(9), "\\t")
  return '"' .. text .. '"'
end
local function number(value)
  if value == nil then return "null" end
  return tostring(value)
end
'''


def build_factory_inspect_command(payload: dict[str, object]) -> str:
    area_literal, _ = _factory_area(payload)
    surface = str(payload.get("surface", "nauvis") or "nauvis").strip()
    if not surface or len(surface) > 64:
        raise ValueError("surface must be a non-empty name of at most 64 characters")
    limit = _factory_limit(payload)
    return "/silent-command " + _factory_lua_prefix() + f'''local surface=game.surfaces[{_lua_string(surface)}]
if not surface then rcon.print('{{"error":"surface_not_found"}}') return end
local rows=surface.find_entities_filtered{{area={area_literal},limit={limit}}}
local types={{}}
local recipes={{}}
local statuses={{}}
local records={{}}
for _,entity in ipairs(rows) do
  if entity.valid then
        pcall(function()
            types[entity.type]=(types[entity.type] or 0)+1
            local recipe_ok,recipe_value=pcall(function() return entity.get_recipe() end)
            local recipe=recipe_ok and recipe_value or nil
            if recipe then recipes[recipe.name]=(recipes[recipe.name] or 0)+1 end
            local status=tostring(entity.status or "unknown")
            statuses[status]=(statuses[status] or 0)+1
            table.insert(records,'{{"name":'..quote(entity.name)..',"type":'..quote(entity.type)..',"x":'..number(entity.position.x)..',"y":'..number(entity.position.y)..',"direction":'..number(entity.direction)..',"recipe":'..quote(recipe and recipe.name or nil)..',"status":'..quote(status)..'}}')
        end)
  end
end
local function object(values)
  local entries={{}}
  for key,value in pairs(values) do table.insert(entries,quote(key)..":"..number(value)) end
  table.sort(entries)
  return "{{"..table.concat(entries,",").."}}"
end
rcon.print('{{"surface":'..quote(surface.name)..',"entity_count":'..number(#rows)..',"types":'..object(types)..',"recipes":'..object(recipes)..',"statuses":'..object(statuses)..',"entities":['..table.concat(records,",")..']}}')'''


def build_factory_map_command(payload: dict[str, object]) -> str:
    area_literal, _ = _factory_area(payload)
    surface = str(payload.get("surface", "nauvis") or "nauvis").strip()
    if not surface or len(surface) > 64:
        raise ValueError("surface must be a non-empty name of at most 64 characters")
    limit = _factory_limit(payload, 1000)
    layers = payload.get("layers", {})
    if not isinstance(layers, dict):
        raise ValueError("layers must be an object")
    include_tiles = bool(layers.get("tiles", False))
    include_resources = bool(layers.get("resources", True))
    include_entities = bool(layers.get("entities", True))
    return "/silent-command " + _factory_lua_prefix() + f'''local surface=game.surfaces[{_lua_string(surface)}]
if not surface then rcon.print('{{"error":"surface_not_found"}}') return end
local entities={{}}
local tiles={{}}
if {str(include_entities).lower()} then
  for _,entity in ipairs(surface.find_entities_filtered{{area={area_literal},limit={limit}}}) do
    if entity.valid and ({str(include_resources).lower()} or entity.type ~= "resource") then
      table.insert(entities,'{{"name":'..quote(entity.name)..',"type":'..quote(entity.type)..',"x":'..number(entity.position.x)..',"y":'..number(entity.position.y)..',"direction":'..number(entity.direction)..'}}')
    end
  end
end
if {str(include_tiles).lower()} then
  for _,tile in ipairs(surface.find_tiles_filtered{{area={area_literal},limit={limit}}}) do
    table.insert(tiles,'{{"name":'..quote(tile.name)..',"x":'..number(tile.position.x)..',"y":'..number(tile.position.y)..'}}')
  end
end
rcon.print('{{"surface":'..quote(surface.name)..',"entities":['..table.concat(entities,",")..'],"tiles":['..table.concat(tiles,",")..']}}')'''


def build_factory_demolish_command(payload: dict[str, object]) -> str:
        area_literal, _ = _factory_area(payload)
        surface = str(payload.get("surface", "nauvis") or "nauvis").strip()
        if not surface or len(surface) > 64:
                raise ValueError("surface must be a non-empty name of at most 64 characters")
        limit = _factory_limit(payload, 500)
        names = payload.get("names", [])
        if not isinstance(names, list) or len(names) > 50 or any(not isinstance(name, str) or not name.strip() or len(name) > 128 for name in names):
                raise ValueError("names must contain at most 50 non-empty entity names")
        name_set = "{" + ",".join(f"[{_lua_string(name.strip())}]=true" for name in names) + "}"
        include_resources = bool(payload.get("resources", False))
        real = _factory_bool(payload, "real", False)
        return "/silent-command " + _factory_lua_prefix() + f'''local surface=game.surfaces[{_lua_string(surface)}]
if not surface then rcon.print('{{"error":"surface_not_found"}}') return end
local selected={name_set}
local results={{}}
local marked=0
local removed=0
for _,entity in ipairs(surface.find_entities_filtered{{area={area_literal},limit={limit}}}) do
    if entity.valid and entity.type ~= "character" and ({str(include_resources).lower()} or entity.type ~= "resource") and (#selected == 0 or selected[entity.name]) then
        local status="skipped"
        if {str(real).lower()} then
            local ok=pcall(function() entity.destroy{{raise_destroy=true}} end)
            status=ok and "removed" or "remove_failed"
            if ok then removed=removed+1 end
        else
            local ok=pcall(function() entity.order_deconstruction("player") end)
            status=ok and "marked" or "mark_failed"
            if ok then marked=marked+1 end
        end
        table.insert(results,'{{"name":'..quote(entity.name)..',"x":'..number(entity.position.x)..',"y":'..number(entity.position.y)..',"status":'..quote(status)..'}}')
    end
end
rcon.print('{{"phase":"demolition","surface":'..quote(surface.name)..',"real":'..tostring({str(real).lower()})..',"marked":'..number(marked)..',"removed":'..number(removed)..',"results":['..table.concat(results,",")..']}}')'''


def build_factory_production_command(payload: dict[str, object]) -> str:
    surface = str(payload.get("surface", "nauvis") or "nauvis").strip()
    if not surface or len(surface) > 64:
        raise ValueError("surface must be a non-empty name of at most 64 characters")
    items = payload.get("items", [])
    if not isinstance(items, list) or not items or len(items) > 50:
        raise ValueError("items must contain between 1 and 50 item names")
    names = []
    for item in items:
        if not isinstance(item, str) or not item.strip() or len(item) > 128:
            raise ValueError("each item must be a non-empty name of at most 128 characters")
        names.append(_lua_string(item.strip()))
    item_table = "{" + ",".join(names) + "}"
    return "/silent-command " + _factory_lua_prefix() + f'''local force=game.forces["player"]
local surface=game.surfaces[{_lua_string(surface)}]
if not force or not surface then rcon.print('{{"error":"force_or_surface_not_found"}}') return end
local stats=force.get_item_production_statistics(surface)
local rows={{}}
for _,name in ipairs({item_table}) do
  local prototype=game.item_prototypes[name]
  if prototype then
    local input=stats.get_input_count(name) or 0
    local output=stats.get_output_count(name) or 0
    table.insert(rows,'{{"name":'..quote(name)..',"input_per_minute":'..number(input*60)..',"output_per_minute":'..number(output*60)..'}}')
  end
end
rcon.print('{{"surface":'..quote(surface.name)..',"items":['..table.concat(rows,",")..']}}')'''


def _factory_item_names(payload: dict[str, object], maximum: int = 20) -> list[str]:
    items = payload.get("items", [])
    if not isinstance(items, list) or len(items) > maximum:
        raise ValueError(f"items must contain at most {maximum} item names")
    names = []
    for item in items:
        if not isinstance(item, str) or not item.strip() or len(item) > 128:
            raise ValueError("each item must be a non-empty name of at most 128 characters")
        names.append(item.strip())
    return names


def _factory_bool(payload: dict[str, object], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    raise ValueError(f"{key} must be a boolean")


def build_factory_plan_command(payload: dict[str, object]) -> str:
    area_literal, _ = _factory_area(payload)
    surface = str(payload.get("surface", "nauvis") or "nauvis").strip()
    goal = str(payload.get("goal", "") or "").strip()
    if not surface or len(surface) > 64:
        raise ValueError("surface must be a non-empty name of at most 64 characters")
    if not goal or len(goal) > 512:
        raise ValueError("goal must be between 1 and 512 characters")
    items = _factory_item_names(payload)
    item_table = "{" + ",".join(_lua_string(item) for item in items) + "}"
    return "/silent-command " + _factory_lua_prefix() + f'''local surface=game.surfaces[{_lua_string(surface)}]
if not surface then rcon.print('{{"error":"surface_not_found"}}') return end
local rows=surface.find_entities_filtered{{area={area_literal},limit=1000}}
local types={{}}
local recipes={{}}
for _,entity in ipairs(rows) do
  if entity.valid then
    types[entity.type]=(types[entity.type] or 0)+1
    local recipe_ok,recipe_value=pcall(function() return entity.get_recipe() end)
    if recipe_ok and recipe_value then recipes[recipe_value.name]=(recipes[recipe_value.name] or 0)+1 end
  end
end
local function object(values)
  local entries={{}}
  for key,value in pairs(values) do table.insert(entries,quote(key)..":"..number(value)) end
  table.sort(entries)
  return "{{"..table.concat(entries,",").."}}"
end
local production={{}}
local force=game.forces["player"]
if force then
  local stats=force.get_item_production_statistics(surface)
  for _,name in ipairs({item_table}) do
    if game.item_prototypes[name] then
      table.insert(production,'{{"name":'..quote(name)..',"input_per_minute":'..number((stats.get_input_count(name) or 0)*60)..',"output_per_minute":'..number((stats.get_output_count(name) or 0)*60)..'}}')
    end
  end
end
rcon.print('{{"phase":"planner","goal":'..quote({_lua_string(goal)})..',"surface":'..quote(surface.name)..',"entity_count":'..number(#rows)..',"types":'..object(types)..',"recipes":'..object(recipes)..',"production":['..table.concat(production,",")..']}}')'''


def build_factory_builder_command(payload: dict[str, object]) -> str:
    surface = str(payload.get("surface", "nauvis") or "nauvis").strip()
    entities = payload.get("entities", [])
    dry_run = _factory_bool(payload, "dry_run", False)
    real = _factory_bool(payload, "real", False)
    if not surface or len(surface) > 64:
        raise ValueError("surface must be a non-empty name of at most 64 characters")
    if not isinstance(entities, list) or not 1 <= len(entities) <= 100:
        raise ValueError("entities must contain between 1 and 100 placements")
    placements = []
    for entity in entities:
        if not isinstance(entity, dict):
            raise ValueError("each entity placement must be an object")
        name = entity.get("name")
        position = entity.get("position")
        if position is None and "x" in entity and "y" in entity:
            position = {"x": entity.get("x"), "y": entity.get("y")}
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            raise ValueError("each entity name must be a non-empty name of at most 128 characters")
        if not isinstance(position, dict):
            raise ValueError("each entity placement must contain a position object")
        try:
            x = float(position["x"])
            y = float(position["y"])
            direction = int(entity.get("direction", 0))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("entity position and direction must be numeric") from exc
        if not all(math.isfinite(value) for value in (x, y)) or not 0 <= direction <= 7:
            raise ValueError("entity position must be finite and direction must be between 0 and 7")
        placements.append((name.strip(), x, y, direction))
    placement_table = "{" + ",".join(
        f"{{name={_lua_string(name)},x={x:g},y={y:g},direction={direction}}}"
        for name, x, y, direction in placements
    ) + "}"
    return "/silent-command " + _factory_lua_prefix() + f'''local surface=game.surfaces[{_lua_string(surface)}]
if not surface then rcon.print('{{"error":"surface_not_found"}}') return end
local force=game.forces["player"]
local results={{}}
for _,entry in ipairs({placement_table}) do
  local status="blocked"
    local prototype=prototypes.entity[entry.name]
  if not prototype then
    status="prototype_not_found"
  else
    local ok,can_place=pcall(function() return surface.can_place_entity{{name=entry.name,position={{x=entry.x,y=entry.y}},direction=entry.direction,force=force}} end)
    if ok and can_place then
            if {str(not dry_run).lower()} then
                local create_spec={{name=entry.name,position={{x=entry.x,y=entry.y}},direction=entry.direction,force=force}}
                if not {str(real).lower()} then
                    create_spec={{name="entity-ghost",inner_name=entry.name,position={{x=entry.x,y=entry.y}},direction=entry.direction,force=force}}
                end
                local created=surface.create_entity(create_spec)
                status=created and ({'"placed"' if real else '"ghost_placed"'}) or "create_failed"
      else
        status="would_place"
      end
    end
  end
  table.insert(results,'{{"name":'..quote(entry.name)..',"x":'..number(entry.x)..',"y":'..number(entry.y)..',"direction":'..number(entry.direction)..',"status":'..quote(status)..'}}')
end
rcon.print('{{"phase":"builder","surface":'..quote(surface.name)..',"real":'..tostring({str(real).lower()})..',"dry_run":'..tostring({str(dry_run).lower()})..',"results":['..table.concat(results,",")..']}}')'''


def build_factory_helper_command(payload: dict[str, object]) -> str:
    player_name = str(payload.get("player", "") or "").strip()
    items = payload.get("items", [])
    if not player_name or len(player_name) > 64:
        raise ValueError("player must be a non-empty name of at most 64 characters")
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise ValueError("items must contain between 1 and 50 entries")
    grants = []
    total = 0
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each item grant must be an object")
        name = item.get("name")
        try:
            count = int(item.get("count"))
        except (TypeError, ValueError) as exc:
            raise ValueError("each item count must be an integer") from exc
        if not isinstance(name, str) or not name.strip() or len(name) > 128 or not 1 <= count <= 50000:
            raise ValueError("each item name must be non-empty and count must be between 1 and 50000")
        total += count
        grants.append((name.strip(), count))
    if total > 50000:
        raise ValueError("total item count must not exceed 50000")
    grant_table = "{" + ",".join(f"{{name={_lua_string(name)},count={count}}}" for name, count in grants) + "}"
    return "/silent-command " + _factory_lua_prefix() + f'''local player=game.get_player({_lua_string(player_name)})
if not player then rcon.print('{{"error":"player_not_found"}}') return end
local results={{}}
for _,entry in ipairs({grant_table}) do
  local inserted=0
  if game.item_prototypes[entry.name] then inserted=player.insert{{name=entry.name,count=entry.count}} end
  table.insert(results,'{{"name":'..quote(entry.name)..',"requested":'..number(entry.count)..',"inserted":'..number(inserted)..',"remaining":'..number(entry.count-inserted)..'}}')
end
rcon.print('{{"phase":"helper","player":'..quote(player.name)..',"results":['..table.concat(results,",")..']}}')'''


def build_factory_helper_mod_arguments(payload: dict[str, object]) -> str:
    """Build the validated Lua arguments for the Factorio Assistant give_items command."""
    player_name = str(payload.get("player", "") or "").strip()
    items = payload.get("items", [])
    if not player_name or len(player_name) > 64:
        raise ValueError("player must be a non-empty name of at most 64 characters")
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise ValueError("items must contain between 1 and 50 entries")
    grants = []
    total = 0
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each item grant must be an object")
        name = item.get("name")
        try:
            count = int(item.get("count"))
        except (TypeError, ValueError) as exc:
            raise ValueError("each item count must be an integer") from exc
        if not isinstance(name, str) or not name.strip() or len(name) > 128 or not 1 <= count <= 50000:
            raise ValueError("each item name must be non-empty and count must be between 1 and 50000")
        total += count
        grants.append(f"{{name={_lua_string(name.strip())},count={count}}}")
    if total > 50000:
        raise ValueError("total item count must not exceed 50000")
    return f"{_lua_string(player_name)},{{{','.join(grants)}}}"


def factory_query(path: str, payload: object) -> tuple[dict[str, object] | None, int, str]:
    if not isinstance(payload, dict):
        return None, 400, "JSON body must be an object."
    try:
        operation = {
            "/api/factory/inspect": "inspect",
            "/api/factory/map": "map",
            "/api/factory/production": "production",
            "/api/factory/plan": "plan",
            "/api/factory/build": "build",
            "/api/factory/demolish": "demolish",
        }.get(path)
        if operation:
            mod_response = execute_mod_command("factory_query", _factory_mod_arguments(operation, payload))
            if mod_response is None:
                return None, 503, "Factorio Assistant mod interface is unavailable."
            if not mod_response.get("ok"):
                message = str(mod_response.get("error") or "Factorio Assistant command failed.")
                if message.startswith("disabled:"):
                    return {"error": "disabled", "message": message}, 403, ""
                return {"error": message}, 400, ""
            result = mod_response.get("result")
            if isinstance(result, dict):
                return result, 200, ""
            return None, 502, "Factorio Assistant returned an invalid factory result."
        elif path == "/api/factory/helper":
            mod_arguments = build_factory_helper_mod_arguments(payload)
            mod_response = execute_mod_command("give_items", mod_arguments)
            if mod_response is None:
                return None, 503, "Factorio Assistant mod interface is unavailable."
            if not mod_response.get("ok"):
                message = str(mod_response.get("error") or mod_response.get("result") or "Factorio Assistant command failed.")
                if message.startswith("disabled:"):
                    return {"error": "disabled", "message": message}, 403, ""
                return {"error": message}, 400, ""
            result = mod_response.get("result")
            if isinstance(result, dict):
                return result, 200, ""
            return None, 502, "Factorio Assistant returned an invalid command result."
        else:
            return None, 404, "Not found"
    except ValueError as exc:
        return None, 400, str(exc)
    response, status, error = execute_rcon(command)
    if response is None:
        return None, status, error
    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        diagnostic = str(response).strip()[:1000]
        return {
            "error": "Factorio returned an invalid factory query response.",
            "factorio_response": diagnostic,
        }, 502, ""
    if not isinstance(result, dict):
        return None, 502, "Factorio returned an invalid factory query response."
    return result, 200, ""


def process_running(fragment: str) -> bool:
    """Check Linux process command lines without requiring Docker API access."""
    proc_dir = Path("/proc")
    try:
        for entry in proc_dir.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                command = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode()
            except (OSError, UnicodeDecodeError):
                continue
            if fragment in command:
                return True
    except OSError:
        pass
    return False


def file_summary(directory: Path, suffix: str | None = None) -> list[dict[str, object]]:
    if not directory.is_dir():
        return []
    items = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or (suffix and path.suffix.lower() != suffix):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append({"name": path.name, "size": stat.st_size, "modified": stat.st_mtime})
    return items


def read_log_tail(limit: int = 120) -> list[str]:
    log_path = SHARE_DIR / "logs" / "factorio-current.log"
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            return [line.rstrip() for line in handle.readlines()[-limit:]]
    except OSError:
        return []


def player_armor_details(details: dict[str, object]) -> dict[str, object]:
    armor = details.get("armor", {})
    if not isinstance(armor, dict):
        armor = {}
    name = str(armor.get("name") or "none")
    try:
        equipment_count = int(armor.get("equipment_count", 0) or 0)
    except (TypeError, ValueError):
        equipment_count = 0
    result: dict[str, object] = {
        "name": name,
        "equipment_count": equipment_count,
    }
    return result


def player_color_details(details: dict[str, object]) -> dict[str, float]:
    color = details.get("color", {})
    if not isinstance(color, dict):
        color = {}
    result = {}
    for channel, default in (("r", 0.869), ("g", 0.5), ("b", 0.130)):
        try:
            result[channel] = max(0.0, min(1.0, float(color.get(channel, default))))
        except (TypeError, ValueError):
            result[channel] = default
    return result


def known_player_summary() -> list[dict[str, object]]:
    path = Path(
        os.environ.get("FACTORIO_PLAYER_PROFILES_PATH") or "/config/player_profiles.json"
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    players = []
    for username, details in sorted(data.items(), key=lambda item: str(item[0]).casefold()):
        if not isinstance(details, dict):
            details = {}
        try:
            deaths = int(details.get("deaths", 0) or 0)
        except (TypeError, ValueError):
            deaths = 0
        players.append({
            "name": str(username),
            "connected": False,
            "deaths": deaths,
            "surface": str(details.get("surface", "unknown")),
            "x": float(details.get("x", 0) or 0),
            "y": float(details.get("y", 0) or 0),
            "health": float(details.get("health", details.get("current_health", 0)) or 0),
            "max_health": float(details.get("max_health", 0) or 0),
            "idle": bool(details.get("idle", False)),
            "motion": False,
            "injured": bool(details.get("injured", False)),
            "color": player_color_details(details),
            "armor": player_armor_details(details),
        })
    return players


def cached_player_summary() -> dict[str, dict[str, object]]:
    """Read the latest player map written by the bridge's existing telemetry query."""
    runtime_dir = Path(os.environ.get("FACTORIO_RUNTIME_DIR") or "/config/runtime")
    path = runtime_dir / "player_snapshot.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    players = payload.get("players", {}) if isinstance(payload, dict) else {}
    if not isinstance(players, dict):
        return {}
    normalized = {}
    for username, details in players.items():
        if not isinstance(details, dict) or not username:
            continue
        position = details.get("position", {})
        if not isinstance(position, dict):
            position = {}
        normalized[str(username)] = {
            "name": str(username),
            "connected": bool(details.get("connected", False)),
            "surface": str(details.get("surface", position.get("surface", "unknown"))),
            "x": float(position.get("x", 0) or 0),
            "y": float(position.get("y", 0) or 0),
            "health": float(details.get("health", details.get("current_health", 0)) or 0),
            "max_health": float(details.get("max_health", 0) or 0),
            "idle": bool(details.get("idle", False)),
            "deaths": int(details.get("deaths", 0) or 0),
            "motion": bool(details.get("motion", False)),
            "injured": bool(details.get("injured", False)),
            "color": player_color_details(details),
            "armor": player_armor_details(details),
        }
    return normalized


def research_summary() -> dict[str, object]:
    """Read the player force research state without changing the game."""
    mod_response = execute_mod_command("research_summary", "")
    empty = {"available": False, "researched": [], "current": "", "progress": 0.0, "queue": []}
    if mod_response is not None and mod_response.get("ok") and isinstance(mod_response.get("result"), dict):
        return mod_response["result"]
    return empty


def _file_info(path: Path) -> dict[str, object]:
    try:
        stat = path.stat()
    except OSError:
        return {"name": path.name, "size": 0, "modified": 0}
    return {"name": path.name, "size": stat.st_size, "modified": stat.st_mtime}


def installed_mod_summary() -> list[dict[str, object]]:
    mods_dir = SHARE_DIR / "mods"
    enabled: dict[str, bool] = {}
    try:
        data = json.loads((mods_dir / "mod-list.json").read_text(encoding="utf-8"))
        enabled = {str(item.get("name")): bool(item.get("enabled")) for item in data.get("mods", []) if isinstance(item, dict) and item.get("name")}
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    result = []
    try:
        paths = sorted((path for path in mods_dir.iterdir() if path.is_file() and path.suffix.lower() == ".zip"), key=lambda path: path.name.casefold())
    except OSError:
        paths = []
    for path in paths:
        stem = path.stem.rsplit("_", 1)[0]
        result.append({**_file_info(path), "id": stem, "enabled": enabled.get(stem, True)})
    return result


def save_summary() -> dict[str, object]:
    saves_dir = SHARE_DIR / "saves"
    saves = [
        {
            **file_info,
            "autosave": str(file_info["name"]).casefold().startswith("autosave"),
            "backup": str(file_info["name"]).startswith(SAVE_BACKUP_PREFIX),
        }
        for file_info in file_summary(saves_dir, ".zip")
    ]
    backup_settings = load_backup_settings()
    return {
        "directory": str(saves_dir),
        "configured": configured_save_name(),
        "files": saves,
        "backup_enabled": backup_settings["enabled"],
        "backup_mode": backup_settings["mode"],
        "backup_interval_hours": backup_settings["interval_hours"],
        "backup_daily_time": backup_settings["daily_time"],
        "backup_max_saves": backup_settings["max_saves"],
        "backup_max_total_size_mb": backup_settings["max_total_size_mb"],
        "last_backup": backup_settings.get("last_backup"),
    }


def _as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"} if value is not None else default


def load_backup_settings() -> dict[str, object]:
    settings: dict[str, object] = {
        "enabled": True,
        "mode": DEFAULT_BACKUP_MODE,
        "interval_hours": DEFAULT_BACKUP_INTERVAL_HOURS,
        "daily_time": DEFAULT_BACKUP_DAILY_TIME,
        "max_saves": DEFAULT_BACKUP_MAX_SAVES,
        "max_total_size_mb": DEFAULT_BACKUP_MAX_TOTAL_SIZE_MB,
    }
    data: object = {}
    try:
        data = json.loads(SAVE_BACKUP_SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            settings.update(data)
    except (OSError, json.JSONDecodeError):
        pass
    if isinstance(data, dict) and "times" in data and "mode" not in data:
        settings["mode"] = "interval"
        settings["interval_hours"] = 12
    return normalize_backup_settings(settings)


def normalize_backup_settings(settings: dict[str, object]) -> dict[str, object]:
    settings = dict(settings)
    settings["enabled"] = _as_bool(settings.get("enabled"), True)
    mode = settings.get("mode")
    settings["mode"] = mode if isinstance(mode, str) and mode in {"hourly", "daily", "interval"} else DEFAULT_BACKUP_MODE
    try:
        settings["interval_hours"] = max(1, min(168, int(settings.get("interval_hours", DEFAULT_BACKUP_INTERVAL_HOURS))))
    except (TypeError, ValueError):
        settings["interval_hours"] = DEFAULT_BACKUP_INTERVAL_HOURS
    daily_time = str(settings.get("daily_time") or DEFAULT_BACKUP_DAILY_TIME)
    settings["daily_time"] = daily_time if is_valid_time(daily_time) else DEFAULT_BACKUP_DAILY_TIME
    try:
        settings["max_saves"] = max(1, min(1000, int(settings.get("max_saves", DEFAULT_BACKUP_MAX_SAVES))))
    except (TypeError, ValueError):
        settings["max_saves"] = DEFAULT_BACKUP_MAX_SAVES
    try:
        settings["max_total_size_mb"] = max(0, min(102400, int(settings.get("max_total_size_mb", DEFAULT_BACKUP_MAX_TOTAL_SIZE_MB))))
    except (TypeError, ValueError):
        settings["max_total_size_mb"] = DEFAULT_BACKUP_MAX_TOTAL_SIZE_MB
    return settings


def is_valid_time(value: str) -> bool:
    return len(value) == 5 and value[2] == ":" and value[:2].isdigit() and value[3:].isdigit() and 0 <= int(value[:2]) <= 23 and 0 <= int(value[3:]) <= 59


def save_backup_settings(enabled: bool, schedule: dict[str, object] | None = None, last_backup: str | None = None, last_backup_at: float | None = None) -> dict[str, object]:
    settings = load_backup_settings()
    settings["enabled"] = enabled
    if schedule is not None:
        settings.update(schedule)
        settings = normalize_backup_settings(settings)
    if last_backup is not None:
        settings["last_backup"] = last_backup
    if last_backup_at is not None:
        settings["last_backup_at"] = last_backup_at
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path = SAVE_BACKUP_SETTINGS_PATH.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(settings, separators=(",", ":")), encoding="utf-8")
    temporary_path.replace(SAVE_BACKUP_SETTINGS_PATH)
    return settings


def configured_save_name() -> str:
    try:
        options = json.loads(Path("/data/options.json").read_text(encoding="utf-8"))
        return Path(str(options.get("save_name") or "world.zip")).name
    except (OSError, json.JSONDecodeError, AttributeError):
        return "world.zip"


def wait_for_save_completion(source: Path, previous_mtime: int) -> bool:
    deadline = time.monotonic() + 30
    previous_signature: tuple[int, int] | None = None
    stable_reads = 0
    while time.monotonic() < deadline:
        try:
            stat = source.stat()
        except OSError:
            time.sleep(0.5)
            continue
        signature = (stat.st_mtime_ns, stat.st_size)
        if stat.st_mtime_ns != previous_mtime:
            if signature == previous_signature:
                stable_reads += 1
            else:
                stable_reads = 0
            if stable_reads >= 2:
                return True
        previous_signature = signature
        time.sleep(0.5)
    return False


def restore_status() -> dict[str, object]:
    try:
        status = json.loads(RESTORE_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"state": "idle"}
    if not isinstance(status, dict):
        return {"state": "idle"}
    if status.get("state") == "starting" and process_running("/opt/factorio/bin/x64/factorio"):
        status = {**status, "state": "complete", "message": "Save restored and Factorio is running."}
    return status


def write_restore_status(state: str, message: str, source: str = "", target: str = "") -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    status = {"state": state, "message": message, "source": source, "target": target, "updated_at": time.time()}
    temporary_path = RESTORE_STATUS_PATH.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(status, separators=(",", ":")), encoding="utf-8")
    temporary_path.replace(RESTORE_STATUS_PATH)


def write_restore_request(source: str, target: str) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    request = {"source": source, "target": target, "requested_at": time.time()}
    temporary_path = RESTORE_REQUEST_PATH.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(request, separators=(",", ":")), encoding="utf-8")
    temporary_path.replace(RESTORE_REQUEST_PATH)


def prune_save_backups(saves_dir: Path, settings: dict[str, object]) -> None:
    backups = sorted(
        (path for path in saves_dir.glob(f"{SAVE_BACKUP_PREFIX}*.zip") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    max_saves = int(settings["max_saves"])
    max_bytes = int(settings["max_total_size_mb"]) * 1024 * 1024
    total_bytes = sum(path.stat().st_size for path in backups)
    for old_backup in backups[1:]:
        if len(backups) <= max_saves and (not max_bytes or total_bytes <= max_bytes):
            break
        try:
            size = old_backup.stat().st_size
            old_backup.unlink()
            backups.remove(old_backup)
            total_bytes -= size
        except OSError as exc:
            logger.warning("Could not rotate save backup %s: %s", old_backup.name, exc)


def backup_is_due(settings: dict[str, object], now: datetime) -> bool:
    last_backup_at = float(settings.get("last_backup_at", 0) or 0)
    if settings["mode"] == "hourly":
        return not last_backup_at or now.timestamp() - last_backup_at >= 3600
    if settings["mode"] == "interval":
        return not last_backup_at or now.timestamp() - last_backup_at >= int(settings["interval_hours"]) * 3600
    hour, minute = (int(value) for value in str(settings["daily_time"]).split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return now >= target and (not last_backup_at or last_backup_at < target.timestamp())


def create_save_backup() -> str | None:
    saves_dir = SHARE_DIR / "saves"
    source = saves_dir / configured_save_name()
    if not source.is_file():
        logger.warning("Scheduled save backup skipped because %s is unavailable", source.name)
        return None
    with SAVE_LOCK:
        if process_running("/opt/factorio/bin/x64/factorio"):
            try:
                previous_mtime = source.stat().st_mtime_ns
            except OSError:
                return None
            response, _, error = execute_rcon("/save")
            if response is None:
                logger.warning("Scheduled save backup skipped because Factorio could not save: %s", error)
                return None
            if not wait_for_save_completion(source, previous_mtime):
                logger.warning("Scheduled save backup skipped because Factorio did not finish saving")
                return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        destination = saves_dir / f"{SAVE_BACKUP_PREFIX}{stamp}.zip"
        temporary_path = destination.with_suffix(".tmp")
        try:
            shutil.copyfile(source, temporary_path)
            temporary_path.replace(destination)
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            logger.warning("Scheduled save backup failed: %s", exc)
            return None
    settings = load_backup_settings()
    prune_save_backups(saves_dir, settings)
    save_backup_settings(True, last_backup=destination.name, last_backup_at=time.time())
    logger.info("Created scheduled save backup %s", destination.name)
    return destination.name


def backup_scheduler() -> None:
    while True:
        now = datetime.now()
        settings = load_backup_settings()
        if settings["enabled"] and backup_is_due(settings, now):
            create_save_backup()
        time.sleep(30)


def watchdog_summary() -> dict[str, object]:
    path = Path(os.environ.get("FACTORIO_RUNTIME_DIR") or "/config/runtime") / "watchdog_snapshot.json"
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "healthy": False, "monitors": []}
    if not isinstance(snapshot, dict):
        return {"available": False, "healthy": False, "monitors": []}
    monitors = []
    processes = snapshot.get("processes", {})
    if isinstance(processes, dict):
        monitors.extend({"name": f"Process: {name}", "healthy": details.get("state") == "running"}
                        for name, details in processes.items() if isinstance(details, dict))
    ages = snapshot.get("heartbeat_age_seconds", {})
    limits = snapshot.get("heartbeat_limits_seconds", {})
    if isinstance(ages, dict) and isinstance(limits, dict):
        monitors.extend({"name": f"Worker: {name}", "healthy": float(age) <= float(limits.get(name, 60))}
                        for name, age in ages.items())
    return {"available": True, "healthy": bool(snapshot.get("healthy")), "monitors": monitors, "checked_at": snapshot.get("checked_at", 0)}


def telemetry_event_history(limit: int = 50, event_name: str = "") -> dict[str, object]:
    """Return a bounded, parsed tail of the current and previous event files."""
    bounded_limit = min(max(int(limit), 1), 200)
    event_dir = SHARE_DIR / "script-output"
    paths = [event_dir / "factorio_assistant_events.jsonl.1", event_dir / "factorio_assistant_events.jsonl"]
    events: list[dict[str, object]] = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-bounded_limit:]
        except (OSError, UnicodeDecodeError):
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and isinstance(event.get("event"), str) and (not event_name or event.get("event") == event_name):
                events.append(event)
    return {"available": bool(events), "events": events[-bounded_limit:]}


def latest_combinator_snapshots(max_tick: int | None = None) -> list[dict[str, object]]:
    """Return the latest live Signal Monitor event for each unit number."""
    event_dir = SHARE_DIR / "script-output"
    paths = [event_dir / "factorio_assistant_events.jsonl"]
    monitors: dict[str, dict[str, object]] = {}
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("event") not in {"combinator_snapshot", "combinator_reader_changed"}:
                continue
            if max_tick is not None:
                try:
                    event_tick = int(event.get("tick", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if event_tick < max_tick - 12000:
                    continue
            unit_number = str(event.get("unit_number") or "").strip()
            if not unit_number:
                continue
            if event.get("action") == "removed":
                monitors.pop(unit_number, None)
            else:
                monitors[unit_number] = event
    return list(monitors.values())


def latest_world_snapshot() -> dict[str, object] | None:
    """Read the newest world snapshot persisted by the telemetry bridge."""
    event_dir = SHARE_DIR / "script-output"
    paths = [event_dir / "factorio_assistant_events.jsonl", event_dir / "factorio_assistant_events.jsonl.1"]
    newest: dict[str, object] | None = None
    newest_tick = -1
    newest_resource_monitor: dict[str, object] | None = None
    newest_resource_monitor_tick = -1
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_type = event.get("event")
            if event_type == "resource_monitor_snapshot":
                resource_monitor = event.get("resource_monitor")
                if isinstance(resource_monitor, dict):
                    try:
                        tick = int(event.get("tick", 0) or 0)
                    except (TypeError, ValueError):
                        tick = 0
                    if tick >= newest_resource_monitor_tick:
                        newest_resource_monitor = resource_monitor
                        newest_resource_monitor_tick = tick
                continue
            if event_type != "state_snapshot":
                continue
            server = event.get("server")
            world = event.get("world")
            players = event.get("players")
            if isinstance(server, dict) and isinstance(world, dict) and isinstance(players, dict):
                try:
                    tick = int(server.get("tick", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if tick < newest_tick:
                    continue
                surfaces = []
                for name, details in world.get("surfaces", {}).items():
                    if not isinstance(details, dict):
                        continue
                    surface = {"name": str(name), **details}
                    pinned_resources = surface.get("pinned_resources", [])
                    if isinstance(pinned_resources, list):
                        surface["pinned_resources"] = [
                            {
                                **resource,
                                "type_name": localized_resource_name(resource.get("type")) if resource.get("type") else resource.get("type_name", "Resource"),
                            }
                            for resource in pinned_resources
                            if isinstance(resource, dict)
                        ]
                    surfaces.append(surface)
                player_rows = []
                for name, details in players.items():
                    if not isinstance(details, dict):
                        continue
                    position = details.get("position", {})
                    if not isinstance(position, dict):
                        position = {}
                    player_rows.append({
                        **details,
                        "name": str(name),
                        "surface": str(details.get("surface", "unknown")),
                        "x": position.get("x", 0),
                        "y": position.get("y", 0),
                        "connected": bool(details.get("connected", False)),
                    })
                surface_names = sorted(str(surface.get("name", "")) for surface in surfaces if surface.get("name"))
                newest = {
                    "available": True,
                    "tick": tick,
                    "ups": server.get("ups", 0),
                    "speed": server.get("speed", 0),
                    "players_online": sum(1 for player in player_rows if player.get("connected")),
                    "tick_paused": server.get("tick_paused", False),
                    "daytime": world.get("daytime", 0),
                    "day_night_cycle": world.get("day_night_cycle", False),
                    "daylight": world.get("daylight", False),
                    "enemy_evolution_enabled": world.get("enemy_evolution_enabled", False),
                    "pollution_enabled": world.get("pollution_enabled", False),
                    "evolution": world.get("evolution_factor", world.get("evolution", 0)),
                    "evolution_progress": world.get("evolution_progress", 0),
                    "game_day": world.get("game_day", 0),
                    "game_time": world.get("game_time", ""),
                    "research": world.get("research", ""),
                    "research_localized_name": localized_technology_name(world.get("research", "")),
                    "research_progress": world.get("research_progress", 0),
                    "research_queue": world.get("research_queue", []),
                    "research_queue_localized_names": [
                        localized_technology_name(item)
                        for item in world.get("research_queue", []) or []
                    ],
                    "technologies_researched": world.get("technologies_researched", 0),
                    "technologies_total": world.get("technologies_total", 0),
                    "rockets_launched": world.get("rockets_launched", 0),
                    "active_entity_count": world.get("active_entity_count", 0),
                    "vehicle_counts": world.get("vehicle_counts", {}),
                    "surface_count": len(surfaces),
                    "surface_names": ",".join(surface_names),
                    "ltn": world.get("ltn", {}),
                    "surfaces": surfaces,
                    "players": player_rows,
                    "combinators": latest_combinator_snapshots(tick),
                }
                newest_tick = tick
    if newest is not None and newest_resource_monitor is not None:
        resource_monitor = newest_resource_monitor
        surfaces = resource_monitor.get("surfaces")
        if isinstance(surfaces, dict):
            normalized_surfaces = []
            for name, details in surfaces.items():
                if not isinstance(details, dict):
                    continue
                surface = {"name": str(name), **details}
                tracked_resources = surface.get("tracked_resources", [])
                if isinstance(tracked_resources, list):
                    surface["tracked_resources"] = [
                        {
                            **resource,
                            "type_name": localized_resource_name(resource.get("type")) if resource.get("type") else resource.get("type_name", "Resource"),
                        }
                        for resource in tracked_resources
                        if isinstance(resource, dict)
                    ]
                normalized_surfaces.append(surface)
            resource_monitor = {**resource_monitor, "surfaces": normalized_surfaces}
        newest["resource_monitor"] = resource_monitor
    return newest


def world_summary() -> dict[str, object]:
    snapshot = latest_world_snapshot()
    if snapshot is not None:
        return snapshot
    mod_response = execute_mod_command("world_summary", "")
    if mod_response is not None and mod_response.get("ok") and isinstance(mod_response.get("result"), dict):
        return mod_response["result"]
    return {"available": False, "surfaces": [], "players": [], "error": "Factorio Assistant mod interface is unavailable."}


def dashboard_data(request_host: str = "") -> dict[str, object]:
    saves = file_summary(SHARE_DIR / "saves", ".zip")
    mods = installed_mod_summary()
    config_dir = Path(os.environ.get("CONFIG_DIR") or "/config")
    players = known_player_summary()
    live_players = cached_player_summary()
    merged_players = {
        player["name"]: {"name": player["name"], "connected": False}
        for player in players
        if player.get("name")
    }
    for username, live_player in live_players.items():
        if live_player.get("connected"):
            merged_players[username] = {**merged_players.get(username, {}), **live_player}
        elif username not in merged_players:
            merged_players[username] = {"name": username, "connected": False}
    server_name = "Factorio Server"
    try:
        settings = json.loads(SERVER_SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(settings, dict) and isinstance(settings.get("name"), str) and settings["name"].strip():
            server_name = settings["name"].strip()
    except (OSError, json.JSONDecodeError):
        pass
    diagnostics: dict[str, object] = {"save_file": "", "save_size": 0, "cpu_usage": 0.0, "mem_usage": 0.0, "uptime": 0}
    configured_path = SHARE_DIR / "saves" / configured_save_name()
    if configured_path.is_file():
        try:
            diagnostics["save_file"] = configured_path.name
            diagnostics["save_size"] = configured_path.stat().st_size
        except OSError:
            pass
    try:
        for process in psutil.process_iter(["name", "exe", "cpu_percent", "memory_percent", "create_time"]):
            identity = f"{process.info.get('name', '')} {process.info.get('exe', '')}".lower()
            if "factorio" in identity:
                diagnostics["cpu_usage"] = round(float(process.info.get("cpu_percent") or 0), 1)
                diagnostics["mem_usage"] = round(float(process.info.get("memory_percent") or 0), 1)
                diagnostics["uptime"] = int(max(0, time.time() - float(process.info.get("create_time") or time.time())))
                break
    except (OSError, psutil.Error, TypeError, ValueError):
        pass
    return {
        "factorio": {
            "name": server_name,
            "running": process_running("/opt/factorio/bin/x64/factorio"),
            "version": "2.0.77",
            "game_port": configured_port("server_port", 34197),
            "rcon_port": configured_port("rcon_port", 27015),
        },
        "bridge": {
            "running": process_running("factorio-assistant-service.py"),
            "rcon_password_present": bool(rcon_password()),
            "host": connection_summary(request_host)["ip"],
        },
        "storage": {
            "saves": saves,
            "save_details": save_summary(),
            "mods": mods,
            "save_count": len(saves),
            "mod_count": len(mods),
        },
        "players": list(merged_players.values()),
        "log": read_log_tail(),
        "processes": {
            "web": process_running("web_server.py"),
            "bridge": process_running("factorio-assistant-service.py"),
            "factorio": process_running("/opt/factorio/bin/x64/factorio"),
        },
        "watchdog": watchdog_summary(),
        "diagnostics": diagnostics,
        "restore": restore_status(),
        "connection": connection_summary(request_host),
        "generated_at": time.time(),
    }


class IngressHandler(BaseHTTPRequestHandler):
    server_version = "FactorioWeb/1.0"

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _allowed(self) -> bool:
        return self.client_address[0] == INGRESS_PROXY_IP

    def _rcon_allowed(self) -> bool:
        try:
            return ipaddress.ip_address(self.client_address[0]) in HA_INTERNAL_NETWORK
        except ValueError:
            return False

    def _api_token_allowed(self) -> bool:
        if not API_TOKEN:
            return False
        supplied = self.headers.get("X-Factorio-API-Token", "")
        return bool(supplied) and hmac.compare_digest(supplied, API_TOKEN)

    def _rest_allowed(self) -> bool:
        return self._rcon_allowed() or self._api_token_allowed()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if WEB_ROLE == "api":
            allowed = self._rest_allowed()
        else:
            allowed = self._allowed()
        if not allowed:
            self._send(b"Forbidden", "text/plain; charset=utf-8", 403)
            return
        if path == "/api/status":
            try:
                payload = json.dumps(dashboard_data(self.headers.get("Host", "")), separators=(",", ":")).encode()
                self._send(payload, "application/json; charset=utf-8")
            except Exception as exc:
                logger.exception("Status payload generation failed")
                self._send(json.dumps({"error": f"Status generation failed: {exc}"}).encode(), "application/json; charset=utf-8", 500)
            return
        if path == "/api/world":
            payload = json.dumps({**world_summary(), "storage": save_summary(), "mods": installed_mod_summary()}, separators=(",", ":")).encode()
            self._send(payload, "application/json; charset=utf-8")
            return
        if path == "/api/telemetry/events":
            query = parse_qs(urlparse(self.path).query)
            try:
                limit = int(query.get("limit", [50])[0])
            except ValueError:
                limit = 50
            event_name = str(query.get("event", [""])[0] or "").strip()
            payload = json.dumps(telemetry_event_history(limit, event_name), separators=(",", ":")).encode()
            self._send(payload, "application/json; charset=utf-8")
            return
        if path == "/api/research":
            try:
                payload = json.dumps(research_summary(), separators=(",", ":")).encode()
            except Exception as exc:
                logging.getLogger("FactorioWebRCON").warning("Research query failed: %s", exc)
                payload = b'{"available":false,"researched":[],"current":"","progress":0.0,"queue":[]}'
            self._send(payload, "application/json; charset=utf-8")
            return
        if path == "/api/icon":
            asset = read_icon_asset(parse_qs(urlparse(self.path).query).get("path", [""])[0])
            if asset is None:
                self._send(b"Not found", "text/plain; charset=utf-8", 404)
                return
            self._send(*asset)
            return
        if path == "/api/catalog":
            try:
                payload = json.dumps(catalog_search(parse_qs(urlparse(self.path).query)), separators=(",", ":")).encode()
                self._send(payload, "application/json; charset=utf-8")
            except FileNotFoundError as exc:
                self._send(json.dumps({"error": str(exc)}).encode(), "application/json; charset=utf-8", 503)
            except ValueError as exc:
                self._send(json.dumps({"error": str(exc)}).encode(), "application/json; charset=utf-8", 400)
            except (json.JSONDecodeError, OSError) as exc:
                self._send(json.dumps({"error": str(exc)}).encode(), "application/json; charset=utf-8", 500)
            return
        if path == "/api/catalog/entry":
            try:
                payload = json.dumps(catalog_entry(parse_qs(urlparse(self.path).query)), separators=(",", ":")).encode()
                self._send(payload, "application/json; charset=utf-8")
            except FileNotFoundError as exc:
                self._send(json.dumps({"error": str(exc)}).encode(), "application/json; charset=utf-8", 503)
            except ValueError as exc:
                self._send(json.dumps({"error": str(exc)}).encode(), "application/json; charset=utf-8", 400)
            except (json.JSONDecodeError, OSError) as exc:
                self._send(json.dumps({"error": str(exc)}).encode(), "application/json; charset=utf-8", 500)
            return
        if WEB_ROLE == "api":
            self._send(b"Not found", "text/plain; charset=utf-8", 404)
            return
        if path in {"/", "/index.html"}:
            self._serve_index()
            return
        if path == "/assets/app.css":
            self._serve_file(WEB_ASSET_DIR / "app.css", "text/css; charset=utf-8")
            return
        if path == "/app.css":
            self._serve_file(WEB_ASSET_DIR / "app.css", "text/css; charset=utf-8")
            return
        if path == "/assets/app.js":
            self._serve_file(WEB_ASSET_DIR / "app.js", "text/javascript; charset=utf-8")
            return
        if path == "/app.js":
            self._serve_file(WEB_ASSET_DIR / "app.js", "text/javascript; charset=utf-8")
            return
        self._send(b"Not found", "text/plain; charset=utf-8", 404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        save_paths = {"/api/saves/restore", "/api/saves/delete", "/api/saves/backup-settings"}
        allowed = self._allowed() if WEB_ROLE == "ui" and path in save_paths else self._rest_allowed()
        if not allowed:
            self._send(b"Forbidden", "text/plain; charset=utf-8", 403)
            return
        if path not in {"/api/rcon", "/api/catalog/production", "/api/factory/inspect", "/api/factory/map", "/api/factory/production", "/api/factory/plan", "/api/factory/build", "/api/factory/demolish", "/api/factory/helper", *save_paths}:
            self._send(b"Not found", "text/plain; charset=utf-8", 404)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            content_length = -1
        max_body_size = 8192 if path == "/api/rcon" else 16384
        if content_length < 0 or content_length > max_body_size:
            self._send(
                json.dumps({"error": f"Request body must be valid JSON no larger than {max_body_size} bytes."}).encode(),
                "application/json; charset=utf-8",
                400,
            )
            return
        try:
            payload = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(b'{"error":"Request body must be valid JSON."}', "application/json; charset=utf-8", 400)
            return
        if path == "/api/catalog/production":
            try:
                response = json.dumps(catalog_production(payload), separators=(",", ":")).encode()
                self._send(response, "application/json; charset=utf-8")
            except FileNotFoundError as exc:
                self._send(json.dumps({"error": str(exc)}).encode(), "application/json; charset=utf-8", 503)
            except ValueError as exc:
                self._send(json.dumps({"error": str(exc)}).encode(), "application/json; charset=utf-8", 400)
            except (json.JSONDecodeError, OSError) as exc:
                self._send(json.dumps({"error": str(exc)}).encode(), "application/json; charset=utf-8", 500)
            return
        if path == "/api/saves/backup-settings":
            enabled = payload.get("enabled") if isinstance(payload, dict) else None
            schedule = {key: payload.get(key) for key in ("mode", "interval_hours", "daily_time", "max_saves", "max_total_size_mb")} if isinstance(payload, dict) else {}
            try:
                valid_schedule = (
                    schedule["mode"] in {"hourly", "daily", "interval"}
                    and isinstance(schedule["daily_time"], str) and is_valid_time(schedule["daily_time"])
                    and 1 <= int(schedule["interval_hours"]) <= 168
                    and 1 <= int(schedule["max_saves"]) <= 1000
                    and 0 <= int(schedule["max_total_size_mb"]) <= 102400
                )
            except (KeyError, TypeError, ValueError):
                valid_schedule = False
            if not isinstance(enabled, bool) or not valid_schedule:
                self._send(b'{"error":"Invalid backup schedule or retention settings."}', "application/json; charset=utf-8", 400)
                return
            schedule["interval_hours"] = int(schedule["interval_hours"])
            schedule["max_saves"] = int(schedule["max_saves"])
            schedule["max_total_size_mb"] = int(schedule["max_total_size_mb"])
            self._send(json.dumps(save_backup_settings(enabled, schedule), separators=(",", ":")).encode(), "application/json; charset=utf-8")
            return
        if path == "/api/saves/delete":
            name = payload.get("name") if isinstance(payload, dict) else None
            configured = configured_save_name()
            target = SHARE_DIR / "saves" / name if isinstance(name, str) else None
            if not target or target.name != name or target.suffix.casefold() != ".zip" or name == configured:
                self._send(b'{"error":"Only a non-configured save .zip file can be deleted."}', "application/json; charset=utf-8", 400)
                return
            try:
                if target.resolve().parent != (SHARE_DIR / "saves").resolve() or not target.is_file():
                    raise OSError("save file is unavailable")
                target.unlink()
            except OSError as exc:
                self._send(json.dumps({"error": f"Delete failed: {exc}"}).encode(), "application/json; charset=utf-8", 409)
                return
            self._send(json.dumps({"deleted": name}, separators=(",", ":")).encode(), "application/json; charset=utf-8")
            return
        if path == "/api/saves/restore":
            source = payload.get("source") if isinstance(payload, dict) else None
            storage = save_summary()
            target = str(storage["configured"])
            if not isinstance(source, str) or Path(source).name != source or Path(source).suffix.casefold() != ".zip" or source == target:
                self._send(b'{"error":"Select a different save .zip file to restore."}', "application/json; charset=utf-8", 400)
                return
            source_path = SHARE_DIR / "saves" / source
            target_path = SHARE_DIR / "saves" / Path(target).name
            current_restore = restore_status()
            if current_restore.get("state") in {"stopping", "restoring", "starting"}:
                self._send(b'{"error":"A save restore is already in progress."}', "application/json; charset=utf-8", 409)
                return
            if process_running("/opt/factorio/bin/x64/factorio"):
                try:
                    if source_path.resolve().parent != target_path.resolve().parent or not source_path.is_file():
                        raise OSError("save file is unavailable")
                    write_restore_request(source, target_path.name)
                    write_restore_status("stopping", "Stopping Factorio before restoring the save.", source, target_path.name)
                    pid = int((RUNTIME_DIR / "factorio.pid").read_text(encoding="utf-8").strip())
                    os.kill(pid, signal.SIGTERM)
                except (OSError, ValueError) as exc:
                    write_restore_status("error", f"Could not stop Factorio: {exc}", source, target_path.name)
                    RESTORE_REQUEST_PATH.unlink(missing_ok=True)
                    self._send(json.dumps({"error": str(exc)}).encode(), "application/json; charset=utf-8", 409)
                    return
                self._send(json.dumps({"state": "stopping", "source": source, "target": target_path.name}, separators=(",", ":")).encode(), "application/json; charset=utf-8", 202)
                return
            try:
                if source_path.resolve().parent != target_path.resolve().parent or not source_path.is_file():
                    raise OSError("save file is unavailable")
                temporary_path = target_path.with_suffix(target_path.suffix + ".restore.tmp")
                write_restore_status("restoring", "Restoring the selected save.", source, target_path.name)
                shutil.copyfile(source_path, temporary_path)
                temporary_path.replace(target_path)
            except OSError as exc:
                write_restore_status("error", f"Restore failed: {exc}", source, target_path.name)
                self._send(json.dumps({"error": f"Restore failed: {exc}"}).encode(), "application/json; charset=utf-8", 409)
                return
            write_restore_status("complete", "Save restored. Factorio remains stopped.", source, target_path.name)
            self._send(json.dumps({"restored": source, "target": target_path.name}, separators=(",", ":")).encode(), "application/json; charset=utf-8")
            return
        if path != "/api/rcon":
            result, status, error = factory_query(path, payload)
            response = result if result is not None else {"error": error}
            self._send(json.dumps(response, separators=(",", ":")).encode(), "application/json; charset=utf-8", status)
            return
        command = payload.get("command") if isinstance(payload, dict) else None
        if not isinstance(command, str) or not command.strip() or len(command) > 4096:
            self._send(b'{"error":"JSON must contain a non-empty command of at most 4096 characters."}', "application/json; charset=utf-8", 400)
            return
        response, status, error = execute_rcon(command)
        result = {"command": command, "response": response} if response is not None else {"error": error}
        self._send(json.dumps(result, separators=(",", ":")).encode(), "application/json; charset=utf-8", status)

    def _serve_file(self, path: Path, content_type: str) -> None:
        try:
            self._send(path.read_bytes(), content_type)
        except OSError:
            self._send(b"Not found", "text/plain; charset=utf-8", 404)

    def _serve_index(self) -> None:
        try:
            body = WEB_DIR.joinpath("index.html").read_text(encoding="utf-8")
        except OSError:
            self._send(b"Not found", "text/plain; charset=utf-8", 404)
            return
        ingress_path = self.headers.get("X-Ingress-Path", "/").strip()
        if not ingress_path.startswith("/") or any(character in ingress_path for character in '"\'<>'):
            ingress_path = "/"
        base_path = ingress_path.rstrip("/") + "/"
        base_tag = f'<base href="{html.escape(base_path, quote=True)}">'
        body = body.replace('<meta name="viewport"', f'{base_tag}\n  <meta name="viewport"', 1)
        self._send(body.encode("utf-8"), "text/html; charset=utf-8")

    def log_message(self, format: str, *args: object) -> None:
        message = f"{self.address_string()} - {format % args}"
        status_value = args[1] if len(args) > 1 else None
        status_code = int(status_value) if isinstance(status_value, str) and status_value.isdigit() else 0
        if status_code < 400 and urlparse(self.path).path == "/api/icon":
            return
        logger.log(logging.WARNING if status_code >= 400 else logging.DEBUG, message)


class ThreadingIngressServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    if WEB_ROLE == "ui":
        threading.Thread(target=backup_scheduler, name="save-backup", daemon=True).start()
    with ThreadingIngressServer((HOST, PORT), IngressHandler) as server:
        logger.info("Ingress %s server listening on %s:%s", WEB_ROLE, HOST, PORT)
        server.serve_forever()


if __name__ == "__main__":
    main()
