"""scripts/stress_ladder.ps1 + scripts/stress_ladder.py and the measured budget.

Synthetic round folders, logs and typeperf CSVs: a check of the parsing and
the verdict rules on this machine, never a measurement. The ps1 is pinned by
reading it (no PowerShell here), like the repo's other ps1 tests.
"""

import json
import re
import sys
from pathlib import Path

import pytest

from core.render.hardware_budget import apply_measurement, budget, budget_from_file

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import stress_ladder as sl  # noqa: E402

LADDER_PS1 = (REPO / "scripts" / "stress_ladder.ps1").read_text(encoding="utf-8")
ROUND_PS1 = (REPO / "scripts" / "visual_fix_round.ps1").read_text(encoding="utf-8")
COMMANDLET = (REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge" / "Private"
              / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")

CSV = '''"(PDH-CSV 4.0) (Eastern Standard Time)(300)","\\\\BOX\\GPU Adapter Memory(luid_0x1_phys_0)\\Dedicated Usage","\\\\BOX\\GPU Adapter Memory(luid_0x2_phys_0)\\Dedicated Usage"
"11/13/2026 10:00:00.000","104857600","0"
"11/13/2026 10:00:01.000","209715200","104857600"
"11/13/2026 10:00:02.000"," ","0"
'''


def _round(tmp, n=9001, outcome="done", why=None, log="", run_id="r1", tier=0):
    rd = tmp / f"round_{n}"
    rd.mkdir(parents=True)
    (rd / "ROUND.json").write_text(json.dumps({
        "round": n, "commit": "abcd1234", "switches": f"-FlightSimStressTier={tier} -DPCVars=r.X=1",
        "seconds": {"scenes": 200.0},
        "outcomes": {"number": 11, "outcome": outcome, "seconds": 180.5, "why": why}}), encoding="utf-8-sig")
    (rd / "summary.json").write_text(json.dumps([{"number": 11, "outcome": outcome, "why": why,
                                                  "run_id": run_id}]), encoding="utf-8")
    run = tmp / "webapp" / run_id / "frames" / "chase"
    run.mkdir(parents=True, exist_ok=True)
    (run / "render.log").write_text(
        f"LogInit: Command Line: -run=FlightSimRender -FlightSimStressTier={tier} -quality=beauty\n"
        "LogFlightSimRender: Display: gpu drain: beauty warm-up 1 finished on the GPU in 0.85 s\n"
        "LogFlightSimRender: Display: gpu drain: beauty frame 0 finished on the GPU in 1.40 s\n"
        "LogFlightSimRender: Display: D3D11 device not removed (GetDeviceRemovedReason S_OK)\n" + log,
        encoding="utf-8")
    return rd


def test_typeperf_csv_sums_instances_and_skips_missed_samples(tmp_path):
    (tmp_path / "t.csv").write_text(CSV, encoding="utf-8")
    got = sl.parse_typeperf(tmp_path / "t.csv")
    assert got["dedicated usage"] == [104857600.0, 314572800.0, 0.0]
    (tmp_path / "u.csv").write_bytes(CSV.encode("utf-16"))          # a UTF-16 file reads the same
    assert sl.parse_typeperf(tmp_path / "u.csv") == got
    m = sl.sampler_metrics([tmp_path / "t.csv", tmp_path / "missing.csv"])
    assert m["gpu_dedicated_mb_peak"] == 300.0 and m["gpu_shared_mb_peak"] is None


def test_a_clean_run_survives_and_reports_its_numbers(tmp_path):
    rd = _round(tmp_path)
    (tmp_path / "t.csv").write_text(CSV, encoding="utf-8")
    v = sl.judge(0, 1, rd, tmp_path / "webapp", [tmp_path / "t.csv"], 0)
    assert v["survived"] is True, v["reasons"]
    assert v["metrics"]["device_lost_lines"] == 0          # "not removed" is not a loss
    assert v["metrics"]["gpu_drain_s_max"] == 1.4 and v["metrics"]["gpu_drains"] == 2
    assert v["metrics"]["scene_seconds"] == 180.5 and v["metrics"]["gpu_dedicated_mb_peak"] == 300.0


@pytest.mark.parametrize("line, reason", [
    ("LogD3D11RHI: Error: Result failed DXGI_ERROR_DEVICE_HUNG\n", "device_lost:1"),
    ("LogFlightSimRender: Error: render.gpu_lost: the D3D11 device was removed while ...\n", "device_lost:1"),
    ("Unreal Engine is exiting due to D3D device being lost.\n", "device_lost:1"),
    ("LogFlightSimRender: Error: render.capture_timeout: no capture stage finished in 300 s\n",
     "capture_watchdog:exit_4"),
    ("[flightsim] render.stalled: nothing written for 600 s; process tree killed\n", "render_stalled"),
    ("LogRHI: Error: Out of video memory trying to allocate a rendering resource\n", "out_of_memory:1"),
])
def test_device_loss_the_watchdog_and_a_stall_are_named(tmp_path, line, reason):
    rd = _round(tmp_path, log=line)
    v = sl.judge(0, 1, rd, tmp_path / "webapp", [], 0)
    assert v["survived"] is False and reason in v["reasons"]


def test_exit_codes_outcomes_and_a_missing_marker_fail_the_run(tmp_path):
    rd = _round(tmp_path, outcome="failed", why="[render.gpu_lost] gone")
    v = sl.judge(0, 1, rd, tmp_path / "webapp", [], 3)
    assert "round_exit:3 (refused by name)" in v["reasons"]
    assert "scene_outcome:failed" in v["reasons"] and "device_lost:1" in v["reasons"]
    rd = _round(tmp_path / "b", tier=0)
    v = sl.judge(1, 1, rd, tmp_path / "b" / "webapp", [], 0)       # tier 1 asked, log says 0
    assert v["reasons"] == ["tier_not_applied:logs_have_[0]"]
    empty = tmp_path / "c" / "round_9001"
    empty.mkdir(parents=True)                                     # the round refused before writing
    v = sl.judge(0, 1, empty, tmp_path / "c", [], 3)
    assert {"no_round_json", "scene_outcome:none", "no_render_log"} <= set(v["reasons"])


def _verdict(tier, run, ok=True, peak=400.0):
    return {"tier": tier, "run": run, "survived": ok, "reasons": [] if ok else ["device_lost:1"],
            "switches": f"-FlightSimStressTier={tier}", "commit": "abcd1234", "round": 9000 + 10 * tier + run,
            "metrics": {"device_lost_lines": 0 if ok else 1, "gpu_memory_mb_peak": peak + run,
                        "available_ram_mb_min": 2000.0 - run, "gpu_drain_s_max": 1.0 + run,
                        "scene_seconds": 100.0 + run}}


def test_tier0_needs_every_run_and_measured_follows_it():
    held = sl.summarise([_verdict(0, r) for r in (1, 2, 3)], 3, gpu="Intel")
    assert held["measured"] is True and held["sustained_tier"] == 0
    assert held["gpu_memory_mb_peak"] == 403.0 and held["available_ram_mb_min"] == 1997.0
    short = sl.summarise([_verdict(0, r) for r in (1, 2)], 3)
    assert short["measured"] is False and short["refused"] == "stress_ladder.tier0_not_sustained"
    lost = sl.summarise([_verdict(0, 1), _verdict(0, 2, ok=False)], 3)
    assert lost["measured"] is False and lost["device_lost_total"] == 1
    climbed = sl.summarise([_verdict(0, r) for r in (1, 2, 3)] + [_verdict(1, 1), _verdict(1, 2, ok=False)], 3)
    assert climbed["sustained_tier"] == 0


def test_the_measurement_flips_hardware_budgets_measured_flag(tmp_path):
    profile = {"cpu": {"logical_cores": 8}, "ram": {"total_gb": 16},
               "gpus": [{"vendor": "intel", "name": "Intel UHD", "integrated": True}]}
    start = budget(profile)
    assert start["measured"] is False
    held = sl.summarise([_verdict(0, r) for r in (1, 2, 3)], 3, gpu="Intel UHD")
    got = apply_measurement(start, held)
    assert got["measured"] is True and got["measurement"]["sustained_tier"] == 0
    assert got["usable_vram_mb"] == start["usable_vram_mb"]     # observed, not chosen
    assert apply_measurement(start, {**held, "gpu": "Other"})["measured"] is False
    refused = apply_measurement(start, sl.summarise([], 3))
    assert refused["measured"] is False and refused["measurement"]["refused"] == "stress_ladder.tier0_not_sustained"
    (tmp_path / "p.json").write_text(json.dumps(profile), encoding="utf-8")
    (tmp_path / "m.json").write_text(json.dumps(held), encoding="utf-8")
    assert budget_from_file(tmp_path / "p.json", tmp_path / "m.json")["measured"] is True
    assert budget_from_file(tmp_path / "p.json", tmp_path / "none.json")["measured"] is False


def test_the_cli_writes_verdicts_and_the_budget(tmp_path):
    rd = _round(tmp_path)
    out = tmp_path / "ladder"
    for run in (1, 2, 3):
        assert sl.main(["judge", "--tier", "0", "--run", str(run), "--round-dir", str(rd),
                        "--run-root", str(tmp_path / "webapp"), "--exit-code", "0",
                        "--out", str(out / f"tier0_run{run}.json")]) == 0
    target = tmp_path / "budget_measured.json"
    assert sl.main(["summarise", "--dir", str(out), "--profile", str(tmp_path / "none.json"),
                    "--out", str(target)]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["measured"] is True
    assert (out / "budget.json").is_file()


# --- the ps1, read as text --------------------------------------------------

def _tiers():
    cvars = dict(re.findall(r'^\$(cv\d) = "([^"]+)"', LADDER_PS1, re.M))
    tiers = re.findall(r'^\s+"(-FlightSimStressTier=\d -DPCVars=\$cv\d)",?$', LADDER_PS1, re.M)
    return [t.replace(f"${k}", v) for t in tiers for k, v in cvars.items() if f"${k}" in t]


def test_tier0_is_the_default_and_higher_tiers_are_opt_in():
    assert re.search(r"\[ValidateRange\(0, 3\)\]\[int\]\$MaxTier = 0", LADDER_PS1)
    assert re.search(r"\[int\]\$Runs = 3", LADDER_PS1) and re.search(r"\[int\]\$Scene = 11", LADDER_PS1)
    assert "for ($tier = 0; $tier -le $MaxTier; $tier++)" in LADDER_PS1
    assert "break ladder" in LADDER_PS1        # stops at the first run that did not survive


def test_each_tier_is_a_switches_string_not_a_side_file():
    tiers = _tiers()
    assert len(tiers) == 4
    for n, t in enumerate(tiers):
        assert t.startswith(f"-FlightSimStressTier={n} -DPCVars=r.") and " " not in t.split(" ", 1)[1]
    assert "active_tier" not in LADDER_PS1 and "active_tier" not in ROUND_PS1


def test_no_tier_switch_collides_with_a_commandlet_value_key():
    """FParse::Value finds its key anywhere in the line and switches sit AHEAD
    of the planned flags: r.SSR.Quality=0 would read as -quality=0."""
    keys = set(re.findall(r'FParse::Value\([^,]+,\s*TEXT\("([^"]+=)"\)', COMMANDLET))
    assert "quality=" in keys and len(keys) > 30
    for tier in _tiers():
        low = tier.lower()
        hits = [k for k in keys if k.lower() in low]
        assert not hits, (tier[:40], hits)


def test_the_ladder_drives_the_round_script_with_the_pinned_regex_compile():
    call = next(ln for ln in LADDER_PS1.splitlines() if ln.strip().startswith("& $round "))
    for word in ('-Scenes "$Scene"', "-Switches $switches", "-Compiler regex", "-SpecDir $specs",
                 "-Port $Port", "-NoPush", "-Prep $thisPrep", "-Round $n"):
        assert word in call, word
    assert 'runs\\stress_ladder\\specs' in LADDER_PS1
    for param in ("$Compiler", "$SpecDir", "$Switches", "$NoPush", "$Port"):
        assert param in ROUND_PS1


def test_the_ladder_samples_typeperf_and_refuses_a_busy_port():
    for counter in ("GPU Adapter Memory(*)\\Dedicated Usage", "GPU Adapter Memory(*)\\Shared Usage",
                    "Memory\\Available MBytes"):
        assert counter in LADDER_PS1
    assert 'Start-Process -FilePath "typeperf"' in LADDER_PS1 and '"-si", "1"' in LADDER_PS1
    assert "Stop-Process -Id $s.Id -Force" in LADDER_PS1
    assert re.search(r"\[int\]\$Port = 8018", LADDER_PS1)
    assert 'Refuse "ladder.port_busy"' in LADDER_PS1
    assert '"judge"' in LADDER_PS1 and "summarise --dir $work" in LADDER_PS1


def test_the_device_loss_rules_name_the_commandlets_own_lines():
    assert 'TEXT("render.gpu_lost' in COMMANDLET and 'TEXT("render.capture_timeout' in COMMANDLET
    assert "::TerminateProcess(::GetCurrentProcess(), 4);" in COMMANDLET
    assert 'TEXT("gpu drain: %s finished on the GPU in %.2f s")' in COMMANDLET


def test_the_ps1_is_ascii_for_windows_powershell_5_1():
    LADDER_PS1.encode("ascii")
