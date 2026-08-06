# Troubleshooting

## RCON Connection Issues

Check that the configured `rcon_port` is available and that Factorio has finished starting. The bridge waits for an RCON `/version` response before collecting telemetry. When `api_token` is configured, it is reused for RCON in memory. When it is empty, a random RCON password is generated in memory for the current boot, so external RCON clients cannot authenticate.

## REST API Access

An `api_token` is required for REST API and RCON access from outside the Supervisor internal network. If it is empty, external REST clients receive `403 Forbidden` and external RCON clients cannot authenticate; Home Assistant internal-network requests and ingress controls remain allowed.

## MQTT Entities Missing

Verify that:

- The MQTT broker is reachable from the add-on.
- Home Assistant is connected to the same broker.
- The configured `mqtt_prefix` matches the discovery prefix used by Home Assistant.
- The add-on logs show MQTT connection and discovery activity.

## Mod Download Issues

Confirm the Factorio account credentials if authenticated downloads are enabled. Also verify that the container can reach the Factorio Mod Portal.
Mod Portal checks have a 20-second API timeout and downloads have a 120-second timeout; timeout warnings identify the affected mod, and startup continues with its existing archive.

## Telemetry Missing

Verify that RCON is available, Factorio has finished starting, and the MQTT broker is reachable. The RCON availability topic should report the bridge's current connection state.

## Save File Errors

On first start the add-on creates the configured save from `/config/map-gen-settings.json` and `/config/map-settings.json`. If world creation fails, inspect `/share/factorio/logs/world-create.log` and validate those files against the matching templates in `/app/factorio-templates`.

## Logs

Container startup and bridge diagnostics are available through the add-on log. Persistent Factorio logs and script-output telemetry are stored under `/share/factorio`.
