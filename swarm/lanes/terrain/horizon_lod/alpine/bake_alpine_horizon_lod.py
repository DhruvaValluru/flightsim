"""Offline plan for the alpine horizon and tile level of detail (Mac, stdlib only).

VISUAL-ONLY. Nothing here is a render result. It writes

  alpine_horizon_lod.json       the tier ladder (Cesium tileset settings per
                                tier), the predicted horizon and the predicted
                                ground-sample-distance curve the pixel gate
                                compares a Windows frame against
  alpine_horizon_lod_curve.csv  the same curve as a table

The ground is the Google Photorealistic 3D Tiles drawn by Cesium for Unreal
(the project rule); this lane only chooses how finely Cesium refines them and
how far out, inside an integrated-GPU memory budget. It ships no terrain data.

Model (all closed form):

* Horizon. The engine draws straight rays over the WGS84 globe, so the
  rendered horizon is the GEOMETRIC one, d = sqrt(2 R h + h^2), with no
  atmospheric refraction. The real one is about 1/sqrt(1-k) farther
  (k = 0.13); that number is recorded, never used by the gate.
* Tile selection. Cesium refines a tile while
  geometric_error * viewport_px / (distance * 2 tan(fov/2)) > max SSE,
  so a drawn tile at slant distance d has geometric error <= SSE * d * ifov.
  The bound scales linearly with SSE: that ratio is what the gate checks.
* Tile count. With tile side = span * geometric error, the tiles in a view
  sector of angle A between ground ranges r0 and r1 from height h are
  N = A / (2 (span * SSE * ifov)^2) * ln((r1^2 + h^2) / (r0^2 + h^2)).
  Cost goes as 1/SSE^2 but only as the LOG of the horizon range: drawing to
  the horizon is cheap, a finer SSE is not. `span` and the bytes per tile are
  ASSUMED, not measured (see CALIBRATION); every megabyte below is an estimate.

Run:  python swarm/lanes/terrain/horizon_lod/alpine/bake_alpine_horizon_lod.py
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

LANE = Path(__file__).resolve().parent

EARTH_RADIUS_M = 6371008.8          # IUGG mean radius
REFRACTION_K = 0.13                 # standard terrestrial refraction, recorded only

#: The scenario shot: scripts/run_test_scenarios.py "A-4 over the matterhorn
#: ... at 5000 m ... flying north". Pitch and the reference ground are NOT read
#: from a run card here; the gate takes the real ones as arguments.
SHOT = {
    "camera_altitude_amsl_m": 5000.0,
    "heading": "north",
    "reference_ground_amsl_m": 500.0,   # Swiss plateau, the far ground flying north
    "near_ground_amsl_m": 3000.0,       # terrain under the aircraft (assumed)
    "hfov_deg": 54.4,                   # core/scenario/camera.py default
    "capture_width_px": 1280,           # budget max_capture_width
    "capture_height_px": 720,
    "camera_pitch_deg": -5.0,           # ASSUMED; the gate takes the real one
}

#: ASSUMED constants of the tile-count model. Calibrate on Windows from
#: Cesium's selection statistics (INTEGRATION.md, step 3).
CALIBRATION = {
    "tile_span_per_geometric_error": 16.0,
    "tile_span_range": [8.0, 32.0],
    "bytes_per_tile": 450_000,          # 256x256 RGBA8 with mips + mesh, assumed
    "status": "UNCALIBRATED",
}

REFERENCE_SSE = 6.0   # FLIGHTSIM_GOOGLE_TILES_BEAUTY_SSE default: today's frame

#: The ladder. Tier 0 keeps today's tile selection and only caps what Cesium
#: holds and loads at once; tiers 1-3 refine. Property names are Cesium for
#: Unreal 2.x ACesium3DTileset UPROPERTY names typed from memory, to be set by
#: reflection by name and recorded as found or not found, as ApplyBeautyLook does.
TIERS = [
    {
        "tier": 0, "maximum_screen_space_error": 6.0,
        "summary": "today's SSE 6 selection, memory capped: small tile cache, no sibling "
                   "preload, few simultaneous loads, no LOD cross-fade",
        "tileset": {"MaximumCachedBytes": 64 * 1024 * 1024, "MaximumSimultaneousTileLoads": 4,
                    "LoadingDescendantLimit": 8, "PreloadAncestors": True, "PreloadSiblings": False,
                    "EnableFogCulling": True, "EnableFrustumCulling": True,
                    "EnforceCulledScreenSpaceError": True, "CulledScreenSpaceError": 64.0,
                    "UseLodTransitions": False, "ForbidHoles": False},
    },
    {
        "tier": 1, "maximum_screen_space_error": 5.0,
        "summary": "SSE 5, fog culling off so nothing short of the horizon is dropped",
        "tileset": {"MaximumCachedBytes": 96 * 1024 * 1024, "MaximumSimultaneousTileLoads": 4,
                    "LoadingDescendantLimit": 8, "PreloadAncestors": True, "PreloadSiblings": False,
                    "EnableFogCulling": False, "EnableFrustumCulling": True,
                    "EnforceCulledScreenSpaceError": True, "CulledScreenSpaceError": 64.0,
                    "UseLodTransitions": False, "ForbidHoles": False},
    },
    {
        "tier": 2, "maximum_screen_space_error": 4.0,
        "summary": "SSE 4, fog culling off, holes forbidden",
        "tileset": {"MaximumCachedBytes": 128 * 1024 * 1024, "MaximumSimultaneousTileLoads": 6,
                    "LoadingDescendantLimit": 12, "PreloadAncestors": True, "PreloadSiblings": False,
                    "EnableFogCulling": False, "EnableFrustumCulling": True,
                    "EnforceCulledScreenSpaceError": True, "CulledScreenSpaceError": 64.0,
                    "UseLodTransitions": False, "ForbidHoles": True},
    },
    {
        "tier": 3, "maximum_screen_space_error": 3.0,
        "summary": "SSE 3, fog culling off, holes forbidden, LOD cross-fade for the 6 s clip",
        "tileset": {"MaximumCachedBytes": 256 * 1024 * 1024, "MaximumSimultaneousTileLoads": 8,
                    "LoadingDescendantLimit": 20, "PreloadAncestors": True, "PreloadSiblings": True,
                    "EnableFogCulling": False, "EnableFrustumCulling": True,
                    "EnforceCulledScreenSpaceError": True, "CulledScreenSpaceError": 64.0,
                    "UseLodTransitions": True, "LodTransitionLength": 0.5, "ForbidHoles": True},
    },
]

#: If tier 0 loses the device, the next thing to try (coarser than today).
FALLBACK = {"maximum_screen_space_error": 8.0,
            "how": "set FLIGHTSIM_GOOGLE_TILES_SSE=8 (an existing switch)"}

CURVE_DISTANCES_KM = [2, 5, 10, 20, 40, 60, 80, 100, 150, 200]


def horizon_distance_m(height_m: float, radius_m: float = EARTH_RADIUS_M) -> float:
    """Straight-line distance to the geometric horizon from height_m above a sphere."""
    return math.sqrt(max(0.0, 2.0 * radius_m * height_m + height_m * height_m))


def horizon_dip_deg(height_m: float, radius_m: float = EARTH_RADIUS_M) -> float:
    """Depression of the geometric horizon below the local horizontal."""
    return math.degrees(math.acos(radius_m / (radius_m + max(0.0, height_m))))


def depression_deg(ground_range_m: float, height_m: float, radius_m: float = EARTH_RADIUS_M) -> float:
    """Depression of the surface point at arc distance ground_range_m, seen from height_m."""
    theta = ground_range_m / radius_m
    return math.degrees(math.atan2((radius_m + height_m) - radius_m * math.cos(theta),
                                   radius_m * math.sin(theta)))


def range_from_depression_m(dep_deg: float, height_m: float, radius_m: float = EARTH_RADIUS_M) -> float:
    """Arc distance whose surface point sits dep_deg below horizontal; the
    horizon arc when dep_deg is at or above the horizon (saturates there)."""
    arc_h = radius_m * math.acos(radius_m / (radius_m + height_m))
    if dep_deg <= horizon_dip_deg(height_m, radius_m):
        return arc_h
    lo, hi = 1.0, arc_h
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if depression_deg(mid, height_m, radius_m) > dep_deg:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def ifov_rad(hfov_deg: float, width_px: int) -> float:
    """Angle of one pixel at the image centre."""
    return 2.0 * math.tan(math.radians(hfov_deg) / 2.0) / width_px


def geometric_error_bound_m(sse: float, slant_m: float, hfov_deg: float, width_px: int) -> float:
    """Largest geometric error Cesium leaves in a drawn tile at slant_m."""
    return sse * slant_m * ifov_rad(hfov_deg, width_px)


def tile_count(sse: float, height_agl_m: float, near_range_m: float, far_range_m: float,
               hfov_deg: float, width_px: int, span: float) -> float:
    """Estimated tiles drawn in the view sector (the docstring's N)."""
    side = span * sse * ifov_rad(hfov_deg, width_px)
    h2 = height_agl_m * height_agl_m
    return (math.radians(hfov_deg) / (2.0 * side * side)
            * math.log((far_range_m ** 2 + h2) / (near_range_m ** 2 + h2)))


def build() -> dict:
    s = SHOT
    w, h_px, hfov = s["capture_width_px"], s["capture_height_px"], s["hfov_deg"]
    cam = s["camera_altitude_amsl_m"]
    h_ref = cam - s["reference_ground_amsl_m"]
    h_near = cam - s["near_ground_amsl_m"]
    vfov = 2.0 * math.degrees(math.atan(math.tan(math.radians(hfov) / 2.0) * h_px / w))
    focal_px = (w / 2.0) / math.tan(math.radians(hfov) / 2.0)
    d_h = horizon_distance_m(h_ref)
    dip = horizon_dip_deg(h_ref)
    bottom_dep = -s["camera_pitch_deg"] + vfov / 2.0
    near_range = h_near / math.tan(math.radians(bottom_dep))
    horizon_row = (h_px - 1) / 2.0 + focal_px * math.tan(math.radians(dip + s["camera_pitch_deg"]))

    def resolvable_km() -> float:
        # farthest range still 2 px above the horizon row: past it the
        # skyline cannot tell a truncated terrain from a full one
        two_px = math.degrees(2.0 / focal_px)
        return range_from_depression_m(dip + two_px, h_ref) / 1000.0

    span = CALIBRATION["tile_span_per_geometric_error"]
    lo_span, hi_span = CALIBRATION["tile_span_range"]
    mb = CALIBRATION["bytes_per_tile"] / 1e6

    def tiles(sse: float, sp: float) -> float:
        return tile_count(sse, h_near, near_range, d_h, hfov, w, sp)

    ref_tiles = tiles(REFERENCE_SSE, span)
    tiers = []
    for t in TIERS:
        sse = t["maximum_screen_space_error"]
        n = tiles(sse, span)
        cache_mb = t["tileset"]["MaximumCachedBytes"] / 1048576.0
        tiers.append({
            **t,
            "predicted_gsd_ratio_vs_reference": round(sse / REFERENCE_SSE, 4),
            "est_tiles_drawn": round(n),
            "est_tiles_drawn_range": [round(tiles(sse, hi_span)), round(tiles(sse, lo_span))],
            "est_drawn_mb": round(n * mb, 1),
            "est_vram_mb": round(n * mb + cache_mb, 1),
            "est_cost_vs_reference": round(n / ref_tiles, 3),
            "status": "ESTIMATE, UNMEASURED: never rendered",
        })

    curve = []
    for km in CURVE_DISTANCES_KM:
        d = km * 1000.0
        row = {"slant_km": km, "pixel_footprint_m": round(d * ifov_rad(hfov, w), 3)}
        for t in TIERS:
            row[f"geometric_error_bound_m_tier{t['tier']}"] = round(
                geometric_error_bound_m(t["maximum_screen_space_error"], d, hfov, w), 3)
        curve.append(row)

    return {
        "lane": "terrain.horizon_lod.alpine",
        "label": "visual-only",
        "scenario": "alpine",
        "ground": "Google Photorealistic 3D Tiles via Cesium for Unreal (unchanged; this lane sets "
                  "level of detail only and ships no terrain data)",
        "shot": {**s, "vfov_deg": round(vfov, 3), "focal_px": round(focal_px, 2),
                 "ifov_mrad": round(1000.0 * ifov_rad(hfov, w), 5)},
        "earth_radius_m": EARTH_RADIUS_M,
        "horizon": {
            "model": "geometric, no refraction (the engine draws straight rays)",
            "height_above_reference_m": h_ref,
            "range_km": round(d_h / 1000.0, 2),
            "dip_deg": round(dip, 4),
            "predicted_row_px_at_assumed_pitch": round(horizon_row, 1),
            "skyline_resolvable_range_km": round(resolvable_km(), 1),
            "peak_visible_to_km": {
                "4000 m summit": round((d_h + horizon_distance_m(4000.0 - s["reference_ground_amsl_m"])) / 1000.0, 1),
            },
            "real_world_refracted_range_km": round(d_h / math.sqrt(1.0 - REFRACTION_K) / 1000.0, 2),
            "refraction_k_recorded_only": REFRACTION_K,
        },
        "reference": {"maximum_screen_space_error": REFERENCE_SSE,
                      "what": "today's beauty frame (FLIGHTSIM_GOOGLE_TILES_BEAUTY_SSE default)",
                      "est_tiles_drawn": round(ref_tiles)},
        "near_ground_range_m": round(near_range, 1),
        "calibration": CALIBRATION,
        "tiers": tiers,
        "fallback": FALLBACK,
        "gsd_curve": curve,
        "gate": {
            "gsd_ratio_max": {"0": 1.10, "1": 0.92, "2": 0.80, "3": 0.65},
            "horizon_range_min_fraction_of_baseline": 0.95,
            "horizon_range_floor_km": 100.0,
            "status": "UNMEASURED: run measure_horizon_lod.py on Windows frames",
        },
    }


def write(out_dir: Path = LANE) -> dict:
    plan = build()
    (out_dir / "alpine_horizon_lod.json").write_text(
        json.dumps(plan, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    with (out_dir / "alpine_horizon_lod_curve.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(plan["gsd_curve"][0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(plan["gsd_curve"])
    return plan


if __name__ == "__main__":
    p = write()
    print(f"horizon {p['horizon']['range_km']} km, dip {p['horizon']['dip_deg']} deg")
    for t in p["tiers"]:
        print(f"tier {t['tier']}: SSE {t['maximum_screen_space_error']}, est {t['est_tiles_drawn']} tiles, "
              f"est {t['est_vram_mb']} MB (ESTIMATE)")
