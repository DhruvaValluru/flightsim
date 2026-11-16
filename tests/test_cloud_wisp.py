"""Sky step 1 (the owner's X-Plane-12 brief, 2026-11-14: "thin translucent
stratocumulus/altocumulus with ragged, wispy edges and fine cauliflower detail
... light bleeding through thin edges"; round 95's #03/#13 drew smooth rounded
blobs with dark undersides). ``-look-cloud-wisp=on|off`` (on by default; off is
round 95 exactly) gives M_FlightSimCloudLayers five new inputs (WispAmount,
CurlStrength, EdgeThinPower, TopDetailGain, BoundaryErosion) on cumulus and
stratocumulus layers, caps the sky light's cloud-bottom occlusion at the belly,
and the material is now built with its own scattering constants
(CLOUD_SCATTERING, not the storm's). BEAUTY ONLY: the measure path never puts
this material on a cloud. Nothing here was rendered: UNMEASURED until
`.\\scripts\\visual_fix_round.ps1 -Round 101 -Scenes 3 -Switches "-look-cloud-wisp=off" -CompareWith 100`
runs on the Windows laptop. These tests pin the C++, the shader, the material
script and core/scene/world_beauty.py to one another so a Windows build cannot
drift from the Python replica."""
import ast
import random
import re
from pathlib import Path

import pytest

from core.scene import world_beauty as wb

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge"
CPP = (SOURCE / "Private/FlightSimClouds.cpp").read_text(encoding="utf-8")
HEADER = (SOURCE / "Public/FlightSimClouds.h").read_text(encoding="utf-8")
HLSL = (ROOT / "assets/shaders/world/cloud_layers.hlsl").read_text(encoding="utf-8")
DISTANT_HLSL = (ROOT / "assets/shaders/world/distant_clouds.hlsl").read_text(encoding="utf-8")
SCRIPT = (ROOT / "scripts/ue_create_materials.py").read_text(encoding="utf-8")
CHECK = (ROOT / "scripts/check_bridge_api.sh").read_text(encoding="utf-8")
PLAN = (ROOT / "docs/VISUAL_FIDELITY_PLAN.md").read_text(encoding="utf-8")
PURE = CPP[CPP.index("// FLIGHTSIM-WORLD-PURE-BEGIN"):CPP.index("// FLIGHTSIM-WORLD-PURE-END")]
APPLY = CPP[CPP.index("void FFlightSimWorldBeauty::ApplyClouds("):CPP.index("void FFlightSimWorldBeauty::ApplyDistantClouds(")]


def _script_value(name):
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def _cpp_constant(name: str) -> float:
    m = re.search(r"constexpr (?:double|int) " + name + r" = ([0-9.-]+);", PURE)
    assert m, name
    return float(m.group(1))


# -- the constants are one number on every side --------------------------------------

@pytest.mark.parametrize("cpp, py", [
    ("CloudWispAmount", "CLOUD_WISP_AMOUNT"),
    ("CloudWispCurl", "CLOUD_WISP_CURL"),
    ("CloudWispEdgePower", "CLOUD_WISP_EDGE_POWER"),
    ("CloudWispTopDetail", "CLOUD_WISP_TOP_DETAIL"),
    ("CloudWispBoundaryErosion", "CLOUD_WISP_BOUNDARY_EROSION"),
    ("CloudWispBottomOcclusion", "CLOUD_WISP_BOTTOM_OCCLUSION"),
    ("CloudAlbedo", "WORLD_CLOUD_ALBEDO_TWIN"),
])
def test_the_cpp_constants_match_python(cpp, py):
    want = _script_value("WORLD_CLOUD_ALBEDO") if py == "WORLD_CLOUD_ALBEDO_TWIN" else getattr(wb, py)
    assert _cpp_constant(cpp) == want


def test_the_shader_constants_match_python():
    assert f"const float CURL_OCTAVE_SCALE = {wb.CLOUD_CURL_OCTAVE_SCALE};" in HLSL
    assert f"const float TOP_DETAIL_LACUNARITY = {wb.CLOUD_TOP_DETAIL_LACUNARITY};" in HLSL
    assert f"const float TOP_DETAIL_MEAN = {wb.CLOUD_TOP_DETAIL_MEAN};" in HLSL
    assert f"const float TOP_DETAIL_LOD = {wb.CLOUD_TOP_DETAIL_LOD};" in HLSL
    # the shader's seeds are the replica's
    assert "N.Perlin(p, seed + 701u)" in HLSL and "N.Perlin(p, seed + 733u)" in HLSL
    assert "N.Worley(q, seed + 193u)" in HLSL
    assert "W.Flow(q * CURL_OCTAVE_SCALE, 23u) * (WispAmount * CurlStrength)" in HLSL
    assert "W.TopDetail(q * TOP_DETAIL_LACUNARITY, 13u) - TOP_DETAIL_MEAN" in HLSL
    # a struct method cannot read the body's locals: the wisp carries its own noise
    assert "struct FWorldWisp\n{\n\tFWorldCloud N;" in HLSL and "C." not in HLSL[HLSL.index("struct FWorldWisp"):HLSL.index("FWorldWisp W;")]
    # the three insertions, in the shader's own words
    assert "if (WispAmount > 0.0 && footKm == 0.0)" in HLSL
    assert ("float ero = DetailErosion * (1.0 - far) * wisp * "
            "(1.0 + WispAmount * BoundaryErosion * (1.0 - density));") in HLSL
    assert "density = lerp(density, pow(density, EdgeThinPower), WispAmount);" in HLSL
    assert "UNCALIBRATED" in HLSL.split("struct FWorldWisp")[0].split("FWorldCloud C;")[1]


def test_the_top_detail_mean_is_the_noises():
    """The top octave is added zero-mean, so DETAIL_MEAN (the mean a wide shadow
    sample reads) still holds: TOP_DETAIL_MEAN is cloud_top_detail's own mean."""
    rng = random.Random(1)
    values = [wb.cloud_top_detail(rng.uniform(0, 300), rng.uniform(0, 300), rng.uniform(0, 300), 13)
              for _ in range(8000)]
    assert sum(values) / len(values) == pytest.approx(wb.CLOUD_TOP_DETAIL_MEAN, abs=0.01)
    assert all(0.0 <= v <= 1.0 for v in values)


def test_the_flow_is_zero_mean_and_bounded():
    rng = random.Random(2)
    flows = [wb.cloud_flow(rng.uniform(0, 300), rng.uniform(0, 300), rng.uniform(0, 300), 23) for _ in range(6000)]
    for axis in range(3):
        values = [f[axis] for f in flows]
        assert abs(sum(values) / len(values)) < 0.02
        assert max(abs(v) for v in values) <= 1.0
    # the vertical component is half the plane's difference (wisps stretch along the layer)
    a, b, c = wb.cloud_flow(1.3, 2.7, 0.4, 23)
    assert c == pytest.approx(0.5 * (b - a))


# -- the switch and the rows ---------------------------------------------------------

def test_the_switch_applies_to_cumulus_and_stratocumulus_only():
    assert wb.CLOUD_WISP_SWITCH == "-look-cloud-wisp"
    assert wb.CLOUD_WISP_SHAPES == ("cumulus", "stratocumulus")
    for shape in wb.CLOUD_PRESETS:
        assert wb.cloud_wisp_applies(True, shape) == (shape in wb.CLOUD_WISP_SHAPES), shape
        assert not wb.cloud_wisp_applies(False, shape)
    # the C++ twin names the same two shapes
    assert "return bWispOn && (Shape == CloudCumulus || Shape == CloudStratocumulus);" in PURE


def test_the_off_row_is_the_materials_defaults_and_the_on_row_is_the_constants():
    scalars = _script_value("WORLD_CLOUD_SCALARS")
    off = wb.cloud_wisp_row(False)
    assert off == wb.CLOUD_WISP_OFF
    assert tuple(off) == wb.CLOUD_WISP_FIELDS
    for name in wb.CLOUD_WISP_FIELDS:
        assert scalars[name] == off[name], name          # an unset material draws round 95
    on = wb.cloud_wisp_row(True)
    assert tuple(on) == wb.CLOUD_WISP_FIELDS
    assert on == {"WispAmount": wb.CLOUD_WISP_AMOUNT, "CurlStrength": wb.CLOUD_WISP_CURL,
                  "EdgeThinPower": wb.CLOUD_WISP_EDGE_POWER, "TopDetailGain": wb.CLOUD_WISP_TOP_DETAIL,
                  "BoundaryErosion": wb.CLOUD_WISP_BOUNDARY_EROSION}
    assert on["WispAmount"] > 0.0 and on["EdgeThinPower"] > 1.0
    # the C++ row: the same OFF values, in the same order
    names = re.search(r"static const char\* const Names\[WspFieldCount\] = \{\s*([^}]*)\}", PURE)
    assert names and tuple(re.findall(r'"([A-Za-z]+)"', names.group(1))) == wb.CLOUD_WISP_FIELDS
    assert "Out[WspEdgePower] = bApplies ? CloudWispEdgePower : 1.0;" in PURE
    for field in ("WspAmount", "WspCurl", "WspTopDetail", "WspBoundaryErosion"):
        assert re.search(rf"Out\[{field}\] = bApplies \? CloudWisp\w+ : 0\.0;", PURE), field


def test_the_belly_occlusion_only_lowers_and_only_when_it_applies():
    cap = wb.CLOUD_WISP_BOTTOM_OCCLUSION
    assert wb.cloud_belly_occlusion(True, 0.8) == cap
    assert wb.cloud_belly_occlusion(True, cap) == cap
    assert wb.cloud_belly_occlusion(True, 0.3) == 0.3
    assert wb.cloud_belly_occlusion(False, 0.8) == 0.8
    # after round 82's raise, so test_cloud_billow's "only rises" law stands
    raised = wb.cloud_bottom_occlusion_for(True, 0.5)
    assert raised == wb.CLOUD_BILLOW_BOTTOM_OCCLUSION
    assert wb.cloud_belly_occlusion(True, raised) == cap < raised
    assert "CloudBellyOcclusion(bWisp, BillowOcclusion)" in APPLY
    assert "const double BillowOcclusion = CloudBottomOcclusionFor(bBillow, AtmRow[AtmCloudBottomOcclusion]);" in APPLY


# -- the density replica ----------------------------------------------------------

def _row():
    return wb.cloud_billow_row(wb.CLOUDS["cumulus"], True)


def test_the_replica_off_is_round_95_exactly():
    """wisp None, CLOUD_WISP_OFF and cloud_wisp_row(False) are the same
    arithmetic as before the step (float64 equality, 200 random samples)."""
    row = _row()
    rng = random.Random(5)
    for _ in range(200):
        km = (rng.uniform(0, 60), rng.uniform(0, 60), rng.uniform(1.5, 2.7))
        h = rng.uniform(0.0, 1.0)
        base = wb.cloud_density(km, h, 0.5, row, rng.uniform(0, 25), height_density=wb.CLOUD_BILLOW_HEIGHT_DENSITY)
        for off in (wb.CLOUD_WISP_OFF, wb.cloud_wisp_row(False)):
            assert wb.cloud_density(km, h, 0.5, row, 0.0, height_density=wb.CLOUD_BILLOW_HEIGHT_DENSITY,
                                    wisp=off) == wb.cloud_density(km, h, 0.5, row, 0.0,
                                                                  height_density=wb.CLOUD_BILLOW_HEIGHT_DENSITY)
        assert base == base   # not NaN


def test_the_wisp_keeps_the_cut_and_the_drawn_cover():
    """The wisp never touches the quantile cut. With the flow and the top octave
    off (the two terms that move the detail point) the boundary erosion only
    grows the erosion and pow(0, p) = 0 keeps every empty point empty, so
    nothing is drawn where round 95 drew nothing. With them on the outline
    moves (a point eroded away in round 95 may fill and another may empty) and
    the drawn share of the sky stays within the coverage test's band."""
    row = _row()
    on = wb.cloud_wisp_row(True)
    no_flow = dict(on, CurlStrength=0.0, TopDetailGain=0.0)
    rng = random.Random(7)
    pts = [(rng.uniform(0, 300), rng.uniform(0, 300)) for _ in range(2500)]
    for h in (0.1, 0.3, 0.45):
        off_in = [wb.cloud_density((x, y, 3.0 + 2.0 * h), h, 0.5, row, 0.0) > 0.0 for x, y in pts]
        flat_in = [wb.cloud_density((x, y, 3.0 + 2.0 * h), h, 0.5, row, 0.0, wisp=no_flow) > 0.0 for x, y in pts]
        on_in = [wb.cloud_density((x, y, 3.0 + 2.0 * h), h, 0.5, row, 0.0, wisp=on) > 0.0 for x, y in pts]
        assert not any(o and not f for o, f in zip(flat_in, off_in))   # nothing drawn where there was none
        assert any(o != f for o, f in zip(on_in, off_in))              # the outline did move
        share_off = sum(off_in) / len(pts)
        share_on = sum(on_in) / len(pts)
        assert share_on == pytest.approx(share_off, abs=0.1 * max(share_off, 0.1))


def test_the_edge_thinning_is_monotone_and_thins_only_the_soft_band():
    row = _row()
    on = wb.cloud_wisp_row(True)
    off = wb.cloud_wisp_row(False)
    rng = random.Random(9)
    pairs = []
    while len(pairs) < 60:
        km = (rng.uniform(0, 60), rng.uniform(0, 60), rng.uniform(1.5, 2.7))
        h = rng.uniform(0.3, 0.9)
        a = wb.cloud_density(km, h, 0.5, row, 0.0, wisp=off)
        if a > 0.0:
            pairs.append((a, wb.cloud_density(km, h, 0.5, row, 0.0, wisp=on)))
    # the on density never exceeds the off one at a full core, and a density in (0, 1)
    # raised to a power above 1 shrinks: the mean drawn density drops
    assert sum(b for _, b in pairs) < sum(a for a, _ in pairs)
    # the law itself is monotone in the density
    ds = [i / 20.0 for i in range(21)]
    thinned = [wb._lerp(d, d ** wb.CLOUD_WISP_EDGE_POWER, wb.CLOUD_WISP_AMOUNT) for d in ds]
    assert thinned == sorted(thinned) and thinned[0] == 0.0 and thinned[-1] == 1.0
    assert all(t <= d for t, d in zip(thinned, ds))


def test_a_shadow_sample_reads_the_undistorted_detail():
    """The flow warp and the top octave are view-sample only (footKm == 0): a
    filtered shadow sample with the wisp on is the same arithmetic as a row with
    CurlStrength and TopDetailGain 0 (float64 equality), so no hash is added to
    the shadow march and no finer octave aliases on its dither. The boundary
    erosion and the thinning DO apply to it (one density field for the view and
    the sun), and a view sample at the same point does feel the flow."""
    row = _row()
    on = wb.cloud_wisp_row(True)
    shadow_only = dict(on, CurlStrength=0.0, TopDetailGain=0.0)
    rng = random.Random(3)
    # a near shadow sample (0.05 km out: ~0.11 km footprint, under the 0.15 km detail
    # cell), so the detail is evaluated, not read at its mean
    foot = wb.cloud_shadow_footprint_per_sqrt_km(6.0, 10.0) * (0.05 ** 0.5)
    assert foot < row["detail_scale_km"]
    checked = moved = 0
    for _ in range(600):
        km = (rng.uniform(0, 60), rng.uniform(0, 60), rng.uniform(1.5, 2.7))
        h = rng.uniform(0.05, 0.95)
        dither = (rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5))
        a = wb.cloud_density(km, h, 0.5, row, 0.0, foot, dither, 1.2, wisp=on)
        b = wb.cloud_density(km, h, 0.5, row, 0.0, foot, dither, 1.2, wisp=shadow_only)
        assert a == b
        checked += a > 0.0
        view_on = wb.cloud_density(km, h, 0.5, row, 0.0, wisp=on)
        view_flat = wb.cloud_density(km, h, 0.5, row, 0.0, wisp=shadow_only)
        moved += view_on != view_flat
    assert checked >= 20 and moved >= 20


# -- the material script, the bridge and the record --------------------------------

def test_the_material_gains_the_five_inputs_and_a_new_generation():
    scalars = _script_value("WORLD_CLOUD_SCALARS")
    inputs = _script_value("WORLD_CLOUD_INPUTS")
    assert tuple(inputs[-5:]) == wb.CLOUD_WISP_FIELDS
    for name in wb.CLOUD_WISP_FIELDS:
        assert name in scalars
        assert re.search(rf"//\s+{name}\s", HLSL), name
    assert int(_script_value("WORLD_GRAPH_GENERATIONS")["M_FlightSimCloudLayers"]) >= 8
    assert int(_script_value("WORLD_GENERATIONS")["M_FlightSimCloudLayers"]) >= 10
    # the distant sheet's shared noise text is untouched: no rebuild asked of it
    assert _script_value("WORLD_GRAPH_GENERATIONS")["M_FlightSimDistantClouds"] == "5"
    # the bridge expects the generation the script stamps
    assert int(_cpp_constant("CloudGraphGeneration")) == int(_script_value("WORLD_GRAPH_GENERATIONS")["M_FlightSimCloudLayers"])


def test_the_beauty_scattering_is_its_own_table_and_the_storm_keeps_its_own():
    script = _script_value("CLOUD_SCATTERING")
    assert script == wb.CLOUD_SCATTERING
    assert tuple(script) == tuple(_script_value("STORM_SCATTERING"))      # the same keys, the node's properties
    assert script != _script_value("STORM_SCATTERING")
    assert "def storm_scattering(material, lib, x, y, constants=STORM_SCATTERING):" in SCRIPT
    assert "for key, value in constants.items()" in SCRIPT
    create = SCRIPT[SCRIPT.index("def create_world_cloud_layers"):SCRIPT.index("def create_world_tiles_beauty")]
    assert "storm_scattering(material, lib, -600, 700, constants=CLOUD_SCATTERING)" in create
    storm = SCRIPT[SCRIPT.index("def create_storm_cell"):SCRIPT.index("def create_windshield_rain")]
    assert "storm_scattering(material, lib, -600, 700)" in storm and "CLOUD_SCATTERING" not in storm
    assert SCRIPT.count("constants=CLOUD_SCATTERING") == 1
    # undersides glow: more multi-scatter contribution, less occlusion than the storm's
    assert script["contribution"] > 0.5 and script["occlusion"] < 0.5
    # the C++ record is the same seven numbers in the same order
    names = re.search(r"static const char\* const Names\[CloudScatteringCount\] = \{\s*([^}]*)\}", PURE)
    values = re.search(r"static const double Values\[CloudScatteringCount\] = \{([^}]*)\};", PURE)
    assert names and values
    cpp = dict(zip(re.findall(r'"([a-z_0-9]+)"', names.group(1)), [float(v) for v in values.group(1).split(",")]))
    assert cpp == {k: float(v) for k, v in wb.CLOUD_SCATTERING.items()}


def test_the_owner_aliases_name_real_parameters():
    scalars = _script_value("WORLD_CLOUD_SCALARS")
    vectors = _script_value("WORLD_CLOUD_VECTORS")
    assert tuple(wb.CLOUD_OWNER_ALIASES) == ("Coverage", "Density", "DetailStrength", "NoiseScale", "Wind")
    for target in wb.CLOUD_OWNER_ALIASES.values():
        assert target in scalars or target in vectors, target
    owner = re.search(r"static const char\* const Owner\[CloudOwnerAliasCount\] = \{\s*([^}]*)\}", PURE)
    target = re.search(r"static const char\* const Target\[CloudOwnerAliasCount\] = \{\s*([^}]*)\}", PURE)
    assert owner and target
    assert dict(zip(re.findall(r'"([A-Za-z]+)"', owner.group(1)),
                    re.findall(r'"([A-Za-z]+)"', target.group(1)))) == wb.CLOUD_OWNER_ALIASES
    # the wind alias is the drift the scene's law advances (Advance sets WindOffsetM)
    advance = CPP[CPP.index("void FFlightSimWorldBeauty::Advance("):]
    assert 'Layer.Material->SetVectorParameterValue(TEXT("WindOffsetM"),' in advance


def test_the_bridge_reads_refuses_sets_and_records_the_switch():
    build = CPP[:CPP.index("// The tables in force")]
    assert 'CloudWispSwitch = TEXT("on");' in build
    assert 'FParse::Value(*Switches, TEXT("look-cloud-wisp="), CloudWispSwitch);' in build
    assert "world_beauty.clouds: -look-cloud-wisp=%s is not on or off" in build
    assert 'FString CloudWispSwitch = TEXT("on");' in HEADER
    assert 'const bool bWisp = CloudWispApplies(CloudWispSwitch == TEXT("on"), State.Shape);' in APPLY
    assert "CloudWispRow(bWisp, WispRow);" in APPLY
    for name in wb.CLOUD_WISP_FIELDS:
        assert f'State.Material->SetScalarParameterValue(TEXT("{name}")' in APPLY, name
    for field in ("cloud_wisp", "cloud_wisp_applied", "belly_occlusion_cap",
                  "sky_light_cloud_bottom_occlusion_before_belly_cap", "cloud_wisp_basis"):
        assert f'TEXT("{field}")' in APPLY, field
    assert "Layer->SetNumberField(ANSI_TO_TCHAR(CloudWispFieldName(F)), WispRow[F]);" in APPLY
    # the material record: what the asset was built with, and whether it is current
    for field in ("graph_generation_expected", "graph_generation", "graph_generation_current", "albedo",
                  "scattering", "owner_aliases", "calibration"):
        assert f'TEXT("{field}")' in APPLY, field
    assert 'GetValue(Base, TEXT("FlightSimGraphGeneration"))' in APPLY
    assert "#if WITH_METADATA" in APPLY
    assert 'GRAPH_GENERATION_TAG = "FlightSimGraphGeneration"' in SCRIPT
    assert 'Out->SetObjectField(TEXT("material"), MaterialOut);' in APPLY
    # the engine symbols the read-back uses are checked before a build
    assert "COREUOBJECT_API FMetaData& GetMetaData();" in CHECK
    assert "const FString& GetValue(const UObject* Object, const TCHAR* Key);" in CHECK
    # the pure block stays dependency-free and labelled
    assert "UNCALIBRATED" in PURE[PURE.index("constexpr double CloudWispAmount") - 1200:PURE.index("constexpr double CloudWispAmount")]


def test_the_distant_sheet_look_moved_on_both_sides():
    """Sky step 1 brightens the far sheet's bellies (3.6 of the design): the C++
    twin's literal row is the Python table's (test_distant_clouds compiles the
    full equality; this pins the three moved numbers by name)."""
    look = wb.DISTANT_LOOK
    assert (look["BaseDarkening"], look["BaseSunShare"], look["SilverLining"]) == (0.70, 0.25, 0.8)
    values = re.search(r"static const double Values\[DistantLookCount\] = \{([^}]*)\};", PURE)
    assert values
    cpp = [float(v) for v in values.group(1).split(",")]
    names = re.search(r"static const char\* const Names\[DistantLookCount\] = \{\s*([^}]*)\}", PURE)
    assert dict(zip(re.findall(r'"([A-Za-z]+)"', names.group(1)), cpp)) == look
    # the parameters' meaning in the sheet's shader is unchanged (no distant rebuild)
    assert "L = ambient * BaseDarkening + sunLambert * BaseSunShare" in DISTANT_HLSL


def test_the_plan_records_the_step_as_unmeasured_with_the_windows_command():
    entry = PLAN[PLAN.index("**Sky step 1"):]
    entry = entry[:entry.index("\n\n")]
    assert "UNMEASURED" in entry and "UNCALIBRATED" in entry
    assert "-look-cloud-wisp" in entry
    assert "visual_fix_round.ps1" in entry
