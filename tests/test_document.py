# SPDX-License-Identifier: GPL-3.0-or-later
"""The viewer's document model (no GUI): what is listed, found and hit, and that opening never writes."""
import hashlib
import shutil
from pathlib import Path

import pytest

from osviewer.document import ViewerDocument, ViewerError
from osviewer.settings import Settings

DEMO = Path(__file__).with_name("demo_project.schematix")


@pytest.fixture
def demo(tmp_path):
    p = tmp_path / "demo.schematix"
    shutil.copy(DEMO, p)
    return p


def test_opening_never_changes_the_file(demo):
    before = hashlib.sha256(demo.read_bytes()).hexdigest(), demo.stat().st_mtime_ns
    d = ViewerDocument(demo)
    d.components(), d.bom(), d.nets(), d.meta(), d.component_at(0, (480, 300))
    assert (hashlib.sha256(demo.read_bytes()).hexdigest(), demo.stat().st_mtime_ns) == before


def test_structure_and_title_block(demo):
    d = ViewerDocument(demo)
    assert d.title == "Conveyor station 3"
    assert d.sheet_names() == ["24 V supply", "Motor control", "Hydraulics"]
    meta = dict(d.meta())
    assert meta["Drawing number"] == "CS3-E" and meta["Revision"] == "A"
    assert d.sheet_size(0)[0] > d.sheet_size(0)[1] > 0


def test_components_search_and_lookup(demo):
    d = ViewerDocument(demo)
    rows = d.components()
    assert len(rows) == 26 and len({(r.sheet_index, r.id) for r in rows}) == 26
    fuse = d.search("fuse")
    assert [r.designator for r in fuse] == ["F1"] and fuse[0].part_number == "FU-2A"
    assert {r.designator for r in d.search("k1 contact")} == {"K1"}
    assert d.search("no such thing") == []
    assert all(r.designator or r.description for r in d.search(""))      # unnamed connectors are not listed
    assert d.component(fuse[0].sheet_index, fuse[0].id) == fuse[0]


def test_hit_testing_finds_the_smallest_component_under_the_point(demo):
    d = ViewerDocument(demo)
    f1 = d.search("fuse")[0]
    box = d.component_bbox(f1.sheet_index, f1.id)
    centre = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    assert d.component_at(f1.sheet_index, centre) == f1.id
    assert d.component_at(f1.sheet_index, (-500, -500)) is None


def test_bom_and_wires(demo):
    d = ViewerDocument(demo)
    bom = d.bom()
    assert any(b.part_number == "FU-2A" and b.quantity == 1 for b in bom)
    nets = d.nets()
    first = next(n for n in nets if n["number"] == "1")
    assert first["terminals"] == ["X1:2", "F1:1"] and first["sheets"] == ["24 V supply"]
    numbers = [n["number"] for n in nets if n["number"]]
    assert numbers == sorted(numbers, key=lambda s: int(s) if s.isdigit() else 10 ** 9)


def test_damaged_and_missing_files_give_a_message(tmp_path):
    bad = tmp_path / "bad.schematix"
    bad.write_bytes(b"PK\x03\x04 not really a zip")
    with pytest.raises(ViewerError):
        ViewerDocument(bad)
    with pytest.raises(ViewerError):
        ViewerDocument(tmp_path / "missing.schematix")


def test_settings_survive_damage_and_remember_recent(tmp_path):
    s = Settings(tmp_path)
    assert s["theme"] == "modern_light" and s["recent"] == []
    for i in range(12):
        s.remember(f"/p/{i}.schematix")
    again = Settings(tmp_path)
    assert again["recent"][0] == "/p/11.schematix" and len(again["recent"]) == 10
    (tmp_path / "settings.json").write_text("{damaged")
    assert Settings(tmp_path)["theme"] == "modern_light"
