# Factorio Assistant

![Factorio 2.0.77](https://img.shields.io/badge/Factorio-2.0.77-blue.svg)
![Requires Linux amd64 Architecture](https://img.shields.io/badge/Linux%20amd64-required-orange.svg)
![Requires Mosquitto MQTT Broker](https://img.shields.io/badge/MQTT%20broker-required-orange.svg)

Factorio Assistant runs a headless Factorio 2.0.77 Space Age server as a Home Assistant add-on and connects it to your smart home.

## What It Offers

- MQTT Discovery for server, world, player, factory, and health sensors
- MQTT controls for saving, pausing, changing game speed, toggling settings, and broadcasting chat
- An authenticated ingress dashboard for server status, players, world data, factory searches, and controls
- RCON and authenticated REST APIs for automation and advanced integrations
- Player, research, pollution, evolution, production, rocket, and surface telemetry
- An optional companion mod for structured events, richer snapshots, circuit-network reading, and validated commands
- RCON polling fallback when the telemetry mod is disabled, unavailable, or stale
- Watchdog health reporting, persistent logs, save management, and optional Mod Portal updates

The add-on stores saves, mods, logs, and generated telemetry under `/share/factorio`. It creates a new save from the configured map settings when the selected save does not yet exist.

## Status And Planned Features

The Home Assistant ingress page is still a work in progress and may continue to change as dashboard features are expanded.

Planned features also include adding external Factorio tools to the add-on, such as Mapshot and Factoriopedia.

## Requirements

- Home Assistant OS, Supervised, or Container on Linux amd64
- A Mosquitto MQTT broker available to Home Assistant
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
