"""S4 (the sensing engine side): the render commandlet, the visual scene's
sun and the verifier's grading of the render.json keys they write.

No engine runs in this container, so the C++ is pinned by READING it
(the tests/test_annotation_passes.py / tests/test_gate6_visual.py
precedent): every constant the Python side also states is read out of the
source and compared with the Python module that owns it, every expression
the chain depends on is evaluated in Python from its text, and every
render.json key the verifier grades is found where the commandlet writes
it. The verifier's five S4 checks are measured on synthetic run
directories written by this file: consistent records PASS, one corrupted
number FAILs by name, nothing to grade is NOT RUN.

Not measured here: that the engine compiles, what SCS_Normal holds, that
one emissive unit is 1 cd/m^2, that the white quad measures within 2 %,
the accumulation's blur on real pixels -- each is a step of the Windows
verification order (docs/PHASE2_REPORT.md, step 8).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np
import pytest

from core.capture import blur, optics, passes, radiometry, verify
from core.messages import is_catalogued
from core.render import flags
from core.scenario import solar

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
COMMANDLET = BRIDGE / "Private" / "FlightSimRenderCommandlet.cpp"
COMMANDLET_H = BRIDGE / "Public" / "FlightSimRenderCommandlet.h"
SCENE = BRIDGE / "Private" / "FlightSimVisualScene.cpp"
SCENE_H = BRIDGE / "Public" / "FlightSimVisualScene.h"
SCRIPT = REPO / "scripts" / "ue_create_materials.py"


def _source() -> str:
    return COMMANDLET.read_text(encoding="utf-8")


def _constant(text: str, name: str) -> float:
    match = re.search(rf"constexpr (?:double|int32) {name} = ([0-9.eE+-]+);", text)
    assert match, f"{name} is not a constexpr number in the commandlet"
    return float(match.group(1))


def _string_constant(text: str, name: str) -> str:
    match = re.search(rf'{name} =\s*TEXT\("([^"]*)"\);', text)
    assert match, f"{name} is not a TEXT constant"
    return match.group(1)


def _body(text: str, signature: str) -> str:
    match = re.search(re.escape(signature) + r"\((.*?)\n\}\n", text, re.S)
    assert match, f"{signature} is not defined"
    return match.group(1)


# -- (1) the linear passes: SCS_Normal / SCS_BaseColor into RTF_RGBA16f ----------

def test_the_normal_and_base_colour_captures_are_the_gbuffer_sources_under_the_label_rule():
    source = _source()
    normal = re.search(r"auto MakeNormalCapture = \[&\]\((.*?)\n\t\t\};", source, re.S)
    base = re.search(r"auto MakeBaseColorCapture = \[&\]\((.*?)\n\t\t\};", source, re.S)
    assert normal and base
    assert "CaptureSource = ESceneCaptureSource::SCS_Normal;" in normal.group(1)
    assert "CaptureSource = ESceneCaptureSource::SCS_BaseColor;" in base.group(1)
    for block in (normal.group(1), base.group(1)):
        assert "ConfigureLabelCapture(" in block      # AA-free, no fog, no cloud, no translucency
        assert "RegisterComponent();" in block
    assert "LinearNormalTarget = MakeLinearPassTarget(RTF_RGBA16f);" in source
    assert "LinearBaseColorTarget = MakeLinearPassTarget(RTF_RGBA16f);" in source
    assert 'LinearNormal = MakeNormalCapture(TEXT("LinearNormal"), LinearNormalTarget);' in source
    assert 'LinearBaseColor = MakeBaseColorCapture(TEXT("LinearBaseColor"), LinearBaseColorTarget);' in source
    # The I6 16-bit PNG route is kept beside them.
    assert "PassNormalTarget = MakePassTarget(RTF_RGBA16f);" in source
    assert 'PassStem + TEXT("_normal.png")' in source and 'PassStem + TEXT("_albedo.png")' in source


def test_the_linear_files_are_named_where_the_python_readers_look():
    source = _source()
    assert 'LinearStem + TEXT("_normal.f32")' in source
    assert 'LinearStem + TEXT("_basecolor.f32")' in source
    assert 'LinearStem + TEXT("_velocity.f32")' in source
    # Frame-level keys: the ones core/capture/passes.py reads.
    assert f'Record->SetStringField(TEXT("{passes.NORMAL_F32_KEY}"), NormalName);' in source
    assert f'Record->SetStringField(TEXT("{passes.BASECOLOR_F32_KEY}"), BaseColorName);' in source
    # labels.* keys: the ones core/capture/verify.py grades.
    for key, value in (("normal", "NormalName"), ("normal_axes", "RenderNormalAxes"),
                       ("normal_encoding", "Encoding"), ("basecolor", "BaseColorName")):
        assert f'FrameLabels->SetStringField(TEXT("{key}"), {value});' in source, key
    assert 'FrameLabels->SetObjectField(TEXT("velocity"), VelocityRecord);' in source
    assert _string_constant(source, "RenderNormalAxes") == verify.S4_NORMAL_AXES
    for word in verify.S4_NORMAL_ENCODINGS:
        assert f'Encoding = TEXT("{word}");' in source, word


def test_the_byte_layout_is_stated_and_the_writer_writes_exactly_it():
    header = COMMANDLET_H.read_text(encoding="utf-8")
    for phrase in ("little-endian", "IEEE-754 float32", "NO header", "row-major from the top-left pixel",
                   "Channels values per pixel interleaved",
                   "numpy.fromfile(path, '<f4').reshape(Height, Width, Channels)"):
        assert phrase in header, phrase
    source = _source()
    body = _body(source, "bool UFlightSimRenderCommandlet::WriteLinearF32")
    assert "static_cast<int64>(Width) * Height * Channels" in body
    assert "Values.Num() != Expected" in body                 # refuses a wrong length, writes nothing
    assert "FMemory::Memcpy(Bytes.GetData(), Values.GetData(), Bytes.Num());" in body
    assert 'static_assert(PLATFORM_LITTLE_ENDIAN' in source
    assert 'static_assert(sizeof(float) == 4' in source
    assert _constant(source, "RenderLinearChannels") == 3
    assert "WriteLinearF32(FPaths::Combine(OutputDirectory, NormalName), Normal, Width, Height," in source
    assert "RenderLinearChannels * i + 0" in source            # interleaved per pixel


def test_s2s_readers_read_the_stated_layout(tmp_path):
    """The layout written the way WriteLinearF32 states it (little-endian
    float32, no header, row-major, 3 interleaved) is what core/capture/
    passes.py reads back, value for value; a file of the wrong length is
    refused by name."""
    height, width = 4, 5
    values = np.arange(height * width * 3, dtype="<f4") / 7.0
    path = tmp_path / "frame_0000_normal.f32"
    path.write_bytes(values.tobytes())                         # the memcpy of a float array
    back = passes.read_normal_f32(path, width, height)
    assert back.shape == (height, width, 3)
    assert back[1, 2, 0] == values[(1 * width + 2) * 3 + 0]    # row-major, channels interleaved
    assert np.array_equal(passes.read_basecolor_f32(path, width, height).ravel(), values)
    path.write_bytes(values[:-1].tobytes())
    with pytest.raises(passes.PassError):
        passes.read_normal_f32(path, width, height)


def test_the_normal_encoding_is_measured_and_refused_by_name():
    source = _source()
    assert _constant(source, "RenderNormalUnitTolerance") == verify.S4_NORMAL_UNIT_TOL
    assert _constant(source, "RenderNormalUnitFraction") == 0.5
    assert "(Texel - FVector(RenderPassSignedOffset)) / RenderPassSignedScale" in source
    assert 'TEXT("labels.normal_encoding: the %s normals of %s decode to unit length on ")' in source
    assert 'TEXT("labels.normal_encoding: -normal-source=\'%s\' is neither scs (the SCS_Normal ")' in source
    assert 'FParse::Value(*Params, TEXT("normal-source="), NormalSource);' in source
    assert "RenderWorldNormalFallbackMaterialPath" in source
    assert "GetENUVectorsAtEngineLocation(" in source           # engine axes -> north, east, up


# -- (2) the velocity cross-check through M_Velocity ----------------------------------

def test_the_velocity_check_persists_its_view_state_and_renders_first():
    source = _source()
    assert _string_constant(source, "RenderVelocityCheckMaterialPath") == "/Game/FlightSim/M_Velocity.M_Velocity"
    assert "VelocityCheckTarget = MakeLinearPassTarget(RTF_RGBA32f);" in source
    assert "VelocityCheck->bAlwaysPersistRenderingState = true;" in source
    assert 'FParse::Param(*Params, TEXT("velocity-check"))' in source
    # The first scene render after the step, before the beauty capture.
    check = source.index("VelocityCheck->CaptureScene();")
    beauty = source.index("Capture->CaptureScene();\n\t\tFlushRenderingCommands();\n\n\t\tFTextureRenderTargetResource* Resource")
    assert check < beauty
    assert "if (bVelocityCheck && bPassVelocity)" in source
    assert "const float DxPx = VelocityCheckRaw[i].R * 0.5f * Width;" in source
    assert "const float DyPx = -VelocityCheckRaw[i].G * 0.5f * Height;" in source
    assert 'VelocityRecord->SetStringField(TEXT("role"),' in source
    assert "never the truth" in source


# -- (3) the calibration frame ------------------------------------------------------

def test_the_chain_constants_are_radiometrys():
    source = _source()
    assert _constant(source, "RenderCalibrationConstant") == radiometry.CALIBRATION_CONSTANT
    assert _constant(source, "RenderLensAttenuationDefault") == radiometry.LENS_ATTENUATION_DEFAULT
    assert _constant(source, "RenderGreyCardReflectance") == radiometry.GREY_CARD_REFLECTANCE
    assert _constant(source, "RenderCalibrationTolerance") == verify.GREY_CARD_TOL
    assert _constant(source, "RenderSunLuxMax") == solar.SUN_LUX_MAX == verify.S4_SUN_LUX_MAX
    assert _constant(source, "RenderEngineSunUnitless") == radiometry.ENGINE_SUN_TODAY
    assert _constant(source, "RenderSlantedEdgeAngleDeg") == 5.0
    assert _constant(source, "RenderEsfrOversample") == optics.ESFR_OVERSAMPLE
    assert 0.0 < _constant(source, "RenderWhiteQuadReflectance") <= 1.0


def test_luminance_per_unit_and_the_lambertian_are_radiometrys_expressions():
    source = _source()
    per_unit = _body(source, "double UFlightSimRenderCommandlet::LuminancePerUnit")
    assert ("return RenderCalibrationConstant * LensAttenuation * FMath::Pow(2.0, Ev100 - "
            "ExposureCompensationEv);") in per_unit
    lambert = _body(source, "double UFlightSimRenderCommandlet::LambertianLuminance")
    assert "return Reflectance * IlluminanceLux / UE_DOUBLE_PI;" in lambert
    # The same numbers as the Python chain, evaluated from the text.
    for ev, ec, a in ((14.97, 0.0, 0.78), (9.0, 1.0, 0.65)):
        cpp = radiometry.CALIBRATION_CONSTANT * a * 2.0 ** (ev - ec)
        assert cpp == pytest.approx(radiometry.luminance_per_unit(ev, ec, a), rel=1e-12)
    assert 0.18 * 95788.0 / math.pi == pytest.approx(radiometry.grey_card_luminance(95788.0), rel=1e-12)


def test_the_calibration_frame_is_the_sun_alone_on_three_quads():
    source = _source()
    block = source[source.index("// -- S4: the calibration frame (-calibration)"):
                   source.index("TSharedPtr<FJsonObject> Root = MakeShared<FJsonObject>();")]
    for flag in ("AntiAliasing", "TemporalAA", "Fog", "Atmosphere", "Cloud", "Bloom", "MotionBlur",
                 "Vignette", "SkyLighting", "GlobalIllumination", "LumenGlobalIllumination",
                 "AmbientOcclusion", "DynamicShadows"):
        assert f"CalibrationCapture->ShowFlags.Set{flag}(false);" in block, flag
    assert "CalibrationSun->SetAtmosphereSunLight(false);" in block
    assert "CalibrationSun->SetCastShadows(false);" in block
    assert "CalibrationSun->bCastCloudShadows = false;" in block
    assert "PRM_UseShowOnlyList" in block and "ShowOnlyActors.Add(Rig);" in block
    assert "CaptureSource = ESceneCaptureSource::SCS_FinalColorHDR;" in block
    assert "CalibrationTarget->RenderTargetFormat = RTF_RGBA32f;" in block
    # The three quads: the emissive grey at the stated nits, the slanted
    # edge at 5 deg, the white Lambertian lit only.
    assert "const double GreyCardNits = LambertianLuminance(AppliedSunLux, RenderGreyCardReflectance);" in block
    assert '{TEXT("CalibrationEmissive"), -RenderCalibrationQuadOffset, 0.0, GreyCardNits, 0.0, nullptr}' in block
    assert ('{TEXT("CalibrationSlantedEdge"), 0.0, RenderSlantedEdgeAngleDeg, GreyCardNits, 0.0, nullptr}'
            in block)
    assert ('{TEXT("CalibrationWhite"), RenderCalibrationQuadOffset, 0.0, 0.0, RenderWhiteQuadReflectance, '
            'nullptr}') in block
    # Predicted from the chain with A read back; the root is the 18 % card's.
    assert "LuminancePerUnit(AppliedEv100, ExposureCompensation, LensAttenuation)" in block
    assert 'FindConsoleVariable(TEXT("r.EyeAdaptation.LensAttenuation"))' in block
    assert "WhiteMeasured * (RenderGreyCardReflectance / RenderWhiteQuadReflectance)" in block
    assert "EsfrMtf50(CalibrationLuminance, Width, Height, EdgeU0, EdgeV0, EdgeU1, EdgeV1)" in block


def test_the_calibration_record_carries_every_key_the_python_side_reads():
    source = _source()
    block = source[source.index("Calibration = MakeShared<FJsonObject>();"):
                   source.index("TSharedPtr<FJsonObject> Root = MakeShared<FJsonObject>();")]
    for key in ("grey_card_nits", "predicted", "measured", "ratio", "ev100", "exposure_compensation_ev",
                "lens_attenuation", "luminance_cd_m2_per_unit", "sun_lux"):
        assert f'Calibration->SetNumberField(TEXT("{key}"),' in block, key
    assert 'Calibration->SetNumberField(TEXT("mtf50_measured"), Mtf50);' in block
    assert 'Calibration->SetObjectField(TEXT("slanted_edge"), Edge);' in block
    assert 'Edge->SetStringField(TEXT("frame"), CalibrationFrameName);' in block
    assert 'Edge->SetArrayField(TEXT("quad_px"), QuadArray(EdgeU0, EdgeV0, EdgeU1, EdgeV1));' in block
    assert 'Calibration->SetObjectField(TEXT("emissive"), EmissiveRecord);' in block
    assert 'Calibration->SetObjectField(TEXT("lambertian"), WhiteRecord);' in block
    # calibration.json beside render.json (what radiometry and verify read),
    # and the same object at render.json's root.
    assert 'FPaths::Combine(OutputDirectory, TEXT("calibration.json"))' in block
    assert 'Root->SetObjectField(TEXT("calibration"), Calibration);' in source


def test_the_esfr_is_iso_12233_shaped():
    body = _body(_source(), "double UFlightSimRenderCommandlet::EsfrMtf50")
    assert "Sorted[CropWidth / 10]" in body and "Sorted[(CropWidth * 9) / 10]" in body
    assert "const double Slope = (Rows * Sxy - Sy * Sx) / Denominator;" in body
    assert "* RenderEsfrOversample" in body
    assert "0.54 + 0.46 * FMath::Cos(" in body                # Hamming
    assert "if (Mtf < 0.5)" in body


# -- (4) the accumulation ---------------------------------------------------------------

def test_the_accumulation_follows_the_quarter_pixel_rule_and_blurs_once():
    source = _source()
    assert _constant(source, "RenderSubPixelBlurPx") == blur.SUB_PIXEL_BLUR_PX == verify.S4_SUB_PIXEL_BLUR_PX
    assert _constant(source, "RenderAccumulateMax") == verify.S4_ACCUMULATE_MAX
    rule = _body(source, "int32 UFlightSimRenderCommandlet::AccumulationCount")
    assert "return PredictedBlurPx < RenderSubPixelBlurPx ? 1 : FMath::Max(1, RequestedK);" in rule
    assert "AccumulationCount(PredictedBlurPx, AccumulateRequested)" in source
    # The window is the shutter centred on the capture instant; K midpoints.
    assert "const double WindowStart = Now - 0.5 * Shutter;" in source
    assert "const double WindowEnd = Now + 0.5 * Shutter;" in source
    assert "const double Offset = Shutter * ((k + 0.5) / SubExposures - 0.5);" in source
    # A dedicated AA-off capture; its mean IS the frame's linear file, and
    # the instantaneous linear capture does not write over it.
    for flag in ("AntiAliasing", "TemporalAA", "MotionBlur"):
        assert f"AccumulateCapture->ShowFlags.Set{flag}(false);" in source, flag
    assert "AccumulateTarget->RenderTargetFormat = RTF_RGBA32f;" in source
    assert "if (bLinear && AccumulateCapture == nullptr)" in source
    assert 'const FString AccumulateName = FrameName.LeftChop(4) + TEXT("_linear.exr");' in source
    assert 'Record->SetStringField(TEXT("linear"), AccumulateName);' in source
    for key in ("k", "t0_s", "t1_s", "exposure_s", "predicted_blur_px", "requested_k"):
        assert f'Accumulation->SetNumberField(TEXT("{key}"),' in source, key
    assert 'Accumulation->SetArrayField(TEXT("sub_frame_times_s"), SubTimes);' in source
    assert 'Record->SetObjectField(TEXT("accumulation"), Accumulation);' in source
    # blur.py reads exactly those keys to stand down.
    record = {"accumulation": {"k": 4, "t0_s": 1.0, "t1_s": 1.02}}
    assert blur.engine_accumulation_of(record) == {"k": 4, "t0_s": 1.0, "t1_s": 1.02}


def test_the_accumulation_rule_in_python_matches_the_expression():
    def count(predicted, requested):
        return 1 if predicted < blur.SUB_PIXEL_BLUR_PX else max(1, requested)
    assert count(0.2499, 8) == 1 and count(0.25, 8) == 8 and count(3.0, 1) == 1


# -- (5) the sun in lux ------------------------------------------------------------------

def test_the_sun_is_set_in_lux_with_physical_units_and_the_old_scale_is_named():
    scene = SCENE.read_text(encoding="utf-8")
    assert "SetIntensity(8.0f)" not in scene
    assert "const double SunIntensity = bPhysicalSun ? Options.SunLux : SceneEngineSunUnitless;" in scene
    assert "SunLight->SetIntensity(static_cast<float>(SunIntensity));" in scene
    assert re.search(r"constexpr double SceneEngineSunUnitless = 8\.0;", scene)
    assert f'ScenePhysicalLightUnits = TEXT("{radiometry.PHYSICAL_LIGHT_UNITS}");' in scene
    for key in ("intensity", "lux"):
        assert f'SunRecord->SetNumberField(TEXT("{key}"),' in scene, key
    assert 'SunRecord->SetStringField(TEXT("light_units"),' in scene
    header = SCENE_H.read_text(encoding="utf-8")
    assert "double SunLux = 0.0;" in header
    assert "9.5 (noon), 10.5 (dawn), 11.0" in header and "OLD scale" in header
    # radiometry's units check accepts exactly the record the scene writes.
    lux = 95788.0
    numbers = radiometry.exposure_units_check(
        {"sun": {"intensity": lux, "light_units": "physical", "lux": lux}}, 14.97)
    assert numbers["light_units"] == "physical"


def test_the_commandlet_hands_the_lux_to_the_scene_and_refuses_an_impossible_sun():
    source = _source()
    assert "SceneOptions.SunLux = AppliedSunLux;" in source
    assert 'CardLook->TryGetNumberField(TEXT("sun_lux"), CardSunLux)' in source
    assert "!(AppliedSunLux > 0.0 && AppliedSunLux <= RenderSunLuxMax)" in source
    assert 'TEXT("sensing.sun_lux: a sun of %g lux (%s) cannot be lit; it must be a positive ")' in source
    assert "FMath::Log2(AppliedSunLux / RenderEngineSunUnitless)" in source
    assert 'TEXT("bias_overexposure_stops")' in source


def test_the_flags_the_builder_emits_are_the_ones_the_commandlet_parses():
    source = _source()
    tokens = flags.sensing_flags(calibration=True, sun_lux=95788.0, accumulate=8)
    assert tokens == ["-calibration", "-sun-lux=95788", "-accumulate=8"]
    assert f'FParse::Param(*Params, TEXT("{flags.CALIBRATION_FLAG[1:]}"))' in source
    assert f'FParse::Value(*Params, TEXT("{flags.SUN_LUX_PREFIX[1:]}"), SunLuxFlag)' in source
    assert f'FParse::Value(*Params, TEXT("{flags.ACCUMULATE_PREFIX[1:]}"), AccumulateRequested)' in source


# -- (6) the read-backs and the refusals ---------------------------------------------------

def test_the_render_settings_read_back_what_the_chain_needs():
    source = _source()
    block = re.search(r"const TCHAR\* const ConsoleNames\[\] = \{(.*?)\n\t\t\};", source, re.S).group(1)
    for name in verify.S4_READBACK_CVARS:
        assert f'TEXT("{name}"),' in block, name
    assert radiometry.LENS_ATTENUATION_CVAR in verify.S4_READBACK_CVARS
    assert 'RenderSettings->SetStringField(TEXT("working_colour_space"),' in source
    assert f'TEXT("{radiometry.WORKING_COLOUR_SPACE_DEFAULT}")' in source
    assert "UE::Color::FColorSpace::GetWorking()" in source


def test_every_s4_refusal_is_by_name_and_catalogued():
    source = _source()
    names = set(re.findall(r'TEXT\("((?:sensing|labels)\.[a-z_]+): ', source))
    for name in ("sensing.calibration", "sensing.accumulate", "sensing.sun_lux",
                 "labels.velocity_check", "labels.normal_encoding", "labels.pass_material"):
        assert name in names, name
    assert all(is_catalogued(name) for name in names), sorted(n for n in names if not is_catalogued(n))
    for name in ("engine_linear_passes", "velocity_readback", "engine_readbacks",
                 "calibration_frame", "engine_accumulation"):
        assert is_catalogued(f"check.{name}"), name
    assert is_catalogued(verify.FAIL_READBACK) and is_catalogued(verify.FAIL_ACCUMULATION)


def test_the_materials_the_commandlet_loads_are_the_scripts():
    source = _source()
    script = SCRIPT.read_text(encoding="utf-8")
    for name in ("M_Velocity", "M_WorldNormal", "M_GreyCard"):
        assert f'TEXT("/Game/FlightSim/{name}.{name}")' in source, name
    assert f'GREY_CARD_LUMINANCE_PARAMETER = "{_string_constant(source, "RenderGreyCardLuminanceParameter")}"' \
        in script
    assert f'GREY_CARD_REFLECTANCE_PARAMETER = "{_string_constant(source, "RenderGreyCardReflectanceParameter")}"' \
        in script
    assert _constant(source, "RenderGreyCardReflectance") == float(
        re.search(r"^GREY_CARD_REFLECTANCE_DEFAULT = ([0-9.]+)$", script, re.M).group(1))


# -- (7) the verifier grades each key only when present -----------------------------------

W, H = 6, 4


def _run(tmp_path, payload: dict, files: dict = None, camera: str = "chase") -> Path:
    folder = tmp_path / "frames" / camera
    folder.mkdir(parents=True)
    (folder / "render.json").write_text(json.dumps(payload), encoding="utf-8")
    for name, data in (files or {}).items():
        path = folder / name
        if isinstance(data, np.ndarray):
            path.write_bytes(data.astype("<f4").tobytes())
        elif isinstance(data, dict):
            path.write_text(json.dumps(data), encoding="utf-8")
        else:
            path.write_bytes(data)
    return tmp_path


def _unit_normals() -> np.ndarray:
    normal = np.zeros((H, W, 3), dtype=np.float32)
    normal[..., 2] = 1.0
    normal[0, :, :] = 0.0                  # the sky row: 0, 0, 0
    return normal


def _linear_payload(**labels) -> dict:
    record = {"frame": "frame_0000.png", "t": 1.0,
              "normal_f32": "frame_0000_normal.f32", "basecolor_f32": "frame_0000_basecolor.f32",
              "labels": {"normal": "frame_0000_normal.f32", "normal_axes": "north,east,up",
                         "normal_encoding": "offset_half", "basecolor": "frame_0000_basecolor.f32",
                         "basecolor_out_of_range_pixels": 0, **labels}}
    return {"width": W, "height": H, "frame_records": [record]}


def test_nothing_to_grade_is_not_run_for_every_s4_check(tmp_path):
    run = _run(tmp_path, {"width": W, "height": H, "frame_records": [{"frame": "frame_0000.png"}]})
    for check in (verify.verify_engine_linear_passes, verify.verify_velocity_readback,
                  verify.verify_engine_readbacks, verify.verify_calibration_frame,
                  verify.verify_engine_accumulation):
        assert check({}, run).status == verify.NOT_RUN, check.__name__
        assert check({}, None).status == verify.NOT_RUN, check.__name__


def test_linear_passes_pass_and_fail_by_name(tmp_path):
    colour = np.full((H, W, 3), 0.4, dtype=np.float32)
    good = _run(tmp_path / "a", _linear_payload(),
                {"frame_0000_normal.f32": _unit_normals(), "frame_0000_basecolor.f32": colour})
    assert verify.verify_engine_linear_passes({}, good).status == verify.PASS
    axes = _run(tmp_path / "b", _linear_payload(normal_axes="x,y,z"),
                {"frame_0000_normal.f32": _unit_normals(), "frame_0000_basecolor.f32": colour})
    result = verify.verify_engine_linear_passes({}, axes)
    assert result.status == verify.FAIL and result.failure == verify.FAIL_NORMALS
    encoded = _unit_normals() * 0.5 + 0.5                      # written still encoded: not unit
    stale = _run(tmp_path / "c", _linear_payload(),
                 {"frame_0000_normal.f32": encoded, "frame_0000_basecolor.f32": colour})
    assert verify.verify_engine_linear_passes({}, stale).failure == verify.FAIL_NORMALS
    short = _run(tmp_path / "d", _linear_payload(),
                 {"frame_0000_normal.f32": _unit_normals()[:, :, :2], "frame_0000_basecolor.f32": colour})
    assert verify.verify_engine_linear_passes({}, short).failure == verify.FAIL_NORMALS
    bright = colour.copy()
    bright[1, 1, 0] = 1.5                                      # one pixel out of range, declared 0
    miscounted = _run(tmp_path / "e", _linear_payload(),
                      {"frame_0000_normal.f32": _unit_normals(), "frame_0000_basecolor.f32": bright})
    assert verify.verify_engine_linear_passes({}, miscounted).failure == verify.FAIL_ALBEDO
    missing = _run(tmp_path / "f", _linear_payload(), {"frame_0000_basecolor.f32": colour})
    assert verify.verify_engine_linear_passes({}, missing).failure == verify.FAIL_FILES


def _velocity_run(root, p95, first=False):
    flow = np.zeros((H, W, 2), dtype=np.float32)
    if not first:
        flow[..., 0] = np.arange(W, dtype=np.float32)[None, :]
    depth = np.full((H, W, 1), 100.0, dtype=np.float32)
    speeds = np.sort(np.hypot(flow[..., 0], flow[..., 1]).ravel())
    own = 0.0 if first else float(speeds[int(0.95 * (speeds.size - 1))])
    record = {"frame": "frame_0001.png", "velocity_f32": "frame_0001_velocity.f32",
              "labels": {"depth_f32": "frame_0001_depth.f32",
                         "velocity": {"file": "frame_0001_velocity.f32", "first_frame": first,
                                      "p95_px": own if p95 is None else p95}}}
    return _run(root, {"width": W, "height": H, "frame_records": [record]},
                {"frame_0001_velocity.f32": flow, "frame_0001_depth.f32": depth})


def test_the_velocity_readback_grades_its_own_record(tmp_path):
    assert verify.verify_velocity_readback({}, _velocity_run(tmp_path / "a", None)).status == verify.PASS
    assert verify.verify_velocity_readback({}, _velocity_run(tmp_path / "b", None, first=True)).status \
        == verify.PASS
    wrong = verify.verify_velocity_readback({}, _velocity_run(tmp_path / "c", 99.0))
    assert wrong.status == verify.FAIL and wrong.failure == verify.FAIL_FLOW


def _readback_payload(lux=95788.0, units="physical", intensity=None, attenuation="0.78"):
    return {"render_settings": {"console": {"r.EyeAdaptation.LensAttenuation": attenuation,
                                            "r.UsePreExposure": "1", "r.VelocityOutputPass": "0",
                                            "r.Substrate": "0"},
                                "working_colour_space": radiometry.WORKING_COLOUR_SPACE_DEFAULT},
            "look_applied": {"sun": {"intensity": lux if intensity is None else intensity,
                                     "light_units": units, "lux": lux}}}


def test_the_readbacks_pass_and_a_sun_that_is_not_in_lux_fails(tmp_path):
    assert verify.verify_engine_readbacks({}, _run(tmp_path / "a", _readback_payload())).status == verify.PASS
    for name, payload in (("b", _readback_payload(units="unitless")),
                          ("c", _readback_payload(intensity=8.0)),
                          ("d", _readback_payload(lux=200000.0)),
                          ("e", _readback_payload(attenuation="1.5")),
                          ("f", _readback_payload(attenuation="lots"))):
        result = verify.verify_engine_readbacks({}, _run(tmp_path / name, payload))
        assert result.status == verify.FAIL and result.failure == verify.FAIL_READBACK, name


def _calibration(ev=14.97, lux=95788.0, a=0.78, white_ratio=1.0, emissive_ratio=1.0, rho=0.9):
    """A calibration record in the commandlet's shape, its predictions from
    core/capture/radiometry.py (the chain the commandlet restates)."""
    per_unit = radiometry.luminance_per_unit(ev, 0.0, a)
    nits = radiometry.grey_card_luminance(lux)
    emissive_p = nits / per_unit
    white_p = radiometry.grey_card_luminance(lux, rho) / per_unit
    grey_p = radiometry.grey_card_prediction(lux, ev, 0.0, a)
    white_m = white_p * white_ratio
    grey_m = white_m * 0.18 / rho
    return {"frame": "calibration_0000.png", "ev100": ev, "exposure_compensation_ev": 0.0,
            "lens_attenuation": a, "luminance_cd_m2_per_unit": per_unit, "sun_lux": lux,
            "grey_card_nits": nits, "predicted": grey_p, "measured": grey_m, "ratio": grey_m / grey_p,
            "emissive": {"nits": nits, "predicted": emissive_p, "measured": emissive_p * emissive_ratio,
                         "ratio": emissive_ratio},
            "lambertian": {"reflectance": rho, "predicted": white_p, "measured": white_m,
                           "ratio": white_ratio},
            "slanted_edge": {"frame": "calibration_0000.png",
                             "quad_px": [[10, 10], [40, 10], [40, 40], [10, 40]]},
            "mtf50_measured": 0.41}


def test_the_calibration_frame_is_re_derived_by_the_checker(tmp_path):
    record = _calibration()
    good = _run(tmp_path / "a", {"calibration": record},
                {"calibration_0000.png": b"png", "calibration.json": record})
    assert verify.verify_calibration_frame({}, good).status == verify.PASS
    # The commandlet's root prediction is the manifest's grey_card_predicted.
    block = radiometry.radiometry_block(14.97, 0.0, {"console": {radiometry.LENS_ATTENUATION_CVAR: "0.78"}},
                                        {"value": 95788.0}, record)
    assert block["grey_card_predicted"] == pytest.approx(record["predicted"], rel=1e-12)
    assert block["calibration_status"] == radiometry.CALIBRATION_MEASURED
    off = _run(tmp_path / "b", {"calibration": _calibration(white_ratio=1.05)}, {"calibration_0000.png": b"png"})
    result = verify.verify_calibration_frame({}, off)
    assert result.status == verify.FAIL and result.failure == verify.FAIL_RADIOMETRY
    emissive = _run(tmp_path / "c", {"calibration": _calibration(emissive_ratio=0.9)},
                    {"calibration_0000.png": b"png"})
    assert verify.verify_calibration_frame({}, emissive).failure == verify.FAIL_RADIOMETRY
    bent = dict(record, luminance_cd_m2_per_unit=record["luminance_cd_m2_per_unit"] * 1.01)
    assert verify.verify_calibration_frame({}, _run(tmp_path / "d", {"calibration": bent},
                                                    {"calibration_0000.png": b"png"})).failure \
        == verify.FAIL_RADIOMETRY
    beside = dict(record, ratio=record["ratio"] * 1.01)
    disagree = _run(tmp_path / "e", {"calibration": record},
                    {"calibration_0000.png": b"png", "calibration.json": beside})
    assert verify.verify_calibration_frame({}, disagree).failure == verify.FAIL_RADIOMETRY
    missing = _run(tmp_path / "f", {"calibration": record})
    assert verify.verify_calibration_frame({}, missing).failure == verify.FAIL_FILES


def _accumulation_run(root, k=4, predicted=3.0, requested=4, shift=0.0):
    t, shutter = 2.0, 1.0 / 60.0
    t0, t1 = t - shutter / 2, t + shutter / 2
    times = [t0 + (j + 0.5) * shutter / k + (shift if j == 0 else 0.0) for j in range(k)]
    record = {"frame": "frame_0000.png", "t": t, "linear": "frame_0000_linear.exr",
              "accumulation": {"k": k, "requested_k": requested, "t0_s": t0, "t1_s": t1,
                               "exposure_s": shutter, "sub_frame_times_s": times,
                               "predicted_blur_px": predicted, "file": "frame_0000_linear.exr"}}
    return _run(root, {"frame_records": [record]}, {"frame_0000_linear.exr": b"exr"})


def test_the_accumulation_record_is_graded_against_itself(tmp_path):
    assert verify.verify_engine_accumulation({}, _accumulation_run(tmp_path / "a")).status == verify.PASS
    assert verify.verify_engine_accumulation(
        {}, _accumulation_run(tmp_path / "b", k=1, predicted=0.1)).status == verify.PASS
    for name, kwargs in (("c", {"k": 1, "predicted": 3.0}),          # the rule says 4
                         ("d", {"k": 4, "predicted": 0.1}),          # the rule says 1
                         ("e", {"shift": 1e-3}),                     # an instant off its midpoint
                         ("f", {"k": 65, "requested": 65})):
        result = verify.verify_engine_accumulation({}, _accumulation_run(tmp_path / name, **kwargs))
        assert result.status == verify.FAIL and result.failure == verify.FAIL_ACCUMULATION, name


def test_verify_run_registers_the_five_checks():
    text = (REPO / "core" / "capture" / "verify.py").read_text(encoding="utf-8")
    body = text[text.index("def verify_run"):]
    for name in ("engine_linear_passes", "velocity_readback", "engine_readbacks",
                 "calibration_frame", "engine_accumulation"):
        assert f'run("{name}", verify_{name}, manifest, run_dir)' in body, name
