"""Convert the A-4E P3D .mdl into the pipeline's mesh manifest for Unreal.

Same output contract as ``convert.py`` (body OBJ + MTL + textures +
``mesh_manifest.json``, UE actor frame in centimetres), from a local model
instead of a fetched FlightGear tree. The same refusals apply before
anything is written: the config's FDM pairing must match the staged FDM's
``<fdm_config>`` name (VALIDITY 1.4), and the license file must exist on
disk (VALIDITY 3.3).

What is exported: every part visible in ``mdl_scene.REST_ENV`` (parked,
all optional variants and stores off), gear stowed, at rest pose, as ONE
rigid body. The exterior is not articulated: no control surfaces, gear or
speed brakes move. Livery: the model repo's texture.VA-12 folder.

Frames: the .mdl is x right, y up, z forward (left-handed, like Unreal), so
UE (X fwd, Y right, Z up) = (z, x, y) -- an even permutation, winding kept.

    python -m assets_pipeline.a4_mdl_convert assets/aircraft_config/A4.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assets_pipeline.convert import ConvertError, _fdm_config_name  # noqa: E402
from assets_pipeline.mdl_scene import MdlScene  # noqa: E402

CM_PER_M = 100.0
TEXTURE_PIXELS = 2048
#: The wing skin is on the second livery sheet; everything else is on the
#: first. Found by rendering, not read from the file (its material records
#: are not decoded).
WING_MATERIAL = 11
SHEETS = ("A4E_1", "A4E_2")
LIVERY_DIR = ("SimObjects", "Airplanes", "A-4E", "texture.VA-12")
MODEL = ("SimObjects", "Airplanes", "A-4E", "model", "A4E.mdl")


def _to_ue(v: np.ndarray) -> np.ndarray:
    return np.c_[v[:, 2], v[:, 0], v[:, 1]]


def convert(config_path: Path, out_root: Path, repo_root: Path) -> Path:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    name = config["name"]
    source_dir = (Path(config_path).parent / config["source_dir"]).resolve()

    fdm_xml = repo_root / ("ue/Plugins/JSBSimFlightDynamicsModel/Resources/"
                           f"JSBSim/aircraft/{config['fdm']}/{config['fdm']}.xml")
    if not fdm_xml.is_file():
        raise ConvertError(f"no staged FDM at {fdm_xml}")
    fdm_name = _fdm_config_name(fdm_xml)
    if fdm_name not in config["fdm_match"]:
        raise ConvertError(
            f"REFUSING the pairing: mesh '{name}' ({config['mesh_airframe']}) "
            f"against FDM '{config['fdm']}' whose <fdm_config> names itself "
            f"{fdm_name!r}, not one of {config['fdm_match']}. A mesh of one "
            f"aircraft flying the model of another is §1.4.")
    license_file = source_dir / config["license"]["file"]
    if not license_file.is_file():
        raise ConvertError(f"license file {license_file} does not exist")
    license_head = license_file.read_text(encoding="utf-8", errors="replace").strip() \
        .splitlines()[0].strip()

    scene = MdlScene(source_dir.joinpath(*MODEL))
    parts = scene.parts()
    if not parts:
        raise ConvertError("no body geometry survived conversion")

    out_dir = out_root / name
    out_dir.mkdir(parents=True, exist_ok=True)

    livery = source_dir.joinpath(*LIVERY_DIR)
    textures: List[str] = []
    for sheet in SHEETS:
        src = livery / f"{sheet}.dds"
        if not src.is_file():
            raise ConvertError(f"livery texture {src} does not exist")
        image = Image.open(src).convert("RGB").resize(
            (TEXTURE_PIXELS, TEXTURE_PIXELS), Image.LANCZOS)
        image.save(out_dir / f"{sheet}.png")
        textures.append(f"{sheet}.png")

    by_material: Dict[str, List[str]] = {s: [] for s in SHEETS}
    v_lines: List[str] = []
    vt_lines: List[str] = []
    vn_lines: List[str] = []
    base = 0
    triangles = 0
    lo = np.full(3, 1e30)
    hi = np.full(3, -1e30)
    for part in parts:
        tri = part.triangles
        a, b, c = (part.positions[tri[:, k]] for k in range(3))
        # zero-area and repeated-index triangles are dropped here rather
        # than left for the engine to discard (the importer rejects a mesh
        # that loses more than 5 percent of its triangles).
        keep = (np.linalg.norm(np.cross(b - a, c - a), axis=1) > 2e-10) & \
            (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & \
            (tri[:, 0] != tri[:, 2])
        part.triangles = tri[keep]
        pos = _to_ue(part.positions) * CM_PER_M
        nrm = _to_ue(part.normals)
        lo, hi = np.minimum(lo, pos.min(0)), np.maximum(hi, pos.max(0))
        v_lines += ["v %.4f %.4f %.4f" % tuple(p) for p in pos]
        vn_lines += ["vn %.5f %.5f %.5f" % tuple(n) for n in nrm]
        # OBJ v runs bottom-up; the .mdl's runs top-down.
        vt_lines += ["vt %.6f %.6f" % (u, 1.0 - v) for u, v in part.uvs]
        sheet = SHEETS[1] if part.material == WING_MATERIAL else SHEETS[0]
        by_material[sheet] += [
            "f " + " ".join(f"{base + i + 1}/{base + i + 1}/{base + i + 1}"
                            for i in tri) for tri in part.triangles]
        triangles += len(part.triangles)
        base += len(pos)

    with (out_dir / "body.obj").open("w", encoding="utf-8") as out:
        out.write("mtllib body.mtl\n")
        out.write("\n".join(v_lines) + "\n")
        out.write("\n".join(vt_lines) + "\n")
        out.write("\n".join(vn_lines) + "\n")
        for sheet in SHEETS:
            out.write(f"usemtl tex_{sheet}\n")
            out.write("\n".join(by_material[sheet]) + "\n")
    with (out_dir / "body.mtl").open("w", encoding="utf-8") as out:
        for sheet in SHEETS:
            out.write(f"newmtl tex_{sheet}\nKd 1.0000 1.0000 1.0000\n"
                      f"map_Kd {sheet}.png\n\n")

    manifest = {
        "magic": "flightsim-aircraft-mesh",
        "version": 1,
        "name": name,
        "fdm": config["fdm"],
        "fdm_config_name": fdm_name,
        "mesh_airframe": config["mesh_airframe"],
        "source": {**config["license"], "source_dir": str(source_dir),
                   "license_first_line": license_head},
        "units": "cm, UE actor frame (+X forward +Y right +Z up)",
        "parts": ["body"],
        "asset_path_root": f"/Game/Aircraft/{name}",
        "surfaces": [],
        "triangles": {"body": triangles},
        "textures": sorted(textures),
        "bounds_cm": {"min": [round(float(x), 2) for x in lo],
                      "max": [round(float(x), 2) for x in hi]},
        "articulated": False,
    }
    path = out_dir / "mesh_manifest.json"
    path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config")
    ap.add_argument("--out", default="assets/generated")
    args = ap.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    path = convert(Path(args.config), (repo / args.out).resolve(), repo)
    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"wrote {path}")
    print(f"  fdm {data['fdm']} ({data['fdm_config_name']}) <- mesh "
          f"{data['mesh_airframe']} [{data['source']['license_name']}]")
    print(f"  body {data['triangles']['body']} tris, bounds cm "
          f"{data['bounds_cm']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
