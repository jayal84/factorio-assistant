local event_path = "factorio_assistant_events.jsonl"
local schema_version = 1
local attack_interval_ticks = 60
local last_attack_tick = {}
local death_interval_ticks = 60
local last_death_tick = {}
local reader_name = "factorio-assistant-combinator"
local telemetry_heartbeat_ticks = 60
local last_reader_error_tick = {}

local function setting_value(name, default)
  local setting = settings.global[name]
  return setting and setting.value or default
end

local function combinator_telemetry_enabled()
  return setting_value("factorio-assistant-enable-combinator-telemetry", false) == true
end

local function event_telemetry_enabled()
  return setting_value("factorio-assistant-enable-event-telemetry", true) == true
end

local function interval_ticks(name, default_seconds)
  local seconds = tonumber(setting_value(name, default_seconds)) or default_seconds
  return math.max(telemetry_heartbeat_ticks, math.floor(seconds * 60))
end

local function write_event(event)
  if event.event == "combinator_snapshot" or event.event == "combinator_reader_changed" then
    if not combinator_telemetry_enabled() then return end
  elseif event.event ~= "state_snapshot" and not event_telemetry_enabled() then
    return
  end
  event.schema_version = schema_version
  event.source = "factorio_assistant"
  local ok, error_message = pcall(function()
    local encoded = helpers.table_to_json(event)
    helpers.write_file(event_path, encoded .. "\n", true)
  end)
  if not ok then
    log("Factorio Assistant could not write an event: " .. tostring(error_message))
  end
end

local function command_success(value)
  return {ok = true, result = value}
end

local function command_failure(message)
  return {ok = false, error = message}
end

local function is_reader(entity)
  return entity and entity.valid and entity.name == reader_name
end

local function position_data(position)
  if not position then
    return nil
  end
  return {x = position.x, y = position.y}
end

local function reader_signal_key(signal)
  return table.concat({signal.type or "", signal.name or "", signal.quality or "normal"}, ":")
end

local function read_reader_network(entity, connector_id, signals)
  local ok, network_signals = pcall(function()
    return entity.get_signals(connector_id)
  end)
  if not ok then
    local error_key = entity.unit_number .. ":" .. tostring(connector_id)
    if not last_reader_error_tick[error_key] or game.tick - last_reader_error_tick[error_key] >= 600 then
      log("Factorio Assistant could not read combinator connector " .. tostring(connector_id) .. ": " .. tostring(network_signals))
      last_reader_error_tick[error_key] = game.tick
    end
    return
  end
  if not network_signals then return end
  for _, entry in pairs(network_signals) do
    if entry.signal and entry.signal.name and entry.count then
      local key = reader_signal_key(entry.signal)
      local current = signals[key]
      if current then
        current.count = current.count + entry.count
      else
        signals[key] = {
          type = entry.signal.type or "virtual",
          name = entry.signal.name,
          quality = entry.signal.quality or "normal",
          count = entry.count,
        }
      end
    end
  end
end

local function reader_snapshot(entity)
  local signals = {}
  if setting_value("factorio-assistant-read-red-wire", true) == true then
    read_reader_network(entity, defines.wire_connector_id.combinator_input_red, signals)
  end
  if setting_value("factorio-assistant-read-green-wire", true) == true then
    read_reader_network(entity, defines.wire_connector_id.combinator_input_green, signals)
  end
  local signal_list = {}
  for _, signal in pairs(signals) do table.insert(signal_list, signal) end
  table.sort(signal_list, function(left, right)
    return (left.type .. ":" .. left.name .. ":" .. left.quality) < (right.type .. ":" .. right.name .. ":" .. right.quality)
  end)
  local max_signals = math.max(1, math.floor(tonumber(setting_value("factorio-assistant-max-combinator-signals", 100)) or 100))
  while #signal_list > max_signals do table.remove(signal_list) end
  local placed_by = ""
  local last_user_ok, last_user = pcall(function() return entity.last_user end)
  if last_user_ok and last_user then placed_by = last_user.name or "" end
  local description = ""
  local description_ok, description_value = pcall(function() return entity.combinator_description end)
  if description_ok and type(description_value) == "string" then
    description = description_value
  end
  if description == "" then
    local name_tag_ok, name_tag = pcall(function() return entity.name_tag end)
    if name_tag_ok and type(name_tag) == "string" then description = name_tag end
  end
  return {
    event = "combinator_snapshot",
    unit_number = entity.unit_number,
    surface = entity.surface.name,
    position = position_data(entity.position),
    name = description,
    placed_by = placed_by,
    signals = signal_list,
    tick = game.tick,
  }
end

local function emit_reader_snapshots()
  if not combinator_telemetry_enabled() then return end
  for _, surface in pairs(game.surfaces or {}) do
    for _, entity in pairs(surface.find_entities_filtered({name = reader_name})) do
      if is_reader(entity) then write_event(reader_snapshot(entity)) end
    end
  end
end

remote.add_interface("factorio_assistant", {
  broadcast_chat = function(message)
    if type(message) ~= "string" or message == "" then
      return command_failure("message must be a non-empty string")
    end
    game.print(message)
    return command_success(message)
  end,

  set_game_speed = function(speed)
    speed = tonumber(speed)
    if not speed or speed < 0.1 or speed > 10 then
      return command_failure("speed must be between 0.1 and 10")
    end
    game.speed = speed
    game.tick_paused = false
    return command_success(speed)
  end,

  set_pause = function(paused)
    if type(paused) ~= "boolean" then
      return command_failure("paused must be a boolean")
    end
    game.tick_paused = paused
    return command_success(paused)
  end,

  set_map_setting = function(setting, enabled)
    if setting ~= "enemy_evolution" and setting ~= "pollution" then
      return command_failure("unsupported map setting")
    end
    if type(enabled) ~= "boolean" then
      return command_failure("enabled must be a boolean")
    end
    game.map_settings[setting].enabled = enabled
    return command_success(enabled)
  end,

  save_game = function()
    local ok, error_message = pcall(function() game.auto_save() end)
    if not ok then return command_failure(tostring(error_message)) end
    return command_success(true)
  end,

  world_summary = function()
    local force = game.forces.player
    local surfaces = {}
    for _, surface in pairs(game.surfaces or {}) do
      local pollution = 0
      local pollution_ok, pollution_value = pcall(function() return surface.get_total_pollution() end)
      if pollution_ok and pollution_value then pollution = pollution_value end
      table.insert(surfaces, {name = surface.name, index = surface.index, pollution = pollution})
    end
    local players = {}
    for _, player in pairs(game.connected_players or {}) do
      table.insert(players, {
        name = player.name,
        surface = player.surface and player.surface.name or "unknown",
        x = math.floor(player.position.x),
        y = math.floor(player.position.y),
      })
    end
    local research = force and force.current_research and force.current_research.name or ""
    local research_queue = {}
    local technologies_researched = 0
    local technologies_total = 0
    if force then
      for _, technology in ipairs(force.research_queue or {}) do table.insert(research_queue, technology.name) end
      for _, technology in pairs(force.technologies or {}) do
        technologies_total = technologies_total + 1
        if technology.researched then technologies_researched = technologies_researched + 1 end
      end
    end
    local evolution = force and force.get_evolution_factor() or 0
    return command_success({
      available = true,
      tick = game.tick,
      speed = game.speed or 0,
      tick_paused = game.tick_paused or false,
      daytime = game.surfaces.nauvis and game.surfaces.nauvis.daytime or 0,
      game_day = math.floor(game.tick / 25000),
      game_time = math.floor(game.tick / 60),
      research = research,
      research_progress = force and (force.research_progress or 0) * 100 or 0,
      research_queue = research_queue,
      technologies_researched = technologies_researched,
      technologies_total = technologies_total,
      rockets_launched = 0,
      evolution = evolution,
      evolution_progress = evolution * 100,
      active_entity_count = 0,
      surfaces = surfaces,
      players = players,
    })
  end,

  research_summary = function()
    local force = game.forces.player
    if not force then
      return command_success({available = false, researched = {}, current = "", progress = 0, queue = {}})
    end
    local researched = {}
    for name, technology in pairs(force.technologies or {}) do
      if technology.researched then table.insert(researched, name) end
    end
    local queue = {}
    for _, technology in ipairs(force.research_queue or {}) do table.insert(queue, technology.name) end
    return command_success({
      available = true,
      researched = researched,
      current = force.current_research and force.current_research.name or "",
      progress = (force.research_progress or 0) * 100,
      queue = queue,
    })
  end,

  factory_query = function(operation, options)
    if type(operation) ~= "string" or type(options) ~= "table" then
      return command_failure("operation and options are required")
    end
    local surface_name = options.surface or "nauvis"
    local surface = game.surfaces[surface_name]
    if not surface then return command_failure("surface_not_found") end
    local bounds = nil
    if operation ~= "production" then
      local area = options.area
      if type(area) ~= "table" or type(area.left_top) ~= "table" or type(area.right_bottom) ~= "table" then
        return command_failure("area is required")
      end
      local left = area.left_top
      local right = area.right_bottom
      bounds = {left_top = {x = left.x, y = left.y}, right_bottom = {x = right.x, y = right.y}}
    end
    local limit = math.min(math.max(math.floor(tonumber(options.limit) or 1000), 1), 5000)
    local entities = bounds and surface.find_entities_filtered({area = bounds, limit = limit}) or {}

    local function entity_record(entity, include_status)
      local record = {name = entity.name, type = entity.type, x = entity.position.x, y = entity.position.y, direction = entity.direction}
      local recipe_ok, recipe = pcall(function() return entity.get_recipe() end)
      record.recipe = recipe_ok and recipe and recipe.name or nil
      if include_status then record.status = tostring(entity.status or "unknown") end
      return record
    end
    local function counts(rows)
      local types, recipes, statuses = {}, {}, {}
      for _, entity in ipairs(rows) do
        if entity.valid then
          types[entity.type] = (types[entity.type] or 0) + 1
          local recipe_ok, recipe = pcall(function() return entity.get_recipe() end)
          if recipe_ok and recipe then recipes[recipe.name] = (recipes[recipe.name] or 0) + 1 end
          local status = tostring(entity.status or "unknown")
          statuses[status] = (statuses[status] or 0) + 1
        end
      end
      return types, recipes, statuses
    end

    if operation == "inspect" then
      local types, recipes, statuses = counts(entities)
      local records = {}
      for _, entity in ipairs(entities) do if entity.valid then table.insert(records, entity_record(entity, true)) end end
      return command_success({surface = surface.name, entity_count = #entities, types = types, recipes = recipes, statuses = statuses, entities = records})
    elseif operation == "map" then
      local records, tiles = {}, {}
      if options.entities ~= false then
        for _, entity in ipairs(entities) do
          if entity.valid and (options.resources ~= false or entity.type ~= "resource") then table.insert(records, entity_record(entity, false)) end
        end
      end
      if options.tiles == true then
        for _, tile in ipairs(surface.find_tiles_filtered({area = bounds, limit = limit})) do
          table.insert(tiles, {name = tile.name, x = tile.position.x, y = tile.position.y})
        end
      end
      return command_success({surface = surface.name, entities = records, tiles = tiles})
    elseif operation == "production" or operation == "plan" then
      local force = game.forces.player
      local production = {}
      local names = options.items or {}
      if force then
        local stats = force.get_item_production_statistics(surface)
        for _, name in ipairs(names) do
          if game.item_prototypes[name] then
            table.insert(production, {name = name, input_per_minute = (stats.get_input_count(name) or 0) * 60, output_per_minute = (stats.get_output_count(name) or 0) * 60})
          end
        end
      end
      if operation == "production" then return command_success({surface = surface.name, items = production}) end
      local types, recipes = counts(entities)
      return command_success({phase = "planner", goal = options.goal or "", surface = surface.name, entity_count = #entities, types = types, recipes = recipes, production = production})
    elseif operation == "build" then
      local force = game.forces.player
      local results = {}
      local dry_run = options.dry_run == true
      local real = options.real == true
      for _, entry in ipairs(options.entities or {}) do
        local status = "blocked"
        local prototype = prototypes.entity[entry.name]
        if not prototype then
          status = "prototype_not_found"
        else
          local can_place_ok, can_place = pcall(function() return surface.can_place_entity({name = entry.name, position = {x = entry.x, y = entry.y}, direction = entry.direction, force = force}) end)
          if can_place_ok and can_place then
            if dry_run then
              status = "would_place"
            else
              local spec = {name = entry.name, position = {x = entry.x, y = entry.y}, direction = entry.direction, force = force}
              if not real then spec = {name = "entity-ghost", inner_name = entry.name, position = {x = entry.x, y = entry.y}, direction = entry.direction, force = force} end
              local created = surface.create_entity(spec)
              status = created and (real and "placed" or "ghost_placed") or "create_failed"
            end
          end
        end
        table.insert(results, {name = entry.name, x = entry.x, y = entry.y, direction = entry.direction, status = status})
      end
      return command_success({phase = "builder", surface = surface.name, real = real, dry_run = dry_run, results = results})
    elseif operation == "demolish" then
      local real = options.real == true
      local include_resources = options.resources == true
      local names = {}
      for _, name in ipairs(options.names or {}) do names[name] = true end
      local results = {}
      local marked, removed = 0, 0
      for _, entity in ipairs(entities) do
        if entity.valid and entity.type ~= "character" and (include_resources or entity.type ~= "resource") and (#(options.names or {}) == 0 or names[entity.name]) then
          local status
          if real then
            local ok = pcall(function() entity.destroy({raise_destroy = true}) end)
            status = ok and "removed" or "remove_failed"
            if ok then removed = removed + 1 end
          else
            local ok = pcall(function() entity.order_deconstruction("player") end)
            status = ok and "marked" or "mark_failed"
            if ok then marked = marked + 1 end
          end
          table.insert(results, {name = entity.name, x = entity.position.x, y = entity.position.y, status = status})
        end
      end
      return command_success({phase = "demolition", surface = surface.name, real = real, marked = marked, removed = removed, results = results})
    end
    return command_failure("unsupported factory operation")
  end,

  give_items = function(player_name, grants)
    if type(player_name) ~= "string" or player_name == "" then
      return command_failure("player must be a non-empty string")
    end
    if type(grants) ~= "table" or #grants < 1 or #grants > 50 then
      return command_failure("grants must contain between 1 and 50 entries")
    end
    local player = game.get_player(player_name)
    if not player then
      return command_failure("player_not_found")
    end

    local total = 0
    local results = {}
    for _, grant in ipairs(grants) do
      if type(grant) ~= "table" or type(grant.name) ~= "string" then
        return command_failure("each grant must contain an item name")
      end
      local count = tonumber(grant.count)
      if not count or count < 1 or count > 50000 or count % 1 ~= 0 then
        return command_failure("each item count must be an integer between 1 and 50000")
      end
      total = total + count
      if total > 50000 then
        return command_failure("total item count must not exceed 50000")
      end
      local inserted = 0
      if game.item_prototypes[grant.name] then
        inserted = player.insert({name = grant.name, count = count})
      end
      table.insert(results, {
        name = grant.name,
        requested = count,
        inserted = inserted,
        remaining = count - inserted,
      })
    end
    return command_success({phase = "helper", player = player.name, results = results})
  end,
})

local function surface_name(entity)
  if entity and entity.surface and entity.surface.valid then
    return entity.surface.name
  end
  return "unknown"
end

local function player_data(player)
  local details = {force = "unknown", surface = "unknown", controller = "unknown", admin = false}
  local ok, value = pcall(function() return player.index end)
  if ok then details.index = value end
  ok, value = pcall(function() return player.force and player.force.name end)
  if ok and value then details.force = value end
  ok, value = pcall(function() return player.surface and player.surface.name end)
  if ok and value then details.surface = value end
  ok, value = pcall(function() return position_data(player.position) end)
  if ok then details.position = value end
  ok, value = pcall(function() return tostring(player.controller_type) end)
  if ok and value then details.controller = value end
  ok, value = pcall(function() return player.admin end)
  if ok then details.admin = value end

  local character_ok, character = pcall(function() return player.character end)
  if character_ok and character and character.valid then
    ok, value = pcall(function() return character.health end)
    if ok then details.health = value end
    ok, value = pcall(function() return character.max_health end)
    if ok and value ~= nil then
      details.max_health = value
    else
      ok, value = pcall(function() return character.get_max_health() end)
      if ok and value ~= nil then details.max_health = value end
    end
  end
  return details
end

local function cause_data(cause)
  local valid_ok, valid = pcall(function() return cause and cause.valid end)
  if not valid_ok or not valid then
    return nil
  end
  local details = {force = "unknown", surface = "unknown"}
  local ok, value = pcall(function() return cause.name end)
  if ok then details.name = value end
  ok, value = pcall(function() return cause.type end)
  if ok then details.type = value end
  ok, value = pcall(function() return cause.force and cause.force.name end)
  if ok and value then details.force = value end
  ok, value = pcall(function() return cause.surface and cause.surface.name end)
  if ok and value then details.surface = value end
  ok, value = pcall(function() return position_data(cause.position) end)
  if ok then details.position = value end
  return details
end

local function entity_data(entity)
  local details = {}
  local ok, value = pcall(function() return entity.name end)
  if ok then details.name = value end
  ok, value = pcall(function() return entity.type end)
  if ok then details.type = value end
  ok, value = pcall(function() return entity.force and entity.force.name end)
  if ok then details.force = value or "unknown" end
  ok, value = pcall(function() return entity.surface and entity.surface.name end)
  if ok then details.surface = value or "unknown" end
  ok, value = pcall(function() return position_data(entity.position) end)
  if ok then details.position = value end
  return details
end

local function snapshot_player_data(player)
  local details = player_data(player)
  local player_deaths = storage.factorio_assistant_player_deaths or {}
  storage.factorio_assistant_player_deaths = player_deaths
  details.connected = player.connected
  details.deaths = player_deaths[player.name] or 0
  details.idle = (player.afk_time or 0) > 3600
  details.position = position_data(player.position)
  details.surface = player.surface and player.surface.name or "unknown"
  details.armor = {name = "none", equipment_count = 0}
  details.inventory = {used_slots = 0, total_slots = 0}

  if setting_value("factorio-assistant-include-inventory-details", true) ~= true then
    return details
  end

  local armor_ok, armor_inventory = pcall(function()
    return player.get_inventory(defines.inventory.character_armor)
  end)
  if armor_ok and armor_inventory then
    for index = 1, #armor_inventory do
      local stack = armor_inventory[index]
      if stack and stack.valid_for_read then
        details.armor = {name = stack.name or "none", equipment_count = stack.count or 0}
        break
      end
    end
  end

  local inventory_ok, inventory = pcall(function()
    return player.get_main_inventory()
  end)
  if inventory_ok and inventory then
    details.inventory.total_slots = #inventory
    for index = 1, #inventory do
      if inventory[index] and inventory[index].valid_for_read then
        details.inventory.used_slots = details.inventory.used_slots + 1
      end
    end
  end
  return details
end

local function emit_state_snapshot()
  local force = game.forces.player
  local enemy_force = game.forces.enemy
  local players = {}
  local surfaces = {}
  local players_online = 0
  local surface_count = 0

  for _, player in pairs(game.players or {}) do
    players[player.name] = snapshot_player_data(player)
    if player.connected then
      players_online = players_online + 1
    end
  end

  for _, surface in pairs(game.surfaces or {}) do
    surface_count = surface_count + 1
    local pollution = 0
    local pollution_ok, pollution_value = pcall(function()
      return surface.get_total_pollution()
    end)
    if pollution_ok and pollution_value ~= nil then
      pollution = pollution_value
    end
    surfaces[surface.name] = {pollution = pollution}
  end

  local research = ""
  local research_progress = 0
  local research_queue = {}
  local technologies_researched = 0
  local technologies_total = 0
  local difficulty = ""
  local map_settings = ""
  if force then
    research = force.current_research and force.current_research.name or ""
    research_progress = force.research_progress or 0
    for _, technology in ipairs(force.research_queue or {}) do
      table.insert(research_queue, technology.name)
    end
    for _, technology in pairs(force.technologies or {}) do
      technologies_total = technologies_total + 1
      if technology.researched then
        technologies_researched = technologies_researched + 1
      end
    end
  end

  local difficulty_ok, difficulty_value = pcall(function()
    return game.difficulty_settings.recipe_difficulty
  end)
  if difficulty_ok and difficulty_value ~= nil then
    difficulty = tostring(difficulty_value)
  end
  local evolution_ok, evolution_enabled = pcall(function()
    return game.map_settings.enemy_evolution.enabled
  end)
  local pollution_ok, pollution_enabled = pcall(function()
    return game.map_settings.pollution.enabled
  end)
  if evolution_ok or pollution_ok then
    map_settings = string.format(
      "enemy_evolution=%s; pollution=%s",
      tostring(evolution_ok and evolution_enabled or false),
      tostring(pollution_ok and pollution_enabled or false)
    )
  end

  local elapsed_ticks = game.tick
  local ticks_played_ok, ticks_played = pcall(function() return game.ticks_played end)
  if ticks_played_ok and ticks_played ~= nil then elapsed_ticks = ticks_played end

  write_event({
    event = "state_snapshot",
    tick = game.tick,
    server = {
      tick = game.tick,
      speed = game.speed or 0,
      tick_paused = game.tick_paused or false,
      players_online = players_online,
    },
    world = {
      research = research,
      research_progress = research_progress,
      research_queue = research_queue,
      technologies_researched = technologies_researched,
      technologies_total = technologies_total,
      rockets_launched = force and force.rockets_launched or 0,
      evolution_factor = enemy_force and enemy_force.get_evolution_factor() or 0,
      evolution_progress = (enemy_force and enemy_force.get_evolution_factor() or 0) * 100,
      game_day = math.floor(elapsed_ticks / 25000),
      game_time = tostring(math.floor(elapsed_ticks / 60)),
      surface_count = surface_count,
      surface_names = table.concat((function()
        local names = {}
        for name in pairs(surfaces) do table.insert(names, name) end
        table.sort(names)
        return names
      end)(), ","),
      difficulty = difficulty,
      map_settings = map_settings,
      surfaces = surfaces,
    },
    players = players,
  })
end

local function emit_configured_telemetry()
  if game.tick % interval_ticks("factorio-assistant-world-snapshot-interval", 20) == 0 then
    emit_state_snapshot()
  end
  if game.tick % interval_ticks("factorio-assistant-combinator-scan-interval", 2) == 0 then
    emit_reader_snapshots()
  end
end

script.on_nth_tick(telemetry_heartbeat_ticks, emit_configured_telemetry)

local function reader_from_event(event)
  local entity = event.entity or event.created_entity or event.destination
  return is_reader(entity) and entity or nil
end

local function publish_reader_change(event, action)
  if not combinator_telemetry_enabled() then return end
  local entity = reader_from_event(event)
  if not entity then return end
  local snapshot = reader_snapshot(entity)
  snapshot.event = "combinator_reader_changed"
  snapshot.action = action
  write_event(snapshot)
end

for _, event_name in pairs({
  defines.events.on_built_entity,
  defines.events.on_robot_built_entity,
  defines.events.script_raised_built,
  defines.events.script_raised_revive,
}) do
  script.on_event(event_name, function(event) publish_reader_change(event, "placed") end)
end

for _, event_name in pairs({
  defines.events.on_player_mined_entity,
  defines.events.on_robot_mined_entity,
  defines.events.script_raised_destroy,
}) do
  script.on_event(event_name, function(event)
    local entity = event.entity or event.entity_number and nil
    if not entity or entity.name ~= reader_name then return end
    write_event({
      event = "combinator_reader_changed",
      action = "removed",
      unit_number = entity.unit_number,
      tick = game.tick,
    })
  end)
end

script.on_event(defines.events.on_entity_damaged, function(event)
  local entity = event.entity
  local cause = event.cause
  if not entity or not entity.valid or not cause or not cause.valid then
    return
  end
  if not entity.force or entity.force.name ~= "player" then
    return
  end
  if not cause.force or cause.force.name ~= "enemy" then
    return
  end

  local current_tick = game.tick
  local surface = surface_name(entity)
  local previous_tick = last_attack_tick[surface] or -attack_interval_ticks
  if current_tick - previous_tick < attack_interval_ticks then
    return
  end
  last_attack_tick[surface] = current_tick

  write_event({
    event = "surface_attack",
    surface = surface,
    tick = current_tick,
    entity = entity.name,
    damage = event.final_damage_amount or event.original_damage_amount or 0,
  })
end)

script.on_event(defines.events.on_player_died, function(event)
  local player = game.get_player(event.player_index)
  if not player then
    return
  end
  local player_deaths = storage.factorio_assistant_player_deaths or {}
  storage.factorio_assistant_player_deaths = player_deaths
  player_deaths[player.name] = (player_deaths[player.name] or 0) + 1
  write_event({
    event = "player_died",
    player = player.name,
    tick = game.tick,
    player_data = player_data(player),
    cause = cause_data(event.cause),
  })
end)

script.on_event(defines.events.on_player_joined_game, function(event)
  local player = game.get_player(event.player_index)
  if not player then
    return
  end
  write_event({
    event = "player_joined",
    player = player.name,
    tick = game.tick,
    player_data = player_data(player),
  })
end)

script.on_event(defines.events.on_player_left_game, function(event)
  local player = game.get_player(event.player_index)
  if not player then
    return
  end
  write_event({
    event = "player_left",
    player = player.name,
    tick = game.tick,
    player_data = player_data(player),
  })
end)

script.on_event(defines.events.on_player_changed_surface, function(event)
  local player = game.get_player(event.player_index)
  if not player then
    return
  end
  write_event({
    event = "player_changed_surface",
    player = player.name,
    tick = game.tick,
    surface_index = event.surface_index,
    player_data = player_data(player),
  })
end)

script.on_event(defines.events.on_player_respawned, function(event)
  local player = game.get_player(event.player_index)
  if not player then
    return
  end
  write_event({
    event = "player_respawned",
    player = player.name,
    tick = game.tick,
    player_data = player_data(player),
  })
end)

script.on_event(defines.events.on_research_finished, function(event)
  local research = event.research
  if not research then
    return
  end
  local ok, name = pcall(function() return research.name end)
  if not ok or not name then
    return
  end
  local force_name = "unknown"
  local force_ok, force_value = pcall(function() return research.force and research.force.name end)
  if force_ok and force_value then
    force_name = force_value
  end
  write_event({
    event = "research_finished",
    technology = name,
    force = force_name,
    tick = game.tick,
  })
end)

script.on_event(defines.events.on_rocket_launched, function(event)
  local silo = event.rocket_silo
  write_event({
    event = "rocket_launched",
    tick = game.tick,
    player = event.player_index and game.get_player(event.player_index) and game.get_player(event.player_index).name or nil,
    silo = entity_data(silo),
  })
end)

script.on_event(defines.events.on_entity_died, function(event)
  local entity = event.entity
  if combinator_telemetry_enabled() and entity and entity.name == reader_name then
    write_event({
      event = "combinator_reader_changed",
      action = "removed",
      unit_number = entity.unit_number,
      tick = game.tick,
    })
  end
  if not entity or not entity.valid then
    return
  end
  local details = entity_data(entity)
  if details.force ~= "player" and details.type ~= "unit" and details.type ~= "unit-spawner" then
    return
  end
  local surface = details.surface or "unknown"
  local previous_tick = last_death_tick[surface] or -death_interval_ticks
  if game.tick - previous_tick < death_interval_ticks then
    return
  end
  last_death_tick[surface] = game.tick
  write_event({
    event = "entity_died",
    tick = game.tick,
    entity = details,
    cause = cause_data(event.cause),
  })
end)

script.on_event(defines.events.on_console_chat, function(event)
  if not event.message or event.message == "" then
    return
  end
  local player = event.player_index and game.get_player(event.player_index) or nil
  write_event({
    event = "console_chat",
    player = player and player.name or "server",
    player_index = event.player_index,
    message = event.message,
    surface = player and player.surface and player.surface.name or "unknown",
    tick = game.tick,
  })
end)
