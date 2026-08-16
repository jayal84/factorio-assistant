"""Shared REST data coordinator for Factorio Assistant."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import BUS_EVENT, CHAT_EVENT, CONF_API_TOKEN, CONF_HOST, CONF_PORT, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__package__)


class FactorioAssistantCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch the shared world and service snapshots for all entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.session = async_get_clientsession(hass)
        host = str(entry.data[CONF_HOST]).rstrip("/")
        port = int(entry.data[CONF_PORT])
        self.base_url = host if "://" in host else f"http://{host}"
        if self.base_url.rsplit(":", 1)[-1].isdigit() is False:
            self.base_url = f"{self.base_url}:{port}"
        self.api_token = str(entry.data.get(CONF_API_TOKEN, ""))
        self._seen_events: set[str] = set()
        self._event_history_initialized = False
        self._previous_tick: float | None = None
        self._previous_research_progress: float | None = None
        self._previous_pollution: dict[str, float] = {}
        # Event poller task for prioritized event delivery (fast updates)
        self._event_task: asyncio.Task | None = None
        self._event_poll_interval = 2.0
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        # start prioritized event poller
        self._event_task = hass.loop.create_task(self._event_poller())

    async def _async_get(self, path: str) -> dict[str, Any]:
        headers = {"X-Factorio-API-Token": self.api_token} if self.api_token else {}
        try:
            async with asyncio.timeout(10):
                async with self.session.get(f"{self.base_url}{path}", headers=headers) as response:
                    response.raise_for_status()
                    payload = await response.json()
        except (asyncio.TimeoutError, ClientError) as err:
            raise UpdateFailed(f"Unable to fetch {path}: {err}") from err
        if not isinstance(payload, dict):
            raise UpdateFailed(f"Invalid response from {path}")
        return payload

    async def async_request_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call an authenticated JSON GET endpoint for a service response."""
        headers = {"X-Factorio-API-Token": self.api_token} if self.api_token else {}
        try:
            async with asyncio.timeout(30):
                async with self.session.get(f"{self.base_url}{path}", headers=headers, params=params) as response:
                    payload = await response.json(content_type=None)
        except (asyncio.TimeoutError, ClientError) as err:
            raise UpdateFailed(f"Unable to request {path}: {err}") from err
        if not isinstance(payload, dict):
            raise UpdateFailed(f"Invalid response from {path}")
        return payload

    async def async_request(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Call an authenticated JSON POST endpoint for a service response."""
        headers = {"X-Factorio-API-Token": self.api_token} if self.api_token else {}
        try:
            async with asyncio.timeout(30):
                async with self.session.post(f"{self.base_url}{path}", headers=headers, json=payload) as response:
                    result = await response.json(content_type=None)
        except (asyncio.TimeoutError, ClientError) as err:
            raise UpdateFailed(f"Unable to request {path}: {err}") from err
        if not isinstance(result, dict):
            raise UpdateFailed(f"Invalid response from {path}")
        return result

    async def async_set_combinator_signal(self, unit_number: str, network: str, slot: str, value: int) -> None:
        """Set a Signal Monitor control slot through the bridge API."""
        command = (
            "/silent-command local ok,result=pcall(remote.call,"
            f"{json.dumps('factorio_assistant')},{json.dumps('set_combinator_signal')},"
            f"{json.dumps(str(unit_number))},{json.dumps(str(network))},"
            f"{json.dumps(str(slot))},{int(value)});"
            "rcon.print(helpers.table_to_json({ok=ok,result=result}))"
        )
        headers = {"X-Factorio-API-Token": self.api_token} if self.api_token else {}
        try:
            async with asyncio.timeout(10):
                async with self.session.post(
                    f"{self.base_url}/api/rcon",
                    headers=headers,
                    json={"command": command},
                ) as response:
                    response.raise_for_status()
                    payload = await response.json()
        except (asyncio.TimeoutError, ClientError) as err:
            raise UpdateFailed(f"Unable to set Signal Monitor control: {err}") from err
        if not isinstance(payload, dict) or payload.get("error"):
            raise UpdateFailed("Factorio Assistant rejected the Signal Monitor control")

    async def async_call_mod(self, method: str, *arguments: Any) -> None:
        """Call an authoritative Factorio Assistant mod control through the bridge."""
        encoded_arguments = ",".join(json.dumps(argument) for argument in arguments)
        command = (
            "/silent-command local ok,result=pcall(remote.call,"
            f"{json.dumps('factorio_assistant')},{json.dumps(method)}"
            f"{',' if encoded_arguments else ''}{encoded_arguments});"
            "rcon.print(helpers.table_to_json({ok=ok,result=result}))"
        )
        headers = {"X-Factorio-API-Token": self.api_token} if self.api_token else {}
        try:
            async with asyncio.timeout(10):
                async with self.session.post(
                    f"{self.base_url}/api/rcon",
                    headers=headers,
                    json={"command": command},
                ) as response:
                    response.raise_for_status()
                    payload = await response.json()
        except (asyncio.TimeoutError, ClientError) as err:
            raise UpdateFailed(f"Unable to set Factorio control: {err}") from err
        if not isinstance(payload, dict) or payload.get("error"):
            raise UpdateFailed(f"Factorio Assistant rejected control {method}")

    async def async_call_mod_result(self, method: str, *arguments: Any) -> dict[str, Any]:
        """Call a mod method and preserve its structured result for a service."""
        encoded_arguments = ",".join(json.dumps(argument) for argument in arguments)
        command = (
            "/silent-command local ok,result=pcall(remote.call,"
            f"{json.dumps('factorio_assistant')},{json.dumps(method)}"
            f"{',' if encoded_arguments else ''}{encoded_arguments});"
            "rcon.print(helpers.table_to_json({ok=ok,result=result}))"
        )
        payload = await self.async_request("/api/rcon", {"command": command})
        response = payload.get("response")
        if not isinstance(response, str):
            return {"error": payload.get("error", f"Factorio Assistant rejected control {method}")}
        try:
            envelope = json.loads(response)
        except json.JSONDecodeError:
            return {"error": "Factorio returned an invalid structured response."}
        if not isinstance(envelope, dict) or envelope.get("ok") is not True:
            message = envelope.get("error") or envelope.get("result") or f"Factorio Assistant rejected control {method}" if isinstance(envelope, dict) else f"Factorio Assistant rejected control {method}"
            if isinstance(message, str) and message.startswith("disabled:"):
                return {"error": "disabled", "message": message}
            return {"error": message}
        result = envelope.get("result")
        return result if isinstance(result, dict) else {"result": result}

    async def _async_update_data(self) -> dict[str, Any]:
        world, status, events = await asyncio.gather(
            self._async_get("/api/world"),
            self._async_get("/api/status"),
            self._async_get("/api/telemetry/events?limit=50"),
        )
        self._async_fire_new_events(events)
        derived = self._derive_metrics(world)
        chat_events = {
            "events": [
                event
                for event in events.get("events", [])
                if isinstance(event, dict) and event.get("event") == "console_chat"
            ]
        }
        return {"world": world, "status": status, "events": events, "chat_events": chat_events, "derived": derived, "rcon": {"connected": True}}

    def _derive_metrics(self, world: dict[str, Any]) -> dict[str, Any]:
        """Estimate rates from successive Factorio tick snapshots."""
        try:
            tick = float(world.get("tick"))
        except (TypeError, ValueError):
            tick = None
        research_seconds = None
        try:
            progress = float(world.get("research_progress"))
        except (TypeError, ValueError):
            progress = None
        if tick is not None and progress is not None and self._previous_tick is not None and self._previous_research_progress is not None:
            tick_delta = tick - self._previous_tick
            progress_delta = progress - self._previous_research_progress
            if tick_delta > 0 and progress_delta > 0 and 0 <= progress < 1:
                research_seconds = round((1 - progress) * tick_delta / progress_delta / 60, 3)

        pollution_rates: dict[str, float] = {}
        surfaces = world.get("surfaces", [])
        if isinstance(surfaces, list):
            for surface in surfaces:
                if not isinstance(surface, dict) or not surface.get("name"):
                    continue
                name = str(surface["name"])
                try:
                    pollution = float(surface.get("pollution", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if tick is not None and self._previous_tick is not None and name in self._previous_pollution:
                    tick_delta = tick - self._previous_tick
                    if tick_delta > 0:
                        pollution_rates[name] = round((pollution - self._previous_pollution[name]) / (tick_delta / 60), 3)
                self._previous_pollution[name] = pollution

        if tick is not None:
            self._previous_tick = tick
        if progress is not None:
            self._previous_research_progress = progress
        return {"research_completion_seconds": research_seconds, "pollution_rates": pollution_rates}

    def _async_fire_new_events(self, event_history: dict[str, Any]) -> None:
        """Fire bus events for records not seen by this coordinator."""
        events = event_history.get("events", [])
        if not isinstance(events, list):
            return

        records: list[tuple[str, dict[str, Any]]] = []
        for event in events:
            if not isinstance(event, dict) or not isinstance(event.get("event"), str):
                continue
            identity = json.dumps(event, sort_keys=True, separators=(",", ":"))
            records.append((identity, event))

        if not self._event_history_initialized:
            self._seen_events = {identity for identity, _ in records}
            self._event_history_initialized = True
            return

        for identity, event in records:
            if identity in self._seen_events:
                continue
            event_data = dict(event)
            event_data["event_type"] = event["event"]
            self.hass.bus.async_fire(BUS_EVENT, event_data)
            if event["event"] == "console_chat":
                self.hass.bus.async_fire(CHAT_EVENT, event_data)

        self._seen_events.update(identity for identity, _ in records)
        if len(self._seen_events) > 200:
            self._seen_events = {identity for identity, _ in records}

    async def _event_poller(self) -> None:
        """Poll the telemetry events endpoint at a higher cadence for priority events.

        This runs in a background task and fires Hub events immediately when new
        records are observed, without waiting for the main coordinator interval.
        """
        try:
            while True:
                try:
                    events = await self._async_get(f"/api/telemetry/events?limit=50")
                except UpdateFailed:
                    await asyncio.sleep(self._event_poll_interval)
                    continue
                # Fire any unseen events immediately
                try:
                    self._async_fire_new_events(events)
                except Exception:
                    _LOGGER.exception("Error while firing new events from event poller")
                # Also update minimal chat_events slice in coordinator data for listeners
                chat_events = {
                    "events": [
                        event
                        for event in events.get("events", [])
                        if isinstance(event, dict) and event.get("event") == "console_chat"
                    ]
                }
                # merge with existing data snapshot if present
                try:
                    current = dict(self.data) if isinstance(self.data, dict) else {}
                    current["events"] = events
                    current["chat_events"] = chat_events
                    latest_snapshot = next(
                        (
                            event
                            for event in reversed(events.get("events", []))
                            if isinstance(event, dict) and event.get("event") == "state_snapshot"
                        ),
                        None,
                    )
                    if isinstance(latest_snapshot, dict):
                        snapshot_world = latest_snapshot.get("world")
                        if isinstance(snapshot_world, dict):
                            merged_world = dict(current.get("world", {})) if isinstance(current.get("world"), dict) else {}
                            merged_world.update(snapshot_world)
                            merged_world.setdefault("available", True)
                            current["world"] = merged_world
                    # notify listeners without changing the slower world/status snapshot
                    await self.async_set_updated_data(current)
                except Exception:
                    _LOGGER.debug("Failed to update coordinator data with chat_events from fast poller")
                await asyncio.sleep(self._event_poll_interval)
        except asyncio.CancelledError:
            return

    async def async_stop(self) -> None:
        """Stop the event poller task when the entry is unloaded."""
        if self._event_task is not None:
            self._event_task.cancel()
            try:
                await self._event_task
            except asyncio.CancelledError:
                pass
            self._event_task = None