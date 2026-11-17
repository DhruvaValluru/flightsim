"""Poly Haven CC0 HDRI skies for the beauty render (round 148, 2026-11-16).

BEAUTY ONLY, behind ``-look-hdri=auto|light|off`` (FLIGHTSIM_RENDER_SWITCHES or
the command line; ``auto`` by default). The host is FlightSimHdriSky.cpp
(``FFlightSimHdriSky``); this module is its Python twin: every constant and law
below is pinned to the C++ pure block (``FLIGHTSIM-HDRI-PURE``) by
tests/test_hdri_sky.py, which compiles that block and compares it number for
number.

Why: the Windows laptop renders on an Intel iGPU (D3D11 SM5), so there is no
Lumen and the shade of every surface is the sky light alone. The captured sky
(the SkyAtmosphere plus the volumetric deck) gives that fill almost no
direction: the shadow sides read flat grey. A photographed sky has the real
structure (a bright, warm side toward the sun, a deep blue zenith, a brighter
horizon band, cloud texture in an overcast), and the sky light convolves it
into a directional fill.

1. The sky light (``light`` and ``auto``): the commandlet captures the scene's
   sky exactly as today, reads its upward irradiance back (the sky light's
   own SH, which is what the engine shades with), then makes the matched
   HDRI the sky light's SPECIFIED CUBEMAP, rotated so the photograph's sun
   azimuth is the directional light's, at an intensity that gives the same
   upward irradiance (``hdri_intensity``). The exposure path therefore sees
   the same fill energy; only its direction and colour change. The lower
   hemisphere (hero lighting's ground bounce, absolute units) is divided by
   the intensity change so the drawn ground bounce is kept.
2. The backdrop (``auto`` only): a camera below ``BACKDROP_FULL_AGL_M`` sees
   the photograph above the horizon on a translucent dome centred on it,
   faded into the SkyAtmosphere / fog over ``BACKDROP_HORIZON_LOW_DEG`` ..
   ``BACKDROP_HORIZON_HIGH_DEG`` and out entirely by ``BACKDROP_NONE_AGL_M``
   (the high cruise scenes #9, #13, #15 never draw it). Clouds and fog draw
   over it (the material applies cloud fogging and height fog).
3. ``off``: nothing is built, nothing is switched: today's frame exactly.

The files are committed: assets/hdri/<name>_2k.hdr (the Poly Haven
downloads, sha256-pinned below) and assets/hdri/prepared/<name>_skylight_1k.hdr
(``prepare``: the sun disk clamped, the upper hemisphere's mean luminance
normalised to 1, box-halved to 1K; the sidecar JSON beside it). The editor
script (scripts/ue_create_materials.py ``create_look_hdris``) imports both as
TextureCubes under /Game/FlightSim/Sky.

Every look value here is UNCALIBRATED and the whole look is UNMEASURED until
the Windows laptop renders it.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from . import sky_hdri

REPO = Path(__file__).resolve().parents[2]
HDRI_DIR = REPO / "assets" / "hdri"
PREPARED_DIR = HDRI_DIR / "prepared"

#: The switch.
LOOK_HDRI_MODES = ("auto", "light", "off")
LOOK_HDRI_DEFAULT = "auto"

#: World presets, in FlightSimWorldPure's order (clear, hazy, overcast, rain, storm).
PRESETS = ("clear", "hazy", "overcast", "rain", "storm")

#: The slots and the HDRI each draws (index order is the C++ enum's).
SLOTS = ("clear", "golden", "overcast", "storm")
SLOT_NONE = -1

#: The pins: Poly Haven CC0 "pure sky" HDRIs, 2K RADIANCE as served on
#: 2026-11-16 (dl.polyhaven.org). sun_* are measured by ``prepare`` (the
#: brightest pixel; for the overcast pair, the brightest patch of cloud).
HDRIS: Dict[str, Dict[str, Any]] = {
    "qwantani_noon_puresky": {
        "slot": "clear",
        "title": "Qwantani Noon (Pure Sky)",
        "source": "https://polyhaven.com/a/qwantani_noon_puresky",
        "url": "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/2k/qwantani_noon_puresky_2k.hdr",
        "sha256": "d070d48c8e802c92027b0f7b1965b5bd820b0d25afca225503abfec67e00ad07",
        "bytes": 4184949,
        "authors": {"Greg Zaal": "Photography", "Jarod Guest": "Processing"},
    },
    "syferfontein_6d_clear_puresky": {
        "slot": "golden",
        "title": "Syferfontein 6d Clear (Pure Sky)",
        "source": "https://polyhaven.com/a/syferfontein_6d_clear_puresky",
        "url": "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/2k/syferfontein_6d_clear_puresky_2k.hdr",
        "sha256": "3efca43f875db8d790001dad1677bd13c0968effc6d3193bdd2ee12e226e7eaa",
        "bytes": 4650421,
        "authors": {"Greg Zaal": "Original", "Jarod Guest": "Sky Edits"},
    },
    "kloofendal_overcast_puresky": {
        "slot": "overcast",
        "title": "Kloofendal Overcast (Pure Sky)",
        "source": "https://polyhaven.com/a/kloofendal_overcast_puresky",
        "url": "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/2k/kloofendal_overcast_puresky_2k.hdr",
        "sha256": "312b1b04b7f10057a4f1418abc59d1166c8933cc93fc72051502edaf8d6b2fcd",
        "bytes": 4335717,
        "authors": {"Greg Zaal": "All"},
    },
    "overcast_soil_puresky": {
        "slot": "storm",
        "title": "Overcast Soil (Pure Sky)",
        "source": "https://polyhaven.com/a/overcast_soil_puresky",
        "url": "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/2k/overcast_soil_puresky_2k.hdr",
        "sha256": "5414e1ac0c35e451d28595b2a2cba05e2ca301fdeb755b0a469408443093dafc",
        "bytes": 4568000,
        "authors": {"Sergej Majboroda": "Original", "Jarod Guest": "Sky Edits"},
    },
}
SLOT_HDRI = {row["slot"]: name for name, row in HDRIS.items()}
LICENCE = "CC0-1.0"

#: Asset names under /Game/FlightSim/Sky.
ASSET_DIR = "/Game/FlightSim/Sky"
LIGHT_ASSET_PREFIX = "T_HdriLight_"
BACKDROP_ASSET_PREFIX = "T_HdriBackdrop_"
BACKDROP_MATERIAL = "/Game/FlightSim/M_FlightSimHdriBackdrop.M_FlightSimHdriBackdrop"

#: The sun clamp of the prepared (sky-light) copy, x the upper hemisphere's
#: median luminance (sky_hdri.clamp_sun). UNCALIBRATED.
CLAMP_FACTOR = 32.0

#: Slot choice. A clear or hazy preset with the sun below GOLDEN_MAX_SUN_DEG is
#: the golden-hour sky; below NIGHT_SUN_DEG no photograph is a match (none is a
#: night sky) and the captured sky stays.
GOLDEN_MAX_SUN_DEG = 15.0
NIGHT_SUN_DEG = -4.0

#: The sky light's upward irradiance as a share of the captured sky's, per slot
#: (1: the same fill energy as today; only its direction and colour change).
#: UNCALIBRATED.
SLOT_FILL_GAIN = (1.0, 1.0, 1.0, 1.0)
#: The intensity ratio is refused outside this band (a capture that read back
#: nothing, or a nonsense ratio): the captured sky stays and the record says so.
MIN_RATIO = 1e-4
MAX_RATIO = 1e6

#: The backdrop: full below BACKDROP_FULL_AGL_M, none above BACKDROP_NONE_AGL_M
#: (smoothstep between), faded in over the horizon band, at most BACKDROP_OPACITY.
BACKDROP_FULL_AGL_M = 600.0
BACKDROP_NONE_AGL_M = 1000.0
BACKDROP_HORIZON_LOW_DEG = 1.0
BACKDROP_HORIZON_HIGH_DEG = 12.0
BACKDROP_OPACITY = 1.0
#: The dome's radius: a photographed sky's cloud distance, so the engine's height
#: fog and aerial perspective veil it as they would those clouds (a 150 km sphere
#: was fogged into the bare atmosphere colour on the Mac look-dev); it draws over
#: SKY pixels only (opaque scene depth beyond BACKDROP_SKY_DEPTH_CM), so nothing
#: beyond it is covered. Its sort priority puts it behind every other translucent
#: (the cirrus is -101).
BACKDROP_RADIUS_KM = 8.0
BACKDROP_SKY_DEPTH_CM = 1.0e8
BACKDROP_SORT_PRIORITY = -110
#: The backdrop's luminance relative to the sky light's matched radiance. UNCALIBRATED.
BACKDROP_GAIN = 1.0
#: Around the scene's sun the sphere opens (clear and golden slots only: their
#: photograph has a sun), SUN_HOLE_DEG plus the photograph's sun offset in
#: elevation, so the SkyAtmosphere's own disk shows and no second sun is drawn.
SUN_HOLE_DEG = 3.0


def mode_from(word: Optional[str]) -> str:
    """The switch's word (empty: the default); anything else is refused by name."""
    word = (word or "").strip() or LOOK_HDRI_DEFAULT
    if word not in LOOK_HDRI_MODES:
        raise ValueError(f"hdri_sky.switch: -look-hdri={word} is not one of {', '.join(LOOK_HDRI_MODES)}")
    return word


def slot_for(preset: str, sun_elevation_deg: float) -> int:
    """The slot index for a world preset and the sun's elevation; SLOT_NONE at night."""
    if preset not in PRESETS:
        raise ValueError(f"hdri_sky.preset: {preset!r}")
    if sun_elevation_deg < NIGHT_SUN_DEG:
        return SLOT_NONE
    if preset in ("rain", "storm"):
        return SLOTS.index("storm")
    if preset == "overcast":
        return SLOTS.index("overcast")
    return SLOTS.index("golden") if sun_elevation_deg < GOLDEN_MAX_SUN_DEG else SLOTS.index("clear")


def wrap_deg(value: float) -> float:
    """[0, 360)."""
    out = math.fmod(value, 360.0)
    if out < 0.0:
        out += 360.0
    return 0.0 if out >= 360.0 else out


def cubemap_yaw_deg(hdri_sun_longitude_deg: float, sun_x: float, sun_y: float) -> float:
    """USkyLightComponent::SourceCubemapAngle that puts the photograph's sun at the
    world direction (sun_x, sun_y) (toward the sun, UE world). A long-lat import
    maps image longitude L to the cube direction at xy angle L - 90 deg (the image
    centre is -Y; TextureCompressorModule LookupLongLat), and the sky light samples
    the source at R(angle) x the world direction (ReflectionEnvironmentShaders.usf),
    so angle = (L - 90) - atan2(sun_y, sun_x)."""
    return wrap_deg((hdri_sun_longitude_deg - 90.0) - math.degrees(math.atan2(sun_y, sun_x)))


def hdri_ratio(captured_up: float, hdri_up: float) -> float:
    """The captured sky's upward irradiance over the HDRI's (both read back from the
    sky light's SH at +Z, luminance); 0 when either is unusable or the ratio is
    outside [MIN_RATIO, MAX_RATIO] (the captured sky then stays)."""
    if not (captured_up > 0.0 and hdri_up > 0.0) or not math.isfinite(captured_up) or not math.isfinite(hdri_up):
        return 0.0
    ratio = captured_up / hdri_up
    return ratio if MIN_RATIO <= ratio <= MAX_RATIO else 0.0


def hdri_intensity(intensity_now: float, ratio: float, slot: int) -> float:
    """The sky light's intensity under the HDRI: today's (fallback fill and stated
    scales included) x the irradiance ratio x the slot's gain."""
    return intensity_now * ratio * SLOT_FILL_GAIN[slot]


def lower_hemisphere_scale(intensity_now: float, intensity_hdri: float) -> float:
    """The lower hemisphere colour is baked into the cube BEFORE the intensity
    (ReflectionEnvironmentCapture.cpp), so it is divided by the intensity change:
    the drawn ground bounce stays hero lighting's absolute value."""
    return intensity_now / intensity_hdri if intensity_hdri > 0.0 else 1.0


#: Under an overcast or storm photograph no sun reaches the ground: it returns at
#: most this share of the sky's upward irradiance. UNCALIBRATED.
LOWER_CAP_ALBEDO = 0.25


def lower_hemisphere_cap(slot: int, lower_luminance: float, hdri_up_luminance: float) -> float:
    """The factor on the lower hemisphere's RGB (cube units, after the switch):
    capped at LOWER_CAP_ALBEDO x the HDRI's upward irradiance / pi under the
    overcast and storm slots; 1 for clear and golden (hero lighting's sunlit ground)."""
    if slot not in (SLOTS.index("overcast"), SLOTS.index("storm")):
        return 1.0
    cap = LOWER_CAP_ALBEDO * hdri_up_luminance / math.pi
    return cap / lower_luminance if lower_luminance > cap and lower_luminance > 0.0 and cap >= 0.0 else 1.0


def smoothstep(edge0: float, edge1: float, x: float) -> float:
    t = min(max((x - edge0) / (edge1 - edge0), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def backdrop_weight(mode: str, camera_agl_m: float) -> float:
    """The dome's opacity for a camera this high above the card's ground (world Z):
    BACKDROP_OPACITY below BACKDROP_FULL_AGL_M, 0 above BACKDROP_NONE_AGL_M;
    0 unless the switch is auto."""
    if mode != "auto":
        return 0.0
    return BACKDROP_OPACITY * (1.0 - smoothstep(BACKDROP_FULL_AGL_M, BACKDROP_NONE_AGL_M, camera_agl_m))


def backdrop_scale(ratio: float, normalise: float) -> float:
    """The dome's multiplier on the ORIGINAL 2K photograph: its normalisation (the
    prepared copy's 1 / upper mean after the clamp) x the irradiance ratio (the
    captured sky's radiance, without the sky light's fill scales) x BACKDROP_GAIN."""
    return normalise * ratio * BACKDROP_GAIN


def sun_hole_deg(slot: int) -> float:
    return SUN_HOLE_DEG if slot in (SLOTS.index("clear"), SLOTS.index("golden")) else 0.0


def sun_span_deg(slot: int, scene_sun_elevation_deg: float, hdri_sun_elevation_deg: float) -> float:
    """The photograph's sun sits at the scene's azimuth but its own elevation: the
    hole spans the difference (clear and golden slots only)."""
    if sun_hole_deg(slot) <= 0.0:
        return 0.0
    return abs(hdri_sun_elevation_deg - scene_sun_elevation_deg)


# -- the files ----------------------------------------------------------------------------

def source_path(name: str) -> Path:
    return HDRI_DIR / f"{name}_2k.hdr"


def prepared_path(name: str) -> Path:
    return PREPARED_DIR / f"{name}_skylight_1k.hdr"


def sidecar_path(name: str) -> Path:
    return PREPARED_DIR / f"{name}_skylight_1k.json"


def light_asset(name: str) -> str:
    return f"{ASSET_DIR}/{LIGHT_ASSET_PREFIX}{name}.{LIGHT_ASSET_PREFIX}{name}"


def backdrop_asset(name: str) -> str:
    return f"{ASSET_DIR}/{BACKDROP_ASSET_PREFIX}{name}.{BACKDROP_ASSET_PREFIX}{name}"


def write_rgbe_rle(path: Path, image, comment: str) -> None:
    """float32 (H, W, 3) linear as an adaptive-RLE RADIANCE .hdr (the form
    sky_hdri.read_rgbe and UE's importer read)."""
    import numpy as np

    img = np.asarray(image, dtype=np.float32)
    height, width = img.shape[:2]
    peak = img.max(axis=2)
    mantissa, exponent = np.frexp(peak)
    scale = np.where(peak > 1e-32, mantissa * 256.0 / np.maximum(peak, 1e-32), 0.0)
    rgbe = np.zeros((height, width, 4), dtype=np.uint8)
    rgbe[..., :3] = np.clip(img * scale[..., None], 0, 255).astype(np.uint8)
    rgbe[..., 3] = np.where(peak > 1e-32, exponent + 128, 0).astype(np.uint8)
    out = bytearray(b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n# " + comment.encode("ascii") + b"\n\n"
                    + f"-Y {height} +X {width}\n".encode("ascii"))
    for row in range(height):
        out += bytes((2, 2, width >> 8, width & 0xFF))
        for channel in range(4):
            data = rgbe[row, :, channel].tobytes()
            pos = 0
            while pos < width:
                run = 1
                while pos + run < width and run < 127 and data[pos + run] == data[pos]:
                    run += 1
                if run >= 3:
                    out += bytes((128 + run, data[pos]))
                    pos += run
                    continue
                start = pos
                pos += 1
                while pos < width and pos - start < 128:
                    if pos + 2 < width and data[pos] == data[pos + 1] == data[pos + 2]:
                        break
                    pos += 1
                out += bytes((pos - start,)) + data[start:pos]
    Path(path).write_bytes(bytes(out))


def prepare(name: str) -> Dict[str, Any]:
    """The prepared sky-light copy and its sidecar from the committed 2K file:
    sha256 checked, the sun clamped and the upper hemisphere normalised
    (sky_hdri.clamp_sun), box-halved to 1K, written RLE."""
    import numpy as np

    row = HDRIS[name]
    source = source_path(name)
    got = sky_hdri.sha256_of(source)
    if got != row["sha256"]:
        raise RuntimeError(f"hdri_sky.sha256: {source} hashed {got}, the pin says {row['sha256']}")
    image = sky_hdri.read_rgbe(source)
    lon, elev = sky_hdri.sun_direction_deg(image)
    out = sky_hdri.clamp_sun(image, CLAMP_FACTOR)
    full = out.pop("image")
    height, width = full.shape[:2]
    half = full.reshape(height // 2, 2, width // 2, 2, 3).mean(axis=(1, 3))
    PREPARED_DIR.mkdir(parents=True, exist_ok=True)
    target = prepared_path(name)
    write_rgbe_rle(target, half, f"flightsim hdri_sky {name}: sun clamped x{CLAMP_FACTOR:g}, upper mean 1")
    back = sky_hdri.read_rgbe(target)
    record = {
        "format": "flightsim.hdri_sky",
        "version": 1,
        "name": name,
        "slot": row["slot"],
        "title": row["title"],
        "source": row["source"],
        "url": row["url"],
        "licence": LICENCE,
        "authors": row["authors"],
        "source_sha256": row["sha256"],
        "source_resolution": [int(width), int(height)],
        "prepared_resolution": [int(back.shape[1]), int(back.shape[0])],
        "prepared_sha256": sky_hdri.sha256_of(target),
        "sun_longitude_deg": round(float(lon), 4),
        "sun_elevation_deg": round(float(elev), 4),
        "clamp_factor": CLAMP_FACTOR,
        "clamp_luminance": float(out["clamp_luminance"]),
        "normalise": 1.0 / float(out["upper_mean_luminance_after_clamp"]),
        "clamped_pixels": out["clamped_pixels"],
        "clamped_energy_share": out["clamped_energy_share"],
        "upper_mean_luminance_before": out["upper_mean_luminance_before"],
        "prepared_upper_mean_luminance": float(sky_hdri.luminance(back[: back.shape[0] // 2]).mean()),
        "basis": ("sun clamped at clamp_factor x the upper hemisphere's median luminance, the upper hemisphere's "
                  "mean luminance normalised to 1 (x normalise), 2x2 box mean to 1K; the backdrop multiplies the "
                  "2K original by normalise and clamps it at clamp_luminance in the material; UNCALIBRATED"),
    }
    sidecar_path(name).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def sidecar(name: str) -> Dict[str, Any]:
    return json.loads(sidecar_path(name).read_text(encoding="utf-8"))


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="The look's Poly Haven HDRI skies (-look-hdri=).")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="the pins and their slots")
    prep = sub.add_parser("prepare", help="write the prepared sky-light copies and sidecars")
    prep.add_argument("names", nargs="*", default=None)
    args = parser.parse_args(argv)
    if args.command == "list":
        for name, row in HDRIS.items():
            print(f"{row['slot']:9s} {name}: {row['source']} sha256 {row['sha256']}")
        return 0
    for name in args.names or list(HDRIS):
        record = prepare(name)
        print(json.dumps({k: record[k] for k in ("name", "slot", "sun_longitude_deg", "sun_elevation_deg",
                                                  "normalise", "clamp_luminance", "clamped_energy_share")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
