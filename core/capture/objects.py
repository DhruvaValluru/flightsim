"""Object identity: the labelled objects of a scene, composed ONCE in Python.

A per-instance mask is only as good as the identity behind it. The
engine never invents an object id: the list of what is in the scene --
the primary airframe, every scripted traffic aircraft, the terrain -- is
composed here from the spec, each entry gets a stable string ``id`` and
a small integer ``int_id``, and the same list rides on the run card (the
commandlet reads it to set every labelled component's Custom Depth
Stencil), in the capture manifest (``objects[]``) and in every frame's
sidecar. The ID image's pixel values are these integers and nothing
else (contracts §2.3, §2.4).

The rules, stated once:

* ``id`` is ``aircraft:<fdm>:<n>`` (n = 0 the primary, 1.. the traffic
  entries in spec order), ``terrain``, ``building:all`` (W2: one
  aggregate for a stated footprint set, composed after the terrain;
  W4: also for a scene whose bake has land cover),
  ``vegetation:all`` (W4: one aggregate for a scene whose bake has land
  cover, composed last). A string, never a hash: two runs of one spec
  name one object the same way, and a reader can tell an aircraft from
  a building without a table.
* The aggregates (W4) are ONE object each, never one per tree or per
  building: the ID image is the 8-bit Custom Depth Stencil, and a
  scene's trees and blocks outnumber its 255 values, so a per-instance
  id is exactly what the stencil cannot carry (stated, not worked
  around; the per-building ids live in the buildings document, and no
  tree has an id at all). Their class is the taxonomy word the
  land-cover legend maps to (core/terrain/weightmaps.py CLASS_OF_COVER:
  tree cover, shrubland, mangroves -> vegetation; built-up -> building)
  and each is composed only when the spec's taxonomy names that class
  (a trimmed taxonomy composes none, rather than refusing a scene for
  cover it did not ask to label). Their boxes and masks per frame come
  from the land-cover class image (core/capture/labels.py
  ``landcover_class_from_depth``); the aggregate's ``int_id`` is where
  the engine's stencil loop (W5, Windows) draws its members.
* ``int_id`` is assigned in COMPOSITION ORDER starting at 1. The primary
  aircraft is composed first, so its ``int_id`` is always 1 and every
  Phase 10 reader (``verify.AIRCRAFT_INSTANCE_ID = 1``, the frames page
  legend) stays true on a single-aircraft run. Traffic follows in spec
  order, then the scene objects. The same spec composes the same list,
  so the ids are stable across frames, cameras and runs of one spec
  (pinned by a test and a mutation guard).
* ``class_id`` is the class's position in the spec's ``taxonomy.classes``
  plus one (0 is reserved for sky / nothing). An object whose class the
  taxonomy does not name refuses by name (``taxonomy.classes``): the
  dataset's categories come from the stated list, never from what
  happened to be in the scene.
* The Custom Depth Stencil is eight bits wide, so a scene that needs
  more than :data:`MAX_INT_ID` ids refuses by name
  (``annotation.identity``) at composition time -- before any engine
  time is spent -- rather than wrapping an id modulo 256 into another
  object's pixels.
* ``mesh_sha256`` is the SHA-256 of the imported model's
  ``mesh_manifest.json`` where the producing machine has one, null
  where it has not (a headless machine honestly has no mesh);
  ``licence`` is the airframe config's stated licence name, null when
  no config exists. ``in_scene`` says the object is drawn in the scene
  the card describes; ``labelled`` says a label is produced for it. A
  missing label is thereby distinguishable from a missing object.

What is NOT claimed: this module says which objects exist and what
integer each carries. Whether the ID image actually holds only those
integers is the verifier's ``mask_integers_only`` (package D); whether
a traffic mesh is on the render host is the ``aircraft.mesh`` refusal
in ``flightsim/capture.py``; buildings and vegetation are composed only
as the two aggregates above (no per-instance id for a tree or a
building, no species, no season), water has no object at all (its
pixels carry their land-cover code in the class image only), and
``cloud`` is a class in the visibility record only (volumetrics write
no ID).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO / "assets" / "aircraft_config"
GENERATED_DIR = REPO / "assets" / "generated"

#: The Custom Depth Stencil is 8 bits wide (contracts §2.3): the largest
#: ``int_id`` the ID image can carry. A scene needing more refuses.
MAX_INT_ID = 255
#: The ID image's value for background / unlabelled pixels; never an
#: object's id.
BACKGROUND_INT_ID = 0
#: The ``int_id`` the primary airframe always gets (composed first).
PRIMARY_INT_ID = 1

ROLE_PRIMARY = "primary"
ROLE_TRAFFIC = "traffic"
ROLE_SCENE = "scene"

CLASS_AIRCRAFT = "aircraft"
CLASS_TERRAIN = "terrain"
#: W2: the buildings' one aggregate object (the 8-bit stencil's limit:
#: no per-instance ids; they live in the buildings document).
CLASS_BUILDING = "building"
BUILDING_ALL_ID = "building:all"
#: W4: the land cover's vegetation aggregate (no per-tree ids: the stencil).
CLASS_VEGETATION = "vegetation"
VEGETATION_ALL_ID = "vegetation:all"
#: W4: every aggregate object id, and the taxonomy class each carries.
AGGREGATE_CLASSES = {BUILDING_ALL_ID: CLASS_BUILDING, VEGETATION_ALL_ID: CLASS_VEGETATION}


class ObjectIdentityError(Exception):
    """The scene cannot be given stable integer ids; named on the
    Violation surface as ``annotation.identity``."""

    constraint = "annotation.identity"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"annotation.identity: {message}")


class TaxonomyError(Exception):
    """An object's class is not in the spec's taxonomy; named
    ``taxonomy.classes`` like the spec-level refusal for the list."""

    constraint = "taxonomy.classes"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"taxonomy.classes: {message}")


@dataclass(frozen=True)
class SceneObject:
    """One labelled object, exactly the manifest's ``objects[]`` entry."""

    id: str
    int_id: int
    class_name: str
    class_id: int
    instance: int
    role: str
    mesh_sha256: Optional[str]
    licence: Optional[str]
    in_scene: bool
    labelled: bool

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "int_id": self.int_id, "class": self.class_name,
            "class_id": self.class_id, "instance": self.instance,
            "role": self.role, "mesh_sha256": self.mesh_sha256,
            "licence": self.licence, "in_scene": self.in_scene,
            "labelled": self.labelled,
        }


def taxonomy_classes(spec) -> List[str]:
    """The spec's ordered class list (``class_id`` = position + 1)."""
    return [str(c) for c in spec.taxonomy.classes.value]


def class_id_of(classes: Sequence[str], name: str) -> int:
    """``class_id`` of a class name in the taxonomy, or a named refusal."""
    try:
        return list(classes).index(name) + 1
    except ValueError:
        raise TaxonomyError(
            f"the taxonomy {list(classes)} does not name class {name!r}, "
            f"which an object in this scene is; a dataset's categories come "
            f"from the stated list, so the object cannot be labelled") from None


def classes_sentence(classes: Sequence[str]) -> str:
    """``"0 sky, 1 aircraft, 2 terrain, ..."`` -- the render.json
    ``labels.classes`` string, generated from the taxonomy."""
    return ", ".join(["0 sky"] + [f"{i + 1} {name}" for i, name in enumerate(classes)])


def mesh_manifest_path(aircraft: str) -> Path:
    return GENERATED_DIR / str(aircraft) / "mesh_manifest.json"


def mesh_sha256(aircraft: str) -> Optional[str]:
    """SHA-256 of the imported model's manifest on THIS machine, or None
    (a headless clone honestly has no mesh; never a hash of nothing)."""
    path = mesh_manifest_path(aircraft)
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def licence_of(aircraft: str, config_dir: Optional[Path] = None) -> Optional[str]:
    """The airframe config's stated licence name, or None without a
    config (nothing is guessed from the airframe's name)."""
    path = Path(config_dir or CONFIG_DIR) / f"{aircraft}.json"
    if not path.is_file():
        return None
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    licence = (config.get("license") or {}).get("license_name")
    return str(licence) if licence else None


def object_entries(spec, config_dir: Optional[Path] = None,
                   landcover: bool = False) -> List[Dict]:
    """The scene's objects in COMPOSITION ORDER, not yet numbered:
    primary airframe, traffic in spec order, then the scene objects.
    Each entry is a SceneObject's fields minus ``int_id``. ``landcover``
    (W4): the scene's bake carries land cover, so the ``building:all``
    and ``vegetation:all`` aggregates are composed (each only when the
    taxonomy names its class; absent-canonical: False composes exactly
    the list composed before W4)."""
    classes = taxonomy_classes(spec)
    primary = str(spec.aircraft.value)
    entries: List[Dict] = [{
        "id": f"aircraft:{primary}:0",
        "class_name": CLASS_AIRCRAFT,
        "class_id": class_id_of(classes, CLASS_AIRCRAFT),
        "instance": 0, "role": ROLE_PRIMARY,
        "mesh_sha256": mesh_sha256(primary),
        "licence": licence_of(primary, config_dir),
        "in_scene": True, "labelled": True,
    }]
    for index, entry in enumerate(spec.traffic):
        aircraft = str(entry.aircraft.value)
        entries.append({
            "id": f"aircraft:{aircraft}:{index + 1}",
            "class_name": CLASS_AIRCRAFT,
            "class_id": class_id_of(classes, CLASS_AIRCRAFT),
            "instance": index + 1, "role": ROLE_TRAFFIC,
            "mesh_sha256": mesh_sha256(aircraft),
            "licence": licence_of(aircraft, config_dir),
            "in_scene": True, "labelled": True,
        })
    # P7: the wake generator (the spec's wake block) is one more scripted
    # aircraft, composed after the traffic entries with the next instance
    # number, so its mesh and its label ride like a traffic aircraft's.
    wake = getattr(spec, "wake", None)
    generator = None if wake is None else wake.generator.value
    if generator is not None:
        index = len(spec.traffic) + 1
        entries.append({
            "id": f"aircraft:{generator}:{index}",
            "class_name": CLASS_AIRCRAFT,
            "class_id": class_id_of(classes, CLASS_AIRCRAFT),
            "instance": index, "role": ROLE_TRAFFIC,
            "mesh_sha256": mesh_sha256(str(generator)),
            "licence": licence_of(str(generator), config_dir),
            "in_scene": True, "labelled": True,
        })
    # The scene classes present. The render scene always draws a ground
    # -- a raster or the flat datum plane -- so the terrain object is in
    # every scene and labelled (its pixels carry its int_id in the ID
    # image; it gets no alone pass, stated on its label record).
    # Buildings, vegetation and water have no producer this phase and
    # are composed only when they exist, which is never yet.
    entries.append({
        "id": CLASS_TERRAIN,
        "class_name": CLASS_TERRAIN,
        "class_id": class_id_of(classes, CLASS_TERRAIN),
        "instance": 0, "role": ROLE_SCENE,
        "mesh_sha256": None, "licence": None,
        "in_scene": True, "labelled": True,
    })
    # W2: a stated footprint set (scene.buildings) composes ONE aggregate
    # object, building:all, after the terrain (so every earlier int_id is
    # unmoved): the 8-bit stencil cannot carry an id per building, so the
    # per-instance ids live in the buildings document, not the ID image
    # (stated). mesh_sha256 is the cached set's own digest (the sidecar's
    # sha256 of the footprint file), licence its licence word; both null
    # when the set is not cached here (the capture refuses that by name).
    scene = getattr(spec, "scene", None)
    buildings = getattr(scene, "buildings", None)
    key = None if buildings is None else buildings.value
    if key is not None:
        from core.scene.buildings import licence_of_key, read_provenance, BuildingsError

        try:
            digest = read_provenance(str(key)).get("sha256")
        except BuildingsError:
            digest = None
        entries.append({
            "id": BUILDING_ALL_ID,
            "class_name": CLASS_BUILDING,
            "class_id": class_id_of(classes, CLASS_BUILDING),
            "instance": 0, "role": ROLE_SCENE,
            "mesh_sha256": str(digest) if isinstance(digest, str) else None,
            "licence": licence_of_key(str(key)),
            "in_scene": True, "labelled": True,
        })
    # W4: a scene with land cover composes the aggregates the legend's
    # taxonomy map names -- building:all (when no footprint set composed
    # it above) then vegetation:all, after every earlier object, so no
    # earlier int_id moves. One id each: the 8-bit stencil's limit.
    if landcover:
        composed = {e["id"] for e in entries}
        for object_id in (BUILDING_ALL_ID, VEGETATION_ALL_ID):
            name = AGGREGATE_CLASSES[object_id]
            if object_id in composed or name not in classes:
                continue
            entries.append({
                "id": object_id, "class_name": name,
                "class_id": class_id_of(classes, name),
                "instance": 0, "role": ROLE_SCENE,
                "mesh_sha256": None, "licence": None,
                "in_scene": True, "labelled": True,
            })
    return entries


#: How a class's pixels are labelled, by class (``presence[].labelled_as``).
LABELLED_AS = {
    CLASS_AIRCRAFT: "instance id (ID image) + class image",
    CLASS_TERRAIN: "instance id (ID image) + class image",
    CLASS_BUILDING: "one aggregate id (building:all) + class image",
    CLASS_VEGETATION: "one aggregate id (vegetation:all) + class image",
}


def class_presence(spec, objects: Sequence["SceneObject"], landcover: bool = False,
                   randomization: Optional[Dict] = None) -> List[Dict]:
    """Scene vs labelled, per taxonomy class: was anything of the class
    in the scene, and did it get a label? One entry per class of
    ``taxonomy.classes`` in class_id order, so "not labelled" (in_scene
    true, labelled false) is told apart from "not there" (in_scene
    false) and from "not known when the scene was composed" (in_scene
    null, with the reason).

    Each entry: ``class``, ``class_id``, ``in_scene`` (true / false /
    null), ``labelled`` (an instance id in the ID image), ``objects``
    (the composed ids of the class), ``labelled_as`` and ``reason``.
    Decided from the spec and the composed objects only -- nothing the
    engine reported; whether an object is IN VIEW in a given frame is the
    frame's own ``labels.presence``.
    """
    classes = taxonomy_classes(spec)
    by_class: Dict[str, List["SceneObject"]] = {}
    for obj in objects:
        by_class.setdefault(obj.class_name, []).append(obj)
    surface = str(getattr(getattr(spec, "surface", None), "value", "") or "")
    cloud_cover = (randomization or {}).get("cloud_cover")
    out: List[Dict] = []
    for index, name in enumerate(classes):
        members = by_class.get(name, [])
        entry = {"class": name, "class_id": index + 1,
                 "objects": [o.id for o in members]}
        if members:
            entry.update(
                in_scene=any(o.in_scene for o in members),
                labelled=any(o.labelled and o.in_scene for o in members),
                labelled_as=LABELLED_AS.get(name, "instance id (ID image)"),
                reason=f"composed as {', '.join(o.id for o in members)}")
        elif name in (CLASS_BUILDING, CLASS_VEGETATION):
            entry.update(
                in_scene=False, labelled=False, labelled_as=None,
                reason=("no building footprint set and no land cover in this "
                        "scene's bake, so none is drawn" if name == CLASS_BUILDING
                        else "no land cover in this scene's bake, so no "
                             "vegetation is drawn"))
        elif name == "water":
            if landcover:
                entry.update(
                    in_scene=None, labelled=False,
                    labelled_as="land-cover class image only (no instance id)",
                    reason="drawn wherever the land cover has water; how much "
                           "is in view is each frame's labels.landcover")
            elif surface == "water":
                entry.update(
                    in_scene=True, labelled=False, labelled_as=None,
                    reason="the stated surface is water; it is drawn but "
                           "carries no id and no class image")
            else:
                entry.update(in_scene=False, labelled=False, labelled_as=None,
                             reason="no water surface and no land cover in "
                                    "this scene")
        elif name == "cloud":
            if cloud_cover is None:
                entry.update(
                    in_scene=None, labelled=False,
                    labelled_as="visibility record only (volumetrics write no id)",
                    reason="no cloud cover was recorded for this run")
            else:
                there = float(cloud_cover) > 0.0
                entry.update(
                    in_scene=there, labelled=False,
                    labelled_as=("visibility record only (volumetrics write no id)"
                                 if there else None),
                    reason=f"cloud cover {float(cloud_cover):g} recorded for "
                           f"this run{'' if there else ': no clouds drawn'}")
        else:
            entry.update(in_scene=False, labelled=False, labelled_as=None,
                         reason=f"no producer in this build composes a "
                                f"{name!r} object")
        out.append(entry)
    return out


def frame_presence(presence: Sequence[Dict], records: Sequence[Dict],
                   class_of: Dict[str, str]) -> List[Dict]:
    """One frame's scene-vs-labelled view: the run's per-class entry plus
    which of the class's labelled objects are in this frame
    (``in_frame_objects``) and which have no in-frame answer before the
    engine's ID image is read (``in_frame_unknown``: a scene object such
    as the terrain carries ``in_frame: null`` until then). So "in the
    scene but out of this frame" reads differently from "not in the
    scene". ``class_of`` maps object id -> class."""
    in_frame: Dict[str, List[str]] = {}
    unknown: Dict[str, List[str]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        name = class_of.get(str(record.get("id")))
        if record.get("in_frame") is None:
            unknown.setdefault(str(name), []).append(str(record.get("id")))
        elif record.get("in_frame"):
            in_frame.setdefault(str(name), []).append(str(record.get("id")))
    return [{"class": entry["class"], "class_id": entry["class_id"],
             "in_scene": entry["in_scene"], "labelled": entry["labelled"],
             "in_frame_objects": in_frame.get(entry["class"], []),
             "in_frame_unknown": unknown.get(entry["class"], [])}
            for entry in presence]


def assign_int_ids(entries: Sequence[Dict]) -> List[SceneObject]:
    """Number the entries 1.. in the order given. Refuses by name
    (``annotation.identity``) a list the 8-bit stencil cannot carry and
    a list that names one id twice -- an id that means two objects is
    exactly the mask a consumer cannot trust."""
    if len(entries) > MAX_INT_ID:
        raise ObjectIdentityError(
            f"{len(entries)} labelled objects need {len(entries)} ids but the "
            f"ID image (the 8-bit Custom Depth Stencil) carries at most "
            f"{MAX_INT_ID}; refusing to wrap an id into another object's pixels")
    seen = set()
    objects: List[SceneObject] = []
    for number, entry in enumerate(entries, start=1):
        if entry["id"] in seen:
            raise ObjectIdentityError(
                f"object id {entry['id']!r} is composed twice; one id, one object")
        seen.add(entry["id"])
        objects.append(SceneObject(
            id=str(entry["id"]), int_id=number,
            class_name=str(entry["class_name"]), class_id=int(entry["class_id"]),
            instance=int(entry["instance"]), role=str(entry["role"]),
            mesh_sha256=entry.get("mesh_sha256"), licence=entry.get("licence"),
            in_scene=bool(entry["in_scene"]), labelled=bool(entry["labelled"])))
    return objects


def compose_objects(spec, config_dir: Optional[Path] = None,
                    landcover: bool = False) -> List[SceneObject]:
    """The scene's labelled objects, numbered: the one list the card, the
    manifest and the ID image share. ``landcover`` (W4) composes the
    land cover's aggregates (:func:`object_entries`)."""
    return assign_int_ids(object_entries(spec, config_dir, landcover=landcover))


def aggregate_objects(objects: Sequence) -> List[Dict]:
    """The aggregate objects (``building:all``, ``vegetation:all``) of a
    list of SceneObjects or ``objects[]`` dicts, as dicts."""
    out = []
    for o in objects:
        entry = o.to_dict() if isinstance(o, SceneObject) else dict(o)
        if entry.get("id") in AGGREGATE_CLASSES:
            out.append(entry)
    return out


def objects_block(objects: Sequence[SceneObject]) -> List[Dict]:
    """The manifest / card ``objects[]`` list."""
    return [o.to_dict() for o in objects]


def by_int_id(objects: Sequence) -> Dict[int, Dict]:
    """``{int_id: entry}`` over SceneObjects or ``objects[]`` dicts."""
    out: Dict[int, Dict] = {}
    for o in objects:
        entry = o.to_dict() if isinstance(o, SceneObject) else dict(o)
        out[int(entry["int_id"])] = entry
    return out


def resolve_ids(int_ids: Sequence[int], objects: Sequence) -> List[str]:
    """Integer ids -> string ids through ``objects[]``. An integer the
    list does not name is kept VISIBLE as ``int_id:<n>`` rather than
    dropped: it is a finding for the verifier, not a value to hide."""
    index = by_int_id(objects)
    out = []
    for value in int_ids:
        entry = index.get(int(value))
        out.append(str(entry["id"]) if entry else f"int_id:{int(value)}")
    return out


def aircraft_objects(objects: Sequence[SceneObject]) -> List[SceneObject]:
    """The objects that get an alone pass (class ``aircraft``)."""
    return [o for o in objects if o.class_name == CLASS_AIRCRAFT and o.labelled]
