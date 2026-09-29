#!/usr/bin/env python3
"""Fetch the two spectral tables the band proxy needs, with provenance.

core/capture/radiometry.py converts the engine's photometric channels
into a band radiance proxy through two published tables:

* the CIE 1924 photopic luminous efficiency function V(lambda) at 1 nm,
  360-830 nm (CIE 018:2019 "The basis of physical photometry", table 1;
  the CVRL distribution file ``vl1924e_1.csv``), written to
  ``assets/cie/vlambda_1nm.csv``;
* the ASTM G173-03 reference direct + circumsolar spectral irradiance
  (AM1.5, 280-4000 nm; NREL "Reference Air Mass 1.5 Spectra"), written
  to ``assets/illuminants/astm_g173_direct.csv``.

NOTHING about either table is written into code: a build without the
files refuses ``sensing.radiometry`` / ``sensing.band`` by name, and
this script is the named step that puts them there. Each file gets a
``.sha256`` sidecar and a ``provenance.json`` naming the URL it came
from, when, the bytes' digest and what was done to them.

Where the bytes come from, honestly: the PRIMARY hosts (cie.co.at,
cvrl.org, nrel.gov) are unreachable through this container's proxy
(measured 2026-09-29: cie.co.at and files.cie.co.at refuse the CONNECT,
cvrl.org answers 403, nrel.gov refuses), so the script reads two
MIRRORS that redistribute the same tables verbatim under a permissive
licence, and says so in the provenance:

* ``colour-science/colour`` (BSD-3-Clause), ``colour/colorimetry/
  datasets/lefs.py``, the ``"CIE 1924 Photopic Standard Observer"``
  mapping -- the CVRL 1 nm table transcribed (their citation: CVRL
  lumindex, "Older CIE Standards");
* ``pvlib/pvlib-python`` (BSD-3-Clause), ``pvlib/data/ASTMG173.csv`` --
  NREL's G173-03 CSV (columns wavelength, extraterrestrial, global tilt,
  direct + circumsolar; W m^-2 nm^-1).

``--primary`` asks for the primary URLs first (they will work on a
networked machine); the provenance then records which source answered.
A digest mismatch against a previously written sidecar is a refusal,
never a silent overwrite (``--force`` replaces it and says so).

What is NOT claimed: that a mirror equals the primary byte for byte
(the primary digests were not measured here: ``primary_verified`` is
false in the provenance until someone runs ``--primary`` on a machine
that reaches them); that V(lambda) at 1 nm is the CIE's own tabulation
rather than CVRL's interpolation of the 5 nm 1924 table (it is CVRL's,
as the CIE distributes it).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import ssl
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
CIE_DIR = REPO / "assets" / "cie"
ILLUMINANT_DIR = REPO / "assets" / "illuminants"
VLAMBDA_FILE = CIE_DIR / "vlambda_1nm.csv"
G173_FILE = ILLUMINANT_DIR / "astm_g173_direct.csv"

#: The primary sources, named even where unreachable.
PRIMARY = {
    "vlambda": ("http://www.cvrl.org/database/data/lum/vl1924e_1.csv",
                "CIE 018:2019 table 1 / CVRL vl1924e_1.csv (CIE 1924 photopic V(lambda), 1 nm)"),
    "g173": ("https://www.nrel.gov/grid/solar-resource/assets/data/astmg173.xls",
             "NREL Reference Air Mass 1.5 Spectra, ASTM G173-03 (direct + circumsolar column)"),
}
#: The mirrors that answer through this container's proxy.
MIRROR = {
    "vlambda": ("https://raw.githubusercontent.com/colour-science/colour/develop/"
                "colour/colorimetry/datasets/lefs.py",
                "colour-science/colour lefs.py, mapping 'CIE 1924 Photopic Standard Observer' "
                "(BSD-3-Clause; CVRL's 1 nm table transcribed)"),
    "g173": ("https://raw.githubusercontent.com/pvlib/pvlib-python/main/pvlib/data/ASTMG173.csv",
             "pvlib/pvlib-python ASTMG173.csv (BSD-3-Clause; NREL's G173-03 table verbatim)"),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, timeout: float = 60.0) -> bytes:
    context = ssl.create_default_context()
    with urllib.request.urlopen(url, timeout=timeout, context=context) as reply:
        return reply.read()


def parse_vlambda_from_lefs(text: str) -> List[Tuple[int, float]]:
    """The CIE 1924 mapping out of colour-science's lefs.py: every
    ``<nm>: <value>,`` line between the mapping's opening and its
    closing brace."""
    start = text.index('"CIE 1924 Photopic Standard Observer": {')
    end = text.index("}", start)
    rows: List[Tuple[int, float]] = []
    for match in re.finditer(r"^\s*(\d+):\s*([0-9.eE+-]+),\s*$", text[start:end], re.M):
        rows.append((int(match.group(1)), float(match.group(2))))
    if not rows:
        raise ValueError("no CIE 1924 rows found in the mirror text")
    return rows


def parse_vlambda_csv(text: str) -> List[Tuple[int, float]]:
    """The CVRL csv: ``wavelength,value`` per line, no header."""
    rows: List[Tuple[int, float]] = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0] and parts[1]:
            try:
                rows.append((int(float(parts[0])), float(parts[1])))
            except ValueError:
                continue
    return rows


def check_vlambda(rows: List[Tuple[int, float]]) -> None:
    """What a V(lambda) table must look like before it is cached: 1 nm
    steps 360..830, every value in [0, 1], the peak 1.0 at 555 nm."""
    nm = [w for w, _ in rows]
    if nm != list(range(360, 831)):
        raise ValueError(f"V(lambda) rows are not 1 nm from 360 to 830 ({nm[:3]}..{nm[-3:]}, {len(nm)})")
    values = dict(rows)
    if values[555] != 1.0:
        raise ValueError(f"V(555 nm) is {values[555]}, not 1.0")
    if any(not (0.0 <= v <= 1.0) for v in values.values()):
        raise ValueError("a V(lambda) value outside [0, 1]")


def parse_g173(text: str) -> List[Tuple[float, float, float, float]]:
    """NREL's CSV: a title line, a header, then wavelength (nm),
    extraterrestrial, global tilt, direct + circumsolar (W m^-2 nm^-1)."""
    rows: List[Tuple[float, float, float, float]] = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            rows.append((float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])))
        except ValueError:
            continue
    return rows


def check_g173(rows) -> None:
    if not rows or rows[0][0] != 280.0 or rows[-1][0] != 4000.0:
        raise ValueError("G173 rows do not span 280..4000 nm")
    if len(rows) != 2002:
        raise ValueError(f"G173 holds {len(rows)} rows, not the standard's 2002")
    if any(r[3] < 0.0 for r in rows):
        raise ValueError("a negative direct irradiance")


def write_table(path: Path, header: str, lines: List[str], provenance: Dict, force: bool) -> str:
    """The CSV, its ``.sha256`` sidecar and ``<stem>.provenance.json``;
    refuses to overwrite a cached table whose digest differs unless
    ``force``."""
    body = header + "\n" + "\n".join(lines) + "\n"
    data = body.encode("utf-8")
    digest = sha256_bytes(data)
    sidecar = path.with_suffix(".csv.sha256")
    if sidecar.is_file() and not force:
        recorded = sidecar.read_text(encoding="utf-8").split()[0]
        if recorded != digest:
            raise SystemExit(f"REFUSED -- sensing.radiometry: {path.name} is already cached with sha256 "
                             f"{recorded[:16]}.. and the fetched table digests {digest[:16]}..; "
                             f"pass --force to replace it, and say why in the commit")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    sidecar.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    provenance = dict(provenance, file=path.name, sha256=digest, bytes=len(data))
    path.with_name(path.stem + ".provenance.json").write_text(
        json.dumps(provenance, indent=1) + "\n", encoding="utf-8")
    return digest


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--primary", action="store_true",
                        help="try the primary hosts before the mirrors")
    parser.add_argument("--force", action="store_true", help="replace a cached table whose digest differs")
    args = parser.parse_args(argv)
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    def get(key: str):
        order = [("primary", PRIMARY[key]), ("mirror", MIRROR[key])] if args.primary \
            else [("mirror", MIRROR[key])]
        errors = []
        for kind, (url, description) in order:
            try:
                data = fetch(url)
                return kind, url, description, data
            except Exception as exc:  # noqa: BLE001 -- every host is tried, then named
                errors.append(f"{kind} {url}: {exc.__class__.__name__}: {exc}")
        raise SystemExit("REFUSED -- sensing.radiometry: no source answered:\n  " + "\n  ".join(errors))

    kind, url, description, raw = get("vlambda")
    text = raw.decode("utf-8")
    rows = parse_vlambda_csv(text) if kind == "primary" else parse_vlambda_from_lefs(text)
    check_vlambda(rows)
    digest_v = write_table(
        VLAMBDA_FILE, "wavelength_nm,v_lambda",
        [f"{w},{v:.10g}" for w, v in rows],
        {"table": "CIE 1924 photopic luminous efficiency function V(lambda), 1 nm, 360-830 nm",
         "primary_source": PRIMARY["vlambda"][0], "primary_description": PRIMARY["vlambda"][1],
         "fetched_from": url, "fetched_kind": kind, "fetched_description": description,
         "fetched_at_utc": now, "fetched_bytes_sha256": sha256_bytes(raw),
         "primary_verified": kind == "primary",
         "transform": ("the mapping's <nm>: <value> rows written as wavelength_nm,v_lambda; "
                       "values unchanged" if kind == "mirror" else "columns renamed"),
         "licence": "CIE data as distributed by CVRL; mirror packaging BSD-3-Clause (colour-science)",
         "unit": "dimensionless, V(555 nm) = 1"},
        args.force)
    print(f"  {VLAMBDA_FILE.relative_to(REPO)}: {len(rows)} rows, sha256 {digest_v[:16]}.. ({kind}: {url})")

    kind, url, description, raw = get("g173")
    rows_g = parse_g173(raw.decode("utf-8"))
    check_g173(rows_g)
    digest_g = write_table(
        G173_FILE, "wavelength_nm,extraterrestrial_w_m2_nm,global_tilt_w_m2_nm,direct_circumsolar_w_m2_nm",
        [f"{w:g},{e:g},{g:g},{d:g}" for w, e, g, d in rows_g],
        {"table": "ASTM G173-03 reference spectra (AM1.5): extraterrestrial, global tilt 37 deg, "
                  "direct + circumsolar; W m^-2 nm^-1, 280-4000 nm",
         "primary_source": PRIMARY["g173"][0], "primary_description": PRIMARY["g173"][1],
         "fetched_from": url, "fetched_kind": kind, "fetched_description": description,
         "fetched_at_utc": now, "fetched_bytes_sha256": sha256_bytes(raw),
         "primary_verified": kind == "primary",
         "transform": "the CSV's four numeric columns, title and header lines dropped; values unchanged",
         "licence": "ASTM G173-03 reference spectra as published by NREL (US government work); "
                    "mirror packaging BSD-3-Clause (pvlib)",
         "unit": "W m^-2 nm^-1"},
        args.force)
    print(f"  {G173_FILE.relative_to(REPO)}: {len(rows_g)} rows, sha256 {digest_g[:16]}.. ({kind}: {url})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
