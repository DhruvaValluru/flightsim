"""Phase 2, the spec-8 bump (docs/PHASE2_CONTRACTS.md §0, §12).

The bump adds four optional, absent-canonical blocks -- ``scene``,
``taxonomy``, ``traffic[]``, ``randomization.policy`` -- and the camera's
``exposure`` triple. The load-bearing claims, each a test here rather
than an intention:

* a version-7 dict refuses by the named version error, as every bump did;
* the canonical form of a spec that states none of the new fields is the
  version-7 form plus the version line -- measured against the COMMITTED
  version-7 examples, frozen byte-identical under tests/data;
* every new field is a provenanced Quantity behind the spec's own
  set()/plan() front door, and a stated one is never silently moved;
* every refusal is by name, and ``Violation.render()`` no longer
  crashes on the randomisation block's string limits.

What is NOT claimed: nothing here samples a policy, composes traffic or
maps exposure to EV100 -- packages F, B and the Look lane own those.
"""

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from core.nl.compiler import compile_prompt
from core.scenario.blocks import (
    DEFAULT_CLASSES, DEFAULT_TRAFFIC_RANGE_M, MAX_TRAFFIC, SceneSpec,
    TaxonomySpec, TrafficSpec, configured_airframes,
)
from core.scenario.camera import (
    DEFAULT_EXPOSURE, CameraSpec, ExposureSpec,
)
from core.scenario.fields import Quantity, Source
from core.scenario.spec import SPEC_VERSION, ScenarioSpec
from core.scenario.validate import (
    Violation, policy_problems, validate, validate_blocks, validate_policy,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SPEC7 = Path(__file__).resolve().parent / "data" / "spec7_examples"


@pytest.fixture
def spec():
    return compile_prompt("fly the 747 at 10000 ft and 280 kt for 60 seconds")


def names(violations):
    return [v.constraint for v in violations]


# -- the bump itself --------------------------------------------------------

def test_spec_version_is_8_and_a_version_7_dict_refuses_by_name(spec):
    """The same refusal every earlier bump used: a ValueError naming the
    version, never a guess at the schema."""
    assert SPEC_VERSION == 8
    data = spec.to_dict()
    assert data["spec_version"] == 8
    data["spec_version"] = 7
    with pytest.raises(ValueError, match="spec_version 7 is not supported"):
        ScenarioSpec.from_dict(data)


def _canonical_digest(payload) -> str:
    """The digest rule, re-implemented (not imported): SHA-256 over the
    canonical JSON minus prompt and notes."""
    payload = dict(payload)
    payload.pop("prompt", None)
    payload.pop("notes", None)
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@pytest.mark.parametrize("name", sorted(p.name for p in SPEC7.glob("*.yaml")))
def test_a_committed_version_7_example_keeps_its_canonical_form_at_8(name):
    """Absent blocks are canonical: upgrading a committed version-7
    example changes NOTHING but the version line.

    The version-7 reader was a round trip on its own writer's output, so
    its canonical digest is the digest of the frozen file's mapping; the
    version-8 reader must produce that mapping again, plus the version.
    """
    frozen = yaml.safe_load(SPEC7.joinpath(name).read_text(encoding="utf-8"))
    assert frozen["spec_version"] == 7
    v7_digest = _canonical_digest(frozen)
    upgraded = copy.deepcopy(frozen)
    upgraded["spec_version"] = 8
    reread = ScenarioSpec.from_dict(upgraded).to_dict()
    assert reread["spec_version"] == 8
    # Field for field, the version-7 form.
    assert {k: v for k, v in reread.items() if k != "spec_version"} == \
        {k: v for k, v in frozen.items() if k != "spec_version"}
    # And the digest rule sees exactly the version line move.
    v8_digest = ScenarioSpec.from_dict(upgraded).digest()
    assert v8_digest == _canonical_digest(reread)
    assert v8_digest != v7_digest              # the version is hashed
    unversioned = dict(reread); unversioned.pop("spec_version")
    frozen_unversioned = dict(frozen); frozen_unversioned.pop("spec_version")
    assert _canonical_digest(unversioned) == _canonical_digest(frozen_unversioned)


def test_the_committed_examples_are_the_frozen_ones_plus_the_version_line():
    """The regeneration went through the writer: every example differs
    from its frozen version-7 copy by the version line alone -- except
    the mountain refusal, which gained the scene block it documents."""
    for frozen_path in sorted(SPEC7.glob("*.yaml")):
        current = (EXAMPLES / frozen_path.name).read_text(encoding="utf-8")
        frozen = frozen_path.read_text(encoding="utf-8")
        current_body = yaml.safe_load(current)
        frozen_body = yaml.safe_load(frozen)
        assert current_body["spec_version"] == 8
        frozen_body["spec_version"] = 8
        if frozen_path.name == "cameras_mountain_refusal.yaml":
            frozen_body["scene"] = current_body["scene"]
            assert current_body["scene"]["terrain_source"]["value"] == \
                "synthesised"
            assert current_body["scene"]["terrain_source"]["source"] == "user"
        else:
            assert current.replace("spec_version: 8", "spec_version: 7") == \
                frozen
        assert current_body == frozen_body


def test_the_new_blocks_are_absent_from_a_spec_that_states_none(spec):
    data = spec.to_dict()
    for key in ("scene", "taxonomy", "traffic", "randomization"):
        assert key not in data
    assert "exposure" not in CameraSpec.defaulted(aircraft="B747").to_dict()


# -- scene --------------------------------------------------------------------

def test_scene_defaults_to_auto_and_a_stated_source_is_carried(spec):
    assert spec.scene.terrain_source.value == "auto"
    assert spec.scene.is_default()
    spec.set("scene.terrain_source", "synthesised", frm="stated")
    data = spec.to_dict()
    assert data["scene"]["terrain_source"] == {
        "value": "synthesised", "source": "user", "from": "stated"}
    reread = ScenarioSpec.from_dict(data)
    assert reread.scene.terrain_source.source is Source.USER
    assert reread.digest() == spec.digest()
    assert "scene" in spec.render_table()


def test_a_stated_terrain_source_is_never_silently_moved(spec):
    spec.set("scene.terrain_source", "flat")
    with pytest.raises(ValueError, match="never.*moved"):
        spec.plan("scene.terrain_source", "baked", frm="a planner")
    spec.plan("scene.terrain", "runs/terrain/matterhorn", frm="planned")
    assert spec.scene.terrain.source is Source.DERIVED


def test_an_unknown_terrain_source_refuses_by_name(spec):
    spec.set("scene.terrain_source", "moon")
    assert "scene.terrain_source" in names(validate_blocks(spec))
    spec.set("scene.terrain_source", "baked")
    spec.set("scene.terrain", "   ")
    assert "scene.terrain" in names(validate_blocks(spec))
    assert names(validate_blocks(compile_prompt("fly the 747"))) == []


def test_scene_refuses_unknown_and_missing_fields():
    with pytest.raises(ValueError, match="unknown fields"):
        SceneSpec.from_dict({**SceneSpec.defaulted().to_dict(),
                             "lod": {"value": 1}})
    with pytest.raises(ValueError, match="missing required field"):
        SceneSpec.from_dict({"terrain_source": {"value": "flat"}})
    with pytest.raises(ValueError, match="not a scene field"):
        SceneSpec.defaulted().set("lod", 1)


# -- taxonomy -----------------------------------------------------------------

def test_taxonomy_default_is_the_documented_list_and_refuses_bad_lists(spec):
    assert spec.taxonomy.classes.value == list(DEFAULT_CLASSES)
    assert spec.taxonomy.classes.value[0] == "aircraft"
    spec.set("taxonomy.classes", ["aircraft", "terrain", "aircraft"])
    violations = validate_blocks(spec)
    assert names(violations) == ["taxonomy.classes"]
    assert "repeats" in violations[0].message
    spec.set("taxonomy.classes", [])
    assert names(validate_blocks(spec)) == ["taxonomy.classes"]
    spec.set("taxonomy.classes", ["aircraft", 3])
    assert names(validate_blocks(spec)) == ["taxonomy.classes"]
    spec.set("taxonomy.classes", ["aircraft", "terrain"])
    assert names(validate_blocks(spec)) == []
    reread = ScenarioSpec.from_dict(spec.to_dict())
    assert reread.taxonomy.classes.value == ["aircraft", "terrain"]
    assert reread.taxonomy.classes.source is Source.USER


# -- traffic ------------------------------------------------------------------

def test_traffic_entries_are_provenanced_and_round_trip(spec):
    spec.traffic = [TrafficSpec.defaulted("A320", track="crossing")]
    entry = spec.traffic[0]
    assert entry.aircraft.source is Source.USER
    assert float(entry.range_m.value) == DEFAULT_TRAFFIC_RANGE_M
    spec.set("traffic[0].range_m", 250.0, frm="stated 250 m")
    data = spec.to_dict()
    assert data["traffic"][0]["range_m"]["source"] == "user"
    reread = ScenarioSpec.from_dict(data)
    assert reread.digest() == spec.digest()
    assert float(reread.traffic[0].range_m.value) == 250.0
    with pytest.raises(ValueError, match="never.*moved"):
        spec.plan("traffic[0].range_m", 300.0, frm="a planner")
    with pytest.raises(ValueError, match="does not exist"):
        spec.set("traffic[1].range_m", 1.0)
    assert "traffic[0]" in spec.render_table()


def test_traffic_refuses_by_name(spec):
    assert "A320" in configured_airframes()
    spec.traffic = [TrafficSpec.defaulted("X15")]
    assert names(validate_blocks(spec)) == ["traffic.aircraft"]
    spec.traffic = [TrafficSpec.defaulted("A320", track="loop")]
    assert names(validate_blocks(spec)) == ["traffic.track"]
    spec.traffic = [TrafficSpec.defaulted("A320")]
    spec.set("traffic[0].range_m", 0.0)
    assert names(validate_blocks(spec)) == ["traffic.range_m"]
    spec.traffic = [TrafficSpec.defaulted("A320")
                    for _ in range(MAX_TRAFFIC + 1)]
    violations = validate_blocks(spec)
    assert "traffic.count" in names(violations)
    assert "limit 2 aircraft" in violations[0].render()
    spec.traffic = [TrafficSpec.defaulted("A320"), TrafficSpec.defaulted("c172p")]
    assert names(validate_blocks(spec)) == []


def test_traffic_refusals_ride_the_core_validation_surface(spec):
    spec.traffic = [TrafficSpec.defaulted("X15")]
    spec.set("taxonomy.classes", ["a", "a"])
    report = validate(spec, check_feasibility=False)
    assert {"traffic.aircraft", "taxonomy.classes"} <= set(names(report.violations))
    report.render()                       # every refusal renders


# -- randomization.policy -------------------------------------------------

CONTRACT_POLICY = {
    "location": {"choice": ["rockies", "alps", "cascades", "flint_hills"],
                 "weights": [3, 3, 2, 1]},
    "weather_date": {"uniform_dates": ["2024-01-01", "2024-12-31"]},
    "hour_local": {"uniform": [5.5, 20.0]},
    "sun_elevation_min_deg": 2,
    "visibility_km": {"lognormal": {"median": 25, "sigma": 0.6},
                      "clip": [1, 80]},
    "cloud_cover": {"beta": [2, 2]},
    "precipitation": {"choice": ["none", "rain", "snow"], "weights": [7, 2, 1],
                      "gated_by": "cloud_cover > 0.6"},
    "wind_speed_kt": {"weibull": {"k": 2.0, "lambda": 12}},
    "turbulence": {"choice": ["none", "light", "moderate", "severe"],
                   "weights": [4, 3, 2, 1]},
    "surface": {"choice": ["grassland", "desert", "forest", "city", "ocean"]},
    "aircraft": {"choice": ["A320", "B747", "c172p"]},
    "livery": {"choice": ["default"]},
    "traffic_count": {"poisson": 0.7, "max": 2},
    "cameras": {"preset": {"choice": ["chase", "tower", "wingman", "ground"]},
                "focal_length_mm": {"loguniform": [24, 400]},
                "offset_jitter_m": {"normal": {"sigma": 5}}},
}


def test_the_contract_policy_is_of_the_documented_form_and_round_trips(spec):
    assert policy_problems(CONTRACT_POLICY) == []
    spec.set("randomization.policy", CONTRACT_POLICY, frm="contracts §5.2")
    assert validate_policy(spec) == []
    data = spec.to_dict()
    assert data["randomization"]["policy"]["value"] == CONTRACT_POLICY
    assert data["randomization"]["policy"]["source"] == "user"
    assert set(data["randomization"]) == {"policy"}   # ranges stay default
    reread = ScenarioSpec.from_dict(data)
    assert reread.randomization_policy.value == CONTRACT_POLICY
    assert reread.randomization.is_default()
    assert reread.digest() == spec.digest()
    assert "policy" in spec.render_table()
    with pytest.raises(ValueError, match="never.*moved"):
        spec.plan("randomization.policy", {}, frm="a planner")


def test_a_policy_beside_a_stated_block_round_trips(spec):
    spec.set("randomization.enabled", True)
    spec.set("randomization.policy", {"hour_local": {"uniform": [5, 20]}})
    data = spec.to_dict()
    assert data["randomization"]["enabled"]["value"] is True
    assert "policy" in data["randomization"]
    reread = ScenarioSpec.from_dict(data)
    assert reread.randomization.is_enabled()
    assert reread.digest() == spec.digest()


@pytest.mark.parametrize("leaf", [
    {"uniform": [3, 1]},
    {"loguniform": [0, 10]},
    {"choice": []},
    {"choice": ["a", "b"], "weights": [1]},
    {"choice": ["a"], "weights": [0]},
    {"normal": {"sigma": -1}},
    {"lognormal": {"median": 25}},
    {"beta": [2]},
    {"weibull": {"k": 2}},
    {"poisson": -1},
    {"uniform_dates": ["2024-12-31", "2024-01-01"]},
    {"uniform_dates": ["yesterday", "today"]},
    {"uniform": [1, 2], "normal": {"sigma": 1}},
    {"uniform": [1, 2], "clip": [5, 1]},
    {"uniform": [1, 2], "gated_by": 3},
    {"uniform": [1, 2], "shape": "round"},
    {"gaussian": {"sigma": 1}},
    [1, 2],
    {},
])
def test_a_policy_leaf_of_an_undocumented_form_refuses_by_name(spec, leaf):
    spec.set("randomization.policy", {"x": leaf})
    violations = validate_policy(spec)
    assert names(violations) == ["randomization.policy"]
    assert "randomization.policy.x" in violations[0].message
    assert violations[0].render()


def test_a_policy_must_be_a_provenanced_mapping(spec):
    data = spec.to_dict()
    data["randomization"] = {"policy": {"hour_local": {"uniform": [5, 20]}}}
    with pytest.raises(ValueError, match="provenanced mapping"):
        ScenarioSpec.from_dict(data)
    spec.set("randomization.policy", "everything")
    assert names(validate_policy(spec)) == ["randomization.policy"]


# -- cameras[].exposure ---------------------------------------------------

def test_exposure_defaults_are_the_documented_triple_and_absent_when_default():
    camera = CameraSpec.defaulted(camera_id="c", preset="tower")
    aperture, shutter, iso = DEFAULT_EXPOSURE
    assert float(camera.exposure.aperture_f.value) == aperture == 8.0
    assert float(camera.exposure.shutter_s.value) == shutter == 1 / 500
    assert float(camera.exposure.iso.value) == iso == 100.0
    assert all(q.source is Source.DEFAULT for _, q in camera.exposure.quantities())
    assert "exposure" not in camera.to_dict()
    assert CameraSpec.from_dict(camera.to_dict()).exposure.is_default("tower")


def test_a_stated_exposure_is_addressable_provenanced_and_immovable(spec):
    spec.cameras = [CameraSpec.defaulted(camera_id="main", aircraft="B747")]
    before = spec.digest()
    spec.set("cameras[0].exposure.shutter_s", 1 / 1000, frm="a fast shutter")
    q = spec.cameras[0].exposure.shutter_s
    assert q.source is Source.USER and q.value == 1 / 1000 and q.unit == "s"
    assert spec.digest() != before
    data = spec.to_dict()
    assert set(data["cameras"][0]["exposure"]) == {"aperture_f", "shutter_s", "iso"}
    reread = ScenarioSpec.from_dict(data)
    assert reread.digest() == spec.digest()
    assert reread.cameras[0].exposure.shutter_s.frm == "a fast shutter"
    with pytest.raises(ValueError, match="never.*moved"):
        spec.plan("cameras[0].exposure.shutter_s", 1 / 500, frm="a planner")
    spec.plan("cameras[0].exposure.iso", 400.0, frm="a planner")
    assert spec.cameras[0].exposure.iso.source is Source.DERIVED
    assert "exposure shutter_s" in spec.render_table()
    with pytest.raises(ValueError, match="not an exposure field"):
        spec.set("cameras[0].exposure.gain", 1.0)
    with pytest.raises(ValueError, match="not a camera field"):
        spec.set("cameras[0].focal_length_mm.extra", 1.0)


def test_exposure_refuses_unknown_and_missing_fields():
    data = CameraSpec.defaulted().to_dict()
    data["exposure"] = {"aperture_f": {"value": 8.0}}
    with pytest.raises(ValueError, match="missing required field"):
        CameraSpec.from_dict(data)
    data["exposure"] = {**ExposureSpec.defaulted().to_dict(),
                        "gain": {"value": 1}}
    with pytest.raises(ValueError, match="unknown fields"):
        CameraSpec.from_dict(data)


@pytest.mark.parametrize("field,value", [
    ("aperture_f", 0.0), ("shutter_s", -1.0), ("iso", "fast"),
    ("iso", True),
])
def test_a_non_positive_exposure_refuses_by_name(spec, field, value):
    from core.capture.validate import exposure_violations, validate_cameras

    spec.cameras = [CameraSpec.defaulted(camera_id="main", aircraft="B747")]
    assert exposure_violations(spec.cameras[0]) == []
    spec.set(f"cameras[0].exposure.{field}", value)
    violations = validate_cameras(spec)
    assert names(violations) == ["camera.exposure"]
    assert field in violations[0].message
    assert violations[0].render()
    report = validate(spec, check_feasibility=False)
    assert "camera.exposure" in names(report.violations)


# -- Violation.render() on the randomisation block's string limits ---------

def test_violation_render_shows_string_limits_instead_of_crashing():
    v = Violation("randomization.year", "year 1800 is outside 1950-2050",
                  actual=1800.0, limit="1950-2050", unit="year")
    assert v.render() == ("[randomization.year] year 1800 is outside "
                          "1950-2050 (requested 1800 year, limit 1950-2050 "
                          "year)")
    assert "requested 3 aircraft, limit 2 aircraft" in Violation(
        "traffic.count", "m", actual=3, limit=2, unit="aircraft").render()
    assert "requested True" in Violation("x", "m", actual=True,
                                         limit=1.0).render()


def test_a_year_of_1800_renders_its_refusal(spec):
    """The report every CLI path prints: it used to raise
    ValueError("Unknown format code 'g' for object of type 'str'")."""
    spec.set("randomization.enabled", True)
    spec.set("randomization.year", 1800)
    report = validate(spec, check_feasibility=False)
    text = report.render()
    assert "[randomization.year]" in text
    assert "limit 1950-2050 year" in text
    spec.set("randomization.day_of_year_min", 400)
    spec.set("randomization.sun_elevation_min_deg", 95)
    text = validate(spec, check_feasibility=False).render()
    assert "limit 1-366 day" in text and "limit -90..90 deg" in text
