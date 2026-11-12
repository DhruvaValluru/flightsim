"""Code-level checks for the alpine VRAM ledger (Mac). These check arithmetic
and parsers only; they are not a render, VRAM or frame-time measurement."""
import importlib.util
import json
from pathlib import Path

LANE = Path(__file__).resolve().parents[1] / "swarm/lanes/hardware_perf/vram_budgeting/alpine"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, LANE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bake = _load("bake_vram_budget")
gate = _load("measure_vram_gate")
MB = 1024 * 1024


def test_mip_chain_bytes_exact():
    assert bake.mip_chain_bytes(4, 4, "RGBA8", mips=False) == 64
    assert bake.mip_chain_bytes(4, 4, "RGBA8") == 64 + 16 + 4
    assert bake.mip_chain_bytes(256, 256, "BC1", mips=False) == 32768
    assert bake.mip_chain_bytes(1024, 1024, "D16", mips=False) == 2 * MB
    # BC1 is 8x smaller than RGBA8 at the top mip; block rounding costs a little on the tail
    r = bake.mip_chain_bytes(512, 512, "RGBA8") / bake.mip_chain_bytes(512, 512, "BC1")
    assert 7.9 < r <= 8.0


def test_tier0_fits_with_margin_and_tiers_grow():
    d = bake.build()
    t = d["tiers"]
    assert [x["tier"] for x in t] == [0, 1, 2, 3]
    assert t[0]["est_vram_mb"] <= d["usable_vram_mb"] * (1 - d["device_loss_margin"])
    est = [x["est_vram_mb"] for x in t]
    assert est == sorted(est) and len(set(est)) == 4
    for x in t:
        assert abs(sum(x["est_bytes"].values()) / MB - x["est_vram_mb"]) < 0.06
        assert x["sustained"] is None
        # the streaming pool is one consumer, never the whole cap
        assert x["cvars"]["r.Streaming.PoolSize"] * MB == x["est_bytes"]["ue_streaming_pool"]
        assert x["cvars"]["r.DynamicGlobalIlluminationMethod"] == 0
    assert t[0]["cvars"]["r.Streaming.PoolSize"] < d["usable_vram_mb"]
    assert t[0]["capture"]["width"] <= 1280
    assert d["measured"] is False


def test_tier0_refuses_when_cap_too_small():
    try:
        bake.build(300)
    except SystemExit as e:
        assert "tier 0" in str(e)
    else:
        raise AssertionError("a 300 MB cap must refuse")


def test_committed_files_match_generator(tmp_path):
    hashes = bake.write(tmp_path)
    for name in hashes:
        assert (LANE / name).read_text() == (tmp_path / name).read_text(), name
    prov = json.loads((LANE / "PROVENANCE.json").read_text())
    assert {g["file"]: g["sha256"] for g in prov["generated"]} == hashes
    assert prov["vendored"] == []
    ini = (LANE / "alpine_vram_tier0.ini").read_text()
    assert "[SystemSettings]" in ini and "r.Streaming.PoolSize=128" in ini


TYPEPERF = (
    '"(PDH-CSV 4.0)","\\\\PC\\GPU Adapter Memory(luid_0)\\Shared Usage",'
    '"\\\\PC\\GPU Adapter Memory(luid_0)\\Dedicated Usage",'
    '"\\\\PC\\Thermal Zone Information(TZ0)\\Temperature"\n'
    '"t0","{a}","0","343.15"\n"t1","{b}","{c}","353.15"\n"t2"," ","0","353.15"\n'
)


def test_typeperf_parser():
    p = gate.parse_typeperf(TYPEPERF.format(a=100 * MB, b=300 * MB, c=50 * MB))
    assert p["gpu_bytes"] == [100 * MB, 350 * MB]  # the blank sample is dropped
    assert [round(t) for t in p["temp_c"]] == [70, 80, 80]
    assert gate.parse_typeperf("") == {"gpu_bytes": [], "temp_c": []}
    # typeperf -sc 1 stdout: blank line first, banner lines after
    out = "\n" + TYPEPERF.format(a=MB, b=2 * MB, c=MB) + "Exiting, please wait...\nThe command completed successfully.\n"
    assert gate.parse_typeperf(out)["gpu_bytes"] == [MB, 3 * MB]
    assert gate.parse_typeperf("Error: No valid counters.\n") == {"gpu_bytes": [], "temp_c": []}


def test_log_parser_and_cvar_switch():
    log = "LogD3D11RHI: Error: DXGI_ERROR_DEVICE_REMOVED\nok\nGPU crash detected\nLogInit: fine\n"
    assert gate.count_device_lost(log) == 2
    assert gate.count_device_lost("LogInit: all good\n") == 0
    tok = gate.cvar_switch(bake.build()["tiers"][0]["cvars"])
    assert tok.startswith("-ini:Engine:[SystemSettings]:") and " " not in tok
    assert "[SystemSettings]:r.Streaming.PoolSize=128" in tok
    import shlex
    assert shlex.split(tok, posix=True) == [tok]  # survives with_render_switches' split


def _png(rows, ctype=2, filt=0):
    import struct, zlib
    h, w = len(rows), len(rows[0])
    ch = {0: 1, 2: 3, 6: 4}[ctype]
    raw = b""
    prev = bytes(w * ch)
    for r in rows:
        line = b"".join(bytes([v] * min(ch, 3)) + (b"\xff" if ch == 4 else b"") for v in r)
        if filt == 2:
            raw += b"\x02" + bytes((a - b) & 255 for a, b in zip(line, prev))
        elif filt == 1:
            raw += b"\x01" + bytes((line[i] - (line[i - ch] if i >= ch else 0)) & 255 for i in range(len(line)))
        else:
            raw += b"\x00" + line
        prev = line
    def chunk(k, d):
        return struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_png_reader_and_ground_sharpness():
    rows = [[(x * 7 + y * 13) % 256 for x in range(16)] for y in range(12)]
    for ctype in (0, 2, 6):
        for filt in (0, 1, 2):
            got = gate.read_png_gray(_png(rows, ctype, filt))
            assert [[round(v) for v in r] for r in got] == rows, (ctype, filt)
    # 64x64: top half sky (flat), bottom half checker terrain
    sharp = [[0.0] * 64 for _ in range(32)] + [[255.0 * ((x + y) % 2) for x in range(64)] for y in range(32)]
    soft = [r[:] for r in sharp[:32]] + [[127.5 + 0.5 * (v - 127.5) for v in r] for r in sharp[32:]]
    assert gate.ground_sharpness_ratio(sharp, sharp) == 1.0
    assert abs(gate.ground_sharpness_ratio(sharp, soft) - 0.25) < 1e-6  # half contrast = quarter variance
    # a different top half (sky, clouds) does not move the ground metric
    sky = [[float((x * 31) % 255) for x in range(64)] for _ in range(32)] + sharp[32:]
    assert gate.ground_sharpness_ratio(sharp, sky) == 1.0
    assert gate.ground_sharpness_ratio(sharp, sharp[:-1]) is None       # size mismatch
    assert gate.ground_sharpness_ratio(sharp[:32] * 2, sharp[:32] * 2) is None  # no detail anywhere


def test_gate_logic():
    ok = gate.evaluate(491, [500 * MB], [100 * MB], 0, True, [80.0], 1.0)
    assert ok["passed"] and ok["may_write_patch"] and ok["peak_gpu_mb_above_idle"] == 400.0
    assert ok["measured_fields"] == ["peak_gpu_memory", "device_loss", "temperature"]
    assert ok["not_measured"] == ["frame_time"]  # this gate never measures frame time
    assert not gate.evaluate(491, [700 * MB], [100 * MB], 0, True, [80.0], 1.0)["passed"]
    assert not gate.evaluate(491, [500 * MB], [100 * MB], 1, True, [80.0], 1.0)["passed"]
    assert not gate.evaluate(491, [500 * MB], [100 * MB], 0, True, [80.0], 0.9)["passed"]
    assert not gate.evaluate(491, [500 * MB], [100 * MB], 0, False, [80.0], 1.0)["passed"]
    # missing inputs never pass and never allow a patch
    none = gate.evaluate(491, [], [], None, None, [], None)
    assert not none["passed"] and not none["may_write_patch"]
    assert not gate.evaluate(491, [500 * MB], [100 * MB], 0, True, [80.0], None)["passed"]
    # no thermal counter: still a VRAM result, and it says temperature was not measured
    cold = gate.evaluate(491, [500 * MB], [100 * MB], 0, True, [], 1.0)
    assert cold["passed"] and cold["not_measured"] == ["frame_time", "temperature"]


def test_windows_command_points_at_real_things():
    """The gate's one command must name the alpine scene and real driver flags."""
    import ast
    repo = LANE.parents[4]
    assert gate.REPO == repo
    src = (repo / "scripts/run_test_scenarios.py").read_text()
    scen = next(n.value for n in ast.parse(src).body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "SCENARIOS")
    name = ast.literal_eval(scen.elts[gate.SCENARIO_NUMBER - 1].elts[0])
    assert gate.SCENARIO_WORD in name.lower()
    for flag in ('"--still"', '"--only"', '"--compiler"', '"regex"'):
        assert flag in src, flag
    runs = (repo / "webapp/runs.py").read_text()
    assert "FLIGHTSIM_RENDER_SWITCHES" in runs and '"render.log"' in runs
    cpp = (repo / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimGoogleTiles.cpp").read_text()
    assert "FLIGHTSIM_GOOGLE_TILES_SSE" in cpp
    doc = (LANE / "INTEGRATION.md").read_text()
    cmd = "python swarm\\lanes\\hardware_perf\\vram_budgeting\\alpine\\measure_vram_gate.py --tier 0"
    assert cmd in doc
    block = doc[doc.index("## Windows measurement"):doc.index("## Mac checks")]
    assert "<" not in block.replace("<= 491", "").replace("<camera>", "")  # no unfilled placeholders
    assert "csvprofile" not in (LANE / "measure_vram_gate.py").read_text()
