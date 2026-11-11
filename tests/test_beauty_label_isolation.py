"""The beauty look never reaches the labels or a measure render.

The output is ML training data: the ID / class / mask, depth and box
passes must be the geometry, not a lens. Lens flare, film grain, bloom,
halation, vignette, denoise and upscale are beauty effects; this file
proves (by reading the C++ source, since nothing compiles on this machine,
and by running the Python plan) that none of them can leak into a label
capture or into a ``-quality=measure`` render:

(a) the engine look (FFlightSimBeautyLook::ApplyEngineLook) and the
    look-dev lane run only inside the beauty-path gate of
    FlightSimRenderCommandlet.cpp, and touch only the beauty capture;
(b) every label capture is a fresh component through ConfigureLabelCapture,
    which turns each of those effects off by show flag, never copies the
    beauty's post-process settings or show flags, and is pinned through
    registration on beauty; the only captures that copy the beauty's
    settings are the beauty's own siblings (linear EXR, accumulation,
    calibration), each lens-free; no post-process volume exists to blend
    into every capture;
(c) a measure-quality run writes no beauty look (no engine_look, no
    film_stock) and adds no flag, and the post pipeline does not run;
(halation, denoise and upscale exist only in scripts/beauty_post.py, whose
label isolation is tests/test_beauty_post.py
test_no_step_reads_or_writes_a_label_file).
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
PUBLIC = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public"
RENDER_CPP = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
LOOK_CPP = (PRIVATE / "FlightSimBeautyLook.cpp").read_text(encoding="utf-8")
LATE = LOOK_CPP[LOOK_CPP.index("bool BeautyLookApplyEngineLook("):LOOK_CPP.index("#undef FLIGHTSIM_BEAUTY_FLOAT")]

#: The beauty effects the engine look and the look-dev lane switch on, and
#: the show flag that turns each off on a capture (the engine gates each
#: effect's pass on it: bloom and the FFT bloom, the lens flare, the film
#: grain, the vignette, plus the other lens/post effects the look sets).
LEAK_FLAGS = ("SetBloom", "SetLensFlares", "SetGrain", "SetVignette", "SetSceneColorFringe",
              "SetLocalExposure", "SetMotionBlur", "SetDepthOfField", "SetLensDistortion",
              "SetPathTracing", "SetEyeAdaptation", "SetLightShafts")


def _block_after(source: str, marker: str) -> str:
    """The brace-balanced block that starts at the first ``{`` after ``marker``."""
    start = source.index("{", source.index(marker))
    depth = 0
    for index in range(start, len(source)):
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        if depth == 0:
            return source[start:index + 1]
    raise AssertionError(f"unbalanced block after {marker!r}")


def _strip_comments(text: str) -> str:
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


CODE = _strip_comments(RENDER_CPP)
LATE_CODE = _strip_comments(LATE)
LOOK_CODE = _strip_comments(LOOK_CPP)


# -- (a) the engine look runs only on the beauty path ------------------------------------

def test_beauty_is_the_beauty_and_pathtrace_tiers_only():
    assert 'const bool bPathTrace = Quality == TEXT("pathtrace");' in CODE
    assert 'const bool bBeauty = Quality == TEXT("beauty") || bPathTrace;' in CODE
    assert CODE.count("const bool bBeauty =") == 1, "bBeauty is defined once and never reassigned"
    assert not re.search(r"\bbBeauty\s*=[^=]", CODE.replace("const bool bBeauty =", "")), \
        "bBeauty is never reassigned"


def test_the_engine_look_is_called_once_inside_the_beauty_raster_gate():
    calls = [m.start() for m in re.finditer(r"FFlightSimBeautyLook::ApplyEngineLook\(", CODE)]
    assert len(calls) == 1, "one call site"
    # The condition the call sits in: from the `if (` before it to the call.
    head = CODE[CODE.rindex("if (", 0, calls[0]):calls[0]]
    assert re.fullmatch(r"if \(bVisual && bBeauty && !bPathTrace &&\s*!", head), head
    # It is handed the beauty capture and nothing else.
    assert CODE[calls[0]:].startswith(
        "FFlightSimBeautyLook::ApplyEngineLook(VisualScene, Capture, bConstrainedGpu, *RenderSwitches)")
    # The other files never call it.
    for path in [*PRIVATE.glob("*.cpp"), *PUBLIC.glob("*.h")]:
        if path.name not in ("FlightSimRenderCommandlet.cpp", "FlightSimBeautyLook.cpp"):
            assert "ApplyEngineLook(" not in _strip_comments(path.read_text(encoding="utf-8")), path.name


def test_the_beauty_capture_is_the_one_named_capture():
    assert re.search(r'USceneCaptureComponent2D\* Capture =\s*NewObject<USceneCaptureComponent2D>'
                     r'\(Director, TEXT\("Capture"\)\);', CODE)
    assert "Capture->CaptureSource = ESceneCaptureSource::SCS_FinalColorLDR;" in CODE


def test_the_engine_look_is_applied_before_any_label_capture_exists():
    call = CODE.index("FFlightSimBeautyLook::ApplyEngineLook(")
    assert call < CODE.index("auto ConfigureLabelCapture"), \
        "label captures are created after the look and take nothing from it"


def test_the_look_dev_lane_and_its_per_frame_hooks_are_beauty_only():
    # The early half (FFlightSimBeautyLook::Apply) is reached only through
    # ApplyBeautyPostProcess, called once inside `if (bVisual && bBeauty)`.
    calls = [m.start() for m in re.finditer(r"FFlightSimVisualScene::ApplyBeautyPostProcess\(", CODE)]
    assert len(calls) == 1
    gate = CODE[CODE.rindex("if (", 0, calls[0]):calls[0]]
    assert re.fullmatch(r"if \(bVisual && bBeauty\)\s*\{\s*", gate), gate
    scene = _strip_comments((PRIVATE / "FlightSimVisualScene.cpp").read_text(encoding="utf-8"))
    assert scene.count("FFlightSimBeautyLook::Apply(") == 1
    assert "FFlightSimBeautyLook::Apply(Capture, FCommandLine::Get());" in _block_after(
        scene, "void FFlightSimVisualScene::ApplyBeautyPostProcess(")
    # The state every later hook reads is set only by Apply (no sidecar on
    # measure, so ApplyEngineLook, UpdatePerFrame and StillAccumulation are
    # no-ops there even where they are not gated by name).
    assert LOOK_CODE.count("State.bApplied = true;") == 1
    assert "State.bApplied = true;" in _block_after(LOOK_CODE, "void FFlightSimBeautyLook::Apply(")
    assert LOOK_CODE.count("State.bEngineLate = true;") == 1 and "State.bEngineLate = true;" in LATE_CODE
    engine = _block_after(LOOK_CODE, "bool FFlightSimBeautyLook::ApplyEngineLook(")
    assert re.search(r"if \(!State\.bApplied \|\| Beauty == nullptr[^\n]*\n\s*\{\s*return true;", engine), engine
    at = CODE.index("FFlightSimBeautyLook::ApplyShutterPolicy(")
    assert CODE[CODE.rindex("if (", 0, at):at].startswith("if (bBeautyRaster)")
    assert re.search(r"const bool bBeautyRaster = bVisual && bBeauty && !bPathTrace;", CODE)
    # The storm meter is short-circuited behind the beauty test.
    assert CODE.count("FFlightSimBeautyLook::ExposureMeter(") == 1
    assert re.search(r"const bool bBeautyMeter = bVisual && bBeauty && !Weather\.DrawsCell\(\) &&\s*"
                     r"FFlightSimBeautyLook::ExposureMeter\(", CODE)


def test_the_engine_look_touches_only_the_capture_it_is_handed():
    # Every show flag and post-process write in the late half is on the
    # parameter `Capture` (the beauty), never another capture.
    for match in re.finditer(r"(\w+)->(ShowFlags|PostProcessSettings|PostProcessBlendWeight)\b", LATE_CODE):
        assert match.group(1) == "Capture", match.group(0)
    for match in re.finditer(r"(\w+)\s*=\s*(\w+)->PostProcessSettings\b", LATE_CODE):
        assert match.group(2) == "Capture", match.group(0)
    # It makes no capture, finds no other capture and spawns no post-process
    # volume (a world volume would blend into every capture, labels too).
    for forbidden in ("NewObject<USceneCapture", "TObjectIterator<USceneCapture",
                      "TActorIterator<ASceneCapture", "PostProcessVolume", "UPostProcessComponent",
                      "SpawnActor"):
        assert forbidden not in LOOK_CODE, forbidden


def test_no_post_process_volume_exists_anywhere_in_the_plugin():
    """A scene capture blends every post-process volume in its world
    (FSceneView::StartFinalPostprocessSettings), so a beauty volume would
    reach the label captures. The plugin spawns none: every beauty setting
    lives on the beauty capture's own PostProcessSettings."""
    for folder in (PRIVATE, PUBLIC):
        for path in [*folder.rglob("*.cpp"), *folder.rglob("*.h")]:
            code = _strip_comments(path.read_text(encoding="utf-8"))
            for forbidden in ("APostProcessVolume", "UPostProcessComponent", "bUnbound"):
                assert forbidden not in code, f"{path.name}: {forbidden}"


# -- (b) the label captures never take the beauty's post process -------------------------

CONFIGURE = _block_after(CODE, "auto ConfigureLabelCapture")
REGISTER = _block_after(CODE, "auto RegisterLabelCapture")
LABEL_REGION = CODE[CODE.index("auto ConfigureLabelCapture"):CODE.index("USceneCaptureComponent2D* LinearCapture = nullptr;")]


@pytest.mark.parametrize("flag", LEAK_FLAGS)
def test_every_label_capture_turns_the_beauty_effect_off(flag):
    assert f"Label->ShowFlags.{flag}(false);" in CONFIGURE, flag
    assert f"Label->ShowFlags.{flag}(true);" not in CONFIGURE


def test_the_label_capture_copies_nothing_from_the_beauty():
    assert "Label->FOVAngle = Capture->FOVAngle;" in CONFIGURE, "the pose's lens angle only"
    copies = re.findall(r"Label->\w+(?:\.\w+)*\s*=\s*Capture->[\w.]+", CONFIGURE)
    assert copies == ["Label->FOVAngle = Capture->FOVAngle"], copies
    for forbidden in ("PostProcessSettings =", "ShowFlags =", "PostProcessBlendWeight =",
                      "WeightedBlendables", "SetShowFlagSettings"):
        assert forbidden not in CONFIGURE, forbidden
    # Only unit exposure is set on its post process.
    for match in re.finditer(r"Label->PostProcessSettings\.(\w+)", CONFIGURE):
        assert "AutoExposure" in match.group(1), match.group(0)
    assert "Label->HiddenActors.Append(VisualScene.BeautyOnlyActors);" in CONFIGURE
    assert "FFlightSimHeroLighting::ExcludeFromLabel(Label);" in CONFIGURE


def test_the_label_flags_are_pinned_through_registration_on_beauty():
    assert re.search(r"if \(bBeauty\)\s*\{\s*RenderPinShowFlags\(Label\);\s*\}\s*Label->RegisterComponent\(\);",
                     REGISTER), REGISTER


def test_every_label_capture_goes_through_configure_and_register():
    made = re.findall(r"(\w+)\s*=\s*NewObject<USceneCaptureComponent2D>", LABEL_REGION)
    made += re.findall(r"USceneCaptureComponent2D\*\s+(\w+)\s*=\s*\n?\s*NewObject<USceneCaptureComponent2D>",
                       LABEL_REGION)
    made = sorted(set(made))
    assert {"Depth", "LabelLandcover", "Pass", "PassNormal", "PassAlbedo", "Normal", "BaseColor"} <= set(made), made
    for name in made:
        assert f"ConfigureLabelCapture({name});" in LABEL_REGION, name
        assert f"RegisterLabelCapture({name});" in LABEL_REGION, name
        assert not re.search(rf"\b{name}->(PostProcessSettings|ShowFlags)\s*=", LABEL_REGION), name
        assert not re.search(rf"\b{name}->[\w.]+\s*=\s*Capture->(PostProcess|ShowFlags)", LABEL_REGION), name
        for weight in re.findall(rf"\b{name}->PostProcessBlendWeight\s*=\s*([^;]+);", LABEL_REGION):
            assert weight == "1.0f", (name, weight)   # the label's own material, at full weight
    # The ID, the class and the depth are all depth-owned show-only captures.
    assert "Depth->CaptureSource = ESceneCaptureSource::SCS_SceneDepth;" in LABEL_REGION
    assert "LabelDepthAll = MakeDepthCapture(" in LABEL_REGION


def test_a_label_blendable_is_only_a_label_material():
    """The label captures that run a post-process material run the label's
    own (land cover, the pass materials), at weight 1 over nothing else."""
    adds = re.findall(r"(\w+)->PostProcessSettings\.WeightedBlendables\.Array\.Add\(\s*FWeightedBlendable\(1\.0f, (\w+)\)\)",
                      LABEL_REGION)
    assert sorted(adds) == sorted([("LabelLandcover", "LandcoverInstance"), ("Pass", "Material"),
                                   ("Pass", "Material")]), adds
    for name, _material in adds:
        assert f"ConfigureLabelCapture({name});" in LABEL_REGION


def test_only_the_beauty_siblings_copy_the_beauty_settings_and_each_is_lens_free():
    copies = sorted(set(re.findall(r"(\w+)->PostProcessSettings = Capture->PostProcessSettings;", CODE)))
    # CoverCapture: the measured cover (2026-11-11), lens-free through
    # RenderMakeCoverCapture, which calls RenderMakeLensFree.
    assert copies == ["AccumulateCapture", "CalibrationCapture", "CoverCapture", "LinearCapture"], copies
    flag_copies = sorted(set(re.findall(r"(\w+)->ShowFlags = Capture->ShowFlags;", CODE)))
    assert flag_copies == ["AccumulateCapture", "CalibrationCapture", "CoverCapture", "LinearCapture"], \
        flag_copies
    assert "RenderMakeLensFree(Cover);" in _block_after(CODE, "void RenderMakeCoverCapture(")
    assert "RenderMakeCoverCapture(CoverCapture);" in CODE and "RenderPinShowFlags(CoverCapture);" in CODE
    lens_free = _block_after(CODE, "void RenderMakeLensFree(")
    for flag in ("SetBloom", "SetLensFlares", "SetGrain", "SetVignette", "SetSceneColorFringe",
                 "SetLocalExposure", "SetMotionBlur", "SetDepthOfField"):
        assert f"Flags.{flag}(false);" in lens_free, flag
    for sibling in ("LinearCapture", "AccumulateCapture"):
        assert f"RenderMakeLensFree({sibling});" in CODE, sibling
        assert f"RenderPinShowFlags({sibling});" in CODE, sibling
    calibration = CODE[CODE.index("CalibrationCapture->ShowFlags = Capture->ShowFlags;"):
                       CODE.index("CalibrationCapture->RegisterComponent();")]
    for flag in ("SetBloom", "SetLensFlares", "SetVignette", "SetGrain", "SetSceneColorFringe",
                 "SetLocalExposure", "SetMotionBlur", "SetDepthOfField", "SetLightShafts"):
        assert f"CalibrationCapture->ShowFlags.{flag}(false);" in calibration, flag
    assert "RenderPinShowFlags(CalibrationCapture);" in calibration


def test_the_engine_looks_global_cvars_need_a_show_flag_the_labels_turn_off():
    """The engine look's renderer cvars are process-wide, so they reach a
    label capture's view; each lens/post one only acts through a show flag
    every label capture has off (and pinned on beauty)."""
    from core.scene.beauty_look import ENGINE_LOOK

    needs = {"r.LensFlareQuality": "SetLensFlares", "r.FilmGrain": "SetGrain",
             "r.VolumetricFog": "SetVolumetricFog", "r.VolumetricFog.GridPixelSize": "SetVolumetricFog",
             "r.VolumetricFog.GridSizeZ": "SetVolumetricFog"}
    seen = set()
    for row in ENGINE_LOOK.values():
        for key in ("cvars", "cvars_constrained", "cvars_off"):
            for name in (row.get(key) or {}):
                if name in needs:
                    seen.add(name)
                    assert f"Label->ShowFlags.{needs[name]}(false);" in CONFIGURE, name
    assert {"r.LensFlareQuality", "r.FilmGrain"} <= seen, seen


# -- (c) the Python plan: measure has no beauty look ------------------------------------

def test_a_measure_run_writes_no_beauty_look_and_adds_no_flag(tmp_path):
    from webapp.runs import beauty_look_render_flags, write_beauty_look_plan

    assert write_beauty_look_plan(None, tmp_path, {}, quality="measure") is None
    assert not (tmp_path / "beauty_look.json").exists()
    assert beauty_look_render_flags(None) == []
    from core.scene.beauty_look import beauty_look_flags

    assert beauty_look_flags(None) == []


def test_a_measure_plan_has_no_engine_look_and_no_film_stock():
    """What the post pipeline and the host see for a measure run: no
    sidecar, so no engine_look and no film_stock; a beauty plan has both."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("beauty_post", REPO / "scripts" / "beauty_post.py")
    bp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bp)
    from core.scene.beauty_look import plan_beauty_look

    for measure in (None, {}):
        choice = bp.look_choices(measure)
        assert choice["cube"] is None and choice["stock"] is None and choice["noisy"] is False
    beauty = plan_beauty_look(20.0, fps=30.0, width_px=1920, world_preset="storm")
    assert beauty.get("engine_look") and beauty.get("film_stock"), "the contrast: beauty carries both"
    assert bp.look_choices(beauty)["cube"] is not None


def test_the_web_app_runs_the_post_pipeline_only_with_a_beauty_look():
    source = _strip_comments((REPO / "webapp/runs.py").read_text(encoding="utf-8"))
    call = source.index("self._beauty_post(run, out, beauty_look)")
    assert re.search(r"if beauty_look is not None:\s*$", source[:call].rstrip() + "\n", re.M) or \
        source[:call].rstrip().endswith("if beauty_look is not None:")
    assert "if (quality or render_quality()) != \"beauty\":\n        return None" in source


def test_the_subject_meter_is_beauty_only_and_never_touches_a_label_capture():
    """Lane A's subject meter (round 7) moves only the beauty capture's exposure
    bias: gated on beauty owning the exposure, no label capture named in its
    block, and the aircraft it hides for the mask shown again before the frame."""
    start = RENDER_CPP.index('SubjectMeterSwitch == TEXT("on"))')
    gate = RENDER_CPP[RENDER_CPP.rindex("if (", 0, start):start]
    assert "bBeauty" in gate and "OwnsExposure()" in gate
    block = RENDER_CPP[start:RENDER_CPP.index('SetObjectField(TEXT("subject_exposure")', start)]
    assert "ConfigureLabelCapture" not in block and "LabelCapture" not in block
    assert block.count("Capture->HiddenActors.AddUnique(Scenario.Aircraft)") == 1
    assert block.count("Capture->HiddenActors.Remove(Scenario.Aircraft)") == 1
    assert block.index("HiddenActors.AddUnique") < block.index("HiddenActors.Remove")


def test_the_lifted_sea_cap_is_beauty_only_so_label_depth_stays_on_the_tiles():
    """Round 19 lane B lifts the beauty sea cap ~20 m over Google's ocean tiles:
    it must be a beauty-only actor (hidden from every label capture), so the
    depth, ID and mask passes keep the tiles' own sea surface."""
    tiles = (PRIVATE / "FlightSimGoogleTiles.cpp").read_text(encoding="utf-8")
    ground = tiles[tiles.index("TSharedPtr<FJsonObject> FFlightSimGoogleTiles::ApplyBeautyGround("):]
    assert "BeautyOnlyActors.Add(SeaActor);" in ground
