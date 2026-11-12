"""Source-level checks (Mac) of the coastal aircraft PBR lane:
swarm/lanes/aircraft_exterior/pbr_materials/coastal. These check the bake and
its numbers. They are NOT a render or pixel result: that is the Windows gate
(measure_gate.py on two rendered frames), UNMEASURED until run on the laptop.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm" / "lanes" / "aircraft_exterior" / "pbr_materials" / "coastal"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"coastal_pbr_{name}", LANE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bake = _load("bake_coastal_pbr")
gate = _load("measure_gate")


@pytest.fixture(scope="module")
def baked(tmp_path_factory):
    out = tmp_path_factory.mktemp("coastal_pbr")
    return out, bake.bake(out, (0,))


def test_bake_is_deterministic_and_matches_the_shipped_tier0(baked, tmp_path):
    out, manifest = baked
    again = bake.bake(tmp_path, (0,))
    assert again["tiers"]["0"]["files"] == manifest["tiers"]["0"]["files"]
    shipped = json.loads((LANE / "baked" / "coastal_pbr_manifest.json").read_text())
    for name, row in shipped["tiers"]["0"]["files"].items():
        data = (LANE / "baked" / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == row["sha256"], name
    provenance = json.loads((LANE / "PROVENANCE.json").read_text())
    listed = {f["path"]: f["sha256"] for f in provenance["generated"]}
    for name, row in shipped["tiers"]["0"]["files"].items():
        assert listed[f"baked/{name}"] == row["sha256"]


def test_maps_tile_and_the_normal_is_unit_length_directx(baked):
    out, _ = baked
    normal = np.asarray(Image.open(out / "T_AcCoastal_DetailN_512.png"), dtype=float) / 255 * 2 - 1
    assert np.abs(np.linalg.norm(normal, axis=-1) - 1).max() < 0.02
    assert normal[..., 2].min() > 0.9          # a detail map: tilts of a few degrees
    assert abs(normal[..., 0].mean()) < 0.01 and abs(normal[..., 1].mean()) < 0.01
    for array in (normal, np.asarray(Image.open(out / "T_AcCoastal_Mask_512.png"), dtype=float) / 255):
        seam = np.abs(array[:, 0] - array[:, -1]).mean()
        inner = np.abs(array[:, 1] - array[:, 0]).mean()
        assert seam < 3 * inner + 0.01          # the wrap edge is no rougher than the interior
    # green DOWN: below a bump's peak (larger row) the normal's Y is positive
    height = np.zeros((64, 64))
    height[24:40, 24:40] = np.hanning(16)[:, None] * np.hanning(16)[None, :]
    bump = bake.height_to_normal(height, slope=1.0).astype(float) / 255 * 2 - 1
    assert bump[36, 32, 1] > 0.02 and bump[27, 32, 1] < -0.02
    assert bump[32, 36, 0] > 0.02 and bump[32, 27, 0] < -0.02


def test_grime_streaks_run_along_u(baked):
    out, _ = baked
    grime = np.asarray(Image.open(out / "T_AcCoastal_Mask_512.png"), dtype=float)[..., 2]
    along_u = np.abs(np.diff(grime, axis=1)).mean()
    along_v = np.abs(np.diff(grime, axis=0)).mean()
    assert along_v > 4 * along_u


def test_no_dark_aircraft_and_albedo_in_calibrated_range(baked):
    out, manifest = baked
    lo, hi = manifest["albedo_range_linear"]
    assert 0.0 < lo < 0.05 and hi == 0.9
    assert lo == pytest.approx(max(bake.TIRE_ALBEDO), abs=1e-4)   # the pinned database row
    m = np.asarray(Image.open(out / "T_AcCoastal_Mask_512.png"), dtype=float) / 255
    for base in (0.0, 0.02, 0.05, 0.18, 0.5, 0.9, 1.0):
        albedo, rough, coat = bake.weather(base, m[..., 0], m[..., 1], m[..., 2])
        assert albedo.min() >= lo - 1e-9 and albedo.max() <= hi + 1e-9
        assert rough.min() >= bake.COASTAL_SCALARS["RoughnessMin"] and rough.max() <= 1
        assert coat.min() >= 0.1 - 1e-9 and coat.max() <= 1
        if lo < base <= hi:
            assert albedo.min() >= base * (1 - bake.MAX_TEXEL_DARKENING)
    report = manifest["tiers"]["0"]["albedo"]
    band = bake.MEAN_ALBEDO_BAND
    assert band[0] <= report["grey_card_0.18"]["mean_ratio"] <= band[1]
    assert report["dark_livery_0.05"]["mean_ratio"] >= 1.0     # a dark livery never gets darker on average
    assert report["white_0.9"]["mean_ratio"] >= band[0]
    # the worst case the parameters allow, whatever the mask holds
    p = bake.COASTAL_SCALARS
    worst = p["GrimeDarkening"] * max(c["GrimeAmount"] for c in bake.CLASS_OVERRIDES.values())
    assert worst <= bake.MAX_TEXEL_DARKENING
    # RGB base keeps its hue order under a little salt
    rgb, _, _ = bake.weather(np.array([0.5, 0.1, 0.1]), 1.0, 0.5, 0.0)
    assert rgb[0] > rgb[1] and rgb.shape == (3,)


def test_weathering_off_is_the_identity():
    off = dict(bake.COASTAL_SCALARS, CoastalWeathering=0.0)
    albedo, rough, coat = bake.weather(0.3, 1.0, 1.0, 1.0, roughness=0.4, p=off)
    assert (float(albedo), float(rough), float(coat)) == pytest.approx((0.3, 0.4, 0.1))


def test_tier_table_and_estimates():
    sizes = [bake.est_vram_mb(t) for t in sorted(bake.TIERS)]
    assert sizes == sorted(sizes) and sizes[0] == pytest.approx(0.5, abs=0.01)
    assert sizes[0] < 0.01 * 491                 # tier 0 under 1 % of the streaming pool
    assert bake.TIERS[0]["samples"] == 2
    for tier in bake.TIERS.values():
        assert tier["normal_px"] <= 4096 and tier["mask_format"] in bake.BPP


def test_shader_twin_names_every_parameter_and_stays_sm5():
    source = (LANE / "coastal_weathering.ush").read_text()
    for name in bake.COASTAL_SCALARS:
        assert re.search(rf"\b{name}\b", source), name
    code = "\n".join(line.split("//")[0] for line in source.splitlines())
    assert code.count(".Sample(") == bake.TIERS[0]["samples"]
    for banned in ("for (", "while (", "ddx", "ddy", "SampleLevel", "TraceRay", "discard"):
        assert banned not in code, banned
    assert "clamp(Albedo, AlbedoMin, AlbedoMax)" in code


def test_provenance_is_complete_and_commercially_usable():
    provenance = json.loads((LANE / "PROVENANCE.json").read_text())
    assert provenance["visual_only"] is True
    for source in provenance["sources"]:
        assert source["licence"] and "NC" not in source["licence"].upper().replace("-", " ").split()
        assert re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
    pin = json.loads((REPO / "assets/looks/physically_based/PIN.json").read_text())
    assert provenance["sources"][0]["sha256"] == pin["files"]["materials.json"]["sha256"]
    assert provenance["sources"][0]["commit"] == pin["commit"]
    assert provenance["third_party_code_vendored"] == []


def _frame(path, body, seed, detail=0.0):
    rng = np.random.default_rng(seed)
    image = np.full((200, 300), 120.0)
    image[50:150, 60:240] = body + detail * rng.standard_normal((100, 180))
    Image.fromarray(np.clip(image, 0, 255).astype(np.uint8)).save(path)


def test_gate_arithmetic_on_synthetic_images_only(tmp_path):
    """The script's arithmetic and refusals on made-up images. This is NOT
    evidence that real renders differ or pass: that is the Windows gate."""
    ids = np.full((200, 300), 2, np.uint8)        # terrain, int_id 2, everywhere else
    ids[:20] = 0                                  # sky / background
    ids[50:150, 60:240] = 1                       # the airframe
    Image.fromarray(ids).save(tmp_path / "mask.png")
    _frame(tmp_path / "ref.png", 140, 1, detail=2.0)
    _frame(tmp_path / "good.png", 141, 2, detail=4.0)
    _frame(tmp_path / "dark.png", 110, 3, detail=4.0)
    good = gate.measure(tmp_path / "ref.png", tmp_path / "good.png", tmp_path / "mask.png")
    assert good["pass"] and good["detail_ratio"] > 1.5
    assert good["aircraft_ids"] == [1] and good["aircraft_pixels"] == 100 * 180
    dark = gate.measure(tmp_path / "ref.png", tmp_path / "dark.png", tmp_path / "mask.png")
    assert not dark["pass"] and not dark["checks"]["no_dark_regression"]
    # same scene, different noise (what an unwired switch looks like): a FAIL
    _frame(tmp_path / "again.png", 140, 9, detail=2.0)
    again = gate.measure(tmp_path / "ref.png", tmp_path / "again.png", tmp_path / "mask.png")
    assert not again["pass"] and not again["checks"]["detail_improved"]
    # the very same pixels, an empty ID image and a wrong-size one are refusals
    Image.fromarray(np.zeros((200, 300), np.uint8)).save(tmp_path / "empty.png")
    Image.fromarray(np.ones((100, 150), np.uint8)).save(tmp_path / "small.png")
    for after, mask in (("ref.png", "mask.png"), ("good.png", "empty.png"), ("good.png", "small.png")):
        with pytest.raises(SystemExit) as refused:
            gate.measure(tmp_path / "ref.png", tmp_path / after, tmp_path / mask)
        assert refused.value.code == gate.REFUSED


def test_gate_ignores_everything_that_is_not_the_airframe(tmp_path):
    ids = np.full((200, 300), 2, np.uint8)
    ids[50:150, 60:240] = 1
    Image.fromarray(ids).save(tmp_path / "mask.png")
    rng = np.random.default_rng(4)
    ref = np.full((200, 300), 120.0)
    ref[50:150, 60:240] = 140 + 2.0 * rng.standard_normal((100, 180))
    cand = ref.copy()
    cand[ids == 2] = 30 + 40 * rng.standard_normal(int((ids == 2).sum()))   # terrain goes dark and noisy
    cand[60, 70] += 1                                                    # one airframe pixel differs
    for name, image in (("ref.png", ref), ("cand.png", cand)):
        Image.fromarray(np.clip(image, 0, 255).astype(np.uint8)).save(tmp_path / name)
    row = gate.measure(tmp_path / "ref.png", tmp_path / "cand.png", tmp_path / "mask.png")
    assert row["luma_ratio"] == pytest.approx(1.0, abs=0.001) and row["dark_share_delta"] == 0
    assert row["detail_ratio"] == pytest.approx(1.0, abs=0.01) and not row["pass"]
    both = gate.measure(tmp_path / "ref.png", tmp_path / "cand.png", tmp_path / "mask.png", ids=(1, 2))
    assert both["luma_ratio"] < 0.6                # the terrain only counts when asked for


def test_windows_command_sets_the_switch_and_uses_the_sheet_s_own_files():
    script = (LANE / "run_gate.ps1").read_text()
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert 'Render-Step $RefStep "0"' in code and 'Render-Step $NewStep "1"' in code
    assert "FLIGHTSIM_COASTAL_WEATHERING" in code and "Select-String" in code
    assert "${Shot}_mask.png" in code and ".Replace(" not in code and "-Recurse" not in code
    assert "--ids $Ids" in code
    # the names it relies on are the ones the contact sheet writes
    sheet = (REPO / "experiments/visual_contact_sheet.py").read_text()
    assert 'directory / f"{key}.png"' in sheet and 'directory / f"{key}_mask.png"' in sheet
    # the airframe id it defaults to is the one the label schema states
    assert "always int_id 1" in (REPO / "core/capture/labels.py").read_text()
    assert gate.AIRFRAME_IDS == (1,)
    # the switch is not in the shared tree yet: the gate must say so, not pretend
    if "FLIGHTSIM_COASTAL_WEATHERING" not in (REPO / "scripts/aircraft_look.py").read_text():
        notes = (LANE / "INTEGRATION.md").read_text()
        assert "cannot run until change 6" in notes and "Today it\n   refuses" in notes
