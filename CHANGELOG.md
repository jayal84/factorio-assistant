# Changelog

All notable changes to **Factorio Assistant** will be documented here.

## 0.3.0 - 2026-08-15

- Expose dedicated Home Assistant services for AAI vehicle follow, drive, and mining actions.
- Add logistics and vehicle UI updates in the ingress app, including the AAI fleet summary, AAI vehicle controls, LTN controls, and tracked resource depletion display.
- Add and expose LTN support with summary and control services for clearing connections, fuel exclusions, temp stops, delivery reassignment, and train snapshots.
- Export tracked Resource Monitor sites through a separate, infrequent `resource_monitor_snapshot` stream for UI use.
- Surface estimated depletion for tracked resource sites in the ingress resources view and related snapshots.
- Cache the generated prototype catalog and rebuild it only when the active mod set changes.
- Remove the redundant generic AAI dispatch surface in favor of the explicit vehicle action services.
- Update the runtime save-path compatibility to mirror the default Factorio save locations under `/share/factorio/saves`.

## 0.2.5 - 2026-08-08

- Added native Home Assistant event-bus delivery for structured Factorio telemetry.
- Added the latest chat event entity and generic event bus compatibility alias.
- Fixed the latest chat event entity so new console chat records are emitted as Home Assistant events and the latest known chat is restored on setup.
- Fully migrated MQTT discovery and runtime publishing to the native Home Assistant integration (2026-08-09). The add-on no longer publishes MQTT discovery or runtime topics and `paho-mqtt` was removed from the add-on dependencies. Use the native Home Assistant integration and REST API for telemetry, controls, and events.
- Added a prioritized push endpoint for low-latency events: the integration registers `POST /api/factorio_assistant/push` which accepts JSON event payloads authenticated by the integration's API token. The add-on can be configured to POST `console_chat` (and other priority events) to this endpoint using the `ha_push_url` and `ha_push_token` add-on options for fast delivery to Home Assistant's event bus.

## 0.2.4 - 2026-08-08

- Separated the required Factorio Assistant mod into its independently published package.
- Updated the add-on to require the separately installed and enabled mod.

## 0.2.3 - 2026-08-07

- Added player armor details to structured Factorio telemetry.
- Added English item and entity translations for Angel's ores, including Bobmonium (`angels-ore6`).
- Updated the bundled companion mod and add-on release metadata to `0.2.3-alpha`.

## 0.2.2 - 2026-08-07 - Bug fixes from 0.2.1

- Fixed runtime translation retries so modded resource names resolve for players.
- Added catalog-backed fallback localization for Home Assistant and ingress telemetry.
- Display localized resource names without exposing internal Angel prototype IDs.
- Prepared the `factorio_assistant_0.2.2.zip` mod package.

## 0.2.1 - 2026-08-07

- Fixed localized resource names by resolving the authoritative Factorio locale domains, including modded resources such as Angel's Saphirite and Stiratite.
- Exported only pinned, active Resource Monitor sites to Home Assistant with localized ore names, reserve amount (`items`), remaining percentage, location, depletion estimate, and extraction rate (`items/s`).
- Added a Resource monitor tab to the authenticated ingress page with one live card per exported pinned site.
- Kept Resource Monitor MQTT entities grouped by surface to avoid creating a Home Assistant device for every site.
- Standardized unit metadata: physical or count-like measurements declare units, while circuit signals and categorical game entity states remain unitless.
- Preserved player inventory percentage reporting while keeping the detailed item breakdown in JSON attributes.
- Added retained MQTT discovery cleanup for removed Resource Monitor sites and improved localized tooltip and catalog handling.
- Documented integrated Resource Monitor attribution and release packaging details.

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
