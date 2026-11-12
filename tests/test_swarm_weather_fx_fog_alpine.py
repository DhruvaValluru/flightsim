"""Source-level checks for the alpine valley-fog lane (Mac).

These check the bake's arithmetic against closed forms and the pixel gate's
fit on synthetic images. They are NOT a render or pixel result: that is
measured on the Windows laptop (see the lane's INTEGRATION.md).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm" / "lanes" / "weather_fx" / "fog" / "alpine"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"alpine_fog_{name}", LANE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bake = _load("bake_alpine_fog")


@pytest.fixture(scope="module")
def rgba():
    return bake.relief_rgba()


def test_fog_top_is_the_unit_optical_depth_surface():
    assert bake.vertical_tau(bake.FOG_TOP_M) == pytest.approx(1.0)
    # the column is the integral of the density (midpoint rule, 1 m steps)
    numeric = sum(bake.sigma_per_m(z + 0.5) for z in range(1600, 9000))
    assert numeric == pytest.approx(bake.vertical_tau(1600.0), rel=1e-4)


def test_valley_is_fog_and_the_peaks_are_clear():
    assert bake.visibility_m(bake.VALLEY_FLOOR_M) < 1000.0   # WMO: fog is under 1 km
    assert bake.visibility_m(bake.VALLEY_FLOOR_M) > 50.0
    # above 2700 m the layer leaves the air to the aerial-perspective lane
    assert bake.vertical_tau(2700.0) < 0.02
    assert bake.transmittance(bake.slant_tau(5000.0, 3500.0, 10.0)) > 0.99


def test_engine_numbers_round_trip_to_the_model():
    eng = bake.engine_fog()
    # the repo's own constant (core/scene/weather_visuals.py)
    from core.scene import weather_visuals
    assert bake.ENGINE_FOG_DENSITY_PER_EXTINCTION == pytest.approx(
        weather_visuals.ENGINE_FOG_DENSITY_PER_EXTINCTION)
    assert bake.KOSCHMIEDER == pytest.approx(
        weather_visuals.fog_extinction_per_m(1.0) * 1000.0, rel=2e-3)
    # the engine's law: beta = D * 0.1 ln2^2 * 2^(-(F / 10) * dz_m)
    for dz in (-300.0, 0.0, 400.0):
        beta = (eng["FogDensity"] * 0.1 * math.log(2.0) ** 2
                * 2.0 ** (-(eng["FogHeightFalloff"] / 10.0) * dz))
        assert beta == pytest.approx(bake.sigma_per_m(bake.FOG_TOP_M + dz), rel=1e-9)
    # the engine clamps the ray's exponent at -127: never reached in this frame
    assert eng["FogHeightFalloff"] / 10.0 * (5000.0 - 1600.0) < 127.0


def test_slant_path_and_opacity_floor():
    assert bake.slant_tau(5000.0, 1600.0, 90.0) == pytest.approx(
        bake.vertical_tau(1600.0) - bake.vertical_tau(5000.0))
    assert bake.slant_tau(5000.0, 1600.0, 30.0) == pytest.approx(
        2.0 * bake.slant_tau(5000.0, 1600.0, 90.0))
    assert bake.transmittance(50.0) == pytest.approx(1.0 - bake.MAX_OPACITY)
    with pytest.raises(ValueError):
        bake.slant_tau(1500.0, 1600.0, 30.0)


def test_brightness_model():
    assert bake.two_stream_albedo(0.0) == 0.0
    assert bake.two_stream_albedo(1e9) == pytest.approx(1.0)
    assert bake.layer_over_ground_albedo(0.0, 0.35) == pytest.approx(0.35)
    assert bake.layer_over_ground_albedo(0.3, 1.0) == pytest.approx(1.0)
    albedo = bake.fog_albedo()
    assert 0.25 < albedo < bake.SNOW_ALBEDO     # the fog reads darker than sunlit snow
    for elevation in (15.0, 30.0, 50.0):
        r, g, b = bake.sun_tint(elevation)
        assert sum(w * c for w, c in zip(bake.LUMA, (r, g, b))) == pytest.approx(1.0)
        assert r > g > b                         # the low sun is warm
    assert bake.sun_tint(15.0)[2] < bake.sun_tint(50.0)[2]
    card = bake.build(b"")
    assert 0.3 < card["nominal"]["sun_inscatter_over_flat_sunlit_snow"] < 0.9


def test_relief_texture_is_tileable_and_deterministic(rgba):
    n = bake.TEX_N
    assert len(rgba) == n * n * 4
    assert rgba == bake.relief_rgba()
    height = rgba[2::4]
    assert min(height) == 0 and max(height) == 255
    # tileable: the step across the wrap is no larger than steps inside
    inside = max(abs(height[y * n + x + 1] - height[y * n + x]) for y in range(n) for x in range(n - 1))
    wrap = max(abs(height[y * n] - height[y * n + n - 1]) for y in range(n))
    assert wrap <= inside
    # normals lean little (a 60 m relief over a 4 km tile), occlusion is in range
    assert all(abs(v - 128) < 64 for v in rgba[0::4])
    assert min(rgba[3::4]) > 64


def test_shipped_files_match_the_generator_and_provenance(rgba):
    card = json.loads((LANE / "alpine_fog.json").read_text(encoding="utf-8"))
    assert card == json.loads(json.dumps(bake.build(rgba)))
    assert card["top_relief"]["rgba_sha256"] == hashlib.sha256(rgba).hexdigest()
    assert card["label"].startswith("visual-only")
    assert [t["tier"] for t in card["tiers"]] == [0, 1, 2, 3]
    assert card["tiers"][0]["est_vram_mb"] == 0.0
    assert card["tiers"][0]["cvars"]["r.VolumetricFog"] == 0
    provenance = json.loads((LANE / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert provenance["vendored"] == []
    for row in provenance["generated"]:
        digest = hashlib.sha256((LANE / row["file"]).read_bytes()).hexdigest()
        assert digest == row["sha256"], row["file"]
    for source in provenance["sources"]:
        assert "non-commercial" not in source["licence"].lower()
    text = (LANE / "INTEGRATION.md").read_text(encoding="utf-8")
    assert "UNMEASURED" in text and "measure_fog.py" in text


def test_pixel_gate_recovers_a_synthetic_fog():
    np = pytest.importorskip("numpy")
    gate = _load("measure_fog")
    rng = np.random.default_rng(7)
    clear = rng.uniform(0.05, 0.5, size=(256, 320, 3))
    t_ref = gate.t_ref()
    assert t_ref == pytest.approx(1.0 - bake.MAX_OPACITY)
    fogged = clear.copy()
    fogged[128:, :, :] = t_ref * clear[128:, :, :] + (1.0 - t_ref) * np.array([0.30, 0.29, 0.27])
    good = gate.measure(clear, fogged, t_ref)
    assert good["status"] == "pass" and good["fog_t_abs_error"] < 1e-6 and good["peak_delta"] < 1e-12
    assert good["blocks"] == {"fitted": 80, "fogged": 40, "untouched": 40}
    assert good["fog_colour_linear_rgb"] == pytest.approx([0.30, 0.29, 0.27], abs=1e-6)
    none = gate.measure(clear, clear, t_ref)
    assert none["status"] == "fail" and not none["fog_detected"]
    assert none["fog_t_abs_error"] == pytest.approx(1.0 - t_ref)
    # a fog half as thick as the model's is measured and refused
    thin = clear.copy()
    thin[128:] = 0.3 * clear[128:] + 0.2
    assert gate.measure(clear, thin, t_ref)["fog_t_abs_error"] == pytest.approx(0.3 - t_ref)
    assert gate.measure(clear, thin, t_ref)["status"] == "fail"
    # a fog that also covers the peaks, or brightens them, fails the second clause
    everywhere = t_ref * clear + (1.0 - t_ref) * 0.3
    assert gate.measure(clear, everywhere, t_ref)["status"] == "fail"
    glow = fogged.copy()
    glow[:128] += 0.05
    assert gate.measure(clear, glow, t_ref)["peak_delta"] == pytest.approx(0.05)
    assert gate.measure(clear, glow, t_ref)["status"] == "fail"
    with pytest.raises(ValueError):
        gate.measure(np.full_like(clear, 0.2), fogged, t_ref)


def _batch(root, outcome, run_id=None, why="", frame=b""):
    (root / "runs").mkdir(exist_ok=True)
    (root / "runs" / "test_scenarios.json").write_text(json.dumps(
        [{"number": 11, "outcome": outcome, "run_id": run_id, "why": why}]), encoding="utf-8")
    if run_id:
        camera = root / "runs" / "webapp" / run_id / "frames" / "chase"
        camera.mkdir(parents=True)
        (camera / "frame_000000.png").write_bytes(frame)
        (camera / "frame_000000_beauty_post.png").write_bytes(b"not this one")


def test_gate_is_blocked_not_failed_while_the_fog_is_not_integrated(tmp_path, capsys):
    gate = _load("measure_fog")
    assert gate.REPO == REPO
    assert gate.gate(tmp_path) == gate.EXIT_BLOCKED            # nothing ran
    assert gate.fog_spec(tmp_path) == gate.EXIT_BLOCKED        # no pinned baseline spec
    _batch(tmp_path, "done", "r1", frame=b"A")
    off = tmp_path / "runs" / "alpine_fog" / "off"
    off.mkdir(parents=True)
    (off / "11.json").write_text(json.dumps({"spec": {"environment": {"turbulence": 1}}}))
    assert gate.keep("baseline", tmp_path) == 0
    assert (tmp_path / "runs" / "alpine_fog" / "baseline.png").read_bytes() == b"A"
    assert gate.fog_spec(tmp_path) == 0
    on = json.loads((off.parent / "on" / "11.json").read_text())
    assert on["spec"]["environment"] == {"turbulence": 1,
                                         "valley_fog": {"top_m": 1900.0, "scale_height_m": 200.0}}
    # today: the validator refuses the unknown key, so the candidate has no frame
    _batch(tmp_path, "refused", why="environment: unknown keys ['valley_fog']")
    assert gate.keep("candidate", tmp_path) == gate.EXIT_BLOCKED
    capsys.readouterr()
    assert gate.gate(tmp_path) == gate.EXIT_BLOCKED
    said = json.loads(capsys.readouterr().out)
    assert said["status"] == "blocked" and said["measured"] is False
    assert "unknown keys" in said["reason"]
    # a candidate that is the baseline's picture is blocked too, never scored
    _batch(tmp_path, "done", "r2", frame=b"A")
    assert gate.keep("candidate", tmp_path) == 0
    assert gate.gate(tmp_path) == gate.EXIT_BLOCKED
    assert "same picture" in capsys.readouterr().out


def test_the_documented_gate_can_be_pasted():
    gate = _load("measure_fog")
    text = (LANE / "INTEGRATION.md").read_text(encoding="utf-8")
    block = text.split("```bat")[1].split("```")[0]
    lines = block.strip().splitlines()
    assert len(lines) == 6 and "<" not in block and "set " not in block
    assert "FLIGHTSIM_VALLEY_FOG" not in text
    calls = [line.split("measure_fog.py", 1)[1].split()
             for source in (text, gate.__doc__) for line in source.splitlines()
             if line.strip().startswith("python") and "measure_fog.py " in line]
    assert len(calls) == 8
    for argv in calls:
        assert argv in (["keep", "baseline"], ["keep", "candidate"], ["fog-spec"], ["gate"])
    runner = (REPO / "scripts" / "run_test_scenarios.py").read_text(encoding="utf-8")
    for flag in ("--still", "--only", "--spec-dir"):
        assert flag in block and f'"{flag}"' in runner

