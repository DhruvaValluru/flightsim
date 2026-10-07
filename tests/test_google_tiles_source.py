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


# -- the geoid undulation the tiles are placed with ---------------------------

def test_a_tiles_card_carries_the_geoid_undulation_at_its_origin(tmp_path, monkeypatch):
    """A flat or synthesised scene's datum has no undulation (null), but the
    tiles are real Earth: the card evaluates N at the origin itself, so
    Cesium's origin sits at terrain_elevation_m + N, not N metres low."""
    from experiments.gate5_ue_parity import reference_spec, write_run_card
    from core.terrain.geoid import grid_for_model

    spec = reference_spec("fly the 747 at 3000 m and 250 kt for 30 seconds")
    monkeypatch.delenv("FLIGHTSIM_GOOGLE_TILES", raising=False)
    plain = json.loads(write_run_card(spec, tmp_path / "plain.json").read_text(encoding="utf-8"))
    assert "google_tiles" not in plain

    monkeypatch.setenv("FLIGHTSIM_GOOGLE_TILES", "on")
    card = json.loads(write_run_card(spec, tmp_path / "card.json").read_text(encoding="utf-8"))
    block = card["google_tiles"]
    grid = grid_for_model("auto")
    assert block["geoid_model"] == grid.model_key
    assert block["geoid_undulation_m"] == grid.undulation(card["latitude_deg"], card["longitude_deg"])
    assert set(card) - set(plain) == {"google_tiles"}


def test_the_matterhorn_undulation_is_about_52_m():
    from core.scenario.card import google_tiles_card_block

    block = google_tiles_card_block(45.9763, 7.6586)
    assert 50.0 < block["geoid_undulation_m"] < 55.0


def test_the_commandlet_falls_back_to_the_cards_undulation_and_never_to_zero():
    enable = COMMANDLET[COMMANDLET.index("if (FFlightSimGoogleTiles::Requested())"):]
    enable = enable[:enable.index("GoogleTiles.HideOwnTerrain(World);")]
    assert 'TEXT("undulation_origin_m")' in enable
    assert 'TEXT("google_tiles")' in enable and 'TEXT("geoid_undulation_m")' in enable
    assert "google_tiles.undulation_missing" in enable
    assert enable.index("google_tiles.undulation_missing") < enable.index("GoogleTiles.Enable(")
