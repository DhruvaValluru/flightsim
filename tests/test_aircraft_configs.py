"""Aircraft configs: every one carries the keys the loaders read, and the
J-11A (Phase 3 box D2, owner decision 3) is pinned, licensed, labelled,
loaded and flyable by name.

The J-11A facts checked here: the FDM is the yanes19/SU-27SK package's
J-11A.xml vendored at commit 925cb531 under assets/fdm_root/aircraft/J11
with its GPL-2.0 LICENSE (byte-equal to the saved packet text), the seven
KEYPOINT_NAMES resolve, the two R-27R payload components weigh what the
FDM's pointmasses weigh, the gear patterns compile and pick the UC_*
objects, the limits carry a value with a source or a reason, the default
run ("fly the J-11 at 3000 m") compiles to J11 at the table's cruise
speed, validates with no envelope refusal and trims.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from core.capture.airframe import KEYPOINT_NAMES, load_airframe
from core.fdm.aircraft import REPO_ROOT_DIR, resolve
from core.nl.compiler import AIRCRAFT_WORDS, CRUISE_DEFAULT_KT, compile_prompt

REPO = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO / "assets" / "aircraft_config"
CONFIGS = sorted(CONFIG_DIR.glob("*.json"))
J11_JSON = CONFIG_DIR / "J11.json"
J11_FDM_DIR = REPO / "assets" / "fdm_root" / "aircraft" / "J11"
J11_UE_DIR = (REPO / "ue/Plugins/JSBSimFlightDynamicsModel/Resources/JSBSim"
              / "aircraft" / "J11")
SAVED_LICENCE = REPO / "docs" / "phase3" / "packets" / "D1-SU-27SK-LICENSE.txt"
PINNED_COMMIT = "925cb5317f3c66fa323a9e186e24d574e0b0881d"
LICENCE_SHA256 = "db296f2f7f35bca3a174efb0eb392b3b17bd94b341851429a3dff411b1c2fc73"
STORE_LB = 230.21

REQUIRED_KEYS = ("name", "fdm", "fdm_match", "mesh_airframe", "source_dir",
                 "license")
REQUIRED_LICENSE_KEYS = ("license_name", "repo", "commit")


def _config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", CONFIGS, ids=[p.stem for p in CONFIGS])
def test_every_config_has_the_required_keys(path):
    """The same glob tests/test_licence.py sweeps: a config the importer,
    converter and labeller can all read, named after its file."""
    config = _config(path)
    for key in REQUIRED_KEYS:
        assert key in config, f"{path.name} lacks {key!r}"
    assert config["name"] == path.stem
    assert isinstance(config["fdm_match"], list) and config["fdm_match"]
    block = config["license"]
    for key in REQUIRED_LICENSE_KEYS:
        assert block.get(key), f"{path.name} license lacks {key!r}"
    assert "licence" not in config, (
        f"{path.name}: the key every loader reads is 'license'")


def test_J11_config_names_the_pinned_commit_and_licence():
    config = _config(J11_JSON)
    block = config["license"]
    assert block["commit"] == PINNED_COMMIT
    assert block["license_name"] == "GPL-2.0"
    assert block["repo"] == "https://github.com/yanes19/SU-27SK"
    assert block["file"] == "LICENSE"
    assert config["fdm"] == "J11" and config["name"] == "J11"
    assert config["source_dir"] == "../aircraft_src/J11"
    files = [part["file"] for part in config["parts"]]
    assert files[0] == "Models/Su-27.ac"
    assert config["surfaces"] == {}, "decision 6: no control surfaces"


def test_J11_licence_file_matches_the_saved_text():
    vendored = J11_FDM_DIR / "LICENSE"
    assert vendored.is_file()
    digest = hashlib.sha256(vendored.read_bytes()).hexdigest()
    assert digest == LICENCE_SHA256
    assert digest == hashlib.sha256(SAVED_LICENCE.read_bytes()).hexdigest()


def test_J11_labels_load_with_seven_keypoints_or_stated_missing():
    airframe = load_airframe("J11")
    assert set(airframe.keypoints) | set(airframe.missing) == set(KEYPOINT_NAMES)
    assert airframe.missing == ()
    assert airframe.keypoints["nose"].basis == "measured"
    assert airframe.keypoints["tail"].basis == "measured"
    for name in ("left_wingtip", "right_wingtip"):
        assert airframe.keypoints[name].basis == "fdm-approximation"
    for name in ("nose_gear", "left_main_gear", "right_main_gear"):
        assert airframe.keypoints[name].basis == "fdm"
    # nose ahead of the CG, tail behind, in the body frame (x forward)
    assert airframe.keypoints["nose"].body_m[0] > 10.0
    assert airframe.keypoints["tail"].body_m[0] < -8.0
    assert airframe.length_m == pytest.approx(21.94)
    assert airframe.span_m == pytest.approx(48.23 * 12 * 0.0254)


def test_J11_components_payload_matches_the_fdm_pointmass():
    airframe = load_airframe("J11")
    by_id = {c.id: c for c in airframe.components}
    assert list(by_id) == ["r27r_left", "r27r_right", "nose_gear",
                           "left_main_gear", "right_main_gear"]
    assert (by_id["r27r_left"].cls, by_id["r27r_left"].station) == ("payload", "pylon2-load")
    assert (by_id["r27r_right"].cls, by_id["r27r_right"].station) == ("payload", "pylon3-load")
    for cid in ("r27r_left", "r27r_right"):
        assert by_id[cid].mass_lb == pytest.approx(STORE_LB)
    for cid in ("nose_gear", "left_main_gear", "right_main_gear"):
        assert by_id[cid].cls == "landing_gear" and by_id[cid].mass_lb == 0.0
    # The vendored XML's own numbers, read without the loader.
    xml = (J11_FDM_DIR / "J11.xml").read_text(encoding="utf-8")
    for name in ("pylon2-load", "pylon3-load"):
        match = re.search(rf'<pointmass name="{name}">.*?<weight unit="LBS">([0-9.]+)</weight>',
                          xml, re.S)
        assert match and float(match.group(1)) == pytest.approx(STORE_LB)
    config = _config(J11_JSON)
    assert config["loading"]["loadout"]["stations"] == {
        "pylon2-load": STORE_LB, "pylon3-load": STORE_LB}
    components = {p["component"]: p for p in config["parts"] if "component" in p}
    assert set(components) == {"r27r_left", "r27r_right"}
    assert components["r27r_left"]["offset_m"][1] == -components["r27r_right"]["offset_m"][1]


def test_J11_gear_geometry_patterns_compile():
    gear = _config(J11_JSON)["gear_geometry"]
    patterns = gear["parts"] + gear["objects"]
    assert patterns and gear["source"]
    compiled = [re.compile(p) for p in patterns]
    assert any(c.fullmatch("UC_Main_Left_Tyre") for c in compiled)
    assert any(c.fullmatch("UC_Nose_Tyres") for c in compiled)
    assert not any(c.fullmatch("HULL_Hull_Upper.001") for c in compiled)
    assert not any(c.fullmatch("Pylon-under-fuselage-L") for c in compiled)


def test_J11_limits_have_values_and_sources():
    limits = _config(J11_JSON)["limits"]
    for key in ("n_z_pos_g", "n_z_neg_g", "speed_limit_kt", "m_mo", "alpha_stall_deg"):
        entry = limits[key]
        if entry["value"] is None:
            assert len(entry["reason"]) > 40, key
        else:
            assert isinstance(entry["value"], (int, float)), key
            assert len(entry["source"]) > 40, key
    assert limits["n_z_pos_g"]["value"] > 0 > limits["n_z_neg_g"]["value"]
    assert "[unverified here]" in limits["n_z_pos_g"]["source"]
    assert limits["note"]


def test_J11_fdm_resolves_from_the_repo_root():
    model = resolve("J11")
    assert model.root_dir == REPO_ROOT_DIR
    assert model.xml_path == J11_FDM_DIR / "J11.xml"
    assert model.license_name == "GPL-2.0"
    header = model.xml_path.read_text(encoding="utf-8")
    assert PINNED_COMMIT in header and "PROVENANCE" in header
    assert '<fdm_config name="Su-27SK"' in header
    assert "Su-27SK" in _config(J11_JSON)["fdm_match"]
    for sub in ("Engines/Saturn-AL-31.xml", "Engines/GTDE-117_T.xml",
                "Engines/direct.xml", "Systems/fuel.xml", "LICENSE"):
        assert (J11_FDM_DIR / sub).is_file(), sub
    # The staged copy the converter and the engine read is the same tree.
    staged = sorted(p.relative_to(J11_UE_DIR) for p in J11_UE_DIR.rglob("*") if p.is_file())
    owned = sorted(p.relative_to(J11_FDM_DIR) for p in J11_FDM_DIR.rglob("*") if p.is_file())
    assert staged == owned and owned
    for rel in owned:
        assert (J11_UE_DIR / rel).read_bytes() == (J11_FDM_DIR / rel).read_bytes(), rel


def test_J11_default_airspeed_is_the_table_value():
    assert CRUISE_DEFAULT_KT["J11"] == 350.0
    assert {w: m for w, m in AIRCRAFT_WORDS if m == "J11"} == {
        "j-11": "J11", "j11": "J11", "flanker": "J11"}
    for prompt in ("fly the J-11 at 3000 m for 10 seconds",
                   "fly the j11 at 3000 m for 10 seconds",
                   "fly the Flanker at 3000 m for 10 seconds"):
        spec = compile_prompt(prompt)
        assert str(spec.aircraft.value) == "J11", prompt
        assert float(spec.airspeed.value) == CRUISE_DEFAULT_KT["J11"]
        assert float(spec.altitude.value) == 3000.0


def test_J11_default_run_trims():
    """The default run's card validates without an envelope refusal and
    the shared configure_from_spec trims the loaded airframe level."""
    from core.scenario.runner import configure_from_spec
    from core.scenario.validate import validate

    spec = compile_prompt("fly the J-11 at 3000 m for 10 seconds")
    report = validate(spec)
    assert report.violations == [], [v.constraint for v in report.violations]
    fdm = configure_from_spec(spec)
    exec_ = fdm._exec
    assert exec_["inertia/pointmass-weight-lbs[2]"] == pytest.approx(STORE_LB)
    assert exec_["inertia/pointmass-weight-lbs[3]"] == pytest.approx(STORE_LB)
    assert abs(exec_["attitude/theta-deg"] - exec_["aero/alpha-deg"]) < 0.1
    assert 0.0 < exec_["fcs/throttle-cmd-norm[0]"] < 1.0
