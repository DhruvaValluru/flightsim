"""The datum null test (gap P10, blueprint section 5, D1): the same flight
with and without the spec's datum block, measured.

Two claims, each measured here on a synthetic bake through the REAL bake
path (``core.terrain.glo30.bake`` with the tile fetch replaced by a
synthetic 0.2 x 0.2 degree peak at 45.9 N 7.1 E, as tests/test_geoid.py
bakes it; a real GLO-30 bake is the networked step):

1. **Bounded invariance.** A spec that states the datum block (vertical
   orthometric, physics frame orthometric, the bake's geoid model
   declared) and the same spec without it fly the SAME flight: the two
   ``output_digest`` values are identical (the block declares and
   checks; it moves nothing inside the simulation). Recorded as a
   ``bounded`` NullTest: differing recorded columns 0 against 0, bound 0.
2. **Reached at export.** The ECEF position formed from ``hae_m``
   (altitude + N, the datum applied where a coordinate leaves the
   system) sits radially N0 further from the Earth's centre than the
   one formed from JSBSim's altitude alone -- the branch's error before
   the block -- at every sample: N0 +- 0.5 m (the altitude null floor).
   Recorded as a ``reached`` NullTest with N0 as the with-value and 0 as
   the without-value.

Everything measured is printed and written to ``runs/datum_null_test/
datum_null_test.json`` (``--out`` to move it). The geoid model is the
bake's choice: EGM2008 when the grid is in the bake cache, else EGM96
(said so in the report).

NOT claimed: a real place (the tile is synthetic; the origin's N is real
because the geoid grid is), any pixel (no engine here), and the per-sample
variation of N over the scene (N is the origin's for the whole flight;
its range over the bbox is in the datum block).

Usage: ``.venv/bin/python -m experiments.datum_null_test [--out DIR]
[--aircraft c172p] [--seconds 3]``
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.interop.geodesy import geodetic_to_ecef  # noqa: E402
from core.nl.compiler import compile_prompt  # noqa: E402
from core.records import NullTest  # noqa: E402
from core.terrain import glo30  # noqa: E402
from core.terrain.geoid import egm2008_available  # noqa: E402
from core.terrain.ground import TerrainGround  # noqa: E402
from core.terrain.heightfield import Heightfield  # noqa: E402

#: The synthetic scene: the same peak tests/test_geoid.py bakes.
LOCATION = glo30.Location(
    key="testpeak", title="synthetic test peak (datum null test)", tiles=("X",),
    bbox=(45.82, 45.98, 7.02, 7.18), crs="EPSG:32632",
    origin_lat=45.9, origin_lon=7.1, snowline_m=2500.0,
    summits=(("Test Peak", 45.9, 7.1, 3000.0),))
#: The altitude null floor (core/record_null.py): 10 x the V9 noise.
RADIAL_TOLERANCE_M = 0.5


def synthetic_tile(path: Path, lat0: float, lon0: float) -> Path:
    from core.terrain.dem import write_geotiff

    n = 240
    lats = np.linspace(lat0 + 0.2, lat0, n)
    lons = np.linspace(lon0, lon0 + 0.2, n)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    distance = np.hypot((lat_grid - (lat0 + 0.1)) * 111e3, (lon_grid - (lon0 + 0.1)) * 78e3)
    z = 800.0 + 2200.0 * np.exp(-(distance / 6500.0) ** 2)
    return write_geotiff(path, z.astype(np.float32), "EPSG:4326", lon0, lat0 + 0.2, 0.2 / n)


def bake_synthetic(out_dir: Path, geoid_model: str = "auto") -> Path:
    """The synthetic peak through the real bake path; returns the .r16."""
    cache = out_dir / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    original = glo30.fetch
    glo30.fetch = lambda loc, cache_dir: [synthetic_tile(glo30.tile_path(Path(cache_dir), "X"), 45.8, 7.0)]
    try:
        raw, _ = glo30.bake(LOCATION, cache, out_dir / "bake", ground_sample_distance_m=90.0,
                            geoid_model=geoid_model)
    finally:
        glo30.fetch = original
    return raw


def spec_over(bake: Heightfield, aircraft: str, seconds: int, with_block: bool):
    spec = compile_prompt(f"fly the {aircraft} at 4000 m and 100 kt for {seconds} seconds",
                          name="datum_null_" + ("with" if with_block else "without"))
    spec.set("hold_state", False, frm="datum null test: trim controls held")
    spec.set("latitude", LOCATION.origin_lat, frm="datum null test: over the synthetic peak")
    spec.set("longitude", LOCATION.origin_lon, frm="datum null test: over the synthetic peak")
    spec.set("terrain_elevation", 3000.0, frm="datum null test: the peak")
    if with_block:
        model = bake.provenance["datum"]["geoid_model_key"]
        spec.set("datum.vertical", "orthometric", frm="datum null test: the block stated")
        spec.set("datum.physics_frame", "orthometric", frm="datum null test: the block stated")
        spec.set("datum.geoid_model", model, frm="datum null test: the bake's model declared")
    return spec


def radial_m(lat: float, lon: float, h: float) -> float:
    x, y, z = geodetic_to_ecef(lat, lon, h)
    return math.sqrt(x * x + y * y + z * z)


def measure(out_dir: Path, aircraft: str = "c172p", seconds: int = 3) -> Dict[str, Any]:
    from core.scenario.runner import run_spec

    out_dir.mkdir(parents=True, exist_ok=True)
    raw = bake_synthetic(out_dir)
    bake = Heightfield.read(raw)
    datum = bake.provenance["datum"]
    n0 = float(datum["undulation_m"])
    results = {}
    t0 = time.perf_counter()
    for with_block in (True, False):
        spec = spec_over(bake, aircraft, seconds, with_block)
        results[with_block] = run_spec(spec, terrain_ground=TerrainGround(bake))
    elapsed = time.perf_counter() - t0
    with_run, without_run = results[True], results[False]
    # 1. the invariance: the two flights are one flight.
    digests_identical = with_run.output_digest == without_run.output_digest
    columns_changed = sum(
        1 for name in with_run.telemetry.columns
        if name not in with_run.telemetry.derived
        and with_run.telemetry.columns[name] != without_run.telemetry.columns.get(name))
    invariance = NullTest(
        quantity="recorded telemetry columns that differ between the flight with the spec "
                 "datum block and the flight without it",
        unit="columns", with_value=float(columns_changed), without_value=0.0, threshold=0.0,
        kind="bounded",
        note=f"output digests {'identical' if digests_identical else 'DIFFER'}: "
             f"{with_run.output_digest[:16]} with, {without_run.output_digest[:16]} without")
    # 2. the export: ECEF radial difference with the datum applied vs without.
    cols = with_run.telemetry.columns
    radial = [radial_m(la, lo, hae) - radial_m(la, lo, alt)
              for la, lo, hae, alt in zip(cols["lat_deg"], cols["lon_deg"], cols["hae_m"], cols["altitude_m"])]
    radial = np.asarray(radial)
    worst = int(np.argmax(np.abs(radial - n0)))
    first_with = radial_m(cols["lat_deg"][0], cols["lon_deg"][0], cols["hae_m"][0])
    first_without = radial_m(cols["lat_deg"][0], cols["lon_deg"][0], cols["altitude_m"][0])
    export = NullTest(
        quantity="ECEF radial distance from the Earth's centre of the exported position "
                 "(hae_m = altitude + N) against the same position with JSBSim's altitude "
                 "taken as ellipsoidal (the branch before the block), first sample",
        unit="m", with_value=first_with, without_value=first_without,
        threshold=abs(n0) - RADIAL_TOLERANCE_M, kind="reached",
        note=f"the difference is N0 = {n0:+.3f} m within {RADIAL_TOLERANCE_M} m at every sample: "
             f"measured mean {radial.mean():+.4f} m, worst |difference - N0| "
             f"{np.max(np.abs(radial - n0)):.2e} m over {len(radial)} samples")
    export_bounded = NullTest(
        quantity="ECEF radial difference (exported minus JSBSim-as-ellipsoidal) at the sample "
                 "furthest from N0, against N0",
        unit="m", with_value=float(radial[worst]), without_value=n0,
        threshold=RADIAL_TOLERANCE_M, kind="bounded",
        note="the export applies exactly the origin's N: the residual is the angle between "
             "the ellipsoidal normal and the geocentric radius (N sin^2 of ~0.19 deg)")
    record = [r for r in with_run.manifest["applied_variables"]["applied_variables"]
              if r["name"] == "scene.geoid_undulation_m"][0]
    report = {
        "experiment": "datum_null_test", "aircraft": aircraft, "seconds": seconds,
        "bake": {"path": str(raw), "geoid_model": datum["geoid_model_key"],
                 "interpolation": datum["interpolation"], "undulation_m": n0,
                 "undulation_bilinear_m": datum.get("undulation_bilinear_m"),
                 "gtx": datum["gtx"]["file"], "gtx_sha256": datum["gtx"]["sha256"],
                 "egm2008_cached": egm2008_available()},
        "digests": {"with": with_run.output_digest, "without": without_run.output_digest,
                    "identical": digests_identical},
        "samples": len(radial), "elapsed_s": elapsed,
        "invariance": invariance.to_dict(),
        "export": export.to_dict(),
        "export_bounded": export_bounded.to_dict(),
        "radial_difference_m": {"mean": float(radial.mean()), "min": float(radial.min()),
                                "max": float(radial.max()),
                                "worst_abs_error_vs_n0": float(np.max(np.abs(radial - n0)))},
        "run_record": record,
        "spec_with_block": with_run.manifest["spec"].get("datum"),
        "not_claimed": ("the tile is synthetic (the origin's N is real: the geoid grid is); "
                        "no pixel; N is the origin's for the whole flight"),
    }
    (out_dir / "datum_null_test.json").write_text(json.dumps(report, indent=1) + "\n",
                                                  encoding="utf-8")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(REPO / "runs" / "datum_null_test"))
    ap.add_argument("--aircraft", default="c172p")
    ap.add_argument("--seconds", type=int, default=3)
    args = ap.parse_args(argv)
    report = measure(Path(args.out), args.aircraft, args.seconds)
    inv, exp = report["invariance"], report["export"]
    print(f"datum null test ({args.aircraft}, {args.seconds} s, {report['samples']} samples, "
          f"{report['elapsed_s']:.1f} s): bake {report['bake']['geoid_model']} "
          f"{report['bake']['interpolation']} N0 = {report['bake']['undulation_m']:+.3f} m")
    print(f"  bounded: output digest identical with and without the datum block: "
          f"{report['digests']['identical']} ({inv['with']:.0f} recorded columns differ; ok {inv['ok']})")
    bounded = report["export_bounded"]
    print(f"  reached: ECEF radial distance with the datum applied at export minus without "
          f"= {exp['difference']:+.4f} m (N0 = {report['bake']['undulation_m']:+.3f} m, threshold "
          f"{exp['threshold']:.3f} m; ok {exp['ok']}); bounded: worst sample {bounded['with']:+.4f} m "
          f"vs N0, |d - N0| {report['radial_difference_m']['worst_abs_error_vs_n0']:.2e} m "
          f"<= {bounded['threshold']} m; ok {bounded['ok']}")
    print(f"  written: {Path(args.out) / 'datum_null_test.json'}")
    return 0 if (inv["ok"] and exp["ok"] and bounded["ok"]) else 1


if __name__ == "__main__":
    sys.exit(main())
