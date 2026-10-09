"""S1, the sensing wiring this item does not own: scene.sun_lux behind
the spec front door (absent-canonical inside the existing scene block,
the committed examples' digests pinned), the validator's refusals by
name, the registry's scene section with the sun's null pair run for
real, the run card's camera sensing keys, the capture manifest's
per-camera sensing block and per-frame radiometry on a real headless
capture, flightsim.verify's three checks NOT RUN on it, and the capture
command's --calibration / --sun-lux / --accumulate reaching the render
command (and the radiometry refused by name after a render that read
back no physical sun). Every flight here is a real JSBSim flight (the
c172p, 1 s; the B747 of examples/cameras_multi.yaml, 12 s).

These tests pass once S1's integration patches are applied on HEAD
d0529c1 (measured on a scratch worktree); on a tree without them they
fail by construction, which is the point of returning them.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.capture.radiometry import LENS_ATTENUATION_DEFAULT, luminance_per_unit
from core.messages import is_catalogued, render
from core.records import read_records
from core.registry import NO_NULL, REGISTRY
from core.scenario.blocks import SceneSpec
from core.scenario.camera import CameraSpec
from core.scenario.fields import Source
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate
from tests.engine_launch import launch_through_run
from tests.test_registry import EXAMPLE_DIGESTS

REPO = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
EXAMPLE = REPO / "examples/cameras_multi.yaml"


def spec_for(seconds: int = 1, sun_lux=None) -> ScenarioSpec:
    from core.nl.compiler import compile_prompt

    spec = compile_prompt(f"fly the c172p at 1500 m and 100 kt for {seconds} seconds")
    spec.set("hold_state", False, frm="test")
    if sun_lux is not None:
        spec.set("scene.sun_lux", sun_lux, frm="test")
    return spec


# -- the spec block ------------------------------------------------------------------------

def test_sun_lux_is_absent_canonical_inside_the_scene_block_and_every_example_keeps_its_digest():
    # W2 appended scene.buildings, W3 scene.night, optional the same way.
    assert SceneSpec.FIELD_ORDER == ("terrain_source", "terrain", "sun_lux", "buildings", "night")
    assert SceneSpec.OPTIONAL_FIELDS == ("sun_lux", "buildings", "night")
    assert SceneSpec.defaulted().sun_lux.value is None and SceneSpec.defaulted().sun_lux.unit == "lx"
    spec = spec_for()
    assert spec.scene.is_default() and "scene" not in spec.to_dict()
    for path, digest in EXAMPLE_DIGESTS.items():
        example = ScenarioSpec.read(REPO / path)
        assert example.digest() == digest, path
        data = example.to_dict()
        if "scene" in data:
            assert "sun_lux" not in data["scene"], path          # absent-canonical inside the block
            assert example.scene.sun_lux.value is None
    # The example that states a scene block round-trips without the field...
    mountain = ScenarioSpec.read(REPO / "examples/cameras_mountain_refusal.yaml")
    assert set(mountain.to_dict()["scene"]) == {"terrain_source", "terrain"}
    again = SceneSpec.from_dict(mountain.to_dict()["scene"])
    assert again.to_dict() == mountain.to_dict()["scene"]
    # ...and refuses an unknown field as every block does.
    with pytest.raises(ValueError, match="unknown fields"):
        SceneSpec.from_dict(dict(mountain.to_dict()["scene"], moon={"value": 1, "source": "user", "from": "x"}))


def test_a_stated_sun_is_behind_the_front_door_round_trips_and_changes_the_digest(tmp_path):
    spec = spec_for()
    before = spec.digest()
    spec.set("scene.sun_lux", 50000.0, frm="declared")
    assert spec.scene.sun_lux.source is Source.USER and spec.digest() != before
    data = spec.to_dict()["scene"]
    assert list(data) == ["terrain_source", "terrain", "sun_lux"]
    assert data["sun_lux"] == {"value": 50000.0, "unit": "lx", "source": "user", "from": "declared"}
    spec.write(tmp_path / "s.yaml")
    reread = ScenarioSpec.read(tmp_path / "s.yaml")
    assert reread.digest() == spec.digest() and reread.scene.sun_lux.value == 50000.0
    with pytest.raises(ValueError, match="never silently moved"):
        spec.plan("scene.sun_lux", 60000.0, frm="a planner")
    # A null pair's form: value null with source derived is a spec (lesson c).
    nulled = SceneSpec.from_dict(dict(data, sun_lux={"value": None, "unit": "lx", "source": "derived",
                                                    "from": "null pair"}))
    assert nulled.sun_lux.value is None and "sun_lux" in nulled.to_dict()


# -- the validator ------------------------------------------------------------------------

def test_the_validator_refuses_the_sun_the_compensation_the_band_file_and_a_profile_block_by_name(tmp_path, monkeypatch):
    report = validate(spec_for(sun_lux=200000.0), check_feasibility=False)
    assert [v.constraint for v in report.violations] == ["sensing.sun_lux"]
    assert "exceeds" in report.violations[0].message
    assert validate(spec_for(sun_lux=95788.0), check_feasibility=False).violations == []
    spec = spec_for()
    camera = CameraSpec.defaulted("c0", "chase", "c172p")
    camera.set("exposure_compensation_ev", "bright", frm="test")
    spec.cameras = [camera]
    assert "camera.exposure" in [v.constraint for v in validate(spec, check_feasibility=False).violations]
    camera.set("exposure_compensation_ev", 1.0, frm="test")
    camera.set("bands", "nowhere", frm="test")
    names = [v.constraint for v in validate(spec, check_feasibility=False).violations]
    assert names == ["sensing.band"]
    camera.set("bands", "rgb_proxy", frm="test")
    assert validate(spec, check_feasibility=False).violations == []
    # A profile whose optics block is malformed is refused by that block's name.
    import core.capture.profile as profile_module

    profiles = tmp_path / "profiles"
    profiles.mkdir()
    data = json.loads((REPO / "assets/camera_profiles/ideal_pinhole.json").read_text(encoding="utf-8"))
    data["name"] = "bad_optics"
    data["optics"] = {"model": "airy"}
    (profiles / "bad_optics.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(profile_module, "PROFILE_DIR", profiles)
    camera.set("profile", "bad_optics", frm="test")
    assert [v.constraint for v in validate(spec, check_feasibility=False).violations] == ["sensing.optics"]


# -- the registry and the null pair, run for real ----------------------------------------------

def test_the_scene_section_is_claimed_and_the_sun_s_null_pair_is_silent():
    from core.record_null import run_null_pair
    from core.registry import unregistered_fields

    assert "scene" in REGISTRY.sections()
    for name in ("scene.terrain_source", "scene.terrain", "scene.sun_lux"):
        entry = REGISTRY.get(name)
        assert entry.spec_path == name and entry.null_value is not NO_NULL and entry.effect_channels
    assert REGISTRY.get("scene.sun_lux").unit == "lx" and REGISTRY.get("scene.sun_lux").null_value is None
    for name in ("sensing.radiometry", "sensing.bands", "sensing.optics", "sensing.motion_blur"):
        assert REGISTRY.get(name).spec_path is None
    spec = spec_for(sun_lux=50000.0)
    assert unregistered_fields(spec.to_dict()) == []
    pair = run_null_pair(spec, "scene.sun_lux")
    assert pair.verdict == "silent" and pair.with_output_digest == pair.without_output_digest
    assert all(effect.peak_abs == 0.0 for effect in pair.effects)
    assert {e.channel for e in pair.effects} == {"lat_deg", "lon_deg"}
    assert pair.null_value is None


# -- the run card ---------------------------------------------------------------------------

def test_the_card_carries_the_camera_s_sensing_keys_only_when_stated():
    from core.capture.poses import solve_pose_track
    from core.capture.schedule import solve_schedule
    from tests.test_camera_poses import FRAME, make_columns

    spec = ScenarioSpec.read(EXAMPLE)
    columns = make_columns(duration_s=6.0)
    camera = spec.cameras[0]
    track = solve_pose_track(columns, camera, FRAME)
    schedule = solve_schedule(columns, camera, FRAME)
    assert "sensing" not in track.card_block(camera, schedule, FRAME)
    camera.set("exposure_compensation_ev", -1.0, frm="test")
    camera.set("bands", "rgb_proxy", frm="test")
    block = track.card_block(camera, schedule, FRAME)
    assert block["sensing"] == {"exposure_compensation_ev": -1.0, "bands": "rgb_proxy"}


# -- the capture manifest on a real headless capture ---------------------------------------------

@pytest.fixture(scope="module")
def sensing_capture(tmp_path_factory):
    """examples/cameras_multi.yaml with camera 0 stating EC +1 and the band
    proxy, captured headless (no render)."""
    from flightsim.capture import main as capture_main

    out = tmp_path_factory.mktemp("sensing")
    spec = ScenarioSpec.read(EXAMPLE)
    spec.cameras[0].set("exposure_compensation_ev", 1.0, frm="test")
    spec.cameras[0].set("bands", "rgb_proxy", frm="test")
    spec.write(out / "spec.yaml")
    assert capture_main([str(out / "spec.yaml"), "--out", str(out / "run"), "--max-previews", "0"]) == 0
    return out / "run", spec


def test_the_manifest_carries_the_sensing_block_the_frame_keys_and_the_records(sensing_capture):
    run_dir, spec = sensing_capture
    manifest = json.loads((run_dir / "capture_manifest.json").read_text(encoding="utf-8"))
    blocks = {c["camera_id"]: c for c in manifest["cameras"]}
    first = str(spec.cameras[0].camera_id.value)
    sensing = blocks[first]["sensing"]
    assert sensing["requested_by"] == ["camera"]
    r = sensing["radiometry"]
    from core.capture.exposure import ev100

    ev = ev100(*(float(spec.cameras[0].exposure._field(n).value) for n in ("aperture_f", "shutter_s", "iso")))
    assert r["ev100"] == pytest.approx(ev) and r["exposure_compensation_ev"] == 1.0
    assert r["lens_attenuation"] == LENS_ATTENUATION_DEFAULT
    assert r["luminance_cd_m2_per_unit"] == pytest.approx(luminance_per_unit(ev, 1.0))
    assert r["calibration_status"] == "predicted" and r["sun_lux"]["source"] == "model"
    assert r["sun_lux"]["value"] == pytest.approx(95788.0, abs=5.0)     # the noon look's 50 deg sun
    assert r["grey_card_predicted"] == pytest.approx(0.366, abs=0.01)   # 0.183 doubled by EC +1
    assert sensing["bands"]["k_band"]["green"] == pytest.approx(0.7588, abs=5e-4)
    assert sensing["optics"] is None and sensing["motion_blur"] is None
    assert sensing["records"] == "applied_variables (this camera)"
    # The other cameras asked for nothing: no key at all.
    for camera_id, block in blocks.items():
        if camera_id != first:
            assert "sensing" not in block
    for record in manifest["frames"]:
        if record["camera_id"] == first:
            assert record["radiometry"]["calibration_status"] == "predicted"
            assert record["radiometry"]["luminance_cd_m2_per_unit"] == pytest.approx(r["luminance_cd_m2_per_unit"])
            assert record["radiometry"]["exposure_units"] is None
        else:
            assert "radiometry" not in record
    names = [rec["name"] for rec in read_records(manifest["applied_variables"])]
    assert "sensing.radiometry" in names and "sensing.bands" in names
    by_name = {rec["name"]: rec for rec in read_records(manifest["applied_variables"])}
    assert by_name["sensing.radiometry"]["null_test"]["ok"] is True
    assert by_name["sensing.radiometry"]["null_test"]["kind"] == "reached"
    assert by_name["sensing.bands"]["null_test"]["ok"] is True and by_name["sensing.bands"]["null_test"]["kind"] == "bounded"
    assert by_name["sensing.radiometry"]["readback"]["agrees"] is True
    # A frame sidecar carries the same keys.
    sidecars = sorted((run_dir / "frames").rglob("*.json"))
    assert any("radiometry" in json.loads(p.read_text(encoding="utf-8")).get("frame", {})
               for p in sidecars if p.name.startswith("frame_"))


def test_a_spec_that_asks_for_nothing_gets_no_sensing_key(tmp_path):
    from flightsim.capture import main as capture_main

    assert capture_main([str(EXAMPLE), "--out", str(tmp_path / "plain"), "--max-previews", "0"]) == 0
    manifest = json.loads((tmp_path / "plain" / "capture_manifest.json").read_text(encoding="utf-8"))
    assert all("sensing" not in c for c in manifest["cameras"])
    assert all("radiometry" not in f for f in manifest["frames"])
    assert not [rec for rec in read_records(manifest["applied_variables"]) if rec["name"].startswith("sensing.")]


def test_the_verifier_reports_the_three_checks_not_run_on_the_capture(sensing_capture):
    run_dir, _ = sensing_capture
    completed = subprocess.run([PYTHON, "-m", "flightsim.verify", str(run_dir)],
                               capture_output=True, text=True, cwd=str(REPO))
    verdict = json.loads((run_dir / "verification.json").read_text(encoding="utf-8"))
    by_name = {c["name"]: c for c in verdict["checks"]}
    for name in ("psf_slanted_edge", "blur_vs_flow", "radiometry_grey_card"):
        assert by_name[name]["status"] == "NOT RUN", (name, by_name[name])
    assert "no calibration.json" in by_name["radiometry_grey_card"]["detail"]
    assert "sensing.optics" in by_name["psf_slanted_edge"]["detail"]
    assert completed.returncode in (0, 1)


# -- the capture command's sensing options ------------------------------------------------------

def _fake_subprocess(commands, wanted):
    real_run = subprocess.run

    def run(command, **kwargs):
        if not wanted(command):
            return real_run(command, **kwargs)
        commands.append([str(part) for part in command])

        class Done:
            returncode = 0
        return Done()
    return run


@pytest.fixture
def imported_repo(tmp_path, monkeypatch):
    import flightsim.capture as capture_module

    spec = ScenarioSpec.read(EXAMPLE)
    mesh = tmp_path / "assets" / "generated" / str(spec.aircraft.value) / "mesh_manifest.json"
    mesh.parent.mkdir(parents=True)
    mesh.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(capture_module, "REPO", tmp_path)
    return tmp_path, mesh


def _render_command(spec_path, out, monkeypatch, *extra):
    import assets_pipeline.importer as importer_module
    import core.util.platform as platform_module
    from flightsim.capture import main as capture_main

    commands = []
    monkeypatch.setattr(platform_module, "ue_available", lambda: True)
    monkeypatch.setattr(importer_module, "is_imported", lambda name: True)
    launch_through_run(monkeypatch)
    monkeypatch.setattr("subprocess.run", _fake_subprocess(
        commands, lambda c: any("render_ue_scenario" in str(p) for p in c)))
    code = capture_main([str(spec_path), "--out", str(out), "--max-previews", "0",
                         "--render", "--no-host-flight", *extra])
    return code, (commands[0] if commands else None)


def test_the_sensing_options_reach_the_render_command_and_a_bad_sun_is_refused_before_it(
        imported_repo, tmp_path, monkeypatch):
    code, command = _render_command(EXAMPLE, tmp_path / "asked", monkeypatch,
                                    "--calibration", "--sun-lux", "auto", "--accumulate", "4")
    assert code == 0
    tokens = [t for t in command if t.startswith(("-calibration", "-sun-lux=", "-accumulate="))]
    assert tokens[0] == "-calibration" and tokens[2] == "-accumulate=4"
    assert abs(float(tokens[1][len("-sun-lux="):]) - 95788.0) < 5.0       # the clear-sky model, noon look
    code, command = _render_command(EXAMPLE, tmp_path / "stated", monkeypatch, "--sun-lux", "50000")
    assert code == 0 and "-sun-lux=50000" in command
    code, command = _render_command(EXAMPLE, tmp_path / "plain", monkeypatch)
    assert code == 0 and not [t for t in command if t.startswith(("-calibration", "-sun-lux", "-accumulate"))]
    for bad in ("200000", "bright", "0"):
        code, command = _render_command(EXAMPLE, tmp_path / f"bad_{bad}", monkeypatch, "--sun-lux", bad)
        assert code == 2 and command is None                                # refused before any render


def test_after_a_render_without_a_physical_sun_the_radiometry_is_refused_by_name(imported_repo, tmp_path,
                                                                                 monkeypatch):
    spec = ScenarioSpec.read(EXAMPLE)
    spec.cameras[0].set("exposure_compensation_ev", 0.5, frm="test")
    spec.write(tmp_path / "spec.yaml")
    code, command = _render_command(tmp_path / "spec.yaml", tmp_path / "run", monkeypatch)
    assert code == 0
    manifest = json.loads((tmp_path / "run" / "capture_manifest.json").read_text(encoding="utf-8"))
    first = str(spec.cameras[0].camera_id.value)
    block = next(c for c in manifest["cameras"] if c["camera_id"] == first)
    assert block["sensing"]["radiometry"]["calibration_status"] == "refused"
    assert "sensing.exposure_units" in block["sensing"]["radiometry"]["calibration_basis"]
    frames = [f for f in manifest["frames"] if f["camera_id"] == first]
    assert frames and all(f["radiometry"]["exposure_units"]["constraint"] == "sensing.exposure_units"
                          for f in frames)
    assert all(f["radiometry"]["calibration_status"] == "refused" for f in frames)


# -- the catalogue -------------------------------------------------------------------------------

def test_every_sensing_name_has_a_catalogue_sentence():
    for name in ("sensing.radiometry", "sensing.band", "sensing.optics", "sensing.motion_blur",
                 "sensing.sun_lux", "sensing.exposure_units", "annotation.psf", "annotation.blur",
                 "annotation.radiometry", "check.psf_slanted_edge", "check.blur_vs_flow",
                 "check.radiometry_grey_card"):
        assert is_catalogued(name), name
        sentence = render(name, actual=200000.0, limit=133100.0, unit="lx")
        assert sentence and sentence != name and sentence[0].isupper(), name
