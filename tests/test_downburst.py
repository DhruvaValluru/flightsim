"""The downburst field: divergence-free, correctly shaped, correctly signed.

The module claims its vertical velocity is DERIVED from continuity rather
than shaped independently; that claim is checked numerically here, because an
algebra slip would produce a plausible-looking field that quietly creates or
destroys air.
"""

import math

import pytest

from core.environment.downburst import (
    _PEAK_ZETA, Downburst, _shaping, _shaping_integral,
)


def field(**overrides):
    parameters = dict(centre_north_m=0.0, centre_east_m=0.0,
                      core_radius_m=1000.0, outflow_max_mps=12.0,
                      outflow_height_m=150.0)
    parameters.update(overrides)
    return Downburst(**parameters)


def test_vicroy_shaping_peaks_at_outflow_height():
    # The published constants put the outflow maximum at z = zm. Verified
    # from the constants, not assumed from the paper.
    assert abs(_PEAK_ZETA - 1.0) < 2e-3
    assert _shaping(_PEAK_ZETA) > _shaping(0.5)
    assert _shaping(_PEAK_ZETA) > _shaping(2.0)


def test_shaping_integral_matches_numeric_quadrature():
    steps = 20000
    for zeta_top in (0.5, 1.0, 3.0):
        dz = zeta_top / steps
        numeric = sum(_shaping((i + 0.5) * dz) * dz for i in range(steps))
        assert abs(numeric - _shaping_integral(zeta_top)) < 1e-6


def test_field_is_divergence_free():
    # Cylindrical continuity: (1/r) d(r u_r)/dr + dw/dz = 0, checked by
    # central differences over a grid spanning core, ring and far field.
    burst = field()
    h = 0.5
    worst = 0.0
    for r in (50.0, 300.0, 700.0, 1000.0, 1400.0, 2500.0):
        for z in (30.0, 150.0, 400.0, 900.0):
            d_ru_dr = ((r + h) * burst.radial_outflow_mps(r + h, z)
                       - (r - h) * burst.radial_outflow_mps(r - h, z)) / (2 * h)
            dw_dz = (burst.vertical_mps(r, z + h)
                     - burst.vertical_mps(r, z - h)) / (2 * h)
            worst = max(worst, abs(d_ru_dr / r + dw_dz))
    assert worst < 1e-6, f"the field creates air: max |div| = {worst}"


def test_downdraft_inside_core_updraft_ring_outside():
    burst = field()
    assert burst.vertical_mps(0.0, 300.0) < -5.0          # core: strong down
    assert burst.vertical_mps(1500.0, 300.0) > 0.0        # ring: up
    assert abs(burst.vertical_mps(25000.0, 300.0)) < 1e-6  # far field: nothing


def test_outflow_peak_magnitude_and_location():
    burst = field()
    r_peak = 1000.0 / math.sqrt(2.0)
    z_peak = _PEAK_ZETA * 150.0
    peak = burst.radial_outflow_mps(r_peak, z_peak)
    assert abs(peak - 12.0) < 1e-9
    assert peak > burst.radial_outflow_mps(r_peak / 2, z_peak)
    assert peak > burst.radial_outflow_mps(r_peak * 2, z_peak)
    assert peak > burst.radial_outflow_mps(r_peak, z_peak * 4)


def test_crossing_the_core_reverses_the_along_track_wind():
    # The hazard is the reversal: approaching the centre from the south gives
    # a southerly (head)wind component, leaving it gives the opposite.
    burst = field()
    before = burst.wind_components(-800.0, 0.0, 300.0)
    after = burst.wind_components(800.0, 0.0, 300.0)
    assert before.north < -3.0
    assert after.north > 3.0
    assert abs(before.north + after.north) < 1e-9   # antisymmetric
    # NED down positive: still-sinking air at 0.8 R (the core itself sinks
    # far harder; see test_downdraft_inside_core_updraft_ring_outside).
    assert before.down > 2.0


def test_ground_and_axis_are_calm():
    burst = field()
    assert burst.radial_outflow_mps(500.0, 0.0) == 0.0
    calm = burst.wind_components(0.0, 0.0, 300.0)
    assert calm.north == 0.0 and calm.east == 0.0
    assert calm.down > 0.0    # but the axis still sinks


def test_refuses_nonsense_parameters():
    with pytest.raises(ValueError):
        field(core_radius_m=-1.0)
    with pytest.raises(ValueError):
        field(outflow_max_mps=-2.0)
    with pytest.raises(ValueError):
        field(outflow_height_m=0.0)
