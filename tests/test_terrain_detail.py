"""Lane B (2026-11-11): the non-urban terrain detail and the beauty ocean.

The committed CC0 maps hash to their pins and are listed in
THIRD_PARTY_VISUAL.md; the detail and ocean shaders read exactly what
scripts/ue_create_materials.py wires, their shared blocks are one copy, their
tile sizes are the pins'; the generated ocean normal is what its generator
writes; the C++ draws the beauty sea with the new material and sets the
snowline's altitude. Nothing here runs the engine.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
PIN = json.loads((REPO / "assets" / "terrain_detail" / "PIN.json").read_text(encoding="utf-8"))
SHADERS = REPO / "assets" / "shaders" / "world"
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
TILES_CPP = (BRIDGE / "Private" / "FlightSimGoogleTiles.cpp").read_text(encoding="utf-8")


def _literal(name):
    tree = ast.parse(SCRIPT)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value) if not isinstance(node.value, ast.DictComp) else eval(  # noqa: S307
                compile(ast.Expression(node.value), name, "eval"))
    raise AssertionError(name)


def _files():
    for role, row in list(PIN["roles"].items()) + [("ocean", PIN["ocean"])]:
        for kind, entry in row["files"].items():
            yield role, row, kind, entry


def _shader(name):
    return (SHADERS / f"{name}.hlsl").read_text(encoding="utf-8")


def _block(text, begin, end):
    return text[text.index(begin):text.index(end)]


def test_every_pinned_file_hashes_to_its_pin_and_is_cc0():
    assert set(PIN["roles"]) == set(_literal("TERRAIN_DETAIL_ROLES"))
    for role, row, kind, entry in _files():
        data = (REPO / entry["path"]).read_bytes()
        assert len(data) == entry["size"], entry["path"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["path"]
        assert row["licence"] == "CC0-1.0", role
        if role != "ocean":
            assert entry["url"].startswith("https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/"), entry["url"]
            assert hashlib.md5(data).hexdigest() == entry["md5"], entry["path"]  # noqa: S324 (the API's pin)
    # 1K maps only: the repository stays light.
    assert sum(e["size"] for _, _, _, e in _files()) < 12_000_000


def test_every_pin_is_listed_and_byte_exact_on_windows():
    third_party = (REPO / "THIRD_PARTY_VISUAL.md").read_text(encoding="utf-8")
    for _, _, _, entry in _files():
        assert entry["sha256"] in third_party, entry["path"]
    assert "assets/terrain_detail/** -text" in (REPO / ".gitattributes").read_text(encoding="utf-8")
    assert "Megascans" not in json.dumps(PIN) and "fab.com" not in json.dumps(PIN)


def test_the_detail_shaders_read_what_the_script_wires():
    inputs = _literal("WORLD_TILES_DETAIL_INPUTS")
    scalars = set(_literal("WORLD_TILES_DETAIL_SCALARS"))
    collection = set(_literal("WORLD_COLLECTION_SCALARS"))
    textures = {f"{role.capitalize()}{kind}" for role in PIN["roles"] for kind in "DN"}
    engine = {"Albedo", "AlbedoMid", "AlbedoLow", "WorldPos", "CameraPos", "NormalWS"}
    noise = _block(_shader("tiles_base_colour"), "// shared: world noise", "// end shared")
    shared = None
    for name, pins in inputs.items():
        hlsl = _shader(name)
        for pin in pins:
            assert re.search(rf"//\s+{pin}\s", hlsl), (name, pin)
            assert pin in engine | scalars | collection | textures, (name, pin)
        assert _block(hlsl, "// shared: world noise", "// end shared") == noise, name
        block = _block(hlsl, "// shared: terrain detail", "// end terrain detail")
        shared = block if shared is None else shared
        assert block == shared, f"{name}: the shared terrain detail differs"
        assert "static const" not in hlsl and "UNCALIBRATED" in hlsl and "BEAUTY ONLY" in hlsl
        # the tile sizes are the pins'
        for role, row in PIN["roles"].items():
            assert f"const float {role.upper()}_TILE_M = {row['tile_m']};" in hlsl, (name, role)
        # derivatives before any branch: explicit-gradient samples only
        assert ".Sample(" not in hlsl and "SampleGrad" in hlsl
    assert {p for pins in inputs.values() for p in pins} >= textures
    assert "SharpenMipBias" in scalars   # the blur's mip bias is a material scalar the graph reads


def test_the_tiles_material_wires_the_detail_and_can_be_built_without_it():
    create = SCRIPT[SCRIPT.index("def create_world_tiles_beauty"):SCRIPT.index("def create_world_scatter")]
    assert "detail_normal = world_tiles_detail(material, lib, common, uv, factor)" in create
    assert create.index('"tiles_delight"') < create.index("world_tiles_detail(") < create.index("for row, (shader")
    assert 'pins["NormalWS"] = (detail_normal, "")' in create
    assert 'common["Albedo"] = (surface, "")' in create
    assert 'TERRAIN_DETAIL_ENV = "FLIGHTSIM_TERRAIN_DETAIL"' in SCRIPT
    assert "-no-detail" in create   # stamped apart: the next run with the detail builds it again
    # a file off its pin is never imported
    assert "hashes {digest}, its pin is" in create
    # no WPO in the tiles material: the labels' geometry is the tiles'
    tiles = SCRIPT[SCRIPT.index("def create_world_tiles_beauty"):SCRIPT.index("def create_world_ocean_beauty")]
    assert "MP_WORLD_POSITION_OFFSET" not in tiles


def test_the_ocean_material_is_beauty_only_and_reads_what_the_script_wires():
    assert "M_FlightSimOceanBeauty" in _literal("WORLD_BEAUTY_MATERIALS")
    # 2: round 10's #13 (a tile grid and screen-space reflection streaks);
    # 3: round 19's #13 (the cap's radial edges as lines, no waves or glint)
    # 4: round 26's #13 (the tiles' ocean still over the cap): the depth pull
    # 5: hyperreal stormsea: the card's wind wired, the storm foam / swell / body
    assert _literal("WORLD_GENERATIONS")["M_FlightSimOceanBeauty"] == "6"
    assert _literal("WORLD_OCEAN_DEPTH_PULL") == 0.01
    ocean = SCRIPT[SCRIPT.index("def create_world_ocean_beauty"):SCRIPT.index("def create_world_scatter")]
    # the only WPO: each vertex along its own line of sight (camera - vertex), so its pixel stays
    assert ocean.count("MP_WORLD_POSITION_OFFSET") == 1
    assert "MaterialExpressionCameraPositionWS, -1500, 1200" in ocean and '"DepthPull", WORLD_OCEAN_DEPTH_PULL' in ocean
    # the sea cap is a beauty-only actor (no label pass draws it)
    assert "BeautyOnlyActors.Add(SeaActor);" in TILES_CPP and 'TEXT("tiles_height_probes")' in TILES_CPP
    for name in ("ocean_normal", "ocean_emissive", "ocean_colour"):
        hlsl = _shader(name)
        # shaded from the sphere's up, never the cap's interpolated vertex normals
        assert "float3 up = S.Up(p);" in hlsl and "normalize(NormalWS)" not in hlsl, name
        assert "swellTilt = S.Swell(p.xy, windDir, TimeS, footprintM);" in hlsl, name
    assert "SHEEN_SHARE" in _shader("ocean_emissive")
    inputs = _literal("WORLD_OCEAN_INPUTS")
    assert set(inputs) == {"ocean_normal", "ocean_emissive", "ocean_colour"}
    assert not (SHADERS / "ocean_roughness.hlsl").exists()
    scalars = set(_literal("WORLD_OCEAN_SCALARS"))
    engine = {"WorldPos", "CameraPos", "NormalWS", "TimeS", "SunDir", "SunIlluminance", "SkyLum", "OceanN"}
    shared = None
    for name, pins in inputs.items():
        hlsl = _shader(name)
        for pin in pins:
            assert re.search(rf"//\s+{pin}\s", hlsl), (name, pin)
            assert pin in scalars | engine, (name, pin)
        block = _block(hlsl, "// shared: ocean", "// end shared")
        shared = block if shared is None else shared
        assert block == shared, f"{name}: the shared ocean block differs"
        assert "0.003 + 0.00512 * max(windMs, 0.0)" in hlsl   # Cox & Munk 1954, clean sea
        assert "3.84e-6 * pow(max(WindSpeedMS, 0.0), 3.41)" in hlsl   # Monahan & O'Muircheartaigh 1980
        # the tile's own trilinear sampler (never the shared point-mip one), and
        # no octave coarser than 256 m: from 10 km the tile is not drawn at all
        assert "View.MaterialTextureBilinearWrapedSampler" not in hlsl and "OceanNSampler" in hlsl
        assert "1357.0" not in hlsl and "float tiles[2] = {256.0, 54.0};" in block
    emissive = _shader("ocean_emissive")
    assert "0.02 + 0.98 * pow(1.0 - nv, 5.0)" in emissive        # Schlick, water F0 0.02
    assert "float alpha = sqrt(variance);" in emissive           # the glint's width is Cox-Munk's
    # the engine's specular is off: no screen-space reflection on the sea
    assert _literal("WORLD_OCEAN_SPECULAR") == 0.0 and _literal("WORLD_OCEAN_ROUGHNESS") == 1.0
    create = SCRIPT[SCRIPT.index("def create_world_ocean_beauty"):SCRIPT.index("def create_world_scatter")]
    assert "MP_EMISSIVE_COLOR" in create and "MP_ROUGHNESS" in create
    for node in ("SkyAtmosphereLightDirection", "SkyAtmosphereLightIlluminance",
                 "SkyAtmosphereDistantLightScatteredLuminance"):
        assert f"unreal.MaterialExpression{node}" in create, node
    assert re.search(r"^create_world_ocean_beauty\(\)", SCRIPT, re.M)
    # M_Ground_Ocean (the flat scene's measure ground) is left as it was
    ground = SCRIPT[SCRIPT.index("def create_ground("):SCRIPT.index("def create_ground_surfaces")]
    assert "OCEAN_WAVES" in ground and "ocean_normal" not in ground


def test_the_beauty_sea_draws_the_beauty_material_first():
    body = TILES_CPP[TILES_CPP.index("FFlightSimGoogleTiles::ApplyBeautyGround"):]
    assert body.index("OceanBeautyPath) : nullptr") < body.index("LoadObject<UMaterialInterface>(nullptr, OceanGroundPath)")
    assert 'TEXT("/Game/FlightSim/M_FlightSimOceanBeauty.M_FlightSimOceanBeauty")' in body
    # round 19: the cap fine enough and lifted with the camera, so the tiles'
    # own ocean never stands above it (its sag let only its edges show)
    assert "constexpr int32 SeaRings = 128;" in TILES_CPP and "constexpr int32 SeaSegments = 256;" in TILES_CPP
    assert "FMath::Clamp(SeaLiftPerAglM * CameraAglM, SeaLiftM, SeaLiftMaxM)" in body
    assert "Vertices.Add(FVector(X, Y, LiftM - Drop) * CmPerM);" in body


def test_the_finer_tiles_are_beauty_only_and_a_stated_error_wins():
    look = TILES_CPP[TILES_CPP.index("FFlightSimGoogleTiles::ApplyBeautyLook"):
                     TILES_CPP.index("FFlightSimGoogleTiles::ApplyBeautyGround")]
    assert 'EnvNumber(TEXT("FLIGHTSIM_GOOGLE_TILES_BEAUTY_SSE"), 6.0)' in look
    assert "if (!bStated && BeautySse < MaximumScreenSpaceError)" in look
    # the measure's own default is unchanged
    assert 'EnvNumber(TEXT("FLIGHTSIM_GOOGLE_TILES_SSE"), 8.0)' in TILES_CPP


def _png_pixels(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, width, height = 8, b"", 0, 0
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", body[:10])
            assert (depth, colour) == (8, 2)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = 3 * width + 1
    assert all(raw[r * stride] == 0 for r in range(height))   # filter 0, as the generator writes
    return b"".join(raw[r * stride + 1:(r + 1) * stride] for r in range(height))


def test_the_ocean_normal_is_its_generators_output(tmp_path):
    meta = json.loads((REPO / "assets" / "terrain_detail" / "ocean" / "ocean_normal.json").read_text(encoding="utf-8"))
    png = (REPO / PIN["ocean"]["files"]["normal_gl"]["path"]).read_bytes()
    assert hashlib.sha256(_png_pixels(png)).hexdigest() == meta["pixels_sha256"]
    assert PIN["ocean"]["tile_m"] == meta["patch_m"] == 256.0
    subprocess.run([sys.executable, "-I", str(REPO / "scripts" / "make_ocean_normal.py"), "--out", str(tmp_path)],
                   check=True, capture_output=True)
    again = json.loads((tmp_path / "ocean_normal.json").read_text(encoding="utf-8"))
    assert again["pixels_sha256"] == meta["pixels_sha256"]


def test_the_snowline_altitude_is_set_from_the_tiles_origin():
    clouds = (BRIDGE / "Private" / "FlightSimClouds.cpp").read_text(encoding="utf-8")
    assert '{TEXT("GroundAltitudeM"), Tiles.GetOriginOrthometricHeightM()}' in clouds
    header = (BRIDGE / "Public" / "FlightSimGoogleTiles.h").read_text(encoding="utf-8")
    assert "double GetOriginOrthometricHeightM() const { return OriginEllipsoidHeightM - UndulationM; }" in header


def test_generation_8_filters_the_detail_to_the_footprint_and_keeps_the_colour():
    """Hyperreal terrain detail (2026-11-15): #02's grey, salt-and-pepper trees
    and #01's flat brown. The role maps are filtered to a texel of a few pixels
    (never the display's one texel per pixel), the luminance ratio is compressed
    and bounded, the unsharp mask moves the luma only (the texel's chromaticity
    is exact), the grass map is mostly cut on forest, the tile relief comes from
    the footprint-filtered AlbedoMid with a bounded step, and the crowns are
    parabolic domes shown only where one spans several pixels."""
    # 9: the relief step's bound made true (test_generation_9_... below computes it)
    assert int(_literal("WORLD_GENERATIONS")["M_FlightSimTilesBeauty"]) >= 9
    surface = _shader("tiles_detail_surface")
    normal = _shader("tiles_detail_normal")
    for hlsl in (surface, normal):
        # the sampler's gradients are the pixel's x DETAIL_TEXEL_PX, before any sample
        assert "const float DETAIL_TEXEL_PX = 2.5;" in hlsl
        assert "dpx *= DETAIL_TEXEL_PX;" in hlsl and "dpy *= DETAIL_TEXEL_PX;" in hlsl
        role = hlsl[hlsl.index("Role(Texture2D tex"):hlsl.index("Crown", hlsl.index("Role(Texture2D tex"))]
        assert role.index("dpx *= DETAIL_TEXEL_PX;") < role.index("[unroll]")   # before any sample
        assert "const float FOREST_TEXTURE_CUT = 0.75;" in hlsl
        assert "(1.0 - FOREST_TEXTURE_CUT * forest)" in hlsl
        # the crowns fade in over the same pixel span, as parabolic domes (no vertical rim)
        assert "smoothstep(CROWN_M / CANOPY_VISIBLE_PX_HI, CROWN_M / CANOPY_VISIBLE_PX_LO, footprintM)" in hlsl
        assert "const float CANOPY_VISIBLE_PX_LO = 4.0;" in hlsl and "const float CANOPY_VISIBLE_PX_HI = 10.0;" in hlsl
        assert "sqrt(saturate(1.0 - d" not in hlsl and "sqrt(saturate(1.0 - dot(d, d)))" not in hlsl
    # the ratio: log-space contrast, bounded
    assert "ratio = exp2(DETAIL_CONTRAST * log2(clamp(ratio, 0.25, 4.0)));" in surface
    assert "ratio = clamp(ratio, DETAIL_RATIO_MIN, DETAIL_RATIO_MAX);" in surface
    assert "clamp(ratio, 0.4, 1.8)" not in surface
    # the luma-only unsharp mask: the colour is the input's times one scalar
    assert "float Ls = max(La + SharpenAmount * fade * (La - Lmid), 0.5 * La);" in surface
    assert "float3 sharp = a * (Ls / max(La, 1e-4));" in surface
    assert "(a - max(AlbedoMid, 0.0))" not in surface
    # the relief from the footprint-filtered tile, its step bounded, the forest gain halved
    assert "AlbedoMid" in _literal("WORLD_TILES_DETAIL_INPUTS")["tiles_detail_normal"]
    assert "float relief = T.Lum(max(AlbedoMid, 0.0)) / max(T.Lum(max(AlbedoLow, 0.0)), 0.01);" in normal
    assert "clamp(ddx_fine(relief), -RELIEF_STEP_MAX, RELIEF_STEP_MAX)" in normal
    assert "const float FOREST_BUMP_GAIN = 0.5;" in normal
    # the node body still takes its derivatives before its first branch
    for hlsl in (surface, normal):
        body = hlsl[hlsl.rindex("\n};\n"):]
        assert body.rindex("ddy_fine(") < body.index("[branch]")


# -- generation 8 / 9 arithmetic, in numbers (the string checks above pin the
#    text; these run the laws, like tests/test_tiles_wet_ground.py) ------------


def _consts(name):
    return {k: float(v) for k, v in re.findall(r"const float (\w+) = ([0-9.]+);", _shader(name))}


def _hash2(ix, iy):
    """The shaders' shared Hash2 on integer cells (uint wrap, Murmur-style mix)."""
    m = np.uint64(0xFFFFFFFF)
    qx = (ix.astype(np.int64) & 0xFFFFFFFF).astype(np.uint64)
    qy = (iy.astype(np.int64) & 0xFFFFFFFF).astype(np.uint64)
    h = ((qx * np.uint64(1597334677)) & m) ^ ((qy * np.uint64(3812015801)) & m)
    h = ((h ^ (h >> np.uint64(16))) * np.uint64(2246822519)) & m
    return ((h ^ (h >> np.uint64(13))) & m).astype(np.float64) / 4294967296.0


def _crowns(px, py, crown_m, tilt):
    """Crowns() (the dome height) and CrownTilt() (its horizontal normal) of the
    two shaders over the same jittered cells; also the winning cell's index and
    radius so a finite difference can stay inside one dome."""
    cx, cy = np.floor(px / crown_m), np.floor(py / crown_m)
    best = np.zeros_like(px)
    out = np.zeros(px.shape + (2,))
    win = np.full(px.shape, -1)
    radius_w = np.zeros_like(px)
    for k, (dy, dx) in enumerate([(y, x) for y in (-1, 0, 1) for x in (-1, 0, 1)]):
        ix, iy = cx + dx, cy + dy
        centre_x = (ix + _hash2(ix, iy)) * crown_m
        centre_y = (iy + _hash2(ix + 37.0, iy + 11.0)) * crown_m
        radius = crown_m * (0.45 + 0.25 * _hash2(ix + 71.0, iy + 53.0))
        dxn, dyn = (px - centre_x) / radius, (py - centre_y) / radius
        h = np.clip(1.0 - (dxn * dxn + dyn * dyn), 0.0, 1.0)
        better = h > best
        best = np.where(better, h, best)
        out[..., 0] = np.where(better, dxn * tilt, out[..., 0])
        out[..., 1] = np.where(better, dyn * tilt, out[..., 1])
        win = np.where(better, k, win)
        radius_w = np.where(better, radius, radius_w)
    return best, out, win, radius_w


def test_generation_8_contrast_law_in_numbers():
    """exp2(DETAIL_CONTRAST x log2(x)) then clamp(DETAIL_RATIO_MIN, DETAIL_RATIO_MAX)
    is x^0.6 held to 0.6..1.5: a quarter maps to the floor, one to one, four to
    the ceiling; the law is monotone and never widens the old 0.4..1.8 span."""
    c = _consts("tiles_detail_surface")
    assert c["DETAIL_CONTRAST"] == 0.6 and (c["DETAIL_RATIO_MIN"], c["DETAIL_RATIO_MAX"]) == (0.6, 1.5)

    def law(x):
        r = np.exp2(c["DETAIL_CONTRAST"] * np.log2(np.clip(x, 0.25, 4.0)))
        return np.clip(r, c["DETAIL_RATIO_MIN"], c["DETAIL_RATIO_MAX"])

    assert law(0.25) == c["DETAIL_RATIO_MIN"] and law(1.0) == 1.0 and law(4.0) == c["DETAIL_RATIO_MAX"]
    for x in (0.5, 1.5, 1.9):                                  # inside the band the law is the power
        assert abs(float(law(x)) - x ** c["DETAIL_CONTRAST"]) < 1e-12, x
    assert float(law(2.0)) == 1.5 and 2.0 ** 0.6 > 1.5       # 2^0.6 = 1.516 already meets the ceiling
    xs = np.linspace(0.05, 8.0, 2001)
    ys = law(xs)
    assert np.all(np.diff(ys) >= 0) and ys.min() == 0.6 and ys.max() == 1.5
    # the compression: the old span's ends come in (0.4 -> 0.6, 1.8 -> 1.42)
    assert float(law(0.4)) == 0.6 and 1.4 < float(law(1.8)) < 1.5


def test_generation_8_luma_sharpen_keeps_the_chromaticity_and_is_bounded():
    """a x (Ls / La) with Ls = max(La + S x fade x (La - Lmid), 0.5 La): the
    output's a / Lum(a) is the input's exactly, and the gain is within
    [0.5, 1 + SharpenAmount] for every tile, blur and fade."""
    scalars = _literal("WORLD_TILES_DETAIL_SCALARS")
    s_amount = scalars["SharpenAmount"]
    assert s_amount == 0.6
    lum_w = np.array([0.2126, 0.7152, 0.0722])
    assert "dot(c, float3(0.2126, 0.7152, 0.0722))" in _shader("tiles_detail_surface")
    rng = np.random.default_rng(20261115)
    a = rng.uniform(0.0, 1.5, size=(4000, 3))
    a[:50] *= 1e-3                                             # near-black texels too
    mid = rng.uniform(0.0, 1.5, size=(4000, 3))
    for fade in (0.0, 0.37, 1.0):
        la = a @ lum_w
        lmid = mid @ lum_w
        ls = np.maximum(la + s_amount * fade * (la - lmid), 0.5 * la)
        gain = ls / np.maximum(la, 1e-4)
        sharp = a * gain[:, None]
        # the gain band
        assert np.all(gain >= 0.5 - 1e-12) and np.all(gain <= 1.0 + s_amount * fade + 1e-12)
        # chromaticity exact: a / Lum(a) is unchanged wherever the luma is not degenerate
        keep = la > 1e-4
        chroma_in = a[keep] / la[keep, None]
        chroma_out = sharp[keep] / (sharp[keep] @ lum_w)[:, None]
        assert np.allclose(chroma_in, chroma_out, rtol=0, atol=1e-9)
        # and the luma itself is Ls
        assert np.allclose(sharp @ lum_w, ls * np.minimum(la / np.maximum(la, 1e-4), 1.0), atol=1e-9)
    # the bound is reached: a texel twice its blur gains the full 1 + S, one far below it the floor
    assert float(np.maximum(1.0 + s_amount * (1.0 - 0.0), 0.5)) == 1.0 + s_amount
    assert float(np.maximum(1.0 + s_amount * (1.0 - 3.0), 0.5)) == 0.5


def test_generation_8_crown_tilt_is_the_domes_gradient():
    """CROWN_TILT is 2 x 0.8: the dome is 0.8 crown radii high as a parabola
    1 - |d|^2, so its horizontal normal is 1.6 d. A finite difference of
    0.8 x Crowns() against CrownTilt() / radius agrees inside every dome."""
    c = _consts("tiles_detail_normal")
    assert c["CROWN_TILT"] == 2.0 * 0.8
    assert c["CROWN_M"] == _consts("tiles_detail_surface")["CROWN_M"] == 7.0
    crown_m, tilt = c["CROWN_M"], c["CROWN_TILT"]
    rng = np.random.default_rng(7)
    px = rng.uniform(-400.0, 400.0, 20000)
    py = rng.uniform(-400.0, 400.0, 20000)
    eps = 1e-3
    h0, t0, w0, r0 = _crowns(px, py, crown_m, tilt)
    hx, _, wx, _ = _crowns(px + eps, py, crown_m, tilt)
    hy, _, wy, _ = _crowns(px, py + eps, crown_m, tilt)
    inside = (h0 > 0.05) & (w0 == wx) & (w0 == wy)             # one dome, away from its rim
    assert inside.sum() > 5000
    grad_x = 0.8 * (hx[inside] - h0[inside]) / eps
    grad_y = 0.8 * (hy[inside] - h0[inside]) / eps
    # the normal's horizontal part is -grad(height), in crown-radius units x 1/radius
    assert np.allclose(grad_x, -t0[inside, 0] / r0[inside], atol=2e-3)
    assert np.allclose(grad_y, -t0[inside, 1] / r0[inside], atol=2e-3)
    # finite at the rim: |d| <= 1 inside the dome, so |tilt| <= CROWN_TILT
    assert np.all(np.hypot(t0[h0 > 0, 0], t0[h0 > 0, 1]) <= tilt + 1e-9)
    # the shader writes the same law
    assert "tilt = d * CROWN_TILT;" in _shader("tiles_detail_normal")
    assert "best = max(best, saturate(1.0 - d * d));" in _shader("tiles_detail_surface")


def _relief_slope(dBs, dBt, bump_amount, scale, forest_gain, forest, footprint_m):
    """tiles_detail_normal.hlsl's surface gradient on a flat quad: dpx, dpy of
    the footprint along x and y, n = z. Returns the tilt from n in degrees."""
    n = np.array([0.0, 0.0, 1.0])
    dpx = np.array([footprint_m, 0.0, 0.0])
    dpy = np.array([0.0, footprint_m, 0.0])
    bump = bump_amount * scale * footprint_m * 1.0 * 1.0 * (1.0 + forest_gain * forest)   # fade 1, land 1
    r1, r2 = np.cross(dpy, n), np.cross(n, dpx)
    det = float(dpx @ r1)
    surf_grad = np.sign(det) * (bump * dBs * r1 + bump * dBt * r2)
    nb = abs(det) * n - surf_grad
    nb /= np.linalg.norm(nb)
    return float(np.degrees(np.arccos(np.clip(nb @ n, -1.0, 1.0))))


def test_generation_9_relief_step_bounds_the_tilt_to_a_few_degrees():
    """The footprint cancels in the surface gradient, so the relief's slope per
    screen axis is BumpAmount x TerrainDetailScale x (1 + FOREST_BUMP_GAIN x
    forest) x RELIEF_STEP_MAX, at every range alike. TerrainDetailScale is 1 off
    a city (0.12 is DetailStrength, tiles_normal.hlsl's older micro relief, not
    this node's): with that 1 the bound must still be a few degrees. Generation
    8's 0.5 gave 24 deg per axis, 32 on the diagonal; generation 9's 0.08 gives
    at most ~6 deg."""
    from core.scene import world_beauty as wb

    c = _consts("tiles_detail_normal")
    scalars = _literal("WORLD_TILES_DETAIL_SCALARS")
    bump_amount, step, forest_gain = scalars["BumpAmount"], c["RELIEF_STEP_MAX"], c["FOREST_BUMP_GAIN"]
    assert bump_amount == 0.6 and forest_gain == 0.5 and step == 0.08
    # the scale this node reads is 1 off a city, 0 over one; 0.12 is another scalar
    rural = wb.tiles_parameters("clear", 0.0, surface="farmland")
    assert rural["TerrainDetailScale"] == 1.0 and wb.tiles_parameters("clear", 0.0, surface="city")["TerrainDetailScale"] == 0.0
    assert rural["DetailStrength"] == 0.12
    scale = rural["TerrainDetailScale"]
    # the slope law and its bound, in numbers
    per_axis = bump_amount * scale * (1.0 + forest_gain) * step
    assert abs(per_axis - 0.072) < 1e-12
    worst = np.degrees(np.arctan(np.sqrt(2.0) * per_axis))          # both axes at the clamp, on forest
    assert 4.0 < worst <= 6.0, worst
    assert np.degrees(np.arctan(per_axis)) < 4.5                  # one axis, forest
    assert np.degrees(np.arctan(bump_amount * scale * step)) < 3.0   # one axis, open ground
    # the shader's own gradient agrees with the law at every footprint (the range cancels)
    for footprint_m in (0.05, 0.5, 5.0, 50.0):
        for forest in (0.0, 1.0):
            for dBs, dBt in ((step, 0.0), (0.0, -step), (step, step), (-step, step)):
                tilt = _relief_slope(dBs, dBt, bump_amount, scale, forest_gain, forest, footprint_m)
                law = np.degrees(np.arctan(bump_amount * scale * (1.0 + forest_gain * forest) * np.hypot(dBs, dBt)))
                assert abs(tilt - law) < 1e-9, (footprint_m, forest, dBs, dBt)
                assert tilt <= worst + 1e-9
    # an unbounded step (a texel edge of x2 across one pixel) would have tilted far past that
    assert _relief_slope(1.0, 1.0, bump_amount, scale, forest_gain, 1.0, 1.0) > 45.0
    # and generation 8's constant did not keep the comment's promise
    assert np.degrees(np.arctan(bump_amount * scale * (1.0 + forest_gain) * 0.5)) > 20.0
    # the relief is not zeroed: the bound stays above 2 degrees on open ground
    assert np.degrees(np.arctan(bump_amount * scale * step)) > 2.0
    # the shader applies the clamp to both derivatives and states the law
    normal = _shader("tiles_detail_normal")
    assert "clamp(ddx_fine(relief), -RELIEF_STEP_MAX, RELIEF_STEP_MAX)" in normal
    assert "clamp(ddy_fine(relief), -RELIEF_STEP_MAX, RELIEF_STEP_MAX)" in normal
    assert "BumpAmount * TerrainDetailScale * footprintM * fade * land * (1.0 + FOREST_BUMP_GAIN * forest)" in normal
    assert "~6 degrees" in normal
