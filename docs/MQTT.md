# MQTT And Home Assistant

The Python bridge publishes Home Assistant MQTT discovery and runtime state without requiring an additional Factorio mod.

## Topic Model

Discovery configs use:

`<mqtt_prefix>/<component>/<device>/<object_id>/config`

After discovery, entity runtime topics use:

- State: `<mqtt_prefix>/<component>/<device>/<object_id>/state`
- Attributes: `<mqtt_prefix>/<component>/<device>/<object_id>/attributes`
- Commands: `<mqtt_prefix>/<component>/<device>/<object_id>/set`

MQTT state topics are the shared synchronization surface for the bridge and Home Assistant. Factorio telemetry publishes updates to them, while discovered Home Assistant commands write changes back through the same state flow. The bridge accepts only discovered entity command topics.

Availability topics are:

- Bridge: `<mqtt_prefix>/sensor/factorio_server/availability`
- RCON: `<mqtt_prefix>/sensor/factorio_server/rcon_availability`
- Player: `<mqtt_prefix>/sensor/factorio_<safe_player>/availability`

Player Connected entities remain available when the player is offline and report `false`. Other player telemetry requires bridge, RCON, and player availability.

Every entity exposes a `Source` attribute through its JSON attributes topic. Live snapshot entities report `MOD` when the optional telemetry mod snapshot is fresh and `RCON` when the bridge falls back. Diagnostics and controls may report `RCON diagnostics` or `RCON`.

Placed Factorio Assistant Senders create one Home Assistant device per
reader and one numeric sensor per circuit signal. Discovery configuration,
signal state, signal attributes, and availability are retained. The device is
named `Factorio Assistant Sender: <Name>` when its in-game description is set,
otherwise the Factorio unit number is used. Signal sensors report numeric
counts without a unit of measurement. Both red and green input networks are
read by default and are always exposed as separate sensors. Names use the
configured Factorio locale followed by the network, such as `Iron Plate (Red)`
and `Iron Plate (Green)`. Their attributes include `Placed by`, surface,
position, signal type, quality, raw Factorio signal name, and `Network`.

Each Sender also creates eight writable number entities: `Red Signal A` through
`Red Signal D` and `Green Signal A` through `Green Signal D`. Their values are
retained by the mod and kept separate by wire network.

It also creates eight read-only input sensors for those same signal slots. For
example, `Red Signal A Input` reports the live `signal-A` value received on the
red network, while `Green Signal A Input` reports the green network value.

When DQOL Resource Monitor is installed, only pinned active sites are imported.
Each surface gets a `Factorio Resource Monitor: <Surface Name>` device. Each
pinned site gets separate unitless sensors for amount, localized ore type,
percentage remaining, location, estimated depletion, and extraction rate
(`/s`) under
`<mqtt_prefix>/resource_monitor/<surface>/<site_id>/<metric>`.

The estimated depletion value is published in seconds with Home Assistant's
duration device class. Resource Monitor is included in the Factorio Assistant
mod, so multiplayer clients only need the same Factorio Assistant archive.

Circuit signal values and Factorio entity states intentionally have no unit of
measurement because they are game counts or categorical values, not physical
quantities. Player inventory state uses `%` for used slots; the item breakdown
remains in its JSON attributes.

When a reader is mined, destroyed, or killed, the mod emits a removal event.
The bridge clears each retained discovery topic with an empty retained payload,
then clears the retained signal state and attributes. Home Assistant removes
the device after its last discovered entity is deleted.

## Telemetry events

When the optional telemetry mod is enabled, the bridge publishes non-retained
JSON events to:

```text
<mqtt_prefix>/event/factorio
```

Console chat is also mirrored to:

```text
<mqtt_prefix>/event/factorio_console_chat
```

These are event topics, not retained sensors. Subscribe with an MQTT trigger
and inspect `trigger.payload_json.event` to select an event type. The event
file is bounded by rollover at approximately 5 MiB, with one `.1` archive.
For a bounded pull-based snapshot instead, use the authenticated
`GET /api/telemetry/events?limit=50` endpoint or the Home Assistant
`factorio_telemetry_events` REST command.

See [Home Assistant entities and sensors](SENSORS.md) for the full entity and topic reference.

## Controls

The Factorio Server device exposes these switches:

- `switch.factorio_server_enemy_evolution`
- `switch.factorio_server_pollution`
- `switch.factorio_server_pause`
- `switch.factorio_server_daylight`

It also exposes these controls:

- `button.factorio_server_save`
- `number.factorio_server_game_speed` from `0.1` to `10.0`
- `text.factorio_server_broadcast_chat`
- `button.factorio_server_day_night_cycle_resume`, available only while the day/night cycle is stopped
- `number.factorio_server_time_of_day` from `0.0` to `1.0`

The default command topics are:

- `homeassistant/switch/factorio_server/factorio_server_enemy_evolution/set`
- `homeassistant/switch/factorio_server/factorio_server_pollution/set`
- `homeassistant/switch/factorio_server/factorio_server_pause/set`
- `homeassistant/switch/factorio_server/factorio_server_daylight/set`
- `homeassistant/button/factorio_server/factorio_server_save/set`
- `homeassistant/number/factorio_server/factorio_server_game_speed/set`
- `homeassistant/text/factorio_server/factorio_server_broadcast_chat/set`
- `homeassistant/button/factorio_server/factorio_server_day_night_cycle_resume/set`
- `homeassistant/number/factorio_server/factorio_server_time_of_day/set`

Replace `homeassistant` with the configured `mqtt_prefix` when it differs from the default.

Use `ON` and `OFF` payloads for switches. The Resume Day/Night Cycle button is available only when telemetry reports the cycle stopped and resumes it with `PRESS`. Daylight `ON` freezes all surfaces at midday; `OFF` freezes them at night. Time of Day sets Factorio's synchronized `daytime` value from `0.0` to `1.0`. Pause uses `/silent-command game.tick_paused = true` and `/silent-command game.tick_paused = false`. The save button uses `/server-save` when the structured mod control is unavailable. Game speed accepts values from `0.1` to `10.0`. Broadcast chat sends the text to all players with `game.print`.

## Game Data Search

The ingress Factory Wiki is a search-first reference for finding items, fluids, recipes, technologies, and buildings. Results emphasize production and usage relationships, recipe inputs and outputs, technology prerequisites and unlocks, and practical entity details; the full prototype record is available under Technical data. The authenticated REST API exposes the same boot-generated game-data catalog without requiring the dashboard or live RCON. Search it with `/api/catalog?query=rocket&kind=item&limit=10&offset=0`. Results retain the full Factorio prototype data, including names, localized names, icons, reverse recipe indexes, and technology relationships. Mod settings from `mod-settings-dump.json` are indexed as `kind=setting`, including their setting type, scope, default, limits, order, and localization data; for example, `/api/catalog?query=vehicle&kind=setting`.
