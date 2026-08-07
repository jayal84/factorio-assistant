#!/usr/bin/env python3
"""Build a searchable index from Factorio's JSON data dump."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path


DATA_DIR = Path(os.environ.get("FACTORIO_DATA_DIR", "/share/factorio"))
SCRIPT_OUTPUT_DIR = DATA_DIR / "script-output"
CATALOG_PATH = Path(os.environ.get("FACTORIO_CATALOG_DIR", "/tmp/factorio-assistant")) / "catalog.json"
REFERENCE_DIR = Path("/app/factorio-reference")


def _load_json(path: Path) -> object | None:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _find_dump() -> tuple[Path, dict[str, object]]:
    candidates = [
        SCRIPT_OUTPUT_DIR / "data.raw.json",
        SCRIPT_OUTPUT_DIR / "data-raw-dump.json",
        SCRIPT_OUTPUT_DIR / "data.json",
        DATA_DIR / "data.raw.json",
        DATA_DIR / "data" / "data.raw.json",
    ]
    for output_dir in (Path("/opt/factorio/script-output"), Path("/factorio/script-output")):
        candidates.extend(output_dir.glob("*.json"))
    candidates.extend(path for path in SCRIPT_OUTPUT_DIR.glob("*.json") if path not in candidates)
    for path in candidates:
        value = _load_json(path)
        if isinstance(value, dict):
            raw = value.get("data", {}).get("raw") if isinstance(value.get("data"), dict) else None
            if isinstance(raw, dict):
                return path, raw
            raw = value.get("raw")
            if isinstance(raw, dict):
                return path, raw
            if any(isinstance(item, dict) for item in value.values()):
                return path, value
    raise FileNotFoundError("Factorio JSON data dump was not found")


def _find_settings_dump() -> dict[str, object]:
    candidates = [SCRIPT_OUTPUT_DIR / "mod-settings-dump.json"]
    for output_dir in (Path("/opt/factorio/script-output"), Path("/factorio/script-output")):
        candidates.append(output_dir / "mod-settings-dump.json")
    for path in candidates:
        value = _load_json(path)
        if isinstance(value, dict):
            return value
    return {}


def _find_locale_dump() -> dict[str, object]:
    candidates = [
        SCRIPT_OUTPUT_DIR / "prototype-locale.json",
        SCRIPT_OUTPUT_DIR / "prototype-locale-dump.json",
        SCRIPT_OUTPUT_DIR / "locale.json",
    ]
    for output_dir in (Path("/opt/factorio/script-output"), Path("/factorio/script-output")):
        candidates.extend(output_dir.glob("*locale*.json"))
    for path in candidates:
        value = _load_json(path)
        if isinstance(value, dict):
            return value
    return {}


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _normal(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _text(value).lower()).strip("-")


def _clean_localized_text(value: str) -> str:
    value = re.sub(r"\[/?font(?:=[^\]]+)?\]", "", value)
    value = re.sub(r"\[/?color(?:=[^\]]+)?\]", "", value)
    return re.sub(r"\[([^=\]]+)=([^\]]+)\]", r"\2", value)


def _flatten_locale(value: object, prefix: str = "", result: dict[str, str] | None = None) -> dict[str, str]:
    if result is None:
        result = {}
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            _flatten_locale(child, path, result)
    elif isinstance(value, str):
        result.setdefault(prefix, _clean_localized_text(value))
        parts = prefix.split(".")
        for start in range(1, len(parts)):
            result.setdefault(".".join(parts[start:]), _clean_localized_text(value))
    return result


def _localized_value(prototype: dict[str, object], field: str, name: str, locale: dict[str, object]) -> str:
    value = prototype.get(field)
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        key = value[0]
        if isinstance(key, str):
            for candidate in (key, f"{key}.{name}"):
                translated = locale.get(candidate)
                if isinstance(translated, str):
                    return translated
            if isinstance(locale.get(key), dict):
                translated = locale[key].get(name)
                if isinstance(translated, str):
                    return translated
        if len(value) > 1:
            return _clean_localized_text(_text(value[1]))
    return ""


def _localized_name(prototype: dict[str, object], name: str, locale: dict[str, object] | None = None) -> str:
    locale = locale or {}
    translated = _localized_value(prototype, "localised_name", name, locale)
    if translated:
        return translated
    for domain in ("item-name", "resource-name", "entity-name", "fluid-name"):
        translated = locale.get(f"{domain}.{name}")
        if not isinstance(translated, str) and isinstance(locale.get(domain), dict):
            translated = locale[domain].get(name)
        if isinstance(translated, str) and translated.strip():
            return _clean_localized_text(translated)
    value = prototype.get("localised_name") or prototype.get("localized_name")
    if isinstance(value, list) and len(value) > 1:
        return _clean_localized_text(_text(value[1]))
    if isinstance(value, str):
        return _clean_localized_text(value)
    return name.replace("-", " ").title()


def _ref(value: object) -> dict[str, object] | str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        name = value.get("name") or value.get("type")
        return {key: value[key] for key in ("name", "type", "amount", "amount_min", "amount_max", "probability") if key in value} if name else value
    return value


def _reference_metadata() -> dict[str, object]:
    version = "2.0.77"
    try:
        version = (REFERENCE_DIR / "version.txt").read_text(encoding="utf-8").strip() or version
    except OSError:
        pass
    modules: list[dict[str, object]] = []
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


def build_catalog(raw: dict[str, object], source: Path, settings: dict[str, object] | None = None, locale: dict[str, object] | None = None) -> dict[str, object]:
    records: list[dict[str, object]] = []
    by_name: dict[tuple[str, str], dict[str, object]] = {}
    locale = _flatten_locale(locale or {})
    groups = [(prototype_type, prototypes, prototype_type) for prototype_type, prototypes in raw.items()]
    groups.extend((prototype_type, prototypes, "setting") for prototype_type, prototypes in (settings or {}).items())
    for prototype_type, prototypes, kind in groups:
        if not isinstance(prototypes, dict):
            continue
        for name, prototype in prototypes.items():
            if not isinstance(prototype, dict) or not isinstance(name, str):
                continue
            record = dict(prototype)
            record.update({
                "name": name,
                "kind": kind,
                "type": prototype.get("type", prototype_type),
                "prototype_type": prototype_type,
                "localized_name": _localized_name(prototype, name, locale),
            })
            description = _localized_value(prototype, "localised_description", name, locale or {})
            if description:
                record["localized_description"] = description
            if kind == "recipe":
                record["ingredients"] = [_ref(value) for value in prototype.get("ingredients", [])] if isinstance(prototype.get("ingredients"), list) else []
                record["results"] = [_ref(value) for value in prototype.get("results", prototype.get("result", []))] if isinstance(prototype.get("results", prototype.get("result", [])), list) else []
            if kind == "technology":
                record["prerequisites"] = prototype.get("prerequisites", [])
                effects = prototype.get("effects", [])
                record["effects"] = effects if isinstance(effects, list) else []
            records.append(record)
            by_name[(kind, name)] = record

    for recipe in [entry for entry in records if entry["kind"] == "recipe"]:
        recipe_reference = {
            "name": recipe["name"],
            "type": "recipe",
            "localized_name": recipe.get("localized_name", recipe["name"]),
        }
        for ingredient in recipe.get("ingredients", []):
            name = ingredient.get("name") if isinstance(ingredient, dict) else ingredient
            item = by_name.get(("item", name)) or by_name.get(("fluid", name))
            if item is not None:
                item.setdefault("used_in", []).append(dict(recipe_reference))
        for result in recipe.get("results", []):
            name = result.get("name") if isinstance(result, dict) else result
            item = by_name.get(("item", name)) or by_name.get(("fluid", name))
            if item is not None:
                item.setdefault("made_in", []).append(dict(recipe_reference))

    records.sort(key=lambda entry: (_normal(entry.get("localized_name")), entry["name"]))
    return {
        "schema_version": 1,
        "source": str(source),
        "record_count": len(records),
        "records": records,
        **_reference_metadata(),
    }


def main() -> int:
    source, raw = _find_dump()
    catalog = build_catalog(raw, source, _find_settings_dump(), _find_locale_dump())
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=CATALOG_PATH.parent, delete=False) as handle:
        json.dump(catalog, handle, ensure_ascii=True, separators=(",", ":"))
        handle.write("\n")
        temporary_path = Path(handle.name)
    temporary_path.replace(CATALOG_PATH)
    print(f"Built catalog with {catalog['record_count']} records at {CATALOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
