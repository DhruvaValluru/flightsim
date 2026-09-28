"""The XML-injection pipeline (ADVANCEMENTS_BLUEPRINT section 1, work item P2).

Every number asserted here was measured in this container on the installed
JSBSim 1.2.4 with the stock c172p (the other airframes appear only where a
refusal is the point): the neutral-value bit-identity of each injection over
8 s of a trimmed elevator step, the failure chain holding half a command for
100 steps, JSBSim's own actuator malfunctions read back by position, the
lift drop at factor 0.8, the stall-peak shift, the roll a rotational gust
produces, and the three refusals by name.

Not claimed: any of these is a statement about the JSBSim c172p model's
tables, not about an aeroplane; no engine has loaded a derived airframe.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from core.control import derive as module
from core.control.derive import (
    AXIS_FACTORS, DEFAULT_INJECTIONS, INJECTION_ORDER, INJECTION_VARIABLES, INJECTIONS,
    SURFACES, DerivationError, derive, injection_variable, select_injections, suffix_for,
    verify_hashes,
)
from core.fdm import units as u
from core.fdm.fdm import FlightDynamics, TrimMode
from core.records import AppliedVariable, NullTest

ALL = ("failures", "icing", "icing_alpha", "gust_rotation")
LEVEL = {"gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
         "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0}
ALT_M, CAS_KT = 1500.0, 100.0

#: The state compared step for step between the stock and the derived
#: airframe: position, attitude, body velocities and rates, alpha, the
#: three aero forces and moments, and the elevator.
COMPARED = ("position/h-sl-ft", "attitude/theta-rad", "attitude/phi-rad", "attitude/psi-rad",
            "velocities/u-fps", "velocities/w-fps", "velocities/p-rad_sec",
            "velocities/q-rad_sec", "aero/alpha-rad", "forces/fwz-aero-lbs",
            "forces/fwx-aero-lbs", "moments/l-aero-lbsft", "moments/m-aero-lbsft",
            "moments/n-aero-lbsft", "fcs/elevator-pos-rad")


@pytest.fixture(scope="module")
def build(tmp_path_factory) -> Path:
    """A build root shaped like the real one (``<root>/aircraft/<name>/``),
    so the derived airframe resolves through the one aircraft lookup."""
    return tmp_path_factory.mktemp("build") / "aircraft"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trimmed(fdm: FlightDynamics) -> FlightDynamics:
    fdm.set_initial_conditions({"h-sl-ft": u.m_to_ft(ALT_M), "vc-kts": CAS_KT, **LEVEL})
    fdm.start_engines()
    fdm.trim(TrimMode.LONGITUDINAL)
    fdm.hold_mass(True)
    return fdm


def elevator_step_flight(fdm: FlightDynamics, seconds: float = 8.0, at_s: float = 1.0,
                         elevator: float = -0.3):
    rows = []
    for i in range(int(seconds * fdm.rate_hz)):
        if i == int(at_s * fdm.rate_hz):
            fdm.set_controls(elevator=elevator)
        fdm.step()
        rows.append([fdm.props.get(p) for p in COMPARED])
    return rows


def worst_diff(rows_a, rows_b) -> float:
    assert len(rows_a) == len(rows_b) == 960
    return max(abs(a - b) for ra, rb in zip(rows_a, rows_b) for a, b in zip(ra, rb))


# -- the pipeline: order, suffix, default, idempotence ---------------------------------

def test_the_selection_is_applied_in_the_fixed_order_and_the_suffix_encodes_the_set():
    assert INJECTION_ORDER == ("tecs", "failures", "icing", "icing_alpha", "gust_rotation")
    given = ("gust_rotation", "icing", "tecs", "failures", "icing_alpha")
    assert tuple(i.name for i in select_injections(given)) == INJECTION_ORDER
    assert suffix_for(given) == "-tecs-fail-ice-alpha-gust"
    assert suffix_for(ALL) == "-fail-ice-alpha-gust"
    assert suffix_for(("tecs",)) == "-tecs" == module.SUFFIX
    for name in INJECTION_ORDER:
        assert suffix_for((name,)) == f"-{INJECTIONS[name].suffix}"


def test_the_default_derivation_is_the_tecs_one_unchanged(build):
    """``derive(name)`` with no selection is the TECS derivation as it always
    was: the same name, the same one system, the same template hash."""
    assert DEFAULT_INJECTIONS == ("tecs",)
    spec = derive("c172p", build_dir=build)
    assert spec.name == "c172p-tecs"
    assert spec.injection_names == ("tecs",)
    assert spec.template_sha256 == hashlib.sha256(
        module.TECS_TEMPLATE.read_bytes()).hexdigest()
    assert spec.provenance()["tecs_template_sha256"] == spec.template_sha256
    assert spec.provenance()["injections"][0]["system_file"] == "Systems/tecs.xml"
    assert sorted(p.name for p in spec.xml_path.parent.iterdir()
                  if p.name != spec.xml_path.name and p.is_dir()) == ["Systems"]
    assert [p.name for p in (spec.xml_path.parent / "Systems").iterdir()] == ["tecs.xml"]


def test_regenerating_is_byte_identical_and_the_hashes_are_of_the_files_on_disk(build):
    first = derive("c172p", build_dir=build, injections=ALL)
    second = derive("c172p", build_dir=build, injections=ALL)
    assert first.name == "c172p-fail-ice-alpha-gust"
    assert first.derived_sha256 == second.derived_sha256 == sha256_of(first.xml_path)
    assert first.template_sha256 is None
    assert first.provenance()["tecs_template_sha256"] is None
    for rec in first.injections:
        template = INJECTIONS[rec.name].template
        assert rec.template_sha256 == sha256_of(template)
        assert rec.written_sha256 == sha256_of(first.xml_path.parent / rec.system_file)
    assert [r.name for r in first.injections] == list(ALL)
    assert first.provenance()["suffix"] == "-fail-ice-alpha-gust"
    assert verify_hashes(first) == {
        first.xml_path.name: first.derived_sha256,
        **{r.system_file: r.written_sha256 for r in first.injections}}


def test_the_headless_and_host_derivations_differ_only_by_the_tecs_system(build):
    """Correction 2: the host never runs TECS, so its derivation is the
    headless one minus the controller -- one line of the airframe and the
    one system file."""
    host = derive("c172p", build_dir=build, injections=ALL)
    headless = derive("c172p", build_dir=build, injections=("tecs",) + ALL)
    a = host.xml_path.read_text(encoding="utf-8").splitlines()
    b = headless.xml_path.read_text(encoding="utf-8").splitlines()
    extra = [line for line in b if line not in a]
    missing = [line for line in a if line not in b]
    assert extra == ['    <system file="tecs"/>'] and missing == []
    assert headless.name == "c172p-tecs-fail-ice-alpha-gust"
    host_files = {p.name for p in (host.xml_path.parent / "Systems").iterdir()}
    headless_files = {p.name for p in (headless.xml_path.parent / "Systems").iterdir()}
    assert headless_files - host_files == {"tecs.xml"}
    for name in host_files:
        assert ((host.xml_path.parent / "Systems" / name).read_bytes()
                == (headless.xml_path.parent / "Systems" / name).read_bytes())


def test_the_anchors_are_recorded_and_the_rewrites_land_where_the_blueprint_says(build):
    spec = derive("c172p", build_dir=build, injections=ALL)
    text = spec.xml_path.read_text(encoding="utf-8")
    anchors = {r.name: r.anchors for r in spec.injections}
    assert anchors["failures"] == {"elevator_inputs": 1, "aileron_inputs": 1, "rudder_inputs": 1}
    assert anchors["icing"] == {"lift_functions": 5, "drag_functions": 5, "side_functions": 5,
                                "roll_functions": 5, "pitch_functions": 6, "yaw_functions": 5}
    assert anchors["icing_alpha"] == {"lift_alpha_tables": 1, "lift_alpha_vars": 1}
    assert anchors["gust_rotation"] == {"roll_rate_terms": 1}
    fcs = re.search(r"<flight_control\b.*?</flight_control>", text, re.S).group(0)
    for s in SURFACES:
        assert f"fcs/{s}-cmd-norm" not in fcs
        assert fcs.count(f"<input>failure/{s}/cmd-in</input>") == 1
    for axis, factor in AXIS_FACTORS.items():
        body = re.search(rf'<axis\s+name="{axis}".*?</axis>', text, re.S).group(0)
        assert body.count(f"<property>{factor}</property>") == anchors["icing"][f"{axis.lower()}_functions"]
    lift = re.search(r'<axis\s+name="LIFT".*?</axis>', text, re.S).group(0)
    assert lift.count("icing/alpha-effective-rad</independentVar>") == 1
    assert "aero/alpha-rad</independentVar>" not in lift
    assert text.count('<function name="icing/alpha-effective-rad">') == 1
    roll = re.search(r'<axis\s+name="ROLL".*?</axis>', text, re.S).group(0)
    assert roll.count("<property>gust/p-equivalent-rad_sec</property>") == 1
    systems = re.findall(r'<system file="([^"]+)"/>', text)
    assert systems == ["failures", "icing", "icing_alpha", "gust_rotation"]
    assert text.find('<system file="gust_rotation"/>') < text.find("<flight_control")


def test_every_written_file_is_ascii_well_formed_xml(build):
    """ASCII in anything the engine reads; and an XML comment may not hold
    two hyphens (a real parse failure met while building this)."""
    spec = derive("c172p", build_dir=build, injections=("tecs",) + ALL)
    base = derive("c172p", build_dir=build, injections=("tecs",)).xml_path.read_text(
        encoding="utf-8").splitlines()
    for path in [spec.xml_path] + sorted((spec.xml_path.parent / "Systems").iterdir()):
        data = path.read_bytes()
        ET.fromstring(data)
        # The pre-existing tecs.xml carries non-ASCII in its comments and is
        # not this item's to change; everything this item writes is ASCII.
        if path.name != "tecs.xml" and path != spec.xml_path:
            data.decode("ascii")
    added = [line for line in spec.xml_path.read_text(encoding="utf-8").splitlines()
             if line not in base]
    assert added and "\n".join(added).isascii()
    for template in sorted(module.SYSTEMS_DIR.iterdir()):
        if template.name != "tecs.xml":
            template.read_bytes().decode("ascii")


# -- refusals by name ------------------------------------------------------------------

@pytest.mark.parametrize("aircraft,selection,fragment", [
    ("DHC6", ("failures",), "reads no <input> fcs/elevator-cmd-norm"),   # FCS in a shared system file
    ("p51d", ("icing_alpha",), "0 table(s) with aero/alpha-rad"),          # alpha in degrees
    ("f16", ("failures",), "outside an <input> element"),                   # <test value=...> reads the command
    ("f16", ("icing_alpha",), "5 table(s) with aero/alpha-rad"),            # ambiguous
])
def test_a_missing_or_ambiguous_anchor_is_refused_by_name(build, aircraft, selection, fragment):
    with pytest.raises(DerivationError) as info:
        derive(aircraft, build_dir=build, injections=selection)
    assert info.value.constraint == "derivation.anchor_missing"
    assert fragment in info.value.message
    assert not (build / f"{aircraft}{suffix_for(selection)}").exists()


def test_a_second_roll_rate_term_is_an_ambiguous_anchor(build, tmp_path):
    """Fabricated: a c172p whose ROLL axis reads the roll rate twice."""
    import jsbsim

    stock = Path(jsbsim.get_default_root_dir()) / "aircraft" / "c172p"
    root = tmp_path / "root"
    shutil.copytree(stock, root / "aircraft" / "c172p")
    xml = root / "aircraft" / "c172p" / "c172p.xml"
    text = xml.read_text(encoding="utf-8")
    roll = re.search(r'<axis\s+name="ROLL".*?</axis>', text, re.S).group(0)
    doubled = roll.replace("<property>velocities/p-aero-rad_sec</property>",
                           "<property>velocities/p-aero-rad_sec</property>\n"
                           "                    <property>velocities/p-aero-rad_sec</property>", 1)
    xml.write_text(text.replace(roll, doubled), encoding="utf-8")
    with pytest.raises(DerivationError) as info:
        derive("c172p", build_dir=build / "dup", root_dir=root, injections=("gust_rotation",))
    assert info.value.constraint == "derivation.anchor_missing"
    assert "2 time(s)" in info.value.message


@pytest.mark.parametrize("selection", [("bogus",), ("icing", "icing"), ()])
def test_an_unknown_repeated_or_empty_selection_is_a_conflict(build, selection):
    with pytest.raises(DerivationError) as info:
        derive("c172p", build_dir=build, injections=selection)
    assert info.value.constraint == "derivation.injection_conflict"


def test_deriving_a_derived_airframe_again_is_a_conflict(build):
    """The build root resolves like the stock one, so a derived airframe can
    be named as a base; injecting on top of itself is refused, never merged."""
    first = derive("c172p", build_dir=build, injections=ALL)
    with pytest.raises(DerivationError) as info:
        derive(first.name, build_dir=build / "again", root_dir=build.parent,
               injections=("failures",))
    assert info.value.constraint == "derivation.injection_conflict"
    assert "failure/elevator/" in info.value.message


def test_a_tampered_build_copy_or_a_wrong_expected_hash_is_refused(build):
    spec = derive("c172p", build_dir=build, injections=ALL)
    original = spec.xml_path.read_bytes()
    spec.xml_path.write_bytes(original + b"\n<!-- edited by hand -->\n")
    with pytest.raises(DerivationError) as info:
        verify_hashes(spec)
    assert info.value.constraint == "derivation.hash_mismatch"
    spec.xml_path.write_bytes(original)
    system = spec.xml_path.parent / "Systems" / "icing.xml"
    system_bytes = system.read_bytes()
    system.write_bytes(system_bytes + b"\n")
    with pytest.raises(DerivationError) as info:
        verify_hashes(spec)
    assert info.value.constraint == "derivation.hash_mismatch"
    system.write_bytes(system_bytes)
    assert verify_hashes(spec)[spec.xml_path.name] == spec.derived_sha256
    # The door check: a manifest's hash that this derivation does not have.
    with pytest.raises(DerivationError) as info:
        FlightDynamics.with_injections("c172p", ALL, build_dir=build,
                                       expected_derived_sha256="0" * 64)
    assert info.value.constraint == "derivation.hash_mismatch"
    fdm = FlightDynamics.with_injections("c172p", ALL, build_dir=build,
                                         expected_derived_sha256=spec.derived_sha256)
    assert fdm.derived.derived_sha256 == spec.derived_sha256
    assert fdm.provenance()["aircraft"]["name"] == "c172p-fail-ice-alpha-gust"


# -- neutral values: bit-identical to the stock airframe -------------------------------

@pytest.fixture(scope="module")
def stock_rows():
    return elevator_step_flight(trimmed(FlightDynamics("c172p")))


@pytest.mark.parametrize("selection", [ALL, ("failures",), ("icing",), ("icing_alpha",),
                                       ("gust_rotation",)])
def test_neutral_values_are_bit_identical_to_the_stock_airframe(build, stock_rows, selection):
    """8 s of a trimmed elevator step (-0.3 at 1 s) at 120 Hz, fifteen
    properties per step: worst |derived - stock| 0.0, measured for each
    injection alone and for all four together."""
    fdm = trimmed(FlightDynamics.with_injections("c172p", selection, build_dir=build))
    assert fdm.derived.injection_names == selection
    assert worst_diff(elevator_step_flight(fdm), stock_rows) == 0.0


def test_the_injected_properties_read_back_exactly_before_and_after_stepping(build):
    fdm = trimmed(FlightDynamics.with_injections("c172p", ALL, build_dir=build))
    for name, (_, prop, _, neutral) in INJECTION_VARIABLES.items():
        assert fdm.props.get(prop) == neutral, name
    writes = {"failure/elevator/authority": 0.5, "failure/aileron/authority": 0.7,
              "failure/rudder/authority": 0.9, "icing/lift-factor": 0.8,
              "icing/drag-factor": 1.3, "icing/side-factor": 0.95, "icing/roll-factor": 0.9,
              "icing/pitch-factor": 0.85, "icing/yaw-factor": 1.1, "icing/eta": 0.2,
              "icing/alpha-shift-rad": 0.05, "gust/p-equivalent-rad_sec": 0.3}
    fdm.props.set_many(writes)
    assert {k: fdm.props.get(k) for k in writes} == writes
    for _ in range(3):
        fdm.step()
    assert {k: fdm.props.get(k) for k in writes} == writes


# -- failures: the re-anchored chain and JSBSim's own malfunctions ---------------------

def test_authority_half_holds_half_the_command_over_100_steps_written_once(build):
    """Correction 1 made a test: the host writes -0.3 once; the chain
    reads it and writes -0.15 to failure/elevator/cmd-in on all 100 steps,
    and the elevator sits exactly where the stock airframe puts it for a
    command of -0.15 (0.014953604875 rad)."""
    fdm = trimmed(FlightDynamics.with_injections("c172p", ("failures",), build_dir=build))
    fdm.props.set_many({"failure/elevator/authority": 0.5})
    fdm.set_controls(elevator=-0.3)
    seen = set()
    for _ in range(100):
        fdm.step()
        seen.add((fdm.props.get("failure/elevator/cmd-in"), fdm.props.get("fcs/elevator-cmd-norm")))
    assert seen == {(-0.15, -0.3)}
    stock = trimmed(FlightDynamics("c172p"))
    stock.set_controls(elevator=-0.15)
    stock.step()
    assert stock.props.get("fcs/elevator-pos-rad") == pytest.approx(0.01495360487503992, abs=1e-15)
    assert fdm.props.get("fcs/elevator-pos-rad") == stock.props.get("fcs/elevator-pos-rad")


def test_a_pass_through_actuator_on_the_hosts_property_decays_the_command(build):
    """Why the input is re-anchored (correction 1, re-measured): the
    research's chain reading AND writing fcs/elevator-cmd-norm halves the
    command every step -- -0.15, -0.075, -0.0375 ... 7e-5 by step 12 -- so
    any authority below 1 floats to zero between the host's writes."""
    import jsbsim

    good = derive("c172p", build_dir=build, injections=("failures",))
    loop = build / "c172p-loop"
    shutil.rmtree(loop, ignore_errors=True)
    shutil.copytree(good.xml_path.parent, loop)
    (loop / "c172p-fail.xml").rename(loop / "c172p-loop.xml")
    airframe = loop / "c172p-loop.xml"
    airframe.write_text(airframe.read_text(encoding="utf-8").replace(
        "<input>failure/elevator/cmd-in</input>", "<input>fcs/elevator-cmd-norm</input>"),
        encoding="utf-8")
    chain = loop / "Systems" / "failures.xml"
    chain.write_text(chain.read_text(encoding="utf-8").replace(
        "<output>failure/elevator/cmd-in</output>", "<output>fcs/elevator-cmd-norm</output>"),
        encoding="utf-8")
    root = Path(jsbsim.get_default_root_dir())
    fdm = trimmed(FlightDynamics("c172p-loop", root_dir=build.parent,
                                 engine_path=root / "engine", systems_path=root / "systems"))
    fdm.props.set_many({"failure/elevator/authority": 0.5})
    fdm.set_controls(elevator=-0.3)
    seq = []
    for _ in range(12):
        fdm.step()
        seq.append(fdm.props.get("fcs/elevator-cmd-norm"))
    assert seq[:4] == pytest.approx([-0.15, -0.075, -0.0375, -0.01875], abs=1e-12)
    assert abs(seq[-1]) < 1e-4
    shutil.rmtree(loop)


def test_jsbsim_malfunctions_on_the_injected_actuator_behave_as_named(build):
    """fail_stuck holds the failing step's output (-0.15) whatever the
    command; fail_zero writes 0 (the elevator to its trim-only position
    0.075156 rad); fail_hardover writes the clip limit on the command's
    side (+1 -> 0.40135 rad, the airframe's +23 deg; -1 -> -0.39711 rad)."""
    fdm = trimmed(FlightDynamics.with_injections("c172p", ("failures",), build_dir=build))
    fdm.props.set_many({"failure/elevator/authority": 0.5})
    fdm.set_controls(elevator=-0.3)
    fdm.step()
    assert fdm.props.get("failure/elevator/cmd-in") == -0.15
    fdm.props.set_many({"failure/elevator/actuator/malfunction/fail_stuck": 1.0})
    fdm.set_controls(elevator=0.8)
    for _ in range(6):
        fdm.step()
        assert fdm.props.get("failure/elevator/cmd-in") == -0.15
    assert fdm.props.get("fcs/elevator-pos-rad") == pytest.approx(0.01495360487503992, abs=1e-15)
    fdm.props.set_many({"failure/elevator/actuator/malfunction/fail_stuck": 0.0,
                        "failure/elevator/actuator/malfunction/fail_zero": 1.0})
    fdm.step()
    assert fdm.props.get("failure/elevator/cmd-in") == 0.0
    assert fdm.props.get("fcs/elevator-pos-rad") == pytest.approx(0.07515610487503992, abs=1e-15)
    fdm.props.set_many({"failure/elevator/actuator/malfunction/fail_zero": 0.0,
                        "failure/elevator/actuator/malfunction/fail_hardover": 1.0})
    fdm.step()
    assert fdm.props.get("failure/elevator/cmd-in") == 1.0
    assert fdm.props.get("fcs/elevator-pos-rad") == pytest.approx(0.40135, abs=1e-12)
    fdm.set_controls(elevator=-0.8)
    fdm.step()
    assert fdm.props.get("failure/elevator/cmd-in") == -1.0
    assert fdm.props.get("fcs/elevator-pos-rad") == pytest.approx(-0.39710561145647316, abs=1e-12)


# -- icing: the factors and the stall-onset shift ----------------------------------------

def lift_after_one_step(build, factor: float) -> tuple:
    fdm = trimmed(FlightDynamics.with_injections("c172p", ("icing",), build_dir=build))
    before = fdm.props.get("forces/fwz-aero-lbs")
    fdm.props.set_many({"icing/lift-factor": factor})
    fdm.step()
    return before, fdm.props.get("forces/fwz-aero-lbs")


def test_lift_factor_0_8_drops_the_next_steps_lift_by_exactly_the_factor(build):
    """Trimmed c172p at 1500 m / 100 kt CAS: 1872.5287 lbf on the step
    after a neutral write (the trim moves 2.2e-4 lbf in one step: not an
    exact equilibrium), 1498.0230 lbf on the same step with the factor 0.8
    written first -- 0.8 x the neutral lift to 1e-12 relative, because
    every LIFT function is wrapped and the whole axis scales. The research
    read 2772 -> 2322 lbf at another state; the factor form is the claim,
    not the number."""
    before, neutral = lift_after_one_step(build, 1.0)
    before2, iced = lift_after_one_step(build, 0.8)
    assert before == before2 == pytest.approx(1872.529, abs=5e-3)
    assert neutral == pytest.approx(1872.5287, abs=5e-4)
    assert iced == pytest.approx(1498.0230, abs=5e-4)
    assert iced == pytest.approx(0.8 * neutral, rel=1e-12)


def lift_curve(build, shift_rad: float):
    fdm = FlightDynamics.with_injections("c172p", ("icing_alpha",), build_dir=build)
    sweep = {k: v for k, v in LEVEL.items() if k != "gamma-deg"}
    out = []
    alpha = 8.0
    while alpha <= 22.0 + 1e-9:
        fdm.set_initial_conditions({"h-sl-ft": u.m_to_ft(ALT_M), "vc-kts": CAS_KT,
                                    "alpha-deg": alpha, **sweep}, tolerance=5e-2)
        fdm.props.set_many({"icing/alpha-shift-rad": shift_rad})
        fdm.step()
        cl = (fdm.props.get("forces/fwz-aero-lbs")
              / (fdm.props.get("aero/qbar-psf") * fdm.props.get("metrics/Sw-sqft")))
        out.append((round(alpha, 2), cl))
        alpha += 0.25
    return out


def test_the_alpha_shift_moves_the_alpha_at_which_lift_peaks(build):
    """Static sweep 8..22 deg in 0.25 deg steps at 100 kt CAS: the c172p
    table peaks at 16.25 deg requested (CL 1.4490); with the shift 2 deg
    (0.0349066 rad) the peak sits at 14.25 deg (CL 1.4497): moved -2.0 deg,
    the shift exactly at the sweep's resolution."""
    plain = lift_curve(build, 0.0)
    shifted = lift_curve(build, 0.0349066)
    peak_plain = max(plain, key=lambda r: r[1])
    peak_shifted = max(shifted, key=lambda r: r[1])
    assert peak_plain[0] == 16.25 and peak_plain[1] == pytest.approx(1.44896, abs=1e-4)
    assert peak_shifted[0] == 14.25 and peak_shifted[1] == pytest.approx(1.44966, abs=1e-4)
    assert peak_shifted[0] - peak_plain[0] == pytest.approx(-2.0)


def test_alpha_effective_sees_this_steps_alpha_not_the_previous_one(build):
    """The sum lives in <aerodynamics>, not in a <system>: a system runs
    before FGAuxiliary and would carry the previous step's alpha (measured
    5.3e-4 .. 1.5e-3 rad behind over six steps of an elevator step). Read
    after each step, the effective alpha equals aero/alpha-rad + shift to
    the bit, at shift 0 and at 0.05 rad."""
    for shift in (0.0, 0.05):
        fdm = trimmed(FlightDynamics.with_injections("c172p", ("icing_alpha",), build_dir=build))
        fdm.props.set_many({"icing/alpha-shift-rad": shift})
        fdm.set_controls(elevator=-0.4)
        moved = 0.0
        for _ in range(6):
            alpha_before = fdm.props.get("aero/alpha-rad")
            fdm.step()
            alpha = fdm.props.get("aero/alpha-rad")
            assert fdm.props.get("icing/alpha-effective-rad") == alpha + shift
            moved = max(moved, abs(alpha - alpha_before))
        assert moved > 5e-4   # alpha did move step to step, so a lagged copy would differ


# -- the rotational gust ---------------------------------------------------------------------

def roll_after(build, p_equivalent: float, seconds: float = 2.0) -> float:
    fdm = trimmed(FlightDynamics.with_injections("c172p", ("gust_rotation",), build_dir=build))
    fdm.props.set_many({"gust/p-equivalent-rad_sec": p_equivalent})
    for _ in range(int(seconds * fdm.rate_hz)):
        fdm.step()
    return fdm.props.get("attitude/phi-deg")


def test_p_equivalent_0_3_for_2_s_rolls_the_trimmed_c172p(build):
    """-30.213 deg at 2 s against -3.671 deg with the property at 0 (the
    longitudinal trim leaves a small roll of its own); the research read
    -30.3 vs -2.7 deg at its state."""
    assert roll_after(build, 0.0) == pytest.approx(-3.6706, abs=5e-3)
    assert roll_after(build, 0.3) == pytest.approx(-30.2129, abs=5e-3)


# -- the record every injected property returns ----------------------------------------------

def test_each_driven_effect_is_a_measured_null_test_in_an_applied_variable(build):
    """The AppliedVariable-shaped dicts the later physics items lift: value,
    exact readback, the injection's hashes as the model block, and the
    null test measured above (with against without, threshold stated)."""
    spec = derive("c172p", build_dir=build, injections=ALL)
    fdm = trimmed(FlightDynamics.with_injections("c172p", ALL, build_dir=build))
    fdm.props.set_many({"failure/elevator/authority": 0.5, "icing/lift-factor": 0.8,
                        "icing/alpha-shift-rad": 0.0349066, "gust/p-equivalent-rad_sec": 0.3})
    driven = {
        "failures.elevator_authority": (0.5, NullTest(
            "failure/elevator/cmd-in over 100 steps for a command of -0.3 written once",
            "1", -0.15, -0.3, 0.01, kind="reached",
            note="without = authority 1.0 (the stock chain); held on all 100 steps")),
        "icing.lift_factor": (0.8, NullTest(
            "aerodynamic lift on the step after the write (forces/fwz-aero-lbs)",
            "lbf", 1498.023, 1872.529, 1.0, kind="reached",
            note="trimmed c172p 1500 m / 100 kt CAS; exactly 0.8 x the neutral lift")),
        "icing.alpha_shift_rad": (0.0349066, NullTest(
            "alpha of peak lift in a static 8..22 deg sweep (0.25 deg steps)",
            "deg", 14.25, 16.25, 0.25, kind="reached",
            note="a 2 deg shift moves the peak -2.0 deg, the sweep's resolution")),
        "gust.p_equivalent_rad_s": (0.3, NullTest(
            "roll angle after 2 s from the longitudinal trim", "deg", -30.2129, -3.6706, 0.05,
            kind="reached", note="0.3 rad/s equivalent roll rate summed into the Clp term")),
    }
    records = []
    for name, (value, null) in driven.items():
        _, prop, unit, neutral = INJECTION_VARIABLES[name]
        rec = injection_variable(name, value, spec, fdm.props.get(prop), null,
                                 telemetry_columns={"failures.elevator_authority": ("pitch_deg",),
                                                    "icing.lift_factor": ("lift_n", "altitude_m"),
                                                    "icing.alpha_shift_rad": ("lift_n", "alpha_deg"),
                                                    "gust.p_equivalent_rad_s": ("roll_deg", "roll_rate_dps")}[name],
                                 frm="tests/test_derive_injections.py")
        assert rec.readback is not None and rec.readback.agrees and rec.readback.tolerance == 0.0
        assert rec.null_test is not None and rec.null_test.ok
        assert rec.properties_written == (prop,) and rec.unit == unit
        assert rec.parameters["neutral_value"] == neutral
        assert rec.parameters["derived_sha256"] == spec.derived_sha256
        assert rec.jsbsim_writes[0].property == prop
        assert rec.model_block is not None and rec.model_block.version == rec.parameters["template_sha256"][:12]
        d = rec.to_dict()
        assert {"readback", "jsbsim_writes", "model_block", "from"} <= set(d)
        assert AppliedVariable.from_dict(d).to_dict() == d
        records.append(rec)
    assert [r.name for r in records] == list(driven)
    # Every other injected property carries the record too, at its neutral value.
    for name, (_, prop, _, neutral) in INJECTION_VARIABLES.items():
        rec = injection_variable(name, neutral, spec, neutral, None, source="default")
        assert rec.null_test is None and rec.readback.agrees


def test_a_record_for_an_injection_the_airframe_was_not_derived_with_is_refused(build):
    spec = derive("c172p", build_dir=build, injections=("icing",))
    with pytest.raises(DerivationError) as info:
        injection_variable("gust.p_equivalent_rad_s", 0.3, spec, 0.3, None)
    assert info.value.constraint == "derivation.injection_conflict"
    assert set(INJECTION_VARIABLES) == {
        "failures.elevator_authority", "failures.aileron_authority", "failures.rudder_authority",
        "icing.lift_factor", "icing.drag_factor", "icing.side_factor", "icing.roll_factor",
        "icing.pitch_factor", "icing.yaw_factor", "icing.eta", "icing.alpha_shift_rad",
        "gust.p_equivalent_rad_s"}


def test_the_tecs_derivation_flies_the_failure_chain_in_the_same_step(build):
    """With TECS in the set the controller's elevator output passes through
    the chain: authority 0 on the elevator leaves the controller's command
    unable to reach the surface (cmd-in 0), while the command itself is
    still written."""
    fdm = trimmed(FlightDynamics.with_injections("c172p", ("tecs", "failures"), build_dir=build))
    assert fdm.has_autopilot
    assert fdm.derived.name == "c172p-tecs-fail"
    fdm.props.set_many({"failure/elevator/authority": 0.0})
    fdm.set_controls(elevator=-0.3)
    fdm.step()
    assert fdm.props.get("fcs/elevator-cmd-norm") == -0.3
    assert fdm.props.get("failure/elevator/cmd-in") == 0.0
