"""P7, the wake-vortex pair (core/environment/wake.py) on a real c172p
behind a B747 generator: the closed forms (V16: the Burnham-Hallock core
value, the far field, the divergence-free pair, the strip-theory
identities, the quadrature), the decay's declared inputs and refusals,
the spec block (absent-canonical, the committed examples' digests), the
registry's claim, the derived airframe, the delivery and read-back of the
gust channel and the roll property, the records, the null pairs
(encounter against none rolls the aircraft past 5 deg and diverges the
flight; a 300 m offset barely moves it), the card block with its five
selftest vectors, and the generator's track for the render host.

Every number asserted here was measured in this container on
2026-09-29 (JSBSim 1.2.4 in .venv, c172p at 1500 m / 100 kt, 120 Hz, the
stock B747 as generator: 523816 lb, 211.5 ft span). What is NOT claimed:
the core radius (a stated convention), any Crow instability, ground
effect or stratification physics, the Sarpkaya constants (from memory),
the engine side (the card is pinned; the host port is P9's Windows
step), the aircraft's response as a validated one.
"""
from __future__ import annotations

import contextlib
import io
import json
import math
from pathlib import Path

import numpy as np
import pytest

from core.capture.poses import (
    PoseSolveError, TRAFFIC_TRACKS, WAKE_GEOMETRY_KEYS, aircraft_local_track,
    solve_traffic_track, solve_wake_generator_track, wake_generator_card_block,
)
from core.environment import wake as wk
from core.environment.wake import (
    B0_FACTOR, CARD_KEYS, CORE_RADIUS_FACTOR, GL_POINTS, SELFTEST_KEYS, TELEMETRY_COLUMNS,
    GeneratorData, WakeError, WakeVortexPair, aileron_authority, burnham_hallock,
    circulation_at, core_radius, descent_speed, generator_data, initial_circulation,
    p_equivalent, pair_velocity, problems, sarpkaya_demise_time, unread_wake_fields,
    vortex_spacing, wake_injections_for,
)
from core.nl.compiler import compile_prompt
from core.record_null import run_null_pair
from core.records import read_records
from core.registry import REGISTRY
from core.scenario.blocks import WAKE_DECAY_MODELS, WakeSpec
from core.scenario.card import wake_card_block, write_run_card
from core.scenario.runner import environment_for, run_spec
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate, validate_wake
from core.telemetry.recorder import DEFAULT_CHANNELS

from tests.test_camera_poses import FRAME, make_columns
from tests.test_registry import EXAMPLE_DIGESTS

REPO = Path(__file__).resolve().parents[1]

#: The B747 as the stock model ships it (measured through FlightDynamics).
B747_SPAN_M = 211.5 * 0.3048
B747_B0_M = 50.63084968304919
B747_RC_M = 2.2562820000000006
#: The demonstration geometry: the c172p 25.315 m right of the pair's
#: centreline (on the starboard vortex's line) and 15 m above it, the wake
#: 20 s old, the B747 at 250 kt.
DEMO = dict(generator="B747", separation_s=20.0, generator_speed_kt=250.0,
            lateral_offset_m=25.315, vertical_offset_m=15.0)
GAMMA_0 = 338.17353043768765
#: The five selftest vectors of the demonstration card, as measured here
#: (the host port must reproduce them to 1e-9).
SELFTEST = [
    (0.0, 0.0, 20.0, 0.0, 0.0, 4.218599485161402, 0.0),
    (27.571706841524595, 0.0, 20.0, 0.0, 0.0, -10.911313830122804, 2.1216034461068665),
    (25.315424841524596, 25.315424841524596, 20.0, 0.0, -1.6847631835698726,
     0.8490731180216566, 0.09108228490222658),
    (-12.657712420762298, -12.657712420762298, 20.0, 0.0, -1.668942155120785,
     3.364399063952879, -0.03827719247018705),
    (25.315, 15.0, 20.0, 0.0, -3.219744589023211, 0.9755782368038669, 0.23342562222842955),
]


def spec_for(duration=4.0, **fields) -> ScenarioSpec:
    spec = compile_prompt(f"fly the c172p at 1500 m and 100 kt for {duration:g} seconds")
    spec.set("hold_state", False, frm="test")
    for name, value in fields.items():
        spec.set(f"wake.{name}", value, frm="test")
    return spec


def quiet_run(spec):
    with contextlib.redirect_stdout(io.StringIO()):
        return run_spec(spec, assert_closure=False)


def quiet_pair(spec, name):
    with contextlib.redirect_stdout(io.StringIO()):
        return run_null_pair(spec, name)


@pytest.fixture(scope="module")
def demo_run():
    return quiet_run(spec_for(**DEMO))


def names(violations):
    return [v.constraint for v in violations]


# -- V16: the closed forms ---------------------------------------------------------------

def test_the_closed_forms_b0_rc_gamma0_and_w0():
    assert B0_FACTOR == math.pi / 4.0 and CORE_RADIUS_FACTOR == 0.035
    assert vortex_spacing(B747_SPAN_M) == pytest.approx(B747_B0_M, abs=1e-12)
    assert core_radius(B747_SPAN_M) == pytest.approx(B747_RC_M, abs=1e-12)
    assert core_radius(10.0) == pytest.approx(0.35) and vortex_spacing(4.0) == pytest.approx(math.pi)
    gamma = initial_circulation(2.0e6, 1.0, 100.0, 50.0)
    assert gamma == pytest.approx(2.0e6 / (1.0 * 100.0 * 50.0))
    assert descent_speed(gamma, 50.0) == pytest.approx(gamma / (2.0 * math.pi * 50.0))
    with pytest.raises(ValueError):
        initial_circulation(0.0, 1.0, 100.0, 50.0)


def test_v16_burnham_hallock_at_the_core_radius_is_gamma_over_4_pi_rc():
    gamma, rc = 338.0, 2.25
    assert burnham_hallock(rc, gamma, rc) == pytest.approx(gamma / (4.0 * math.pi * rc), rel=1e-14)
    assert burnham_hallock(0.0, gamma, rc) == 0.0
    # Far from the core the profile is the potential vortex's Gamma / (2 pi r).
    assert burnham_hallock(1000.0 * rc, gamma, rc) == pytest.approx(
        gamma / (2.0 * math.pi * 1000.0 * rc), rel=2e-6)
    # And below it the solid-body core: V grows with r.
    assert burnham_hallock(0.5 * rc, gamma, rc) < burnham_hallock(rc, gamma, rc)


def test_v16_the_far_field_tends_to_zero_as_a_dipole():
    """The pair's field at r >> b_0 falls as Gamma b_0 / (2 pi r^2): a
    hundredfold between 100 b_0 and 1000 b_0 (a single vortex would give
    tenfold), and is below 1e-6 of w_0 at 10^4 b_0."""
    gamma, b0, rc = GAMMA_0, B747_B0_M, B747_RC_M
    w0 = descent_speed(gamma, b0)
    speeds = {}
    for factor in (100.0, 1000.0, 10000.0):
        v, w = pair_velocity(0.0, factor * b0, gamma, b0, rc)
        speeds[factor] = math.hypot(v, w)
    assert speeds[1000.0] / speeds[100.0] == pytest.approx(0.01, rel=0.05)
    assert speeds[10000.0] < 1e-6 * w0
    # The dipole strength: Gamma b_0 / (2 pi r^2) on the axis above the pair.
    assert speeds[1000.0] == pytest.approx(gamma * b0 / (2.0 * math.pi * (1000.0 * b0) ** 2), rel=1e-4)


def test_v16_the_pair_is_divergence_free_numerically():
    """d v / d y + d w / d z by central differences (h = 1 mm) at points
    inside, between and outside the cores: below 1e-6 1/s (measured 3.1e-8,
    the difference scheme's own truncation) against gradients of order
    1 1/s; a field that is not solenoidal (a source term, a vortex whose
    speed depends on the angle) measures of order 1."""
    gamma, b0, rc = GAMMA_0, B747_B0_M, B747_RC_M
    h = 1e-3
    worst = 0.0
    largest_gradient = 0.0
    for y, z in ((0.0, 0.0), (0.5 * b0 + rc, 0.0), (0.5 * b0 + 0.3 * rc, 0.2 * rc), (10.0, 5.0),
                 (-30.0, -8.0), (0.5 * b0, 3.0 * rc), (70.0, 40.0)):
        dv_dy = (pair_velocity(y + h, z, gamma, b0, rc)[0] - pair_velocity(y - h, z, gamma, b0, rc)[0]) / (2 * h)
        dw_dz = (pair_velocity(y, z + h, gamma, b0, rc)[1] - pair_velocity(y, z - h, gamma, b0, rc)[1]) / (2 * h)
        worst = max(worst, abs(dv_dy + dw_dz))
        largest_gradient = max(largest_gradient, abs(dv_dy), abs(dw_dz))
    assert largest_gradient > 0.1
    assert worst < 1e-6


def test_v16_p_eq_of_a_uniform_upwash_is_0_and_of_a_linear_one_is_p():
    assert p_equivalent(lambda y: 3.7, 10.9) == pytest.approx(0.0, abs=1e-12)
    for p in (0.37, -2.0, 1e-3):
        assert p_equivalent(lambda y: p * y, 10.9) == pytest.approx(p, rel=1e-12)
    # A quadratic (symmetric) upwash rolls nothing either.
    assert p_equivalent(lambda y: 0.5 * y * y, 10.9) == pytest.approx(0.0, abs=1e-12)
    with pytest.raises(ValueError):
        p_equivalent(lambda y: 0.0, 0.0)


def test_the_32_point_quadrature_matches_a_fine_rule_on_the_pair_field():
    """Over a 10.9 m span centred on the starboard core line the upwash
    is far from polynomial; 32 Gauss-Legendre points agree with a
    200000-point midpoint rule to 1e-7 relative (2 points miss by 30 %,
    measured: the mutation guard)."""
    assert GL_POINTS == 32
    gamma, b0, rc, span = GAMMA_0, B747_B0_M, B747_RC_M, 10.91184
    y0, z0 = 0.5 * b0 + 1.0, 2.0
    upwash = lambda s: pair_velocity(y0 + s, z0, gamma, b0, rc)[1]
    n = 200000
    stations = (np.arange(n) + 0.5) / n * span - 0.5 * span
    fine = 12.0 / span ** 3 * float(np.sum([upwash(s) * s for s in stations])) * (span / n)
    assert p_equivalent(upwash, span) == pytest.approx(fine, rel=1e-7)
    assert abs(fine) > 0.1


# -- the decay ----------------------------------------------------------------------------

def test_the_sarpkaya_decay_has_declared_inputs_a_demise_time_and_the_none_model_holds():
    gamma, b0 = GAMMA_0, B747_B0_M
    assert sarpkaya_demise_time(0.2) == pytest.approx((0.7475 / 0.2) ** (4.0 / 3.0))
    assert sarpkaya_demise_time(0.2, 0.0) == sarpkaya_demise_time(0.2)
    # N* bounds the demise at a quarter buoyancy period (a stated bound).
    assert sarpkaya_demise_time(0.01, 0.5) == pytest.approx(math.pi / (2.0 * 0.5))
    with pytest.raises(ValueError):
        sarpkaya_demise_time(0.0)
    t0 = b0 / descent_speed(gamma, b0)
    demise_s = sarpkaya_demise_time(0.2) * t0
    assert circulation_at(0.0, gamma, b0, "sarpkaya", 0.2) == pytest.approx(gamma)
    assert circulation_at(0.5 * demise_s, gamma, b0, "sarpkaya", 0.2) == pytest.approx(0.5 * gamma)
    assert circulation_at(demise_s, gamma, b0, "sarpkaya", 0.2) == 0.0
    assert circulation_at(2.0 * demise_s, gamma, b0, "sarpkaya", 0.2) == 0.0
    assert circulation_at(1e9, gamma, b0, "none") == gamma          # held
    assert circulation_at(-1.0, gamma, b0, "none") == 0.0           # the generator not yet past
    with pytest.raises(WakeError) as err:
        circulation_at(1.0, gamma, b0, "crow")
    assert err.value.constraint == "wake.model"
    assert WAKE_DECAY_MODELS == ("none", "sarpkaya")


# -- refusals by name ------------------------------------------------------------------------

def test_problems_refuse_by_name_and_a_block_without_a_generator_yields_nothing():
    good = dict(generator="B747", generator_speed_kt=250.0, lateral_offset_m=25.0,
                vertical_offset_m=0.0, separation_s=20.0, age_s=None, model="none",
                eps_star=None, n_star=None)
    assert problems(**good) == []
    assert problems(**{**good, "generator": None, "separation_s": None}) == []

    def refused(**changes):
        return [p.constraint for p in problems(**{**good, **changes})]

    assert refused(generator="X15") == ["wake.generator"]
    assert refused(generator="") == ["wake.generator"]
    assert refused(generator_speed_kt=0.0) == ["wake.geometry"]
    assert refused(lateral_offset_m="near") == ["wake.geometry"]
    assert refused(vertical_offset_m=float("nan")) == ["wake.geometry"]
    assert refused(separation_s=None) == ["wake.geometry"]
    assert refused(age_s=5.0) == ["wake.geometry"]
    assert refused(separation_s=-1.0) == ["wake.geometry"]
    assert refused(separation_s=None, age_s=0.0) == []
    assert refused(model="crow") == ["wake.model"]
    assert refused(model="sarpkaya") == ["wake.decay"]
    assert refused(model="sarpkaya", eps_star=0.0) == ["wake.decay"]
    assert refused(model="sarpkaya", eps_star=3.0) == ["wake.decay"]
    assert refused(model="sarpkaya", eps_star=0.1, n_star=2.0) == ["wake.decay"]
    assert refused(model="sarpkaya", eps_star=0.1, n_star=0.3) == []
    assert refused(model="sarpkaya", eps_star=1.0) == []
    # eps* beside the none model is carried, not applied: not refused.
    assert refused(eps_star=0.1, n_star=0.2) == []
    provider = WakeVortexPair(generator_data("B747"), 25.0, 0.0, 0.0, separation_s=20.0,
                              eps_star=0.1, n_star=0.2)
    assert provider.unread_stated_fields == ["eps_star", "n_star"]
    with pytest.raises(WakeError) as err:
        WakeVortexPair(generator_data("B747"), 25.0, 0.0, 0.0, separation_s=20.0, model="sarpkaya")
    assert err.value.constraint == "wake.decay"


def test_a_generator_without_span_or_weight_data_refuses_wake_generator(monkeypatch):
    import core.fdm as fdm_module

    class NoSpan:
        class props:
            @staticmethod
            def get(name):
                return {"inertia/weight-lbs": 1000.0, "metrics/bw-ft": 0.0}[name]

        class model:
            sha256 = "0" * 64

        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(fdm_module, "FlightDynamics", NoSpan)
    monkeypatch.setattr(wk, "_GENERATORS", {})
    with pytest.raises(WakeError) as err:
        generator_data("A320")
    assert err.value.constraint == "wake.generator" and "span" in str(err.value)


def test_validation_refuses_the_wake_problems_by_name():
    cases = [
        (dict(generator="X15", separation_s=20.0), "wake.generator"),
        (dict(generator="B747", separation_s=20.0, model="crow"), "wake.model"),
        (dict(generator="B747", separation_s=20.0, model="sarpkaya"), "wake.decay"),
        (dict(generator="B747", separation_s=20.0, model="sarpkaya", eps_star=3.0), "wake.decay"),
        (dict(generator="B747", separation_s=20.0, model="sarpkaya", eps_star=0.1, n_star=2.0), "wake.decay"),
        (dict(generator="B747"), "wake.geometry"),
        (dict(generator="B747", separation_s=20.0, age_s=5.0), "wake.geometry"),
        (dict(generator="B747", separation_s=-1.0), "wake.geometry"),
        (dict(generator="B747", separation_s=20.0, lateral_offset_m="near"), "wake.geometry"),
        (dict(generator="B747", separation_s=20.0, generator_speed_kt=0.0), "wake.geometry"),
    ]
    for fields, name in cases:
        spec = spec_for(**fields)
        assert names(validate_wake(spec)) == [name], fields
        with contextlib.redirect_stdout(io.StringIO()):
            report = validate(spec, check_feasibility=False)
        assert name in names(report.violations), fields
        assert f"[{name}]" in report.render()
    # A stated block with no generator applies nothing and refuses nothing.
    assert validate_wake(spec_for(separation_s=20.0, lateral_offset_m=30.0)) == []
    with contextlib.redirect_stdout(io.StringIO()):
        assert validate(spec_for(**DEMO), check_feasibility=False).ok


# -- the block -------------------------------------------------------------------------------

def test_the_block_is_absent_canonical_and_the_committed_examples_keep_their_digests():
    assert WakeSpec.defaulted().is_default()
    assert WakeSpec.FIELD_ORDER == ("generator", "generator_speed_kt", "lateral_offset_m",
                                    "vertical_offset_m", "separation_s", "age_s", "model",
                                    "eps_star", "n_star")
    for path, digest in EXAMPLE_DIGESTS.items():
        spec = ScenarioSpec.read(REPO / path)
        assert spec.wake.is_default() and "wake" not in spec.to_dict(), path
        assert spec.digest() == digest, path
    spec = spec_for()
    plain = spec.digest()
    assert "wake" not in spec.to_dict()
    spec.set("wake.generator", "B747", frm="test")
    spec.set("wake.separation_s", 20.0, frm="test")
    assert spec.digest() != plain
    data = spec.to_dict()
    assert list(data["wake"]) == list(WakeSpec.FIELD_ORDER)
    assert data["wake"]["generator"]["source"] == "user"
    again = ScenarioSpec.from_dict(json.loads(json.dumps(data)))
    assert again.digest() == spec.digest()
    assert "[wake]" in spec.render_table() and "B747" in spec.render_table()
    with pytest.raises(ValueError, match="never silently moved"):
        spec.plan("wake.generator", "A320", frm="planner")
    spec.plan("wake.model", "sarpkaya", frm="planner")        # a defaulted field may be planned
    assert str(spec.wake.model.source) == "derived"
    with pytest.raises(ValueError, match="unknown fields"):
        WakeSpec.from_dict({**data["wake"], "crow": {"value": 1, "source": "user"}})
    assert wake_injections_for(spec_for()) == ()
    assert wake_injections_for(spec_for(**DEMO)) == ("gust_rotation",)
    assert wake_injections_for(spec_for(separation_s=20.0)) == ()
    assert unread_wake_fields(spec_for(separation_s=20.0, lateral_offset_m=3.0)) == [
        "lateral_offset_m", "separation_s"]


def test_a_block_without_a_generator_applies_nothing_and_says_so():
    stack = environment_for(spec_for(separation_s=20.0, lateral_offset_m=30.0))
    assert not any(isinstance(p, WakeVortexPair) for p in stack.gust)
    note = [n for n in stack.notes if n.get("provider") == "wake_vortex_pair"]
    assert len(note) == 1 and note[0]["applied"] is False
    assert note[0]["unread_stated_fields"] == ["lateral_offset_m", "separation_s"]
    assert not environment_for(spec_for()).notes


def test_the_registry_claims_the_block_field_for_field_with_recorded_channels(demo_run):
    fields = {f"wake.{f}" for f in WakeSpec.FIELD_ORDER}
    assert fields <= set(REGISTRY.spec_fields())
    assert "wake" in REGISTRY.sections()
    recorded = set(demo_run.telemetry.columns)
    for name in fields:
        entry = REGISTRY.get(name)
        assert entry.null_basis and entry.effect_channels
        assert [w.property for w in entry.jsbsim_writes] == [
            "atmosphere/gust-north-fps", "atmosphere/gust-east-fps", "atmosphere/gust-down-fps",
            "gust/p-equivalent-rad_sec"]
        assert entry.readback_tolerance.value == 0.0
        missing = [c.name for c in entry.effect_channels if c.name not in recorded]
        assert missing == [], (name, missing)
    assert REGISTRY.get("wake.generator").null_value is None
    assert REGISTRY.get("wake.model").null_value == "none"
    assert REGISTRY.get("wake.lateral_offset_m").null_value == 0.0
    # The circulation column is NEVER an effect channel of the generator's
    # entry (its pair moves the column from Gamma_0 to 0 by construction,
    # which would call every generator pair reached, the far-offset control
    # included) nor of the offsets (Gamma does not depend on them); where
    # it is registered at all, it is on the six entries whose variable
    # enters the circulation: the speed, the model, eps*, N* and the ages.
    with_gamma = {name for name in fields
                  if any(c.name == "wake_gamma_m2_s" for c in REGISTRY.get(name).effect_channels)}
    assert not with_gamma & {"wake.generator", "wake.lateral_offset_m", "wake.vertical_offset_m"}
    assert with_gamma in (set(), {"wake.generator_speed_kt", "wake.model", "wake.eps_star",
                                  "wake.n_star", "wake.separation_s", "wake.age_s"})
    assert set(TELEMETRY_COLUMNS) <= recorded
    assert not set(TELEMETRY_COLUMNS) & set(DEFAULT_CHANNELS)      # the provider's own columns
    # The stock run without a wake records the nine columns as zeros.
    plain = quiet_run(spec_for(duration=1.0))
    for column in TELEMETRY_COLUMNS:
        assert set(plain.telemetry.columns[column]) == {0.0}, column
    assert plain.manifest["wake"] is None and "wake." not in json.dumps(
        [r["name"] for r in read_records(plain.manifest["applied_variables"])])


# -- the real run -------------------------------------------------------------------------------

def test_the_demo_run_flies_the_derived_airframe_delivers_the_field_and_reads_it_back(demo_run):
    """The c172p is derived with the gust_rotation injection; the stack
    writes the pair's velocity into the gust channel and p_eq into the
    roll property every step and reads all four back exact (max |error|
    0.0 over 479 checked steps of 480); the gust-down column equals the
    wake's w to the bit and the roll property equals p_eq; the first
    sample carries the field at the stated geometry; the aircraft on the
    starboard vortex's line rolls LEFT (-7.46 deg at 0.5 s, -39.75 deg
    peak at 3.6 s) and sinks 6.4 m in 4 s."""
    fdm = demo_run.manifest["fdm"]
    assert fdm["derivation"]["suffix"] == "-gust" and fdm["aircraft"]["name"] == "c172p-gust"
    gust = demo_run.manifest["environment_delivery"]["gust"]
    assert gust["p_equivalent"] == "property" and gust["providers"] == ["wake_vortex_pair"]
    assert gust["steps_written"] == 480 and gust["steps_checked"] == 479
    assert gust["max_abs_error"] == {p: 0.0 for p in (
        "atmosphere/gust-north-fps", "atmosphere/gust-east-fps", "atmosphere/gust-down-fps",
        "gust/p-equivalent-rad_sec")}
    cols = demo_run.telemetry.columns
    # The first sample precedes the first step's write (the gust channel
    # still reads 0 there; the wake columns carry the stated geometry);
    # from the first step on the channel IS the wake's w and p_eq.
    assert cols["gust_down_mps"][0] == 0.0 and cols["gust_p_equivalent_rad_s"][0] == 0.0
    assert max(abs(a - b) for a, b in zip(cols["gust_down_mps"][1:], cols["wake_w_mps"][1:])) < 1e-12
    assert cols["gust_p_equivalent_rad_s"][1:] == cols["wake_p_eq_rad_s"][1:]
    assert set(cols["wake_u_mps"]) == {0.0}
    assert set(cols["wake_gamma_m2_s"]) == {GAMMA_0}          # the none model holds Gamma_0
    # The first sample is the stated geometry: the fifth selftest vector.
    assert cols["wake_lateral_m"][0] == 25.315 and cols["wake_vertical_m"][0] == 15.0
    assert cols["wake_age_s"][0] == 20.0
    assert cols["wake_p_eq_rad_s"][0] == pytest.approx(SELFTEST[4][6], abs=1e-12)
    assert cols["wake_w_mps"][0] == pytest.approx(SELFTEST[4][5], abs=1e-12)
    assert cols["wake_v_mps"][0] == pytest.approx(SELFTEST[4][4], abs=1e-12)
    # The age evolves as separation + t (1 - V_own / V_gen): 20 -> 22.28 s over 4 s
    # (22.27 at the last 10 Hz sample, measured).
    assert cols["wake_age_s"][-1] == pytest.approx(20.0 + 4.0 * (1.0 - 55.322 / 128.611), abs=0.02)
    # The sign: an upwash on the right wing (outside the starboard vortex)
    # gives a positive p_eq and a LEFT roll.
    assert cols["wake_p_eq_rad_s"][0] > 0.2
    assert cols["roll_deg"][5] == pytest.approx(-7.456, abs=0.05)
    roll = np.array(cols["roll_deg"])
    k = int(np.argmax(np.abs(roll)))
    assert roll[k] == pytest.approx(-39.75, abs=0.1) and cols["t"][k] - cols["t"][0] == pytest.approx(3.6, abs=0.05)
    assert cols["altitude_m"][0] - cols["altitude_m"][-1] == pytest.approx(6.39, abs=0.1)
    # The RCR on the c172p (its aileron term is a plain value): 0.139 at the first sample.
    assert cols["wake_rcr"][0] == pytest.approx(0.139, abs=0.002)
    block = demo_run.manifest["wake"]
    assert block["applied"] and block["rcr"]["available"] is True
    assert block["prepared"]["gamma_0_m2_s"] == GAMMA_0
    assert block["prepared"]["rho_kgm3"] == pytest.approx(1.05811, abs=1e-4)
    assert block["prepared"]["own_span_m"] == pytest.approx(10.91184, abs=1e-5)


def test_the_stated_fields_return_their_records_with_readback_and_null_test(demo_run):
    records = {r["name"]: r for r in read_records(demo_run.manifest["applied_variables"])}
    stated = ["wake.generator", "wake.generator_speed_kt", "wake.lateral_offset_m",
              "wake.vertical_offset_m", "wake.separation_s"]
    assert [n for n in records if n.startswith("wake.")] == stated
    for name in stated:
        r = records[name]
        assert r["source"] == "user" and r["readback"]["agrees"] is True
        assert r["readback"]["property"] == "gust/p-equivalent-rad_sec"
        assert r["readback"]["tolerance"] == 0.0 and r["readback"]["value"] == r["readback"]["written"]
        assert [w["property"] for w in r["jsbsim_writes"]] == list(r["properties_written"])
        assert len(r["jsbsim_writes"]) == 4
        assert r["telemetry_columns"] == list(TELEMETRY_COLUMNS) == r["frame_keys"]
        assert r["model"]["name"] == "Burnham-Hallock vortex pair with uniform-lift strip theory"
        assert r["model"]["parameters"]["gamma_0_m2_s"] == GAMMA_0
        assert r["null_test"]["kind"] == "reached" and r["null_test"]["ok"] is True
        assert r["null_test"]["with"] == pytest.approx(0.2392, abs=1e-3)
        assert r["parameters"]["per_step_readback"]["agrees"] is True
        assert r["parameters"]["delivery"]["p_equivalent"] == "property"
        assert any("Crow" in n for n in r["not_claimed"])
        assert any("strip-theory" in n for n in r["not_claimed"])
        assert r["std"]
    assert records["wake.generator"]["value"] == "B747" and records["wake.generator"]["unit"] == "word"
    assert records["wake.separation_s"]["value"] == 20.0 and records["wake.separation_s"]["unit"] == "s"
    assert records["wake.generator"]["parameters"]["card"]["gamma_0"] == GAMMA_0
    assert "selftest" not in records["wake.generator"]["parameters"]["card"]


def test_the_rcr_is_readable_on_the_c172p_and_absent_on_the_b747():
    c172p = aileron_authority("c172p")
    assert c172p["available"] and c172p["clp"] == -0.484 and c172p["clda"] == 0.229
    assert c172p["aileron_max_rad"] == pytest.approx(20.0 * 0.01745)
    b747 = aileron_authority("B747")
    assert b747["available"] is False and "table" in b747["reason"]
    provider = WakeVortexPair(generator_data("B747"), 25.0, 0.0, 0.0, separation_s=20.0)
    assert provider.rcr_at(1.0, 50.0) == 0.0                 # not prepared: absent
    provider.rcr = c172p
    provider.own_span_m = 10.9
    assert provider.rcr_at(0.2334, 55.322) == pytest.approx(
        abs(-0.484 * 0.2334 * 10.9 / (2 * 55.322)) / (0.229 * 0.349), rel=1e-9)


# -- the null pairs, measured ------------------------------------------------------------------------

@pytest.mark.timeout(300)
def test_the_null_pair_encounter_against_none_rolls_the_aircraft_past_5_deg_and_diverges():
    """run_null_pair on wake.generator (B747 against unstated) at the
    demonstration geometry: roll_deg peak 33.10 deg (floor 0.05),
    wake_p_eq_rad_s 0.2392 rad/s, altitude 6.29 m, the digests differ, ~3 s
    for the pair. On the starboard core line at the pair's height the
    c172p flips (|roll| beyond 90 deg within 1.6 s, 86 m lost in 4 s)."""
    pair = quiet_pair(spec_for(**DEMO), "wake.generator")
    d = pair.to_dict()
    assert pair.verdict == "reached" and pair.digests_differ
    assert d["effect"]["roll_deg"]["peak_abs"] == pytest.approx(33.10, abs=0.2)
    assert d["effect"]["roll_deg"]["peak_abs"] > 5.0 and d["effect"]["roll_deg"]["reached"] is True
    assert d["effect"]["wake_p_eq_rad_s"]["peak_abs"] == pytest.approx(0.2392, abs=1e-3)
    assert d["effect"]["gust_p_equivalent_rad_s"]["peak_abs"] == d["effect"]["wake_p_eq_rad_s"]["peak_abs"]
    assert d["effect"]["altitude_m"]["peak_abs"] == pytest.approx(6.29, abs=0.1)
    assert pair.null_test().ok and pair.elapsed_s < 60.0
    core = quiet_run(spec_for(**{**DEMO, "vertical_offset_m": 0.0}))
    cols = core.telemetry.columns
    assert max(abs(r) for r in cols["roll_deg"][:20]) > 90.0
    assert cols["altitude_m"][0] - cols["altitude_m"][-1] > 50.0
    assert max(cols["wake_rcr"]) > 1.0             # beyond the aileron's authority
    print(f"wake pair c172p behind B747 (demo geometry): {pair.elapsed_s:.2f} s; roll peak "
          f"{d['effect']['roll_deg']['peak_abs']:.2f} deg; core line flips to "
          f"{max(cols['roll_deg'], key=abs):.1f} deg")


@pytest.mark.timeout(300)
def test_the_far_offset_control_barely_moves_the_aircraft():
    """The same pair 300 m to the side of the pair: silent -- roll 0.038
    deg (floor 0.05), altitude 0.048 m (floor 0.5), w 0.031 m/s (floor
    0.051), p_eq 2e-4 rad/s -- while the digests still differ. The
    circulation column is present on the generator's flight (338 m^2/s
    against 0 without one) but is not a graded channel of the
    generator's pair: it is the generator's own constant, moved by
    construction, so grading it there would call this control reached."""
    pair = quiet_pair(spec_for(**{**DEMO, "lateral_offset_m": 300.0, "vertical_offset_m": 0.0}),
                      "wake.generator")
    d = pair.to_dict()
    assert pair.verdict == "silent" and pair.digests_differ
    assert d["effect"]["roll_deg"]["peak_abs"] < 0.05
    assert d["effect"]["altitude_m"]["peak_abs"] < 0.1
    assert d["effect"]["wake_p_eq_rad_s"]["peak_abs"] < 5e-4
    assert "wake_gamma_m2_s" not in d["effect"]
    assert not any(e["reached"] for e in d["effect"].values())      # None = ungraded (wake_rcr, unit 1)


@pytest.mark.timeout(300)
def test_the_geometry_and_decay_pairs_measure_their_fields():
    """lateral 25.315 -> 0 (centred between the cores: downwash, no roll)
    moves the offset column by 25.3 m and the roll by 33.0 deg; sarpkaya
    (eps* 0.2) against none at 20 s of age moves p_eq by 0.018 rad/s and
    the roll by 2.2 deg."""
    lateral = quiet_pair(spec_for(**DEMO), "wake.lateral_offset_m").to_dict()
    assert lateral["verdict"] == "reached"
    assert lateral["effect"]["wake_lateral_m"]["peak_abs"] == pytest.approx(25.315, abs=1e-6)
    assert lateral["effect"]["roll_deg"]["peak_abs"] == pytest.approx(32.96, abs=0.2)
    decay = quiet_pair(spec_for(**{**DEMO, "model": "sarpkaya", "eps_star": 0.2}), "wake.model").to_dict()
    assert decay["verdict"] == "reached"
    assert decay["effect"]["wake_p_eq_rad_s"]["peak_abs"] == pytest.approx(0.0182, abs=5e-4)
    assert decay["effect"]["roll_deg"]["peak_abs"] == pytest.approx(2.155, abs=0.05)
    if "wake_gamma_m2_s" in decay["effect"]:
        # Once the circulation is a registered effect channel of the model's
        # entry (the integration patch: the _m2_s suffix, the six entries,
        # the 1 m^2/s floor), the decay pair moves it by Gamma_0 - Gamma(age):
        # 24.48 m^2/s at the first sample (338.17 - 313.69 at 20 s; T = 0.420,
        # T_d = 5.800 at eps* 0.2) growing to the peak 27.25 m^2/s at the last
        # (the age 22.27 s), reached against the floor.
        gamma = decay["effect"]["wake_gamma_m2_s"]
        assert gamma["unit"] == "m^2/s" and gamma["floor"] == 1.0 and gamma["reached"] is True
        assert gamma["peak_abs"] == pytest.approx(27.25, abs=0.05)
        assert gamma["peak_index"] == gamma["samples"] - 1
        print(f"wake.model pair: circulation effect {gamma['peak_abs']:.2f} m^2/s (floor {gamma['floor']})")
    # An unstated age refuses by name (the variable that moves the age is the one stated).
    with pytest.raises(Exception) as err:
        quiet_pair(spec_for(**DEMO), "wake.separation_s")
    assert "wake.geometry" in str(err.value)


# -- the card ---------------------------------------------------------------------------------------------

def test_the_card_block_carries_the_pair_in_the_fixed_key_order_with_the_selftest_vectors(tmp_path):
    spec = spec_for(**DEMO)
    with contextlib.redirect_stdout(io.StringIO()):
        block = wake_card_block(spec)
    assert tuple(block) == CARD_KEYS == ("generator", "gamma_0", "b_0", "r_c", "decay",
                                         "geometry", "selftest")
    assert block["gamma_0"] == GAMMA_0 and block["b_0"] == B747_B0_M and block["r_c"] == B747_RC_M
    assert block["generator"]["aircraft"] == "B747" and block["generator"]["weight_lb"] == 523816.0
    assert block["generator"]["span_ft"] == 211.5
    assert block["generator"]["speed_mps"] == pytest.approx(250.0 * 1852.0 / 3600.0)
    assert block["generator"]["ahead_m"] == pytest.approx(20.0 * block["generator"]["speed_mps"])
    assert block["generator"]["right_m"] == -25.315
    assert block["generator"]["above_m"] == pytest.approx(21.2606 - 15.0, abs=1e-3)
    assert block["decay"]["model"] == "none" and block["decay"]["demise_time_s"] is None
    assert block["geometry"]["own_span_m"] == pytest.approx(10.91184, abs=1e-5)
    assert len(block["selftest"]) == 5
    for vector, expected in zip(block["selftest"], SELFTEST):
        assert tuple(vector) == SELFTEST_KEYS
        for key, value in zip(SELFTEST_KEYS, expected):
            assert vector[key] == pytest.approx(value, abs=1e-9), (key, vector)
    # The first vector sits between the cores: downwash, no roll; the
    # second at r_c outside the starboard core: the analytic core value
    # of the near vortex plus the far one's, upward.
    assert block["selftest"][0]["p_eq_rad_s"] == 0.0 and block["selftest"][0]["w_mps"] > 0.0
    near = burnham_hallock(B747_RC_M, GAMMA_0, B747_RC_M)
    far = burnham_hallock(B747_B0_M + B747_RC_M, GAMMA_0, B747_RC_M)
    assert block["selftest"][1]["w_mps"] == pytest.approx(-(near - far), abs=1e-9)
    # On the card, after the icing schedule; absent without a generator.
    with contextlib.redirect_stdout(io.StringIO()):
        write_run_card(spec, tmp_path / "card.json")
        write_run_card(spec_for(), tmp_path / "plain.json")
    card = json.loads((tmp_path / "card.json").read_text(encoding="utf-8"))
    assert list(card["wake"]) == list(CARD_KEYS)
    assert "wake" not in json.loads((tmp_path / "plain.json").read_text(encoding="utf-8"))
    assert wake_card_block(spec_for()) is None
    (tmp_path / "card.json").read_text(encoding="utf-8").encode("ascii")


def test_a_sarpkaya_card_states_the_demise_and_the_unread_fields_beside_none():
    provider = WakeVortexPair(generator_data("B747"), 25.315, 15.0, 0.0, separation_s=20.0,
                              model="sarpkaya", eps_star=0.2, n_star=0.1)
    provider.gamma_0 = GAMMA_0
    provider.w_0 = descent_speed(GAMMA_0, B747_B0_M)
    decay = provider.decay_block()
    assert decay["demise_time_nd"] == pytest.approx(min((0.7475 / 0.2) ** (4 / 3), math.pi / 0.2))
    assert decay["demise_time_s"] == pytest.approx(decay["demise_time_nd"] * decay["t_0_s"])
    assert decay["gamma_at_age_0_m2_s"] < GAMMA_0
    held = WakeVortexPair(generator_data("B747"), 25.315, 15.0, 0.0, age_s=20.0, eps_star=0.3)
    assert held.age_0_s == 20.0 and held.decay_block()["unread_stated_fields"] == ["eps_star"]


# -- the generator's track for the render host --------------------------------------------------------

def test_the_wake_generator_track_is_a_straight_line_ahead_and_above_at_the_stated_speed():
    assert TRAFFIC_TRACKS == ("formation", "crossing", "overtaking", "wake_generator")
    columns = make_columns(duration_s=6.0, speed_mps=55.0, heading=lambda t: 30.0)
    geometry = {"heading_deg": 30.0, "speed_mps": 128.6, "ahead_m": 2572.0, "right_m": -25.3,
                "above_m": 6.26}
    track = solve_traffic_track(columns, "wake_generator", 0.0, FRAME, "aircraft:B747:1",
                                wake=geometry)
    assert track.digest() == solve_wake_generator_track(columns, geometry, FRAME,
                                                        "aircraft:B747:1").digest()
    first = aircraft_local_track(columns, FRAME)[0]
    h = math.radians(30.0)
    forward, right = (math.cos(h), math.sin(h)), (-math.sin(h), math.cos(h))
    assert track.north_m[0] == pytest.approx(first["north_m"] + 2572.0 * forward[0] - 25.3 * right[0])
    assert track.east_m[0] == pytest.approx(first["east_m"] + 2572.0 * forward[1] - 25.3 * right[1])
    assert track.alt_m[0] == pytest.approx(first["alt_m"] + 6.26)
    assert set(track.alt_m) == {track.alt_m[0]} and set(track.roll_deg) == {0.0}
    assert set(track.yaw_deg) == {30.0} and set(track.pitch_deg) == {0.0}
    dt = track.t[1] - track.t[0]
    step = math.hypot(track.north_m[1] - track.north_m[0], track.east_m[1] - track.east_m[0])
    assert step / dt == pytest.approx(128.6, rel=1e-9)
    assert track.preset == "wake_generator" and track.camera_id == "aircraft:B747:1"
    for bad in ({}, {**geometry, "speed_mps": 0.0}, {**geometry, "ahead_m": -1.0}, None):
        with pytest.raises(PoseSolveError, match="camera.poses"):
            solve_wake_generator_track(columns, bad, FRAME, "x")
    with pytest.raises(PoseSolveError, match="camera.poses"):
        solve_traffic_track(columns, "wake_generator", 100.0, FRAME, "x")

    class Obj:
        id = "aircraft:B747:1"
        int_id = 2

    block = wake_generator_card_block(track, "B747", geometry, Obj, FRAME, (1327.0, 0.0, -24.0), None)
    assert block["track"] == "wake_generator" and block["range_m"] == 2572.0
    assert block["wake_geometry"] == {k: geometry[k] for k in WAKE_GEOMETRY_KEYS}
    assert block["cg_actor_cm"] == [-3370.58, 0.0, -60.96]
    assert block["track_digest"] == track.digest()
    json.dumps(block).encode("ascii")


def test_the_provider_geometry_feeds_the_track_solver(demo_run):
    geometry = demo_run.manifest["wake"]["card"]["generator"]
    assert all(k in geometry for k in WAKE_GEOMETRY_KEYS)
    track = solve_wake_generator_track(demo_run.telemetry.columns, geometry, FRAME, "aircraft:B747:1")
    assert len(track) == len(demo_run.telemetry.columns["t"])
    assert track.alt_m[0] == pytest.approx(demo_run.telemetry.columns["altitude_m"][0] + geometry["above_m"])


def test_everything_the_engine_or_a_reader_sees_is_ascii():
    for rel in ("core/environment/wake.py", "tests/test_wake.py"):
        (REPO / rel).read_text(encoding="utf-8").encode("ascii")


# -- the verifier: the card's selftest vectors re-evaluated independently ------------------------

#: The text returned to the integrator for core/capture/verify.py (P7),
#: verbatim: the checker's own two-line Burnham-Hallock from the card's
#: Gamma, b_0 and r_c and its own strip-theory quadrature, against the five
#: selftest vectors the card carries -- and, once a render host writes
#: ``environment.wake_selftest`` into render.json (P9), the host's vectors
#: against the card's. Executed here with the verifier's own Check /
#: PASS / FAIL / NOT_RUN so the clauses are tested before the patch lands.
VERIFY_WAKE_PATCH = r'''
# -- P7: the wake-vortex pair's selftest vectors -------------------------------

#: How far the checker's own evaluation of the card's field may sit from
#: the card's vectors, and a host's from the card's: 1e-9 m/s and rad/s
#: (the blueprint's bound; two IEEE-754 evaluations of one closed form).
WAKE_SELFTEST_TOL = 1e-9
FAIL_WAKE = "check.wake_selftest"
WAKE_SELFTEST_KEYS = ("y_m", "z_m", "age_s", "u_mps", "v_mps", "w_mps", "p_eq_rad_s")


def _wake_vortex_speed(r, gamma, r_c):
    """Burnham-Hallock, written from the definition: Gamma/(2 pi r) x r^2/(r^2 + r_c^2)."""
    return gamma * r / (2.0 * math.pi * (r * r + r_c * r_c))


def _wake_pair(y, z, gamma, b_0, r_c):
    """(v, w_up) of the pair: starboard (+b_0/2) counter-clockwise seen from
    behind, port (-b_0/2) clockwise; y right, z up."""
    v = w = 0.0
    for y0, sign in ((0.5 * b_0, 1.0), (-0.5 * b_0, -1.0)):
        dy, dz = y - y0, z
        r = math.hypot(dy, dz)
        if r > 0.0:
            s = _wake_vortex_speed(r, gamma, r_c)
            v += sign * s * (-dz / r)
            w += sign * s * (dy / r)
    return v, w


def _wake_p_eq(y, z, gamma, b_0, r_c, span):
    """(12/b^3) int w_up(y + s) s ds over the span by 32-point Gauss-Legendre
    (numpy's nodes; the producer's rule of the same order, re-written)."""
    import numpy as np

    nodes, weights = np.polynomial.legendre.leggauss(32)
    total = 0.0
    for x, wt in zip(nodes, weights):
        s = 0.5 * span * float(x)
        total += float(wt) * s * _wake_pair(y + s, z, gamma, b_0, r_c)[1]
    return 12.0 / span ** 3 * total * 0.5 * span


def verify_wake_selftest(manifest: Dict, run_dir=None) -> Check:
    """The run card's ``wake`` block against the checker's own evaluation
    of the same closed forms: for each of the five selftest vectors, u = 0,
    (v, w down) from the checker's Burnham-Hallock pair at the card's
    Gamma at the age, b_0 and r_c, and p_eq from the checker's own
    strip-theory quadrature over the card's own span, each within
    WAKE_SELFTEST_TOL; then, where a render host wrote
    ``environment.wake_selftest`` into a render.json (P9), the host's
    vectors against the card's within the same bound. NOT RUN without a
    run directory, a card.json or a wake block (no wake was stated), and
    the host half is reported NOT RUN inside the detail when no render.json
    carries the key. FAIL (check.wake_selftest) on a block missing a key,
    a vector that does not reproduce, or a host vector that differs. What
    is NOT checked: Gamma_0 itself against the generator's weight (the card
    states it; the generator's data are the producer's), the decay's
    history (the card's circulation at the age is taken as stated), and
    that the field reached the aircraft (the delivery is the run's own
    read-back)."""
    if run_dir is None:
        return Check("wake_selftest", NOT_RUN, "no run directory: no card to read")
    card_path = Path(run_dir) / "card.json"
    if not card_path.is_file():
        return Check("wake_selftest", NOT_RUN, "no card.json in the run directory")
    try:
        card = json.loads(card_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Check("wake_selftest", FAIL, f"card.json could not be read: {exc}", FAIL_WAKE)
    wake = card.get("wake") if isinstance(card, dict) else None
    if not isinstance(wake, dict):
        return Check("wake_selftest", NOT_RUN, "the card states no wake: nothing to re-evaluate")
    try:
        b_0 = float(wake["b_0"])
        r_c = float(wake["r_c"])
        gamma = float(wake["decay"]["gamma_at_age_0_m2_s"])
        span = float(wake["geometry"]["own_span_m"])
        vectors = list(wake["selftest"])
    except (KeyError, TypeError, ValueError) as exc:
        return Check("wake_selftest", FAIL,
                     f"the wake block lacks a key the re-evaluation needs: {exc!r}", FAIL_WAKE)
    if len(vectors) != 5 or any(tuple(v) != WAKE_SELFTEST_KEYS for v in vectors):
        return Check("wake_selftest", FAIL,
                     f"the selftest is not five vectors of {list(WAKE_SELFTEST_KEYS)}", FAIL_WAKE)
    worst = 0.0
    for vector in vectors:
        y, z = float(vector["y_m"]), float(vector["z_m"])
        v, w_up = _wake_pair(y, z, gamma, b_0, r_c)
        own = {"u_mps": 0.0, "v_mps": v, "w_mps": -w_up,
               "p_eq_rad_s": _wake_p_eq(y, z, gamma, b_0, r_c, span)}
        for key, value in own.items():
            worst = max(worst, abs(float(vector[key]) - value))
    if worst > WAKE_SELFTEST_TOL:
        return Check("wake_selftest", FAIL,
                     f"the card's selftest vectors differ from the checker's own Burnham-Hallock "
                     f"pair and strip-theory quadrature by up to {worst:.3e} (bound "
                     f"{WAKE_SELFTEST_TOL:g})", FAIL_WAKE)
    host_worst = None
    host_files = 0
    for path in sorted(Path(run_dir).rglob("render.json")):
        try:
            render = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        host = (render.get("environment") or {}).get("wake_selftest") if isinstance(render, dict) else None
        if not isinstance(host, list):
            continue
        host_files += 1
        if len(host) != len(vectors):
            return Check("wake_selftest", FAIL,
                         f"{path.name} carries {len(host)} host vectors for the card's "
                         f"{len(vectors)}", FAIL_WAKE)
        for ours, theirs in zip(vectors, host):
            for key in ("u_mps", "v_mps", "w_mps", "p_eq_rad_s"):
                try:
                    diff = abs(float(ours[key]) - float(theirs[key]))
                except (KeyError, TypeError, ValueError):
                    return Check("wake_selftest", FAIL,
                                 f"{path.name}'s host vector lacks {key}", FAIL_WAKE)
                host_worst = diff if host_worst is None else max(host_worst, diff)
    if host_worst is not None and host_worst > WAKE_SELFTEST_TOL:
        return Check("wake_selftest", FAIL,
                     f"the render host's wake selftest differs from the card's vectors by up to "
                     f"{host_worst:.3e} (bound {WAKE_SELFTEST_TOL:g})", FAIL_WAKE)
    return Check("wake_selftest", PASS,
                 f"five vectors re-evaluated by the checker's own pair and quadrature, worst "
                 f"{worst:.3e}; host half "
                 + ("NOT RUN (no render.json carries environment.wake_selftest: the host port "
                    "is a Windows step)" if host_worst is None else
                    f"PASS over {host_files} render.json, worst {host_worst:.3e}"))
'''


def _wake_verifier():
    """``verify_wake_selftest``: verify.py's own once the patch is applied,
    else the patch text executed against verify.py's Check types."""
    from core.capture import verify

    if hasattr(verify, "verify_wake_selftest"):
        return verify.verify_wake_selftest
    namespace = {"Check": verify.Check, "PASS": verify.PASS, "FAIL": verify.FAIL,
                 "NOT_RUN": verify.NOT_RUN, "Path": Path, "math": math, "json": json, "Dict": dict}
    exec(compile(VERIFY_WAKE_PATCH, "<verify_wake patch>", "exec"), namespace)
    return namespace["verify_wake_selftest"]


def test_the_verifier_patch_imports_no_producer_and_re_evaluates_the_card(tmp_path):
    assert "core.environment" not in VERIFY_WAKE_PATCH and "from core" not in VERIFY_WAKE_PATCH
    check = _wake_verifier()
    with contextlib.redirect_stdout(io.StringIO()):
        write_run_card(spec_for(**DEMO), tmp_path / "card.json")
    result = check({}, tmp_path)
    assert result.status == "PASS" and "host half NOT RUN" in result.detail, result.detail
    assert check({}, None).status == "NOT RUN"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert check({}, empty).status == "NOT RUN"
    with contextlib.redirect_stdout(io.StringIO()):
        write_run_card(spec_for(), empty / "card.json")
    assert check({}, empty).status == "NOT RUN"
    # A corrupted vector (1e-6 m/s on one w) fails by name; so does a moved
    # core radius, whose vectors no longer reproduce.
    card = json.loads((tmp_path / "card.json").read_text(encoding="utf-8"))
    for corrupt in (lambda c: c["wake"]["selftest"][1].__setitem__("w_mps", c["wake"]["selftest"][1]["w_mps"] + 1e-6),
                    lambda c: c["wake"].__setitem__("r_c", c["wake"]["r_c"] * 1.01),
                    lambda c: c["wake"]["selftest"].pop(),
                    lambda c: c["wake"].pop("b_0")):
        bad = json.loads(json.dumps(card))
        corrupt(bad)
        (tmp_path / "bad" ).mkdir(exist_ok=True)
        (tmp_path / "bad" / "card.json").write_text(json.dumps(bad), encoding="utf-8")
        result = check({}, tmp_path / "bad")
        assert result.status == "FAIL" and result.failure == "check.wake_selftest", result.detail
    # The host half: a fabricated render.json with the card's vectors passes;
    # one whose vector moved by 2e-9 fails by name.
    host = tmp_path / "cam0"
    host.mkdir()
    vectors = card["wake"]["selftest"]
    (host / "render.json").write_text(json.dumps({"environment": {"wake_selftest": vectors}}),
                                      encoding="utf-8")
    result = check({}, tmp_path)
    assert result.status == "PASS" and "host half PASS over 1" in result.detail
    moved = json.loads(json.dumps(vectors))
    moved[2]["p_eq_rad_s"] += 2e-9
    (host / "render.json").write_text(json.dumps({"environment": {"wake_selftest": moved}}),
                                      encoding="utf-8")
    result = check({}, tmp_path)
    assert result.status == "FAIL" and result.failure == "check.wake_selftest"
