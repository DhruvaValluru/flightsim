"""Phase 10, package 7: domain randomisation as a spec block.

Sampled once from the block's own seed, written back as derived
fields, never touching a stated one, value-idempotent across planner
passes, refused by name when the stated window has no daylight -- and
the sun is where the cited algorithm puts it, not where a palette
says.
"""

import json
import math
from pathlib import Path

import pytest
import yaml

from core.nl.compiler import compile_prompt
from core.scenario.randomization import (
    EXPOSURE_CALIBRATION, FOG_CLEAR, FOG_HAZY, JITTER_BASE_KEY, MAX_SEED,
    RandomizationError, RandomizationSpec, card_block, declared_liveries,
    derive_block_seed, engine_sun_azimuth, exposure_for_elevation,
    render_look, sample_randomization,
)
from core.scenario.solar import julian_day, solar_position
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _spec(prompt="fly the 747 at 10000 ft and 280 kt for 60 seconds, chase view"):
    return compile_prompt(prompt)


def _enabled(seed=None, **fields):
    spec = _spec()
    spec.set("randomization.enabled", True, frm="test")
    if seed is not None:
        spec.set("randomization.seed", seed, frm="test")
    for name, value in fields.items():
        spec.set(f"randomization.{name}", value, frm="test")
    return spec


# -- the solar position ----------------------------------------------------

def test_julian_day_anchors_on_j2000_and_refuses_a_day_that_does_not_exist():
    assert julian_day(2000, 1, 12.0) == 2451545.0
    assert julian_day(2024, 366, 0.0) > julian_day(2024, 365, 0.0)
    with pytest.raises(ValueError):
        julian_day(2023, 366, 0.0)


def test_solstice_noon_at_london_matches_the_textbook():
    """90 - latitude + declination: 90 - 51.5 + 23.44 = 61.94 deg, sun
    due south (azimuth 180), declination 23.44 on the June solstice."""
    p = solar_position(51.5, 0.0, 2024, 173, 12.0)
    assert abs(p.elevation_deg - 61.94) < 0.3
    assert abs(p.declination_deg - 23.44) < 0.05
    assert abs(p.azimuth_deg - 180.0) < 2.0
    night = solar_position(51.5, 0.0, 2024, 173, 0.0)
    assert night.elevation_deg < 0.0
    morning = solar_position(51.5, 0.0, 2024, 173, 6.0)
    assert 0.0 < morning.azimuth_deg < 90.0            # north-east
    # Equinox, equator, at its own solar noon: the sun overhead.
    eq = solar_position(0.0, 0.0, 2024, 80, 12.0 - solar_position(
        0.0, 0.0, 2024, 80, 12.0).equation_of_time_min / 60.0)
    assert eq.elevation_deg > 89.5
    # Southern hemisphere summer noon: sun to the north.
    sydney = solar_position(-33.9, 151.2, 2024, 355, 2.0)
    assert sydney.elevation_deg > 75.0
    assert sydney.azimuth_deg > 300.0 or sydney.azimuth_deg < 60.0


# -- the block on the spec -------------------------------------------------

def test_a_default_block_is_absent_from_the_canonical_form_and_keeps_digests():
    """Absent IS the default: the canonical spec omits an all-default
    block, so a spec written before the block existed hashes the same,
    and a dict carrying an explicit default block normalises to it."""
    spec = _spec()
    assert "randomization" not in spec.to_dict()
    digest = spec.digest()
    explicit = spec.to_dict()
    explicit["randomization"] = RandomizationSpec.defaulted().to_dict()
    assert ScenarioSpec.from_dict(explicit).digest() == digest
    assert "randomization" not in ScenarioSpec.from_dict(explicit).to_dict()
    example = ScenarioSpec.read(EXAMPLES / "cameras_multi.yaml")
    assert "randomization" not in example.to_dict()


def test_enabling_the_block_changes_the_digest_and_round_trips(tmp_path):
    spec = _spec()
    before = spec.digest()
    spec.set("randomization.enabled", True, frm="test")
    assert spec.to_dict()["randomization"]["enabled"]["source"] == "user"
    assert spec.digest() != before
    path = spec.write(tmp_path / "s.yaml")
    reread = ScenarioSpec.read(path)
    assert reread.digest() == spec.digest()
    assert reread.randomization.is_enabled()
    assert "[randomization]" in spec.render_table()
    assert "[randomization]" not in _spec().render_table()


def test_unknown_missing_or_malformed_block_fields_refuse_by_name():
    spec = _enabled()
    data = spec.to_dict()
    data["randomization"]["invented"] = {"value": 1}
    with pytest.raises(ValueError, match="unknown fields"):
        ScenarioSpec.from_dict(data)
    data = spec.to_dict()
    del data["randomization"]["seed"]
    with pytest.raises(ValueError, match="missing required field seed"):
        ScenarioSpec.from_dict(data)
    data = spec.to_dict()
    data["randomization"] = "yes please"
    with pytest.raises(ValueError, match="must be a mapping"):
        ScenarioSpec.from_dict(data)


def test_plan_refuses_a_stated_block_field_and_a_bad_address():
    spec = _enabled(seed=5)
    with pytest.raises(ValueError, match="never silently moved"):
        spec.plan("randomization.seed", 6, frm="planner")
    spec.plan("randomization.fog_density", 0.002, frm="planner")
    assert str(spec.randomization.fog_density.source) == "derived"
    with pytest.raises(ValueError, match="not a randomization field"):
        spec.set("randomization.nope", 1)


# -- the sampler -------------------------------------------------------------

def test_sampling_is_deterministic_from_the_seed_and_changes_with_it():
    a, b = _enabled(), _enabled()
    sample_randomization(a)
    sample_randomization(b)
    assert a.to_dict() == b.to_dict()
    block = a.randomization
    assert int(block.seed.value) == derive_block_seed(int(a.seed.value))
    assert 0 < int(block.seed.value) < MAX_SEED
    assert str(block.seed.source) == "derived"
    other = _enabled()
    other.set("seed", 99, frm="a different run seed")
    sample_randomization(other)
    assert other.randomization.hour_utc.value != block.hour_utc.value
    assert other.randomization.fog_density.value != block.fog_density.value


def test_sampling_is_value_idempotent_across_planner_passes():
    """/compile and /run both run the sampler; the second pass must land
    on the same numbers -- including the camera jitter, which keeps the
    un-jittered base in the field's detail rather than jittering the
    jitter."""
    spec = _enabled()
    sample_randomization(spec)
    first = spec.to_dict()
    sample_randomization(spec)
    assert spec.to_dict() == first
    camera = spec.cameras[0]
    assert camera.offset_forward_m.detail[JITTER_BASE_KEY] == -110.0
    assert str(camera.offset_forward_m.source) == "derived"
    assert camera.offset_forward_m.value != -110.0
    # Round trip through YAML and a third pass: still the same.
    reread = ScenarioSpec.from_dict(json.loads(json.dumps(first)))
    sample_randomization(reread)
    assert reread.to_dict() == first


def test_the_jitter_never_moves_a_stated_camera_field_and_says_so():
    spec = _enabled()
    spec.set("cameras[0].offset_forward_m", -120.0, frm="stated by the test")
    sample_randomization(spec)
    camera = spec.cameras[0]
    assert camera.offset_forward_m.value == -120.0
    assert str(camera.offset_forward_m.source) == "user"
    assert JITTER_BASE_KEY not in camera.offset_forward_m.detail
    notes = [n for n in spec.notes if "offset_forward_m" in n]
    assert len(notes) == 1 and "not jittered" in notes[0]
    sample_randomization(spec)
    assert len([n for n in spec.notes if "offset_forward_m" in n]) == 1
    # The others moved, within the stated bounds.
    jm = float(spec.randomization.camera_jitter_m.value)
    assert 0.0 < abs(camera.offset_right_m.value) <= jm
    assert abs(camera.offset_up_m.value - 12.0) <= jm
    jf = float(spec.randomization.camera_focal_jitter.value)
    assert abs(camera.focal_length_mm.value / 35.0 - 1.0) <= jf
    # An aircraft-aimed offset camera has no aim angles to jitter.
    assert camera.aim_bearing_deg.value == 0.0


def test_the_sun_is_where_the_algorithm_puts_it_and_the_look_follows():
    spec = _enabled()
    sample_randomization(spec)
    block = spec.randomization
    assert str(block.day_of_year.source) == "derived"
    position = solar_position(float(spec.latitude.value),
                              float(spec.longitude.value),
                              int(block.year.value), int(block.day_of_year.value),
                              float(block.hour_utc.value))
    assert abs(position.elevation_deg - float(block.sun_elevation_deg.value)) < 1e-3
    assert abs(position.azimuth_deg - float(block.sun_azimuth_deg.value)) < 1e-3
    assert float(block.sun_elevation_deg.value) >= float(block.sun_elevation_min_deg.value)
    assert float(block.exposure_bias.value) == pytest.approx(
        exposure_for_elevation(float(block.sun_elevation_deg.value)), abs=1e-3)
    assert FOG_CLEAR <= float(block.fog_density.value) <= FOG_HAZY
    assert "Meeus" in block.sun_elevation_deg.frm
    look = render_look(spec)
    assert look["sun_elev"] == float(block.sun_elevation_deg.value)
    assert look["sun_azim"] == engine_sun_azimuth(float(block.sun_azimuth_deg.value))
    assert look["fog_density"] == float(block.fog_density.value)


def test_exposure_and_fog_come_from_the_calibrated_look_points_only():
    """Gotcha 6/7: no palette is invented. The interpolation's anchors
    ARE the harness's probe-calibrated dawn and noon, and the fog range
    is its clear and hazy."""
    from experiments.showcase_matrix import TIME_OF_DAY, VISIBILITY

    dawn, noon = TIME_OF_DAY["dawn"], TIME_OF_DAY["noon"]
    assert EXPOSURE_CALIBRATION == ((dawn["sun_elev"], dawn["exposure_bias"]),
                                    (noon["sun_elev"], noon["exposure_bias"]))
    assert (FOG_CLEAR, FOG_HAZY) == (VISIBILITY["clear"], VISIBILITY["hazy"])
    assert exposure_for_elevation(8.0) == 10.5
    assert exposure_for_elevation(50.0) == 9.5
    assert exposure_for_elevation(29.0) == pytest.approx(10.0)
    assert exposure_for_elevation(2.0) == 10.5          # clamped, not extrapolated
    assert exposure_for_elevation(85.0) == 9.5


def test_the_engine_azimuth_points_the_light_at_the_sun():
    """Scene frame X east, Y north; a rotator's yaw psi points along
    (cos psi, sin psi). The yaw the commandlet is given must point
    TOWARD the sun's compass bearing."""
    for compass, east, north in ((90.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                                 (180.0, 0.0, -1.0), (270.0, -1.0, 0.0),
                                 (45.0, math.sqrt(0.5), math.sqrt(0.5))):
        yaw = math.radians(engine_sun_azimuth(compass))
        assert math.cos(yaw) == pytest.approx(east, abs=1e-9)
        assert math.sin(yaw) == pytest.approx(north, abs=1e-9)
    assert 0.0 <= engine_sun_azimuth(-30.0) < 360.0


def test_a_window_with_no_daylight_refuses_by_name():
    spec = _enabled(hour_utc_min=0.0, hour_utc_max=1.0,
                    day_of_year_min=355, day_of_year_max=356)
    spec.set("latitude", 51.5, frm="test")
    spec.set("longitude", 0.0, frm="test")
    with pytest.raises(RandomizationError) as caught:
        sample_randomization(spec)
    assert caught.value.constraint == "randomization.time_of_day"
    assert "daylight" in caught.value.message
    # Stated day AND hour below the floor: one check, one refusal.
    stated = _enabled(day_of_year=355, hour_utc=0.5)
    stated.set("latitude", 51.5, frm="test")
    stated.set("longitude", 0.0, frm="test")
    with pytest.raises(RandomizationError):
        sample_randomization(stated)


def test_a_stated_day_and_hour_are_used_not_drawn():
    spec = _enabled(day_of_year=173, hour_utc=12.0)
    spec.set("latitude", 51.5, frm="test")
    spec.set("longitude", 0.0, frm="test")
    sample_randomization(spec)
    block = spec.randomization
    assert str(block.day_of_year.source) == "user"
    assert abs(float(block.sun_elevation_deg.value) - 61.94) < 0.3
    assert str(block.sun_elevation_deg.source) == "derived"


def test_render_look_is_none_when_off_and_refuses_an_unsampled_block():
    assert render_look(_spec()) is None
    assert card_block(_spec()) is None
    with pytest.raises(RandomizationError) as caught:
        render_look(_enabled())
    assert caught.value.constraint == "randomization.unsampled"


def test_livery_samples_only_declared_variants(tmp_path):
    (tmp_path / "B747.json").write_text(json.dumps({"liveries": ["red", "blue"]}), encoding="utf-8")
    assert declared_liveries("B747", tmp_path) == ["red", "blue"]
    assert declared_liveries("c172p", tmp_path) == []
    spec = _enabled()
    sample_randomization(spec, config_dir=tmp_path)
    assert spec.randomization.livery.value in ("red", "blue")
    plain = _enabled()
    sample_randomization(plain)
    assert plain.randomization.livery.value == "default"
    assert "declares no livery variants" in plain.randomization.livery.frm
    (tmp_path / "B747.json").write_text(json.dumps({"liveries": [1]}), encoding="utf-8")
    with pytest.raises(RandomizationError) as caught:
        sample_randomization(_enabled(), config_dir=tmp_path)
    assert caught.value.constraint == "randomization.livery"


# -- what the render, the card and the endpoints get -------------------------

def test_the_render_look_selector_prefers_the_sample_over_the_storm_look():
    from webapp.runs import STORM_LOOK, render_look_for

    assert render_look_for(_spec(), None) is None
    assert render_look_for(_spec(), "thunderstorm") == STORM_LOOK
    spec = _enabled()
    sample_randomization(spec)
    assert render_look_for(spec, "thunderstorm") == render_look(spec)


def test_the_render_command_carries_the_sampled_look(tmp_path, monkeypatch):
    import webapp.runs as runs

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = list(command)

        class Result:
            returncode = 0
        return Result()

    monkeypatch.setattr(runs.subprocess, "run", fake_run)
    spec = _enabled()
    sample_randomization(spec)
    look = runs.render_look_for(spec, None)
    runs.RunManager._render(tmp_path / "card.json", tmp_path / "frames",
                            {"key": "flat", "terrain": None, "imagery": None},
                            tmp_path / "missing_mesh.json", "B747",
                            look=look,
                            camera_flags=runs.camera_render_flags(spec))
    command = captured["command"]
    assert f"-sun-elev={look['sun_elev']}" in command
    assert f"-sun-azim={look['sun_azim']}" in command
    assert f"-exposure-bias={look['exposure_bias']}" in command
    assert f"-fog-density={look['fog_density']}" in command


def test_the_card_carries_the_block_only_when_on(tmp_path):
    from core.scenario.card import write_run_card

    spec = _enabled()
    sample_randomization(spec)
    card = json.loads(write_run_card(
        spec, tmp_path / "card.json",
        randomization=card_block(spec)).read_text(encoding="utf-8"))
    block = card["randomization"]
    assert block["engine_sun_azimuth_deg"] == engine_sun_azimuth(block["sun_azimuth_deg"])
    assert block["livery"] == "default"
    assert "Meeus" in block["solar_source"]
    moved = block["camera_jitter"]["chase"]      # regex camera ids are the preset names
    assert moved["offset_forward_m"]["base"] == -110.0
    assert moved["offset_forward_m"]["delta"] == pytest.approx(
        moved["offset_forward_m"]["value"] + 110.0, abs=1e-6)
    plain = json.loads(write_run_card(
        _spec(), tmp_path / "plain.json",
        randomization=card_block(_spec())).read_text(encoding="utf-8"))
    assert "randomization" not in plain


def test_validation_refuses_bad_ranges_by_name():
    spec = _enabled(day_of_year_min=200, day_of_year_max=100,
                    fog_density_min=0.0, year=1800, camera_jitter_m=-1.0)
    spec.set("randomization.enabled", "false", frm="a string")
    names = {v.constraint for v in validate(spec, check_feasibility=False).violations}
    assert {"randomization.enabled", "randomization.year",
            "randomization.day_of_year_max", "randomization.fog_density_min",
            "randomization.camera_jitter_m"} <= names
    assert validate(_enabled(), check_feasibility=False).ok


def test_the_endpoints_carry_the_block_and_run_refuses_no_daylight_by_name():
    from fastapi.testclient import TestClient

    from webapp.server import app

    client = TestClient(app)
    compiled = client.post("/compile", json={
        "prompt": "fly the 747 at 3000 m and 250 kt", "compiler": "regex"}).json()
    rows = {row["name"]: row for row in compiled["spec"]["randomization"]}
    assert rows["enabled"]["value"] is False
    assert "randomization" in compiled["spec"]["dict"]     # editable on the page
    assert "randomization" not in ScenarioSpec.from_dict(
        compiled["spec"]["dict"]).to_dict()                 # ...and canonical off
    # A floor no sun reaches (89.9 deg) at the prompt's own place: the
    # sampler refuses by name on /run, whatever the location.
    edited = compiled["spec"]["dict"]
    for name, value in (("enabled", True), ("sun_elevation_min_deg", 89.9)):
        edited["randomization"][name]["value"] = value
        edited["randomization"][name]["source"] = "user"
    response = client.post("/run", json={"spec": edited})
    assert response.status_code == 409
    assert response.json()["refused"] == "validation"
    assert any(v["constraint"] == "randomization.time_of_day"
               for v in response.json()["violations"])


def test_the_capture_command_samples_records_and_prints_the_block(tmp_path, capsys):
    """python -m flightsim.capture over the committed randomised example:
    the block draws on this path too, the card and the manifest carry
    the same sampled dict, and every frame's sidecar has it."""
    from flightsim.capture import main as capture_main

    out = tmp_path / "run"
    code = capture_main([str(EXAMPLES / "randomized.yaml"), "--out", str(out),
                         "--max-previews", "1", "--card"])
    assert code == 0
    printed = capsys.readouterr().out
    assert "randomization: seed 7" in printed
    card = json.loads((out / "card.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "capture_manifest.json").read_text(encoding="utf-8"))
    assert card["randomization"] == manifest["randomization"]
    assert manifest["randomization"]["seed"] == 7
    sidecar = json.loads(next((out / "frames").rglob("frame_0000.json")).read_text(encoding="utf-8"))
    assert sidecar["context"]["randomization"] == manifest["randomization"]
    # The example's own spec, re-read from the run, still says so.
    written = yaml.safe_load((out / "scenario.yaml").read_text(encoding="utf-8"))
    assert written["randomization"]["sun_elevation_deg"]["source"] == "derived"
