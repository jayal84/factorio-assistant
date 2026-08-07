# Factorio Assistant

Factorio Assistant is an optional companion mod for Factorio 2.0. It adds structured telemetry and a small remote interface for the Factorio Assistant Home Assistant add-on.

## Features

- Emits player join, leave, death, surface-change, and enemy-attack events.
- Emits periodic world and player snapshots.
- Reports player health, position, surface, armor, inventory usage, idle state, and deaths.
- Exposes validated commands for world summaries, research, factory queries, saving, chat, pause, speed, and selected map settings.
- Adds the Factorio Assistant Signal Monitor for reading circuit-network signals and publishing telemetry.
- Includes the complete Resource Monitor UI and tracking system, with pinned active sites exported as separate Home Assistant sensors.

The mod is optional. The add-on falls back to RCON polling when the mod is disabled, unavailable, or stale.

## Compatibility

- Factorio 2.0
- Space Age supported when installed on the server
- Mod version: 0.2.2

Resource Monitor is included in this mod. Install the same
`factorio_assistant_<version>.zip` on the server and every multiplayer client;
no separate DQOL archive is required.

The Factorio Assistant Signal Monitor uses Factorio 2.0's red and green input
connector APIs directly. Its native arithmetic-combinator property window is
left to Factorio; the mod does not intercept entity GUI events. The
description entered there becomes the Home Assistant device name. Both red and
green input networks are read by default, and duplicate signal counts are
combined.

## Telemetry output

The mod writes JSON Lines events to:

```text
script-output/factorio_assistant_events.jsonl
```

World and player state snapshots default to every 20 seconds. Combinator snapshots default to every 2 seconds when combinator telemetry is enabled. Both intervals are configurable per save, and event output is throttled where necessary to avoid excessive file writes.

## Map settings

The mod exposes runtime-global settings in the map settings menu:

- Combinator telemetry is disabled by default and can be enabled after the save is stable.
- Combinator scan interval defaults to 2 seconds and can be set from 1 to 60 seconds.
- Red-wire and green-wire reading can be enabled independently.
- Combinator snapshots are limited to 100 signals by default, configurable up to 1,000.
- Event telemetry, world snapshot interval, and player inventory/armor details are configurable.

The combinator safety switch is independent of the rest of the telemetry mod. Disabling it stops combinator scans and change events while leaving world and player telemetry available.

## Remote interface

The `factorio_assistant` interface provides validated operations for the companion bridge, including:

- `world_summary`
- `research_summary`
- `factory_query`
- `save_game`
- `broadcast_chat`
- `set_game_speed`
- `set_pause`
- `set_map_setting`

The `set_map_setting` operation supports the existing Factorio map settings `pollution` and `enemy_evolution`. It does not change map-generation settings on an existing save.

## Privacy and performance

Telemetry is written locally by Factorio. The companion Home Assistant add-on may forward selected values to MQTT according to its configuration. No external network service is required by this mod.

The mod does not alter terrain or resource generation and does not add gameplay entities beyond the optional Factorio Assistant Signal Monitor.
