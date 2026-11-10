"""The vendored Physically Based API materials database (CC0), read for the
aircraft master materials' measured constants (visual round 5, lane L4).

``assets/looks/physically_based/materials.json`` is the upstream
``deploy/v2/materials.json`` at the commit ``PIN.json`` names, vendored
byte-identical; :func:`load` refuses, by name, a file whose sha256 is not
the pinned one (an edited database is not the measured one).

Plain Python, stdlib only: this is imported by scripts/aircraft_look.py,
which also runs inside UnrealEditor's Python on the render machine.

What the numbers mean (the database's conventions, schema 2.2):

* ``color`` (linear sRGB) is the base colour. For a metal (``metalness``
  1) that is its normal-incidence reflectance F0, the number a metalness
  workflow such as UE's puts in BaseColor with Metallic 1.
* a dielectric carries ``ior``; its F0 is ((n - 1) / (n + 1))^2, and UE's
  Specular input is F0 / 0.08 (ShadingCommon.ush DielectricSpecularToF0).
* ``roughness`` is the database's perceptual (GGX alpha = r^2) roughness,
  the same convention as UE's Roughness input.
"""

from __future__ import annotations

import hashlib
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRECTORY = os.path.join(REPO, "assets", "looks", "physically_based")
MATERIALS_FILE = "materials.json"
PIN_FILE = "PIN.json"

#: UE's dielectric F0 per unit Specular (ShadingCommon.ush, UE 5.7.4).
UE_F0_PER_SPECULAR = 0.08


class PhysicallyBasedError(ValueError):
    """The vendored database cannot be used, and why."""


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_pin(directory=DIRECTORY):
    with open(os.path.join(directory, PIN_FILE), encoding="utf-8") as handle:
        return json.load(handle)


_CACHE = {}


def load(directory=DIRECTORY):
    """{name: material row} of the vendored database, verified against the
    pin's sha256 once per process."""
    if directory in _CACHE:
        return _CACHE[directory]
    pin = read_pin(directory)
    path = os.path.join(directory, MATERIALS_FILE)
    wanted = pin["files"][MATERIALS_FILE]["sha256"]
    actual = sha256_file(path)
    if actual != wanted:
        raise PhysicallyBasedError(
            f"{path}: sha256 {actual} is not the pinned {wanted} (PIN.json); the database "
            f"was edited, so its numbers are no longer the measured ones")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("header", {}).get("license") != "CC0 1.0 Universal":
        raise PhysicallyBasedError(f"{path}: header licence is {data.get('header', {}).get('license')!r}, "
                                   f"not 'CC0 1.0 Universal'")
    rows = {row["name"]: row for row in data["data"]}
    _CACHE[directory] = rows
    return rows


def material(name, directory=DIRECTORY):
    rows = load(directory)
    if name not in rows:
        raise PhysicallyBasedError(f"{name!r} is not in the vendored database ({len(rows)} materials)")
    return rows[name]


def linear_color(row):
    """The row's linear-sRGB base colour as an (r, g, b) tuple."""
    for entry in row.get("color", ()):
        if entry.get("colorSpace") == "srgb-linear":
            return tuple(float(c) for c in entry["color"][:3])
    raise PhysicallyBasedError(f"{row.get('name')!r} carries no srgb-linear colour")


def f0_from_ior(ior):
    """Normal-incidence Fresnel reflectance of a dielectric of index n."""
    n = float(ior)
    return ((n - 1.0) / (n + 1.0)) ** 2


def specular_from_ior(ior):
    """UE's Specular input for a dielectric of index n (F0 / 0.08)."""
    return f0_from_ior(ior) / UE_F0_PER_SPECULAR


def metal_f0(name, directory=DIRECTORY):
    """The measured F0 (linear sRGB) of a metal in the database; refuses a
    row that is not a metal (its colour would be an albedo, not an F0)."""
    row = material(name, directory)
    if row.get("metalness") != 1:
        raise PhysicallyBasedError(f"{name!r} has metalness {row.get('metalness')!r}: not a metal")
    return linear_color(row)
