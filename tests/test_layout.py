import pytest

from ndi_multiviewer import layout as L


def test_presets_are_valid():
    for name, lay in L.PRESETS.items():
        lay.validate()
        assert lay.name == name


def test_preset_tile_counts():
    assert L.PRESETS["1+5"].tile_count == 6
    assert L.PRESETS["1+7"].tile_count == 8
    assert L.PRESETS["2+8"].tile_count == 10
    assert L.uniform(3, 4).tile_count == 12


def test_round_trip(tmp_path):
    lay = L.uniform(2, 3)
    lay.assignments = {0: "HOST (Cam 1)", 4: "HOST (Cam 2)"}
    L.save(lay, tmp_path / "l.json")
    back = L.load(tmp_path / "l.json")
    assert back == lay


def test_assignments_survive_shrink_and_grow():
    lay = L.uniform(3, 3)
    lay.assignments = {0: "A", 8: "B"}
    small = lay.with_cells_of(L.uniform(2, 2))
    assert small.tile_count == 4
    big = small.with_cells_of(L.uniform(3, 3))
    assert big.assignments == {0: "A", 8: "B"}


def test_overlap_rejected():
    bad = L.Layout(2, 2, [L.Cell(0, 0, 2, 2), L.Cell(1, 1)])
    with pytest.raises(ValueError):
        bad.validate()
