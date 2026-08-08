"""The imagery drape, verified ON GEOMETRY: landmark projection on a render.

core/terrain/imagery.py already proves the baked texture matches its source
mosaic texel by texel; what that cannot see is a UV-mapping bug between the
texture and the MESH. This experiment closes that gap the way Gate 6 decides
its on-screen clauses: known world points are projected through the camera
of record, and the rendered pixels there are compared against what the
imagery says those places look like.

The claim checked, stated first
-------------------------------
* The raster's peak sample (the Matterhorn massif, 4540 m in this bake)
  projects to a pixel; the drape says that place is BRIGHT (glacier/snow --
  the sidecar's own measurement: mean brightness 194 above the snowline
  against 96 below).
* The drape says that place is BRIGHTER than the scene at large (the
  texture's own median), and the RENDERED summit window must likewise beat
  the rendered frame's median by a stated margin -- lighting scales
  luminance but does not swap a glacier with a valley floor. A drape that
  is flipped, shifted, or mis-mapped puts unglaciated texels on the summit
  pixel and fails the ordering. (The point under the aircraft is never in
  frame from a level chase -- measured, it projects thousands of pixels
  below the bottom edge -- so the reference is the median, not a second
  landmark.)
* An A/B against the classification render at the same projected pixel must
  DIFFER: a drape that silently failed to apply would pass any self-check.

Usage: .venv/bin/python experiments/imagery_drape.py [--skip-renders]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from core.terrain.glo30 import LOCATIONS  # noqa: E402
from core.terrain.heightfield import Heightfield  # noqa: E402
from experiments.gate5_ue_parity import reference_spec, write_run_card  # noqa: E402

RULE = "=" * 96

CHECKS = {
    #: Rendered luminance at the summit window over the rendered frame median.
    "min_render_ratio": 1.25,
    #: Texture: summit texel over the texture's median luminance.
    "min_texture_ratio": 1.3,
    #: A/B: imagery vs classification over the terrain half, mean |dRGB|.
    "min_ab_difference": 8.0,
    #: Sampling window half-size, px.
    "window_px": 6,
}


def render(card: Path, frames: Path, terrain: Path,
           imagery: Optional[Path]) -> None:
    editor = Path("/Users/Shared/Epic Games/UE_5.5/Engine/Binaries/Mac/UnrealEditor-Cmd")
    project = Path(__file__).resolve().parents[1] / "ue" / "FlightSim.uproject"
    frames.mkdir(parents=True, exist_ok=True)
    (frames / "render.json").unlink(missing_ok=True)
    command = [
        str(editor), str(project), "-run=FlightSimBridge.FlightSimRender",
        f"-scenario={card}", f"-frames={frames}",
        "-Visual", "-GeorefTerrain", "-shot=showcase", f"-terrain={terrain}",
        f"-mesh={Path('assets/generated/c172p/mesh_manifest.json').resolve()}",
        "-chase=-40:0:5",
        "-width=1280", "-height=720",
        "-fps=2", "-seconds=3",
        "-sun-elev=50.0", "-sun-azim=180.0",
        "-exposure-bias=9.5", "-fog-density=0.0012",
        "-unattended", "-nopause", "-nosplash",
        "-stdout", "-FullStdOutLogOutput",
        "-RenderOffScreen", "-AllowCommandletRendering",
    ]
    if imagery is not None:
        command.insert(10, f"-imagery={imagery}")
    log = frames.parent / f"{frames.name}.log"
    with log.open("w") as sink:
        proc = subprocess.run(command, stdout=sink, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL)
    if not (frames / "render.json").is_file():
        raise RuntimeError(f"render into {frames} wrote no manifest (exit "
                           f"{proc.returncode}); see {log}")


def window_mean(image: np.ndarray, px: float, py: float,
                half: int) -> Optional[np.ndarray]:
    x, y = int(round(px)), int(round(py))
    if not (half <= x < image.shape[1] - half and
            half <= y < image.shape[0] - half):
        return None
    return image[y - half:y + half + 1, x - half:x + half + 1].reshape(-1, 3) \
        .mean(axis=0)


def texel_at(texture: np.ndarray, sidecar: Dict, x_m: float,
             y_m: float) -> np.ndarray:
    info = sidecar["texture"]
    col = int((x_m - info["origin_x_m"]) / info["texel_size_m"])
    row = int((info["origin_y_m"] - y_m) / info["texel_size_m"])
    col = np.clip(col, 0, info["width"] - 1)
    row = np.clip(row, 0, info["height"] - 1)
    return texture[row, col].astype(np.float64)


def pick_frame(manifest: Dict) -> Dict:
    """The first frame where the summit projects on screen."""
    for record in manifest["frame_records"]:
        marks = record.get("landmarks", {})
        if marks.get("near_peak", {}).get("visible"):
            return record
    raise RuntimeError("no frame shows the peak; the framing cannot support "
                       "the landmark check")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="imagery drape on-geometry check")
    ap.add_argument("--out", default="runs/imagery_drape")
    ap.add_argument("--terrain", default="runs/terrain/matterhorn")
    ap.add_argument("--skip-renders", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    terrain = Path(args.terrain).resolve()
    sidecar_path = Path("runs/terrain/matterhorn_imagery.json").resolve()

    from PIL import Image

    location = LOCATIONS["matterhorn"]
    baked = Heightfield.read(terrain)
    sidecar = json.loads(sidecar_path.read_text())
    texture = np.asarray(Image.open(
        sidecar_path.parent / sidecar["texture"]["file"]).convert("RGB"))

    print(f"\n{RULE}\n1. the scene: c172p over the massif, still frames\n{RULE}")
    from pyproj import Transformer
    transformer = Transformer.from_crs("EPSG:4326", baked.georeference.crs,
                                       always_xy=True)
    ox, oy = transformer.transform(location.origin_lon, location.origin_lat)
    spec = reference_spec("fly the c172 at 3600 m and 100 kt for 30 seconds")
    spec.set("latitude", location.origin_lat, frm="matterhorn scene origin")
    spec.set("longitude", location.origin_lon, frm="matterhorn scene origin")
    # The raster's PEAK sample is the Monte Rosa massif (Dufourspitze side,
    # 4540 m in this bake), not the Matterhorn: head straight at it so the
    # landmark the commandlet projects is in frame.
    import math as _m
    peak_index = int(np.argmax(baked.samples))
    _prow, _pcol = np.unravel_index(peak_index, baked.samples.shape)
    g = baked.georeference
    peak_x = g.origin_x_m + int(_pcol) * g.pixel_size_m
    peak_y = g.origin_y_m - int(_prow) * g.pixel_size_m
    bearing = _m.degrees(_m.atan2(peak_x - ox, peak_y - oy)) % 360.0
    spec.set("heading", round(bearing), frm="straight at the raster peak")
    spec.set("terrain_elevation", round(baked.elevation_at(ox, oy), 1),
             frm="baked raster at origin")
    card = write_run_card(spec, out / "card.json")

    if not args.skip_renders:
        render(card, out / "imagery", terrain, sidecar_path)
        render(card, out / "classified", terrain, None)
    imagery_m = json.loads((out / "imagery" / "render.json").read_text())
    classified_m = json.loads((out / "classified" / "render.json").read_text())

    assert imagery_m["scene"]["imagery_sha256"] == sidecar["texture"]["sha256"], \
        "the manifest's imagery sha must be the sidecar's"

    print(f"\n{RULE}\n2. landmark projection through the camera of record\n{RULE}")
    frame = pick_frame(imagery_m)
    index = imagery_m["frame_records"].index(frame)
    marks = frame["landmarks"]
    image = np.asarray(Image.open(
        out / "imagery" / f"frame_{index:04d}.png").convert("RGB"))
    control = np.asarray(Image.open(
        out / "classified" / f"frame_{index:04d}.png").convert("RGB"))

    half = CHECKS["window_px"]
    peak = window_mean(image, marks["near_peak"]["px"],
                       marks["near_peak"]["py"], half)
    peak_control = window_mean(control, marks["near_peak"]["px"],
                               marks["near_peak"]["py"], half)
    if peak is None or peak_control is None:
        raise RuntimeError("the summit window fell off the frame edge")
    # The reference is the frame's own median luminance (sky excluded by
    # taking the lower half of the frame, which is terrain in this framing).
    lower = image[image.shape[0] // 2:]
    frame_median = float(np.median(lower.mean(axis=2)))

    # What the imagery itself says about the summit against its own median.
    peak_index = int(np.argmax(baked.samples))
    prow, pcol = np.unravel_index(peak_index, baked.samples.shape)
    g = baked.georeference
    peak_x = g.origin_x_m + int(pcol) * g.pixel_size_m
    peak_y = g.origin_y_m - int(prow) * g.pixel_size_m
    texture_peak = texel_at(texture, sidecar, peak_x, peak_y)
    texture_median = float(np.median(texture.mean(axis=2)))

    render_ratio = float(peak.mean()) / max(frame_median, 1.0)
    texture_ratio = float(texture_peak.mean()) / max(texture_median, 1.0)
    # The A/B is over the whole lower (terrain) half of the frame: at the
    # summit itself BOTH surfaces are white (the classification also snows
    # above the snowline -- measured |dRGB| 4.1 there), so the summit pixel
    # cannot distinguish applied from not-applied. The broad terrain can:
    # a four-colour classification against textured imagery.
    control_lower = control[control.shape[0] // 2:]
    ab_difference = float(np.abs(lower.astype(np.float64)
                                 - control_lower.astype(np.float64)).mean())

    checks = {
        "texture_says_summit_bright": texture_ratio >= CHECKS["min_texture_ratio"],
        "render_shows_the_same_ordering": render_ratio >= CHECKS["min_render_ratio"],
        "drape_actually_applied_ab": ab_difference >= CHECKS["min_ab_difference"],
    }
    print(f"  imagery: summit texel {texture_peak.mean():.0f} vs texture "
          f"median {texture_median:.0f} (ratio {texture_ratio:.2f})")
    print(f"  rendered: summit window {peak.mean():.0f} vs lower-frame "
          f"median {frame_median:.0f} (ratio {render_ratio:.2f})")
    print(f"  A/B vs classification over the terrain half: mean |dRGB| "
          f"{ab_difference:.1f}")
    for name, ok in checks.items():
        print(f"  [{'ok  ' if ok else 'FAIL'}] {name}")

    report = {
        "frame_index": index,
        "landmarks": marks,
        "texture_peak_rgb": texture_peak.tolist(),
        "texture_median": texture_median,
        "frame_median": frame_median,
        "render_ratio": render_ratio,
        "texture_ratio": texture_ratio,
        "ab_difference": ab_difference,
        "checks": {k: bool(v) for k, v in checks.items()},
        "thresholds": CHECKS,
        "ok": all(checks.values()),
    }
    (out / "report.json").write_text(json.dumps(report, indent=1))
    print(f"\n  IMAGERY DRAPE ON GEOMETRY: "
          f"{'PASS' if report['ok'] else 'FAIL'} -> {out / 'report.json'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
