"""W5 -- the world engine side, pinned by reading the source (no engine here).

The FlightSimBridgeEditor module (ImportLandscape from W1's import
manifest, BuildNanite, the sha256 tag, the refusals by name), the scene
script's plain half (run here on a fixture bake), the -scene= route of the
render commandlet with the land-cover ID pass and the primitive-component
stencil loop, the read-backs, FlightSimVisualScene's scene load with the sha
check, the moon, the starfield, the beauty-only rain and the drift per tick,
world_applied, the -scene= flag emitted only when asked, the verifier's
check.world_record and the catalogue entries.

Not verified here: that any of the C++ or editor Python compiles or runs;
every clause below is a consistency pin of the source, and the first
Windows build and run (docs/PHASE2_REPORT.md, the Windows order, step 10)
is the verification.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source"
BRIDGE = SOURCE / "FlightSimBridge"
EDITOR = SOURCE / "FlightSimBridgeEditor"
COMMANDLET = (BRIDGE / "Private" / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
SCENE_CPP = (BRIDGE / "Private" / "FlightSimVisualScene.cpp").read_text(encoding="utf-8")
SCENE_H = (BRIDGE / "Public" / "FlightSimVisualScene.h").read_text(encoding="utf-8")
IMPORTER_CPP = (EDITOR / "Private" / "FlightSimLandscapeImporter.cpp").read_text(encoding="utf-8")
IMPORTER_H = (EDITOR / "Public" / "FlightSimLandscapeImporter.h").read_text(encoding="utf-8")
BUILD_SCENE = REPO / "scripts" / "ue_build_scene.py"


def _load_build_scene():
    spec = importlib.util.spec_from_file_location("ue_build_scene", BUILD_SCENE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scene_script = _load_build_scene()


def _function(text: str, signature: str) -> str:
    """The body of one C++ function, from its signature to the next
    top-level closing brace."""
    start = text.index(signature)
    end = text.index("\n}\n", start)
    return text[start:end]


# -- the editor module -------------------------------------------------------------

def test_the_editor_module_is_registered_and_depends_on_what_it_uses():
    plugin = json.loads((REPO / "ue" / "Plugins" / "FlightSimBridge" /
                         "FlightSimBridge.uplugin").read_text(encoding="utf-8"))
    modules = {m["Name"]: m for m in plugin["Modules"]}
    assert modules["FlightSimBridgeEditor"]["Type"] == "Editor"
    assert modules["FlightSimBridge"]["Type"] == "Runtime"
    build = (EDITOR / "FlightSimBridgeEditor.Build.cs").read_text(encoding="utf-8")
    for dependency in ('"Landscape"', '"UnrealEd"', '"AssetRegistry"', '"FlightSimBridge"'):
        assert dependency in build, dependency
    assert "IMPLEMENT_MODULE(FDefaultModuleImpl, FlightSimBridgeEditor)" in (
        EDITOR / "Private" / "FlightSimBridgeEditorModule.cpp").read_text(encoding="utf-8")
    runtime = (BRIDGE / "FlightSimBridge.Build.cs").read_text(encoding="utf-8")
    assert '"Landscape",' in runtime
    project = json.loads((REPO / "ue" / "FlightSim.uproject").read_text(encoding="utf-8"))
    enabled = {p["Name"] for p in project["Plugins"] if p.get("Enabled")}
    assert {"PCG", "GeometryScripting", "FlightSimBridge", "GeoReferencing"} <= enabled


def test_import_landscape_reads_the_manifest_and_refuses_by_name():
    body = _function(IMPORTER_CPP, "ALandscape* UFlightSimLandscapeImporter::ImportLandscape(")
    # The three refusals, each by name, each in the log and the report.
    for name in ("terrain.landscape_missing", "terrain.landscape_stale",
                 "terrain.landscape_layout"):
        assert f'TEXT("{name}: ' in body, name
    assert "UE_LOG(LogFlightSimWorld, Error" in body
    # What it reads: the datum block, the bake's sha256 (against the scene's),
    # the layout, the scale, the heightmap beside the manifest, every layer's
    # digest.
    for key in ('TEXT("datum")', 'TEXT("undulation_m")', 'TEXT("vertical_datum_of_heights")',
                'TEXT("bake")', 'TEXT("weight_layers")', 'TEXT("quads_per_section")',
                'TEXT("sections_per_component")', 'TEXT("components")', 'TEXT("scale")'):
        assert key in body, key
    assert "BakeSha.Equals(ExpectedBakeSha256, ESearchCase::IgnoreCase)" in body
    assert 'FPaths::ChangeExtension(ManifestPath, TEXT("r16"))' in body
    assert "EditorSha256Hex(Bytes.GetData(), Bytes.Num())" in body
    # The Import call site (a consistency pin of the 5.5-5.7 signature) and
    # the weight blend.
    assert ("Landscape->Import(FGuid::NewGuid(), 0, 0, Resolution - 1, Resolution - 1,\n"
            "\t                  static_cast<int32>(Sections), static_cast<int32>(Quads),\n"
            "\t                  HeightDataPerLayer, nullptr, MaterialLayerDataPerLayer,\n"
            "\t                  ELandscapeImportAlphamapType::Additive);") in body
    # The height encoding: the actor sits at the height sample 32768 encodes.
    assert "MinElevation + Relief * 32768.0 / 65535.0" in body
    # The rows: north-up (+Y) writes the .r16's row 0 (north) last.
    assert "return bNorthPlusY ? Resolution - 1 - Row : Row;" in IMPORTER_CPP
    assert 'const bool bNorthPlusY = NorthAxis != TEXT("-Y");' in body


def test_the_sha_tag_is_written_by_the_editor_and_read_by_the_render_with_one_prefix():
    body = _function(IMPORTER_CPP, "ALandscape* UFlightSimLandscapeImporter::ImportLandscape(")
    assert "Landscape->Tags.AddUnique(FName(FlightSimWorld::TerrainTag));" in body
    assert "Landscape->Tags.AddUnique(FName(*TerrainSha256Tag(BakeSha)));" in body
    assert "return FString(FlightSimWorld::TerrainSha256TagPrefix) + Sha256.ToLower();" in IMPORTER_CPP
    tags = dict(re.findall(r'inline constexpr const TCHAR\* (\w+) = TEXT\("([^"]+)"\);', SCENE_H))
    assert tags["TerrainTag"] == scene_script.TAG_TERRAIN == "FlightSim.Terrain"
    assert tags["TerrainSha256TagPrefix"] == scene_script.TAG_TERRAIN_SHA256_PREFIX
    assert tags["VegetationTag"] == scene_script.TAG_VEGETATION
    assert tags["BuildingTag"] == scene_script.TAG_BUILDING
    assert tags["RunwayTag"] == scene_script.TAG_RUNWAY
    assert tags["VegetationObjectId"] == "vegetation:all"
    assert tags["BuildingObjectId"] == "building:all"
    load = _function(SCENE_CPP, "bool FFlightSimVisualScene::LoadSceneLevel(")
    assert "Text.StartsWith(FlightSimWorld::TerrainSha256TagPrefix)" in load
    assert "!TagSha.Equals(Terrain.Sha256, ESearchCase::IgnoreCase)" in load


def test_build_nanite_is_a_measured_toggle():
    body = _function(IMPORTER_CPP, "bool UFlightSimLandscapeImporter::BuildNanite(")
    assert 'FindFProperty<FBoolProperty>(ALandscapeProxy::StaticClass(),\n' in body
    assert 'TEXT("bEnableNanite")' in body
    assert "Subsystem->BuildNanite();" in body
    assert "const bool bReadBack = Landscape->IsNaniteEnabled();" in body
    assert "return bReadBack == bEnable;" in body
    assert "UFUNCTION(BlueprintCallable" in IMPORTER_H and "static bool BuildNanite(" in IMPORTER_H


# -- the scene script's plain half, run on a fixture bake ----------------------------

def _fixture(tmp_path):
    """A tiny georeferenced bake with a datum, its Landscape export, two
    weight layers, the import manifest (W1's own writer), and a class map."""
    from PIL import Image

    from core.terrain.heightfield import Georeference, Heightfield
    from core.terrain.landscape import export, import_manifest

    rng = np.random.default_rng(5)
    elevations = 1000.0 + 200.0 * rng.random((16, 20))
    geo = Georeference(crs="EPSG:32632", origin_x_m=400000.0, origin_y_m=5100000.0,
                       pixel_size_m=30.0)
    datum = {"undulation_m": 47.2, "vertical_datum_of_heights": "EGM2008"}
    field = Heightfield.from_elevations(elevations, geo, name="ridge",
                                        provenance={"datum": datum})
    stem = tmp_path / "ridge"
    field.write(stem)
    spec = export(field, tmp_path / "ridge_landscape")
    layout = {"quads_per_section": spec.layout.quads_per_section,
              "sections_per_component": spec.layout.sections_per_component,
              "components": spec.layout.components}
    count = spec.resolution * spec.resolution
    layers = []
    for code, key, value in ((10, "tree_cover", 200), (0, "nodata", 55)):
        path = tmp_path / f"ridge_landcover_{code}.u8"
        path.write_bytes(bytes([value]) * count)
        layers.append({"code": code, "class": "vegetation" if code else "nodata", "key": key,
                       "file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "layout": layout, "resolution": spec.resolution})
    import_manifest(field, spec, layers)
    cover = tmp_path / "ridge_landcover"
    cover.mkdir()
    Image.fromarray(np.full((16, 20), 10, dtype=np.uint8), mode="L").save(cover / "class_map.png")
    (cover / "landcover.json").write_text(json.dumps({"class_map": {
        "file": "class_map.png",
        "sha256": hashlib.sha256((cover / "class_map.png").read_bytes()).hexdigest()}}),
        encoding="utf-8")
    return stem, field


def test_the_scene_script_checks_what_the_editor_will_read(tmp_path):
    stem, field = _fixture(tmp_path)
    bake = scene_script.read_bake(stem)
    assert bake["sha256"] == field.digest()
    manifest = scene_script.check_manifest(scene_script.manifest_path_for(stem), bake["sha256"])
    assert len(manifest["weight_layers"]) == 2
    class_map = scene_script.check_class_map(stem)
    assert class_map["sha256"] == hashlib.sha256(
        (tmp_path / "ridge_landcover" / "class_map.png").read_bytes()).hexdigest()

    def refused(call):
        with pytest.raises(scene_script.SceneError) as info:
            call()
        return info.value.constraint

    manifest_path = scene_script.manifest_path_for(stem)
    # Another bake's sha256: stale.
    assert refused(lambda: scene_script.check_manifest(manifest_path, "0" * 64)) == \
        "terrain.landscape_stale"
    # A layer file that changed after export: stale.
    layer = tmp_path / "ridge_landcover_10.u8"
    original = layer.read_bytes()
    layer.write_bytes(bytes([199]) + original[1:])
    assert refused(lambda: scene_script.check_manifest(manifest_path, bake["sha256"])) == \
        "terrain.landscape_stale"
    layer.write_bytes(original)
    # A layer of another layout: layout; a manifest without its datum: missing.
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    broken = dict(data, weight_layers=[dict(data["weight_layers"][0], resolution=9)])
    manifest_path.write_text(json.dumps(broken), encoding="utf-8")
    assert refused(lambda: scene_script.check_manifest(manifest_path, bake["sha256"])) == \
        "terrain.landscape_layout"
    manifest_path.write_text(json.dumps({k: v for k, v in data.items() if k != "datum"}),
                             encoding="utf-8")
    assert refused(lambda: scene_script.check_manifest(manifest_path, bake["sha256"])) == \
        "terrain.landscape_missing"
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    assert refused(lambda: scene_script.check_manifest(tmp_path / "absent.json", "x")) == \
        "terrain.landscape_missing"
    # A class map that is not the recorded one: terrain.landcover.
    (tmp_path / "ridge_landcover" / "class_map.png").write_bytes(b"not a png")
    assert refused(lambda: scene_script.check_class_map(stem)) == "terrain.landcover"
    # A bake whose samples are not its sidecar's sha256: stale.
    raw = stem.with_suffix(".r16")
    raw.write_bytes(b"\x00\x00" + raw.read_bytes()[2:])
    assert refused(lambda: scene_script.read_bake(stem)) == "terrain.landscape_stale"


def test_the_scene_document_and_the_card_members(tmp_path):
    stem, field = _fixture(tmp_path)
    bake = scene_script.read_bake(stem)
    manifest = scene_script.check_manifest(scene_script.manifest_path_for(stem), bake["sha256"])
    class_map = scene_script.check_class_map(stem)
    document = scene_script.scene_document(stem, manifest, bake, "+Y", True, class_map)
    assert tuple(document) == scene_script.DOCUMENT_KEYS
    assert document["scene_level"] == "/Game/FlightSim/Scenes/ridge/L_ridge"
    assert document["terrain_sha256"] == field.digest()
    assert document["landscape"]["tags"] == ["FlightSim.Terrain",
                                             "FlightSim.TerrainSha256=" + field.digest()]
    assert document["datum"] == {"undulation_m": 47.2, "vertical_datum_of_heights": "EGM2008"}
    assert [layer["code"] for layer in document["layers"]] == [10, 0]
    assert document["class_map"]["asset"] == \
        "/Game/FlightSim/Scenes/ridge/T_ridge_ClassMap.T_ridge_ClassMap"
    assert (document["class_map"]["width"], document["class_map"]["height"]) == (20, 16)
    for name in ("bake", "landscape_manifest", "landscape_heightmap", "landcover"):
        entry = document["sidecars"][name]
        assert entry["sha256"] == hashlib.sha256(Path(entry["file"]).read_bytes()).hexdigest()
    # North-up rows: the Landscape's first sample is the bake's south-west one.
    assert document["landscape_origin_xy"] == [400000.0, 5100000.0 - 15 * 30.0]
    assert scene_script.landscape_origin_xy(bake, "-Y") == [400000.0, 5100000.0]
    assert scene_script.to_level_cm(400030.0, 5099580.0, 1200.0, document["landscape_origin_xy"],
                                    "+Y") == [3000.0, 3000.0, 120000.0]
    assert scene_script.to_level_cm(400030.0, 5099970.0, 0.0, [400000.0, 5100000.0],
                                    "-Y") == [3000.0, 3000.0, 0.0]
    # The card's world members: what LoadSceneLevel matches.
    members = scene_script.world_card_members(document)
    assert set(members) == {"scene_level", "terrain_sha256", "sidecars", "layers"}
    assert members["layers"] == [{"code": 10, "sha256": manifest["weight_layers"][0]["sha256"]},
                                 {"code": 0, "sha256": manifest["weight_layers"][1]["sha256"]}]
    load = _function(SCENE_CPP, "bool FFlightSimVisualScene::LoadSceneLevel(")
    for key in ("scene_level", "terrain_sha256", "sidecars", "layers", "north_axis",
                "landscape_origin_xy", "class_map", "vegetation", "biome_graph", "instances"):
        assert f'TEXT("{key}")' in load, key
    with pytest.raises(ValueError):
        scene_script.scene_document(stem, manifest, bake, "+X", True)
    # The document the render reads is ASCII (gotcha 13).
    path = scene_script.write_scene_document(document, tmp_path / "ridge_scene.json")
    path.read_bytes().decode("ascii")
    # The capture command's --scene: the same members reach the card's world
    # block, and a missing document or bake refuses world.scene_missing.
    from flightsim import capture

    assert capture._scene_members(path, stem) == members
    assert capture._with_scene({"terrain": str(stem)}, members) == {"terrain": str(stem), **members}
    assert capture._with_scene(None, members) is None
    for missing in (capture._scene_members(tmp_path / "none.json", stem),
                    capture._scene_members(path, None)):
        assert [v.constraint for v in missing["violations"]] == ["world.scene_missing"]


def test_the_scene_script_is_plain_python_until_the_editor_half():
    text = BUILD_SCENE.read_text(encoding="utf-8")
    top = text[:text.index("# -- the editor half")]
    assert "import unreal" not in top
    editor = text[text.index("def build_in_editor"):]
    assert "import unreal" in editor
    assert "unreal.FlightSimLandscapeImporter.import_landscape(" in editor
    assert "unreal.FlightSimLandscapeImporter.build_nanite(" in editor
    assert 'print(f"REFUSED -- {exc.constraint}: {exc.message}")' in text
    # The class map is imported as data: linear, nearest, no mips.
    assert "linear=True, nearest=True)" in editor
    helper = text[text.index("def _import_texture"):text.index("def _material_instance")]
    for setting in ('"srgb", False', "TF_NEAREST", "TMGS_NO_MIPMAPS", '"never_stream", True'):
        assert setting in helper, setting
    # Every refusal name the script prints is catalogued.
    from core.messages import is_catalogued

    for name in set(re.findall(r'SceneError\(\s*"([a-z_.]+)"', text)):
        assert is_catalogued(name), name


# -- the render commandlet: -scene=, the land-cover pass, the stencil loop -------------

def test_the_commandlet_takes_scene_and_refuses_it_off_the_georeferenced_scene():
    assert 'FParse::Value(*Params, TEXT("scene="), ScenePath);' in COMMANDLET
    assert "[-scene=<scene document>]" in COMMANDLET
    assert "if (!ScenePath.IsEmpty() && !(bVisual && bGeorefTerrain))" in COMMANDLET
    assert 'TEXT("world.scene_missing: -scene=%s loads a Landscape' in COMMANDLET
    assert "SceneOptions.SceneDocumentPath = ScenePath;" in COMMANDLET
    assert "SceneOptions.Card = WorldCardRoot;" in COMMANDLET
    # The scene level replaces the procedural tiles on the georeferenced route.
    assert ("if (SceneDocument.IsValid() ? !LoadSceneLevel(World, Options, Error)\n"
            "\t\t                            : !BuildGeoreferencedTerrain(World, Options, Error))") \
        in SCENE_CPP


def test_the_stencil_loop_runs_over_primitive_components_with_the_aggregates():
    start = COMMANDLET.index("TMap<int32, int32> StencilCounts;")
    loop = COMMANDLET[start:COMMANDLET.index("UMaterialInterface* StencilMaterial", start)]
    assert "TInlineComponentArray<UPrimitiveComponent*> Primitives;" in loop
    assert "UMeshComponent" not in loop
    assert "Primitive->SetRenderCustomDepth(true);" in loop
    assert "Primitive->SetCustomDepthStencilValue(IntId);" in loop
    assert "It->ActorHasTag(FName(FlightSimWorld::VegetationTag))" in loop
    assert "It->ActorHasTag(FName(FlightSimWorld::BuildingTag))" in loop
    assert "if (VisualScene.BeautyOnlyActors.Contains(*It))" in loop
    assert 'TEXT("annotation.identity: the scene level carries' in loop
    ids = COMMANDLET[COMMANDLET.index("int32 LabelVegetationIntId = 0;"):start]
    assert "Entry.Id == FlightSimWorld::VegetationObjectId" in ids
    assert "Entry.Id == FlightSimWorld::BuildingObjectId" in ids


def test_the_land_cover_id_pass_writes_the_key_the_python_side_reads():
    from core.capture.labels import ENGINE_LANDCOVER_KEY, LANDCOVER_SUFFIX

    assert ENGINE_LANDCOVER_KEY == "landcover_png"
    assert f'Labels->SetStringField(TEXT("{ENGINE_LANDCOVER_KEY}"), LandcoverName);' in COMMANDLET
    assert 'const FString LandcoverName = Stem + TEXT("_landcover_id.png");' in COMMANDLET
    assert "_landcover_id.png" != LANDCOVER_SUFFIX     # never over the Python image
    assert ('constexpr const TCHAR* RenderLandcoverMaterialPath =\n'
            '\t\tTEXT("/Game/FlightSim/M_LandcoverID.M_LandcoverID");') in COMMANDLET
    block = COMMANDLET[COMMANDLET.index("if (bLandcoverAsked)"):]
    block = block[:block.index("LabelLandcover->RegisterComponent();")]
    assert 'TEXT("labels.landcover_pass: the scene carries land cover' in block
    assert "ConfigureLabelCapture(LabelLandcover);" in block
    assert "LabelLandcover->CaptureSource = ESceneCaptureSource::SCS_FinalColorHDR;" in block
    assert "LandcoverTarget->RenderTargetFormat = RTF_R32f;" in block
    assert 'SetScalarParameterValue(TEXT("TerrainStencil"), static_cast<float>(LabelTerrainIntId))' in block
    # The registration is MEASURED at load through the georeferencing.
    load = _function(SCENE_CPP, "bool FFlightSimVisualScene::LoadSceneLevel(")
    assert "Landcover.CellXCm = OneEast.X - NorthWest.X;" in load
    assert "Landcover.CellYCm = OneSouth.Y - NorthWest.Y;" in load
    assert "FVector(Terrain.OriginXMetres, Terrain.OriginYMetres - Pixel, 0.0), OneSouth);" in load


def test_the_world_read_backs_are_read_back_by_name():
    names = COMMANDLET[COMMANDLET.index("const TCHAR* const ConsoleNames[] = {"):]
    names = names[:names.index("};")]
    for cvar in ("landscape.RenderNanite", "r.VirtualTextures", "r.MegaLights", "r.Substrate"):
        assert f'TEXT("{cvar}")' in names, cvar
    from core.capture.verify import WORLD_READBACK_CVARS

    assert WORLD_READBACK_CVARS == ("landscape.RenderNanite", "r.VirtualTextures",
                                    "r.MegaLights", "r.Substrate")
    load = _function(SCENE_CPP, "bool FFlightSimVisualScene::LoadSceneLevel(")
    assert 'Component->GetClass()->GetName() == TEXT("PCGComponent")' in load
    assert "VegetationInstances += Instanced->GetInstanceCount();" in load
    assert 'VegetationRow->SetNumberField(TEXT("pcg_components"), PcgComponents);' in load
    assert 'Row->SetBoolField(TEXT("nanite_enabled"), SceneLandscape->IsNaniteEnabled());' in load
    ini = (REPO / "ue" / "Config" / "DefaultEngine.ini").read_text(encoding="utf-8")
    assert "\nr.VirtualTextures=True\n" in ini
    assert "\n[SystemSettings]\n" in ini and "\nlandscape.RenderNanite=1\n" in ini
    assert "\nr.MegaLights.EnableForProject=False\n" in ini


def test_the_physics_environment_report_is_called_before_environment_is_written():
    call = "Scenario.AppendEnvironmentReport(Card, Environment);"
    assert COMMANDLET.count(call) == 1
    assert COMMANDLET.index(call) < COMMANDLET.index(
        'Root->SetObjectField(TEXT("environment"), Environment);')


# -- the visual scene: the scene load, the moon, the stars, the rain, the drift --------

def test_the_scene_load_checks_the_sha_and_refuses_world_scene_stale():
    load = _function(SCENE_CPP, "bool FFlightSimVisualScene::LoadSceneLevel(")
    assert 'Error = TEXT("world.scene_stale: ") + Why;' in load
    assert "if (!DocSha.Equals(Terrain.Sha256, ESearchCase::IgnoreCase))" in load
    assert "if (!CardSha.IsEmpty() && !CardSha.Equals(DocSha, ESearchCase::IgnoreCase))" in load
    assert "if (!CardLevel.IsEmpty() && CardLevel != SceneLevel)" in load
    assert "if (!bEastPlusX || Measured != NorthAxis)" in load
    assert "ULevelStreamingDynamic::LoadLevelInstance(\n\t\tWorld, SceneLevel, Origin, FRotator::ZeroRotator, bLoaded);" in load
    assert "World->FlushLevelStreaming(EFlushLevelStreamingType::Full);" in load
    for name in ("world.scene_missing", "vegetation.biome_asset", "vegetation.count_mismatch"):
        assert f'TEXT("{name}: ' in load, name
    assert 'Row->SetStringField(TEXT("sha256_tag"), TagSha);' in load
    assert 'Row->SetBoolField(TEXT("matched"), true);' in load


def test_the_moon_is_the_second_directional_light_in_lux():
    look = _function(SCENE_CPP, "bool FFlightSimVisualScene::BuildWorldLook(")
    assert "Moon = World->SpawnActor<ADirectionalLight>();" in look
    assert "MoonLight->SetAtmosphereSunLight(true);" in look
    assert "MoonLight->SetAtmosphereSunLightIndex(1);" in look
    assert "MoonLight->SetIntensity(static_cast<float>(MoonLux));" in look
    assert "Moon->SetActorRotation(MoonRotation(MoonElevation, MoonAzimuth));" in look
    assert 'TEXT("night.sun_units: the moon' in look and 'TEXT("look.moon: ' in look
    assert 'MoonLight->GetAtmosphereSunLightIndex());' in look
    # The rotation is the sun's convention (randomization.engine_sun_azimuth).
    assert "return FRotator(-ElevationDeg, (90.0 - CompassAzimuthDeg) + 180.0, 0.0);" in SCENE_CPP
    from core.scenario.randomization import engine_sun_azimuth

    for azimuth in (0.0, 37.5, 180.0, 301.0):
        assert ((90.0 - azimuth) + 180.0) % 360.0 == pytest.approx(
            (engine_sun_azimuth(azimuth) + 180.0) % 360.0)
    # Every look.night card key is required (night.CARD_KEYS).
    from core.scene.night import CARD_KEYS

    for key in CARD_KEYS:
        assert f'TEXT("{key}")' in look, key


def test_the_starfield_is_the_cataloguechecked_sky_hidden_from_the_labels():
    from core.scene import night

    assert f'SceneStarCatalogueSha256 =\n\t\tTEXT("{night.CATALOGUE_SHA256}");' in SCENE_CPP
    for cpp, value in (("SceneStarProceduralCount", night.PROCEDURAL_COUNT),
                       ("SceneStarLimitingMag", night.STAR_LIMITING_MAG),
                       ("SceneStarBrightestMag", night.STAR_BRIGHTEST_MAG),
                       ("SceneStarProceduralSlope", night.PROCEDURAL_SLOPE)):
        match = re.search(rf"constexpr (?:int32|double) {cpp} = ([-0-9.]+);", SCENE_CPP)
        assert match and float(match.group(1)) == float(value), cpp
    stars = _function(SCENE_CPP, "UTexture2D* FFlightSimVisualScene::BuildStarTexture(")
    assert 'TEXT("look.stars: the cached star catalogue' in stars
    assert "SceneSha256Hex(Bytes.GetData(), Bytes.Num())" in stars
    look = _function(SCENE_CPP, "bool FFlightSimVisualScene::BuildWorldLook(")
    assert "BeautyOnlyActors.Add(Starfield);" in look
    assert "Starfield->SetActorRotation(StarfieldRotation(LatitudeDeg, SiderealDeg));" in look
    assert "Label->HiddenActors.Append(VisualScene.BeautyOnlyActors);" in COMMANDLET
    # The rotation: local Z the pole at the latitude, local X RA 0h.
    assert "const FVector Pole(0.0, FMath::Cos(Lat), FMath::Sin(Lat));" in SCENE_CPP
    assert "return FQuat(FMatrix(RaZero, RaSix, Pole, FVector::ZeroVector));" in SCENE_CPP
    # The same axes, evaluated here: right-handed, the pole at the latitude.
    lat, theta = np.radians(46.0), np.radians(75.0)
    pole = np.array([0.0, np.cos(lat), np.sin(lat)])
    meridian = np.array([0.0, -np.sin(lat), np.cos(lat)])
    west = np.array([-1.0, 0.0, 0.0])
    ra0 = meridian * np.cos(theta) + west * np.sin(theta)
    ra6 = meridian * np.sin(theta) - west * np.cos(theta)
    assert np.allclose(np.cross(ra0, ra6), pole)
    assert np.degrees(np.arcsin(pole[2])) == pytest.approx(46.0)


def test_the_rain_is_on_the_beauty_capture_only():
    rain = _function(SCENE_CPP, "bool FFlightSimVisualScene::ApplyRainToBeauty(")
    assert ("Beauty->PostProcessSettings.WeightedBlendables.Array.Add(FWeightedBlendable(1.0f, "
            "RainInstance));") in rain
    assert 'TEXT("look.precipitation_particles: ' in rain
    assert 'Row->SetStringField(TEXT("applied_to"), TEXT("beauty"));' in rain
    # The commandlet hands it the beauty capture, once, and nothing else.
    assert COMMANDLET.count("VisualScene.ApplyRainToBeauty(") == 1
    assert "VisualScene.ApplyRainToBeauty(Capture, RainCameraId, Error)" in COMMANDLET
    assert "RainInstance" not in COMMANDLET
    # The label captures' configuration adds no blendable of the look.
    configure = COMMANDLET[COMMANDLET.index("auto ConfigureLabelCapture = [&](USceneCaptureComponent2D* Label)"):]
    configure = configure[:configure.index("\t\t};")]
    assert "WeightedBlendables" not in configure


def test_the_cloud_drift_parameter_is_advanced_every_tick_before_the_captures():
    assert 'constexpr const TCHAR* SceneCloudDriftNeedle = TEXT("Wind");' in SCENE_CPP
    advance = _function(SCENE_CPP, "void FFlightSimVisualScene::AdvanceWorld(")
    assert "CloudMaterialInstance->SetVectorParameterValue(CloudDriftParameter," in advance
    assert "CloudDriftOffsetMetres(DriftMps, DriftFromDeg, TimeSeconds)" in advance
    look = _function(SCENE_CPP, "bool FFlightSimVisualScene::BuildWorldLook(")
    assert 'TEXT("look.cloud_drift_parameter: the card asks for' in look
    from core.scene.weather_visuals import CLOUD_DRIFT_KEYS

    for key in CLOUD_DRIFT_KEYS:
        assert f'TEXT("{key}")' in look, key
    # Called in the step loop before the beauty capture of the step.
    loop = COMMANDLET[COMMANDLET.index("for (int32 Step = 0; Step < Steps; ++Step)"):]
    tick = loop.index('VisualScene.AdvanceWorld(Scenario.ReadProperty(TEXT("simulation/sim-time-sec")));')
    assert tick < loop.index("Capture->CaptureScene();")
    # Downwind: FROM 270 (a west wind) moves the clouds east (+X).
    drift = _function(SCENE_CPP, "FVector FFlightSimVisualScene::CloudDriftOffsetMetres(")
    assert "FMath::DegreesToRadians(FromDeg + 180.0)" in drift
    assert "FVector(Distance * FMath::Sin(Toward), Distance * FMath::Cos(Toward), 0.0)" in drift


def test_world_applied_carries_the_ten_keys_the_verifier_grades():
    from core.capture.verify import WORLD_APPLIED_KEYS

    build = _function(SCENE_CPP, "bool FFlightSimVisualScene::Build(")
    for key in WORLD_APPLIED_KEYS[:-1]:
        assert f'TEXT("{key}")' in build, key
    assert 'WorldApplied->SetObjectField(TEXT("materials"), Materials);' in build
    assert 'Root->SetObjectField(TEXT("world_applied"), WorldRecord);' in COMMANDLET
    assert "if (bVisual && bWorldAsked && VisualScene.WorldApplied.IsValid())" in COMMANDLET


# -- the flag, the verifier, the catalogue ---------------------------------------------

def test_scene_is_emitted_only_when_asked_right_after_imagery():
    from core.render.flags import SCENE_PREFIX, render_flags

    def flags(**overrides):
        kwargs = dict(scene={"terrain": "ridge", "imagery": "drape.json"}, mesh=None, look=None,
                      camera_flags=None, width=1280, height=720, fps=30)
        kwargs.update(overrides)
        return render_flags("/abs/card.json", "/abs/frames", **kwargs)

    default = flags()
    assert not [t for t in default if t.startswith(SCENE_PREFIX)]
    assert flags(scene_document=None) == default
    asked = flags(scene_document="/abs/ridge_scene.json")
    assert asked[asked.index("-imagery=drape.json") + 1] == "-scene=/abs/ridge_scene.json"
    assert [t for t in asked if t != "-scene=/abs/ridge_scene.json"] == default
    assert not [t for t in flags(void=True, scene_document="/x.json") if t.startswith(SCENE_PREFIX)]
    # Parity: the web app never asks for it and the CLI only under --scene
    # (None otherwise), so the two still build one default list
    # (tests/test_render_flags.py compares them).
    assert "scene_document" not in (REPO / "webapp" / "runs.py").read_text(encoding="utf-8")
    assert ('scene_document=str(args.scene) if getattr(args, "scene", None) else None'
            in (REPO / "flightsim" / "capture.py").read_text(encoding="utf-8"))


def _world_run(tmp_path, moon_index=1, streak=12.5):
    tmp_path.mkdir(parents=True, exist_ok=True)
    card = {"objects": [{"id": "terrain", "int_id": 2}, {"id": "building:all", "int_id": 3}],
            "world": {"terrain_sha256": "a" * 64},
            "look": {"night": {"moon_elevation_deg": 30.0, "moon_azimuth_deg": 120.0,
                               "phase": 0.8, "illuminance_lux": 0.2, "stars_mode": "procedural",
                               "sun_units": "physical"},
                     "precipitation": {"streak_px": {"cam0": {"relative_px": 12.5}}},
                     "cloud_drift": {"mps": 4.0, "from_deg": 270.0, "base_m": 1500.0,
                                     "source": "wind at cloud base"}}}
    (tmp_path / "card.json").write_text(json.dumps(card), encoding="utf-8")
    folder = tmp_path / "frames" / "cam0"
    folder.mkdir(parents=True)
    (folder / "frame_0000_landcover_id.png").write_bytes(b"png")
    world = {key: {"asked": False, "drawn": False} for key in (
        "imagery", "vegetation", "runway")}
    world.update({
        "landscape": {"asked": True, "drawn": True, "sha256_tag": "a" * 64,
                      "bake_sha256": "a" * 64, "matched": True, "north_axis_scene": "+Y",
                      "north_axis_measured": "+Y"},
        "land_cover": {"asked": True, "drawn": True},
        "buildings": {"asked": True, "drawn": True, "int_id": 3},
        "night": {"asked": True, "moon": {"drawn": True, "atmosphere_sun_light_index": moon_index,
                                          "intensity_lux": 0.2, "light_units": "physical",
                                          "elevation_deg": 30.0, "azimuth_deg": 120.0},
                  "stars": {"drawn": True, "mode": "procedural", "label_captures": "hidden"}},
        "precipitation": {"asked": True, "drawn": True, "applied_to": "beauty",
                          "streak_length_px": streak},
        "cloud_drift": {"asked": True, "drawn": True, "parameter": "WindOffset", "mps": 4.0,
                        "from_deg": 270.0},
        "materials": {"/Game/FlightSim/M_Landscape.M_Landscape": "loaded"},
    })
    render = {"world_applied": world,
              "render_settings": {"console": {"landscape.RenderNanite": "1",
                                              "r.VirtualTextures": "absent"}},
              "frame_records": [{"labels": {"landcover_png": "frame_0000_landcover_id.png"}}]}
    (folder / "render.json").write_text(json.dumps(render), encoding="utf-8")
    return tmp_path


def test_check_world_record_grades_each_key_only_when_present(tmp_path):
    from core.capture.verify import FAIL_WORLD_RECORD, verify_world_record

    ok = verify_world_record({}, _world_run(tmp_path / "ok"))
    assert ok.status == "PASS", ok.detail
    moon = verify_world_record({}, _world_run(tmp_path / "moon", moon_index=0))
    assert moon.status == "FAIL" and moon.failure == FAIL_WORLD_RECORD == "check.world_record"
    streak = verify_world_record({}, _world_run(tmp_path / "streak", streak=40.0))
    assert streak.status == "FAIL" and "streak" in streak.detail
    assert verify_world_record({}, tmp_path / "nothing").status == "NOT RUN"
    assert verify_world_record({}, None).status == "NOT RUN"
    source = (REPO / "core" / "capture" / "verify.py").read_text(encoding="utf-8")
    assert 'run("world_record", verify_world_record, manifest, run_dir)' in source


def test_every_new_refusal_name_is_catalogued_and_the_look_names_have_landed():
    from core.messages import catalogue, is_catalogued

    for name in ("world.scene_missing", "world.scene_stale", "labels.landcover_pass",
                 "vegetation.biome_asset", "vegetation.count_mismatch", "check.world_record",
                 "look.precipitation_particles", "look.cloud_drift_parameter", "look.moon",
                 "look.stars", "night.sun_units", "terrain.landscape_missing",
                 "terrain.landscape_stale", "terrain.landscape_layout"):
        assert is_catalogued(name), name
    assert catalogue()["world.scene_stale"]["hint"]
    messages = (REPO / "tests" / "test_messages.py").read_text(encoding="utf-8")
    future = messages[messages.index("ALLOWED_FUTURE: Dict[str, str] = {"):]
    future = future[:future.index("\n}\n")]
    assert '"look.precipitation_particles":' not in future
    assert '"look.cloud_drift_parameter":' not in future


def test_the_windows_order_carries_the_world_steps():
    report = (REPO / "docs" / "PHASE2_REPORT.md").read_text(encoding="utf-8")
    order = report[report.index("**The Windows verification order**"):report.index("**Open findings.**")]
    step = order[order.index("10. W5, the world engine side"):]
    for fragment in ("control_ridge", "matterhorn", "sha256_tag", "posting_m", "Nanite on / off",
                     "SVT on / off", ">= 0.95", "PCG on / off", "buildings on / off",
                     "< 2 px", "-12 deg", "-18 deg", "streaks on / off", "drift doublet",
                     "Substrate on / off", "1- and 2-worker campaign"):
        assert fragment in step, fragment
