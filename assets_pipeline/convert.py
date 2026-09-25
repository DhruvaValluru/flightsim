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

Where the mesh sits (manifest version 2)
----------------------------------------
The vertices are mapped to the UE actor frame ABOUT THE MODEL'S OWN
ORIGIN, and the model's origin is not the actor's. FlightGear's convention
is that a model's origin sits at the FDM's visual reference point (VRP);
the JSBSim plugin makes the actor origin the STRUCTURAL DATUM
(``StructuralToActorMatrix`` negates x about ``StructuralFrameOrigin``,
default zero) and ``FlightSimScenarioWorld`` places the actor so the CG
lands on the commanded point. A mesh attached at the actor root is
therefore drawn with its VRP on the datum -- 33.7 m forward of where it
belongs on the B747 (VRP x = 1327 in), 16.8 m on the A320, 1.1 m on the
c172p -- while the label (built from the telemetry's CG) stays put.
Measured in the Camera Phase 1 initial run report: the rendered airframe
sat 25-30 m ahead of the position the capture manifest recorded for it.

So the manifest now records ``mesh_origin_actor_cm`` -- the FDM XML's VRP
mapped to the actor frame, plus an optional documented offset -- and the
render commandlet attaches the body and every hinge under a scene
component at that point. A manifest without the field (version 1) is
stale: the importer re-converts it.

Aircraft config keys (``assets/aircraft_config/<name>.json``)
------------------------------------------------------------
``name``, ``fdm``, ``fdm_match`` (§1.4), ``mesh_airframe``, ``source_dir``,
``license`` (§3.3), ``parts`` (each ``file`` with an optional
``offset_m`` in the FlightGear model frame), ``exclude``, ``surfaces``
(``bone``, ``objects``, ``property``, ``scale_deg_per_unit``, ``hinge_m``,
optional ``continuous``), ``labels`` (read by core/capture/airframe.py),
and OPTIONAL ``model_origin_offset_m``: ``[x, y, z]`` in the UE actor
frame, metres, default ``[0, 0, 0]``, for a model whose origin is
DOCUMENTED not to sit at the FDM's VRP (state the source in the config
beside it). It is added to the VRP; it is never a way to nudge a mesh
that "looks" off -- that is the datum bug above, and it is fixed by the
manifest field, not per aircraft.
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
from core.capture.airframe import fdm_xml_path  # noqa: E402

CM_PER_M = 100.0
CM_PER_IN = 2.54
CM_PER_FT = 30.48

#: Bumped from 1 when ``mesh_origin_actor_cm`` was added. A reader that
#: finds a lower version has a manifest whose mesh the commandlet would
#: attach at the structural datum, i.e. every mask offset by the VRP.
MESH_MANIFEST_VERSION = 2

#: The convention behind ``mesh_origin_actor_cm``, carried in the manifest
#: so the number is never separated from the argument that produced it.
MESH_ORIGIN_BASIS = (
    "FlightGear places the model origin at the FDM's visual reference "
    "point (VRP); the VRP is read from the JSBSim XML's <location "
    "name=\"VRP\"> in the structural frame (inches, x aft, y right, z up) "
    "and mapped to the UE actor frame by (-x, y, z), the plugin's "
    "StructuralToActorMatrix about its zero origin, so the actor origin is "
    "the structural datum; the mesh must be attached at this point, not at "
    "the actor root, plus the config's documented model_origin_offset_m")


class ConvertError(Exception):
    pass


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


def fdm_vrp_actor_cm(xml_path: Path) -> Tuple[float, float, float]:
    """The FDM's visual reference point in the UE actor frame, cm.

    FlightGear models are built about the VRP, so this is where the
    converted mesh's origin belongs in the actor. Read from the XML's
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
    a silently dropped offset would place the mesh by the VRP alone
    while the config says otherwise."""
    raw = config.get("model_origin_offset_m", (0.0, 0.0, 0.0))
    if (not isinstance(raw, (list, tuple)) or len(raw) != 3
            or not all(isinstance(v, (int, float)) and math.isfinite(v)
                       for v in raw)):
        raise ConvertError(
            f"model_origin_offset_m must be three finite numbers (UE actor "
            f"frame, metres), not {raw!r}")
    return tuple(float(v) * CM_PER_M for v in raw)


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
    config = json.loads(Path(config_path).read_text())
    name = config["name"]
    source_dir = (Path(config_path).parent / config["source_dir"]).resolve()

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

    # -- where the mesh sits: the FDM's VRP, read from the XML the labels
    # are built from (core/capture/airframe.py reads the CG out of the same
    # file), so the drawn mesh and the label share one source ----------
    vrp_xml = fdm_xml_path(config["fdm"])
    vrp_actor_cm = fdm_vrp_actor_cm(vrp_xml)
    origin_offset_cm = _model_origin_offset_actor_cm(config)
    mesh_origin_cm = tuple(a + b for a, b in zip(vrp_actor_cm, origin_offset_cm))

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

    for part in config["parts"]:
        ac_path = source_dir / part["file"]
        model = parse_ac(ac_path)
        offset = tuple(part.get("offset_m", (0.0, 0.0, 0.0)))  # FG model frame
        for obj, verts in world_vertices(model):
            if _matches(obj.name, exclude):
                continue
            target = "body"
            for pattern, surface_name in claimed.items():
                if re.fullmatch(pattern, obj.name):
                    target = surface_name
                    break
            writer = writers[target]
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
        # Version 2: the point in the actor frame the body and every hinge
        # are attached at. The vertices above are about the MODEL's origin;
        # the actor's is the structural datum.
        "vrp_actor_cm": list(vrp_actor_cm),
        "model_origin_offset_actor_cm": list(origin_offset_cm),
        "mesh_origin_actor_cm": list(mesh_origin_cm),
        "mesh_origin_basis": MESH_ORIGIN_BASIS,
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
    manifest = convert(Path(args.config), (repo_root / args.out).resolve(), repo_root)
    data = json.loads(manifest.read_text())
    print(f"wrote {manifest}")
    print(f"  fdm {data['fdm']} ({data['fdm_config_name']}) <- mesh "
          f"{data['mesh_airframe']} [{data['source']['license_name']}]")
    for surface in data["surfaces"]:
        print(f"  {surface['part']:12s} {surface['triangles']:6d} tris  "
              f"{surface['property']}")
    print(f"  body         {data['triangles']['body']:6d} tris")
    origin = data["mesh_origin_actor_cm"]
    print(f"  mesh origin  ({origin[0]:.1f}, {origin[1]:.1f}, {origin[2]:.1f}) cm "
          f"in the actor frame (the FDM's VRP; manifest version "
          f"{data['version']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
