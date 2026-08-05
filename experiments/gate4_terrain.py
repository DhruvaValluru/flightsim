"""Gate 4 -- terrain: one pipeline, two producers, correct metres.

    Elevation queried through the FDM interface matches the source DEM to within
    interpolation error, for both real and procedural terrain, through the
    identical code path. Slope distribution of generated terrain is physically
    plausible. Round-trip a known elevation through DEM -> heightmap ->
    Landscape -> query and confirm the metres come back correct -- this is the
    most common source of "my mountain is the wrong height". (§5 Phase 4)

The "identical code path" clause is the one that carries the research design.
If procedural and real terrain reach the FDM through the same interface, then
terrain statistics are a controllable independent variable measured in the same
units either way. If they reach it through two paths, every comparison between
them also compares the two paths.

The DEM used here is written as a real GeoTIFF in a geographic CRS and read back
through GDAL, so ingestion is exercised against the parts most likely to be
wrong -- the CRS handling and the reprojection -- rather than against a numpy
array handed straight to the baker.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.terrain import dem, landscape, synthesis  # noqa: E402
from core.terrain.ground import TerrainGround, terrain_field_from  # noqa: E402
from core.terrain.heightfield import Heightfield  # noqa: E402
from core.terrain.synthesis import TerrainStatistics  # noqa: E402

RULE = "=" * 96

#: Real terrain rarely sustains past this (§3.2). Checked as a high percentile
#: rather than a maximum: a single steep pixel is a cliff, and cliffs exist.
PLAUSIBLE_P99_SLOPE_DEG = 45.0


def make_reference_dem(path: Path, size: int = 240) -> Tuple[Path, np.ndarray]:
    """A GeoTIFF in EPSG:4326 with an analytically known surface.

    Analytic on purpose: the elevation at any coordinate is known in closed
    form, so ingestion error can be measured against truth rather than against
    another implementation of the same thing.
    """
    lon0, lat0 = 12.0, 46.0
    pixel_deg = 0.001
    rows = np.arange(size)
    cols = np.arange(size)
    cc, rr = np.meshgrid(cols, rows)
    # Two crossed cosines plus a ramp: smooth, no aliasing, unique per pixel.
    z = (800.0
         + 300.0 * np.cos(2 * math.pi * cc / 60.0)
         + 200.0 * np.cos(2 * math.pi * rr / 90.0)
         + 0.5 * cc)
    dem.write_geotiff(path, z, "EPSG:4326", lon0, lat0 + size * pixel_deg,
                      pixel_deg)
    return path, z


def report_statistics(field: Heightfield, label: str) -> None:
    stats = field.statistics()
    slopes = field.slope_degrees()
    print(f"  {label}")
    print(f"    {field!r}")
    print(f"    relief {stats['relief_m']:8.1f} m   rms height "
          f"{stats['rms_height_m']:7.1f} m   quantisation "
          f"{stats['quantisation_m'] * 100:.2f} cm")
    print(f"    slope  median {np.percentile(slopes, 50):5.1f}  "
          f"p95 {np.percentile(slopes, 95):5.1f}  "
          f"p99 {np.percentile(slopes, 99):5.1f}  max {slopes.max():5.1f} deg")


def check_identical_interface(real: Heightfield, procedural: Heightfield
                              ) -> Tuple[bool, List[str]]:
    """Both kinds of terrain must be the same type, queried the same way."""
    notes = []
    ok = True
    if type(real) is not type(procedural):
        notes.append(f"different types: {type(real)} vs {type(procedural)}")
        ok = False

    real_ground = TerrainGround(real)
    procedural_ground = TerrainGround(procedural)
    if type(real_ground) is not type(procedural_ground):
        notes.append("different ground-callback types")
        ok = False

    # The query returns a finite elevation for both, through the same call.
    for name, ground in (("real", real_ground), ("procedural", procedural_ground)):
        lon, lat = ground.centre_lonlat()
        elevation = ground.elevation_at(lat, lon)
        if not math.isfinite(elevation):
            notes.append(f"{name} terrain returned a non-finite elevation")
            ok = False
        else:
            notes.append(f"{name}: elevation_at(centre) = {elevation:.2f} m")
    return ok, notes


def check_dem_fidelity(source_path: Path, field: Heightfield,
                       source: np.ndarray) -> Tuple[bool, List[str]]:
    """Baked elevations must match the source DEM to within interpolation error."""
    import rasterio
    from pyproj import Transformer

    notes = []
    with rasterio.open(source_path) as src:
        transform = src.transform
        to_utm = Transformer.from_crs(src.crs, field.georeference.crs,
                                      always_xy=True)
        rng = np.random.default_rng(11)
        rows = rng.integers(5, src.height - 5, 400)
        cols = rng.integers(5, src.width - 5, 400)

        errors = []
        for r, c in zip(rows, cols):
            lon, lat = transform * (c + 0.5, r + 0.5)
            x, y = to_utm.transform(lon, lat)
            if not field.contains(x, y):
                continue
            errors.append(abs(field.elevation_at(x, y) - source[r, c]))

    errors = np.array(errors)
    # Tolerance is derived, not guessed: resampling a surface with this much
    # local curvature onto a coarser grid, plus the 16-bit quantisation.
    gradient = np.abs(np.diff(source, axis=1)).mean()
    tolerance = max(4.0 * gradient, 10.0 * field.quantisation_m)
    ok = bool(len(errors) > 100 and errors.max() < tolerance)
    notes.append(f"{len(errors)} sample points, max error {errors.max():.3f} m, "
                 f"mean {errors.mean():.3f} m")
    notes.append(f"tolerance {tolerance:.3f} m "
                 f"(4x mean pixel gradient {gradient:.3f} m, "
                 f"quantisation {field.quantisation_m:.4f} m)")
    return ok, notes


def check_slope_plausibility(field: Heightfield) -> Tuple[bool, List[str]]:
    slopes = field.slope_degrees()
    p99 = float(np.percentile(slopes, 99))
    ok = p99 < PLAUSIBLE_P99_SLOPE_DEG
    return ok, [
        f"p99 slope {p99:.1f} deg (limit {PLAUSIBLE_P99_SLOPE_DEG:.0f}); "
        f"median {np.percentile(slopes, 50):.1f}, max {slopes.max():.1f}"
    ]


def check_landscape_round_trip(field: Heightfield, out_dir: Path
                               ) -> Tuple[bool, List[str]]:
    """DEM -> heightmap -> Landscape encoding -> query, in metres."""
    spec = landscape.export(field, out_dir / f"{field.name}_landscape")
    result = landscape.verify_round_trip(field, spec)
    notes = [line for line in spec.describe().splitlines()]
    notes.append(
        f"decoded vs source: max error {result['max_error_m']:.4f} m, "
        f"mean {result['mean_error_m']:.4f} m"
    )
    notes.append(
        f"relief preserved: resampled {result['resampled_relief_m']:.2f} m -> "
        f"landscape {result['landscape_relief_m']:.2f} m "
        f"(error {result['relief_error_m']:.4f} m; source raster "
        f"{result['source_relief_m']:.2f} m)"
    )
    notes.append(
        f"aspect ratio: source {result['aspect_source']:.4f} -> landscape "
        f"{result['aspect_landscape']:.4f} (error {result['aspect_error']:.5f})"
    )
    # The encoding must be exactly invertible up to its own quantisation, and
    # the ground must not be squashed.
    tolerance = 4.0 * result["quantisation_m"]
    ok = (result["max_error_m"] < tolerance
          and result["relief_error_m"] < tolerance
          and result["aspect_error"] < 1e-6)
    notes.append(f"tolerance {tolerance:.4f} m (4x landscape quantisation "
                 f"{result['quantisation_m']:.5f} m)")
    return ok, notes


def check_orographic_coupling(field: Heightfield) -> Tuple[bool, List[str]]:
    """Orographic lift must now run over the baked raster, not an analytic ridge."""
    from core.environment.terrain_field import OrographicWind

    terrain = terrain_field_from(field)
    provider = OrographicWind(terrain, 15.0, 180.0)
    # Sample across the raster's own extent rather than a fixed distance: a
    # 3 km transect over terrain whose dominant wavelength is 5.4 km can be
    # monotonic, and would report "no downdraught" for a landscape that plainly
    # has both faces.
    _, extent_y = field.extent_m
    half = extent_y * 0.45
    samples = [provider.linear_updraught(n, 0.0)
               for n in np.linspace(-half, half, 81)]
    positive = max(samples)
    negative = min(samples)
    ok = positive > 0.05 and negative < -0.05
    return ok, [
        f"terrain '{terrain.name}' drives w from {negative:+.3f} to "
        f"{positive:+.3f} m/s along a {2 * half / 1000:.1f} km transect",
        "updraught and downdraught both present, as a real ridge produces",
    ]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 4")
    ap.add_argument("--out", default="build/terrain")
    ap.add_argument("--size", type=int, default=256)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"\n{RULE}\n1. both producers write the same raster format\n{RULE}")
    source_path, source = make_reference_dem(out / "reference_dem.tif")
    real = dem.ingest(source_path, target_crs="EPSG:32633",
                      ground_sample_distance_m=60.0, name="reference_dem")
    procedural = synthesis.generate(
        size=args.size, pixel_size_m=60.0, seed=4,
        statistics=TerrainStatistics(hurst=0.8, rms_slope_deg=20.0,
                                     outer_scale_m=6000.0),
        name="procedural",
    )
    report_statistics(real, "ingested DEM")
    report_statistics(procedural, "synthesised terrain")

    results: List[Tuple[str, bool]] = []

    interface_ok, notes = check_identical_interface(real, procedural)
    print("\n  identical query interface:")
    for note in notes:
        print(f"    {note}")
    results.append(("real and procedural share one interface", interface_ok))

    print(f"\n{RULE}\n2. baked elevations match the source DEM\n{RULE}")
    fidelity_ok, notes = check_dem_fidelity(source_path, real, source)
    for note in notes:
        print(f"  {note}")
    results.append(("DEM fidelity within interpolation error", fidelity_ok))

    print(f"\n{RULE}\n3. generated terrain has a plausible slope distribution\n{RULE}")
    slope_ok, notes = check_slope_plausibility(procedural)
    for note in notes:
        print(f"  {note}")
    results.append(("procedural slope distribution plausible", slope_ok))

    print(f"\n{RULE}\n4. Landscape round trip -- do the metres come back?\n{RULE}")
    all_round_trips = True
    for field in (real, procedural):
        print(f"  {field.name}:")
        ok, notes = check_landscape_round_trip(field, out)
        for note in notes:
            print(f"    {note}")
        all_round_trips = all_round_trips and ok
    results.append(("Landscape round trip preserves metres", all_round_trips))

    print(f"\n{RULE}\n5. orographic lift now runs over baked terrain\n{RULE}")
    for field in (real, procedural):
        ok, notes = check_orographic_coupling(field)
        print(f"  {field.name}:")
        for note in notes:
            print(f"    {note}")
        results.append((f"orographic coupling over {field.name}", ok))

    print(f"\n{RULE}\n6. persistence round trip\n{RULE}")
    written = procedural.write(out / "procedural")
    reloaded = Heightfield.read(out / "procedural")
    persist_ok = (reloaded.digest() == procedural.digest()
                  and reloaded.elevation_at(100.0, 100.0)
                  == procedural.elevation_at(100.0, 100.0))
    print(f"  wrote {written}")
    print(f"  digest {procedural.digest()[:16]} -> {reloaded.digest()[:16]} "
          f"{'match' if persist_ok else 'MISMATCH'}")
    results.append(("raster persists bit-identically", persist_ok))

    print(f"\n{RULE}\nGATE 4\n{RULE}")
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    everything = all(ok for _, ok in results)
    print(f"\n  GATE 4: {'PASS' if everything else 'FAIL'}")
    return 0 if everything else 1


if __name__ == "__main__":
    raise SystemExit(main())
