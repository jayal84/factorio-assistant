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

## 0.1.8 - 2026-08-06

- Added per-save runtime-global settings for combinator telemetry, scan cadence, wire selection, signal limits, event telemetry, world snapshots, and inventory details.
- Added a blue Factorio Assistant Sender based on Factorio 2.0.77 arithmetic-combinator behavior, preserving native input, arithmetic, and output wiring.
- Added circuit-network telemetry for red and green Sender input connectors, including signal type, quality, count, position, surface, and placement metadata.
- Added native-description-based Home Assistant device naming as `Factorio Assistant Sender: <description>` with a unit-number fallback.
- Added retained MQTT discovery, state, attributes, and availability handling for Sender entities, including cleanup when a Sender is mined, destroyed, or killed.
- Removed the misleading `signals` unit of measurement from Sender sensors.
- Added bounded JSONL telemetry rotation at approximately 5 MiB with one archive.
- Added Factorio 2.0.77 compatibility fixes for circuit connector APIs, property-page stability, entity metadata, and mod packaging.
- Preserved isolated Home Assistant ingress and external REST listeners on separate ports.
- Added localized Sender labels, descriptions, technology, recipe, and item metadata.
- Added release packaging and pinned Factorio reference data for reproducible add-on builds.
