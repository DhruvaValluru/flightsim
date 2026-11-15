#!/usr/bin/env python3
"""Fetch JangaFX's CC0 "Tornado Looping" VDB into the asset cache (2026-11-14).

The owner's tornado (scripts/bake_tornado_flipbook.py bakes it into the flipbook that
M_TornadoFlipbook plays in the funnel's place). The raw simulation is about 1.7 GB, so it
NEVER enters git: it lives in a cache beside the checkout,

    <repo>/../flightsim_assets/jangafx_tornado/      (FLIGHTSIM_ASSETS_DIR overrides <repo>/../flightsim_assets)

and only the baked atlas and its JSON (a few MB, assets/looks/tornado_vdb/) are committed,
so every checkout renders the new tornado with no download. This script is the named step
that fills the cache: it downloads the zip from JangaFX's official page, checks it against
the pinned sha256 BEFORE anything is extracted (a mismatch is refused by name and the file
removed), unzips it, and writes a marker; run again, it does nothing while the marker and
the VDB files are there.

Source: JangaFX EmberGen free VDB animations, https://jangafx.com/software/embergen/download/free-vdb-animations,
CC0 1.0 as stated on that page (THIRD_PARTY_VISUAL.md lists it).

    python scripts/fetch_tornado_vdb.py           # fetch, verify, unzip (skip if present)
    python scripts/fetch_tornado_vdb.py --check   # say whether the cache is complete, fetch nothing

The pin below is a PLACEHOLDER until the render machine records the URL, size and sha256 of
its own download; until then the fetch refuses by name (tornado_vdb.pin_missing) rather than
trust an unpinned file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

REPO = Path(__file__).resolve().parents[1]
ENV_ASSETS = "FLIGHTSIM_ASSETS_DIR"
CACHE_NAME = "jangafx_tornado"
MARKER = ".fetched.json"
USER_AGENT = "flightsim-tornado-vdb/1 (github.com/DhruvaValluru/flightsim)"

#: The one pinned download. url / zip_bytes / zip_sha256 are filled from the render
#: machine's download (p3-windows, 2026-11-14); None = not pinned yet.
PIN: Dict[str, Any] = {
    "title": "Tornado Looping (JangaFX EmberGen free VDB)",
    "page": "https://jangafx.com/software/embergen/download/free-vdb-animations",
    "licence": "CC0-1.0",
    "licence_basis": "the download page states the free VDB simulations are licensed CC0 (Public Domain)",
    # MediaFire (the page's link) serves a Cloudflare challenge to scripts, so the render machine
    # downloads it in a browser and installs it with --zip; the URL is kept as the source of record.
    "zip_url": "https://www.mediafire.com/file/fynwmhozanxv821/TornadoLoopingVDB.zip/file",
    "zip_bytes": 1797795595,
    "zip_sha256": "492c99321ae911d0ad6c6ff3df6eb53c83e443ba91b6aab7b97ba86e536ac57c",
    "zip_name": "TornadoLoopingVDB.zip",
    # What the zip holds (p3-windows, 2026-11-14): TornadoLooping/TornadoVDB/tornado_0000..0127.vdb,
    # 128 frames (the page says 200), one "density" grid each (half-float, blosc), EmberGen 0.7.5.7.
    "frames": 128,
}


class FetchRefused(RuntimeError):
    """A refusal by name (the message starts with its code)."""


def cache_dir(env: Optional[Dict[str, str]] = None) -> Path:
    """Where the VDB lives: $FLIGHTSIM_ASSETS_DIR/jangafx_tornado, else <repo>/../flightsim_assets/jangafx_tornado."""
    env = os.environ if env is None else env
    root = env.get(ENV_ASSETS, "").strip()
    base = Path(root) if root else REPO.parent / "flightsim_assets"
    return base / CACHE_NAME


def vdb_files(folder: Path):
    return sorted(p for p in folder.rglob("*.vdb")) if folder.is_dir() else []


def vdb_dir(folder: Path) -> Optional[Path]:
    """The folder holding the VDB sequence (the zip may nest it), or None."""
    files = vdb_files(folder)
    return files[0].parent if files else None


def is_present(folder: Path, pin: Dict[str, Any] = PIN) -> bool:
    """True when the marker records the pinned sha256 and VDB files are on disk."""
    marker = folder / MARKER
    if not marker.is_file() or not vdb_files(folder):
        return False
    try:
        record = json.loads(marker.read_text(encoding="utf-8"))
    except ValueError:
        return False
    return bool(pin.get("zip_sha256")) and record.get("zip_sha256") == pin["zip_sha256"]


def _require_pin(pin: Dict[str, Any]) -> None:
    if not pin.get("zip_url") or not pin.get("zip_sha256"):
        raise FetchRefused(
            "tornado_vdb.pin_missing: scripts/fetch_tornado_vdb.py PIN has no zip_url / zip_sha256 yet; "
            "record the render machine's download (its URL from " + pin["page"] + ", size and sha256) "
            "in PIN, or pass --vdb-dir to the bake")


def fetch(folder: Optional[Path] = None, pin: Dict[str, Any] = PIN,
          opener: Callable[..., Any] = urllib.request.urlopen) -> Path:
    """The VDB folder, downloading and unzipping only when not present. A download whose
    sha256 is not the pin's is deleted and refused (tornado_vdb.sha_mismatch)."""
    folder = cache_dir() if folder is None else Path(folder)
    if is_present(folder, pin):
        found = vdb_dir(folder)
        assert found is not None
        return found
    _require_pin(pin)
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / (pin["zip_name"] + ".part")
    digest = hashlib.sha256()
    size = 0
    request = urllib.request.Request(pin["zip_url"], headers={"User-Agent": USER_AGENT})
    with opener(request) as response, part.open("wb") as out:
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            digest.update(block)
            size += len(block)
            out.write(block)
    got = digest.hexdigest()
    if got != pin["zip_sha256"]:
        part.unlink(missing_ok=True)
        raise FetchRefused(f"tornado_vdb.sha_mismatch: {pin['zip_url']} hashed {got} ({size} bytes), "
                           f"its pin is {pin['zip_sha256']}; nothing was extracted")
    zip_path = folder / pin["zip_name"]
    part.replace(zip_path)
    return _install(zip_path, folder, pin, got, size)


def install_zip(zip_path: Path, folder: Optional[Path] = None, pin: Dict[str, Any] = PIN) -> Path:
    """Install a zip downloaded by hand (the page's host challenges scripts): checked against the
    pin's sha256 and size, then unzipped into the cache exactly as a fetch would."""
    folder = cache_dir() if folder is None else Path(folder)
    if is_present(folder, pin):
        found = vdb_dir(folder)
        assert found is not None
        return found
    _require_pin(pin)
    digest = hashlib.sha256()
    size = 0
    with Path(zip_path).open("rb") as src:
        for block in iter(lambda: src.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
    got = digest.hexdigest()
    if got != pin["zip_sha256"]:
        raise FetchRefused(f"tornado_vdb.sha_mismatch: {zip_path} hashed {got} ({size} bytes), "
                           f"its pin is {pin['zip_sha256']}; nothing was extracted")
    folder.mkdir(parents=True, exist_ok=True)
    return _install(Path(zip_path), folder, pin, got, size)


def _install(zip_path: Path, folder: Path, pin: Dict[str, Any], got: str, size: int) -> Path:
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            target = (folder / member).resolve()
            if folder.resolve() not in target.parents and target != folder.resolve():
                raise FetchRefused(f"tornado_vdb.zip_path: member {member!r} would land outside {folder}")
        archive.extractall(folder)
    found = vdb_dir(folder)
    if found is None:
        raise FetchRefused(f"tornado_vdb.no_vdb: {zip_path} held no .vdb file")
    (folder / MARKER).write_text(json.dumps({"zip_sha256": got, "zip_bytes": size, "url": pin["zip_url"],
                                             "licence": pin["licence"], "vdb_dir": str(found)},
                                            indent=1) + "\n", encoding="utf-8")
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", type=Path, default=None, help=f"default {cache_dir()}")
    ap.add_argument("--check", action="store_true", help="say whether the cache is complete; fetch nothing")
    ap.add_argument("--zip", type=Path, default=None,
                    help="a zip downloaded by hand in a browser (the host challenges scripts); checked and unzipped")
    ns = ap.parse_args(argv)
    folder = ns.dest or cache_dir()
    if ns.check:
        ok = is_present(folder)
        print(f"{'present' if ok else 'absent'}: {folder}")
        return 0 if ok else 1
    try:
        found = install_zip(ns.zip, folder) if ns.zip else fetch(folder)
    except FetchRefused as refusal:
        print(f"REFUSED {refusal}")
        return 3
    print(f"tornado VDB ready: {found} ({len(vdb_files(found))} frames)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
