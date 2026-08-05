"""TECS, its sign calibration, and the closure assertion.

The regression that matters here is §1.2: two independent PID loops on a
coupled plant fought each other, and the previous build shipped the result.
"""

import math

import pytest

from core.control.autopilot import Autopilot, AutopilotError, ClosureError
from core.control.derive import derive
from core.control.response import Acceptance, characterise
from core.control.signs import measure
from core.fdm import FlightDynamics, TrimMode
from core.fdm import units as u

LEVEL = {
    "gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
    "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0,
}


def flying(aircraft="B747", altitude_m=6000.0, cas_kt=280.0):
    fdm = FlightDynamics.with_tecs(aircraft)
    fdm.set_initial_conditions(
        {"h-sl-ft": u.m_to_ft(altitude_m), "vc-kts": cas_kt, **LEVEL}
    )
    fdm.props.set_many(
        {"atmosphere/wind-north-fps": 0.0, "atmosphere/wind-east-fps": 0.0,
         "atmosphere/turb-type": 0.0}
    )
    fdm.start_engines()
    fdm.trim(TrimMode.LONGITUDINAL)
    fdm.hold_mass(True)
    return fdm


# -- derivation ---------------------------------------------------------


def test_derived_aircraft_does_not_modify_the_stock_model():
    """Provenance depends on the stock hash staying what it was."""
    from core.fdm import aircraft as ac

    before = ac.resolve("B747").sha256
    spec = derive("B747")
    assert ac.resolve("B747").sha256 == before == spec.base_sha256
    assert spec.derived_sha256 != spec.base_sha256


def test_derivation_is_reproducible():
    assert derive("B747").derived_sha256 == derive("B747").derived_sha256


def test_throttle_outputs_cover_every_engine():
    """A hand-written output list would silently drive only some of them."""
    spec = derive("B747")
    assert spec.engine_count == 4
    system = (spec.xml_path.parent / "Systems" / "tecs.xml").read_text()
    assert system.count("<output> fcs/throttle-cmd-norm") == 4
    assert "<!--THROTTLE_OUTPUTS-->" not in system


def test_derived_model_exposes_the_controller():
    fdm = FlightDynamics.with_tecs("B747")
    assert fdm.has_autopilot
    assert fdm.props.has("ap/tecs/ste-error")
    assert fdm.provenance()["aircraft"]["name"] == "B747-tecs"


# -- the disengaged controller must be inert ----------------------------


def test_disengaged_autopilot_does_not_prevent_trim():
    """Regression: the output switches once zeroed all four throttles.

    The disengaged path writes each actuator's current command back to it,
    which is an identity. An earlier version defaulted to a separate property
    that was zero before engage, so the trim solver could not move thrust and
    reported 'udot doesn't appear to be trimmable' on an airframe that trims
    perfectly well without the controller attached.
    """
    fdm = flying()
    assert fdm.is_trimmed
    assert fdm.props.get("ap/enable") == 0.0
    assert fdm.props.get("fcs/throttle-cmd-norm") > 0.1


# -- control signs ------------------------------------------------------


def test_control_signs_are_measured_not_assumed():
    """The B747 is a model where the naive assumption is wrong."""
    signs = measure("B747")
    assert signs.elevator == -1.0     # positive elevator command pitches DOWN
    assert signs.aileron == 1.0
    assert signs.rudder == -1.0       # positive rudder command yaws LEFT


def test_engage_writes_the_measured_signs():
    fdm = flying()
    ap = Autopilot(fdm)
    ap.engage()
    assert fdm.props.get("ap/sign/elevator") == ap.signs.elevator


# -- engage -------------------------------------------------------------


def test_engage_on_an_untrimmed_aircraft_is_refused():
    fdm = FlightDynamics.with_tecs("B747")
    fdm.set_initial_conditions({"h-sl-ft": 20000.0, "vc-kts": 280.0, **LEVEL})
    with pytest.raises(AutopilotError, match="untrimmed"):
        Autopilot(fdm).engage()


def test_autopilot_requires_a_model_that_has_one():
    plain = FlightDynamics("B747")
    with pytest.raises(AutopilotError, match="no TECS controller"):
        Autopilot(plain)


def test_engage_does_not_move_the_controls():
    """The precise form of bumpless engage, per channel.

    Regression for integrator windup while disengaged. These channels are
    evaluated from the moment the model loads; only the output switches are
    gated. With the setpoints at zero before engage, every integrator winds up
    throughout trim, and engaging dumped the accumulated state onto the
    surfaces in one frame -- elevator 0.000 to +0.398, throttle 0.689 to 0.539.

    Measuring the altitude excursion alone is too coarse to catch a single
    channel regressing, so each surface is checked against its trimmed value.
    """
    fdm = flying()
    before = {
        name: fdm.props.get(name)
        for name in ("fcs/elevator-cmd-norm", "fcs/aileron-cmd-norm",
                     "fcs/rudder-cmd-norm", "fcs/throttle-cmd-norm")
    }
    trim_pitch = fdm.props.get("attitude/theta-rad")

    Autopilot(fdm).engage()
    fdm.step()

    for name, value in before.items():
        assert fdm.props.get(name) == pytest.approx(value, abs=0.01), (
            f"{name} moved on engage: {value:.4f} -> {fdm.props.get(name):.4f}"
        )
    # The pitch command must start at the trimmed attitude, not somewhere the
    # controller's own accumulated integrator put it.
    assert fdm.props.get("ap/tecs/pitch-command-rad") == pytest.approx(
        trim_pitch, abs=0.005
    )


def test_engage_is_bumpless():
    """Regression: engaging once zeroed the elevator and dipped the aircraft.

    The inner loops command a deviation from the trimmed surface position. The
    trimmed B747 elevator sits near -0.055; without capturing it, engaging drove
    the surface to 0 and the aircraft lost 15 m before recovering -- an engage
    transient of the controller's own making.
    """
    fdm = flying()
    trimmed_elevator = fdm.props.get("fcs/elevator-cmd-norm")
    start = fdm.state().altitude_m
    ap = Autopilot(fdm)
    ap.engage()
    assert fdm.props.get("ap/trim/elevator") == pytest.approx(trimmed_elevator)

    worst = 0.0
    for _ in range(30 * 120):
        fdm.step()
        worst = max(worst, abs(fdm.state().altitude_m - start))
    assert worst < 5.0, f"engage transient of {worst:.1f} m"


# -- the loops actually close -------------------------------------------


def test_altitude_command_is_achieved():
    fdm = flying()
    ap = Autopilot(fdm)
    ap.engage()
    target = fdm.state().altitude_m + 100.0
    ap.command(altitude_m=target)
    for i in range(220 * 120):
        fdm.step()
        if i % 60 == 0:
            ap.update()
    assert fdm.state().altitude_m == pytest.approx(target, abs=5.0)


def test_airspeed_command_is_achieved_without_losing_altitude():
    """The §1.2 shape in miniature: commanding speed must not cost height."""
    fdm = flying()
    ap = Autopilot(fdm)
    ap.engage()
    start = fdm.state()
    ap.command(tas_kt=start.tas_kt + 15.0)
    for i in range(220 * 120):
        fdm.step()
        if i % 60 == 0:
            ap.update()
    end = fdm.state()
    assert end.tas_kt == pytest.approx(start.tas_kt + 15.0, abs=2.0)
    assert end.altitude_m == pytest.approx(start.altitude_m, abs=15.0)


def test_bank_command_is_tracked():
    fdm = flying()
    ap = Autopilot(fdm)
    ap.engage()
    ap.command(bank_deg=20.0)
    for _ in range(60 * 120):
        fdm.step()
    assert fdm.state().roll_deg == pytest.approx(20.0, abs=2.0)


# -- the closure assertion (§2.8) ---------------------------------------


def test_closure_passes_an_achieved_command():
    fdm = flying()
    ap = Autopilot(fdm)
    ap.engage()
    ap.command(altitude_m=fdm.state().altitude_m + 50.0)
    alts, speeds, headings, rates = [], [], [], []
    for i in range(200 * 120):
        fdm.step()
        if i % 60 == 0:
            ap.update()
        if i % 60 == 0:
            s = fdm.state()
            alts.append(s.altitude_m); speeds.append(s.tas_kt)
            headings.append(s.heading_deg); rates.append(s.climb_rate_mps)
    report = ap.closure(alts, speeds, headings, rates)
    assert report.ok, report.render()


def test_closure_fails_a_command_that_was_not_achieved():
    """The assertion that would have caught the previous build.

    An assertion never seen to fail is not evidence that it works.
    """
    fdm = flying()
    ap = Autopilot(fdm)
    ap.engage()
    ap.command(altitude_m=fdm.state().altitude_m + 900.0)
    alts, speeds, headings, rates = [], [], [], []
    for i in range(40 * 120):
        fdm.step()
        if i % 60 == 0:
            s = fdm.state()
            alts.append(s.altitude_m); speeds.append(s.tas_kt)
            headings.append(s.heading_deg); rates.append(s.climb_rate_mps)
    report = ap.closure(alts, speeds, headings, rates)
    assert not report.ok
    with pytest.raises(ClosureError, match="Refusing to emit output"):
        report.raise_if_failed()


def test_closure_rejects_a_state_that_crosses_its_target_while_diverging():
    """Matching the target for an instant is not achieving it.

    The settled check exists because a trace can pass through its commanded
    value at high climb rate on the way somewhere else.
    """
    fdm = flying()
    ap = Autopilot(fdm)
    ap.engage()
    target = fdm.state().altitude_m
    report = ap.closure([target] * 10, [400.0] * 10, [0.0] * 10,
                        climb_rates_mps=[8.0] * 10)
    assert not report.ok
    assert any(c.name == "settled" and not c.ok for c in report.checks)


# -- response metrics ---------------------------------------------------


def test_characterise_measures_a_known_response():
    """A first-order rise to 1.0 has no overshoot and settles."""
    times = [i * 0.1 for i in range(600)]
    values = [1.0 - math.exp(-t / 5.0) for t in times]
    r = characterise(times, values, 1.0, "test", "-", band=0.02)
    assert r.overshoot_pct == 0.0
    assert r.settled
    assert abs(r.steady_state_error) < 0.02
    # 10%-90% of a first-order lag is about 2.2 time constants.
    assert r.rise_time_s == pytest.approx(2.2 * 5.0, rel=0.1)


def test_acceptance_reports_each_violated_criterion():
    times = [i * 0.1 for i in range(200)]
    values = [2.0 for _ in times]          # never reaches 1.0
    r = characterise(times, values, 1.0, "test", "-", band=0.02)
    failures = Acceptance(max_overshoot_pct=5.0, max_settling_time_s=5.0,
                          max_abs_sse=0.1).check(r)
    assert len(failures) >= 2
