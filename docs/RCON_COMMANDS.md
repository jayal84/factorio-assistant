# Factorio Lua Console Commands and Uses

This reference applies to the Factorio `2.0.77` headless server used by this add-on.
It focuses on commands submitted through Factorio RCON. RCON sends the same command
text that a player would enter in the in-game console.

## Important distinction

`/c` and `/sc` are not separate catalogs of built-in commands. They are two console
prefixes that execute Lua:

| Prefix | Syntax | Function |
| --- | --- | --- |
| `/c` | `/c <lua>` | Executes the Lua code and displays command output in the console/RCON response. |
| `/sc` | `/sc <lua>` | Executes the same Lua code silently. Use `rcon.print(...)` when a response is needed. |

The Lua after either prefix can be a single expression, a statement, or a longer
script containing local variables, loops, and conditionals. The valid API is the
Factorio runtime API plus APIs provided by installed mods. Consequently, there is
no finite exhaustive list of valid `/c` or `/sc` commands.

Scripting commands are powerful and using them disables achievements for the save.
Test mutating scripts on a copy of the save first.

## RCON submission

The add-on's internal RCON endpoint is `127.0.0.1:27015`; the container publishes
TCP port `27015` according to the add-on configuration. Authenticate with the RCON
password before sending a command. Examples using a generic RCON client are:

```text
/version
/c rcon.print(game.tick)
/sc rcon.print(game.tick)
```

RCON clients differ in how they quote arguments and display responses. Keep the
Factorio command itself as one request and do not add shell quoting unless the
client requires it.

## Output and error handling

Use `rcon.print` for machine-readable output, especially with `/sc`:

```text
/sc rcon.print(game.tick)
/sc rcon.print(game.players["Alice"] and "online" or "offline")
```

For a script that may fail because an object is missing, use `pcall` and print a
controlled result:

```text
/sc local ok, result = pcall(function() return game.get_player("Alice").position end); rcon.print(serpent.line({ok=ok, result=result}))
```

`game.print` and `player.print` target in-game chat, while `rcon.print` targets the
RCON response. Do not rely on chat output for automation.

## REST command endpoint

The dedicated REST API listener exposes the same Factorio RCON command path through
port `8100`; ingress remains dedicated to the browser UI on port `8099`:

```text
POST /api/rcon
Content-Type: application/json

{"command":"/version"}
```

A successful request returns the command and Factorio response:

```json
{"command":"/version","response":"Factorio 2.0.77"}
```

The endpoint returns `400` for malformed JSON or commands longer than 4096
characters, `503` when RCON is unavailable, and `504` when Factorio does not
respond before the timeout. The add-on reads the current persisted RCON
password internally. REST requests are accepted only from Home Assistant's
internal `172.30.32.0/23` network; set `HA_INTERNAL_NETWORK` if the Supervisor
network uses a different subnet. The browser ingress remains restricted to its
ingress proxy address.
Commands are not restricted to read-only operations. Treat this endpoint like
direct RCON access: `/c` and `/sc` can mutate the game and can disable
achievements.

If Home Assistant reaches the add-on from an address outside the internal
network, configure the optional add-on `api_token` setting and send the same
secret in the `X-Factorio-API-Token` header. This is a shared add-on API secret,
not a Home Assistant long-lived access token; it is compared locally and is
never logged or returned. For example:

```yaml
rest_command:
	factorio_factory_inspect:
		url: "http://local-factorio-assistant:8100/api/factory/inspect"
		method: POST
		headers:
			X-Factorio-API-Token: !secret factorio_api_token
		content_type: "application/json"
		timeout: 15
		payload: >-
			{
				"surface": {{ surface | tojson }},
				"area": {
					"left_top": {"x": {{ left }}, "y": {{ top }}},
					"right_bottom": {"x": {{ right }}, "y": {{ bottom }}}
				},
				"limit": 1000
			}
```

The browser UI uses ingress port `8099`; Home Assistant REST commands must use
port `8100`. Restart the add-on after changing `api_token` or the port setup.

The read-only catalog API can also be called from Home Assistant with
`GET /api/catalog`. It accepts `query`, `kind`, `limit`, and `offset` query
parameters and uses the same REST network or token authorization. This avoids
running the catalog search helper through a shell command.

## Factory query endpoints

Home Assistant and LLM tools should prefer the bounded, read-only factory
endpoints below instead of constructing arbitrary Lua for `/api/rcon`.

All three endpoints use `POST` with `Content-Type: application/json` and are
restricted to the same Home Assistant internal network as `/api/rcon`.

### Inspect an area

`POST /api/factory/inspect` returns entity coordinates, types, recipes, and
runtime statuses for one surface area:

```json
{
	"surface": "nauvis",
	"area": {
		"left_top": {"x": -128, "y": -128},
		"right_bottom": {"x": 128, "y": 128}
	},
	"limit": 500
}
```

The area dimensions are limited to 512 tiles and the entity limit to 5000.

### Read map data

`POST /api/factory/map` returns bounded entity and optional tile data. Set
`layers.entities`, `layers.resources`, and `layers.tiles` explicitly when a
caller needs a particular layer:

```json
{
	"surface": "nauvis",
	"area": {
		"left_top": {"x": 0, "y": 0},
		"right_bottom": {"x": 64, "y": 64}
	},
	"layers": {"entities": true, "resources": false, "tiles": false},
	"limit": 1000
}
```

Large map reviews should request multiple bounded windows rather than loading
an entire surface into one response.

### Read production statistics

`POST /api/factory/production` returns per-minute input and output counts for
up to 50 requested item names on a surface:

```json
{
	"surface": "nauvis",
	"items": ["iron-plate", "copper-plate", "electronic-circuit"]
}
```

These endpoints do not mutate the save. Responses are generated by a bounded
Factorio 2.0.77 Lua query and returned as JSON. A missing surface or invalid
request returns an error response; unavailable RCON returns `503` or `504` as
with the generic REST endpoint.

### Planner, Builder, and Helper endpoints

The Planner endpoint is read-only and returns a bounded factory summary plus
optional production context for an LLM to turn into explicit placements:

```json
{
	"surface": "nauvis",
	"goal": "Add a compact green circuit line",
	"area": {
		"left_top": {"x": -64, "y": -64},
		"right_bottom": {"x": 64, "y": 64}
	},
	"items": ["iron-plate", "copper-plate"]
}
```

Builder validates explicit placements and creates ghosts by default:

```json
{
	"surface": "nauvis",
	"real": false,
	"dry_run": false,
	"entities": [
		{"name": "assembling-machine-2", "position": {"x": 10, "y": 10}, "direction": 0}
	]
}
```

Set `real` to `true` only after reviewing the ghost placement. Set `dry_run` to
`true` to validate without creating ghosts or real entities. Builder is limited
to 100 placements. Helper gives a named player explicit item counts, reports
how many items fit, and limits a request to 50 entries and 50,000 total items:

```json
{
	"player": "Alice",
	"items": [{"name": "iron-plate", "count": 100}]
}
```

These mutating endpoints use the same authentication as `/api/rcon` and can
change the live save. They do not accept arbitrary Lua or a caller-supplied
force.

## Common runtime objects

These objects are available to console Lua in Factorio 2.0.77. Their members are
documented in the [Factorio runtime API](https://lua-api.factorio.com/latest/):

| Object | Function |
| --- | --- |
| `game` | Main game state and runtime API entry point. |
| `game.players` | Players indexed by player name or numeric index. |
| `game.connected_players` | Array of players currently online. |
| `game.surfaces` | Surfaces indexed by name or numeric index. |
| `game.forces` | Forces such as `player`, `enemy`, and `neutral`. |
| `game.item_prototypes` | Registered item prototypes and their metadata. |
| `game.recipe_prototypes` | Registered recipe prototypes and their metadata. |
| `game.technology_prototypes` | Registered technology prototypes and their metadata. |
| `prototypes` | Prototype collections available in the current runtime. |
| `defines` | Factorio constants and enum values. |
| `rcon.print(value)` | Sends text to the RCON response. |
| `serpent` | Factorio's table serialization helper, useful for readable output. |

Examples:

```text
/sc rcon.print(game.players["Alice"] and game.players["Alice"].online or false)
/sc rcon.print(game.surfaces["nauvis"].name)
/sc local count=0; for _ in pairs(game.players) do count=count+1 end; rcon.print(count)
/sc rcon.print(serpent.line({tick=game.tick, speed=game.speed, players=#game.connected_players}))
```

Prototype names and fields are stable enough for targeted queries, but the
available prototypes and some fields depend on Factorio version, Space Age, and
installed mods. Prefer IDs in automation and treat localized names as display text.

## Lua language commands

The following are valid Lua constructs that can be used after `/c` or `/sc`.
They are language features, not Factorio-specific commands:

| Lua construct | Example | Potential use |
| --- | --- | --- |
| Expression | `game.tick` | Read a value. The result is useful when printed with `rcon.print`. |
| Assignment | `game.speed = 1` | Change a writable game, force, player, or entity property. |
| Local variable | `local surface = game.surfaces["nauvis"]` | Keep a query readable and avoid repeating lookups. |
| Conditional | `if player then player.print("online") end` | Avoid errors when an object may not exist. |
| Loop | `for _, p in pairs(game.players) do ... end` | Process players, surfaces, prototypes, or entities. |
| Function | `local function name(p) return p.name end` | Reuse logic within one command. |
| Protected call | `pcall(function() ... end)` | Handle expected lookup or API errors without aborting the script. |
| Table | `{name="iron-plate", count=100}` | Pass structured parameters to Factorio API methods. |
| String formatting | `string.format("tick=%d", game.tick)` | Produce stable text for logs or automation. |

Multiple Lua statements can be separated with semicolons in a one-line RCON
request. Longer scripts are easier to maintain as mod code or a version-controlled
script file rather than being pasted into RCON.

## API commands by purpose

The following table describes the most useful runtime API areas. Each entry is a
starting point, not an exhaustive member list. Open the linked API class for the
complete members and version-specific behavior.

| Purpose | Common API members | Potential uses |
| --- | --- | --- |
| Game status | `game.tick`, `game.ticks_played`, `game.speed`, `game.finished` | Publish telemetry, detect a paused or finished game, or verify server time. |
| Players | `game.players`, `game.connected_players`, `game.get_player(name)` | List online players, inspect health/position, or target an administrative action. |
| Surfaces | `game.surfaces`, `game.get_surface(name)` | List planets/surfaces, inspect daytime, or query surface entities. |
| Forces | `game.forces`, `game.forces["player"]` | Read research, evolution, statistics, bonuses, and force membership. |
| Entities | `surface.find_entities_filtered{...}`, `game.get_entity_by_tag(tag)` | Count machines, locate tagged entities, inspect health, or perform maintenance. |
| Prototypes | `game.item_prototypes`, `game.recipe_prototypes`, `game.technology_prototypes` | Look up stable internal IDs, localized names, categories, and recipe/technology data. |
| Inventory | `player.get_main_inventory()`, `inventory.get_item_count(name)`, `player.insert(...)` | Inspect or change player inventory. Mutation requires care and permissions. |
| Research | `force.current_research`, `force.technologies[name]` | Report research state or change research in a controlled test/save. |
| Production | `force.get_item_production_statistics(surface)`, `force.get_fluid_production_statistics(surface)` | Read production and consumption flow data for dashboards. |
| Pollution | `surface.get_pollution(position)`, `surface.pollute(position, amount)` | Inspect pollution or deliberately change it for testing. |
| Saving | `game.server_save(name)`, `game.auto_save(name)` | Trigger a server save or test save behavior. |
| Messaging | `rcon.print(value)`, `game.print(message)`, `player.print(message)` | Return machine-readable output, broadcast chat, or message one player. |

## Practical Lua examples

### Server telemetry

Return one compact line that an RCON client can parse:

```text
/sc rcon.print(serpent.line({tick=game.tick, speed=game.speed, finished=game.finished, players=#game.connected_players}))
```

List online players and their current surface:

```text
/sc for _, player in pairs(game.connected_players) do rcon.print(serpent.line({name=player.name, surface=player.surface.name, x=player.position.x, y=player.position.y})) end
```

### Catalog and prototype lookup

Search item prototypes by internal ID or localized display name. This is useful
for validating catalog data before sending it to Home Assistant:

```text
/sc local needle="rocket"; for name, prototype in pairs(game.item_prototypes) do if string.find(string.lower(name), needle, 1, true) then rcon.print(serpent.line({id=name, localised_name=prototype.localised_name})) end end
```

Inspect the ingredients and products of a known recipe:

```text
/sc local recipe=game.recipe_prototypes["rocket-part"]; if recipe then rcon.print(serpent.line({name=recipe.name, category=recipe.category, enabled=recipe.enabled})) else rcon.print("missing") end
```

### Research and force state

Report research without changing it:

```text
/sc local force=game.forces["player"]; rcon.print(serpent.line({current=force.current_research and force.current_research.name or nil, progress=force.research_progress}))
```

Inspect researched technologies using stable IDs:

```text
/sc local force=game.forces["player"]; for name, technology in pairs(force.technologies) do if technology.researched then rcon.print(name) end end
```

### Entity maintenance

Count entities of a type on a surface without changing the map:

```text
/sc local surface=game.surfaces["nauvis"]; rcon.print(#surface.find_entities_filtered{type="assembling-machine"})
```

Find an entity by its map tag:

```text
/sc local entity=game.get_entity_by_tag("main-mall"); rcon.print(entity and entity.gps_tag or "not found")
```

### Controlled mutations

Only run these on an intentional target. Resolve the player first and check that
the object exists:

```text
/sc local player=game.get_player("Alice"); if player then player.insert{name="iron-plate", count=100} end
```

Change a force setting for a test scenario:

```text
/c game.forces["player"].manual_mining_speed_modifier=1
```

Clear pollution on one surface:

```text
/sc game.surfaces["nauvis"].clear_pollution()
```

## Limits and compatibility

- Console Lua runs in the live game state and can affect the save immediately.
- `game.player` can be `nil` for headless RCON execution; use `game.get_player(...)`.
- Prototype IDs are not localized. Use `localised_name` only for human-facing output.
- Mods can add APIs, commands, prototypes, and behavior that are absent from vanilla.
- API members can change between Factorio releases. Validate scripts against the
	server's pinned version before deploying them through automation.
- Large loops over all entities, prototypes, or production statistics can stall
	the game. Prefer bounded filters and small, read-only queries for telemetry.

## Read-only query examples

These examples inspect state without intentionally changing the map:

```text
# Current game version and tick
/version
/sc rcon.print(serpent.line({tick=game.tick, ticks_played=game.ticks_played, speed=game.speed}))

# Online players
/sc for _, player in pairs(game.connected_players) do rcon.print(player.name) end

# Current research for the player force
/sc local force=game.forces["player"]; rcon.print(force.current_research and force.current_research.name or "none")

# Prototype lookup
/sc local item=game.item_prototypes["iron-plate"]; rcon.print(item and item.localised_name or "missing")
```

## State-changing examples

The following are intentionally included to show the scope of `/c` and `/sc`.
Run them only when the change is wanted and after taking a backup:

```text
# Save the current multiplayer game
/server-save

# Set game speed back to normal
/c game.speed=1

# Grant an item to the current console player when one exists
/c if game.player then game.player.insert{name="iron-plate", count=100} end

# Save through the Lua API
/sc game.server_save()
```

`game.player` may be `nil` for a headless RCON command because there is no local
player typing it. Use `game.get_player("name")` when a player must be addressed,
and check the result before accessing its fields.

## Built-in slash commands

These are separate from `/c` and `/sc`. They are registered by Factorio or the
multiplayer server and do not use Lua. The table lists the commands most useful
for headless administration; `/help` on the running server is authoritative for
the exact version and installed command set.

| Command | Function | Permission |
| --- | --- | --- |
| `/help [command]` or `/h [command]` | Lists commands or describes one command. | No |
| `/version` | Prints the Factorio version. | No |
| `/players [online\|count]` or `/p` | Lists players, online players, or only the count. | No |
| `/admins` | Lists server admins. | No |
| `/time` | Prints map age and time information. | No |
| `/seed` | Prints the map seed. | No |
| `/server-save` | Saves the game on the server in multiplayer. | Admin |
| `/ban <player> [reason]` | Bans a player. | Admin |
| `/unban <player>` | Removes a player from the ban list. | Admin |
| `/kick <player> [reason]` | Kicks a player. | Admin |
| `/promote <player>` | Promotes a player to admin. | Admin |
| `/demote <player>` | Removes admin status from a player. | Admin |
| `/whitelist add\|remove\|get\|clear [player]` | Manages the multiplayer whitelist. | Admin or server permission |
| `/permissions` | Opens or manages the permissions system. | Admin |
| `/config get\|set <option> [value]` | Reads or changes multiplayer server settings. | Admin |
| `/editor` | Toggles the map editor. | Depends on server permissions |
| `/cheat [all\|off]` | Enables or disables cheat mode and related research effects. | Depends on command settings |

Command aliases and permissions can vary with the Factorio version, server
configuration, and mods. Use `/help` and `/help <command>` against the actual
server before building automation around a command.

## Security

Anyone who can authenticate to RCON can potentially run arbitrary Lua through
`/c` or `/sc`, including scripts that grant items, alter research, delete entities,
change server state, or write files inside the Factorio data directory. Protect the
RCON password, bind RCON only to trusted networks, and avoid exposing port `27015`
directly to the public internet. Treat Home Assistant services that can publish
RCON commands as administrative controls.

## References

- [Factorio console reference](https://wiki.factorio.com/Console)
- [Factorio 2.0 runtime API](https://lua-api.factorio.com/2.0.77/)
- [Project troubleshooting](TROUBLESHOOTING.md)