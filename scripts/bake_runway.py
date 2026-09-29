"""Bake a runway's flatten pad, markings raster and record beside a bake.

    .venv/bin/python scripts/bake_runway.py --bake runs/terrain/control_ridge \\
        --designator 09 --threshold-lat 45.90 --threshold-lon 7.08 --heading 90 \\
        --length 1200 --width 30 [--surface asphalt] [--shoulder 60] [--null-test]
    .venv/bin/python scripts/bake_runway.py --bake runs/terrain/<key> --spec scenario.yaml

Writes, beside the bake (or under ``--out``):

* ``<key>_runway_<designator>.r16`` + ``.json`` -- the NEW bake: the
  parent's raster with the runway's plane over its footprint and a graded
  shoulder, its own sha256, the parent's provenance extended with the pad
  block (core.terrain.glo30.bake_runway_pad);
* ``<key>_runway_<designator>_markings.png`` -- the Annex 14 section 5.2
  markings at 0.1 m per pixel;
* ``<key>_runway_<designator>_record.json`` -- the geometry, the marking
  measurement (painted area against the analytic sum, the stripe counts),
  the section 5.3 light positions with the photometry named as missing,
  the pad statistics and the ``scene.runway`` record; with ``--null-test``
  the c172p is flown 1 s over the pad and over the parent and h_agl at the
  threshold with against without is the record's null test.

Refusals print one ``REFUSED -- <name>: ...`` line and exit 1:
``runway.geometry``, ``runway.taxonomy``, ``runway.markings``,
``runway.terrain_mismatch``. The parent bake is never modified.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.scene import runway as rw  # noqa: E402
from core.terrain.glo30 import bake_runway_pad  # noqa: E402
from core.terrain.heightfield import Heightfield  # noqa: E402


def spec_from_args(args) -> rw.RunwaySpec:
    if args.spec:
        from core.scenario.spec import ScenarioSpec

        spec = ScenarioSpec.read(Path(args.spec))
        block = getattr(spec, "runway", None)
        resolved = rw.RunwaySpec.from_block(block)
        if resolved is None:
            raise rw.RunwayError("runway.geometry", f"{args.spec} states no runway designator")
        return resolved
    missing = [name for name in ("designator", "threshold_lat", "threshold_lon", "heading",
                                 "length", "width") if getattr(args, name) is None]
    if missing:
        raise rw.RunwayError("runway.geometry",
                             f"--{', --'.join(m.replace('_', '-') for m in missing)} needed "
                             f"(or --spec)")
    return rw.RunwaySpec(designator=args.designator, threshold_lat_deg=args.threshold_lat,
                         threshold_lon_deg=args.threshold_lon, heading_deg=args.heading,
                         length_m=args.length, width_m=args.width, surface=args.surface,
                         markings=args.markings)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bake", required=True, help="the parent bake stem (<stem>.r16 + .json)")
    ap.add_argument("--spec", default=None, help="a scenario YAML whose runway block is used")
    ap.add_argument("--designator", default=None)
    ap.add_argument("--threshold-lat", type=float, default=None)
    ap.add_argument("--threshold-lon", type=float, default=None)
    ap.add_argument("--heading", type=float, default=None)
    ap.add_argument("--length", type=float, default=None)
    ap.add_argument("--width", type=float, default=None)
    ap.add_argument("--surface", default="asphalt")
    ap.add_argument("--markings", default="standard")
    ap.add_argument("--shoulder", type=float, default=rw.DEFAULT_SHOULDER_M)
    ap.add_argument("--out", default=None, help="directory for the outputs (default: beside the bake)")
    ap.add_argument("--null-test", action="store_true",
                    help="fly the c172p over the pad and the parent and record h_agl with vs without")
    args = ap.parse_args(argv)

    bake_stem = Path(args.bake).with_suffix("")
    if not bake_stem.with_suffix(".json").is_file():
        print(f"REFUSED -- runway.terrain_mismatch: no bake at {bake_stem} (.r16 + .json)")
        return 1
    try:
        spec = spec_from_args(args)
        raw, statistics = bake_runway_pad(bake_stem, spec, out_dir=args.out,
                                          shoulder_m=args.shoulder)
    except rw.RunwayError as exc:
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        return 1
    pad_stem = raw.with_suffix("")
    pad = Heightfield.read(pad_stem)
    parent = Heightfield.read(bake_stem)
    geometry = rw.RunwayGeometry.for_spec(spec, pad.georeference.crs)
    raster, rects, counts = rw.markings_raster(spec)
    measurement = rw.measure_markings(raster, rects)
    png = rw.write_markings_png(raster, rw.markings_path_for(pad_stem))
    markings = rw.markings_block(spec, png, counts, measurement)
    lights, light_counts = rw.light_positions(spec)
    lights_block = {"counts": light_counts, "positions": lights}
    pad_block = {"key": pad.name, "stem": str(pad_stem), "sha256": pad.digest(),
                 "parent_stem": str(bake_stem), "parent_sha256": parent.digest(),
                 "statistics": statistics}
    null_test = None
    if args.null_test:
        measured = rw.measure_pad_null(pad_stem, bake_stem, spec)
        null_test = measured["null_test"]
        pad_block["null_measurement"] = {k: v for k, v in measured.items() if k != "null_test"}
    document = rw.runway_document(spec, geometry, markings, lights_block, pad_block, null_test)
    record_path = rw.write_runway_document(document, rw.document_path_for(pad_stem))

    print(f"  pad bake     {raw} (sha256 {pad.digest()[:16]}; parent {parent.digest()[:16]} untouched)")
    print(f"  plane        z = {statistics['plane']['a_m']:.2f} + {statistics['plane']['b_per_m']:+.5f} s "
          f"+ {statistics['plane']['c_per_m']:+.5f} t; footprint {statistics['footprint_pixels']} px, "
          f"shoulder {statistics['shoulder_pixels']} px; cut {statistics['max_cut_m']:.2f} m, "
          f"fill {statistics['max_fill_m']:.2f} m; ends differ {statistics['ends_difference_m']:.2f} m "
          f"(tolerance {statistics['tolerance_m']:.1f} m)")
    print(f"  markings     {png.name}: {measurement['shape'][0]} x {measurement['shape'][1]} px at "
          f"{rw.PX_M} m; painted {measurement['painted_area_m2']:.2f} m2 vs analytic "
          f"{measurement['analytic_area_m2']:.2f} m2 ({measurement['relative_error']:.2%}); "
          f"threshold stripes {counts.get('threshold_stripes')} drawn, "
          f"{measurement['threshold_stripes_read']} read back")
    print(f"  lights       {light_counts['total']} (edge {light_counts['edge']}, threshold "
          f"{light_counts['threshold']}, end {light_counts['end']}, centreline "
          f"{light_counts['centreline']}); photometry: {rw.PHOTOMETRY['candela']} (missing, named)")
    if null_test is not None:
        print(f"  null test    h_agl with {null_test['with']:.2f} m vs without "
              f"{null_test['without']:.2f} m: |difference| {abs(null_test['difference']):.2f} m "
              f"against {null_test['threshold']} m -> {'ok' if null_test['ok'] else 'NOT ok'}")
    else:
        print("  null test    not measured (pass --null-test to fly the c172p over both bakes)")
    print(f"  record       {record_path}")
    print(json.dumps({"pad": str(pad_stem), "record": str(record_path), "markings": str(png)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
