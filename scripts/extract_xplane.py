"""Extract water, terrain-type and sky-colour data from an X-Plane 12 install.

    .venv/bin/python scripts/extract_xplane.py --xplane-root "~/X-Plane 12"

Writes assets/xplane/, which IS committed so a machine without the local
simulator install renders the same terrain. core.xplane reads the result; see
core/xplane/extract.py for what each output does and does not claim.
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
    print(f"drape:   {counts['drape']['textures']} ground textures")
    print(f"sky:     {counts['sky']['conditions']} conditions")
    print(f"written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
