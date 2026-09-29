"""Rasterise ESA WorldCover land cover onto a baked terrain -- any OS.

    .venv/bin/python scripts/bake_landcover.py --location yosemite \
        --cache data/worldcover --out runs/terrain

Reads the bake ``<out>/<location>.r16`` + ``.json`` (what
scripts/bake_terrain.py writes; ``--bake PATH`` for another), fetches only
the scene's window of the WorldCover 2021 v200 tile (``/vsicurl/``, or a
whole tile already in ``--cache`` under its bucket name; ``--source TIF``
takes a local WorldCover-format raster and touches no network), and
writes ``<out>/<location>_landcover/``: one ``<class>_weight.png`` per
legend class (0-255 = fraction of 10 m cells in each bake cell, summing
to exactly 255 with nodata), ``class_map.png`` (majority code) and
``landcover.json`` (classes, fractions, source sha256, licence,
attribution, grid, the ``scene.landcover`` applied-variable record).

Then, beside the bake-grid maps (W1; ``--no-landscape`` skips it): the
Landscape-resolution layers ``<location>_landcover_<code>.u8`` (one uint8
layer per class on the heightmap's own sample positions, summing to 255
at every texel; core/terrain/weightmaps.py) with their sidecar
``<location>_landcover_layers.json``, the Landscape heightmap
``<location>_landscape.r16`` and its import manifest
``<location>_landscape.json`` carrying ``weight_layers``, the bake's
``datum`` block and the bake's sha256 (core/terrain/landscape.py), and
the round trip verified here (heights, layer sums, layouts, digests).

Refusals print one ``REFUSED -- <name>: ...`` line and exit 1:
``terrain.landcover_grid`` (no bake sidecar or no grid in it),
``terrain.landcover`` (tile unreachable, not the product, values outside
the legend, or the rasterised window disagreeing with its source),
``landcover.legend`` (a class code outside the legend has no taxonomy
word), ``terrain.landscape_missing`` (the bake carries no datum block to
copy into the import manifest), ``terrain.landscape_layout`` and
``terrain.landscape_stale`` (a layer of another layout; a bake or layer
whose digest is not the manifest's).

The data is CC BY 4.0: the attribution line printed at the end must
travel with any dataset built on these weightmaps. Nothing in the engine
reads the weightmaps or the layers yet: the Landscape layer import in
the editor is W5 (a Windows step); this is the data pipeline only.
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.terrain.glo30 import LOCATIONS  # noqa: E402
from core.terrain.heightfield import Heightfield  # noqa: E402
from core.terrain.landcover import (  # noqa: E402
    ATTRIBUTION, LEGEND, LICENSE, LandcoverError, LandcoverGridError, rasterise,
)
from core.terrain.landscape import (  # noqa: E402
    LandscapeManifestError, bake_datum_block, export as export_landscape,
    import_manifest, verify_round_trip,
)
from core.terrain.weightmaps import LandcoverLegendError, export_layers  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--location", required=True,
                    help=f"curated location key ({', '.join(LOCATIONS)}), or "
                         f"any name when --bake is given")
    ap.add_argument("--cache", required=True,
                    help="cache dir for the fetched WorldCover window")
    ap.add_argument("--out", required=True,
                    help="terrain dir holding <location>.r16/.json; the "
                         "<location>_landcover/ directory is written here")
    ap.add_argument("--bake", default=None,
                    help="bake path (default <out>/<location>.r16)")
    ap.add_argument("--source", default=None,
                    help="local WorldCover-format GeoTIFF instead of the bucket")
    ap.add_argument("--no-landscape", action="store_true",
                    help="write the bake-grid maps only; skip the Landscape-"
                         "resolution layers, heightmap and import manifest")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    bake = Path(args.bake) if args.bake else out_dir / f"{args.location}.r16"
    if args.location in LOCATIONS:
        target = LOCATIONS[args.location]
    elif args.bake:
        target = bake
    else:
        print(f"unknown location: {args.location} -- curated: "
              f"{', '.join(LOCATIONS)}; or give --bake PATH")
        return 2

    try:
        scene_dir, document = rasterise(
            target, args.cache, out_dir, bake_path=bake, source_4326=args.source)
    except (LandcoverError, LandcoverGridError) as exc:
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        return 1

    print(f"  {args.location:<18} land cover written to {scene_dir}")
    grid = document["grid"]
    print(f"  {'':<18} grid {grid['width']} x {grid['height']} cells of "
          f"{grid['cell_size_m']:g} m in {grid['crs']}, "
          f"{grid['texels_per_cell']} x {grid['texels_per_cell']} fine cells each")
    for entry in LEGEND:
        fraction = document["fractions"][entry.key]
        if fraction > 0:
            print(f"  {'':<18} {entry.title:<26} {fraction * 100:6.2f} %")
    print(f"  {'':<18} nodata {document['nodata_fraction'] * 100:.2f} %; "
          f"dominant {document['dominant_class']}; weights sum "
          f"{document['weight_sum_per_cell']['min']}..{document['weight_sum_per_cell']['max']}")
    v = document["verification_vs_source"]
    print(f"  {'':<18} verified against the source window: "
          f"{v['agreement'] * 100:.1f} % of {v['samples']} texels agree")
    print(f"  {'':<18} source sha256 {document['sha256']}")
    if not args.no_landscape:
        code = landscape_step(scene_dir, bake, args.location)
        if code:
            return code
    print(f"  {'':<18} licence {LICENSE}; attribution required: {ATTRIBUTION}")
    return 0


def landscape_step(scene_dir: Path, bake: Path, key: str) -> int:
    """The Landscape-resolution layers, the heightmap and the import
    manifest with the datum, verified; a refusal prints its name and
    returns 1."""
    try:
        field = Heightfield.read(bake)
        bake_datum_block(field)       # a bake without its datum refuses before anything is written
        sidecar, layers = export_layers(scene_dir)
        spec = export_landscape(field, scene_dir / f"{bake.with_suffix('').name}_landscape")
        manifest = import_manifest(field, spec, layers["layers"], layer_dir=scene_dir)
        result = verify_round_trip(field, spec, manifest, scene_dir)
    except (LandcoverError, LandcoverLegendError, LandscapeManifestError) as exc:
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        return 1
    layout = layers["layout"]
    print(f"  {'':<18} Landscape layers {len(layers['layers'])} x "
          f"{layout['resolution']}x{layout['resolution']} "
          f"({layout['components']} components x {layout['sections_per_component']} "
          f"sections x {layout['quads_per_section']} quads + 1) in {sidecar.name}; "
          f"sum per texel {layers['sum_per_texel']['min']}..{layers['sum_per_texel']['max']}")
    rt = layers["argmax_round_trip"]
    print(f"  {'':<18} argmax round trip: {rt['agreement'] * 100:.2f} % of "
          f"{rt['texels']} texels reproduce the bake's dominant class; "
          f"{layers['alignment']['exact_texels']} exact texels agree to the count")
    print(f"  {'':<18} import manifest {spec.raw_path.with_suffix('.json').name}: "
          f"heights within {result['max_error_m']:.4f} m "
          f"(quantisation {result['quantisation_m']:.4f} m), layers sum "
          f"{result['layers']['sum_min']}..{result['layers']['sum_max']}, datum "
          f"{manifest['datum'].get('vertical_datum_of_heights')!r} copied, bake sha256 "
          f"{manifest['bake']['sha256'][:12]}...")
    print(f"  {'':<18} the Landscape layer import in the editor is W5 (Windows); "
          f"nothing engine-side is verified here")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
