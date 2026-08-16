"""Constants for the Factorio Assistant integration."""

from __future__ import annotations

from datetime import timedelta
from homeassistant.const import Platform

DOMAIN = "factorio_assistant"
BUS_EVENT = "factorio_assistant_event"
CHAT_EVENT = "factorio_assistant_chat"
DEFAULT_PORT = 8098
DEFAULT_SCAN_INTERVAL = timedelta(minutes=1)
CONF_HOST = "host"
CONF_PORT = "port"
CONF_API_TOKEN = "api_token"
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SWITCH, Platform.BUTTON, Platform.EVENT]
BRIDGE_VERSION = "0.3.0"
BRIDGE_DEVICE_NAME = "Factorio Assistant Bridge"
BRIDGE_MODEL = "Home Assistant Add-on"
SERVER_MODEL = "Factorio Headless Server"
FACTORIO_MANUFACTURER = "Wube Software"