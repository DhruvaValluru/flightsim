"""The airframe as the labels see it: extents and keypoints, cited.

A ground-truth label is only as good as the geometry it was projected
from, so every number here has a stated source and the manifest carries
the sources beside the numbers. The definitions live in
``assets/aircraft_config/<name>.json`` under ``labels`` (next to the
mesh config, as the phase brief asks); the NUMBERS are resolved here
from the pinned JSBSim model wherever it has them, and copied from a
cited document only where it does not.

Three kinds of keypoint definition, in order of pedigree:

* ``{"fdm_contact": "<name>"}`` -- a ``<contact>`` element of the FDM's
  own XML (gear, and the structural skids/tips many models carry for
  crash detection). The FDM flew it; the label is where the FDM says
  that point is.
* ``{"fdm_wingspan": "left"|"right"}`` -- half the FDM's ``<wingspan>``
  abeam the aerodynamic reference point. A stated approximation: sweep
  and dihedral put the real tip aft and above/below this station, and
  the record says so.
* ``{"structural_in": [x, y, z], "source": ..., "basis": ...}`` -- a
  point in JSBSim's structural frame copied from a cited document, for
  the airframes whose FDM carries no element for it (the B747's nose
  and tail). ``basis`` is ``"estimate"`` where the source is a
  document's overall figure placed by an argument rather than a
  measured station, and the manifest keeps that word.

Frames. JSBSim's structural frame is inches, x positive AFT, y right, z
UP, about an origin the model author chose. The labels' body frame is
the pose solver's: metres, x forward, y right, z DOWN, about the
CENTRE OF GRAVITY -- the point the telemetry's lat/lon/alt describe and
the point the engine places the mesh by (FlightSimScenarioWorld solves
for the actor origin that puts the CG on the commanded point). So

    body = ((cg_x - x) / 39.3701, y / 39.3701, (cg_z - z) / 39.3701)

with the CG read from the same XML's ``<location name="CG">``. Checked
against three numbers that come from nowhere near this code: the
c172p's tips land at +-5.46 m (its wingspan is 10.91 m), the A320's at
+-16.96 m (33.92 m), and the A320's nose-to-tail is 37.5 m against the
type's 37.57 m.

The 3-D box is the airframe's OVERALL extents, not a tight hull:
nose-to-tail in x, the FDM wingspan in y, and in z from the lowest gear
contact (the tyres on the ground) up by the cited height. A stand-in
for the mesh's bounding box that exists on every machine, including the
ones with no mesh on disk.
"""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO / "assets" / "aircraft_config"

INCH_M = 0.0254
#: The keypoints a full label set names, in the order the manifest lists
#: them. An airframe may lack some (it says which); it may not invent one.
KEYPOINT_NAMES = ("nose", "tail", "left_wingtip", "right_wingtip",
                  "nose_gear", "left_main_gear", "right_main_gear")


class AirframeLabelError(Exception):
    """This airframe cannot be labelled; named on the Violation surface."""

    constraint = "camera.labels"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"camera.labels: {message}")


@dataclass(frozen=True)
class Keypoint:
    name: str
    #: Body frame, metres, about the CG: (forward, right, down).
    body_m: Tuple[float, float, float]
    source: str
    basis: str            # "fdm" | "fdm-approximation" | "estimate"

    def to_dict(self) -> Dict:
        return {"name": self.name, "body_m": list(self.body_m),
                "source": self.source, "basis": self.basis}


@dataclass(frozen=True)
class Airframe:
    aircraft: str
    length_m: float
    span_m: float
    height_m: float
    dimensions_source: str
    span_source: str
    cg_structural_in: Tuple[float, float, float]
    keypoints: Dict[str, Keypoint]
    config_sha256: str
    fdm_xml_path: str
    fdm_xml_sha256: str
    missing: Tuple[str, ...] = field(default_factory=tuple)

    # -- the box ----------------------------------------------------------

    def box_body_m(self) -> Dict[str, Tuple[float, float]]:
        """Extents along each body axis, metres about the CG:
        ``{"forward": (aft, fwd), "right": (left, right), "down": (up, down)}``.

        x from the tail keypoint to the nose keypoint when both exist,
        else centred on the CG at the cited length; y symmetric at half
        the span; z from the lowest gear contact (ground) UP by the
        cited height -- z is DOWN, so the top is the smaller number.
        """
        if "nose" in self.keypoints and "tail" in self.keypoints:
            x = (self.keypoints["tail"].body_m[0],
                 self.keypoints["nose"].body_m[0])
        else:
            x = (-self.length_m / 2.0, self.length_m / 2.0)
        y = (-self.span_m / 2.0, self.span_m / 2.0)
        gear = [k.body_m[2] for n, k in self.keypoints.items()
                if n.endswith("_gear")]
        bottom = max(gear) if gear else self.height_m / 2.0
        z = (bottom - self.height_m, bottom)
        return {"forward": x, "right": y, "down": z}

    def box_corners_body_m(self) -> List[Tuple[float, float, float]]:
        """The eight corners, a fixed order: for x in (aft, fwd), for y
        in (left, right), for z in (top, bottom)."""
        box = self.box_body_m()
        return [(x, y, z) for x in box["forward"] for y in box["right"]
                for z in box["down"]]

    def to_dict(self) -> Dict:
        box = self.box_body_m()
        return {
            "aircraft": self.aircraft,
            "length_m": self.length_m, "span_m": self.span_m,
            "height_m": self.height_m,
            "dimensions_source": self.dimensions_source,
            "span_source": self.span_source,
            "cg_structural_in": list(self.cg_structural_in),
            "body_frame": "metres about the CG: x forward, y right, z down",
            "box_body_m": {k: list(v) for k, v in box.items()},
            "keypoints": [self.keypoints[n].to_dict() for n in KEYPOINT_NAMES
                          if n in self.keypoints],
            "keypoints_missing": list(self.missing),
            "config_sha256": self.config_sha256,
            "fdm_xml": self.fdm_xml_path,
            "fdm_xml_sha256": self.fdm_xml_sha256,
        }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fdm_xml_path(fdm: str) -> Path:
    import jsbsim

    return Path(jsbsim.get_default_root_dir()) / "aircraft" / fdm / f"{fdm}.xml"


def _location_in(element) -> Tuple[float, float, float]:
    loc = element.find("location")
    if loc is None or loc.get("unit", "IN").upper() != "IN":
        raise AirframeLabelError(
            f"<{element.tag} name={element.get('name')!r}> carries no "
            f"<location unit=\"IN\">; only inch locations are read")
    return tuple(float(loc.find(axis).text) for axis in ("x", "y", "z"))


def _read_fdm(path: Path) -> Dict:
    """CG, wingspan, aero reference point and every contact, from the
    FDM's own XML."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise AirframeLabelError(f"FDM XML {path} unreadable: {exc}") from exc
    metrics = root.find("metrics")
    mass = root.find("mass_balance")
    if metrics is None or mass is None:
        raise AirframeLabelError(f"{path} has no <metrics> or <mass_balance>")
    span = metrics.find("wingspan")
    if span is None or span.get("unit", "FT").upper() != "FT":
        raise AirframeLabelError(f"{path}: <wingspan unit=\"FT\"> missing")
    aerorp = None
    for loc in metrics.findall("location"):
        if loc.get("name") == "AERORP":
            aerorp = tuple(float(loc.find(a).text) for a in ("x", "y", "z"))
    cg = None
    for loc in mass.findall("location"):
        if loc.get("name") == "CG":
            cg = tuple(float(loc.find(a).text) for a in ("x", "y", "z"))
    if cg is None or aerorp is None:
        raise AirframeLabelError(f"{path}: CG or AERORP location missing")
    contacts = {}
    ground = root.find("ground_reactions")
    if ground is not None:
        for contact in ground.findall("contact"):
            contacts[contact.get("name")] = (contact.get("type"),
                                             _location_in(contact))
    return {"cg_in": cg, "wingspan_ft": float(span.text),
            "aerorp_in": aerorp, "contacts": contacts}


def structural_to_body(point_in: Tuple[float, float, float],
                       cg_in: Tuple[float, float, float]
                       ) -> Tuple[float, float, float]:
    """JSBSim structural (in; x aft, y right, z up) -> body (m; x
    forward, y right, z down) about the CG."""
    x, y, z = point_in
    cx, cy, cz = cg_in
    return ((cx - x) * INCH_M, (y - cy) * INCH_M, (cz - z) * INCH_M)


def load_airframe(aircraft: str, config_dir: Optional[Path] = None
                  ) -> Airframe:
    """The labelled airframe, or a named ``camera.labels`` refusal.

    Refuses an airframe with no config, a config with no ``labels``
    block, a dimension with no source, and a keypoint definition the
    FDM cannot supply -- never a silent default, because a label that
    quietly describes a different aircraft is exactly the failure this
    module exists to prevent.
    """
    config_dir = Path(config_dir or CONFIG_DIR)
    path = config_dir / f"{aircraft}.json"
    if not path.is_file():
        raise AirframeLabelError(
            f"no aircraft config for {aircraft!r} at {path}; an airframe "
            f"with no stated geometry cannot be labelled")
    config = json.loads(path.read_text(encoding="utf-8"))
    labels = config.get("labels")
    if not isinstance(labels, dict):
        raise AirframeLabelError(
            f"{path.name} has no 'labels' block: {aircraft!r} states no "
            f"dimensions or keypoints, so its frames cannot be labelled")
    dims = labels.get("dimensions_m") or {}
    for key in ("length", "height", "source"):
        if key not in dims:
            raise AirframeLabelError(
                f"{path.name} labels.dimensions_m lacks {key!r}; a "
                f"dimension without a source is a guess")
    fdm = str(config.get("fdm", aircraft))
    xml_path = fdm_xml_path(fdm)
    if not xml_path.is_file():
        raise AirframeLabelError(f"FDM XML for {fdm!r} not found at {xml_path}")
    model = _read_fdm(xml_path)
    cg = model["cg_in"]

    keypoints: Dict[str, Keypoint] = {}
    missing: List[str] = []
    for name in KEYPOINT_NAMES:
        definition = (labels.get("keypoints") or {}).get(name)
        if definition is None:
            missing.append(name)
            continue
        if "fdm_contact" in definition:
            contact = model["contacts"].get(definition["fdm_contact"])
            if contact is None:
                raise AirframeLabelError(
                    f"{path.name} keypoint {name!r} names FDM contact "
                    f"{definition['fdm_contact']!r}, which "
                    f"{xml_path.name} does not carry (it has "
                    f"{sorted(model['contacts'])})")
            kind, loc = contact
            keypoints[name] = Keypoint(
                name, structural_to_body(loc, cg),
                source=f"{xml_path.name} <contact type=\"{kind}\" "
                       f"name=\"{definition['fdm_contact']}\"> location, "
                       f"about the same file's <location name=\"CG\">",
                basis="fdm")
        elif "fdm_wingspan" in definition:
            side = definition["fdm_wingspan"]
            if side not in ("left", "right"):
                raise AirframeLabelError(
                    f"{path.name} keypoint {name!r}: fdm_wingspan must be "
                    f"'left' or 'right', not {side!r}")
            half_in = model["wingspan_ft"] * 12.0 / 2.0
            ax, _, az = model["aerorp_in"]
            loc = (ax, -half_in if side == "left" else half_in, az)
            keypoints[name] = Keypoint(
                name, structural_to_body(loc, cg),
                source=f"half of {xml_path.name} <wingspan> abeam its "
                       f"<location name=\"AERORP\"> station; sweep and "
                       f"dihedral not modelled",
                basis="fdm-approximation")
        elif "structural_in" in definition:
            if not definition.get("source"):
                raise AirframeLabelError(
                    f"{path.name} keypoint {name!r} is a stated point with "
                    f"no source; refused")
            loc = tuple(float(v) for v in definition["structural_in"])
            keypoints[name] = Keypoint(
                name, structural_to_body(loc, cg),
                source=str(definition["source"]),
                basis=str(definition.get("basis", "stated")))
        else:
            raise AirframeLabelError(
                f"{path.name} keypoint {name!r} has no fdm_contact, "
                f"fdm_wingspan or structural_in definition")

    return Airframe(
        aircraft=aircraft,
        length_m=float(dims["length"]),
        span_m=model["wingspan_ft"] * 12.0 * INCH_M,
        height_m=float(dims["height"]),
        dimensions_source=str(dims["source"]),
        span_source=f"{xml_path.name} <metrics><wingspan>",
        cg_structural_in=cg,
        keypoints=keypoints,
        config_sha256=_sha256(path),
        fdm_xml_path=str(xml_path),
        fdm_xml_sha256=_sha256(xml_path),
        missing=tuple(missing),
    )
