"""Config flow for the Factorio Assistant REST integration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import CONF_API_TOKEN, CONF_PORT, DEFAULT_PORT, DOMAIN


class FactorioAssistantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a Factorio Assistant bridge endpoint."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip().rstrip("/")
            port = int(user_input[CONF_PORT])
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()
            if host.startswith("http://") or host.startswith("https://"):
                title = host
            else:
                title = f"Factorio Assistant ({host})"
            return self.async_create_entry(
                title=title,
                data={
                    CONF_HOST: host,
                    CONF_PORT: port,
                    CONF_API_TOKEN: str(user_input.get(CONF_API_TOKEN, "")),
                },
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default="homeassistant.local"): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
                vol.Optional(CONF_API_TOKEN, default=""): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
