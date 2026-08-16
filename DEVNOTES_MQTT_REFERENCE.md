# MQTT Reference (Developer-only, Deprecated)

This file is a historical reference of the add-on's MQTT discovery and runtime topic model.
The MQTT bridge was removed from the add-on on 2026-08-09 and this content is retained for development and migration purposes only.

---

# MQTT And Home Assistant

The Python bridge used to publish Home Assistant MQTT discovery and runtime state without requiring an additional Factorio mod.

## Topic Model

Discovery configs use:

`<mqtt_prefix>/<component>/<device>/<object_id>/config`

After discovery, entity runtime topics use:

- State: `<mqtt_prefix>/<component>/<device>/<object_id>/state`
- Attributes: `<mqtt_prefix>/<component>/<device>/<object_id>/attributes`
- Commands: `<mqtt_prefix>/<component>/<device>/<object_id>/set`

MQTT state topics are the shared synchronization surface for the bridge and Home Assistant. Factorio telemetry publishes updates to them, while discovered Home Assistant commands write changes back through the same state flow. The bridge accepted only discovered entity command topics.

Availability topics were:

- Bridge: `<mqtt_prefix>/sensor/factorio_server/availability`
- RCON: `<mqtt_prefix>/sensor/factorio_server/rcon_availability`
- Player: `<mqtt_prefix>/sensor/factorio_<safe_player>/availability`

Player Connected entities remained available when the player was offline and reported `false`. Other player telemetry required bridge, RCON, and player availability.

Every entity exposed a `Source` attribute through its JSON attributes topic. Live snapshot entities reported `MOD`. Diagnostics reported `RCON diagnostics`, while controls used the required mod interface over RCON.

Placed Factorio Assistant Senders created one Home Assistant device per
reader and one numeric sensor per circuit signal. Discovery configuration,
signal state, signal attributes, and availability were retained. The device was
named `Factorio Assistant Sender: <Name>` when its in-game description was set,
otherwise the Factorio unit number was used. Signal sensors reported numeric
counts without a unit of measurement. Both red and green input networks were
read by default and were always exposed as separate sensors. Names used the
configured Factorio locale followed by the network, such as `Iron Plate (Red)`
and `Iron Plate (Green)`. Their attributes included `Placed by`, surface,
position, signal type, quality, raw Factorio signal name, and `Network`.

Each Sender also created eight writable number entities: `Red Signal A` through
`Red Signal D` and `Green Signal A` through `Green Signal D`. Their values were
retained by the mod and kept separate by wire network.

It also created eight read-only input sensors for those same signal slots. For
example, `Red Signal A Input` reported the live `signal-A` value received on the
red network, while `Green Signal A Input` reported the green network value.

When DQOL Resource Monitor was installed, only pinned active sites were imported.
Each surface got a `Factorio Resource Monitor: <Surface Name>` device. Each
pinned site got separate unitless sensors for amount, localized ore type,
percentage remaining, location, estimated depletion, and extraction rate
(`/s`) under
`<mqtt_prefix>/resource_monitor/<surface>/<site_id>/<metric>`.

The estimated depletion value was published in seconds with Home Assistant's
duration device class. Resource Monitor was included in the Factorio Assistant
mod, so multiplayer clients only needed the same Factorio Assistant archive.

Circuit signal values and Factorio entity states intentionally had no unit of
measurement because they were game counts or categorical values, not physical
quantities. Player inventory state used `%` for used slots; the item breakdown
remained in its JSON attributes.

When a reader was mined, destroyed, or killed, the mod emitted a removal event.
The bridge cleared each retained discovery topic with an empty retained payload,
then cleared the retained signal state and attributes. Home Assistant removed
the device after its last discovered entity was deleted.

## Telemetry events

The required telemetry mod caused the bridge to publish non-retained
JSON events to:

```
<mqtt_prefix>/event/factorio
```

Console chat was also mirrored to:

```
<mqtt_prefix>/event/factorio_console_chat
```

These were event topics, not retained sensors. Subscribe with an MQTT trigger
and inspect `trigger.payload_json.event` to select an event type. The event
file was bounded by rollover at approximately 5 MiB, with one `.1` archive.
For a bounded pull-based snapshot instead, use the authenticated
`GET /api/telemetry/events?limit=50` endpoint or the Home Assistant
`factorio_telemetry_events` REST command.

See the historic `docs/SENSORS.md` for the full entity and topic reference.

## Controls

The Factorio Server device exposed these switches in the MQTT model:

- `switch.factorio_server_enemy_evolution`
- `switch.factorio_server_pollution`
- `switch.factorio_server_pause`
- `switch.factorio_server_daylight`

It also exposed these controls:

- `button.factorio_server_save`
- `number.factorio_server_game_speed` from `0.1` to `10.0`
- `text.factorio_server_broadcast_chat`
- `button.factorio_server_day_night_cycle_resume`, available only while the day/night cycle was stopped
- `number.factorio_server_time_of_day` from `0.0` to `1.0`

The default command topics were:

- `homeassistant/switch/factorio_server/factorio_server_enemy_evolution/set`
- `homeassistant/switch/factorio_server/factorio_server_pollution/set`
- `homeassistant/switch/factorio_server/factorio_server_pause/set`
- `homeassistant/switch/factorio_server/factorio_server_daylight/set`
- `homeassistant/button/factorio_server/factorio_server_save/set`
- `homeassistant/number/factorio_server/factorio_server_game_speed/set`
- `homeassistant/text/factorio_server/factorio_server_broadcast_chat/set`
- `homeassistant/button/factorio_server/factorio_server_day_night_cycle_resume/set`
- `homeassistant/number/factorio_server/factorio_server_time_of_day/set`

Replace `homeassistant` with the configured `mqtt_prefix` when it differed from the default.

Use `ON` and `OFF` payloads for switches. The Resume Day/Night Cycle button was available only when telemetry reported the cycle stopped and resumed it with `PRESS`. Daylight `ON` froze all surfaces at midday; `OFF` froze them at night. Time of Day set Factorio's synchronized `daytime` value from `0.0` to `1.0`. Pause used `/silent-command game.tick_paused = true` and `/silent-command game.tick_paused = false`. The save button used `/server-save` when the structured mod control was unavailable. Game speed accepted values from `0.1` to `10.0`. Broadcast chat sent the text to all players with `game.print`.

## Game Data Search

The ingress Factory Wiki was a search-first reference for finding items, fluids, recipes, technologies, and buildings. Results emphasized production and usage relationships, recipe inputs and outputs, technology prerequisites and unlocks, and practical entity details; the full prototype record was available under Technical data. The authenticated REST API exposed the same boot-generated game-data catalog without requiring the dashboard or live RCON. Search it with `/api/catalog?query=rocket&kind=item&limit=10&offset=0`. Results retained the full Factorio prototype data, including names, localized names, icons, reverse recipe indexes, and technology relationships. Mod settings from `mod-settings-dump.json` were indexed as `kind=setting`, including their setting type, scope, default, limits, order, and localization data; for example, `/api/catalog?query=vehicle&kind=setting`.
