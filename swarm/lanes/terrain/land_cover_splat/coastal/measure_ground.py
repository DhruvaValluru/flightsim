"""Pixel gate for the coastal land-cover splat: effective ground sample
distance and visible ground range, measured on a rendered frame.

Run on the Windows laptop on frames the laptop rendered (``run_gate.py`` in
this directory renders both sides and calls this). On the Mac this file is
only exercised on synthetic arrays and made-up run directories (tests); that
is not a render result.

Two ways in. ``--baseline-run`` / ``--candidate-run`` take the web app's run
directories (``runs/webapp/<run id>``): the frame is the first camera's first
``frame_*[0-9].png`` (the pick scripts/run_test_scenarios.py collect() makes),
the camera comes from that frame's record in ``capture_manifest.json``
(``position_alt_m``, ``pitch_deg`` positive up, ``roll_deg``, ``fy_px``,
``height_px``; core/capture/manifest.py), and the gate REFUSES unless the
engine's ``frames/<camera>/render.json`` says the splat was applied in the
candidate and not in the baseline (the echo INTEGRATION.md change 3 asks the
commandlet to write). ``--baseline`` / ``--candidate`` take bare PNGs plus the
three camera numbers; that way cannot tell whether the splat was drawn, so its
report says ``splat_evidence: none`` and it is not the lane's gate.
Either way, two frames with identical pixels are refused: nothing changed.

Geometry: pinhole camera at ``altitude_m`` above the surface, optical axis
``pitch_down_deg`` below level, no roll, vertical field of view ``vfov_deg``,
spherical Earth (mean radius 6 371 008.8 m, IUGG), no refraction.

Metrics
-------
``effective_gsd_m``   In the image rows whose ground range lies inside
    ``--gsd-range-km``: the horizontal spatial frequency f95 (cycles/pixel)
    below which 95 % of the non-DC row power lies, turned into metres with the
    rows' pixel footprint: footprint / (2 * f95). Smaller = finer detail on
    the ground. A blurrier frame scores larger.
``visible_range_km``  The farthest ground range whose row still shows local
    contrast: (p95 - p5) of the row's high-passed linear luminance over twice
    the row mean >= max(0.02, 2 x the same figure in the sky). 0.02 is the
    Koschmieder threshold contrast.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

EARTH_RADIUS_M = 6371008.8
CONTRAST_THRESHOLD = 0.02
HIGH_PASS_PX = 33

#: Gate thresholds (see INTEGRATION.md).
GSD_RATIO_MAX = 1.02          # candidate / baseline: the splat must not blur the ground
RANGE_RATIO_MIN = 0.95        # candidate / baseline: nor shorten the visible ground
RANGE_OVER_HAZE_MAX = 1.15    # candidate / sea-haze visibility: nor punch through the haze
HAZE_VISIBILITY_KM = 15.7     # sun_time_of_day lane, marine AOD 0.25 at 500 nm
MIN_MEAN_LUMINANCE = 0.005    # a black frame is a failed render, not a pass
MAX_ROLL_DEG = 0.5            # the row-to-range geometry assumes a level horizon

#: The key the card (request) and the engine's render.json (echo) carry once
#: INTEGRATION.md changes 1 and 3 are merged. Neither exists in the tree today.
SPLAT_KEY = "land_cover_splat"
#: Lines in a run's render.log that mean the GPU device went away. Written
#: from UE's usual D3D11 wording, NOT checked against this build's log.
DEVICE_LOST = re.compile(r"device (being )?lost|DXGI_ERROR_DEVICE_(REMOVED|HUNG|RESET)|0x887A000[567]",
                         re.IGNORECASE)


class GroundGateError(Exception):
    name = "terrain.land_cover_splat.gate"

    def __init__(self, reason: str):
        super().__init__(f"{self.name}: {reason}")


def load_luminance(path: Path) -> np.ndarray:
    rgb = np.asarray(Image.open(path).convert("RGB"), np.float32) / 255.0
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return (lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)).astype(np.float32)


@dataclass(frozen=True)
class Camera:
    altitude_m: float
    pitch_down_deg: float
    vfov_deg: float
    height_px: int

    @property
    def focal_px(self) -> float:
        return (self.height_px / 2.0) / math.tan(math.radians(self.vfov_deg) / 2.0)

    def depression_rad(self) -> np.ndarray:
        rows = np.arange(self.height_px, dtype=np.float64)
        return math.radians(self.pitch_down_deg) + np.arctan((rows - (self.height_px - 1) / 2.0) / self.focal_px)

    def ranges(self) -> Tuple[np.ndarray, np.ndarray]:
        """Per row: slant range and ground (arc) range in metres; NaN above the horizon."""
        delta = self.depression_rad()
        a = EARTH_RADIUS_M + self.altitude_m
        disc = EARTH_RADIUS_M ** 2 - (a * np.cos(delta)) ** 2
        ok = (delta > 0) & (disc >= 0)
        slant = np.full(delta.shape, np.nan)
        slant[ok] = a * np.sin(delta[ok]) - np.sqrt(disc[ok])
        ground = EARTH_RADIUS_M * np.arctan2(slant * np.cos(delta), a - slant * np.sin(delta))
        return slant, ground

    def horizon_km(self) -> float:
        return EARTH_RADIUS_M * math.acos(EARTH_RADIUS_M / (EARTH_RADIUS_M + self.altitude_m)) / 1000.0


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise GroundGateError(f"cannot read {path}: {error}")


def run_frame(run_dir: Path) -> Tuple[Path, str]:
    """(frame PNG, camera id) of a web-app run: the first camera directory's
    first ``frame_*[0-9].png``, as run_test_scenarios.py collect() picks it."""
    frames = Path(run_dir) / "frames"
    cameras = sorted(d for d in frames.glob("*") if d.is_dir()) if frames.is_dir() else []
    if not cameras:
        raise GroundGateError(f"{run_dir} has no frames/<camera> directory (the render wrote nothing)")
    found = sorted(cameras[0].glob("frame_*[0-9].png"))
    if not found:
        raise GroundGateError(f"{cameras[0]} holds no frame_*.png (the render wrote nothing)")
    return found[0], cameras[0].name


def camera_numbers(manifest: Dict[str, Any], camera_id: str, frame_name: str,
                   surface_elevation_m: float = 0.0) -> Dict[str, float]:
    """Height above the surface, pitch below level and vertical field of view
    of one frame, from its capture_manifest.json record."""
    records = [f for f in manifest.get("frames") or []
               if isinstance(f, dict) and f.get("camera_id") == camera_id]
    named = [f for f in records if f.get("file") == frame_name]
    if not named:
        raise GroundGateError(f"capture_manifest.json has no frame record {frame_name!r} for camera {camera_id!r}")
    record = named[0]
    try:
        altitude = float(record["position_alt_m"]) - float(surface_elevation_m)
        pitch_down = -float(record["pitch_deg"])
        roll = float(record["roll_deg"])
        vfov = 2.0 * math.degrees(math.atan(float(record["height_px"]) / (2.0 * float(record["fy_px"]))))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        raise GroundGateError(f"frame record {frame_name!r} lacks a camera field: {error!r}")
    if abs(roll) > MAX_ROLL_DEG:
        raise GroundGateError(f"camera roll is {roll:.2f} deg; the gate needs a level camera (<= {MAX_ROLL_DEG})")
    if altitude <= 0:
        raise GroundGateError(f"camera is {altitude:.1f} m above a surface at {surface_elevation_m} m; "
                              "pass the sea surface's height in the manifest's datum as --surface-elevation-m")
    return {"altitude_m": altitude, "pitch_down_deg": pitch_down, "vfov_deg": vfov, "roll_deg": roll}


def splat_state(run_dir: Path, camera_id: str) -> Dict[str, Any]:
    """What the run says about the splat: the card's request and the engine's
    echo. ``applied`` is true only when the ENGINE's render.json says so."""
    run_dir = Path(run_dir)
    card_path = run_dir / "card.json"
    render_path = run_dir / "frames" / camera_id / "render.json"
    card = _read_json(card_path) if card_path.is_file() else {}
    render = _read_json(render_path) if render_path.is_file() else {}
    requested = card.get(SPLAT_KEY) if isinstance(card, dict) else None
    echo = render.get(SPLAT_KEY) if isinstance(render, dict) else None
    echo = echo if isinstance(echo, dict) else {}
    return {"requested": requested, "applied": echo.get("applied") is True,
            "tier": echo.get("tier"), "sidecar_sha256": echo.get("sidecar_sha256")}


def device_lost_lines(run_dir: Path) -> int:
    count = 0
    for log in sorted(Path(run_dir).rglob("render.log")):
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        count += sum(1 for line in text.splitlines() if DEVICE_LOST.search(line))
    return count


def load_run(run_dir: Path, surface_elevation_m: float) -> Dict[str, Any]:
    frame, camera_id = run_frame(run_dir)
    manifest = _read_json(Path(run_dir) / "capture_manifest.json")
    return {"run_dir": str(run_dir), "frame": str(frame), "camera_id": camera_id,
            "camera": camera_numbers(manifest, camera_id, frame.name, surface_elevation_m),
            "splat": splat_state(run_dir, camera_id),
            "device_lost_lines": device_lost_lines(run_dir)}


def check_splat_evidence(baseline: Dict[str, Any], candidate: Dict[str, Any]) -> None:
    """Refuse a comparison that cannot be about the splat."""
    if baseline["splat"]["applied"]:
        raise GroundGateError("the baseline run's render.json says the splat was applied; "
                              "render the baseline with FLIGHTSIM_LAND_COVER_SPLAT=off")
    if not candidate["splat"]["applied"]:
        raise GroundGateError(
            f"the candidate run's frames/{candidate['camera_id']}/render.json carries no "
            f"\"{SPLAT_KEY}\": {{\"applied\": true}}: the engine did not draw the splat "
            "(INTEGRATION.md changes 1-4 not merged, or the switch was off), so both frames are the same scene")
    for name in ("altitude_m", "pitch_down_deg", "vfov_deg"):
        a, b = baseline["camera"][name], candidate["camera"][name]
        if abs(a - b) > 1e-3 * max(1.0, abs(a)):
            raise GroundGateError(f"the two runs' cameras differ in {name} ({a} vs {b}); "
                                  "pin the compiled spec so both sides are the same shot")


def f95_cycles_per_px(block: np.ndarray) -> float:
    x = block.astype(np.float64) - block.mean(axis=1, keepdims=True)
    x *= np.hanning(block.shape[1])[None, :]
    power = (np.abs(np.fft.rfft(x, axis=1)) ** 2).mean(axis=0)[1:]
    total = power.sum()
    if not total > 0:
        raise GroundGateError("the ground band is flat: no detail to measure")
    index = int(np.searchsorted(np.cumsum(power) / total, 0.95))
    return (min(index, power.size - 1) + 1) / block.shape[1]


def row_contrast(lum: np.ndarray) -> np.ndarray:
    kernel = np.ones(HIGH_PASS_PX) / HIGH_PASS_PX
    half = HIGH_PASS_PX // 2
    padded = np.pad(lum.astype(np.float64), ((0, 0), (half, half)), mode="reflect")
    low = np.apply_along_axis(lambda r: np.convolve(r, kernel, mode="valid"), 1, padded)
    detail = lum - low
    lo, hi = np.percentile(detail, [5, 95], axis=1)
    contrast = (hi - lo) / (2.0 * np.maximum(lum.mean(axis=1), 1e-6))
    padded_c = np.pad(contrast, 2, mode="edge")
    return np.median(np.stack([padded_c[i:i + contrast.size] for i in range(5)]), axis=0)


def measure(lum: np.ndarray, camera: Camera, gsd_range_km: Tuple[float, float] = (1.0, 3.0)) -> Dict[str, Any]:
    if lum.shape[0] != camera.height_px:
        raise GroundGateError(f"frame is {lum.shape[0]} rows, camera says {camera.height_px}")
    slant, ground = camera.ranges()
    ground_km = ground / 1000.0
    band = np.flatnonzero((ground_km >= gsd_range_km[0]) & (ground_km <= gsd_range_km[1]))
    if band.size < 8:
        raise GroundGateError(
            f"only {band.size} rows look at ground between {gsd_range_km[0]} and {gsd_range_km[1]} km; "
            "check altitude, pitch and field of view, or pass --gsd-range-km")
    footprint = float(np.median(slant[band]) / camera.focal_px)
    f95 = f95_cycles_per_px(lum[band])
    contrast = row_contrast(lum)
    sky = np.flatnonzero(camera.depression_rad() < -math.radians(1.0))
    sky_contrast = float(np.median(contrast[sky])) if sky.size else 0.0
    threshold = max(CONTRAST_THRESHOLD, 2.0 * sky_contrast)
    seen = np.flatnonzero(np.isfinite(ground_km) & (contrast >= threshold))
    return {
        "mean_luminance": float(lum.mean()),
        "pixel_footprint_m": footprint,
        "f95_cycles_per_px": f95,
        "effective_gsd_m": footprint / (2.0 * f95),
        "gsd_rows": [int(band[0]), int(band[-1])],
        "sky_contrast": sky_contrast,
        "contrast_threshold": threshold,
        "visible_range_km": float(ground_km[seen].max()) if seen.size else 0.0,
        "geometric_horizon_km": camera.horizon_km(),
    }


def gate(baseline: Dict[str, Any], candidate: Dict[str, Any],
         haze_visibility_km: float = HAZE_VISIBILITY_KM) -> Dict[str, Any]:
    gsd_ratio = candidate["effective_gsd_m"] / baseline["effective_gsd_m"]
    base_range = baseline["visible_range_km"]
    range_ratio = candidate["visible_range_km"] / base_range if base_range > 0 else float("inf")
    range_cap = max(RANGE_OVER_HAZE_MAX * haze_visibility_km, 1.05 * base_range)
    checks = {
        "frame_not_black": candidate["mean_luminance"] >= MIN_MEAN_LUMINANCE,
        "gsd_ratio_le_1.02": gsd_ratio <= GSD_RATIO_MAX,
        "range_ratio_ge_0.95": range_ratio >= RANGE_RATIO_MIN,
        "range_within_haze": candidate["visible_range_km"] <= range_cap,
    }
    return {"gsd_ratio": gsd_ratio, "range_ratio": range_ratio, "range_cap_km": range_cap,
            "checks": checks, "pass": all(checks.values())}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--baseline-run", type=Path, help="runs/webapp/<run id> rendered with the splat off")
    parser.add_argument("--candidate-run", type=Path, help="runs/webapp/<run id> rendered with the splat on")
    parser.add_argument("--surface-elevation-m", type=float, default=0.0,
                        help="height of the sea surface in the manifest's datum (default 0)")
    parser.add_argument("--baseline", type=Path, help="bare PNG (no splat evidence)")
    parser.add_argument("--candidate", type=Path, help="bare PNG (no splat evidence)")
    parser.add_argument("--altitude-m", type=float, help="with bare PNGs: camera height above the surface")
    parser.add_argument("--pitch-down-deg", type=float, help="with bare PNGs")
    parser.add_argument("--vfov-deg", type=float, help="with bare PNGs")
    parser.add_argument("--gsd-range-km", type=float, nargs=2, default=(1.0, 3.0))
    parser.add_argument("--haze-visibility-km", type=float, default=HAZE_VISIBILITY_KM)
    args = parser.parse_args(argv)
    try:
        report: Dict[str, Any] = {}
        runs: Optional[Dict[str, Dict[str, Any]]] = None
        if args.baseline_run and args.candidate_run:
            runs = {"baseline": load_run(args.baseline_run, args.surface_elevation_m),
                    "candidate": load_run(args.candidate_run, args.surface_elevation_m)}
            check_splat_evidence(runs["baseline"], runs["candidate"])
            paths = {name: Path(run["frame"]) for name, run in runs.items()}
            numbers = runs["candidate"]["camera"]
            report["splat_evidence"] = "render.json"
        elif args.baseline and args.candidate and None not in (args.altitude_m, args.pitch_down_deg, args.vfov_deg):
            paths = {"baseline": args.baseline, "candidate": args.candidate}
            numbers = {"altitude_m": args.altitude_m, "pitch_down_deg": args.pitch_down_deg,
                       "vfov_deg": args.vfov_deg}
            report["splat_evidence"] = "none"
        else:
            raise GroundGateError("give --baseline-run and --candidate-run, or --baseline and --candidate "
                                  "with --altitude-m, --pitch-down-deg and --vfov-deg")
        for path in paths.values():
            if not Path(path).is_file():
                raise GroundGateError(f"no frame at {path}")
        frames = {name: load_luminance(path) for name, path in paths.items()}
        if frames["baseline"].shape != frames["candidate"].shape:
            raise GroundGateError("baseline and candidate differ in size")
        if np.array_equal(frames["baseline"], frames["candidate"]):
            raise GroundGateError("baseline and candidate have identical pixels: nothing changed between "
                                  "the two renders, so there is nothing to gate")
        camera = Camera(numbers["altitude_m"], numbers["pitch_down_deg"], numbers["vfov_deg"],
                        frames["baseline"].shape[0])
        report["camera"] = dict(numbers)
        for name, lum in frames.items():
            report[name] = measure(lum, camera, tuple(args.gsd_range_km))
            if runs is not None:
                report[name].update({k: runs[name][k] for k in ("run_dir", "frame", "splat", "device_lost_lines")})
        report["gate"] = gate(report["baseline"], report["candidate"], args.haze_visibility_km)
        if runs is not None:
            report["gate"]["checks"]["no_device_lost_in_render_log"] = runs["candidate"]["device_lost_lines"] == 0
            report["gate"]["pass"] = all(report["gate"]["checks"].values())
    except GroundGateError as error:
        print(error, file=sys.stderr)
        return 2
    print(json.dumps(report, indent=1))
    return 0 if report["gate"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
