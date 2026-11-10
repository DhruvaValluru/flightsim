"""Visual round 5, lane L1: the engine look (core/scene/beauty_look.py
ENGINE_LOOK and its host, FlightSimBeautyLook.cpp ApplyEngineLook).

Pure Python checks on the tables and the plan, and source-reading checks
on the C++ twin (nothing compiles on this machine). Each value the Python
writes must be applied by the host with its bOverride_, each effect must
have its ``-look-<name>=`` switch, every value must land in the record,
and the probes must be off on the constrained GPU unless asked.
"""

import re
from pathlib import Path

import pytest

from core.scene import beauty_look as bl
from core.scene.beauty_look import BeautyLookError

REPO = Path(__file__).resolve().parents[1]
PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
LOOK_CPP = (PRIVATE / "FlightSimBeautyLook.cpp").read_text(encoding="utf-8")
LOOK_H = (PRIVATE / "FlightSimBeautyLook.h").read_text(encoding="utf-8")
RENDER_CPP = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
CHECK = (REPO / "scripts/check_bridge_api.sh").read_text(encoding="utf-8")
INI = (REPO / "ue/Config/DefaultEngine.ini").read_text(encoding="utf-8")

LATE = LOOK_CPP[LOOK_CPP.index("bool BeautyLookApplyEngineLook("):LOOK_CPP.index("#undef FLIGHTSIM_BEAUTY_FLOAT")]


def plan(preset="clear", **kw):
    return bl.plan_beauty_look(20.0, fps=30.0, width_px=1920, world_preset=preset, **kw)


# -- the tables --------------------------------------------------------------------


def test_every_effect_has_a_switch_a_probe_flag_and_a_row_per_preset():
    assert set(bl.ENGINE_LOOK_PRESETS) == {"clear", "hazy", "overcast", "rain", "storm"}
    for key, row in bl.ENGINE_LOOK.items():
        assert re.fullmatch(r"[a-z-]+", row["switch"]), key
        assert isinstance(row["probe"], bool), key
        assert row["off_means"], key
        assert row["stage"] in ("capture", "scene"), key
        assert set(row["per_preset"]) == set(bl.ENGINE_LOOK_PRESETS), key
        assert "cvars" in row and "cvars_constrained" in row, key
    assert len(bl.ENGINE_LOOK_SWITCHES) == len(bl.ENGINE_LOOK)   # switch words are unique


def test_the_probes_are_the_costly_ones_and_auto_is_off_on_the_constrained_gpu():
    probes = {k for k, row in bl.ENGINE_LOOK.items() if row["probe"]}
    assert probes == {"df_shadows", "bloom_fft", "fog_grid"}
    look = bl.engine_look_for("clear")
    for key in probes:
        assert look[key]["switch_words"] == ["auto", "on", "off"], key
    # The fine fog grid is what every passing round rendered with: its auto
    # stays on; the two new passes are off on the constrained GPU.
    assert look["fog_grid"]["auto_on_constrained"] is True
    assert look["df_shadows"]["auto_on_constrained"] is False
    assert look["bloom_fft"]["auto_on_constrained"] is False
    assert look["fog_grid"]["cvars_off"] == {"r.VolumetricFog.GridPixelSize": 8.0, "r.VolumetricFog.GridSizeZ": 64.0}


def test_nothing_in_the_engine_look_touches_the_cloud_march():
    text = str(bl.ENGINE_LOOK)
    for word in ("VolumetricCloud", "TracingMaxDistance", "SampleCountScale", "ShadowSampleCount",
                 "ViewSampleCount", "CloudConstrained"):
        assert word not in text, word


def test_the_sun_shadows_cover_less_than_the_scene_build_and_pcss_only_under_a_clear_sun():
    rows = bl.ENGINE_LOOK["sun_shadows"]["per_preset"]
    for preset, row in rows.items():
        assert row["DynamicShadowDistanceMovableLight_m"] < 20000.0, preset   # the scene's 20 km
        assert 4 <= row["DynamicShadowCascades"] <= 10, preset
    assert rows["clear"]["r.Shadow.FilterMethod"] == 1 and rows["hazy"]["r.Shadow.FilterMethod"] == 1
    for deck in ("overcast", "rain", "storm"):
        assert rows[deck]["r.Shadow.FilterMethod"] == 0, deck
    assert bl.ENGINE_LOOK["sun_shadows"]["cvars"]["r.Shadow.MaxCSMResolution"] == 4096.0
    assert bl.ENGINE_LOOK["sun_shadows"]["cvars"]["r.Shadow.MaxResolution"] == 4096.0


def test_distance_field_shadows_need_the_projects_mesh_distance_fields():
    assert "r.GenerateMeshDistanceFields=True" in INI
    for row in bl.ENGINE_LOOK["df_shadows"]["per_preset"].values():
        assert row["bUseRayTracedDistanceFieldShadows"] is True
        assert row["DistanceFieldShadowDistance_m"] > 6000.0   # beyond every cascade distance


def test_local_exposure_never_re_tones_the_sky_band():
    # Round 2's Gate 6 clause: the highlight scale stays 1 on every preset.
    for preset, row in bl.ENGINE_LOOK["local_exposure"]["per_preset"].items():
        assert row["LocalExposureHighlightContrastScale"] == 1.0, preset
        assert row["LocalExposureShadowContrastScale"] < 1.0, preset
    assert plan("storm")["local_exposure"]["LocalExposureShadowContrastScale"] == 0.85
    assert plan("clear")["local_exposure"]["LocalExposureShadowContrastScale"] == 0.75


def test_bloom_is_low_and_the_flare_threshold_high():
    for preset, row in bl.ENGINE_LOOK["bloom"]["per_preset"].items():
        assert 0.2 <= row["BloomIntensity"] <= 0.4, preset
        assert row["BloomMethod"] == "BM_SOG"
    for preset, row in bl.ENGINE_LOOK["lens_flare"]["per_preset"].items():
        assert 0.1 <= row["LensFlareIntensity"] <= 0.3, preset
        assert row["LensFlareThreshold"] >= 8.0, preset
        assert row["sun_in_frame_margin_deg"] > 0.0


def test_one_grain_constant_scaled_by_the_preset_and_the_stock():
    row = bl.film_grain_for("storm")
    assert row["FilmGrainIntensity"] == pytest.approx(bl.GRAIN_STRENGTH * 1.4)
    assert row["GrainStrength"] == bl.GRAIN_STRENGTH and row["stock_scale"] == 1.0
    stock = bl.film_grain_for("clear", stock_scale=1.5)
    assert stock["FilmGrainIntensity"] == pytest.approx(bl.GRAIN_STRENGTH * 1.5)
    assert plan("clear", stock_grain_scale=1.5)["engine_look"]["film_grain"]["values"]["FilmGrainIntensity"] == \
        pytest.approx(bl.GRAIN_STRENGTH * 1.5)
    assert plan()["pixel_effects"]["film_grain"]["FilmGrainIntensity"] == pytest.approx(bl.GRAIN_STRENGTH)
    for bad in (-1.0, float("nan")):
        with pytest.raises(BeautyLookError) as err:
            bl.film_grain_for("clear", bad)
        assert err.value.constraint == bl.CONSTRAINT
    # The grain is finest in the highlights, a negative's split.
    for row in bl.ENGINE_LOOK["film_grain"]["per_preset"].values():
        assert row["FilmGrainIntensityHighlights"] < row["FilmGrainIntensityMidtones"]


def test_the_volumetric_fog_row_sets_only_the_albedo():
    for row in bl.ENGINE_LOOK["volumetric_fog"]["per_preset"].values():
        assert set(row) == {"VolumetricFogAlbedo_srgb8"}
        assert all(200 <= c <= 255 for c in row["VolumetricFogAlbedo_srgb8"])
    # The distribution and extinction stay the world lane's (one haze).
    assert "VolumetricFogScatteringDistribution" not in str(bl.ENGINE_LOOK["volumetric_fog"])
    assert "VolumetricFogExtinctionScale" not in str(bl.ENGINE_LOOK["volumetric_fog"])


def test_the_still_accumulation_is_raised_and_lower_on_the_constrained_gpu():
    look = bl.engine_look_for("clear")
    assert look["tsr"]["values"] == {"warmup_captures": 24, "still_samples": 16}
    assert look["tsr"]["values_constrained"] == {"warmup_captures": 20, "still_samples": 12}
    assert look["ssr"]["values_constrained"]["ScreenSpaceReflectionQuality"] == 80.0
    assert look["ssgi"]["cvars_constrained"]["r.SSGI.Quality"] == 3.0


def test_the_filmback_is_full_frame():
    row = bl.ENGINE_LOOK["filmback"]["per_preset"]["clear"]
    assert (row["sensor_width_mm"], row["sensor_height_mm"]) == (36.0, 24.0)
    assert row["sensor_width_mm"] == bl.DEFAULT_SENSOR_WIDTH_MM


# -- the plan ----------------------------------------------------------------------


@pytest.mark.parametrize("preset", bl.ENGINE_LOOK_PRESETS)
def test_the_plan_carries_the_presets_engine_look(preset):
    p = plan(preset)
    look = p["engine_look"]
    assert look["preset"] == preset
    assert "world preset" in look["preset_basis"]
    for key in bl.ENGINE_LOOK:
        assert look[key]["switch"] == f"-look-{bl.ENGINE_LOOK[key]['switch']}"
        assert look[key]["values"] == (bl.film_grain_for(preset) if key == "film_grain"
                                       else bl.ENGINE_LOOK[key]["per_preset"][preset])
    assert p["beauty_look_version"] == 3


def test_no_card_falls_back_through_the_grade():
    p = bl.plan_beauty_look(5.0, fps=30.0, width_px=1920)
    assert p["grade"] == "golden_hour" and p["engine_look"]["preset"] == "clear"
    storm = bl.plan_beauty_look(5.0, fps=30.0, width_px=1920, weather_event="thunderstorm")
    assert storm["engine_look"]["preset"] == "storm"
    assert bl.look_preset_for("overcast", "golden_hour")[0] == "overcast"
    assert bl.look_preset_for(None, "overcast")[0] == "overcast"


def test_the_lens_no_longer_carries_bloom_flare_or_grain():
    for lens in bl.LENSES.values():
        for key in ("BloomIntensity", "LensFlareIntensity", "FilmGrainIntensity", "BloomThreshold"):
            assert key not in lens, key
    assert "ScreenSpaceReflectionIntensity" not in bl.REFLECTIONS
    effects = plan("rain")["pixel_effects"]
    assert effects["bloom"]["on"] and effects["bloom"]["effect"] == "softens"
    assert effects["lens_flare"]["on"] and effects["lens_flare"]["effect"] == "none"
    assert effects["film_grain"]["on"] and effects["pixel_moving"] == []


def test_the_look_switches_parse_and_refuse_by_name():
    assert bl.parse_look_switches("-look-bloom=off -look-fog-grid=auto -look-df-shadows=on") == {
        "bloom": "off", "fog-grid": "auto", "df-shadows": "on"}
    assert bl.parse_look_switches("-sky-fill-probe=red -gpu-drain=on") == {}
    assert bl.parse_look_switches(None) == {}
    for text in ("-look-bloom=auto", "-look-ssgi=maybe", "-look-nothing=on"):
        with pytest.raises(BeautyLookError) as err:
            bl.parse_look_switches(text)
        assert err.value.constraint == "render.look_switch"
        assert str(err.value).startswith("render.look_switch: ")


def test_the_switch_refusal_is_catalogued_and_the_env_var_registered():
    from core.messages import is_catalogued
    from core.config_surface import SETTINGS

    assert is_catalogued("render.look_switch")
    assert 'TEXT("render.look_switch: -look-%s=%s is not one of %s")' in LOOK_CPP
    row = next(s for s in SETTINGS if s.env == "FLIGHTSIM_RENDER_SWITCHES")
    assert any("FlightSimBeautyLook.cpp" in ref for ref in row.where_read)
    assert "ENGINE_LOOK_SWITCHES" in row.note


# -- the host (source-reading) -------------------------------------------------


def _applied(effect: str) -> str:
    """The host's block for one effect of the late half."""
    start = LATE.index(f'BeautyLookEffect(TEXT("{effect}")')
    after = LATE[start + 1:]
    nxt = re.search(r'BeautyLookEffect\(TEXT\("(?!bloom_fft)\w+"\)', after)
    return LATE[start:start + 1 + (nxt.start() if nxt else len(after))]


POST_PROCESS_EFFECTS = ("ssgi", "ssr", "ssao", "bloom", "bloom_fft", "lens_flare", "film_grain", "filmback")


@pytest.mark.parametrize("effect", POST_PROCESS_EFFECTS)
def test_every_post_process_value_the_python_writes_the_host_applies_with_its_override(effect):
    values = bl.engine_look_for("clear")[effect]["values"]
    macros = set(re.findall(r"FLIGHTSIM_BEAUTY_FLOAT\((?:Effect|Fft)\.Values, (\w+)\)", LOOK_CPP))
    explicit = {"AmbientOcclusionRadiusInWS", "BloomMethod"}
    informational = {"grain_scale", "GrainStrength", "stock_scale", "sun_in_frame_margin_deg",
                     "sensor_width_mm", "sensor_height_mm"}
    for key in values:
        if key in informational:
            assert f'TEXT("{key}")' in LOOK_CPP, key
            continue
        if key in explicit:
            assert f"Settings.bOverride_{key} = true;" in LOOK_CPP, key
            continue
        assert key in macros, key
    assert f'BeautyLookEffect(TEXT("{effect}")' in LATE


def test_the_light_and_fog_values_reach_the_sun_and_the_fog_with_metres_converted():
    sun = _applied("sun_shadows")
    for setter in ("SetDynamicShadowCascades(FMath::RoundToInt32(Cascades))",
                   "SetCascadeDistributionExponent(static_cast<float>(Exponent))",
                   "SetDynamicShadowDistanceMovableLight(static_cast<float>(DistanceM * BeautyLookCmPerMetre))",
                   "SetShadowDistanceFadeoutFraction(static_cast<float>(Fade))",
                   "SetCascadeTransitionFraction(static_cast<float>(Transition))"):
        assert setter in sun, setter
    assert 'Entry.Key.StartsWith(TEXT("r."))' in sun   # the per-preset filter method rides the values
    df = _applied("df_shadows")
    assert "Sun->SetUseRayTracedDistanceFieldShadows(bUse);" in df
    assert "Sun->DistanceFieldShadowDistance = static_cast<float>(DistanceM * BeautyLookCmPerMetre);" in df
    assert "Capture->ShowFlags.SetRayTracedDistanceFieldShadows(true);" in df
    contact = _applied("contact_shadows")
    for member in ("ContactShadowLength", "ContactShadowLengthInWS", "ContactShadowCastingIntensity",
                   "ContactShadowNonCastingIntensity"):
        assert f"Sun->{member} = " in contact, member
    fog = _applied("volumetric_fog")
    assert "Fog->SetVolumetricFogAlbedo(Albedo);" in fog
    assert "SetVolumetricFogScatteringDistribution" not in fog and "SetVolumetricFogExtinctionScale" not in fog
    assert "TObjectIterator<UExponentialHeightFogComponent>" in fog


def test_off_is_the_effect_off_or_the_earlier_lanes_value_as_the_python_says():
    assert "Settings.DynamicGlobalIlluminationMethod = EDynamicGlobalIlluminationMethod::None;" in _applied("ssgi")
    assert "Settings.ReflectionMethod = EReflectionMethod::None;" in _applied("ssr")
    assert "Settings.AmbientOcclusionIntensity = 0.0f;" in _applied("ssao")
    assert "Settings.BloomIntensity = 0.0f;" in _applied("bloom")
    assert "Settings.LensFlareIntensity = 0.0f;" in _applied("lens_flare")
    assert "Settings.FilmGrainIntensity = 0.0f;" in _applied("film_grain")
    # sun shadows and contact shadows off: nothing set (the earlier lanes stand)
    sun = _applied("sun_shadows")
    assert sun.index("if (Effect.bOn)") < sun.index("Sun->SetDynamicShadowCascades(")
    assert "else" not in sun[sun.index("Sun->SetCascadeTransitionFraction"):sun.index("Echo->SetNumberField(TEXT(\"DynamicShadowCascades\")")]
    fog_grid = _applied("fog_grid")
    assert "Effect.bOn ? Effect.Cvars : Effect.CvarsOff" in fog_grid


def test_a_probe_is_off_on_the_constrained_gpu_unless_asked():
    body = LOOK_CPP[LOOK_CPP.index("bool BeautyLookEffect(const TCHAR* Key"):LOOK_CPP.index("void BeautyLookCvars(")]
    assert ('Out.bOn = Out.Mode == TEXT("on") ||\n'
            '\t\t\t(Out.Mode == TEXT("auto") && (!bConstrained || bAutoOnConstrained));') in body
    assert 'TryGetObjectField(TEXT("values_constrained")' in body
    assert 'bConstrained ? TEXT("cvars_constrained") : TEXT("cvars")' in body
    # the commandlet hands the constrained answer and the switch text over
    assert ("FFlightSimBeautyLook::ApplyEngineLook(VisualScene, Capture, bConstrainedGpu, *RenderSwitches)"
            in RENDER_CPP)


def test_the_switches_come_from_the_command_line_and_the_environment():
    assert 'FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"))' in LOOK_CPP
    assert 'const TCHAR* const BeautyLookSwitchPrefix = TEXT("look-");' in LOOK_CPP
    body = LOOK_CPP[LOOK_CPP.index("bool BeautyLookSwitch(const FString& Name"):LOOK_CPP.index("struct FBeautyLookEffect")]
    assert 'Mode = bProbe ? TEXT("auto") : TEXT("on");' in body
    assert '(bProbe && Mode == TEXT("auto"))' in body


def test_the_host_runs_after_the_other_lanes_and_before_registration():
    call = RENDER_CPP.index("FFlightSimBeautyLook::ApplyEngineLook(VisualScene, Capture")
    assert RENDER_CPP.index("FFlightSimHeroLighting::Apply(VisualScene, Capture") < call
    assert RENDER_CPP.index("FFlightSimBeautyFallback::ApplyCapture(Capture);") < call
    assert RENDER_CPP.index("SetBeautyCvar(TEXT(\"r.TSR.History.ScreenPercentage\")") < call
    assert call < RENDER_CPP.index("\n\tCapture->RegisterComponent();")
    # the call's own if (it spans two lines) is gated on beauty raster
    assert "if (bVisual && bBeauty && !bPathTrace &&\n\t    !FFlightSimBeautyLook::ApplyEngineLook(" in RENDER_CPP
    assert "return Fail(FFlightSimBeautyLook::LastError());" in RENDER_CPP[call:call + 200]
    assert "5b. Engine look" in RENDER_CPP[RENDER_CPP.index("ONE owner per setting"):call]


def test_the_lens_flare_gate_is_decided_once_from_the_sun_and_the_frame():
    body = LOOK_CPP[LOOK_CPP.index("void FFlightSimBeautyLook::UpdatePerFrame"):LOOK_CPP.index("void FFlightSimBeautyLook::ApplyShutterPolicy")]
    assert "if (State.bFlareGate && !State.bFlareDecided)" in body
    assert "const FVector ToSun = -Sun->GetDirection();" in body
    assert "FMath::Tan(HalfHorizontal) * FMath::Sqrt(1.0 + 1.0 / (Aspect * Aspect))" in body
    assert "const bool bDraw = AngleDeg <= HalfDiagonalDeg + State.FlareMarginDeg;" in body
    assert "Capture->ShowFlags.SetLensFlares(false);" in body
    assert '(*Flare)->SetObjectField(TEXT("gate"), Gate);' in body


def test_the_still_accumulation_raises_the_commandlets_defaults_and_never_a_stated_flag():
    assert 'const bool bWarmupStated = FParse::Value(*Params, TEXT("warmup="), WarmupCaptures);' in RENDER_CPP
    assert "if (!bWarmupStated && FFlightSimBeautyLook::StillAccumulation(LookWarmup, LookStillSamples))" in RENDER_CPP
    assert "WarmupCaptures = FMath::Max(WarmupCaptures, LookWarmup);" in RENDER_CPP
    still = RENDER_CPP[RENDER_CPP.index("const bool bLookSamples = FFlightSimBeautyLook::StillAccumulation("):]
    still = still[:still.index("// aircraft-sharp")]
    assert "LookStillSamples > RenderBeautyStillSamplesDefault" in still
    assert "FMath::Min(LookStillSamples, RenderBeautyStillSamplesMax) : RenderBeautyStillSamplesDefault" in still
    # a stated -still-samples= is read in an earlier branch, so it wins
    assert RENDER_CPP.index('BeautySubFramesBasis = TEXT("-still-samples, stated");') < RENDER_CPP.index(
        "const bool bLookSamples = ")
    assert "static bool StillAccumulation(int32& WarmupCaptures, int32& StillSamples);" in LOOK_H


def test_every_value_and_read_back_lands_in_the_record():
    assert 'State.Applied->SetObjectField(TEXT("engine_look"), State.EngineApplied);' in LOOK_CPP
    assert "State.EngineApplied->SetObjectField(Key, Out.Record);" in LOOK_CPP
    for key in ("before", "asked", "read_back"):
        assert f'Out->SetObjectField(TEXT("{key}"), {key.title().replace("_", "")});' in LOOK_CPP, key
    for read_back in ("LightSourceAngle_deg_read_back", "r.Shadow.FilterMethod_read_back",
                      "sun_volumetric_scattering_intensity_read_back", "scattering_distribution_read_back",
                      "r.TSR.History.ScreenPercentage_read_back", "DepthOfFieldSensorWidth_read_back"):
        assert f'TEXT("{read_back}")' in LATE, read_back


def test_the_sidecar_version_moved_with_the_block():
    assert bl.BEAUTY_LOOK_VERSION == 3
    assert "constexpr int32 BeautyLookSupportedVersion = 3;" in LOOK_CPP
    assert 'BeautyLookObject(Plan, TEXT("engine_look"), State.EngineLook)' in LOOK_CPP


def test_check_bridge_api_names_every_engine_symbol_and_cvar_the_host_uses():
    block = CHECK[CHECK.index("BEGIN engine look"):CHECK.index("END engine look")]
    for cvar in sorted({c for row in bl.ENGINE_LOOK.values()
                        for c in list(row["cvars"]) + list(row["cvars_constrained"]) + list(row.get("cvars_off", {}))}):
        assert f"el_cvar {cvar} " in block, cvar
    assert "el_cvar r.Shadow.FilterMethod " in block
    # the members: new ones in this block, the rest already in the look-dev block
    for member in re.findall(r"FLIGHTSIM_BEAUTY_FLOAT\((?:Effect|Fft)\.Values, (\w+)\)", LOOK_CPP):
        assert re.search(rf"\b{member}\b", CHECK), member
    for symbol in ("SetVolumetricFogAlbedo", "SetUseRayTracedDistanceFieldShadows", "DistanceFieldShadowDistance",
                   "SetDynamicShadowDistanceMovableLight", "GetForwardVector", "GetDirection", "BM_FFT",
                   "DefaultFilmGrainTexture", "DefaultBloomKernelTexture", "PCSS"):
        assert symbol in block, symbol
    for flag in ("ScreenSpaceAO", "RayTracedDistanceFieldShadows", "ContactShadows", "LensFlares", "Grain", "Bloom"):
        assert f"show flag" in block and flag in block, flag
