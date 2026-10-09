"""Extract water, terrain-type and sky-colour data from an X-Plane 12 install.

    .venv/bin/python scripts/extract_xplane.py --xplane-root "~/X-Plane 12"

Writes assets/xplane/, which IS committed so a machine without the local
simulator install renders the same terrain. core.xplane reads the result; see
core/xplane/extract.py for what each output does and does not claim.

Since 2026-10-05 the drape pull is what the terrain material needs
(M_TerrainImagery, scripts/ue_create_materials.py): the five ground textures
at up to 2048 px (512 before; the committed PNGs are the old pull until this
is re-run on the machine with the install -- tens of MB in git, and three
constants of the material script to re-measure, see
core.xplane.extract.DRAPE_TEXTURE_MAX_PX), every texture- or decal-naming
directive of each role's .ter with the referenced map pulled as
terrain/drape/<role>_<kind>.png when it is on disk (the normal map under
the role's "normal"), and the terrain library.txt lines that name the .ter
(the record a per-season resolution will be built from; no seasonal texture
is pulled yet). The weather bitmaps are not pulled: core.xplane.physical
reads the committed assets/physical_renders tree alone. The drape line
below counts the five textures and the directive maps pulled ("maps" in
the returned counts, present only when one was written).
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.xplane import DATA_DIR  # noqa: E402
from core.xplane.extract import XPlaneExtractError, extract  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--xplane-root", required=True, type=Path,
                        help="the X-Plane 12 install folder")
    parser.add_argument("--out", type=Path, default=DATA_DIR,
                        help=f"output folder (default {DATA_DIR})")
    args = parser.parse_args()
    try:
        counts = extract(args.xplane_root.expanduser(), args.out)
    except XPlaneExtractError as exc:
        print(f"extract_xplane: {exc}", file=sys.stderr)
        return 1
    print(f"water:   {counts['water']['polygons']} polygon records in "
          f"{counts['water']['tiles']} tiles")
    print(f"terrain: {counts['terrain']['definitions']} definitions")
    print(f"drape:   {counts['drape']['textures']} ground textures, "
          f"{counts['drape'].get('maps', 0)} directive map(s)")
    print(f"sky:     {counts['sky']['conditions']} conditions")
    print(f"written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
