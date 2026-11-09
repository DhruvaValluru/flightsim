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
  Extinction means the far copy of the very same mountain reads fainter. The
  near copy stands in front of the far peak, so the far peak is read from a
  second still with ``-HideNearTerrain`` (same camera, same sun, same fog, the
  near copy left out); a projected pixel is "in frame", not "seen". Contrast
  is the spread of light inside the same piece of each mountain (lit rock
  against shaded rock), C = C0 * T. A pair with ``-NoAerialPerspective`` is the
  control: with nothing between camera and rock, distance must fade nothing.
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

Phase 2 look clauses (contracts §5.4, §10; brainstorm §9.2, §9.7)
--------------------------------------------------------------------
Four more clauses, each a pixel measurement against a control render with
ONE switch changed (the gotcha 6 pattern), each reporting NOT RUN with its
measurement stated when its renders do not exist -- which is every run in
an environment without the engine. They are rendered by ``--look`` and
graded whenever their directories exist:

* **Cloud base bracket.** The same still with a cloud layer whose base is
  300 m ABOVE the 300 m flight (600-1400 m) and one whose layer is 300 m
  BELOW it (20-200 m), each against a no-cloud control. Pixels that change
  are cloud. With the base above the camera, cloud may change the sky band
  only; with the layer below, the ground band only. A base drawn at the
  wrong height fails one side of the bracket. (The brainstorm's "cloud-only
  depth render" does not exist: volumetrics write no depth.)
* **Extinction vs visibility_km.** The near peak's contrast, re-run with the
  fog density set by Koschmieder (beta = 3.912 / V, re-implemented here, not
  imported from the producer) at 50 km and at 10 km. One peak at one range,
  so only the air differs; the hazy day must keep at most a stated share of
  the clear day's contrast. The far peak cannot grade this: at the true
  density it sits on the fog's 0.92 opacity cap on both days. ``FogDensity``
  is NOT a per-metre extinction, see core/scene/weather_visuals.py ENGINE_FOG_DENSITY_PER_EXTINCTION.
* **Wet-surface null test.** The same still with ``-precip=rain`` and
  ``-precip=none``. The terrain band must change (the wetness scalar
  reached a material parameter -- and ``look_applied`` must not say the
  parameter was absent), and the sky band must NOT change: the sky does
  not get wet, so a change there is a different switch, not wetness.
* **Exposure holds at -12 deg sun.** The doublet at ``-sun-elev=-12``: the
  frames must not be black (a clause on black frames measures nothing) and
  the sky band must hold exactly as the daylight exposure clause demands.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import struct
import subprocess
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.util.platform import (  # noqa: E402
    TOOLCHAIN, UE_ENGINE_PATCH, UE_ENGINE_VERSION, ue_editor_path,
)
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
    #: (the old build) shows ratios near 1. The 0.27 of 5.5 graded a far pixel
    #: that lay on the near copy. Measured 2026-11-04 on 5.7.4, far peak seen
    #: alone: good 0.14, the no-aerial-perspective control that must fail it
    #: 0.91. The number stands.
    "max_extinction_ratio": 0.75,
    #: Minimum sky-contrast of the NEAR peak, in 8-bit counts. Below this the
    #: extinction ratio is a quotient of noise.
    "min_near_contrast": 8.0,
    #: Cast-shadow area on terrain, pixels of a 960x540 frame (~1.9%).
    "min_valley_shadow_px": 10000,
    #: Aircraft ground-shadow area, pixels, after excluding its body. Measured
    #: 2026-11-04 on 5.7.4: good 863; bad 79, the same A/B with the ground
    #: culled and no shadow on it, all of it edge pixels of the body (1,181
    #: on 5.5). The number stands.
    "min_aircraft_shadow_px": 300,
    #: Sky-band luminance excursion across the doublet window, 8-bit counts.
    #: Empirically anchored from both sides: with §6.6's manual exposure this
    #: scene measures 4.9 (smooth drift from three kilometres of camera
    #: travel), and with auto-exposure -- the failure the clause forbids --
    #: it measures 34.4 (both measured on 5.5). Measured 2026-11-04 on 5.7.4:
    #: good 5.96 under manual exposure; bad 57.90, one stop of real exposure
    #: change. The number stands.
    "max_sky_excursion": 8.0,
    #: What the negative control must exceed. A metric that the known failure
    #: cannot trip is not a measurement (§1.7), so every gate run re-validates
    #: its own instrument. The control is auto-exposure, as on 5.5 (34.4). On
    #: 5.7.4 this flight's frame barely changes with bank (5.85), so the control
    #: renders the same shot with the plain going dark at EXPOSURE_STEP_AT_S, a
    #: luminance step clear of the sky band: measured 29.62 under auto-exposure
    #: and 5.84 under manual, which must hold under max_sky_excursion.
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

# -- Phase 2 look clauses: declared before any frame is measured ----------

#: Rows below the horizon in the terrain shot: the plain under the 300 m
#: flight, where a cloud layer BELOW the aircraft shows and one above it
#: cannot.
CLOUD_GROUND_ROWS = (300, 540)
#: The cloud base bracket: the layer is placed this far above, then this far
#: below, the flight altitude of the gate's card (300 m).
CLOUD_BASE_BRACKET_M = 300.0
FLIGHT_ALTITUDE_M = 300.0
#: The two visibilities the extinction clause is re-run at, km.
VISIBILITY_CLEAR_KM = 50.0
VISIBILITY_HAZY_KM = 10.0
#: Koschmieder's constant, ln(1/0.02): RE-IMPLEMENTED here on purpose. The
#: producer is core/scene/weather_visuals.py; this harness must not import
#: the thing it measures.
KOSCHMIEDER = 3.912

#: Half-size and drop below the peak of the block the extinction clauses
#: read, pixels at the near peak (the far one shrinks with range, so both
#: cover the same ground): large enough to hold lit and shaded rock at once.
PEAK_PATCH_HALF = 20
PEAK_PATCH_DROP = 24
#: The block's contrast: its luminance spread between these percentiles.
PEAK_SPREAD_PERCENTILES = (10, 90)
#: When the exposure control's plain goes dark (-GroundDarkAt), seconds into
#: sky_excursion's window, leaving the meter the rest of the clip to chase it.
EXPOSURE_STEP_AT_S = 10.0

LOOK_THRESHOLDS = {
    #: Cloud on/off must change this many pixels in the band the layer's
    #: height predicts ...
    "cloud_min_changed_px": 2000,
    #: ... and at most this many in the band it cannot reach.
    "cloud_max_leak_px": 500,
    #: A layer above the camera shades the ground and must not black it out:
    #: the share of the clear ground's mean it keeps. Measured on 5.7.4: 0.86
    #: with the sky light captured; 0.01 without it, the defect this grades.
    "cloud_min_ground_kept": 0.25,
    #: Rain on/off must change this many terrain-band pixels ...
    "wet_min_changed_px": 2000,
    #: ... and this few sky-band pixels (the null: sky does not get wet).
    "wet_max_sky_changed_px": 200,
    #: Mean frame luminance under a -12 deg sun, 8-bit counts: below this the
    #: frames are black and the exposure clause is vacuous.
    "night_min_mean_luminance": 2.0,
    #: I6 albedo sun invariance: the two albedo images (16-bit) may differ
    #: by more than this many counts (1/255 of full scale) on at most
    #: ``albedo_max_changed_fraction`` of their pixels ...
    "albedo_tolerance_counts": 257,
    "albedo_max_changed_fraction": 0.001,
    #: ... while the two BEAUTY frames must differ on at least this many
    #: terrain-band pixels, or the sun switch moved nothing and the
    #: invariance is vacuous.
    "albedo_control_min_changed_px": 2000,
}


def koschmieder_fog_density(visibility_km: float) -> float:
    """beta = 3.912 / (1000 V) in 1/m, V in km (re-implemented, see above)."""
    return KOSCHMIEDER / (1000.0 * float(visibility_km))


def engine_fog_density(visibility_km: float) -> float:
    """The -fog-density the product draws this visibility with: the product's
    own conversion, so the clause grades that path and not a copy of it."""
    from core.scene import weather_visuals

    return weather_visuals.engine_fog_density(weather_visuals.fog_extinction_per_m(visibility_km))


#: The look control renders (--look): one switch per pair, everything else
#: the gate's terrain shot. Values are (shot, extra flags).
LOOK_RUNS = {
    "cloud_above": ("terrain", [
        "-seconds=2", "-cloud-cover=0.9",
        f"-cloud-base={FLIGHT_ALTITUDE_M + CLOUD_BASE_BRACKET_M:g}",
        "-cloud-thickness=800"]),
    "cloud_below": ("terrain", [
        "-seconds=2", "-cloud-cover=0.9",
        f"-cloud-base={FLIGHT_ALTITUDE_M - CLOUD_BASE_BRACKET_M + 20:g}",
        "-cloud-thickness=180"]),
    "cloud_control": ("terrain", ["-seconds=2", "-cloud-cover=0"]),
    "visibility_clear": ("terrain", [
        "-seconds=2", f"-fog-density={engine_fog_density(VISIBILITY_CLEAR_KM):.6g}"]),
    "visibility_hazy": ("terrain", [
        "-seconds=2", f"-fog-density={engine_fog_density(VISIBILITY_HAZY_KM):.6g}"]),
    "wet": ("terrain", ["-seconds=2", "-precip=rain"]),
    "wet_control": ("terrain", ["-seconds=2", "-precip=none"]),
    "night": ("terrain", ["-sun-elev=-12", "-sun-azim=180"]),
    # I6: the albedo pass under two suns, everything else equal. The base
    # colour is what the lights see, not what they make; the beauty
    # frames must change and the albedo images must not.
    "albedo_sun_high": ("terrain", [
        "-seconds=2", "-labels", "-passes=albedo", "-sun-elev=60", "-sun-azim=180"]),
    "albedo_sun_low": ("terrain", [
        "-seconds=2", "-labels", "-passes=albedo", "-sun-elev=15", "-sun-azim=180"]),
}


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


def measure_extinction(frames_dir: Path, far_dir: Optional[Path] = None,
                       control_dir: Optional[Path] = None,
                       control_far_dir: Optional[Path] = None) -> Check:
    """The same raster, near and far: the far copy must read fainter.

    Contrast is the spread of light inside the same piece of each mountain
    (peak_contrasts), not its distance from the sky. Measured 2026-11-04 on
    5.7.4 that distance is not monotonic in fog (0.66, 1.95, 1.04 at three
    rising densities): a grey peak's mean sits near the sky's colour, so
    haze can raise it or lower it. Lit against shaded rock can only collapse.

    ``far_dir`` is the render the far peak is read from (the near copy left
    out, see peak_contrasts); without it both peaks come from ``frames_dir``.
    ``control_dir``/``control_far_dir`` are the same pair with no aerial
    perspective: its ratio must MISS the threshold, or the clause cannot tell
    haze from anything else and a pass means nothing.
    """
    contrasts = peak_contrasts(frames_dir, far_dir)
    if contrasts is None:
        return Check("terrain shows range extinction", False,
                     "a terrain peak is not in frame; nothing to measure")
    if contrasts["near"] < THRESHOLDS["min_near_contrast"]:
        return Check("terrain shows range extinction", False,
                     f"near peak contrast {contrasts['near']:.1f} is below "
                     f"{THRESHOLDS['min_near_contrast']:g}; the measurement "
                     f"would be a quotient of noise")
    ratio = contrasts["far"] / contrasts["near"]
    control_note, control_ok = "", True
    if control_dir is not None:
        control = peak_contrasts(control_dir, control_far_dir)
        if control is None:
            return Check("terrain shows range extinction", False,
                         "a terrain peak is not in frame in the control")
        control_ratio = control["far"] / control["near"]
        control_ok = control_ratio > THRESHOLDS["max_extinction_ratio"]
        control_note = f"; no-aerial-perspective control {control_ratio:.2f} must exceed it"
    return Check(
        "terrain shows range extinction",
        ratio <= THRESHOLDS["max_extinction_ratio"] and control_ok,
        f"same raster: contrast {contrasts['near']:.1f} at "
        f"{_range_text(contrasts['near_range_m'], '~10 km')} vs "
        f"{contrasts['far']:.1f} at "
        f"{_range_text(contrasts['far_range_m'], '~30 km')} (ratio {ratio:.2f}, "
        f"threshold {THRESHOLDS['max_extinction_ratio']:g}{control_note})",
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
        f"(threshold {THRESHOLDS['max_sky_excursion']:g})",
    )


def sky_excursion(frames_dir: Path) -> float:
    """Peak-to-peak sky-band luminance inside the doublet window."""
    manifest = json.loads((frames_dir / "render.json").read_text(encoding="utf-8"))
    means = [float(luminance(load_rgb(frames_dir / record["frame"]))
                   [SKY_BAND_ROWS[0]:SKY_BAND_ROWS[1], :].mean())
             for record in manifest["frame_records"]
             if 3.0 <= record["t"] <= 20.0]
    return max(means) - min(means)


def measure_exposure_control(control_dir: Path, manual_dir: Optional[Path] = None) -> Check:
    """The metric must catch the failure it exists for, every run.

    The control renders the flight with the engine's default auto-exposure,
    exactly the metering the manual exposure replaces, and the plain going
    dark mid-shot, so the meter has something to chase: it must pump the sky
    band past the line. ``manual_dir`` is the same shot under manual exposure,
    which must hold, or the sky moved by itself and the step proves nothing.
    """
    manifest = json.loads((control_dir / "render.json").read_text(encoding="utf-8"))
    exposure = manifest.get("scene", {}).get("exposure", "")
    if not exposure.startswith("auto"):
        return Check("exposure metric discriminates", False,
                     f"the control rendered with '{exposure}', not "
                     f"auto-exposure; it controls for nothing")
    excursion = sky_excursion(control_dir)
    manual_note, manual_ok = "", True
    if manual_dir is not None:
        manual = sky_excursion(manual_dir)
        manual_ok = manual <= THRESHOLDS["max_sky_excursion"]
        manual_note = (f"; the same step under manual exposure {manual:.2f}/255 "
                       f"(must stay under {THRESHOLDS['max_sky_excursion']:g})")
    return Check(
        "exposure metric discriminates",
        excursion >= THRESHOLDS["min_control_excursion"] and manual_ok,
        f"auto-exposure control pumps the sky band {excursion:.2f}/255 "
        f"(must exceed {THRESHOLDS['min_control_excursion']:g} for the "
        f"manual run's pass to mean anything){manual_note}",
    )


# -- Phase 2 look clauses -------------------------------------------------


# -- edge aliasing (visual plan V0 "Measure"; REPORTED, not a gate) --------
#
# "Edge-aliasing metric (high-frequency energy along the aircraft
# silhouette) drops against today's baseline." This is that number, and
# only a number: no threshold is set (none has been measured), so it never
# passes or fails Gate 6. Definition, so a reader can recompute it:
#
#   * the silhouette is the aircraft body mask (shadow vs shadow_hidden,
#     the same body test measure_aircraft_shadow uses), or a label mask;
#   * the band is every pixel within ALIASING_BAND_PX of the mask's
#     boundary (8-neighbour dilation XOR erosion);
#   * the high-pass is luminance minus its 3x3 box mean;
#   * energy = RMS of the high-pass over the band, divided by the edge
#     contrast (|mean luminance just inside - just outside|), so a brighter
#     sky does not read as more aliasing. Lower is smoother.
#
# Self-validation (the plan's §5 rule, "the metric must trip on a
# deliberately broken input or the pass is void"): the same frame point-
# sampled at ALIASING_CONTROL_STRIDE and blown back up by nearest neighbour
# has staircased edges; its energy must come out HIGHER, or the number is
# reported as void.

#: Band half-width around the silhouette, pixels.
ALIASING_BAND_PX = 2
#: The aliased control's point-sampling stride.
ALIASING_CONTROL_STRIDE = 2
#: Below this edge contrast (8-bit counts) there is no edge to grade.
ALIASING_MIN_CONTRAST = 8.0


def _grow(mask, steps: int):
    import numpy as np

    out = mask.copy()
    for _ in range(steps):
        grown = out.copy()
        grown[1:, :] |= out[:-1, :]
        grown[:-1, :] |= out[1:, :]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        grown[1:, 1:] |= out[:-1, :-1]
        grown[:-1, :-1] |= out[1:, 1:]
        grown[1:, :-1] |= out[:-1, 1:]
        grown[:-1, 1:] |= out[1:, :-1]
        out = grown
    return out


def _box3(image):
    import numpy as np

    padded = np.pad(image, 1, mode="edge")
    total = np.zeros_like(image, dtype=float)
    for dy in range(3):
        for dx in range(3):
            total += padded[dy:dy + image.shape[0], dx:dx + image.shape[1]]
    return total / 9.0


def edge_aliasing_energy(rgb, mask, band_px: int = ALIASING_BAND_PX) -> Optional[float]:
    """Contrast-normalised high-frequency RMS along ``mask``'s boundary
    (definition above), or None when the mask has no edge to grade."""
    import numpy as np

    mask = np.asarray(mask, dtype=bool)
    if mask.sum() == 0 or (~mask).sum() == 0:
        return None
    light = luminance(rgb).astype(float)
    outer = _grow(mask, band_px)
    inner = ~_grow(~mask, band_px)
    band = outer & ~inner
    inside, outside = band & mask, band & ~mask
    if band.sum() == 0 or inside.sum() == 0 or outside.sum() == 0:
        return None
    contrast = abs(float(light[inside].mean()) - float(light[outside].mean()))
    if contrast < ALIASING_MIN_CONTRAST:
        return None
    high = light - _box3(light)
    return float(np.sqrt(np.mean(high[band] ** 2)) / contrast)


def aliased_control(rgb, stride: int = ALIASING_CONTROL_STRIDE):
    """The same frame point-sampled every ``stride`` pixels and blown back
    up by nearest neighbour: deliberately staircased edges."""
    import numpy as np

    small = rgb[:, ::stride, ::stride]
    big = np.repeat(np.repeat(small, stride, axis=1), stride, axis=2)
    return big[:, :rgb.shape[1], :rgb.shape[2]]


def measure_edge_aliasing(frame_rgb, mask) -> dict:
    """The reported row: the frame's energy, the aliased control's, and
    whether the control tripped (``void`` when it did not)."""
    import numpy as np

    mask = np.asarray(mask, dtype=bool)
    energy = edge_aliasing_energy(frame_rgb, mask)
    control_mask = aliased_control(mask[None].astype(np.int64))[0].astype(bool)
    control = edge_aliasing_energy(aliased_control(frame_rgb), control_mask)
    void = energy is None or control is None or not control > energy
    return {"energy": energy, "control_energy": control, "void": void,
            "band_px": ALIASING_BAND_PX, "control_stride": ALIASING_CONTROL_STRIDE,
            "silhouette_px": int(mask.sum()),
            "definition": "RMS of (luminance - 3x3 box mean) within band_px of the "
                          "silhouette, over the edge contrast; lower is smoother; "
                          "reported, not a gate"}


def aircraft_body_mask(shadow_still: Path, hidden_still: Path):
    """The pixels the aircraft's own body occupies: what changes by more
    than the body threshold when it is drawn (measure_aircraft_shadow's
    test)."""
    import numpy as np

    with_aircraft = load_rgb(shadow_still)
    without = load_rgb(hidden_still)
    return np.abs(with_aircraft - without).max(axis=0) > THRESHOLDS["body_threshold"]


def report_edge_aliasing(out: Path, baseline: Optional[Path] = None) -> Optional[dict]:
    """Grade the shadow shot's silhouette and write ``out/aliasing.json``;
    with ``baseline`` (another tree's aliasing.json or its directory) the
    row carries the change against it. None when the shots do not exist."""
    shadow = sorted((out / "shadow").glob("frame_*.png"))
    hidden = sorted((out / "shadow_hidden").glob("frame_*.png"))
    if not shadow or not hidden:
        return None
    row = measure_edge_aliasing(load_rgb(shadow[-1]),
                                aircraft_body_mask(shadow[-1], hidden[-1]))
    row["frame"] = str(shadow[-1])
    if baseline is not None:
        path = baseline / "aliasing.json" if baseline.is_dir() else baseline
        try:
            before = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            before = None
        row["baseline"] = str(path)
        # A VOID row (the control did not trip) has no comparable number:
        # no change is computed against one, and the line says why.
        if before and before.get("void"):
            row["change_void"] = "baseline void"
        elif row["void"]:
            row["change_void"] = "this run void"
        elif before and before.get("energy") is not None and row["energy"] is not None:
            row["baseline_energy"] = before["energy"]
            row["change"] = row["energy"] - before["energy"]
    (out / "aliasing.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
    return row


def edge_aliasing_line(row: dict) -> str:
    """The one report line: [info], never PASS or FAIL."""
    energy = row["energy"]
    control = row["control_energy"]
    line = (f"  [info] edge aliasing (reported, not a gate) "
            f"{'no edge to grade' if energy is None else f'{energy:.4f}'}; aliased control "
            f"{'n/a' if control is None else f'{control:.4f}'}; "
            f"{'VOID: the control did not trip' if row['void'] else 'control tripped'}")
    if "change" in row:
        line += f"; change vs baseline {row['change']:+.4f}"
    elif row.get("change_void"):
        line += f"; no comparison with the baseline ({row['change_void']})"
    return line


@dataclass(frozen=True)
class LookClause:
    """A look clause's outcome: PASS, FAIL, or NOT RUN with the measurement
    it WOULD make stated -- never a silent skip."""
    name: str
    status: str          # "PASS" | "FAIL" | "NOT RUN"
    detail: str
    measurement: str

    @property
    def ran(self) -> bool:
        return self.status != "NOT RUN"

    @property
    def ok(self) -> bool:
        return self.status == "PASS"

    def render(self) -> str:
        tag = {"PASS": "ok  ", "FAIL": "FAIL"}.get(self.status, "----")
        line = f"  [{tag}] {self.name:30s} {self.detail}"
        if not self.ran:
            line += f"\n         measurement: {self.measurement}"
        return line


def _last_frame(frames_dir: Path) -> Path:
    manifest = json.loads((frames_dir / "render.json").read_text(encoding="utf-8"))
    return frames_dir / manifest["frame_records"][-1]["frame"]


def _look_applied(frames_dir: Path) -> dict:
    manifest = json.loads((frames_dir / "render.json").read_text(encoding="utf-8"))
    return manifest.get("look_applied", {}) or {}


def changed_mask(a_path: Path, b_path: Path):
    """Pixels whose mean-RGB differs by the darkening threshold either way."""
    import numpy as np

    a = luminance(load_rgb(a_path))
    b = luminance(load_rgb(b_path))
    return np.abs(a - b) > THRESHOLDS["darkening_threshold"]


def _band_count(mask, rows: Tuple[int, int]) -> int:
    return int(mask[rows[0]:rows[1], :].sum())


CLOUD_MEASUREMENT = (
    "same still, cloud layer 300 m above the flight vs 300 m below it, each "
    "against a no-cloud control, cloud shadows on; changed pixels are cloud; "
    f"above -> sky band rows {SKY_BAND_ROWS} only, below -> ground band rows "
    f"{CLOUD_GROUND_ROWS} only (min changed / max leak px in LOOK_THRESHOLDS). "
    "Above, the ground is compared after its mean shade is divided out, so the "
    "layer's shadow is not counted as cloud, and it must keep "
    "cloud_min_ground_kept of the clear ground's mean")


def measure_cloud_base(above_dir: Path, below_dir: Path, control_dir: Path) -> LookClause:
    control = _last_frame(control_dir)
    above = changed_mask(_last_frame(above_dir), control)
    below = changed_mask(_last_frame(below_dir), control)
    above_sky = _band_count(above, SKY_BAND_ROWS)
    rows = slice(*CLOUD_GROUND_ROWS)
    clear_ground = luminance(load_rgb(control))[rows]
    shaded_ground = luminance(load_rgb(_last_frame(above_dir)))[rows]
    kept = float(shaded_ground.mean()) / max(float(clear_ground.mean()), 1e-6)
    above_ground = int((abs(shaded_ground / max(kept, 1e-6) - clear_ground)
                        > THRESHOLDS["darkening_threshold"]).sum())
    below_sky = _band_count(below, SKY_BAND_ROWS)
    below_ground = _band_count(below, CLOUD_GROUND_ROWS)
    minimum = LOOK_THRESHOLDS["cloud_min_changed_px"]
    leak = LOOK_THRESHOLDS["cloud_max_leak_px"]
    applied = _look_applied(above_dir).get("clouds", {})
    floor = LOOK_THRESHOLDS["cloud_min_ground_kept"]
    ok = (above_sky >= minimum and above_ground <= leak and kept >= floor
          and below_ground >= minimum and below_sky <= leak)
    return LookClause(
        "cloud base bracket", "PASS" if ok else "FAIL",
        f"layer above: {above_sky} sky px / {above_ground} ground px changed, ground "
        f"keeps {kept:.2f} of its light (min {floor:g}); "
        f"layer below: {below_ground} ground px / {below_sky} sky px "
        f"(min {minimum}, leak max {leak}; cover parameter "
        f"{applied.get('cover_parameter', 'unrecorded')})",
        CLOUD_MEASUREMENT)


def _range_text(range_m: Optional[float], fallback: str) -> str:
    return fallback if range_m is None else f"{range_m / 1000.0:.1f} km"


def peak_contrasts(frames_dir: Path, far_dir: Optional[Path] = None) -> Optional[dict]:
    """Near/far peak contrast (the luminance spread of a block on each), or
    None when a peak is out of frame. The one quantity both extinction
    clauses use.

    The near peak is read from ``frames_dir`` and the far peak from
    ``far_dir`` (the same still with -HideNearTerrain). Measured 2026-11-04
    on UE 5.7.4: in the two-copy frame the far peak's pixel lies on the near
    copy, so it was never the far mountain that was graded. When the record
    states each peak's range the far block shrinks with it, so both cover
    the same piece of the same mountain.
    """
    import numpy as np

    far_dir = frames_dir if far_dir is None else far_dir
    near_record = json.loads((frames_dir / "render.json").read_text(
        encoding="utf-8"))["frame_records"][-1]
    far_record = json.loads((far_dir / "render.json").read_text(
        encoding="utf-8"))["frame_records"][-1]
    near = near_record.get("landmarks", {}).get("near_peak", {})
    far = far_record.get("landmarks", {}).get("far_peak", {})
    if not (near.get("visible") and far.get("visible")):
        return None
    near_range, far_range = near.get("range_m"), far.get("range_m")
    far_scale = near_range / far_range if near_range and far_range else 1.0

    def contrast(frame: Path, mark: dict, scale: float) -> float:
        lum = luminance(load_rgb(frame))
        half = max(2, round(PEAK_PATCH_HALF * scale))
        y = int(mark["py"] + PEAK_PATCH_DROP * scale)
        x = int(mark["px"])
        block = lum[max(0, y - half):y + half + 1, max(0, x - half):x + half + 1]
        low, high = np.percentile(block, PEAK_SPREAD_PERCENTILES)
        return float(high - low)

    return {"near": contrast(frames_dir / near_record["frame"], near, 1.0),
            "far": contrast(far_dir / far_record["frame"], far, far_scale),
            "near_range_m": near_range, "far_range_m": far_range}


VISIBILITY_MEASUREMENT = (
    f"the near peak's contrast at the -fog-density of V = {VISIBILITY_CLEAR_KM:g} km and "
    f"{VISIBILITY_HAZY_KM:g} km (Koschmieder, in engine units): the hazy day must keep at "
    f"most {THRESHOLDS['max_extinction_ratio']:g} of the clear day's, the clear contrast "
    f"above {THRESHOLDS['min_near_contrast']:g}. One peak at one range, so only the air "
    "differs; the far peak sits on the fog's opacity cap on both days")


def measure_extinction_vs_visibility(clear_dir: Path, hazy_dir: Path) -> LookClause:
    """Measured 2026-11-04 on 5.7.4: good 0.26 kept (118.7 to 30.3, the
    gate6_r5 renders); bad 0.93, the same days with beta handed over
    unconverted. The far peak in those r5 renders kept 0.97, which is why it
    is not graded."""
    clear = peak_contrasts(clear_dir)
    hazy = peak_contrasts(hazy_dir)
    if clear is None or hazy is None:
        return LookClause("extinction follows visibility", "FAIL",
                          "a terrain peak is not in frame; nothing to measure",
                          VISIBILITY_MEASUREMENT)
    floor = THRESHOLDS["min_near_contrast"]
    if clear["near"] < floor:
        return LookClause("extinction follows visibility", "FAIL",
                          f"clear-day near contrast {clear['near']:.1f} below {floor:g}; "
                          f"a quotient of noise", VISIBILITY_MEASUREMENT)
    kept = hazy["near"] / clear["near"]
    ok = kept <= THRESHOLDS["max_extinction_ratio"]
    return LookClause(
        "extinction follows visibility", "PASS" if ok else "FAIL",
        f"near peak contrast {clear['near']:.1f} at {VISIBILITY_CLEAR_KM:g} km visibility "
        f"vs {hazy['near']:.1f} at {VISIBILITY_HAZY_KM:g} km (kept {kept:.2f}, threshold "
        f"{THRESHOLDS['max_extinction_ratio']:g}; fog_density applied "
        f"{_look_applied(hazy_dir).get('fog', {}).get('fog_density', 'unrecorded')})",
        VISIBILITY_MEASUREMENT)


WET_MEASUREMENT = (
    "same still with -precip=rain vs -precip=none: changed pixels in the terrain "
    f"band rows {TERRAIN_BAND_ROWS} must exceed the minimum and in the sky band "
    f"rows {SKY_BAND_ROWS} stay under the null maximum; look_applied.precipitation."
    "wetness_parameter must not be 'absent'")


def measure_wet_surface_null(wet_dir: Path, dry_dir: Path) -> LookClause:
    applied = _look_applied(wet_dir).get("precipitation", {})
    parameter = applied.get("wetness_parameter", "unrecorded")
    if parameter in ("absent", "unrecorded"):
        return LookClause(
            "wet surface null test", "FAIL",
            f"look_applied says the wetness parameter is {parameter}: the scalar "
            f"drove nothing, so any change measured would not be wetness",
            WET_MEASUREMENT)
    mask = changed_mask(_last_frame(wet_dir), _last_frame(dry_dir))
    terrain = _band_count(mask, TERRAIN_BAND_ROWS)
    sky = _band_count(mask, SKY_BAND_ROWS)
    ok = (terrain >= LOOK_THRESHOLDS["wet_min_changed_px"]
          and sky <= LOOK_THRESHOLDS["wet_max_sky_changed_px"])
    return LookClause(
        "wet surface null test", "PASS" if ok else "FAIL",
        f"{terrain} terrain-band px change with rain (min "
        f"{LOOK_THRESHOLDS['wet_min_changed_px']}), {sky} sky-band px change "
        f"(null max {LOOK_THRESHOLDS['wet_max_sky_changed_px']}); parameter "
        f"{parameter}, wetness {applied.get('wetness', '?')}",
        WET_MEASUREMENT)


NIGHT_MEASUREMENT = (
    "the doublet at -sun-elev=-12: mean frame luminance above "
    f"{LOOK_THRESHOLDS['night_min_mean_luminance']:g}/255 (frames not black), the "
    f"roll sweep above {THRESHOLDS['min_roll_sweep_deg']:g} deg, and the sky band's "
    f"excursion within {THRESHOLDS['max_sky_excursion']:g}/255 as by day")


def measure_exposure_low_sun(night_dir: Path) -> LookClause:
    manifest = json.loads((night_dir / "render.json").read_text(encoding="utf-8"))
    records = manifest["frame_records"]
    means = [float(luminance(load_rgb(night_dir / record["frame"])).mean())
             for record in records]
    mean = sum(means) / max(1, len(means))
    if mean < LOOK_THRESHOLDS["night_min_mean_luminance"]:
        return LookClause("exposure holds at -12 deg sun", "FAIL",
                          f"frames average {mean:.2f}/255: black frames cannot "
                          f"breathe and cannot hold; the clause is vacuous",
                          NIGHT_MEASUREMENT)
    rolls = [record["roll_deg"] for record in records]
    sweep = max(rolls) - min(rolls)
    if sweep < THRESHOLDS["min_roll_sweep_deg"]:
        return LookClause("exposure holds at -12 deg sun", "FAIL",
                          f"the aircraft only rolled {sweep:.1f} deg; tested "
                          f"without any banking", NIGHT_MEASUREMENT)
    excursion = sky_excursion(night_dir)
    sun = _look_applied(night_dir).get("sun", {}).get("sun_elevation_deg", "unrecorded")
    ok = excursion <= THRESHOLDS["max_sky_excursion"]
    return LookClause(
        "exposure holds at -12 deg sun", "PASS" if ok else "FAIL",
        f"sky band moved {excursion:.2f}/255 over a {sweep:.1f} deg roll sweep "
        f"(threshold {THRESHOLDS['max_sky_excursion']:g}); frames average "
        f"{mean:.1f}/255; sun elevation applied {sun}",
        NIGHT_MEASUREMENT)


ALBEDO_MEASUREMENT = (
    "same still rendered with -labels -passes=albedo under a 60 deg and a 15 deg "
    "sun: the two frame_NNNN_albedo.png (16-bit, read here) must agree within "
    f"{LOOK_THRESHOLDS['albedo_tolerance_counts']} counts on all but "
    f"{LOOK_THRESHOLDS['albedo_max_changed_fraction'] * 100:g} % of pixels, while "
    f"the two beauty frames differ on at least "
    f"{LOOK_THRESHOLDS['albedo_control_min_changed_px']} terrain-band pixels "
    f"(rows {TERRAIN_BAND_ROWS}); each render.json must name the albedo file")


def _last_albedo(frames_dir: Path) -> Optional[Path]:
    """The last frame's albedo file as its render.json record names it
    (never inferred from a file name), or None when the record does not."""
    manifest = json.loads((frames_dir / "render.json").read_text(encoding="utf-8"))
    name = manifest["frame_records"][-1].get("albedo_png")
    return frames_dir / name if isinstance(name, str) and name else None


def measure_albedo_sun_invariance(high_dir: Path, low_dir: Path) -> LookClause:
    """I6: the base colour must not depend on the sun. Two renders that
    differ only in sun elevation: their beauty frames must differ (the
    control -- a sun that changed no pixel proves nothing) and their
    albedo images must be identical within the stated tolerance. NOT RUN
    off Windows; measured on the pixels only, never on the flag."""
    import numpy as np

    high, low = _last_albedo(high_dir), _last_albedo(low_dir)
    if high is None or low is None:
        return LookClause("albedo sun invariance", "FAIL",
                          "a render.json names no albedo_png on its last frame: the "
                          "pass did not run, so there is no base colour to compare",
                          ALBEDO_MEASUREMENT)
    beauty = changed_mask(_last_frame(high_dir), _last_frame(low_dir))
    control = _band_count(beauty, TERRAIN_BAND_ROWS)
    if control < LOOK_THRESHOLDS["albedo_control_min_changed_px"]:
        return LookClause("albedo sun invariance", "FAIL",
                          f"the beauty frames differ on only {control} terrain-band px "
                          f"between the 60 and 15 deg suns (control minimum "
                          f"{LOOK_THRESHOLDS['albedo_control_min_changed_px']}): the sun "
                          f"switch moved nothing, so an unchanged albedo is vacuous",
                          ALBEDO_MEASUREMENT)
    a, b = load_rgb(high), load_rgb(low)
    if a.shape != b.shape:
        return LookClause("albedo sun invariance", "FAIL",
                          f"albedo images of different shapes {a.shape} / {b.shape}",
                          ALBEDO_MEASUREMENT)
    changed = np.any(np.abs(a - b) > LOOK_THRESHOLDS["albedo_tolerance_counts"], axis=0)
    fraction = float(changed.mean())
    ok = fraction <= LOOK_THRESHOLDS["albedo_max_changed_fraction"]
    return LookClause(
        "albedo sun invariance", "PASS" if ok else "FAIL",
        f"albedo differs on {fraction * 100:.3f} % of pixels between the two suns "
        f"(max {LOOK_THRESHOLDS['albedo_max_changed_fraction'] * 100:g} %, tolerance "
        f"{LOOK_THRESHOLDS['albedo_tolerance_counts']} counts of 65535); beauty "
        f"changed on {control} terrain-band px (control min "
        f"{LOOK_THRESHOLDS['albedo_control_min_changed_px']})",
        ALBEDO_MEASUREMENT)


def look_clauses(out: Path) -> List[LookClause]:
    """Every Phase 2 look clause: measured when its renders exist under
    ``out``, else NOT RUN with the measurement stated."""
    def rendered(*names: str) -> bool:
        return all((out / name / "render.json").is_file() for name in names)

    clauses: List[LookClause] = []
    if rendered("cloud_above", "cloud_below", "cloud_control"):
        clauses.append(measure_cloud_base(out / "cloud_above", out / "cloud_below",
                                          out / "cloud_control"))
    else:
        clauses.append(LookClause("cloud base bracket", "NOT RUN",
                                  "renders cloud_above / cloud_below / cloud_control "
                                  "absent (no engine here, or --look not given)",
                                  CLOUD_MEASUREMENT))
    if rendered("visibility_clear", "visibility_hazy"):
        clauses.append(measure_extinction_vs_visibility(out / "visibility_clear",
                                                        out / "visibility_hazy"))
    else:
        clauses.append(LookClause("extinction follows visibility", "NOT RUN",
                                  "renders visibility_clear / visibility_hazy absent",
                                  VISIBILITY_MEASUREMENT))
    if rendered("wet", "wet_control"):
        clauses.append(measure_wet_surface_null(out / "wet", out / "wet_control"))
    else:
        clauses.append(LookClause("wet surface null test", "NOT RUN",
                                  "renders wet / wet_control absent", WET_MEASUREMENT))
    if rendered("night"):
        clauses.append(measure_exposure_low_sun(out / "night"))
    else:
        clauses.append(LookClause("exposure holds at -12 deg sun", "NOT RUN",
                                  "render night absent", NIGHT_MEASUREMENT))
    if rendered("albedo_sun_high", "albedo_sun_low"):
        clauses.append(measure_albedo_sun_invariance(out / "albedo_sun_high",
                                                     out / "albedo_sun_low"))
    else:
        clauses.append(LookClause("albedo sun invariance", "NOT RUN",
                                  "renders albedo_sun_high / albedo_sun_low absent "
                                  "(no engine here, or --look not given)",
                                  ALBEDO_MEASUREMENT))
    return clauses


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


# -- B4 probe: the numbers a re-derivation reads off a frame ---------------
#
# Decision 13 pins the engine at 5.7.4 (changelist 51494982); the exposure
# biases and the vertex palette on record were measured on 5.5 (history,
# ue/Config/DefaultEngine.ini header). "Recalibrate by probe render, not
# theory" (NEXT.md gotcha 6): the probe reads band and patch means off a
# rendered frame and writes them with the engine pin, so a re-derivation
# is a file a reader can check, not a number typed from memory.

#: Decision 15 (B4-1): "equals the reference" is a sky-band mean luminance
#: within 4/255 and a terrain-class patch mean RGB within 4/255 -- half
#: the Gate 6 sky-excursion threshold.
PROBE_TOLERANCE = 4.0
#: The ONE stated mid-grey target (decision 15, B4-1) for the noon frame's
#: terrain band: an 18 % reflectance grey card encodes to sRGB 118/255.
#: A stated target, written beside the number in docs/VALIDITY.md 2.13;
#: not a measurement, and not a 5.5 frame.
MID_GREY_TARGET = 118.0
#: The sweeps of B4 step 5, per look: the Gate 6 look (commandlet default
#: 11.0), the noon look (DEFAULT_LOOK 9.5) and the dawn look (10.5).
PROBE_SWEEPS = {
    "gate6": (10.0, 10.5, 11.0, 11.5, 12.0),
    "noon": (8.5, 9.0, 9.5, 10.0, 10.5),
    "dawn": (9.5, 10.0, 10.5, 11.0, 11.5),
}
#: Where --probe-sweep writes: <root>/<look>/<bias>/probe.json. The note
#: said <root>/<bias>/; the biases of the three sweeps overlap (10.5 sits
#: in all three), so the look is one directory level above the bias.
PROBE_SWEEP_ROOT = "runs/b4_probe"
#: The bands every probe reads from the terrain shot: pure sky (top of
#: frame), the terrain band (the mountains: rock / scrub / snow classes)
#: and the plain under the flight (the valley class). Each frame record's
#: visible landmarks (the peaks) are added as patches by name.
PROBE_BANDS = {
    "sky": {"rows": SKY_BAND_ROWS},
    "terrain": {"rows": TERRAIN_BAND_ROWS},
    "ground": {"rows": CLOUD_GROUND_ROWS},
}
#: The doublet window sky_excursion measures over (same bounds as there).
PROBE_WINDOW_S = (3.0, 20.0)

PROBE_MESSAGES = {
    "probe_frame_missing":
        "REFUSED gate6.probe_frame_missing: frame {frame} does not exist; a "
        "probe reads pixels, it does not invent them",
    "probe_band_shape":
        "REFUSED gate6.probe_band_shape: band {band} is {spec!r}; a band is "
        "{{'rows': (y0, y1)}} or {{'px': x, 'py': y[, 'half': n]}}",
    "probe_manifest_missing":
        "REFUSED gate6.probe_manifest_missing: {run} has no render.json; "
        "nothing was rendered there, so nothing can be probed",
    "probe_no_frames":
        "REFUSED gate6.probe_no_frames: {run}/render.json lists no frames",
    "rederive_no_probes":
        "REFUSED gate6.rederive_no_probes: no <bias>/probe.json under {root}; "
        "run --probe-sweep first",
    "rederive_out_of_tolerance":
        "REFUSED gate6.rederive_out_of_tolerance: no bias in {biases} puts the "
        "{band} band within {tolerance:g}/255 of the stated {target:g}/255 with "
        "the sky excursion under {excursion:g}/255 (nearest: bias {nearest:g} at "
        "{value:.2f}/255); decision 15 re-tunes only against a measurement, so "
        "widen the sweep, not the tolerance",
}


class ProbeRefusal(ValueError):
    """A probe or re-derivation refusal, by rule name (PROBE_MESSAGES)."""


def refuse(rule: str, **fields) -> None:
    raise ProbeRefusal(PROBE_MESSAGES[rule].format(**fields))


def engine_string() -> str:
    """The pinned engine, from toolchain.json via core.util.platform (B2),
    so a probe file names the same 5.7.4 / changelist as decision 13."""
    return (f"{UE_ENGINE_VERSION}.{UE_ENGINE_PATCH} "
            f"(changelist {TOOLCHAIN['engine']['changelist']})")


def probe_frame(frame: Path, bands: dict) -> dict:
    """Mean luminance and mean RGB of every band of one frame.

    A band is ``{"rows": (y0, y1)}`` (full-width row band) or
    ``{"px": x, "py": y, "half": n}`` (a patch, as patch_mean clamps it).
    Refuses by name when the frame is absent.
    """
    frame = Path(frame)
    if not frame.is_file():
        refuse("probe_frame_missing", frame=frame)
    rgb = load_rgb(frame)
    lum = luminance(rgb)
    result = {"frame": frame.name, "width": int(rgb.shape[2]),
              "height": int(rgb.shape[1]), "bands": {}}
    for name, spec in bands.items():
        if "rows" in spec:
            height = int(rgb.shape[1])
            y0 = max(0, min(int(spec["rows"][0]), height))
            y1 = max(0, min(int(spec["rows"][1]), height))
            if y1 <= y0:
                # A band below the bottom of a smaller frame (the 540-row
                # ground band on a test frame): recorded as outside, never
                # as a NaN that reads like a number.
                result["bands"][name] = {"mean_luminance": None, "mean_rgb": None,
                                         "outside_frame": True}
                continue
            mean_rgb = [float(rgb[channel, y0:y1, :].mean()) for channel in range(3)]
            mean_lum = float(lum[y0:y1, :].mean())
        elif "px" in spec and "py" in spec:
            half = int(spec.get("half", 6))
            mean_rgb = [patch_mean(rgb[channel], spec["px"], spec["py"], half)
                        for channel in range(3)]
            mean_lum = patch_mean(lum, spec["px"], spec["py"], half)
        else:
            refuse("probe_band_shape", band=name, spec=spec)
        result["bands"][name] = {"mean_luminance": round(mean_lum, 3),
                                 "mean_rgb": [round(v, 3) for v in mean_rgb]}
    return result


def probe_bias(manifest: dict) -> Optional[float]:
    """The exposure bias a render recorded: render_settings.exposure_bias
    (Look lane) or the scene's "manual, AutoExposureBias N" string."""
    settings = manifest.get("render_settings") or {}
    if isinstance(settings.get("exposure_bias"), (int, float)):
        return float(settings["exposure_bias"])
    found = re.search(r"AutoExposureBias\s+(-?\d+(?:\.\d+)?)",
                      str(manifest.get("scene", {}).get("exposure", "")))
    return float(found.group(1)) if found else None


def probe_run(frames_dir: Path, bias: Optional[float] = None) -> dict:
    """Probe every frame of one render: the band means per frame, and the
    run's summary (bias, sky/terrain/ground means over the doublet window,
    sky excursion). ``bias`` overrides the manifest's record (a sweep
    names the bias it asked for)."""
    frames_dir = Path(frames_dir)
    manifest_path = frames_dir / "render.json"
    if not manifest_path.is_file():
        refuse("probe_manifest_missing", run=frames_dir)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest.get("frame_records") or []
    if not records:
        refuse("probe_no_frames", run=frames_dir)
    rows = []
    for record in records:
        bands = dict(PROBE_BANDS)
        for name, mark in (record.get("landmarks") or {}).items():
            if mark.get("visible"):
                bands[name] = {"px": mark["px"], "py": mark["py"]}
        row = probe_frame(frames_dir / record["frame"], bands)
        row["t"] = record.get("t")
        row["roll_deg"] = record.get("roll_deg")
        rows.append(row)
    window = [row for row in rows
              if row["t"] is not None and PROBE_WINDOW_S[0] <= row["t"] <= PROBE_WINDOW_S[1]]
    sample = window or rows

    def band_mean(name: str) -> Optional[float]:
        values = [row["bands"][name]["mean_luminance"] for row in sample
                  if row["bands"][name]["mean_luminance"] is not None]
        return round(sum(values) / len(values), 3) if values else None

    return {
        "run": frames_dir.name,
        "bias": float(bias) if bias is not None else probe_bias(manifest),
        "exposure": manifest.get("scene", {}).get("exposure", "unrecorded"),
        "frames": len(rows),
        "window_frames": len(window),
        "sky_mean": band_mean("sky"),
        "terrain_mean": band_mean("terrain"),
        "ground_mean": band_mean("ground"),
        "sky_excursion": round(sky_excursion(frames_dir), 3) if window else None,
        "rows": rows,
    }


def probe_tree(out: Path, bias: Optional[float] = None) -> List[dict]:
    """Every render under ``out`` that has a render.json, probed, in name
    order -- the --skip-render path over an existing runs/gate6/ tree."""
    return [probe_run(path, bias) for path in sorted(Path(out).iterdir())
            if path.is_dir() and (path / "render.json").is_file()]


def write_probe(out: Path, rows: list, engine: str) -> Path:
    """Write the probe file: the engine pin, the tolerances of decision 15
    and the stated mid-grey target beside every measured row."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "engine": engine,
        "tolerance": PROBE_TOLERANCE,
        "mid_grey_target": MID_GREY_TARGET,
        "sky_excursion_threshold": THRESHOLDS["max_sky_excursion"],
        "written_by": "experiments/gate6_visual.py",
        "runs": rows,
    }, indent=2), encoding="utf-8")
    return out


def probe_look_flags(look: str) -> List[str]:
    """The commandlet flags of a sweep's look: none for the Gate 6 scene
    (its defaults are what Gate 6 measured), the showcase matrix's sun and
    clear air for noon and dawn (imported, not copied, so they cannot
    drift from DEFAULT_LOOK, which a test pins to that table)."""
    if look == "gate6":
        return []
    from experiments.showcase_matrix import TIME_OF_DAY, VISIBILITY
    tod = TIME_OF_DAY[look]
    return [f"-sun-elev={tod['sun_elev']:g}", f"-sun-azim={tod['sun_azim']:g}",
            f"-fog-density={VISIBILITY['clear']:g}"]


def parse_biases(text: str) -> List[float]:
    return [float(item) for item in text.split(",") if item.strip()]


def rederive_bias(probes: List[dict], target: float = MID_GREY_TARGET,
                  tolerance: float = PROBE_TOLERANCE, band: str = "terrain",
                  max_excursion: float = THRESHOLDS["max_sky_excursion"]) -> dict:
    """Pick the bias whose ``band`` mean is nearest the stated target and
    within the tolerance, among the probes whose sky excursion (when
    measured) meets Gate 6's own threshold. Refuses by name when none
    qualifies: a re-tune without a measurement in tolerance has no cause."""
    key = f"{band}_mean"
    ranked = sorted(probes, key=lambda probe: (abs(probe[key] - target), probe["bias"]))
    candidates = [probe for probe in ranked
                  if abs(probe[key] - target) <= tolerance
                  and (probe.get("sky_excursion") is None
                       or probe["sky_excursion"] <= max_excursion)]
    if not candidates:
        nearest = ranked[0]
        refuse("rederive_out_of_tolerance",
               biases=[probe["bias"] for probe in sorted(probes, key=lambda p: p["bias"])],
               band=band, tolerance=tolerance, target=target,
               excursion=max_excursion, nearest=nearest["bias"], value=nearest[key])
    chosen = candidates[0]
    return {
        "engine": engine_string(),
        "band": band, "target": target, "tolerance": tolerance,
        "max_sky_excursion": max_excursion,
        "chosen_bias": chosen["bias"], "value": chosen[key],
        "sky_excursion": chosen.get("sky_excursion"),
        "candidates": [{"bias": p["bias"], key: p[key], "sky_excursion": p.get("sky_excursion")}
                       for p in sorted(probes, key=lambda p: p["bias"])],
    }


def rederive_from_files(look_dir: Path) -> dict:
    """The re-derivation path: read every <bias>/probe.json a sweep wrote
    under ``look_dir`` (the first run of each file is the sweep's render),
    choose by rederive_bias, write <look_dir>/rederived.json."""
    look_dir = Path(look_dir)
    files = sorted(look_dir.glob("*/probe.json"))
    if not files:
        refuse("rederive_no_probes", root=look_dir)
    probes = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        run = dict(data["runs"][0])
        run.pop("rows", None)
        run["engine"] = data["engine"]
        run["probe"] = str(path)
        probes.append(run)
    result = rederive_bias(probes)
    result["probes"] = [probe["probe"] for probe in probes]
    result["measured_on"] = sorted({probe["engine"] for probe in probes})
    (look_dir / "rederived.json").write_text(json.dumps(result, indent=2),
                                             encoding="utf-8")
    return result


def emit_probe(out: Path, probe_out: Path) -> Path:
    rows = probe_tree(out)
    path = write_probe(Path(probe_out).resolve(), rows, engine_string())
    print(f"\n{RULE}\nprobe ({engine_string()})\n{RULE}")
    for row in rows:
        bias = "unrecorded" if row["bias"] is None else f"{row['bias']:g}"
        excursion = ("--" if row["sky_excursion"] is None
                     else f"{row['sky_excursion']:.2f}")
        means = "  ".join(
            "{} {:>7s}".format(band, "--" if row[band + "_mean"] is None
                               else "{:.2f}".format(row[band + "_mean"]))
            for band in ("sky", "terrain", "ground"))
        print(f"  {row['run']:18s} bias {bias:>10s}  {means}  "
              f"excursion {excursion:>6s}  ({row['frames']} frames)")
    print(f"  wrote {path}")
    return path


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
    ap.add_argument("--substitute-baseline", default=None,
                    help="a PNG or folder standing in for the lost old footage "
                         "(decision 25); every line then says it is a substitute")
    ap.add_argument("--skip-render", action="store_true",
                    help="measure existing renders without re-rendering")
    ap.add_argument("--look", action="store_true",
                    help="also render the Phase 2 look controls (LOOK_RUNS); "
                         "without them the look clauses report NOT RUN")
    ap.add_argument("--quality", choices=("measure", "beauty"),
                    default="measure",
                    help="renderer configuration (visual plan V0). beauty "
                         "re-measures the same four clauses with Lumen/TSR/"
                         "VSM on, at the SAME 960x540 the thresholds were "
                         "set at, so a pass means the clauses survive the "
                         "renderer change -- not a new resolution's luck")
    ap.add_argument("--probe-out", default=None, metavar="PATH",
                    help="B4: write a probe.json of every render under --out "
                         "(band means per frame, bias, engine pin); with "
                         "--skip-render it reads an existing tree before "
                         "anything else, so a tree missing the still runs "
                         "still yields its probe")
    ap.add_argument("--probe-sweep", choices=tuple(PROBE_SWEEPS), default=None,
                    help="B4 step 5: render the Gate 6 scene once per bias "
                         "of this look's sweep (--probe-biases overrides the "
                         "list) and write <probe-root>/<look>/<bias>/probe.json; "
                         "nothing else runs")
    ap.add_argument("--probe-biases", default=None, metavar="B1,B2,...",
                    help="the biases --probe-sweep renders (default: the "
                         "look's PROBE_SWEEPS entry)")
    ap.add_argument("--probe-root", default=PROBE_SWEEP_ROOT,
                    help="where --probe-sweep and --rederive read and write")
    ap.add_argument("--rederive", choices=tuple(PROBE_SWEEPS), default=None,
                    metavar="LOOK",
                    help="B4 step 6: read <probe-root>/<look>/*/probe.json, "
                         "choose the bias nearest the stated mid-grey target "
                         f"within {PROBE_TOLERANCE:g}/255 (decision 15), write "
                         "rederived.json beside them; refuses by name when "
                         "no bias is within tolerance")
    ap.add_argument("--aliasing-baseline", default=None, metavar="DIR|JSON",
                    help="visual plan V0: compare the reported edge-aliasing "
                         "number against another tree's aliasing.json "
                         "(reported, never a gate)")
    args = ap.parse_args(argv)
    if args.rederive:
        try:
            result = rederive_from_files(Path(args.probe_root) / args.rederive)
        except ProbeRefusal as refusal:
            print(refusal)
            return 1
        print(f"\n{RULE}\nre-derived {args.rederive} bias on {result['engine']}\n{RULE}")
        for row in result["candidates"]:
            print(f"  bias {row['bias']:5g}  {result['band']} {row[result['band'] + '_mean']:7.2f}  "
                  f"excursion {row['sky_excursion']}")
        print(f"  chosen {result['chosen_bias']:g}: {result['band']} band "
              f"{result['value']:.2f}/255 against the stated {result['target']:g}/255 "
              f"(tolerance {result['tolerance']:g}); measured on "
              f"{', '.join(result['measured_on'])}")
        return 0
    if args.quality == "beauty" and args.out == "runs/gate6":
        args.out = "runs/gate6_beauty"
    quality_flags = ([] if args.quality == "measure" else
                     [f"-quality={args.quality}", "-width=960", "-height=540"])
    # Absolute, because these paths are handed to the editor, whose working
    # directory is its own binary's -- a relative card path resolves to
    # nothing there and the render dies before its first frame.
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    root = Path(__file__).resolve().parents[1]
    editor = ue_editor_path()
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
        # Range extinction: the far peak, with the near copy that stands in
        # front of it left out; and the control pair with no aerial
        # perspective, which must miss the threshold.
        "still_far": ("terrain", ["-seconds=2", "-HideNearTerrain"]),
        "extinction_control": ("terrain", ["-seconds=2", "-NoAerialPerspective"]),
        "extinction_control_far": ("terrain", ["-seconds=2", "-HideNearTerrain",
                                               "-NoAerialPerspective"]),
        "shadow": ("shadow", ["-seconds=2"]),
        "shadow_hidden": ("shadow", ["-seconds=2", "-HideAircraft"]),
        # The exposure clause's negative control (see measure_exposure_control).
        "full_auto": ("terrain", ["-AutoExposure", f"-GroundDarkAt={EXPOSURE_STEP_AT_S:g}"]),
        "full_step": ("terrain", [f"-GroundDarkAt={EXPOSURE_STEP_AT_S:g}"]),
    }
    if args.probe_sweep:
        biases = (parse_biases(args.probe_biases) if args.probe_biases
                  else list(PROBE_SWEEPS[args.probe_sweep]))
        look_dir = Path(args.probe_root).resolve() / args.probe_sweep
        print(f"\n{RULE}\n2. probe sweep ({args.probe_sweep}: {biases})\n{RULE}")
        for bias in biases:
            frames = look_dir / f"{bias:g}"
            if args.skip_render and (frames / "render.json").is_file():
                print(f"  [kept] bias {bias:g}")
            elif editor is None or not editor.is_file():
                print(f"  no editor at {editor}, and no render at {frames}"
                      f"\n\n  PROBE SWEEP: BLOCKED")
                return 2
            else:
                ok = render(editor, project, card, frames, terrain, "terrain",
                            [*probe_look_flags(args.probe_sweep),
                             f"-exposure-bias={bias:g}", *quality_flags])
                print(f"  [{'ok  ' if ok else 'FAIL'}] bias {bias:g}")
                if not ok:
                    print("\n  PROBE SWEEP: BLOCKED -- a render did not complete.")
                    return 2
            path = write_probe(frames / "probe.json", [probe_run(frames, bias)],
                               engine_string())
            print(f"  wrote {path}")
        return 0

    if args.probe_out and args.skip_render:
        emit_probe(out, args.probe_out)

    print(f"\n{RULE}\n2. renders\n{RULE}")
    for name, (shot, extra) in runs.items():
        frames = out / name
        if args.skip_render and (frames / "render.json").is_file():
            print(f"  [kept] {name}")
            continue
        if editor is None or not editor.is_file():
            print(f"  no editor at {editor}\n\n  GATE 6: BLOCKED")
            return 2
        ok = render(editor, project, card, frames, terrain, shot,
                    [*extra, *quality_flags])
        print(f"  [{'ok  ' if ok else 'FAIL'}] {name} ({shot} shot"
              f"{' ' + ' '.join(extra) if extra else ''})")
        if not ok:
            print("\n  GATE 6: BLOCKED -- a render did not complete.")
            return 2

    if args.look:
        for name, (shot, extra) in LOOK_RUNS.items():
            frames = out / name
            if args.skip_render and (frames / "render.json").is_file():
                print(f"  [kept] {name}")
                continue
            if editor is None or not editor.is_file():
                print(f"  no editor at {editor}\n\n  GATE 6: BLOCKED")
                return 2
            ok = render(editor, project, card, frames, terrain, shot, extra)
            print(f"  [{'ok  ' if ok else 'FAIL'}] {name} ({shot} shot "
                  f"{' '.join(extra)})")
            if not ok:
                print("\n  GATE 6: BLOCKED -- a look control render did not complete.")
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

    if args.probe_out and not args.skip_render:
        emit_probe(out, args.probe_out)

    print(f"\n{RULE}\n3. the four measurable clauses\n{RULE}")
    still = sorted((out / "still").glob("frame_*.png"))[-1]
    still_ns = sorted((out / "still_noshadow").glob("frame_*.png"))[-1]
    shadow = sorted((out / "shadow").glob("frame_*.png"))[-1]
    shadow_hidden = sorted((out / "shadow_hidden").glob("frame_*.png"))[-1]
    checks = [
        measure_extinction(out / "still", out / "still_far",
                           out / "extinction_control", out / "extinction_control_far"),
        measure_valley_shadow(still, still_ns),
        measure_aircraft_shadow(shadow, shadow_hidden),
        measure_exposure(out / "full"),
        measure_exposure_control(out / "full_auto", out / "full_step"),
    ]
    for check in checks:
        print(check.render())

    # Visual plan V0 "Measure": reported beside the clauses, never one.
    # A number that is never a gate must never change the gate's outcome:
    # an error computing it is reported as [info] and the run goes on.
    try:
        aliasing = report_edge_aliasing(
            out, Path(args.aliasing_baseline) if args.aliasing_baseline else None)
        if aliasing is not None:
            print(edge_aliasing_line(aliasing))
    except Exception as error:  # noqa: BLE001 -- reported, never a gate
        print(f"  [info] edge aliasing (reported, not a gate) not computed: {error}")

    print(f"\n{RULE}\n4. the side-by-side\n{RULE}")
    substitute = Path(args.substitute_baseline) if args.substitute_baseline else None
    baseline_words = ("a SUBSTITUTE baseline, not the old footage (decision 25)"
                      if substitute else "the old footage")
    if substitute and substitute.is_file():
        old_frames = [substitute]
    else:
        old_frames = sorted((substitute or Path(args.old_footage)).glob("*.png"))
    side_by_side = None
    if old_frames:
        old = old_frames[len(old_frames) // 2]
        new = sorted((out / "full").glob("frame_*.png"))[-1]
        side_by_side = compose_side_by_side(old, new, out / "side_by_side.png")
        print(f"  {'SUBSTITUTE ' if substitute else 'old footage'} {old}")
        print(f"  this build  {new}")
        print(f"  wrote       {side_by_side}")
        print("  Likeness is the reader's judgment to make, not this "
              "harness's. What the")
        print("  measurements above establish is that the four properties "
              "the brief named")
        print("  as missing from the old footage are present in the new.")
        if substitute:
            print("  The left panel is an earlier render of THIS project, not the "
                  "old footage,")
            print("  which is lost: it shows change since then, not likeness to "
                  "the old build.")
    else:
        print(f"  [----] side-by-side NOT RUN: no old footage under {args.old_footage}")
        print("         measurement: this harness composes old beside new for a "
              "person to judge;")
        print("         the footage is the owner's, and nothing stands in for it.")

    print(f"\n{RULE}\n5. Phase 2 look clauses (NOT RUN without their control renders)\n{RULE}")
    looks = look_clauses(out)
    for clause in looks:
        print(clause.render())

    measured = (all(check.ok for check in checks)
                and all(clause.ok for clause in looks if clause.ran))
    everything = measured and side_by_side is not None
    print(f"\n{RULE}\nGATE 6\n{RULE}")
    for check in checks:
        print(f"  [{'PASS' if check.ok else 'FAIL'}] {check.name}")
    for clause in looks:
        print(f"  [{clause.status}] {clause.name}")
    print(f"  [{'PASS' if side_by_side else 'NOT RUN'}] side-by-side produced "
          f"against {baseline_words}")
    if everything:
        print("\n  GATE 6: PASS -- four clauses measured from the pixels, the "
              "side-by-side")
        print("  produced for human judgment. Scope: box airframe, default "
              "terrain material,")
        print("  no foliage -- docs/VALIDITY.md lists the Phase 6 work that "
              "remains.")
        if substitute:
            print("  The side-by-side used a substitute baseline (decision 25); "
                  "the old footage is lost.")
        return 0
    if measured:
        # A clause that did not run is not a clause that passed.
        print("\n  GATE 6: INCOMPLETE -- every measured clause passes; the "
              "side-by-side is NOT RUN")
        print("  until the owner's footage is present, so this is not a pass.")
        return 3
    print("\n  GATE 6: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
