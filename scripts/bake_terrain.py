"""Bake the curated terrains the webapp renders -- one command, any OS.

    .venv/bin/python scripts/bake_terrain.py            # the showcase trio
    .venv/bin/python scripts/bake_terrain.py --all      # every curated location
    .venv/bin/python scripts/bake_terrain.py yosemite   # just one

A fresh clone has NO terrain baked, so a "mountains" prompt renders the
labeled flat slab (measured: run fc2cbf725e69 -- "the mountains didnt
load"). pick_scene (webapp/runs.py) reads runs/terrain/<key>.r16; this
writes exactly there, through the same fetch->mosaic->ingest->verify
path everything else uses (core.terrain.glo30.bake refuses to produce an
unverified bake), plus the synthesised control ridge with the SAME
parameters the showcase matrix bakes (seed 6, 28 deg RMS slope) so the
two never drift. First bake per location downloads Copernicus GLO-30
tiles (tens of MB, a few minutes); re-running skips existing bakes.
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.terrain.glo30 import LOCATIONS, bake  # noqa: E402
from core.terrain.synthesis import TerrainStatistics, generate  # noqa: E402

#: What the showcase matrix bakes; enough for every "mountains" prompt to
#: land on real terrain. --all adds the remaining curated locations.
DEFAULT_KEYS = ("matterhorn", "yosemite", "control")


def ensure_imagery(key: str, terrain_dir: Path, args) -> None:
    """The Sentinel-2 cloudless drape (core/terrain/imagery.py) beside the
    bake. Without it the renderer colours the terrain by elevation class
    alone (measured on the owner's machine: a Matterhorn render with
    "imagery": null looked untextured). Fetched once, verified, cached."""
    sidecar = terrain_dir / f"{key}_imagery.json"
    if args.no_imagery:
        return
    if sidecar.is_file() and not args.force:
        print(f"  {'':<18} imagery: drape present ({sidecar.name})")
        return
    from core.terrain.imagery import drape

    print(f"  {'':<18} imagery: fetching Sentinel-2 cloudless tiles and draping them")
    try:
        texture, verification = drape(LOCATIONS[key], terrain_dir / key,
                                      REPO / "data" / "imagery_cache", terrain_dir)
    except Exception as exc:          # the bake stands; the drape is said missing
        print(f"  {'':<18} imagery: FAILED ({type(exc).__name__}: {exc}); "
              f"the terrain renders untextured until this succeeds")
        return
    print(f"  {'':<18} imagery: {texture.name} (verified)")


def wants_other_source(raw: Path, source: str) -> bool:
    """True when a baked raster's provenance names a different dataset
    than the one asked for (a GLO-30 bake under --source 3dep is re-baked,
    not skipped); an unreadable sidecar counts as different."""
    try:
        import json

        provenance = json.loads(raw.with_suffix(".json").read_text(
            encoding="utf-8")).get("provenance", {})
    except (OSError, ValueError):
        return True
    dataset = str(provenance.get("dataset", ""))
    return ("3DEP" in dataset) != (source == "3dep")


def has_datum(raw: Path) -> bool:
    """Whether the bake's sidecar carries the vertical-datum block."""
    from core.terrain.heightfield import Heightfield

    try:
        datum = Heightfield.read(raw).provenance.get("datum") or {}
    except Exception:
        return False
    return isinstance(datum.get("undulation_m"), (int, float))


def datum_line(key: str, raw: Path) -> str:
    """The vertical-datum line for a bake (P10), read back from ITS
    sidecar: the geoid undulation at the origin, the interpolation
    bound, and the ellipsoidal height of the origin. A bake from before
    the datum block says so rather than printing a number it lacks."""
    from core.terrain.heightfield import Heightfield

    datum = Heightfield.read(raw).provenance.get("datum") or {}
    n = datum.get("undulation_m")
    if not isinstance(n, (int, float)):
        return (f"  {'':<18} datum: no datum block in the sidecar (baked "
                f"before the geoid landed); re-bake to record it")
    return (f"  {'':<18} datum: heights {datum.get('vertical_datum_of_heights')}; "
            f"geoid N = {n:+.2f} m at the origin ({datum.get('geoid_model')}, "
            f"{datum.get('interpolation', 'bilinear')} "
            f"+-{datum.get('interpolation_error_bound_m', datum.get('bilinear_error_bound_m'))} m; "
            f"EGM96-EGM2008 bound {datum.get('model_difference_bound_m')} m); "
            f"origin {datum.get('orthometric_height_of_origin_m'):.1f} m "
            f"orthometric = {datum.get('ellipsoidal_height_of_origin_m'):.1f} m "
            f"ellipsoidal")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("keys", nargs="*",
                    help=f"locations to bake (default: {' '.join(DEFAULT_KEYS)}); "
                         f"curated: {', '.join(LOCATIONS)}, plus 'control'")
    ap.add_argument("--all", action="store_true",
                    help="bake every curated location and the control ridge")
    ap.add_argument("--force", action="store_true",
                    help="re-bake locations that are already baked")
    ap.add_argument("--no-imagery", action="store_true",
                    help="skip the Sentinel-2 imagery drape")
    ap.add_argument("--source", choices=("glo30", "3dep"), default="glo30",
                    help="the elevation source: Copernicus GLO-30 (30 m, "
                         "worldwide) or USGS 3DEP 1/3 arc-second (~10 m, "
                         "the United States only; core/terrain/dem3dep.py)")
    ap.add_argument("--gsd", type=float, default=None,
                    help="ground sample distance in metres (default: the "
                         "source's own, 30 for GLO-30 and 10 for 3DEP)")
    args = ap.parse_args(argv)

    keys = list(args.keys) or list(DEFAULT_KEYS)
    if args.all:
        keys = list(LOCATIONS) + ["control"]
    unknown = [k for k in keys if k != "control" and k not in LOCATIONS]
    if unknown:
        print(f"unknown location(s): {', '.join(unknown)} -- "
              f"curated: {', '.join(LOCATIONS)}, plus 'control'")
        return 2

    terrain_dir = REPO / "runs" / "terrain"
    terrain_dir.mkdir(parents=True, exist_ok=True)
    for key in keys:
        if key == "control":
            raw = terrain_dir / "control_ridge.r16"
            if raw.is_file():
                print(f"  control ridge      already baked ({raw})")
                continue
            print("  control ridge      synthesising (showcase parameters)")
            field = generate(size=1024, pixel_size_m=30.0,
                             statistics=TerrainStatistics(rms_slope_deg=28.0),
                             seed=6, base_elevation_m=600.0,
                             name="control_ridge")
            field.write(terrain_dir / "control_ridge")
            continue
        raw = terrain_dir / f"{key}.r16"
        if (raw.is_file() and not args.force and has_datum(raw)
                and not wants_other_source(raw, args.source)):
            print(f"  {key:<18} already baked ({raw})")
            print(datum_line(key, raw))
            ensure_imagery(key, terrain_dir, args)
            continue
        if raw.is_file():
            # A bake from before the datum block is refused by every
            # georeferenced run (datum.sidecar_without_datum, measured on
            # the owner's machine), so it is re-baked, not skipped. The
            # downloaded tiles are cached, so this is ingest + verify only.
            print(f"  {key:<18} re-baking ({'--force' if args.force else 'no datum block in its sidecar'})")
        elif args.source == "3dep":
            print(f"  {key:<18} baking from USGS 3DEP 1/3 arc-second "
                  f"(windowed fetch + ingest + verify)")
        else:
            print(f"  {key:<18} baking from GLO-30 (fetch + ingest + verify)")
        if args.source == "3dep":
            from core.terrain.dem3dep import NOMINAL_GSD_M, bake as bake_3dep

            bake_3dep(LOCATIONS[key], REPO / "data" / "3dep", terrain_dir,
                      ground_sample_distance_m=args.gsd or NOMINAL_GSD_M)
        else:
            bake(LOCATIONS[key], REPO / "data" / "glo30", terrain_dir,
                 ground_sample_distance_m=args.gsd or 30.0)
        print(f"  {key:<18} done")
        print(datum_line(key, raw))
        ensure_imagery(key, terrain_dir, args)

    print()
    print("Baked. The web app picks these up immediately (no restart needed):")
    print("a mountains prompt now lands on real terrain instead of the slab.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
