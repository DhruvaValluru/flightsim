"""Environment providers, and the null-test ladder as permanent regressions.

§5 Phase 3 requires the null tests to live in the suite, not only in the gate:
"the old build's 34/34 passing suite contained none of them". A null test asks
whether a feature reached the equations of motion at all. It is a low bar, and
it is the bar the previous build failed -- it advertised WIND 270/25KT with no
way to see it in the output, and carried an orographic model that left no trace
in the state.
"""

import math

import pytest

from core.environment.base import Position, WindNED
from core.environment.gust import DiscreteGust
from core.environment.stack import EnvironmentStack
from core.environment.terrain_field import OrographicWind, TerrainField
from core.environment.turbulence import (
    POE_SIGMA_W_FPS,
    TURB_CULP,
    DrydenTurbulence,
    poe_index_for,
)
from core.environment.wind import BoundaryLayerWind, LogProfileWind, SteadyWind
from core.fdm import FlightDynamics, TrimMode
from core.fdm import units as u

HERE = Position(latitude_deg=0.0, longitude_deg=0.0, altitude_m=1000.0,
                agl_m=1000.0, terrain_elevation_m=0.0)


def trimmed(altitude_m=3000.0, cas_kt=250.0, rate_hz=120.0, aircraft="B747"):
    fdm = FlightDynamics(aircraft, rate_hz=rate_hz)
    fdm.set_initial_conditions(
        {"h-sl-ft": u.m_to_ft(altitude_m), "vc-kts": cas_kt, "gamma-deg": 0.0,
         "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
         "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0}
    )
    fdm.start_engines()
    fdm.trim(TrimMode.LONGITUDINAL)
    fdm.hold_mass(True)
    return fdm


def altitudes(stack, seconds=40.0, **kwargs):
    fdm = trimmed(**kwargs)
    stack.configure(fdm)
    out = []
    for i in range(int(seconds * fdm.rate_hz)):
        stack.apply(fdm)
        fdm.step()
        if i % 30 == 0:
            out.append(fdm.state().altitude_m)
    return out


def peak_diff(a, b):
    return max(abs(x - y) for x, y in zip(a, b))


# -- the null-test ladder ------------------------------------------------


def test_null_steady_wind_reaches_the_fdm():
    off = altitudes(EnvironmentStack())
    on = altitudes(EnvironmentStack([SteadyWind(u.kt_to_mps(25.0), 270.0)]))
    assert peak_diff(on, off) > 1.0, "wind never reached the FDM"


def test_null_turbulence_reaches_the_fdm():
    off = altitudes(EnvironmentStack([DrydenTurbulence("none")]))
    on = altitudes(EnvironmentStack([DrydenTurbulence("moderate", seed=17)]))
    assert peak_diff(on, off) > 1.0, "turbulence never reached the FDM"


def test_null_discrete_gust_reaches_the_fdm():
    gust = DiscreteGust(peak_mps=7.5, start_s=5.0,
                        airspeed_mps=u.kt_to_mps(250.0))
    off = altitudes(EnvironmentStack())
    on = altitudes(EnvironmentStack([gust]))
    assert peak_diff(on, off) > 1.0, "gust never reached the FDM"


def test_null_orographic_reaches_the_fdm():
    speed = u.kt_to_mps(30.0)
    flat = EnvironmentStack([SteadyWind(speed, 180.0),
                             OrographicWind(TerrainField.flat(), speed, 180.0)])
    ridge = EnvironmentStack([
        SteadyWind(speed, 180.0),
        OrographicWind(TerrainField.sinusoidal_ridge(300.0, 4000.0), speed, 180.0),
    ])
    off = altitudes(flat, altitude_m=900.0)
    on = altitudes(ridge, altitude_m=900.0)
    assert peak_diff(on, off) > 1.0, "orographic lift never reached the FDM"


def test_null_boundary_layer_differs_from_uniform_wind():
    speed = u.kt_to_mps(25.0)
    uniform = altitudes(EnvironmentStack([SteadyWind(speed, 270.0)]), altitude_m=200.0)
    sheared = altitudes(
        EnvironmentStack([BoundaryLayerWind(speed, 270.0, terrain="open")]),
        altitude_m=200.0,
    )
    assert peak_diff(uniform, sheared) > 1.0


def test_null_log_profile_differs_from_uniform_wind():
    """Phase 7's surface-layer law must reach the FDM as its own shape."""
    speed = u.kt_to_mps(25.0)
    uniform = altitudes(EnvironmentStack([SteadyWind(speed, 270.0)]),
                        altitude_m=200.0)
    sheared = altitudes(
        EnvironmentStack([LogProfileWind(speed, 270.0, terrain="open")]),
        altitude_m=200.0,
    )
    assert peak_diff(uniform, sheared) > 1.0


def test_a_uniform_wind_set_once_does_persist():
    """Correction to §5 Phase 3, which says the opposite.

    The brief warns that "JSBSim's atmosphere model overwrites wind properties
    if you set them once at init". Measured on the pinned build it does not:
    ``atmosphere/wind-east-fps`` survives unchanged with turbulence off and on,
    and ``total-wind-east-fps`` reports it faithfully.

    Writing every step is still required here, but for a different reason --
    the providers are functions of position and time, so a boundary-layer
    profile, an orographic field or a gust has to be re-evaluated as the
    aircraft moves. A uniform wind is the one case where it does not matter,
    which is exactly why testing only that case would prove nothing.
    """
    fdm = trimmed()
    fdm.props.set("atmosphere/wind-east-fps", u.kt_to_fps(25.0))
    fdm.run_for(10.0)
    assert fdm.props.get("atmosphere/total-wind-east-fps") == pytest.approx(
        u.kt_to_fps(25.0), rel=0.01
    )


def test_a_position_dependent_wind_needs_writing_every_step():
    """The case that actually justifies the per-step write.

    A boundary-layer profile evaluated once at the initial altitude stays at
    that value for the whole run, so an aircraft that climbs flies through the
    wrong wind while the property still reports a plausible number.
    """
    profile = BoundaryLayerWind(u.kt_to_mps(25.0), 270.0, reference_height_m=10.0,
                                terrain="open")
    low = profile.wind_at(
        Position(0.0, 0.0, 50.0, agl_m=50.0, terrain_elevation_m=0.0), 0.0
    )
    high = profile.wind_at(
        Position(0.0, 0.0, 500.0, agl_m=500.0, terrain_elevation_m=0.0), 0.0
    )
    assert abs(high.east) > abs(low.east) * 1.2

    stack = EnvironmentStack([profile])
    fdm = trimmed(altitude_m=200.0)
    stack.configure(fdm)
    for _ in range(600):
        stack.apply(fdm)
        fdm.step()
    expected = profile.speed_at(fdm.state().agl_m)
    assert fdm.props.get("atmosphere/total-wind-east-fps") == pytest.approx(
        u.mps_to_fps(expected), rel=0.05
    )


# -- turbulence: the measured JSBSim behaviour ---------------------------


def test_reseeding_every_step_destroys_the_turbulence_process():
    """Regression for a failure that reads as violent turbulence, not a bug.

    Measured: peak turbulence 37.6 fps and peak |Nz-1| 0.40 g with the seed
    written once, against 566 fps and 515 g when re-seeded every step.
    """
    from core.fdm import SimulationError

    def peak_turbulence(reseed):
        fdm = trimmed(altitude_m=1000.0)
        fdm.props.set_many(DrydenTurbulence("moderate", seed=3).configure())
        worst = 0.0
        try:
            for _ in range(30 * 120):
                if reseed:
                    fdm.props.set("atmosphere/randomseed", 3.0)
                fdm.step()
                worst = max(worst, abs(fdm.props.get("atmosphere/turb-down-fps")))
        except SimulationError:
            # Re-seeding can drive the state non-finite outright, which is an
            # even clearer demonstration than a large number.
            return float("inf")
        return worst

    sane = peak_turbulence(reseed=False)
    broken = peak_turbulence(reseed=True)
    assert sane < 60.0, f"correctly-seeded turbulence peaked at {sane:.1f} fps"
    assert broken > 5.0 * sane


def test_culp_turbulence_model_is_refused():
    """It diverged to a load factor of 1.5e9 during characterisation."""
    with pytest.raises(ValueError, match="diverges"):
        DrydenTurbulence("moderate", model=TURB_CULP)


def test_turbulence_intensity_words_carry_a_measured_definition():
    """§2.5: "what does moderate mean" must have an answer with a citation."""
    provider = DrydenTurbulence("moderate")
    terms = {t.phrase: t for t in provider.vocabulary()}
    assert "MIL-F-8785C" in terms["moderate"].standard
    assert terms["moderate"].value > terms["light"].value
    assert terms["severe"].value > terms["moderate"].value
    assert terms["none"].value == 0.0


def test_poe_ladder_is_monotone():
    assert list(POE_SIGMA_W_FPS) == sorted(POE_SIGMA_W_FPS)
    assert poe_index_for("none") == 0
    assert poe_index_for("severe") > poe_index_for("light")


def test_scheduled_turbulence_is_w20_only_with_pinned_severity():
    """The evolving-conditions machinery (Phase 7 3.1) may move ONLY W20:
    per-step seed writes are the 515 g failure and mid-run severity changes
    deliver 2-5x the commanded sigma_w (JSBSIM_CORRECTIONS §9/§13)."""
    from core.environment.turbulence import ScheduledDrydenTurbulence

    schedule = ScheduledDrydenTurbulence(
        [(0.0, "none"), (40.0, "light"), (80.0, "moderate"), (115.0, "severe")],
        seed=11)
    writes = schedule.configure()
    assert writes["atmosphere/turbulence/milspec/severity"] == 1.0
    assert writes["atmosphere/randomseed"] == 11.0

    step = schedule.step_writes(HERE, 100.0)
    assert set(step) == {
        "atmosphere/turbulence/milspec/windspeed_at_20ft_AGL-fps"}

    assert schedule.w20_fps_at(0.0) == 0.0
    assert schedule.w20_fps_at(50.0) == pytest.approx(u.kt_to_fps(15.0))
    assert schedule.w20_fps_at(114.9) == pytest.approx(u.kt_to_fps(30.0))
    assert schedule.w20_fps_at(140.0) == pytest.approx(u.kt_to_fps(45.0))

    card = schedule.card_schedule()
    assert card["times_s"] == [0.0, 40.0, 80.0, 115.0]
    assert card["w20_fps"][-1] == pytest.approx(u.kt_to_fps(45.0))


def test_scheduled_turbulence_refuses_bad_schedules():
    from core.environment.turbulence import ScheduledDrydenTurbulence

    with pytest.raises(ValueError, match="t=0"):
        ScheduledDrydenTurbulence([(5.0, "light")], seed=1)
    with pytest.raises(ValueError, match="increasing"):
        ScheduledDrydenTurbulence([(0.0, "light"), (10.0, "severe"),
                                   (5.0, "none")], seed=1)
    with pytest.raises(ValueError, match="unknown intensity"):
        ScheduledDrydenTurbulence([(0.0, "hurricane")], seed=1)


def test_low_altitude_turbulence_scales_with_w20():
    """MIL-F-8785C's low-altitude relation, sigma_w = 0.1 * W20."""
    moderate = DrydenTurbulence("moderate")
    light = DrydenTurbulence("light")
    assert moderate.expected_sigma_w_mps(100.0) > light.expected_sigma_w_mps(100.0)
    # W20 is ignored above the low-altitude regime; the POE index takes over.
    assert moderate.expected_sigma_w_mps(5000.0) != moderate.expected_sigma_w_mps(100.0)


def test_only_one_turbulence_provider_is_allowed():
    stack = EnvironmentStack([DrydenTurbulence("light")])
    with pytest.raises(ValueError, match="only one turbulence provider"):
        stack.add(DrydenTurbulence("severe"))


# -- provider unit behaviour ---------------------------------------------


def test_wind_contributions_sum():
    """§2.4: velocity fields superpose, which is why this seam is pluggable."""
    stack = EnvironmentStack([
        SteadyWind(10.0, 270.0),      # blows toward the east
        SteadyWind(10.0, 90.0),       # blows toward the west
    ])
    total = stack.wind_at(HERE, 0.0)
    assert total.east == pytest.approx(0.0, abs=1e-9)


def test_meteorological_direction_convention():
    """Wind 'from 270' blows toward the east."""
    w = WindNED.from_meteorological(10.0, 270.0)
    assert w.east == pytest.approx(10.0)
    assert w.north == pytest.approx(0.0, abs=1e-9)


def test_boundary_layer_increases_with_height():
    profile = BoundaryLayerWind(10.0, 270.0, reference_height_m=10.0, terrain="open")
    assert profile.speed_at(10.0) == pytest.approx(10.0)
    assert profile.speed_at(100.0) > profile.speed_at(10.0)
    assert profile.speed_at(1.0) < profile.speed_at(10.0)
    # Flat above the layer depth: the free atmosphere is not slowed by the surface.
    assert profile.speed_at(2000.0) == pytest.approx(profile.speed_at(600.0))


def test_rougher_terrain_gives_more_shear():
    open_country = BoundaryLayerWind(10.0, 270.0, terrain="open")
    urban = BoundaryLayerWind(10.0, 270.0, terrain="urban")
    assert urban.speed_at(2.0) < open_country.speed_at(2.0)


# -- the log profile (Phase 7): the surface-layer law with a stated z0 ---


def test_log_profile_matches_its_reference_and_is_log_linear():
    profile = LogProfileWind(10.0, 270.0, reference_height_m=10.0,
                             terrain="open")
    assert profile.speed_at(10.0) == pytest.approx(10.0)
    # The shape check: u is linear in ln z, so equal ln-steps give equal
    # speed increments -- the property that IS the log law.
    z0 = profile.z0_m
    heights = [1.0, 10.0, 100.0]     # equal factors of 10
    speeds = [profile.speed_at(z) for z in heights]
    assert speeds[2] - speeds[1] == pytest.approx(speeds[1] - speeds[0])


def test_log_profile_is_zero_at_and_below_z0():
    profile = LogProfileWind(10.0, 270.0, terrain="forest")
    assert profile.speed_at(profile.z0_m) == 0.0
    assert profile.speed_at(0.0) == 0.0


def test_log_profile_holds_above_the_surface_layer():
    """The log law is not extended beyond its derivation: held at 300 m."""
    profile = LogProfileWind(10.0, 270.0, terrain="open")
    top = profile.speed_at(LogProfileWind.SURFACE_LAYER_TOP_M)
    assert profile.speed_at(1000.0) == pytest.approx(top)
    assert profile.speed_at(5000.0) == pytest.approx(top)


def test_log_profile_rougher_terrain_gives_more_shear():
    """At the same reference wind, forest bends the profile harder than
    water: below the reference height it is slower, above it faster."""
    water = LogProfileWind(10.0, 270.0, terrain="water")
    forest = LogProfileWind(10.0, 270.0, terrain="forest")
    assert forest.speed_at(2.0) < water.speed_at(2.0)
    assert forest.speed_at(200.0) > water.speed_at(200.0)


def test_log_profile_refuses_reference_below_z0():
    with pytest.raises(ValueError, match="roughness length"):
        LogProfileWind(10.0, 270.0, reference_height_m=0.5, terrain="forest")


def test_log_profile_vocabulary_cites_the_standard():
    terms = LogProfileWind(10.0, 270.0).vocabulary()
    assert all("Stull" in t.standard for t in terms)
    z0 = {t.phrase: t.value for t in terms}
    assert z0["water terrain"] < z0["open terrain"] < z0["forest terrain"]


def test_log_profile_composes_with_the_downburst():
    """The microburst regime: outflow + surface-layer shear sum in the stack,
    and the composed field keeps both structures (§2.4 superposition)."""
    from core.environment.downburst import Downburst

    shear = LogProfileWind(u.kt_to_mps(15.0), 270.0, terrain="open")
    burst = Downburst(core_radius_m=600.0, outflow_max_mps=10.0,
                      centre_north_m=0.0, centre_east_m=0.0)
    stack = EnvironmentStack([shear, burst])
    inside = Position(latitude_deg=0.0, longitude_deg=600.0 / 111_320.0,
                      altitude_m=80.0, agl_m=80.0, terrain_elevation_m=0.0)
    far = Position(latitude_deg=0.0, longitude_deg=0.5,
                   altitude_m=80.0, agl_m=80.0, terrain_elevation_m=0.0)
    composed_inside = stack.wind_at(inside, 0.0)
    composed_far = stack.wind_at(far, 0.0)
    # Far from the cell only the shear profile remains...
    assert composed_far.horizontal_speed == pytest.approx(
        shear.speed_at(80.0), rel=1e-6)
    # ...inside it the two contributions are literally summed.
    burst_only = burst.wind_at(inside, 0.0)
    shear_only = shear.wind_at(inside, 0.0)
    assert composed_inside.east == pytest.approx(
        burst_only.east + shear_only.east)
    assert composed_inside.down == pytest.approx(burst_only.down)


def test_gust_is_exactly_zero_outside_its_window():
    """So a run before the gust starts is bit-identical to one without it."""
    gust = DiscreteGust(peak_mps=10.0, start_s=10.0, gradient_m=120.0,
                        airspeed_mps=100.0)
    assert gust.magnitude_at(9.99) == 0.0
    assert gust.magnitude_at(10.0) == 0.0
    assert gust.magnitude_at(gust.start_s + 2 * gust.half_period_s + 0.01) == 0.0


def test_gust_reaches_its_commanded_peak():
    gust = DiscreteGust(peak_mps=10.0, start_s=0.0, gradient_m=120.0,
                        airspeed_mps=100.0)
    assert gust.magnitude_at(gust.half_period_s) == pytest.approx(10.0)


def test_orographic_lift_reverses_across_a_ridge():
    """U . grad(h) must change sign between windward and lee faces."""
    ridge = TerrainField.sinusoidal_ridge(amplitude_m=300.0, wavelength_m=4000.0)
    provider = OrographicWind(ridge, 15.0, 180.0)
    windward = provider.linear_updraught(1000.0, 0.0)
    lee = provider.linear_updraught(-1000.0, 0.0)
    assert windward * lee < 0.0


def test_orographic_lift_decays_with_height():
    ridge = TerrainField.sinusoidal_ridge()
    provider = OrographicWind(ridge, 15.0, 180.0)
    assert provider.decay(0.0) == pytest.approx(1.0)
    assert provider.decay(provider.decay_height_m) == pytest.approx(math.exp(-1.0))
    assert provider.decay(10_000.0) < 0.01


def test_orographic_saturates_on_slopes_beyond_linear_theory():
    """Linear theory over-predicts badly on steep faces; it is capped, not trusted."""
    gentle = TerrainField.sinusoidal_ridge(amplitude_m=50.0, wavelength_m=8000.0)
    cliff = TerrainField.sinusoidal_ridge(amplitude_m=2000.0, wavelength_m=800.0)
    w_gentle = abs(OrographicWind(gentle, 20.0, 180.0).linear_updraught(500.0, 0.0))
    w_cliff = abs(OrographicWind(cliff, 20.0, 180.0).linear_updraught(100.0, 0.0))
    assert w_cliff <= 20.0 * 0.35 + 1e-6
    assert w_gentle < w_cliff


def test_flat_terrain_produces_no_orographic_lift():
    provider = OrographicWind(TerrainField.flat(), 20.0, 180.0)
    assert provider.wind_at(HERE, 0.0).down == pytest.approx(0.0, abs=1e-9)


def test_every_provider_declares_its_vocabulary():
    """§2.5: a provider that cannot say what its words mean is not finished."""
    providers = [
        SteadyWind(10.0, 270.0),
        BoundaryLayerWind(10.0, 270.0),
        DiscreteGust(7.5, 10.0),
        OrographicWind(TerrainField.sinusoidal_ridge(), 15.0, 180.0),
        DrydenTurbulence("moderate"),
    ]
    for provider in providers:
        terms = provider.vocabulary()
        assert terms, f"{provider.name} declares no vocabulary"
        for term in terms:
            assert term.standard, f"{provider.name}:{term.phrase} cites no standard"
