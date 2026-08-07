#!/usr/bin/env python3
"""Add the Factorio Assistant compatibility API to an installed DQOL archive."""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from pathlib import Path

MARKER = "factorio-assistant-dqol-api"
API = r'''
-- factorio-assistant-dqol-api
remote.add_interface("factorio_assistant_dqol", {
  get_pinned_sites = function()
    local result = {}
    local sites = storage.sites and storage.sites.surfaces or {}
    for surface_id, site_types in pairs(sites) do
      if type(site_types) == "table" then
        for resource_type, site_list in pairs(site_types) do
          if type(site_list) == "table" then
            for _, site in pairs(site_list) do
              if type(site) == "table" and site.pinned == true and site.archived ~= true then
                local calculated = site.calculated or {}
                table.insert(result, {
                  id = site.id,
                  surface = surface_id,
                  name = site.name or resource_type,
                  type = site.type or resource_type,
                  type_name = game.get_localised_string({"entity-name." .. (site.type or resource_type)}),
                  initial_amount = site.initial_amount or 0,
                  amount = calculated.amount or 0,
                  percent = calculated.percent or 0,
                  rate = calculated.rate or 0,
                  estimated_depletion = calculated.estimated_depletion,
                  position = {x = site.area and site.area.x or 0, y = site.area and site.area.y or 0},
                })
              end
            end
          end
        end
      end
    end
    table.sort(result, function(left, right)
      if left.surface ~= right.surface then return left.surface < right.surface end
      return tostring(left.id) < tostring(right.id)
    end)
    return result
  end,
})
'''


def find_archive(mods_dir: Path) -> Path | None:
    for archive in sorted(mods_dir.glob("dqol-resource-monitor*.zip")):
        try:
            with zipfile.ZipFile(archive) as package:
                info_entries = [
                    name for name in package.namelist()
                    if name.replace("\\", "/").endswith("/info.json")
                    or name.replace("\\", "/") == "info.json"
                ]
                for info_name in info_entries:
                    metadata = json.loads(package.read(info_name).decode("utf-8"))
                    if metadata.get("name") == "dqol-resource-monitor":
                        return archive
        except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile):
            continue
    return None


def patch_archive(archive: Path) -> bool:
    with zipfile.ZipFile(archive, "r") as source:
        names = [name.replace("\\", "/") for name in source.namelist()]
        control_candidates = [name for name in names if name.endswith("/control.lua")]
        if not control_candidates:
            raise RuntimeError(f"DQOL archive has no control.lua: {archive}")
        control_name = control_candidates[0]
        control = source.read(control_name).decode("utf-8")
        if MARKER in control:
            return False
        entries = [(name, source.read(original)) for name, original in zip(names, source.namelist())]

    control = control.rstrip() + "\n\n" + API.lstrip() + "\n"
    entries = [(name, control.encode("utf-8") if name == control_name else data) for name, data in entries]
    fd, temporary_name = tempfile.mkstemp(prefix=f"{archive.stem}.", suffix=".zip", dir=archive.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for name, data in entries:
                target.writestr(name, data)
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def main() -> int:
    mods_dir = Path(os.environ.get("FACTORIO_MODS_DIR", "/share/factorio/mods"))
    archive = find_archive(mods_dir)
    if archive is None:
        print("DQOL Resource Monitor archive not found; compatibility patch skipped.")
        return 0
    changed = patch_archive(archive)
    print(f"DQOL compatibility API {'patched' if changed else 'already present'}: {archive.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
