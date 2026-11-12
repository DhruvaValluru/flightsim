"""Source-level checks for the alpine stress-ladder lane (Mac).

They check the ladder generator and the judge's arithmetic on synthetic
files. They are NOT a frame-time, VRAM or thermal result: that is measured
on the Windows laptop (see the lane's INTEGRATION.md).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import struct
import sys
import zlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm" / "lanes" / "hardware_perf" / "stress_ladder" / "alpine"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"alpine_ladder_{name}", LANE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build = _load("build_ladder")
measure = _load("measure_ladder")
LADDER = json.loads((LANE / "alpine_ladder.json").read_text())
THRESHOLDS = LADDER["protocol"]["thresholds"]


def test_committed_ladder_is_what_the_generator_writes():
    assert (LANE / "alpine_ladder.json").read_text() == build.dumps(build.build())


def test_provenance_hashes_match():
    prov = json.loads((LANE / "PROVENANCE.json").read_text())
    assert prov["vendored"] == []
    for item in prov["generated"]:
        digest = hashlib.sha256((LANE / item["file"]).read_bytes()).hexdigest()
        assert digest == item["sha256"], item["file"]


def test_tier0_fits_the_starting_budget_and_tiers_climb():
    totals = [t["est_vram_mb"]["total"] for t in LADDER["tiers"]]
    assert totals == sorted(totals) and len(set(totals)) == 4
    t0 = LADDER["tiers"][0]
    assert totals[0] <= LADDER["target"]["start_usable_vram_mb"]
    assert t0["width"] <= LADDER["target"]["start_max_capture_width"]
    assert max(t["width"] for t in LADDER["tiers"]) <= LADDER["target"]["display"][0]
    for t in LADDER["tiers"]:
        assert t["est_vram_mb"]["total"] == pytest.approx(
            sum(v for k, v in t["est_vram_mb"].items() if k != "total"), abs=0.11)
        assert t["sustained"] is None  # never claimed from the Mac


def test_every_tier_is_d3d11_safe():
    for t in LADDER["tiers"]:
        c = t["cvars"]
        assert c["r.DynamicGlobalIlluminationMethod"] == 0
        assert c["r.ReflectionMethod"] == 0
        assert c["r.Shadow.Virtual.Enable"] == 0
        assert c["r.AntiAliasingMethod"] in (1, 2)  # FXAA or TAA, never TSR
        assert "-dx11" in t["launch_args"]
        assert f"-FlightSimStressTier={t['tier']}" in t["launch_args"]


def _png(path: Path, width=64, height=40, flat=None, filter_kind=0):
    rows = bytearray()
    prev = bytes(width * 3)
    for y in range(height):
        line = bytearray()
        for x in range(width):
            v = flat if flat is not None else (x * 4 + y * 3) % 256
            line += bytes((v, v, min(255, v + 10)))
        if filter_kind == 2:   # Up
            enc = bytes((a - b) & 0xFF for a, b in zip(line, prev))
        elif filter_kind == 1:  # Sub
            enc = bytes((line[i] - (line[i - 3] if i >= 3 else 0)) & 0xFF for i in range(len(line)))
        else:
            enc = bytes(line)
        rows += bytes((filter_kind,)) + enc
        prev = bytes(line)

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b""))


def _run(tmp_path: Path, tier=0, log_extra="", gap_s=0.2, frames=12, flat=None,
         ram=(4000, 3900, 3800), perf=(100, 99, 98, 100, 99, 98), kelvin=(330.0, 340.0)):
    run = tmp_path / "run"
    cam = run / "frames" / "chase"
    cam.mkdir(parents=True)
    (cam.parent / "render.log").write_text(
        f"LogInit: Command Line: -dx11 -FlightSimStressTier={tier} -DPCVars=a=1\n{log_extra}\n")
    for i in range(frames):
        p = cam / f"frame_{i:04d}.png"
        _png(p, flat=flat, filter_kind=i % 3)
        os.utime(p, (1_000_000 + i * gap_s, 1_000_000 + i * gap_s))
    _png(cam / "frame_0000_beauty_post.png")  # must be ignored
    n = max(len(ram), len(perf))
    rows = ['"(PDH-CSV 4.0)","\\\\PC\\GPU Adapter Memory(luid_a)\\Shared Usage",'
            '"\\\\PC\\GPU Adapter Memory(luid_b)\\Shared Usage",'
            '"\\\\PC\\GPU Adapter Memory(luid_a)\\Dedicated Usage",'
            '"\\\\PC\\Memory\\Available MBytes",'
            '"\\\\PC\\Processor Information(_Total)\\% Processor Performance"']
    for i in range(n):
        rows.append(f'"11/12/2026 10:00:{i:02d}.000","{200 * 1024 * 1024}","{100 * 1024 * 1024}",'
                    f'"{50 * 1024 * 1024}","{ram[i % len(ram)]}","{perf[i % len(perf)]}"')
    sampler = tmp_path / "sampler.csv"
    sampler.write_text("\n".join(rows) + "\n")
    thermal = tmp_path / "thermal.csv"
    thermal.write_text('"(PDH-CSV 4.0)","\\\\PC\\Thermal Zone Information(TZ0)\\Temperature"\n'
                       + "".join(f'"t","{k}"\n' for k in kelvin))
    return measure.judge_run(run, tier, THRESHOLDS, sampler, thermal)


def test_clean_run_passes_with_the_expected_numbers(tmp_path):
    v = _run(tmp_path)
    assert v["pass"], v["reasons"]
    m = v["metrics"]
    assert m["frames"] == 12  # the beauty copy is not a frame
    assert m["frame_wall_ms_p95"] == pytest.approx(200.0, abs=0.5)
    assert m["gpu_memory_mb_peak"] == pytest.approx(350.0)  # instances summed
    assert m["available_ram_mb_min"] == 3800
    assert m["temperature_c_max"] == pytest.approx(66.9, abs=0.1)
    assert (m["frame_width"], m["frame_height"]) == (64, 40)


@pytest.mark.parametrize("kwargs, reason", [
    ({"log_extra": "LogD3D11RHI: Error: DXGI_ERROR_DEVICE_REMOVED"}, "device_lost"),
    ({"log_extra": "LogRHI: Out of video memory trying to allocate"}, "out_of_memory"),
    ({"gap_s": 1.5}, "frame_time_p95"),
    ({"frames": 3}, "too_few_frames"),
    ({"flat": 0}, "black_frame"),
    ({"flat": 128}, "flat_frame"),
    ({"ram": (4000, 600)}, "low_ram"),
    ({"perf": (100, 100, 100, 60, 60, 60)}, "cpu_throttled"),
    ({"kelvin": (372.0,)}, "too_hot"),
])
def test_each_failure_is_refused_by_name(tmp_path, kwargs, reason):
    v = _run(tmp_path, **kwargs)
    assert not v["pass"]
    assert any(r.startswith(reason) for r in v["reasons"]), v["reasons"]


def test_unapplied_tier_and_missing_sampler_are_refused(tmp_path):
    v = _run(tmp_path, tier=1)
    assert v["pass"]
    run = Path(v["metrics"]["run_dir"])
    wrong = measure.judge_run(run, 2, THRESHOLDS, tmp_path / "sampler.csv")
    assert "tier_not_applied:log_has_1" in wrong["reasons"]
    assert wrong["metrics"]["temperature_c_max"] is None  # no thermal file: recorded, not failed
    blind = measure.judge_run(run, 1, THRESHOLDS, tmp_path / "absent.csv")
    assert "sampler_empty" in blind["reasons"]


def test_png_filters_decode_to_the_same_picture(tmp_path):
    stats = []
    for kind in (0, 1, 2):
        _png(tmp_path / f"f{kind}.png", filter_kind=kind)
        stats.append(measure.png_stats(tmp_path / f"f{kind}.png"))
    assert stats[0] == stats[1] == stats[2]
    assert stats[0]["luma_stddev"] > 10


def _verdict(tier, ok, lost=0):
    return {"pass": ok, "reasons": [] if ok else ["device_lost:1"],
            "metrics": {"tier": tier, "device_lost": lost, "gpu_memory_mb_peak": 400.0 + tier,
                        "frame_wall_ms_p95": 300.0, "available_ram_mb_min": 2000.0,
                        "throttle_ratio": 0.97, "temperature_c_max": None}}


def test_summary_sets_measured_only_when_tier0_held():
    held = [_verdict(0, True)] * 3 + [_verdict(1, True)] * 3 + [_verdict(2, False, lost=1)]
    s = measure.summarise(LADDER, held)
    assert s["measured"] is True and s["sustained_tier"] == 1
    assert s["device_lost_total"] == 1
    assert s["budget"]["measured"] is True and s["budget"]["usable_vram_mb"] == 401
    assert s["budget"]["max_capture_width"] == LADDER["tiers"][1]["width"]
    assert s["budget"]["cvars"] == LADDER["tiers"][1]["cvars"]

    two_runs = measure.summarise(LADDER, [_verdict(0, True)] * 2)
    assert two_runs["measured"] is False and two_runs["refused"] == "tier0_not_sustained"
    failed = measure.summarise(LADDER, [_verdict(0, True), _verdict(0, False, lost=1)])
    assert failed["measured"] is False and "budget" not in failed
    # a tier above an unsustained one never counts
    gap = measure.summarise(LADDER, [_verdict(1, True)] * 3)
    assert gap["sustained_tier"] is None


def test_percentile():
    assert measure.percentile([1, 2, 3, 4, 5], 50) == 3
    assert measure.percentile(list(range(101)), 95) == 95
    with pytest.raises(ValueError, match="no_values"):
        measure.percentile([], 95)
