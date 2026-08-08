"""Lee-rotor turbulence: the coupling the measurement allows, and nothing more.

docs/JSBSIM_CORRECTIONS.md §13 is the contract these tests enforce: intensity
that moves mid-run is delivered through W20 only, the seed and the POE
severity are written exactly once (severity pinned to zero), and the claimed
sigma_w cuts off above the 300 m AGL ceiling where the W20 route is inert.
"""

import math

import pytest

from core.environment.base import Position
from core.environment.rotor import (
    ROTOR_SIGMA_GAIN,
    SIGMA_W_PER_W20,
    W20_CAP_KT,
    W20_PROP,
    LeeRotorTurbulence,
)
from core.environment.stack import EnvironmentStack
from core.environment.terrain_field import OrographicWind, TerrainField
from core.environment.turbulence import LOW_ALTITUDE_CEILING_M
from core.fdm import units as u

from .test_environment import trimmed

#: A SINGLE Gaussian ridge, crest running east-west at n=0. A periodic ridge
#: would leave every "windward" point in the lee of the previous crest, which
#: is physically true but makes the null test's control side ambiguous; one
#: isolated ridge gives an upwind side with exactly zero lee sink.
RIDGE = TerrainField(
    lambda n, e: 400.0 * math.exp(-n * n / (2.0 * 600.0 ** 2)),
    wavelength_m=4000.0, name="gaussian_ridge",
)
WIND_MPS = 25.0
FROM_SOUTH = 180.0


def rotor(background="none", wind_mps=WIND_MPS, seed=17):
    return LeeRotorTurbulence(
        OrographicWind(RIDGE, wind_mps, FROM_SOUTH), seed=seed,
        background_intensity=background,
    )


def at(north_m, agl_m=150.0):
    """A Position at local-scene north offset, on the tangent plane."""
    return Position(latitude_deg=north_m / 111_320.0, longitude_deg=0.0,
                    altitude_m=agl_m, agl_m=agl_m, terrain_elevation_m=0.0)


#: Lee = ~1.5 crest prominences downwind (north) of the crest, inside the
#: rotor zone AC 00-57 places at 1-3 prominences; windward is the mirror
#: position upwind of the crest.
LEE = at(900.0)
WINDWARD = at(-900.0)


# -- the field shape -----------------------------------------------------


def test_rotor_sigma_positive_in_lee_zero_windward():
    provider = rotor()
    assert provider.rotor_sigma_w_mps(LEE) > 0.2
    assert provider.rotor_sigma_w_mps(WINDWARD) == 0.0


def test_rotor_needs_wind():
    assert rotor(wind_mps=0.0).rotor_sigma_w_mps(LEE) == 0.0


def test_rotor_sigma_decays_with_height():
    provider = rotor()
    low = provider.rotor_sigma_w_mps(at(900.0, agl_m=50.0))
    high = provider.rotor_sigma_w_mps(at(900.0, agl_m=280.0))
    assert 0.0 < high < low


def test_w20_is_capped_at_severe():
    """A hurricane over a cliff must not claim intensities off the ladder."""
    provider = rotor(wind_mps=80.0)
    assert provider.w20_kt_at(at(1500.0)) == W20_CAP_KT


def test_background_word_is_a_floor():
    provider = rotor(background="moderate")
    assert provider.w20_kt_at(WINDWARD) == pytest.approx(30.0)
    assert provider.w20_kt_at(LEE) >= 30.0


# -- the §13 contract ----------------------------------------------------


def test_configure_pins_severity_nonzero_and_writes_seed_once():
    """Severity 0 is a measured master off-switch (it silences the W20 route
    too); the pin must be nonzero, constant, and written only at configure."""
    writes = rotor().configure()
    assert writes["atmosphere/turbulence/milspec/severity"] == 1.0
    assert writes["atmosphere/randomseed"] == 17.0


def test_step_writes_touch_w20_and_nothing_else():
    """The seed re-write is the 515 g failure; severity steps deliver 2-5x
    the commanded sigma_w. Neither may ever appear in the per-step writes."""
    writes = rotor().step_writes(LEE, 0.0)
    assert set(writes) == {W20_PROP}


def test_claimed_sigma_above_the_ceiling_is_the_pinned_floor():
    """Above 300 m AGL the W20 route is inert: the claim is the constant POE
    index-1 floor (1.785 fps), stated, never the rotor coupling."""
    from core.environment.turbulence import POE_SIGMA_W_FPS
    provider = rotor()
    assert provider.expected_sigma_w_mps(LOW_ALTITUDE_CEILING_M + 1.0) == (
        pytest.approx(u.fps_to_mps(POE_SIGMA_W_FPS[1])))
    below = provider.expected_sigma_w_mps(150.0, position=LEE)
    assert below == pytest.approx(
        u.fps_to_mps(SIGMA_W_PER_W20 * u.kt_to_fps(provider.w20_kt_at(LEE))))


def test_vocabulary_states_the_ceiling_and_the_anchor():
    term = {t.phrase: t for t in rotor().vocabulary()}["rotor turbulence"]
    assert "300" in term.note
    assert term.value == ROTOR_SIGMA_GAIN
    assert "Doyle" in term.standard


# -- the null test: did the rotor reach the FDM? -------------------------


def test_null_lee_rotor_turbulence_reaches_the_fdm():
    """Same seed, same altitude, same aircraft; a track in the lee must fly
    through measurably rougher air than the mirror track windward."""

    def turb_rms(north_m):
        fdm = trimmed(altitude_m=150.0, cas_kt=250.0)
        stack = EnvironmentStack([rotor()])
        # Place the aircraft on the tangent-plane offset and fly east, along
        # the ridge, so it stays in its zone for the whole run.
        fdm.set_initial_conditions(
            {"h-sl-ft": u.m_to_ft(150.0), "vc-kts": 250.0, "gamma-deg": 0.0,
             "phi-deg": 0.0, "psi-true-deg": 90.0, "beta-deg": 0.0,
             "lat-geod-deg": north_m / 111_320.0, "long-gc-deg": 0.0,
             "terrain-elevation-ft": 0.0}
        )
        fdm.trim()
        stack.configure(fdm)
        total = 0.0
        samples = 0
        for _ in range(int(15 * fdm.rate_hz)):
            stack.apply(fdm)
            fdm.step()
            w = fdm.props.get("atmosphere/turb-down-fps")
            total += w * w
            samples += 1
        return math.sqrt(total / samples)

    lee_rms = turb_rms(900.0)
    windward_rms = turb_rms(-900.0)
    assert windward_rms < 0.1, "windward air should be still (background none)"
    assert lee_rms > 10.0 * max(windward_rms, 1e-6), (
        f"lee rotor turbulence never reached the FDM: lee RMS {lee_rms:.3f} "
        f"fps vs windward {windward_rms:.3f} fps"
    )
