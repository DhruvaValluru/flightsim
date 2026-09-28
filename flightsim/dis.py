"""A DIS Entity State PDU stream from a captured run (IEEE 1278.1-2012).

    .venv/bin/python -m flightsim.dis RUN_DIR --out entity_state.dis \
        [--site N --application N --entity N] [--exercise N]
    .venv/bin/python -m flightsim.dis --decode entity_state.dis [--limit N]

The first form reads ``RUN_DIR/telemetry.json`` (written by
``python -m flightsim.capture``) and writes one Entity State PDU per
telemetry sample into ``--out`` -- protocol version 7, PDU type 1, 144
bytes each, back to back -- with ``dis_manifest.json`` beside it: the
counts, the datum handling (the ellipsoidal height from the run's datum
block, or 'orthometric treated as ellipsoidal' when the run has none),
the entity type with which of its numbers are verified, the position
check against pyproj and the ``interop.dis`` applied-variable record.

The second form decodes a stream and prints one line per PDU: the time
past the hour, the entity id, the geodetic position recovered from the
ECEF location and the heading, pitch, roll recovered from the DIS Euler
angles (core/interop/geodesy.py), so a reader can compare them with the
telemetry by eye.

Refusals are by name (``REFUSED -- interop.dis.<what>: ...``), exit 2:
a directory with no telemetry (``interop.dis.run``), telemetry without
the geodetic columns (``interop.dis.channels``), an airframe the entity
type table does not carry (``interop.dis.airframe``), an entity id
outside 16 bits (``interop.dis.entity_id``), a file that is not a stream
of version-7 Entity State PDUs (``interop.dis.stream``).

What is NOT claimed: nothing is sent on a network and no DIS consumer
has read the stream here; the entity type's country, category and
subcategory are unverified here (the sidecar says so per field); the
decode lines are a reading aid, not a verifier. Nothing here is
behaviour: every behaviour is core/interop/dis.py's, tested there.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m flightsim.dis",
        description="Write or decode an IEEE 1278.1-2012 Entity State PDU stream.")
    parser.add_argument("run_dir", nargs="?", help="a run directory written by "
                        "flightsim.capture (holds telemetry.json)")
    parser.add_argument("--out", help="the stream file to write (dis_manifest.json "
                        "is written beside it)")
    parser.add_argument("--decode", metavar="FILE", help="decode this stream file "
                        "and print one line per PDU instead of writing one")
    parser.add_argument("--site", type=int, default=1, help="entity id: site (0..65535)")
    parser.add_argument("--application", type=int, default=1,
                        help="entity id: application (0..65535)")
    parser.add_argument("--entity", type=int, default=1, help="entity id: entity (0..65535)")
    parser.add_argument("--exercise", type=int, default=1, help="exercise id (0..255)")
    parser.add_argument("--limit", type=int, default=None,
                        help="with --decode: print at most this many PDUs")
    return parser


def _decode(path: Path, limit: Optional[int]) -> int:
    from core.interop.dis import DisError, describe, read_stream

    try:
        pdus = read_stream(path)
    except DisError as exc:
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        return 2
    print(f"{len(pdus)} Entity State PDU(s) in {path}")
    shown = pdus if limit is None else pdus[:max(0, limit)]
    for index, pdu in enumerate(shown):
        d = describe(pdu)
        e = d["entity_id"]
        print(f"  [{index}] t+{d['time_past_hour_s']:.6f} s  id {e['site']}:{e['application']}:"
              f"{e['entity']}  {d['marking']!s:11}  lat {d['lat_deg']:.6f} lon "
              f"{d['lon_deg']:.6f} h {d['h_ellipsoidal_m']:.2f} m  hdg {d['heading_deg']:.2f} "
              f"pitch {d['pitch_deg']:.2f} roll {d['roll_deg']:.2f} deg")
    if len(shown) < len(pdus):
        print(f"  ... {len(pdus) - len(shown)} more")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.decode:
        return _decode(Path(args.decode), args.limit)
    if not args.run_dir or not args.out:
        print("REFUSED -- interop.dis.arguments: give RUN_DIR and --out to write a "
              "stream, or --decode FILE to read one")
        return 2
    from core.interop.dis import DisError, feed

    try:
        manifest = feed(args.run_dir, args.out, site=args.site,
                        application=args.application, entity=args.entity,
                        exercise_id=args.exercise)
    except DisError as exc:
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        return 2
    check = manifest["position_check"]
    e = manifest["entity_id"]
    print(f"wrote {manifest['pdu_count']} Entity State PDU(s) for {manifest['samples']} "
          f"telemetry sample(s) to {args.out} ({manifest['stream_bytes']} bytes)")
    print(f"  entity: {e['site']}:{e['application']}:{e['entity']} marking "
          f"{manifest['marking']!r}, type {manifest['entity_type']}")
    print(f"  {manifest['datum']['handling']}")
    print(f"  position check: first PDU {check['residual_m']:.3e} m from pyproj "
          f"(tolerance {check['tolerance_m']:g} m) -> {'ok' if check['ok'] else 'FAILED'}")
    print(f"  manifest: {Path(args.out).parent / 'dis_manifest.json'}")
    return 0 if check["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
