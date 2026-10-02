"""S2: the ground-truth passes in the KITTI layout, and the consumer of each.

The derived passes (core/capture/passes.py) sit beside each frame in
this project's own encodings, named with their sha256 in the camera's
``passes.json``. A KITTI export (core/dataset/export.py) re-encodes them
into the layouts the KITTI devkits read (Geiger et al. 2013; Menze &
Geiger 2015 for flow and disparity):

* ``flow_occ/<key>.png`` and ``flow_noc/<key>.png`` -- the FORWARD flow
  as a 16-bit RGB PNG, R = u * 64 + 2^15, G = v * 64 + 2^15 (rounded,
  unsigned), B = 1 where valid; ``flow_occ`` counts occluded pixels as
  valid (their flow is defined, the surface is hidden at the next
  sample), ``flow_noc`` only the non-occluded ones. Out-of-frame pixels,
  the sky, and a flow outside the encoding's +-512 px range are 0
  (invalid). ``backward_flow_occ/`` and ``backward_flow_noc/`` carry the
  backward flow the same way (Virtual KITTI 2's second direction; not a
  KITTI directory).
* ``disp_occ_0/<key>.png`` -- the left camera's disparity, uint16 =
  d * 256 rounded, 0 = invalid (the sky, and a disparity above
  65535 / 256 px, counted).
* ``velodyne/<key>.bin`` -- the points as float32 N x 4 in the
  velodyne axes (x forward, y left, z up; reflectance 0), converted from
  the pass's camera axes (x right, y down, z forward): x_v = z_c, y_v =
  -x_c, z_v = -y_c; the frame's ``calib`` then carries the
  ``Tr_velo_to_cam`` that undoes it (:data:`VELO_TO_CAM`). The sensor
  origin is the camera's centre (no lidar mount is modelled).
  ``velodyne_id/<key>.bin`` -- one uint8 object id per point (this
  project's sidecar; KITTI has none).
* ``normals/<key>.png`` (16-bit RGB, (n * 0.5 + 0.5) * 65535, the I6
  encoding, scene frame north, east, up) and ``normals/<key>.f32``
  (float32 h x w x 3, the same normals decoded).

Every encoding here is round-tripped in tests/test_passes_export.py by
an INDEPENDENT reader (rasterio's libpng for the PNGs, numpy.fromfile
for the binaries, written from the devkit's definitions) -- never by
this module. What is NOT claimed: that any training stack has read
these trees; the lidar is a depth back-projection with no beam model.
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional

#: KITTI flow: u = (R - 2^15) / 64 (the devkit's flow_read).
KITTI_FLOW_SCALE = 64.0
KITTI_FLOW_OFFSET = 2 ** 15
#: KITTI disparity: d = value / 256, 0 invalid (the devkit's disp_read).
KITTI_DISPARITY_SCALE = 256.0
PNG16_MAX = 65535
#: The flow validity bits of core/capture/passes.py (restated; pinned
#: equal by test).
FLOW_VALID, FLOW_OCCLUDED = 1, 2
#: Velodyne axes (x forward, y left, z up) -> camera axes (x right, y
#: down, z forward): cam = VELO_TO_CAM[:, :3] velo, no translation.
VELO_TO_CAM = ((0.0, -1.0, 0.0, 0.0), (0.0, 0.0, -1.0, 0.0), (1.0, 0.0, 0.0, 0.0))

#: The KITTI directories a pass writes, by passes.json file key.
KITTI_PASS_DIRS = ("flow_occ", "flow_noc", "backward_flow_occ", "backward_flow_noc",
                   "disp_occ_0", "velodyne", "velodyne_id", "normals")

#: Who reads each pass: the consumer the dataset card names.
PASS_CONSUMERS: Dict[str, Dict[str, str]] = {
    "flow": {
        "consumer": ("optical-flow and scene-flow models, trained and evaluated through the "
                     "KITTI 2015 flow devkit layout (flow_occ / flow_noc) and the Virtual "
                     "KITTI 2 forward / backward convention"),
        "encoding": ("KITTI: 16-bit RGB PNG, u = (R - 2^15) / 64, v = (G - 2^15) / 64, B = "
                     "valid; WebDataset: float32 (du, dv) pairs and a validity byte per pixel "
                     "(1 valid, 2 occluded, 4 out of frame, 0 no surface)"),
        "not_claimed": "exact for rigid bodies only; no control surfaces or propellers",
    },
    "disparity": {
        "consumer": "stereo-matching models, through the KITTI 2015 disp_occ_0 layout",
        "encoding": "KITTI: uint16 PNG, d = value / 256, 0 invalid; WebDataset: float32 px",
        "not_claimed": "rectified by construction; not a matcher's output",
    },
    "points": {
        "consumer": ("3-D detection and point-cloud segmentation models, through the KITTI "
                     "velodyne layout, with a per-point object id sidecar"),
        "encoding": ("KITTI: float32 N x 4 (x forward, y left, z up, reflectance 0) and a uint8 "
                     "id per point; WebDataset: float32 N x 4 in camera axes and the id bytes"),
        "not_claimed": "a depth back-projection with no beam model and no intensity",
    },
    "normals": {
        "consumer": "surface-normal estimation models (Hypersim-style per-pixel normals)",
        "encoding": ("16-bit RGB PNG (n * 0.5 + 0.5) * 65535 and float32 h x w x 3, scene frame "
                     "north, east, up"),
        "not_claimed": "vertex-interpolated engine normals; the sky's pixels",
    },
    "amodal": {
        "consumer": ("amodal instance segmentation (Zhu et al. 2017 / KINS conventions), in "
                     "every format's sidecar: the manifest record's amodal box and mask"),
        "encoding": "the alone pass (pixels equal to the object's id) and its tight box",
        "not_claimed": "aircraft only: the terrain has no alone pass",
    },
}


# -- encoders ---------------------------------------------------------------------

def kitti_flow_image(flow, bits, include_occluded: bool):
    """(h, w, 3) uint16 in the KITTI flow encoding, and the count of valid
    pixels dropped because their flow is outside the encoding's range."""
    import numpy as np

    flow = np.asarray(flow, dtype=np.float64)
    bits = np.asarray(bits)
    valid = bits == FLOW_VALID
    if include_occluded:
        valid = valid | (bits == FLOW_OCCLUDED)
    encoded = np.rint(flow * KITTI_FLOW_SCALE + KITTI_FLOW_OFFSET)
    representable = np.all((encoded >= 0) & (encoded <= PNG16_MAX), axis=2)
    dropped = int(np.count_nonzero(valid & ~representable))
    valid = valid & representable
    image = np.zeros(flow.shape[:2] + (3,), dtype=np.uint16)
    image[..., :2] = np.where(valid[..., None], np.clip(encoded, 0, PNG16_MAX), 0).astype(np.uint16)
    image[..., 2] = valid.astype(np.uint16)
    return image, dropped


def kitti_disparity_image(disparity, finite):
    """(h, w) uint16 = d * 256 rounded, 0 invalid; and the count of
    surface pixels whose disparity the encoding cannot hold."""
    import numpy as np

    d = np.asarray(disparity, dtype=np.float64)
    encoded = np.rint(d * KITTI_DISPARITY_SCALE)
    ok = np.asarray(finite) & (d > 0.0) & (encoded >= 1) & (encoded <= PNG16_MAX)
    dropped = int(np.count_nonzero(np.asarray(finite) & (d > 0.0) & ~ok))
    return np.where(ok, encoded, 0).astype(np.uint16), dropped


def velodyne_points(points_camera):
    """float32 N x 4 in camera axes -> the velodyne axes (x forward, y
    left, z up), reflectance kept."""
    import numpy as np

    p = np.asarray(points_camera, dtype=np.float32).reshape(-1, 4)
    out = np.empty_like(p)
    out[:, 0] = p[:, 2]
    out[:, 1] = -p[:, 0]
    out[:, 2] = -p[:, 1]
    out[:, 3] = p[:, 3]
    return out


def encode_normals16(normals):
    """(h, w, 3) float normals -> the I6 16-bit encoding."""
    import numpy as np

    scaled = (np.asarray(normals, dtype=np.float64) * 0.5 + 0.5) * PNG16_MAX
    return np.clip(np.rint(scaled), 0, PNG16_MAX).astype(np.uint16)


def write_png16(path: Path, array) -> Path:
    """A 16-bit grey (h, w) or RGB (h, w, 3) PNG, filter 0, zlib -- written
    from the PNG specification (ISO/IEC 15948): big-endian samples."""
    import numpy as np

    array = np.asarray(array)
    if array.dtype != np.uint16 or array.ndim not in (2, 3) or (
            array.ndim == 3 and array.shape[2] != 3):
        raise ValueError(f"write_png16 takes (h, w) or (h, w, 3) uint16, got "
                         f"{array.shape} {array.dtype}")
    height, width = array.shape[:2]
    channels = 1 if array.ndim == 2 else 3
    rows = array.astype(">u2").tobytes()
    stride = width * channels * 2
    raw = b"".join(b"\x00" + rows[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff))

    header = struct.pack(">IIBBBBB", width, height, 16, 0 if channels == 1 else 2, 0, 0, 0)
    path = Path(path)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    return path


def kitti_calib_velodyne() -> str:
    """The ``Tr_velo_to_cam`` line for a frame whose points ship."""
    return "Tr_velo_to_cam: " + " ".join(f"{v:.6f}" for row in VELO_TO_CAM for v in row)


# -- the frame's passes, read back from the run ----------------------------------------

def frame_passes_entry(run_dir: Path, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The passes.json entry of a manifest frame, or None."""
    camera = str(record.get("camera_id"))
    path = Path(run_dir) / "frames" / camera / "passes.json"
    if not path.is_file():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    name = Path(str(record.get("file"))).name
    for entry in document.get("frames") or []:
        if isinstance(entry, dict) and entry.get("frame") == name:
            return entry
    return None


def write_kitti_passes(run_dir: Path, record: Dict[str, Any], root: Path, key: str
                       ) -> Dict[str, Any]:
    """Write every pass the frame carries into the KITTI tree at ``root``
    (a split directory); returns {what was written, dropped counts}."""
    import numpy as np

    from core.capture.passes import (
        read_disparity_file, read_flow_file, read_normal_pass, read_points_file,
        read_points_ids, read_valid_file,
    )

    run_dir = Path(run_dir)
    folder = run_dir / "frames" / str(record["camera_id"])
    width, height = int(record["width_px"]), int(record["height_px"])
    written: Dict[str, Any] = {}
    entry = frame_passes_entry(run_dir, record)
    files = (entry or {}).get("files") or {}
    for tag, prefix in (("fw", ""), ("bw", "backward_")):
        if f"flow_{tag}" in files and f"flow_{tag}_valid" in files:
            flow = read_flow_file(folder / files[f"flow_{tag}"]["file"], width, height)
            bits = read_valid_file(folder / files[f"flow_{tag}_valid"]["file"], width, height)
            for occ, name in ((True, "flow_occ"), (False, "flow_noc")):
                image, dropped = kitti_flow_image(flow, bits, include_occluded=occ)
                target = root / f"{prefix}{name}"
                target.mkdir(parents=True, exist_ok=True)
                write_png16(target / f"{key}.png", image)
                written[f"{prefix}{name}"] = {"file": f"{prefix}{name}/{key}.png",
                                              "dropped_out_of_range": dropped}
    if "disparity" in files:
        d = read_disparity_file(folder / files["disparity"]["file"], width, height)
        image, dropped = kitti_disparity_image(d, d > 0.0)     # 0 = the sky's
        (root / "disp_occ_0").mkdir(parents=True, exist_ok=True)
        write_png16(root / "disp_occ_0" / f"{key}.png", image)
        written["disp_occ_0"] = {"file": f"disp_occ_0/{key}.png", "dropped_out_of_range": dropped}
    if "points" in files and "points_id" in files:
        points = read_points_file(folder / files["points"]["file"])
        ids = read_points_ids(folder / files["points_id"]["file"])
        for sub in ("velodyne", "velodyne_id"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        velodyne_points(points).astype("<f4").tofile(root / "velodyne" / f"{key}.bin")
        np.ascontiguousarray(ids, dtype=np.uint8).tofile(root / "velodyne_id" / f"{key}.bin")
        written["velodyne"] = {"file": f"velodyne/{key}.bin", "points": int(points.shape[0])}
    render = folder / "render.json"
    if render.is_file():
        payload = json.loads(render.read_text(encoding="utf-8"))
        name = Path(str(record["file"])).name
        engine = next((r for r in payload.get("frame_records") or []
                       if isinstance(r, dict) and r.get("frame") == name), None)
        normals = read_normal_pass(folder, engine, width, height) if engine else None
        if normals is not None:
            (root / "normals").mkdir(parents=True, exist_ok=True)
            write_png16(root / "normals" / f"{key}.png", encode_normals16(normals))
            np.ascontiguousarray(normals, dtype="<f4").tofile(root / "normals" / f"{key}.f32")
            written["normals"] = {"file": f"normals/{key}.png", "f32": f"normals/{key}.f32"}
    return written


def pass_card_block(shipped: Dict[str, List[str]], formats: List[str]) -> Dict[str, Any]:
    """The dataset card's ``passes`` block: the consumer of every pass, the
    KITTI directories, and which runs shipped which pass files."""
    return {
        "consumers": PASS_CONSUMERS,
        "kitti_directories": {
            "flow_occ / flow_noc": "forward flow, occluded pixels valid / not",
            "backward_flow_occ / backward_flow_noc": "backward flow (not a KITTI directory)",
            "disp_occ_0": "the left camera's disparity",
            "velodyne / velodyne_id": ("points in velodyne axes with calib Tr_velo_to_cam, "
                                       "and one uint8 object id per point"),
            "normals": "16-bit PNG and float32 normals, scene frame",
        } if "kitti" in formats else None,
        "shipped": {run: list(files) for run, files in shipped.items() if files},
        "gate": ("a pass file ships only from a run whose verdict has its checks PASS: flow "
                 "flow_vs_keypoints and flow_static_null, disparity disparity_vs_right_depth, "
                 "points points_vs_depth, normals normals_vs_depth"),
    }
