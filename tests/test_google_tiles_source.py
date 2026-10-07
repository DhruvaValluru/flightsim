"""Google Photorealistic 3D Tiles (FlightSimGoogleTiles.*): the wiring that
must hold without an engine to run it.

* the Cesium plugin stays OPTIONAL -- a machine without it builds and
  renders exactly as before, and asking for the tiles refuses by name;
* the API key is read from the environment and never written into
  render.json;
* every frame waits for its own view's tiles BEFORE any capture, so the
  beauty, ID and depth passes see the same ground.
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge"
SOURCE = BRIDGE / "Source" / "FlightSimBridge"
TILES_CPP = (SOURCE / "Private" / "FlightSimGoogleTiles.cpp").read_text(encoding="utf-8")
COMMANDLET = (SOURCE / "Private" / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
SCENE = (SOURCE / "Private" / "FlightSimVisualScene.cpp").read_text(encoding="utf-8")
BUILD = (SOURCE / "FlightSimBridge.Build.cs").read_text(encoding="utf-8")


def test_the_cesium_plugin_is_optional_everywhere():
    for path in (REPO / "ue" / "FlightSim.uproject", BRIDGE / "FlightSimBridge.uplugin"):
        plugins = json.loads(path.read_text(encoding="utf-8"))["Plugins"]
        cesium = [p for p in plugins if p["Name"] == "CesiumForUnreal"]
        assert cesium and cesium[0].get("Optional") is True, path
    assert 'PublicDependencyModuleNames.Add("CesiumRuntime")' in BUILD
    assert 'PublicDefinitions.Add("WITH_FLIGHTSIM_CESIUM=" + (bCesium ? "1" : "0"))' in BUILD
    assert "#if WITH_FLIGHTSIM_CESIUM" in TILES_CPP
    # Without the plugin, asking refuses by name instead of rendering old ground.
    assert "this build has no Cesium" in TILES_CPP


def test_the_key_comes_from_the_environment_and_is_never_recorded():
    assert 'GetEnvironmentVariable(TEXT("GOOGLE_MAPS_API_KEY"))' in TILES_CPP
    assert 'GetEnvironmentVariable(TEXT("CESIUM_ION_TOKEN"))' in TILES_CPP
    record = TILES_CPP[TILES_CPP.index("FFlightSimGoogleTiles::Record()"):]
    assert "*Key" not in record and "IonToken" not in record
    assert 'SetStringField(TEXT("url"), GoogleTilesRootUrl)' in record


def test_each_frame_loads_its_tiles_before_any_capture():
    wait = COMMANDLET.index("GoogleTiles.WaitForView(")
    velocity = COMMANDLET.index("// I6: the velocity pass renders FIRST")
    beauty = COMMANDLET.index("		Capture->CaptureScene();\n		FlushRenderingCommands();\n\n")
    assert wait < velocity < beauty
    assert COMMANDLET.index("GoogleTiles.Enable(") < COMMANDLET.index(
        "TMap<int32, int32> StencilCounts;")   # tiles exist before the label groups


def test_only_the_scenes_own_ground_is_hidden():
    assert SCENE.count('Tags.Add(FName(TEXT("FlightSim.terrain")))') == 4
    assert 'ActorHasTag(FName(TerrainTag))' in TILES_CPP
    assert 'TerrainTag = TEXT("FlightSim.terrain")' in TILES_CPP
