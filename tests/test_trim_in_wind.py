"""Package A: the aircraft is trimmed IN the spec's wind.

Measured before this package (analysis/flight-dynamics-research-ledger.md
2.1): the wind written before trim() was zeroed by FGTrim::DoTrim's
Initialize(&fgic); the aircraft trimmed in calm air and met the wind as a
step on the first step of the run -- +333 m / -327 m in 30 s open loop for
a 30 kt head/tail wind, a 44 m balloon closed loop. These tests pin the
post-package state: the wind is in the trim, the airspeed is the spec's,
there is no sideslip, the crab emerges at trim, and the run starts still.
"""

import math

import pytest

from core.fdm import FlightDynamics, mode_for
from core.fdm import units as u
from core.fdm.errors import TrimStateError
from core.nl.compiler import compile_prompt
from core.scenario.runner import configure_from_spec, wind_components_fps


CASES = [
    # aircraft, prompt fragment, wind kt, from deg
    ("B747", "fly the 747 at 3000 m and 250 kt", 30.0, 0.0),
    ("B747", "fly the 747 at 3000 m and 250 kt", 30.0, 180.0),
    ("B747", "fly the 747 at 3000 m and 250 kt", 30.0, 90.0),
    ("c172p", "fly the c172p at 600 m and 85 kt", 20.0, 0.0),
    ("c172p", "fly the c172p at 600 m and 85 kt", 20.0, 90.0),
]


def spec_with_wind(prompt, wind_kt, from_deg):
    spec = compile_prompt(prompt + " for 10 seconds")
    spec.set("wind_speed", wind_kt, frm="test: wind")
    spec.set("wind_direction", from_deg, frm="test: wind direction")
    spec.set("hold_state", False, frm="test: open loop")
    return spec


@pytest.mark.parametrize("aircraft,prompt,wind_kt,from_deg", CASES)
def test_the_trim_carries_the_spec_wind_at_the_spec_airspeed(
        aircraft, prompt, wind_kt, from_deg):
    spec = spec_with_wind(prompt, wind_kt, from_deg)
    fdm = configure_from_spec(spec)
    p = fdm.props
    n, e = wind_components_fps(wind_kt, from_deg)
    assert p.get("atmosphere/total-wind-north-fps") == pytest.approx(n, abs=0.05)
    assert p.get("atmosphere/total-wind-east-fps") == pytest.approx(e, abs=0.05)
    assert p.get("velocities/vc-kts") == pytest.approx(
        float(spec.airspeed.value), abs=0.1)
    assert abs(p.get("aero/beta-deg")) < 0.05
    assert abs(p.get("attitude/phi-deg")) < 0.2
    # Groundspeed differs from airspeed by the along-track wind: the FDM is
    # flying in the wind, not merely reporting it.
    tas = p.get("velocities/vtrue-fps")
    gs = p.get("velocities/vg-fps")
    psi = math.radians(p.get("attitude/psi-deg"))
    along = n * math.cos(psi) + e * math.sin(psi)
    assert gs == pytest.approx(math.hypot(tas * math.cos(psi) + n,
                                          tas * math.sin(psi) + e), abs=0.5)
    assert (gs - tas) * (along if abs(along) > 1 else 1) >= -1.0
    prov = fdm.provenance()
    assert prov["wind_in_initial_conditions_fps"] == pytest.approx((n, e, 0.0))
    assert prov["wind_ic_iterations"] >= 1


@pytest.mark.parametrize("aircraft,prompt,wind_kt,from_deg", CASES[:3])
def test_the_run_starts_still_open_loop(aircraft, prompt, wind_kt, from_deg):
    """The whole point: 30 s open loop in the wind moves the altitude by
    centimetres, not hundreds of metres. Today's number before the
    package: 333 m (headwind), 327 m (tailwind)."""
    spec = spec_with_wind(prompt, wind_kt, from_deg)
    fdm = configure_from_spec(spec)
    n, e = wind_components_fps(wind_kt, from_deg)
    p = fdm.props
    hs = []
    for i in range(30 * int(fdm.rate_hz)):
        p.set_many({"atmosphere/wind-north-fps": n,
                    "atmosphere/wind-east-fps": e,
                    "atmosphere/wind-down-fps": 0.0})
        fdm.step()
        if i % 12 == 0:
            hs.append(u.ft_to_m(p.get("position/h-sl-ft")))
    assert max(hs) - min(hs) < 5.0


def test_a_crosswind_crab_emerges_at_trim():
    """Heading north in a 30 kt wind from the east: the trimmed state has
    zero sideslip and a ground track west of north -- the crab is in the
    trim, not learned over the first seconds of the run."""
    spec = spec_with_wind("fly the 747 at 3000 m and 250 kt", 30.0, 90.0)
    fdm = configure_from_spec(spec)
    p = fdm.props
    vn, ve = p.get("velocities/v-north-fps"), p.get("velocities/v-east-fps")
    track = math.degrees(math.atan2(ve, vn)) % 360.0
    heading = p.get("attitude/psi-deg") % 360.0
    crab = (track - heading + 180.0) % 360.0 - 180.0
    assert crab < -4.0            # west of the nose, ~6 deg for 30 kt / 288 kt TAS
    assert abs(p.get("aero/beta-deg")) < 0.05


def test_the_fixed_point_reports_its_iterations_and_converges_fast():
    fdm = FlightDynamics("B747", rate_hz=120.0)
    fdm.set_initial_conditions({"h-sl-ft": u.m_to_ft(3000.0), "vc-kts": 250.0,
                                "gamma-deg": 0.0, "phi-deg": 0.0,
                                "psi-true-deg": 45.0, "beta-deg": 0.0,
                                "lat-geod-deg": 0.0, "long-gc-deg": 0.0,
                                "terrain-elevation-ft": 0.0})
    n, e = wind_components_fps(30.0, 300.0)      # quartering
    iterations = fdm.set_wind_initial_conditions(n, e, 0.0)
    assert 1 <= iterations <= 3
    assert fdm.props.get("velocities/vc-kts") == pytest.approx(250.0, abs=0.05)
    assert abs(fdm.props.get("aero/beta-deg")) < 0.02


def test_the_guard_refuses_a_trim_that_lost_the_wind():
    """The safeguard itself: an FDM whose trimmed state does not carry the
    spec wind refuses by name. Reproduces the pre-package defect exactly --
    write the wind as a property, trim, and let FGTrim zero it."""
    fdm = FlightDynamics("B747", rate_hz=120.0)
    fdm.set_initial_conditions({"h-sl-ft": u.m_to_ft(3000.0), "vc-kts": 250.0,
                                "gamma-deg": 0.0, "phi-deg": 0.0,
                                "psi-true-deg": 0.0, "beta-deg": 0.0,
                                "lat-geod-deg": 0.0, "long-gc-deg": 0.0,
                                "terrain-elevation-ft": 0.0})
    n, e = wind_components_fps(30.0, 0.0)
    fdm.props.set_many({"atmosphere/wind-north-fps": n,
                        "atmosphere/wind-east-fps": e})
    fdm.start_engines()
    fdm.trim(mode_for(crosswind=True))
    with pytest.raises(TrimStateError) as caught:
        fdm.verify_wind_state(n, e, 250.0)
    assert caught.value.constraint == "wind.trim_state"
    assert "total wind" in str(caught.value)


def test_the_fixed_point_refuses_rather_than_approximates(monkeypatch):
    """If the iteration cannot reach the spec airspeed with the wind present
    it raises -- it never hands trim a state in a different wind."""
    fdm = FlightDynamics("B747", rate_hz=120.0)
    fdm.set_initial_conditions({"h-sl-ft": u.m_to_ft(3000.0), "vc-kts": 250.0,
                                "gamma-deg": 0.0, "phi-deg": 0.0,
                                "psi-true-deg": 0.0, "beta-deg": 0.0,
                                "lat-geod-deg": 0.0, "long-gc-deg": 0.0,
                                "terrain-elevation-ft": 0.0})
    n, e = wind_components_fps(30.0, 0.0)
    # A tolerance of zero can never be met (the fixed point is exact to
    # floating point on the first iteration -- 1e-9 still passes), so this
    # exercises the refusal path honestly: no convergence, no trim.
    with pytest.raises(TrimStateError) as caught:
        fdm.set_wind_initial_conditions(n, e, 0.0, max_iterations=2,
                                        vc_tolerance_kt=0.0,
                                        beta_tolerance_deg=0.0)
    assert caught.value.constraint == "wind.trim_state"
    assert not fdm.is_trimmed


def test_the_runner_refuses_a_calm_trim_in_a_wind_spec(monkeypatch):
    """The runner-level guard. If the wind is NOT placed in the initial
    conditions (the pre-package behaviour, simulated here by turning the
    placement into a no-op), configure_from_spec must refuse by name rather
    than hand back an aircraft trimmed in calm air."""
    import core.fdm.fdm as fdm_module

    monkeypatch.setattr(fdm_module.FlightDynamics, "set_wind_initial_conditions",
                        lambda self, *a, **k: 0)
    spec = spec_with_wind("fly the 747 at 3000 m and 250 kt", 30.0, 0.0)
    with pytest.raises(TrimStateError) as caught:
        configure_from_spec(spec)
    assert caught.value.constraint == "wind.trim_state"


def test_a_calm_spec_is_unchanged():
    """No wind: no wind IC, no iterations, provenance says so."""
    spec = compile_prompt("fly the 747 at 3000 m and 250 kt for 10 seconds")
    spec.set("hold_state", False, frm="test")
    fdm = configure_from_spec(spec)
    prov = fdm.provenance()
    assert prov["wind_in_initial_conditions_fps"] is None
    assert prov["wind_ic_iterations"] == 0
    assert fdm.props.get("atmosphere/total-wind-north-fps") == pytest.approx(0.0, abs=1e-9)
