"""LOOK_GENERATION 14 (lane aircraft-refl): the scene's own sky and ground in
the paint / bare-metal / canopy mirrors (scripts/aircraft_scene_sky.py and its
HLSL twins). Numeric checks against the real-world numbers each rule cites."""
import math
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import aircraft_scene_sky as ss  # noqa: E402

ENV = (ROOT / "assets/shaders/aircraft/scene_sky_env.hlsl").read_text()
DIR = (ROOT / "assets/shaders/aircraft/scene_sky_dir.hlsl").read_text()
FX = (ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimAircraftFX.cpp").read_text()


def test_rayleigh_column_matches_bucholtz_550nm():
    # UE's default atmosphere, far above the ground: green Rayleigh tau ~0.108,
    # within 12 % of Bucholtz 1995's 0.0973 at 550 nm, sea level.
    tau_g = ss.column(ss.UE_DEFAULT_RAYLEIGH_PER_KM[1], ss.UE_DEFAULT_RAYLEIGH_H_KM, 1.0e4)
    assert abs(tau_g - 0.1085) < 1.0e-3
    assert abs(tau_g / ss.BUCHOLTZ_TAU_R_550 - 1.0) < 0.12


def test_ground_tau_zero_on_ground_and_grows_with_altitude():
    assert ss.ground_tau(0.0) == (0.0, 0.0, 0.0)
    low, high = ss.ground_tau(0.3), ss.ground_tau(3.0)
    assert all(h > l > 0.0 for l, h in zip(low, high))
    assert high[2] > high[1] > high[0]          # blue scatters most


def test_cie_overcast_horizon_is_a_third_of_zenith():
    assert math.isclose(ss.overcast(3.0, 0.0), 1.0)
    assert math.isclose(ss.overcast(3.0, 1.0), 3.0)


def test_scene_off_or_lut_missing_is_the_strip():
    sky = (1.0, 2.0, 4.0)
    assert ss.sky_env(sky, sky, (0, 0, 0), (0, 0, 0), (0, 0, 1), 0.1, 0.0, scale=0.0)[3] == 0.0
    assert ss.sky_env((0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 1), 0.1, 0.0)[3] == 0.0
    strip = (0.3, 0.4, 0.5)
    assert tuple(ss.mix(strip, (9.0, 9.0, 9.0, 0.0))) == strip


def test_above_horizon_reads_the_sky_below_reads_the_ground():
    sky, ground = (1.0, 2.0, 4.0), (0.5, 0.4, 0.2)
    up = ss.sky_env(sky, sky, ground, (0, 0, 0), (0, 0, 1), 0.05, 0.0, scale=1.0)
    assert up[3] == 1.0 and all(math.isclose(a, b) for a, b in zip(up[:3], sky))
    down = ss.sky_env(sky, sky, ground, (0, 0, 0), (0, 0, -1), 0.05, 0.0, scale=1.0)
    # ground x exp(0) + the LUT's in-scatter on that ray
    assert all(math.isclose(d, g + s) for d, g, s in zip(down[:3], ground, sky))


def test_overcast_cover_greys_the_sky():
    sky = (1.0, 2.0, 4.0)
    r = ss.sky_env(sky, sky, (0, 0, 0), (0, 0, 0), (0, 0, 1), 0.05, 1.0, scale=1.0)
    assert math.isclose(r[0], r[1]) and math.isclose(r[1], r[2])


def test_horizon_blur_follows_ggx_alpha():
    assert math.isclose(ss.horizon_width(0.5), 0.5)          # 2 x 0.5^2
    assert ss.horizon_width(0.0) == ss.MIN_W


def test_sky_dir_unit_and_sun_facing_centre():
    d = ss.sky_dir((0.5, 0.5), (0.0, 1.0, 0.3))
    assert all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(d, (0.0, 1.0, 0.0)))
    z = ss.sky_dir((0.37, 0.2), (0.6, -0.8, 0.1))
    assert math.isclose(math.hypot(*z), 1.0)


def test_scene_scale_half_physical_and_zero_inside():
    assert math.isclose(ss.SCENE_SHARE, 0.5)
    assert ss.scene_scale(True) == 0.5 and ss.scene_scale(True, interior=True) == 0.0
    assert ss.scene_scale(False) == 0.0
    assert ss.parameters("Paint")["scalars"]["PaintEnvSceneScale"] == 0.0   # master default = strip


def test_hlsl_and_host_constants_match_the_twin():
    assert "smoothstep(-w, w, rz)" in ENV and "(1.0 + 2.0 * saturate(rz)) / 3.0" in ENV
    assert "6.2831853" in DIR
    assert re.search(r"AircraftFxSceneSkyShare = 0\.10 / 0\.2;", FX)
    assert re.search(r"AircraftFxSceneOvercastShare = 1\.0 - 0\.75;", FX)
    assert 'TEXT("reflect-scene-sky="), true' in FX
