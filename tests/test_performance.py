"""Package D: the throttle loop knows how much aircraft it is flying.

Before: tecs.xml applied a fixed gain (1.2) to an energy-rate error that
is physically a required thrust-to-weight increment, with the airframe's
thrust range nowhere in it. Measured: the same file drove the B747 to
17-54% of its excess power (a 300 m step took 75 s) and the c172p to 98%
throttle. core.performance measures T_max, T_idle and T_trim at the
trimmed state and the loop is normalised by 1/((T_max - T_idle)/W).
"""

import pytest

from core import performance as perf_module
from core.control.autopilot import Autopilot
from core.fdm import units as u
from core.nl.compiler import compile_prompt
from core.performance import PerformanceError, measure_performance
from core.scenario.runner import configure_from_spec, run_spec


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(perf_module, "_CACHE", {})


def fly_step(prompt, altitude_m, step_m, seconds=120):
    spec = compile_prompt(prompt)
    fdm = configure_from_spec(spec)
    fdm.hold_mass(True)
    p = fdm.props
    engines = [n for n in range(8) if p.has(f"propulsion/engine[{n}]/thrust-lbs")]
    thrust = lambda: sum(p.get(f"propulsion/engine[{n}]/thrust-lbs")
                         for n in engines)
    ap = Autopilot(fdm)
    ap.engage()
    t0 = thrust()
    for _ in range(600):
        fdm.step()
    ap.command(altitude_m=altitude_m + step_m)
    rows = []
    for i in range(int(seconds * fdm.rate_hz)):
        fdm.step()
        if i % 60 == 0:
            ap.update()
        if i % 12 == 0:
            rows.append((fdm.sim_time, u.ft_to_m(p.get("position/h-sl-ft")),
                         p.get("velocities/vc-kts"), thrust(),
                         p.get("velocities/h-dot-fps")))
    t90 = next((r[0] for r in rows if r[1] >= altitude_m + 0.9 * step_m),
               float("inf")) - 5.0
    tmax_lbf = ap.performance.thrust_max_n / 4.4482216152605
    return dict(
        t90=t90,
        overshoot=max(r[1] for r in rows) - (altitude_m + step_m),
        cas_excursion=max(r[2] for r in rows) - min(r[2] for r in rows),
        excess_used=(max(r[3] for r in rows) - t0) / (tmax_lbf - t0),
        hdot_peak_fps=max(r[4] for r in rows),
        hdot_cap_fps=p.get("ap/tecs/hdot-max-fps"),
        ap=ap)


def test_performance_is_measured_and_differs_between_airframes():
    b747 = measure_performance("B747", 3000.0, 250.0)
    c172 = measure_performance("c172p", 600.0, 85.0)
    for perf in (b747, c172):
        assert perf.edot_max_mps > 0.0
        assert perf.edot_min_mps < 0.0
        assert 0.0 < perf.gamma_max_deg < 45.0
        assert perf.thr_per_ste > 1.0          # T_max - T_idle is less than W
    assert b747.thr_per_ste != pytest.approx(c172.thr_per_ste, rel=0.05)
    # The 747's excess power at 250 kt is a few m/s (thousands of ft/min).
    assert 3.0 < b747.edot_max_mps < 30.0


def test_engage_writes_the_measured_normalisation_not_the_constant():
    spec = compile_prompt("fly the 747 at 3000 m and 250 kt for 10 seconds")
    fdm = configure_from_spec(spec)
    ap = Autopilot(fdm)
    ap.engage()
    p = fdm.props
    assert p.get("ap/tecs/thr-per-ste") == pytest.approx(ap.performance.thr_per_ste)
    assert p.get("ap/tecs/thr-per-ste") != pytest.approx(1.0, abs=0.05)
    assert p.get("ap/tecs/stedot-max-fps") == pytest.approx(
        u.mps_to_fps(ap.performance.edot_max_mps))
    # The demanded climb-rate limit is derived from the measurement, never
    # above the airframe's capability.
    assert p.get("ap/tecs/hdot-max-fps") <= u.mps_to_fps(ap.performance.edot_max_mps)
    assert "ap/tecs/thr-per-ste" in ap.gains()


def test_the_manifest_records_the_performance_the_loop_used():
    spec = compile_prompt("fly the 747 at 3000 m and 250 kt for 8 seconds")
    result = run_spec(spec, assert_closure=False)
    perf = result.manifest["control"]["performance"]
    assert perf["aircraft"] == "B747"
    assert perf["thr_per_ste"] > 1.0


def test_the_b747_captures_a_300_m_step_in_under_30_s():
    """Before: 75 s at 3.9 m/s, the climb-rate demand never reached. After:
    the climb rate tracks its demanded cap (12.2 m/s), 28.7 s to 90%, no
    overshoot, CAS held within 1 kt (measured, experiments/airborne/
    tecs_step.py)."""
    r = fly_step("fly the 747 at 3000 m and 250 kt for 10 seconds", 3000.0, 300.0)
    assert r["t90"] < 30.0
    assert r["overshoot"] < 15.0                 # < 5% of the step
    assert r["cas_excursion"] < 1.5
    # The loop reaches the climb rate it demands: that is what the
    # normalisation plus feed-forward buy. Before, 6.4 of 12.2.
    assert r["hdot_peak_fps"] > 0.9 * r["hdot_cap_fps"]


def test_each_airframe_either_tracks_its_demand_or_uses_its_thrust():
    """The point of normalising: the same file works on every airframe. The
    747 has excess power to spare and must TRACK its demanded climb rate;
    the c172p (measured Edot_max ~7 m/s) is thrust-limited on a 100 m step
    and must be USING that thrust -- before, the same file left the 747 at
    17% of its excess and the Cessna at 98% throttle with a slower climb
    than it now achieves. "Same rise time" is not physically available
    when one airframe is saturated, so the test asserts what is."""
    b = fly_step("fly the 747 at 3000 m and 250 kt for 10 seconds", 3000.0, 100.0, seconds=90)
    c = fly_step("fly the c172p at 600 m and 85 kt for 10 seconds", 600.0, 100.0, seconds=90)
    for r in (b, c):
        assert r["t90"] < 30.0
        assert r["overshoot"] < 10.0
    assert b["hdot_peak_fps"] > 0.9 * b["hdot_cap_fps"]     # tracks
    assert c["excess_used"] > 0.8                          # saturates honestly


def test_a_probe_with_no_excess_power_refuses_by_name(monkeypatch):
    """An airframe that cannot out-thrust its trim has no performance to
    normalise by; that is a named refusal, not a division by zero. The
    probe is made to read a thrust that never changes with throttle (the
    aircraft's weight stands in for it), so full throttle equals trim."""
    import core.performance as pm

    monkeypatch.setattr(pm, "_engine_thrust_props",
                        lambda fdm: ["inertia/weight-lbs"])
    with pytest.raises(PerformanceError) as caught:
        pm.measure_performance("B747", 3000.0, 250.0, use_cache=False)
    assert caught.value.constraint == "performance.measure"
    assert "no excess power" in str(caught.value)
