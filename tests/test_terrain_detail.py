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
    assert _literal("WORLD_GENERATIONS")["M_FlightSimOceanBeauty"] == "4"
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
        assert "tilt += S.Swell(p.xy, windDir, TimeS, footprintM);" in hlsl, name
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
