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
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assets_pipeline.acmodel import (  # noqa: E402
    ac_to_model, model_to_ue, parse_ac, world_vertices,
)

CM_PER_M = 100.0


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
        manifest_surfaces.append({
            "bone": surface["bone"],
            "part": surface_name,
            "property": surface["property"],
            "scale_deg_per_unit": surface["scale_deg_per_unit"],
            "hinge_mid_cm": mid_cm,
            "axis_ue": axis,
            "triangles": counts[surface_name],
        })

    writers["body"].write(out_dir / "body.obj")

    manifest = {
        "magic": "flightsim-aircraft-mesh",
        "version": 1,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
