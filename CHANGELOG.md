# Changelog

All notable changes to **Factorio Assistant** will be documented here.

## Current Features

- Runs a headless Factorio 2.0.77 Space Age server as a Home Assistant add-on on Linux amd64.
- Publishes MQTT discovery and telemetry for the server, world, surfaces, players, research, production, rockets, pollution, evolution, factory state, and health.
- Provides MQTT controls for saving, pausing, changing game speed, changing server settings, and broadcasting chat.
- Provides an authenticated Ingress dashboard for server status, world data, players, factory searches, controls, technologies, and system information. The Ingress experience remains a work in progress.
- Provides authenticated REST and RCON interfaces for automation and advanced integrations.
- Supports an optional published `factorio_assistant` telemetry mod for structured events, richer snapshots, circuit-network reading, and validated commands.
- Falls back to RCON polling when the telemetry mod is disabled, unavailable, or stale.
- Manages saves, logs, runtime data, player profiles, and generated Factorio catalog data under the configured Home Assistant storage locations.
- Includes watchdog health reporting, persistent logging, configurable autosaves, and optional authenticated Mod Portal updates.
- Includes a searchable localized Factorio catalog with prototype details, icons, recipes, technologies, references, and raw diagnostic data.

Planned external tool integrations include Mapshot and Factoriopedia.

## Unreleased

- Added per-save runtime settings for combinator telemetry, scan cadence, wire selection, signal limits, event telemetry, world snapshots, and inventory details.
- Combinator telemetry is disabled by default as a safety control while custom combinator compatibility is being validated.
