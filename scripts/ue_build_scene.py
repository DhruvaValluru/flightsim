"""Build a bake's Landscape scene level in the editor. Runs inside UE:

    UnrealEditor-Cmd <project> -run=pythonscript -script="scripts/ue_build_scene.py
        --terrain runs/terrain/control_ridge [--north-axis +Y] [--nanite on|off]
        [--imagery runs/terrain/control_ridge_imagery.json]
        [--buildings runs/terrain/control_ridge_buildings.json]
        [--runway runs/terrain/control_ridge_runway_09_record.json]
        [--biome /Game/FlightSim/Biomes/PCG_Forest.PCG_Forest]"

W5 (the world engine side, docs/ADVANCEMENTS_BLUEPRINT.md section 4). For
one bake key it:

1. checks, BEFORE anything is built, what the editor will read: the bake's
   sidecar sha256 against its samples, W1's import manifest
   ``<stem>_landscape.json`` (core/terrain/landscape.py import_manifest:
   the layout, the scale, the weight layers with their sha256s, the bake's
   sha256, the datum), every layer file's digest, and the bake-grid class
   map ``<stem>_landcover/class_map.png`` against its ``landcover.json``;
   refusals print ``REFUSED -- <name>: ...`` and exit 1
   (``terrain.landscape_missing``, ``terrain.landscape_stale``,
   ``terrain.landscape_layout``, ``terrain.landcover``,
   ``vegetation.biome_asset``);
2. creates the scene level ``/Game/FlightSim/Scenes/<key>/L_<key>`` and
   imports the Landscape through FlightSimBridgeEditor's
   ``ImportLandscape`` (the heights, one paint layer per land-cover class,
   the M_Landscape instance, the tags ``FlightSim.Terrain`` and
   ``FlightSim.TerrainSha256=<sha256>``), then ``BuildNanite`` on or off
   (the measured toggle);
3. imports the class map as ``T_<key>_ClassMap`` (8-bit codes as a linear,
   nearest-filtered, no-mip, never-streamed texture: the land-cover ID
   pass samples it), and the imagery drape when given;
4. draws what the scene states: the LoD1 buildings of W2's buildings
   document as one GeometryScript mesh tagged ``FlightSim.building`` (the
   ``building:all`` aggregate), the runway of W2's runway document as a
   plane on the pad's fitted plane with M_Runway and a point light per
   Annex 14 light position (tagged ``FlightSim.runway``; photometry is the
   document's named missing input, the lights' intensity a stated
   placeholder), and vegetation from a PCG biome graph when one is named
   (tagged ``FlightSim.vegetation``, the ``vegetation:all`` aggregate);
5. saves the level and writes the scene document ``<stem>_scene.json``
   beside the bake: the level, the bake's sha256, the axes, the landscape
   block, the layers, every sidecar with its sha256, the class map, the
   imagery, buildings, runway and vegetation blocks. The render's
   ``-scene=`` takes this document; the card's world block carries
   :func:`world_card_members` of it (scene_level, terrain_sha256,
   sidecars, layers), which the render matches at load
   (FlightSimVisualScene LoadSceneLevel, refused ``world.scene_stale``).

Everything above step 2 is plain Python (no ``unreal`` import), so the
checks and the document are exercised here (tests/test_ue_world_source.py);
the editor half is UNRUN here -- its node, actor and API names are the UE
Python API's, checked by the first Windows run (docs/PHASE2_REPORT.md, the
Windows order, step 9).

Not claimed: the imagery drape is a regular streamed texture (M_Landscape's
Imagery sampler is a colour sampler), so the SVT clause toggles the
project's r.VirtualTextures, not the drape's own flag; the runway's UV
orientation and the building extrusion are the GeometryScript defaults,
measured by the runway residual and the buildings on/off clause on Windows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

#: The scene document's version and its keys, in their fixed order.
DOCUMENT_VERSION = 1
DOCUMENT_KEYS = ("document_version", "key", "scene_level", "terrain_sha256", "north_axis",
                 "landscape_origin_xy", "bake", "landscape", "datum", "layers", "sidecars",
                 "class_map", "imagery", "buildings", "runway", "vegetation", "materials")
#: Where the scenes live in the project, and the name rules.
SCENE_ROOT = "/Game/FlightSim/Scenes"
#: The actor tags the render reads (FlightSimVisualScene.h FlightSimWorld,
#: pinned equal by test).
TAG_TERRAIN = "FlightSim.Terrain"
TAG_TERRAIN_SHA256_PREFIX = "FlightSim.TerrainSha256="
TAG_VEGETATION = "FlightSim.vegetation"
TAG_BUILDING = "FlightSim.building"
TAG_RUNWAY = "FlightSim.runway"
#: The two axis conventions a scene can be built for; the render measures
#: the georeferencing's and refuses the other (world.scene_stale).
NORTH_AXES = ("+Y", "-Y")
DEFAULT_NORTH_AXIS = "+Y"
#: The world materials the scene uses (scripts/ue_create_materials.py).
MATERIALS = {"landscape": "/Game/FlightSim/M_Landscape.M_Landscape",
             "land_cover_id": "/Game/FlightSim/M_LandcoverID.M_LandcoverID",
             "runway": "/Game/FlightSim/M_Runway.M_Runway"}
#: The runway plane sits this far above the pad's fitted plane (no z-fight).
RUNWAY_LIFT_M = 0.05
#: The runway lights' intensity: a stated PLACEHOLDER (Annex 14 Appendix 2
#: candela values are the runway document's named missing photometry).
RUNWAY_LIGHT_CANDELA = 1000.0
RUNWAY_LIGHT_COLOURS = {"white": (1.0, 1.0, 1.0), "green": (0.0, 1.0, 0.2),
                        "red": (1.0, 0.0, 0.0)}


class SceneError(Exception):
    """A scene that cannot be built, refused by name (``.constraint``)."""

    def __init__(self, constraint: str, message: str) -> None:
        self.constraint = constraint
        self.message = message
        super().__init__(f"{constraint}: {message}")


# -- the plain half: checks and the document --------------------------------------

def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scene_key(bake_stem) -> str:
    return Path(bake_stem).with_suffix("").name


def scene_paths(key: str) -> Dict[str, str]:
    """The /Game paths one scene owns."""
    folder = f"{SCENE_ROOT}/{key}"
    return {"folder": folder, "level": f"{folder}/L_{key}",
            "class_map": f"{folder}/T_{key}_ClassMap", "imagery": f"{folder}/T_{key}_Imagery",
            "material": f"{folder}/MI_{key}_Landscape", "markings": f"{folder}/T_{key}_Markings",
            "runway_material": f"{folder}/MI_{key}_Runway"}


def asset_object_path(package: str) -> str:
    """``/Game/a/B`` -> ``/Game/a/B.B`` (the form LoadObject takes)."""
    return f"{package}.{package.rsplit('/', 1)[-1]}"


def manifest_path_for(bake_stem) -> Path:
    stem = Path(bake_stem).with_suffix("")
    return stem.with_name(f"{stem.name}_landscape.json")


def document_path_for(bake_stem) -> Path:
    stem = Path(bake_stem).with_suffix("")
    return stem.with_name(f"{stem.name}_scene.json")


def landcover_dir_for(bake_stem) -> Path:
    """core/terrain/landcover.py scene_dir_for's rule, restated."""
    stem = Path(bake_stem).with_suffix("")
    return stem.with_name(f"{stem.name}_landcover")


def read_bake(bake_stem) -> Dict[str, Any]:
    """The bake's sidecar, its sha256 checked against the samples
    (terrain.landscape_stale otherwise; terrain.landscape_missing without
    the files)."""
    stem = Path(bake_stem).with_suffix("")
    sidecar, raw = stem.with_suffix(".json"), stem.with_suffix(".r16")
    if not sidecar.is_file() or not raw.is_file():
        raise SceneError("terrain.landscape_missing",
                         f"the bake {stem} (.r16 and .json) is not on this machine")
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    if sha256_of(raw) != meta.get("sha256"):
        raise SceneError("terrain.landscape_stale",
                         f"the bake {raw.name}'s samples are not the sha256 its sidecar records")
    return meta


def check_manifest(manifest_path, bake_sha256: str) -> Dict[str, Any]:
    """W1's import manifest, checked the way ImportLandscape checks it:
    present with its datum and bake (terrain.landscape_missing), exported
    from THIS bake and with every layer file at its recorded sha256
    (terrain.landscape_stale), every layer of the heightmap's layout
    (terrain.landscape_layout)."""
    path = Path(manifest_path)
    if not path.is_file():
        raise SceneError("terrain.landscape_missing",
                         f"the import manifest {path} is absent; export the landscape with "
                         f"scripts/bake_landcover.py")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    datum = manifest.get("datum")
    if not isinstance(datum, dict) or "undulation_m" not in datum \
            or "vertical_datum_of_heights" not in datum:
        raise SceneError("terrain.landscape_missing",
                         f"the import manifest {path.name} carries no datum block")
    bake = manifest.get("bake")
    if not isinstance(bake, dict) or not bake.get("sha256"):
        raise SceneError("terrain.landscape_missing",
                         f"the import manifest {path.name} names no bake")
    if bake["sha256"] != bake_sha256:
        raise SceneError("terrain.landscape_stale",
                         f"the manifest was exported from a bake with sha256 "
                         f"{bake['sha256'][:12]}..., the bake is {bake_sha256[:12]}...; export "
                         f"the landscape again")
    layout, resolution = manifest.get("layout"), manifest.get("resolution")
    for layer in manifest.get("weight_layers") or []:
        if layer.get("layout") != layout or layer.get("resolution") != resolution:
            raise SceneError("terrain.landscape_layout",
                             f"layer {layer.get('file')} is laid out for another Landscape "
                             f"than the heightmap")
        layer_path = path.parent / str(layer["file"])
        if not layer_path.is_file() or sha256_of(layer_path) != layer.get("sha256"):
            raise SceneError("terrain.landscape_stale",
                             f"the layer file {layer_path.name} is absent or differs from its "
                             f"recorded sha256")
    raw = path.with_suffix(".r16")
    if not raw.is_file() or raw.stat().st_size != 2 * int(resolution) ** 2:
        raise SceneError("terrain.landscape_layout",
                         f"the heightmap {raw.name} is not {resolution}^2 16-bit samples")
    return manifest


def check_class_map(bake_stem) -> Optional[Dict[str, Any]]:
    """The bake-grid class map and its record, or None when the bake has no
    land cover; a map that is not the one landcover.json recorded refuses
    terrain.landcover."""
    folder = landcover_dir_for(bake_stem)
    document = folder / "landcover.json"
    if not document.is_file():
        return None
    record = json.loads(document.read_text(encoding="utf-8"))
    block = record.get("class_map") or {}
    path = folder / str(block.get("file", "class_map.png"))
    if not path.is_file() or sha256_of(path) != block.get("sha256"):
        raise SceneError("terrain.landcover",
                         f"the class map {path} is absent or not the one {document.name} "
                         f"recorded; rasterise the land cover again")
    return {"file": str(path), "sha256": block["sha256"], "record": str(document),
            "record_sha256": sha256_of(document)}


def landscape_origin_xy(bake: Dict[str, Any], north_axis: str) -> List[float]:
    """The projected position of the Landscape's first sample: the bake's
    south-west sample when rows were written north-up (+Y), the north-west
    one otherwise (the .r16 row 0 is north)."""
    geo = bake["georeference"]
    x, y, px = float(geo["origin_x_m"]), float(geo["origin_y_m"]), float(geo["pixel_size_m"])
    if north_axis == "+Y":
        return [x, y - (int(bake["height"]) - 1) * px]
    return [x, y]


def to_level_cm(x: float, y: float, z: float, origin_xy: Sequence[float],
                north_axis: str) -> List[float]:
    """A projected point (metres, MSL) in the scene level's own frame (cm):
    X east from the Landscape's first sample, Y along the north axis the
    level was built for, Z the MSL height (the render offsets the level by
    the engine position of MSL 0 under that sample)."""
    dx = (float(x) - float(origin_xy[0])) * 100.0
    dy = (float(y) - float(origin_xy[1])) * 100.0
    return [dx, dy if north_axis == "+Y" else -dy, float(z) * 100.0]


def scene_document(bake_stem, manifest: Dict[str, Any], bake: Dict[str, Any], north_axis: str,
                   nanite: bool, class_map: Optional[Dict[str, Any]] = None,
                   imagery: Optional[Dict[str, Any]] = None,
                   buildings: Optional[Dict[str, Any]] = None,
                   runway: Optional[Dict[str, Any]] = None,
                   vegetation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The scene document, in DOCUMENT_KEYS order."""
    if north_axis not in NORTH_AXES:
        raise ValueError(f"north axis {north_axis!r} is not one of {list(NORTH_AXES)}")
    key = scene_key(bake_stem)
    paths = scene_paths(key)
    stem = Path(bake_stem).with_suffix("")
    manifest_path = manifest_path_for(stem)
    geo = bake["georeference"]
    layers = [{"code": int(layer["code"]), "class": layer["class"], "key": layer["key"],
               "sha256": layer["sha256"]} for layer in manifest.get("weight_layers") or []]
    sidecars: Dict[str, Dict[str, str]] = {
        "bake": {"file": str(stem.with_suffix(".json")), "sha256": sha256_of(stem.with_suffix(".json"))},
        "landscape_manifest": {"file": str(manifest_path), "sha256": sha256_of(manifest_path)},
        "landscape_heightmap": {"file": str(manifest_path.with_suffix(".r16")),
                                "sha256": sha256_of(manifest_path.with_suffix(".r16"))},
    }
    layers_sidecar = manifest_path.with_name(f"{key}_landcover_layers.json")
    if layers_sidecar.is_file():
        sidecars["landcover_layers"] = {"file": str(layers_sidecar),
                                        "sha256": sha256_of(layers_sidecar)}
    if class_map is not None:
        sidecars["landcover"] = {"file": class_map["record"], "sha256": class_map["record_sha256"]}
        class_block = {"file": class_map["file"], "sha256": class_map["sha256"],
                       "width": int(bake["width"]), "height": int(bake["height"]),
                       "asset": asset_object_path(paths["class_map"])}
    else:
        class_block = None
    for name, block in (("imagery", imagery), ("buildings", buildings), ("runway", runway)):
        if block is not None and block.get("document"):
            sidecars[name] = {"file": block["document"], "sha256": block["document_sha256"]}
    pixel_x = float(manifest["pixel_size_m"]["x"])
    document = {
        "document_version": DOCUMENT_VERSION,
        "key": key,
        "scene_level": paths["level"],
        "terrain_sha256": bake["sha256"],
        "north_axis": north_axis,
        "landscape_origin_xy": landscape_origin_xy(bake, north_axis),
        "bake": {"stem": str(stem), "name": bake.get("name"), "sha256": bake["sha256"],
                 "width": int(bake["width"]), "height": int(bake["height"]),
                 "crs": geo.get("crs"), "origin_x_m": float(geo["origin_x_m"]),
                 "origin_y_m": float(geo["origin_y_m"]),
                 "pixel_size_m": float(geo["pixel_size_m"])},
        "landscape": {"manifest": str(manifest_path), "resolution": int(manifest["resolution"]),
                      "layout": dict(manifest["layout"]), "scale": dict(manifest["scale"]),
                      "posting_m": pixel_x,
                      "min_elevation_m": float(manifest["min_elevation_m"]),
                      "max_elevation_m": float(manifest["max_elevation_m"]),
                      "nanite": bool(nanite),
                      "tags": [TAG_TERRAIN, TAG_TERRAIN_SHA256_PREFIX + bake["sha256"]]},
        "datum": manifest["datum"],
        "layers": layers,
        "sidecars": sidecars,
        "class_map": class_block,
        "imagery": imagery,
        "buildings": buildings,
        "runway": runway,
        "vegetation": vegetation,
        "materials": dict(MATERIALS),
    }
    assert tuple(document) == DOCUMENT_KEYS
    return document


def world_card_members(document: Dict[str, Any]) -> Dict[str, Any]:
    """What the run card's world block carries of a scene (beside W2's
    terrain / buildings / runway members): the level, the terrain sha256,
    every sidecar's digest and the layers -- matched by the render at load."""
    return {"scene_level": document["scene_level"],
            "terrain_sha256": document["terrain_sha256"],
            "sidecars": {name: {"sha256": block["sha256"]}
                         for name, block in document["sidecars"].items()},
            "layers": [{"code": layer["code"], "sha256": layer["sha256"]}
                       for layer in document["layers"]]}


def write_scene_document(document: Dict[str, Any], path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(document, indent=1), encoding="utf-8")
    return path


def document_block(path, **extra) -> Dict[str, Any]:
    """A W2 document named on the command line: its path and sha256."""
    path = Path(path)
    if not path.is_file():
        raise SceneError("world.scene_missing", f"{path} is not on this machine")
    return {"document": str(path), "document_sha256": sha256_of(path), **extra}


# -- the editor half ---------------------------------------------------------------

def _import_texture(unreal, source, folder: str, name: str, linear: bool, nearest: bool,
                    virtual_texture: bool = False):
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", str(source))
    task.set_editor_property("destination_path", folder)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", False)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    texture = unreal.load_asset(f"{folder}/{name}")
    if texture is None:
        raise SceneError("world.scene_missing", f"{source} did not import as {folder}/{name}")
    if linear:
        # Codes and markings are data: no sRGB curve, uncompressed 8 bits.
        texture.set_editor_property("srgb", False)
        texture.set_editor_property("compression_settings",
                                    unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP)
    if nearest:
        texture.set_editor_property("filter", unreal.TextureFilter.TF_NEAREST)
        texture.set_editor_property("mip_gen_settings",
                                    unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
        texture.set_editor_property("never_stream", True)
    texture.set_editor_property("virtual_texture_streaming", bool(virtual_texture))
    unreal.EditorAssetLibrary.save_asset(f"{folder}/{name}")
    return texture


def _material_instance(unreal, parent_path: str, package: str):
    folder, name = package.rsplit("/", 1)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    instance = unreal.load_asset(package) or tools.create_asset(
        name, folder, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    instance.set_editor_property("parent", unreal.load_asset(parent_path))
    return instance


def _tag(unreal, actor, tag: str) -> None:
    tags = list(actor.get_editor_property("tags"))
    tags.append(unreal.Name(tag))
    actor.set_editor_property("tags", tags)


def _build_buildings(unreal, document_path, origin_xy, north_axis) -> int:
    """W2's LoD1 blocks as ONE GeometryScript mesh (the building:all
    aggregate): each footprint extruded from its pad seat by its height."""
    data = json.loads(Path(document_path).read_text(encoding="utf-8"))
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.DynamicMeshActor,
                                                             unreal.Vector(0.0, 0.0, 0.0))
    mesh = actor.get_dynamic_mesh_component().get_dynamic_mesh()
    options = unreal.GeometryScriptPrimitiveOptions()
    for block in data.get("buildings") or []:
        ring = []
        for x, y in block["polygon_xy"]:
            cx, cy, _ = to_level_cm(x, y, 0.0, origin_xy, north_axis)
            ring.append(unreal.Vector2D(cx, cy))
        seat = unreal.Transform(location=[0.0, 0.0, float(block["pad_seat_m"]) * 100.0])
        unreal.GeometryScript_Primitives.append_simple_extrude_polygon(
            mesh, options, seat, ring, float(block["height_m"]) * 100.0, 0, True)
    actor.set_actor_label("Buildings_LoD1")
    _tag(unreal, actor, TAG_BUILDING)
    return len(data.get("buildings") or [])


def _build_runway(unreal, document_path, origin_xy, north_axis, paths) -> int:
    """W2's runway: a plane on the pad's fitted plane (z = a + b s + c t,
    lifted RUNWAY_LIFT_M) with M_Runway and the markings raster, and a point
    light per Annex 14 position; all tagged FlightSim.runway."""
    import math

    data = json.loads(Path(document_path).read_text(encoding="utf-8"))
    geometry, plane = data["geometry"], data["pad"]["statistics"]["plane"]
    x0, y0 = geometry["threshold_xy"]
    along, across = geometry["along"], geometry["across"]
    length, width = float(geometry["length_m"]), float(geometry["width_m"])

    def point(s, t):
        x = x0 + s * along[0] + t * across[0]
        y = y0 + s * along[1] + t * across[1]
        z = plane["a_m"] + plane["b_per_m"] * s + plane["c_per_m"] * t + RUNWAY_LIFT_M
        return to_level_cm(x, y, z, origin_xy, north_axis)

    markings = _import_texture(unreal, data["markings"]["file"], paths["folder"],
                               paths["markings"].rsplit("/", 1)[-1], linear=True, nearest=False)
    material = _material_instance(unreal, MATERIALS["runway"], paths["runway_material"])
    unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(
        material, "Markings", markings)
    centre = point(length / 2.0, 0.0)
    ax, ay, _ = to_level_cm(x0 + along[0], y0 + along[1], 0.0, (x0, y0), north_axis)
    yaw = math.degrees(math.atan2(ay, ax))
    pitch = math.degrees(math.atan(plane["b_per_m"]))
    roll = math.degrees(math.atan(plane["c_per_m"]))
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.DynamicMeshActor,
                                                             unreal.Vector(*centre))
    mesh = actor.get_dynamic_mesh_component().get_dynamic_mesh()
    unreal.GeometryScript_Primitives.append_rectangle_xy(
        mesh, unreal.GeometryScriptPrimitiveOptions(), unreal.Transform(),
        length * 100.0, width * 100.0, 0, 0)
    actor.set_actor_rotation(unreal.Rotator(roll=roll, pitch=pitch, yaw=yaw), False)
    actor.get_dynamic_mesh_component().set_material(0, material)
    actor.set_actor_label(f"Runway_{data['spec']['designator']}")
    _tag(unreal, actor, TAG_RUNWAY)
    lights = 0
    for light in (data.get("lights") or {}).get("positions") or []:
        location = point(float(light["s_m"]), float(light["t_m"]))
        lamp = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.PointLight,
                                                                unreal.Vector(*location))
        component = lamp.get_component_by_class(unreal.PointLightComponent)
        component.set_editor_property("intensity_units", unreal.LightUnits.CANDELAS)
        component.set_editor_property("intensity", RUNWAY_LIGHT_CANDELA)
        component.set_editor_property("light_color", unreal.Color(
            *[int(255 * c) for c in RUNWAY_LIGHT_COLOURS[light["colour"]]], 255))
        _tag(unreal, lamp, TAG_RUNWAY)
        lights += 1
    return lights


def _build_vegetation(unreal, biome: str, landscape) -> int:
    """A PCG volume over the Landscape running the named biome graph,
    generated in the editor and saved with the level; returns the instances
    generated (the render refuses vegetation.count_mismatch on another count)."""
    graph = unreal.load_asset(biome)
    if graph is None:
        raise SceneError("vegetation.biome_asset", f"the PCG biome graph {biome} does not load")
    origin, extent = landscape.get_actor_bounds(False)
    volume = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.PCGVolume, origin)
    volume.set_actor_scale3d(unreal.Vector(extent.x / 100.0, extent.y / 100.0, extent.z / 100.0 + 1.0))
    component = volume.get_component_by_class(unreal.PCGComponent)
    component.set_graph(graph)
    component.generate(True)
    _tag(unreal, volume, TAG_VEGETATION)
    instances = 0
    for mesh in volume.get_components_by_class(unreal.InstancedStaticMeshComponent):
        instances += mesh.get_instance_count()
    return instances


def build_in_editor(args, manifest, bake, class_map) -> Dict[str, Any]:
    import unreal  # noqa: PLC0415 -- only inside the editor

    key = scene_key(args.terrain)
    paths = scene_paths(key)
    north = args.north_axis
    levels = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not levels.new_level(paths["level"]):
        raise SceneError("world.scene_missing", f"the editor did not create {paths['level']}")
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    material = _material_instance(unreal, MATERIALS["landscape"], paths["material"])
    lib = unreal.MaterialEditingLibrary
    lib.set_material_instance_scalar_parameter_value(material, "LandscapeTexels",
                                                     float(manifest["resolution"]) - 1.0)
    lib.set_material_instance_scalar_parameter_value(material, "ImageryFlipV",
                                                     1.0 if north == "+Y" else 0.0)
    imagery_block = None
    if args.imagery:
        sidecar = json.loads(Path(args.imagery).read_text(encoding="utf-8"))
        png = Path(args.imagery).with_name(str(sidecar.get("file") or
                                               Path(args.imagery).with_suffix(".png").name))
        texture = _import_texture(unreal, png, paths["folder"], paths["imagery"].rsplit("/", 1)[-1],
                                  linear=False, nearest=False, virtual_texture=False)
        lib.set_material_instance_texture_parameter_value(material, "Imagery", texture)
        lib.set_material_instance_scalar_parameter_value(material, "ImageryWeight", 1.0)
        imagery_block = document_block(args.imagery, sha256=sha256_of(png),
                                       asset=asset_object_path(paths["imagery"]),
                                       virtual_texture=False)
    unreal.EditorAssetLibrary.save_asset(paths["material"])

    landscape, report = unreal.FlightSimLandscapeImporter.import_landscape(
        world, str(manifest_path_for(args.terrain)), bake["sha256"], paths["folder"], material,
        north)
    if landscape is None:
        # ImportLandscape's line already names the refusal.
        name, _, message = report.partition(": ")
        raise SceneError(name, message)
    print(f"  landscape    {report}")
    ok, nanite_report = unreal.FlightSimLandscapeImporter.build_nanite(landscape, args.nanite == "on")
    print(f"  nanite       {nanite_report}")
    if class_map is not None:
        _import_texture(unreal, class_map["file"], paths["folder"],
                        paths["class_map"].rsplit("/", 1)[-1], linear=True, nearest=True)
    origin_xy = landscape_origin_xy(bake, north)
    buildings = runway = vegetation = None
    if args.buildings:
        count = _build_buildings(unreal, args.buildings, origin_xy, north)
        buildings = document_block(args.buildings, count=count)
    if args.runway:
        lights = _build_runway(unreal, args.runway, origin_xy, north, paths)
        runway = document_block(args.runway, lights=lights)
    if args.biome:
        vegetation = {"biome_graph": args.biome,
                      "instances": _build_vegetation(unreal, args.biome, landscape)}
    levels.save_current_level()
    unreal.EditorAssetLibrary.save_directory(paths["folder"])
    return {"imagery": imagery_block, "buildings": buildings, "runway": runway,
            "vegetation": vegetation, "nanite_ok": bool(ok)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--terrain", required=True, help="the bake stem (<dir>/<key>, .r16 + .json)")
    ap.add_argument("--north-axis", default=DEFAULT_NORTH_AXIS, choices=NORTH_AXES,
                    help="the engine axis north lies along (the render measures it)")
    ap.add_argument("--nanite", default="on", choices=("on", "off"))
    ap.add_argument("--imagery", default=None, help="a drape sidecar (core/terrain/imagery.py)")
    ap.add_argument("--buildings", default=None, help="W2's <bake>_buildings.json")
    ap.add_argument("--runway", default=None, help="W2's runway record document")
    ap.add_argument("--biome", default=None, help="a PCG graph asset path for the vegetation")
    args = ap.parse_args(argv)
    try:
        bake = read_bake(args.terrain)
        manifest = check_manifest(manifest_path_for(args.terrain), bake["sha256"])
        class_map = check_class_map(args.terrain)
        built = build_in_editor(args, manifest, bake, class_map)
        document = scene_document(args.terrain, manifest, bake, args.north_axis,
                                  args.nanite == "on" and built["nanite_ok"], class_map,
                                  built["imagery"], built["buildings"], built["runway"],
                                  built["vegetation"])
    except SceneError as exc:
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        return 1
    path = write_scene_document(document, document_path_for(args.terrain))
    print(f"scene {document['scene_level']} for {document['key']} "
          f"(sha256 {document['terrain_sha256'][:12]}..., north {document['north_axis']}, "
          f"{len(document['layers'])} layers) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
