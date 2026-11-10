"""Clouds round 6 (2026-11-10): the volumetric clouds' altitude-slice banding.

Round 3's clear-sky beauty frames (#03 A320 over New York, #12 C172 over the
Grand Canyon, #13 747 over the ocean) and head3 shot d drew the clouds as
horizontal strata, pancake ledges and topographic contours with no grain in
them. The engine marches a cloud layer in fixed altitude slices and hides the
slice boundaries with a per-pixel, per-capture blue-noise start offset that TSR
averages; a rendering commandlet gets a constant offset instead (BlueNoise.cpp's
1x1 dummy, or a texture still building answering as a default stand-in), so
every capture traced the same slices. The render commandlet now loads and
builds the two blue-noise textures before its first beauty capture. Source
pins (the authoring Mac cannot build UE), the engine lines where its install
exists, and the proof that the constrained-GPU march did not move."""

import re
from pathlib import Path

import pytest

from core.scene import world_beauty

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
COMMANDLET = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
CLOUDS = (PRIVATE / "FlightSimClouds.cpp").read_text(encoding="utf-8")
CHECK = (ROOT / "scripts/check_bridge_api.sh").read_text(encoding="utf-8")
ENGINE = Path("/Users/Shared/Epic Games/UE_5.7/Engine")


def _blue_noise_block() -> str:
    start = COMMANDLET.index("// -- clouds round 6 (2026-11-10): the cloud march's jitter in a commandlet --")
    end = COMMANDLET.index("// Every volumetric cloud's material checked the way the engine's cloud", start)
    return COMMANDLET[start:end]


# -- the fix sits where the renderer's lazy load cannot ------------------------

def test_the_textures_are_loaded_and_built_after_the_asset_wait_and_before_the_first_capture():
    block_at = COMMANDLET.index("// -- clouds round 6 (2026-11-10): the cloud march's jitter in a commandlet --")
    asset_wait = COMMANDLET.index("FAssetCompilingManager::Get().FinishAllCompilation();")
    first_capture = COMMANDLET.index("for (int32 i = 0; i < WarmupCaptures; ++i)")
    assert asset_wait < block_at < first_capture
    block = _blue_noise_block()
    # the renderer's own call, then the build finished the way the meshes' is
    assert block.index("GEngine->LoadBlueNoiseTexture(true);") < block.index(
        "FAssetCompilingManager::Get().FinishAllCompilation();")
    # the render thread's pointer is set before the first warm-up capture
    assert block.index("FlushRenderingCommands();") > block.index('DescribeBlueNoise(TEXT("vec2")')


def test_both_textures_are_described_because_the_engine_needs_both():
    block = _blue_noise_block()
    assert 'DescribeBlueNoise(TEXT("scalar"), GEngine->BlueNoiseScalarTexture);' in block
    assert 'DescribeBlueNoise(TEXT("vec2"), GEngine->BlueNoiseVec2Texture);' in block
    # a texture with no resource gets one; a stand-in is reported, not trusted
    assert "if (Texture != nullptr && Texture->GetResource() == nullptr)" in block
    assert "Texture->UpdateResource();" in block
    assert "Texture->IsDefaultTexture();" in block
    assert "bBlueNoiseReady = bBlueNoiseReady && Resource != nullptr && !bStandIn;" in block


def test_the_record_names_what_the_cloud_pass_will_find():
    block = _blue_noise_block()
    for key in ("loaded", "path", "resource_created_here", "default_stand_in", "resource",
                "size_x", "size_y", "cloud_march_jittered", "basis"):
        assert f'TEXT("{key}")' in block, key
    assert 'BeautyPath->SetObjectField(TEXT("blue_noise"), BlueNoise);' in block
    # not ready is a warning on the log, never a silent default (UE_LOG takes a
    # compile-time verbosity, so the two states are two calls)
    ready = block.index("if (bBlueNoiseReady)\n")
    assert "UE_LOG(LogFlightSimRender, Display," in block[ready:]
    assert "UE_LOG(LogFlightSimRender, Warning," in block[block.index("else", ready):]
    assert "slice banding" in block


# -- beauty only, measure byte-identical -----------------------------------------

def test_the_load_runs_only_inside_the_beauty_gate():
    block = _blue_noise_block()
    gate = block.index("if (BeautyPath.IsValid())")
    assert gate < block.index("GEngine->LoadBlueNoiseTexture(true);")
    # BeautyPath is allocated under "if (bVisual && bBeauty)" alone
    alloc = COMMANDLET.index("BeautyPath = MakeShared<FJsonObject>();")
    assert COMMANDLET.rindex("if (bVisual && bBeauty)", 0, alloc) > COMMANDLET.rindex(
        "TSharedPtr<FJsonObject> BeautyPath;", 0, alloc)
    # the only LoadBlueNoiseTexture call in the plugin is this one
    plugin_calls = sum(text.count("LoadBlueNoiseTexture(")
                       for text in (p.read_text(encoding="utf-8") for p in PRIVATE.glob("*.cpp")))
    assert plugin_calls == 1


def test_the_commandlet_includes_the_texture_header_it_calls_into():
    assert '#include "Engine/Texture2D.h"' in COMMANDLET
    assert '#include "TextureResource.h"' in COMMANDLET
    assert '#include "AssetCompilingManager.h"' in COMMANDLET


# -- no march cost: the constrained row is ef361bd6's, untouched -----------------

def test_the_constrained_gpu_march_did_not_move():
    """The fix is a texture bind, never a sample: the Intel iGPU's row stays
    the one that rendered (a8c964fc's rise deadlocked it, bisected)."""
    assert world_beauty.CLOUD_MARCH["integrated"] == {
        "view_sample_count_scale": 2.0, "shadow_sample_count_scale": 1.0, "tracing_max_distance_km": 80.0}
    assert world_beauty.CLOUD_SHADOW_CONSTRAINED_KM == 15.0
    rows = re.search(r"static const double Rows\[MarchCount\]\[MarchFieldCount\] = \{(.*?)\};", CLOUDS, re.S)
    constrained = re.search(r"\{([\d., ]+)\},\s*// constrained", rows.group(1)).group(1)
    assert [float(v) for v in constrained.split(",")] == [2.0, 1.0, 80.0]
    assert "constexpr double CloudShadowConstrainedKm = 15.0;" in CLOUDS
    assert "return GRHIDeviceIsIntegrated || GMaxRHIFeatureLevel < ERHIFeatureLevel::SM6;" in CLOUDS
    # the commandlet's cloud cvars are the round-2 set: no sample-count cvar was added
    beauty = COMMANDLET[COMMANDLET.index("TSharedPtr<FJsonObject> BeautyPath;"):
                        COMMANDLET.index('AntiAliasingMethod = ReadCvar(TEXT("r.AntiAliasingMethod"));')]
    cloud_cvars = sorted(set(re.findall(r'SetBeautyCvar\(TEXT\("(r\.Volumetric[^"]+)"\)', beauty)))
    assert cloud_cvars == ["r.VolumetricCloud", "r.VolumetricCloud.HighQualityAerialPerspective",
                           "r.VolumetricRenderTarget.Mode"]


def test_the_march_record_no_longer_claims_the_jitter_unconditionally():
    assert "ONLY once the commandlet has loaded and built the blue-noise textures" in CLOUDS
    assert "render_settings.beauty_path.blue_noise" in CLOUDS
    assert "cloud_march_jittered" in world_beauty.__doc__ or "cloud_march_jittered" in (
        ROOT / "core/scene/world_beauty.py").read_text(encoding="utf-8")


# -- the engine lines this rests on ----------------------------------------------

def test_the_bridge_api_check_pins_the_engine_lines():
    for label in ("UEngine::LoadBlueNoiseTexture", "renderer loads blue noise lazily",
                  "commandlet gets the blue-noise dummy", "blue-noise dummy is 1x1",
                  "cloud march starts at a blue-noise offset", "cloud shadow march is unjittered",
                  "a building texture is a default stand-in",
                  "mode 3 composes the trace with no reconstruction"):
        assert f'rp_check "{label}"' in CHECK, label


@pytest.mark.skipif(not ENGINE.exists(), reason="the engine install is not on this machine")
def test_the_engine_source_still_reads_as_the_fix_assumes():
    """Each fixed string the bridge check greps for, read here too, with the
    structural facts the check cannot express: the lazy load sits in the
    FSceneRenderer constructor (so a scene-capture-only commandlet reaches it
    only inside its first capture), and the dummy fallback is the else of the
    both-textures-have-a-resource test."""
    for label, rel, needle in re.findall(r'^rp_check "([^"]+)" "([^"]+)" "(.*)"$', CHECK, re.M):
        if "blue" not in label.lower() and "stand-in" not in label and "mode 3" not in label \
                and "cloud march" not in label and "cloud shadow march" not in label:
            continue
        path = ENGINE / "Source/Runtime" / rel
        assert path.exists(), (label, rel)
        assert needle.replace('\\"', '"') in path.read_text(encoding="utf-8", errors="replace"), label
    scene = (ENGINE / "Source/Runtime/Renderer/Private/SceneRendering.cpp").read_text(
        encoding="utf-8", errors="replace")
    ctor = scene.index("FSceneRenderer::FSceneRenderer(const FSceneViewFamily* InViewFamily, FHitProxyConsumer* HitProxyConsumer)")
    load = scene.index("GEngine->LoadBlueNoiseTexture(LoadVector2BlueNoiseTexture);")
    assert ctor < load < scene.index("\n}\n", ctor)
    noise = (ENGINE / "Source/Runtime/Renderer/Private/BlueNoise.cpp").read_text(encoding="utf-8", errors="replace")
    body = noise[noise.index("FBlueNoise GetBlueNoiseGlobalParameters()"):]
    body = body[:body.index("\n}\n")]
    assert "GEngine->BlueNoiseScalarTexture->GetResource() != nullptr" in body
    assert "GEngine->BlueNoiseVec2Texture->GetResource() != nullptr" in body
    assert body.index("ensure(IsRunningCommandlet() && IsAllowCommandletRendering());") < body.index(
        "Out.BlueNoise = GetBlueNoiseDummyParameters();")


# -- why slices: the engine's step is the slab path over the count --------------

def test_the_march_samples_a_layer_in_altitude_slices_whatever_the_pixel():
    """VolumetricCloud.usf: StepT = (TMax - TMin) / StepCount along the ray,
    with TMin/TMax the slab intersections, so sample k's altitude above the
    base is (k + jitter) x thickness / N for any elevation that exits through
    the top: the slices are horizontal planes, and a constant jitter puts the
    same planes under every pixel (the strata of round 3). The jittered march
    spreads them over the slice."""
    import math
    thickness_m = 3000.0
    for elevation_deg in (12.0, 30.0, 60.0, 85.0):
        sin_e = math.sin(math.radians(elevation_deg))
        path_m = thickness_m / sin_e
        n = max(2, int(192 * min(path_m / 15000.0, 1.0)))   # the constrained row's 192, 15 km rule
        step_m = path_m / n
        altitudes = [((k + 0.0) * step_m) * sin_e for k in range(n)]
        assert altitudes[1] - altitudes[0] == pytest.approx(thickness_m / n)
        # with a per-pixel offset the k-th sample spreads over the whole slice
        spread = [((k + xi) * step_m) * sin_e for k in (0,) for xi in (0.0, 0.25, 0.5, 0.75, 0.999)]
        assert spread[-1] - spread[0] == pytest.approx(0.999 * thickness_m / n)
    # and at this extinction a slice is opaque, so its boundary is the frame's
    for elevation_deg, cloud in ((60.0, "cumulus"), (30.0, "overcast")):
        sin_e = math.sin(math.radians(elevation_deg))
        path_m = thickness_m / sin_e
        n = max(2, int(192 * min(path_m / 15000.0, 1.0)))
        optical_depth = world_beauty.CLOUDS[cloud]["extinction_per_m"] * path_m / n
        assert optical_depth > 1.5, (cloud, optical_depth)
