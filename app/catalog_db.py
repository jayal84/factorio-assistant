#!/usr/bin/env python3
"""SQLite storage and query layer for the Factorio prototype catalog."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from collections import defaultdict
from pathlib import Path

CATALOG_DIR = Path(os.environ.get("FACTORIO_CATALOG_DIR", "/tmp/factorio-assistant"))
CATALOG_PATH = CATALOG_DIR / "catalog.sqlite"
SCHEMA_VERSION_FALLBACK = 2

# Ordered by how likely a bare search term refers to that kind.
KIND_PRIORITY = {
    "item": 0, "fluid": 1, "entity": 2, "recipe": 3, "technology": 4, "module": 5, "equipment": 6,
    "vehicle": 7, "weapon": 8, "resource": 9, "tile": 10, "signal": 11, "space": 12, "quality": 13,
    "achievement": 14, "setting": 15,
}
KIND_LABELS = {
    "item": "Items", "fluid": "Fluids", "recipe": "Recipes", "technology": "Technologies",
    "entity": "Buildings & machines", "module": "Modules", "equipment": "Equipment",
    "vehicle": "Vehicles", "weapon": "Weapons", "resource": "Resources", "tile": "Tiles",
    "signal": "Circuit signals", "space": "Space", "quality": "Quality", "achievement": "Achievements",
    "setting": "Mod settings",
}
# Fields returned when the caller does not ask for the full prototype.
SUMMARY_FIELDS = (
    "name", "kind", "type", "prototype_type", "localized_name", "localized_description", "group",
    "subgroup", "icon", "icons", "stack_size", "category", "energy_required", "ingredients", "results",
    "crafted_in", "made_in", "used_in", "unlocked_by", "prerequisites", "effects", "crafting_speed",
    "crafting_categories", "energy_usage", "module_slots", "max_health", "place_result", "placed_by",
    "fuel_value", "fuel_category", "default_temperature", "setting_type", "default_value",
)

SCHEMA = """
PRAGMA journal_mode = OFF;
PRAGMA synchronous = OFF;

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE records (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    type TEXT,
    prototype_type TEXT,
    localized_name TEXT,
    localized_description TEXT,
    grouping TEXT,
    subgroup TEXT,
    sort_order TEXT,
    hidden INTEGER NOT NULL DEFAULT 0,
    doc TEXT NOT NULL
);
CREATE UNIQUE INDEX records_key ON records (kind, name);
CREATE INDEX records_name ON records (name);
CREATE INDEX records_browse ON records (kind, grouping, subgroup, sort_order);

CREATE VIRTUAL TABLE records_fts USING fts5 (
    name, localized_name, description, aliases,
    content='', prefix='2 3 4'
);

CREATE TABLE recipe_io (
    recipe TEXT NOT NULL,
    item TEXT NOT NULL,
    item_type TEXT NOT NULL,
    role TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    probability REAL NOT NULL DEFAULT 1
);
CREATE INDEX recipe_io_item ON recipe_io (item, role);
CREATE INDEX recipe_io_recipe ON recipe_io (recipe);

CREATE TABLE machines (
    category TEXT NOT NULL,
    entity TEXT NOT NULL,
    crafting_speed REAL NOT NULL DEFAULT 1,
    module_slots INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX machines_category ON machines (category);

CREATE TABLE tech_unlocks (technology TEXT NOT NULL, recipe TEXT NOT NULL);
CREATE INDEX tech_unlocks_recipe ON tech_unlocks (recipe);
CREATE INDEX tech_unlocks_technology ON tech_unlocks (technology);
"""

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _tokens(value: str) -> list[str]:
    return _TOKEN_PATTERN.findall(value.lower())


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _ref_names(record: dict[str, object], field: str) -> list[str]:
    values = record.get(field)
    if not isinstance(values, list):
        return []
    names = []
    for entry in values:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, dict) and entry.get("name"):
            names.append(str(entry["name"]))
    return names


def write_catalog(document: dict[str, object], path: Path = CATALOG_PATH) -> Path:
    """Write the built catalog to a fresh SQLite database, swapped in atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".sqlite.tmp")
    temporary_path.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary_path)
    try:
        connection.executescript(SCHEMA)
        records = [record for record in document.get("records", []) if isinstance(record, dict)]
        connection.executemany(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            [(key, json.dumps(value)) for key, value in document.items() if key != "records"],
        )
        rows = []
        fts_rows = []
        for index, record in enumerate(records, start=1):
            aliases = " ".join(
                _ref_names(record, "ingredients") + _ref_names(record, "results")
                + [str(record.get("prototype_type", "")), str(record.get("subgroup", ""))]
            )
            rows.append((
                index, record.get("name"), record.get("kind"), record.get("type"),
                record.get("prototype_type"), record.get("localized_name"),
                record.get("localized_description"), record.get("group"), record.get("subgroup"),
                record.get("order"), 1 if record.get("hidden") else 0,
                json.dumps(record, ensure_ascii=False, separators=(",", ":")),
            ))
            fts_rows.append((
                index, str(record.get("name", "")).replace("-", " "),
                record.get("localized_name") or "", record.get("localized_description") or "",
                aliases.replace("-", " "),
            ))
        connection.executemany(
            "INSERT INTO records (id, name, kind, type, prototype_type, localized_name,"
            " localized_description, grouping, subgroup, sort_order, hidden, doc)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.executemany(
            "INSERT INTO records_fts (rowid, name, localized_name, description, aliases)"
            " VALUES (?, ?, ?, ?, ?)",
            fts_rows,
        )
        connection.execute(
            "INSERT INTO records_fts (records_fts, rank) VALUES ('rank', 'bm25(8.0, 10.0, 1.0, 2.0)')"
        )
        _write_relations(connection, records)
        connection.commit()
        connection.execute("VACUUM")
        connection.commit()
    finally:
        connection.close()
    temporary_path.replace(path)
    return path


def _write_relations(connection: sqlite3.Connection, records: list[dict[str, object]]) -> None:
    recipe_io: list[tuple[str, str, str, float, float]] = []
    machines: list[tuple[str, str, float, int]] = []
    unlocks: list[tuple[str, str]] = []
    for record in records:
        kind = record.get("kind")
        name = str(record.get("name", ""))
        if kind == "recipe":
            for role, field in (("ingredient", "ingredients"), ("result", "results")):
                for entry in record.get(field, []) or []:
                    if not isinstance(entry, dict) or not entry.get("name"):
                        continue
                    amount = _number(entry.get("amount"))
                    if not amount:
                        amount = (_number(entry.get("amount_min")) + _number(entry.get("amount_max"))) / 2
                    recipe_io.append((
                        name, str(entry["name"]), str(entry.get("type") or "item"), role,
                        amount, _number(entry.get("probability"), 1.0),
                    ))
        categories = record.get("crafting_categories")
        if isinstance(categories, list):
            for category in categories:
                machines.append((
                    str(category), name, _number(record.get("crafting_speed"), 1.0),
                    int(_number(record.get("module_slots"))),
                ))
        if kind == "technology":
            for effect in record.get("effects", []) or []:
                if isinstance(effect, dict) and effect.get("type") == "unlock-recipe" and effect.get("recipe"):
                    unlocks.append((name, str(effect["recipe"])))
    connection.executemany("INSERT INTO recipe_io VALUES (?, ?, ?, ?, ?, ?)", recipe_io)
    connection.executemany("INSERT INTO machines VALUES (?, ?, ?, ?)", machines)
    connection.executemany("INSERT INTO tech_unlocks VALUES (?, ?)", unlocks)


class Catalog:
    """Read-only catalog access with one connection per thread."""

    def __init__(self, path: Path = CATALOG_PATH) -> None:
        self.path = path
        self._local = threading.local()

    @property
    def available(self) -> bool:
        return self.path.is_file()

    def _connect(self) -> sqlite3.Connection:
        stamp = self.path.stat().st_mtime_ns
        connection = getattr(self._local, "connection", None)
        if connection is not None and getattr(self._local, "stamp", None) == stamp:
            return connection
        if connection is not None:
            connection.close()
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA cache_size = -32000")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.execute("PRAGMA mmap_size = 268435456")
        self._local.connection = connection
        self._local.stamp = stamp
        return connection

    def metadata(self) -> dict[str, object]:
        if not self.available:
            raise FileNotFoundError("Catalog is not available yet.")
        rows = self._connect().execute("SELECT key, value FROM meta").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def entry(self, name: str, kind: str = "") -> dict[str, object] | None:
        if not self.available or not name:
            return None
        if kind:
            row = self._connect().execute(
                "SELECT doc FROM records WHERE kind = ? AND name = ?", (kind, name)
            ).fetchone()
        else:
            row = self._connect().execute(
                "SELECT doc FROM records WHERE name = ? ORDER BY CASE kind"
                " WHEN 'item' THEN 0 WHEN 'fluid' THEN 1 WHEN 'entity' THEN 2 ELSE 3 END LIMIT 1",
                (name,),
            ).fetchone()
        return json.loads(row["doc"]) if row else None

    def localized_name(self, name: str, kind: str = "") -> str:
        record = self.entry(name, kind)
        return str(record.get("localized_name") or name) if record else name

    def search(
        self,
        query: str = "",
        kind: str = "",
        group: str = "",
        subgroup: str = "",
        limit: int = 25,
        offset: int = 0,
        include_hidden: bool = False,
    ) -> tuple[int, list[dict[str, object]]]:
        if not self.available:
            raise FileNotFoundError("Catalog is not available yet.")
        connection = self._connect()
        filters = []
        parameters: list[object] = []
        if kind and kind != "all":
            filters.append("r.kind = ?")
            parameters.append(kind)
        else:
            filters.append("r.kind != 'setting'")
        if group:
            filters.append("r.grouping = ?")
            parameters.append(group)
        if subgroup:
            filters.append("r.subgroup = ?")
            parameters.append(subgroup)
        if not include_hidden:
            filters.append("r.hidden = 0")
        where = " AND ".join(filters)

        tokens = _tokens(query)
        if not tokens:
            total = connection.execute(f"SELECT COUNT(*) FROM records r WHERE {where}", parameters).fetchone()[0]
            rows = connection.execute(
                f"SELECT r.doc FROM records r WHERE {where}"
                " ORDER BY r.grouping, r.subgroup, r.sort_order, r.localized_name LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
            return total, [json.loads(row["doc"]) for row in rows]

        # Only the trailing token is prefix-matched; prefix-expanding every token is far slower.
        terms = [f'"{token}"' for token in tokens[:-1]] + [f'"{tokens[-1]}"*']
        rows = self._match(connection, " AND ".join(terms), where, parameters)
        relaxed = False
        if not rows and len(tokens) > 1:
            rows = self._match(connection, " OR ".join(f'"{token}"*' for token in tokens), where, parameters)
            relaxed = True
        scored = sorted(
            rows,
            key=lambda row: (
                -_relevance(row, query, tokens),
                KIND_PRIORITY.get(row["kind"], 99),
                len(row["name"]),
                row["name"],
            ),
        )
        page = scored[offset:offset + (5 if relaxed else limit)]
        return len(scored), self._documents([row["id"] for row in page])

    @staticmethod
    def _match(connection: sqlite3.Connection, match: str, where: str, parameters: list[object]) -> list[sqlite3.Row]:
        """Rank on narrow columns only; reading `doc` here would load megabytes per query."""
        try:
            return connection.execute(
                "SELECT r.id, r.name, r.kind, r.localized_name, records_fts.rank AS rank"
                " FROM records_fts JOIN records r ON r.id = records_fts.rowid"
                f" WHERE records_fts MATCH ? AND {where} ORDER BY records_fts.rank LIMIT 300",
                [match, *parameters],
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    def _documents(self, identifiers: list[int]) -> list[dict[str, object]]:
        if not identifiers:
            return []
        placeholders = ",".join("?" * len(identifiers))
        rows = self._connect().execute(
            f"SELECT id, doc FROM records WHERE id IN ({placeholders})", identifiers
        ).fetchall()
        documents = {row["id"]: row["doc"] for row in rows}
        return [json.loads(documents[identifier]) for identifier in identifiers if identifier in documents]

    def facets(self, kind: str = "") -> list[dict[str, object]]:
        if not self.available:
            raise FileNotFoundError("Catalog is not available yet.")
        labels = self.metadata().get("group_labels", {}) or {}
        group_labels = labels.get("group", {}) if isinstance(labels, dict) else {}
        subgroup_labels = labels.get("subgroup", {}) if isinstance(labels, dict) else {}
        parameters: list[object] = []
        where = "hidden = 0 AND grouping != ''"
        if kind and kind != "all":
            where += " AND kind = ?"
            parameters.append(kind)
        else:
            where += " AND kind != 'setting'"
        rows = self._connect().execute(
            f"SELECT grouping, subgroup, COUNT(*) AS count FROM records WHERE {where}"
            " GROUP BY grouping, subgroup ORDER BY grouping, subgroup",
            parameters,
        ).fetchall()
        facets: dict[str, dict[str, object]] = {}
        for row in rows:
            facet = facets.setdefault(row["grouping"], {
                "id": row["grouping"],
                "label": group_labels.get(row["grouping"], row["grouping"]),
                "count": 0,
                "subcategories": [],
            })
            facet["count"] = int(facet["count"]) + row["count"]
            facet["subcategories"].append({
                "id": row["subgroup"],
                "label": subgroup_labels.get(row["subgroup"], row["subgroup"]),
                "count": row["count"],
            })
        return sorted(facets.values(), key=lambda facet: str(facet["label"]))

    def recipes_producing(self, item: str) -> list[str]:
        rows = self._connect().execute(
            "SELECT DISTINCT recipe FROM recipe_io WHERE item = ? AND role = 'result'", (item,)
        ).fetchall()
        return [row["recipe"] for row in rows]

    def recipes_consuming(self, item: str) -> list[str]:
        rows = self._connect().execute(
            "SELECT DISTINCT recipe FROM recipe_io WHERE item = ? AND role = 'ingredient'", (item,)
        ).fetchall()
        return [row["recipe"] for row in rows]

    def recipe_io(self, recipes: list[str]) -> dict[str, list[sqlite3.Row]]:
        if not recipes:
            return {}
        placeholders = ",".join("?" * len(recipes))
        rows = self._connect().execute(
            f"SELECT recipe, item, item_type, role, amount, probability FROM recipe_io"
            f" WHERE recipe IN ({placeholders})",
            recipes,
        ).fetchall()
        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(row["recipe"], []).append(row)
        return grouped

    def machines_for(self, category: str) -> list[sqlite3.Row]:
        return self._connect().execute(
            "SELECT entity, crafting_speed, module_slots FROM machines WHERE category = ?"
            " ORDER BY crafting_speed DESC",
            (category,),
        ).fetchall()

    def recipes_unlocked_by(self, technologies: list[str]) -> set[str]:
        if not technologies:
            return set()
        placeholders = ",".join("?" * len(technologies))
        rows = self._connect().execute(
            f"SELECT DISTINCT recipe FROM tech_unlocks WHERE technology IN ({placeholders})", technologies
        ).fetchall()
        return {row["recipe"] for row in rows}

    def suggestions(self, query: str, limit: int = 5) -> list[str]:
        tokens = _tokens(query)
        if not tokens:
            return []
        rows = self._connect().execute(
            "SELECT r.localized_name FROM records_fts JOIN records r ON r.id = records_fts.rowid"
            " WHERE records_fts MATCH ? AND r.hidden = 0 ORDER BY records_fts.rank LIMIT 60",
            [" OR ".join(f'"{token}"*' for token in tokens)],
        ).fetchall()
        unique: list[str] = []
        for row in rows:
            if row["localized_name"] not in unique:
                unique.append(row["localized_name"])
            if len(unique) >= limit:
                break
        return unique

    def production_plan(
        self,
        targets: list[dict[str, object]],
        known_recipes: set[str] | None = None,
        max_depth: int = 8,
    ) -> dict[str, object]:
        """Build a surplus-aware FactoryPlanner-style production tree."""
        if not targets:
            return {"items": [], "recipes": [], "raw_inputs": [], "alternatives": []}
        known_recipes = known_recipes or set()
        state: dict[str, object] = {
            "known_recipes": known_recipes,
            "surplus": defaultdict(float),
            "raw_inputs": {},
            "recipes": {},
            "alternatives": {},
        }
        items: list[dict[str, object]] = []
        for target in targets:
            name = str(target.get("name") or "").strip()
            if not name:
                continue
            rate = _number(target.get("rate"), _number(target.get("amount"), 1.0))
            node = self._production_node(name, rate, state, [], 0, max_depth)
            if node is not None:
                items.append(node)
        plan = {
            "items": items,
            "recipes": sorted(state["recipes"].values(), key=lambda entry: (-_number(entry.get("rate")), str(entry.get("name")))),
            "raw_inputs": sorted(state["raw_inputs"].values(), key=lambda entry: (-_number(entry.get("rate")), str(entry.get("name")))),
            "alternatives": [item for options in state["alternatives"].values() for item in options],
        }
        return plan

    def _production_node(
        self,
        name: str,
        rate: float,
        state: dict[str, object],
        stack: list[str],
        depth: int,
        max_depth: int,
    ) -> dict[str, object] | None:
        if rate <= 0:
            return None
        entry = self.entry(name) or {}
        kind = str(entry.get("kind") or "item")
        surplus = state["surplus"]
        available = float(surplus.get(name, 0.0))
        if available > 0:
            used = min(available, rate)
            surplus[name] = available - used
            rate -= used
        if rate <= 0:
            return {"name": name, "kind": kind, "rate": 0.0, "status": "fulfilled_by_surplus"}
        if depth > max_depth or name in stack:
            raw_inputs = state["raw_inputs"]
            raw_inputs.setdefault(name, {"name": name, "kind": kind, "rate": 0.0})["rate"] += rate
            return {"name": name, "kind": kind, "rate": rate, "status": "raw"}
        candidates = self._recipe_candidates(name)
        if not candidates:
            raw_inputs = state["raw_inputs"]
            raw_inputs.setdefault(name, {"name": name, "kind": kind, "rate": 0.0})["rate"] += rate
            return {"name": name, "kind": kind, "rate": rate, "status": "raw"}
        candidates = self._rank_candidates(candidates, state["known_recipes"])
        candidates = sorted(candidates, key=lambda candidate: self._candidate_score(candidate, name, state["known_recipes"]))
        chosen = candidates[0]
        alternatives = state["alternatives"]
        alternatives.setdefault(name, [])
        for candidate in candidates[:5]:
            alternatives[name].append({
                "item": name,
                "recipe": candidate["name"],
                "localized_name": candidate.get("localized_name", candidate["name"]),
                "kind": candidate.get("kind", "recipe"),
                "category": candidate.get("category", "crafting"),
            })
        recipe_name = str(chosen["name"])
        recipes = state["recipes"]
        recipe_record = recipes.get(recipe_name)
        if recipe_record is None:
            recipe_record = {
                "name": recipe_name,
                "kind": "recipe",
                "localized_name": chosen.get("localized_name", recipe_name),
                "category": str(chosen.get("category") or "crafting"),
                "rate": 0.0,
                "target_rate": 0.0,
                "runs_per_minute": 0.0,
                "energy_required": _number(chosen.get("energy_required"), 1.0) or 1.0,
                "machine": {},
                "machine_count": 0.0,
                "ingredients": [],
                "results": chosen.get("results") or [],
                "status": "chosen",
            }
            recipes[recipe_name] = recipe_record
        stack.append(name)
        ingredient_nodes = []
        outputs = chosen.get("results") or []
        output_amount = self._expected_output_amount(outputs, name)
        if output_amount <= 0:
            output_amount = 1.0
        recipe_rate = rate / output_amount
        recipe_record["rate"] += recipe_rate
        recipe_record["target_rate"] += rate
        recipe_record["results"] = outputs
        self._finalize_recipe_record(recipe_record)
        machine_rows = self.machines_for(str(recipe_record["category"]))
        recipe_record["machine"] = dict(machine_rows[0]) if machine_rows else {"entity": "character", "crafting_speed": 1.0, "module_slots": 0}
        crafting_speed = _number(recipe_record["machine"].get("crafting_speed"), 1.0) or 1.0
        recipe_record["runs_per_minute"] = recipe_record["rate"]
        recipe_record["machine_count"] = recipe_record["rate"] * _number(recipe_record["energy_required"], 1.0) / (60.0 * crafting_speed)
        produced_total = recipe_rate * output_amount
        surplus[name] = float(surplus.get(name, 0.0)) + max(0.0, produced_total - rate)
        for ingredient in chosen.get("ingredients", []) or []:
            if not isinstance(ingredient, dict):
                continue
            ingredient_name = str(ingredient.get("name") or "").strip()
            if not ingredient_name:
                continue
            ingredient_amount = _number(ingredient.get("amount"), _number(ingredient.get("amount_min"), 1.0))
            ingredient_rate = recipe_rate * ingredient_amount
            child = self._production_node(
                ingredient_name,
                ingredient_rate,
                state,
                stack,
                depth + 1,
                max_depth,
            )
            if child is not None:
                ingredient_nodes.append(child)
        stack.pop()
        recipe_record["ingredients"] = ingredient_nodes
        return {
            "name": name,
            "kind": kind,
            "rate": rate,
            "recipe": self._recipe_reference(recipe_record),
            "status": "planned",
        }

    def _recipe_reference(self, recipe_record: dict[str, object]) -> dict[str, object]:
        return {
            "name": recipe_record.get("name"),
            "kind": recipe_record.get("kind", "recipe"),
            "localized_name": recipe_record.get("localized_name"),
            "category": recipe_record.get("category"),
            "target_rate": recipe_record.get("target_rate"),
            "rate": recipe_record.get("rate"),
            "runs_per_minute": recipe_record.get("runs_per_minute"),
            "energy_required": recipe_record.get("energy_required"),
            "machine": recipe_record.get("machine"),
            "machine_count": recipe_record.get("machine_count"),
            "status": recipe_record.get("status"),
        }

    def _expected_output_amount(self, outputs: list[dict[str, object]], name: str) -> float:
        total = 0.0
        for output in outputs:
            if not isinstance(output, dict):
                continue
            if str(output.get("name")) != name:
                continue
            amount = _number(output.get("amount"), 0.0)
            if amount <= 0:
                amount = _number(output.get("amount_min"), 0.0)
            if amount <= 0:
                amount = 1.0
            probability = _number(output.get("probability"), 1.0) or 1.0
            total += amount * probability
        return total

    def _finalize_recipe_record(self, recipe_record: dict[str, object]) -> None:
        machine = recipe_record.get("machine") if isinstance(recipe_record.get("machine"), dict) else None
        if machine is None:
            machine = {"entity": "character", "crafting_speed": 1.0, "module_slots": 0}
            recipe_record["machine"] = machine
        crafting_speed = _number(machine.get("crafting_speed"), 1.0) or 1.0
        energy_required = _number(recipe_record.get("energy_required"), 1.0) or 1.0
        rate = _number(recipe_record.get("rate"), 0.0)
        recipe_record["runs_per_minute"] = rate
        recipe_record["machine_count"] = rate * energy_required / (60.0 * crafting_speed)

    def _recipe_candidates(self, name: str) -> list[dict[str, object]]:
        rows = self._connect().execute(
            "SELECT r.doc FROM recipe_io io JOIN records r ON r.name = io.recipe AND r.kind = 'recipe'"
            " WHERE io.item = ? AND io.role = 'result' ORDER BY r.hidden ASC, r.localized_name",
            (name,),
        ).fetchall()
        return [json.loads(row["doc"]) for row in rows]

    def _rank_candidates(self, candidates: list[dict[str, object]], known_recipes: set[str]) -> list[dict[str, object]]:
        return sorted(
            candidates,
            key=lambda candidate: (
                0 if str(candidate.get("name")) in known_recipes else 1,
                0 if candidate.get("unlocked_by") else 1,
                0 if not candidate.get("hidden") else 1,
                len(candidate.get("ingredients", []) or []),
                str(candidate.get("localized_name") or candidate.get("name") or ""),
            ),
        )

    def _candidate_score(self, candidate: dict[str, object], target_name: str, known_recipes: set[str]) -> tuple[float, float, float, float, str]:
        candidate_name = str(candidate.get("name") or "").lower()
        localized_name = str(candidate.get("localized_name") or "").lower()
        target_slug = target_name.lower()
        output_amount = self._expected_output_amount(candidate.get("results") or [], target_name)
        ingredient_count = float(len(candidate.get("ingredients", []) or []))
        category = str(candidate.get("category") or "crafting")
        direct_match = 0.0
        if candidate_name == target_slug:
            direct_match -= 80.0
        if target_slug in candidate_name:
            direct_match -= 40.0
        if target_slug.replace("-", " ") in localized_name:
            direct_match -= 30.0
        primary_output = 0.0
        if output_amount > 0:
            if abs(output_amount - 1.0) < 0.001:
                primary_output -= 25.0
            else:
                primary_output += min(abs(output_amount - 1.0) * 2.0, 60.0)
        category_penalty = 0.0
        if category in {"recycling", "crafting-with-fluid", "crafting-with-fuel"}:
            category_penalty += 20.0
        score = (
            0.0 if candidate_name in known_recipes else 1.0,
            0.0 if not candidate.get("hidden") else 1.0,
            0.0 if candidate.get("unlocked_by") else 1.0,
            direct_match,
            primary_output,
            category_penalty,
            ingredient_count,
            str(candidate.get("localized_name") or candidate.get("name") or ""),
        )
        return score


def _relevance(row: sqlite3.Row, query: str, tokens: list[str]) -> float:
    """Rank exact and prefix identifier hits above bag-of-words matches."""
    name = str(row["name"]).lower()
    localized = str(row["localized_name"] or "").lower()
    normalized = query.strip().lower()
    joined = "-".join(tokens)
    score = -float(row["rank"])
    if normalized in (name, localized):
        score += 1000
    elif joined == name:
        score += 900
    elif name.startswith(joined) or localized.startswith(normalized):
        score += 500
    elif joined in name or normalized in localized:
        score += 250
    if all(token in name or token in localized for token in tokens):
        score += 120
    return score


def summarize(record: dict[str, object], relation_limit: int = 8) -> dict[str, object]:
    """Trim a record to the fields that answer a question, keeping LLM payloads small."""
    summary = {key: record[key] for key in SUMMARY_FIELDS if record.get(key) not in (None, "", [], {})}
    for field in ("made_in", "used_in", "crafted_in", "unlocked_by", "effects", "prerequisites"):
        values = summary.get(field)
        if isinstance(values, list) and len(values) > relation_limit:
            summary[field] = values[:relation_limit]
            summary[f"{field}_total"] = len(values)
    return summary
