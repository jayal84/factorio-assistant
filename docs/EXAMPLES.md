# REST Commands And Scripts

This page contains copyable Home Assistant examples for the Factorio Assistant REST API. The examples use the REST listener on port `8100`; the browser UI and Home Assistant ingress use port `8099` and are not REST command targets.

Replace `local-factorio-assistant` with the hostname or add-on hostname used by your Home Assistant installation. Because the add-on uses host networking, configure the optional add-on `api_token` and send it in the `X-Factorio-API-Token` header for reliable REST access from Home Assistant automations.

Do not put the RCON password in Home Assistant configuration. The add-on reads its current RCON password internally.

## Common Setup

For requests from the Home Assistant internal network:

```yaml
rest_command:
  factorio_status:
    url: "http://local-factorio-assistant:8100/api/status"
    method: GET
    timeout: 15

  factorio_world:
    url: "http://local-factorio-assistant:8100/api/world"
    method: GET
    timeout: 15

  factorio_research:
    url: "http://local-factorio-assistant:8100/api/research"
    method: GET
    timeout: 15
```

When the request source is outside the configured internal network, add the shared add-on API token. Store it in `secrets.yaml` rather than writing it directly in configuration:

```yaml
rest_command:
  factorio_status:
    url: "http://local-factorio-assistant:8100/api/status"
    method: GET
    headers:
      X-Factorio-API-Token: !secret factorio_api_token
    timeout: 15
```

The add-on option `api_token` must contain the same secret. This is not a Home Assistant long-lived access token.

## Read-Only Commands

### Server status

`factorio_status` returns process state, connection details, save and mod counts, player profiles, recent log lines, and storage metadata.

```yaml
script:
  factorio_refresh_status:
    alias: Factorio - Refresh status
    sequence:
      - action: rest_command.factorio_status
```

A REST command response is not automatically exposed as a sensor. Use the response in an automation integration or call the endpoint from an external script if you need to persist selected fields in Home Assistant.

### World and research

These endpoints query live Factorio state through RCON when called:

```yaml
rest_command:
  factorio_world:
    url: "http://local-factorio-assistant:8100/api/world"
    method: GET
    timeout: 15

  factorio_research:
    url: "http://local-factorio-assistant:8100/api/research"
    method: GET
    timeout: 15
```

`/api/world` returns live tick, speed, daytime, evolution, surfaces, connected players, save files, and installed mods. `/api/research` returns researched technology IDs, current research, progress, and the research queue.

### Bounded factory queries

Prefer these read-only endpoints for factory inspection instead of constructing broad `/api/rcon` scans:

```yaml
rest_command:
  factorio_inspect_area:
    url: "http://local-factorio-assistant:8100/api/factory/inspect"
    method: POST
    content_type: application/json
    timeout: 30
    payload: >-
      {
        "surface": {{ surface | default('nauvis') | tojson }},
        "area": {
          "left_top": {"x": {{ left | float }}, "y": {{ top | float }}},
          "right_bottom": {"x": {{ right | float }}, "y": {{ bottom | float }}}
        },
        "limit": {{ limit | default(500) | int }}
      }

  factorio_read_map:
    url: "http://local-factorio-assistant:8100/api/factory/map"
    method: POST
    content_type: application/json
    timeout: 30
    payload: >-
      {
        "surface": "nauvis",
        "area": {
          "left_top": {"x": 0, "y": 0},
          "right_bottom": {"x": 64, "y": 64}
        },
        "layers": {"entities": true, "resources": false, "tiles": false},
        "limit": 1000
      }

  factorio_production:
    url: "http://local-factorio-assistant:8100/api/factory/production"
    method: POST
    content_type: application/json
    timeout: 30
    payload: >-
      {
        "surface": "nauvis",
        "items": ["iron-plate", "copper-plate", "electronic-circuit"]
      }
```

Factory requests are bounded to protect the game: inspect/map areas cannot exceed 512 tiles in either dimension, entity results are limited to 5000, and production accepts at most 50 item names.

### Planner, Builder, and Helper phases

The phase scripts are intended for an LLM workflow where planning is reviewed
before any mutation:

```yaml
script:
  plan_factorio_factory:
    # Read-only: returns bounded factory context for the requested goal.
  build_factorio_factory:
    # Mutation is dry-run by default; set dry_run: false after review.
  helper_factorio_give_items:
    # Mutation: gives explicit item counts to one named player.
```

The corresponding REST endpoints are `POST /api/factory/plan`,
`POST /api/factory/build`, and `POST /api/factory/helper`. Planner accepts a
goal, a 128x128 area, and up to 20 optional item names. Builder accepts up to
100 explicit `{name, position: {x, y}, direction}` placements and validates
prototype existence and placement before creating ghosts. Builder creates
real entities only when `real: true` is explicitly requested; `dry_run: true`
validates without creating anything. Helper accepts up
to 50 item grants with a combined maximum of 50,000 items. Builder and Helper
are state-changing operations and should remain behind deliberate scripts or
automations.

When `enable_telemetry_mod` is enabled, the Helper endpoint sends its validated
item grants through the Factorio Assistant `give_items` interface. If the mod
is disabled or unavailable, it uses the existing bounded RCON implementation.

## Controls

These examples use the generic RCON endpoint. They can change the live save, so use them only from trusted automations.

```yaml
rest_command:
  factorio_save:
    url: "http://local-factorio-assistant:8100/api/rcon"
    method: POST
    content_type: application/json
    timeout: 30
    payload: '{"command":"/server-save"}'

  factorio_pause:
    url: "http://local-factorio-assistant:8100/api/rcon"
    method: POST
    content_type: application/json
    timeout: 15
    payload: '{"command":"/silent-command game.tick_paused = true"}'

  factorio_resume:
    url: "http://local-factorio-assistant:8100/api/rcon"
    method: POST
    content_type: application/json
    timeout: 15
    payload: '{"command":"/silent-command game.tick_paused = false"}'

  factorio_set_speed:
    url: "http://local-factorio-assistant:8100/api/rcon"
    method: POST
    content_type: application/json
    timeout: 15
    payload: >-
      {"command":"/silent-command game.speed = {{ speed | float }}"}

  factorio_broadcast:
    url: "http://local-factorio-assistant:8100/api/rcon"
    method: POST
    content_type: application/json
    timeout: 15
    payload: >-
      {"command":"/silent-command game.print({{ message | tojson }})"}
```

A script can expose a safe pause control:

```yaml
script:
  factorio_pause_game:
    alias: Factorio - Pause game
    sequence:
      - action: rest_command.factorio_pause

  factorio_resume_game:
    alias: Factorio - Resume game
    sequence:
      - action: rest_command.factorio_resume
```

For speed and broadcast commands, validate and constrain user input in the script or automation. The built-in MQTT number and text entities already apply the add-on's normal validation for those controls.

## Save Management

Scheduled backup settings are managed only from the Save files ingress page. They are not configured in `config.yaml` and are not exposed as REST commands. The page allows these values to be changed without rebuilding or restarting the add-on:

- backup enabled or disabled
- hourly, daily-at-time, or every-X-hours scheduling
- maximum number of backup archives
- optional maximum combined backup size in MB

The defaults are enabled, every 12 hours, 14 archives, and no combined-size limit. A total-size value of `0` means unlimited. The page also identifies backup archives in the save list and provides deletion for non-configured saves.

## Save Restore

The browser provides save restore through `POST /api/saves/restore`. The restore request is asynchronous when Factorio is running: the assistant asks the supervisor to stop Factorio, copies the selected save over the configured save atomically, and the supervisor starts Factorio again. The ingress page displays the current restore state. The endpoint is intentionally not included as an unrestricted Home Assistant REST command.

Use the web UI after stopping Factorio, or call the endpoint only from a tightly controlled administrative workflow:

```yaml
rest_command:
  factorio_restore_save:
    url: "http://local-factorio-assistant:8100/api/saves/restore"
    method: POST
    content_type: application/json
    timeout: 60
    payload: >-
      {"source":"{{ source }}"}
```

The source must be a save `.zip` basename and must not be the configured save itself. Confirm the selected save before calling this command; API callers should monitor the ingress status page for completion. A successful HTTP response only confirms that the restore request was accepted when Factorio was still running; it does not mean the replacement has completed.

## External Script Examples

The API can also be called from a trusted machine on the authorized network. These examples do not contain credentials:

```bash
curl --fail --silent --show-error \
  'http://local-factorio-assistant:8100/api/status'

curl --fail --silent --show-error \
  'http://local-factorio-assistant:8100/api/catalog?query=rocket&kind=item&limit=10&offset=0'

curl --fail --silent --show-error \
  -H 'Content-Type: application/json' \
  --data '{"surface":"nauvis","items":["iron-plate","copper-plate"]}' \
  'http://local-factorio-assistant:8100/api/factory/production'
```

With an API token, add `-H "X-Factorio-API-Token: $FACTORIO_API_TOKEN"` to each request. Keep the token in an environment variable or secret store; do not put it in shell history or source control.

## Errors And Safety

- `400`: invalid JSON, invalid parameters, or a request outside endpoint limits.
- `403`: the request is not from the authorized network and has no valid API token.
- `404`: unknown endpoint.
- `409`: an operation such as save restore cannot be performed in the current state.
- `503`: RCON is unavailable.
- `504`: Factorio did not answer before the RCON timeout.

The generic `/api/rcon` endpoint accepts arbitrary Factorio console commands, including mutations. Factorio console scripting can disable achievements for the save. Prefer the bounded read-only factory endpoints for inspection and keep mutating commands behind deliberate scripts or automations.
