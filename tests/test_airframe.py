"""C1: the airframe's ``components`` block and its default loadout.

A drawn store must be a store the flight model carries: the loader matches
every declared component to a part (a loadable station whose FDM pointmass
weighs the stated mass, or a defined gear keypoint) and refuses the rest
by name (``aircraft.component_unmatched``).
"""

import contextlib
import io
import json
import math
from pathlib import Path

import pytest

from core.capture.airframe import (
    AirframeLabelError, Component, ComponentUnmatchedError, load_airframe,
)
from core.fdm import FlightDynamics, TrimMode
from core.fdm import units as u

REPO = Path(__file__).resolve().parents[1]
A4_JSON = REPO / "assets" / "aircraft_config" / "A4.json"
LEVEL = {"gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
         "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0}


def _a4_config() -> dict:
    return json.loads(A4_JSON.read_text(encoding="utf-8"))


def _write(tmp_path, config) -> Path:
    (tmp_path / "A4.json").write_text(json.dumps(config), encoding="utf-8")
    return tmp_path


def test_components_a4_loads_three_payloads():
    airframe = load_airframe("A4")
    payloads = [c for c in airframe.components if c.cls == "payload"]
    assert {c.station for c in payloads} == {"STA2", "STA3", "STA4"}
    assert all(isinstance(c, Component) and c.mass_lb == 750.0
               for c in payloads)
    assert not hasattr(payloads[0], "int_id")
    assert airframe.loadout["model_vars"] == {
        "STA2_LOAD": 1, "STA3_LOAD": 1, "STA4_LOAD": 1}
    assert airframe.to_dict()["components"][0]["id"] == payloads[0].id


def test_components_dead_station_refused_by_name(tmp_path):
    config = _a4_config()
    config["labels"]["components"][0]["station"] = "STA1"   # not loadable
    with pytest.raises(ComponentUnmatchedError,
                       match="aircraft.component_unmatched") as info:
        load_airframe("A4", config_dir=_write(tmp_path, config))
    assert config["labels"]["components"][0]["id"] in str(info.value)
    assert isinstance(info.value, AirframeLabelError)


def test_components_gear_component_needs_a_keypoint(tmp_path):
    config = _a4_config()
    config["labels"]["components"][3]["source"] = "no_such_gear"
    with pytest.raises(ComponentUnmatchedError, match="no_such_gear"):
        load_airframe("A4", config_dir=_write(tmp_path, config))
    ok = load_airframe("A4")
    gear = [c for c in ok.components if c.cls == "landing_gear"]
    assert {c.part_name for c in gear} == {
        "nose_gear", "left_main_gear", "right_main_gear"}


def test_components_weights_match_the_fdm_xml(tmp_path):
    config = _a4_config()
    for st in config["loading"]["stations"]:
        if st["name"] == "STA3":
            st["default_lb"] = 1500.0       # the XML still carries 750
    with pytest.raises(ComponentUnmatchedError, match="disagree"):
        load_airframe("A4", config_dir=_write(tmp_path, config))


def test_components_a_clean_config_has_none():
    for name in ("B747",):
        airframe = load_airframe(name)
        assert airframe.components == ()
        assert airframe.loadout == {}


def test_components_loadout_trims():
    """The A-4 flies loaded (3 x 750 lb on STA2-4 from the generated XML)
    and its longitudinal trim converges."""
    with contextlib.redirect_stdout(io.StringIO()):
        fdm = FlightDynamics("A4")
        fdm.set_initial_conditions(
            {"h-sl-ft": u.m_to_ft(3000.0), "vc-kts": 300.0, **LEVEL})
        for n in (2, 3, 4):
            assert fdm.props.get(f"inertia/pointmass-weight-lbs[{n}]") == \
                pytest.approx(750.0)
        fdm.start_engines()
        fdm.trim(TrimMode.LONGITUDINAL)
    assert math.isfinite(fdm.props.get("fcs/elevator-pos-rad"))


# C7: the c172p declares ONE landing_gear component (letter C: one per
# aircraft), sourced on a defined keypoint; a dead keypoint is refused by name.
C172P_JSON = REPO / "assets" / "aircraft_config" / "c172p.json"


def test_components_c172p_gear_needs_a_keypoint(tmp_path):
    airframe = load_airframe("c172p")
    [gear] = airframe.components
    assert isinstance(gear, Component)
    assert gear.cls == "landing_gear" and gear.id == "landing_gear"
    assert gear.part_name == "nose_gear" and gear.station is None
    assert airframe.loadout == {}                 # a gear component loads no store
    config = json.loads(C172P_JSON.read_text(encoding="utf-8"))
    [entry] = [c for c in config["labels"]["components"] if c["class"] == "landing_gear"]
    entry["source"] = "no_such_gear"
    (tmp_path / "c172p.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ComponentUnmatchedError, match="no_such_gear") as info:
        load_airframe("c172p", config_dir=tmp_path)
    assert "landing_gear" in str(info.value)
