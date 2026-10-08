#!/usr/bin/env python3
"""Fetch CC0 ground textures from Poly Haven for the flat-scene ground materials.

The flat scene's ground follows the spec's surface word (desert, forest,
grassland, snow, bare, city; the ocean is procedural water and fetches
nothing). scripts/ue_create_materials.py builds each ground material
procedurally, so a build WITHOUT this step still renders every surface;
with it, the material samples a real photographed texture instead of the
procedural pattern. This script is the named step that puts the files
there:

    data/textures/polyhaven/<surface>/diffuse.jpg
    data/textures/polyhaven/<surface>/normal.jpg      (OpenGL convention)
    data/textures/polyhaven/<surface>/rough.jpg
    data/textures/polyhaven/<surface>/provenance.json

Where the bytes come from: Poly Haven (polyhaven.com), whose assets are
CC0 1.0 (public domain, no attribution needed). Their public API asks
software that uses the LIVE API to credit them visibly; the provenance
and NOTICE.md carry "Textures: Poly Haven (polyhaven.com), CC0" and the
render records which asset each surface used. The API wants a
descriptive User-Agent (sent).

How an asset is chosen, honestly: the asset ids could not be checked
from the container this was written in (api.polyhaven.com is not
reachable through its proxy), so no id is hard-coded. The script lists
Poly Haven's textures, keeps those whose tags or categories match the
surface's words, prefers aerial ones (the ground is seen from the air),
and takes the most downloaded; ``--pick desert=<asset_id>`` overrides
the choice. The choice, its tags and the download URLs are recorded.
Every file's md5 is checked against the API's when the API gives one,
and a sha256 is recorded; an existing file with another digest is a
refusal unless ``--force``.

    python scripts/fetch_ground_textures.py                 # all surfaces, 1k
    python scripts/fetch_ground_textures.py --res 2k --only desert,snow
    python scripts/fetch_ground_textures.py --list desert   # show candidates, fetch nothing

Then re-run scripts/ue_create_materials.py in the editor so the ground
materials pick the textures up.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "data" / "textures" / "polyhaven"
API = "https://api.polyhaven.com"
USER_AGENT = "flightsim-ground-textures/1 (github.com/DhruvaValluru/flightsim)"
CREDIT = "Textures: Poly Haven (polyhaven.com), CC0 1.0"
LICENCE = "CC0-1.0"

#: The surface words (core/environment/surface.py SURFACE_CLASSES) that
#: take a photographed texture, each with the words a Poly Haven texture's
#: tags or categories must carry. The ocean is procedural water.
SURFACE_WORDS: Dict[str, Tuple[str, ...]] = {
    "desert": ("sand", "desert", "dune"),
    "forest": ("forest", "leaves", "moss", "forest floor"),
    "grassland": ("grass", "meadow", "field"),
    "snow": ("snow",),
    "bare": ("rock", "rocky", "gravel", "soil", "dirt"),
    "city": ("asphalt", "concrete", "road"),
}
#: Poly Haven's texture map names: what each file here is made from.
MAPS = {"diffuse": "Diffuse", "normal": "nor_gl", "rough": "Rough"}
RESOLUTIONS = ("1k", "2k", "4k")

Fetch = Callable[[str], bytes]


class TextureError(RuntimeError):
    """A refusal, by name (``.constraint``)."""

    def __init__(self, constraint: str, message: str) -> None:
        self.constraint = constraint
        super().__init__(f"{constraint}: {message}")


def http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def get_json(fetch: Fetch, url: str) -> Any:
    try:
        return json.loads(fetch(url).decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise TextureError("textures.unreachable", f"{url}: {exc}") from None


def candidates(assets: Dict[str, Dict[str, Any]], surface: str) -> List[Tuple[str, Dict[str, Any]]]:
    """The textures whose tags or categories match the surface's words,
    best first: aerial ones before the rest, then by download count."""
    words = SURFACE_WORDS[surface]
    out = []
    for asset_id, info in assets.items():
        labels = {str(t).lower() for t in (info.get("tags") or [])}
        labels |= {str(c).lower() for c in (info.get("categories") or [])}
        if not any(w in labels for w in words):
            continue
        aerial = "aerial" in labels or asset_id.startswith("aerial")
        out.append((asset_id, info, aerial))
    out.sort(key=lambda item: (not item[2], -int(item[1].get("download_count") or 0), item[0]))
    return [(asset_id, info) for asset_id, info, _ in out]


def map_files(files: Dict[str, Any], resolution: str) -> Dict[str, Dict[str, Any]]:
    """The three maps' jpg entries ({url, md5?, size?}) at a resolution;
    ``textures.map_missing`` names what the asset does not carry."""
    out: Dict[str, Dict[str, Any]] = {}
    for name, key in MAPS.items():
        entry = (((files.get(key) or {}).get(resolution) or {}).get("jpg"))
        if not isinstance(entry, dict) or not entry.get("url"):
            raise TextureError("textures.map_missing",
                               f"no {key} jpg at {resolution} (the asset carries "
                               f"{sorted(files)})")
        out[name] = entry
    return out


def fetch_surface(surface: str, assets: Dict[str, Dict[str, Any]], fetch: Fetch,
                  resolution: str = "1k", pick: Optional[str] = None,
                  out_dir: Path = OUT_DIR, force: bool = False) -> Dict[str, Any]:
    """Download one surface's three maps and write its provenance."""
    if pick is not None:
        if pick not in assets:
            raise TextureError("textures.unknown_asset", f"{surface}: no texture {pick!r}")
        chosen = [(pick, assets[pick])]
    else:
        chosen = candidates(assets, surface)
        if not chosen:
            raise TextureError("textures.no_candidate",
                               f"{surface}: no Poly Haven texture is tagged {SURFACE_WORDS[surface]}")
    errors = []
    for asset_id, info in chosen[:5]:
        files = get_json(fetch, f"{API}/files/{asset_id}")
        try:
            entries = map_files(files, resolution)
        except TextureError as exc:
            errors.append(f"{asset_id}: {exc}")
            continue
        target = out_dir / surface
        target.mkdir(parents=True, exist_ok=True)
        written = {}
        for name, entry in entries.items():
            data = fetch(entry["url"])
            md5 = hashlib.md5(data).hexdigest()
            if entry.get("md5") and entry["md5"] != md5:
                raise TextureError("textures.digest",
                                   f"{entry['url']}: md5 {md5}, the API says {entry['md5']}")
            path = target / f"{name}.jpg"
            sha = hashlib.sha256(data).hexdigest()
            if path.is_file() and not force:
                old = hashlib.sha256(path.read_bytes()).hexdigest()
                if old != sha:
                    raise TextureError("textures.digest",
                                       f"{path} holds other bytes (sha256 {old[:12]}...); "
                                       f"--force replaces it")
            path.write_bytes(data)
            written[name] = {"file": path.name, "url": entry["url"], "md5": md5,
                             "sha256": sha, "bytes": len(data), "polyhaven_map": MAPS[name]}
        provenance = {
            "surface": surface, "asset_id": asset_id, "name": info.get("name"),
            "tags": info.get("tags"), "categories": info.get("categories"),
            "resolution": resolution, "files": written, "licence": LICENCE,
            "credit": CREDIT, "source": f"https://polyhaven.com/a/{asset_id}",
            "chosen_by": "--pick" if pick is not None else
                         f"tags/categories matching {list(SURFACE_WORDS[surface])}, aerial "
                         f"first, then most downloaded",
            "fetched_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        }
        (target / "provenance.json").write_text(json.dumps(provenance, indent=1),
                                                encoding="utf-8")
        return provenance
    raise TextureError("textures.map_missing",
                       f"{surface}: none of the top candidates carries all three maps: "
                       + "; ".join(errors))


def main(argv: Optional[List[str]] = None, fetch: Fetch = http_get) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--res", default="1k", choices=RESOLUTIONS)
    parser.add_argument("--only", default="", help="comma-separated surfaces")
    parser.add_argument("--pick", action="append", default=[], metavar="SURFACE=ASSET_ID")
    parser.add_argument("--list", metavar="SURFACE", help="print candidates, fetch nothing")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    picks = dict(p.split("=", 1) for p in args.pick)
    surfaces = [s for s in args.only.split(",") if s] or list(SURFACE_WORDS)
    unknown = [s for s in [*surfaces, *picks, *([args.list] if args.list else [])]
               if s not in SURFACE_WORDS]
    if unknown:
        print(f"REFUSED -- textures.surface: {unknown} not in {list(SURFACE_WORDS)}")
        return 2
    try:
        assets = get_json(fetch, f"{API}/assets?t=textures")
        if args.list:
            for asset_id, info in candidates(assets, args.list)[:20]:
                print(f"{asset_id:32} {info.get('download_count', 0):>8}  {info.get('tags')}")
            return 0
        for surface in surfaces:
            record = fetch_surface(surface, assets, fetch, args.res, picks.get(surface),
                                   args.out, args.force)
            print(f"{surface:10} {record['asset_id']} ({record['resolution']}) -> "
                  f"{args.out / surface}")
    except TextureError as exc:
        print(f"REFUSED -- {exc}")
        return 1
    print(CREDIT)
    print("Now re-run scripts/ue_create_materials.py in the editor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
