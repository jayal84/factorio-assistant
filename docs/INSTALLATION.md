# Installation And Configuration

## Requirements

Before installing, make sure you have:

- Home Assistant OS, Supervised, or Container on Linux x86-64 (amd64)
- A Mosquitto MQTT broker available to Home Assistant
- Enough disk space in `/share/factorio` for saves, mods, and logs
- Network access for Factorio server ports:
  - `34197/UDP` for game traffic by default; configurable with `server_port`
  - `27015/TCP` for RCON by default; configurable with `rcon_port`
  - `8100/TCP` for the authenticated REST API by default; configurable with `rest_api_port`
- Host networking is enabled so Factorio LAN discovery broadcasts can leave the container.
- Optional Factorio account credentials for authenticated mod downloads

For file-based add-on configuration, create `/addon_configs/local_factorio_assistant`
on the Home Assistant host. Home Assistant mounts this directory as `/config`
inside the add-on. The image installs read-only example templates at
`/app/factorio-templates` during the add-on build. On first start, missing
editable Factorio files are copied into `/config`; existing files are never
overwritten.

## Installation

1. Add this repository to the Home Assistant add-on store.
2. Install the add-on and wait for the build to finish.
3. Configure the add-on options, including MQTT connection details and the MQTT discovery prefix.
4. Start the add-on and monitor the logs for MQTT and RCON readiness.
5. Open **Factorio Assistant** from the add-on panel. Home Assistant ingress on `8099` provides the authenticated web entry point. REST commands use the separate authenticated API listener on the configured `rest_api_port`; do not route REST commands through the ingress port.

## Configuration

| Option | Default | Purpose |
| :--- | :--- | :--- |
| `refresh_rate_profile` | `medium` | Telemetry polling profile: slow, medium, fast, high, or debug |
| `save_name` | `world.zip` | Save filename in `/share/factorio/saves`; created from the map settings only when it does not exist |
| `enable_mod_updates` | `false` | Check the Mod Portal for updates when enabled |
| `enable_telemetry_mod` | `true` | Enable the bundled Factorio Assistant mod for structured events, snapshots, and validated commands; the versioned archive is installed in `/share/factorio/mods/factorio_assistant_<version>.zip` |
| `server_port` | `34197` | Factorio game traffic port; change it if the host port is already in use |
| `rcon_port` | `27015` | Factorio RCON port used by the bridge and web controls; change it if the host port is already in use |
| `rest_api_port` | `8100` | Authenticated REST API port; change it if the host port is already in use |
| `api_token` | empty | API key for REST and external RCON access; without it, external clients cannot authenticate to either service. When set, it is also used for local Factorio RCON authentication |
| `factorio_user` / `factorio_token` | empty | Optional Factorio account credentials used only for authenticated Mod Portal updates |
| `mqtt_prefix` | `homeassistant` | MQTT discovery prefix for Home Assistant entities |

On first start, if the configured `/share/factorio/saves/<save_name>` does not exist, the add-on creates it using `map-gen-settings.json` and `map-settings.json`. Edit those files before first start to customize the initial world. Edit `server-settings.json` for the server name, player limit, visibility, password, autosaves, and other Factorio server settings; edit `server-adminlist.json` for admins. When `api_token` is configured, the add-on reuses it for Factorio RCON in memory. When it is empty, a random RCON password is generated in memory for the current boot, so external clients cannot authenticate to RCON. Do not place the add-on configuration files under `/share/factorio/config`.

The browser UI uses the fixed ingress port `8099`. The authenticated REST API uses `rest_api_port` and accepts requests from Home Assistant's internal network or with the optional `X-Factorio-API-Token` header. Without an `api_token`, clients outside the Supervisor internal network are unable to access either the REST API or RCON.

The add-on uses host networking for Factorio's LAN broadcast discovery. Factorio binds `server_port/UDP`, `rcon_port/TCP`, the fixed ingress UI port `8099/TCP`, and `rest_api_port/TCP` directly on the Home Assistant host. Allow the configured game port through the host firewall for LAN clients, restrict the configured RCON port to trusted management sources, and restrict the configured REST API port to trusted Home Assistant management sources. AppArmor support is enabled using Home Assistant's default profile.

See [Home Assistant entities and sensors](SENSORS.md) for the generated entity list and [Troubleshooting](TROUBLESHOOTING.md) if startup or telemetry fails.
