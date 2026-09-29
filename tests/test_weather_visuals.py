"""Phase 2, package F: the look coupling table (contracts §5.4).

Every row is a pure function with a documented formula; each test
RE-IMPLEMENTS the formula from the docstring and compares (the
producer/verifier rule), so a row that drifts from its documentation
fails by name. What the engine does with each number is measured on
the Windows box (Gate 6), not here.
"""

import math

import pytest

from core.scene import weather_visuals as wv


def test_koschmieder_fog_extinction_is_3_912_over_v_in_engine_units():
    """V = 10 km: beta = 3.912 / 10 per km = 0.3912 / km = 0.0003912 / m,
    in the block's documented unit (1/m, the -fog-density unit)."""
    assert wv.fog_extinction_per_m(10.0) == pytest.approx(3.912 / 10.0 / 1000.0)
    assert wv.fog_extinction_per_m(10.0) == pytest.approx(0.0003912)
    for v in (1.0, 2.5, 25.0, 80.0):
        beta = wv.fog_extinction_per_m(v)
        assert beta == pytest.approx(wv.KOSCHMIEDER_CONSTANT / (1000.0 * v))
        assert wv.visibility_km_for_extinction(beta) == pytest.approx(v)
        # Extinction over V metres leaves 2 % contrast: exp(-beta V) = 0.02.
        assert math.exp(-beta * v * 1000.0) == pytest.approx(0.02, rel=1e-4)
    assert wv.KOSCHMIEDER_CONSTANT == pytest.approx(-math.log(0.02), abs=1e-3)
    with pytest.raises(ValueError):
        wv.fog_extinction_per_m(0.0)


def test_the_harness_fog_constants_read_back_as_visibilities():
    """The Phase 10 clear/hazy densities, read through the same formula,
    are stated visibilities -- so the block's fog_density and the
    policy's visibility_km are one number in two units."""
    from core.scenario.randomization import FOG_CLEAR, FOG_HAZY

    clear = wv.visibility_km_for_extinction(FOG_CLEAR)
    hazy = wv.visibility_km_for_extinction(FOG_HAZY)
    assert clear == pytest.approx(3.912 / (1000.0 * 0.0012))
    assert hazy == pytest.approx(3.912 / (1000.0 * 0.010))
    assert clear > hazy


def test_aerosol_scale_carries_the_same_extinction_alone():
    v = 25.0
    beta_km = 3.912 / v
    assert wv.aerosol_scale(v) == pytest.approx(beta_km / (0.003996 + 0.000444))


def test_cloud_layers_are_one_layer_with_documented_defaults_or_none():
    assert wv.cloud_layers(0.0) == []
    layer, = wv.cloud_layers(0.55)
    assert layer == {"cover": 0.55, "base_m": wv.DEFAULT_CLOUD_BASE_M,
                     "top_m": wv.DEFAULT_CLOUD_BASE_M + wv.DEFAULT_CLOUD_THICKNESS_M}
    layer, = wv.cloud_layers(1.0, 800.0, 2300.0)
    assert layer == {"cover": 1.0, "base_m": 800.0, "top_m": 2300.0}
    with pytest.raises(ValueError):
        wv.cloud_layers(1.2)
    with pytest.raises(ValueError):
        wv.cloud_layers(0.5, 2000.0, 1000.0)


def test_precipitation_floors_the_visibility_and_wets_the_surface():
    assert wv.visibility_floor_km(60.0, "none") == 60.0
    assert wv.visibility_floor_km(60.0, "rain") == 10.0
    assert wv.visibility_floor_km(3.0, "rain") == 3.0
    assert wv.visibility_floor_km(60.0, "snow") == 5.0
    assert wv.wetness("none") == 0.0
    assert wv.wetness("rain") == 1.0
    assert 0.0 < wv.wetness("snow") < 1.0
    with pytest.raises(ValueError):
        wv.wetness("hail")


def test_cloud_drift_is_the_wind_in_metres_per_second():
    assert wv.cloud_drift_mps(1.0) == pytest.approx(1852.0 / 3600.0, abs=1e-4)
    assert wv.cloud_drift_mps(12.0) == pytest.approx(12 * 0.514444, abs=1e-4)


def test_ev100_from_the_exposure_triple():
    """EV100 = log2(N^2 / t) - log2(ISO / 100): f/8, 1/500 s, ISO 100
    (the contracts' daylight default) is log2(64 * 500) = 14.97."""
    assert wv.ev100(8.0, 1 / 500.0, 100.0) == pytest.approx(math.log2(64 * 500), abs=1e-3)
    assert wv.ev100(8.0, 1 / 500.0, 400.0) == pytest.approx(math.log2(64 * 500) - 2.0, abs=1e-3)
    assert wv.ev100(2.8, 1 / 60.0, 100.0) == pytest.approx(math.log2(2.8 ** 2 * 60), abs=1e-3)
    with pytest.raises(ValueError):
        wv.ev100(0.0, 1 / 500.0, 100.0)


def test_look_block_is_the_documented_table_and_states_what_it_does_not_claim():
    look = wv.look_block({
        "visibility_km": 10.0, "cloud_cover": 0.7, "cloud_base_m": 900.0,
        "precipitation": "rain", "wind_speed_kt": 20.0,
        "wind_direction_deg": 250.0,
        "exposures": {"chase": (8.0, 1 / 500.0, 100.0)},
    })
    assert look["visibility_km"] == 10.0            # rain's floor is 10 km: unchanged
    assert look["fog_extinction_per_m"] == pytest.approx(0.0003912, rel=1e-4)
    assert look["clouds"] == [{"cover": 0.7, "base_m": 900.0, "top_m": 1900.0}]
    assert look["precipitation"] == "rain" and look["wetness"] == 1.0
    assert look["cloud_drift_mps"] == pytest.approx(20 * 0.514444, abs=1e-3)
    assert look["cloud_drift_from_deg"] == 250.0
    assert look["ev100"]["chase"] == pytest.approx(14.966, abs=1e-2)
    assert "precipitation_particles" in look["not_claimed"]
    assert "moon" in look["not_claimed"]
    # Every key the table produces names the engine parameter it drives.
    for key in look:
        if key not in ("visibility_km", "not_claimed"):
            assert key in wv.ENGINE_PARAMETERS, key
    # The rain floor applies to a clearer day.
    floored = wv.look_block({"visibility_km": 60.0, "precipitation": "rain"})
    assert floored["visibility_km"] == 10.0
    # No visibility drawn: the block's fog density is the source, and
    # with neither the engine default is the visibility stated.
    from_fog = wv.look_block({"fog_density": 0.0012})
    assert from_fog["visibility_km"] == pytest.approx(3.912 / 1.2, abs=1e-3)
    bare = wv.look_block({})
    assert bare["fog_extinction_per_m"] == pytest.approx(wv.ENGINE_FOG_DENSITY_DEFAULT)
    assert bare["clouds"] == [] and bare["ev100"] == {}


def test_the_phase10_flag_names_are_kept_for_the_look_lane():
    assert wv.RENDER_FLAGS == {"sun_elev": "-sun-elev", "sun_azim": "-sun-azim",
                               "exposure_bias": "-exposure-bias",
                               "fog_density": "-fog-density"}
    assert wv.CARD_LOOK_KEY == "look"


# -- W3: the drift from the wind at cloud base, the night and rain rows --------------

LAYERED = [[0.0, 10.0, 270.0], [1000.0, 20.0, 270.0], [3000.0, 40.0, 300.0]]


def test_cloud_drift_is_the_providers_wind_at_cloud_base_with_a_layered_fixture():
    """Base 1500 m above a 500 m datum is 2000 m MSL, halfway between the
    second and third layers: 30 kt from 285 deg (shorter arc), and the
    drift equals the provider's own wind_at there component for component."""
    from core.environment.base import Position
    from core.environment.shear import LayeredWind

    provider = LayeredWind(LAYERED)
    drift = wv.cloud_drift_at_base([provider], 46.0, 7.7, 500.0, 1500.0)
    wind = provider.wind_at(Position(46.0, 7.7, 2000.0, 1500.0, 500.0), 0.0)
    assert drift["source"] == wv.CLOUD_DRIFT_SOURCE == "wind at cloud base"
    assert drift["north_mps"] == wind.north and drift["east_mps"] == wind.east
    assert drift["mps"] == pytest.approx(30.0 * 0.514444, abs=1e-3)
    assert drift["from_deg"] == pytest.approx(285.0, abs=1e-3)
    assert drift["altitude_m"] == 2000.0 and drift["base_m"] == 1500.0
    # The spec's uniform wind at the surface is NOT the wind aloft here.
    assert drift["mps"] != wv.cloud_drift_mps(10.0)
    assert wv.cloud_drift_at_base([], 0.0, 0.0, 0.0, 1500.0)["mps"] == 0.0     # calm
    assert wv.drift_offset_m(drift["mps"], 30.0) == pytest.approx(30.0 * drift["mps"])


def test_the_spec_path_reads_the_runs_own_providers_at_the_base():
    from core.environment.base import Position
    from core.nl.compiler import compile_prompt
    from core.scene.world_record import spec_cloud_drift, world_stated
    from core.scenario.runner import environment_for

    spec = compile_prompt("fly the c172p at 1500 m and 100 kt for 1 seconds")
    assert not world_stated(spec)
    spec.set("wind_speed", 10.0, frm="test")
    spec.set("wind_direction", 270.0, frm="test")
    spec.set("wind_profile.kind", "layered", frm="test")
    spec.set("wind_profile.layers", LAYERED, frm="test")
    assert world_stated(spec)
    drift = spec_cloud_drift(spec)
    base = wv.DEFAULT_CLOUD_BASE_M + float(spec.terrain_elevation.value)
    total = [p.wind_at(Position(0.0, 0.0, base, wv.DEFAULT_CLOUD_BASE_M,
                                float(spec.terrain_elevation.value)), 0.0)
             for p in environment_for(spec).wind]
    assert drift["north_mps"] == pytest.approx(sum(w.north for w in total), abs=1e-12)
    assert drift["east_mps"] == pytest.approx(sum(w.east for w in total), abs=1e-12)
    assert "layered_wind" in drift["providers"]


def test_the_rain_rows_ride_only_with_a_rate_and_name_their_engine_parameters():
    dry = wv.look_block({"visibility_km": 60.0, "precipitation": "rain"})
    assert "precipitation_rate_mmh" not in dry and "rain_extinction_per_m" not in dry
    wet = wv.look_block({"visibility_km": 60.0, "precipitation_rate_mmh": 4.0})
    for key in wet:
        if key not in ("visibility_km", "not_claimed"):
            assert key in wv.ENGINE_PARAMETERS, key
    assert wet["precipitation_rate_mmh"] == 4.0
    for row in ("night", "precipitation", "cloud_drift"):
        assert row in wv.WORLD_PARAMETERS
    assert wv.CLOUD_DRIFT_KEYS == ("mps", "from_deg", "base_m", "source")
