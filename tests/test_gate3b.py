"""Gate 3b (P8): the physics layers' null ladder, A8, the three-rate study
and the order core/uncertainty.py reads from it.

The long runs are the scripts' (experiments/gate3b_layers.py,
experiments/gate3b_convergence.py); here two ladder rows are reproduced
from 1 s flights, A8 from three latched initial conditions, and the rest
from fakes: the row status logic (a FAIL cannot read PASS), the manifests'
shape and output digest, the study file's contract and the u_num read.
"""
from __future__ import annotations

import contextlib
import io
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from core.experiments.manifest import sha256_file
from core.registry import REGISTRY
from core.uncertainty import (
    CONVERGENCE_STUDY_PATH, FORMAL_ORDER, SRQS, study_observed_p, u_num_twin,
)
from experiments import gate3b_convergence as conv
from experiments import gate3b_layers as ladder

REPO = Path(__file__).resolve().parents[1]


# -- the row status ---------------------------------------------------------------------

@pytest.mark.parametrize("criterion, verdict, expected, differ, not_run, status", [
    (True, "reached", "reached", True, None, "PASS"),
    (False, "reached", "reached", True, None, "FAIL"),          # the criterion missed
    (True, "silent", "reached", True, None, "FAIL"),            # met, but the layer never reached
    (True, "reached", "reached", False, None, "FAIL"),          # reached with equal digests
    (True, "ungraded", "reached", True, None, "FAIL"),
    (True, "silent", "silent", True, None, "PASS"),             # a control
    (True, "reached", "silent", True, None, "FAIL"),            # a control that moved
    (None, "reached", "reached", True, None, "NOT RUN"),        # could not be graded
    (True, "reached", "reached", True, "refused wake.generator", "NOT RUN"),
])
def test_a_row_passes_only_when_its_criterion_verdict_and_digests_all_agree(
        criterion, verdict, expected, differ, not_run, status):
    assert ladder.row_status(criterion, verdict, expected, differ, not_run) == status


def test_every_rung_names_a_registered_spec_field_and_a_stated_criterion():
    keys = [r.key for r in ladder.RUNGS]
    assert len(keys) == len(set(keys))
    assert set(keys) == {"delta_t", "humidity", "vk_vs_none", "vk_vs_dryden", "wake",
                         "wake_far_control", "icing", "loading", "engine_out", "jam", "layered"}
    for r in ladder.RUNGS:
        entry = REGISTRY.get(r.variable)
        assert entry.spec_path is not None, r.key
        assert r.criterion and r.expected_verdict in ("reached", "silent")
    rows = {row for r in ladder.RUNGS for row in r.rows}
    assert {"A7", "A9", "V13", "V15", "V16", "V17", "V19", "V20"} <= rows
    assert ladder.rung("wake_far_control").expected_verdict == "silent"


class _Refusal(Exception):
    constraint = "wake.generator"


def test_a_refused_rung_is_not_run_with_the_refusal_named():
    def refusing(spec):
        raise _Refusal("not a configured airframe")
    row = ladder.run_rung(ladder.rung("wake"), seconds=1.0, runner=refusing)
    assert row["status"] == "NOT RUN" and "wake.generator" in row["reason"]


# -- two rows from short runs -------------------------------------------------------------

@pytest.fixture(scope="module")
def humidity_row():
    return ladder.run_rung(ladder.rung("humidity"), seconds=1.0)


def test_the_humidity_row_reproduces_a7_from_a_one_second_pair(humidity_row):
    """A7: JSBSim's humid / dry density ratio at the same P and T against
    1 - 0.378 e / p: measured 0.99603420 against 0.99603417 at 1500 m
    (E 2.9e-8, u_D 4.0e-6 from A&E 1996's 0.1 % in e_s), within 0.05 %."""
    row = humidity_row
    assert row["status"] == "PASS" and row["verdict"] == "reached" and row["digests"]["differ"]
    m = row["measured"]
    assert m["S_density_ratio"] == pytest.approx(0.9960342, abs=2e-7)
    assert abs(m["vv20"]["E"]) < m["vv20"]["u_D"] and m["vv20"]["validated_at_u_val"]
    assert m["vv20"]["relative_E"] <= ladder.HUMIDITY_RATIO_TOLERANCE
    assert row["effect"]["rh_pct"]["reached"] and row["effect"]["vapour_pressure_pa"]["reached"]


def test_the_delta_t_row_reproduces_and_measures_the_cas_the_stated_day_flies():
    """TAS / CAS within 0.5 % of 1 / sqrt(sigma) in both runs (0.050 % and
    0.056 % measured). The stated day flies the CAS asked (100.0 kt both
    runs, to 1e-9: the requested airspeed is re-stated before the pre-trim
    re-latch, core/fdm/fdm.py) and so a higher TRUE airspeed (112.214 kt at
    +30 degC against 107.537 kt, +4.676 kt). Before that fix the re-latch
    kept the IC's TAS and the stated day flew 95.83 kt CAS; VV_REPORT's
    ladder row and VALIDITY 2.27 say so."""
    row = ladder.run_rung(ladder.rung("delta_t"), seconds=1.0)
    assert row["status"] == "PASS" and row["criterion_ok"] is True
    m = row["measured"]
    for side in ("with", "without"):
        assert m[side]["relative_error"] <= ladder.TAS_CAS_TOLERANCE
        assert m[side]["cas_kt"] == pytest.approx(100.0, abs=1e-6)
    assert abs(m["cas_difference_kt"]) < 1e-9
    assert m["tas_difference_kt"] == pytest.approx(4.676, abs=0.01)


# -- A8 -----------------------------------------------------------------------------------

def test_a8_the_standard_day_matches_the_1976_table_and_the_table_its_equations():
    for z, table in ladder.USSA_1976.items():
        defining = ladder.ussa1976_defining(z)
        for i in range(3):
            assert abs(defining[i] - table[i]) <= 1.0001 * ladder.USSA_1976_HALF_DIGIT[z][i], (z, i)
    row = ladder.a8_row()
    assert row["status"] == "PASS" and row["transcription_ok"]
    worst = max(r[q]["relative_E"] for r in row["measured"]
                for q in ("temperature_k", "pressure_pa", "density_kgm3"))
    assert worst < 2e-5                                  # measured 1.2e-5 (3000 m density)
    sea = row["measured"][0]["pressure_pa"]
    assert sea["E"] == pytest.approx(0.5447, abs=1e-3)    # JSBSim's 2116.228 psf is 101325.54 Pa
    assert sea["validated_at_u_val"] is False


def test_a8_fails_on_a_standard_day_off_by_more_than_the_tolerance():
    def warm(z):
        t, p, rho = ladder.ussa1976_defining(z)
        return t * 1.002, p, rho
    assert ladder.a8_row(standard_day=warm)["status"] == "FAIL"


# -- the manifests ------------------------------------------------------------------------

def _fake_result() -> Dict[str, Any]:
    rows = [{**r.definition(), "status": "PASS"} for r in ladder.RUNGS]
    return {"experiment": ladder.EXPERIMENT, "seconds": 1.0, "rows": rows,
            "counts": {"PASS": len(rows), "FAIL": 0, "NOT RUN": 0}, "gate": "PASS"}


def test_the_ladder_manifest_has_the_experiments_form_and_pins_the_ladder_digest(tmp_path):
    ladder_path, manifest_path = ladder.write(_fake_result(), tmp_path, 1.0)
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(m) == {"manifest_version", "name", "git", "host", "parameters", "seeds",
                      "components", "inputs", "outputs", "reproducibility", "notes"}
    assert m["name"] == "gate3b-layers" and m["manifest_version"] == 1
    assert m["outputs"] == {"ladder": sha256_file(ladder_path)}
    assert set(m["inputs"]) == {f"spec:{r.key}" for r in ladder.RUNGS}
    assert [r["key"] for r in m["parameters"]["rungs"]] == [r.key for r in ladder.RUNGS]
    assert set(m["seeds"]["per_rung"]) == {r.key for r in ladder.RUNGS}
    assert m["parameters"]["tolerances"]["sigma_w"] == 0.10
    assert m["parameters"]["tolerances"]["humidity_ratio"] == 0.0005


def test_the_convergence_manifest_names_its_study_by_digest(tmp_path):
    study = tmp_path / "study.json"
    doc = conv.study_document(_study(), _manifest(), 10.0)
    conv.write_study(doc, study)
    m = conv.build_manifest(doc, study).to_dict()
    assert m["name"] == "gate3b-convergence" and m["outputs"] == {"study": sha256_file(study)}
    assert m["inputs"] == {"spec": sha256_file(conv.EXAMPLE)}
    assert m["parameters"]["rates_hz"] == [60.0, 120.0, 240.0]


# -- the study and the u_num read -------------------------------------------------------------

def _manifest(sha="a" * 64, version="1.2.4 test") -> Dict[str, Any]:
    return {"fdm": {"aircraft": {"name": "c172p", "sha256": sha}, "jsbsim_version": version}}


def _study() -> Dict[str, Any]:
    orders = {"altitude_m": 1.18, "tas_kt": 0.5, "roll_deg": -0.09}
    return {"observed_p": orders, "rates_hz": [60.0, 120.0, 240.0], "digests": ["a", "b", "c"],
            "detail": {s: ({"e_coarse_mid": 0.2, "e_mid_fine": 0.1, "p": orders[s]}
                           if s in orders else {"basis": "NOT RUN", "p": None}) for s in SRQS}}


@dataclass
class _Fake:
    spec_digest: str
    output_digest: str
    telemetry: Any
    manifest: Dict[str, Any] = field(default_factory=dict)


def _runner(manifest, t0_by_rate=None):
    """Altitude 1000 + 0.2 (120 / rate - 1) + the elapsed time: the dt run
    and the dt/2 twin differ by exactly 0.1 m. Each rate's clock starts
    where ``t0_by_rate`` says (a crank of rate-dependent length)."""
    def run(spec):
        rate = float(spec.rate.value)
        t0 = (t0_by_rate or {}).get(rate, 0.0)
        t = [t0 + 0.1 * i for i in range(11)]
        alt = [1000.0 + 0.2 * (120.0 / rate - 1.0) + (ti - t0) for ti in t]
        cols = {"t": t, "altitude_m": alt, "tas_kt": [100.0] * 11, "pitch_deg": [1.0] * 11,
                "roll_deg": [0.0] * 11, "heading_deg": [0.0] * 11,
                "lat_deg": [0.0] * 11, "lon_deg": [0.0] * 11}
        return _Fake(f"s{rate:g}", f"o{rate:g}", SimpleNamespace(columns=cols), manifest)
    return run


def _spec(rate=120.0):
    from core.scenario.spec import ScenarioSpec

    spec = ScenarioSpec.read(REPO / "examples" / "cameras_waypoint.yaml")
    spec.set("duration", 1.0)
    spec.set("rate", rate)
    return spec


def test_u_num_reads_the_study_capped_at_the_formal_order_only_for_its_own_case(tmp_path):
    path = conv.write_study(conv.study_document(_study(), _manifest(), 10.0), tmp_path / "s.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["observed_p"] == {"altitude_m": 1.18, "tas_kt": 0.5}           # the negative order dropped
    assert doc["srqs"]["roll_deg"]["used_by_u_num"] is None
    assert path.read_bytes().decode("ascii")                                   # ASCII, committed form

    block = u_num_twin(_spec(), runner=_runner(_manifest()), study_path=path)
    alt = block["srq"]["altitude_m"]
    assert alt["p"] == FORMAL_ORDER and alt["fs"] == 1.25                     # 1.18 capped at 1
    assert alt["value"] == pytest.approx(1.25 * 0.1 / (2 ** 1 - 1))
    assert "s.json" in alt["basis"] and "capped" in alt["basis"]
    assert block["srq"]["roll_deg"]["p"] == 1.0 and block["srq"]["roll_deg"]["fs"] == 3.0
    assert block["srq"]["tas_kt"]["p"] == 0.5
    assert block["order_source"]["sha256"] == sha256_file(path)

    for runner, spec in ((_runner(_manifest(sha="b" * 64)), _spec()),        # another airframe file
                         (_runner(_manifest(version="other")), _spec()),     # another JSBSim
                         (_runner(_manifest()), _spec(rate=240.0)),          # outside the range
                         (_runner({}), _spec())):                           # no manifest (a fake)
        other = u_num_twin(spec, runner=runner, study_path=path)
        assert other["srq"]["altitude_m"]["p"] == 1.0 and other["srq"]["altitude_m"]["fs"] == 3.0
        assert other["order_source"] == "assumed"
    absent = u_num_twin(_spec(), runner=_runner(_manifest()), study_path=tmp_path / "none.json")
    assert absent["order_source"] == "assumed"
    given = u_num_twin(_spec(), runner=_runner(_manifest()), study_path=path,
                       observed_p={"altitude_m": 2.0})
    assert given["srq"]["altitude_m"]["p"] == 2.0 and given["order_source"] == "given"


def test_the_twin_difference_is_taken_on_each_run_s_own_clock():
    """A crank of rate-dependent length starts JSBSim's clock at another
    time per rate (4.933 / 4.900 / 4.879 s at 60 / 120 / 240 Hz on the
    c172p); compared on the raw clock the altitude difference was the
    phase shift (0.048 m against 0.0019 m on the elapsed time)."""
    block = u_num_twin(_spec(), runner=_runner({}, {120.0: 4.900, 240.0: 4.879}))
    assert block["srq"]["altitude_m"]["difference"] == pytest.approx(0.1, abs=1e-9)


def test_the_committed_study_is_the_committed_examples_and_applies_to_its_c172p():
    doc = json.loads(CONVERGENCE_STUDY_PATH.read_text(encoding="utf-8"))
    assert doc["kind"] == "three_rate_study" and doc["study_version"] == 1
    assert doc["applies_to"]["aircraft"] == "c172p"
    assert doc["applies_to"]["rates_hz"] == [60.0, 120.0, 240.0]
    assert doc["scenario"]["spec"] == "examples/cameras_waypoint.yaml"
    assert doc["formal_order"] == FORMAL_ORDER
    assert all(p > 0 and math.isfinite(p) for p in doc["observed_p"].values())
    assert set(doc["srqs"]) == set(SRQS)
    fake = SimpleNamespace(manifest={"fdm": {"aircraft": {"sha256": doc["applies_to"]["aircraft_sha256"]},
                                             "jsbsim_version": doc["applies_to"]["jsbsim_version"]}})
    found = study_observed_p(fake, _spec())
    assert found is not None and all(p <= FORMAL_ORDER for p in found["observed_p"].values())
