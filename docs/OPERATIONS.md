# Operations And Telemetry

This page covers routine operation from a user and administrator perspective.

## Runtime Storage

The add-on stores persistent runtime data under `/share/factorio`, making it visible through the Home Assistant SMB share.

The main storage areas are:

```text
/share/factorio/
├── logs/
├── mods/
├── saves/
└── script-output/
```

The add-on configuration directory is `/config` inside the container, backed by `/addon_configs/local_factorio_assistant` on the Home Assistant host. Example templates are installed into the image at `/app/factorio-templates` during the add-on build. On first start, missing editable `server-settings.json`, `map-gen-settings.json`, `map-settings.json`, `server-adminlist.json`, and `server-whitelist.json` files are copied from those templates into `/config`; existing files are never overwritten. Player profiles and runtime state are also stored there. The `logs` directory contains Factorio logs, `mods` contains installed mods, `saves` contains world saves, and `script-output` contains Factorio-generated output. The generated catalog is ephemeral at `/tmp/factorio-assistant/catalog.json`.

Back up the `saves` directory and keep sufficient free space for save files, mods, and logs. The add-on creates the configured save automatically when it does not exist. The add-on's configuration backup should include `/addon_configs/local_factorio_assistant` so server settings, map generation, player profiles, and runtime state survive restoration.

## Save Backups And Restore

Factorio writes rotating autosaves according to the values in `/config/server-settings.json`.

The add-on uses blocking saves (`non_blocking_saving: false`) for reliable writes on the Home Assistant container filesystem. With the default settings, Factorio writes `autosave1.zip` through `autosave8.zip` in `/share/factorio/saves` while the server is running.

The Save files ingress page controls the assistant's additional scheduled backups. Backup settings are kept in runtime storage and are deliberately not add-on options in `config.yaml`.

The page supports three schedule modes:

- **Hourly** creates one backup each hour.
- **Daily at** creates one backup at the selected local time.
- **Every X hours** creates a backup at the configured interval from the last successful backup.

Backups are enabled by default. The default interval is 12 hours, the default daily time is `00:00`, and the default maximum is 14 backup archives. Set **Max total MB** to `0` to disable the combined-size limit. When either retention limit is reached, the oldest backup archives are removed first. The count limit is always active and must be at least 1.

The page lists normal saves, Factorio autosaves, and assistant backup archives. A non-configured save can be deleted from the list. Restoring a selected save is asynchronous: the assistant asks the supervisor to stop Factorio, replaces the configured save atomically, and the supervisor starts Factorio again. Follow the restore status indicator in the ingress page until it reports completion. Do not manually edit or remove the configured save while a restore is in progress.

## Game Data Catalog

Factorio Assistant reports Factorio and bridge status, save and mod archive counts, and recent logs through the Home Assistant ingress panel. The separate REST API also exposes the cached prototype catalog for authenticated Home Assistant requests.

The prototype catalog is generated from Factorio's `--dump-data` output after mod synchronization. The cache is stored ephemerally at `/tmp/factorio-assistant/catalog.json`. It retains the full prototype objects, adds localized names and static recipe reverse indexes, and includes Factorio's generated `mod-settings-dump.json` as searchable `setting` records. A separate `--dump-prototype-locale` export is generated at startup so translated names and descriptions are resolved for the ingress catalog.

The catalog contains definition data only. Current production rates, inventories, power, pollution, researched state, and other factory telemetry come from the separate RCON bridge.

For example, configure a Home Assistant REST command:

```yaml
rest_command:
  factorio_catalog_search:
    url: "http://homeassistant.eremophobia.net:8098/api/catalog?query={{ query | urlencode }}&kind={{ search_type | urlencode }}&limit=25&offset=0"
    method: GET
```

The endpoint returns one JSON document with `total`, `offset`, `limit`, and `results`. Add `X-Factorio-API-Token` when the request does not originate from the Home Assistant internal network.

## Factorio Control Agent

Home Assistant includes a `Factorio Control Agent` script that routes a request
through the configured `conversation.openai_conversation` agent. The wrapper
does not store credentials or create a second OpenAI integration; it supplies
Factorio-specific operating rules and preserves the existing OpenAI setup.

Before using it, configure the OpenAI Conversation integration for home control
(Assist mode), then expose these scripts to Assist from **Settings > Voice
assistants > Expose** or from each script's settings:

```text
search_factorio_catalog
review_factorio_factory_area
inspect_factorio_map_area
inspect_factorio_production
plan_factorio_factory
build_factorio_factory
helper_factorio_give_items
demolish_factorio_area
factorio_demolition_agent
```

The agent should inspect before planning and plan before building. Builder
requests create ghosts by default; real entities require `real: true` in the
same explicit user request. Giving items changes the live save and requires an
explicit player name plus exact item counts. Use `dry_run: true` when validating
a build request without placing anything.

Demolition requests use `demolish_factorio_area`. It marks matching entities for
deconstruction by default, excludes resources, and is bounded to a 512x512 tile
area. Set `real: true` only after explicit confirmation to remove entities
immediately. Optional exact entity names can narrow the operation.

For mod-dependent requests, the agent must first inspect the attributes of
`sensor.factorio_server_installed_mods`. Those attributes identify which mods
are active in the current server. It should then use `search_factorio_catalog`
to resolve the exact item, recipe, or entity ID. The agent must not claim that
a mod-provided object is available from catalog data alone; the mod must also
be active in the installed-mod attributes.

The wrapper can be called from an automation or script with the standard
`conversation.process` action, using the conversation agent exposed by the
OpenAI integration:

```yaml
action: conversation.process
data:
  agent_id: conversation.openai_conversation
  text: "Inspect the Factorio copper smelting area on nauvis"
```

For a direct UI call, run the `Factorio Control Agent` script and fill in its
`request` field. Verify tool calls in the Assist debug dialog; exposed scripts
appear as callable tools rather than static entities.

### Factorio chat assistant

When `enable_telemetry_mod` is enabled, player console chat is published as a
non-retained JSON MQTT event on:

```text
<mqtt_prefix>/event/factorio_console_chat
```

The default prefix is `homeassistant`. The payload contains `player`,
`message`, `surface`, `player_index`, and `tick`. An automation can listen for
messages addressed to Cassandra, send the message through the Home Assistant
conversation agent, and print the response back into Factorio:

The mod also exposes the stable `factorio_assistant` command interface. The
bridge uses it for validated chat, game-speed, pause, map-setting, and save
commands, plus structured world, research, factory, and item-helper requests
when the mod toggle is enabled. RCON remains the fallback transport for these
operations when the mod is unavailable. Generic RCON access and filesystem save
restore are intentionally not routed through the mod.
falling back to the existing RCON Lua commands when the interface is
unavailable. The installed package ID is `factorio_assistant`.

```yaml
automation:
  - alias: Factorio chat addressed to Cassandra
    mode: queued
    trigger:
      - platform: mqtt
        topic: homeassistant/event/factorio_console_chat
    condition:
      - condition: template
        value_template: >-
          {{ 'cassandra' in (trigger.payload_json.message | default('') | lower) }}
    action:
      - variables:
          conversation_id: >-
            {% set last_chat = states('input_datetime.cassandra_last_chat') %}
            {% set previous_id = states('input_text.cassandra_conversation_id') %}
            {% if last_chat not in ['unknown', 'unavailable', '']
                  and previous_id not in ['unknown', 'unavailable', '']
                  and (as_timestamp(now()) - as_timestamp(last_chat, 0)) < 300 %}
              {{ previous_id }}
            {% else %}
              {{ '' }}
            {% endif %}
      - action: conversation.process
        data:
          agent_id: conversation.openai_conversation
          text: >-
            A Factorio player named {{ trigger.payload_json.player }} says:
            {{ trigger.payload_json.message }}
          conversation_id: "{{ conversation_id }}"
        response_variable: cassandra_response
      - action: input_text.set_value
        target:
          entity_id: input_text.cassandra_conversation_id
        data:
          value: "{{ cassandra_response.conversation_id | default('') }}"
      - action: input_datetime.set_datetime
        target:
          entity_id: input_datetime.cassandra_last_chat
        data:
          timestamp: "{{ now().timestamp() }}"
      - action: rest_command.factorio_console_reply
        data:
          speech: >-
            {{ cassandra_response.response.speech.plain.speech
               | default('I could not answer that.') }}

rest_command:
  factorio_console_reply:
    url: "http://homeassistant.eremophobia.net:8098/api/rcon"
    method: POST
    headers:
      X-Factorio-API-Token: !secret factorio_api_token
    content_type: application/json
    timeout: 15
    payload: >-
      {% set text = speech | string %}
      {% set command = '/say ' ~ text %}
      {{ {'command': command} | tojson }}

    # Store the same value in Home Assistant secrets.yaml and in the add-on's
    # api_token option before using this automation.

input_text:
  cassandra_conversation_id:
    name: Cassandra conversation ID
    max: 255

input_datetime:
  cassandra_last_chat:
    name: Cassandra last chat
    has_date: true
    has_time: true
```

The first chat, or a chat after five minutes of inactivity, starts a new
conversation. Subsequent chats reuse the stored ID. Keep the automation in
`mode: queued` if several players may address Cassandra at once and add that
key at the automation root if ordering matters for your server.

The REST endpoint must be reachable from Home Assistant's internal network or
be configured with the add-on API token. The event is deliberately not
retained, so old chat messages cannot be replayed after a restart. Restrict
the automation condition to a name such as `Cassandra` before enabling any
state-changing tools for the conversation agent.

## Telemetry

The bridge uses the optional telemetry mod as the primary source for current player and world snapshots when it is enabled. The existing RCON stats command remains the fallback when the mod is disabled, unavailable, or stale, and RCON continues to serve on-demand queries and controls.

The bridge still waits until Factorio's RCON service is ready before publishing live telemetry because RCON remains the control and fallback channel. With the telemetry mod enabled, server, world, surface, and player entities use its fresh snapshot without issuing the duplicate full stats command. The `refresh_rate_profile` option controls bridge publishing cadence; choose `slow` for lower-frequency updates and `fast` or `high` when more responsive updates are important.

## Mod Updates

Optional Mod Portal update checks run during startup when `enable_mod_updates` is enabled. Authenticated downloads require the configured Factorio account credentials. A failed update does not replace the installed archive.

