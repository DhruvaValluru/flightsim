"""Gate 6 -- visual realism, measured where it can be and honest where it cannot.

The gate, verbatim from the brief (recovered and recorded in
docs/BRIEF_PHASE6.md -- see its provenance note):

    GATE 6. Side-by-side against the old footage. Distant terrain shows
    range-based extinction. Peaks shadow the valley. The aircraft has a ground
    shadow. Exposure does not breathe when the aircraft banks.

Five clauses. Four are physical properties of the rendered frames and are
measured from the PNGs by this harness -- never from what the engine said it
did. The fifth, the side-by-side, is a human-judgment clause: this harness
PRODUCES the comparison image and says so; it does not pretend to judge
likeness.

How each measurable clause is decided
-------------------------------------
* **Range-based extinction.** The scene places the SAME terrain raster twice:
  once ~10 km from the camera and once ~30 km. The commandlet projects each
  instance's peak through the camera of record into pixel coordinates, and the
  harness compares each peak's contrast against the sky directly above it.
  Extinction means the far copy of the very same mountain reads fainter.
* **Peaks shadow the valley.** A null test in the Gate 3 style: the same
  still, rendered with and without dynamic shadows. Only cast shadows differ,
  so pixels that darken in the terrain band ARE the terrain's cast shadows.
  The threshold asks for far more area than the aircraft's own shadow could
  supply.
* **The aircraft has a ground shadow.** The same still with and without the
  aircraft. Pixels that darken when the aircraft appears, minus the pixels
  the aircraft's own body occupies, are its cast shadow on the ground.
* **Exposure does not breathe.** §6.6 commands manual exposure; the failure it
  prevents is the image re-metering as the bright-ground fraction changes with
  bank. Measured as the sky band's mean luminance across the roll doublet:
  the FDM roll must actually sweep (or the clause is vacuous) while the sky
  stays constant to within a couple of 8-bit counts.

What this gate does NOT claim: that the frames look like the real world. The
airframe is still boxes, the terrain material is the engine default, and there
is no foliage and no land-cover material (docs/VALIDITY.md records these as
Phase 6 work remaining). The four properties above are necessary conditions
the brief names, each of which the old footage measurably lacked.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import subprocess
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.terrain.synthesis import TerrainStatistics, generate  # noqa: E402
from experiments.gate5_ue_parity import (  # noqa: E402
    RENDER_DURATION_S, ROLL_DOUBLET, reference_spec, write_run_card,
)

RULE = "=" * 96

#: The flight the gate renders: low enough that the ground shadow subtends
#: real pixels, with the same roll doublet the Gate 5 on-screen clauses use.
PROMPT = "fly the 747 at 300 m and 250 kt for 60 seconds"

#: Terrain bake parameters. Deterministic: same seed, same raster, same sha256
#: -- and the commandlet's manifest must echo that sha back, or the rendered
#: mountains are not the raster this harness thinks they are (§1.4).
TERRAIN_SEED = 6
TERRAIN_RMS_SLOPE_DEG = 30.0

#: Thresholds, declared before any frame is measured.
THRESHOLDS = {
    #: Far peak's sky-contrast as a fraction of the near peak's. Extinction
    #: means the same mountain reads fainter with distance; 0.75 asks for a
    #: quarter of its contrast gone over ~20 km, which the fog settings exceed
    #: comfortably -- while a renderer with no aerial perspective at all
    #: (the old build) shows ratios near 1.
    "max_extinction_ratio": 0.75,
    #: Minimum sky-contrast of the NEAR peak, in 8-bit counts. Below this the
    #: extinction ratio is a quotient of noise.
    "min_near_contrast": 8.0,
    #: Cast-shadow area on terrain, pixels of a 960x540 frame (~1.9%).
    "min_valley_shadow_px": 10000,
    #: Aircraft ground-shadow area, pixels, after excluding its body.
    "min_aircraft_shadow_px": 300,
    #: Sky-band luminance excursion across the doublet window, 8-bit counts.
    #: Empirically anchored from both sides: with §6.6's manual exposure this
    #: scene measures 4.9 (smooth drift from three kilometres of camera
    #: travel), and with auto-exposure -- the failure the clause forbids --
    #: it measures 34.4. The threshold sits 1.6x above the one and 4x below
    #: the other.
    "max_sky_excursion": 8.0,
    #: What the auto-exposure negative control must exceed. A metric that the
    #: known failure cannot trip is not a measurement (§1.7), so every gate
    #: run re-validates its own instrument.
    "min_control_excursion": 16.0,
    #: The doublet must actually roll the aircraft, or "does not breathe when
    #: the aircraft banks" is being tested without any banking.
    "min_roll_sweep_deg": 10.0,
    #: A pixel counts as darkened in an A/B when its mean-RGB drops by this.
    "darkening_threshold": 12.0,
    #: A pixel belongs to the aircraft's body when any channel moves this much
    #: between aircraft-present and aircraft-hidden.
    "body_threshold": 60.0,
}

#: Rows of the frame treated as the terrain band in the terrain shot (the
#: mountains sit just above the horizon) and as pure sky (top of frame).
TERRAIN_BAND_ROWS = (80, 235)
SKY_BAND_ROWS = (0, 50)


# -- pixels ---------------------------------------------------------------


def load_rgb(path: Path):
    import numpy as np
    import rasterio

    with rasterio.open(path) as dataset:
        return dataset.read()[:3].astype(np.int64)


def luminance(rgb):
    return rgb.mean(axis=0)


def write_png_rgb(path: Path, rgb) -> Path:
    """Minimal 8-bit RGB PNG writer, so composing images needs no new deps."""
    import numpy as np

    array = np.clip(rgb, 0, 255).astype(np.uint8)
    height, width = array.shape[1], array.shape[2]
    interleaved = np.moveaxis(array, 0, 2)
    raw = b"".join(b"\x00" + interleaved[row].tobytes() for row in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return path


def patch_mean(image, px: float, py: float, half: int = 6) -> float:
    """Mean luminance of a small patch, clamped inside the frame."""
    height, width = image.shape
    x0 = max(0, int(px) - half)
    x1 = min(width, int(px) + half + 1)
    y0 = max(0, int(py) - half)
    y1 = min(height, int(py) + half + 1)
    return float(image[y0:y1, x0:x1].mean())


# -- the clauses ----------------------------------------------------------


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str

    def render(self) -> str:
        return f"  [{'ok  ' if self.ok else 'FAIL'}] {self.name:30s} {self.detail}"


def measure_extinction(frames_dir: Path) -> Check:
    """The same raster, near and far: the far copy must read fainter.

    Contrast is each peak's COLOUR distance from the sky directly above its
    projected pixel, not its luminance difference. Measured on this scene, a
    sunlit mountain and the sky behind it can match in luminance to within
    half a count while remaining plainly separate to the eye -- the eye is
    using chromaticity (warm rock against blue sky), and extinction is
    precisely the collapse of that difference toward the haze colour.
    """
    import numpy as np

    manifest = json.loads((frames_dir / "render.json").read_text(encoding="utf-8"))
    record = manifest["frame_records"][-1]
    landmarks = record.get("landmarks", {})
    near = landmarks.get("near_peak", {})
    far = landmarks.get("far_peak", {})
    if not (near.get("visible") and far.get("visible")):
        return Check("terrain shows range extinction", False,
                     "a terrain peak is not in frame; nothing to measure")

    rgb = load_rgb(frames_dir / record["frame"])

    def patch_rgb(px: float, py: float, half: int = 6):
        y0 = max(0, int(py) - half)
        x0 = max(0, int(px) - half)
        return rgb[:, y0:int(py) + half + 1, x0:int(px) + half + 1] \
            .mean(axis=(1, 2))

    contrasts = {}
    for name, mark in (("near", near), ("far", far)):
        peak = patch_rgb(mark["px"], mark["py"] + 8)
        sky = patch_rgb(mark["px"], mark["py"] - 45)
        contrasts[name] = float(np.linalg.norm(peak - sky))
    if contrasts["near"] < THRESHOLDS["min_near_contrast"]:
        return Check("terrain shows range extinction", False,
                     f"near peak contrast {contrasts['near']:.1f} is below "
                     f"{THRESHOLDS['min_near_contrast']:g}; the measurement "
                     f"would be a quotient of noise")
    ratio = contrasts["far"] / contrasts["near"]
    return Check(
        "terrain shows range extinction",
        ratio <= THRESHOLDS["max_extinction_ratio"],
        f"same raster: contrast {contrasts['near']:.1f} at ~10 km vs "
        f"{contrasts['far']:.1f} at ~30 km (ratio {ratio:.2f}, "
        f"threshold {THRESHOLDS['max_extinction_ratio']:g})",
    )


def darkened_mask(with_path: Path, without_path: Path):
    a = luminance(load_rgb(with_path))
    b = luminance(load_rgb(without_path))
    return (b - a) > THRESHOLDS["darkening_threshold"]


def measure_valley_shadow(still: Path, still_no_shadows: Path) -> Check:
    """Null test: what darkens when cast shadows exist is cast shadow."""
    mask = darkened_mask(still, still_no_shadows)
    band = mask[TERRAIN_BAND_ROWS[0]:TERRAIN_BAND_ROWS[1], :]
    area = int(band.sum())
    return Check(
        "peaks shadow the valley",
        area >= THRESHOLDS["min_valley_shadow_px"],
        f"{area} px of the terrain band darken when cast shadows are on "
        f"(threshold {THRESHOLDS['min_valley_shadow_px']})",
    )


def measure_aircraft_shadow(shadow_still: Path, hidden_still: Path) -> Check:
    """A/B against the hidden aircraft, with its own body pixels excluded."""
    import numpy as np

    with_aircraft = load_rgb(shadow_still)
    without = load_rgb(hidden_still)
    darkened = (luminance(without) - luminance(with_aircraft)) \
        > THRESHOLDS["darkening_threshold"]
    body = np.abs(with_aircraft - without).max(axis=0) \
        > THRESHOLDS["body_threshold"]
    area = int((darkened & ~body).sum())
    return Check(
        "aircraft has a ground shadow",
        area >= THRESHOLDS["min_aircraft_shadow_px"],
        f"{area} px darken on the ground when the aircraft is present, "
        f"excluding its body (threshold {THRESHOLDS['min_aircraft_shadow_px']})",
    )


def measure_exposure(frames_dir: Path) -> Check:
    """The sky must not re-meter while the aircraft banks under it."""
    manifest = json.loads((frames_dir / "render.json").read_text(encoding="utf-8"))
    records = manifest["frame_records"]
    rolls = [record["roll_deg"] for record in records]
    sweep = max(rolls) - min(rolls)
    if sweep < THRESHOLDS["min_roll_sweep_deg"]:
        return Check("exposure does not breathe", False,
                     f"the aircraft only rolled {sweep:.1f} deg; the clause "
                     f"would be tested without any banking")
    excursion = sky_excursion(frames_dir)
    return Check(
        "exposure does not breathe",
        excursion <= THRESHOLDS["max_sky_excursion"],
        f"sky band moved {excursion:.2f}/255 over a {sweep:.1f} deg roll sweep "
        f"(threshold {THRESHOLDS['max_sky_excursion']:g}; auto-exposure "
        f"measures ~34 on this scene)",
    )


def sky_excursion(frames_dir: Path) -> float:
    """Peak-to-peak sky-band luminance inside the doublet window."""
    manifest = json.loads((frames_dir / "render.json").read_text(encoding="utf-8"))
    means = [float(luminance(load_rgb(frames_dir / record["frame"]))
                   [SKY_BAND_ROWS[0]:SKY_BAND_ROWS[1], :].mean())
             for record in manifest["frame_records"]
             if 3.0 <= record["t"] <= 20.0]
    return max(means) - min(means)


def measure_exposure_control(control_dir: Path) -> Check:
    """The metric must catch the failure it exists for, every run.

    The control renders the same flight with the engine's default
    auto-exposure -- exactly the metering §6.6 replaces -- and the measurement
    has to trip on it. If it does not, the manual run's pass says nothing,
    and the clause fails on the instrument rather than the image.
    """
    manifest = json.loads((control_dir / "render.json").read_text(encoding="utf-8"))
    exposure = manifest.get("scene", {}).get("exposure", "")
    if not exposure.startswith("auto"):
        return Check("exposure metric discriminates", False,
                     f"the control rendered with '{exposure}', not "
                     f"auto-exposure; it controls for nothing")
    excursion = sky_excursion(control_dir)
    return Check(
        "exposure metric discriminates",
        excursion >= THRESHOLDS["min_control_excursion"],
        f"auto-exposure control pumps the sky band {excursion:.2f}/255 "
        f"(must exceed {THRESHOLDS['min_control_excursion']:g} for the "
        f"manual run's pass to mean anything)",
    )


def compose_side_by_side(old_frame: Path, new_frame: Path, out: Path) -> Path:
    """The human-judgment clause's evidence: old footage beside this build."""
    import numpy as np

    def fit(rgb, height: int):
        scale = rgb.shape[1] / height
        rows = (np.arange(height) * scale).astype(int)
        columns = (np.arange(int(rgb.shape[2] / scale)) * scale).astype(int)
        return rgb[:, rows][:, :, columns]

    new = load_rgb(new_frame)
    old = fit(load_rgb(old_frame), new.shape[1])
    divider = np.full((3, new.shape[1], 4), 255, dtype=np.int64)
    return write_png_rgb(out, np.concatenate([old, divider, new], axis=2))


# -- orchestration --------------------------------------------------------


def render(editor: Path, project: Path, card: Path, frames: Path,
           terrain: Path, shot: str, extra: Sequence[str]) -> bool:
    frames.mkdir(parents=True, exist_ok=True)
    for stale in frames.glob("frame_*.png"):
        stale.unlink()
    (frames / "render.json").unlink(missing_ok=True)
    command = [
        str(editor), str(project),
        "-run=FlightSimBridge.FlightSimRender",
        f"-scenario={card}", f"-frames={frames}",
        "-Visual", f"-shot={shot}", f"-terrain={terrain}",
        "-unattended", "-nopause", "-nosplash",
        # -stdout matters for more than logging: without it this editor build
        # stalls indefinitely when driven from a subprocess. Measured -- the
        # identical command with these flags finishes in seconds.
        "-stdout", "-FullStdOutLogOutput",
        "-RenderOffScreen", "-AllowCommandletRendering",
        *extra,
    ]
    log = frames.parent / f"{frames.name}.log"
    with log.open("w") as sink:
        process = subprocess.run(command, stdout=sink, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL)
    return process.returncode == 0 and (frames / "render.json").is_file()


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 6")
    ap.add_argument("--out", default="runs/gate6")
    ap.add_argument("--old-footage",
                    default=str(Path.home() / "FlightScene" / "renders"))
    ap.add_argument("--skip-render", action="store_true",
                    help="measure existing renders without re-rendering")
    args = ap.parse_args(argv)
    # Absolute, because these paths are handed to the editor, whose working
    # directory is its own binary's -- a relative card path resolves to
    # nothing there and the render dies before its first frame.
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    root = Path(__file__).resolve().parents[1]
    editor = Path("/Users/Shared/Epic Games/UE_5.5/Engine/Binaries/Mac/UnrealEditor-Cmd")
    project = root / "ue" / "FlightSim.uproject"

    print(f"\n{RULE}\n1. inputs, all deterministic\n{RULE}")
    field = generate(size=512, pixel_size_m=30.0,
                     statistics=TerrainStatistics(rms_slope_deg=TERRAIN_RMS_SLOPE_DEG),
                     seed=TERRAIN_SEED, base_elevation_m=0.0, name="gate6_ridge")
    terrain = field.write(out / "terrain")
    print(f"  terrain     {terrain} (sha {field.digest()[:16]})")
    spec = reference_spec(PROMPT)
    card = write_run_card(spec, out / "ue_render_scenario.json",
                          control_inputs=ROLL_DOUBLET,
                          duration_s=RENDER_DURATION_S)
    print(f"  scenario    {card} (digest {spec.digest()[:16]})")

    runs = {
        "full": ("terrain", []),
        "still": ("terrain", ["-seconds=2"]),
        "still_noshadow": ("terrain", ["-seconds=2", "-NoShadows"]),
        "shadow": ("shadow", ["-seconds=2"]),
        "shadow_hidden": ("shadow", ["-seconds=2", "-HideAircraft"]),
        # The exposure clause's negative control (see measure_exposure_control).
        "full_auto": ("terrain", ["-AutoExposure"]),
    }
    print(f"\n{RULE}\n2. renders\n{RULE}")
    for name, (shot, extra) in runs.items():
        frames = out / name
        if args.skip_render and (frames / "render.json").is_file():
            print(f"  [kept] {name}")
            continue
        if not editor.is_file():
            print(f"  no editor at {editor}\n\n  GATE 6: BLOCKED")
            return 2
        ok = render(editor, project, card, frames, terrain, shot, extra)
        print(f"  [{'ok  ' if ok else 'FAIL'}] {name} ({shot} shot"
              f"{' ' + ' '.join(extra) if extra else ''})")
        if not ok:
            print("\n  GATE 6: BLOCKED -- a render did not complete.")
            return 2

    # The terrain the commandlet drew must be the raster baked above (§1.4:
    # one lookup, verified after load -- the renderer's version of it).
    for name in runs:
        manifest = json.loads((out / name / "render.json").read_text(encoding="utf-8"))
        rendered_sha = manifest.get("scene", {}).get("terrain_sha256", "")
        if rendered_sha != field.digest():
            print(f"\n  {name} rendered terrain {rendered_sha[:16]}, but the "
                  f"bake is {field.digest()[:16]}.")
            print("  The measured mountains are not the raster this harness "
                  "baked. GATE 6: BLOCKED")
            return 2

    print(f"\n{RULE}\n3. the four measurable clauses\n{RULE}")
    still = sorted((out / "still").glob("frame_*.png"))[-1]
    still_ns = sorted((out / "still_noshadow").glob("frame_*.png"))[-1]
    shadow = sorted((out / "shadow").glob("frame_*.png"))[-1]
    shadow_hidden = sorted((out / "shadow_hidden").glob("frame_*.png"))[-1]
    checks = [
        measure_extinction(out / "full"),
        measure_valley_shadow(still, still_ns),
        measure_aircraft_shadow(shadow, shadow_hidden),
        measure_exposure(out / "full"),
        measure_exposure_control(out / "full_auto"),
    ]
    for check in checks:
        print(check.render())

    print(f"\n{RULE}\n4. the side-by-side\n{RULE}")
    old_frames = sorted(Path(args.old_footage).glob("*.png"))
    side_by_side = None
    if old_frames:
        old = old_frames[len(old_frames) // 2]
        new = sorted((out / "full").glob("frame_*.png"))[-1]
        side_by_side = compose_side_by_side(old, new, out / "side_by_side.png")
        print(f"  old footage {old}")
        print(f"  this build  {new}")
        print(f"  wrote       {side_by_side}")
        print("  Likeness is the reader's judgment to make, not this "
              "harness's. What the")
        print("  measurements above establish is that the four properties "
              "the brief named")
        print("  as missing from the old footage are present in the new.")
    else:
        print(f"  no old footage found under {args.old_footage}")

    everything = all(check.ok for check in checks) and side_by_side is not None
    print(f"\n{RULE}\nGATE 6\n{RULE}")
    for check in checks:
        print(f"  [{'PASS' if check.ok else 'FAIL'}] {check.name}")
    print(f"  [{'PASS' if side_by_side else 'FAIL'}] side-by-side produced "
          f"against the old footage")
    if everything:
        print("\n  GATE 6: PASS -- four clauses measured from the pixels, the "
              "side-by-side")
        print("  produced for human judgment. Scope: box airframe, default "
              "terrain material,")
        print("  no foliage -- docs/VALIDITY.md lists the Phase 6 work that "
              "remains.")
        return 0
    print("\n  GATE 6: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
