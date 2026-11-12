"""Code-level checks for swarm lane aircraft_exterior.decals_wear.alpine.

Runs on the Mac: generator arithmetic, file formats, the dark-aircraft guard
in the numpy mirror of the shader, and the pixel gate's arithmetic on
synthetic frames. None of this is a rendered or visual result.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import numpy as np
import pytest

LANE = Path(__file__).resolve().parents[1] / "swarm/lanes/aircraft_exterior/decals_wear/alpine"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"alpine_wear_{name}", LANE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bake = _load("bake_decals_wear")
gate = _load("pixel_gate")

PAINTS = {"white": (0.80, 0.80, 0.80), "grey": (0.30, 0.31, 0.33), "red": (0.50, 0.03, 0.03),
          "navy": (0.02, 0.03, 0.10)}


@pytest.fixture(scope="module")
def mask():
    return bake.bake_mask(256)


def _seam_ok(img):
    """Wrap-edge steps are no larger than the interior's steps."""
    for axis in (0, 1):
        interior = np.abs(np.diff(img, axis=axis)).mean()
        seam = np.abs(np.take(img, 0, axis=axis) - np.take(img, -1, axis=axis)).mean()
        assert seam < 2.5 * interior + 1e-6


def test_mask_range_tileable_deterministic(mask):
    assert mask.shape == (256, 256, 3)
    assert mask.min() >= 0.0 and mask.max() <= 1.0
    _seam_ok(mask)
    assert np.array_equal(mask, bake.bake_mask(256))
    assert not np.array_equal(mask, bake.bake_mask(256, seed=1))


def test_mask_channels_look_like_what_they_claim(mask):
    grime, chips, frost = (mask[..., i] for i in range(3))
    assert 0.10 < grime.mean() < 0.45
    assert 0.01 < (chips > 0.5).mean() < 0.07          # sparse flecks
    assert 0.2 < frost.mean() < 0.8
    # Streaks run along U (aft): far smoother along x than across.
    assert np.abs(np.diff(grime, axis=1)).mean() < 0.5 * np.abs(np.diff(grime, axis=0)).mean()


@pytest.mark.parametrize("paint", sorted(PAINTS))
def test_no_dark_aircraft_guard(mask, paint):
    p = bake.PARAMS
    a0 = np.broadcast_to(np.array(PAINTS[paint]), mask.shape)
    worn = bake.apply_wear(a0, mask[..., 0], mask[..., 1])   # full placement weight, no frost
    assert (worn >= a0 * p["WearFloorRatio"] - 1e-9).all()
    assert (worn >= np.minimum(a0, p["AlbedoMin"]) - 1e-9).all()
    assert (worn <= np.maximum(a0, p["AlbedoMax"]) + 1e-9).all()
    ratio = bake.luminance(worn).mean() / bake.luminance(a0).mean()
    if paint in ("white", "grey"):
        assert 0.90 <= ratio <= 1.02      # dirtier, never a dark aircraft
    else:
        assert ratio >= 0.90              # primer chips may brighten dark paint


def test_frost_brightens_toward_snow_and_stays_in_range(mask):
    a0 = np.broadcast_to(np.array(PAINTS["grey"]), mask.shape)
    frosted = bake.apply_wear(a0, mask[..., 0], mask[..., 1], frost=mask[..., 2])
    plain = bake.apply_wear(a0, mask[..., 0], mask[..., 1])
    assert bake.luminance(frosted).mean() > bake.luminance(plain).mean()
    assert frosted.max() <= bake.PARAMS["AlbedoMax"] + 1e-9


def test_soot_and_ink_darken_only_to_their_own_floor():
    p = bake.PARAMS
    white = np.array([PAINTS["white"]])
    soot = bake.apply_wear(white, 0.0, 0.0, soot=1.0)
    ink = bake.apply_wear(white, 0.0, 0.0, decal=1.0)
    assert np.allclose(soot, white * (p["WearFloorRatio"] + (p["SootFloorRatio"] - p["WearFloorRatio"]) * p["SootAmount"]))
    assert soot.min() >= p["AlbedoMin"] and ink.min() >= p["AlbedoMin"]
    assert bake.luminance(ink)[0] < 0.2 * bake.luminance(white)[0]
    assert np.allclose(bake.apply_wear(white, 0.0, 0.0), white)   # no masks, no change


def test_normal_map_unit_and_gentle():
    n = bake.bake_normal(128)
    assert np.allclose(np.linalg.norm(n, axis=-1), 1.0)
    assert n[..., 2].min() > 0.8
    assert n[..., :2].std() > 1e-3
    _seam_ok(n)


def test_soot_lut_is_a_decaying_spreading_plume():
    s = bake.bake_soot()
    assert s.shape == (64, 256) and 0.0 <= s.min() and s.max() <= 1.0
    centre = s[32]
    peak = int(centre.argmax())
    assert peak < 30 and (np.diff(centre[peak:]) <= 1e-9).all()
    assert s[:, 0].max() < 0.2 and s[:, -1].max() < 1e-3 and s[0].max() < 0.05   # clamp-safe edges
    width = lambda col: (s[:, col] > 0.5 * s[:, col].max()).sum()  # noqa: E731
    assert width(200) > width(20)


def test_decal_atlas_rows():
    d = bake.bake_decals()
    assert d.shape == (256, 512) and d.min() >= 0.0 and d.max() == 1.0
    for i in range(len(bake.DECAL_ROWS)):
        row = d[i * 64:(i + 1) * 64]
        assert 0.03 < row.mean() < 0.5
        assert row[0].max() == 0 and row[-1].max() == 0     # no bleed between rows
    assert set("".join(r for r in bake.DECAL_ROWS if not r.startswith("@"))) <= set(bake._GLYPHS)
    assert all(len(g.split()) == 7 and all(len(b) == 5 for b in g.split()) for g in bake._GLYPHS.values())


def test_bake_writes_readable_pngs_and_manifest(tmp_path):
    from PIL import Image

    old = dict(bake.TIER_SIZE)
    bake.TIER_SIZE.update({0: 64, 1: 64})
    try:
        m0 = bake.bake(0, tmp_path / "t0")
        m1 = bake.bake(1, tmp_path / "t1")
    finally:
        bake.TIER_SIZE.update(old)
    assert list(m0["sha256"]) == ["T_AlpineWear_Mask.png"]
    assert set(m1["sha256"]) == {"T_AlpineWear_Mask.png", "T_AlpineWear_N.png",
                                 "T_AlpineWear_Soot.png", "T_AlpineWear_Decals.png"}
    assert m0["sha256"]["T_AlpineWear_Mask.png"] == m1["sha256"]["T_AlpineWear_Mask.png"]
    img = Image.open(tmp_path / "t1" / "T_AlpineWear_Mask.png")
    assert img.mode == "RGB" and img.size == (64, 64)
    assert np.abs(np.asarray(img) / 255.0 - bake.bake_mask(64)).max() <= 0.5 / 255 + 1e-9
    assert Image.open(tmp_path / "t1" / "T_AlpineWear_Decals.png").mode == "L"
    on_disk = json.loads((tmp_path / "t0" / "bake_manifest.json").read_text())
    assert on_disk["visual_only"] is True and on_disk["wear"]["stamp"].startswith("UNCALIBRATED")
    assert on_disk["wear"]["constants"]["FrostAmount"] == 0.0


def test_shader_names_match_generator_params():
    ush = (LANE / "alpine_wear.ush").read_text()
    struct = re.search(r"struct FAlpineWearParams\s*\{(.*?)\};", ush, re.S).group(1)
    fields = set(re.findall(r"\b(\w+);", struct))
    assert fields == set(bake.PARAMS)
    for banned in ("WorldPositionOffset", "Opacity", "for (", "while ("):
        assert banned not in ush.split("#ifndef")[1]
    assert "max(A, Albedo * lerp(W.WearFloorRatio, W.SootFloorRatio, Dark))" in ush


def test_tiers_and_provenance():
    tiers = json.loads((LANE / "tiers.json").read_text())
    assert [t["tier"] for t in tiers["tiers"]] == [0, 1, 2, 3]
    est = [t["est_vram_mb"] for t in tiers["tiers"]]
    assert est == sorted(est) and est[0] < 1.0 and est[-1] < 0.05 * tiers["budget_usable_vram_mb"]
    assert [t["mask_px"] for t in tiers["tiers"]] == [bake.TIER_SIZE[i] for i in range(4)]
    assert "UNMEASURED" in tiers["status"]
    sp = tiers["shared_params"]
    assert sp["ground_albedo_snow"]["value"] == bake.PARAMS["FrostAlbedo"]
    assert sp["wear_floor_ratio"]["value"] == bake.PARAMS["WearFloorRatio"]
    assert sp["wear_tile_cm"]["value"] == bake.PARAMS["WearTileCm"]
    prov = json.loads((LANE / "PROVENANCE.json").read_text())
    assert prov["fetched_assets"] == [] and prov["vendored_code"] == [] and prov["visual_only"] is True
    integ = (LANE / "INTEGRATION.md").read_text()
    assert "UNMEASURED" in integ and "BLOCKED" in integ and "run_gate.cmd" in integ
    assert tiers["gate"]["switch_default"] == "off" and "BLOCKED" in tiers["gate"]["status"]


def _frames(seed=0):
    rng = np.random.default_rng(seed)
    h, w = 96, 128
    alb = np.full((h, w, 3), 0.15)
    alb[30:60, 40:90] = 0.80                              # a white airframe over rock
    m = bake.bake_mask(128)[:h, :w]
    cand = alb.copy()
    cand[30:60, 40:90] = bake.apply_wear(alb[30:60, 40:90], m[30:60, 40:90, 0], m[30:60, 40:90, 1])
    enc = lambda a: np.clip(np.rint(255 * np.clip(a, 0, 1) ** (1 / 2.2)), 0, 255).astype(np.uint8)  # noqa: E731
    return alb, cand, enc(alb + rng.normal(0, 0.002, alb.shape)), enc(cand), enc


def test_pixel_gate_passes_wear_and_fails_dark_or_absent():
    alb, cand, b_ref, b_cand, enc = _frames()
    good = gate.evaluate(alb, cand, b_ref, b_cand)
    assert good["ok"], good
    assert good["detail_gain"] >= 1.25 and good["beauty_ratio"] >= 0.90

    same = gate.evaluate(alb, alb, b_ref, b_ref)
    assert not same["ok"] and same["failed"] == ["changed_fraction"]

    dark = alb.copy()
    dark[30:60, 40:90] = 0.02                             # the black-airframe regression
    bad = gate.evaluate(alb, dark, b_ref, enc(dark))
    assert not bad["ok"] and {"beauty_ratio", "dark_fraction"} <= set(bad["failed"])

    leak = cand * 0.9                                     # the whole frame moved: terrain too
    assert "changed_fraction" in gate.evaluate(alb, leak, b_ref, enc(leak))["failed"]


def _write_run(root, albedo, beauty_u8, wear):
    from core.capture.labels import write_rgb16_png
    from PIL import Image

    cam = root / "cam0"
    cam.mkdir(parents=True)
    write_rgb16_png(cam / "frame_0000_albedo.png", np.rint(np.clip(albedo, 0, 1) * 65535).astype(np.uint16))
    Image.fromarray(beauty_u8).save(cam / "frame_0000.png")
    if wear is not None:
        (cam / "render.json").write_text(json.dumps({"look_applied": {"aircraft_wear": wear}}))
    return root


def test_gate_main_separates_not_measured_from_wear_failure(tmp_path, capsys):
    """main() on synthetic run folders through the repo's 16-bit PNG reader.
    Code check only: the engine's own files have never been read by it."""
    alb, cand, b_ref, b_cand, enc = _frames()
    ref = _write_run(tmp_path / "ref", alb, b_ref, "off")
    good = _write_run(tmp_path / "good", cand, b_cand, "tier0")
    assert gate.main(["--reference", str(ref), "--candidate", str(good)]) == 0

    # the switch is not integrated: the engine states nothing, both runs identical
    bare_ref = _write_run(tmp_path / "bare_ref", alb, b_ref, None)
    bare = _write_run(tmp_path / "bare", alb, b_ref, None)
    assert gate.main(["--reference", str(bare_ref), "--candidate", str(bare)]) == 3
    assert "not_measured" in capsys.readouterr().out

    # the value "off " (cmd's trailing space) or the wrong tier is not proof either
    spaced = _write_run(tmp_path / "spaced", alb, b_ref, "off ")
    assert gate.main(["--reference", str(spaced), "--candidate", str(good)]) == 3
    assert gate.main(["--reference", str(ref), "--candidate", str(good), "--expect", "tier1"]) == 3

    # the engine says tier0 but drew nothing
    same = _write_run(tmp_path / "same", alb, b_ref, "tier0")
    assert gate.main(["--reference", str(ref), "--candidate", str(same)]) == 3

    # wear drawn and too dark: the only case that is a wear failure
    dark = alb.copy()
    dark[30:60, 40:90] = 0.02
    bad = _write_run(tmp_path / "bad", dark, enc(dark), "tier0")
    assert gate.main(["--reference", str(ref), "--candidate", str(bad)]) == 1


def test_run_gate_cmd_is_guarded_and_quotes_the_switch():
    cmd = (LANE / "run_gate.cmd").read_text()
    assert 'set "FLIGHTSIM_AIRCRAFT_WEAR=off"' in cmd and 'set "FLIGHTSIM_AIRCRAFT_WEAR=%TIER%"' in cmd
    assert not re.search(r"set FLIGHTSIM_AIRCRAFT_WEAR=\S+ *&&", cmd)
    assert cmd.index("findstr") < cmd.index("flightsim.capture") and "exit /b 4" in cmd
    assert "--passes albedo" in cmd and "--expect %TIER%" in cmd
    # while the switch is only a proposal, the lane must say the gate is blocked
    flags = (LANE.parents[4] / "core/render/flags.py").read_text()
    if "FLIGHTSIM_AIRCRAFT_WEAR" not in flags:
        assert "does not exist yet" in (LANE / "INTEGRATION.md").read_text()
