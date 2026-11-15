"""The pre-rendered impostor clouds (2026-11-14): JangaFX's CC0 Cloud Pack baked once in
Blender into octahedral six-way atlases, drawn beauty-only under -cloud-impostors=.

Nothing here runs Blender or the engine: the maths is scripts/cloud_impostor_math.py
(the bake, the shader and the C++ share its conventions, pinned below), the fetch is
exercised on a fabricated zip, and the C++ / HLSL / material script are read as text.
(Named test_impostor_clouds.py: tests/test_cloud_*.py is the cloud lane's.)"""
import io
import json
import math
import re
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import cloud_impostor_math as cim  # noqa: E402
import fetch_cloud_vdbs as fetch  # noqa: E402

PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
PUBLIC = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public"
CPP = (PRIVATE / "FlightSimImpostorClouds.cpp").read_text(encoding="utf-8")
HDR = (PUBLIC / "FlightSimImpostorClouds.h").read_text(encoding="utf-8")
RENDER_CPP = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
HLSL = (REPO / "assets/shaders/world/cloud_impostor.hlsl").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts/ue_create_materials.py").read_text(encoding="utf-8")
CATALOG = (REPO / "core/messages/catalog.yaml").read_text(encoding="utf-8")

DIRS = [(0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (1, 1, 1), (-1, 2, -3),
        (0.3, -0.7, 0.2), (-0.1, -0.1, -0.98), (5, -1, -0.01)]


def _close(a, b, tol=1e-9):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# -- the octahedral map and the frames -------------------------------------------------

@pytest.mark.parametrize("d", DIRS)
def test_octahedral_round_trip(d):
    n = cim._norm(d)
    u, v = cim.oct_encode(n)
    assert 0.0 <= u <= 1.0 and 0.0 <= v <= 1.0
    assert _close(cim.oct_decode(u, v), n, 1e-9)


@pytest.mark.parametrize("d", DIRS)
def test_blend_picks_a_triangle_whose_weights_sum_to_one(d):
    frames = cim.blend_frames(d, 8)
    assert len(frames) == 3
    assert abs(sum(w for _, w in frames) - 1.0) < 1e-9
    assert all(w >= -1e-12 for _, w in frames)
    assert all(0 <= i < 8 and 0 <= j < 8 for (i, j), _ in frames)


def test_a_frames_own_direction_takes_all_the_weight():
    # (the octahedral square's border folds: a border frame and its mirror are one direction)
    for i, j in ((0, 0), (3, 4), (7, 7), (2, 7), (5, 1)):
        target = cim.frame_dir(i, j, 8)
        same = sum(w for (a, b), w in cim.blend_frames(target, 8)
                   if cim._dot(cim.frame_dir(a, b, 8), target) > 1.0 - 1e-9)
        assert same == pytest.approx(1.0, abs=1e-9), (i, j)


@pytest.mark.parametrize("d", DIRS)
def test_frame_basis_is_orthonormal_and_faces_the_viewer(d):
    right, up, forward = cim.frame_basis(d)
    for a in (right, up, forward):
        assert cim._dot(a, a) == pytest.approx(1.0)
    assert cim._dot(right, up) == pytest.approx(0.0, abs=1e-12)
    assert cim._dot(forward, cim._norm(d)) == pytest.approx(-1.0)


def test_frame_uv_centre_and_axes():
    d = (0.0, -1.0, 0.0)                  # seen from the south: right is +x, up +z
    assert cim.frame_uv((0, 0, 0), d, 10.0) == (0.5, 0.5)
    u, v = cim.frame_uv((5.0, 0.0, 5.0), d, 10.0)
    assert u == pytest.approx(0.75) and v == pytest.approx(0.25)


def test_six_way_weights_for_known_suns():
    assert cim.six_way_weights((0, 0, 1)) == pytest.approx((0, 0, 1, 0, 0, 0))
    assert cim.six_way_weights((0, 0, -2)) == pytest.approx((0, 0, 0, 0, 0, 1))
    w = cim.six_way_weights((1, -1, 0))
    assert w == pytest.approx((math.sqrt(0.5), 0, 0, 0, math.sqrt(0.5), 0))


@pytest.mark.parametrize("yaw", [0.0, 0.7, -2.1, math.pi])
def test_world_object_round_trip_and_handedness(yaw):
    v = (1.0, 2.0, 3.0)
    assert _close(cim.object_to_world(cim.world_to_object(v, yaw), yaw), v, 1e-9)
    # yaw 0: UE y (right) is Blender -y; z stays up
    assert _close(cim.world_to_object((0.0, 1.0, 0.0), 0.0), (0.0, -1.0, 0.0))


# -- keep-out and placement --------------------------------------------------------------

def test_keep_out_hides_a_cloud_on_the_line_of_sight_only():
    cam, aircraft = (0.0, 0.0, 0.0), (0.0, 1000.0, 0.0)
    assert cim.keep_out((0.0, 500.0, 0.0), 100.0, cam, aircraft, 30.0)
    assert cim.keep_out((250.0, 500.0, 0.0), 100.0, cam, aircraft, 30.0)        # 250 < 100 + 30 + 150
    assert not cim.keep_out((300.0, 500.0, 0.0), 100.0, cam, aircraft, 30.0)    # 300 > 280
    assert not cim.keep_out((5000.0, 500.0, 0.0), 100.0, cam, aircraft, 30.0)
    assert not cim.keep_out((0.0, 9000.0, 0.0), 100.0, cam, aircraft, 30.0)      # far behind the aircraft


def test_placement_counts_ranges_and_determinism():
    layers = [{"cover": 0.5, "base_m": 1500.0, "top_m": 3500.0}, {"cover": 0.9, "base_m": 6000.0, "top_m": 6200.0}]
    a = cim.placement(7, layers, (0.0, 0.0), "pilot", 4)
    assert a == cim.placement(7, layers, (0.0, 0.0), "pilot", 4)
    assert len(a) == cim.MAX_INSTANCES["pilot"] == 12        # 0.5 x 40 = 20, capped; the thin layer gives 0
    for inst in a:
        r = math.hypot(inst["x"], inst["y"])
        assert cim.RING_INNER_M - 1e-6 <= r <= cim.RING_OUTER_M + 1e-6
        assert 1500.0 - 1e-6 <= inst["z"] - 0.5 * inst["height_m"]
        assert inst["z"] + 0.5 * inst["height_m"] <= 3500.0 + 1e-6
        assert 0 <= inst["cloud"] < 4
    assert cim.instance_count(0.9, 200.0, "on") == 0
    assert cim.instance_count(0.02, 2000.0, "on") == 0
    assert cim.instance_count(0.5, 2000.0, "on") == 20
    assert cim.placement(7, layers, (0.0, 0.0), "off", 4) == []


def test_the_cpp_constants_are_the_python_twins():
    def const(name):
        m = re.search(rf"constexpr (?:double|int32) {name} = ([0-9.x]+);", CPP)
        assert m, name
        return float(int(m.group(1), 16)) if m.group(1).startswith("0x") else float(m.group(1))
    assert const("ImpostorCumulusMinThicknessM") == cim.CUMULUS_MIN_THICKNESS_M
    assert const("ImpostorMinCover") == cim.MIN_COVER
    assert const("ImpostorInstancesAtFullCover") == cim.INSTANCES_AT_FULL_COVER
    assert const("ImpostorMaxInstancesPilot") == cim.MAX_INSTANCES["pilot"]
    assert const("ImpostorMaxInstancesOn") == cim.MAX_INSTANCES["on"]
    assert const("ImpostorRingInnerM") == cim.RING_INNER_M
    assert const("ImpostorRingOuterM") == cim.RING_OUTER_M
    assert (const("ImpostorHeightShareMin"), const("ImpostorHeightShareMax")) == cim.HEIGHT_SHARE
    assert const("ImpostorKeepOutMarginM") == cim.KEEP_OUT_MARGIN_M
    # The same world -> object map and frame basis on all three sides.
    assert "return FVector(C * V.X - S * V.Y, -(S * V.X + C * V.Y), V.Z);" in CPP
    assert "return float3(c * v.x - s * v.y, -(s * v.x + c * v.y), v.z);" in HLSL
    assert "FMath::Abs(D.Z) > 0.999 ? FVector(0.0, 1.0, 0.0) : FVector(0.0, 0.0, 1.0)" in CPP
    assert "abs(d.z) > 0.999 ? float3(0.0, 1.0, 0.0) : float3(0.0, 0.0, 1.0)" in HLSL


# -- the bake's numbers ----------------------------------------------------------------

def test_light_encoding_round_trip_and_budget():
    for v in (0.0, 0.01, 0.3, 0.9):
        assert cim.decode_light(cim.encode_light(v, 1.0), 1.0) == pytest.approx(v, abs=1e-9)
    assert cim.encode_light(5.0, 1.0) == 1.0
    assert cim.atlas_px(8, 128) == 1024
    assert cim.atlas_px(cim.DEFAULT_VIEWS, cim.DEFAULT_PX) == 2048 == cim.ATLAS_MAX_PX
    with pytest.raises(ValueError):
        cim.atlas_px(16, 256)
    assert cim.straighten((0.2, 0.4, 0.1), 0.5) == pytest.approx((0.4, 0.8, 0.2))
    assert cim.straighten((0.2, 0.4, 0.1), 0.0) == (0.0, 0.0, 0.0)
    assert cim.encode_depth_offset(None, 1.0) == 0.5
    assert cim.encode_depth_offset(2.0, 1.0) == 1.0
    assert cim.percentile([0, 1, 2, 3, 4], 50) == 2


def test_cloud_record_and_pin(tmp_path):
    rec = cim.cloud_record("cloud00", "a.vdb", "ab" * 32, (-1, -1, 0), (1, 1, 2), 8, 128, 0.7,
                           {"pos": "cloud00_pos.png", "neg": "cloud00_neg.png"}, {"engine": "Cycles"})
    assert rec["sphere_over_height"] == pytest.approx(2 * 0.5 * math.sqrt(12) / 2)
    assert rec["channels"]["pos"]["a"] == "opacity" and rec["channels"]["neg"]["a"] == "depth_offset"
    assert "CC0" in rec["licence"] and rec["atlas_px"] == 1024
    assert rec["framing"] == {"method": "box half-diagonal"}
    # The fitted bake: the frame's half-side is tight_fit's radius, the height the density's.
    framing = {"method": "test", "threshold": 0.01}
    tight = cim.cloud_record("cloud00", "a.vdb", "ab" * 32, (-1, -1, 0), (1, 1, 2), 8, 256, 0.7,
                             {"pos": "p.png", "neg": "n.png"}, {}, sphere_radius=1.5, framing=framing)
    assert tight["sphere_radius_vdb_units"] == 1.5 and tight["atlas_px"] == 2048
    assert tight["sphere_over_height"] == pytest.approx(2 * 1.5 / 2)      # the C++: RadiusCm = 0.5 x this x HeightM
    assert tight["framing"] is framing and tight["bounds_vdb_units"]["size"] == [2.0, 2.0, 2.0]
    for name in ("cloud00_pos.png", "cloud00_neg.png"):
        (tmp_path / name).write_bytes(name.encode("utf-8"))
    pin = cim.pin_json(tmp_path, ["cloud00_pos.png", "cloud00_neg.png"])
    assert pin["files"]["cloud00_pos.png"]["path"] == "assets/looks/clouds/impostors/cloud00_pos.png"
    assert pin["files"]["cloud00_neg.png"]["sha256"] == cim.sha256_file(tmp_path / "cloud00_neg.png")


def test_the_bake_script_imports_without_blender_and_parses():
    import bake_cloud_impostors as bake
    args = bake.parse(["blender", "--", "--out", "x", "--clouds", "4"])
    assert args.clouds == 4 and args.views == cim.DEFAULT_VIEWS and args.px == cim.DEFAULT_PX == 256
    assert bake.ANISOTROPY >= 0.6 and bake.ALBEDO >= 0.98 and bake.VOLUME_BOUNCES >= 16
    # The frame is fitted to the density through the Volume to Mesh shell, not to the grid,
    # and the record carries the fit (sphere_radius) and how it was found (framing).
    source = (REPO / "scripts/bake_cloud_impostors.py").read_text(encoding="utf-8")
    assert "cim.bisect_peak(lambda t: shell_vertex_count(t) > 0)" in source
    assert "cim.tight_fit(co.reshape(-1, 3).tolist(), extra=voxel)" in source
    assert "sphere_radius=radius, framing=framing" in source
    assert "cam_data.ortho_scale = 2.0 * radius" in source
    assert 'print(f"BAKE-FAILED: {exc!r}", flush=True)' in source and "out = Path(args.out).resolve()" in source


# -- the tight frame (pure Python; the bake's Blender side only feeds it points) -----------

def test_density_threshold_is_a_share_of_the_peak_with_a_floor():
    assert cim.density_threshold(1.0) == pytest.approx(0.01)
    assert cim.density_threshold(0.3) == pytest.approx(0.003)
    assert cim.density_threshold(0.0) == 1e-6


@pytest.mark.parametrize("peak", [0.37, 1.0, 2.9, 0.004])
def test_bisect_peak_finds_a_lower_bound_within_the_step(peak):
    calls = []

    def nonempty(t):
        calls.append(t)
        return t < peak
    found = cim.bisect_peak(nonempty)
    assert found <= peak
    assert peak - found <= max(1.0, peak) * 2.0 / 2 ** 10 + 1e-12
    assert len(calls) <= 24                     # a few shell evaluations, not a scan


def test_bisect_peak_of_nothing_is_zero_and_the_cap_holds():
    assert cim.bisect_peak(lambda t: False) == 0.0
    assert cim.bisect_peak(lambda t: True, cap=64.0) == 64.0


def test_dense_points_and_tight_fit():
    samples = [(0, 0, 0, 0.0), (1, 2, 3, 0.5), (-1, 0, 1, 0.02), (10, 10, 10, 0.009), (3, 2, 1, 1.0)]
    pts = cim.dense_points(samples, cim.density_threshold(1.0))
    assert pts == [(1.0, 2.0, 3.0), (-1.0, 0.0, 1.0), (3.0, 2.0, 1.0)]     # the padding voxel at 10 is out
    fit = cim.tight_fit(pts, margin=0.0)
    assert fit["min"] == [-1.0, 0.0, 1.0] and fit["max"] == [3.0, 2.0, 3.0]
    assert fit["size"] == [4.0, 2.0, 2.0] and fit["centre"] == [1.0, 1.0, 2.0]
    # the farthest point from the centre ((-1, 0, 1) and (3, 2, 1): sqrt(4 + 1 + 1)), not the half-diagonal
    assert fit["radius"] == pytest.approx(math.sqrt(6.0))
    assert fit["radius"] <= 0.5 * math.sqrt(4 ** 2 + 2 ** 2 + 2 ** 2)      # never above the half-diagonal
    padded = cim.tight_fit(pts, margin=0.04, extra=0.5)
    assert padded["radius"] == pytest.approx(math.sqrt(6.0) * 1.04 + 0.5)
    assert padded["min"] == fit["min"]                                 # the margin widens the frame, not the box
    assert cim.tight_fit([]) is None
    assert cim.frame_fill(fit["size"], fit["radius"]) == pytest.approx(4.0 / (2 * math.sqrt(6.0)))
    assert cim.frame_fill([1, 1, 1], 0.0) == 0.0


def test_the_first_bakes_grid_fit_was_the_blur():
    # cloud00's grid (272 x 528 x 176 VDB units): a sphere on the grid's half-diagonal gives
    # a frame the cloud's shortest side spans by less than a third.
    grid = cim.tight_fit([(-160, -232, -104), (112, 296, 72)], margin=0.0)
    assert grid["radius"] == pytest.approx(309.735, abs=0.01)
    assert 176.0 / (2 * grid["radius"]) < 1 / 3


# -- the fetch (no network) ---------------------------------------------------------------

def _zip(tmp_path):
    path = tmp_path / "pack.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Clouds/cloud_a.vdb", b"vdb-a")
        z.writestr("Clouds/cloud_b.vdb", b"vdb-b")
        z.writestr("../evil.vdb", b"no")
    return path


def test_fetch_refuses_an_unpinned_zip_unless_trusted(tmp_path):
    env = {"FLIGHTSIM_ASSETS_DIR": str(tmp_path / "assets")}
    pin = dict(fetch.PIN, zip_sha256=None)
    with pytest.raises(fetch.CloudVdbError, match="assets.cloud_vdbs_unpinned"):
        fetch.fetch(_zip(tmp_path), env=env, pin=pin)
    folder = fetch.fetch(_zip(tmp_path), trust_first=True, env=env, pin=pin)
    assert folder == tmp_path / "assets" / "jangafx_clouds"
    assert sorted(p.name for p in folder.rglob("*.vdb")) == ["cloud_a.vdb", "cloud_b.vdb"]
    assert not (tmp_path / "assets" / "evil.vdb").exists()


def test_fetch_checks_the_pin_and_skips_when_present(tmp_path):
    env = {"FLIGHTSIM_ASSETS_DIR": str(tmp_path / "assets")}
    z = _zip(tmp_path)
    with pytest.raises(fetch.CloudVdbError, match="assets.cloud_vdbs_sha"):
        fetch.fetch(z, env=env, pin=dict(fetch.PIN, zip_sha256="0" * 64))
    good = dict(fetch.PIN, zip_sha256=fetch.sha256(z))
    folder = fetch.fetch(z, env=env, pin=good)
    assert fetch.present(folder, good)
    assert fetch.fetch(None, env=env, pin=good) == folder        # present: no zip, no network
    with pytest.raises(fetch.CloudVdbError, match="assets.cloud_vdbs_missing"):
        fetch.fetch(None, check=True, env={"FLIGHTSIM_ASSETS_DIR": str(tmp_path / "none")}, pin=good)


def test_fetch_default_cache_is_outside_the_repo():
    assert fetch.cache_dir({}) == REPO.parent / "flightsim_assets" / "jangafx_clouds"
    assert "CC0" in (REPO / "THIRD_PARTY_VISUAL.md").read_text(encoding="utf-8").split("## Impostor clouds")[1]


# -- the engine side: switch, beauty only, refusals ------------------------------------------

def test_switch_parse_defaults_off_and_refuses_by_name():
    parse = CPP[CPP.index("bool FFlightSimImpostorClouds::ParseMode("):CPP.index("bool FFlightSimImpostorClouds::Build(")]
    assert 'FString Value = TEXT("off");' in parse
    assert 'Value != TEXT("off") && Value != TEXT("pilot") && Value != TEXT("on")' in parse
    for name in ("cloud.impostor_switch", "cloud.impostor_assets"):
        assert f'TEXT("{name}:' in CPP
        assert re.search(rf"^{re.escape(name)}:$", CATALOG, re.M), name


def test_impostors_are_beauty_only_and_hidden_from_every_label_pass():
    hook = RENDER_CPP.index("FFlightSimImpostorClouds::ParseMode(ImpostorSwitches")
    gate = RENDER_CPP.rindex("if (bBeauty)", 0, hook)
    block = RENDER_CPP[gate:RENDER_CPP.index("if (FFlightSimGoogleTiles::Requested()", hook)]
    assert 'FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"))' in block
    assert "VisualScene.BeautyOnlyActors.Append(ImpostorClouds.BeautyOnlyActors);" in block
    assert 'SetObjectField(TEXT("cloud_impostors"), ImpostorClouds.Record)' in block
    # appended before the label captures read BeautyOnlyActors
    assert RENDER_CPP.index("VisualScene.BeautyOnlyActors.Append(ImpostorClouds.BeautyOnlyActors);") < \
        RENDER_CPP.index("Label->HiddenActors.Append(VisualScene.BeautyOnlyActors);")
    assert "BeautyOnlyActors.Add(Actor);" in CPP and "SetCastShadow(false)" in CPP
    assert "ImpostorClouds.Advance(Capture->GetComponentLocation()" in RENDER_CPP


# -- the material and the shader ----------------------------------------------------------------

def _assigned(name):
    import ast
    tree = ast.parse(SCRIPT)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


def test_the_material_is_listed_stamped_and_wired_to_the_shader():
    # Its own block, list-free and stamped by its own tag (the world/cloud sections are the cloud lane's).
    assert "M_FlightSimCloudImpostor" not in _assigned("WORLD_BEAUTY_MATERIALS")
    assert "M_FlightSimCloudImpostor" not in _assigned("WORLD_GENERATIONS")
    assert _assigned("CLOUD_IMPOSTOR_GENERATION") == "1"
    assert re.search(r"^create_cloud_impostor\(\)", SCRIPT, re.M)
    body = SCRIPT[SCRIPT.index("def create_cloud_impostor("):SCRIPT.index("def _cloud_impostor_material(")]
    assert "_translucent_unlit(material, unreal.BlendMode.BLEND_TRANSLUCENT)" in body
    assert "set_metadata_tag(material, CLOUD_IMPOSTOR_GENERATION_TAG" in body
    header = [m.group(1) for m in re.finditer(r"^//   (\w+)\s+(?:float\d?|Texture2D)\s", HLSL, re.M)]
    assert tuple(header) == _assigned("CLOUD_IMPOSTOR_INPUTS")
    assert set(_assigned("CLOUD_IMPOSTOR_SCALARS")) >= {"Yaw", "SphereRadiusCm", "Opacity", "SphereOverHeight"}
    for name in ("Yaw", "SphereRadiusCm", "Opacity"):
        assert f'SetScalarParameterValue(TEXT("{name}")' in CPP
    assert "MI_FlightSimCloudImpostor_cloud%02d" in CPP
    assert _assigned("CLOUD_IMPOSTOR_INSTANCE_PREFIX") == "MI_FlightSimCloudImpostor_"


def _strip(code):
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return "\n".join(re.sub(r"//.*$", "", line) for line in code.splitlines())


def test_the_shader_is_sm5_safe():
    code = _strip(HLSL)
    for forbidden in (r"\bwhile\s*\(", r"\[loop", r"\bWave\w+\(", r"\bddx", r"\bddy", r"\bfwidth\(",
                      r"\.Sample\(", r"\.SampleGrad\(", r"\bdiscard\b", r"\buint64", r"\bdouble\b"):
        assert not re.search(forbidden, code), forbidden
    loops = re.findall(r"for\s*\(", code)
    assert len(loops) == 1 and "[unroll] for (int k = 0; k < 3; ++k)" in code
    assert code.count(".SampleLevel(") == 2
    assert "PosTexSampler" in code and "NegTexSampler" in code


def test_the_pin_is_the_render_machines_download():
    assert fetch.PIN["zip_sha256"] == "3676ba4c7ac431446731f956f98e925ad3db31354b8b4adcb137dc0250595f73"
    assert fetch.PIN["zip_name"] == "CloudPackVDB.zip" and fetch.PIN["zip_bytes"] == "109761538"
    bake_doc = (REPO / "scripts/bake_cloud_impostors.py").read_text(encoding="utf-8")
    assert "blender-5.2.3-windows-x64" in bake_doc and "bpy.data.volumes.new" in bake_doc
