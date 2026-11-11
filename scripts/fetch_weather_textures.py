#!/usr/bin/env python3
"""Fetch the pinned CC0 weather textures (lane D, 2026-11-11).

The beauty windscreen's water (M_WindshieldRain generation 3: the sheet of
run-off and beaded drops a cockpit camera sees through in heavy rain) samples a
photographed-and-scanned water-on-a-surface map instead of drawing only the
procedural drops. One asset, pinned by URL and sha256 (THIRD_PARTY_VISUAL.md
lists it):

    data/textures/weather/leaking019c/normal_gl.jpg   (OpenGL normal, 1024 px)
    data/textures/weather/leaking019c/height.jpg      (displacement, 1024 px)
    data/textures/weather/leaking019c/provenance.json

Source: ambientCG "Leaking 019 C" (https://ambientcg.com/a/Leaking019C), CC0 1.0
(ambientCG's licence page: every asset is CC0; no attribution required). The
zip is the 1K-JPG download; only the two maps are kept (about 0.4 MB); the zip
is checked against its sha256 before anything is extracted and each kept map
against its own. Nothing here is committed (data/textures/ is git-ignored); the
script is the named step that puts the files there, and a checkout without them
still builds M_WindshieldRain (the procedural drops alone, recorded).

    python scripts/fetch_weather_textures.py            # fetch, verify, extract
    python scripts/fetch_weather_textures.py --check    # verify what is there, fetch nothing

Then re-run scripts/ue_create_materials.py in the editor on the render machine
(M_WindshieldRain is rebuilt at generation 3 and imports the maps as
T_WindshieldWater_N / T_WindshieldWater_H).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "data" / "textures" / "weather"
USER_AGENT = "flightsim-weather-textures/1 (github.com/DhruvaValluru/flightsim)"

#: Every pinned asset: its page, licence, the zip (the API's download link and the
#: CDN file it redirected to on 2026-11-11) and the members kept, each with its
#: sha256 (computed from the download on 2026-11-11).
PINS: Dict[str, Dict[str, Any]] = {
    "leaking019c": {
        "title": "Leaking 019 C (ambientCG)",
        "page": "https://ambientcg.com/a/Leaking019C",
        "licence": "CC0-1.0",
        "licence_url": "https://docs.ambientcg.com/license/",
        "zip_url": "https://ambientcg.com/get?file=Leaking019C_1K-JPG.zip",
        "zip_cdn_url": ("https://acg-download.struffelproductions.com/file/ambientCG-Web/download/"
                        "Leaking019C_J3FPnb71/Leaking019C_1K-JPG.zip"),
        "zip_bytes": 2304286,
        "zip_sha256": "fbac60faa458fba2cbd4d63cfc815346573af09db328fe99df287614af279706",
        "members": {
            "normal_gl.jpg": {"member": "Leaking019C_1K-JPG_NormalGL.jpg", "bytes": 156156,
                              "sha256": "e88c1c745f486f8bf2cc095ff8e20bb897045c6ba00ed9da9eb4509f5b5ccc41"},
            "height.jpg": {"member": "Leaking019C_1K-JPG_Displacement.jpg", "bytes": 235018,
                           "sha256": "66be629c57708a0b4cf344c8dc2817c8fb60c667002fae3195603c669c671102"},
        },
    },
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check(name: str, pin: Dict[str, Any], out_root: Path = OUT_ROOT) -> bool:
    """True when every kept member of ``name`` is on disk with its pinned sha256."""
    folder = out_root / name
    for file, member in pin["members"].items():
        path = folder / file
        if not path.is_file() or sha256(path.read_bytes()) != member["sha256"]:
            return False
    return True


def fetch(name: str, pin: Dict[str, Any], out_root: Path = OUT_ROOT) -> None:
    """Download the zip, verify it, extract the kept members, verify each,
    write them and the provenance. Raises RuntimeError naming any mismatch."""
    request = urllib.request.Request(pin["zip_url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    digest = sha256(data)
    if digest != pin["zip_sha256"]:
        raise RuntimeError(f"{name}: the zip's sha256 is {digest}, pinned {pin['zip_sha256']} "
                           f"({pin['zip_url']}); nothing written")
    folder = out_root / name
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for file, member in pin["members"].items():
            body = archive.read(member["member"])
            if sha256(body) != member["sha256"]:
                raise RuntimeError(f"{name}: {member['member']} does not match its pin")
            (folder / file).write_bytes(body)
    provenance = {key: pin[key] for key in ("title", "page", "licence", "licence_url", "zip_url",
                                            "zip_cdn_url", "zip_sha256")}
    provenance["files"] = pin["members"]
    (folder / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="verify what is there; fetch nothing")
    args = parser.parse_args(argv)
    status = 0
    for name, pin in PINS.items():
        if check(name, pin):
            print(f"OK {name}: {OUT_ROOT / name}")
            continue
        if args.check:
            print(f"MISSING {name}: run scripts/fetch_weather_textures.py")
            status = 1
            continue
        fetch(name, pin)
        print(f"FETCHED {name}: {OUT_ROOT / name} ({pin['licence']})")
    return status


if __name__ == "__main__":
    sys.exit(main())
