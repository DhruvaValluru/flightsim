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
from core.capture import airframe as airframe_module  # noqa: E402
from core.capture.airframe import fdm_xml_path  # noqa: E402

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


class ObjWriter:
    """Accumulates triangles grouped by (texture, material colour)."""

    def __init__(self) -> None:
        self.vertices: List[Tuple[float, float, float]] = []
        self.uvs: List[Tuple[float, float]] = []
        self.faces: Dict[str, List[Tuple[Tuple[int, int], ...]]] = defaultdict(list)
        self.materials: Dict[str, Dict] = {}

    def material_key(self, texture: Optional[str], rgb, transparency: float) -> str:
        if texture:
            key = "tex_" + re.sub(r"[^A-Za-z0-9]+", "_", Path(texture).stem)
        else:
            key = "rgb_%02x%02x%02x" % tuple(int(max(0, min(1, c)) * 255) for c in rgb)
        if key not in self.materials:
            self.materials[key] = {
                "texture": texture, "rgb": tuple(rgb), "transparency": transparency,
            }
        return key

    def add_triangle(self, key: str, tri) -> None:
        indices = []
        for vertex, uv in tri:
            self.vertices.append(vertex)
            self.uvs.append(uv)
            indices.append((len(self.vertices), len(self.uvs)))
        self.faces[key].append(tuple(indices))

    def write(self, obj_path: Path, texture_dir_relative: str = "") -> None:
        mtl_path = obj_path.with_suffix(".mtl")
        with obj_path.open("w") as out:
            out.write(f"mtllib {mtl_path.name}\n")
            for v in self.vertices:
                out.write("v %.6f %.6f %.6f\n" % v)
            for uv in self.uvs:
                out.write("vt %.6f %.6f\n" % uv)
            for key, faces in self.faces.items():
                out.write(f"usemtl {key}\n")
                for face in faces:
                    out.write("f " + " ".join(f"{vi}/{ti}" for vi, ti in face) + "\n")
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
    license_file = source_dir / config["license"]["file"]
    if not license_file.is_file():
        raise ConvertError(f"license file {license_file} does not exist")
    license_head = license_file.read_text(errors="replace").strip().splitlines()[0].strip()

    out_dir = out_root / name
    out_dir.mkdir(parents=True, exist_ok=True)

    exclude = config.get("exclude", [])
    surface_defs = config["surfaces"]
    claimed: Dict[str, str] = {}
    for surface_name, surface in surface_defs.items():
        for pattern in surface["objects"]:
            claimed[pattern] = surface_name

    writers: Dict[str, ObjWriter] = {"body": ObjWriter()}
    for surface_name in surface_defs:
        writers[surface_name] = ObjWriter()
    counts: Dict[str, int] = defaultdict(int)
    textures_used: Dict[str, Path] = {}
    extents = MeshExtents()

    for part in config["parts"]:
        ac_path = source_dir / part["file"]
        model = parse_ac(ac_path)
        offset = tuple(part.get("offset_m", (0.0, 0.0, 0.0)))  # FG model frame
        gear_part = _matches(part["file"], gear_part_patterns)
        for obj, verts in world_vertices(model):
            if _matches(obj.name, exclude):
                continue
            target = "body"
            for pattern, surface_name in claimed.items():
                if re.fullmatch(pattern, obj.name):
                    target = surface_name
                    break
            writer = writers[target]
            gear = gear_part or _matches(obj.name, gear_object_patterns)
            texture = None
            if obj.texture:
                texture_path = (ac_path.parent / obj.texture)
                if texture_path.is_file() and texture_path.suffix.lower() == ".png":
                    texture = texture_path.name
                    textures_used[texture] = texture_path
            for surf in obj.surfaces:
                if not surf.is_polygon or len(surf.refs) < 3:
                    continue
                material = model.materials[surf.material] if surf.material < len(model.materials) else None
                rgb = material.rgb if material else (0.8, 0.8, 0.8)
                transparency = material.transparency if material else 0.0
                if transparency >= 0.9 and not texture:
                    continue    # invisible glass shells contribute nothing
                key = writer.material_key(texture, rgb, transparency)
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
                        vm = ac_to_model(vertex_ac)
                        vm = (vm[0] + offset[0], vm[1] + offset[1], vm[2] + offset[2])
                        vu = model_to_ue(vm)
                        position_cm = (vu[0] * CM_PER_M, vu[1] * CM_PER_M,
                                       vu[2] * CM_PER_M)
                        extents.add(position_cm, gear)
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
        shutil.copyfile(texture_path, out_dir / texture_name)

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

    manifest = {
        "magic": "flightsim-aircraft-mesh",
        "version": MESH_MANIFEST_VERSION,
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
        "parts": ["body"] + list(surface_defs),
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
        "vrp_source": {
            "fdm_xml": str(vrp_xml),
            "sha256": hashlib.sha256(vrp_xml.read_bytes()).hexdigest(),
        },
    }
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
