"""Code-level checks for swarm lane validation.pixel_metrics.alpine.

Runs on the Mac: metric arithmetic on synthetic frames, the AST argument
reader, the committed manifest against the lane scripts on disk, argv
assembly and status mapping with a stubbed subprocess. None of this is a
rendered or visual result; no lane gate is executed here.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm/lanes/validation/pixel_metrics/alpine"
sys.path.insert(0, str(LANE))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, LANE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


am = _load("alpine_metrics")
bgm = _load("build_gate_manifest")
run = _load("run_alpine_gates")
FRAMES = bgm.calib_frames()


def test_each_calibration_frame_trips_only_its_own_check():
    want = {"neutral": [], "black": ["blank"], "clipped": ["snow_clip"],
            "blue_snow": ["snow_chroma"], "crushed": ["crushed"]}
    for name, fails in want.items():
        assert am.health_failures(am.frame_health(FRAMES[name])) == fails, name


def test_known_fractions():
    assert am.frame_health(FRAMES["clipped"])["snow_clip"] == pytest.approx(0.10)
    assert am.frame_health(FRAMES["crushed"])["crushed"] == pytest.approx(0.25)


def test_compare_same_frame_passes_and_degradations_fail():
    ref = FRAMES["neutral"]
    same = am.compare(ref, ref)
    assert same["pass"] and same["ssim"] == pytest.approx(1.0) and same["detail_ratio"] == pytest.approx(1.0)
    blurred = ((ref.astype(float) + np.roll(ref, 1, 1) + np.roll(ref, -1, 1)
                + np.roll(ref, 1, 0) + np.roll(ref, -1, 0)) / 5).astype(np.uint8)
    assert "detail_ratio" in am.compare(blurred, ref)["failures"]
    assert "penalty" in am.compare(FRAMES["clipped"], ref)["failures"]
    assert am.compare(FRAMES["black"], ref)["failures"] == ["blank"]
    other = np.random.default_rng(1).integers(30, 220, ref.shape).astype(np.uint8)
    assert "ssim" in am.compare(other, ref)["failures"]
    assert "shape_mismatch" in am.compare(ref[:, :80], ref)["failures"]


def test_sequence_flags_blank_frame_and_flicker():
    h = am.frame_health
    steady = am.sequence([h(FRAMES["neutral"])] * 4)
    assert steady["failures"] == [] and steady["flicker"] == 0.0
    lost = am.sequence([h(FRAMES["neutral"]), h(FRAMES["black"]), h(FRAMES["neutral"])])
    assert lost["blank_frames"] == [1] and "blank_frames" in lost["failures"] and "flicker" in lost["failures"]


def test_baked_calibration_matches_and_selfcheck_detects_drift(tmp_path):
    assert run.selfcheck() == []
    expected = json.loads((LANE / "calib/expected.json").read_text())
    for name, arr in FRAMES.items():
        assert expected[name]["pixels_sha256"] == hashlib.sha256(arr.tobytes()).hexdigest()
    bgm.bake_calib(tmp_path)
    exp = json.loads((tmp_path / "expected.json").read_text())
    exp["clipped"]["health"]["snow_clip"] = 0.2
    (tmp_path / "expected.json").write_text(json.dumps(exp))
    assert any("clipped.snow_clip" in p for p in run.selfcheck(tmp_path))


def test_parse_args_reads_literals_and_flags_the_rest():
    src = ('ap.add_argument("--a", required=True)\nap.add_argument("--b", default=1)\n'
           'ap.add_argument("--v", action="store_true")\nap.add_argument("--" + n)\nap.add_argument("pos")\n')
    assert bgm.parse_args(src) == {"required": ["a"], "optional": ["b"], "flags": ["v"], "dynamic": True}


def test_scan_finds_gates_in_a_fixture_tree_and_skips_itself(tmp_path):
    root = tmp_path / "swarm/lanes"
    for lane, name in (("a/b/alpine", "measure_x.py"), ("a/c/alpine", "pixel_gate.py"),
                       ("a/c/storm", "measure_y.py"), ("validation/pixel_metrics/alpine", "measure_self.py")):
        (root / lane).mkdir(parents=True)
        (root / lane / name).write_text('ap.add_argument("--baseline", required=True)\n')
    (root / "a/b/alpine/bake_x.py").write_text("")
    gates = bgm.scan(root)
    assert [(g["lane"], g["script"]) for g in gates] == [
        ("a.b.alpine", "swarm/lanes/a/b/alpine/measure_x.py"),
        ("a.c.alpine", "swarm/lanes/a/c/alpine/pixel_gate.py")]
    assert gates[0]["required"] == ["baseline"] and len(gates[0]["sha256"]) == 64
    assert bgm.template(gates)["common"] == {"baseline": None}


def test_committed_manifest_is_well_formed_and_staleness_is_reported():
    manifest = json.loads((LANE / "alpine_gates.json").read_text())
    gates = manifest["gates"]
    assert len(gates) >= 10
    assert all(g["lane"].endswith(".alpine") and g["lane"] != bgm.SELF_ID for g in gates)
    assert all((REPO / g["script"]).is_file() for g in gates)
    assert json.loads((LANE / "shot.template.json").read_text()) == bgm.template(gates)
    # Sibling lanes are edited while the swarm runs, so drift is a warning here;
    # the Windows runner turns the same drift into STALE / UNLISTED and exit 1.
    if gates != bgm.scan():
        import warnings
        warnings.warn("alpine_gates.json is stale: re-run build_gate_manifest.py")


GATE = {"lane": "x.y.alpine", "script": "swarm/lanes/validation/pixel_metrics/alpine/alpine_metrics.py",
        "sha256": "0" * 64, "required": ["baseline", "box"], "optional": ["hfov-deg"], "flags": ["verbose"],
        "dynamic": False}


def test_build_argv_precedence_and_missing():
    shot = {"common": {"baseline": "b.png", "unrelated": "no"},
            "lanes": {"x.y.alpine": {"box": "1,2,3,4", "verbose": True, "extra": 5}}}
    built = run.build_argv(GATE, shot)
    assert built["missing"] == []
    assert built["argv"] == ["--baseline", "b.png", "--box", "1,2,3,4", "--verbose", "--extra", "5"]
    assert run.build_argv(GATE, {"common": {"baseline": "b.png"}})["missing"] == ["box"]
    cleared = run.build_argv(GATE, {"common": {"baseline": "b.png"}, "lanes": {"x.y.alpine": {"baseline": None}}})
    assert cleared["missing"] == ["baseline", "box"]


def test_run_gate_status_mapping_without_executing_anything():
    shot = {"common": {"baseline": "b.png", "box": "0,0,1,1"}}
    calls = []

    def fake(code, out=""):
        def runner(cmd, **kw):
            calls.append(cmd)
            return SimpleNamespace(returncode=code, stdout=out, stderr="boom")
        return runner

    ok = run.run_gate(GATE, shot, 5, runner=fake(0, 'noise {"a": {"b": 1}}\n'))
    assert ok["status"] == "PASS" and ok["metrics"] == {"a": {"b": 1}} and ok["stale"] is True
    assert run.run_gate(GATE, shot, 5, runner=fake(1))["status"] == "FAIL"
    assert run.run_gate(GATE, shot, 5, runner=fake(2))["status"] == "ERROR"
    n = len(calls)
    assert run.run_gate(GATE, {}, 5, runner=fake(0))["status"] == "UNMEASURED"
    assert run.run_gate(dict(GATE, script="nope.py"), shot, 5, runner=fake(0))["status"] == "UNMEASURED"
    assert len(calls) == n, "an unmeasurable gate must not be launched"


def test_summary_only_passes_when_everything_measured_and_passed():
    good = [{"lane": "a", "status": "PASS"}, {"lane": "b", "status": "PASS"}]
    assert run.summarise({"status": "PASS"}, good, [])["all_pass"]
    assert not run.summarise({"status": "PASS"}, good + [{"lane": "c", "status": "UNMEASURED"}], [])["all_pass"]
    assert not run.summarise({"status": "UNMEASURED"}, good, [])["all_pass"]
    assert not run.summarise({"status": "PASS"}, [dict(good[0], stale=True)], [])["all_pass"]
    assert not run.summarise({"status": "PASS"}, good, ["new_gate.py"])["all_pass"]


def test_health_runs_from_png_files_and_reports_unmeasured(tmp_path):
    from PIL import Image
    for name in ("neutral", "black"):
        Image.fromarray(FRAMES[name]).save(tmp_path / f"{name}.png")
    seq = tmp_path / "seq"
    seq.mkdir()
    for i, name in enumerate(("neutral", "black", "neutral")):
        Image.fromarray(FRAMES[name]).save(seq / f"f{i:03d}.png")
    ref = str(tmp_path / "neutral.png")
    assert run.run_health({"reference": ref, "candidate": ref}, 0)["status"] == "PASS"
    assert run.run_health({"reference": ref, "candidate": str(tmp_path / "black.png")}, 0)["status"] == "FAIL"
    assert run.run_health({"reference": ref}, 0)["status"] == "UNMEASURED"
    assert run.run_health({"reference": ref, "candidate": str(tmp_path / "gone.png")}, 0)["status"] == "UNMEASURED"
    assert run.run_health({"reference": ref, "candidate": str(seq)}, 0)["status"] == "PASS"   # first frame only
    t2 = run.run_health({"reference": ref, "candidate": str(seq)}, 2)
    assert t2["status"] == "FAIL" and t2["sequence"]["blank_frames"] == [1]


def test_main_exit_codes_with_empty_shot(tmp_path, capsys):
    shot = tmp_path / "shot.json"
    shot.write_text((LANE / "shot.template.json").read_text())
    out = tmp_path / "report.json"
    assert run.main(["--shot", str(shot), "--out", str(out)]) == 1
    report = json.loads(out.read_text())
    assert report["summary"]["gates_unmeasured"] >= 8 and report["summary"]["gates_passed"] == 0
    assert report["health"]["status"] == "UNMEASURED"
    capsys.readouterr()


def test_lane_files_and_provenance():
    prov = json.loads((LANE / "PROVENANCE.json").read_text())
    assert prov["lane"] == bgm.SELF_ID and prov["visual_only"] is True
    assert prov["fetched_assets"] == [] and prov["vendored_code"] == []
    for name, digest in prov["generated"]["sha256"].items():
        assert hashlib.sha256((LANE / name).read_bytes()).hexdigest() == digest, name
    text = (LANE / "INTEGRATION.md").read_text()
    assert "UNMEASURED" in text and "run_alpine_gates.py --shot" in text
