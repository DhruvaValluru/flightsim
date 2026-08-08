"""Allen thermals: pinned to the TM's own check case, then to the FDM.

NASA/TM-2006-214019's Section VI works one example end to end (w* = 2.56,
zi = 1401 m, z = 280 m, 1000 x 1000 m area, five updrafts) and prints the
resulting numbers: r2 = 79.4 m, five updrafts by eq (20), a centre velocity
near 2.7 m/s and an ambient sink near -0.13 m/s (Figures 11-12). Those are
the strongest tests available: they pin this implementation to the paper's
own verified artifact, not to itself.
"""

import math

import numpy as np
import pytest

from core.environment.base import Position
from core.environment.stack import EnvironmentStack
from core.environment.thermals import (
    K_SHAPE,
    R1R2_SHAPE,
    SEASON_TABLE,
    AllenThermals,
    shape_constants,
)
from core.fdm import units as u

from .test_environment import trimmed

#: The TM Section VI example, verbatim.
CHECK = dict(wstar_mps=2.56, zi_m=1401.0, area_north_m=1000.0,
             area_east_m=1000.0, seed=1)
CHECK_Z = 280.0


def check_field(**overrides):
    """The example field: five updrafts evenly along the diagonal."""
    n = 5
    positions = [((k + 1) * 1000.0 / (n + 1), (k + 1) * 1000.0 / (n + 1))
                 for k in range(n)]
    params = {**CHECK, "positions": positions, **overrides}
    return AllenThermals(**params)


# -- the paper's own numbers --------------------------------------------


def test_outer_radius_matches_the_papers_example():
    field = check_field()
    assert field._r2_m(CHECK_Z) == pytest.approx(79.4, abs=0.2)


def test_updraft_count_matches_equation_20():
    """N = 0.6*X*Y/(zi*r2) rounds to five in the example (the paper says
    'the resulting five updrafts'). Our N uses the spacing height z/zi=0.4;
    the example's own r2 at its test height gives the same five."""
    field = AllenThermals(**CHECK)
    assert round(0.6 * 1000.0 * 1000.0 / (1401.0 * 79.4)) == 5
    assert 4 <= field.count <= 6


def test_centre_velocity_matches_figure_12():
    """Figure 12's single-updraft cross-section peaks near 2.7 m/s."""
    field = check_field()
    n, e = field.positions[0]
    assert field.w_at(n, e, CHECK_Z) == pytest.approx(2.7, abs=0.15)


def test_environment_sink_matches_figure_12():
    """The ambient level between updrafts in Figures 11-12 is ~ -0.13 m/s."""
    field = check_field()
    # A point far from every updraft on the anti-diagonal.
    w = field.w_at(900.0, 100.0, CHECK_Z)
    assert w == pytest.approx(-0.128, abs=0.02)


def test_shape_constant_lookup_is_appendix_bs_ladder():
    assert shape_constants(0.10) == K_SHAPE[0]
    assert shape_constants(0.80) == K_SHAPE[-1]
    # The example's r1/r2 = 0.0011*79.4 + 0.14 = 0.227 -> second row.
    assert shape_constants(0.227) == K_SHAPE[1]
    assert len(R1R2_SHAPE) == len(K_SHAPE) == 7


# -- conservation and shape ---------------------------------------------


def test_area_mean_vertical_velocity_is_near_zero():
    """The environment sink exists to balance the updraft mass flux
    (eq 21): the area-mean w over the field must be near zero. This is the
    conservation check the physics offers."""
    field = check_field()
    xs = np.linspace(5.0, 995.0, 100)
    total = 0.0
    for n in xs:
        for e in xs:
            total += field.w_at(float(n), float(e), CHECK_Z)
    mean = total / (len(xs) ** 2)
    # The blend (eq 23) stretches distributions slightly, so "near zero"
    # is relative to the peak: |mean| under 3% of the centre velocity.
    assert abs(mean) < 0.03 * 2.7, f"area-mean w = {mean:.4f} m/s"


def test_no_updraft_above_the_mixing_layer():
    field = check_field()
    n, e = field.positions[0]
    assert field.w_at(n, e, 1401.0 * 1.05) <= 0.0


def test_toroid_downdraft_ring_at_height():
    """At 0.5 < z/zi < 0.9 the edge of the updraft carries a downdraft ring
    stronger than the far-field sink (eqs 17-18, Figure 10)."""
    field = check_field()
    z = 0.7 * 1401.0
    n, e = field.positions[2]
    r2 = field._r2_m(z)
    ring = field.w_at(n, e + 1.4 * r2, z)
    far = field.w_at(900.0, 100.0, z)
    assert ring < far < 0.0


def test_zero_at_and_below_ground():
    field = check_field()
    assert field.w_at(500.0, 500.0, 0.0) == 0.0


# -- determinism and refusal --------------------------------------------


def test_placement_is_deterministic_from_the_seed():
    a = AllenThermals(**CHECK)
    b = AllenThermals(**CHECK)
    c = AllenThermals(**{**CHECK, "seed": 2})
    assert a.positions == b.positions
    assert a.positions != c.positions


def test_area_too_small_for_its_updrafts_is_refused():
    with pytest.raises(ValueError, match="cannot hold"):
        AllenThermals(wstar_mps=2.56, zi_m=1401.0, area_north_m=200.0,
                      area_east_m=200.0, seed=1,
                      positions=[(50.0, 50.0), (150.0, 150.0)])


def test_season_words_carry_the_tm_table():
    assert SEASON_TABLE["summer"] == (2.69, 1975.0)
    terms = check_field().vocabulary()
    assert any("NASA/TM-2006-214019" in t.standard for t in terms)


# -- the null test: a c172p crossing a column feels it -------------------


def test_null_crossing_a_thermal_lifts_the_aircraft():
    """Same aircraft, same track, one run with a thermal column planted on
    the flight path and one without: the crossing must show up as climb
    rate and altitude the calm run does not have.

    The column sits EARLY on the track (210 m out, crossed at t ~ 4-8 s):
    the c172p flown hands-off spirals gently left under prop torque, so a
    distant column would measure the drift, not the thermal. Measured with
    the column at 700 m the aircraft misses the 92 m core entirely; at
    210 m it flies through it (peak updraft seen 8.3 fps, the field's own
    2.5 m/s core).
    """

    def fly(with_thermal):
        from core.fdm import FlightDynamics, TrimMode

        fdm = FlightDynamics("c172p", rate_hz=120.0)
        # Heading 90: due east, straight through the column at (0, 210).
        fdm.set_initial_conditions(
            {"h-sl-ft": u.m_to_ft(500.0), "vc-kts": 100.0, "gamma-deg": 0.0,
             "phi-deg": 0.0, "psi-true-deg": 90.0, "beta-deg": 0.0,
             "lat-geod-deg": 0.0, "long-gc-deg": 0.0,
             "terrain-elevation-ft": 0.0}
        )
        fdm.start_engines()
        fdm.trim(TrimMode.LONGITUDINAL)
        fdm.hold_mass(True)
        providers = []
        if with_thermal:
            providers.append(AllenThermals(
                wstar_mps=2.56, zi_m=1401.0, area_north_m=2000.0,
                area_east_m=2000.0, origin_north_m=-1000.0,
                origin_east_m=-1000.0, seed=7,
                positions=[(0.0, 210.0)],
            ))
        stack = EnvironmentStack(providers)
        stack.configure(fdm)
        peak_climb = 0.0
        altitudes = []
        for _ in range(int(15 * fdm.rate_hz)):
            stack.apply(fdm)
            fdm.step()
            s = fdm.state()
            peak_climb = max(peak_climb, s.climb_rate_mps)
            altitudes.append(s.altitude_m)
        return peak_climb, altitudes

    climb_on, alt_on = fly(True)
    climb_off, alt_off = fly(False)
    diff = max(abs(a - b) for a, b in zip(alt_on, alt_off))
    assert diff > 2.0, f"thermal never reached the FDM (peak alt diff {diff:.2f} m)"
    assert climb_on > climb_off + 0.5, (
        f"no climb event crossing the column: {climb_on:.2f} vs "
        f"{climb_off:.2f} m/s")
