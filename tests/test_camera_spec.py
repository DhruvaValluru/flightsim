"""Camera Phase 1, package A: the camera as a spec element.

Cameras are provenanced Quantitys on the spec (version 6), digest-
relevant, addressable through the same set()/plan() front door -- and an
EMPTY camera list drives the render pipeline with byte-identical
commandlet arguments to the pre-camera build. That last claim is the
load-bearing one: it is a test here, not an intention.
"""

import pytest

from core.nl.compiler import compile_prompt
from core.scenario.camera import (
    CHASE_OFFSETS, CameraSpec, default_cameras,
)
from core.scenario.fields import Source
from core.scenario.spec import ScenarioSpec


@pytest.fixture
def spec():
    return compile_prompt("fly the 747 at 10000 ft and 280 kt for 60 seconds")


@pytest.fixture
def spec_with_camera(spec):
    spec.cameras = [CameraSpec.defaulted(
        camera_id="main", preset="chase", aircraft="B747")]
    return spec


# -- serialisation and identity -----------------------------------------

def test_cameras_serialize_as_an_always_present_list(spec):
    """One spelling of "no cameras": the canonical form always carries
    the list, so the digest cannot fork on absent-vs-empty."""
    assert spec.to_dict()["cameras"] == []


def test_yaml_round_trip_preserves_the_digest(spec_with_camera, tmp_path):
    spec_with_camera.cameras[0].moves = [
        {"t_s": 0.0, "focal_length_mm": 35.0},
        {"t_s": 10.0, "focal_length_mm": 85.0},
    ]
    path = spec_with_camera.write(tmp_path / "s.yaml")
    reread = ScenarioSpec.read(path)
    assert reread.digest() == spec_with_camera.digest()
    assert reread.cameras[0].moves == spec_with_camera.cameras[0].moves


def test_specs_differing_only_in_cameras_hash_differently(spec):
    before = spec.digest()
    spec.cameras = [CameraSpec.defaulted(camera_id="main", aircraft="B747")]
    with_camera = spec.digest()
    assert with_camera != before
    spec.set("cameras[0].focal_length_mm", 85.0, frm="tighter framing")
    assert spec.digest() != with_camera


def test_spec_version_5_documents_refuse_by_name(spec_with_camera):
    data = spec_with_camera.to_dict()
    data["spec_version"] = 5
    with pytest.raises(ValueError, match="not supported"):
        ScenarioSpec.from_dict(data)


def test_unknown_camera_field_is_refused(spec_with_camera):
    data = spec_with_camera.to_dict()
    data["cameras"][0]["zoom_factor"] = {"value": 2.0, "source": "user"}
    with pytest.raises(ValueError, match="unknown fields"):
        ScenarioSpec.from_dict(data)


def test_missing_camera_field_is_refused(spec_with_camera):
    data = spec_with_camera.to_dict()
    del data["cameras"][0]["focal_length_mm"]
    with pytest.raises(ValueError, match="missing required field"):
        ScenarioSpec.from_dict(data)


def test_camera_provenance_round_trips(spec_with_camera):
    spec_with_camera.cameras[0].set("focal_length_mm", 50.0,
                                    frm="stated 50 mm")
    reread = ScenarioSpec.from_dict(spec_with_camera.to_dict())
    q = reread.cameras[0].focal_length_mm
    assert q.value == 50.0
    assert q.source is Source.USER
    assert q.frm == "stated 50 mm"


# -- attribution: set() and plan() through the spec front door ----------

def test_camera_field_edit_becomes_source_user(spec_with_camera):
    spec_with_camera.set("cameras[0].focal_length_mm", 85.0,
                         frm="edited in the web UI")
    q = spec_with_camera.cameras[0].focal_length_mm
    assert q.source is Source.USER and q.value == 85.0


def test_plan_moves_a_defaulted_camera_field(spec_with_camera):
    spec_with_camera.plan("cameras[0].position_alt_m", 500.0,
                          frm="raised above terrain")
    assert spec_with_camera.cameras[0].position_alt_m.source is Source.DERIVED


def test_plan_refuses_a_user_stated_camera_field(spec_with_camera):
    spec_with_camera.set("cameras[0].focal_length_mm", 85.0)
    with pytest.raises(ValueError, match="never.*moved"):
        spec_with_camera.plan("cameras[0].focal_length_mm", 35.0,
                              frm="planner tried to move it")


def test_addressing_a_nonexistent_camera_is_refused(spec_with_camera):
    with pytest.raises(ValueError, match="does not exist"):
        spec_with_camera.set("cameras[3].focal_length_mm", 50.0)
    with pytest.raises(ValueError, match="not a camera field"):
        spec_with_camera.set("cameras[0].not_a_field", 50.0)


def test_render_table_shows_camera_blocks(spec_with_camera):
    table = spec_with_camera.render_table()
    assert "camera[0] main" in table
    assert "focal length mm" in table


# -- the documented default camera --------------------------------------

def test_default_cameras_is_the_webapp_chase(spec):
    cameras = default_cameras(spec)
    assert len(cameras) == 1
    camera = cameras[0]
    assert str(camera.preset.value) == "chase"
    forward, right, up = CHASE_OFFSETS["B747"]
    assert float(camera.offset_forward_m.value) == forward
    assert float(camera.offset_right_m.value) == right
    assert float(camera.offset_up_m.value) == up
    assert all(str(q.source) == "default" for _, q in camera.quantities())


def test_default_cameras_tornado_core_flies_wingman():
    spec = compile_prompt("fly the 747 through a tornado")
    assert str(spec.weather_event.detail.get("aim")) == "core"
    assert str(default_cameras(spec)[0].preset.value) == "wingman"
    flyby = compile_prompt("fly the 747 past a tornado")
    assert str(default_cameras(flyby)[0].preset.value) == "chase"


# -- byte-identical commandlet arguments for a camera-less spec ---------

def _historic_command(card, frames, aircraft):
    """The pre-camera build's argument list, reconstructed VERBATIM from
    webapp/runs.py as it stood before Camera Phase 1 (a chase render of
    a flat scene, no mesh, no telemetry, default look)."""
    from experiments.showcase_matrix import (
        EDITOR, FPS, HEIGHT, TIME_OF_DAY, VISIBILITY, WIDTH,
    )
    from webapp.runs import REPO, WEBAPP_CHASE

    project = REPO / "ue" / "FlightSim.uproject"
    tod = TIME_OF_DAY["noon"]
    return [
        str(EDITOR), str(project), "-run=FlightSimBridge.FlightSimRender",
        f"-scenario={card}", f"-frames={frames}",
        "-Visual", "-shot=showcase",
        f"-chase={WEBAPP_CHASE.get(aircraft, '-110:0:12')}",
        "-camera=chase",
        f"-fps={FPS}", f"-width={WIDTH}", f"-height={HEIGHT}",
        f"-sun-elev={tod['sun_elev']}", f"-sun-azim={tod['sun_azim']}",
        f"-exposure-bias={tod['exposure_bias']}",
        f"-fog-density={VISIBILITY['clear']}",
        "-unattended", "-nopause", "-nosplash",
        "-stdout", "-FullStdOutLogOutput",
        "-RenderOffScreen", "-AllowCommandletRendering",
    ]


def test_cameraless_spec_builds_byte_identical_commandlet_args(
        spec, tmp_path, monkeypatch):
    """The whole point of the empty-list default: no camera stated ==
    exactly the current behaviour, proven on the real command builder."""
    import webapp.runs as runs

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = list(command)

        class Result:
            returncode = 0
        return Result()

    monkeypatch.setattr(runs.subprocess, "run", fake_run)
    card = tmp_path / "card.json"
    frames = tmp_path / "frames"
    scene = {"key": "flat", "terrain": None, "imagery": None}
    runs.RunManager._render(card, frames, scene,
                            tmp_path / "missing_mesh.json", "B747",
                            camera_flags=runs.camera_render_flags(spec))
    assert captured["command"] == _historic_command(card, frames, "B747")


def test_camera_flags_for_the_tornado_core_default(monkeypatch):
    from webapp.runs import camera_render_flags

    spec = compile_prompt("fly the 747 through a tornado")
    inline, trailing = camera_render_flags(spec)
    assert inline == ["-chase=-110:0:12", "-camera=wingman"]
    assert trailing == ["-wingman-abeam=180"]


def test_stated_camera_offsets_reach_the_flags():
    from webapp.runs import camera_render_flags

    spec = compile_prompt("fly the 747 at 280 kt")
    spec.cameras = [CameraSpec.defaulted(camera_id="near", preset="chase",
                                         aircraft="B747")]
    spec.set("cameras[0].offset_forward_m", -60.0, frm="closer")
    inline, trailing = camera_render_flags(spec)
    assert inline == ["-chase=-60:0:12", "-camera=chase"]
    assert trailing == []


def test_unsupported_preset_refuses_by_name():
    from webapp.runs import camera_render_flags

    spec = compile_prompt("fly the 747 at 280 kt")
    spec.cameras = [CameraSpec.defaulted(camera_id="free", preset="explicit")]
    with pytest.raises(ValueError, match="camera.preset"):
        camera_render_flags(spec)


# -- planned camera defaults (the planners' discipline, on cameras) -----

def test_defaulted_tower_camera_follows_the_staged_terrain():
    """A placeless prompt's tower camera is built against flat ground;
    when the scene planners stage terrain, the SYSTEM's own camera is
    re-planned onto the final datum (recorded, source derived) instead
    of being refused kilometres underground -- measured on the first
    3-second tower demo (camera.terrain_clearance at -2803 m AGL)."""
    from webapp.runs import plan_camera_defaults

    spec = compile_prompt(
        "fly the 747 at 3000 m and 250 kt, 15 images from the tower")
    camera = spec.cameras[0]
    assert float(camera.position_alt_m.value) == 80.0     # flat + 80
    spec.plan("terrain_elevation", 2900.0, frm="staged by the test")
    plan_camera_defaults(spec)
    assert float(camera.position_alt_m.value) == 2980.0
    assert str(camera.position_alt_m.source) == "derived"
    # Value-idempotent: planning again from the same scene moves nothing.
    plan_camera_defaults(spec)
    assert float(camera.position_alt_m.value) == 2980.0


def test_stated_camera_placement_is_never_replanned():
    from webapp.runs import plan_camera_defaults

    spec = compile_prompt(
        "fly the 747 at 3000 m and 250 kt, 15 images from the tower")
    spec.set("cameras[0].position_alt_m", 80.0, frm="stated placement")
    spec.plan("terrain_elevation", 2900.0, frm="staged by the test")
    plan_camera_defaults(spec)
    assert float(spec.cameras[0].position_alt_m.value) == 80.0
    assert str(spec.cameras[0].position_alt_m.source) == "user"


def test_offset_cameras_are_not_touched_by_the_camera_planner():
    from webapp.runs import plan_camera_defaults

    spec = compile_prompt("chase view of the 747 at 3000 m and 250 kt")
    before = spec.cameras[0].to_dict()
    spec.plan("terrain_elevation", 2900.0, frm="staged by the test")
    plan_camera_defaults(spec)
    assert spec.cameras[0].to_dict() == before


def test_moves_carry_their_provenance_through_the_round_trip(spec_with_camera,
                                                             tmp_path):
    """The moves list is one recorded decision, so it carries one source
    word and one note (``moves_source`` / ``moves_from``) beside it,
    serialised only when there are moves, digest-relevant like every
    field's source, preserved by the YAML round trip; an absent source
    is None (the table says "no recorded source"), and a word outside
    Source is refused by name -- never guessed."""
    camera = spec_with_camera.cameras[0]
    assert "moves_source" not in camera.to_dict()       # no moves, no source
    camera.moves = [{"t_s": 0.0, "focal_length_mm": 35.0},
                    {"t_s": 10.0, "focal_length_mm": 85.0}]
    unrecorded = camera.to_dict()
    assert unrecorded["moves_source"] is None and unrecorded["moves_from"] is None
    digest_unrecorded = spec_with_camera.digest()
    camera.set_moves(camera.moves, frm="stated: zoom 35 to 85 mm over 10 s")
    assert camera.moves_source == "user"
    assert camera.moves_from == "stated: zoom 35 to 85 mm over 10 s"
    assert spec_with_camera.digest() != digest_unrecorded
    path = spec_with_camera.write(tmp_path / "moves.yaml")
    reread = ScenarioSpec.read(path)
    assert reread.digest() == spec_with_camera.digest()
    assert reread.cameras[0].moves == camera.moves
    assert reread.cameras[0].moves_source == "user"
    assert reread.cameras[0].moves_from == "stated: zoom 35 to 85 mm over 10 s"
    camera.set_moves(camera.moves, frm="a planner's dolly", source=Source.DERIVED)
    assert camera.to_dict()["moves_source"] == "derived"
    bad = spec_with_camera.to_dict()
    bad["cameras"][0]["moves_source"] = "planner"
    with pytest.raises(ValueError, match="moves_source.*'planner'"):
        ScenarioSpec.from_dict(bad)
    with pytest.raises(ValueError, match="moves source must be one of"):
        camera.set_moves(camera.moves, frm="x", source="planner")
