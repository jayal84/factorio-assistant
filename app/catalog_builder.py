#!/usr/bin/env python3
"""Build a searchable index from Factorio's JSON data dump."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import catalog_db


DATA_DIR = Path(os.environ.get("FACTORIO_DATA_DIR", "/share/factorio"))
SCRIPT_OUTPUT_DIR = DATA_DIR / "script-output"
REFERENCE_DIR = Path("/app/factorio-reference")
SCHEMA_VERSION = 2

# Prototype types that only describe presentation, audio, or engine internals.
PRESENTATION_TYPES = {
    "airborne-pollutant", "ambient-sound", "ammo-category", "animation", "arrow", "autoplace-control",
    "beam", "burner-usage", "character-corpse", "collision-layer", "corpse", "custom-input",
    "damage-type", "deconstructible-tile-proxy", "decorative", "deliver-impact-combination",
    "editor-controller", "entity-ghost", "equipment-category", "equipment-grid", "explosion", "fire",
    "flying-text", "font", "fuel-category", "god-controller", "gui-style", "highlight-box",
    "item-entity", "item-request-proxy", "map-gen-presets", "map-settings", "module-category",
    "mouse-cursor", "noise-expression", "noise-function", "noise-layer", "optimized-decorative",
    "optimized-particle", "particle", "particle-source", "projectile", "rail-remnants",
    "recipe-category", "remote-controller", "resource-category", "rocket-silo-rocket-shadow",
    "shortcut", "smoke", "smoke-with-trigger", "sound", "speech-bubble", "spectator-controller",
    "sprite", "sticker", "stream", "surface-property", "tile-effect", "tips-and-tricks-item",
    "tips-and-tricks-item-category", "trigger-target-type", "trivial-smoke", "tutorial",
    "utility-constants", "utility-sounds", "utility-sprites",
}

ITEM_TYPES = {
    "item", "ammo", "armor", "blueprint", "blueprint-book", "capsule", "copy-paste-tool",
    "deconstruction-item", "gun", "item-with-entity-data", "item-with-inventory", "item-with-label",
    "item-with-tags", "mining-tool", "module", "rail-planner", "repair-tool", "selection-tool",
    "space-platform-starter-pack", "spidertron-remote", "tool", "upgrade-item",
}
VEHICLE_TYPES = {"car", "locomotive", "cargo-wagon", "fluid-wagon", "artillery-wagon", "spider-vehicle"}
WEAPON_ITEM_TYPES = {"gun", "ammo"}
ACHIEVEMENT_TYPES = {
    "achievement", "build-entity-achievement", "combat-robot-count-achievement",
    "construct-with-robots-achievement", "deconstruct-with-robots-achievement",
    "deliver-by-robots-achievement", "dont-build-entity-achievement", "dont-craft-manually-achievement",
    "dont-use-entity-in-energy-production-achievement", "finish-the-game-achievement",
    "group-attack-achievement", "kill-achievement", "player-damaged-achievement",
    "produce-achievement", "produce-per-hour-achievement", "research-achievement", "shoot-achievement",
    "train-path-achievement",
}
EXPLICIT_KINDS = {
    "recipe": "recipe",
    "technology": "technology",
    "fluid": "fluid",
    "resource": "resource",
    "tile": "tile",
    "virtual-signal": "signal",
    "space-location": "space",
    "space-connection": "space",
    "planet": "space",
    "surface": "space",
    "asteroid-chunk": "space",
    "quality": "quality",
}

# Localization domains searched when a prototype has no explicit localised_name.
KIND_LOCALE_DOMAINS = {
    "item": ("item", "entity", "equipment", "fluid"),
    "module": ("item", "entity"),
    "equipment": ("equipment", "item", "entity"),
    "weapon": ("item", "entity"),
    "vehicle": ("entity", "item"),
    "entity": ("entity", "item"),
    "fluid": ("fluid", "item"),
    "recipe": ("recipe", "item", "entity", "fluid"),
    "technology": ("technology",),
    "resource": ("entity", "item"),
    "tile": ("tile", "entity"),
    "signal": ("virtual-signal", "item", "fluid"),
    "space": ("space-location", "space-connection", "surface", "asteroid-chunk"),
    "achievement": ("achievement",),
    "setting": ("mod-setting",),
    "quality": ("quality",),
}
LOCALE_DOMAIN_ORDER = (
    "item", "entity", "fluid", "recipe", "technology", "equipment", "tile", "virtual-signal",
    "achievement", "mod-setting", "space-location", "space-connection", "asteroid-chunk", "surface",
    "quality", "decorative", "autoplace-control", "shortcut", "custom-input", "ammo-category",
    "damage-type", "fuel-category", "item-group", "recipe-category", "surface-property",
    "airborne-pollutant", "noise-expression",
)

# Factorio emits these when a mod's locale key is missing or malformed.
JUNK_LOCALE = re.compile(r"^(unknown key|something went wrong|__|localised)", re.IGNORECASE)

COMMON_FIELDS = ("order", "hidden", "hidden_in_factoriopedia", "icon", "icons", "icon_size", "flags")
KIND_FIELDS = {
    "item": ("stack_size", "fuel_category", "fuel_value", "fuel_acceleration_multiplier", "place_result",
             "place_as_tile", "placed_as_equipment_result", "burnt_result", "spoil_result", "spoil_ticks",
             "weight", "rocket_capacity", "ammo_category", "magazine_size", "durability", "effect",
             "category", "tier", "inventory_size", "equipment_grid", "capsule_action"),
    "fluid": ("default_temperature", "max_temperature", "heat_capacity", "fuel_value", "gas_temperature",
              "auto_barrel", "emissions_multiplier"),
    "recipe": ("category", "additional_categories", "energy_required", "enabled", "allow_productivity",
               "maximum_productivity", "allow_quality", "surface_conditions", "main_product",
               "requester_paste_multiplier", "hidden_from_player_crafting", "hidden_from_flow_stats"),
    "technology": ("prerequisites", "effects", "unit", "max_level", "upgrade", "essential",
                   "research_trigger"),
    "resource": ("category", "infinite", "minimum", "normal", "resource_patch_search_radius"),
    "tile": ("layer", "walking_speed_modifier", "vehicle_friction_modifier", "fluid", "default_cover_tile"),
    "signal": (),
    "setting": ("setting_type", "default_value", "minimum_value", "maximum_value", "allowed_values",
                "forced_value", "allow_blank"),
    "space": ("gravity_pull", "distance", "orientation", "magnitude", "surface_properties", "from", "to",
              "length"),
    "achievement": ("steam_stats_name", "amount", "limited_to_one_game", "to_build", "type_to_build"),
    "quality": ("level", "next", "beacon_power_usage_multiplier", "science_pack_drain_multiplier"),
}
ENTITY_FIELDS = (
    "max_health", "crafting_speed", "crafting_categories", "energy_usage", "module_slots",
    "allowed_effects", "allowed_module_categories", "effect_receiver", "inventory_size", "mining_speed",
    "resource_categories", "resource_searching_radius", "ingredient_count", "speed",
    "emissions_per_second", "supply_area_distance", "maximum_wire_distance", "logistic_mode",
    "logistic_radius", "construction_radius", "filter_count", "production", "consumption",
    "effectivity", "distribution_effectivity", "energy_per_move", "energy_per_tick", "max_energy",
    "buffer_capacity", "power_input", "power_output", "max_power_output", "fluid_usage_per_tick",
    "target_temperature", "pumping_speed", "range", "min_range", "damage_modifier", "rotation_speed",
    "braking_force", "friction_force", "weight", "max_speed", "burner", "energy_source", "minable",
    "collision_box", "selection_box", "tile_width", "tile_height", "placeable_by", "next_upgrade",
    "fast_replaceable_group", "circuit_wire_max_distance", "heating_energy", "surface_conditions",
)
NESTED_KEEP = {
    "energy_source": ("type", "emissions_per_minute", "fuel_categories", "usage_priority",
                      "input_flow_limit", "output_flow_limit", "buffer_capacity", "effectivity"),
    "burner": ("type", "fuel_categories", "effectivity", "emissions_per_minute"),
    "minable": ("mining_time", "result", "results", "count", "required_fluid", "fluid_amount"),
    "effect": ("speed", "productivity", "consumption", "pollution", "quality"),
    "unit": ("count", "count_formula", "time", "ingredients"),
    "effect_receiver": ("base_effect", "uses_module_effects", "uses_beacon_effects"),
}
MEDIA_KEY_PATTERN = re.compile(
    r"picture|animation|sprite|sound|graphic|visuali[sz]ation|shadow|remnant|light|smoke|particle|"
    r"working_visualisations|water_reflection|circuit_connector|draw_|corpse|explosion|trigger"
)


def _load_json(path: Path) -> object | None:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _script_output_dirs() -> list[Path]:
    seen: list[Path] = []
    for directory in (SCRIPT_OUTPUT_DIR, Path("/opt/factorio/script-output"), Path("/factorio/script-output")):
        resolved = directory.resolve() if directory.exists() else directory
        if resolved not in seen:
            seen.append(resolved)
    return seen


def _find_dump() -> tuple[Path, dict[str, object]]:
    candidates: list[Path] = []
    for directory in _script_output_dirs():
        candidates.extend(directory / name for name in ("data.raw.json", "data-raw-dump.json", "data.json"))
    candidates.extend((DATA_DIR / "data.raw.json", DATA_DIR / "data" / "data.raw.json"))
    for directory in _script_output_dirs():
        candidates.extend(path for path in sorted(directory.glob("*.json")) if "locale" not in path.name)
    for path in candidates:
        value = _load_json(path)
        if not isinstance(value, dict):
            continue
        data = value.get("data")
        raw = data.get("raw") if isinstance(data, dict) else None
        if not isinstance(raw, dict):
            raw = value.get("raw") if isinstance(value.get("raw"), dict) else None
        if isinstance(raw, dict):
            return path, raw
        if "recipe" in value and "item" in value:
            return path, value
    raise FileNotFoundError("Factorio JSON data dump was not found")


def _find_settings_dump() -> dict[str, object]:
    for directory in _script_output_dirs():
        value = _load_json(directory / "mod-settings-dump.json")
        if isinstance(value, dict):
            return value
    return {}


def _clean_localized_text(value: str) -> str:
    value = re.sub(r"\[/?font(?:=[^\]]+)?\]", "", value)
    value = re.sub(r"\[/?color(?:=[^\]]+)?\]", "", value)
    value = re.sub(r"\[([^=\]]+)=([^\]]+)\]", r"\2", value)
    return re.sub(r"\s+", " ", value.replace("\\n", " ")).strip()


def _load_locale() -> dict[str, str]:
    """Merge every ``<domain>-locale.json`` export into ``<domain>-name.<key>`` entries."""
    locale: dict[str, str] = {}
    for directory in _script_output_dirs():
        for path in sorted(directory.glob("*locale*.json")):
            document = _load_json(path)
            if not isinstance(document, dict):
                continue
            domain = path.stem.removesuffix("-dump").removesuffix("-locale")
            names = document.get("names")
            descriptions = document.get("descriptions")
            if isinstance(names, dict) or isinstance(descriptions, dict):
                for key, value in (names if isinstance(names, dict) else {}).items():
                    if isinstance(value, str):
                        locale.setdefault(f"{domain}-name.{key}", _clean_localized_text(value))
                for key, value in (descriptions if isinstance(descriptions, dict) else {}).items():
                    if isinstance(value, str):
                        locale.setdefault(f"{domain}-description.{key}", _clean_localized_text(value))
                continue
            # Legacy single-file export already keyed by locale section.
            for section, entries in document.items():
                if isinstance(entries, dict):
                    for key, value in entries.items():
                        if isinstance(value, str):
                            locale.setdefault(f"{section}.{key}", _clean_localized_text(value))
    return locale


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _normal(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _text(value).lower()).strip("-")


def _humanize(name: str) -> str:
    return re.sub(r"[-_]+", " ", name).strip().capitalize()


def _is_junk(value: str) -> bool:
    return not value or bool(JUNK_LOCALE.match(value.strip()))


def _explicit_localized(value: object, locale: dict[str, str]) -> str:
    if isinstance(value, str) and value:
        return _clean_localized_text(value)
    if isinstance(value, list) and value:
        key = value[0]
        if isinstance(key, str) and key and isinstance(locale.get(key), str) and locale[key]:
            return locale[key]
        if len(value) > 1 and isinstance(value[1], str):
            return _clean_localized_text(value[1])
    return ""


def _localized(prototype: dict[str, object], name: str, kind: str, suffix: str, locale: dict[str, str]) -> str:
    explicit = _explicit_localized(
        prototype.get("localised_name" if suffix == "name" else "localised_description"), locale
    )
    if explicit and not _is_junk(explicit):
        return explicit
    for domain in tuple(KIND_LOCALE_DOMAINS.get(kind, ())) + LOCALE_DOMAIN_ORDER:
        translated = locale.get(f"{domain}-{suffix}.{name}")
        if translated and not _is_junk(translated):
            return translated
    return ""


def _ref_name(value: object) -> str:
    if isinstance(value, str):
        return value
    return _text(value.get("name")) if isinstance(value, dict) else ""


def _ingredient(value: object) -> dict[str, object] | None:
    if isinstance(value, str):
        return {"name": value, "type": "item", "amount": 1}
    if not isinstance(value, dict):
        return None
    name = _text(value.get("name"))
    if not name:
        return None
    entry: dict[str, object] = {"name": name, "type": _text(value.get("type")) or "item"}
    for key in ("amount", "amount_min", "amount_max", "probability", "temperature", "ignored_by_stats"):
        if value.get(key) is not None:
            entry[key] = value[key]
    return entry


def _ref_list(value: object) -> list[dict[str, object]]:
    if isinstance(value, dict):
        value = list(value.values())
    if not isinstance(value, list):
        return []
    return [entry for entry in (_ingredient(item) for item in value) if entry]


def _semantic_kind(prototype_type: str, prototype: dict[str, object]) -> str:
    if prototype_type in EXPLICIT_KINDS:
        return EXPLICIT_KINDS[prototype_type]
    if prototype_type in ACHIEVEMENT_TYPES:
        return "achievement"
    if prototype_type.endswith("-equipment"):
        return "equipment"
    if prototype_type in VEHICLE_TYPES:
        return "vehicle"
    if prototype_type == "module":
        return "module"
    if prototype_type in WEAPON_ITEM_TYPES:
        return "weapon"
    if prototype_type in ITEM_TYPES or prototype.get("stack_size") is not None:
        return "item"
    if prototype.get("max_health") is not None or prototype.get("collision_box") is not None:
        return "entity"
    return ""


def _is_media_key(key: object) -> bool:
    return bool(MEDIA_KEY_PATTERN.search(str(key)))


def _prune(value: object, depth: int = 0) -> object:
    if depth > 3:
        return None
    if isinstance(value, dict):
        pruned = {key: _prune(item, depth + 1) for key, item in value.items() if not _is_media_key(key)}
        return {key: item for key, item in pruned.items() if item not in (None, {}, [])}
    if isinstance(value, list):
        return [item for item in (_prune(item, depth + 1) for item in value[:24]) if item not in (None, {}, [])]
    return value


def _project(prototype: dict[str, object], kind: str) -> dict[str, object]:
    fields = list(COMMON_FIELDS) + list(KIND_FIELDS.get(kind, ()))
    if kind in {"entity", "vehicle", "resource", "tile", "item", "module", "weapon", "equipment"}:
        fields += list(ENTITY_FIELDS)
    record: dict[str, object] = {}
    for field in fields:
        if field not in prototype or field in record:
            continue
        value = prototype[field]
        if value in (None, "", [], {}):
            continue
        keep = NESTED_KEEP.get(field)
        if keep and isinstance(value, dict):
            value = {key: value[key] for key in keep if key in value}
        else:
            value = _prune(value)
        if value in (None, "", [], {}):
            continue
        record[field] = value
    return record


def _reference_metadata() -> dict[str, object]:
    version = "2.0.77"
    try:
        version = (REFERENCE_DIR / "version.txt").read_text(encoding="utf-8").strip() or version
    except OSError:
        pass
    modules: list[dict[str, object]] = []
    if (REFERENCE_DIR / "modules").is_dir():
        for path in sorted((REFERENCE_DIR / "modules").glob("*.info.json")):
            value = _load_json(path)
            if isinstance(value, dict):
                modules.append({"name": path.name.removesuffix(".info.json"), **value})
    return {
        "factorio_version": version,
        "factorio_data_ref": version,
        "data_source": "Factorio runtime dump, with release metadata from wube/factorio-data",
        "data_source_url": f"https://github.com/wube/factorio-data/tree/{version}",
        "changelog_url": f"https://github.com/wube/factorio-data/blob/{version}/changelog.txt",
        "changelog_available": (REFERENCE_DIR / "changelog.txt").is_file(),
        "credits_available": (REFERENCE_DIR / "credits.txt").is_file(),
        "modules": modules,
    }


def _group_maps(raw: dict[str, object], locale: dict[str, str]) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    subgroup_to_group: dict[str, str] = {}
    labels: dict[str, dict[str, str]] = {"group": {}, "subgroup": {}}
    for name in (raw.get("item-group") or {}):
        labels["group"][name] = locale.get(f"item-group-name.{name}") or _humanize(name)
    for name, prototype in (raw.get("item-subgroup") or {}).items():
        if isinstance(prototype, dict):
            subgroup_to_group[name] = _text(prototype.get("group"))
            labels["subgroup"][name] = _humanize(name)
    return subgroup_to_group, labels


def _link_recipes(records: list[dict[str, object]], by_name: dict[tuple[str, str], dict[str, object]]) -> None:
    """Add FNEI-style reverse indexes so "what makes X" and "what uses X" are single lookups."""
    for recipe in (entry for entry in records if entry["kind"] == "recipe"):
        reference = {"name": recipe["name"], "type": "recipe", "localized_name": recipe["localized_name"]}
        for field, target in (("ingredients", "used_in"), ("results", "made_in")):
            for entry in recipe.get(field, []) or []:
                name = _ref_name(entry)
                item = (by_name.get(("item", name)) or by_name.get(("fluid", name))
                        or by_name.get(("module", name)) or by_name.get(("weapon", name)))
                if item is not None and len(item.setdefault(target, [])) < 64:
                    item[target].append(dict(reference))


def _link_technologies(records: list[dict[str, object]], by_name: dict[tuple[str, str], dict[str, object]]) -> None:
    for technology in (entry for entry in records if entry["kind"] == "technology"):
        reference = {"name": technology["name"], "type": "technology",
                     "localized_name": technology["localized_name"]}
        for effect in technology.get("effects", []) or []:
            if isinstance(effect, dict) and effect.get("type") == "unlock-recipe":
                recipe = by_name.get(("recipe", _text(effect.get("recipe"))))
                if recipe is not None:
                    recipe.setdefault("unlocked_by", []).append(dict(reference))
        for prerequisite in technology.get("prerequisites", []) or []:
            parent = by_name.get(("technology", _ref_name(prerequisite)))
            if parent is not None and len(parent.setdefault("leads_to", [])) < 64:
                parent["leads_to"].append(dict(reference))


def _link_crafting_machines(records: list[dict[str, object]]) -> None:
    """Map each recipe category to the machines that can run it."""
    machines: dict[str, list[dict[str, object]]] = {}
    for record in records:
        categories = record.get("crafting_categories")
        if not isinstance(categories, list):
            continue
        reference = {"name": record["name"], "type": "entity", "localized_name": record["localized_name"],
                     "crafting_speed": record.get("crafting_speed", 1)}
        for category in categories:
            machines.setdefault(_text(category), []).append(reference)
    for recipe in (entry for entry in records if entry["kind"] == "recipe"):
        crafted_in = machines.get(_text(recipe.get("category")) or "crafting", [])
        if crafted_in:
            recipe["crafted_in"] = [dict(reference) for reference in crafted_in[:24]]


def _inherit_entity_groups(
    records: list[dict[str, object]],
    by_name: dict[tuple[str, str], dict[str, object]],
    subgroup_to_group: dict[str, str],
) -> None:
    """Entities carry no item group, so borrow the group of the item that places them."""
    for record in records:
        place_result = _text(record.get("place_result"))
        subgroup = _text(record.get("subgroup"))
        if not place_result or not subgroup:
            continue
        for kind in ("entity", "vehicle", "resource"):
            entity = by_name.get((kind, place_result))
            if entity is not None and not entity.get("subgroup"):
                entity["subgroup"] = subgroup
                entity["group"] = subgroup_to_group.get(subgroup, "")
                entity["placed_by"] = record["name"]


def _main_product(record: dict[str, object]) -> str:
    declared = _text(record.get("main_product"))
    if declared:
        return declared
    results = record.get("results") or []
    return _ref_name(results[0]) if len(results) == 1 else ""


def _related(record: dict[str, object], by_name: dict[tuple[str, str], dict[str, object]]) -> dict[str, object] | None:
    """Find the prototype a record borrows its wording from: recipe -> product, item -> placed entity."""
    if record["kind"] == "recipe":
        product = _main_product(record)
        for kind in ("item", "fluid", "module", "weapon", "equipment", "entity"):
            related = by_name.get((kind, product))
            if related is not None:
                return related
        return None
    place_result = _text(record.get("place_result"))
    if place_result:
        for kind in ("entity", "vehicle", "resource"):
            related = by_name.get((kind, place_result))
            if related is not None:
                return related
    placed_by = _text(record.get("placed_by"))
    return by_name.get(("item", placed_by)) if placed_by else None


def _inherit_localization(records: list[dict[str, object]], by_name: dict[tuple[str, str], dict[str, object]]) -> None:
    """Borrow wording from the related prototype when a mod leaves a name or description blank."""
    fallbacks = {id(record) for record in records if record.get("_name_fallback")}
    for record in records:
        related = _related(record, by_name)
        if related is None:
            continue
        if id(record) in fallbacks and id(related) not in fallbacks:
            record["localized_name"] = related["localized_name"]
        if not record.get("localized_description") and related.get("localized_description"):
            record["localized_description"] = related["localized_description"]
    for record in records:
        record.pop("_name_fallback", None)


def build_catalog(
    raw: dict[str, object],
    source: Path,
    settings: dict[str, object] | None = None,
    locale: dict[str, str] | None = None,
) -> dict[str, object]:
    locale = locale or {}
    subgroup_to_group, group_labels = _group_maps(raw, locale)
    records: list[dict[str, object]] = []
    by_name: dict[tuple[str, str], dict[str, object]] = {}

    groups: list[tuple[str, dict[str, object], str]] = [
        (prototype_type, prototypes, "")
        for prototype_type, prototypes in raw.items()
        if isinstance(prototypes, dict) and prototype_type not in PRESENTATION_TYPES
    ]
    groups.extend(
        (prototype_type, prototypes, "setting")
        for prototype_type, prototypes in (settings or {}).items()
        if isinstance(prototypes, dict)
    )

    for prototype_type, prototypes, forced_kind in groups:
        for name, prototype in prototypes.items():
            if not isinstance(prototype, dict) or not isinstance(name, str):
                continue
            kind = forced_kind or _semantic_kind(prototype_type, prototype)
            if not kind:
                continue
            subgroup = _text(prototype.get("subgroup"))
            resolved = _localized(prototype, name, kind, "name", locale)
            record: dict[str, object] = {
                "name": name,
                "kind": kind,
                "type": _text(prototype.get("type")) or prototype_type,
                "prototype_type": prototype_type,
                "localized_name": resolved or _humanize(name),
                "group": subgroup_to_group.get(subgroup, ""),
                "subgroup": subgroup,
            }
            if not resolved:
                record["_name_fallback"] = True
            description = _localized(prototype, name, kind, "description", locale)
            if description:
                record["localized_description"] = description
            record.update(_project(prototype, kind))
            if kind == "recipe":
                record["ingredients"] = _ref_list(prototype.get("ingredients"))
                record["results"] = _ref_list(prototype.get("results", prototype.get("result")))
            if kind == "technology":
                prerequisites = prototype.get("prerequisites")
                record["prerequisites"] = prerequisites if isinstance(prerequisites, list) else []
                effects = prototype.get("effects")
                record["effects"] = effects if isinstance(effects, list) else []
            records.append(record)
            by_name.setdefault((kind, name), record)

    _link_recipes(records, by_name)
    _link_technologies(records, by_name)
    _link_crafting_machines(records)
    _inherit_entity_groups(records, by_name, subgroup_to_group)
    _inherit_localization(records, by_name)

    kinds: dict[str, int] = {}
    for record in records:
        kinds[str(record["kind"])] = kinds.get(str(record["kind"]), 0) + 1

    records.sort(key=lambda entry: (entry["kind"], _normal(entry.get("localized_name")), entry["name"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "source": str(source),
        "record_count": len(records),
        "kinds": kinds,
        "group_labels": group_labels,
        "records": records,
        **_reference_metadata(),
    }


def main() -> int:
    source, raw = _find_dump()
    catalog = build_catalog(raw, source, _find_settings_dump(), _load_locale())
    mod_fingerprint = os.environ.get("FACTORIO_CATALOG_MOD_FINGERPRINT", "").strip()
    if mod_fingerprint:
        catalog["mod_fingerprint"] = mod_fingerprint
    path = catalog_db.write_catalog(catalog)
    summary = ", ".join(f"{kind} {count}" for kind, count in sorted(catalog["kinds"].items()))
    print(f"Built catalog with {catalog['record_count']} records at {path} ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
