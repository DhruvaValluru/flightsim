#!/usr/bin/env python3
"""Fetch and pin the CC0 ground-scatter models (trees, shrubs, rocks, grass).

The beauty render's ground scatter (FlightSimGroundDetail.cpp, -ground-scatter=,
core/scene/world_beauty.py) draws a species only when its asset is PINNED: a
source URL, a redistributable non-NC licence, and a sha256 for every file.
assets/scatter/polyhaven_pins.json carries the pins. On 2026-11-09 (a Mac that
cannot render) only each model's small root .gltf was downloaded: its md5
matched Poly Haven's API and its sha256 is recorded; the five small assets
(shrub_02, rock_moss_set_01, grass_medium_01, namaqualand_boulder_02,
wild_rooibos_bush, ~15 MB) were then fetched in full and pinned with
--write-pins. The big trees' meshes and textures (hundreds of MB) were NOT
downloaded: their sha256 is null, so those species are drawn as nothing until
this script runs:

    python scripts/fetch_scatter_assets.py --dry-run            # sizes, nothing fetched
    python scripts/fetch_scatter_assets.py --only shrub_02,rock_moss_set_01
    python scripts/fetch_scatter_assets.py --write-pins         # fetch all, record the sha256s

Every file goes to data/scatter/polyhaven/<id>/<its glTF-relative path>, is
checked against the API's md5 from the pin, and, when the pin already has a
sha256, against that too (a mismatch refuses: the upstream file changed and
the pin must be re-made on purpose). ``--write-pins`` writes the sha256s it
computed back into the pins file, which is then committed. Poly Haven assets
are CC0 1.0 (https://polyhaven.com/license); NOTICE.md credits them.

Importing the fetched glTFs into /Game/FlightSim/Scatter/<id>/<id> (Nanite on
at import time, NEXT.md gotcha 5) is the next step and is NOT written yet:
recorded as a TODO in docs/visual/PROBE_LOG.md (## world).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
PINS = REPO / "assets" / "scatter" / "polyhaven_pins.json"
OUT_DIR = REPO / "data" / "scatter" / "polyhaven"
USER_AGENT = "flightsim-scatter-assets/1 (github.com/DhruvaValluru/flightsim)"
ALLOWED_LICENCES = ("CC0-1.0", "CC-BY-4.0")

Fetch = Callable[[str], bytes]


class ScatterAssetError(RuntimeError):
    """A refusal, by name."""


def http_fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:   # noqa: S310 (pinned https URLs)
        return response.read()


def files_of(pin: Dict) -> List[tuple]:
    """(relative path, file pin) for the root and every include."""
    rows = [(pin["root"]["path"], pin["root"])]
    rows += sorted(pin.get("includes", {}).items())
    return rows


def fetch_asset(asset_id: str, pin: Dict, out_dir: Path, fetch: Fetch = http_fetch) -> Dict[str, str]:
    """Download one asset's files, verify each, return {relative path: sha256}."""
    if pin.get("licence") not in ALLOWED_LICENCES:
        raise ScatterAssetError(f"scatter.licence: {asset_id} is {pin.get('licence')!r}, "
                                f"not one of {ALLOWED_LICENCES}")
    digests: Dict[str, str] = {}
    for relative, file_pin in files_of(pin):
        if ".." in Path(relative).parts or Path(relative).is_absolute():
            raise ScatterAssetError(f"scatter.path: {asset_id} names {relative!r} outside its folder")
        data = fetch(file_pin["url"])
        md5 = hashlib.md5(data).hexdigest()   # noqa: S324 (the API's integrity value, not security)
        if md5 != file_pin["md5"]:
            raise ScatterAssetError(f"scatter.md5: {asset_id}/{relative} has md5 {md5}, the pin "
                                    f"(Poly Haven's API) says {file_pin['md5']}")
        sha = hashlib.sha256(data).hexdigest()
        if file_pin.get("sha256") and file_pin["sha256"] != sha:
            raise ScatterAssetError(f"scatter.sha256: {asset_id}/{relative} is {sha}, pinned "
                                    f"{file_pin['sha256']}: the upstream file changed")
        target = out_dir / asset_id / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        digests[relative] = sha
    provenance = {"asset": asset_id, "licence": pin["licence"], "source": pin["root"]["url"],
                  "credit": "Models: Poly Haven (polyhaven.com), CC0 1.0", "sha256": digests}
    (out_dir / asset_id / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return digests


def write_pins(pins: Dict, asset_id: str, digests: Dict[str, str]) -> None:
    pin = pins["assets"][asset_id]
    for relative, file_pin in files_of(pin):
        file_pin["sha256"] = digests[relative]


def main(argv: Optional[Sequence[str]] = None, fetch: Fetch = http_fetch,
         pins_path: Path = PINS, out_dir: Path = OUT_DIR) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", default="", help="comma-separated asset ids")
    parser.add_argument("--dry-run", action="store_true", help="list sizes, fetch nothing")
    parser.add_argument("--write-pins", action="store_true",
                        help="write the computed sha256s into the pins file")
    args = parser.parse_args(argv)
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    wanted = [a for a in args.only.split(",") if a] or sorted(pins["assets"])
    unknown = [a for a in wanted if a not in pins["assets"]]
    if unknown:
        print(f"scatter.unknown: {unknown} are not in {pins_path.name}", file=sys.stderr)
        return 2
    for asset_id in wanted:
        pin = pins["assets"][asset_id]
        if args.dry_run:
            pending = sum(1 for _, f in files_of(pin) if not f.get("sha256"))
            print(f"{asset_id}: {pin['total_bytes'] / 1e6:.1f} MB in {len(files_of(pin))} files, "
                  f"{pending} without a sha256")
            continue
        digests = fetch_asset(asset_id, pin, out_dir, fetch)
        if args.write_pins:
            write_pins(pins, asset_id, digests)
        print(f"FETCHED {asset_id}: {len(digests)} files verified")
    if args.write_pins and not args.dry_run:
        pins_path.write_text(json.dumps(pins, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"pins written: {pins_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
