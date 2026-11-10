"""Convert a FlightGear aircraft model into per-part OBJ files for Unreal.

One part per rigid piece: the body, and one OBJ per control surface, each
surface exported in place (UE actor frame, centimetres) together with its
hinge line -- so the Unreal side can attach each surface mesh under a hinge
scene component exactly the way the placeholder boxes are attached, and the
existing ``UFlightSimSurfaceAnimator`` drives real geometry through the same
binding code path Gate 5 measured.

The §1.4 rule is enforced here, before any import happens: the config states
which JSBSim FDM the mesh matches, and :func:`convert` refuses to run if the
FDM's ``<fdm_config name=...>`` does not appear in the config's
``fdm_match`` allowance. A mesh of one aircraft flying the model of another is
the failure this repository exists to prevent.

License discipline (§3.3): the config carries the license name and source
(repo URL + commit), and the converter refuses to write anything if the
license file it points at does not exist on disk. The whole block is copied
into the output manifest, which the render commandlet echoes into every
render.json.

Where the mesh sits (manifest version 3): MEASURED from the vertices
---------------------------------------------------------------------
The vertices are mapped to the UE actor frame ABOUT THE MODEL'S OWN
ORIGIN, and the model's origin is not the actor's. The JSBSim plugin makes
the actor origin the STRUCTURAL DATUM (``StructuralToActorMatrix`` negates
x about ``StructuralFrameOrigin``, default zero) and ``FlightSimScenarioWorld``
places the actor so the CG lands on the commanded point. A mesh attached at
the actor root is therefore drawn with its model origin on the datum while
the label (built from the telemetry's CG) stays put -- the Camera Phase 1
"25-30 m ahead" offset. So the manifest records ``mesh_origin_actor_cm``,
the point in the actor frame the render commandlet attaches the body and
every hinge at.

Version 2 (eb5c71d) set that point to the STAGED FDM's visual reference
point (VRP), on the argument that FlightGear models are built about their
FDM's VRP. That was the wrong FDM: each FlightGear mesh was modelled
against its OWN repository's FDM file (FGMEMBERS/747-400's ``747-400.xml``
has VRP (1263, 0, 0) in; the staged ``B747.xml`` has (1327, 0, -24)), and
some meshes are not built about any VRP at all. Measured from the pinned
``.ac`` files with this package's own reader, in the actor frame about the
model origin: the B747's nose is 29.80 m AHEAD of its origin (the staged
VRP rule drew it 3.9 m aft of its label), the A320's origin is 2.53 m
ahead of its nose (the VRP rule introduced a NEW 19.3 m error), the
c172p's nose is 2.14 m ahead (right to 0.1 m by luck).

The rule now, version 3 -- a measurement, not a convention:

* ``x``: the mesh's forward extreme (its nose, the largest actor-frame x
  over every drawn vertex) is aligned with the airframe labels' ``nose``
  keypoint (``core/capture/airframe.py``, the same keypoint the labels
  project), mapped structural -> actor by the plugin's (-x, y, z):
  ``x = nose_actor_cm - mesh_nose_cm``.
* ``y = 0``: the model is taken as symmetric about its own origin; the
  measured y extents are recorded, not corrected.
* ``z``: where gear geometry is identifiable (the config's documented
  ``gear_geometry`` patterns, below), the lowest gear vertex is aligned
  with the FDM's main-gear ``<contact>`` z (the labels' ``left_main_gear``
  / ``right_main_gear`` keypoints, the lower of the two):
  ``z = main_gear_contact_actor_cm - gear_lowest_cm``. Otherwise the
  VRP's z is used and the manifest SAYS SO in ``mesh_origin_basis``.
* the config's documented ``model_origin_offset_m`` is added on top,
  exactly as in version 2.
* REFUSAL ``aircraft.mesh_extent``: when the mesh's nose-to-tail span
  disagrees with ``labels.dimensions_m.length`` by more than
  ``MESH_EXTENT_TOLERANCE`` (5 %) the geometry converted is not the
  airframe the labels describe -- a wrong mesh, a wrong unit or a wrong
  axis map -- and no origin can fix it; the message says which is
  likeliest.

The manifest carries the measurement beside the number: the extents
(``mesh_extents_actor_cm``, ``mesh_extent_actor_m``), the lengths compared,
the anchors used (``origin_anchor``, ``origin_measurement``), the basis in
words, and the VRP for reference (``vrp_actor_cm``). A manifest below
version 3 is stale: the importer re-converts it.

A config with NO ``labels`` block (DHC6 today) has no nose keypoint to
align to. Its origin stays the version-2 VRP rule -- byte-identical to
before -- with a basis that says so; the extents are still recorded and
the verifier's ``drawn_airframe`` grades the basis by name.

What is NOT claimed here. The mesh nose is aligned with the LABELLED
nose, whose own basis may be an estimate (the B747's is the structural
datum taken as the nose tip, basis ``estimate``); if that label is off,
the mesh follows it, and only a pixel check on a rendered frame
(``mask_vs_geometry``) measures the residual -- no engine runs in the
container this was written in. The z rule compares the LOWEST gear vertex
with the MAIN-gear contact; the nose-gear height in the mesh against the
FDM's is not compared (the 747 mesh's nose wheels sit 0.8 m below its
main wheels while its FDM puts the nose contact 0.25 m above the mains).
Rotational offsets in the model XML (the c172p's -3 deg pitch) are not
applied. The y axis is not measured against anything.

Aircraft config keys (``assets/aircraft_config/<name>.json``)
------------------------------------------------------------
``name``, ``fdm``, ``fdm_match`` (§1.4), ``mesh_airframe``, ``source_dir``,
``license`` (§3.3), ``parts`` (each ``file`` with an optional
``offset_m`` in the FlightGear model frame), ``exclude``, ``surfaces``
(``bone``, ``objects``, ``property``, ``scale_deg_per_unit``, ``hinge_m``,
optional ``continuous``), ``labels`` (read by core/capture/airframe.py
and, for the nose keypoint, the main-gear contacts and the length, here),
OPTIONAL ``gear_geometry``: ``{"parts": [regex...], "objects":
[regex...], "source": "..."}`` -- full-match patterns naming the part
files and/or object names whose vertices are landing gear (tyres, struts;
NOT doors or wells), so the lowest gear vertex can be told from the
lowest fuselage or nacelle vertex; absent or empty, the z origin falls
back to the VRP and the manifest says so -- and OPTIONAL
``model_origin_offset_m``: ``[x, y, z]`` in the UE actor frame, metres,
default ``[0, 0, 0]``, for a model whose origin is DOCUMENTED to need a
correction on top of the measured one (state the source in the config
beside it). It is never a way to nudge a mesh that "looks" off.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assets_pipeline.acmodel import (  # noqa: E402
    ac_to_model, model_to_ue, parse_ac, world_vertices,
)
from assets_pipeline.importer import COMPONENTS_MANIFEST_VERSION  # noqa: E402
from assets_pipeline.obj_frame import (  # noqa: E402
    OBJ_FRAME, OBJ_FRAME_KEY, actor_to_obj, obj_winding,
)
from assets_pipeline.smooth_normals import flipped, vertex_normals  # noqa: E402
from assets_pipeline.package_pins import (  # noqa: E402
    PackagePinError, verify as verify_package_pins,
)
from core.capture import airframe as airframe_module  # noqa: E402
from core.capture.airframe import fdm_xml_path  # noqa: E402
from core.capture.objects import component_mesh_name  # noqa: E402

CM_PER_M = 100.0
CM_PER_IN = 2.54
CM_PER_FT = 30.48

#: 1 -> 2 when ``mesh_origin_actor_cm`` was added (the FDM's VRP);
#: 2 -> 3 when the origin became a MEASUREMENT of the mesh (nose keypoint
#: in x, main-gear contact in z) -- the VRP rule was wrong by 3.9 m on
#: the B747 and 19.3 m on the A320. A reader that finds a lower version
#: has a manifest whose mesh the commandlet would draw off its label.
MESH_MANIFEST_VERSION = 3

#: The mesh's nose-to-tail span may differ from the labels' cited length
#: by this fraction before the mesh is refused as not the labelled
#: airframe. Measured slack on the three pinned meshes: 0.4 % (B747),
#: 0.0 % (A320), 0.6 % (c172p); a wrong unit is a factor of 3.28 or 39.4.
MESH_EXTENT_TOLERANCE = 0.05

#: The basis strings the manifest carries. A verifier grades the FIRST
#: one by prefix ("measured from vertices"); the VRP fallbacks are named
#: so a drawn mesh can never be mistaken for a measured one.
MESH_ORIGIN_BASIS_MEASURED = (
    "measured from vertices: nose keypoint (x), main-gear contact (z)")
MESH_ORIGIN_BASIS_MEASURED_X_ONLY = (
    "measured from vertices: nose keypoint (x), VRP (z: {reason})")
MESH_ORIGIN_BASIS_VRP = (
    "FDM VRP ({reason}); the VRP is read from the JSBSim XML's <location "
    "name=\"VRP\"> in the structural frame (inches, x aft, y right, z up) "
    "and mapped to the UE actor frame by (-x, y, z), the plugin's "
    "StructuralToActorMatrix about its zero origin, plus the config's "
    "documented model_origin_offset_m")

#: Kept for readers of version-2 manifests and for the fallback wording.
MESH_ORIGIN_BASIS = MESH_ORIGIN_BASIS_VRP


class ConvertError(Exception):
    """A named converter refusal. ``constraint`` is the refusal's name on
    the Violation surface (``aircraft.mesh_extent``, ``camera.labels``)
    where one exists; None for the older refusals that predate names."""

    def __init__(self, message: str, constraint: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.constraint = constraint


def _fdm_config_name(xml_path: Path) -> str:
    text = xml_path.read_text(errors="replace")
    match = re.search(r'<fdm_config[^>]*\bname="([^"]+)"', text)
    if not match:
        raise ConvertError(f"{xml_path}: no <fdm_config name=...> found")
    return match.group(1)


def _matches(name: str, patterns: Sequence[str]) -> bool:
    return any(re.fullmatch(p, name) for p in patterns)


def _structural_to_actor_cm(point: Tuple[float, float, float],
                            unit: str) -> Tuple[float, float, float]:
    """JSBSim structural (x aft, y right, z up, in the stated unit) ->
    UE actor frame (x forward, y right, z up), centimetres: the same
    (-x, y, z) map as the plugin's StructuralToActorMatrix, whose origin
    is zero, so no translation is applied here."""
    scale = {"IN": CM_PER_IN, "M": CM_PER_M, "FT": CM_PER_FT}.get(unit.upper())
    if scale is None:
        raise ConvertError(
            f"<location unit={unit!r}> is not a unit this converter reads "
            f"(IN, FT, M); refusing to guess the scale of the mesh origin")
    x, y, z = point
    # + 0.0 turns a -0.0 (x = 0 negated) into 0.0 for the JSON.
    return (-x * scale + 0.0, y * scale, z * scale)


def _body_to_actor_cm(body_m: Tuple[float, float, float],
                      cg_structural_in: Tuple[float, float, float]
                      ) -> Tuple[float, float, float]:
    """The labels' body frame (metres about the CG: x forward, y right,
    z DOWN; ``core/capture/airframe.py``) -> UE actor frame, cm.

    body = ((cg_x - x) in, (y - cg_y) in, (cg_z - z) in) * 0.0254, so the
    structural point is (cg_x - fwd/0.0254, cg_y + right/0.0254,
    cg_z - down/0.0254) and the plugin's (-x, y, z) map gives
    actor_cm = CG_actor_cm + (fwd, right, -down) * 100.
    """
    cg_actor = _structural_to_actor_cm(cg_structural_in, "IN")
    fwd, right, down = body_m
    # Rounded to 1e-6 cm: the two unit conversions leave 1e-13 residue
    # on points that are exactly on the datum (a nose at x = 0).
    return (round(cg_actor[0] + fwd * CM_PER_M, 6) + 0.0,
            round(cg_actor[1] + right * CM_PER_M, 6) + 0.0,
            round(cg_actor[2] - down * CM_PER_M, 6) + 0.0)


def fdm_vrp_actor_cm(xml_path: Path) -> Tuple[float, float, float]:
    """The FDM's visual reference point in the UE actor frame, cm.

    Recorded in every manifest for reference (``vrp_actor_cm``) and used
    as the z anchor where no gear geometry is identifiable, and as the
    whole origin for a config with no labels. Read from the XML's
    ``<metrics><location name="VRP">`` in its stated unit (JSBSim's
    default is inches). REFUSES, by name, an FDM with no VRP: the
    alternative is (0, 0, 0), which puts the mesh on the structural
    datum -- the measured 25-30 m offset this field exists to remove.
    """
    xml_path = Path(xml_path)
    if not xml_path.is_file():
        raise ConvertError(f"FDM XML {xml_path} does not exist; no VRP to "
                           f"place the mesh by")
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as exc:
        raise ConvertError(f"FDM XML {xml_path} unreadable: {exc}") from exc
    metrics = root.find("metrics")
    vrp = None
    if metrics is not None:
        for loc in metrics.findall("location"):
            if loc.get("name") == "VRP":
                vrp = loc
                break
    if vrp is None:
        raise ConvertError(
            f"REFUSING to place the mesh: {xml_path.name} carries no "
            f"<metrics><location name=\"VRP\">, so the point the "
            f"FlightGear model was built about is unknown. A mesh attached "
            f"at a guessed origin is drawn at the wrong place under a "
            f"correct label; state the VRP in the FDM before converting.")
    try:
        point = tuple(float(vrp.find(axis).text) for axis in ("x", "y", "z"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ConvertError(
            f"{xml_path.name}: the VRP location lacks a numeric x, y, z "
            f"({exc})") from exc
    return _structural_to_actor_cm(point, vrp.get("unit", "IN"))


def _model_origin_offset_actor_cm(config: Dict) -> Tuple[float, float, float]:
    """The config's optional ``model_origin_offset_m`` (UE actor frame,
    metres; default zero) in centimetres. A malformed value refuses:
    a silently dropped offset would place the mesh by the measurement
    alone while the config says otherwise."""
    raw = config.get("model_origin_offset_m", (0.0, 0.0, 0.0))
    if (not isinstance(raw, (list, tuple)) or len(raw) != 3
            or not all(isinstance(v, (int, float)) and math.isfinite(v)
                       for v in raw)):
        raise ConvertError(
            f"model_origin_offset_m must be three finite numbers (UE actor "
            f"frame, metres), not {raw!r}")
    return tuple(float(v) * CM_PER_M for v in raw)


def _gear_patterns(config: Dict) -> Tuple[List[str], List[str]]:
    """The config's documented ``gear_geometry`` patterns: (part-file
    patterns, object-name patterns), each full-match regexes. Absent ->
    two empty lists (no gear identifiable). Malformed -> refuse: a
    dropped pattern would silently move the z anchor to the VRP."""
    raw = config.get("gear_geometry")
    if raw is None:
        return [], []
    if not isinstance(raw, dict):
        raise ConvertError(
            f"gear_geometry must be an object with 'parts' and/or 'objects' "
            f"pattern lists, not {raw!r}")
    out = []
    for key in ("parts", "objects"):
        patterns = raw.get(key, [])
        if (not isinstance(patterns, list)
                or not all(isinstance(p, str) for p in patterns)):
            raise ConvertError(
                f"gear_geometry.{key} must be a list of regex strings, not "
                f"{patterns!r}")
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConvertError(
                    f"gear_geometry.{key} pattern {pattern!r} does not "
                    f"compile: {exc}") from exc
        out.append(list(patterns))
    return out[0], out[1]


def _component_parts(config: Dict) -> Dict[str, str]:
    """Component id -> OBJ stem (``SM_<aircraft>_<id>``, the one name
    core.capture.objects.component_mesh_name states for the converter,
    the card and the engine) for every ``parts[]`` entry carrying a
    ``component`` key. No such key anywhere -> {} and the converter's
    output is byte-for-byte the pre-component one. A part that names a
    component ``labels.components`` does not declare as payload, or one
    named by two parts, is refused: the picture would carry a store the
    physics does not, the disagreement C1 forbids."""
    declared = {c.get("id"): c for c in
                ((config.get("labels") or {}).get("components") or [])
                if isinstance(c, dict)}
    out: Dict[str, str] = {}
    for part in config.get("parts", []):
        if "component" not in part:
            continue
        cid = part["component"]
        if not isinstance(cid, str) or not cid:
            raise ConvertError(
                f"parts[] entry {part.get('file')!r} has a component key that "
                f"is not a non-empty string: {cid!r}")
        if cid in out:
            raise ConvertError(
                f"component {cid!r} is named by two parts[] entries; one OBJ "
                f"per component, so the second is refused")
        entry = declared.get(cid)
        if entry is None or entry.get("class") != "payload":
            raise ConvertError(
                f"parts[] entry {part.get('file')!r} names component {cid!r}, "
                f"which labels.components does not declare as payload "
                f"(declared: {sorted(k for k in declared if k)}); a drawn "
                f"store must be a declared payload component",
                constraint="aircraft.component_unmatched")
        out[cid] = component_mesh_name(str(config["name"]), cid)
    return out


def _component_records(component_parts: Dict[str, str], airframe,
                       writers: Dict[str, "ObjWriter"], counts: Dict[str, int],
                       component_extents: Dict[str, "MeshExtents"],
                       out_dir: Path, name: str,
                       mesh_origin_cm: Tuple[float, float, float]) -> List[Dict]:
    """One ``components[]`` row and one OBJ per component part, the
    fields C2's MDL converter writes and C3's card reads: ``id`` (the bare
    config id), ``class``, ``station``, ``part`` (the OBJ stem and asset
    name), ``asset_path``, ``triangles``, ``mesh_extent_actor_m`` (actor
    frame, metres, about the model origin like the body's),
    ``mesh_origin_actor_cm`` (the body's) and ``mass_lb`` from the
    labelled airframe's matching component."""
    if not component_parts:
        return []
    if airframe is None:
        raise ConvertError(
            "parts[] name components but the config has no labels block to "
            "match them against")
    labelled = {c.id: c for c in airframe.components}
    records: List[Dict] = []
    for cid, stem in component_parts.items():
        component = labelled.get(cid)
        if component is None:
            raise ConvertError(
                f"component {cid!r} is not among the labelled airframe's "
                f"components ({sorted(labelled)})",
                constraint="aircraft.component_unmatched")
        if counts[stem] == 0:
            raise ConvertError(
                f"component {cid!r} ({stem}): its part drew no geometry, so "
                f"the store the physics carries would not be shown",
                constraint="aircraft.component_unmatched")
        writers[stem].write(out_dir / f"{stem}.obj")
        extent = component_extents[stem].to_manifest()["mesh_extent_actor_m"]
        records.append({
            "id": cid,
            "class": component.cls,
            "station": component.station,
            "part": stem,
            "asset_path": f"/Game/Aircraft/{name}/{stem}",
            "triangles": counts[stem],
            "vertices": int(component_extents[stem].count),
            "model_vars": {},
            "mesh_extent_actor_m": extent,
            "mesh_origin_actor_cm": list(mesh_origin_cm),
            "mass_lb": component.mass_lb,
        })
    return records


def _gear_component(config: Dict) -> Optional[Dict]:
    """The config's ONE declared ``landing_gear`` component
    (``labels.components``, class ``landing_gear``) when it declares exactly
    one, else None. The gear split (every wheel, strut and brake the
    ``gear_geometry`` patterns match into one ``SM_<aircraft>_<id>`` OBJ
    and a manifest row) applies only to that single-component shape (the
    c172p). Two or more landing_gear components are the C1/C3 per-leg
    pattern (the A-4's and the J-11A's ``nose_gear`` / ``left_main_gear`` /
    ``right_main_gear``, ``mesh: null``): no split, the gear stays in the
    body OBJ and no gear row is written (decision in notes/C7.md "align").
    A malformed block refuses, because a silently ignored gear entry would
    leave the gear in the body OBJ with no box of its own."""
    declared = (config.get("labels") or {}).get("components")
    if declared is None:
        return None
    if not isinstance(declared, list):
        raise ConvertError("labels.components must be a list of component "
                           "objects", constraint="aircraft.component_unmatched")
    gear = [c for c in declared
            if isinstance(c, dict) and c.get("class") == "landing_gear"]
    if len(gear) != 1:
        return None     # none, or per-leg declarations: the gear stays in the body
    if not gear[0].get("id"):
        raise ConvertError("the landing_gear component has no id",
                           constraint="aircraft.component_unmatched")
    return gear[0]


def _gear_component_row(extents_gear: "MeshExtents", config: Dict,
                        mesh_origin_cm: Tuple[float, float, float],
                        triangles: int) -> Dict:
    """The mesh manifest ``components[]`` row for the gear OBJ, in the
    shape the A-4 payload rows use: ``id`` (the C1 id, the shared key),
    ``class``, ``part`` (the OBJ stem and asset name), ``asset_path``,
    ``triangles``, ``mesh_extent_actor_m`` (the gear vertices' box, metres,
    actor frame, about the MODEL origin, the top-level shape so
    ``hull_box_body_m({**manifest, **row})`` works) and
    ``mesh_origin_actor_cm`` (the body's: the gear OBJ shares the body's
    vertex frame and is attached at the same point)."""
    component = _gear_component(config)
    if component is None:
        raise ConvertError("no landing_gear component declared; no gear row")
    if extents_gear.count == 0:
        raise ConvertError(
            f"landing_gear component {component['id']!r} matched no geometry: "
            f"the gear_geometry patterns {_gear_patterns(config)} name no "
            f"drawn vertex, so a gear OBJ would be empty; refusing")
    name = config["name"]
    part = component_mesh_name(name, str(component["id"]))
    return {
        "id": str(component["id"]),
        "class": "landing_gear",
        "station": None,
        "part": part,
        "asset_path": f"/Game/Aircraft/{name}/{part}",
        "triangles": int(triangles),
        "vertices": int(extents_gear.count),
        "model_vars": {},
        "mesh_extent_actor_m": extents_gear.to_manifest()["mesh_extent_actor_m"],
        "mesh_origin_actor_cm": list(mesh_origin_cm),
        "mass_lb": 0.0,
    }


class MeshExtents:
    """Running extents of the DRAWN vertices in the actor frame, cm,
    about the model's own origin -- every vertex a written triangle
    references, after the config's exclusions and the glass drop, so the
    numbers describe the geometry that reaches a frame and nothing else.
    ``gear_lowest_cm`` is the lowest z over vertices of gear-matched
    parts/objects, or None when none matched."""

    def __init__(self) -> None:
        self.count = 0
        self.gear_count = 0
        self.min = [math.inf, math.inf, math.inf]
        self.max = [-math.inf, -math.inf, -math.inf]
        self.gear_lowest_cm: Optional[float] = None

    def add(self, point_cm: Tuple[float, float, float], gear: bool) -> None:
        self.count += 1
        for axis in range(3):
            v = point_cm[axis]
            if v < self.min[axis]:
                self.min[axis] = v
            if v > self.max[axis]:
                self.max[axis] = v
        if gear:
            self.gear_count += 1
            if self.gear_lowest_cm is None or point_cm[2] < self.gear_lowest_cm:
                self.gear_lowest_cm = point_cm[2]

    @property
    def nose_cm(self) -> float:
        return self.max[0]

    @property
    def tail_cm(self) -> float:
        return self.min[0]

    @property
    def lowest_cm(self) -> float:
        return self.min[2]

    @property
    def length_m(self) -> float:
        return (self.max[0] - self.min[0]) / CM_PER_M

    def to_manifest(self) -> Dict:
        return {
            "mesh_extents_actor_cm": {
                "nose": self.nose_cm, "tail": self.tail_cm,
                "lowest": self.lowest_cm, "gear_lowest": self.gear_lowest_cm,
            },
            "mesh_extent_actor_m": {
                "x": [self.min[0] / CM_PER_M, self.max[0] / CM_PER_M],
                "y": [self.min[1] / CM_PER_M, self.max[1] / CM_PER_M],
                "z": [self.min[2] / CM_PER_M, self.max[2] / CM_PER_M],
            },
            "mesh_length_m": self.length_m,
            "vertices_measured": self.count,
            "gear_vertices_measured": self.gear_count,
        }


def _labelled_airframe(config: Dict, config_path: Path):
    """The labels' airframe for this config, None when the config has no
    ``labels`` block (nothing to align to: the VRP fallback applies), a
    named refusal when it has one the labeller cannot resolve -- a
    labelled airframe whose labels do not load would fail at capture
    time anyway, and a mesh placed by a guess under such a label is the
    failure this measurement exists to prevent."""
    if not isinstance(config.get("labels"), dict):
        return None
    try:
        return airframe_module.load_airframe(config_path.stem,
                                             config_dir=config_path.parent)
    except airframe_module.AirframeLabelError as exc:
        raise ConvertError(
            f"REFUSING to place the mesh: the labels of {config_path.name} "
            f"do not load ({exc.message}); the nose keypoint the mesh must "
            f"be aligned to is unknown", constraint=exc.constraint) from exc


def _extent_disagreement_cause(extents: MeshExtents, labels_length_m: float
                               ) -> str:
    """Which of the three explanations for a mesh whose span is not the
    labelled length is likeliest, stated for the refusal message."""
    ratio = extents.length_m / labels_length_m if labels_length_m > 0 else math.inf
    units = {39.3701: "inches per metre", 3.28084: "feet per metre",
             100.0: "centimetres per metre", 1 / 39.3701: "metres per inch",
             1 / 3.28084: "metres per foot", 0.01: "metres per centimetre"}
    for factor, words in units.items():
        if abs(ratio / factor - 1.0) <= MESH_EXTENT_TOLERANCE:
            return (f"a wrong unit: the mesh span is {ratio:.2f} x the labelled "
                    f"length, i.e. {words}")
    span_y = (extents.max[1] - extents.min[1]) / CM_PER_M
    span_z = (extents.max[2] - extents.min[2]) / CM_PER_M
    for axis, span in (("y", span_y), ("z", span_z)):
        if span > 0 and abs(span / labels_length_m - 1.0) <= MESH_EXTENT_TOLERANCE:
            return (f"a wrong frame: the mesh's {axis} span ({span:.2f} m) is "
                    f"the labelled length, so the .ac -> model axis map "
                    f"does not hold for this model")
    return ("a wrong mesh: the geometry converted (parts, exclusions, "
            "the pinned commit) is not the airframe the labels describe")


def measure_mesh_origin(extents: MeshExtents, airframe,
                        vrp_actor_cm: Tuple[float, float, float],
                        name: str) -> Tuple[Tuple[float, float, float], Dict]:
    """The mesh origin in the actor frame, cm, BEFORE the config's offset,
    with the record of how it was measured.

    Returns ``(origin, record)`` where ``record`` carries
    ``mesh_origin_basis``, ``origin_anchor`` and ``origin_measurement``.
    Raises ``ConvertError(constraint="aircraft.mesh_extent")`` when the
    mesh span and the labelled length disagree beyond the tolerance.
    ``airframe`` None (no labels block) -> the VRP rule, said so.
    """
    measurement: Dict = {
        "nose_keypoint": None, "main_gear_contact": None,
        "mesh_nose_cm": extents.nose_cm, "mesh_tail_cm": extents.tail_cm,
        "gear_lowest_cm": extents.gear_lowest_cm,
        "vrp_actor_cm": list(vrp_actor_cm),
    }
    if airframe is None:
        record = {
            "mesh_origin_basis": MESH_ORIGIN_BASIS_VRP.format(
                reason="no labels block in the config: nose keypoint "
                       "unavailable, mesh extent unchecked"),
            "origin_anchor": {"x": "vrp", "z": "vrp"},
            "origin_measurement": measurement,
            "labels_length_m": None,
        }
        return tuple(vrp_actor_cm), record

    labels_length_m = float(airframe.length_m)
    measurement["labels_length_m"] = labels_length_m
    deviation = abs(extents.length_m - labels_length_m) / labels_length_m
    measurement["length_deviation"] = deviation
    if deviation > MESH_EXTENT_TOLERANCE:
        raise ConvertError(
            f"the converted {name} mesh spans "
            f"{extents.length_m:.2f} m nose to tail in the actor frame "
            f"(x {extents.tail_cm / CM_PER_M:.2f} .. {extents.nose_cm / CM_PER_M:.2f} m "
            f"about the model origin) but labels.dimensions_m.length says "
            f"{labels_length_m:.2f} m -- {deviation:.1%} off, tolerance "
            f"{MESH_EXTENT_TOLERANCE:.0%}. Likeliest: "
            f"{_extent_disagreement_cause(extents, labels_length_m)}. The "
            f"mesh is then not the airframe the labels describe, and "
            f"model_origin_offset_m cannot fix it.",
            constraint="aircraft.mesh_extent")

    nose = airframe.keypoints.get("nose")
    if nose is None:
        record = {
            "mesh_origin_basis": MESH_ORIGIN_BASIS_VRP.format(
                reason="the labels carry no nose keypoint; the mesh extent "
                       "was checked"),
            "origin_anchor": {"x": "vrp", "z": "vrp"},
            "origin_measurement": measurement,
            "labels_length_m": labels_length_m,
        }
        return tuple(vrp_actor_cm), record

    nose_actor_cm = _body_to_actor_cm(nose.body_m, airframe.cg_structural_in)
    measurement["nose_keypoint"] = {
        "name": "nose", "basis": nose.basis, "source": nose.source,
        "body_m": list(nose.body_m), "actor_cm": list(nose_actor_cm),
    }
    origin_x = nose_actor_cm[0] - extents.nose_cm  # the measured rule (x)

    # The lower of the two main-gear contacts, where the labels have them
    # from the FDM's own <contact> elements (basis "fdm").
    mains = [(n, airframe.keypoints[n]) for n in ("left_main_gear", "right_main_gear")
             if n in airframe.keypoints and airframe.keypoints[n].basis == "fdm"]
    z_reason = None
    if not mains:
        z_reason = "the labels name no main-gear FDM contact"
    elif extents.gear_lowest_cm is None:
        z_reason = "no gear geometry identifiable in the model (no gear_geometry patterns matched)"
    if z_reason is None:
        contact_name, contact = max(mains, key=lambda item: item[1].body_m[2])  # largest "down"
        contact_actor_cm = _body_to_actor_cm(contact.body_m, airframe.cg_structural_in)
        gear_contact_z_cm = contact_actor_cm[2]
        measurement["main_gear_contact"] = {
            "name": contact_name, "source": contact.source,
            "body_m": list(contact.body_m), "actor_cm": list(contact_actor_cm),
        }
        origin_z = gear_contact_z_cm - extents.gear_lowest_cm  # the measured rule (z)
        basis = MESH_ORIGIN_BASIS_MEASURED
        z_anchor = "main-gear contact"
    else:
        origin_z = vrp_actor_cm[2]
        basis = MESH_ORIGIN_BASIS_MEASURED_X_ONLY.format(reason=z_reason)
        z_anchor = "vrp"
    record = {
        "mesh_origin_basis": basis,
        "origin_anchor": {"x": f"nose keypoint ({nose.basis})", "z": z_anchor},
        "origin_measurement": measurement,
        "labels_length_m": labels_length_m,
    }
    return (round(origin_x, 4) + 0.0, 0.0, round(origin_z, 4) + 0.0), record


# -- the package beyond the airframe .ac (j11-package lane, 2026-11-09) -------
#
# Three optional config keys bring more of an upstream FlightGear package
# into the conversion, each checked against the pinned bytes first
# (assets_pipeline/package_pins.py, ``package_files``):
#
# * ``livery`` -- the model XML's livery: FlightGear's ``<animation><type>
#   material</type>`` swaps the texture of NAMED objects for the livery
#   PNG (J-11A.xml: the hull, canopy frame, speedbrake, flaperons, elevons
#   and rudders take Liveries/<name>.png; every other object keeps the
#   .ac's own texture). The converter does the same swap, object by
#   object, so the drawn texture is the one the package's model XML draws.
# * parts[] rows with ``"interior": true`` -- cockpit interior, seat and
#   pilot (sub-models the model XML places with ``<offsets>``; the summed
#   offset is ``offset_m`` and the pitch ``pitch_deg``). They are written
#   into the BODY part, so they take the aircraft's class and int_id with
#   every other primitive of the aircraft actor (the commandlet's stencil
#   loop) and no new component box exists. They do not move the measured
#   nose / tail / gear anchors (kept out of ``extents``), and each vertex
#   must lie inside the hull's own extents: one outside refuses
#   (``aircraft.interior_outside_hull``), because it would grow the drawn
#   silhouette beyond the airframe the labels measure.
# * ``views`` -- package viewpoints (the -set.xml pilot eye), mapped to the
#   actor frame for the camera; recorded only, nothing is drawn from them.

#: An interior vertex may sit this far outside the hull's extents (cm)
#: before it refuses: rounding of the .ac's own 4-6 decimals.
INTERIOR_HULL_TOLERANCE_CM = 1.0


def _pitch_model(v: Tuple[float, float, float],
                 pitch_deg: float) -> Tuple[float, float, float]:
    """A FlightGear ``<offsets><pitch-deg>`` rotation of a sub-model about
    its own origin, in the FG model frame (+x aft, +y right, +z up), taken
    as nose-up positive (a forward point, -x, rises): the right-handed
    rotation about +y. [unverified here: the sign is FlightGear's
    convention as remembered, not measured; the only use is the seat's
    -5 deg.]"""
    if not pitch_deg:
        return v
    t = math.radians(pitch_deg)
    x, y, z = v
    return (x * math.cos(t) + z * math.sin(t), y,
            -x * math.sin(t) + z * math.cos(t))


def _livery(config: Dict) -> Optional[Dict]:
    """The config's ``livery`` block, checked for shape, or None."""
    livery = config.get("livery")
    if not livery:
        return None
    missing = [k for k in ("name", "texture", "replaces", "part", "objects", "source")
               if not livery.get(k)]
    if missing:
        raise ConvertError(f"livery lacks {missing}", constraint="aircraft.livery_unmatched")
    return livery


#: Written beside the OBJs: which FlightGear (.ac) materials each MTL
#: material was made from, with their specular / shininess, so the beauty
#: look (scripts/aircraft_look.py) can derive a roughness from the package
#: instead of a guess. The MTL itself is NOT given Ks / Ns: Interchange
#: reads the MTL for the measured path's own instances, which stay as
#: they were.
MATERIAL_SOURCES_NAME = "material_sources.json"
MATERIAL_SOURCES_MAGIC = "flightsim-aircraft-material-sources"


def _record_material_source(sources: Dict[str, Dict], key: str, texture_rel,
                            material, part_file: str, object_name: str,
                            triangles: int) -> None:
    row = sources.setdefault(key, {"texture": texture_rel, "ac_materials": {},
                                   "objects": set()})
    row["objects"].add(f"{part_file}:{object_name}")
    if material is None:
        name, values = "(none)", {"rgb": [0.8, 0.8, 0.8], "specular": [0.0, 0.0, 0.0],
                                   "shininess": 0.0, "transparency": 0.0}
    else:
        name = f"{part_file}:{material.name}"
        values = {"rgb": list(material.rgb), "specular": list(material.specular),
                  "shininess": float(material.shininess),
                  "transparency": float(material.transparency)}
    entry = row["ac_materials"].setdefault(name, {**values, "triangles": 0})
    entry["triangles"] += triangles


def _material_sources_out(sources: Dict[str, Dict]) -> Dict:
    return {
        "magic": MATERIAL_SOURCES_MAGIC, "version": 1,
        "note": "per MTL material: the .ac MATERIAL rows (rgb, spec, shi, trans) "
                "its triangles came from, with triangle counts; the texture as a "
                "package path (after the livery swap)",
        "materials": {key: {"texture": row["texture"],
                            "ac_materials": row["ac_materials"],
                            "objects": sorted(row["objects"])}
                      for key, row in sources.items()},
    }


def _interior_record(rows: List[Dict], interior: "MeshExtents",
                     hull: "MeshExtents") -> Optional[Dict]:
    """The manifest's ``interior`` block; refuses an interior vertex
    outside the hull's extents."""
    if not rows:
        return None
    if interior.count == 0:
        raise ConvertError("the interior parts drew no geometry",
                           constraint="aircraft.interior_outside_hull")
    outside = []
    for axis, label in enumerate("xyz"):
        if interior.min[axis] < hull.min[axis] - INTERIOR_HULL_TOLERANCE_CM:
            outside.append(f"{label} {interior.min[axis] / CM_PER_M:.3f} m below the hull's "
                           f"{hull.min[axis] / CM_PER_M:.3f} m")
        if interior.max[axis] > hull.max[axis] + INTERIOR_HULL_TOLERANCE_CM:
            outside.append(f"{label} {interior.max[axis] / CM_PER_M:.3f} m above the hull's "
                           f"{hull.max[axis] / CM_PER_M:.3f} m")
    if outside:
        raise ConvertError(
            "an interior part reaches outside the hull's extents (" + "; ".join(outside)
            + "): it would grow the drawn silhouette past the airframe the labels "
              "measure", constraint="aircraft.interior_outside_hull")
    return {
        "parts": rows,
        "drawn_in": "body",
        "label": ("drawn in the body part: the aircraft's class and int_id (the "
                  "commandlet stencils every primitive of the aircraft actor), no "
                  "component, no box of its own; inside the hull's extents, so the "
                  "measured nose / tail / gear anchors and the extremes the look "
                  "lamps snap to are the hull's alone"),
        "extent_actor_m": {
            "x": [interior.min[0] / CM_PER_M, interior.max[0] / CM_PER_M],
            "y": [interior.min[1] / CM_PER_M, interior.max[1] / CM_PER_M],
            "z": [interior.min[2] / CM_PER_M, interior.max[2] / CM_PER_M],
        },
        "vertices": interior.count,
    }


def _view_records(config: Dict, mesh_origin_cm) -> Dict[str, Dict]:
    """Each ``views`` entry with its point in the UE actor frame (cm)."""
    out = {}
    for name, view in (config.get("views") or {}).items():
        point = tuple(float(v) for v in view["model_m"])
        ue = model_to_ue(point)
        out[name] = {
            **view,
            "actor_cm": [round(ue[i] * CM_PER_M + mesh_origin_cm[i], 2) + 0.0
                         for i in range(3)],
            "frame": "UE actor frame, cm, about the JSBSim structural datum "
                     "(model_m mapped by model_to_ue, plus mesh_origin_actor_cm)",
        }
    return out


#: The part a body's beauty-only copy is written as (round 2,
#: cockpit-airframe lane). NOT in the manifest's ``parts``: the commandlet
#: attaches every part it lists, so a listed copy would draw the body twice.
BEAUTY_BODY_PART = "body_beauty"


def _beauty_mesh_config(config: Dict) -> Optional[Dict]:
    """The config's ``beauty_mesh`` block, or None (no beauty copy)."""
    block = config.get("beauty_mesh")
    if not block:
        return None
    if block.get("normals") != "crease":
        raise ConvertError(f"beauty_mesh.normals {block.get('normals')!r} is not 'crease'")
    for field in ("flip_objects", "hide_objects"):
        patterns = block.get(field, [])
        if not isinstance(patterns, list) or not all(isinstance(p, str) and p for p in patterns):
            raise ConvertError(f"beauty_mesh.{field} {patterns!r} is not a list of object-name "
                               f"patterns")
    return block


def _beauty_part_name(part: str) -> str:
    """The beauty-only copy of a measured part: ``body`` -> ``body_beauty``,
    ``propeller`` -> ``propeller_beauty``."""
    return f"{part}_beauty"


def _write_beauty_mesh(rows: List[tuple], block: Dict, body_writer: "ObjWriter",
                       out_dir: Path) -> Dict:
    """``body_beauty.obj``: the body's triangles, same positions, same UVs,
    same materials in the same first-use order, with vertex normals by the
    .ac crease angle (assets_pipeline/smooth_normals.py) and, when
    ``two_sided``, a back face for every AC3D two-sided surface (SURF 0x20:
    FlightGear draws both sides; the measured body draws one, so from the
    pilot's eye the canopy frame and the cockpit tub, seen from inside,
    are culled away). Beauty only: the commandlet swaps it onto the body
    component on a -quality=beauty render (FlightSimAircraftFX.cpp
    ApplyMaterials), so the label silhouette, the depth and every
    -quality=measure frame are those of ``body``.

    ``flip_objects`` (full-match patterns over the .ac object names): those
    objects' triangles are written facing the other way, with no back face.
    For an inner glass shell modelled facing the cabin (the c172p's
    glas_interior, 3 mm inside the windshield; round 1 web scene 12,
    2026-11-10): every aircraft glass slot draws the OPAQUE M_AircraftGlass
    on a beauty render, so a shell facing the cabin is a dark slab across
    the cockpit view. Flipped it faces out, is culled from the pilot's eye
    and sits behind the windshield's own glass from outside; same
    positions, same slots, so the silhouette and the slot match hold.

    ``hide_objects`` (full-match patterns): those objects' triangles are
    not written at all (round 2 scene 12, 2026-11-10: the c172p's static
    PropellerCowlPlugs blade, which FlightGear selects only while the cowl
    plugs are fitted, stood still across the cockpit view of a running
    engine). See :func:`_write_beauty_part`."""
    return {"body": _write_beauty_part(rows, block, body_writer, out_dir, "body")}


def _write_beauty_surfaces(surface_rows: Optional[Dict[str, List[tuple]]], block: Dict,
                           writers: Dict[str, "ObjWriter"], out_dir: Path) -> Dict:
    """A ``<surface>_beauty`` copy (:func:`_write_beauty_part`) of each
    control surface that ``beauty_mesh.hide_objects`` takes an object out
    of; a surface it takes nothing from has no copy and draws its measured
    part as before. The manifest rows, by surface."""
    out = {}
    patterns = list(block.get("hide_objects", []))
    for surface, rows in sorted((surface_rows or {}).items()):
        if any(_matches(r[6], patterns) for r in rows):
            out[surface] = _write_beauty_part(rows, block, writers[surface], out_dir, surface)
    return out


def _check_hide_objects(block: Optional[Dict], seen_names: Sequence[str]) -> None:
    """Every ``beauty_mesh.hide_objects`` pattern must name a converted
    object: a pattern that matches nothing hides nothing, silently."""
    if not block:
        return
    for pattern in block.get("hide_objects", []):
        if not any(re.fullmatch(pattern, name) for name in seen_names):
            raise ConvertError(f"beauty_mesh.hide_objects pattern {pattern!r} matches no "
                               f"converted object of the body or a control surface")


def _write_beauty_part(rows: List[tuple], block: Dict, measured_writer: "ObjWriter",
                       out_dir: Path, part: str) -> Dict:
    """``<part>_beauty.obj`` from the measured part's rows (key, tri,
    object serial, smooth, crease, two-sided, object name): crease
    normals, ``two_sided`` back faces, ``flip_objects`` turned and
    ``hide_objects`` left out (see :func:`_write_beauty_mesh`). Its manifest
    row. Refused by name when a hidden object would leave one of the
    measured part's slots with no triangle: the commandlet swaps a copy in
    only when its slots are the measured part's, name for name, so that
    copy would never be drawn.

    A hidden object is out of the beauty frame AND out of that frame's
    label masks (the label captures draw the swapped component), so the
    labels keep matching the pixels; every -quality=measure frame and its
    labels draw the measured part, which keeps the object."""
    flip_patterns = list(block.get("flip_objects", []))
    hide_patterns = list(block.get("hide_objects", []))
    hidden_rows = [r for r in rows if hide_patterns and _matches(r[6] if len(r) > 6 else "",
                                                                 hide_patterns)]
    kept = [r for r in rows if not (hide_patterns and _matches(r[6] if len(r) > 6 else "",
                                                               hide_patterns))]
    triangles = [tuple(position for position, _ in row[1]) for row in kept]
    normals = vertex_normals_actor(triangles, [r[2] for r in kept], [r[3] for r in kept],
                                   [r[4] for r in kept])
    writer = ObjWriter()
    # The measured part's materials in its order, so the slots line up.
    writer.materials = dict(measured_writer.materials)
    for key in measured_writer.faces:
        writer.faces[key] = []
    emptied = sorted({r[0] for r in hidden_rows} - {r[0] for r in kept})
    if emptied:
        raise ConvertError(
            f"beauty_mesh.hide_objects leaves {part} slot(s) {emptied} with no triangle; the "
            f"beauty copy's slots would not be the measured part's and it would never be "
            f"swapped in")
    two_sided = bool(block.get("two_sided"))
    back_faces = 0
    flipped_faces = 0
    for row, corner_normals in zip(kept, normals):
        key, tri, sided = row[0], row[1], row[5]
        name = row[6] if len(row) > 6 else ""
        if flip_patterns and _matches(name, flip_patterns):
            writer.add_triangle(key, [tri[0], tri[2], tri[1]],
                                [flipped(corner_normals[0]), flipped(corner_normals[2]),
                                 flipped(corner_normals[1])])
            flipped_faces += 1
            continue
        writer.add_triangle(key, tri, corner_normals)
        if two_sided and sided:
            writer.add_triangle(key, [tri[0], tri[2], tri[1]],
                                [flipped(corner_normals[0]), flipped(corner_normals[2]),
                                 flipped(corner_normals[1])])
            back_faces += 1
    beauty_part = _beauty_part_name(part)
    writer.write(out_dir / f"{beauty_part}.obj")
    smooth = sum(1 for r in kept if r[3])
    row = {
        "part": beauty_part,
        "triangles": len(kept) + back_faces,
        "front_triangles": len(kept),
        "back_faces": back_faces,
        "flipped_faces": flipped_faces,
        "smooth_triangles": smooth,
        "flat_triangles": len(kept) - smooth,
        "normals": "per corner, by each .ac object's crease angle over its smooth "
                   "(SURF 0x10) faces; flat faces keep their face normal",
        "drawn_in": f"beauty only: swapped onto the {part} component on -quality=beauty "
                    f"(FlightSimAircraftFX ApplyMaterials); same positions as {part}, so "
                    f"mask, depth and every measure frame are {part}'s",
        "source": block.get("source", ""),
    }
    if hide_patterns:
        row["hidden_faces"] = len(hidden_rows)
        row["hidden_objects"] = sorted({r[6] for r in hidden_rows})
        if hidden_rows:
            row["drawn_in"] = (
                f"beauty only: swapped onto the {part} component on -quality=beauty "
                f"(FlightSimAircraftFX ApplyMaterials); same positions as {part} less the "
                f"hidden objects, which the beauty frame's label masks (drawn from the "
                f"swapped component) leave out with it; every measure frame and its "
                f"labels are {part}'s")
    return row


def vertex_normals_actor(triangles, groups, smooth, crease):
    """:func:`assets_pipeline.smooth_normals.vertex_normals` for triangles
    in the UE actor frame (cm, left-handed) wound as ObjWriter stores them:
    computed in the OBJ's right-handed frame on the WRITTEN winding (the
    normal Interchange reads), returned per stored corner in the actor
    frame, which ObjWriter.write maps back with actor_to_obj."""
    obj_tris = [tuple(actor_to_obj(p) for p in obj_winding(tri)) for tri in triangles]
    obj_normals = vertex_normals(obj_tris, groups, smooth, crease, unit_m=0.01)
    return [tuple(actor_to_obj(n) for n in obj_winding(corners)) for corners in obj_normals]


#: Prefix of a textured material's name. NOT "tex_": Interchange names the
#: texture asset of ``map_Kd wings_texture.png`` "TEX_wings_texture", UE
#: asset names are case-insensitive, so a material "tex_wings_texture"
#: collided with its own texture and was renamed on import (measured
#: 2026-10-05 on the A320, UE 5.7: tex_A320 -> tex_A3201, and the
#: commandlet then died in the content browser with no Slate app).
TEXTURED_MATERIAL_PREFIX = "mat_"


def power_of_two(n: int) -> int:
    """The power of two nearest ``n`` (ties go up)."""
    lower = 1 << (max(1, n).bit_length() - 1)
    return lower if n - lower < lower * 2 - n else lower * 2


def copy_texture(source: Path, destination: Path) -> Tuple[int, int]:
    """Copy a texture, resampled to power-of-two sides when it is not.

    UE's texture import refuses other sizes ("Cannot import texture with
    non-power of two dimensions", measured 2026-10-05 on the A320 sheets),
    and that refusal took the whole import commandlet down with it. UVs
    are normalised, so a resample keeps every mapping. A texture already
    power-of-two is copied byte for byte. Returns the written size.
    """
    from PIL import Image

    with Image.open(source) as image:
        size = image.size
        target = (power_of_two(size[0]), power_of_two(size[1]))
        if target == size:
            shutil.copyfile(source, destination)
            return size
        image.load()
        image.resize(target, Image.LANCZOS).save(destination, format="PNG")
        return target


class ObjWriter:
    """Accumulates triangles grouped by (texture, material colour), in the
    UE actor frame (cm, outward winding); :meth:`write` puts them in the
    OBJ frame of ``assets_pipeline/obj_frame.py`` (Y negated, faces
    rewound: decision 19), the same convention ``a4_mdl_convert`` writes."""

    def __init__(self) -> None:
        self.vertices: List[Tuple[float, float, float]] = []
        self.uvs: List[Tuple[float, float]] = []
        self.normals: List[Tuple[float, float, float]] = []
        self.faces: Dict[str, List[Tuple[Tuple[int, int], ...]]] = defaultdict(list)
        self.materials: Dict[str, Dict] = {}

    def material_key(self, texture: Optional[str], rgb, transparency: float) -> str:
        if texture:
            key = TEXTURED_MATERIAL_PREFIX + re.sub(r"[^A-Za-z0-9]+", "_", Path(texture).stem)
        else:
            key = "rgb_%02x%02x%02x" % tuple(int(max(0, min(1, c)) * 255) for c in rgb)
        if key not in self.materials:
            self.materials[key] = {
                "texture": texture, "rgb": tuple(rgb), "transparency": transparency,
            }
        return key

    def add_triangle(self, key: str, tri, normals=None) -> None:
        """``normals``: one unit normal per corner in the UE actor frame
        (the beauty mesh only); a writer given none writes no ``vn``, so
        the measured meshes' OBJs are byte-identical to before."""
        indices = []
        for corner, (vertex, uv) in enumerate(tri):
            self.vertices.append(vertex)
            self.uvs.append(uv)
            if normals is not None:
                self.normals.append(normals[corner])
                indices.append((len(self.vertices), len(self.uvs), len(self.normals)))
            else:
                indices.append((len(self.vertices), len(self.uvs)))
        self.faces[key].append(tuple(indices))

    def write(self, obj_path: Path, texture_dir_relative: str = "") -> None:
        mtl_path = obj_path.with_suffix(".mtl")
        with obj_path.open("w") as out:
            out.write(f"mtllib {mtl_path.name}\n")
            for v in self.vertices:
                out.write("v %.6f %.6f %.6f\n" % actor_to_obj(v))
            for uv in self.uvs:
                out.write("vt %.6f %.6f\n" % uv)
            for n in self.normals:
                out.write("vn %.6f %.6f %.6f\n" % actor_to_obj(n))
            for key, faces in self.faces.items():
                out.write(f"usemtl {key}\n")
                for face in faces:
                    out.write("f " + " ".join("/".join(str(i) for i in corner)
                                              for corner in obj_winding(face)) + "\n")
        with mtl_path.open("w") as out:
            for key, material in self.materials.items():
                out.write(f"newmtl {key}\n")
                r, g, b = material["rgb"]
                out.write(f"Kd {r:.4f} {g:.4f} {b:.4f}\n")
                if material["transparency"] > 0:
                    out.write(f"d {1.0 - material['transparency']:.3f}\n")
                if material["texture"]:
                    name = Path(material["texture"]).name
                    prefix = texture_dir_relative
                    out.write(f"map_Kd {prefix}{name}\n")
                out.write("\n")


def convert(config_path: Path, out_root: Path, repo_root: Path) -> Path:
    config_path = Path(config_path)
    config = json.loads(config_path.read_text())
    name = config["name"]
    source_dir = (config_path.parent / config["source_dir"]).resolve()

    # -- §1.4: the mesh must match the flown FDM ------------------------
    fdm_xml = repo_root / (
        "ue/Plugins/JSBSimFlightDynamicsModel/Resources/JSBSim/aircraft/"
        f"{config['fdm']}/{config['fdm']}.xml")
    if not fdm_xml.is_file():
        raise ConvertError(f"no staged FDM at {fdm_xml}")
    fdm_name = _fdm_config_name(fdm_xml)
    if fdm_name not in config["fdm_match"]:
        raise ConvertError(
            f"REFUSING the pairing: mesh '{name}' ({config['mesh_airframe']}) "
            f"against FDM '{config['fdm']}' whose <fdm_config> names itself "
            f"{fdm_name!r}, not one of {config['fdm_match']}. A mesh of one "
            f"aircraft flying the model of another is §1.4."
        )

    # -- the reference points the origin is measured against: the FDM's
    # VRP (reference, and the fallback), the labels' nose keypoint and
    # main-gear contacts (core/capture/airframe.py reads them out of the
    # same XML the labels are built from, so the drawn mesh and the label
    # share one source), and the config's documented offset -----------
    vrp_xml = fdm_xml_path(config["fdm"])
    vrp_actor_cm = fdm_vrp_actor_cm(vrp_xml)
    origin_offset_cm = _model_origin_offset_actor_cm(config)
    gear_part_patterns, gear_object_patterns = _gear_patterns(config)
    airframe = _labelled_airframe(config, config_path)

    # -- §3.3: license present on disk ---------------------------------
    # An airframe the owner cleared by name has no file to point at; its
    # clearance is the recorded basis, and it never claims a licence.
    owner_clearance = config["license"].get("owner_clearance")
    if owner_clearance:
        license_head = owner_clearance
    else:
        license_file = source_dir / config["license"]["file"]
        if not license_file.is_file():
            raise ConvertError(f"license file {license_file} does not exist")
        license_head = license_file.read_text(errors="replace").strip().splitlines()[0].strip()

    # -- every pinned package file is the pinned content ----------------
    try:
        package_rows = verify_package_pins(config, source_dir)
    except PackagePinError as exc:
        raise ConvertError(exc.message, constraint="aircraft.package_pin") from exc
    livery = _livery(config)
    livery_applied: Dict[str, int] = defaultdict(int)

    out_dir = out_root / name
    out_dir.mkdir(parents=True, exist_ok=True)

    exclude = config.get("exclude", [])
    surface_defs = config["surfaces"]
    claimed: Dict[str, str] = {}
    for surface_name, surface in surface_defs.items():
        for pattern in surface["objects"]:
            claimed[pattern] = surface_name

    # Payload components (parts[].component): each one its own writer and
    # its own extents, so a hung store neither joins the body OBJ nor
    # moves the body's measured nose/tail/gear anchors.
    component_parts = _component_parts(config)
    writers: Dict[str, ObjWriter] = {"body": ObjWriter()}
    for surface_name in surface_defs:
        writers[surface_name] = ObjWriter()
    for stem in component_parts.values():
        writers[stem] = ObjWriter()
    # C7: a declared landing_gear component takes the gear-matched
    # triangles (the same ``gear`` flag that anchors z) into its own OBJ;
    # with no component declared the gear stays in the body as before.
    gear_component = _gear_component(config)
    if gear_component is not None:
        writers["gear"] = ObjWriter()
    counts: Dict[str, int] = defaultdict(int)
    textures_used: Dict[str, Path] = {}
    extents = MeshExtents()
    extents_gear = MeshExtents()
    component_extents: Dict[str, MeshExtents] = {
        stem: MeshExtents() for stem in component_parts.values()}
    # The interior parts' own extents (never the hull's: they must not move
    # the measured anchors), their triangles, and the per-material record
    # of the FlightGear material each MTL material was made from.
    extents_interior = MeshExtents()
    interior_rows: List[Dict] = []
    material_sources: Dict[str, Dict] = {}
    # Round 2 (cockpit-airframe): the body's triangles again, for the
    # beauty-only smooth / two-sided copy of the body (_write_beauty_mesh).
    # None when the config asks for no beauty mesh: nothing else changes.
    beauty = _beauty_mesh_config(config)
    beauty_rows: Optional[List[tuple]] = [] if beauty is not None else None
    # A control surface's triangles too, when beauty_mesh.hide_objects is
    # stated: a surface that loses an object gets its own beauty copy
    # (round 2 scene 12: the c172p's propeller blades, a still image of a
    # prop at cruise RPM).
    beauty_surface_rows: Optional[Dict[str, List[tuple]]] = (
        defaultdict(list) if beauty is not None and beauty.get("hide_objects") else None)
    object_serial = 0

    for part in config["parts"]:
        ac_path = source_dir / part["file"]
        model = parse_ac(ac_path)
        offset = tuple(part.get("offset_m", (0.0, 0.0, 0.0)))  # FG model frame
        interior = bool(part.get("interior"))
        pitch_deg = float(part.get("pitch_deg", 0.0))
        if interior and part.get("component"):
            raise ConvertError(
                f"parts[] entry {part['file']!r} is both interior and a component; "
                f"an interior part is drawn in the body", constraint="aircraft.interior_outside_hull")
        gear_part = _matches(part["file"], gear_part_patterns)
        component_stem = component_parts.get(part.get("component"))
        part_extents = (extents_interior if interior
                        else component_extents.get(component_stem, extents))
        part_triangles = 0
        livery_here = livery is not None and livery["part"] == part["file"]
        for obj, verts in world_vertices(model):
            if _matches(obj.name, exclude):
                continue
            object_serial += 1
            target = "body"
            if component_stem is not None:
                target = component_stem
            elif not interior:
                for pattern, surface_name in claimed.items():
                    if re.fullmatch(pattern, obj.name):
                        target = surface_name
                        break
            gear = (not interior) and (gear_part or _matches(obj.name, gear_object_patterns))
            if gear and target == "body" and gear_component is not None:
                target = "gear"     # a surface claim wins: it is articulated
            writer = writers[target]
            texture = None
            texture_rel = None
            if obj.texture:
                texture_path = (ac_path.parent / obj.texture)
                if (livery_here and obj.name in livery["objects"]
                        and Path(obj.texture).name == livery["replaces"]):
                    # The model XML's material animation: this object
                    # draws the livery, not the .ac's own texture.
                    texture_path = source_dir / livery["texture"]
                    livery_applied[obj.name] += 1
                if texture_path.is_file() and texture_path.suffix.lower() == ".png":
                    texture = texture_path.name
                    previous = textures_used.get(texture)
                    if previous is not None and previous.resolve() != texture_path.resolve():
                        raise ConvertError(
                            f"two different package files are both named {texture!r} "
                            f"({previous} and {texture_path}); the converted textures "
                            f"share one folder and Interchange names each TEX_<stem>, "
                            f"so one would silently replace the other",
                            constraint="aircraft.texture_collision")
                    textures_used[texture] = texture_path
                    try:
                        texture_rel = texture_path.resolve().relative_to(
                            source_dir.resolve()).as_posix()
                    except ValueError:
                        texture_rel = str(texture_path)
            for surf in obj.surfaces:
                if not surf.is_polygon or len(surf.refs) < 3:
                    continue
                material = model.materials[surf.material] if surf.material < len(model.materials) else None
                rgb = material.rgb if material else (0.8, 0.8, 0.8)
                transparency = material.transparency if material else 0.0
                if transparency >= 0.9 and not texture:
                    continue    # invisible glass shells contribute nothing
                key = writer.material_key(texture, rgb, transparency)
                _record_material_source(material_sources, key, texture_rel, material,
                                        part["file"], obj.name, len(surf.refs) - 2)
                part_triangles += len(surf.refs) - 2
                refs = surf.refs
                for i in range(1, len(refs) - 1):
                    tri = []
                    # Reversed winding: exactly once, for the determinant -1
                    # model->UE map (see acmodel docstring).
                    for ref in (refs[0], refs[i + 1], refs[i]):
                        vi, u, v = ref
                        vertex_ac = verts[vi]
                        # .ac -> FG model frame, then the part offset (stated
                        # in the model XML, FG model frame), then -> UE, cm.
                        vm = _pitch_model(ac_to_model(vertex_ac), pitch_deg)
                        vm = (vm[0] + offset[0], vm[1] + offset[1], vm[2] + offset[2])
                        vu = model_to_ue(vm)
                        position_cm = (vu[0] * CM_PER_M, vu[1] * CM_PER_M,
                                       vu[2] * CM_PER_M)
                        part_extents.add(position_cm, gear)
                        if target == "gear":
                            extents_gear.add(position_cm, gear)
                        tri.append((position_cm, (u, v)))
                    # Degenerate UV triangles (untextured .ac surfaces carry
                    # u=v=0 on every vertex; some textured ones collapse too)
                    # make MikkTSpace tangent generation fail and Unreal's
                    # mesh build corrupt the whole asset (measured: the 747
                    # body simply did not render). Position-derived UVs are
                    # never degenerate for a real triangle.
                    (u0, v0), (u1, v1), (u2, v2) = (t[1] for t in tri)
                    uv_area = abs((u1 - u0) * (v2 - v0) - (u2 - u0) * (v1 - v0))
                    if uv_area < 1e-9:
                        tri = [
                            (p, ((p[0] + p[2]) * 1e-4, (p[1] + p[2]) * 1e-4))
                            for p, _ in tri
                        ]
                    writer.add_triangle(key, tri)
                    counts[target] += 1
                    if beauty_rows is not None and target == "body":
                        beauty_rows.append((key, tri, object_serial, surf.smooth,
                                            obj.crease, surf.two_sided, obj.name))
                    elif beauty_surface_rows is not None and target in surface_defs:
                        beauty_surface_rows[target].append(
                            (key, tri, object_serial, surf.smooth, obj.crease,
                             surf.two_sided, obj.name))
        if interior:
            interior_rows.append({
                "file": part["file"], "offset_m": list(offset), "pitch_deg": pitch_deg,
                "triangles": part_triangles, "source": part.get("source", ""),
            })

    if livery is not None:
        unmatched = [o for o in livery["objects"] if not livery_applied.get(o)]
        if unmatched:
            raise ConvertError(
                f"livery {livery['name']!r}: {len(unmatched)} object(s) the model XML "
                f"names carry no {livery['replaces']!r} texture in {livery['part']}: "
                f"{', '.join(unmatched)}", constraint="aircraft.livery_unmatched")
    interior_record = _interior_record(interior_rows, extents_interior, extents)

    for surface_name in surface_defs:
        if counts[surface_name] == 0:
            raise ConvertError(
                f"surface {surface_name!r} matched no geometry. A binding "
                f"that computes deflections and moves nothing is the failure "
                f"the animator exists to catch; refusing to bake it in."
            )
    if counts["body"] == 0:
        raise ConvertError("no body geometry survived conversion")

    # -- where the mesh sits: measured from what was just converted -----
    measured_origin_cm, origin_record = measure_mesh_origin(
        extents, airframe, vrp_actor_cm, name)
    mesh_origin_cm = tuple(a + b for a, b in zip(measured_origin_cm, origin_offset_cm))

    # Textures alongside the OBJs so the importer finds them by relative path.
    for texture_name, texture_path in textures_used.items():
        copy_texture(texture_path, out_dir / texture_name)

    manifest_surfaces = []
    for surface_name, surface in surface_defs.items():
        writer = writers[surface_name]
        p1 = model_to_ue(tuple(surface["hinge_m"][0]))
        p2 = model_to_ue(tuple(surface["hinge_m"][1]))
        axis = tuple(b - a for a, b in zip(p1, p2))
        length = math.sqrt(sum(c * c for c in axis))
        if length < 1e-6:
            raise ConvertError(f"surface {surface_name!r} hinge line has no length")
        axis = tuple(c / length for c in axis)
        mid_cm = tuple((a + b) / 2.0 * CM_PER_M for a, b in zip(p1, p2))
        obj_path = out_dir / f"{surface_name}.obj"
        writer.write(obj_path)
        record = {
            "bone": surface["bone"],
            "part": surface_name,
            "property": surface["property"],
            "scale_deg_per_unit": surface["scale_deg_per_unit"],
            "hinge_mid_cm": mid_cm,
            "axis_ue": axis,
            "triangles": counts[surface_name],
        }
        # Continuous bindings (Phase 7 3.3): the value is a RATE, not an
        # angle -- a propeller's rpm integrates into rotation instead of
        # deflecting to it. scale is then degrees per second per unit.
        if surface.get("continuous"):
            record["continuous"] = True
        manifest_surfaces.append(record)

    writers["body"].write(out_dir / "body.obj")
    beauty_record = None
    if beauty_rows is not None:
        _check_hide_objects(beauty, [r[6] for r in beauty_rows] + [
            r[6] for rows in (beauty_surface_rows or {}).values() for r in rows])
        beauty_record = _write_beauty_mesh(beauty_rows, beauty, writers["body"], out_dir)
        beauty_record.update(_write_beauty_surfaces(beauty_surface_rows, beauty, writers,
                                                    out_dir))
    # ONE components list: the payload parts' rows, then the gear row.
    payload_rows = _component_records(
        component_parts, airframe, writers, counts, component_extents,
        out_dir, name, mesh_origin_cm)
    manifest_components = list(payload_rows)
    if gear_component is not None:
        gear_row = _gear_component_row(extents_gear, config, mesh_origin_cm,
                                       counts["gear"])
        counts[gear_row["part"]] = counts.pop("gear")
        writers["gear"].write(out_dir / f"{gear_row['part']}.obj")
        manifest_components.append(gear_row)

    manifest = {
        "magic": "flightsim-aircraft-mesh",
        # Version 4 (COMPONENTS_MANIFEST_VERSION) only when the airframe
        # carries payload component parts (C7's gear row alone stays at 3): the importer's stale rule reads it, and an
        # airframe without any stays at 3 with its manifest unchanged.
        "version": (COMPONENTS_MANIFEST_VERSION if payload_rows
                    else MESH_MANIFEST_VERSION),
        # The OBJs' axis convention (decision 19); the importer's stale
        # rule re-converts a manifest without this exact stamp.
        OBJ_FRAME_KEY: OBJ_FRAME,
        "name": name,
        "fdm": config["fdm"],
        "fdm_config_name": fdm_name,
        "mesh_airframe": config["mesh_airframe"],
        "source": {
            **config["license"],
            "source_dir": str(source_dir),
            "license_first_line": license_head,
        },
        "units": "cm, UE actor frame (+X forward +Y right +Z up)",
        "parts": ["body"] + list(surface_defs)
                 + [row["part"] for row in manifest_components],
        "asset_path_root": f"/Game/Aircraft/{name}",
        "surfaces": manifest_surfaces,
        "triangles": dict(counts),
        "textures": sorted(textures_used),
        # The point in the actor frame the body and every hinge are
        # attached at. The vertices above are about the MODEL's origin;
        # the actor's is the structural datum. Version 3: measured.
        "vrp_actor_cm": list(vrp_actor_cm),
        "model_origin_offset_actor_cm": list(origin_offset_cm),
        "mesh_origin_measured_actor_cm": list(measured_origin_cm),
        "mesh_origin_actor_cm": list(mesh_origin_cm),
        "mesh_origin_basis": origin_record["mesh_origin_basis"],
        "origin_anchor": origin_record["origin_anchor"],
        "origin_measurement": origin_record["origin_measurement"],
        "labels_length_m": origin_record["labels_length_m"],
        **extents.to_manifest(),
        "gear_geometry": {"parts": gear_part_patterns,
                          "objects": gear_object_patterns},
        "components": manifest_components,
        "vrp_source": {
            "fdm_xml": str(vrp_xml),
            "sha256": hashlib.sha256(vrp_xml.read_bytes()).hexdigest(),
        },
    }
    # j11-package lane: the package beyond the .ac, each key only when the
    # config uses it, so every other airframe's manifest is unchanged.
    if package_rows:
        manifest["package_files"] = package_rows
    if livery is not None:
        manifest["livery"] = {**livery, "objects_applied": dict(sorted(livery_applied.items()))}
    if interior_record is not None:
        manifest["interior"] = interior_record
    if config.get("views"):
        manifest["views"] = _view_records(config, mesh_origin_cm)
    if beauty_record is not None:
        manifest["beauty_parts"] = beauty_record
    if material_sources:
        (out_dir / MATERIAL_SOURCES_NAME).write_text(
            json.dumps(_material_sources_out(material_sources), indent=1, sort_keys=True),
            encoding="utf-8")
    manifest_path = out_dir / "mesh_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=1))
    return manifest_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config")
    ap.add_argument("--out", default="assets/generated")
    args = ap.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    try:
        manifest = convert(Path(args.config), (repo_root / args.out).resolve(), repo_root)
    except ConvertError as exc:
        # By name, never a stack trace: the constraint where one exists,
        # the converter's own reason otherwise. Exit 2 = refused.
        print(f"REFUSED -- {exc.constraint or 'aircraft.mesh_import'}: {exc.message}")
        return 2
    data = json.loads(manifest.read_text())
    print(f"wrote {manifest}")
    print(f"  fdm {data['fdm']} ({data['fdm_config_name']}) <- mesh "
          f"{data['mesh_airframe']} [{data['source']['license_name']}]")
    for surface in data["surfaces"]:
        print(f"  {surface['part']:12s} {surface['triangles']:6d} tris  "
              f"{surface['property']}")
    print(f"  body         {data['triangles']['body']:6d} tris")
    ext = data["mesh_extents_actor_cm"]
    print(f"  mesh extent  nose {ext['nose'] / 100:+.2f} m, tail {ext['tail'] / 100:+.2f} m "
          f"about the model origin ({data['mesh_length_m']:.2f} m long; labels say "
          f"{data['labels_length_m']} m); lowest {ext['lowest'] / 100:+.2f} m, "
          f"lowest gear {'%+.2f m' % (ext['gear_lowest'] / 100) if ext['gear_lowest'] is not None else 'none identifiable'}")
    origin = data["mesh_origin_actor_cm"]
    print(f"  mesh origin  ({origin[0]:.1f}, {origin[1]:.1f}, {origin[2]:.1f}) cm "
          f"in the actor frame -- {data['mesh_origin_basis']} (manifest version "
          f"{data['version']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
