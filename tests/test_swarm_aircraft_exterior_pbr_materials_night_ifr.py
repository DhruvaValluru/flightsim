"""Lane aircraft_exterior.pbr_materials.night_ifr: what the Mac can check.

Code-level only: the bake's arithmetic, the file format, the gate's own
logic on synthetic images. None of it is a rendered frame or a visual
result; those are measured on the Windows laptop (INTEGRATION.md).
"""

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm" / "lanes" / "aircraft_exterior" / "pbr_materials" / "night_ifr"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"night_ifr_{name}", LANE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bake = _load("bake_night_pbr")
gate = _load("measure_gate")
SIZE = 256


@pytest.fixture(scope="module")
def fields():
    return bake.build_fields(SIZE)


@pytest.fixture(scope="module")
def mips(fields):
    return bake.build_mips(fields)


def test_the_period_holds_a_whole_number_of_panels():
    for pitch in bake.PANEL_PITCH_CM:
        assert (bake.PERIOD_CM / pitch).is_integer()


def test_the_noise_wraps(fields):
    """A tileable field has no seam: the step across the wrap is no larger
    than the steps inside the field."""
    noise = bake.spectral_noise(SIZE, np.random.default_rng(1), beta=2.2, low_cut=2.0)
    inside = np.abs(np.diff(noise, axis=1)).max()
    assert np.abs(noise[:, 0] - noise[:, -1]).max() <= inside * 1.5
    assert np.abs(noise[0, :] - noise[-1, :]).max() <= np.abs(np.diff(noise, axis=0)).max() * 1.5
    assert 0.0 <= noise.min() and noise.max() <= 1.0 and noise.std() > 0.05


def test_the_grooves_sit_on_the_panel_pitch(fields):
    """AO is lowest on the lines x = 0, 120, 240 cm and untouched mid-panel."""
    ao, texel = fields["ao"], fields["texel_cm"]
    on_line = int(round(120.0 / texel - 0.5))
    mid = int(round(60.0 / texel - 0.5))
    assert ao[:, on_line].mean() < 0.8
    assert ao[int(45.0 / texel), mid] == pytest.approx(1.0)
    assert ao.min() >= bake.AO_MIN - 1e-9


def test_the_baked_darkening_is_bounded(fields):
    """The dark-aircraft guard: grime can only take base colour to
    MIN_ALBEDO_GAIN, and occlusion is a separate channel."""
    assert fields["gain"].min() >= bake.MIN_ALBEDO_GAIN - 1e-9
    assert fields["gain"].max() <= 1.0
    assert fields["gain"].mean() > 0.8          # mostly clean paint, not a dirty one


def test_night_albedo_stays_in_the_calibrated_range():
    base = np.array([0.0, 0.01, 0.2, 0.5, 1.0])
    for gain in (0.0, bake.MIN_ALBEDO_GAIN, 1.0):
        out = bake.night_albedo(base, gain)
        assert out.min() >= bake.ALBEDO_MIN and out.max() <= bake.ALBEDO_MAX
    # a mid grey under the dirtiest texel keeps MIN_ALBEDO_GAIN of itself
    assert bake.night_albedo(0.2, 0.0) == pytest.approx(0.2 * bake.MIN_ALBEDO_GAIN)
    assert bake.night_albedo(0.2, 1.0) == pytest.approx(0.2)


def test_the_albedo_bounds_are_the_repos_own_numbers():
    sys.path.insert(0, str(REPO / "scripts"))
    import aircraft_look
    assert bake.ALBEDO_MAX == aircraft_look.CLASS_SCALARS["paint"]["AlbedoMax"]
    assert bake.ALBEDO_MIN == pytest.approx(min(aircraft_look.TIRE_ALBEDO), abs=5e-4)
    assert bake.PANEL_WIDTH_CM == aircraft_look.CLASS_SCALARS["paint"]["PanelWidthCm"]
    assert bake.ROUGHNESS_BREAKUP == aircraft_look.CLASS_SCALARS["paint"]["RoughnessBreakup"]
    assert tuple(bake.PANEL_PITCH_CM) == aircraft_look.CLASS_VECTORS["paint"]["PanelPitchCm"][:2]
    look = json.loads((REPO / "assets/aircraft_config/look/J11.json").read_text())
    assert look["class_scalars"]["paint"]["Roughness"] == bake.BAKED_BASE_ROUGHNESS


def test_the_gate_bounds_match_the_bake():
    # The albedo pass is linear (core/capture/labels.py read_albedo_png), so
    # the gate holds the bake's linear clamp, not an sRGB copy of it.
    assert gate.ALBEDO_LINEAR == (bake.ALBEDO_MIN, bake.ALBEDO_MAX)


def test_mip0_normals_are_unit_and_face_out(mips):
    normal = mips[0][1]
    assert np.allclose(np.linalg.norm(normal, axis=-1), 1.0, atol=1e-6)
    assert normal[..., 2].min() > 0.5
    assert np.abs(normal[..., :2]).max() > 0.02      # the grooves are really there


def test_the_mip_chain_is_complete(mips):
    assert len(mips) == int(np.log2(SIZE)) + 1
    assert [m[0].shape[0] for m in mips] == [SIZE >> i for i in range(len(mips))]


def test_roughness_widens_where_the_normals_disagree(mips, fields):
    """The specular antialiasing: a mip-1 texel over a groove is rougher than
    the plain average of the four roughnesses under it; one over flat paint
    is not."""
    plain = np.power(bake._box(np.power(fields["roughness"], 4.0)), 0.25)
    widened = mips[1][0][..., 1]
    length = mips[1][2]
    assert (widened >= plain - 1e-9).all()
    bumpy = length < 0.999
    assert bumpy.any()
    assert (widened[bumpy] - plain[bumpy]).mean() > 1e-3
    assert widened.max() <= bake.ROUGHNESS_MAX


def test_widening_is_clamped_and_zero_for_agreeing_normals():
    assert bake.widen_roughness(np.array(0.4), np.array(1.0)) == pytest.approx(0.4)
    capped = bake.widen_roughness(np.array(0.4), np.array(0.01))
    assert capped == pytest.approx((0.4 ** 4 + bake.SPECULAR_AA_CLAMP) ** 0.25)


def test_rivets_only_where_a_texel_can_hold_one():
    assert not bake.build_fields(512)["rivets"]
    assert bake.PERIOD_CM / 2048 <= bake.RIVET_MAX_TEXEL_CM < bake.PERIOD_CM / 1024


def test_the_dds_round_trips_with_every_mip(mips):
    orm, normal = bake.encode(mips)
    data = bake.dds_bytes(orm)
    assert data[:4] == b"DDS " and len(data) == 128 + sum(l.shape[0] * l.shape[1] * 4 for l in orm)
    back = bake.read_dds(data)
    assert len(back) == len(orm)
    assert all(np.array_equal(a, b) for a, b in zip(back, orm))
    # blue of the normal map is +Z: never below the mid grey
    assert normal[0][..., 2].min() > 190


def test_the_bake_is_deterministic_and_writes_what_the_tier_says(tmp_path):
    one = bake.bake_tier(0, tmp_path / "a", size=128)
    two = bake.bake_tier(0, tmp_path / "b", size=128)
    assert one["textures"]["orm"]["sha256"] == two["textures"]["orm"]["sha256"]
    assert "normal" not in one["textures"]          # tier 0 ships the ORM alone
    three = bake.bake_tier(1, tmp_path / "c", size=128)
    assert set(three["textures"]) == {"orm", "normal"}
    for record, folder in ((one, "a"), (three, "c")):
        for tex in record["textures"].values():
            data = (tmp_path / folder / tex["file"]).read_bytes()
            assert bake.sha256(data) == tex["sha256"] and len(data) == tex["bytes"]


def test_tiers_are_ordered_estimates_and_claim_nothing():
    sizes = [bake.vram_estimate_mb(t) for t in sorted(bake.TIERS)]
    assert sizes == sorted(sizes) and sizes[0] < 1.0
    assert not bake.TIERS[0]["clear_coat"] and not bake.TIERS[0]["procedural_wear"]
    text = json.dumps(bake.manifest([])).lower()
    assert "uncalibrated" in text and "visual-only" in text and "sustained" not in text


def test_the_committed_tier0_bake_matches_its_manifest():
    path = LANE / "baked" / "night_pbr.json"
    record = json.loads(path.read_text())
    assert record["schema"] == bake.SCHEMA
    tier0 = [t for t in record["tiers"] if t["tier"] == 0][0]
    for tex in tier0["textures"].values():
        assert bake.sha256((LANE / "baked" / tex["file"]).read_bytes()) == tex["sha256"]
    provenance = json.loads((LANE / "PROVENANCE.json").read_text())
    listed = {a["file"]: a["sha256"] for a in provenance["generated"]}
    for tex in tier0["textures"].values():
        assert listed[f"baked/{tex['file']}"] == tex["sha256"]
    assert all(s.get("licence") for s in provenance["sources"])
    assert not any("NC" in s["licence"].upper().split() for s in provenance["sources"])


# -- the gate's own logic, on synthetic frames and a fake run folder --------------
# None of this is a measurement: the gate has never seen a rendered frame.

def _scene(aircraft_luma, background=12.0):
    frame = np.full((64, 64), background)
    mask = np.zeros((64, 64), bool)
    mask[16:48, 16:48] = True
    frame[mask] = aircraft_luma
    return frame, mask


def test_gate_fails_a_darker_aircraft_and_passes_a_brighter_one():
    ref, mask = _scene(20.0)
    assert gate.measure(ref, _scene(14.0)[0], mask)["verdict"] == "FAIL"
    assert gate.measure(ref, _scene(26.0)[0], mask)["verdict"] == "PASS"


def test_gate_is_void_not_pass_when_it_cannot_measure():
    ref, mask = _scene(0.5)
    assert gate.measure(ref, _scene(0.6)[0], mask)["verdict"] == "VOID"   # black shot
    assert gate.measure(ref, ref, np.zeros_like(mask))["verdict"] == "VOID"   # no aircraft
    assert gate.measure(ref, ref[:32], mask)["verdict"] == "VOID"       # sizes differ


def test_gate_is_void_when_the_switch_changed_nothing():
    # A switch the build does not know leaves the aircraft pixel-identical;
    # that must never read as "not darker: PASS".
    ref, mask = _scene(20.0)
    result = gate.measure(ref, ref.copy(), mask)
    assert result["verdict"] == "VOID" and "identical" in result["why"]


def _albedos():
    """Reference and candidate base colour, linear: paint the night branch
    darkens a little, plus glass (near black) and a white light lens that it
    leaves alone."""
    ref = np.full((64, 64, 3), 0.40)
    ref[16:20, 16:48] = 0.005           # glass / tyre: below the paint range
    ref[44:48, 16:48] = 0.97            # a light lens: above it
    cand = ref.copy()
    cand[20:44, 16:48] = 0.36           # the paint the branch touched
    return ref, cand


def test_untouched_glass_tyres_and_lights_do_not_fail_the_albedo_clause():
    frame, mask = _scene(20.0)
    ref_albedo, cand_albedo = _albedos()
    result = gate.measure(frame, _scene(21.0)[0], mask, cand_albedo, ref_albedo)
    assert result["verdict"] == "PASS" and result["clauses"]["changed_albedo_in_range"]
    assert result["albedo_outside_fraction_whole_aircraft"] == pytest.approx(0.25)   # reported only
    assert result["albedo_changed_fraction"] == pytest.approx(0.75)
    assert result["albedo_changed_outside_fraction"] == 0.0


def test_gate_fails_when_the_branch_itself_pushes_paint_out_of_range():
    frame, mask = _scene(20.0)
    ref_albedo, cand_albedo = _albedos()
    cand_albedo[20:30, 16:48] = 0.01    # changed AND below the clamp
    result = gate.measure(frame, _scene(21.0)[0], mask, cand_albedo, ref_albedo)
    assert result["verdict"] == "FAIL" and not result["clauses"]["changed_albedo_in_range"]


def test_without_a_reference_albedo_the_range_is_reported_not_gated():
    frame, mask = _scene(20.0)
    result = gate.measure(frame, _scene(21.0)[0], mask, _albedos()[1])
    assert result["verdict"] == "PASS" and "changed_albedo_in_range" not in result["clauses"]
    assert "not gated" in result["albedo"]


def test_gate_fails_more_crushed_blacks():
    ref, mask = _scene(20.0)
    cand = _scene(30.0)[0]
    cand[16:24, 16:48] = 0.0
    result = gate.measure(ref, cand, mask)
    assert result["verdict"] == "FAIL" and not result["clauses"]["not_more_crushed"]


def test_the_mask_is_the_primary_airframes_id_not_every_object(tmp_path):
    from PIL import Image
    ids = np.zeros((8, 8), np.uint8)
    ids[:4] = 1                          # the primary airframe
    ids[4:6] = 2                         # something else with an id
    Image.fromarray(ids).save(tmp_path / "frame_0000_mask.png")
    assert gate.aircraft_mask(tmp_path / "frame_0000_mask.png").sum() == 32
    assert gate.aircraft_mask(tmp_path / "frame_0000_mask.png", (1, 2)).sum() == 48


def _fake_round(repo, number, run_id, night, luma_value, spec="abc"):
    """The files a visual round leaves, as scripts/visual_round.py and the web
    app name them. A fake: it shows the gate finds its inputs, nothing more."""
    from PIL import Image
    folder = repo / "runs" / "webapp" / run_id / "frames" / "tower"
    folder.mkdir(parents=True)
    frame, mask = _scene(luma_value)
    Image.fromarray(np.repeat(frame[..., None], 3, -1).astype(np.uint8)).save(folder / "frame_0000.png")
    Image.fromarray(frame.astype(np.uint8)).save(folder / "frame_0000_beauty_post.png")
    Image.fromarray(mask.astype(np.uint8)).save(folder / "frame_0000_mask.png")
    record = {"aircraft_look": {"night_pbr": {"tier": 0}}} if night else {"aircraft_look": {}}
    (folder / "render.json").write_text(json.dumps(record))
    out = repo / "docs" / "visual" / f"round_{number}"
    out.mkdir(parents=True)
    (out / "summary.json").write_text(json.dumps(
        [{"number": 16, "run_id": run_id, "spec_sha256": spec}]))


def test_the_gate_finds_a_rounds_frame_and_id_image(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gate, "REPO", tmp_path)
    monkeypatch.setattr(gate.round_inputs, "__defaults__", (tmp_path,))
    _fake_round(tmp_path, 90, "ref", night=False, luma_value=20.0)
    _fake_round(tmp_path, 91, "cand", night=True, luma_value=24.0)
    found = gate.round_inputs(91, 16)
    assert found["frame"].name == "frame_0000.png" and found["mask"].name == "frame_0000_mask.png"
    assert found["albedo"] is None and found["night_pbr_recorded"]
    args = ["--reference-round", "90", "--candidate-round", "91", "--scene", "16"]
    assert gate.main(args) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "PASS"


def test_the_gate_is_void_when_the_candidate_never_applied_the_switch(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gate.round_inputs, "__defaults__", (tmp_path,))
    _fake_round(tmp_path, 90, "ref", night=False, luma_value=20.0)
    _fake_round(tmp_path, 91, "cand", night=False, luma_value=24.0)
    args = ["--reference-round", "90", "--candidate-round", "91", "--scene", "16"]
    assert gate.main(args) == 2
    assert "night_pbr" in json.loads(capsys.readouterr().out)["why"]
    assert gate.main(["--reference-round", "90", "--candidate-round", "92", "--scene", "16"]) == 2


def test_the_gate_is_void_when_the_two_rounds_are_different_shots(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gate.round_inputs, "__defaults__", (tmp_path,))
    _fake_round(tmp_path, 90, "ref", night=False, luma_value=20.0, spec="abc")
    _fake_round(tmp_path, 91, "cand", night=True, luma_value=24.0, spec="xyz")
    assert gate.main(["--reference-round", "90", "--candidate-round", "91", "--scene", "16"]) == 2
    assert "different pinned specs" in json.loads(capsys.readouterr().out)["why"]


# -- the written command names only things the repository has ---------------------

def test_the_gate_command_uses_no_placeholder_and_no_switch_the_web_app_already_states():
    text = (LANE / "INTEGRATION.md").read_text(encoding="utf-8")
    commands = "\n".join(block for block in text.split("```powershell")[1:])
    commands = commands.split("```")[0]
    assert "<S>" not in text and "<" not in commands
    assert "-labels" not in commands                # webapp/capture.py states it itself
    assert '"-labels"' in (REPO / "webapp" / "capture.py").read_text(encoding="utf-8")
    assert "FLIGHTSIM_CAPTURE_PASSES" in (REPO / "webapp" / "capture.py").read_text(encoding="utf-8")
    script = (REPO / "scripts" / "visual_fix_round.ps1").read_text(encoding="utf-8")
    for word in ("-Round", "-Scenes", "-NoPush", "-Switches"):
        assert "$" + word[1:] in script


def test_the_night_switch_and_scene_are_stated_as_missing_while_they_are_missing():
    """The day an integrator lands them this test fails, and the "blocked"
    wording in INTEGRATION.md and PROVENANCE.json must be taken out with it."""
    sys.path.insert(0, str(REPO / "scripts"))
    import run_test_scenarios
    fx = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimAircraftFX.cpp"
    switch_exists = fx.is_file() and "aircraft-night-pbr" in fx.read_text(encoding="utf-8", errors="replace")
    night_scene = any(" at night" in prompt for _, prompt, _ in run_test_scenarios.SCENARIOS)
    text = (LANE / "INTEGRATION.md").read_text(encoding="utf-8")
    assert not switch_exists and not night_scene
    assert "BLOCKED" in text and f"scene {len(run_test_scenarios.SCENARIOS) + 1}" in text
