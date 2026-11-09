"""Render-path lane (visual plan V0/V8): source pins over the beauty and
path-trace path of the render commandlet, the engine ini decision and the
bridge API check. Nothing here compiles or renders (this Mac cannot);
these pin what was written so a later edit cannot quietly undo it."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMANDLET = (ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/"
              "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
INI = (ROOT / "ue/Config/DefaultEngine.ini").read_text(encoding="utf-8")
CHECK = (ROOT / "scripts/check_bridge_api.sh").read_text(encoding="utf-8")


def _beauty_block() -> str:
    start = COMMANDLET.index("TSharedPtr<FJsonObject> BeautyPath;")
    end = COMMANDLET.index('AntiAliasingMethod = ReadCvar(TEXT("r.AntiAliasingMethod"));', start)
    return COMMANDLET[start:end]


def test_quality_accepts_pathtrace_and_still_refuses_unknown_words():
    assert 'Quality != TEXT("pathtrace")' in COMMANDLET
    assert "is not one of measure, beauty, pathtrace" in COMMANDLET
    assert 'const bool bPathTrace = Quality == TEXT("pathtrace");' in COMMANDLET
    assert 'const bool bBeauty = Quality == TEXT("beauty") || bPathTrace;' in COMMANDLET


def test_the_beauty_block_runs_only_on_beauty_and_records_nothing_on_measure():
    block = _beauty_block()
    assert "if (bVisual && bBeauty)" in block
    # BeautyPath is only allocated inside the gate, and render_settings
    # only writes it when it was allocated.
    assert block.index("BeautyPath = MakeShared<FJsonObject>();") > block.index("if (bVisual && bBeauty)")
    assert "if (BeautyPath.IsValid())" in COMMANDLET
    assert 'RenderSettings->SetObjectField(TEXT("beauty_path"), BeautyPath);' in COMMANDLET


def test_tsr_is_actually_on_in_the_beauty_capture():
    """The V0 audit: a 2D capture's constructor clears TemporalAA and the
    view falls back from TSR to FXAA without it."""
    block = _beauty_block()
    tsr = block[block.index("if (!bPathTrace)"):block.index("else", block.index("if (!bPathTrace)"))]
    assert "Capture->ShowFlags.SetTemporalAA(true);" in tsr
    assert "Capture->ShowFlags.SetAntiAliasing(true);" in tsr


def test_measure_takes_exactly_one_capture_a_frame():
    assert "int32 BeautySubFrames = 1;" in COMMANDLET
    loop = ("for (int32 SubFrame = 1; SubFrame < BeautySubFrames; ++SubFrame)")
    assert loop in COMMANDLET
    # Every assignment that raises it is gated on a beauty tier.
    for match in re.finditer(r"\n(\t+)(?:else )?if \(([^\n]*)\)\n\1\{\n\1\tBeautySubFrames = ", COMMANDLET):
        assert "bBeauty" in match.group(2) or "bPathTrace" in match.group(2), match.group(0)
    assert COMMANDLET.count("BeautySubFrames = ") == 4   # the 1 and three gated


def test_still_samples_and_pathtrace_flags_refuse_off_their_tier():
    assert "render.still_samples: -still-samples needs -quality=beauty" in COMMANDLET
    assert "render.pathtrace: -pathtrace-spp/-bounces/-denoise need -quality=pathtrace" in COMMANDLET


def test_pathtrace_refuses_by_name_where_it_cannot_run():
    block = _beauty_block()
    for needle in ("#if !PLATFORM_WINDOWS", "!GRHISupportsRayTracing",
                   "GetSupportsPathTracing(GMaxRHIShaderPlatform)", "!IsRayTracingEnabled()",
                   "bAccumulate || bLinear || bCalibration",
                   "Capture->ShowFlags.SetPathTracing(true);",
                   "Beauty.PathTracingSamplesPerPixel = PathTraceSpp;",
                   "Beauty.bOverride_PathTracingEnableDenoiser = true;"):
        assert needle in block, needle
    assert "render.pathtrace: -quality=pathtrace needs -Visual" in COMMANDLET


def test_every_look_constant_is_marked_uncalibrated():
    names = re.findall(r"constexpr \w+ (Render(?:Beauty|PathTrace)\w+) = ", COMMANDLET)
    assert len(names) >= 15
    section = COMMANDLET[COMMANDLET.index("-- Visual plan V0/V8, render-path lane"):
                         COMMANDLET.index("RenderPathTraceDenoiseDefault = 1;")]
    # one UNCALIBRATED marker per constant group, each naming its probe
    groups = section.split("// UNCALIBRATED: set by probe render on the render machine.")
    assert len(groups) - 1 >= 9
    for group in groups[1:]:
        assert "probe" in group.lower()


def test_every_beauty_cvar_is_checked_against_the_engine():
    """A cvar the commandlet sets is one check_bridge_api.sh greps for."""
    block = _beauty_block()
    set_names = set(re.findall(r'SetBeautyCvar\(TEXT\("([^"]+)"\)', block))
    checked = set(re.findall(r"^rp_cvar (\S+) ", CHECK, re.M))
    # the two re-asserted from the earlier V0 code are checked elsewhere
    # (the ini block and the console read-back), not by rp_cvar
    missing = set_names - checked - {"r.AntiAliasingMethod", "r.Shadow.Virtual.Enable"}
    assert not missing, missing
    assert "rp_check \"show flag TemporalAA\"" in CHECK
    assert "rp_check \"show flag PathTracing\"" in CHECK


def test_ray_tracing_support_stays_out_of_the_project_ini():
    active = [line for line in INI.splitlines()
              if line.strip().startswith("r.RayTracing")]
    assert active == []
    assert "-ini:Engine:[/Script/Engine.RendererSettings]:r.RayTracing=True" in INI
    # the startup-only switches the measure path already ran on stay
    assert "\nr.Nanite.ProjectEnabled=True\n" in INI
    assert "\nr.GenerateMeshDistanceFields=True\n" in INI
    assert "\nr.Lumen.HardwareRayTracing=False\n" in INI


def test_refusal_names_are_catalogued():
    text = (ROOT / "core/messages/catalog.yaml").read_text(encoding="utf-8")
    assert "\nrender.still_samples:\n" in text
    assert "\nrender.pathtrace:\n" in text


# -- fix pass (shots-render, 2026-11-09) --------------------------------------


def _aa_lambda() -> str:
    start = COMMANDLET.index("auto AntiAliasingName = ")
    return COMMANDLET[start:COMMANDLET.index("};", start)]


def test_the_aa_record_follows_the_engine_fallback():
    """SceneView.cpp drops TSR/TAA to FXAA when the capture's TemporalAA
    show flag is clear; render.json must name what ran, not what was asked."""
    body = _aa_lambda()
    assert "const FEngineShowFlags& Flags" in body
    assert "Flags.TemporalAA == 0" in body
    assert "(Method == 2 || Method == 4)" in body
    assert "FXAA (%s fell back: TemporalAA show flag off)" in body
    assert "Flags.PathTracing != 0" in body
    assert 'AntiAliasing->SetStringField(TEXT("beauty"), AntiAliasingName(Capture->ShowFlags));' in COMMANDLET
    assert "AntiAliasingName(LinearCapture->ShowFlags)" in COMMANDLET
    assert "AntiAliasingName(AccumulateCapture->ShowFlags)" in COMMANDLET
    assert 'rp_check "TAA falls back without the flag"' in CHECK


def test_the_beauty_sky_never_lowers_the_cinematic_level():
    value = float(re.search(r"constexpr float RenderBeautySkySampleCountMax = ([\d.]+)f;",
                            COMMANDLET).group(1))
    per_slice = float(re.search(
        r"constexpr float RenderBeautyAerialPerspectiveSamplesPerSlice = ([\d.]+)f;",
        COMMANDLET).group(1))
    assert value >= 256.0 and per_slice >= 8.0   # BaseScalability.ini [EffectsQuality@Cine]
    block = _beauty_block()
    assert 'BeforeOverride->SetStringField(Name, Variable->GetString());' in block
    assert block.index("BeforeOverride->SetStringField") < block.index("Variable->Set(Value, ECVF_SetByCode);")
    assert 'BeautyPath->SetObjectField(TEXT("cvars_before_override"), BeforeOverride);' in block
    assert 'rp_check "Cinematic sky SampleCountMax 256"' in CHECK


def _subframes() -> str:
    start = COMMANDLET.index("const bool bPathTraceClip = ")
    return COMMANDLET[start:COMMANDLET.index('BeautyPath->SetObjectField(TEXT("accumulation"), SubFrames);', start)]


def test_the_path_tracer_refuses_a_clip_unless_asked():
    block = _subframes()
    assert 'FParse::Param(*Params, TEXT("pathtrace-clip"))' in block
    refusal = block[block.index("if (DeliveredFrames > RenderBeautyStillMaxFrames && !bPathTraceClip)"):]
    assert refusal.index("return Fail(") < refusal.index("int32 BeautySubFrames = 1;")
    assert "render.pathtrace: -quality=pathtrace is for stills" in refusal
    assert "path-traced captures" in block   # the estimate is logged
    assert 'SubFrames->SetNumberField(TEXT("total_captures")' in COMMANDLET


def test_a_beauty_clip_keeps_one_capture_a_frame():
    block = _subframes()
    stated = ("else if (bVisual && bBeauty && bStillSamplesFlag && "
              "DeliveredFrames <= RenderBeautyStillMaxFrames)")
    assert stated in block
    ignored = block[block.index("else if (bVisual && bBeauty && bStillSamplesFlag)\n"):]
    ignored = ignored[:ignored.index("else if", 10)]
    assert "BeautySubFrames = " not in ignored and "ignored on this clip" in ignored


def test_the_path_tracer_draws_the_reference_sky_and_says_so():
    block = _beauty_block()
    pt = block[block.index("Capture->ShowFlags.SetPathTracing(true);"):]
    assert "Beauty.PathTracingEnableReferenceAtmosphere = 1;" in pt
    assert 'SetBeautyCvar(TEXT("r.PathTracing.EnableReferenceClouds"), 1.0f);' in pt
    assert 'PathTracer->SetBoolField(TEXT("reference_atmosphere")' in pt


def test_the_label_mismatches_are_said_in_render_json():
    block = _beauty_block()
    pt = block[block.index("Capture->ShowFlags.SetPathTracing(true);"):]
    labels_note = pt[pt.index('TEXT("labels_note")'):]
    assert "FALLBACK" in labels_note[:800]
    assert 'TEXT("r.RayTracing.Nanite.Mode")' in pt
    acc = COMMANDLET[COMMANDLET.index('SubFrames->SetStringField(TEXT("labels"),'):
                     COMMANDLET.index('BeautyPath->SetObjectField(TEXT("accumulation"), SubFrames);')]
    assert acc.index("if (!bPathTrace)") < acc.index('TEXT("history_across_frames")')
    assert acc.index("if (LinearCapture != nullptr)") < acc.index('TEXT("linear_capture")')
    assert "render-path: the path tracer replaces Lumen" in COMMANDLET


def test_measure_render_json_gains_no_beauty_look_key():
    """Record() is nullptr on measure; FJsonObject::SetObjectField would
    then store a JSON null, so the write must sit behind the guard."""
    write = 'Root->SetObjectField(TEXT("beauty_look"), BeautyLook);'
    assert COMMANDLET.count(write) == 1
    guard = "if (TSharedPtr<FJsonObject> BeautyLook = FFlightSimBeautyLook::Record())"
    before = COMMANDLET[:COMMANDLET.index(write)]
    assert before.rstrip().endswith(guard + " {")
    look = (ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/"
            "FlightSimBeautyLook.cpp").read_text(encoding="utf-8")
    body = look[look.index("TSharedPtr<FJsonObject> FFlightSimBeautyLook::Record()"):]
    body = re.sub(r"\s+", " ", body[:400])
    assert "{ const FBeautyLookState& State = BeautyLookState(); if (!State.bApplied) { return nullptr; }" in body


def test_a_beauty_look_with_an_animated_sun_refuses_by_name():
    start = COMMANDLET.index("if (!FFlightSimBeautyLook::LastError().IsEmpty())")
    block = COMMANDLET[start:COMMANDLET.index("auto SetCvar = ", start)]
    assert "if (bSunAnimated && FFlightSimBeautyLook::Record().IsValid())" in block
    assert 'return Fail(TEXT("render.beauty_look: -beauty-look= plans' in block


def test_measure_render_json_gains_no_aircraft_look_key():
    write = 'Root->SetObjectField(TEXT("aircraft_look")'
    assert COMMANDLET.count(write) == 1
    before = COMMANDLET[:COMMANDLET.index(write)][-120:]
    guard = "if (AircraftFX.IsBuilt() && AircraftFX.Record.IsValid())"
    assert guard in before and "}" not in before[before.index(guard):]
