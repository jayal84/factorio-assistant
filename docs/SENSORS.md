# Home Assistant Entities

This add-on publishes Home Assistant MQTT discovery entities from the Python RCON bridge. Entity discovery is dynamic: fixed server and world entities are published at startup, surface entities appear for surfaces returned by Factorio, and player entities appear when players are known to the bridge.

Replace `<mqtt_prefix>` below with the configured `mqtt_prefix` value. The default is `homeassistant`.

## Entity Counts

| Group | Entities |
| :--- | ---: |
| Fixed server sensors | 11 |
| Fixed server binary sensors | 2 |
| Fixed world sensors | 16 |
| Surface entities | 1 pollution sensor per Factorio surface; plus 1 attack binary sensor when the telemetry mod is enabled |
| Player entities | 10 per discovered player |
| Server controls | 9 |

## Sender Combinators

Each Factorio Assistant Sender imports signals from both its red and green
input networks by default. Red and green signals are always separate entities,
even when the same signal is present on both networks. Each signal name uses
the configured Factorio locale followed by its network, for example
`Iron Plate (Red)` and `Iron Plate (Green)`.

Each discovered Sender device also provides eight writable Home Assistant
number entities: `Red Signal A` through `Red Signal D` and `Green Signal A`
through `Green Signal D`. Their values are retained by the Factorio Assistant
mod and kept separate by wire network.

The same device also reports eight read-only input sensors named `Red Signal A
Input` through `Red Signal D Input` and `Green Signal A Input` through `Green
Signal D Input`. These contain the live Factorio virtual signals `signal-A`
through `signal-D` received on each network.

When DQOL Resource Monitor is installed, each surface with pinned active sites
gets a device named `Factorio Resource Monitor: <Surface Name>`. Each pinned
site gets six sensors: unitless Amount, localized Ore Type, % Remaining, Location,
Estimated Depletion, and Rate (`/s`). Estimated Depletion is a Home Assistant
duration sensor in seconds; the underlying DQOL value is measured in Factorio
ticks. Unpinned and archived sites are not imported.

Circuit signal values and categorical Factorio entity states do not declare a
unit of measurement. Player inventory state uses `%` for used slots; the item
breakdown is published as JSON attributes rather than a unit-bearing sensor
value.

Resource Monitor is included in the Factorio Assistant mod. Every multiplayer
client must install the same Factorio Assistant archive as the server before
joining.

All discovered entities use the Factorio server or Factorio game device as appropriate. State and attribute topics are rewritten to the entity-scoped form described in [MQTT topics](#mqtt-topics).

## Server Sensors

These entities are attached to the `Factorio Server` device.

| Entity | Name | State | Notes |
| :--- | :--- | :--- | :--- |
| `sensor.factorio_server_ups` | UPS | `<mqtt_prefix>/sensor/factorio_server/factorio_server_ups/state` | Measured updates/s; numeric measurement |
| `sensor.factorio_server_active_players` | Active Players | `<mqtt_prefix>/sensor/factorio_server/factorio_server_players_online/state` | Numeric player count |
| `sensor.factorio_server_save_file` | Save File | `<mqtt_prefix>/sensor/factorio_server/factorio_server_save_file/state` | Diagnostic save filename |
| `sensor.factorio_server_save_size` | Save Size | `<mqtt_prefix>/sensor/factorio_server/factorio_server_save_size/state` | Bytes; diagnostic |
| `sensor.factorio_server_cpu_usage` | CPU Usage | `<mqtt_prefix>/sensor/factorio_server/factorio_server_cpu_usage/state` | Percent; diagnostic |
| `sensor.factorio_server_memory_usage` | Memory Usage | `<mqtt_prefix>/sensor/factorio_server/factorio_server_mem_usage/state` | Percent; diagnostic |
| `sensor.factorio_server_uptime` | Uptime | `<mqtt_prefix>/sensor/factorio_server/factorio_server_uptime/state` | Seconds; diagnostic |
| `sensor.factorio_server_version` | Version | `<mqtt_prefix>/sensor/factorio_server/factorio_server_version/state` | Factorio version |
| `sensor.factorio_server_installed_mods` | Installed Mods | `<mqtt_prefix>/sensor/factorio_server/factorio_server_mod_count/state` | Count of all installed mods; each mod is a boolean attribute indicating whether it is active; diagnostic |
| `sensor.factorio_server_difficulty` | Difficulty | `<mqtt_prefix>/sensor/factorio_server/factorio_server_difficulty/state` | Map difficulty/settings summary |

Server sensor attributes include `Source`. Diagnostic sensors also expose context specific to the measurement, such as save details, process details, mod information, or map settings.

## Server Binary Sensors

| Entity | Name | State | Meaning |
| :--- | :--- | :--- | :--- |
| `binary_sensor.factorio_server_watchdog` | Watchdog Status | `<mqtt_prefix>/binary_sensor/factorio_server/factorio_server_watchdog/state` | `on`/problem when a worker or supervised web/Factorio process is unhealthy; `off`/ok otherwise |
| `binary_sensor.factorio_server_rcon_status` | RCON Status | `<mqtt_prefix>/binary_sensor/factorio_server/factorio_server_rcon_status/state` | `on`/ok when RCON is ready; `off`/error otherwise |

## World Sensors

These entities are attached to the `Factorio Game` device.

| Entity | Name | State suffix |
| :--- | :--- | :--- |
| `sensor.factorio_game_tick` | Tick | `world/tick` (`ticks`) |
| `sensor.factorio_game_speed` | Speed | `world/speed` |
| `sensor.factorio_game_players_online` | Players Online | `world/players_online` (`players`) |
| `sensor.factorio_game_research` | Research | `world/research` |
| `sensor.factorio_game_research_progress` | Research Progress | `world/research_progress` |
| `sensor.factorio_game_research_level` | Current Research Level | `world/research_level` (`levels`; active research only) |
| `sensor.factorio_game_research_queue` | Research Queue | `world/research_queue` |
| `sensor.factorio_game_technologies_researched` | Technologies Researched | `world/technologies_researched` (`technologies`; completed technology count) |
| `sensor.factorio_game_technologies_total` | Technologies Total | `world/technologies_total` (`technologies`) |
| `sensor.factorio_game_rockets_launched` | Rockets Launched | `world/rockets_launched` (`rockets`; total increasing) |
| `sensor.factorio_game_evolution_factor` | Evolution Factor | `world/evolution_factor` |
| `sensor.factorio_game_evolution_progress` | Evolution Progress | `world/evolution_progress` |
| `sensor.factorio_game_day` | Day | `world/game_day` (`days`) |
| `sensor.factorio_game_time` | Time | `world/game_time` (elapsed seconds since the game was created) |
| `sensor.factorio_game_surface_count` | Surface Count | `world/surface_count` (`surfaces`) |
| `sensor.factorio_game_surfaces` | Surfaces | `world/surface_names` |

For world sensors, the state topic is `<mqtt_prefix>/sensor/factorio_world/<object_id>/state`. The suffix column identifies the telemetry path backing the entity.

`Factorio Server Game Speed` is the configured speed multiplier. `Factorio Server UPS` is measured separately from tick progress over elapsed wall-clock time.

Research sensor states use localized technology names when available, falling back to stable Factorio IDs. The research sensor attributes include the current technology ID, localization key, and `localized_name`. The research queue sensor state lists localized names, while its attributes include the ID and localization metadata for each queued technology. Names use the configured `factorio_locale`.

## Surface Sensors

For every Factorio surface reported by RCON, the bridge creates one entity:

- Entity: `sensor.factorio_surface_<safe_surface>_pollution`
- Name: `<Surface Name>: Pollution`
- State topic: `<mqtt_prefix>/sensor/factorio_world/factorio_surface_<safe_surface>_pollution/state`
- Unit: `pollution`; numeric measurement

When `enable_telemetry_mod` is enabled, it also creates:

- Entity: `binary_sensor.factorio_surface_<safe_surface>_under_attack`
- Name: `<Surface Name>: Under Attack`
- Device class: `problem`
- State: `on` for 30 seconds after throttled enemy damage to a player-force entity on that surface; `off` afterward unless another event arrives

The player health state is a percentage from 0 to 100. The `current_health` and `max_health` attributes retain raw Factorio HP values.

Surface names are normalized for entity IDs. For example, `nauvis` becomes `sensor.factorio_surface_nauvis_pollution`.

## Player Entities

For every discovered player, `<safe_player>` is a normalized version of the player name. These entities use a player-specific device.

| Entity pattern | Name pattern | Type | Notes |
| :--- | :--- | :--- | :--- |
| `binary_sensor.factorio_<safe_player>_connected` | `<Player> Connected` | Binary sensor | `true` or `false`; remains available while offline |
| `sensor.factorio_<safe_player>_health` | `<Player> Health` | Sensor | Health percentage; JSON attributes include current HP and maximum HP |
| `binary_sensor.factorio_<safe_player>_injured` | `<Player> Injured` | Binary sensor | `on` (`problem`) while the connected player's health is below maximum |
| `binary_sensor.factorio_<safe_player>_motion` | `<Player> Motion` | Binary sensor | `on` (`motion`) for a polling interval when the connected player's position changes |
| `sensor.factorio_<safe_player>_deaths` | `<Player> Deaths` | Sensor | Total increasing count; `deaths` |
| `sensor.factorio_<safe_player>_armor` | `<Player> Armor` | Sensor | Armor name/count attributes |
| `sensor.factorio_<safe_player>_inventory` | `<Player> Inventory` | Sensor | Inventory usage percentage and attributes |
| `binary_sensor.factorio_<safe_player>_active` | `<Player> Active` | Binary sensor | Generic active/idle state; `true` when active |
| `sensor.factorio_<safe_player>_location` | `<Player> Location` | Sensor | Current `(x, y)` position; JSON attributes include position and surface |
| `sensor.factorio_<safe_player>_surface` | `<Player> Surface` | Sensor | Current Factorio surface name |

Player telemetry requires bridge, RCON, and player availability. The connected entity is the exception: it remains available so it can report `false` when the player is offline.

Motion is derived from successive position polls, so a movement shorter than the polling interval can be missed. The attack entity requires the bundled event mod and does not exist when that option is disabled.

The bridge also does not currently parse Factorio log files into an event entity. Persistent logs remain available under `/share/factorio/logs` for diagnostics; they are not an MQTT telemetry source.

The optional Factorio Assistant mod archive is available at `/share/factorio/factorio_assistant_<version>.zip` for players who need to install the same mod in a local client. The version comes from the mod's `info.json`; the server copy is installed under `/share/factorio/mods` when the option is enabled.

## Telemetry Mod Expansion

The mod writes newline-delimited JSON events to `/share/factorio/script-output/factorio_assistant_events.jsonl`. Each event includes `schema_version: 1` and `source: factorio_assistant`. The bridge adds an ISO-8601 `bridge_received_at` timestamp, then publishes every valid event, without retention, on `<mqtt_prefix>/event/factorio` as JSON. Console chat is also mirrored to `<mqtt_prefix>/event/factorio_console_chat` for conversation automations. The local event file rolls to `factorio_assistant_events.jsonl.1` at approximately 5 MiB.

Current event names are:

- `surface_attack`: surface, damaged player-force entity, damage, and tick; throttled per surface.
- `player_joined`, `player_left`, `player_died`: player identity and best-effort force, surface, position, controller, health, armor-independent character state, and tick. Deaths also include a best-effort cause.
- `player_changed_surface`: player, new surface index, current player data, and tick.
- `player_respawned`: player data and tick.
- `console_chat`: player, message, surface, and tick.
- `research_finished`: technology, force, and tick.
- `rocket_launched`: silo details, optional launching player, and tick.
- `entity_died`: throttled player-force or enemy unit/spawner death with entity and cause details.

The `state_snapshot` event is consumed by the bridge to refresh live state and
is also published on the generic event topic. It refreshes every 1,200 game
ticks (approximately 20 seconds at 60 UPS) and carries the current player,
research, surface, pollution, and world-count state.

Events are intentionally structured and throttled rather than exposed as one MQTT entity per game action. The bridge keeps the existing attack binary sensor in addition to the generic event stream.

The ingress Logs view reads the same bounded history through
`GET /api/telemetry/events?limit=50`. The endpoint accepts at most 200 events,
skips malformed records, and reads only the current JSONL file plus its single
rollover archive. Home Assistant can call the equivalent
`rest_command.factorio_telemetry_events` command when an automation needs a
recent event snapshot.

When the optional telemetry mod is enabled, its periodic state snapshot is the primary source for current player, research, surface, pollution, and world-count telemetry. The bridge uses the existing RCON stats command only when the MOD snapshot is missing or older than 45 seconds. RCON remains the fallback for current snapshots and is still used for on-demand commands such as research detail, factory inspection, and controls. The mod should focus on event timing and causality, where polling can miss short-lived activity.

## Availability

The bridge publishes these retained availability topics:

- Bridge: `<mqtt_prefix>/sensor/factorio_server/availability`
- RCON: `<mqtt_prefix>/sensor/factorio_server/rcon_availability`
- Player: `<mqtt_prefix>/sensor/factorio_<safe_player>/availability`

Most entities require bridge and RCON availability. Player entities additionally use the player availability topic.

## Controls

The bridge also creates these non-sensor entities:

| Entity | Type | Purpose |
| :--- | :--- | :--- |
| `switch.factorio_server_enemy_evolution` | Switch | Enable or disable enemy evolution |
| `switch.factorio_server_pollution` | Switch | Enable or disable pollution |
| `switch.factorio_server_pause` | Switch | Pause or resume the game |
| `switch.factorio_server_daylight` | Switch | Freeze all surfaces at midday or night |
| `button.factorio_server_save` | Button | Save the game |
| `button.factorio_server_day_night_cycle_resume` | Button | Resume the cycle when it is stopped |
| `number.factorio_server_game_speed` | Number | Set game speed from `0.1` to `10.0` |
| `number.factorio_server_time_of_day` | Number | Set synchronized daytime from `0.0` to `1.0` |
| `text.factorio_server_broadcast_chat` | Text | Broadcast a message to players |

## MQTT Topics

Discovery configs use:

`<mqtt_prefix>/<component>/<device>/<object_id>/config`

After discovery, state and attribute topics use:

- State: `<mqtt_prefix>/<component>/<device>/<object_id>/state`
- Attributes: `<mqtt_prefix>/<component>/<device>/<object_id>/attributes`
- Commands: `<mqtt_prefix>/<component>/<device>/<object_id>/set`

The MQTT state and command topics form a shared two-way synchronization surface between Factorio telemetry, the bridge, and Home Assistant.
