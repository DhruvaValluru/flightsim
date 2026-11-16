"""Sky step 2 (the owner's X-Plane-12 brief, 2026-11-14): the beauty host reads
the sky plan's cloud fields. ``sky.json`` "clouds" gains cloud_type, coverage,
density, detail, cirrus_coverage, coverage_source and seed (step 5 writes them;
this step parses them with defaults when absent). Under ``-quality=beauty``
FFlightSimWorldBeauty::ApplyClouds sets M_FlightSimCloudLayers' Coverage,
ExtinctionPerM (x the plan's density) and DetailErosion (x the plan's detail)
from the plan, the card and the ``-cloud-type=`` switch by one precedence law
(FlightSimWorldPure::LayerSource) and records everything under
look_applied.world_beauty.clouds. The measure host (FlightSimSky.cpp Build)
is untouched: it still draws the stock m_SimpleVolumetricCloud_Inst from
bottom_km/thickness_km only. These tests pin the C++, the header defaults, the
commandlet call site, the switch registry and core/scene/world_beauty.py to
one another so a Windows build cannot drift from the Python replica.
UNMEASURED: nothing here was rendered."""
import re
import shutil
from pathlib import Path

import pytest

from core import config_surface
from core.scene import world_beauty as wb
from core.sky import plan as sky_plan

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
PUBLIC = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public"
CPP = PRIVATE / "FlightSimClouds.cpp"
HEADER = PUBLIC / "FlightSimClouds.h"
SKY_CPP = PRIVATE / "FlightSimSky.cpp"
SKY_H = PUBLIC / "FlightSimSky.h"
COMMANDLET = PRIVATE / "FlightSimRenderCommandlet.cpp"
CHECK = ROOT / "scripts/check_bridge_api.sh"
CATALOG = ROOT / "core/messages/catalog.yaml"
VFP = ROOT / "docs/VISUAL_FIDELITY_PLAN.md"
DESIGN = ROOT / "docs/visual/XPLANE_SKY_DESIGN.md"

NEEDS_CXX = pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler on this machine")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _between(text: str, begin: str, end: str) -> str:
    start = text.index(begin)
    return text[start:text.index(end, start)]


# -- the plan struct and its parser --------------------------------------------------

def test_the_header_defaults_are_the_python_ones():
    """FFlightSimSkyPlan's cloud fields default to PLAN_CLOUD_DEFAULTS: a v1 plan
    without them loads and the record says these."""
    text = _read(SKY_H)
    assert "bool bCloudPlanFields = false;" in text
    assert "FString CloudType;" in text and wb.PLAN_CLOUD_DEFAULTS["cloud_type"] == ""
    assert f"double CloudCoverage = {wb.PLAN_CLOUD_DEFAULTS['coverage']};" in text
    assert f"double CloudDensity = {wb.PLAN_CLOUD_DEFAULTS['density']};" in text
    assert f"double CloudDetail = {wb.PLAN_CLOUD_DEFAULTS['detail']};" in text
    assert f"double CloudCirrusCoverage = {wb.PLAN_CLOUD_DEFAULTS['cirrus_coverage']};" in text
    assert "FString CloudCoverageSource;" in text and wb.PLAN_CLOUD_DEFAULTS["coverage_source"] == ""
    assert f"int64 CloudSeed = {wb.PLAN_CLOUD_DEFAULTS['seed']};" in text
    assert "bool bCloudSeedStated = false;" in text


def test_load_reads_every_field_optionally_and_the_version_stands():
    """The new keys are read with TryGet* AFTER the mandatory reads (a plan without
    them loads); none joins the SkyNumber(...) refusals; SKY_VERSION is unchanged
    on both sides (additive keys need no bump)."""
    text = _read(SKY_CPP)
    load = _between(text, "bool FFlightSimSkyPlan::Load(", "void FFlightSimSky::EnableRendererFeatures()")
    for key, getter in (("cloud_type", "TryGetStringField"), ("coverage", "TryGetNumberField"),
                        ("density", "TryGetNumberField"), ("detail", "TryGetNumberField"),
                        ("cirrus_coverage", "TryGetNumberField"), ("coverage_source", "TryGetStringField"),
                        ("seed", "TryGetNumberField")):
        assert f'CloudsJson->{getter}(TEXT("{key}")' in load, key
        assert f'SkyNumber(CloudsJson, TEXT("{key}")' not in load, key
    assert load.index('TryGetStringField(TEXT("cloud_type")') > load.index('SkyNumber(CloudsJson, TEXT("thickness_km")')
    assert "Out.CloudSeed = Out.bCloudSeedStated ? static_cast<int64>(CloudSeedValue) : 0;" in load
    assert int(re.search(r"constexpr int32 SkySupportedVersion = (\d+);", text).group(1)) == sky_plan.SKY_VERSION == 1


def test_the_measure_build_is_untouched():
    """FFlightSimSky::Build (every quality) still loads the stock instance from
    bottom_km/thickness_km and never reads a new field: measure renders are
    byte-identical with or without them."""
    text = _read(SKY_CPP)
    build = _between(text, "bool FFlightSimSky::Build(", "void FFlightSimSky::ApplyPostProcess(")
    assert "m_SimpleVolumetricCloud_Inst" in build
    assert "Plan.CloudBottomKm" in build and "Plan.CloudThicknessKm" in build
    for name in ("CloudType", "CloudCoverage", "CloudDensity", "CloudDetail", "CloudCirrusCoverage",
                 "CloudCoverageSource", "CloudSeed", "bCloudPlanFields"):
        assert name not in build, name
    assert 'CloudsNote = TEXT("engine cloud material m_SimpleVolumetricCloud_Inst ' in build


def test_plan_cloud_fields_defaults_and_parse():
    """The Python twin of Load: absent or mistyped fields keep the defaults and
    ``stated`` says whether any was present. Sky step 5 moved two pins here: the
    fields gained ``march_tier`` (the step 3 cvar set the plan asks for), and
    plan_sky now WRITES the fields (step 2 pinned that it wrote none; step 5 is
    the step that writes them), so a fresh plan reads back ``stated`` and the
    four v1 keys are a subset of the block rather than the whole of it."""
    none = wb.plan_cloud_fields({})
    assert none == {**wb.PLAN_CLOUD_DEFAULTS, "stated": False}
    assert wb.plan_cloud_fields(None) == none
    full = wb.plan_cloud_fields({"cloud_type": "stratocumulus", "coverage": 0.6, "density": 1.2, "detail": 0.8,
                                 "cirrus_coverage": 0.3, "coverage_source": "ERA5", "seed": 42.0,
                                 "march_tier": "probe"})
    assert full == {"cloud_type": "stratocumulus", "coverage": 0.6, "density": 1.2, "detail": 0.8,
                    "cirrus_coverage": 0.3, "coverage_source": "ERA5", "seed": 42, "march_tier": "probe",
                    "stated": True}
    assert isinstance(full["seed"], int)
    typed = wb.plan_cloud_fields({"cloud_type": 3, "coverage": "high", "seed": True, "density": None,
                                  "march_tier": 2})
    assert typed == none
    partial = wb.plan_cloud_fields({"cloud_type": "cumulus"})
    assert partial["stated"] and partial["coverage"] == -1.0 and partial["density"] == 1.0
    assert partial["march_tier"] == ""
    # an unknown word is carried (forward-compatible with step 5), the host draws it as "not stated"
    assert wb.plan_cloud_fields({"cloud_type": "mammatus"})["cloud_type"] == "mammatus"
    plan = sky_plan.plan_sky("12:00", None, 37.6, -122.4, 1000.0, 0.0)
    read = wb.plan_cloud_fields(plan["clouds"])
    assert read["stated"] is True and read["cloud_type"] == "cumulus" and read["march_tier"] == "auto"
    assert {"enabled", "bottom_km", "thickness_km", "basis"} <= set(plan["clouds"])


# -- the laws --------------------------------------------------------------------------

def test_the_type_words_and_their_shapes():
    assert wb.PLAN_CLOUD_TYPES == ("clear", "cumulus", "stratocumulus", "altocumulus", "cirrus",
                                   "overcast", "nimbostratus")
    assert set(wb.PLAN_CLOUD_SHAPES) == set(wb.PLAN_CLOUD_TYPES)
    for word, shape in wb.PLAN_CLOUD_SHAPES.items():
        assert wb.cloud_shape_for_plan_type(word) == shape
        assert shape is None or shape in wb.CLOUD_PRESETS
    assert wb.cloud_shape_for_plan_type("clear") is None and wb.cloud_shape_for_plan_type("cirrus") is None
    # sky step 5: altocumulus draws its own CLOUDS row (step 2 pinned stratocumulus until the row existed)
    assert wb.cloud_shape_for_plan_type("altocumulus") == "altocumulus"
    with pytest.raises(ValueError):
        wb.cloud_shape_for_plan_type("mammatus")
    text = _read(CPP)
    names = re.search(r'static const char\* const Names\[PlanCloudTypeCount\] = \{\s*((?:"[a-z]+",?\s*)+)\};', text)
    assert names and tuple(re.findall(r'"([a-z]+)"', names.group(1))) == wb.PLAN_CLOUD_TYPES
    assert "constexpr int PlanCloudTypeCount = 7;" in text


def test_the_scales_clamp_and_saturate():
    assert wb.plan_density_scale(1.0) == 1.0
    assert wb.plan_density_scale(0.1) == wb.PLAN_DENSITY_MIN
    assert wb.plan_density_scale(9.0) == wb.PLAN_DENSITY_MAX
    assert wb.plan_detail_erosion(0.35, 1.0) == 0.35
    assert wb.plan_detail_erosion(0.35, 4.0) == 1.0
    assert wb.plan_detail_erosion(0.35, -1.0) == 0.0
    text = _read(CPP)
    assert f"constexpr double PlanDensityMin = {wb.PLAN_DENSITY_MIN};" in text
    assert f"constexpr double PlanDensityMax = {wb.PLAN_DENSITY_MAX};" in text


LAYER_CASES = [
    # switch, card_cover, fair, plan_type, plan_cover, preset, thickness
    (None, None, False, None, None, "clear", 1200.0),
    (None, None, False, "cumulus", 0.5, "clear", 1200.0),
    (None, None, False, "stratocumulus", None, "clear", 3000.0),
    (None, None, False, "altocumulus", 0.45, "hazy", 3000.0),
    (None, None, False, "overcast", 0.9, "overcast", 3000.0),
    (None, None, False, "clear", 0.0, "clear", 3000.0),
    (None, None, False, "cirrus", 0.3, "clear", 3000.0),
    (None, None, False, "cumulus", 1.7, "clear", 3000.0),
    (None, None, False, "cumulus", 0.5, "rain", 3000.0),
    (None, None, False, "cumulus", 0.5, "storm", 3000.0),
    (None, None, False, "nimbostratus", 0.98, "clear", 3000.0),
    (None, 0.4, False, "overcast", 0.9, "clear", 1200.0),
    (None, 0.9, False, "clear", 0.0, "clear", 1200.0),
    (None, None, True, "overcast", 0.9, "clear", 1200.0),
    ("overcast", None, False, "cumulus", 0.5, "clear", 1200.0),
    ("overcast", 0.4, False, None, None, "clear", 1200.0),
    ("clear", 0.9, False, None, None, "clear", 1200.0),
    ("cirrus", None, False, "overcast", 0.9, "clear", 1200.0),
    ("cumulus", None, False, None, None, "rain", 3000.0),
    ("stratocumulus", None, True, None, None, "hazy", 1200.0),
]


def test_the_precedence_law():
    """-cloud-type= > the card's layer or the fair layer > the plan (not under rain
    or storm: the deck stands) > the shape's default (layer_cover_and_shape)."""
    ls = wb.layer_source
    assert ls(None, None, False, None, None, "clear", 1200.0) == (0.35, "cumulus", "shape default")
    assert ls(None, None, False, "mammatus", 0.5, "clear", 1200.0) == (0.35, "cumulus", "shape default")
    assert ls(None, None, False, "cumulus", 0.5, "clear", 1200.0) == (0.5, "cumulus", "plan")
    assert ls(None, None, False, "stratocumulus", None, "clear", 3000.0) == (0.6, "stratocumulus", "plan")
    # sky step 5: the altocumulus row (step 2 drew stratocumulus until it existed)
    assert ls(None, None, False, "altocumulus", 0.45, "hazy", 3000.0) == (0.45, "altocumulus", "plan")
    assert ls(None, None, False, "cumulus", 1.7, "clear", 3000.0) == (1.0, "cumulus", "plan")
    assert ls(None, None, False, "clear", 0.0, "clear", 3000.0) == (0.0, None, "plan")
    assert ls(None, None, False, "cirrus", 0.3, "clear", 3000.0) == (0.0, None, "plan")
    # the rain and storm decks stand above the plan's type
    assert ls(None, None, False, "cumulus", 0.5, "rain", 3000.0) == (wb.RAIN_DEFAULT_COVER, "nimbostratus", "shape default")
    assert ls(None, None, False, "cumulus", 0.5, "storm", 3000.0) == (0.98, "nimbostratus", "shape default")
    # the card is dataset truth, never overridden by data
    assert ls(None, 0.4, False, "overcast", 0.9, "clear", 1200.0) == (0.4, "cumulus", "card")
    assert ls(None, 0.9, False, "clear", 0.0, "clear", 1200.0) == (0.9, "overcast", "card")
    assert ls(None, None, True, "overcast", 0.9, "clear", 1200.0) == (wb.FAIR_LAYER["cover"], "cumulus", "card")
    # the switch is the owner's probe, above everything; the card's cover is kept with the switch's shape
    assert ls("overcast", None, False, "cumulus", 0.5, "clear", 1200.0) == (0.95, "overcast", "switch")
    assert ls("overcast", 0.4, False, None, None, "clear", 1200.0) == (0.4, "overcast", "switch")
    assert ls("clear", 0.9, False, None, None, "clear", 1200.0) == (0.0, None, "switch")
    assert ls("cumulus", None, False, None, None, "rain", 3000.0) == (0.35, "cumulus", "switch")
    assert ls("stratocumulus", None, True, None, None, "hazy", 1200.0) == (wb.FAIR_LAYER["cover"], "stratocumulus", "switch")
    with pytest.raises(ValueError):
        ls("mammatus", None, False, None, None, "clear", 1200.0)
    assert wb.LAYER_SOURCES == ("switch", "card", "plan", "shape default")


@NEEDS_CXX
def test_the_cpp_laws_are_the_python_ones(tmp_path):
    """The pure block's PlanCloudTypeIndex, CloudShapeForPlanType, LayerSource,
    PlanDensityScale and PlanDetailErosion, compiled and run over the tables above,
    equal the Python twins."""
    import subprocess
    from tests.test_world_beauty import _block

    def _compile_and_run(path, block, main):
        # test_world_beauty's harness, plus -Wno-unused-const-variable: its main
        # prints every constant of the block; this one reads only the step-2 laws.
        source = path / "pure.cpp"
        source.write_text("#include <cmath>\n#include <cstdint>\n#include <cstdio>\n#include <cstring>\n"
                          + block + "\n" + main, encoding="utf-8")
        binary = path / "pure"
        subprocess.run(["g++", "-std=c++17", "-O1", "-Wall", "-Werror", "-Wno-unused-const-variable",
                        "-o", str(binary), str(source)], check=True, capture_output=True, text=True)
        return subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout.splitlines()

    block = _block(_read(CPP), "// FLIGHTSIM-WORLD-PURE-BEGIN", "// FLIGHTSIM-WORLD-PURE-END")
    words = list(wb.PLAN_CLOUD_TYPES) + ["mammatus", ""]
    main = ["using namespace FlightSimWorldPure;", "int main() {"]
    for word in words:
        main.append(f'printf("type %d\\n", PlanCloudTypeIndex("{word}"));')
    for t in range(-2, 8):
        main.append(f'printf("shape %d\\n", CloudShapeForPlanType({t}));')
    for switch, card, fair, plan_type, plan_cover, preset, thick in LAYER_CASES:
        sw = f'CloudShapeForPlanType(PlanCloudTypeIndex("{switch}"))' if switch else "PlanCloudUnknown"
        pt = f'CloudShapeForPlanType(PlanCloudTypeIndex("{plan_type}"))' if plan_type else "PlanCloudUnknown"
        cc = -1.0 if card is None else card
        pc = -1.0 if plan_cover is None else plan_cover
        p = wb.PRESETS.index(preset)
        main.append(f"{{ double Cv = 0.0; int S = LayerCoverAndShape({cc!r}, {thick!r}, {p}, {'true' if fair else 'false'},"
                    f" nullptr, &Cv); int Src = LayerSource({sw}, {cc!r}, {'true' if fair else 'false'}, {pt}, {pc!r},"
                    f" {p}, nullptr, &Cv, &S); printf(\"layer %.17g %d %s\\n\", Cv, S, LayerSourceName(Src)); }}")
    for d in (0.1, 0.5, 1.0, 1.25, 1.5, 9.0):
        main.append(f'printf("dens %.17g\\n", PlanDensityScale({d!r}));')
    for e, d in ((0.35, 1.0), (0.35, 4.0), (0.35, -1.0), (0.25, 0.5)):
        main.append(f'printf("det %.17g\\n", PlanDetailErosion({e!r}, {d!r}));')
    main.append("return 0; }")
    lines = _compile_and_run(tmp_path, block, "\n".join(main))
    types = [int(l.split()[1]) for l in lines if l.startswith("type ")]
    assert types == [wb.PLAN_CLOUD_TYPES.index(w) if w in wb.PLAN_CLOUD_TYPES else -2 for w in words]
    shapes = [int(l.split()[1]) for l in lines if l.startswith("shape ")]
    expected = []
    for t in range(-2, 8):
        if 0 <= t < len(wb.PLAN_CLOUD_TYPES):
            s = wb.PLAN_CLOUD_SHAPES[wb.PLAN_CLOUD_TYPES[t]]
            expected.append(-1 if s is None else wb.CLOUD_PRESETS.index(s))
        else:
            expected.append(-2)
    assert shapes == expected
    layers = [l.split(None, 3) for l in lines if l.startswith("layer ")]
    assert len(layers) == len(LAYER_CASES)
    for (switch, card, fair, plan_type, plan_cover, preset, thick), (_, cv, s, src) in zip(LAYER_CASES, layers):
        ref_cover, ref_shape, ref_src = wb.layer_source(switch, card, fair, plan_type, plan_cover, preset, thick)
        assert float(cv) == ref_cover, (switch, card, fair, plan_type, plan_cover, preset)
        assert int(s) == (-1 if ref_shape is None else wb.CLOUD_PRESETS.index(ref_shape))
        assert src == ref_src
    dens = [float(l.split()[1]) for l in lines if l.startswith("dens ")]
    assert dens == [wb.plan_density_scale(d) for d in (0.1, 0.5, 1.0, 1.25, 1.5, 9.0)]
    det = [float(l.split()[1]) for l in lines if l.startswith("det ")]
    assert det == [wb.plan_detail_erosion(e, d) for e, d in ((0.35, 1.0), (0.35, 4.0), (0.35, -1.0), (0.25, 0.5))]


# -- the host ------------------------------------------------------------------------------

def test_the_bridge_parses_refuses_and_records_the_switch():
    text = _read(CPP)
    assert 'FParse::Value(*Switches, TEXT("cloud-type="), CloudTypeSwitch);' in text
    assert "world_beauty.clouds: -cloud-type=%s is not one of clear, cumulus, stratocumulus, " in text
    assert 'PlanCloudTypeIndex(TCHAR_TO_ANSI(*CloudTypeSwitch)) == PlanCloudUnknown' in text
    assert wb.CLOUD_TYPE_SWITCH == "-cloud-type"
    assert "FString CloudTypeSwitch;" in _read(HEADER)
    assert "const FFlightSimSkyPlan* SkyPlanRef = nullptr;" in _read(HEADER)
    assert "SkyPlanRef = SkyPlan;" in text
    # the switch and the catalogue
    assert "-cloud-type=" in config_surface.by_key("render_switches").note
    catalog = _between(_read(CATALOG), "world_beauty.clouds:", "world_beauty.distant_clouds:")
    for word in wb.PLAN_CLOUD_TYPES:
        assert word in catalog, word


def test_apply_clouds_reads_the_plan_through_layer_source_and_records_it():
    text = _read(CPP)
    apply = _between(text, "void FFlightSimWorldBeauty::ApplyClouds(", "void FFlightSimWorldBeauty::KeepAircraftClearOfClouds(")
    # the pinned round-2 call stands; LayerSource runs right after it on the same cover and shape
    pinned = ("State.Shape = LayerCoverAndShape(CardCover, State.TopM - State.BaseM, Preset, bFair, "
              "CloudValues.GetData(),")
    assert pinned in apply
    assert apply.index("LayerSource(SwitchShape, CardCover, bFair, PlanShape, PlanCover, Preset,") > apply.index(pinned)
    assert "CloudValues.GetData(), &State.Cover, &State.Shape);" in apply
    # the plan's fields arrive through the struct, with the header's defaults when absent
    assert "const bool bPlanFields = SkyPlanRef != nullptr && SkyPlanRef->bCloudPlanFields;" in apply
    assert "const double PlanCover = bPlanFields ? SkyPlanRef->CloudCoverage : -1.0;" in apply
    assert "const double PlanDensity = bPlanFields ? SkyPlanRef->CloudDensity : 1.0;" in apply
    assert "const double PlanDetail = bPlanFields ? SkyPlanRef->CloudDetail : 1.0;" in apply
    # the owner's Density and DetailStrength: the row x the plan, on the material
    assert ('SetScalarParameterValue(TEXT("ExtinctionPerM"),\n'
            '\t\t                                        static_cast<float>(CloudRow[CldExtinctionPerM] * DensityScale));') in apply
    assert 'SetScalarParameterValue(TEXT("DetailErosion"), static_cast<float>(DetailErosion));' in apply
    assert "const double DensityScale = PlanDensityScale(PlanDensity);" in apply
    assert "const double DetailErosion = PlanDetailErosion(CloudRow[CldDetailErosion], PlanDetail);" in apply
    assert "State.DensityScale = DensityScale;" in apply
    # Coverage is the cover LayerSource decided; NoiseScale is the row's; Wind is untouched here
    assert 'SetScalarParameterValue(TEXT("Coverage"), static_cast<float>(State.Cover));' in apply
    assert 'SetScalarParameterValue(TEXT("ShapeScaleKm"), static_cast<float>(CloudRow[CldShapeScaleKm]));' in apply
    assert 'SetVectorParameterValue(TEXT("WindOffsetM"), FLinearColor(0.0f, 0.0f, 0.0f, 0.0f));' in apply
    # the record
    for key in ("plan", "fields_source", "cloud_type_known", "seed_matches_card", "cloud_type_switch", "precedence",
                "owner_parameters", "exposure_sees_plan_clouds", "measure_path", "cloud_type_source",
                "cloud_type_applied", "cloud_type_requested", "component_source", "engine_stack_shadowed",
                "plan_density_scale", "extinction_per_m_applied", "detail_erosion_applied", "hidden_layers",
                "plan_component_shadowed_by_card", "engine_stack_basis"):
        assert f'TEXT("{key}")' in apply, key
    assert 'PlanOut->SetBoolField(TEXT("exposure_sees_plan_clouds"), false);' in apply
    assert "UNMEASURED" in apply and "UNCALIBRATED" in apply
    # the occlusion row reads the extinction drawn
    advance = text[text.index("void FFlightSimWorldBeauty::Advance"):]
    assert "CldExtinctionPerM] * Layer.DensityScale," in advance


def test_hidden_only_for_no_layer_and_the_sky_capture_only_on_the_shadowed_component():
    text = _read(CPP)
    apply = _between(text, "void FFlightSimWorldBeauty::ApplyClouds(", "void FFlightSimWorldBeauty::KeepAircraftClearOfClouds(")
    assert text.count("SetVisibleInRealTimeSkyCaptures(false)") == 1
    shadowed = _between(apply, "if (bShadowed)\n\t\t{", "}\n\t\telse\n\t\t{\n\t\t\tCloudLayers.Add(State);")
    assert "Cloud->SetVisibleInRealTimeSkyCaptures(false);" in shadowed
    assert text.count("Cloud->SetVisibility(false);") == 1
    hidden = _between(apply, "if (State.Shape == PlanCloudNoLayer)\n\t\t{", "continue;\n\t\t}")
    assert "Cloud->SetVisibility(false);" in hidden and 'TEXT("hidden_layers")' in apply
    # the plan's component is told apart by its owner; the fair one by name
    assert "Cloud->GetOwner()->IsA<AVolumetricCloud>()" in apply
    assert 'Cloud->GetName() == TEXT("FairCumulus") ? TEXT("fair") : TEXT("card look.clouds")' in apply
    assert "const bool bShadowed = bPlanComponent && bCardComponent && ComponentSrc == TEXT(\"sky plan\");" in apply


def test_the_round_95_lowering_keys_on_stated_heights_not_the_plan_type():
    """The design said bStatedLayer would turn true for a plan-stated cover; the
    code proves that wrong: the plan's heights are its placement law (>= 1 km
    above the flight), not weather data, so a PLAN cumulus over a cruise is still
    lowered to the fair slab (c641a8c4 / round 95) and the camera stays clear."""
    text = _read(CPP)
    apply = _between(text, "void FFlightSimWorldBeauty::ApplyClouds(", "void FFlightSimWorldBeauty::KeepAircraftClearOfClouds(")
    assert "const bool bStatedLayer = CardCover >= 0.0 || bFair;" in apply
    assert "CumulusLayerLowered(State.Shape == CloudCumulus, bStatedLayer, State.BaseM)" in apply
    assert wb.cumulus_layer_lowered(True, False, 11000.0)
    assert wb.FAIR_LAYER["top_m"] < 10000.0 - 1000.0


def test_the_commandlet_passes_the_plan_only_at_the_beauty_site():
    text = _read(COMMANDLET)
    assert text.count("bPhysicalSky ? &SkyPlan : nullptr") == 1
    call = _between(text, "if (bBeauty && !WorldBeauty.Build(", "{ return Fail(Error); }")
    assert "bPhysicalSky ? &SkyPlan : nullptr" in call
    header = _read(HEADER)
    assert "FFlightSimGoogleTiles& Tiles, const FFlightSimSkyPlan* SkyPlan, FString& Error);" in header
    assert "struct FFlightSimSkyPlan;" in header
    # the measure render.json gains no field: scene.sky is not told about the cloud fields
    sky_record = _between(text, 'SkyJson->SetStringField(TEXT("plan"), SkyPlan.SourcePath);', 'Scene->SetObjectField(TEXT("sky"), SkyJson);')
    for name in ("CloudType", "CloudCoverage", "CloudDensity", "CloudDetail"):
        assert name not in sky_record, name


def test_the_bridge_check_and_the_docs():
    check = _read(CHECK)
    assert 'sky_check "world: VolumetricCloud SetVisibleInRealTimeSkyCaptures" "$VC" "void SetVisibleInRealTimeSkyCaptures(bool bValue)"' in check
    assert 'sky_check "world: SceneComponent SetVisibility" "Classes/Components/SceneComponent.h"' in check
    vfp = _read(VFP)
    entry = vfp[vfp.index("### Sky step 2"):]
    assert "UNMEASURED" in entry and "UNCALIBRATED" in entry
    assert "-cloud-type=" in entry and "visual_fix_round.ps1" in entry
    design = _read(DESIGN)
    assert "Built (sky step 2" in design
