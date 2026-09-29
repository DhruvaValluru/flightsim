"""A DIS Entity State PDU stream from a captured run (IEEE 1278.1-2012).

    .venv/bin/python -m flightsim.dis RUN_DIR --out entity_state.dis \
        [--site N --application N --entity N] [--exercise N]
    .venv/bin/python -m flightsim.dis --decode entity_state.dis [--limit N]
    .venv/bin/python -m flightsim.dis RUN_DIR --stream [--out-dir DIR] \
        [--emitter full_rate|thresholded] [--timestamp-mode relative|absolute --epoch ISO] \
        [--entity-type standard|fallback|unspecified] [--marking TEXT] [--force-id N] \
        [--udp HOST:PORT]

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

The third form (D2) writes the full-rate Entity State PDU log
``dis_entity_state.bin`` and its index ``dis_entity_state.json`` into the
run directory (or ``--out-dir``): core/interop/dis_stream.py, the same
files ``flightsim.capture --dis`` writes, so a run captured before the
option existed can get its stream after the fact. The entity type comes
from the standard table by default and refuses by name while that table
is empty (``dis.entity_type_unknown``); ``--entity-type fallback`` takes
the remembered batch-1 row (marked unverified), ``unspecified`` writes
0 = Other and records the absence. Nothing is sent unless ``--udp`` is
given, and never from a campaign case (``dis.udp_in_campaign``).

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
    # D2: the full-rate log beside the manifest (core/interop/dis_stream.py).
    parser.add_argument("--stream", action="store_true",
                        help="write dis_entity_state.bin and dis_entity_state.json "
                             "(the D2 full-rate log with its index and record) into "
                             "RUN_DIR or --out-dir")
    parser.add_argument("--out-dir", default=None,
                        help="with --stream: the directory to write into (default RUN_DIR)")
    parser.add_argument("--emitter", choices=("full_rate", "thresholded"), default="full_rate",
                        help="with --stream: one PDU per sample, or the dead-reckoning "
                             "thresholded emitter (thresholds and heartbeat recorded)")
    parser.add_argument("--position-threshold-m", type=float, default=None,
                        help="with --emitter thresholded: the position threshold (default 1 m)")
    parser.add_argument("--orientation-threshold-deg", type=float, default=None,
                        help="with --emitter thresholded: the orientation threshold (default 3 deg)")
    parser.add_argument("--heartbeat-s", type=float, default=None,
                        help="with --emitter thresholded: the heartbeat (default 5 s)")
    parser.add_argument("--timestamp-mode", choices=("relative", "absolute"), default="relative",
                        help="with --stream: relative (simulation time past the hour, LSB 0) "
                             "or absolute (a stated UTC epoch plus the sample time, LSB 1)")
    parser.add_argument("--epoch", default=None,
                        help="with --timestamp-mode absolute: the UTC instant of simulation "
                             "time 0, ISO 8601 (e.g. 2026-09-29T10:00:00Z); refused by name "
                             "when absent")
    parser.add_argument("--entity-type", choices=("standard", "fallback", "unspecified"),
                        default="standard",
                        help="with --stream: the standard table (refuses while empty), the "
                             "remembered fallback row (unverified), or 0 = Other recorded as absent")
    parser.add_argument("--marking", default="",
                        help="with --stream: the 11-character ASCII marking (default: the "
                             "airframe key, derived)")
    parser.add_argument("--force-id", type=int, default=0,
                        help="with --stream: the force id (0..255; 0 Other)")
    parser.add_argument("--udp", default=None, metavar="HOST:PORT",
                        help="with --stream: also send one datagram per PDU (off by default; "
                             "never from a campaign case)")
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


def _stream(args: argparse.Namespace) -> int:
    import math

    from core.interop import dis_stream
    from core.interop.dis import DisError

    if not args.run_dir:
        print("REFUSED -- interop.dis.arguments: --stream needs RUN_DIR")
        return 2
    overrides = {"emitter": args.emitter, "timestamp_mode": args.timestamp_mode,
                 "epoch": args.epoch, "entity_type_policy": args.entity_type,
                 "marking": args.marking, "force_id": args.force_id,
                 "site": args.site, "application": args.application, "entity": args.entity,
                 "exercise_id": args.exercise}
    if args.position_threshold_m is not None:
        overrides["position_threshold_m"] = float(args.position_threshold_m)
    if args.orientation_threshold_deg is not None:
        overrides["orientation_threshold_rad"] = math.radians(args.orientation_threshold_deg)
    if args.heartbeat_s is not None:
        overrides["heartbeat_s"] = float(args.heartbeat_s)
    out_dir = Path(args.out_dir) if args.out_dir else Path(args.run_dir)
    try:
        for problem in dis_stream.dis_spec_problems(
                {k: overrides[k] for k in ("site", "application", "entity", "force_id",
                                           "marking", "timestamp_mode")}):
            raise problem
        udp = dis_stream.parse_udp_target(args.udp)
        options = dis_stream.StreamOptions(**overrides)
        if args.run_dir != str(out_dir):
            from core.interop.dis import aircraft_of_run, datum_for_run, read_telemetry

            telemetry = read_telemetry(args.run_dir)
            index = dis_stream.write_stream(
                out_dir, telemetry=telemetry, datum=datum_for_run(args.run_dir),
                aircraft=aircraft_of_run(args.run_dir, telemetry), options=options, udp=udp)
        else:
            index = dis_stream.write_stream(out_dir, options=options, udp=udp)
    except DisError as exc:
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        return 2
    e = index["entity_id"]
    print(f"wrote {index['pdu_count']} Entity State PDU(s) for {index['samples']} "
          f"telemetry sample(s) to {out_dir / dis_stream.STREAM_FILE} "
          f"({index['stream_bytes']} bytes; index {dis_stream.INDEX_FILE})")
    print(f"  entity: {e['site']}:{e['application']}:{e['entity']} marking "
          f"{index['marking']['text']!r} ({index['marking']['source']}), entity type "
          f"{index['entity_type']['source']}: {index['entity_type']['septuplet']}")
    print(f"  timestamps: {index['timestamp_mode']}"
          + (f", epoch {index['epoch']}" if index["epoch"] else "")
          + f"; emitter {index['emitter']['kind']} ({index['emitter']['emitted']} emitted, "
            f"{index['emitter']['suppressed']} suppressed)")
    print(f"  ellipsoidal height: {index['datum']['hae_source']}")
    check = index["location_check"]
    print(f"  location check: first PDU {check['error_with_n_m']:.3e} m from pyproj with N, "
          f"{check['error_without_n_m']:.3f} m without (N {check['undulation_m']:+.3f} m)")
    print(f"  udp: {'sent ' + str(index['udp']['datagrams']) + ' datagram(s) to ' + index['udp']['host'] + ':' + str(index['udp']['port']) if index['udp']['sent'] else 'off (nothing sent)'}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.decode:
        return _decode(Path(args.decode), args.limit)
    if args.stream:
        return _stream(args)
    if not args.run_dir or not args.out:
        print("REFUSED -- interop.dis.arguments: give RUN_DIR and --out to write a "
              "stream, RUN_DIR --stream to write the full-rate log, or --decode FILE "
              "to read one")
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
