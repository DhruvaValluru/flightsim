"""The airframe's sky reflection (item "aircraft", 2026-11-14;
scripts/aircraft_paint_reflect.py), without an engine: the numpy-free twins
of the two HLSL bodies, the wet layer's rivulet lean, and the contracts
between the module, the shaders, the masters builder, the look manifest and
FlightSimAircraftFX.cpp.

Nothing here measures a rendered frame: every number is UNCALIBRATED, and the
graph is UNCOMPILED on this machine. What the tests do prove: with the gain
at the master's 0 (the switch off, or no sun) the graft adds exactly nothing;
a matte dry panel adds nothing; the same panel wet mirrors the sky; the
graft is Emissive only, so the label passes see the same surface.
"""

import math
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import aircraft_look as look  # noqa: E402
import aircraft_glass_reflect as glass  # noqa: E402
import aircraft_paint_reflect as paint  # noqa: E402
import aircraft_wet_layer as wet  # noqa: E402

BRIDGE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge"
FX_CPP = (BRIDGE / "Private/FlightSimAircraftFX.cpp").read_text(encoding="utf-8")
FX_H = (BRIDGE / "Public/FlightSimAircraftFX.h").read_text(encoding="utf-8")
MASTERS = (REPO / "scripts/ue_aircraft_master_materials.py").read_text(encoding="utf-8")
MODULE = (REPO / "scripts/aircraft_paint_reflect.py").read_text(encoding="utf-8")
LAYER = (REPO / "scripts/aircraft_wet_layer.py").read_text(encoding="utf-8")
SHADERS = REPO / look.SHADER_DIR
UV_HLSL = (SHADERS / "paint_env_uv.hlsl").read_text(encoding="utf-8")
REFLECT_HLSL = (SHADERS / "paint_env_reflect.hlsl").read_text(encoding="utf-8")
WET_HLSL = (SHADERS / "aircraft_wet.hlsl").read_text(encoding="utf-8")
APPLY = FX_CPP[FX_CPP.index("void FFlightSimAircraftFX::ApplyMaterials("):FX_CPP.index("double FFlightSimAircraftFX::CanopyReflectGain(")]
UPDATE = FX_CPP[FX_CPP.index("void FFlightSimAircraftFX::UpdateCanopyReflect()"):FX_CPP.index("void FFlightSimAircraftFX::SetCanopyReflectCamera(")]


def _documented(text):
    return tuple(re.findall(r"^//\s{2,}(\w+)\s+float", text, re.M))


# -- the shaders and their twins ---------------------------------------------------

def test_the_hlsl_input_names_match_shader_inputs():
    for name, text in (("paint_env_uv", UV_HLSL), ("paint_env_reflect", REFLECT_HLSL)):
        assert _documented(text) == paint.PAINT_REFLECT_SHADER_INPUTS[name] == look.SHADER_INPUTS[name], name
        body = "\n".join(line for line in text.splitlines() if not line.startswith("//"))
        for pin in paint.PAINT_REFLECT_SHADER_INPUTS[name]:
            assert re.search(rf"\b{pin}\b", body), (name, pin)
        # bounded: no loops at all, no texture fetch inside the Custom node, no discard
        assert "for (" not in body and "while" not in body
        assert "Texture2DSample" not in body and "discard" not in body
    assert f"const float RoughCutoff = {paint.HLSL_ROUGH_CUTOFF};" in REFLECT_HLSL
    assert f"const float CoatF0 = {paint.HLSL_COAT_F0};" in REFLECT_HLSL
    assert "Lean.x * ax + Lean.y * ay + Lean.z * az" in UV_HLSL


def test_the_strip_uv_is_the_canopy_lanes_convention_and_the_lean_turns_it():
    n, v, sun = (0.0, 0.0, 1.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)
    ndv, zero, u, vv = paint.env_uv(n, v, sun)
    lut_u, _, glass_u, glass_v = glass.reflect_uv(n, v, sun)
    assert zero == 0.0 and ndv == pytest.approx(1.0)
    assert (u, vv) == (pytest.approx(glass_u), pytest.approx(glass_v))   # the same strip, read the same way
    # a lean of zero changes nothing; a lean across the flow moves the lookup
    assert paint.env_uv(n, v, sun, lean=(0.0, 0.0, 0.0), strength=1.0) == pytest.approx((ndv, zero, u, vv))
    assert paint.env_uv(n, v, sun, lean=(0.0, 0.4, 0.0), strength=0.0) == pytest.approx((ndv, zero, u, vv))
    leaned = paint.env_uv(n, v, sun, lean=(0.0, 0.4, 0.0), strength=1.0)
    assert leaned[0] < ndv and leaned[2] != pytest.approx(u)
    # the lean is in the object frame: rotating the object rotates it
    axes = ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    rotated = paint.env_uv(n, v, sun, lean=(0.4, 0.0, 0.0), strength=1.0, axes=axes)
    assert rotated == pytest.approx(leaned)


def test_gain_zero_adds_exactly_nothing_everywhere():
    env, tint = (0.7, 0.72, 0.8), (1.0, 1.0, 1.0)
    for ndv in (0.0, 0.3, 1.0):
        for rough, coat in ((0.04, 1.0), (0.5, 0.0), (0.08, 0.3)):
            out = paint.reflect_emissive(env, glass.ENV_ENCODE_SCALE, 0.0, tint, ndv, (0.04,) * 3, rough, coat, 0.1)
            assert out == (0.0, 0.0, 0.0)
    # Amount 0 (a class opting out) adds nothing either
    assert paint.reflect_emissive(env, 1.0, 5.0, tint, 0.2, (0.04,) * 3, 0.04, 1.0, 0.03, amount=0.0) == (0.0,) * 3


def test_a_matte_dry_panel_adds_nothing_and_the_same_panel_wet_mirrors_the_sky():
    # the J-11's PLAAF grey: ClearCoat 0, Roughness 0.5 (assets/aircraft_config/look/J11.json)
    j11 = look.load_config("J11")["class_scalars"]["paint"]
    assert j11["ClearCoat"] == 0.0 and j11["Roughness"] == 0.5 == paint.HLSL_ROUGH_CUTOFF
    env, tint, f0 = (0.7, 0.72, 0.8), (1.0, 1.0, 1.0), (0.04,) * 3
    for ndv in (0.05, 0.5, 1.0):
        dry = paint.reflect_emissive(env, 1.0, 100.0, tint, ndv, f0, j11["Roughness"], j11["ClearCoat"], 1.0)
        assert dry == (0.0, 0.0, 0.0)
        # wet: aircraft_wet_layer takes the roughness to WetRoughness and the coat to 1 at WetCoatRoughness
        _, r_wet, coat_wet = wet.wet_surface([0.5], [j11["Roughness"]], 1.0, 0.05)
        wet_out = paint.reflect_emissive(env, 1.0, 100.0, tint, ndv, f0, float(r_wet[0]), float(coat_wet),
                                         wet.WET_DEFAULTS["WetCoatRoughness"])
        assert all(c > 0.0 for c in wet_out)
    # grazing mirrors more than face-on (Fresnel), and the face-on share is the coat's F0 x gloss
    face = paint.mirror(1.0, 0.04, 0.08, coat=1.0, coat_roughness=0.03)
    graze = paint.mirror(0.05, 0.04, 0.08, coat=1.0, coat_roughness=0.03)
    assert 0.0 < face < graze <= 1.0
    assert face == pytest.approx(paint.HLSL_COAT_F0 * paint.gloss(0.03) + (1 - paint.HLSL_COAT_F0) * 0.04 * paint.gloss(0.08))


def test_the_mirror_fades_with_roughness_and_follows_ue_f0():
    # (1 - r / 0.5)^2: 1 at a mirror, 0 at the cutoff and above
    assert paint.gloss(0.0) == 1.0 and paint.gloss(0.25) == pytest.approx(0.25)
    assert paint.gloss(0.5) == 0.0 and paint.gloss(0.9) == 0.0
    shares = [paint.mirror(0.5, 0.04, r) for r in (0.02, 0.1, 0.2, 0.3, 0.45, 0.5)]
    assert shares == sorted(shares, reverse=True) and shares[-1] == 0.0
    # UE's F0: a dielectric at Specular 0.5 is 0.04, a metal its base colour, a worn edge in between
    assert paint.ue_f0((0.3, 0.4, 0.5), 0.5, 0.0) == pytest.approx((0.04, 0.04, 0.04))
    assert paint.ue_f0(look.ALUMINIUM_F0, 0.5, 1.0) == pytest.approx(look.ALUMINIUM_F0)
    half = paint.ue_f0(look.ALUMINIUM_F0, 0.5, 0.5)
    assert all(0.04 < c < a for c, a in zip(half, look.ALUMINIUM_F0))
    # a rough metal shows no mirror rim: the grazing term is capped by 1 - roughness
    assert paint.schlick(0.9, 0.0, 0.3) == pytest.approx(0.9)
    assert paint.schlick(0.04, 0.0, 0.0) == pytest.approx(1.0)
    # bare metal takes half (the engine's own IBL already mirrors it at F0 0.92)
    assert paint.class_default("Amount{cls}", "bare_metal") == 0.5 < paint.class_default("Amount{cls}", "paint") == 1.0
    assert paint.class_default(0.0, "paint") == 0.0
    with pytest.raises(ValueError):
        paint.class_default("Amount{cls}", "glass")


def test_the_rivulet_lean_is_zero_on_the_crest_and_off_the_line_and_odd():
    w = 0.15
    assert wet.rivulet_lean(0.0, w) == 0.0 and paint.rivulet_lean(0.0, w) == 0.0
    assert wet.rivulet_lean(w, w) == 0.0 and wet.rivulet_lean(2 * w, w) == 0.0
    for a in (0.02, 0.05, 0.075, 0.1):
        assert wet.rivulet_lean(a, w) > 0.0
        assert wet.rivulet_lean(-a, w) == pytest.approx(-wet.rivulet_lean(a, w))
        assert wet.rivulet_lean(a, w) == paint.rivulet_lean(a, w)
    # the HLSL: the same expression, an additional output, never the Normal
    assert "float slope = clamp((f - offset) / width, -1.0, 1.0) * profile * 2.0;" in WET_HLSL
    assert "lean += w * slope * shape * present * acrossDir;" in WET_HLSL
    assert f"{wet.WET_LEAN_OUTPUT} = lean;" in WET_HLSL
    # the layer never wires the lean into its Make (Normal is a pass-through): the
    # output is declared there and read only by the paint reflection's lookup
    layer_code = "\n".join(line for line in LAYER[LAYER.index("def add_wet_layer"):LAYER.index(
        "def add_canopy_scratch")].splitlines() if not line.strip().startswith("#"))
    assert layer_code.count("WET_LEAN_OUTPUT") == 1 and "WetLean" not in layer_code
    assert "WET_LEAN_OUTPUT, make" not in layer_code and "a_out=WET_LEAN_OUTPUT" not in layer_code
    assert "Normal" in wet.PASS_THROUGH
    # the wet inputs are unchanged (the lean is an output): the existing contracts hold
    assert _documented(WET_HLSL) == wet.WET_SHADER_INPUTS["aircraft_wet"]


# -- the masters builder --------------------------------------------------------------

def test_the_paint_and_bare_metal_masters_take_the_graft_after_the_wet_layer():
    assert re.search(r'^LOOK_GENERATION = "16"$', MASTERS, re.M)
    surface = MASTERS[MASTERS.index("def _surface("):MASTERS.index("def create_aircraft_paint")]
    assert surface.count("wet = aircraft_wet_layer.add_wet_layer(material, sys.modules[__name__], cls, raw_base=raw_base)") == 1
    assert surface.count("aircraft_paint_reflect.add_reflection(material, sys.modules[__name__], cls, aircraft_wet_layer, wet)") == 1
    assert surface.index("_use_attributes(material, out)") < surface.index("aircraft_wet_layer.add_wet_layer") \
        < surface.index("aircraft_paint_reflect.add_reflection") < surface.index("_finish(")
    # the glass, rubber, flat and coat masters are untouched
    for start, end in (("def _glass(", "def create_aircraft_rubber"), ("def create_aircraft_rubber", "def _fx("),
                       ("def create_aircraft_probe_flat", "def create_aircraft_paint_coat"),
                       ("def create_aircraft_paint_coat", "def create_aircraft_bare_metal")):
        assert "aircraft_paint_reflect" not in MASTERS[MASTERS.index(start):MASTERS.index(end)], start
    assert paint.CLASSES == ("paint", "bare_metal") and paint.COATED_CLASSES == ("paint",)
    assert set(paint.CLASSES) == set(paint.CLASS_KEYS) <= set(look.CLASS_MASTERS)


def test_the_graft_is_emissive_only_and_uses_only_the_builders_helpers():
    add = MODULE[MODULE.index("def add_reflection("):]
    # every attribute the wet layer wires passes straight through; only Emissive is new
    for name in wet.PASS_THROUGH:
        assert name in paint.PASS_THROUGH
    assert set(paint.PASS_THROUGH) == {"BaseColor", "Metallic", "Specular", "Roughness", "Normal", "AmbientOcclusion"}
    assert paint.COAT_PASS_THROUGH == ("ClearCoat", "ClearCoatRoughness")
    assert 'make, wet_layer._pin("EmissiveColor")' in add
    assert add.count("make, ") == 3   # the pass-through loop, the coat loop, the emissive
    for forbidden in ("WorldPositionOffset", "blend_mode", "TRANSLUCENT", "shading_model", "Substrate",
                      "tangent_space_normal", '"Normal")', "SceneTexture", "ReflectionCapture"):
        assert forbidden not in add, forbidden
    # the lookup reads the wet layer's lean output, never the material's normal
    assert "(wet_node, wet_layer.WET_LEAN_OUTPUT)" in add
    assert wet.WET_LEAN_OUTPUT == "WetLean"
    # the helpers used exist on scripts/ue_aircraft_master_materials.py (and the two shared ones)
    import ast
    defined = {n.name for n in ast.parse(MASTERS).body if isinstance(n, ast.FunctionDef)}
    used = set(re.findall(r"\blib\.(\w+)\(", MODULE))
    assert used and used <= defined, used - defined
    shared = set(re.findall(r"\bwet_layer\.(\w+)\(", MODULE))
    assert shared == {"_graft", "_commit", "_pin"}
    glass_used = set(re.findall(r"\b_glass\.(\w+)\(", MODULE))
    assert glass_used == {"texture_import", "texture_path", "import_textures", "_texture_parameter"}
    # the strip is the canopy lane's tier-0 strip: no new asset
    assert paint.ENV_TEXTURE_NAME == glass.TIER_TEXTURES[0]["GlassEnv"] == "T_GlassEnv_64"
    provenance = (glass.LANE_DIR + "/PROVENANCE.json")
    assert "T_GlassEnv_64.png" in Path(provenance).read_text(encoding="utf-8")


def test_the_master_scalars_default_from_defaults_and_do_not_collide():
    for cls in paint.CLASSES:
        names = set(paint.MASTER_SCALARS) | set(paint.MASTER_VECTORS)
        assert not names & set(look.CLASS_SCALARS[cls]), cls
        assert not names & set(look.CLASS_VECTORS[cls]), cls
        assert not names & (set(wet.WET_MASTER_SCALARS) | set(wet.WET_DYNAMIC_PARAMETERS) | set(wet.PROBE_SCALARS)), cls
        assert not names & (set(glass.MASTER_SCALARS) | set(glass.MASTER_VECTORS)), cls
    assert paint.MASTER_SCALARS[paint.GAIN_PARAMETER] == 0.0   # the master adds nothing by itself
    assert paint.MASTER_SCALARS["PaintEnvEncodeScale"] == glass.ENV_ENCODE_SCALE
    # every default reaches a master scalar
    reached = {template.format(cls=key) for template in paint.MASTER_SCALARS.values() if isinstance(template, str)
               for key in paint.CLASS_KEYS.values()}
    assert set(paint.DEFAULTS) <= reached


# -- the look manifest and the switch -------------------------------------------------

def test_the_look_manifest_carries_the_group_and_the_switch_is_on_by_default():
    group = paint.constants_group()
    assert set(group) == set(paint.DEFAULTS)
    for key, entry in group.items():
        assert entry["value"] == float(paint.DEFAULTS[key])
        assert entry["calibration"] == look.UNCALIBRATED == paint.UNCALIBRATED and entry["probe"]
    assert ("paint-reflect=", True) in look.FX_SWITCHES
    assert paint.parse_paint_reflect("") is True
    assert paint.parse_paint_reflect("-paint-reflect=off") is False
    assert paint.parse_paint_reflect("-aircraft-look=off") is False
    assert paint.parse_paint_reflect("-canopy-reflect=on") is True
    with pytest.raises(look.LookError):
        paint.parse_paint_reflect("-paint-reflect=maybe")
    for name in ("paint_env_uv", "paint_env_reflect"):
        assert (SHADERS / f"{name}.hlsl").is_file()
    assert "UNCALIBRATED" in MODULE and "UNCOMPILED" in MODULE


# -- the host --------------------------------------------------------------------------

def test_the_host_parses_the_switch_and_sets_the_gain_only_on_a_gen13_master():
    parse = FX_CPP[FX_CPP.index("void FFlightSimAircraftFXOptions::ParseParams"):]
    parse = parse[:parse.index("\n}\n")]
    assert 'AircraftFxSwitch(Params, TEXT("paint-reflect="), true, SwitchError)' in parse
    assert "bPaintReflect = bAll && bPaintReflectSwitch;" in parse
    assert "bool bPaintReflect = true;" in FX_H
    assert "TArray<UMaterialInstanceDynamic*> PaintReflectMids;" in FX_H
    assert f'AircraftFxPaintEnvGainParam = TEXT("{paint.GAIN_PARAMETER}")' in FX_CPP
    assert f'AircraftFxPaintEnvTintParam = TEXT("{paint.TINT_PARAMETER}")' in FX_CPP
    assert f'AircraftFxPaintSunParam = TEXT("{paint.SUN_PARAMETER}")' in FX_CPP
    block = APPLY[APPLY.index("if (Options.bPaintReflect)"):]
    block = block[:block.index("// Round 24 (aircraft_wet_layer.PROBE_SCALARS")]
    # a master without the parameter is counted stale, never written to
    assert "FHashedMaterialParameterInfo(FName(AircraftFxPaintEnvGainParam)), PaintGain))" in block
    assert "++PaintReflectStale;" in block and "PaintReflectMids.Add(LookMid);" in block
    # it sits inside the paint / bare-metal branch: glass and rubber slots never take it
    gate = APPLY.index("if (bProbeSlot && LookMid != nullptr)")
    assert gate < APPLY.index("if (Options.bPaintReflect)") < APPLY.index("Part->SetMaterial(Slot, LookMid != nullptr")
    # the tint and cover are computed when either reflection is on; the glass master loads only under its own switch
    assert "if (Options.bCanopyReflect || Options.bPaintReflect)" in APPLY
    assert APPLY.index("if (Options.bCanopyReflect || Options.bPaintReflect)") < APPLY.index(
        "GlassReflect = LoadObject<UMaterialInterface>(nullptr, ReflectPath);")
    assert 'Row->SetObjectField(TEXT("paint_reflect"), PaintReflectRow);' in APPLY
    assert 'PaintReflectRow->SetNumberField(TEXT("slots_stale_master"), PaintReflectStale);' in APPLY


def test_the_gain_is_the_canopys_rule_each_step_with_no_interior_zero():
    assert "if (ReflectMids.Num() == 0 && PaintReflectMids.Num() == 0)" in UPDATE
    assert "CanopyReflectGain(Intensity, ElevationDeg, ReflectCover, false)" in UPDATE
    assert "Mid->SetScalarParameterValue(FName(AircraftFxPaintEnvGainParam), static_cast<float>(PaintGain));" in UPDATE
    assert "Mid->SetVectorParameterValue(FName(AircraftFxPaintSunParam)," in UPDATE
    assert 'PaintReflectRow->SetNumberField(TEXT("gain"), PaintGain);' in UPDATE
    # the canopy's own loop is unchanged
    assert 'Mid->SetScalarParameterValue(TEXT("GlassEnvGain"), static_cast<float>(Gain));' in UPDATE
    # called each captured step (the sun may be animated), before the wet scalars
    advance = FX_CPP[FX_CPP.index("void FFlightSimAircraftFX::Advance("):]
    assert advance.index("UpdateCanopyReflect();") < advance.index("Wet.Advance(LookMids")
    # the twin of the gain the host sets
    assert paint.SWITCH_DEFAULT is True
    gain = glass.canopy_reflect_gain(10.0, 45.0, 0.0)
    assert gain == pytest.approx(0.10 * 10.0 / math.pi / glass.STRIP_HORIZON_LUMINANCE)
    assert glass.canopy_reflect_gain(10.0, -5.0, 0.0) == 0.0            # night: nothing
    assert glass.canopy_reflect_gain(10.0, 45.0, 1.0) == pytest.approx(gain * 0.25)   # overcast: dimmed, not off


def test_labels_are_untouched_the_graft_changes_emissive_only():
    # the beauty-only gate and the label isolation are the aircraft lane's (tests/test_aircraft_look.py,
    # tests/test_beauty_label_isolation.py); here: nothing of this item reaches a label capture.
    for text in (MODULE, UV_HLSL, REFLECT_HLSL):
        assert "WorldPositionOffset" not in text and "WORLD_POSITION_OFFSET" not in text
        assert "blend_mode" not in text and "TRANSLUCENT" not in text
        assert "ConfigureLabelCapture" not in text and "CustomDepth" not in text
    assert 'TEXT("labels"), TEXT("unchanged: the paint and bare-metal masters stay opaque ")' in APPLY
    # no label render ever reaches the FX: the header's contract, still stated
    assert "BEAUTY ONLY" in FX_H
