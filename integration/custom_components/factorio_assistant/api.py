"""HTTP push endpoint for prioritized Factorio events."""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import BUS_EVENT, CHAT_EVENT, DOMAIN

_LOGGER = logging.getLogger(__package__)


class FactorioPushView(HomeAssistantView):
    url = "/api/factorio_assistant/push"
    name = "api:factorio_assistant:push"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:  # type: ignore[override]
        try:
            body = await request.text()
            payload = json.loads(body)
        except Exception as exc:
            _LOGGER.debug("Invalid push payload: %s", exc)
            return web.Response(status=400, text="invalid payload")

        token = request.headers.get("X-Factorio-API-Token", "")

        # Find coordinator with matching api_token
        coordinators = self.hass.data.get(DOMAIN, {})
        target = None
        for entry_id, coordinator in coordinators.items():
            if getattr(coordinator, "api_token", "") == token:
                target = coordinator
                break

        if target is None:
            _LOGGER.warning("Push rejected: no matching coordinator for token")
            return web.Response(status=401, text="unauthorized")

        if not isinstance(payload, dict) or not isinstance(payload.get("event"), str):
            return web.Response(status=400, text="invalid event")

        try:
            identity = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        except Exception:
            identity = None

        if identity and identity in getattr(target, "_seen_events", set()):
            return web.Response(status=204)

        # mark seen to avoid duplicates
        if identity:
            getattr(target, "_seen_events", set()).add(identity)

        event_data: dict[str, Any] = dict(payload)
        event_data["event_type"] = payload.get("event")

        # Fire onto the hass bus
        try:
            target.hass.bus.async_fire(BUS_EVENT, event_data)
            if payload.get("event") == "console_chat":
                target.hass.bus.async_fire(CHAT_EVENT, event_data)
        except Exception:
            _LOGGER.exception("Failed to deliver pushed Factorio event")
            return web.Response(status=500, text="delivery failed")

        return web.Response(status=200, text="ok")
