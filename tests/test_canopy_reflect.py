"""The canopy reflection (scripts/aircraft_glass_reflect.py): tiers 0-1 of
swarm lane aircraft_exterior.glass.coastal, beauty only, OFF unless
-canopy-reflect=on.

Read from source (nothing compiles or renders on this Mac): the switch
reaches the commandlet's argv and the host's parse, the reflect masters are
opaque and never replace a thin instance or the -labels rule, the lane's bake
is reproducible against its PROVENANCE, and the host's gain is the Python
twin's. How it LOOKS is the Windows A/B round's question, not this file's.
"""

import hashlib
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import aircraft_glass_reflect as reflect  # noqa: E402
import aircraft_look as look  # noqa: E402
from webapp.runs import with_render_switches  # noqa: E402

PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
PUBLIC = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public"
FX_CPP = (PRIVATE / "FlightSimAircraftFX.cpp").read_text(encoding="utf-8")
FX_H = (PUBLIC / "FlightSimAircraftFX.h").read_text(encoding="utf-8")
COMMANDLET = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
MASTERS = (REPO / "scripts/ue_aircraft_master_materials.py").read_text(encoding="utf-8")
REFLECT_PY = (REPO / "scripts/aircraft_glass_reflect.py").read_text(encoding="utf-8")
SHADERS = REPO / look.SHADER_DIR
PARSE = FX_CPP[FX_CPP.index("void FFlightSimAircraftFXOptions::ParseParams"):]
PARSE = PARSE[:PARSE.index("\n}\n")]
APPLY = FX_CPP[FX_CPP.index("void FFlightSimAircraftFX::ApplyMaterials"):]
APPLY = APPLY[:APPLY.index("\n}\n")]

PLANNED = ["UnrealEditor-Cmd.exe", "FlightSim.uproject", "-run=FlightSimBridge.FlightSimRender",
           "-quality=beauty", "-beauty-look=C:/runs/x/beauty_look.json", "-labels"]


# -- the switch ------------------------------------------------------------------

def test_the_switch_reaches_the_argv_ahead_of_the_planned_flags():
    out = with_render_switches(PLANNED, "-canopy-reflect=on -canopy-reflect-tier=1")
    run = out.index("-run=FlightSimBridge.FlightSimRender")
    assert out[run + 1:run + 3] == ["-canopy-reflect=on", "-canopy-reflect-tier=1"]
    assert out[run + 3:] == PLANNED[3:]                       # -labels stays: the web app's renders carry it


def test_the_switch_is_off_by_default_and_under_aircraft_look_off():
    assert ("canopy-reflect=", False) in look.FX_SWITCHES
    assert reflect.parse_canopy_reflect("") == (False, 0)
    assert reflect.parse_canopy_reflect("-canopy-reflect=off") == (False, 0)
    assert reflect.parse_canopy_reflect("-canopy-reflect=on") == (True, 0)
    assert reflect.parse_canopy_reflect("-canopy-reflect=on -canopy-reflect-tier=1") == (True, 1)
    assert reflect.parse_canopy_reflect("-aircraft-look=off -canopy-reflect=on") == (False, 0)
    # "canopy-reflect=" is not a prefix of the tier key: the tier word alone turns nothing on
    assert reflect.parse_canopy_reflect("-canopy-reflect-tier=1") == (False, 1)


@pytest.mark.parametrize("params", ["-canopy-reflect=yes", "-canopy-reflect=on -canopy-reflect-tier=2",
                                    "-canopy-reflect-tier=3", "-canopy-reflect-tier=fine"])
def test_a_bad_word_is_refused_by_name(params):
    with pytest.raises(look.LookError, match=r"^aircraft_look\.switch: "):
        reflect.parse_canopy_reflect(params)


def test_the_host_parse_is_the_twin():
    # the environment channel (FLIGHTSIM_RENDER_SWITCHES) is the same string the switch rides
    assert 'FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"))' in PARSE
    assert 'AircraftFxSwitch(Params, TEXT("canopy-reflect="), false, SwitchError)' in PARSE
    assert "bCanopyReflect = bAll && bCanopyReflectSwitch;" in PARSE
    assert 'FParse::Value(*Params, TEXT("canopy-reflect-tier="), TierWord)' in PARSE
    assert 'TierWord == TEXT("0") || TierWord == TEXT("1")' in PARSE
    assert "aircraft_look.switch: -canopy-reflect-tier=%s is not 0 or 1" in PARSE
    assert "bool bCanopyReflect = false;" in FX_H and "int32 CanopyReflectTier = 0;" in FX_H
    # Build refuses a switch error by name before anything is drawn
    assert "if (!Options.SwitchError.IsEmpty())" in FX_CPP


def test_off_loads_nothing_and_changes_nothing():
    load = APPLY.index("GlassReflect = LoadObject<UMaterialInterface>(nullptr, ReflectPath);")
    gate = APPLY.rindex("if (Options.bCanopyReflect)", 0, load)
    assert APPLY.index("{", gate) < load
    # every reflect branch in the slot loop is under the switch
    for match in re.finditer(r"GlassReflect, Part\)", APPLY):
        branch = APPLY.rindex("if (", 0, match.start())
        assert "Options.bCanopyReflect" in APPLY[branch:match.start()]
    assert 'Row->SetObjectField(TEXT("canopy_reflect"), ReflectRow);' in APPLY
    assert "off (the default; -canopy-reflect=on is the A/B)" in APPLY
    # the master's own gain is 0: a reflect master drawn without the host's gain adds nothing
    assert reflect.MASTER_SCALARS[reflect.GAIN_PARAMETER] == 0.0
    assert reflect.reflect_emissive((0.5, 0.5, 0.5), (0.7, 0.7, 0.7), 1.5, 0.0) == (0.0, 0.0, 0.0)


# -- labels stay opaque ------------------------------------------------------------

def test_the_reflect_masters_are_the_opaque_glass_graph_plus_emissive():
    glass = MASTERS[MASTERS.index("def _glass("):MASTERS.index("def create_aircraft_rubber")]
    assert "blend_mode" not in glass and "TRANSLUCENT" not in glass and "two_sided" not in glass
    assert '"MSM_DEFAULT_LIT"' in glass
    assert "if reflect_tier is not None:" in glass
    assert glass.index("add_canopy_scratch") < glass.index("aircraft_glass_reflect.add_reflection")
    assert 'def create_aircraft_glass():\n    _glass("M_AircraftGlass")\n' in MASTERS   # gen-10 graph exactly
    thin = MASTERS[MASTERS.index("def create_aircraft_glass_thin"):MASTERS.index("#: Every master this module")]
    assert "add_reflection" not in thin                     # the thin canopy never gets it
    creators = MASTERS[MASTERS.index("CREATORS = ("):MASTERS.index("CREATED = (")]
    assert "create_aircraft_glass_reflect, create_aircraft_glass_reflect_fine" in creators
    created = MASTERS[MASTERS.index("CREATED = ("):MASTERS.index("def build_all")]
    for name in reflect.MASTERS.values():
        assert f'"{name}"' in created
    assert look.CANOPY_REFLECT_MASTERS == reflect.MASTERS
    assert re.search(r'^LOOK_GENERATION = "11"$', MASTERS, re.M)


def test_the_graft_changes_only_emissive_and_roughness():
    add = REFLECT_PY[REFLECT_PY.index("def add_reflection("):]
    # BaseColor and Normal (what SCS_BaseColor / SCS_Normal read) pass straight through
    for name in ("BaseColor", "Normal", "Metallic", "Specular", "Tangent", "Anisotropy", "AmbientOcclusion"):
        assert name in reflect.PASS_THROUGH
    assert "WorldPositionOffset" not in add and "Opacity" not in add and "blend_mode" not in add
    assert 'lib._link(emissive, "", make, wet_layer._pin("EmissiveColor"))' in add
    assert add.count("lib._link(") == 3   # pass-through loop, roughness, emissive


def test_the_host_never_swaps_a_thin_instance_or_the_labels_rule():
    labels = APPLY.index("if (!Options.bLabels)")
    branch = APPLY.index("if (Options.bCanopyReflect && bThin)")
    assert labels < branch                                   # the -labels choice is made first, unchanged
    swap = APPLY[branch:APPLY.index("if (LookMid == nullptr)", branch)]
    assert "++ReflectThinKept;" in swap.split("else if")[0]  # a thin slot keeps its thin instance
    assert "ProbeBaseName == AircraftFxOpaqueGlassMaster" in swap
    assert 'AircraftFxOpaqueGlassMaster = TEXT("M_AircraftGlass")' in FX_CPP
    assert "LookMid->CopyParameterOverrides(LookMic);" in swap
    assert "ReflectMids.Add(LookMid);" in swap
    # the reflect MID is also a look MID: the wet layer's per-step scalars still reach it
    assert "if (LookMid != nullptr) { LookMids.Add(LookMid); }" in APPLY
    for tier, name in reflect.MASTERS.items():
        assert f'TEXT("/Game/FlightSim/Aircraft/{name}.{name}")' in FX_CPP
    # compile-checked like the class masters; a failure keeps the look instance
    assert "GlassReflectProblem = CompileProblemOf(GlassReflect);" in APPLY


def test_an_interior_camera_gets_no_sky_in_the_pane():
    assert reflect.canopy_reflect_gain(120000.0, 30.0, interior=True) == 0.0
    assert tuple(reflect.INTERIOR_PRESETS) == ("cockpit", "shoulder")
    call = COMMANDLET[COMMANDLET.index("AircraftFX.SetCanopyReflectCamera("):][:200]
    assert 'ReflectPreset == TEXT("cockpit") || ReflectPreset == TEXT("shoulder")' in call
    assert "AircraftFXOptions.Sun = VisualScene.Sun;" in COMMANDLET
    # set before the frame loop's first Advance
    assert COMMANDLET.index("AircraftFX.SetCanopyReflectCamera(") < COMMANDLET.index("AircraftFX.Advance(")


# -- the gain and tint (the host's numbers are the twin's) ----------------------------

def test_the_gain_twin():
    g = reflect.canopy_reflect_gain(120000.0, 30.0)
    assert g == pytest.approx(0.10 * 120000.0 / math.pi / reflect.STRIP_HORIZON_LUMINANCE)
    assert reflect.canopy_reflect_gain(120000.0, -5.0) == 0.0            # night
    assert reflect.canopy_reflect_gain(120000.0, 3.0) == pytest.approx(g * 0.5)   # mid-fade
    assert reflect.canopy_reflect_gain(120000.0, 30.0, cover=1.0) == pytest.approx(g * 0.25)
    assert reflect.canopy_reflect_gain(240000.0, 30.0) == pytest.approx(2.0 * g)
    # the anti-sun horizon of the strip lands at 0.10 x E / pi (conservative: half a clear sky's)
    horizon = reflect.STRIP_HORIZON_LUMINANCE * g
    assert horizon == pytest.approx(0.10 * 120000.0 / math.pi)


def test_the_host_constants_are_the_twin():
    def constant(name):
        return float(re.search(rf"constexpr double {name} = ([-0-9.e]+);", FX_CPP).group(1))
    assert constant("AircraftFxReflectSkyShare") == reflect.SKY_HORIZON_SHARE
    assert constant("AircraftFxReflectNightFadeLoDeg") == reflect.NIGHT_FADE_DEG[0]
    assert constant("AircraftFxReflectNightFadeHiDeg") == reflect.NIGHT_FADE_DEG[1]
    assert constant("AircraftFxReflectOvercastDim") == reflect.OVERCAST_DIM
    assert constant("AircraftFxReflectStripHorizonLuminance") == pytest.approx(reflect.STRIP_HORIZON_LUMINANCE,
                                                                              abs=1e-6)
    assert constant("AircraftFxReflectTintMin") == reflect.TINT_BOUNDS[0]
    assert constant("AircraftFxReflectTintMax") == reflect.TINT_BOUNDS[1]
    strip = re.search(r"AircraftFxReflectStripHorizon\[3\] = \{([^}]*)\}", FX_CPP).group(1)
    assert tuple(float(v) for v in strip.split(",")) == reflect.STRIP_HORIZON_LINEAR
    gain = FX_CPP[FX_CPP.index("double FFlightSimAircraftFX::CanopyReflectGain"):]
    gain = gain[:gain.index("\n}\n")]
    assert "FMath::SmoothStep(AircraftFxReflectNightFadeLoDeg, AircraftFxReflectNightFadeHiDeg" in gain
    assert "/ UE_DOUBLE_PI" in gain and "if (bInterior)" in gain
    assert 'TEXT("ocast")' in APPLY and "ReflectCover = 1.0;" in APPLY


def test_the_tint_follows_the_horizon_hue_only():
    assert reflect.horizon_tint(None)[0] == (1.0, 1.0, 1.0)
    assert reflect.horizon_tint((0, 0, 0))[0] == (1.0, 1.0, 1.0)
    # the strip's own horizon colour, as sRGB8, comes back (about) white
    own = tuple(round(255 * (1.055 * c ** (1 / 2.4) - 0.055)) for c in reflect.STRIP_HORIZON_LINEAR)
    assert reflect.horizon_tint(own)[0] == pytest.approx((1.0, 1.0, 1.0), abs=0.02)
    # hue only: a darker horizon of the same (linear) hue is the same tint
    def srgb8(lin):
        return tuple(round(255 * (1.055 * c ** (1 / 2.4) - 0.055)) for c in lin)
    assert reflect.horizon_tint(srgb8((0.30, 0.40, 0.60)))[0] == pytest.approx(
        reflect.horizon_tint(srgb8((0.15, 0.20, 0.30)))[0], rel=0.03)
    blue = reflect.horizon_tint((120, 160, 230))[0]
    assert blue[2] > 1.0 > blue[0]
    assert all(reflect.TINT_BOUNDS[0] <= c <= reflect.TINT_BOUNDS[1] for c in reflect.horizon_tint((255, 0, 0))[0])
    assert reflect.parse_srgb8("120:160:230") == (120, 160, 230)
    assert reflect.parse_srgb8("300:0:0") is None and reflect.parse_srgb8("1,2,3") is None
    assert 'FParse::Value(*Params, TEXT("xplane-horizon="), HorizonWord)' in PARSE


# -- the shader bodies and their twins ----------------------------------------------

def test_the_shaders_are_registered_and_sample_no_texture_themselves():
    for name, inputs in reflect.GLASS_REFLECT_SHADER_INPUTS.items():
        assert look.SHADER_INPUTS[name] == inputs
        text = (SHADERS / f"{name}.hlsl").read_text(encoding="utf-8")
        assert "Texture2DSample" not in text and "discard" not in text
    assert "max(Gain, 0.0)" in (SHADERS / "glass_reflect.hlsl").read_text(encoding="utf-8")


def test_the_lookup_twin():
    up = (0.0, 0.0, 1.0)
    lut_u, lut_v, env_u, env_v = reflect.reflect_uv(up, up, (1.0, 0.0, 0.0))
    assert lut_u == pytest.approx(0.9921875) and lut_v == 0.5          # face-on, clamped inside the LUT
    assert env_v == pytest.approx(0.0078125)                          # mirrors the zenith
    # a grazing view along -x off a horizontal pane mirrors toward +x, where the sun is: u = 0.5
    view = (-math.cos(math.radians(5)), 0.0, math.sin(math.radians(5)))
    lut_u, _, env_u, env_v = reflect.reflect_uv(up, view, (1.0, 0.0, 0.0))
    assert env_u == pytest.approx(0.5, abs=1e-6) and lut_u < 0.1 and env_v < 0.5
    # the anti-sun direction lands on the strip's seam (u = 0 or 1)
    _, _, env_u, _ = reflect.reflect_uv(up, view, (-1.0, 0.0, 0.0))
    assert min(env_u, 1.0 - env_u) == pytest.approx(0.0, abs=1e-6)
    # the micro normal at strength 0 changes nothing
    assert reflect.reflect_uv(up, view, (1, 0, 0), micro=(0.9, 0.1, 1.0), strength=0.0) == \
        reflect.reflect_uv(up, view, (1, 0, 0))
    assert reflect.micro_uv((70.0, 35.0, 10.0), up, 35.0) == (2.0, 1.0)
    assert reflect.micro_uv((70.0, 35.0, 10.0), (1.0, 0.0, 0.0), 35.0) == (1.0, 10.0 / 35.0)


def test_tier1_reaches_the_bake_numbers_and_tiers_2_3_are_not_built():
    bake = reflect.load_bake()
    assert set(reflect.TIERS) == {0, 1}
    for tier in reflect.TIERS:
        row = bake["tiers"][str(tier)]
        assert row["blend"] == "opaque"
        names = reflect.TIER_TEXTURES[tier]
        assert names["GlassEnv"] == f"T_GlassEnv_{row['env_w']}"
        if row["micro"]:
            assert names["GlassMicroN"] == f"T_GlassMicro_N_{row['micro']}"
            assert names["GlassFilmM"] == f"T_GlassFilm_M_{row['micro']}"
        for name in names.values():
            assert (Path(reflect.LANE_OUT) / f"{name}.png").is_file()
    assert reflect.MASTER_SCALARS["GlassEnvEncodeScale"] == bake["shared_params"]["env_encode_scale"]
    assert "MSM_THIN_TRANSLUCENT" not in REFLECT_PY and "screen_space_reflections" not in REFLECT_PY


# -- the lane's bake is reproducible -------------------------------------------------

def test_the_bake_reproduces_provenance(tmp_path):
    spec = importlib.util.spec_from_file_location("glass_bake_repro", Path(reflect.LANE_DIR) / "bake_glass.py")
    bake = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bake)
    doc = bake.bake(tmp_path)
    provenance = json.loads(Path(reflect.PROVENANCE_JSON).read_text(encoding="utf-8"))["outputs"]
    assert set(provenance) == set(doc["files"])
    for name, row in provenance.items():
        data = (tmp_path / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == row["sha256"], name
        assert len(data) == row["bytes"], name
        assert (Path(reflect.LANE_OUT) / name).read_bytes() == data, name   # the committed file is the bake
    assert (tmp_path / "glass_coastal.json").read_text() == \
        (Path(reflect.LANE_OUT) / "glass_coastal.json").read_text()
