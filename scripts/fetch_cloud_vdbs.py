#!/usr/bin/env python3
"""Fetch JangaFX's free CC0 Cloud Pack (static cloud VDBs) into a cache outside git.

The impostor clouds (scripts/bake_cloud_impostors.py, -cloud-impostors=) are baked
ONCE from these VDBs on the render machine; the committed atlases under
assets/looks/clouds/impostors/ are what every render reads, so a checkout renders
the clouds without this download. The VDBs are only needed to bake again.

Source: https://jangafx.com/software/embergen/download/free-vdb-animations ("Cloud
Pack", ~104 MB, 10 variations; the page: "These free VDB simulations are licensed
as CC0 (Public Domain)"). THIRD_PARTY_VISUAL.md lists it.

    python scripts/fetch_cloud_vdbs.py                  # fetch (URL pinned below), verify, unzip
    python scripts/fetch_cloud_vdbs.py --zip PATH       # a zip downloaded by hand (the page may gate it)
    python scripts/fetch_cloud_vdbs.py --check          # verify what is there, fetch nothing

Cache: <repo>/../flightsim_assets/jangafx_clouds (FLIGHTSIM_ASSETS_DIR overrides the
flightsim_assets folder). The zip is checked against PIN["zip_sha256"] before anything
is unpacked; a mismatch refuses by name (assets.cloud_vdbs_sha). The pin is the
render machine's download of 2026-11-14 (an empty pin would refuse to unpack unless
--trust-first-download is given).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, Optional

REPO = Path(__file__).resolve().parents[1]
USER_AGENT = "flightsim-cloud-vdbs/1 (github.com/DhruvaValluru/flightsim)"
CACHE_NAME = "jangafx_clouds"
MARKER = "fetched.json"

#: The pin, from the render machine's download on 2026-11-14: CloudPackVDB.zip,
#: 109,761,538 bytes; it unpacks to CloudPack/CloudPackVDB/cloud_01_variant_0000.vdb ..
#: cloud_10_variant_0000.vdb (16-22 MB each, one half-float "density" grid, one static
#: frame, EmberGen 0.7.5.7). The page's download link is not a stable URL, so zip_url
#: stays empty: download from the page and pass --zip PATH (the digest is checked).
PIN: Dict[str, Optional[str]] = {
    "title": "Cloud Pack (JangaFX EmberGen free VDB simulations)",
    "page": "https://jangafx.com/software/embergen/download/free-vdb-animations",
    "licence": "CC0-1.0",
    "zip_name": "CloudPackVDB.zip",
    "zip_bytes": "109761538",
    "zip_url": None,
    "zip_sha256": "3676ba4c7ac431446731f956f98e925ad3db31354b8b4adcb137dc0250595f73",
}


class CloudVdbError(RuntimeError):
    """Refused by name (core/messages/catalog.yaml)."""


def assets_root(env: Optional[Dict[str, str]] = None) -> Path:
    env = os.environ if env is None else env
    override = env.get("FLIGHTSIM_ASSETS_DIR")
    return Path(override) if override else REPO.parent / "flightsim_assets"


def cache_dir(env: Optional[Dict[str, str]] = None) -> Path:
    return assets_root(env) / CACHE_NAME


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def present(folder: Path, pin: Dict[str, Optional[str]]) -> bool:
    """The cache already holds this pin's unpacked VDBs."""
    marker = folder / MARKER
    if not marker.is_file():
        return False
    try:
        record = json.loads(marker.read_text(encoding="utf-8"))
    except ValueError:
        return False
    if not any(folder.rglob("*.vdb")):
        return False
    return pin.get("zip_sha256") is None or record.get("zip_sha256") == pin.get("zip_sha256")


def verify(zip_path: Path, pin: Dict[str, Optional[str]], trust_first: bool) -> str:
    digest = sha256(zip_path)
    want = pin.get("zip_sha256")
    if want is None:
        if not trust_first:
            raise CloudVdbError(
                f"assets.cloud_vdbs_unpinned: {zip_path} hashes {digest}, and the pin is empty; put "
                f"zip_sha256 = '{digest}' in scripts/fetch_cloud_vdbs.py PIN, or re-run with "
                f"--trust-first-download")
        print(f"UNPINNED: {zip_path} sha256 {digest} (record it in PIN)")
    elif digest != want:
        raise CloudVdbError(f"assets.cloud_vdbs_sha: {zip_path} hashes {digest}, the pin is {want}")
    return digest


def unpack(zip_path: Path, folder: Path, digest: str) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            name = Path(member.filename)
            if member.is_dir() or name.is_absolute() or ".." in name.parts:
                continue
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            count += name.suffix.lower() == ".vdb"
    (folder / MARKER).write_text(json.dumps({"zip_sha256": digest, "vdb_files": count,
                                             "page": PIN["page"], "licence": PIN["licence"]},
                                            indent=2) + "\n", encoding="utf-8")
    return count


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, open(target, "wb") as out:
        shutil.copyfileobj(response, out)


def fetch(zip_arg: Optional[Path] = None, trust_first: bool = False, check: bool = False,
          env: Optional[Dict[str, str]] = None, pin: Optional[Dict[str, Optional[str]]] = None) -> Path:
    """The cache folder holding the unpacked VDBs (fetched only when absent)."""
    pin = PIN if pin is None else pin
    folder = cache_dir(env)
    if present(folder, pin):
        print(f"PRESENT: {folder}")
        return folder
    if check:
        raise CloudVdbError(f"assets.cloud_vdbs_missing: no unpacked Cloud Pack at {folder}")
    if zip_arg is None:
        if not pin.get("zip_url"):
            raise CloudVdbError(
                f"assets.cloud_vdbs_missing: no zip URL is pinned; download the Cloud Pack from "
                f"{pin['page']} and pass it with --zip PATH")
        zip_arg = folder.parent / f"{CACHE_NAME}.zip"
        download(str(pin["zip_url"]), zip_arg)
    digest = verify(Path(zip_arg), pin, trust_first)
    count = unpack(Path(zip_arg), folder, digest)
    print(f"UNPACKED: {count} VDB files into {folder}")
    return folder


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zip", type=Path, help="a Cloud Pack zip downloaded by hand")
    parser.add_argument("--check", action="store_true", help="verify the cache, fetch nothing")
    parser.add_argument("--trust-first-download", action="store_true",
                        help="unpack an unpinned zip and print its digest for PIN")
    args = parser.parse_args(argv)
    try:
        fetch(args.zip, args.trust_first_download, args.check)
    except CloudVdbError as error:
        print(f"REFUSED {error}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
