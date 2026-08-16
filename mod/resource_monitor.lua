require('version')

require('commands/commands')

require('util/util')

require('components/translation')
require('components/settings')
require('components/resources')
require('components/sites')
require('components/surfaces')
require('components/scanner')
require('components/ui/ui')

-- enable gvv
if script.active_mods['gvv'] then
    require('__gvv__.gvv')()
end

---Called on mod startup
function boot(event, initialize_storage)
    if initialize_storage == true and storage.sites == nil then
        Sites.resetGlobal()
    end
    Resources.boot(initialize_storage == true)
    Settings.boot()
    Scanner.boot()
    Sites.boot()
    Ui.boot()
end

---Called on new players
function dqol_boot_player(player)
    Ui.bootPlayer(player)
    Resources.bootPlayer(player)
end

function dqol_reboot_players()
    for key, player in pairs(game.players) do dqol_boot_player(player) end    
end

---This is called when this mod is new to a save, before migrations
function dqol_on_init(event)
    boot(event, true)

    Scanner.onInitMod()
    Sites.onInitMod()
    Surfaces.onInitMod()

    dqol_reboot_players()
end

---This is called when this mod is not new to a save, after migrations
function dqol_on_load(event)
    boot(event, false)
end

local function dqol_initialize_missing_storage()
    local missing_sites = storage.sites == nil
    local missing_resources = storage.resources == nil
    local missing_scanner = storage.scanner == nil
    local missing_surfaces = storage.surface_storage == nil
    if missing_sites then
        Sites.resetGlobal()
    end
    if missing_resources then
        Resources.boot(true)
    end
    if missing_scanner then
        Scanner.onInitMod()
    end
    if missing_surfaces then
        Surfaces.onInitMod()
    end
    if missing_sites then
        Sites.onInitMod()
    end
    if missing_sites or missing_resources or missing_scanner or missing_surfaces then
        dqol_reboot_players()
    end
    return missing_sites or missing_resources or missing_scanner or missing_surfaces
end

---This is called after dqol_on_init/dqol_on_load when the mod config changed
---@see https://lua-api.factorio.com/latest/auxiliary/data-lifecycle.html
function dqol_on_configuration_changed(event)
    dqol_initialize_missing_storage()
    Resources.on_configuration_changed()
    Settings.on_configuration_changed(event)
    Surfaces.on_configuration_changed()
    Ui.on_configuration_changed(event)
end



---This is called when a player is created (singleplayer game start)
function dqol_on_player_created(event)
    dqol_boot_player(game.players[event.player_index])
end

---This is called when a player is created in multiplayer (join)
function dqol_on_player_joined_game(event)
    -- this is also called in singleplayer once when the game is created
    -- therefore, filter when tick is 0
    if game.tick > 0 then
        dqol_boot_player(game.players[event.player_index])
    end
end

