#!/usr/bin/env python3
"""Higher-detail airframe candidates for the Phase 3 subjects (J-11, J-15,
J-35), with their licences, and the pinned fetch for the ones that may be
used. Visual overhaul V7, aircraft lane, 2026-11-09.

The rule (VISUAL_FIDELITY_PLAN.md §3.3/§3.4, the owner's): no asset without a
pinned source URL, a sha256 and a REDISTRIBUTABLE licence that is not
NonCommercial -- CC-BY, CC-BY-SA, CC0, GPL or similar. No "editorial only",
no store-exclusive or royalty-free-store licence (those forbid
redistribution), no NoAI clause (this project makes training data), and no
placeholder airframes. The table below is what a web search on 2026-11-09
found; nothing was downloaded (large assets are not fetched in this
session). A candidate with ``sha256: None`` cannot be fetched by this script
until a human downloads it once and records the digest with
``--record-pin`` on the render machine.

A mesh is only half of a subject: VALIDITY 1.4 requires the mesh to match
the FLOWN FDM (assets_pipeline/convert.py refuses a mismatch), so a J-15
mesh needs a J-15 FDM too, and every candidate here still goes through the
normal aircraft_config + convert + import path, labels and keypoints
re-measured from its own vertices.

What was found (``python scripts/fetch_aircraft_models.py --list``):

* J-11 (the current subject flies yanes19/SU-27SK, GPL-2.0, pinned in
  assets/aircraft_config/J11.json). One higher-detail candidate: a
  Sketchfab "Sukhoi Su-27 Flanker" by andertan, CC Attribution 4.0, 28.8k
  triangles, downloadable (the J-11A is the licence-built Su-27SK; external
  differences are small). Sketchfab downloads need an account token and
  hand back a temporary URL, so the sha256 can only be pinned after a first
  download; the model page must also be re-checked for a NoAI tag then.
* J-15 (a Su-33 derivative). No J-15 model under a redistributable licence
  was found (CGTrader / TurboSquid / Free3D listings are store licences).
  Closest redistributable airframe: FlightGear FGAddon
  Aircraft/Sukhoi-Su-33 by helijah (FGAddon is GPLv2+; the folder carries a
  COPYING file), pinnable by SVN revision; its FDM is the package's own and
  is not a J-15's.
* J-35 / FC-31. Nothing redistributable was found: every listing seen
  (RenderHub, CGTrader, MakerWorld) is a store or no-redistribution licence.
  None qualifies; say so rather than substitute another airframe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "assets" / "aircraft_src" / "_candidates"  # git-ignored with aircraft_src

#: Licences this project may redistribute (SPDX-style ids).
REDISTRIBUTABLE = {"CC0-1.0", "CC-BY-4.0", "CC-BY-3.0", "CC-BY-SA-4.0", "CC-BY-SA-3.0",
                   "GPL-2.0", "GPL-2.0-or-later", "GPL-3.0", "GPL-3.0-or-later"}
#: Words that disqualify a licence however it is spelled.
FORBIDDEN_WORDS = ("NC", "NonCommercial", "editorial", "royalty free", "royalty-free",
                   "store", "NoAI", "all rights reserved")

#: The candidate table. ``usable`` is derived (licence + pin), never typed.
CANDIDATES = [
    {
        "id": "su27_andertan_sketchfab",
        "subject": "J11",
        "airframe": "Sukhoi Su-27 Flanker (J-11A's licence-built parent)",
        "source": "sketchfab",
        "url": "https://sketchfab.com/3d-models/sukhoi-su-27-flanker-2541c1dbc6c1499cb7b38b5bf1314750",
        "uid": "2541c1dbc6c1499cb7b38b5bf1314750",
        "author": "andertan",
        "licence": "CC-BY-4.0",
        "licence_evidence": "model page licence field 'CC Attribution' linking "
                            "creativecommons.org/licenses/by/4.0 (read 2026-11-09)",
        "triangles": 28800,
        "sha256": None,
        "pin_note": "Sketchfab's download API needs an account token and returns a temporary "
                    "URL: pin after the first download (--record-pin). Re-check the page for a "
                    "NoAI tag at that time.",
    },
    {
        "id": "su33_fgaddon_helijah",
        "subject": "J15",
        "airframe": "Sukhoi Su-33 Flanker-D (the J-15's parent design), FlightGear FGAddon",
        "source": "svn",
        "url": "https://svn.code.sf.net/p/flightgear/fgaddon/trunk/Aircraft/Sukhoi-Su-33",
        "browse": "https://sourceforge.net/p/flightgear/fgaddon/HEAD/tree/trunk/Aircraft/Sukhoi-Su-33/",
        "revision": 18942,
        "author": "helijah (FGAddon)",
        "licence": "GPL-2.0-or-later",
        "licence_evidence": "FGAddon hangar terms GPLv2+ (wiki.flightgear.org/FGAddon); the folder "
                            "lists a COPYING file (r10024) whose text was not read here",
        "triangles": None,
        "sha256": None,
        "pin_note": "svn export at the revision, then --record-pin (the tree digest below); read "
                    "COPYING before use. Not a J-15: a J-15 subject also needs a J-15 FDM.",
    },
    {
        "id": "su30mki_sketchfab_rejected",
        "subject": "J11",
        "airframe": "Su-30 MKI (Sketchfab)",
        "source": "sketchfab",
        "url": "https://sketchfab.com/3d-models/su-30-mki-d320a578ff8e44eba8fd3f111d1d1dba",
        "author": None,
        "licence": "CC-BY-NC-ND-4.0",
        "licence_evidence": "search snippet: CC Attribution-NonCommercial-NoDerivs (2026-11-09)",
        "triangles": None,
        "sha256": None,
        "pin_note": "REJECTED: NonCommercial.",
    },
    {
        "id": "j35_store_listings_rejected",
        "subject": "J35",
        "airframe": "J-35 / FC-31 (RenderHub, CGTrader, MakerWorld listings)",
        "source": "store",
        "url": "https://www.renderhub.com/mossfx/j-35a-stealth-fighter",
        "author": None,
        "licence": "store licence (Extended Use, IP Restricted / Royalty Free)",
        "licence_evidence": "listing terms (2026-11-09): no redistribution",
        "triangles": None,
        "sha256": None,
        "pin_note": "REJECTED: store licence, not redistributable. No redistributable J-35 found.",
    },
]


def licence_ok(licence: str) -> bool:
    """A licence id this project may redistribute (and none of the forbidden words)."""
    if licence not in REDISTRIBUTABLE:
        return False
    tokens = licence.replace("-", " ").split()
    return not any(word in tokens or word.lower() in licence.lower().split()
                   for word in FORBIDDEN_WORDS)


def usable(candidate: dict) -> bool:
    return licence_ok(candidate["licence"]) and bool(candidate.get("sha256"))


def tree_sha256(root: Path) -> str:
    """A digest of a directory tree: sha256 over sorted 'path\\0file-sha256\\n' lines."""
    lines = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and ".svn" not in p.parts):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{path.relative_to(root).as_posix()}\0{digest}\n")
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def fetch(candidate: dict, dest: Path, record_pin: bool) -> str:
    """Fetch one candidate into ``dest`` and verify (or, with record_pin,
    print) its digest. Refuses a licence that is not redistributable."""
    if not licence_ok(candidate["licence"]):
        raise SystemExit(f"{candidate['id']}: licence {candidate['licence']!r} is not "
                         f"redistributable; refused")
    if not candidate.get("sha256") and not record_pin:
        raise SystemExit(f"{candidate['id']}: no sha256 pinned ({candidate['pin_note']}); "
                         f"fetch once with --record-pin and commit the digest")
    if candidate["source"] == "svn":
        if dest.exists():
            raise SystemExit(f"{dest} exists; remove it first")
        subprocess.run(["svn", "export", "-q", "-r", str(candidate["revision"]), candidate["url"],
                        str(dest)], check=True)
        digest = tree_sha256(dest)
    elif candidate["source"] == "sketchfab":
        raise SystemExit(f"{candidate['id']}: Sketchfab needs an account download (token + "
                         f"temporary URL); download the glTF by hand into {dest}, then run "
                         f"--digest {dest}")
    else:
        raise SystemExit(f"{candidate['id']}: source {candidate['source']!r} cannot be fetched")
    if candidate.get("sha256") and digest != candidate["sha256"]:
        raise SystemExit(f"{candidate['id']}: tree sha256 {digest} != pinned {candidate['sha256']}")
    return digest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="print the candidate table (default)")
    parser.add_argument("--fetch", metavar="ID", help="fetch one candidate")
    parser.add_argument("--dest", type=Path, help="destination folder (default under "
                        "assets/aircraft_src/_candidates/<id>)")
    parser.add_argument("--record-pin", action="store_true",
                        help="fetch an unpinned candidate and print its digest to commit")
    parser.add_argument("--digest", type=Path, help="print the tree sha256 of a folder")
    args = parser.parse_args(argv)
    if args.digest:
        print(tree_sha256(args.digest))
        return 0
    if args.fetch:
        candidate = next((c for c in CANDIDATES if c["id"] == args.fetch), None)
        if candidate is None:
            raise SystemExit(f"no candidate {args.fetch!r}")
        dest = args.dest or OUT_ROOT / candidate["id"]
        digest = fetch(candidate, dest, args.record_pin)
        print(f"FETCHED {candidate['id']} -> {dest} tree sha256 {digest}")
        return 0
    rows = [{**c, "licence_redistributable": licence_ok(c["licence"]), "usable": usable(c)}
            for c in CANDIDATES]
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
