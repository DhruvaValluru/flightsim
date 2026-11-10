"""A pinned Poly Haven CC0 sky-only HDRI as the sky light's specified cubemap
(visual round 5, lane L3, 2026-11-10). BEAUTY ONLY, and only behind a switch:
``-sky-hdri=<name>`` / ``FLIGHTSIM_SKY_HDRI`` (FlightSimClouds.cpp
ApplySkyHdri) on the clear and hazy world presets. The #02 history (rounds
2-5: a blue/indigo shade the captured sky's fill did not explain) is why this
is a PROBE: the A/B pair on Windows compares the fill colour against the
captured sky and the record says which sky lit the frame.

The file is never committed. ``prepare`` (this module's CLI, the repo venv on
the render machine) downloads the pinned 4K .hdr into the cache at first use,
refuses a wrong sha256 by name, then writes the SKY-LIGHT copy beside it:
the sun disk CLAMPED (a specified cubemap is convolved as it is, so an
unclipped sun would light the scene a second time beside the directional
light) and the upper hemisphere's mean luminance normalised to 1, so the host
can set the sky light's intensity as a stated share of the sun's illuminance
(``fill_share x sun_lux / pi``). The sidecar JSON records the clamp, the
measured sun direction in the image (for the cubemap's yaw) and the
normalisation. scripts/ue_create_materials.py imports the prepared file as
/Game/FlightSim/Sky/T_SkyHdri_<name> when FLIGHTSIM_SKY_HDRI names it.

Attribution: THIRD_PARTY_VISUAL.md (CC0 needs none; the entry is kept so every
pinned asset is listed in one place).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

HDRI_FORMAT = "flightsim.sky_hdri"
HDRI_VERSION = 1
#: Licences a sky HDRI may carry (the project rule: no NC).
HDRI_LICENCES = ("CC0-1.0",)
#: Where the editor script finds the imported cubemap (ApplySkyHdri loads
#: /Game/FlightSim/Sky/T_SkyHdri_<name>).
HDRI_ASSET_DIR = "/Game/FlightSim/Sky"
HDRI_ASSET_PREFIX = "T_SkyHdri_"

#: The pins: 4K, sky-only, CC0. The sha256 is of the download as served on
#: 2026-11-10 (dl.polyhaven.org, 17,919,364 bytes, RADIANCE 32-bit_rle_rgbe,
#: 4096 x 2048). UNCALIBRATED where it is a look: which HDRI suits which
#: preset is for the probe to say.
HDRIS: Dict[str, Dict[str, Any]] = {
    "qwantani_puresky": {
        "title": "Qwantani (Pure Sky)",
        "source": "https://polyhaven.com/a/qwantani_puresky",
        "url": "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/4k/qwantani_puresky_4k.hdr",
        "sha256": "5776f890607ff98e21cc1f04bdc3dacbdf33795386dbebb418f42b0fc92814d1",
        "bytes": 17919364,
        "resolution": [4096, 2048],
        "licence": "CC0-1.0",
        "authors": {"Greg Zaal": "Original", "Jarod Guest": "Sky edits"},
        "weather": "clear",
        "time_of_day": "afternoon",
        "presets": ["clear", "hazy"],
    },
}

#: The sun clamp: a pixel brighter than this many times the upper hemisphere's
#: MEDIAN luminance is the sun disk or its aureole and is clamped to that
#: level. UNCALIBRATED: set by probe render on the render machine.
SUN_CLAMP_FACTOR = 32.0
#: The sky light's fill as a share of the sun's illuminance (a clear sky's
#: diffuse-to-direct order, 0.1-0.2 at noon). The host's default for
#: -sky-hdri-fill=. UNCALIBRATED.
HDRI_FILL_SHARE = 0.15

LUMA = (0.2126, 0.7152, 0.0722)


def cache_dir() -> Path:
    """The HDRI cache: %LOCALAPPDATA%\\flightsim\\hdri on Windows, else
    ~/.cache/flightsim/hdri (FLIGHTSIM_HDRI_CACHE overrides)."""
    override = os.environ.get("FLIGHTSIM_HDRI_CACHE")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "flightsim" / "hdri"
    return Path.home() / ".cache" / "flightsim" / "hdri"


def pin(name: str) -> Dict[str, Any]:
    """The pin for ``name``; ValueError (sky_hdri.unknown) when it is not pinned."""
    if name not in HDRIS:
        raise ValueError(f"sky_hdri.unknown: {name!r} is not a pinned sky HDRI ({sorted(HDRIS)})")
    row = HDRIS[name]
    if row.get("licence") not in HDRI_LICENCES:
        raise ValueError(f"sky_hdri.licence: {name} carries {row.get('licence')!r}, not one of {HDRI_LICENCES}")
    return row


def asset_path(name: str) -> str:
    """The imported cubemap's object path."""
    return f"{HDRI_ASSET_DIR}/{HDRI_ASSET_PREFIX}{name}.{HDRI_ASSET_PREFIX}{name}"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_path(name: str, cache: Optional[Path] = None) -> Path:
    return (cache or cache_dir()) / f"{name}_4k.hdr"


def skylight_path(name: str, cache: Optional[Path] = None) -> Path:
    return (cache or cache_dir()) / f"{name}_skylight.hdr"


def sidecar_path(name: str, cache: Optional[Path] = None) -> Path:
    return (cache or cache_dir()) / f"{name}_skylight.json"


def _download(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as response, open(target, "wb") as out:
        shutil.copyfileobj(response, out)


def fetch(name: str, cache: Optional[Path] = None,
          download: Callable[[str, Path], None] = _download) -> Path:
    """The pinned source file in the cache, downloaded at first use and
    verified by sha256 (a mismatch is refused by name: sky_hdri.sha256; the
    bad file is removed). A cached file is re-hashed, never trusted by name."""
    row = pin(name)
    cache = cache or cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    target = source_path(name, cache)
    if target.is_file() and sha256_of(target) == row["sha256"]:
        return target
    handle, tmp_name = tempfile.mkstemp(prefix=f"{name}.", suffix=".part", dir=str(cache))
    os.close(handle)
    tmp = Path(tmp_name)
    try:
        download(row["url"], tmp)
        got = sha256_of(tmp)
        if got != row["sha256"]:
            raise RuntimeError(f"sky_hdri.sha256: {row['url']} hashed {got}, the pin says {row['sha256']}; "
                               f"not used")
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return target


# -- RADIANCE .hdr (RGBE) ---------------------------------------------------------------

def read_rgbe(path: Path):
    """A RADIANCE .hdr as float32 (H, W, 3), linear. Reads the flat and the
    adaptive-RLE scanline forms (the two Poly Haven and UE write)."""
    import numpy as np

    data = Path(path).read_bytes()
    pos = 0
    if not data.startswith(b"#?"):
        raise ValueError(f"sky_hdri.format: {path} is not a RADIANCE file")
    width = height = None
    while True:
        end = data.index(b"\n", pos)
        line = data[pos:end]
        pos = end + 1
        if line.startswith(b"-Y") or line.startswith(b"+Y"):
            parts = line.split()
            if len(parts) != 4 or parts[0] != b"-Y" or parts[2] != b"+X":
                raise ValueError(f"sky_hdri.format: unsupported orientation {line!r}")
            height, width = int(parts[1]), int(parts[3])
            break
        if line.startswith(b"FORMAT=") and line.strip() != b"FORMAT=32-bit_rle_rgbe":
            raise ValueError(f"sky_hdri.format: {line!r} is not 32-bit_rle_rgbe")
    rgbe = np.zeros((height, width, 4), dtype=np.uint8)
    buf = np.frombuffer(data, dtype=np.uint8)
    for row in range(height):
        if (width < 8 or width > 0x7FFF or buf[pos] != 2 or buf[pos + 1] != 2 or (buf[pos + 2] & 0x80)):
            # flat scanline
            rgbe[row] = buf[pos:pos + width * 4].reshape(width, 4)
            pos += width * 4
            continue
        if (int(buf[pos + 2]) << 8 | int(buf[pos + 3])) != width:
            raise ValueError("sky_hdri.format: RLE scanline width mismatch")
        pos += 4
        for channel in range(4):
            col = 0
            while col < width:
                count = int(buf[pos])
                pos += 1
                if count > 128:
                    count -= 128
                    rgbe[row, col:col + count, channel] = buf[pos]
                    pos += 1
                else:
                    rgbe[row, col:col + count, channel] = buf[pos:pos + count]
                    pos += count
                col += count
            if col != width:
                raise ValueError("sky_hdri.format: RLE scanline overrun")
    exponent = rgbe[..., 3].astype(np.int32)
    scale = np.where(exponent > 0, np.ldexp(1.0, exponent - 136), 0.0).astype(np.float32)
    return rgbe[..., :3].astype(np.float32) * scale[..., None]


def write_rgbe(path: Path, image) -> None:
    """float32 (H, W, 3) linear as a flat-scanline RADIANCE .hdr."""
    import numpy as np

    img = np.asarray(image, dtype=np.float32)
    height, width = img.shape[:2]
    peak = img.max(axis=2)
    mantissa, exponent = np.frexp(peak)
    scale = np.where(peak > 1e-32, mantissa * 256.0 / np.maximum(peak, 1e-32), 0.0)
    rgbe = np.zeros((height, width, 4), dtype=np.uint8)
    rgbe[..., :3] = np.clip(img * scale[..., None], 0, 255).astype(np.uint8)
    rgbe[..., 3] = np.where(peak > 1e-32, exponent + 128, 0).astype(np.uint8)
    header = (b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n# flightsim sky_hdri (sun clamped, normalised)\n\n"
              + f"-Y {height} +X {width}\n".encode("ascii"))
    Path(path).write_bytes(header + rgbe.tobytes())


def luminance(image):
    return image[..., 0] * LUMA[0] + image[..., 1] * LUMA[1] + image[..., 2] * LUMA[2]


def sun_direction_deg(image) -> Tuple[float, float]:
    """(longitude, elevation) of the brightest pixel in degrees: the image's
    centre column is longitude 0, the top row elevation +90."""
    import numpy as np

    lum = luminance(image)
    row, col = np.unravel_index(int(np.argmax(lum)), lum.shape)
    height, width = lum.shape
    return ((col + 0.5) / width * 360.0 - 180.0, 90.0 - (row + 0.5) / height * 180.0)


def clamp_sun(image, factor: float = SUN_CLAMP_FACTOR) -> Dict[str, Any]:
    """The sky-light copy: the upper hemisphere's median luminance times
    ``factor`` caps every pixel (the sun disk and its aureole, scaled down in
    colour), then the whole image is divided by the upper hemisphere's mean
    luminance so that mean is 1. Returns the image and its record."""
    import numpy as np

    img = np.asarray(image, dtype=np.float32)
    height = img.shape[0]
    upper = img[: height // 2]
    lum_upper = luminance(upper)
    median = float(np.median(lum_upper))
    cap = median * float(factor)
    lum = luminance(img)
    total_before = float(lum_upper.sum())
    gain = np.where(lum > cap, cap / np.maximum(lum, 1e-30), 1.0).astype(np.float32)
    clamped = img * gain[..., None]
    clamped_pixels = int((lum > cap).sum())
    mean_after_clamp = float(luminance(clamped[: height // 2]).mean())
    normalised = clamped / max(mean_after_clamp, 1e-30)
    return {
        "image": normalised,
        "clamp_factor": float(factor),
        "upper_median_luminance": median,
        "clamp_luminance": cap,
        "clamped_pixels": clamped_pixels,
        "clamped_energy_share": 1.0 - float(luminance(clamped[: height // 2]).sum()) / max(total_before, 1e-30),
        "upper_mean_luminance_before": float(lum_upper.mean()),
        "upper_mean_luminance_after_clamp": mean_after_clamp,
        "upper_mean_luminance_written": float(luminance(normalised[: height // 2]).mean()),
    }


def prepare(name: str, cache: Optional[Path] = None,
            download: Callable[[str, Path], None] = _download, force: bool = False) -> Dict[str, Any]:
    """Fetch (verify) the pin, write the sky-light copy and its sidecar; returns
    the sidecar. An existing sidecar whose source sha256 is the pin's is reused."""
    row = pin(name)
    cache = cache or cache_dir()
    side = sidecar_path(name, cache)
    if not force and side.is_file() and skylight_path(name, cache).is_file():
        existing = json.loads(side.read_text(encoding="utf-8"))
        if existing.get("source_sha256") == row["sha256"] and existing.get("clamp_factor") == SUN_CLAMP_FACTOR:
            return existing
    source = fetch(name, cache, download)
    image = read_rgbe(source)
    lon, elev = sun_direction_deg(image)
    out = clamp_sun(image)
    target = skylight_path(name, cache)
    write_rgbe(target, out.pop("image"))
    record = {
        "format": HDRI_FORMAT,
        "version": HDRI_VERSION,
        "name": name,
        "title": row["title"],
        "source": row["source"],
        "url": row["url"],
        "licence": row["licence"],
        "authors": row["authors"],
        "source_sha256": row["sha256"],
        "source_file": str(source),
        "skylight_file": str(target),
        "skylight_sha256": sha256_of(target),
        "resolution": [int(image.shape[1]), int(image.shape[0])],
        "sun_longitude_deg": lon,
        "sun_elevation_deg": elev,
        "asset": asset_path(name),
        "fill_share_default": HDRI_FILL_SHARE,
        "basis": ("sun clamped at clamp_factor x the upper hemisphere's median luminance, then the upper "
                  "hemisphere's mean luminance normalised to 1 (the host sets intensity = fill_share x sun_lux "
                  "/ pi); UNCALIBRATED"),
        **out,
    }
    side.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Pinned sky HDRIs for the sky-light probe (-sky-hdri=).")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="the pins")
    prep = sub.add_parser("prepare", help="fetch, verify, clamp the sun, write the sky-light copy")
    prep.add_argument("name", choices=sorted(HDRIS))
    prep.add_argument("--cache", type=Path, default=None)
    prep.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "list":
        for name, row in HDRIS.items():
            print(f"{name}: {row['title']} ({row['licence']}, {row['resolution'][0]}x{row['resolution'][1]}) "
                  f"sha256 {row['sha256']}")
        return 0
    record = prepare(args.name, args.cache, force=args.force)
    print(json.dumps({k: record[k] for k in ("name", "skylight_file", "sun_longitude_deg", "sun_elevation_deg",
                                              "clamped_pixels", "clamped_energy_share", "asset")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
