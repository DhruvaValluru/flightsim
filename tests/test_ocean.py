"""Water rules transcribed from the simulator's ocean shaders."""
import numpy as np
import pytest

from core.xplane import ocean
from core.xplane.physical import WaterTiles


def test_fresnel_reduces_to_schlick_f0_at_normal_incidence():
    assert ocean.mean_fresnel(1.0) == pytest.approx(0.02)
    assert ocean.mean_fresnel(0.0) == pytest.approx(1.0)


def test_slope_variance_lowers_grazing_fresnel():
    assert ocean.mean_fresnel(0.2, 0.1) < ocean.mean_fresnel(0.2, 0.0)


def test_extinction_matches_the_water_tile_rule():
    for a8 in (0, 64, 128, 255):
        assert ocean.extinction_per_m(a8 / 255.0) == pytest.approx(
            WaterTiles.depth_attenuation(a8))


def test_depth_opacity():
    assert ocean.depth_opacity(0.0, 10.0) == pytest.approx(1 - np.exp(-1.0))
    assert ocean.depth_opacity(0.5, -3.0) == 0.0


def test_jonswap_published_example():
    s = ocean.jonswap(10.0, 100_000.0)
    assert s["alpha"] == pytest.approx(0.0101, abs=2e-4)
    assert s["peak_omega"] == pytest.approx(1.01, abs=0.01)


def test_composite_weights_deep_by_one_minus_fresnel():
    rgb, a = ocean.composite(np.ones(3), np.zeros(3), 0.25, opacity=1.5)
    assert np.allclose(rgb, 0.75) and a == 1.0
