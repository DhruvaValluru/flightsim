"""Linearised modal analysis against the handling-qualities bands
(gap M2, validation row A5; core/fdm/linearize.py, core/fdm/modes.py,
flightsim/modes.py).

What is measured here: JSBSim's own linearisation (``FGLinearization``)
of the c172p at the examples' cruise condition
(examples/cameras_waypoint.yaml: 1200 m, 100 kt CAS) gives modes inside
PLAUSIBILITY bands (short period, phugoid, Dutch roll) -- plausibility,
not validation: no referent exists for this model; the independent
Jacobian agrees with JSBSim's under the stated bound; the modes differ
between two airspeeds (the null test of the analysis); the levels
follow the encoded bands on synthetic modes and on the measured c172p;
the A320 and B747 run and their modes are recorded (no band asserted);
refusals arrive by name; the CLI prints ASCII and writes the record.

Not claimed: that any airframe meets a handling-qualities requirement;
the band numbers as re-checked against MIL-F-8785C (unverified here);
the DHC6 and p51d, which do not load in this container.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from core.fdm import FlightDynamics
from core.fdm import units as u
from core.fdm.linearize import (
    CLASSICAL_STATES, FT_TO_M, LATERAL_STATES, LONGITUDINAL_STATES, RESIDUAL_BOUND,
    RESIDUAL_STEP, ModesError, Residual, check_residual, classical_block, linearize,
)
from core.fdm.modes import (
    AIRFRAME_CLASS, BANDS, BELOW_LEVEL_3, MODES_VERSION, analyse, analyse_spec, assign_levels,
    bands_block, lateral_modes, longitudinal_modes, modes_block, n_alpha, worst_level,
)
from core.nl.compiler import compile_prompt
from core.scenario.blocks import configured_airframes
from core.scenario.spec import ScenarioSpec
from flightsim.modes import main as modes_main, render_table

EXAMPLE = "examples/cameras_waypoint.yaml"


# -- fixtures: one trim and one linearisation per condition ---------------------

@pytest.fixture(scope="module")
def c172p_cruise():
    """The examples' cruise condition: c172p, 1200 m, 100 kt CAS."""
    spec = ScenarioSpec.read(EXAMPLE)
    assert (str(spec.aircraft.value), float(spec.altitude.value),
            float(spec.airspeed.value)) == ("c172p", 1200.0, 100.0)
    return analyse_spec(spec)


@pytest.fixture(scope="module")
def c172p_faster():
    return analyse_spec(compile_prompt("fly the c172p at 1200 m and 120 kt for 5 seconds"))


@pytest.fixture(scope="module")
def a320():
    return analyse_spec(compile_prompt("fly the A320 at 3000 m and 250 kt for 5 seconds"))


@pytest.fixture(scope="module")
def b747():
    return analyse_spec(compile_prompt("fly the B747 at 3000 m and 250 kt for 5 seconds"))


# -- the c172p at cruise: plausibility bands, not validation -----------------------

def test_c172p_cruise_modes_lie_in_the_plausibility_bands(c172p_cruise):
    """Measured 2026-09-28: short period wn 7.01 rad/s, zeta 0.610,
    period 1.13 s; phugoid period 26.1 s, zeta 0.114; Dutch roll wn 2.44
    rad/s, zeta 0.185; roll tau 0.146 s; spiral stable, T1/2 29.4 s.
    These bands are plausibility for a light single; no referent."""
    m = c172p_cruise.modes
    sp, ph, dr = m["short_period"], m["phugoid"], m["dutch_roll"]
    assert sp["oscillatory"] and 0.3 < sp["zeta"] < 1.0 and sp["period_s"] < 5.0
    assert ph["oscillatory"] and 15.0 < ph["period_s"] < 60.0
    assert dr["oscillatory"] and 0.5 < dr["omega_n_rad_s"] < 4.0
    assert m["roll"]["stable"] and 0.0 < m["roll"]["time_constant_s"] < 2.0
    assert not m["roll"]["coupled"]
    assert c172p_cruise.model.method == "jsbsim.FGLinearization"


def test_the_short_period_is_the_faster_longitudinal_pair(c172p_cruise):
    """The mapping rule, on the measured matrix: the pair named the short
    period has the higher natural frequency of the two; the phugoid the
    lower. The guard flips the sort so the names swap."""
    sp, ph = c172p_cruise.modes["short_period"], c172p_cruise.modes["phugoid"]
    assert sp["omega_n_rad_s"] > 10.0 * ph["omega_n_rad_s"]
    dr = c172p_cruise.modes["dutch_roll"]
    roll, spiral = c172p_cruise.modes["roll"], c172p_cruise.modes["spiral"]
    assert abs(roll["eigenvalues"][0][0]) > dr["omega_n_rad_s"] > abs(spiral["eigenvalues"][0][0])


# -- the residual ----------------------------------------------------------------------

@pytest.mark.parametrize("name", ["c172p_cruise", "a320", "b747"])
def test_the_independent_jacobian_agrees_with_jsbsim_under_the_bound(name, request):
    """Measured 2026-09-28 at step 1e-4 (relative Frobenius, lon / lat):
    c172p 3.2e-3 / 1.0e-5; A320 2.3e-9 / 7.1e-7; B747 2.1e-9 / 2.5e-7;
    bound 1e-2. The linear range at 1e-3: c172p 3.2e-3 / 6.9e-5, A320
    4.7e-2 / 2.0e-5 (a CD-table breakpoint 0.5 mrad below trim alpha),
    B747 2.1e-7 / 7.1e-6 -- reported, not bounded."""
    result = request.getfixturevalue(name)
    res = result.model.residual
    assert res.ok and res.step == RESIDUAL_STEP and res.bound == RESIDUAL_BOUND
    assert res.longitudinal < RESIDUAL_BOUND and res.lateral < RESIDUAL_BOUND
    rng = result.model.linear_range
    assert rng["step"] > res.step and math.isfinite(rng["longitudinal"])
    assert result.to_dict()["refusals"] == []


def test_the_residual_measurement_restores_the_trim_state(c172p_cruise):
    """The derivatives after linearising and perturbing equal those
    before to within the disturbance JSBSim's own linearisation leaves
    (measured 8.5e-6 rad/s^2 on the c172p); the runner never linearises
    the flight's own FDM for this reason."""
    d = c172p_cruise.model.disturbance
    assert 0.0 <= d["max_abs_xdot_change"] < 1e-4


def test_a_residual_beyond_the_bound_is_refused_by_name():
    bad = Residual(step=1e-4, longitudinal=0.2, lateral=1e-6, max_abs=1.0,
                   max_abs_entry=("Q", "Alpha"), bound=RESIDUAL_BOUND)
    assert not bad.ok
    with pytest.raises(ModesError) as exc:
        check_residual(bad)
    assert exc.value.constraint == "modes.residual"
    good = Residual(step=1e-4, longitudinal=1e-3, lateral=1e-6, max_abs=0.1,
                    max_abs_entry=("Q", "Alpha"), bound=RESIDUAL_BOUND)
    check_residual(good)
    assert good.to_dict()["ok"] is True


def test_the_residual_bound_is_applied_by_linearize(c172p_cruise):
    """Reusing the module's FDM route: a bound below the measured c172p
    residual makes linearize refuse by name."""
    spec = ScenarioSpec.read(EXAMPLE)
    from core.scenario.runner import configure_from_spec
    fdm = configure_from_spec(spec)
    with pytest.raises(ModesError) as exc:
        linearize(fdm, residual_bound=1e-4)
    assert exc.value.constraint == "modes.residual"


# -- the null test: two airspeeds ----------------------------------------------------------

def test_modes_differ_between_two_airspeeds(c172p_cruise, c172p_faster):
    """Measured 2026-09-28, c172p at 1200 m: short period wn 7.01 -> 8.31
    rad/s (100 -> 120 kt), Dutch roll wn 2.44 -> 2.89 rad/s, phugoid
    period 26.1 -> 29.3 s. An analysis that returned the same modes for
    two airspeeds would not be reading the trim."""
    a, b = c172p_cruise.modes, c172p_faster.modes
    assert c172p_faster.trim["vt_mps"] > c172p_cruise.trim["vt_mps"] * 1.1
    assert b["short_period"]["omega_n_rad_s"] > a["short_period"]["omega_n_rad_s"] * 1.1
    assert b["dutch_roll"]["omega_n_rad_s"] > a["dutch_roll"]["omega_n_rad_s"] * 1.1
    assert abs(b["phugoid"]["period_s"] - a["phugoid"]["period_s"]) > 1.0


# -- the transports: run and record, no band asserted -----------------------------------------

@pytest.mark.parametrize("name", ["a320", "b747"])
def test_transports_run_and_record_their_modes(name, request):
    """Measured 2026-09-28 at 3000 m / 250 kt: A320 short period wn 2.53
    rad/s zeta 0.225, phugoid period 69 s, Dutch roll wn 3.41 zeta 0.56,
    roll tau 0.57 s, spiral stable; B747 short period wn 1.30 zeta 0.50,
    phugoid period 83 s, Dutch roll wn 0.92 zeta 0.34, roll tau 0.84 s,
    spiral stable. Recorded, not graded against a referent."""
    result = request.getfixturevalue(name)
    record = result.to_dict()
    assert record["attempted"] and record["airframe_class"] == "III"
    for mode in ("short_period", "phugoid", "dutch_roll"):
        assert record["modes"][mode]["oscillatory"]
        assert math.isfinite(record["modes"][mode]["omega_n_rad_s"])
    assert record["modes"]["roll"]["stable"]
    assert set(record["levels"]) == {"short_period_damping", "short_period_frequency",
                                     "phugoid", "dutch_roll", "roll", "spiral"}
    assert record["overall_level"] in (1, 2, 3, BELOW_LEVEL_3)


# -- eigenvalues to modes, on synthetic matrices ------------------------------------------------

def _oscillator(wn: float, zeta: float) -> np.ndarray:
    return np.array([[0.0, 1.0], [-wn ** 2, -2.0 * zeta * wn]])


def _block_diag(*blocks):
    n = sum(b.shape[0] for b in blocks)
    out = np.zeros((n, n))
    i = 0
    for b in blocks:
        k = b.shape[0]
        out[i:i + k, i:i + k] = b
        i += k
    return out


def test_longitudinal_mapping_names_the_faster_pair_the_short_period():
    A = _block_diag(_oscillator(0.2, 0.05), _oscillator(5.0, 0.6))   # phugoid first on purpose
    m = longitudinal_modes(A)
    assert m["short_period"]["omega_n_rad_s"] == pytest.approx(5.0)
    assert m["short_period"]["zeta"] == pytest.approx(0.6)
    assert m["short_period"]["period_s"] == pytest.approx(2 * math.pi / (5.0 * math.sqrt(1 - 0.36)))
    assert m["phugoid"]["omega_n_rad_s"] == pytest.approx(0.2)
    assert m["phugoid"]["zeta"] == pytest.approx(0.05)


def test_longitudinal_mapping_with_real_roots():
    # one pair (the phugoid, slow) and two large real roots: a non-oscillatory short period
    A = _block_diag(_oscillator(0.2, 0.05), np.diag([-3.0, -8.0]))
    m = longitudinal_modes(A)
    assert not m["short_period"]["oscillatory"] and m["short_period"]["stable"]
    assert sorted(r for r, _ in m["short_period"]["eigenvalues"]) == [-8.0, -3.0]
    assert m["phugoid"]["oscillatory"] and m["phugoid"]["omega_n_rad_s"] == pytest.approx(0.2)
    # one fast pair and two tiny real roots: a non-oscillatory phugoid, one unstable
    A = _block_diag(_oscillator(5.0, 0.6), np.diag([-0.01, 0.002]))
    m = longitudinal_modes(A)
    assert m["short_period"]["oscillatory"]
    assert not m["phugoid"]["oscillatory"] and not m["phugoid"]["stable"]


def test_lateral_mapping_names_dutch_roll_roll_and_spiral():
    A = _block_diag(np.diag([-0.02, -8.0]), _oscillator(2.4, 0.18))
    m = lateral_modes(A)
    assert m["dutch_roll"]["omega_n_rad_s"] == pytest.approx(2.4)
    assert m["dutch_roll"]["zeta"] == pytest.approx(0.18)
    assert m["roll"]["time_constant_s"] == pytest.approx(1 / 8.0)
    assert m["spiral"]["eigenvalues"] == [[-0.02, 0.0]]
    assert m["spiral"]["stable"] and m["spiral"]["time_to_half_s"] == pytest.approx(math.log(2) / 0.02)
    # an unstable spiral carries its time to double
    A = _block_diag(np.diag([0.02, -8.0]), _oscillator(2.4, 0.18))
    m = lateral_modes(A)
    assert not m["spiral"]["stable"]
    assert m["spiral"]["time_to_double_s"] == pytest.approx(math.log(2) / 0.02)
    # a coupled roll-spiral pair is reported as such
    A = _block_diag(_oscillator(0.3, 0.2), _oscillator(2.4, 0.18))
    m = lateral_modes(A)
    assert m["dutch_roll"]["omega_n_rad_s"] == pytest.approx(2.4)
    assert m["roll"]["coupled"] and m["spiral"]["coupled"]
    assert m["roll"]["omega_n_rad_s"] == pytest.approx(0.3)


def test_classical_block_is_a_similarity_transform_into_si():
    names = ("Vt", "Alpha", "Theta", "Q", "Beta", "Phi", "P", "Psi", "R")
    rng = np.random.default_rng(3)
    A = rng.normal(size=(9, 9))
    lon = classical_block(A, names, LONGITUDINAL_STATES)
    lat = classical_block(A, names, LATERAL_STATES)
    raw_lon = A[np.ix_([0, 1, 2, 3], [0, 1, 2, 3])]
    assert np.allclose(sorted(np.linalg.eigvals(lon), key=lambda e: (e.real, e.imag)),
                       sorted(np.linalg.eigvals(raw_lon), key=lambda e: (e.real, e.imag)))
    # the Vt row is scaled by ft->m, the Vt column by m->ft, the diagonal untouched
    assert lon[0, 1] == pytest.approx(raw_lon[0, 1] * FT_TO_M)
    assert lon[1, 0] == pytest.approx(raw_lon[1, 0] / FT_TO_M)
    assert lon[0, 0] == pytest.approx(raw_lon[0, 0])
    assert np.array_equal(lat, A[np.ix_([4, 5, 6, 8], [4, 5, 6, 8])])
    assert CLASSICAL_STATES == LONGITUDINAL_STATES + LATERAL_STATES


# -- the bands and the levels ---------------------------------------------------------------------

def _modes(sp=(5.0, 0.6), ph=(0.2, 0.06), dr=(2.4, 0.2), roll=-8.0, spiral=-0.02):
    lon = _block_diag(_oscillator(*sp), _oscillator(*ph))
    lat = _block_diag(np.diag([spiral, roll]), _oscillator(*dr))
    return {**longitudinal_modes(lon), **lateral_modes(lat)}


def test_levels_follow_the_encoded_bands_on_synthetic_modes():
    """Class I, Category B. Short-period damping Table IV: 0.30-2.00 is
    Level 1, 0.20-0.30 Level 2, 0.15-0.20 Level 3, below 0.15 worse.
    Phugoid 3.2.1.2: zeta >= 0.04 Level 1, >= 0 Level 2. Dutch roll
    Table VI Cat B: zeta >= 0.08, zeta*wn >= 0.15, wn >= 0.4 Level 1;
    0.02 / 0.05 / 0.4 Level 2. Roll Table VII Cat B: tau <= 1.4 Level 1,
    <= 3.0 Level 2, <= 10 Level 3. Spiral Table VIII Cat B: T2 >= 20 s
    Level 1, >= 8 Level 2, >= 4 Level 3."""
    na = 15.0
    lv = assign_levels(_modes(), "I", "B", na)
    assert {k: v["level"] for k, v in lv.items()} == {
        "short_period_damping": 1, "short_period_frequency": 1, "phugoid": 1,
        "dutch_roll": 1, "roll": 1, "spiral": 1}
    assert lv["short_period_frequency"]["value"]["cap"] == pytest.approx(25.0 / na)
    assert worst_level(lv) == 1

    assert assign_levels(_modes(sp=(5.0, 0.25)), "I", "B", na)["short_period_damping"]["level"] == 2
    assert assign_levels(_modes(sp=(5.0, 0.17)), "I", "B", na)["short_period_damping"]["level"] == 3
    assert assign_levels(_modes(sp=(5.0, 0.10)), "I", "B", na)["short_period_damping"]["level"] == BELOW_LEVEL_3
    assert assign_levels(_modes(sp=(5.0, 0.32)), "I", "A", na)["short_period_damping"]["level"] == 2
    assert assign_levels(_modes(sp=(5.0, 0.30)), "I", "B", na)["short_period_damping"]["level"] == 1

    assert assign_levels(_modes(ph=(0.2, 0.02)), "I", "B", na)["phugoid"]["level"] == 2
    unstable = _modes(ph=(0.2, -0.01))   # zeta < 0: time to double = ln2/(0.002) = 347 s -> Level 3
    assert assign_levels(unstable, "I", "B", na)["phugoid"]["level"] == 3
    fast_unstable = _modes(ph=(0.2, -0.2))   # T2 = ln2/0.04 = 17 s < 55 -> worse
    assert assign_levels(fast_unstable, "I", "B", na)["phugoid"]["level"] == BELOW_LEVEL_3

    assert assign_levels(_modes(dr=(2.4, 0.05)), "I", "B", na)["dutch_roll"]["level"] == 2
    assert assign_levels(_modes(dr=(0.3, 0.5)), "I", "B", na)["dutch_roll"]["level"] == BELOW_LEVEL_3
    assert assign_levels(_modes(dr=(2.4, 0.1)), "I", "A", na)["dutch_roll"]["level"] == 2   # 0.19 for Cat A
    assert assign_levels(_modes(dr=(1.0, 0.2)), "III", "A", na)["dutch_roll"]["level"] == 2   # zeta*wn 0.20 < 0.35
    assert assign_levels(_modes(dr=(1.0, 0.2)), "III", "B", na)["dutch_roll"]["level"] == 1   # 0.20 >= 0.15
    assert assign_levels(_modes(dr=(0.5, 0.2)), "III", "B", na)["dutch_roll"]["level"] == 2   # 0.10 < 0.15

    assert assign_levels(_modes(roll=-0.5), "I", "B", na)["roll"]["level"] == 2      # tau 2.0
    assert assign_levels(_modes(roll=-0.5), "I", "A", na)["roll"]["level"] == 3   # 1.0 / 1.4 / 10: tau 2.0
    assert assign_levels(_modes(roll=-0.5), "III", "A", na)["roll"]["level"] == 2   # 1.4 / 3.0
    assert assign_levels(_modes(roll=-0.05), "I", "B", na)["roll"]["level"] == BELOW_LEVEL_3

    t2 = lambda seconds: math.log(2) / seconds
    assert assign_levels(_modes(spiral=t2(25.0)), "I", "B", na)["spiral"]["level"] == 1
    assert assign_levels(_modes(spiral=t2(15.0)), "I", "B", na)["spiral"]["level"] == 2
    assert assign_levels(_modes(spiral=t2(15.0)), "I", "A", na)["spiral"]["level"] == 1
    assert assign_levels(_modes(spiral=t2(5.0)), "I", "B", na)["spiral"]["level"] == 3
    assert assign_levels(_modes(spiral=t2(3.0)), "I", "B", na)["spiral"]["level"] == BELOW_LEVEL_3
    assert worst_level(assign_levels(_modes(spiral=t2(3.0)), "I", "B", na)) == BELOW_LEVEL_3
    assert worst_level(assign_levels(_modes(roll=-0.5), "I", "B", na)) == 2


def test_short_period_frequency_band_uses_cap_and_the_omega_floor():
    na = 4.0
    # CAP = wn^2 / (n/alpha): wn 1.0 -> 0.25: Cat B Level 1 (0.085-3.6); Cat A Level 2 (0.16-10, wn>=0.6)
    assert assign_levels(_modes(sp=(1.0, 0.6)), "I", "B", na)["short_period_frequency"]["level"] == 1
    assert assign_levels(_modes(sp=(1.0, 0.6)), "I", "A", na)["short_period_frequency"]["level"] == 2
    # wn 0.5 -> CAP 0.0625: Cat B Level 2 (>= 0.038); Cat A below 0.16 -> worse
    assert assign_levels(_modes(sp=(0.5, 0.6)), "I", "B", na)["short_period_frequency"]["level"] == 2
    assert assign_levels(_modes(sp=(0.5, 0.6)), "I", "A", na)["short_period_frequency"]["level"] == BELOW_LEVEL_3
    lv = assign_levels(_modes(sp=(1.0, 0.6)), "I", "B", na)["short_period_frequency"]
    assert lv["confidence"].startswith("moderate")


def test_c172p_levels_are_assigned_per_the_bands(c172p_cruise):
    """The measured c172p at Category B, Class I: short-period zeta 0.610
    (Table IV Level 1: 0.30-2.00), phugoid zeta 0.114 (Level 1: >= 0.04),
    Dutch roll zeta 0.185 / zeta*wn 0.45 / wn 2.44 (Level 1: 0.08 / 0.15
    / 0.4), roll tau 0.146 s (Level 1: <= 1.4), spiral stable (Level 1).
    A statement about the model. The band guard moves the Level 1
    short-period damping floor above 0.61."""
    lv = c172p_cruise.levels
    assert lv["short_period_damping"]["level"] == 1
    assert lv["short_period_damping"]["band"]["1"] == {"min_zeta": 0.30, "max_zeta": 2.00}
    assert lv["phugoid"]["level"] == 1
    assert lv["dutch_roll"]["level"] == 1
    assert lv["roll"]["level"] == 1
    assert lv["spiral"]["level"] == 1
    assert c172p_cruise.airframe_class == "I" and c172p_cruise.category == "B"
    assert lv["short_period_damping"]["reference"] == "MIL-F-8785C 3.2.2.1.2, Table IV"
    assert "unverified here" in lv["short_period_damping"]["verification"]
    assert 5.0 < c172p_cruise.n_alpha_g_per_rad < 40.0


def test_every_band_table_carries_a_reference_and_its_confidence():
    for name, table in BANDS.items():
        assert table["reference"].startswith("MIL-F-8785C"), name
        assert table["confidence"] in ("high",) or table["confidence"].startswith("moderate"), name
        assert "unverified here" in table["verification"], name
    # the levels are nested: Level 1 is never looser than Level 2 (damping floors)
    for cat, levels in BANDS["short_period_damping"]["levels"].items():
        assert levels[1][0] >= levels[2][0] >= levels[3][0], cat
    for cat in ("A", "B", "C"):
        assert BANDS["spiral"]["levels"][1][cat] >= BANDS["spiral"]["levels"][2][cat] >= BANDS["spiral"]["levels"][3][cat]
    block = bands_block("I", "B")
    assert block["short_period_damping"]["levels"]["1"] == [0.30, 2.00]
    assert block["dutch_roll"]["levels"]["1"] == [0.08, 0.15, 0.4]
    assert block["roll"]["levels"]["1"] == 1.4 and block["spiral"]["levels"]["1"] == 20.0


def test_every_configured_airframe_has_a_stated_class():
    for name in configured_airframes():
        assert name in AIRFRAME_CLASS, name
        assert AIRFRAME_CLASS[name]["class"] in ("I", "II", "III", "IV")
        assert "MIL-F-8785C 3.1.1" in AIRFRAME_CLASS[name]["source"]


def test_n_alpha_is_read_from_the_alpha_row():
    A = np.zeros((4, 4))
    A[1, 1] = -2.0
    assert n_alpha(A, 50.0) == pytest.approx(2.0 * 50.0 / 9.80665)


# -- refusals by name -----------------------------------------------------------------------------

def test_an_airframe_without_a_class_is_refused_by_name(monkeypatch):
    spec = ScenarioSpec.read(EXAMPLE)
    monkeypatch.delitem(AIRFRAME_CLASS, "c172p")
    with pytest.raises(ModesError) as exc:
        analyse_spec(spec)
    assert exc.value.constraint == "modes.airframe_class"
    block = modes_block(spec)
    assert block == {"modes_version": MODES_VERSION, "kind": "result", "attempted": False,
                     "refusal": "modes.airframe_class", "reason": exc.value.message,
                     "aircraft": "c172p"}


def test_a_bad_class_or_category_is_refused_by_name():
    with pytest.raises(ModesError) as exc:
        assign_levels(_modes(), "V", "B", 10.0)
    assert exc.value.constraint == "modes.airframe_class"
    with pytest.raises(ModesError) as exc:
        bands_block("I", "D")
    assert exc.value.constraint == "modes.airframe_class"


def test_an_untrimmed_fdm_is_refused_by_name():
    fdm = FlightDynamics("c172p")
    fdm.set_initial_conditions({"h-sl-ft": u.m_to_ft(1200.0), "vc-kts": 100.0,
                                "gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0,
                                "beta-deg": 0.0, "lat-geod-deg": 0.0, "long-gc-deg": 0.0,
                                "terrain-elevation-ft": 0.0})
    assert not fdm.is_trimmed
    with pytest.raises(ModesError) as exc:
        linearize(fdm)
    assert exc.value.constraint == "modes.untrimmed"
    with pytest.raises(ModesError) as exc:
        analyse(fdm, "c172p")
    assert exc.value.constraint == "modes.untrimmed"


# -- the record and the CLI ----------------------------------------------------------------------------

def test_the_record_is_a_result_not_an_applied_variable(c172p_cruise):
    record = c172p_cruise.to_dict()
    assert record["kind"] == "result" and record["attempted"] is True
    assert record["modes_version"] == MODES_VERSION
    for key in ("source", "properties_written", "telemetry_columns", "null_test"):
        assert key not in record          # the AppliedVariable keys are absent on purpose
    assert set(record["modes"]) == {"short_period", "phugoid", "dutch_roll", "roll", "spiral"}
    lin = record["linearization"]
    assert lin["method"] == "jsbsim.FGLinearization" and lin["step"] == 1e-4
    assert np.array(lin["A_longitudinal"]).shape == (4, 4)
    assert np.array(lin["A_lateral"]).shape == (4, 4)
    assert lin["units"]["Vt"] == "m/s" and lin["full"]["units"][0] == "ft/s"
    assert len(record["eigenvalues"]["full"]) == len(lin["full"]["names"])
    assert record["references"][0].startswith("MIL-F-8785C")
    assert record["not_claimed"] and record["refusals"] == []
    assert record["bands"]["dutch_roll"]["levels"]["1"] == [0.08, 0.15, 0.4]
    text = json.dumps(record)
    assert text.isascii()
    json.loads(text)   # serialisable as written


def test_modes_block_on_the_example_is_the_result(c172p_cruise):
    block = modes_block(ScenarioSpec.read(EXAMPLE))
    assert block["attempted"] and block["kind"] == "result"
    # the same trim gives the same modes: the analysis is deterministic
    assert block["modes"]["short_period"]["omega_n_rad_s"] == pytest.approx(
        c172p_cruise.modes["short_period"]["omega_n_rad_s"], rel=1e-9)


def test_cli_prints_the_table_and_writes_the_record(tmp_path, capsys):
    out = tmp_path / "modes.json"
    code = modes_main([EXAMPLE, "--json", str(out)])
    printed = capsys.readouterr().out
    assert code == 0
    assert printed.isascii()
    assert "modes: c172p (class I, category B)" in printed
    for word in ("short period", "phugoid", "dutch roll", "roll", "spiral", "residual", "unverified here"):
        assert word in printed
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["kind"] == "result" and record["overall_level"] in (1, 2, 3, BELOW_LEVEL_3)
    assert render_table(record) in printed


def test_cli_refuses_by_name(tmp_path, capsys, monkeypatch):
    assert modes_main([str(tmp_path / "missing.yaml")]) == 1
    assert "REFUSED -- spec.read:" in capsys.readouterr().out
    monkeypatch.delitem(AIRFRAME_CLASS, "c172p")
    assert modes_main([EXAMPLE]) == 1
    assert "REFUSED -- modes.airframe_class:" in capsys.readouterr().out
