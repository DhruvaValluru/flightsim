"""Dataset export: verified runs -> COCO, KITTI or WebDataset, with a card.

What goes in is a set of run directories (or batch directories holding
them), each with a ``capture_manifest.json``, rendered frames, and a
``verification.json`` whose checks did not fail -- an unverified run,
or one with a failed check, REFUSES the whole export by name; a
dataset built on a run whose labels were never checked is exactly the
thing this phase exists to prevent, and dropping such a run silently
would hide it.

What comes out:

* ``coco``        -- ``images/<split>/…png`` and
  ``annotations/instances_<split>.json`` (one category per airframe,
  the seven keypoints in KEYPOINT_NAMES order with COCO visibility 2 =
  in frame / 0 = not, bbox as ``[x, y, w, h]`` from the CLIPPED box,
  ``truncation``, and the 3-D box and horizon carried as extra keys).
* ``kitti``       -- ``<split>/image_2``, ``label_2`` (15-field lines:
  type, truncated, occluded, alpha, bbox, h w l, x y z, rotation_y),
  ``calib`` (``P0``-``P3`` the frame's pinhole, rectification identity).
  KITTI's camera frame is this manifest's (x right, y down, z forward),
  so location IS the 3-D box centre; ``rotation_y = atan2(-f_z, f_x)``
  for the body forward axis ``f`` in camera coordinates, and
  ``alpha = rotation_y - atan2(x, z)``, wrapped to ``[-pi, pi]``; both
  conventions are written into the card. ``occluded`` is 3 (unknown)
  unless the engine's occlusion fraction was recorded.
* ``webdataset``  -- ``<split>/shard-NNNNNN.tar`` of ``<key>.png`` +
  ``<key>.json`` (the frame's sidecar verbatim), sorted keys, a fixed
  shard size, so the tars are reproducible byte for byte.

The split is by **simulation digest**: every frame of one flight
(every camera, every randomisation of it) lands on one side of a
train/val/test line, assigned by a seeded shuffle of the simulations,
greedily by frame count. The card records the seed and the mapping.

``--image sensor`` exports the sensor-model frames (``*_sensor.png``)
with the labels mapped onto that sensor (``labels_sensor``); the
default is the ideal frame with the ideal labels. The 3-D box and the
horizon are pinhole quantities either way and are marked as such.
"""

from __future__ import annotations

import json
import math
import random
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core.capture.airframe import KEYPOINT_NAMES
from core.capture.manifest import (
    frame_sidecar, read_capture_manifest, software_revision,
)
from core.capture.verify import VERIFICATION_FILE

FORMATS = ("coco", "kitti", "webdataset")
SPLITS = ("train", "val", "test")
DEFAULT_FRACTIONS = (0.8, 0.1, 0.1)
KITTI_OCCLUDED_UNKNOWN = 3
CARD_JSON = "dataset.json"
CARD_MD = "DATASET_CARD.md"


class ExportError(ValueError):
    def __init__(self, constraint: str, message: str):
        super().__init__(message)
        self.constraint = constraint
        self.message = message


# -- runs ----------------------------------------------------------------

@dataclass
class Run:
    directory: Path
    manifest: Dict[str, Any]
    verification: Dict[str, Any]

    @property
    def name(self) -> str:
        return self.directory.name


def discover_runs(paths: Iterable) -> List[Path]:
    """Run directories under the given paths: a directory holding a
    capture manifest is a run; any other directory is searched one
    level down (a batch directory). Nothing found refuses."""
    found: List[Path] = []
    for entry in paths:
        entry = Path(entry)
        if (entry / "capture_manifest.json").is_file():
            found.append(entry)
            continue
        if entry.is_dir():
            children = sorted(p for p in entry.iterdir()
                              if (p / "capture_manifest.json").is_file())
            if children:
                found.extend(children)
                continue
        raise ExportError("export.runs",
                          f"{entry} is neither a run directory (no "
                          f"capture_manifest.json) nor a directory of runs")
    unique: List[Path] = []
    seen = set()
    for path in found:
        key = path.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def load_run(directory) -> Run:
    """A run and its verdict. Refuses by name a run with no
    verification.json, or one whose verification failed."""
    directory = Path(directory)
    manifest = read_capture_manifest(directory / "capture_manifest.json")
    record = directory / VERIFICATION_FILE
    if not record.is_file():
        raise ExportError(
            "export.unverified",
            f"{directory} has no {VERIFICATION_FILE}: run "
            f"`python -m flightsim.verify {directory}` first; a dataset is "
            f"not built on labels nobody checked")
    verification = json.loads(record.read_text(encoding="utf-8"))
    failed = [c["name"] for c in verification.get("checks", [])
              if c.get("status") == "FAIL"]
    if failed or not verification.get("ok", False):
        raise ExportError(
            "export.verification_failed",
            f"{directory} failed verification ({', '.join(failed) or 'ok=false'}); "
            f"refusing to export it")
    return Run(directory=directory, manifest=manifest, verification=verification)


# -- samples -------------------------------------------------------------

@dataclass
class Sample:
    key: str
    run: Run
    record: Dict[str, Any]
    image: Optional[Path]
    labels: Dict[str, Any]          # the 2-D labels in the exported image's pixels
    image_kind: str                 # "ideal" | "sensor"

    @property
    def simulation_digest(self) -> str:
        return str(self.run.manifest["simulation_digest"])

    @property
    def width(self) -> int:
        return int(self.record["width_px"])

    @property
    def height(self) -> int:
        return int(self.record["height_px"])

    @property
    def aircraft(self) -> str:
        return str(self.run.manifest["aircraft"])


def image_path(run: Run, record: Dict[str, Any], image: str) -> Path:
    file = str(record["file"])
    if image == "sensor":
        file = file[:-len(".png")] + "_sensor.png"
    return run.directory / file


def sample_labels(record: Dict[str, Any], image: str) -> Dict[str, Any]:
    """The 2-D labels in the exported image's own pixels, with the
    pinhole-only quantities carried and marked."""
    ideal = record["labels"]
    if image == "ideal":
        return {"bbox_2d": ideal.get("bbox_2d"),
                "bbox_2d_unclipped": ideal.get("bbox_2d_unclipped"),
                "truncation": ideal.get("truncation"),
                "in_frame": ideal.get("in_frame"),
                "keypoints": ideal.get("keypoints", {}),
                "bbox_3d_camera": ideal.get("bbox_3d_camera"),
                "horizon": ideal.get("horizon"),
                "pixels": "ideal pinhole"}
    sensor = record.get("sensor", {}).get("labels_sensor")
    if not sensor:
        raise ExportError("export.sensor_labels",
                          f"frame {record.get('file')} carries no labels_sensor; "
                          f"a manifest older than version 5 cannot export the "
                          f"sensor image with its labels")
    box = sensor.get("bbox_2d")
    unclipped = sensor.get("bbox_2d_unclipped")
    width, height = float(record["width_px"]), float(record["height_px"])
    truncation = None
    if unclipped:
        full = max(0.0, unclipped[2] - unclipped[0]) * max(0.0, unclipped[3] - unclipped[1])
        part = (max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])) if box else 0.0
        truncation = (1.0 - part / full) if full > 0 else 1.0
    keypoints = {}
    for name, kp in sensor.get("keypoints", {}).items():
        base = ideal.get("keypoints", {}).get(name, {})
        keypoints[name] = {"u": kp.get("u"), "v": kp.get("v"),
                           "in_frame": bool(kp.get("in_frame")),
                           "depth_m": base.get("depth_m"),
                           "camera_xyz_m": base.get("camera_xyz_m")}
    return {"bbox_2d": box, "bbox_2d_unclipped": unclipped,
            "truncation": truncation, "in_frame": box is not None,
            "keypoints": keypoints,
            "bbox_3d_camera": ideal.get("bbox_3d_camera"),
            "horizon": ideal.get("horizon"),
            "pixels": (f"sensor ({record['sensor'].get('profile')}); the 3-D "
                       f"box and the horizon are pinhole quantities")}


def collect_samples(runs: Sequence[Run], image: str = "ideal",
                    labels_only: bool = False) -> List[Sample]:
    """Every frame of every run. A frame whose image is absent refuses
    by name unless ``labels_only`` (then the sample carries no image and
    the card says so)."""
    if image not in ("ideal", "sensor"):
        raise ExportError("export.image", f"image must be ideal or sensor, not {image!r}")
    samples: List[Sample] = []
    missing: List[str] = []
    for run in runs:
        for record in run.manifest["frames"]:
            path = image_path(run, record, image)
            key = f"{run.name}_{record['camera_id']}_{int(record['index']):04d}"
            if not path.is_file():
                if labels_only:
                    path = None
                else:
                    missing.append(str(path))
                    continue
            samples.append(Sample(key=key, run=run, record=record, image=path,
                                  labels=sample_labels(record, image),
                                  image_kind=image))
    if missing:
        raise ExportError(
            "export.missing_frames",
            f"{len(missing)} frame(s) named by the manifests have no {image} "
            f"image on disk (first: {missing[0]}); render them, or pass "
            f"--labels-only to export annotations without pixels")
    if not samples:
        raise ExportError("export.empty", "no frames to export")
    return samples


# -- the split -----------------------------------------------------------

def assign_splits(samples: Sequence[Sample], fractions=DEFAULT_FRACTIONS,
                  seed: int = 0) -> Dict[str, str]:
    """{simulation digest: split}. Simulations are shuffled by the seed
    and dealt greedily by frame count toward the target fractions;
    every frame of a simulation goes to one split."""
    if len(fractions) != 3 or any(f < 0 for f in fractions) or abs(sum(fractions) - 1.0) > 1e-9:
        raise ExportError("export.split",
                          f"split fractions must be three non-negative numbers "
                          f"summing to 1, not {list(fractions)}")
    counts: Dict[str, int] = {}
    for sample in samples:
        counts[sample.simulation_digest] = counts.get(sample.simulation_digest, 0) + 1
    digests = sorted(counts)
    random.Random(int(seed)).shuffle(digests)
    total = sum(counts.values())
    targets = [f * total for f in fractions]
    filled = [0, 0, 0]
    assignment: Dict[str, str] = {}
    for digest in digests:
        # The split furthest below its target, by fraction of target;
        # a zero target never receives.
        best = None
        best_gap = None
        for i in range(3):
            if targets[i] <= 0:
                continue
            gap = (targets[i] - filled[i]) / targets[i]
            if best_gap is None or gap > best_gap:
                best, best_gap = i, gap
        if best is None:
            best = 0
        assignment[digest] = SPLITS[best]
        filled[best] += counts[digest]
    return assignment


# -- writers -------------------------------------------------------------

def _keypoints_coco(labels: Dict[str, Any]) -> Tuple[List[float], int]:
    flat: List[float] = []
    visible = 0
    for name in KEYPOINT_NAMES:
        kp = labels["keypoints"].get(name)
        if kp and kp.get("u") is not None and kp.get("in_frame"):
            flat += [float(kp["u"]), float(kp["v"]), 2]
            visible += 1
        else:
            flat += [0.0, 0.0, 0]
    return flat, visible


def _place_image(sample: Sample, target: Path) -> Optional[str]:
    if sample.image is None:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copyfile(sample.image, target)
    return target.name


def export_coco(samples: Sequence[Sample], out: Path, splits: Dict[str, str]
                ) -> Dict[str, int]:
    aircraft = sorted({s.aircraft for s in samples})
    categories = [{"id": i + 1, "name": name, "supercategory": "aircraft",
                   "keypoints": list(KEYPOINT_NAMES),
                   "skeleton": [[1, 2], [3, 4], [1, 5], [6, 7]]}
                  for i, name in enumerate(aircraft)]
    category_id = {c["name"]: c["id"] for c in categories}
    per_split: Dict[str, Dict[str, list]] = {
        s: {"images": [], "annotations": []} for s in SPLITS}
    image_id = 0
    annotation_id = 0
    for sample in sorted(samples, key=lambda s: s.key):
        split = splits[sample.simulation_digest]
        image_id += 1
        file_name = _place_image(sample, out / "images" / split / f"{sample.key}.png")
        per_split[split]["images"].append({
            "id": image_id, "file_name": file_name or f"{sample.key}.png",
            "width": sample.width, "height": sample.height,
            "run": sample.run.name, "camera_id": sample.record["camera_id"],
            "frame_index": int(sample.record["index"]),
            "t_s": sample.record["t_s"],
            "spec_digest": sample.run.manifest["spec_digest"],
            "simulation_digest": sample.simulation_digest,
            "pixels": sample.labels["pixels"],
        })
        box = sample.labels.get("bbox_2d")
        if box:
            annotation_id += 1
            flat, visible = _keypoints_coco(sample.labels)
            w, h = box[2] - box[0], box[3] - box[1]
            per_split[split]["annotations"].append({
                "id": annotation_id, "image_id": image_id,
                "category_id": category_id[sample.aircraft],
                "bbox": [box[0], box[1], w, h], "area": w * h, "iscrowd": 0,
                "keypoints": flat, "num_keypoints": visible,
                "truncation": sample.labels.get("truncation"),
                "bbox_3d_camera": sample.labels.get("bbox_3d_camera"),
                "horizon": sample.labels.get("horizon"),
            })
    counts = {}
    (out / "annotations").mkdir(parents=True, exist_ok=True)
    for split, content in per_split.items():
        payload = {"info": {"description": "flightsim labelled frames",
                            "conventions": "see DATASET_CARD.md"},
                   "licenses": [], "categories": categories, **content}
        (out / "annotations" / f"instances_{split}.json").write_text(
            json.dumps(payload, indent=1), encoding="utf-8")
        counts[split] = len(content["images"])
    return counts


def kitti_rotation_y(forward_axis_cam: Sequence[float]) -> float:
    fx, _, fz = forward_axis_cam
    return math.atan2(-fz, fx)


def kitti_alpha(rotation_y: float, centre_cam: Sequence[float]) -> float:
    alpha = rotation_y - math.atan2(centre_cam[0], centre_cam[2])
    while alpha > math.pi:
        alpha -= 2 * math.pi
    while alpha < -math.pi:
        alpha += 2 * math.pi
    return alpha


def kitti_label_line(sample: Sample) -> Optional[str]:
    labels = sample.labels
    box = labels.get("bbox_2d")
    box3 = labels.get("bbox_3d_camera")
    if not box or not box3:
        return None
    forward, right, down = box3["extents_m"]
    centre = box3["centre_m"]
    ry = kitti_rotation_y(box3["body_axes_in_camera"][0])
    alpha = kitti_alpha(ry, centre)
    occluded = KITTI_OCCLUDED_UNKNOWN
    engine = sample.record.get("engine_labels") or {}
    if isinstance(engine.get("occlusion"), (int, float)):
        fraction = float(engine["occlusion"])
        occluded = 0 if fraction < 0.05 else 1 if fraction < 0.5 else 2
    truncation = labels.get("truncation")
    fields = [sample.aircraft.replace(" ", "_"),
              f"{float(truncation or 0.0):.2f}", str(occluded), f"{alpha:.4f}",
              f"{box[0]:.2f}", f"{box[1]:.2f}", f"{box[2]:.2f}", f"{box[3]:.2f}",
              f"{down:.3f}", f"{right:.3f}", f"{forward:.3f}",
              f"{centre[0]:.3f}", f"{centre[1]:.3f}", f"{centre[2]:.3f}",
              f"{ry:.4f}"]
    return " ".join(fields)


def kitti_calib(record: Dict[str, Any]) -> str:
    fx, fy = float(record["fx_px"]), float(record["fy_px"])
    cx, cy = (float(v) for v in record["principal_point_px"])
    p = f"{fx:.6f} 0.000000 {cx:.6f} 0.000000 0.000000 {fy:.6f} {cy:.6f} 0.000000 0.000000 0.000000 1.000000 0.000000"
    identity3 = "1.000000 0.000000 0.000000 0.000000 1.000000 0.000000 0.000000 0.000000 1.000000"
    identity34 = "1.000000 0.000000 0.000000 0.000000 0.000000 1.000000 0.000000 0.000000 0.000000 0.000000 1.000000 0.000000"
    return "\n".join([f"P0: {p}", f"P1: {p}", f"P2: {p}", f"P3: {p}",
                      f"R0_rect: {identity3}", f"Tr_velo_to_cam: {identity34}",
                      f"Tr_imu_to_velo: {identity34}"]) + "\n"


def export_kitti(samples: Sequence[Sample], out: Path, splits: Dict[str, str]
                 ) -> Dict[str, int]:
    counts = {s: 0 for s in SPLITS}
    for sample in sorted(samples, key=lambda s: s.key):
        split = splits[sample.simulation_digest]
        root = out / split
        for sub in ("image_2", "label_2", "calib"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        _place_image(sample, root / "image_2" / f"{sample.key}.png")
        line = kitti_label_line(sample)
        (root / "label_2" / f"{sample.key}.txt").write_text(
            (line + "\n") if line else "", encoding="utf-8")
        (root / "calib" / f"{sample.key}.txt").write_text(
            kitti_calib(sample.record), encoding="utf-8")
        counts[split] += 1
    return counts


def export_webdataset(samples: Sequence[Sample], out: Path,
                      splits: Dict[str, str], shard_size: int = 1000
                      ) -> Dict[str, int]:
    if shard_size < 1:
        raise ExportError("export.shard_size", "shard size must be >= 1")
    by_split: Dict[str, List[Sample]] = {s: [] for s in SPLITS}
    for sample in sorted(samples, key=lambda s: s.key):
        by_split[splits[sample.simulation_digest]].append(sample)
    counts = {}
    for split, members in by_split.items():
        counts[split] = len(members)
        if not members:
            continue
        root = out / split
        root.mkdir(parents=True, exist_ok=True)
        for shard_index in range(0, len(members), shard_size):
            shard = members[shard_index:shard_index + shard_size]
            path = root / f"shard-{shard_index // shard_size:06d}.tar"
            with tarfile.open(path, "w") as tar:
                for sample in shard:
                    if sample.image is not None:
                        tar.add(str(sample.image), arcname=f"{sample.key}.png")
                    sidecar = frame_sidecar(sample.run.manifest, sample.record)
                    sidecar["export"] = {"labels": sample.labels,
                                         "split": split}
                    payload = json.dumps(sidecar, sort_keys=True).encode("utf-8")
                    info = tarfile.TarInfo(name=f"{sample.key}.json")
                    info.size = len(payload)
                    info.mtime = 0
                    import io
                    tar.addfile(info, io.BytesIO(payload))
    return counts


# -- the card --------------------------------------------------------------

def dataset_card(runs: Sequence[Run], samples: Sequence[Sample],
                 splits: Dict[str, str], counts: Dict[str, int], fmt: str,
                 fractions, seed: int, image: str, labels_only: bool
                 ) -> Dict[str, Any]:
    cameras = sorted({(s.run.name, str(s.record["camera_id"])) for s in samples})
    profiles = sorted({str(s.record.get("sensor", {}).get("profile", "ideal_pinhole"))
                       for s in samples})
    randomised = sorted(r.name for r in runs if r.manifest.get("randomization"))
    first = runs[0].manifest
    return {
        "format": fmt,
        "image": image,
        "labels_only": labels_only,
        "frames": len(samples),
        "frames_per_split": counts,
        "runs": [{
            "name": r.name, "directory": str(r.directory),
            "spec_digest": r.manifest["spec_digest"],
            "simulation_digest": r.manifest["simulation_digest"],
            "aircraft": r.manifest["aircraft"],
            "solve_source": r.manifest.get("solve_source"),
            "frames": len(r.manifest["frames"]),
            "cameras": [c["camera_id"] for c in r.manifest.get("cameras", [])],
            "randomization": r.manifest.get("randomization"),
            "verification": {k: r.verification.get(k)
                             for k in ("ok", "passed", "failed", "not_run")},
            "not_run": [c["name"] for c in r.verification.get("checks", [])
                        if c.get("status") == "NOT RUN"],
        } for r in runs],
        "split": {"by": "simulation_digest", "fractions": list(fractions),
                  "seed": int(seed), "assignment": dict(splits)},
        "aircraft": sorted({s.aircraft for s in samples}),
        "cameras": [f"{run}/{cam}" for run, cam in cameras],
        "sensor_profiles": profiles,
        "randomised_runs": randomised,
        "label_conventions": first.get("label_conventions"),
        "airframes": {r.manifest["aircraft"]: r.manifest.get("airframe") for r in runs},
        "kitti_conventions": {
            "camera_frame": "x right, y down, z forward (the manifest's)",
            "location": "bbox_3d_camera.centre_m",
            "dimensions_hwl": "extents down, right, forward (metres)",
            "rotation_y": "atan2(-f_z, f_x) for the body forward axis f in camera coordinates",
            "alpha": "rotation_y - atan2(x, z), wrapped to [-pi, pi]",
            "occluded": "3 (unknown) unless the engine recorded an occlusion fraction",
        },
        "coco_conventions": {
            "bbox": "[x, y, w, h] from the CLIPPED 2-D box; truncation carried",
            "keypoints": list(KEYPOINT_NAMES),
            "visibility": "2 = inside the image with positive depth, 0 otherwise",
        },
        "not_claimed": [
            "render reproducibility: not established in either direction "
            "until Gate 10-R runs on an engine (VALIDITY section 3)",
            "labels are the headless geometry of the recorded flight; the "
            "engine's masks and depth, where present, are checked against "
            "them by the verifier, not substituted for them",
            "the 3-D box and the horizon are pinhole quantities even when "
            "the sensor image is exported",
            "no photometric calibration: sun, fog and exposure are the "
            "harness's calibrated look points or a sampled range between them",
        ],
        "software_revision": software_revision(),
        "manifest_versions": sorted({int(r.manifest["manifest_version"]) for r in runs}),
    }


def render_card(card: Dict[str, Any]) -> str:
    lines = [
        "# Dataset card",
        "",
        f"Format: **{card['format']}**; images: {card['image']}"
        + (" (labels only, no pixels)" if card["labels_only"] else ""),
        f"Frames: {card['frames']} -- " + ", ".join(
            f"{s}: {n}" for s, n in card["frames_per_split"].items()),
        f"Aircraft: {', '.join(card['aircraft'])}",
        f"Sensor profiles: {', '.join(card['sensor_profiles'])}",
        f"Split by simulation digest, fractions {card['split']['fractions']}, "
        f"seed {card['split']['seed']}: {len(card['split']['assignment'])} "
        f"simulation(s)",
        f"Software revision: {card['software_revision']}",
        "",
        "## Runs",
        "",
    ]
    for run in card["runs"]:
        v = run["verification"]
        lines.append(
            f"- `{run['name']}` {run['aircraft']}, {run['frames']} frames, "
            f"cameras {run['cameras']}, solve {run['solve_source']}, "
            f"verification {v['passed']} passed / {v['failed']} failed / "
            f"{v['not_run']} not run"
            + (f" (NOT RUN: {', '.join(run['not_run'])})" if run["not_run"] else "")
            + (" -- randomised" if run["randomization"] else ""))
    lines += ["", "## Conventions", ""]
    for key in ("coco_conventions", "kitti_conventions"):
        for name, text in card[key].items():
            lines.append(f"- {key.split('_')[0]} {name}: {text}")
    lines += ["", "## Not claimed", ""]
    lines += [f"- {item}" for item in card["not_claimed"]]
    return "\n".join(lines) + "\n"


# -- the whole thing -------------------------------------------------------

def export(paths: Sequence, out, fmt: str, fractions=DEFAULT_FRACTIONS,
           seed: int = 0, image: str = "ideal", labels_only: bool = False,
           shard_size: int = 1000) -> Dict[str, Any]:
    if fmt not in FORMATS:
        raise ExportError("export.format", f"format must be one of {FORMATS}, not {fmt!r}")
    out = Path(out)
    runs = [load_run(d) for d in discover_runs(paths)]
    samples = collect_samples(runs, image=image, labels_only=labels_only)
    splits = assign_splits(samples, fractions, seed)
    out.mkdir(parents=True, exist_ok=True)
    if fmt == "coco":
        counts = export_coco(samples, out, splits)
    elif fmt == "kitti":
        counts = export_kitti(samples, out, splits)
    else:
        counts = export_webdataset(samples, out, splits, shard_size=shard_size)
    card = dataset_card(runs, samples, splits, counts, fmt, fractions, seed,
                        image, labels_only)
    (out / CARD_JSON).write_text(json.dumps(card, indent=1), encoding="utf-8")
    (out / CARD_MD).write_text(render_card(card), encoding="utf-8")
    return card
