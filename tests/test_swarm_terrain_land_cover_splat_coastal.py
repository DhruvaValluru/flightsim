"""Source-level checks for the coastal land-cover splat lane (Mac).

These check the bake's arithmetic, the pixel gate's maths and the gate's
refusals on synthetic arrays and made-up run directories laid out the way
webapp/runs.py and core/capture/manifest.py write them. They are NOT a
render or pixel result: that is measured on the Windows laptop (see the
lane's INTEGRATION.md). No real WorldCover crop and no rendered frame was
on the Mac when these were written, so neither is exercised here.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm" / "lanes" / "terrain" / "land_cover_splat" / "coastal"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"coastal_splat_{name}", LANE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bake = _load("bake_coastal_splat")
gate = _load("measure_ground")
driver = _load("run_gate")


@pytest.fixture(scope="module")
def baked(tmp_path_factory):
    out = tmp_path_factory.mktemp("splat")
    assert bake.main(["--synthetic", "--tier", "0", "--out", str(out)]) == 0
    return out, json.loads((out / "land_cover_splat.json").read_text())


def test_every_legend_code_maps_to_weights_summing_to_one():
    for code, weights in bake.CODE_TO_GROUPS.items():
        assert len(weights) == len(bake.GROUPS) and abs(sum(weights) - 1.0) < 1e-9, code
    try:
        from core.terrain.landcover import LEGEND_CODES
    except Exception:
        pytest.skip("core.terrain.landcover not importable here")
    assert set(bake.CODE_TO_GROUPS) == set(LEGEND_CODES)


def test_splat_sums_to_255_in_every_texel_and_every_mip(baked):
    out, sidecar = baked
    top = np.asarray(Image.open(out / "splat_rgba.png"))
    assert top.shape == (512, 512, 4)
    assert (top.astype(int).sum(axis=-1) == 255).all()
    blob = np.frombuffer((out / "splat_bgra_mips.bin").read_bytes(), np.uint8)
    edges = sidecar["files"]["splat_bgra_mips.bin"]["mip_edges"]
    assert edges == [512 >> i for i in range(10)]
    assert blob.size == sum(e * e * 4 for e in edges)
    offset = 0
    for edge in edges:
        mip = blob[offset:offset + edge * edge * 4].reshape(edge, edge, 4)
        assert (mip.astype(int).sum(axis=-1) == 255).all()
        offset += edge * edge * 4
    assert (blob[:512 * 512 * 4].reshape(512, 512, 4)[..., [2, 1, 0, 3]] == top).all()


def test_sidecar_hashes_match_the_files_and_the_bake_is_deterministic(baked, tmp_path):
    out, sidecar = baked
    for name, entry in sidecar["files"].items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == entry["sha256"], name
    assert bake.main(["--synthetic", "--tier", "0", "--out", str(tmp_path)]) == 0
    again = json.loads((tmp_path / "land_cover_splat.json").read_text())
    assert again["files"] == sidecar["files"]
    assert sidecar["source"]["synthetic"] is True
    assert abs(sum(sidecar["group_fractions"].values()) - 1.0) < 1e-4


def test_shore_sdf_sign_follows_the_water_channel(baked):
    out, sidecar = baked
    water = np.asarray(Image.open(out / "splat_rgba.png"))[..., 3] >= 128
    sdf = bake.decode_sdf(np.asarray(Image.open(out / "shore_sdf.png")))
    assert (sdf[water] < 0).mean() > 0.999 and (sdf[~water] > 0).mean() > 0.999
    assert sidecar["shore_sdf"]["range_m"] == bake.SDF_RANGE_M


def test_capped_edt_matches_brute_force():
    rng = np.random.default_rng(7)
    mask = rng.random((40, 48)) > 0.97
    cap = 12
    ys, xs = np.nonzero(mask)
    yy, xx = np.mgrid[0:40, 0:48]
    brute = np.sqrt(((yy[..., None] - ys) ** 2 + (xx[..., None] - xs) ** 2).min(axis=-1))
    assert np.allclose(bake.capped_edt(mask, cap), np.minimum(brute, cap), atol=1e-4)


def test_shore_distance_in_metres_on_a_straight_coast():
    water = np.zeros((64, 64), bool)
    water[:, :20] = True
    sdf = bake.shore_sdf_m(water, texel_m=40.0)
    assert sdf[10, 20] == pytest.approx(20.0)      # first land texel: half a texel inland
    assert sdf[10, 24] == pytest.approx(180.0)
    assert sdf[10, 19] == pytest.approx(-20.0)
    encoded = bake.encode_sdf(sdf)
    assert abs(bake.decode_sdf(encoded)[10, 24] - 180.0) <= bake.SDF_RANGE_M / 127.0


def test_refusals_are_by_name(tmp_path, capsys):
    with pytest.raises(bake.LandCoverSplatError, match="terrain.land_cover_splat"):
        bake.group_fractions(np.full((4, 4), 33, np.uint8))
    assert bake.main(["--synthetic", "--extent-m", "1000", "2000", "--out", str(tmp_path)]) == 2
    # tier 3 over a small extent: texels too fine for the 320 m shoreline search
    assert bake.main(["--synthetic", "--tier", "3", "--extent-m", "4096", "4096", "--out", str(tmp_path)]) == 2
    assert "terrain.land_cover_splat" in capsys.readouterr().err


def test_vram_estimates_rise_with_tier_and_tier0_is_small():
    totals = [bake.est_vram_mb(t)["total"] for t in sorted(bake.TIERS)]
    assert totals == sorted(totals) and totals[0] < 2.0
    assert totals[0] == pytest.approx(512 * 512 * 5 * 4 / 3 / 2 ** 20, abs=0.01)


def test_provenance_lists_the_lane_code_with_matching_sha256():
    provenance = json.loads((LANE / "PROVENANCE.json").read_text())
    assert provenance["label"].startswith("visual-only") and provenance["vendored"] == []
    for entry in provenance["lane_code"]:
        assert hashlib.sha256((LANE / entry["file"]).read_bytes()).hexdigest() == entry["sha256"], entry["file"]
    for source in provenance["sources"]:
        assert source["name"] and source["licence"]
        assert "non-commercial" not in source["licence"].lower()


# ---- pixel gate maths, on synthetic frames (not a render) ----

CAMERA = gate.Camera(altitude_m=300.0, pitch_down_deg=8.0, vfov_deg=50.0, height_px=480)


def _frame(visibility_km: float, blur: int = 1, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    _, ground = CAMERA.ranges()
    noise = rng.standard_normal((CAMERA.height_px, 640))
    if blur > 1:
        kernel = np.ones(blur) / blur
        noise = np.apply_along_axis(lambda r: np.convolve(r, kernel, mode="same"), 1, noise) * np.sqrt(blur)
    transmit = np.exp(-3.912 * np.nan_to_num(ground, nan=np.inf) / (visibility_km * 1000.0))
    lum = 0.3 + 0.05 * noise * transmit[:, None]
    lum[~np.isfinite(ground)] = 0.6
    return np.clip(lum, 0.0, 1.0).astype(np.float32)


def test_camera_geometry():
    flat = gate.Camera(300.0, 45.0, 50.0, 481)
    slant, ground = flat.ranges()
    assert ground[240] == pytest.approx(300.0, rel=1e-3)
    assert slant[240] == pytest.approx(300.0 * 2 ** 0.5, rel=1e-3)
    assert flat.horizon_km() == pytest.approx((2 * gate.EARTH_RADIUS_M * 300.0) ** 0.5 / 1000.0, rel=1e-3)
    assert np.isnan(CAMERA.ranges()[1][0])          # top row looks at the sky


def test_blur_raises_effective_gsd_and_fails_the_gate():
    sharp = gate.measure(_frame(15.7), CAMERA)
    soft = gate.measure(_frame(15.7, blur=5), CAMERA)
    assert soft["effective_gsd_m"] > 1.5 * sharp["effective_gsd_m"]
    assert sharp["effective_gsd_m"] >= sharp["pixel_footprint_m"] * 0.99
    assert gate.gate(sharp, sharp)["pass"] is True
    assert gate.gate(sharp, soft)["checks"]["gsd_ratio_le_1.02"] is False


def test_visible_range_follows_the_haze():
    clear = gate.measure(_frame(40.0), CAMERA)
    hazy = gate.measure(_frame(8.0), CAMERA)
    assert 0 < hazy["visible_range_km"] < clear["visible_range_km"] <= clear["geometric_horizon_km"]
    assert gate.gate(clear, hazy)["checks"]["range_ratio_ge_0.95"] is False
    # a candidate that shows ground far past the haze visibility is refused
    assert gate.gate(hazy, clear, haze_visibility_km=8.0)["checks"]["range_within_haze"] is False


def _save(path: Path, lum: np.ndarray) -> str:
    srgb = np.where(lum <= 0.0031308, lum * 12.92, 1.055 * lum ** (1 / 2.4) - 0.055)
    u8 = np.rint(srgb * 255).astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.dstack([u8] * 3)).save(path)
    return str(path)


def test_gate_cli_on_png_frames(tmp_path, capsys):
    base = _save(tmp_path / "base.png", _frame(15.7))
    again = _save(tmp_path / "again.png", _frame(15.7, seed=4))
    soft = _save(tmp_path / "soft.png", _frame(15.7, blur=5))
    common = ["--altitude-m", "300", "--pitch-down-deg", "8", "--vfov-deg", "50"]
    # the same file twice is not a pass: nothing changed, nothing to gate
    assert gate.main(["--baseline", base, "--candidate", base, *common]) == 2
    assert "identical pixels" in capsys.readouterr().err
    assert gate.main(["--baseline", base, "--candidate", again, *common]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["gate"]["pass"] is True and report["splat_evidence"] == "none"
    assert gate.main(["--baseline", base, "--candidate", soft, *common]) == 1
    capsys.readouterr()
    # the camera numbers are not optional with bare PNGs
    assert gate.main(["--baseline", base, "--candidate", again]) == 2


# ---- the gate on run directories (made-up, in the web app's layout) ----

def _run_dir(root: Path, lum: np.ndarray, *, applied=None, requested=None, roll=0.0,
             alt=300.0, log="") -> Path:
    """runs/webapp/<id> as webapp/runs.py lays it out: card.json,
    capture_manifest.json, render.log, frames/<camera>/{frame_0000.png, render.json}."""
    camera = "chase"
    _save(root / "frames" / camera / "frame_0000.png", lum)
    _save(root / "frames" / camera / "frame_0000_beauty_post.png", lum)   # must not be picked
    height, vfov = lum.shape[0], 50.0
    fy = (height / 2.0) / np.tan(np.radians(vfov) / 2.0)
    record = {"index": 0, "camera_id": camera, "file": "frame_0000.png", "position_alt_m": alt,
              "pitch_deg": -8.0, "roll_deg": roll, "fy_px": float(fy), "height_px": height}
    (root / "capture_manifest.json").write_text(json.dumps({"frames": [record]}))
    (root / "card.json").write_text(json.dumps({} if requested is None else {"land_cover_splat": requested}))
    render = {"frames": 1, "frame_records": [{"frame": 0}]}
    if applied is not None:
        render["land_cover_splat"] = {"applied": applied, "tier": 0, "sidecar_sha256": "0" * 64}
    (root / "frames" / camera / "render.json").write_text(json.dumps(render))
    (root / "render.log").write_text(log)
    return root


def test_camera_comes_from_the_capture_manifest(tmp_path):
    run = _run_dir(tmp_path / "a", _frame(15.7))
    frame, camera = gate.run_frame(run)
    assert (frame.name, camera) == ("frame_0000.png", "chase")
    numbers = gate.camera_numbers(json.loads((run / "capture_manifest.json").read_text()), camera, frame.name)
    assert numbers["altitude_m"] == 300.0 and numbers["pitch_down_deg"] == 8.0
    assert numbers["vfov_deg"] == pytest.approx(50.0, abs=1e-6)
    with pytest.raises(gate.GroundGateError, match="roll"):
        gate.load_run(_run_dir(tmp_path / "rolled", _frame(15.7), roll=5.0), 0.0)
    with pytest.raises(gate.GroundGateError, match="above a surface"):
        gate.load_run(_run_dir(tmp_path / "low", _frame(15.7), alt=10.0), 40.0)
    with pytest.raises(gate.GroundGateError, match="no frames"):
        gate.run_frame(tmp_path / "missing")


def test_gate_refuses_when_the_engine_did_not_draw_the_splat(tmp_path, capsys):
    """The vacuous pass: today's tree writes no land_cover_splat echo, so two
    renders of it are refused (exit 2), never passed."""
    off = _run_dir(tmp_path / "off", _frame(15.7))
    same_tree = _run_dir(tmp_path / "same", _frame(15.7, seed=4), requested={"tier": 0})
    args = ["--baseline-run", str(off), "--candidate-run"]
    assert gate.main([*args, str(same_tree)]) == 2
    assert "did not draw the splat" in capsys.readouterr().err
    on = _run_dir(tmp_path / "on", _frame(15.7, seed=4), applied=True, requested={"tier": 0})
    assert gate.main(["--baseline-run", str(on), "--candidate-run", str(on)]) == 2      # baseline had it on
    assert "baseline" in capsys.readouterr().err
    assert gate.main([*args, str(on)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["splat_evidence"] == "render.json" and report["candidate"]["splat"]["applied"] is True
    assert report["camera"]["altitude_m"] == 300.0
    # a different shot on the two sides is refused, not compared
    higher = _run_dir(tmp_path / "higher", _frame(15.7, seed=4), applied=True, alt=900.0)
    assert gate.main([*args, str(higher)]) == 2
    assert "cameras differ" in capsys.readouterr().err


def test_device_lost_in_the_candidate_log_fails_the_gate(tmp_path, capsys):
    off = _run_dir(tmp_path / "off", _frame(15.7))
    lost = _run_dir(tmp_path / "lost", _frame(15.7, seed=4), applied=True,
                    log="LogD3D11RHI: Error: Unreal Engine is exiting due to D3D device being lost.\n")
    assert gate.main(["--baseline-run", str(off), "--candidate-run", str(lost)]) == 1
    assert json.loads(capsys.readouterr().out)["gate"]["checks"]["no_device_lost_in_render_log"] is False


# ---- the Windows driver's refusals (nothing is rendered here) ----

def test_driver_names_what_is_not_integrated(tmp_path):
    assert len(driver.missing_markers(tmp_path)) == len(driver.MARKERS)
    (tmp_path / "core" / "scenario").mkdir(parents=True)
    (tmp_path / "core" / "scenario" / "card.py").write_text(f'os.environ.get("{driver.SWITCH}")')
    source = tmp_path / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "X"
    source.mkdir(parents=True)
    (source / "FlightSimGoogleTiles.cpp").write_text('TEXT("LandCoverSplat")')
    assert driver.missing_markers(tmp_path) == []


def test_driver_finds_exactly_one_scenario():
    rows = [("golden hour", "p", {}), ("coastal A-4, low sun over the sea", "p", {})]
    assert driver.find_scenario(rows, "coastal") == 2
    for bad in (rows[:1], rows + [("coastal again", "p", {})]):
        with pytest.raises(driver.Refused, match="no_coastal_scenario"):
            driver.find_scenario(bad, "coastal")


def test_driver_on_this_tree_refuses_until_the_integration_lands(capsys):
    """Against the REAL repo: the gate must refuse (3) for as long as the
    switch is not in the tree, and must never start a render to find out."""
    missing = driver.missing_markers()
    code = driver.main(["--check", "--server", "http://127.0.0.1:9"])
    if missing:
        assert code == 3 and "not_integrated" in capsys.readouterr().err
    else:
        assert code in (0, 3)


def test_driver_renders_off_then_tier_and_measures_the_two_runs(tmp_path, monkeypatch):
    calls, values = [], []
    runs = tmp_path / "webapp"

    class Runner:
        RUNS = runs

        @staticmethod
        def run_batch(args, wanted, summary=None, gather=None):
            assert args.still and args.compiler == "regex" and args.spec_dir and wanted == {2}
            summary.write_text(json.dumps([{"number": 2, "outcome": "done", "run_id": f"run{len(calls)}"}]))
            calls.append(summary.name)
            return 0

    class Process:
        def poll(self): return None
        def terminate(self): pass
        def wait(self, timeout=None): return 0

    state = {"up": False}
    monkeypatch.setattr(driver, "answering", lambda server, timeout=2.0: state["up"])

    def start(env):
        values.append(env[driver.SWITCH])
        state["up"] = True
        return Process()

    args = type("A", (), {"server": "http://127.0.0.1:8008", "app_wait": 5.0, "min_free_mb": 1.0})()
    rows = []
    for value in ("off", "0"):
        state["up"] = False
        rows.append(driver.render_side(Runner, 2, value, args, tmp_path, start=start))
    assert values == ["off", "0"]                       # exact values, no trailing space
    assert [r["run_id"] for r in rows] == ["run0", "run1"]
    assert calls == ["summary_off.json", "summary_0.json"]
    state["up"] = True
    with pytest.raises(driver.Refused, match="app_already_running"):
        driver.render_side(Runner, 2, "off", args, tmp_path, start=start)


# ---- the --class-map path, on files in core/terrain/landcover.py's format ----

def test_class_map_path_checks_the_png_against_landcover_json(tmp_path, capsys):
    """A mode-L PNG of legend codes and a landcover.json carrying its sha256,
    as rasterise() writes them. Made-up codes, not a WorldCover crop."""
    codes = np.full((256, 256), 80, np.uint8)            # water
    codes[:, 96:] = 60                                    # bare / sand
    codes[:, 128:] = 10                                   # trees
    codes[:64, 200:] = 50                                 # built
    png = tmp_path / "class_map.png"
    Image.fromarray(codes, mode="L").save(png)
    sha = hashlib.sha256(png.read_bytes()).hexdigest()
    document = {"dataset": "ESA WorldCover", "attribution": "(c) ESA WorldCover project 2021",
                "class_map": {"file": png.name, "sha256": sha}}
    (tmp_path / "landcover.json").write_text(json.dumps(document))
    common = ["--class-map", str(png), "--landcover-json", str(tmp_path / "landcover.json"),
              "--extent-m", "5120", "5120", "--tier", "0"]
    assert bake.main([*common, "--out", str(tmp_path / "out")]) == 0
    sidecar = json.loads((tmp_path / "out" / "land_cover_splat.json").read_text())
    capsys.readouterr()
    assert json.dumps(document["attribution"])[1:-1] in json.dumps(sidecar)
    assert sha in json.dumps(sidecar) and '"synthetic": false' in json.dumps(sidecar)
    splat = np.asarray(Image.open(tmp_path / "out" / "splat_rgba.png"))
    assert splat.shape[2] == 4 and splat[..., 3][:, :64].min() == 255      # sea on the west edge
    assert splat[..., 3][:, 300:].max() == 0                               # none inland
    # a class map that is not the one landcover.json describes is refused by name
    document["class_map"]["sha256"] = "0" * 64
    (tmp_path / "landcover.json").write_text(json.dumps(document))
    assert bake.main([*common, "--out", str(tmp_path / "out2")]) == 2
    assert "terrain.land_cover_splat" in capsys.readouterr().err
