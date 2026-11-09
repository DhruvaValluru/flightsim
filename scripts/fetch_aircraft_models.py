#!/usr/bin/env python3
"""Higher-detail airframe candidates for the Phase 3 subjects (J-11, J-15,
J-35), with their licences, and the pinned fetch for the ones that may be
used. Visual overhaul V7, aircraft lane, 2026-11-09; pin audit (lane pins)
the same day.

The rule (VISUAL_FIDELITY_PLAN.md §3.3/§3.4, the owner's): no asset without a
pinned source URL, a sha256 and a REDISTRIBUTABLE licence that is not
NonCommercial -- CC-BY, CC-BY-SA, CC0, GPL or similar. No "editorial only",
no store-exclusive or royalty-free-store licence (those forbid
redistribution), no NoAI clause (this project makes training data), and no
placeholder airframes. A licence label is only as good as its chain: a
model whose uploader says it is not theirs, a re-upload of one, or a game
rip carries a CC label the uploader could not grant, so ``provenance`` must
be ``"ok"`` too. ``usable`` is derived (licence + provenance + pin), never
typed.

A mesh is only half of a subject: VALIDITY 1.4 requires the mesh to match
the FLOWN FDM (assets_pipeline/convert.py refuses a mismatch), so a J-15
mesh needs a J-15 FDM too, and every candidate here still goes through the
normal aircraft_config + convert + import path, labels and keypoints
re-measured from its own vertices.

What the 2026-11-09 pin audit found (``--list``; evidence per row; every
Sketchfab row read from api.sketchfab.com/v3/models/<uid> that day):

* J-11 (the current subject flies yanes19/SU-27SK, GPL-2.0, pinned in
  assets/aircraft_config/J11.json). Best higher-detail candidate: Sketchfab
  "Shenyang J-11" by Rhine_Lab_Muelsyse, CC BY 4.0, 47.8k triangles,
  downloadable, no NoAI tag. Also andertan's J-11 "Flanker-L" (29.9k) and
  Su-27 (28.8k), CC BY 4.0. Sketchfab downloads need an account token and
  hand back a temporary URL, so none of them has a sha256 yet (UNVERIFIED:
  no token on this machine).
* J-15 (a Su-33 derivative). PINNED: FlightGear FGAddon
  Aircraft/Sukhoi-Su-33 by Emmanuel Baranger (helijah), GPL-2.0 (the
  folder's COPYING is the GPLv2 text; the bundled Nasal and glass-rain
  files say GPLv2+), last changed in r18942; the tree (403 files, 97.4 MB)
  was fetched over WebDAV at r18942 and its tree sha256 recorded below. Its
  FDM is a YASim Su-33, not a J-15's. The two Sketchfab J-15s with CC
  labels are re-uploads (42manako: "Not my model"), REJECTED.
* J-35 / FC-31. Sketchfab: andertan "Shenyang J31 Gyrfalcon" (51.6k, the
  FC-31 prototype shape, tagged j35) and oega279 "J-35 Chinese fighter jet"
  (57.4k), both CC BY 4.0, unpinned (token). The store listings (RenderHub,
  CGTrader, Free3D, MakerWorld) stay REJECTED.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "assets" / "aircraft_src" / "_candidates"  # git-ignored with aircraft_src
USER_AGENT = "flightsim-aircraft-models/1 (github.com/DhruvaValluru/flightsim)"

#: Licences this project may redistribute (SPDX-style ids).
REDISTRIBUTABLE = {"CC0-1.0", "CC-BY-4.0", "CC-BY-3.0", "CC-BY-SA-4.0", "CC-BY-SA-3.0",
                   "GPL-2.0", "GPL-2.0-or-later", "GPL-3.0", "GPL-3.0-or-later"}
#: Words that disqualify a licence however it is spelled.
FORBIDDEN_WORDS = ("NC", "NonCommercial", "editorial", "royalty free", "royalty-free",
                   "store", "NoAI", "all rights reserved")

_SKETCHFAB_DL = ("Sketchfab's download API needs an account token and returns a temporary URL: "
                 "UNVERIFIED (no token on the 2026-11-09 audit machine). Download the glTF once, "
                 "--digest the folder, commit the sha256, and re-check the page for a NoAI tag then.")

#: The candidate table.
CANDIDATES = [
    # -- J-11 -------------------------------------------------------------------------
    {
        "id": "j11_rhinelab_sketchfab",
        "subject": "J11",
        "airframe": "Shenyang J-11 (Sketchfab)",
        "source": "sketchfab",
        "url": "https://sketchfab.com/3d-models/shenyang-j-11-f3b0a285198a4523b96b9ac372e18865",
        "uid": "f3b0a285198a4523b96b9ac372e18865",
        "author": "Rhine_Lab_Muelsyse",
        "licence": "CC-BY-4.0",
        "licence_evidence": "model page and api.sketchfab.com/v3/models/<uid> (2026-11-09): licence "
                            "'CC Attribution' -> creativecommons.org/licenses/by/4.0, downloadable, "
                            "no NoAI tag; CC BY 4.0 deed read the same day (share and adapt, "
                            "commercial use, attribution)",
        "provenance": "ok",
        "provenance_evidence": "uploaded 2025-02-15 by the credited author; the description is "
                               "aircraft history, no claim that the model is someone else's",
        "triangles": 47786,
        "sha256": None,
        "pin_note": _SKETCHFAB_DL,
    },
    {
        "id": "j11_andertan_flanker_l_sketchfab",
        "subject": "J11",
        "airframe": "Shenyang J-11 'Flanker-L' (Sketchfab)",
        "source": "sketchfab",
        "url": "https://sketchfab.com/3d-models/shenyang-j11-flanker-l-aaa7700649fc43848020981313cc595c",
        "uid": "aaa7700649fc43848020981313cc595c",
        "author": "andertan",
        "licence": "CC-BY-4.0",
        "licence_evidence": "api.sketchfab.com/v3/models/<uid> (2026-11-09): 'CC Attribution' -> "
                            "creativecommons.org/licenses/by/4.0, downloadable, no NoAI tag",
        "provenance": "ok",
        "provenance_evidence": "andertan's own series (Su-27, Su-30, Su-33, Su-35, J-31), 2024-07-21",
        "triangles": 29862,
        "sha256": None,
        "pin_note": _SKETCHFAB_DL,
    },
    {
        "id": "su27_andertan_sketchfab",
        "subject": "J11",
        "airframe": "Sukhoi Su-27 Flanker (J-11A's licence-built parent)",
        "source": "sketchfab",
        "url": "https://sketchfab.com/3d-models/sukhoi-su-27-flanker-2541c1dbc6c1499cb7b38b5bf1314750",
        "uid": "2541c1dbc6c1499cb7b38b5bf1314750",
        "author": "andertan",
        "licence": "CC-BY-4.0",
        "licence_evidence": "model page re-read 2026-11-09 (pin audit): 'CC Attribution' -> "
                            "creativecommons.org/licenses/by/4.0, 'Download 3D Model', 28.8k "
                            "triangles, 16.8k vertices, no NoAI tag",
        "provenance": "ok",
        "provenance_evidence": "andertan's own series, 2024-08-11",
        "triangles": 28840,
        "sha256": None,
        "pin_note": _SKETCHFAB_DL,
    },
    {
        "id": "j11_chenzoss_sketchfab",
        "subject": "J11",
        "airframe": "Shenyang J-11 (Sketchfab, Chenzoss)",
        "source": "sketchfab",
        "url": "https://sketchfab.com/3d-models/shenyang-j-11-1bca4b1e8ecb4c3188148a39c2f1c197",
        "uid": "1bca4b1e8ecb4c3188148a39c2f1c197",
        "author": "Chenzoss",
        "licence": "CC-BY-4.0",
        "licence_evidence": "api.sketchfab.com/v3/models/<uid> (2026-11-09): 'CC Attribution', "
                            "downloadable",
        "provenance": "UNVERIFIED: the description is only 'shenyang j-11'; 120k triangles from a "
                      "one-model account, origin not stated, so the CC grant cannot be checked",
        "triangles": 119998,
        "sha256": None,
        "pin_note": _SKETCHFAB_DL,
    },
    {
        "id": "j11_42manako_sketchfab_rejected",
        "subject": "J11",
        "airframe": "Chinese Shenyang J-11 (Sketchfab, 42manako)",
        "source": "sketchfab",
        "url": "https://sketchfab.com/3d-models/chinese-shenyang-j-11-508bcb11c9ac494d906f0354e36ffacc",
        "uid": "508bcb11c9ac494d906f0354e36ffacc",
        "author": None,
        "licence": "CC-BY-4.0",
        "licence_evidence": "labelled 'CC Attribution' (2026-11-09)",
        "provenance": "REJECTED: the uploader's description says 'Not my model.'; 751k triangles, "
                      "the same uploader's other pages are tagged warthunder (game rips)",
        "triangles": 751756,
        "sha256": None,
        "pin_note": "REJECTED: the CC label was not granted by the model's author.",
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
        "provenance": "n/a",
        "triangles": None,
        "sha256": None,
        "pin_note": "REJECTED: NonCommercial.",
    },
    # -- J-15 -------------------------------------------------------------------------
    {
        "id": "su33_fgaddon_helijah",
        "subject": "J15",
        "airframe": "Sukhoi Su-33 Flanker-D (the J-15's parent design), FlightGear FGAddon",
        "source": "svn",
        "url": "https://svn.code.sf.net/p/flightgear/fgaddon/trunk/Aircraft/Sukhoi-Su-33",
        "browse": "https://sourceforge.net/p/flightgear/fgaddon/HEAD/tree/trunk/Aircraft/Sukhoi-Su-33/",
        "dav_root": "https://svn.code.sf.net",
        "dav_path": "/p/flightgear/fgaddon/!svn/bc/18942/trunk/Aircraft/Sukhoi-Su-33/",
        "revision": 18942,
        "author": "Emmanuel Baranger (helijah), FGAddon",
        "licence": "GPL-2.0",
        "licence_evidence": "COPYING at r18942 read 2026-11-09: the GNU GPL version 2 text; "
                            "su33-set.xml credits 'BARANGER Emmanuel (3D/FDM)'; the bundled "
                            "Nasal/generic-yasim-engine.nas (Ryan Miller) and "
                            "Systems/glass-rain.xml (Wayne Bragg) say GPLv2 or later; no other "
                            "licence statement in the tree",
        "provenance": "ok",
        "provenance_evidence": "FGAddon is FlightGear's official GPL hangar; PROPFIND on the folder "
                               "gives version-name 18942 (its last change, 2026-01-23)",
        "files": 403,
        "bytes": 97365937,
        "triangles": None,
        "surfaces": 21577,   # numsurf total in Models/su33.ac at r18942 (AC3D polygons)
        "sha256": "5e56e2f27102d128507ba0b90218bdf54da31f3ff617ba125c0a127b8885c146",
        "pin_note": "tree sha256 (tree_sha256) of the 403 files fetched over WebDAV at r18942 on "
                    "2026-11-09 and re-checked with this script's tree_sha256; two files carry "
                    "svn:eol-style native and hold LF only, so an svn export on macOS/Linux gives "
                    "the same bytes (on Windows it would give CRLF and the pin refuses). Not a "
                    "J-15: a J-15 subject also needs a J-15 FDM (this one is YASim Su-33).",
    },
    {
        "id": "su33_andertan_sketchfab",
        "subject": "J15",
        "airframe": "Sukhoi Su-33 (Sketchfab)",
        "source": "sketchfab",
        "url": "https://sketchfab.com/3d-models/sukhoi-su-33-33-d80603a8a13b49bda90f19d80cac61d4",
        "uid": "d80603a8a13b49bda90f19d80cac61d4",
        "author": "andertan",
        "licence": "CC-BY-4.0",
        "licence_evidence": "api.sketchfab.com/v3/models/<uid> (2026-11-09): 'CC Attribution' -> "
                            "creativecommons.org/licenses/by/4.0, downloadable, no NoAI tag",
        "provenance": "ok",
        "provenance_evidence": "andertan's own series, 2024-07-24",
        "triangles": 19582,
        "sha256": None,
        "pin_note": _SKETCHFAB_DL + " Lower detail than the FGAddon Su-33.",
    },
    {
        "id": "j15_heedblock_simpleplanes_sketchfab",
        "subject": "J15",
        "airframe": "J-15 (Sketchfab 'J-15_export', a SimplePlanes build)",
        "source": "sketchfab",
        "url": "https://sketchfab.com/3d-models/j-15-export-c6fbb690297846e79b96c430b395fc14",
        "uid": "c6fbb690297846e79b96c430b395fc14",
        "author": "heedblock",
        "licence": "CC-BY-4.0",
        "licence_evidence": "labelled 'CC Attribution' (2026-11-09)",
        "provenance": "UNVERIFIED: description 'Made by simpleplanes': an export of a SimplePlanes "
                      "craft whose builder, and the game's terms for exported meshes, are not "
                      "stated",
        "triangles": 117884,
        "sha256": None,
        "pin_note": _SKETCHFAB_DL,
    },
    {
        "id": "j15_42manako_sketchfab_rejected",
        "subject": "J15",
        "airframe": "PLA Navy Shenyang J-15 (Sketchfab, 42manako; and the Revoulution_Quokka "
                    "re-upload 430ed5c9a1cd4ca8a9a3a2de09cdcb6d, 286,926 faces)",
        "source": "sketchfab",
        "url": "https://sketchfab.com/3d-models/pla-navy-shenyang-j-15-f2bf5c1e2e654ee6819b696b6095a552",
        "uid": "f2bf5c1e2e654ee6819b696b6095a552",
        "author": None,
        "licence": "CC-BY-4.0",
        "licence_evidence": "labelled 'CC Attribution' (2026-11-09)",
        "provenance": "REJECTED: the uploader's description says 'Not my model, though I did edit "
                      "the textures a bit.'; the second upload has the same mesh size and no source",
        "triangles": 287132,
        "sha256": None,
        "pin_note": "REJECTED: the CC label was not granted by the model's author.",
    },
    {
        "id": "su33_helijah_sketchfab_rejected",
        "subject": "J15",
        "airframe": "Sukhoi Su 33 Flanker D (Sketchfab copy of the FGAddon model)",
        "source": "sketchfab",
        "url": "https://sketchfab.com/3d-models/sukhoi-su-33-flanker-d-b355182c980e4e53958956a56fa91f2e",
        "uid": "b355182c980e4e53958956a56fa91f2e",
        "author": "helijah",
        "licence": "Sketchfab Free Standard",
        "licence_evidence": "api.sketchfab.com/v3/models/<uid> (2026-11-09): 'Free Standard' -> "
                            "sketchfab.com/licenses (a store licence; the page did not render for "
                            "WebFetch)",
        "provenance": "ok",
        "triangles": 73064,
        "sha256": None,
        "pin_note": "REJECTED: store licence, not on the redistributable list. Use the same "
                    "author's GPL FGAddon tree (su33_fgaddon_helijah) instead.",
    },
    {
        "id": "su33_warthunder_sketchfab_rejected",
        "subject": "J15",
        "airframe": "Su-33 (#1 Custom) (War Thunder), and '[War Thunder] Su-33 Flanker-D' "
                    "50b8ac6119c7429e8c37a46b6bacfe66 (Sketchfab)",
        "source": "sketchfab",
        "url": "https://sketchfab.com/3d-models/none-5a98ae1c6b1c4f428f397f094fe24046",
        "uid": "5a98ae1c6b1c4f428f397f094fe24046",
        "author": None,
        "licence": "CC-BY-4.0",
        "licence_evidence": "labelled 'CC Attribution' in Sketchfab search (2026-11-09)",
        "provenance": "REJECTED: titled as a War Thunder model, a game rip; the uploader cannot "
                      "grant CC BY",
        "triangles": 604544,
        "sha256": None,
        "pin_note": "REJECTED: game rip.",
    },
    # -- J-35 -------------------------------------------------------------------------
    {
        "id": "j31_andertan_sketchfab",
        "subject": "J35",
        "airframe": "Shenyang J-31 'Gyrfalcon' (FC-31 prototype shape; Sketchfab)",
        "source": "sketchfab",
        "url": "https://sketchfab.com/3d-models/shenyang-j31-gyrfalcon-23dbff530e21491299ac67bbab42b553",
        "uid": "23dbff530e21491299ac67bbab42b553",
        "author": "andertan",
        "licence": "CC-BY-4.0",
        "licence_evidence": "api.sketchfab.com/v3/models/<uid> (2026-11-09): 'CC Attribution' -> "
                            "creativecommons.org/licenses/by/4.0, downloadable, tagged j35, no "
                            "NoAI tag",
        "provenance": "ok",
        "provenance_evidence": "andertan's own series, 2024-07-16",
        "triangles": 51612,
        "sha256": None,
        "pin_note": _SKETCHFAB_DL + " The FC-31 prototype differs from the production J-35 "
                    "(tails, nose, canopy); label it by what it is.",
    },
    {
        "id": "j35_oega279_sketchfab",
        "subject": "J35",
        "airframe": "J-35 Chinese fighter jet (Sketchfab)",
        "source": "sketchfab",
        "url": "https://sketchfab.com/3d-models/j-35-chinese-fighter-jet-a3243074e8a04c67ba3847cd62ebdbfb",
        "uid": "a3243074e8a04c67ba3847cd62ebdbfb",
        "author": "oega279",
        "licence": "CC-BY-4.0",
        "licence_evidence": "api.sketchfab.com/v3/models/<uid> (2026-11-09): 'CC Attribution' -> "
                            "creativecommons.org/licenses/by/4.0, downloadable, no NoAI tag",
        "provenance": "ok",
        "provenance_evidence": "tagged maya/maya2017/modeling, uploaded 2025-01-06 as the author's "
                               "own work",
        "triangles": 57380,
        "sha256": None,
        "pin_note": _SKETCHFAB_DL,
    },
    {
        "id": "j35_hrd4588_sketchfab",
        "subject": "J35",
        "airframe": "Shenyang J-35 (Sketchfab, low detail)",
        "source": "sketchfab",
        "url": "https://sketchfab.com/3d-models/shenyang-j-35-37085f458d7943cd8314372af76e0f67",
        "uid": "37085f458d7943cd8314372af76e0f67",
        "author": "hrd4588",
        "licence": "CC-BY-4.0",
        "licence_evidence": "api.sketchfab.com/v3/models/<uid> (2026-11-09): 'CC Attribution', "
                            "downloadable",
        "provenance": "ok",
        "provenance_evidence": "uploaded 2025-09-29, no claim that it is someone else's",
        "triangles": 8235,
        "sha256": None,
        "pin_note": _SKETCHFAB_DL + " 8.2k triangles: not higher detail; recorded for completeness.",
    },
    {
        "id": "j35_store_listings_rejected",
        "subject": "J35",
        "airframe": "J-35 / FC-31 (RenderHub, CGTrader, Free3D, MakerWorld listings)",
        "source": "store",
        "url": "https://www.renderhub.com/mossfx/j-35a-stealth-fighter",
        "author": None,
        "licence": "store licence (Extended Use, IP Restricted / Royalty Free)",
        "licence_evidence": "listing terms (2026-11-09): no redistribution; Free3D FC-31 is "
                            "'Royalty Free License Editorial Only'",
        "provenance": "n/a",
        "triangles": None,
        "sha256": None,
        "pin_note": "REJECTED: store licence, not redistributable.",
    },
]


def licence_ok(licence: str) -> bool:
    """A licence id this project may redistribute (and none of the forbidden words)."""
    if licence not in REDISTRIBUTABLE:
        return False
    tokens = licence.replace("-", " ").split()
    return not any(word in tokens or word.lower() in licence.lower().split()
                   for word in FORBIDDEN_WORDS)


def provenance_ok(candidate: dict) -> bool:
    """The licence was granted by the model's author (not a re-upload or a rip)."""
    return candidate.get("provenance") == "ok"


def usable(candidate: dict) -> bool:
    return (licence_ok(candidate["licence"]) and provenance_ok(candidate)
            and bool(candidate.get("sha256")))


def tree_sha256(root: Path) -> str:
    """A digest of a directory tree: sha256 over sorted 'path\\0file-sha256\\n' lines."""
    lines = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and ".svn" not in p.parts):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{path.relative_to(root).as_posix()}\0{digest}\n")
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


_DAV_BODY = b'<?xml version="1.0"?><propfind xmlns="DAV:"><allprop/></propfind>'


def _dav_list(root: str, path: str) -> list:
    """Every file href under ``path`` (a pinned-revision !svn/bc/<rev>/ path), by PROPFIND."""
    files, stack = [], [path]
    while stack:
        href = stack.pop()
        request = urllib.request.Request(root + href, data=_DAV_BODY, method="PROPFIND",
                                         headers={"Depth": "1", "Content-Type": "text/xml",
                                                  "User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:   # noqa: S310 (pinned https)
            tree = ET.fromstring(response.read())
        for resp in tree.findall("{DAV:}response"):
            child = resp.find("{DAV:}href").text
            if child.rstrip("/") == href.rstrip("/"):
                continue
            if resp.find(".//{DAV:}resourcetype/{DAV:}collection") is not None:
                stack.append(child)
            else:
                files.append(child)
    return files


def fetch_svn_dav(candidate: dict, dest: Path) -> None:
    """Fetch an SVN folder at its pinned revision over WebDAV (no svn client needed)."""
    root, path = candidate["dav_root"], candidate["dav_path"]
    for href in _dav_list(root, path):
        relative = urllib.parse.unquote(href[len(path):])
        if ".." in Path(relative).parts or Path(relative).is_absolute():
            raise SystemExit(f"{candidate['id']}: {relative!r} is outside the folder")
        request = urllib.request.Request(root + href, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=300) as response:   # noqa: S310 (pinned https)
            data = response.read()
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def fetch(candidate: dict, dest: Path, record_pin: bool) -> str:
    """Fetch one candidate into ``dest`` and verify (or, with record_pin,
    print) its digest. Refuses a licence that is not redistributable."""
    if not licence_ok(candidate["licence"]):
        raise SystemExit(f"{candidate['id']}: licence {candidate['licence']!r} is not "
                         f"redistributable; refused")
    if not provenance_ok(candidate):
        raise SystemExit(f"{candidate['id']}: provenance {candidate.get('provenance')!r}; refused")
    if not candidate.get("sha256") and not record_pin:
        raise SystemExit(f"{candidate['id']}: no sha256 pinned ({candidate['pin_note']}); "
                         f"fetch once with --record-pin and commit the digest")
    if candidate["source"] == "svn":
        if dest.exists():
            raise SystemExit(f"{dest} exists; remove it first")
        if shutil.which("svn"):
            subprocess.run(["svn", "export", "-q", "-r", str(candidate["revision"]),
                            candidate["url"], str(dest)], check=True)
        elif candidate.get("dav_path"):
            fetch_svn_dav(candidate, dest)
        else:
            raise SystemExit(f"{candidate['id']}: no svn client and no WebDAV path")
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
    rows = [{**c, "licence_redistributable": licence_ok(c["licence"]),
             "provenance_ok": provenance_ok(c), "usable": usable(c)} for c in CANDIDATES]
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
