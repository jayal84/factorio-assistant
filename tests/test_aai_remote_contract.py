from pathlib import Path


ROOT = Path(r"x:\factorio_assistant")
AAI_MOD = Path(r"z:\factorio\mods\tmp_aai\aai-programmable-vehicles\control.lua")
BRIDGE_MOD = ROOT / "mod" / "control.lua"


def test_aai_mod_exposes_remote_vehicle_api():
    text = AAI_MOD.read_text(encoding="utf-8", errors="ignore")
    assert 'remote.add_interface("aai-programmable-vehicles"' in text
    assert 'function unit_by_unit_number(unit_number)' in text
    assert "return storage.unit.units[unit_id]" in text
    assert "return storage.unit.unit_numbers[unit_number]" not in text


def test_bridge_normalizes_aai_units_before_dispatch():
    text = BRIDGE_MOD.read_text(encoding="utf-8", errors="ignore")
    assert 'local function aai_unit_from_entity(entity)' in text
    assert 'type(unit) == "table"' in text
    assert 'unit_by_unit_id' in text
