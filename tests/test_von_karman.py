"""P6, the von Karman field (core/environment/von_karman.py): the spectra
normalise, the sigma and scale ladders are FGWinds' and the blueprint's,
the realised table carries the commanded sigma and the -5/3 slope, the
same seed gives the same table to the bit through the named stream, and
the card rows are %.17g strings.

Every number asserted here was measured in the container on 2026-09-28
(JSBSim 1.2.4 in .venv; numpy 2.0.2). What is NOT claimed: the
specification's own numbers beyond FGWinds' transcription (marked
unverified in the module), the engine side, any aircraft response (that
is tests/test_gust_provider.py's).
"""
from __future__ import annotations

import inspect
import json
import math
from pathlib import Path

import numpy as np
import pytest

from core.environment import von_karman as vk
from core.environment.von_karman import (
    CARD_KEYS, N_FREQUENCIES, ROW_FORMAT, SEED_STREAM, VonKarmanTurbulence,
    bin_energies, draw_phases, harmonics, p_gust_parameters, phi_p, phi_u, phi_v, phi_w,
    poe_sigma_fps, psd_slope, scale_lengths_ft, sigma_ladder_fps, spectrum_integral,
)
from core.experiments.seeds import stable_hash
from core.fdm import units as u

REPO = Path(__file__).resolve().parents[1]
#: The c172p's condition the item measures on: 1500 m ASL (4921.26 ft),
#: 100 kt CAS (TAS 55.322 m/s), span 35.8 ft (10.912 m), 120 Hz.
ALTITUDE_M = 1500.0
TAS_MPS = 55.32206123132793
SPAN_M = 10.91184


def provider(seed=7, duration_s=3.0, intensity="moderate", altitude_m=ALTITUDE_M):
    return VonKarmanTurbulence(intensity, seed=seed, altitude_m=altitude_m,
                               duration_s=duration_s, rate_hz=120.0)


# -- the spectra ------------------------------------------------------------------------

@pytest.mark.parametrize("label,phi,sigma", [
    ("u", lambda w: phi_u(w, 2.0, 762.0), 2.0),
    ("v", lambda w: phi_v(w, 2.0, 381.0), 2.0),
    ("w", lambda w: phi_w(w, 2.0, 381.0), 2.0),
    ("p", lambda w: phi_p(w, 0.1, 40.0), 0.1),
])
def test_each_spectrum_integrates_to_sigma_squared(label, phi, sigma):
    """The MIL-F-8785C forms are normalised so that the integral over
    0..inf is sigma^2 (the 1.339 constant's job): measured 1.00013 (u),
    0.99997 (w), 1.0000 (p) up to 1e5 rad/m."""
    assert spectrum_integral(phi, 1e5) / sigma ** 2 == pytest.approx(1.0, abs=2e-3), label


def test_the_asymptotic_slope_of_u_and_w_is_minus_five_thirds():
    """Far above 1/(1.339 L) both spectra fall as Omega^(-5/3): the
    log-log slope between 0.1 and 1 rad/m at the c172p's scales is
    -1.667 (u) and -1.666 (w); the p-gust's first-order form falls as
    Omega^-2."""
    omega = np.geomspace(0.1, 1.0, 50)
    for phi in (lambda w: phi_u(w, 2.0, 762.0), lambda w: phi_w(w, 2.0, 381.0)):
        slope = np.polyfit(np.log(omega), np.log(phi(omega)), 1)[0]
        assert slope == pytest.approx(-5.0 / 3.0, abs=0.01)
    slope_p = np.polyfit(np.log(omega), np.log(phi_p(omega, 0.1, 40.0)), 1)[0]
    assert slope_p == pytest.approx(-2.0, abs=0.05)      # L_p Omega = 4 at 0.1 rad/m: -1.98 measured


# -- the ladders ------------------------------------------------------------------------

def test_the_exceedance_table_is_fgwinds_figure_7_and_interpolates_in_altitude():
    assert poe_sigma_fps(3, 500.0) == 6.6 and poe_sigma_fps(3, 3750.0) == 7.4
    assert poe_sigma_fps(7, 80000.0) == 7.2 and poe_sigma_fps(7, 90000.0) == 7.2   # held
    assert poe_sigma_fps(3, 100.0) == 6.6                                            # held
    assert poe_sigma_fps(3, 4921.259842519685) == pytest.approx(7.181364829396326)
    assert poe_sigma_fps(0, 4921.0) == 0.0
    with pytest.raises(ValueError):
        poe_sigma_fps(8, 4921.0)


def test_the_sigma_ladder_is_fgwinds_l276_l288():
    """Below 1000 ft sigma_w = 0.1 W20 and sigma_u = sigma_w/(0.177 +
    0.000823 h)^0.4 (L279-L280); above 2000 ft the table (L288); linear
    between (L284-L285); h clipped at 10 ft (L273)."""
    assert sigma_ladder_fps(500.0, 25.0, 3) == pytest.approx(
        (3.0905901903566573, 3.0905901903566573, 2.5))
    assert sigma_ladder_fps(750.0, 25.0, 3)[2] == 2.5                 # the low band, exactly
    assert sigma_ladder_fps(1500.0, 25.0, 3) == pytest.approx((4.67, 4.67, 4.67))
    assert sigma_ladder_fps(4921.259842519685, 50.634, 3) == pytest.approx(
        (7.181364829396326,) * 3)
    assert sigma_ladder_fps(1000.0, 25.0, 3)[2] == 2.5                # the branch at 1000 ft
    assert sigma_ladder_fps(0.0, 25.0, 3) == sigma_ladder_fps(10.0, 25.0, 3)
    # The moderate word: W20 30 kt at the c172p's altitude gives the table row.
    sigma = provider().sigma_fps
    assert sigma == pytest.approx((7.181364829396326,) * 3)


def test_the_scale_lengths_are_l_u_equals_2_l_v_equals_2_l_w_above_2000_ft():
    """Correction 5: L_u = 2 L_v = 2 L_w = 2500 ft; the low-altitude
    relations below 1000 ft (L_w = h, L_u = L_v = h/(0.177+0.000823h)^1.2);
    linear between; clipped at 10 ft."""
    assert scale_lengths_ft(4921.259842519685) == (2500.0, 1250.0, 1250.0)
    assert scale_lengths_ft(50000.0) == (2500.0, 1250.0, 1250.0)
    l_u, l_v, l_w = scale_lengths_ft(500.0)
    assert l_w == 500.0 and l_u == l_v == pytest.approx(944.6572102018667)
    assert scale_lengths_ft(1000.0) == pytest.approx((1000.0, 1000.0, 1000.0))
    assert scale_lengths_ft(1500.0) == pytest.approx((1750.0, 1125.0, 1125.0))
    assert scale_lengths_ft(5.0) == scale_lengths_ft(10.0)
    assert provider().scale_ft == (2500.0, 1250.0, 1250.0)
    assert provider().scale_m == pytest.approx((762.0, 381.0, 381.0))


def test_the_roll_gust_parameters_are_yeager_eqs_8_and_10():
    sigma_p, l_p = p_gust_parameters(7.181364829396326, 1250.0, 35.8)
    assert sigma_p == pytest.approx(1.9 * 7.181364829396326 / math.sqrt(1250.0 * 35.8))
    assert l_p == pytest.approx(math.sqrt(1250.0 * 35.8) / 2.6)
    assert (sigma_p, l_p) == pytest.approx((0.0645006470773544, 81.3622915434853))
    with pytest.raises(ValueError):
        p_gust_parameters(1.0, 0.0, 10.0)


def test_a_numeric_w20_picks_the_nearest_exceedance_row_and_a_word_maps_as_dryden():
    word = provider(intensity="moderate")
    assert word.word == "moderate" and word.w20_kt == 30.0 and word.poe_index == 3
    number = provider(intensity=30.0)
    assert number.word is None and number.w20_kt == 30.0
    # 0.1 x 50.63 fps = 5.06 fps at 4921 ft: row 3 (7.18) is nearer than row 2 (2.77).
    assert number.poe_index == 3
    low = provider(intensity=30.0, altitude_m=100.0)
    assert low.sigma_fps[2] == pytest.approx(0.1 * u.kt_to_fps(30.0))
    with pytest.raises(ValueError):
        provider(intensity="hurricane")
    with pytest.raises(ValueError):
        provider(intensity=-1.0)
    assert provider(intensity="none").silent


# -- the realisation --------------------------------------------------------------------

def test_the_phases_come_from_the_named_stream_and_the_seed():
    """default_rng(SeedSequence(seed, spawn_key=(stable_hash('von_karman'),)));
    the first phase for seed 7 is 2.51559109465875, for seed 8
    3.1082881788848336 (measured; pinned so the stream name is load-bearing)."""
    assert SEED_STREAM == "von_karman"
    assert stable_hash(SEED_STREAM) == 697359353913396029
    phases = draw_phases(7, 4)
    assert phases.shape == (4, 4)
    assert phases[0][0] == pytest.approx(2.51559109465875, abs=1e-12)
    assert draw_phases(8, 4)[0][0] == pytest.approx(3.1082881788848336, abs=1e-12)
    assert np.array_equal(draw_phases(7, 300), draw_phases(7, 300))
    assert ((phases >= 0.0) & (phases < 2.0 * math.pi)).all()


def test_the_harmonics_are_log_spaced_targets_snapped_to_whole_cycles():
    ks = harmonics(361)
    assert ks[0] == 1 and ks[-1] == 361 // 2 - 1 and len(ks) == 113
    assert (np.diff(ks) > 0).all() and ks.dtype.kind == "i"
    assert len(harmonics(7201)) == 179 and len(harmonics(7201)) <= N_FREQUENCIES
    with pytest.raises(ValueError):
        harmonics(4)


def test_bin_energies_sum_to_the_spectrum_integral():
    omegas = harmonics(7201) * (2.0 * math.pi / (TAS_MPS * 7201 / 120.0))
    energies = bin_energies(lambda w: phi_u(w, 2.0, 762.0), omegas)
    assert energies.sum() == pytest.approx(4.0, rel=3e-3)     # 0.19 % lost above the last bin
    assert (energies > 0).all()


@pytest.mark.parametrize("duration_s,expect_slope", [(3.0, None), (60.0, -1.665)])
def test_the_table_carries_the_commanded_sigma_and_the_slope(duration_s, expect_slope):
    """Over the table each component's std is the commanded sigma within
    0.5 % (measured: u 2.1867/2.1868 vs 2.1889, v and w 2.1844 vs 2.1889,
    p 0.06441 vs 0.06450 for 3 and 60 s), the mean is zero to 1e-15 (whole
    cycles), and on the 60 s table the periodogram's log-log slope over
    0.1..1 rad/m is -1.665 (12 bands) against -5/3. The 3 s table holds
    too few lines per band for the fit (reported, not pinned)."""
    p = provider(duration_s=duration_s)
    table = p.build(TAS_MPS, SPAN_M)
    assert table.shape == (int(duration_s * 120) + 1, 5)
    assert np.array_equal(table[:, 0], np.arange(table.shape[0]) / 120.0)
    built = p.built
    for column, label in ((1, "u"), (2, "v"), (3, "w"), (4, "p")):
        commanded = built["realised"][label]["sigma_commanded"]
        assert table[:, column].std() == pytest.approx(commanded, rel=0.01)
        assert table[:, column].std() == pytest.approx(commanded, rel=0.10)    # the claim
        assert table[:, column].std() == pytest.approx(built["realised"][label]["sigma_amplitudes"], rel=1e-12)
        assert abs(table[:, column].mean()) < 1e-12 * commanded + 1e-15
        assert built["realised"][label]["truncated_fraction"] < 0.005
    assert built["realised"]["w"]["sigma_commanded"] == pytest.approx(u.fps_to_mps(7.181364829396326))
    assert built["n_frequencies"] == N_FREQUENCIES
    slope = built["realised"]["u"]["psd_slope"]
    if expect_slope is None:
        assert slope is None or slope["bands"] < 12 or abs(slope["slope"] + 5.0 / 3.0) < 0.3
    else:
        assert slope["bands"] == 12 and slope["slope"] == pytest.approx(expect_slope, abs=0.02)
        assert slope["slope"] == pytest.approx(-5.0 / 3.0, abs=0.1)
        for label in ("v", "w"):
            assert built["realised"][label]["psd_slope"]["slope"] == pytest.approx(-5.0 / 3.0, abs=0.1)


def test_psd_slope_is_measured_from_the_column_not_from_the_construction():
    """A synthetic Omega^-2 line spectrum on the same harmonic grid fits -2,
    so the fit reads the data (the -5/3 above is the spectrum's, not the
    fitter's)."""
    n = 7201
    x_length = TAS_MPS * n / 120.0
    ks = harmonics(n)
    omegas = ks * 2.0 * math.pi / x_length
    x = TAS_MPS * np.arange(n) / 120.0
    amplitudes = np.sqrt(omegas ** -2.0 * np.diff(np.concatenate(([0.0], 0.5 * (omegas[:-1] + omegas[1:]), [omegas[-1] * 1.01]))))
    series = (amplitudes[None, :] * np.cos(np.outer(x, omegas))).sum(axis=1)
    fit = psd_slope(series, x_length)
    assert fit is not None and fit["slope"] == pytest.approx(-2.0, abs=0.15)
    assert psd_slope(np.zeros(n), x_length) is None


def test_the_same_seed_gives_the_same_table_to_the_bit_and_another_seed_differs():
    a = provider(seed=7).build(TAS_MPS, SPAN_M)
    b = provider(seed=7).build(TAS_MPS, SPAN_M)
    c = provider(seed=8).build(TAS_MPS, SPAN_M)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c) and a[:, 0].tolist() == c[:, 0].tolist()
    assert provider(seed=7).build(TAS_MPS, SPAN_M)[1].tolist() == pytest.approx(
        [1 / 120.0, -2.8446120819651921, 2.4122232716735685, 2.8392513736911078,
         -0.0040209645713615069], abs=1e-15)


def test_a_silent_intensity_builds_a_table_of_zeros():
    table = provider(intensity="none").build(TAS_MPS, SPAN_M)
    assert not table[:, 1:].any() and table.shape == (361, 5)


def test_the_build_refuses_a_zero_airspeed_or_span():
    with pytest.raises(ValueError):
        provider().build(0.0, SPAN_M)
    with pytest.raises(ValueError):
        provider().build(TAS_MPS, 0.0)


# -- the card form ------------------------------------------------------------------------

def test_the_card_rows_are_17_significant_digit_strings_that_round_trip():
    """%.17g: every row value survives str -> float exactly, so both hosts
    write the same doubles; the block's keys are the fixed order and the
    sha256 covers the rows' text."""
    p = provider()
    p.build(TAS_MPS, SPAN_M)
    rows = p.card_rows()
    assert len(rows) == 361 and all(len(row) == 5 for row in rows)
    assert ROW_FORMAT == "%.17g"
    for row, values in zip(rows, p.table):
        assert row == [ROW_FORMAT % v for v in values]
        assert [float(s) for s in row] == list(values)
        assert all(s.isascii() for s in row)
    assert rows[1] == ["0.0083333333333333332", "-2.8446120819651921", "2.4122232716735685",
                       "2.8392513736911078", "-0.0040209645713615069"]
    block = p.card_block()
    assert tuple(block) == CARD_KEYS
    assert block["model"] == "von_karman" and block["seed"] == 7
    assert block["sigma"] == pytest.approx([u.fps_to_mps(7.181364829396326)] * 3)
    assert block["L"] == pytest.approx([762.0, 381.0, 381.0])
    assert block["tas_mps"] == TAS_MPS and block["dt_s"] == 1 / 120.0
    assert block["sha256"] == p.rows_sha256(rows)
    assert block["sha256"] == "acd2ceacc2422818ae0c80580fb294fd4a6a7869d89bae4f9cadc56c4d805ca5"
    assert json.dumps(block).isascii()
    with pytest.raises(ValueError):
        provider().card_rows()                    # not built


def test_the_row_lookup_latches_the_first_call_as_row_zero_and_counts_past_the_end():
    from core.environment.base import OwnShipState, Position

    p = provider()
    p.build(TAS_MPS, SPAN_M)
    own = OwnShipState(Position(0.0, 0.0, 1500.0, 1500.0, 0.0), 55.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                       SPAN_M, TAS_MPS)
    first = p.gust_at(own, 4.875)                # JSBSim's clock after the crank
    assert p.t_start_s == 4.875 and p.built["t_start_s"] == 4.875
    assert (first.north, first.east, first.down) == pytest.approx(
        (p.table[0][1], p.table[0][2], p.table[0][3]))
    assert p.p_equivalent_at(own, 4.875 + 1 / 120.0) == p.table[1][4]
    beyond = p.gust_at(own, 4.875 + 4.0)
    assert (beyond.north, beyond.east, beyond.down) == (0.0, 0.0, 0.0)
    assert p.steps_beyond_table == 1 and p.steps_delivered == 1


def test_the_gust_is_rotated_by_the_heading_the_table_was_built_with():
    from core.environment.base import OwnShipState, Position

    p = VonKarmanTurbulence("moderate", seed=7, altitude_m=ALTITUDE_M, duration_s=1.0,
                            rate_hz=120.0, heading_deg=90.0)
    p.build(TAS_MPS, SPAN_M)
    own = OwnShipState(Position(0.0, 0.0, 1500.0, 1500.0, 0.0), 0.0, 55.0, 0.0, 0.0, 0.0, 90.0,
                       SPAN_M, TAS_MPS)
    g = p.gust_at(own, 0.0)
    along, right, down = p.table[0][1:4]
    assert g.north == pytest.approx(-right) and g.east == pytest.approx(along)
    assert g.down == down


def test_the_record_refuses_a_provider_never_prepared_and_the_module_is_ascii():
    with pytest.raises(ValueError):
        provider().applied_variables({})
    assert (REPO / "core/environment/von_karman.py").read_text(encoding="utf-8").isascii()
    assert inspect.getsource(vk).isascii()
