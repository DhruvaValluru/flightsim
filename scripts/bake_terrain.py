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
        if raw.is_file():
            print(f"  {key:<18} already baked ({raw})")
            print(datum_line(key, raw))
            continue
        print(f"  {key:<18} baking from GLO-30 (fetch + ingest + verify)")
        bake(LOCATIONS[key], REPO / "data" / "glo30", terrain_dir)
        print(f"  {key:<18} done")
        print(datum_line(key, raw))

    print()
    print("Baked. The web app picks these up immediately (no restart needed):")
    print("a mountains prompt now lands on real terrain instead of the slab.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
