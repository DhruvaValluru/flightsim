"""Dataset export: verified runs -> COCO, KITTI, WebDataset, YOLO or
Pascal VOC, with a card.

What goes in is a set of run directories (or batch directories holding
them), each with a ``capture_manifest.json``, rendered frames, and a
``verification.json`` whose checks did not fail -- an unverified run,
or one with a failed check, REFUSES the whole export by name
(``export.unverified`` / ``export.verification_failed``); a dataset
built on a run whose labels were never checked is exactly the thing
this phase exists to prevent, and dropping such a run silently would
hide it.

What comes out (``--format`` takes one name or a comma list; one
format writes into ``<out>`` directly, several write ``<out>/<format>/``
each, with ONE card at ``<out>``):

* ``coco``        -- ``images/<split>/…png`` and
  ``annotations/instances_<split>.json`` (categories from the taxonomy
  when the manifests carry one, else one per airframe; the seven
  keypoints in KEYPOINT_NAMES order with COCO visibility 2 = in frame /
  0 = not, bbox as ``[x, y, w, h]`` from the CLIPPED box,
  ``truncation``, the 3-D box and horizon carried as extra keys, and
  ``segmentation`` as uncompressed RLE from the ID mask where a mask
  exists beside the frame).
* ``kitti``       -- ``<split>/image_2``, ``label_2`` (15-field lines:
  type, truncated, occluded, alpha, bbox, h w l, x y z, rotation_y),
  ``calib`` (``P0``-``P3`` the frame's pinhole, rectification identity).
  KITTI's camera frame is this manifest's (x right, y down, z forward),
  so location IS the 3-D box centre; ``rotation_y = atan2(-f_z, f_x)``
  for the body forward axis ``f`` in camera coordinates, and
  ``alpha = rotation_y - atan2(x, z)``, wrapped to ``[-pi, pi]``; both
  conventions are written into the card. ``occluded`` is derived from
  the object's ``visible_fraction`` (>= 0.95 -> 0, >= 0.5 -> 1, else 2)
  and is 3 (unknown) when no visibility was recorded.
* ``webdataset``  -- ``<split>/shard-NNNNNN.tar`` of ``<key>.png`` +
  ``<key>.json`` (the frame's sidecar verbatim), plus ``<key>.mask.png``,
  ``<key>.class.png`` and ``<key>.depth.f32`` when those label files
  exist beside the frame; sorted keys, a fixed shard size, every member
  written from bytes with mtime 0 / uid 0, so the tars are reproducible
  byte for byte with or without pixels.
* ``yolo``        -- the Ultralytics detect layout: ``images/<split>/``,
  ``labels/<split>/<key>.txt`` with ``class cx cy w h`` normalised to
  the image (0-based class index in taxonomy order), ``data.yaml`` with
  ``train``, ``val``, ``test`` and ``names`` and NO ``path`` key: with
  one, Ultralytics resolves the split directories against its own
  datasets directory (or the process's working directory), not against
  the yaml; without one it resolves them beside the yaml, which is
  where they are.
* ``voc``         -- the Pascal VOC devkit layout at ONE root:
  ``JPEGImages/<key>.png`` (the PNGs as they are; the directory name is
  the devkit's), ``Annotations/<key>.xml`` (folder, filename, size,
  one ``object`` per labelled object with ``name``, ``truncated``,
  ``occluded``, ``difficult``, ``bndbox``), ``ImageSets/Main/<split>.txt``
  listing the stems of each split. ``bndbox`` is the devkit's 1-based
  inclusive integer box that covers the float box (floor+1 / ceil).
  ``truncated`` = the object leaves the frame (``truncation > 0``, or
  ``fraction_in_frame < 1`` when a record carries that key);
  ``occluded`` = ``visible_fraction < 0.9`` when a visibility was
  recorded, else 0 (the card says so); ``difficult`` = the clipped box's
  longer side is under the not-claimed pixel threshold (the object's
  own ``objects_under_px`` entry, else ``NOT_CLAIMED_EXTENT_PX``).

The label source is the manifest's per-frame ``labels`` block. When a
frame carries ``labels.objects[]`` (manifest 6, contracts §3) every
object is exported with its class resolved through the manifest's
``objects[]`` / taxonomy; otherwise the single primary airframe of the
existing ``labels`` keys is the one object and its class is the
airframe name. The reader keys on the PRESENCE of ``objects[]``, not on
the manifest version, so both shapes read on either build.

The split is by **simulation digest**: every frame of one flight
(every camera, every randomisation of it) lands on one side of a
train/val/test line, assigned by a seeded shuffle of the simulations,
greedily by frame count. The card records the seed and the mapping.

``--image sensor`` exports the sensor-model frames (``*_sensor.png``)
with the labels mapped onto that sensor (``labels_sensor``); the
default is the ideal frame with the ideal labels. The 3-D box and the
horizon are pinhole quantities either way and are marked as such.

Provenance: a verdict that names the manifest it graded
(``verification.json`` ``manifest_sha256``, written by the batch and
campaign runners through ``bind_verification``) is compared with the
manifest on disk, and a manifest changed since -- a re-render, a label
pass, a hand edit -- refuses ``export.verification_stale`` by name; a
verdict without that key (an older verifier) is accepted and the card
says the binding is missing. Each camera's ``render.json`` ``drawn``,
``render_settings`` and ``look_applied`` are copied into the card per
run (null, with the reason, for a headless run), so what the engine
drew and every rendering switch reach the dataset's consumer.

What is NOT claimed by this module: it does not check a label -- it
reads the verifier's verdict and refuses without a green one; it reads
``render.json`` for the card's provenance only, never for a label (the
per-object visibility it exports is what the manifest record carries);
it does not decide a taxonomy (it refuses ``export.taxonomy`` when the
runs disagree, and an object whose class is outside the list refuses
before a file is written); the YOLO and VOC writers have been
round-tripped through independent readers on fabricated pixels only,
never through a training stack.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import random
import shutil
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET

from core.capture.airframe import KEYPOINT_NAMES
from core.capture.manifest import (
    frame_sidecar, read_capture_manifest, software_revision,
)
from core.capture.verify import VERIFICATION_FILE

FORMATS = ("coco", "kitti", "webdataset", "yolo", "voc")
SPLITS = ("train", "val", "test")
DEFAULT_FRACTIONS = (0.8, 0.1, 0.1)
KITTI_OCCLUDED_UNKNOWN = 3
CARD_JSON = "dataset.json"
CARD_MD = "DATASET_CARD.md"

#: KITTI ``occluded`` from ``visible_fraction`` (contracts §3): fully
#: visible, partly, largely occluded; 3 when no visibility was recorded.
KITTI_VISIBLE_FULL = 0.95
KITTI_VISIBLE_PARTLY = 0.5
#: Pascal VOC ``occluded`` flag: set when less than this fraction of the
#: object's unoccluded footprint is visible.
VOC_OCCLUDED_BELOW = 0.9
#: The pixel extent under which the labels are NOT claimed (contracts
#: §3: "not claimed under 16 px"); a per-object ``not_claimed`` entry
#: ``objects_under_px: N`` overrides it. VOC ``difficult`` is derived
#: from it, and the card carries it.
NOT_CLAIMED_EXTENT_PX = 16
#: The per-object ``not_claimed`` entry that states the threshold.
NOT_CLAIMED_EXTENT_KEY = "objects_under_px"
#: The primary airframe's ID-mask value on a single-aircraft run
#: (verify.AIRCRAFT_INSTANCE_ID, re-stated here rather than imported:
#: the export does not import the verifier's numbers).
PRIMARY_INT_ID = 1
#: The verifier checks that grade the ID mask (contracts §4); the
#: class image is graded by the same pair (``mask_integers_only`` reads
#: it against the ID mask, ``mask_vs_geometry`` places that mask).
MASK_CHECKS = ("mask_integers_only", "mask_vs_geometry")
#: The verifier checks that grade the raw depth image.
DEPTH_CHECKS = ("depth_range", "depth_vs_geometry")
#: The label files the render commandlet writes beside a frame
#: (contracts §1): suffix -> WebDataset member extension.
LABEL_FILES = (("_mask.png", "mask.png"), ("_class.png", "class.png"),
               ("_depth.f32", "depth.f32"))
#: The checks that must PASS before a label file ships, per suffix.
LABEL_FILE_CHECKS = {"_mask.png": MASK_CHECKS, "_class.png": MASK_CHECKS,
                     "_depth.f32": DEPTH_CHECKS}
#: The label files each format ships: COCO carries the ID mask as
#: ``segmentation``, WebDataset every file found beside the frame. A
#: run whose file the verifier never graded refuses
#: ``export.unverified_labels`` for these when that file is on disk.
SHIPPED_LABEL_FILES = {"coco": ("_mask.png",),
                       "webdataset": tuple(s for s, _ in LABEL_FILES)}
#: Formats that ship the ID mask (Phase 10 API, kept).
MASK_SHIPPING_FORMATS = tuple(SHIPPED_LABEL_FILES)
#: The key a verdict carries to name the manifest it graded (the
#: sha256 of ``capture_manifest.json`` as bytes); written by
#: ``bind_verification``, compared by ``load_run``.
MANIFEST_DIGEST_KEY = "manifest_sha256"
#: The engine's per-camera record and the root keys the card carries
#: from it as provenance (contracts §6.2): what was drawn, every
#: rendering switch, the look actually applied.
RENDER_JSON = "render.json"
RENDER_PROVENANCE_KEYS = ("drawn", "render_settings", "look_applied")
#: The taxonomy class that is an airframe (core/scenario/blocks.py
#: DEFAULT_CLASSES[0]); COCO's airframe keypoints are declared on it
#: and on the airframe-name classes of a run without a taxonomy.
AIRCRAFT_CLASS = "aircraft"


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
    #: sha256 of capture_manifest.json as read; the verdict's
    #: ``manifest_sha256`` matched it (or the verdict carries none).
    manifest_sha256: str = ""
    #: {camera_id: {drawn, render_settings, look_applied}} from each
    #: camera's render.json; empty for a run with none (headless).
    render: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.directory.name

    @property
    def verification_bound(self) -> bool:
        """The verdict names the manifest it graded."""
        return MANIFEST_DIGEST_KEY in self.verification

    def airframes(self) -> List[str]:
        """Every airframe in the run: the primary (``aircraft``) and each
        ``objects[]`` entry named ``aircraft:<airframe>:<n>`` (contracts
        §3 -- the traffic aircraft are objects, not the manifest's
        ``aircraft``)."""
        names = {str(self.manifest["aircraft"])}
        for entry in self.manifest.get("objects") or []:
            if not isinstance(entry, dict) or entry.get("class") != AIRCRAFT_CLASS:
                continue
            parts = str(entry.get("id", "")).split(":")
            if len(parts) == 3 and parts[0] == AIRCRAFT_CLASS and parts[1]:
                names.add(parts[1])
        return sorted(names)


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
    # Every frame is keyed by its run's directory name, so two DIFFERENT
    # runs with one name would write one set of files over the other:
    # the first run's pixels under the second run's boxes. Refuse.
    by_name: Dict[str, List[Path]] = {}
    for path in unique:
        by_name.setdefault(path.name, []).append(path)
    clashes = {name: paths for name, paths in by_name.items() if len(paths) > 1}
    if clashes:
        name, paths = sorted(clashes.items())[0]
        raise ExportError(
            "export.run_names",
            f"{len(paths)} different runs share the name {name!r} ({paths[0]} "
            f"and {paths[1]}); every exported frame is named after its run, so "
            f"export them from directories with distinct names")
    return unique


def manifest_digest(directory) -> str:
    """sha256 of ``capture_manifest.json`` as bytes: the identity a
    verdict is bound to."""
    return hashlib.sha256((Path(directory) / "capture_manifest.json").read_bytes()).hexdigest()


def bind_verification(directory) -> Path:
    """Record in a run's ``verification.json`` the digest of the manifest
    it graded (``manifest_sha256``), so ``load_run`` can tell a verdict
    from a verdict on labels that changed since. Written atomically
    (a staged file, then ``os.replace``) like the verdict itself; the
    batch and campaign runners call this right after the verifier."""
    directory = Path(directory)
    record = directory / VERIFICATION_FILE
    verification = json.loads(record.read_text(encoding="utf-8"))
    verification[MANIFEST_DIGEST_KEY] = manifest_digest(directory)
    staged = record.with_name(f".{VERIFICATION_FILE}.{os.getpid()}.bind.tmp")
    staged.write_text(json.dumps(verification, indent=1), encoding="utf-8")
    os.replace(staged, record)
    return record


def render_provenance(directory) -> Dict[str, Dict[str, Any]]:
    """{camera_id: {drawn, render_settings, look_applied}} read from
    ``frames/<camera>/render.json`` for every camera that has one; a
    key the record lacks is None. Nothing else of render.json is read:
    the labels come from the manifest."""
    out: Dict[str, Dict[str, Any]] = {}
    frames = Path(directory) / "frames"
    if not frames.is_dir():
        return out
    for camera in sorted(p for p in frames.iterdir() if p.is_dir()):
        path = camera / RENDER_JSON
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        if not isinstance(payload, dict):
            out[camera.name] = {k: None for k in RENDER_PROVENANCE_KEYS}
            out[camera.name]["note"] = f"{path} is not a JSON record"
            continue
        out[camera.name] = {k: payload.get(k) for k in RENDER_PROVENANCE_KEYS}
    return out


def load_run(directory) -> Run:
    """A run and its verdict. Refuses by name a run with no
    verification.json (``export.unverified``), or one whose
    verification failed (``export.verification_failed``)."""
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
    digest = manifest_digest(directory)
    bound = verification.get(MANIFEST_DIGEST_KEY)
    if bound is not None and str(bound) != digest:
        raise ExportError(
            "export.verification_stale",
            f"{directory}'s labels changed after they were checked "
            f"(capture_manifest.json is not the file the verdict graded: "
            f"{digest[:12]} now, {str(bound)[:12]} then); run "
            f"`python -m flightsim.verify {directory}` again before exporting")
    return Run(directory=directory, manifest=manifest, verification=verification,
               manifest_sha256=digest, render=render_provenance(directory))


# -- the taxonomy --------------------------------------------------------

def run_taxonomy(manifest: Dict[str, Any]) -> Optional[List[str]]:
    """The class list a manifest carries, in class_id order (class_id =
    position + 1), or None for a manifest that names no taxonomy (a
    version-5 single-airframe run: its one class is the airframe name).

    Read from a top-level ``taxonomy`` (a list of names, or a mapping
    with ``classes``), else from the top-level ``objects[]`` entries'
    ``class`` / ``class_id`` pairs. Refuses ``export.taxonomy`` when
    those pairs are not a contiguous 1..N list with one name per id.
    """
    taxonomy = manifest.get("taxonomy")
    if isinstance(taxonomy, dict):
        taxonomy = taxonomy.get("classes")
        if isinstance(taxonomy, dict):
            taxonomy = taxonomy.get("value")
    if isinstance(taxonomy, list) and taxonomy and all(isinstance(t, str) for t in taxonomy):
        return [str(t) for t in taxonomy]
    objects = manifest.get("objects")
    if not isinstance(objects, list) or not objects:
        return None
    by_id: Dict[int, str] = {}
    for entry in objects:
        try:
            class_id = int(entry["class_id"])
            name = str(entry["class"])
        except (KeyError, TypeError, ValueError):
            raise ExportError("export.taxonomy",
                              f"objects[] entry {entry!r} carries no class / "
                              f"class_id pair; the taxonomy cannot be read")
        if by_id.get(class_id, name) != name:
            raise ExportError("export.taxonomy",
                              f"class_id {class_id} is both {by_id[class_id]!r} "
                              f"and {name!r} in one manifest")
        by_id[class_id] = name
    if sorted(by_id) != list(range(1, len(by_id) + 1)):
        raise ExportError("export.taxonomy",
                          f"objects[] class ids {sorted(by_id)} are not 1..N; "
                          f"the taxonomy's order cannot be recovered")
    return [by_id[i] for i in range(1, len(by_id) + 1)]


def dataset_taxonomy(samples: Sequence["Sample"]) -> Tuple[List[str], str]:
    """The class names of the whole export, in class-id order, and where
    they came from: ``"manifest taxonomy"`` when every run carries the
    SAME list, ``"airframe names"`` (sorted, as Phase 10 wrote COCO
    categories) when no run carries one. A mix, or two different lists,
    refuses ``export.taxonomy`` -- one dataset, one class list."""
    lists = {}
    for sample in samples:
        lists[sample.run.name] = run_taxonomy(sample.run.manifest)
    named = {tuple(t) for t in lists.values() if t is not None}
    unnamed = [name for name, t in lists.items() if t is None]
    if named and unnamed:
        raise ExportError(
            "export.taxonomy",
            f"run(s) {sorted(unnamed)} name no taxonomy while others do; one "
            f"dataset takes one class list -- export them separately")
    if len(named) > 1:
        raise ExportError(
            "export.taxonomy",
            f"the runs carry different taxonomies {sorted(named)}; one "
            f"dataset takes one class list -- export them separately")
    if named:
        return list(named.pop()), "manifest taxonomy"
    return sorted({s.aircraft for s in samples}), "airframe names"


def refuse_classes_outside_taxonomy(samples: Sequence["Sample"],
                                    names: Sequence[str]) -> None:
    """Every object of every frame resolves in the taxonomy, checked
    BEFORE a directory is made: a refusal raised from inside a writer
    would leave a half-written tree with no card."""
    for sample in samples:
        for obj in sample.objects:
            class_index(obj, names)


def class_index(obj: Dict[str, Any], names: Sequence[str]) -> int:
    """0-based position of an object's class in the taxonomy."""
    if obj.get("class_id") is not None:
        index = int(obj["class_id"]) - 1
        if not 0 <= index < len(names) or names[index] != obj["class_name"]:
            raise ExportError("export.taxonomy",
                              f"object {obj.get('id')!r} has class_id "
                              f"{obj['class_id']} ({obj['class_name']!r}) outside "
                              f"the taxonomy {list(names)}")
        return index
    try:
        return list(names).index(obj["class_name"])
    except ValueError:
        raise ExportError("export.taxonomy",
                          f"class {obj['class_name']!r} is not in the taxonomy "
                          f"{list(names)}")


# -- samples -------------------------------------------------------------

@dataclass
class Sample:
    key: str
    run: Run
    record: Dict[str, Any]
    image: Optional[Path]
    labels: Dict[str, Any]          # the 2-D labels in the exported image's pixels
    image_kind: str                 # "ideal" | "sensor"
    #: One entry per labelled object (see ``object_labels``); the
    #: primary airframe first. Kept OFF ``labels`` so the sidecar a
    #: WebDataset carries is unchanged for a run without ``objects[]``.
    objects: List[Dict[str, Any]] = field(default_factory=list)

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


def label_file_path(run: Run, record: Dict[str, Any], suffix: str) -> Path:
    """``frames/<cam>/frame_NNNN.png`` -> the commandlet's label file
    with ``suffix`` (``_mask.png``, ``_class.png``, ``_depth.f32``)."""
    file = str(record["file"])
    return run.directory / (file[:-len(".png")] + suffix)


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


def _object_index(manifest: Dict[str, Any]) -> Dict[Any, Dict[str, Any]]:
    """The manifest's top-level ``objects[]`` keyed by ``id`` and by
    ``int_id`` (both, so a per-frame record naming either resolves)."""
    index: Dict[Any, Dict[str, Any]] = {}
    for entry in manifest.get("objects") or []:
        if isinstance(entry, dict):
            if entry.get("id") is not None:
                index[("id", str(entry["id"]))] = entry
            if entry.get("int_id") is not None:
                index[("int_id", int(entry["int_id"]))] = entry
    return index


def object_labels(run: Run, record: Dict[str, Any], labels: Dict[str, Any],
                  image: str) -> List[Dict[str, Any]]:
    """The labelled objects of one frame, primary first, each as
    ``{id, int_id, role, class_name, class_id, bbox_2d, bbox_2d_unclipped,
    truncation, fraction_in_frame, in_frame, visible_fraction,
    occluded_by, keypoints, bbox_3d_camera, horizon, not_claimed}``.

    Without ``labels.objects[]`` the one object is the primary airframe
    from ``labels`` (class = the airframe name, no visibility, no
    ``not_claimed``). With it, every entry is an object; its class comes
    from the entry's own ``class`` / ``class_id`` or from the manifest's
    ``objects[]`` by ``id`` / ``int_id``; the primary (``int_id`` 1 or
    ``role: primary``) takes the 2-D labels already mapped onto the
    exported image (``labels``, i.e. the sensor mapping under
    ``--image sensor``); any other object under ``--image sensor``
    needs its own ``labels_sensor.objects[]`` entry or refuses
    ``export.sensor_labels`` -- an ideal-pinhole box on a sensor image
    would be a silently wrong label.
    """
    ideal = record.get("labels") or {}
    entries = ideal.get("objects")
    if not isinstance(entries, list):
        return [{
            "id": f"aircraft:{run.manifest['aircraft']}:0",
            "int_id": PRIMARY_INT_ID, "role": "primary",
            "class_name": str(run.manifest["aircraft"]), "class_id": None,
            "bbox_2d": labels.get("bbox_2d"),
            "bbox_2d_unclipped": labels.get("bbox_2d_unclipped"),
            "truncation": labels.get("truncation"),
            "fraction_in_frame": None,
            "in_frame": labels.get("in_frame"),
            "visible_fraction": None, "occluded_by": [],
            "keypoints": labels.get("keypoints", {}),
            "bbox_3d_camera": labels.get("bbox_3d_camera"),
            "horizon": labels.get("horizon"),
            "not_claimed": [],
        }]
    index = _object_index(run.manifest)
    sensor_objects: Dict[Any, Dict[str, Any]] = {}
    if image == "sensor":
        for entry in (record.get("sensor", {}).get("labels_sensor", {}) or {}).get("objects") or []:
            if isinstance(entry, dict) and entry.get("id") is not None:
                sensor_objects[str(entry["id"])] = entry
    out: List[Dict[str, Any]] = []
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ExportError("export.taxonomy",
                              f"frame {record.get('file')} labels.objects[{position}] "
                              f"is not a record")
        int_id = entry.get("int_id")
        object_id = entry.get("id")
        top = (index.get(("id", str(object_id))) if object_id is not None else None) \
            or (index.get(("int_id", int(int_id))) if int_id is not None else None) or {}
        class_id = entry.get("class_id", top.get("class_id"))
        class_name = entry.get("class", top.get("class"))
        if class_id is None and class_name is None:
            raise ExportError("export.taxonomy",
                              f"object {object_id!r} (int_id {int_id}) in frame "
                              f"{record.get('file')} has no class in its record or "
                              f"in the manifest's objects[]")
        if class_name is None:
            taxonomy = run_taxonomy(run.manifest)
            if taxonomy and 1 <= int(class_id) <= len(taxonomy):
                class_name = taxonomy[int(class_id) - 1]
            else:
                raise ExportError("export.taxonomy",
                                  f"object {object_id!r} has class_id {class_id} but "
                                  f"the manifest names no class for it")
        role = top.get("role") or ("primary" if (int_id == PRIMARY_INT_ID or position == 0) else "object")
        primary = role == "primary"
        if primary:
            box, unclipped, truncation = (labels.get("bbox_2d"), labels.get("bbox_2d_unclipped"),
                                          labels.get("truncation"))
            keypoints = labels.get("keypoints", {})
            in_frame = labels.get("in_frame")
        elif image == "sensor":
            mapped = sensor_objects.get(str(object_id))
            if mapped is None:
                raise ExportError(
                    "export.sensor_labels",
                    f"object {object_id!r} in frame {record.get('file')} has no "
                    f"labels_sensor.objects[] entry; its ideal-pinhole box is not "
                    f"a label for the sensor image")
            box, unclipped = mapped.get("bbox_2d"), mapped.get("bbox_2d_unclipped")
            truncation = mapped.get("truncation", entry.get("truncation"))
            keypoints = {}
            in_frame = box is not None
        else:
            box = entry.get("bbox_2d")
            if box is None:
                box = entry.get("bbox_2d_tight")
            unclipped, truncation = entry.get("bbox_2d_unclipped"), entry.get("truncation")
            keypoints = entry.get("keypoints", {}) or {}
            in_frame = entry.get("in_frame", box is not None)
        out.append({
            "id": str(object_id) if object_id is not None else f"int_id:{int_id}",
            "int_id": int(int_id) if int_id is not None else None,
            "role": role,
            "class_name": str(class_name),
            "class_id": int(class_id) if class_id is not None else None,
            "bbox_2d": box, "bbox_2d_unclipped": unclipped,
            "truncation": truncation,
            "fraction_in_frame": entry.get("fraction_in_frame"),
            "in_frame": in_frame,
            "visible_fraction": entry.get("visible_fraction"),
            "occluded_by": list(entry.get("occluded_by") or []),
            "keypoints": keypoints,
            "bbox_3d_camera": labels.get("bbox_3d_camera") if primary else entry.get("bbox_3d_camera"),
            "horizon": labels.get("horizon") if primary else entry.get("horizon"),
            "not_claimed": [str(n) for n in (entry.get("not_claimed") or [])],
        })
    out.sort(key=lambda o: (o["role"] != "primary", o["int_id"] if o["int_id"] is not None else 1 << 30))
    return out


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
            labels = sample_labels(record, image)
            samples.append(Sample(key=key, run=run, record=record, image=path,
                                  labels=labels, image_kind=image,
                                  objects=object_labels(run, record, labels, image)))
    if missing:
        raise ExportError(
            "export.missing_frames",
            f"{len(missing)} frame(s) named by the manifests have no {image} "
            f"image on disk (first: {missing[0]}); render them, or pass "
            f"--labels-only to export annotations without pixels")
    if not samples:
        raise ExportError("export.empty", "no frames to export")
    return samples


def refuse_unverified_labels(samples: Sequence[Sample], formats: Sequence[str]
                             ) -> Dict[str, List[str]]:
    """A format may not ship a label file the verifier never graded:
    for every file a chosen format ships (``SHIPPED_LABEL_FILES``: the
    ID mask for COCO; the ID mask, the class image and the depth for
    WebDataset) that is on disk for any frame of a run, every check in
    ``LABEL_FILE_CHECKS`` for it must be PASS in the run's verdict, or
    the export refuses ``export.unverified_labels`` by name. A run with
    none of those files on disk ships none and is not affected (every
    Phase 10 run). Returns {run name: the suffixes shipped}, for the
    card."""
    suffixes: List[str] = []
    for fmt in formats:
        for suffix in SHIPPED_LABEL_FILES.get(fmt, ()):
            if suffix not in suffixes:
                suffixes.append(suffix)
    shipped: Dict[str, List[str]] = {}
    if not suffixes:
        return shipped
    for run in {s.run.name: s.run for s in samples}.values():
        passed = {c.get("name") for c in run.verification.get("checks", [])
                  if c.get("status") == "PASS"}
        for suffix in suffixes:
            on_disk = any(label_file_path(run, s.record, suffix).is_file()
                          for s in samples if s.run is run)
            if not on_disk:
                continue
            ungraded = [name for name in LABEL_FILE_CHECKS[suffix] if name not in passed]
            if ungraded:
                ships = [f for f in formats if suffix in SHIPPED_LABEL_FILES.get(f, ())]
                raise ExportError(
                    "export.unverified_labels",
                    f"{run.directory} has {suffix} label files on disk that the "
                    f"verifier did not grade ({', '.join(ungraded)} not PASS); a "
                    f"format that ships them ({', '.join(ships)}) refuses them -- "
                    f"verify the run on a build with those checks, or export a "
                    f"format without them")
            shipped.setdefault(run.name, []).append(suffix)
    return shipped


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


def sample_split(sample: Sample, splits: Dict[str, str]) -> str:
    """The split a sample lands in: its FLIGHT's, never its own. Every
    writer goes through this one lookup so a frame of one simulation
    cannot straddle train and val."""
    return splits[sample.simulation_digest]


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
    """Copy the frame under its key. A file already there with the same
    bytes is left (a re-export); one with DIFFERENT bytes refuses
    ``export.out_directory`` by name -- keeping it would put another
    export's pixels under this run's labels."""
    if sample.image is None:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != sample.image.read_bytes():
            raise ExportError(
                "export.out_directory",
                f"{target} already holds a different image than {sample.image} "
                f"(the dataset directory was used for another export); export "
                f"into an empty directory")
        return target.name
    shutil.copyfile(sample.image, target)
    return target.name


def mask_rle(mask_path: Path, int_id: int) -> Optional[Dict[str, Any]]:
    """COCO uncompressed RLE (``{"size": [h, w], "counts": [...]}``,
    column-major runs starting with a background run) of the pixels of
    an ID mask equal to ``int_id``. Computed here with numpy; the
    round-trip test decodes it with pycocotools, which this module does
    not import. None when the object has no pixel."""
    import numpy as np
    from PIL import Image

    with Image.open(mask_path) as image:
        array = np.asarray(image)
    if array.ndim == 3:
        array = array[..., 0]
    binary = (array == int_id).astype(np.uint8)
    if not binary.any():
        return None
    flat = binary.flatten(order="F")
    changes = np.flatnonzero(np.diff(flat)) + 1
    boundaries = np.concatenate(([0], changes, [flat.size]))
    counts = np.diff(boundaries).tolist()
    if flat[0] == 1:
        counts = [0] + counts
    return {"size": [int(array.shape[0]), int(array.shape[1])],
            "counts": [int(c) for c in counts]}


def airframe_classes(samples: Sequence[Sample], names: Sequence[str]) -> List[str]:
    """The taxonomy classes that are airframes: ``AIRCRAFT_CLASS`` when
    the list names it, and every class of an object that carries the
    airframe keypoints (the airframe-name classes of a run without a
    taxonomy). Only these declare COCO keypoints and a skeleton."""
    classes = {n for n in names if n == AIRCRAFT_CLASS}
    for sample in samples:
        for obj in sample.objects:
            if obj.get("keypoints") and obj["class_name"] in names:
                classes.add(obj["class_name"])
    return [n for n in names if n in classes]


def coco_categories(samples: Sequence[Sample], names: Sequence[str]) -> List[Dict[str, Any]]:
    """One category per taxonomy class. An airframe class keeps the
    seven keypoints and the airframe skeleton under supercategory
    ``aircraft``; any other class is its own supercategory with no
    keypoints (a terrain annotation has none to declare)."""
    airframes = set(airframe_classes(samples, names))
    categories = []
    for i, name in enumerate(names):
        if name in airframes:
            categories.append({"id": i + 1, "name": name, "supercategory": AIRCRAFT_CLASS,
                               "keypoints": list(KEYPOINT_NAMES),
                               "skeleton": [[1, 2], [3, 4], [1, 5], [6, 7]]})
        else:
            categories.append({"id": i + 1, "name": name, "supercategory": name})
    return categories


def coco_licenses(runs: Sequence[Run]) -> List[Dict[str, Any]]:
    """COCO's ``licenses`` list from the manifests' ``objects[]``
    licences (manifest 6): one entry per distinct asset / licence /
    mesh, ``name`` the licence as stated (``unknown`` when none was).
    A version-5 run states none and the list stays empty."""
    out = []
    for entry in asset_licences(runs):
        if entry["kind"] != "object":
            continue
        out.append({"id": len(out) + 1, "name": entry["licence"] or "unknown",
                    "url": "", "asset": entry["asset"],
                    "mesh_sha256": entry.get("mesh_sha256"), "runs": entry["runs"]})
    return out


def export_coco(samples: Sequence[Sample], out: Path, splits: Dict[str, str]
                ) -> Dict[str, int]:
    names, _ = dataset_taxonomy(samples)
    categories = coco_categories(samples, names)
    licenses = coco_licenses(sorted({s.run.name: s.run for s in samples}.values(),
                                    key=lambda r: r.name))
    per_split: Dict[str, Dict[str, list]] = {
        s: {"images": [], "annotations": []} for s in SPLITS}
    image_id = 0
    annotation_id = 0
    for sample in sorted(samples, key=lambda s: s.key):
        split = sample_split(sample, splits)
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
        mask_path = label_file_path(sample.run, sample.record, "_mask.png")
        for obj in sample.objects:
            box = obj.get("bbox_2d")
            if not box:
                continue
            annotation_id += 1
            flat, visible = _keypoints_coco(obj)
            w, h = box[2] - box[0], box[3] - box[1]
            annotation = {
                "id": annotation_id, "image_id": image_id,
                "category_id": class_index(obj, names) + 1,
                "bbox": [box[0], box[1], w, h], "area": w * h, "iscrowd": 0,
                "keypoints": flat, "num_keypoints": visible,
                "truncation": obj.get("truncation"),
                "bbox_3d_camera": obj.get("bbox_3d_camera"),
                "horizon": obj.get("horizon"),
            }
            if obj.get("visible_fraction") is not None:
                annotation["visible_fraction"] = obj["visible_fraction"]
                annotation["occluded_by"] = obj["occluded_by"]
            if obj.get("not_claimed"):
                annotation["not_claimed"] = obj["not_claimed"]
            if obj.get("int_id") is not None and mask_path.is_file():
                rle = mask_rle(mask_path, int(obj["int_id"]))
                if rle is not None:
                    annotation["segmentation"] = rle
                    annotation["mask_pixels"] = sum(rle["counts"][1::2])
            per_split[split]["annotations"].append(annotation)
    counts = {}
    (out / "annotations").mkdir(parents=True, exist_ok=True)
    for split, content in per_split.items():
        payload = {"info": {"description": "flightsim labelled frames",
                            "conventions": "see DATASET_CARD.md"},
                   "licenses": licenses, "categories": categories, **content}
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


def kitti_occluded(visible_fraction: Optional[float]) -> int:
    """KITTI ``occluded``: 0 fully visible (>= KITTI_VISIBLE_FULL), 1
    partly (>= KITTI_VISIBLE_PARTLY), 2 largely occluded, 3 unknown
    (no visibility recorded -- every run without an ID pass)."""
    if not isinstance(visible_fraction, (int, float)) or isinstance(visible_fraction, bool):
        return KITTI_OCCLUDED_UNKNOWN
    fraction = float(visible_fraction)
    if fraction >= KITTI_VISIBLE_FULL:
        return 0
    if fraction >= KITTI_VISIBLE_PARTLY:
        return 1
    return 2


def kitti_object_line(obj: Dict[str, Any]) -> Optional[str]:
    box = obj.get("bbox_2d")
    box3 = obj.get("bbox_3d_camera")
    if not box or not box3:
        return None
    forward, right, down = box3["extents_m"]
    centre = box3["centre_m"]
    ry = kitti_rotation_y(box3["body_axes_in_camera"][0])
    alpha = kitti_alpha(ry, centre)
    occluded = kitti_occluded(obj.get("visible_fraction"))
    truncation = obj.get("truncation")
    fields = [str(obj["class_name"]).replace(" ", "_"),
              f"{float(truncation or 0.0):.2f}", str(occluded), f"{alpha:.4f}",
              f"{box[0]:.2f}", f"{box[1]:.2f}", f"{box[2]:.2f}", f"{box[3]:.2f}",
              f"{down:.3f}", f"{right:.3f}", f"{forward:.3f}",
              f"{centre[0]:.3f}", f"{centre[1]:.3f}", f"{centre[2]:.3f}",
              f"{ry:.4f}"]
    return " ".join(fields)


def kitti_label_line(sample: Sample) -> Optional[str]:
    """The primary airframe's KITTI line (Phase 10 API, kept)."""
    for obj in sample.objects:
        if obj.get("role") == "primary":
            return kitti_object_line(obj)
    return None


def kitti_label_lines(sample: Sample) -> List[str]:
    """One line per object that has both boxes; objects without a 3-D
    box (scene objects) are not KITTI objects and are left out."""
    lines = []
    for obj in sample.objects:
        line = kitti_object_line(obj)
        if line:
            lines.append(line)
    return lines


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
        split = sample_split(sample, splits)
        root = out / split
        for sub in ("image_2", "label_2", "calib"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        _place_image(sample, root / "image_2" / f"{sample.key}.png")
        lines = kitti_label_lines(sample)
        (root / "label_2" / f"{sample.key}.txt").write_text(
            "".join(line + "\n" for line in lines), encoding="utf-8")
        (root / "calib" / f"{sample.key}.txt").write_text(
            kitti_calib(sample.record), encoding="utf-8")
        counts[split] += 1
    return counts


def _tar_bytes(tar: tarfile.TarFile, name: str, payload: bytes) -> None:
    """A member from bytes with every filesystem-derived field fixed
    (mtime 0, uid/gid 0, no names), so two exports of one dataset are
    the same bytes on any machine."""
    info = tarfile.TarInfo(name=name)
    info.size = len(payload)
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(payload))


def export_webdataset(samples: Sequence[Sample], out: Path,
                      splits: Dict[str, str], shard_size: int = 1000
                      ) -> Dict[str, int]:
    if shard_size < 1:
        raise ExportError("export.shard_size", "shard size must be >= 1")
    by_split: Dict[str, List[Sample]] = {s: [] for s in SPLITS}
    for sample in sorted(samples, key=lambda s: s.key):
        by_split[sample_split(sample, splits)].append(sample)
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
                        _tar_bytes(tar, f"{sample.key}.png", sample.image.read_bytes())
                    for suffix, extension in LABEL_FILES:
                        label = label_file_path(sample.run, sample.record, suffix)
                        if label.is_file():
                            _tar_bytes(tar, f"{sample.key}.{extension}", label.read_bytes())
                    sidecar = frame_sidecar(sample.run.manifest, sample.record)
                    sidecar["export"] = {"labels": sample.labels,
                                         "split": split}
                    payload = json.dumps(sidecar, sort_keys=True).encode("utf-8")
                    _tar_bytes(tar, f"{sample.key}.json", payload)
    return counts


def yolo_line(obj: Dict[str, Any], class_idx: int, width: int, height: int
              ) -> Optional[str]:
    """``class cx cy w h`` normalised to the image from the CLIPPED box;
    None for an object without a box."""
    box = obj.get("bbox_2d")
    if not box:
        return None
    x0, y0, x1, y1 = (float(v) for v in box)
    cx = (x0 + x1) / 2.0 / width
    cy = (y0 + y1) / 2.0 / height
    w = (x1 - x0) / width
    h = (y1 - y0) / height
    return f"{class_idx} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"


def export_yolo(samples: Sequence[Sample], out: Path, splits: Dict[str, str]
                ) -> Dict[str, int]:
    """The Ultralytics detect layout: ``images/<split>/<key>.png``,
    ``labels/<split>/<key>.txt``, ``data.yaml``. Every split's two
    directories exist (empty when the split is), so a loader that
    resolves ``val`` finds a directory, not an error."""
    import yaml

    names, source = dataset_taxonomy(samples)
    counts = {s: 0 for s in SPLITS}
    for split in SPLITS:
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)
    for sample in sorted(samples, key=lambda s: s.key):
        split = sample_split(sample, splits)
        _place_image(sample, out / "images" / split / f"{sample.key}.png")
        lines = []
        for obj in sample.objects:
            line = yolo_line(obj, class_index(obj, names), sample.width, sample.height)
            if line:
                lines.append(line)
        (out / "labels" / split / f"{sample.key}.txt").write_text(
            "".join(line + "\n" for line in lines), encoding="utf-8")
        counts[split] += 1
    # No ``path`` key on purpose: Ultralytics resolves a relative
    # ``path`` against its datasets directory or the working directory,
    # and only an ABSENT one against the yaml's own directory.
    data = {"train": "images/train", "val": "images/val", "test": "images/test",
            "names": {i: name for i, name in enumerate(names)},
            "flightsim": {"class_order": source,
                          "box": "clipped bbox_2d, normalised cx cy w h",
                          "path": "no path key: the split directories are beside this file",
                          "card": "../DATASET_CARD.md or DATASET_CARD.md"}}
    (out / "data.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return counts


def voc_flags(obj: Dict[str, Any]) -> Dict[str, int]:
    """Pascal VOC's three flags from the label record.

    ``truncated``: the object leaves the frame -- ``fraction_in_frame <
    1`` when the record carries that key, else ``truncation > 0`` (the
    existing key; ``1 - clipped area / unclipped area``); 0 when neither
    is recorded. ``occluded``: ``visible_fraction < VOC_OCCLUDED_BELOW``
    when a visibility was recorded, else 0. ``difficult``: the clipped
    box's longer side is under the not-claimed threshold (the object's
    ``objects_under_px: N`` entry, else ``NOT_CLAIMED_EXTENT_PX``).
    """
    fraction = obj.get("fraction_in_frame")
    truncation = obj.get("truncation")
    if isinstance(fraction, (int, float)) and not isinstance(fraction, bool):
        truncated = int(float(fraction) < 1.0)
    elif isinstance(truncation, (int, float)) and not isinstance(truncation, bool):
        truncated = int(float(truncation) > 0.0)
    else:
        truncated = 0
    visible = obj.get("visible_fraction")
    occluded = 0
    if isinstance(visible, (int, float)) and not isinstance(visible, bool):
        occluded = int(float(visible) < VOC_OCCLUDED_BELOW)
    threshold = NOT_CLAIMED_EXTENT_PX
    for item in obj.get("not_claimed") or []:
        text = str(item)
        if text.startswith(NOT_CLAIMED_EXTENT_KEY + ":"):
            try:
                threshold = float(text.split(":", 1)[1].strip())
            except ValueError:
                pass
    difficult = 0
    box = obj.get("bbox_2d")
    if box:
        extent = max(float(box[2]) - float(box[0]), float(box[3]) - float(box[1]))
        difficult = int(extent < threshold)
    return {"truncated": truncated, "occluded": occluded, "difficult": difficult}


def voc_bndbox(box: Sequence[float]) -> Dict[str, int]:
    """The devkit's 1-based inclusive integer box covering the float
    box: ``xmin = floor(x0) + 1``, ``xmax = ceil(x1)`` (and y alike), so
    a reader that treats the numbers as pixel indices sees every pixel
    the float box touches."""
    x0, y0, x1, y1 = (float(v) for v in box)
    return {"xmin": int(math.floor(x0)) + 1, "ymin": int(math.floor(y0)) + 1,
            "xmax": max(int(math.ceil(x1)), int(math.floor(x0)) + 1),
            "ymax": max(int(math.ceil(y1)), int(math.floor(y0)) + 1)}


def voc_annotation_xml(sample: Sample, names: Sequence[str]) -> str:
    root = ET.Element("annotation")
    ET.SubElement(root, "folder").text = "JPEGImages"
    ET.SubElement(root, "filename").text = f"{sample.key}.png"
    source = ET.SubElement(root, "source")
    ET.SubElement(source, "database").text = "flightsim"
    ET.SubElement(source, "annotation").text = "flightsim capture manifest"
    ET.SubElement(source, "image").text = sample.labels["pixels"]
    size = ET.SubElement(root, "size")
    ET.SubElement(size, "width").text = str(sample.width)
    ET.SubElement(size, "height").text = str(sample.height)
    ET.SubElement(size, "depth").text = "3"
    ET.SubElement(root, "segmented").text = "0"
    for obj in sample.objects:
        box = obj.get("bbox_2d")
        if not box:
            continue
        index = class_index(obj, names)        # refuses a class outside the taxonomy
        element = ET.SubElement(root, "object")
        ET.SubElement(element, "name").text = names[index]
        ET.SubElement(element, "pose").text = "Unspecified"
        flags = voc_flags(obj)
        ET.SubElement(element, "truncated").text = str(flags["truncated"])
        ET.SubElement(element, "occluded").text = str(flags["occluded"])
        ET.SubElement(element, "difficult").text = str(flags["difficult"])
        bndbox = ET.SubElement(element, "bndbox")
        for key, value in voc_bndbox(box).items():
            ET.SubElement(bndbox, key).text = str(value)
    ET.indent(root)
    return ET.tostring(root, encoding="unicode") + "\n"


def export_voc(samples: Sequence[Sample], out: Path, splits: Dict[str, str]
               ) -> Dict[str, int]:
    """The Pascal VOC devkit layout at one root: ``JPEGImages/``,
    ``Annotations/``, ``ImageSets/Main/{train,val,test}.txt`` (each
    split's stems, one per line; an empty split is an empty file)."""
    names, _ = dataset_taxonomy(samples)
    counts = {s: 0 for s in SPLITS}
    stems: Dict[str, List[str]] = {s: [] for s in SPLITS}
    (out / "JPEGImages").mkdir(parents=True, exist_ok=True)
    (out / "Annotations").mkdir(parents=True, exist_ok=True)
    (out / "ImageSets" / "Main").mkdir(parents=True, exist_ok=True)
    for sample in sorted(samples, key=lambda s: s.key):
        split = sample_split(sample, splits)
        _place_image(sample, out / "JPEGImages" / f"{sample.key}.png")
        (out / "Annotations" / f"{sample.key}.xml").write_text(
            voc_annotation_xml(sample, names), encoding="utf-8")
        stems[split].append(sample.key)
        counts[split] += 1
    for split in SPLITS:
        (out / "ImageSets" / "Main" / f"{split}.txt").write_text(
            "".join(stem + "\n" for stem in stems[split]), encoding="utf-8")
    return counts


WRITERS = {"coco": export_coco, "kitti": export_kitti,
           "webdataset": export_webdataset, "yolo": export_yolo,
           "voc": export_voc}


# -- the card --------------------------------------------------------------

def parse_formats(fmt) -> List[str]:
    """One name, a comma list or a sequence -> the ordered, de-duplicated
    format list; an unknown name refuses ``export.format``."""
    if isinstance(fmt, str):
        parts = [p.strip() for p in fmt.split(",")]
    else:
        parts = [str(p).strip() for p in fmt]
    formats: List[str] = []
    for part in parts:
        if part not in FORMATS:
            raise ExportError("export.format",
                              f"format must be one of {FORMATS}, not {part!r}")
        if part not in formats:
            formats.append(part)
    if not formats:
        raise ExportError("export.format", f"format must be one of {FORMATS}, not {fmt!r}")
    return formats


def asset_licences(runs: Sequence[Run]) -> List[Dict[str, Any]]:
    """The licence of every asset drawn, from the manifests' ``objects[]``
    (``licence`` per object, manifest 6) and from the ``assets``
    block: the airframe config file each run names (its ``license``
    block, read from this repository when the file is here; otherwise
    null WITH the reason). A licence is never guessed, and never
    attributed to a run that stated another: an object id that two
    runs record with different licences or mesh hashes gets one entry
    per distinct pair, each with its own runs and a ``note`` naming
    the disagreement."""
    repo = Path(__file__).resolve().parents[2]
    entries: Dict[Tuple[str, ...], Dict[str, Any]] = {}
    for run in runs:
        for obj in run.manifest.get("objects") or []:
            if not isinstance(obj, dict) or obj.get("licence") is None and obj.get("mesh_sha256") is None:
                continue
            key = ("object", str(obj.get("id")), str(obj.get("licence")),
                   str(obj.get("mesh_sha256")))
            entry = entries.setdefault(key, {
                "asset": str(obj.get("id")), "kind": "object",
                "licence": obj.get("licence"), "mesh_sha256": obj.get("mesh_sha256"),
                "source": "manifest objects[]", "runs": []})
            entry["runs"].append(run.name)
        config = (run.manifest.get("assets") or {}).get("aircraft_config") or {}
        path = config.get("path")
        if not path:
            continue
        key = ("aircraft_config", str(path))
        if key not in entries:
            licence: Optional[Dict[str, Any]] = None
            note = None
            file = repo / str(path)
            if file.is_file():
                try:
                    block = json.loads(file.read_text(encoding="utf-8")).get("license")
                except (OSError, ValueError):
                    block = None
                if isinstance(block, dict):
                    licence = {"name": block.get("license_name"), "file": block.get("file"),
                               "repo": block.get("repo"), "commit": block.get("commit")}
                else:
                    note = f"{path} carries no license block"
            else:
                note = f"{path} is not on this machine; the licence was not read"
            entries[key] = {"asset": str(path), "kind": "aircraft_config",
                            "sha256": config.get("sha256"),
                            "licence": licence["name"] if licence else None,
                            "licence_detail": licence, "note": note,
                            "source": f"{path} license block", "runs": []}
        entries[key]["runs"].append(run.name)
    by_asset: Dict[str, List[Dict[str, Any]]] = {}
    for key, entry in entries.items():
        if key[0] == "object":
            by_asset.setdefault(entry["asset"], []).append(entry)
    for asset, variants in by_asset.items():
        if len(variants) > 1:
            for entry in variants:
                entry["note"] = (f"the runs disagree: {asset} is recorded with "
                                 f"{len(variants)} different licence / mesh pairs; "
                                 f"this entry's runs stated this one")
    return [entries[k] for k in sorted(entries)]


def _numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def conditions_summary(runs: Sequence[Run]) -> Dict[str, Any]:
    """What the runs were asked to fly in (``conditions``, per stated
    value with its source) and what the randomisation drew
    (``randomization`` block, per key: n / min / max / mean for numbers,
    a count per value otherwise)."""
    stated: Dict[str, Dict[str, int]] = {}
    sources: Dict[str, Dict[str, int]] = {}
    for run in runs:
        for name, quantity in (run.manifest.get("conditions") or {}).items():
            if not isinstance(quantity, dict):
                continue
            value = json.dumps(quantity.get("value"), sort_keys=True)
            stated.setdefault(name, {})
            stated[name][value] = stated[name].get(value, 0) + 1
            source = str(quantity.get("source"))
            sources.setdefault(name, {})
            sources[name][source] = sources[name].get(source, 0) + 1
    sampled: Dict[str, Any] = {}
    numbers: Dict[str, List[float]] = {}
    for run in runs:
        block = run.manifest.get("randomization")
        if not isinstance(block, dict):
            continue
        for name, value in block.items():
            if _numeric(value):
                numbers.setdefault(name, []).append(float(value))
            elif isinstance(value, str):
                sampled.setdefault(name, {})
                sampled[name][value] = sampled[name].get(value, 0) + 1
    for name, values in numbers.items():
        sampled[name] = {"n": len(values), "min": min(values), "max": max(values),
                         "mean": sum(values) / len(values)}
    return {"stated": {name: {"values": stated[name], "sources": sources[name]}
                       for name in sorted(stated)},
            "sampled": dict(sorted(sampled.items())),
            "randomised_runs": sorted(r.name for r in runs
                                      if isinstance(r.manifest.get("randomization"), dict))}


def class_balance(samples: Sequence[Sample], splits: Dict[str, str],
                  names: Sequence[str]) -> Dict[str, Any]:
    """Instances and images per class, overall and per split."""
    per_class: Dict[str, Dict[str, Any]] = {
        name: {"instances": 0, "images": 0,
               "per_split": {s: {"instances": 0, "images": 0} for s in SPLITS}}
        for name in names}
    for sample in samples:
        split = sample_split(sample, splits)
        seen = set()
        for obj in sample.objects:
            if not obj.get("bbox_2d"):
                continue
            name = names[class_index(obj, names)]
            per_class[name]["instances"] += 1
            per_class[name]["per_split"][split]["instances"] += 1
            if name not in seen:
                seen.add(name)
                per_class[name]["images"] += 1
                per_class[name]["per_split"][split]["images"] += 1
    return per_class


def not_claimed_from_labels(samples: Sequence[Sample]) -> Dict[str, int]:
    """Every distinct ``not_claimed`` sentence in the label records,
    with the number of object records that carry it."""
    counts: Dict[str, int] = {}
    for sample in samples:
        for obj in sample.objects:
            for item in obj.get("not_claimed") or []:
                counts[str(item)] = counts.get(str(item), 0) + 1
    return dict(sorted(counts.items()))


def dataset_card(runs: Sequence[Run], samples: Sequence[Sample],
                 splits: Dict[str, str], counts: Dict[str, int], fmt: str,
                 fractions, seed: int, image: str, labels_only: bool,
                 formats: Optional[Sequence[str]] = None,
                 masks_shipped: Sequence[str] = (),
                 labels_shipped: Optional[Dict[str, Sequence[str]]] = None
                 ) -> Dict[str, Any]:
    formats = list(formats) if formats else [fmt]
    shipped: Dict[str, List[str]] = {name: list(s) for name, s in (labels_shipped or {}).items()}
    for name in masks_shipped:
        if "_mask.png" not in shipped.setdefault(name, []):
            shipped[name].append("_mask.png")
    member_of = dict(LABEL_FILES)
    unbound = [r.name for r in runs if not r.verification_bound]
    headless = [r.name for r in runs if not r.render]
    cameras = sorted({(s.run.name, str(s.record["camera_id"])) for s in samples})
    profiles = sorted({str(s.record.get("sensor", {}).get("profile", "ideal_pinhole"))
                       for s in samples})
    randomised = sorted(r.name for r in runs if r.manifest.get("randomization"))
    first = runs[0].manifest
    names, taxonomy_source = dataset_taxonomy(samples)
    balance = class_balance(samples, splits, names)
    instances = sum(c["instances"] for c in balance.values())
    conventions_by_version: Dict[str, Any] = {}
    for run in runs:
        conventions_by_version.setdefault(str(int(run.manifest["manifest_version"])),
                                          run.manifest.get("label_conventions"))
    labels_not_claimed = not_claimed_from_labels(samples)
    return {
        "format": fmt,
        "formats": formats,
        "layout": ({f: "." for f in formats} if len(formats) == 1
                   else {f: f"{f}/" for f in formats}),
        "image": image,
        "labels_only": labels_only,
        "frames": len(samples),
        "images": len(samples),
        "instances": instances,
        "frames_per_split": counts,
        "classes": list(names),
        "class_order": taxonomy_source,
        "class_balance": balance,
        "runs": [{
            "name": r.name, "directory": str(r.directory),
            "spec_digest": r.manifest["spec_digest"],
            "simulation_digest": r.manifest["simulation_digest"],
            "seed": r.manifest.get("seed"),
            "aircraft": r.manifest["aircraft"],
            "solve_source": r.manifest.get("solve_source"),
            "frames": len(r.manifest["frames"]),
            "cameras": [c["camera_id"] for c in r.manifest.get("cameras", [])],
            "randomization": r.manifest.get("randomization"),
            "verification": {**{k: r.verification.get(k)
                                for k in ("ok", "passed", "failed", "not_run")},
                             "status": "passed" if r.verification.get("ok") else "failed",
                             "file": str(r.directory / VERIFICATION_FILE)},
            "not_run": [c["name"] for c in r.verification.get("checks", [])
                        if c.get("status") == "NOT RUN"],
            "masks_shipped": "_mask.png" in shipped.get(r.name, []),
            "labels_shipped": [member_of[s] for s in shipped.get(r.name, [])],
            "verification_bound_to_manifest": r.verification_bound,
            "manifest_sha256": r.manifest_sha256,
            "airframes": r.airframes(),
            "render": (r.render if r.render else None),
            "render_note": (None if r.render else
                            f"no {RENDER_JSON} under frames/ (a headless capture): "
                            f"nothing was drawn and no rendering switch is recorded"),
        } for r in runs],
        "split": {"by": "simulation_digest", "fractions": list(fractions),
                  "seed": int(seed), "assignment": dict(splits),
                  "policy": ("simulations shuffled by the seed, dealt greedily by "
                             "frame count to the fractions; every frame of one "
                             "simulation digest lands on one side")},
        "aircraft": sorted({name for r in runs for name in r.airframes()}),
        "primary_aircraft": sorted({s.aircraft for s in samples}),
        "cameras": [f"{run}/{cam}" for run, cam in cameras],
        "sensor_profiles": profiles,
        "randomised_runs": randomised,
        "conditions": conditions_summary(runs),
        "licences": asset_licences(runs),
        "label_conventions": first.get("label_conventions"),
        "label_conventions_by_manifest_version": conventions_by_version,
        "airframes": {r.manifest["aircraft"]: r.manifest.get("airframe") for r in runs},
        "kitti_conventions": {
            "camera_frame": "x right, y down, z forward (the manifest's)",
            "location": "bbox_3d_camera.centre_m",
            "dimensions_hwl": "extents down, right, forward (metres)",
            "rotation_y": "atan2(-f_z, f_x) for the body forward axis f in camera coordinates",
            "alpha": "rotation_y - atan2(x, z), wrapped to [-pi, pi]",
            "occluded": (f"from visible_fraction: 0 when >= {KITTI_VISIBLE_FULL}, 1 when >= "
                         f"{KITTI_VISIBLE_PARTLY}, else 2; 3 (unknown) when no visibility "
                         f"was recorded"),
        },
        "coco_conventions": {
            "bbox": "[x, y, w, h] from the CLIPPED 2-D box; truncation carried",
            "keypoints": list(KEYPOINT_NAMES),
            "visibility": "2 = inside the image with positive depth, 0 otherwise",
            "segmentation": ("uncompressed RLE (column-major) of the ID mask's pixels "
                             "equal to the object's int_id, present only where a "
                             "_mask.png exists beside the frame; area stays w*h, "
                             "mask_pixels carries the mask count"),
        },
        "yolo_conventions": {
            "layout": "Ultralytics detect: images/<split>/, labels/<split>/<key>.txt, data.yaml",
            "path": ("data.yaml names no path key: Ultralytics then resolves train/val/test "
                     "beside the yaml, where they are (a relative path would be resolved "
                     "against its datasets directory or the working directory instead)"),
            "line": "class cx cy w h normalised to the image from the CLIPPED bbox_2d",
            "class": f"0-based index in taxonomy order ({taxonomy_source})",
        },
        "voc_conventions": {
            "layout": "one root: JPEGImages/ (PNGs as they are), Annotations/<key>.xml, ImageSets/Main/<split>.txt",
            "bndbox": "1-based inclusive integers covering the float box: floor(x0)+1 .. ceil(x1)",
            "truncated": "1 when the object leaves the frame (fraction_in_frame < 1, else truncation > 0)",
            "occluded": f"1 when visible_fraction < {VOC_OCCLUDED_BELOW}; 0 when no visibility was recorded",
            "difficult": (f"1 when the clipped box's longer side is under the not-claimed "
                          f"threshold (the record's {NOT_CLAIMED_EXTENT_KEY}, else "
                          f"{NOT_CLAIMED_EXTENT_PX} px)"),
        },
        "not_claimed_extent_px": NOT_CLAIMED_EXTENT_PX,
        "not_claimed_from_labels": labels_not_claimed,
        "not_claimed": [
            "render reproducibility: not established in either direction "
            "until Gate 10-R runs on an engine (VALIDITY section 3)",
            "labels are the headless geometry of the recorded flight; an "
            "engine ID mask, class image or depth ships only in a format that "
            "carries it (COCO: the ID mask; WebDataset: all three) and only "
            "from a run whose verdict has every check for that file PASS "
            "(refused by name otherwise); it is never substituted for the "
            "geometry",
            "the 3-D box and the horizon are pinhole quantities even when "
            "the sensor image is exported",
            "no photometric calibration: sun, fog and exposure are the "
            "harness's calibrated look points or a sampled range between them",
            "the YOLO and VOC trees have been round-tripped through "
            "independent readers, not through a training stack",
            "an object's VOC occluded flag is 0, and its KITTI occluded is 3, "
            "when no visibility was recorded (every run without an ID pass)",
        ] + [f"labels: {item} ({n} object record(s))"
             for item, n in labels_not_claimed.items()]
          + ([f"run(s) {', '.join(unbound)}: the verdict names no manifest digest "
              f"(a verifier that did not record which manifest it graded), so a "
              f"label edited after that verification could not have been told "
              f"apart from the verified ones"] if unbound else [])
          + ([f"run(s) {', '.join(headless)}: no {RENDER_JSON} -- nothing was "
              f"drawn by an engine and no rendering switch or applied look is "
              f"recorded"] if headless else []),
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
        f"Instances: {card['instances']} over {len(card['classes'])} class(es) "
        f"({card['class_order']}): " + ", ".join(
            f"{name} {c['instances']}" for name, c in card["class_balance"].items()),
        f"Aircraft: {', '.join(card['aircraft'])} (primary: "
        f"{', '.join(card.get('primary_aircraft', card['aircraft']))})",
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
            f"seed {run['seed']}, "
            f"verification {v['passed']} passed / {v['failed']} failed / "
            f"{v['not_run']} not run"
            + (f" (NOT RUN: {', '.join(run['not_run'])})" if run["not_run"] else "")
            + ("" if run.get("verification_bound_to_manifest", True)
               else ", verdict not bound to the manifest")
            + (f", label files shipped: {', '.join(run['labels_shipped'])}"
               if run.get("labels_shipped") else "")
            + (" -- randomised" if run["randomization"] else "")
            + (f"; airframes {', '.join(run['airframes'])}" if run.get("airframes") else "")
            + (f"; render: {', '.join(sorted(run['render']))}" if run.get("render")
               else f"; {run.get('render_note', 'no render record')}"))
    lines += ["", "## Class balance", ""]
    for name, c in card["class_balance"].items():
        per_split = ", ".join(f"{s} {p['instances']}" for s, p in c["per_split"].items())
        lines.append(f"- {name}: {c['instances']} instance(s) in {c['images']} image(s) ({per_split})")
    lines += ["", "## Conditions", ""]
    for name, block in card["conditions"]["stated"].items():
        values = ", ".join(f"{v} x{n}" for v, n in block["values"].items())
        sources = ", ".join(f"{s} x{n}" for s, n in block["sources"].items())
        lines.append(f"- {name}: {values} (source {sources})")
    if card["conditions"]["sampled"]:
        lines += ["", "Sampled by the randomisation block:", ""]
        for name, block in card["conditions"]["sampled"].items():
            if "n" in block:
                lines.append(f"- {name}: n {block['n']}, min {block['min']}, "
                             f"max {block['max']}, mean {block['mean']:.4g}")
            else:
                lines.append(f"- {name}: " + ", ".join(f"{v} x{n}" for v, n in block.items()))
    lines += ["", "## Licences", ""]
    for entry in card["licences"]:
        lines.append(f"- {entry['kind']} `{entry['asset']}`: {entry['licence'] or 'unknown'}"
                     + (f" ({entry['note']})" if entry.get("note") else "")
                     + f" -- {len(entry['runs'])} run(s)")
    lines += ["", "## Conventions", ""]
    for key in ("coco_conventions", "kitti_conventions", "yolo_conventions", "voc_conventions"):
        for name, text in card[key].items():
            lines.append(f"- {key[:-len('_conventions')]} {name}: {text}")
    lines += ["", "## Not claimed", ""]
    lines += [f"- {item}" for item in card["not_claimed"]]
    return "\n".join(lines) + "\n"


# -- the whole thing -------------------------------------------------------

def export(paths: Sequence, out, fmt, fractions=DEFAULT_FRACTIONS,
           seed: int = 0, image: str = "ideal", labels_only: bool = False,
           shard_size: int = 1000) -> Dict[str, Any]:
    """Export ``paths`` (runs or batch directories) as ``fmt`` -- one
    format name, a comma list, or a sequence -- into ``out``. One format
    writes into ``out`` itself (the Phase 10 layout); several write
    ``out/<format>/`` each. One card at ``out`` either way."""
    formats = parse_formats(fmt)
    out = Path(out)
    runs = [load_run(d) for d in discover_runs(paths)]
    samples = collect_samples(runs, image=image, labels_only=labels_only)
    names, _ = dataset_taxonomy(samples)            # refuses a mixed class list first
    refuse_classes_outside_taxonomy(samples, names)  # ...and a stray class, before any file
    labels_shipped = refuse_unverified_labels(samples, formats)
    splits = assign_splits(samples, fractions, seed)
    out.mkdir(parents=True, exist_ok=True)
    counts: Dict[str, int] = {}
    for name in formats:
        target = out if len(formats) == 1 else out / name
        target.mkdir(parents=True, exist_ok=True)
        if name == "webdataset":
            counts = export_webdataset(samples, target, splits, shard_size=shard_size)
        else:
            counts = WRITERS[name](samples, target, splits)
    card = dataset_card(runs, samples, splits, counts, ",".join(formats), fractions,
                        seed, image, labels_only, formats=formats,
                        labels_shipped=labels_shipped)
    (out / CARD_JSON).write_text(json.dumps(card, indent=1), encoding="utf-8")
    (out / CARD_MD).write_text(render_card(card), encoding="utf-8")
    return card
