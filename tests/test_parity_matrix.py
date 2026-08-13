"""The host-parity matrix, and the three ways it could report a lie.

A matrix is a claim about coverage, and coverage claims fail quietly:

* it can compare two hosts flying *different aircraft files*, and attribute the
  difference to the integration;
* it can run nine copies of one condition because the prompts did not compile
  to what the case names say;
* it can drop the conditions it could not run and report the rest as the whole.

Each has a guard, and each guard has a test here.
"""

import io
import contextlib

import pytest

from experiments.host_parity_matrix import (
    Case, CaseResult, DEFAULT_AIRCRAFT, DEFAULT_POINTS, model_files_match,
    report, spec_for,
)


def case(aircraft="B747", altitude=3000.0, airspeed=250.0):
    return Case(aircraft, altitude, airspeed, 60.0)


# -- the two hosts must load the same model ------------------------------


@pytest.mark.parametrize("aircraft", DEFAULT_AIRCRAFT)
def test_both_hosts_stage_identical_model_xml(aircraft):
    """The precondition the whole matrix rests on.

    ``scripts/ue_preflight.sh`` checks that both hosts run the same JSBSim
    library. Nothing checks that they load the same *aircraft*, and the plugin
    stages its own copy of the data.
    """
    ok, detail = model_files_match(aircraft)
    assert ok, detail


def test_an_airframe_the_plugin_has_not_staged_is_refused():
    ok, detail = model_files_match("no-such-airframe")
    assert not ok
    assert "no-such-airframe" in detail


def staged_pair(tmp_path, wheel_text, staged_text):
    wheel = tmp_path / "wheel" / "T1"
    staged = tmp_path / "staged" / "T1"
    wheel.mkdir(parents=True)
    staged.mkdir(parents=True)
    (wheel / "T1.xml").write_text(wheel_text, encoding="utf-8")
    (staged / "T1.xml").write_text(staged_text, encoding="utf-8")
    return tmp_path / "wheel", tmp_path / "staged"


def test_two_revisions_of_the_same_aircraft_are_caught(tmp_path):
    """The failure the real files cannot demonstrate, because they agree.

    A plugin staged from a different revision would fly a different aeroplane
    in one host, and the difference would be reported as an integration
    divergence.
    """
    wheel, staged = staged_pair(tmp_path, "<fdm_config a='1'/>",
                                "<fdm_config a='2'/>")
    ok, detail = model_files_match("T1", wheel, staged)
    assert not ok
    assert "T1.xml differs" in detail


def test_identical_files_are_accepted(tmp_path):
    wheel, staged = staged_pair(tmp_path, "<fdm_config/>", "<fdm_config/>")
    ok, detail = model_files_match("T1", wheel, staged)
    assert ok, detail


def test_a_model_file_the_plugin_never_staged_is_caught(tmp_path):
    wheel, staged = staged_pair(tmp_path, "<fdm_config/>", "<fdm_config/>")
    (wheel / "T1" / "extra.xml").write_text("<system/>", encoding="utf-8")
    ok, detail = model_files_match("T1", wheel, staged)
    assert not ok
    assert "extra.xml missing from the plugin" in detail


# -- the case must be the case it says it is -----------------------------


def test_the_prompt_must_compile_to_the_condition_the_case_names():
    """A prompt that resolves to a different airframe would be a silent duplicate.

    "global 5000" with a space is what a person writes; the compiler resolves
    it to ``global5000``. Harmless in a prompt, and not harmless in a matrix
    that labels the row by what it asked for rather than by what it ran.
    """
    with pytest.raises(ValueError, match="compiled to"):
        spec_for(case(aircraft="global 5000"))


def test_a_well_formed_case_compiles_to_itself():
    spec = spec_for(case())
    assert str(spec.aircraft.value) == "B747"
    assert float(spec.altitude.value) == 3000.0
    assert float(spec.airspeed.value) == 250.0
    # And it inherits Gate 5's treatment: open loop, mass held.
    assert spec.hold_state.value is False
    assert spec.mass_held.value is True


# -- coverage is reported, not implied -----------------------------------


def agreeing(name):
    return CaseResult(case(aircraft=name), True, "",
                      {"altitude_m": 0.001, "tas_kt": 0.0001, "roll_deg": 0.0,
                       "pitch_deg": 0.0, "heading_deg": 0.0, "n_z": 0.0},
                      overlap_fraction=0.999)


def rendered(results):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        verdict = report(results)
    return verdict, buffer.getvalue()


def test_a_refused_condition_is_named_and_not_counted_as_agreement():
    refused = CaseResult(case(aircraft="737", altitude=10000.0, airspeed=240.0),
                         True, "refused by the validator: [airspeed.stall_margin]",
                         {}, refused=True)
    verdict, text = rendered([agreeing("B747"), refused])

    assert verdict is True                       # nothing that ran disagreed
    assert "ran in both hosts:                   1 of 2" in text
    assert "agree within the Gate 5 tolerances:  1 of 1" in text
    assert "never compared, refused by the spec layer: 1 of 2" in text
    assert "737 10000m 240kt" in text


def test_a_matrix_where_nothing_ran_is_not_a_pass():
    """Twelve refusals and no comparisons is zero evidence, not a clean sweep."""
    refused = [CaseResult(case(), True, "refused", {}, refused=True)
               for _ in range(3)]
    verdict, text = rendered(refused)
    assert verdict is False
    assert "ran in both hosts:                   0 of 3" in text


def test_one_disagreeing_condition_fails_the_matrix():
    bad = CaseResult(case(aircraft="737"), False, "outside tolerance: altitude_m",
                     {"altitude_m": 40.0, "tas_kt": 0.0, "roll_deg": 0.0,
                      "pitch_deg": 0.0, "heading_deg": 0.0, "n_z": 0.0})
    verdict, text = rendered([agreeing("B747"), bad])
    assert verdict is False
    assert "outside tolerance" in text


def test_the_matrix_covers_every_airframe_at_altitude():
    """The reason for the fourth point.

    The spec layer refuses 10000 m / 240 kt for two of the three airframes, so
    without another high point the top of the envelope would be covered by one
    airframe and the matrix would still say "all conditions agree".
    """
    high = [altitude for altitude, _ in DEFAULT_POINTS if altitude >= 8000.0]
    assert len(high) >= 2, "no high-altitude point survives the validator"
