"""Mac bake: land-cover splat and shoreline distance field for the coastal scenario.

VISUAL-ONLY. Nothing here feeds the flight model, and nothing here has been
rendered: every look value is UNMEASURED until the Windows gate in
INTEGRATION.md has run on the laptop.

What it does
------------
The Google tiles stay the ground and its colour. This bake turns the repo's
own ESA WorldCover class map (``core/terrain/landcover.py`` writes
``<key>_landcover/class_map.png`` + ``landcover.json``) into two small
textures the tile material samples, so the laptop does no classification:

``splat``      4 channels, 8 bit, summing to exactly 255 in every texel:
               vegetation, bare/sand, built, water. Feathered, so the 10 m
               class staircase does not show as blocks in the roughness.
``shore_sdf``  1 channel, 8 bit: signed distance to the water line in metres
               (land positive), 128 = the line, +-127 = +-``SDF_RANGE_M``.
               Drives the wet-sand band, the foam line and the shallow tint
               with arithmetic only.

Both are also written as ready-to-upload mip chains (``*_mips.bin``, top mip
first, row-major, splat in BGRA byte order for PF_B8G8R8A8, sdf for PF_G8)
so the render side does one memcpy per mip and no PNG decode.

Refusals are by name: ``terrain.land_cover_splat``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from PIL import Image

LANE = "terrain.land_cover_splat.coastal"
LABEL = "visual-only; look values UNMEASURED on the render machine"
VERSION = 1

GROUPS: Tuple[str, ...] = ("vegetation", "bare_sand", "built", "water")

#: ESA WorldCover v200 map code -> weight per group (rows sum to 1). The codes
#: are table 3 of the product user manual, the same table
#: core/terrain/landcover.py LEGEND carries. The split of the two wetland
#: classes between vegetation and water is this lane's look choice.
CODE_TO_GROUPS: Dict[int, Tuple[float, float, float, float]] = {
    10: (1.0, 0.0, 0.0, 0.0),   # tree cover
    20: (1.0, 0.0, 0.0, 0.0),   # shrubland
    30: (1.0, 0.0, 0.0, 0.0),   # grassland
    40: (1.0, 0.0, 0.0, 0.0),   # cropland
    50: (0.0, 0.0, 1.0, 0.0),   # built-up
    60: (0.0, 1.0, 0.0, 0.0),   # bare / sparse vegetation (beach, rock)
    70: (0.0, 1.0, 0.0, 0.0),   # snow and ice: none expected on this coast
    80: (0.0, 0.0, 0.0, 1.0),   # permanent water
    90: (0.6, 0.0, 0.0, 0.4),   # herbaceous wetland (look choice; stays land for the shoreline)
    95: (0.7, 0.0, 0.0, 0.3),   # mangroves (look choice)
    100: (1.0, 0.0, 0.0, 0.0),  # moss and lichen
}
NODATA_CODE = 0
#: WorldCover has no tile over open ocean, so nodata next to a coast is sea.
NODATA_GROUPS = (0.0, 0.0, 0.0, 1.0)

#: Tier -> texture edge in texels (square, power of two) and what the
#: material does with it. Costs are ESTIMATES (see est_vram_mb).
TIERS: Dict[int, Dict[str, Any]] = {
    0: {"edge": 512, "features": ["roughness_from_splat", "water_mask"]},
    1: {"edge": 1024, "features": ["roughness_from_splat", "water_mask",
                                   "wet_sand_band", "foam_line"]},
    2: {"edge": 2048, "features": ["roughness_from_splat", "water_mask",
                                   "wet_sand_band", "foam_line",
                                   "detail_normal_512_per_group"]},
    3: {"edge": 4096, "features": ["roughness_from_splat", "water_mask",
                                   "wet_sand_band", "foam_line",
                                   "detail_normal_1024_per_group",
                                   "shallow_water_tint"]},
}

SDF_RANGE_M = 320.0
SDF_CAP_TEXELS = 64

#: Authored look values (not measurements). Roughness and specular are what
#: the tile material lerps to by splat weight. Water is the water lane's to
#: set; this lane only hands over the mask. Albedo is an AUTHORED, UNCITED
#: broadband pick per group, used only for the sidecar's mean-albedo figures;
#: no source was read for it, so no lane may quote it as a measured value.
#: The tile imagery, not this number, is the colour on screen.
MATERIAL: Dict[str, Dict[str, Any]] = {
    "vegetation": {"roughness": 0.85, "specular": 0.30, "albedo": 0.18, "detail_tile_m": 6.0},
    "bare_sand": {"roughness": 0.75, "specular": 0.35, "albedo": 0.30, "detail_tile_m": 3.0},
    "built": {"roughness": 0.70, "specular": 0.40, "albedo": 0.15, "detail_tile_m": 4.0},
    "water": {"roughness": None, "specular": None, "albedo": 0.06, "detail_tile_m": None,
              "note": "owned by the water lane; 0.06 matches the sun_time_of_day lane's sea bounce"},
}
#: Wet sand: darker and smoother within this many metres landward of the
#: water line (phenomenon: Lekner & Dorf, Applied Optics 27(7), 1988; the two
#: numbers are look choices).
WET_SAND = {"band_m": 12.0, "albedo_multiplier": 0.6, "roughness": 0.35}
FOAM_LINE = {"centre_m": 0.0, "half_width_m": 4.0, "opacity": 0.5}


class LandCoverSplatError(Exception):
    """Refusal by name."""

    name = "terrain.land_cover_splat"

    def __init__(self, reason: str):
        super().__init__(f"{self.name}: {reason}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def synthetic_class_map(edge: int = 768) -> np.ndarray:
    """A deterministic made-up coast for tests and dry runs. NOT a place and
    never a render input: the sidecar marks a bake from it ``synthetic``."""
    y, x = np.mgrid[0:edge, 0:edge].astype(np.float64) / edge
    coast = 0.38 + 0.05 * np.sin(7.0 * y) + 0.02 * np.sin(23.0 * y + 1.0)
    d = x - coast                                   # > 0 is land
    codes = np.full((edge, edge), 80, np.uint8)
    codes[d > 0.0] = 60                             # beach
    inland = d > 0.02 + 0.01 * np.sin(31.0 * y)
    codes[inland] = 30                              # grass
    wood = np.sin(19.0 * x + 3.0 * np.sin(11.0 * y)) * np.cos(17.0 * y) > 0.35
    codes[inland & wood & (d > 0.08)] = 10          # trees
    codes[inland & (np.sin(40.0 * x) * np.sin(37.0 * y) > 0.8)] = 20  # shrub
    town = (np.abs(x - 0.62) < 0.07) & (np.abs(y - 0.45) < 0.09)
    codes[town] = 50
    lagoon = (x - 0.55) ** 2 + (y - 0.8) ** 2 < 0.05 ** 2
    codes[lagoon] = 90
    codes[(x < 0.04)] = NODATA_CODE                 # far offshore: no tile
    return codes


def group_fractions(codes: np.ndarray) -> np.ndarray:
    """(H, W) WorldCover codes -> (H, W, 4) float32 group weights summing to 1."""
    if codes.ndim != 2:
        raise LandCoverSplatError(f"class map must be 2-D, got shape {codes.shape}")
    present = np.unique(codes)
    unknown = [int(c) for c in present if int(c) != NODATA_CODE and int(c) not in CODE_TO_GROUPS]
    if unknown:
        raise LandCoverSplatError(f"class map holds codes outside the WorldCover legend: {unknown}")
    lut = np.zeros((256, 4), np.float32)
    lut[NODATA_CODE] = NODATA_GROUPS
    for code, weights in CODE_TO_GROUPS.items():
        lut[code] = weights
    return lut[codes]


def resample(fractions: np.ndarray, edge: int) -> np.ndarray:
    """Area-average down (BOX) or interpolate up (BILINEAR) to edge x edge."""
    h, w, _ = fractions.shape
    resample_filter = Image.BOX if (h >= edge and w >= edge) else Image.BILINEAR
    out = np.empty((edge, edge, fractions.shape[2]), np.float32)
    for c in range(fractions.shape[2]):
        img = Image.fromarray(fractions[..., c])
        out[..., c] = np.asarray(img.resize((edge, edge), resample_filter), np.float32)
    return _renormalise(out)


def _renormalise(fractions: np.ndarray) -> np.ndarray:
    fractions = np.clip(fractions, 0.0, None)
    total = fractions.sum(axis=-1, keepdims=True)
    return fractions / np.where(total > 0, total, 1.0)


def feather(fractions: np.ndarray) -> np.ndarray:
    """One separable binomial [1 4 6 4 1]/16 pass with clamped edges. Linear,
    so the weights still sum to 1."""
    kernel = np.array([1, 4, 6, 4, 1], np.float32) / 16.0
    out = fractions
    for axis in (0, 1):
        pad = [(0, 0)] * out.ndim
        pad[axis] = (2, 2)
        padded = np.pad(out, pad, mode="edge")
        acc = np.zeros_like(out)
        n = out.shape[axis]
        for i, k in enumerate(kernel):
            acc += k * np.take(padded, np.arange(i, i + n), axis=axis)
        out = acc
    return _renormalise(out)


def quantise_to_255(fractions: np.ndarray) -> np.ndarray:
    """Largest-remainder rounding: every texel's channels sum to exactly 255
    (the convention of core/terrain/weightmaps.py quantise_to_255)."""
    scaled = _renormalise(fractions).astype(np.float64) * 255.0
    floor = np.floor(scaled)
    short = (255 - floor.sum(axis=-1)).astype(np.int64)           # 0..channels-1
    order = np.argsort(-(scaled - floor), axis=-1, kind="stable")
    rank = np.argsort(order, axis=-1, kind="stable")
    out = floor + (rank < short[..., None])
    return out.astype(np.uint8)


def capped_edt(mask: np.ndarray, cap: int) -> np.ndarray:
    """Euclidean distance in texels from every cell to the nearest True cell,
    exact up to ``cap`` and clamped to ``cap`` beyond it."""
    h, w = mask.shape
    big = float(cap + 1)
    g = np.where(mask, 0.0, big).astype(np.float32)
    for x in range(1, w):
        np.minimum(g[:, x], g[:, x - 1] + 1.0, out=g[:, x])
    for x in range(w - 2, -1, -1):
        np.minimum(g[:, x], g[:, x + 1] + 1.0, out=g[:, x])
    np.minimum(g, big, out=g)
    g2 = g * g
    best = g2.copy()
    for dy in range(1, min(cap, h - 1) + 1):
        np.minimum(best[dy:], g2[:-dy] + dy * dy, out=best[dy:])
        np.minimum(best[:-dy], g2[dy:] + dy * dy, out=best[:-dy])
    return np.minimum(np.sqrt(best), float(cap))


def shore_sdf_m(water: np.ndarray, texel_m: float, cap: int = SDF_CAP_TEXELS) -> np.ndarray:
    """Signed distance to the water line in metres: land > 0, water < 0. The
    line sits on the texel edge between a water texel and a land texel."""
    to_water = capped_edt(water, cap)
    to_land = capped_edt(~water, cap)
    signed = np.where(water, -(to_land - 0.5), to_water - 0.5)
    return (signed * texel_m).astype(np.float32)


def encode_sdf(sdf_m: np.ndarray, range_m: float = SDF_RANGE_M) -> np.ndarray:
    return np.rint(128.0 + np.clip(sdf_m / range_m, -1.0, 1.0) * 127.0).astype(np.uint8)


def decode_sdf(u8: np.ndarray, range_m: float = SDF_RANGE_M) -> np.ndarray:
    return (u8.astype(np.float32) - 128.0) / 127.0 * range_m


def _halve(a: np.ndarray) -> np.ndarray:
    return 0.25 * (a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2])


def splat_mips(fractions: np.ndarray) -> List[np.ndarray]:
    """Box mips down to 1x1, each re-quantised so it still sums to 255."""
    mips, level = [], fractions.astype(np.float32)
    while True:
        mips.append(quantise_to_255(level))
        if level.shape[0] == 1:
            return mips
        level = _halve(level)


def sdf_mips(sdf_m: np.ndarray) -> List[np.ndarray]:
    mips, level = [], sdf_m.astype(np.float32)
    while True:
        mips.append(encode_sdf(level))
        if level.shape[0] == 1:
            return mips
        level = _halve(level)


def est_vram_mb(tier: int) -> Dict[str, float]:
    """ESTIMATE of texture memory, uncompressed with a full mip chain (x 4/3).
    Not measured on the laptop. BC3 + BC4 would be a quarter of the first two."""
    edge = TIERS[tier]["edge"]
    mb = 1024.0 * 1024.0
    splat = edge * edge * 4 * 4 / 3 / mb
    sdf = edge * edge * 1 * 4 / 3 / mb
    detail_edge = {2: 512, 3: 1024}.get(tier, 0)
    detail = 3 * detail_edge * detail_edge * 1 * 4 / 3 / mb       # 3 groups, BC5 at 1 byte/texel
    return {"splat_rgba8": round(splat, 2), "shore_sdf_r8": round(sdf, 2),
            "detail_normals_bc5": round(detail, 2), "total": round(splat + sdf + detail, 2)}


def build(codes: np.ndarray, extent_m: float, tier: int) -> Dict[str, Any]:
    if tier not in TIERS:
        raise LandCoverSplatError(f"unknown tier {tier}; tiers are {sorted(TIERS)}")
    if not extent_m > 0:
        raise LandCoverSplatError(f"extent must be positive metres, got {extent_m}")
    edge = TIERS[tier]["edge"]
    texel_m = extent_m / edge
    if SDF_CAP_TEXELS * texel_m < SDF_RANGE_M:
        raise LandCoverSplatError(
            f"texel {texel_m:.1f} m is too fine for the {SDF_RANGE_M:.0f} m shoreline range "
            f"at a {SDF_CAP_TEXELS}-texel search; use a lower tier or a larger extent")
    source = group_fractions(codes)
    fractions = feather(resample(source, edge))
    water = fractions[..., GROUPS.index("water")] > 0.5
    sdf = shore_sdf_m(water, texel_m)
    mean = source.reshape(-1, 4).mean(axis=0)
    albedo = float(sum(mean[i] * MATERIAL[g]["albedo"] for i, g in enumerate(GROUPS)))
    land = 1.0 - float(mean[3])
    land_albedo = (float(sum(mean[i] * MATERIAL[g]["albedo"] for i, g in enumerate(GROUPS[:3]))) / land
                   if land > 0 else None)
    return {
        "tier": tier, "edge": edge, "texel_m": texel_m, "extent_m": extent_m,
        "splat_mips": splat_mips(fractions), "sdf_mips": sdf_mips(sdf),
        "group_fractions": {g: round(float(mean[i]), 6) for i, g in enumerate(GROUPS)},
        "nodata_fraction": round(float((codes == NODATA_CODE).mean()), 6),
        "scene_mean_albedo": round(albedo, 4),
        "land_mean_albedo": None if land_albedo is None else round(land_albedo, 4),
        "source_texel_m": extent_m / max(codes.shape),
    }


def write(result: Dict[str, Any], out_dir: Path, source: Dict[str, Any]) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files: Dict[str, Dict[str, Any]] = {}

    def put(name: str, data: bytes, **extra: Any) -> None:
        (out_dir / name).write_bytes(data)
        files[name] = {"sha256": sha256_bytes(data), "bytes": len(data), **extra}

    splat0, sdf0 = result["splat_mips"][0], result["sdf_mips"][0]
    Image.fromarray(splat0).save(out_dir / "splat_rgba.png", optimize=False)
    Image.fromarray(sdf0).save(out_dir / "shore_sdf.png", optimize=False)
    for name in ("splat_rgba.png", "shore_sdf.png"):
        data = (out_dir / name).read_bytes()
        files[name] = {"sha256": sha256_bytes(data), "bytes": len(data), "use": "inspection / editor import"}
    put("splat_bgra_mips.bin", b"".join(m[..., [2, 1, 0, 3]].tobytes() for m in result["splat_mips"]),
        pixel_format="PF_B8G8R8A8", srgb=False,
        mip_edges=[int(m.shape[0]) for m in result["splat_mips"]])
    put("shore_sdf_mips.bin", b"".join(m.tobytes() for m in result["sdf_mips"]),
        pixel_format="PF_G8", srgb=False,
        mip_edges=[int(m.shape[0]) for m in result["sdf_mips"]])
    sidecar = {
        "lane": LANE, "label": LABEL, "version": VERSION,
        "tier": result["tier"], "features": TIERS[result["tier"]]["features"],
        "edge": result["edge"], "extent_m": result["extent_m"], "texel_m": result["texel_m"],
        "source_texel_m": result["source_texel_m"],
        "channels": {"R": GROUPS[0], "G": GROUPS[1], "B": GROUPS[2], "A": GROUPS[3]},
        "channel_sum": 255,
        "shore_sdf": {"range_m": SDF_RANGE_M, "zero": 128, "scale": 127,
                      "sign": "land positive, water negative",
                      "decode": "(v - 128) / 127 * range_m"},
        "uv": "u = (x - origin_x) / extent_m, v = (origin_y_top - y) / extent_m in the bake's "
              "projected CRS; row 0 is the north edge",
        "material": MATERIAL, "wet_sand": WET_SAND, "foam_line": FOAM_LINE,
        "group_fractions": result["group_fractions"],
        "nodata_fraction": result["nodata_fraction"],
        "nodata_treated_as": "water",
        "scene_mean_albedo": result["scene_mean_albedo"],
        "land_mean_albedo": result["land_mean_albedo"],
        "est_vram_mb": est_vram_mb(result["tier"]),
        "est_vram_note": "ESTIMATE, uncompressed with mips; not measured on the laptop",
        "source": source, "files": files,
    }
    (out_dir / "land_cover_splat.json").write_text(json.dumps(sidecar, indent=1, sort_keys=True) + "\n")
    return sidecar


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--class-map", type=Path, help="<key>_landcover/class_map.png (WorldCover codes)")
    src.add_argument("--synthetic", action="store_true", help="made-up coast, for dry runs only")
    parser.add_argument("--landcover-json", type=Path,
                        help="<key>_landcover/landcover.json; required with --class-map (carries "
                             "the source sha256 and the CC BY 4.0 attribution)")
    parser.add_argument("--extent-m", type=float, nargs=2, metavar=("X", "Y"), default=None,
                        help="ground size of the class map in metres (must be square within 1 %%)")
    parser.add_argument("--tier", type=int, default=0, choices=sorted(TIERS))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.synthetic:
            codes = synthetic_class_map()
            extent = args.extent_m or [20480.0, 20480.0]
            source = {"synthetic": True,
                      "note": "made-up coast from synthetic_class_map(); NOT a place, NOT a render input"}
        else:
            if args.landcover_json is None or args.extent_m is None:
                raise LandCoverSplatError("--class-map needs --landcover-json and --extent-m")
            raw = args.class_map.read_bytes()
            codes = np.asarray(Image.open(args.class_map))
            extent = args.extent_m
            landcover = json.loads(args.landcover_json.read_text())
            stated = (landcover.get("class_map") or {}).get("sha256") if isinstance(landcover, dict) else None
            if stated != sha256_bytes(raw):
                raise LandCoverSplatError(
                    f"{args.class_map} is not the class map {args.landcover_json} describes "
                    f"(class_map.sha256 {stated} vs {sha256_bytes(raw)})")
            if codes.ndim != 2:
                raise LandCoverSplatError(f"{args.class_map} is not a single-channel code map (shape {codes.shape})")
            source = {"synthetic": False, "class_map": args.class_map.name,
                      "class_map_sha256": sha256_bytes(raw), "landcover": landcover}
        if abs(extent[0] - extent[1]) > 0.01 * max(extent):
            raise LandCoverSplatError(f"extent {extent} is not square; crop the class map to a square window")
        sidecar = write(build(codes, float(extent[0]), args.tier), args.out, source)
    except LandCoverSplatError as error:
        print(error, file=sys.stderr)
        return 2
    print(json.dumps({k: sidecar[k] for k in ("tier", "edge", "texel_m", "group_fractions",
                                              "scene_mean_albedo", "est_vram_mb")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
