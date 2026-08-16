# Factorio Assistant

![Factorio 2.0.77](https://img.shields.io/badge/Factorio-2.0.77-blue.svg)
![Requires Linux amd64 Architecture](https://img.shields.io/badge/Linux%20amd64-required-orange.svg)


Factorio Assistant runs a headless Factorio 2.0.77 Space Age server as a Home Assistant add-on and connects it to your smart home.

Migration note: MQTT discovery and bridge publishing has been fully migrated to the native Home Assistant integration as of 2026-08-09. The add-on no longer publishes MQTT discovery or runtime topics; use the `integration/custom_components/factorio_assistant` integration and the add-on REST API for telemetry, controls, and events.

Fast event delivery: the integration exposes a push endpoint at `/api/factorio_assistant/push` which the add-on can POST priority events to. Configure the add-on options `ha_push_url` (default: `http://supervisor/core/api/factorio_assistant/push`) and `ha_push_token` (the integration's `api_token`) to enable fast, authenticated delivery of `console_chat` and other prioritized events into Home Assistant's event bus.

## What It Offers

- Native Home Assistant integration for server, world, player, factory, and health sensors
- Native HA services and events for saving, pausing, changing game speed, toggling settings, and broadcasting chat
- An authenticated ingress dashboard for server status, players, world data, factory searches, and controls
- RCON and authenticated REST APIs for automation and advanced integrations
- Player, research, pollution, evolution, production, rocket, and surface telemetry
- A required, separately published companion mod for structured events, richer snapshots, circuit-network reading, and validated commands
- Mod-backed telemetry with RCON retained for transport, readiness, and administration
- Watchdog health reporting, persistent logs, save management, and optional Mod Portal updates

The add-on stores saves, mods, logs, and generated telemetry under `/share/factorio`. It creates a new save from the configured map settings when the selected save does not yet exist.

## Status And Planned Features

The Home Assistant ingress page is still a work in progress and may continue to change as dashboard features are expanded.

Planned features also include adding external Factorio tools to the add-on, such as Mapshot and Factoriopedia.

## Requirements

- Home Assistant OS, Supervised, or Container on Linux amd64
- A Home Assistant instance for the native integration
- Network access for the Factorio game, RCON, ingress, and REST API ports

## Install

Add this repository to the Home Assistant app repository list:

```text
https://github.com/jayal84/factorio-assistant
```

Install **Factorio Assistant**, configure MQTT and the server options, then open it from the app panel. Factorio account credentials are only needed when authenticated Mod Portal downloads are enabled.

## Documentation

- [Documentation index](docs/README.md)
- [Installation and configuration](docs/INSTALLATION.md)
- [MQTT, Home Assistant, and controls](docs/MQTT.md)
- [REST commands and Home Assistant scripts](docs/EXAMPLES.md)
- [Complete sensors and entities reference](docs/SENSORS.md)
- [Operations and telemetry](docs/OPERATIONS.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## License And Disclaimer

The add-on source code in this repository is licensed under the [MIT License](LICENSE).

This add-on runs the official Factorio server software and depends on the upstream Factorio distribution and applicable third-party terms. It does not bundle Factorio binaries by itself.
Factorio, Space Age, installed mods, generated game data, and their assets remain subject to their respective licenses and terms.
