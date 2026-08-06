local tint = {r = 0.25, g = 0.65, b = 1.0, a = 1.0}

local function tint_main_render(sprites)
  if type(sprites) ~= "table" or type(sprites.layers) ~= "table" then return end
  for _, layer in pairs(sprites.layers) do
    if type(layer) == "table" and layer.filename and not layer.draw_as_shadow then
      layer.tint = tint
    end
  end
end

local base_entity = data.raw["arithmetic-combinator"]["arithmetic-combinator"]
local reader_entity = table.deepcopy(base_entity)
reader_entity.name = "factorio-assistant-combinator"
reader_entity.localised_name = {"entity-name.factorio-assistant-combinator"}
reader_entity.localised_description = {"entity-description.factorio-assistant-combinator"}
reader_entity.icon = "__base__/graphics/icons/arithmetic-combinator.png"
reader_entity.minable = table.deepcopy(reader_entity.minable)
reader_entity.minable.result = "factorio-assistant-combinator"
reader_entity.placeable_by = {item = "factorio-assistant-combinator", count = 1}
reader_entity.fast_replaceable_group = "factorio-assistant-combinator"
tint_main_render(reader_entity.sprites)
data:extend({reader_entity})

local base_item = data.raw.item["arithmetic-combinator"]
local reader_item = table.deepcopy(base_item)
reader_item.name = "factorio-assistant-combinator"
reader_item.localised_name = {"item-name.factorio-assistant-combinator"}
reader_item.localised_description = {"item-description.factorio-assistant-combinator"}
reader_item.place_result = "factorio-assistant-combinator"
reader_item.icon = "__base__/graphics/icons/arithmetic-combinator.png"
reader_item.order = "c[combinators]-e[factorio-assistant-combinator]"
data:extend({reader_item})

local base_recipe = data.raw.recipe["arithmetic-combinator"]
local reader_recipe = table.deepcopy(base_recipe)
reader_recipe.name = "factorio-assistant-combinator"
reader_recipe.localised_name = {"recipe-name.factorio-assistant-combinator"}
reader_recipe.enabled = false
reader_recipe.ingredients = table.deepcopy(base_recipe.ingredients)
reader_recipe.results = {{type = "item", name = "factorio-assistant-combinator", amount = 1}}
data:extend({reader_recipe})

data:extend({
  {
    type = "technology",
    name = "factorio-assistant-combinator",
    localised_name = {"technology-name.factorio-assistant-combinator"},
    localised_description = {"technology-description.factorio-assistant-combinator"},
    icon = "__base__/graphics/technology/circuit-network.png",
    icon_size = 256,
    prerequisites = {"circuit-network"},
    unit = {
      count = 100,
      ingredients = {
        {"automation-science-pack", 1},
        {"logistic-science-pack", 1},
      },
      time = 30,
    },
    effects = {{type = "unlock-recipe", recipe = "factorio-assistant-combinator"}},
    order = "circuit-network-a[factorio-assistant-combinator]",
  },
})
