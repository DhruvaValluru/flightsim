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
