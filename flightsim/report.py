"""The report surface shared by ``flightsim.capture`` and ``flightsim.verify``.

Both commands print the same kind of document, in the same order, from
the same data:

* a **header**: the run's digests (spec, simulation, output), the scene
  (flat, or the raster's path and SHA-256), the flight (aircraft,
  duration, fixed-step rate) and one line per camera (id, preset and
  position mode, aim mode, resolution, focal length in mm and pixels,
  capture count and trigger) -- :func:`header`;
* a **schedule table** per camera: every scheduled instant with its
  index, simulation time, telemetry sample, camera position and the
  aircraft's pixel through the manifest's own projection model
  (:func:`core.capture.verify.project_point`, the verifier's independent
  implementation) -- :func:`schedule_tables`; ``--brief`` collapses a
  uniform schedule to one line;
* the **verification table** (:meth:`core.capture.verify.VerificationReport.render`);
* a **verdict line** whose first word is the exit code's word.

``--json`` prints the document the text was rendered from, as data
(:func:`finish`), with the text lines beside it.

Exit codes (:data:`EXIT_WORDS`), one table for both commands::

    0  done / verified   capture produced what was asked; verify passed
    1  FAILED            the verifier failed the artefact (a check FAILED)
    2  REFUSED           a named constraint refused before/while producing
    3  USAGE             the command line, a spec or run path that does
                         not exist, or a run directory that holds nothing
                         to verify
    4  UNEXPECTED        an exception; the traceback goes to stderr

The verdict line's first word is the code's word, so the last line of
stdout and the exit status always agree.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import traceback
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

EXIT_DONE = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2
EXIT_USAGE = 3
EXIT_UNEXPECTED = 4

#: The word the verdict line starts with, per exit code. ``done`` is
#: capture's word for 0; verify's is ``verified`` (:func:`exit_word`).
EXIT_WORDS: Dict[int, str] = {
    EXIT_DONE: "done", EXIT_FAILED: "FAILED", EXIT_REFUSED: "REFUSED",
    EXIT_USAGE: "USAGE", EXIT_UNEXPECTED: "UNEXPECTED",
}
EXIT_MEANINGS: Dict[int, str] = {
    EXIT_DONE: "done (capture) / verified (verify): what was asked was "
               "produced and every check that ran passed",
    EXIT_FAILED: "the verifier FAILED the artefact: at least one check "
                 "FAILED; the table names it and where",
    EXIT_REFUSED: "REFUSED by name: a named constraint (camera.*, "
                  "ue.platform, render.*) refused before or while "
                  "producing; nothing is approximated",
    EXIT_USAGE: "USAGE: the command line is wrong, a spec or run path "
                "does not exist, or the run directory holds nothing to "
                "verify",
    EXIT_UNEXPECTED: "UNEXPECTED: an exception; the traceback is on "
                     "stderr",
}


def exit_word(code: int, success_word: str = "done") -> str:
    return success_word if code == EXIT_DONE else EXIT_WORDS[code]


class UsageError(Exception):
    """A command-line or run-directory problem: exit 3, by word."""


class ReportParser(argparse.ArgumentParser):
    """argparse with the shared exit code for usage errors (3, never the
    2 that REFUSED owns) and a shared epilog stating the table."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("formatter_class",
                          argparse.RawDescriptionHelpFormatter)
        kwargs.setdefault("epilog", exit_code_table())
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> None:  # noqa: D401 (argparse API)
        self.print_usage(sys.stderr)
        raise UsageError(f"{self.prog}: {message}")


def exit_code_table() -> str:
    lines = ["exit codes (shared by flightsim.capture and flightsim.verify):"]
    for code in sorted(EXIT_MEANINGS):
        lines.append(f"  {code}  {EXIT_MEANINGS[code]}")
    return "\n".join(lines)


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true",
                        help="print the report as JSON (the same document "
                             "the text report is rendered from, with the "
                             "text lines beside it) instead of text")
    parser.add_argument("--brief", action="store_true",
                        help="collapse each camera's schedule table to one "
                             "line when its instants are uniformly spaced")


def run_command(main: Callable[[argparse.Namespace, Dict], int],
                parser: argparse.ArgumentParser,
                argv: Optional[Sequence[str]], success_word: str) -> int:
    """Parse, run ``main(args, doc)`` and finish the document: the
    verdict word, the exit code, ``--json`` output. Usage errors exit
    3, exceptions exit 4 with the traceback on stderr -- the report
    never dies with a bare traceback on stdout."""
    doc: Dict = {"command": parser.prog, "text": []}
    try:
        args = parser.parse_args(argv)
    except UsageError as exc:
        # Named ONCE, on stdout (the verdict line, exit 3's word, where
        # every other verdict lives); stderr carries argparse's own
        # usage text alone, so a terminal never shows the line twice.
        print(f"USAGE: {exc}")
        return EXIT_USAGE
    except SystemExit as exc:          # --help, -h
        return int(exc.code or 0)
    doc["arguments"] = {k: (str(v) if isinstance(v, Path) else v)
                        for k, v in vars(args).items()}
    json_mode = bool(getattr(args, "json", False))
    buffer = io.StringIO()
    sink = contextlib.redirect_stdout(buffer) if json_mode \
        else contextlib.nullcontext()
    try:
        with sink:
            try:
                code = main(args, doc)
            except UsageError as exc:
                print(f"USAGE: {exc}")
                code = EXIT_USAGE
            except Exception as exc:          # noqa: BLE001 -- exit 4, by word
                traceback.print_exc(file=sys.stderr)
                print(f"UNEXPECTED {type(exc).__name__}: {exc} (traceback "
                      f"on stderr)")
                code = EXIT_UNEXPECTED
    finally:
        pass
    doc["exit_code"] = int(code)
    doc["verdict"] = exit_word(code, success_word)
    if json_mode:
        doc["text"] = buffer.getvalue().splitlines()
        print(json.dumps(doc, indent=1, default=str))
    return int(code)


# -- the header ----------------------------------------------------------

def _digest16(value) -> str:
    return str(value)[:16] if value else "-"


def telemetry_window(t: Sequence[float]) -> Optional[Dict[str, float]]:
    """The recorded clock's window: first and last instant, the sample
    count and the spacing (the median gap, measured from the record
    itself -- the recorder's 0.1 s interval snaps to 13 fixed steps at
    120 Hz, 0.108 s, so the nominal interval is never quoted)."""
    t = [float(v) for v in t]
    if not t:
        return None
    gaps = sorted(b - a for a, b in zip(t, t[1:]))
    spacing = gaps[len(gaps) // 2] if gaps else None
    return {"first_s": t[0], "last_s": t[-1], "samples": len(t),
            "spacing_s": spacing}


def header(manifest: Dict, out=None, aircraft: Optional[str] = None,
           duration_s: Optional[float] = None,
           samples: Optional[int] = None,
           telemetry: Optional[Dict[str, float]] = None
           ) -> Tuple[List[str], Dict]:
    """The header block as (lines, data) from a capture manifest.
    ``aircraft`` / ``duration_s`` come from the spec when the caller has
    it (capture) or from scenario.yaml beside the manifest (verify:
    :func:`flight_words_from_run`); ``telemetry`` is
    :func:`telemetry_window` of the recorded clock (the flight line
    states the window the schedule lives in beside the spec's
    duration: a 30 s spec whose record runs 4.900..34.858 s says so);
    the manifest's own aircraft_metrics name the airframe when nothing
    else does."""
    metrics = manifest.get("aircraft_metrics") or {}
    aircraft = aircraft or metrics.get("aircraft") or "-"
    scene = manifest.get("scene") or {}
    rate = float(manifest.get("rate_hz") or 0.0)
    frame = manifest.get("frame") or {}
    cameras = []
    for block in manifest.get("cameras", []):
        spec = block.get("spec") or {}

        def value(key, default=None):
            field = spec.get(key)
            return field.get("value", default) if isinstance(field, dict) \
                else default

        first = next((r for r in manifest.get("frames", [])
                      if r["camera_id"] == block["camera_id"]), None)
        cameras.append({
            "camera_id": block["camera_id"],
            "preset": block.get("preset") or value("preset", "-"),
            "position_mode": value("position_mode", "-"),
            "aim_mode": value("aim_mode", "-"),
            "width_px": int(value("width_px", first["width_px"] if first
                                  else 0)),
            "height_px": int(value("height_px", first["height_px"] if first
                                   else 0)),
            "focal_length_mm": float(value("focal_length_mm",
                                           first["focal_length_mm"] if first
                                           else 0.0)),
            "fx_px": float(first["fx_px"]) if first else None,
            "capture_count": int(block.get("capture_count", 0)),
            "trigger": block.get("trigger") or value("trigger", "-"),
            "schedule_basis": block.get("schedule_basis"),
            "horizon_stable": block.get("horizon_stable"),
        })
    data = {
        "run": str(out) if out is not None else None,
        "spec_digest": manifest.get("spec_digest"),
        "simulation_digest": manifest.get("simulation_digest"),
        "output_digest": manifest.get("output_digest"),
        "manifest_version": manifest.get("manifest_version"),
        "scene": {"key": scene.get("key"), "terrain": scene.get("terrain"),
                  "terrain_sha256": scene.get("terrain_sha256"),
                  "crs": frame.get("crs")},
        "aircraft": aircraft, "duration_s": duration_s,
        "rate_hz": rate, "step_s": manifest.get("step_s"),
        "samples": samples,
        "telemetry": telemetry,
        "span_m": metrics.get("span_m"),
        "software_revision": manifest.get("software_revision"),
        "cameras": cameras,
    }
    lines = []
    if out is not None:
        lines.append(f"run:         {out}")
    lines.append(f"spec         {_digest16(data['spec_digest'])}   "
                 f"simulation {_digest16(data['simulation_digest'])}   "
                 f"output {_digest16(data['output_digest'])}")
    if scene.get("key") == "terrain":
        lines.append(f"scene        terrain {scene.get('terrain')}   "
                     f"sha256 {_digest16(scene.get('terrain_sha256'))}   "
                     f"crs {frame.get('crs', '-')}")
    else:
        lines.append(f"scene        flat (no raster)   crs "
                     f"{frame.get('crs', '-')}")
    flight = f"flight       {aircraft}"
    if duration_s is not None:
        flight += f", {float(duration_s):g} s"
    step = 1.0 / rate if rate else 0.0
    flight += f" at {rate:g} Hz (step {step:.6f} s)"
    if telemetry:
        # The window the schedule lives in, from the record itself.
        flight += (f"; telemetry t {telemetry['first_s']:.3f}.."
                   f"{telemetry['last_s']:.3f} s ({int(telemetry['samples'])} "
                   f"samples")
        if telemetry.get("spacing_s") is not None:
            flight += f", {telemetry['spacing_s']:.3f} s apart"
        flight += ")"
        if telemetry["first_s"] > step + 1e-9:
            # The record starts where the run starts: the clock ran
            # through trim and engine start first (the c172p's starter
            # crank steps the FDM; the record's own first t says how
            # far).
            flight += (f", the clock at {telemetry['first_s']:.3f} s when "
                       f"the record began (trim and engine start)")
    elif samples is not None:
        flight += f", {int(samples)} telemetry samples"
    if metrics.get("span_m"):
        flight += f"; span {float(metrics['span_m']):.1f} m"
    lines.append(flight)
    lines.append(f"cameras      {len(cameras)}")
    width = max((len(c["camera_id"]) for c in cameras), default=6)
    for c in cameras:
        fx = f"fx {c['fx_px']:.1f} px" if c["fx_px"] is not None else "fx -"
        lines.append(
            f"  {c['camera_id']:<{width}}  {c['preset']}/{c['position_mode']}"
            f"  aim {c['aim_mode']}  {c['width_px']}x{c['height_px']}  "
            f"{c['focal_length_mm']:.1f} mm ({fx})  "
            f"{c['capture_count']} captures, {c['trigger']}")
    return lines, data


def flight_words_from_run(run_dir) -> Dict:
    """(aircraft, duration_s, samples) read from scenario.yaml and
    telemetry.json beside a manifest when they exist -- plain YAML/JSON
    reads, so a verify never refuses over a spec detail."""
    words: Dict = {"aircraft": None, "duration_s": None, "samples": None,
                   "telemetry": None}
    scenario = Path(run_dir) / "scenario.yaml"
    if scenario.is_file():
        try:
            import yaml

            spec = yaml.safe_load(scenario.read_text(encoding="utf-8")) or {}
            words["aircraft"] = ((spec.get("aircraft") or {})
                                 .get("aircraft") or {}).get("value")
            words["duration_s"] = ((spec.get("run") or {})
                                   .get("duration") or {}).get("value")
        except Exception:         # noqa: BLE001 -- informational only
            pass
    telemetry = Path(run_dir) / "telemetry.json"
    if telemetry.is_file():
        try:
            columns = json.loads(telemetry.read_text(encoding="utf-8"))
            columns = columns.get("columns", columns)
            words["samples"] = len(columns.get("t", []))
            words["telemetry"] = telemetry_window(columns.get("t", []))
        except Exception:         # noqa: BLE001
            pass
    return words


# -- the schedule tables -------------------------------------------------

SCHEDULE_HEAD = ("idx", "t_s", "sample", "cam north m", "cam east m",
                 "cam alt m", "aircraft px (u, v)")


def schedule_rows(manifest: Dict) -> Dict[str, List[Dict]]:
    """Per camera, one row per scheduled frame: the manifest's record
    and the aircraft's pixel through the verifier's own projection."""
    from core.capture.verify import project_point

    rows: Dict[str, List[Dict]] = {}
    for record in manifest.get("frames", []):
        u, v, depth = project_point(record, (
            record["aircraft"]["north_m"], record["aircraft"]["east_m"],
            record["aircraft"]["alt_m"]))
        rows.setdefault(record["camera_id"], []).append({
            "index": int(record["index"]), "t_s": float(record["t_s"]),
            "sample_index": int(record["sample_index"]),
            "north_m": float(record["position_north_m"]),
            "east_m": float(record["position_east_m"]),
            "alt_m": float(record["position_alt_m"]),
            "aircraft_u_px": (u if depth > 0 else None),
            "aircraft_v_px": (v if depth > 0 else None),
            "aircraft_depth_m": float(depth),
            "file": record.get("file"),
        })
    return rows


def _uniform_period(times: Sequence[float]) -> Optional[float]:
    if len(times) < 2:
        return None
    gaps = [b - a for a, b in zip(times, times[1:])]
    if max(gaps) - min(gaps) > 1e-6:
        return None
    return sum(gaps) / len(gaps)


def schedule_tables(manifest: Dict, brief: bool = False,
                    indent: str = "  ") -> Tuple[List[str], Dict]:
    """The per-camera schedule as (lines, data). Every instant is a row;
    with ``brief`` each camera collapses to one line -- "0..23 every
    0.521 s from 0.008 s" when the spacing is uniform; otherwise the
    cause from the camera's own trigger ("every 400 m of track;
    instants 6.600..7.433 s apart" for a distance trigger, the aim
    point and radius for proximity, the channel and threshold for an
    event) and, for a count or period schedule, the spacing's range
    with the words "sample-snapped, not uniform" -- never a period that
    was not measured."""
    rows = schedule_rows(manifest)
    blocks = {b["camera_id"]: b for b in manifest.get("cameras", [])}
    basis = {camera_id: b.get("schedule_basis")
             for camera_id, b in blocks.items()}
    lines: List[str] = []
    for camera_id, records in rows.items():
        times = [r["t_s"] for r in records]
        lines.append(f"{indent}{camera_id}: {len(records)} scheduled "
                     f"instant(s)"
                     + (f" ({basis[camera_id]})" if basis.get(camera_id)
                        else ""))
        if brief:
            period = _uniform_period(times)
            span = (f"from {times[0]:.3f} s to {times[-1]:.3f} s (samples "
                    f"{records[0]['sample_index']}.."
                    f"{records[-1]['sample_index']})")
            if period is not None:
                spacing = f"every {period:.3f} s"
            elif len(times) > 1:
                gaps = [b - a for a, b in zip(times, times[1:])]
                apart = f"instants {min(gaps):.3f}..{max(gaps):.3f} s apart"
                block = blocks.get(camera_id) or {}
                trigger = block.get("trigger")
                spec = block.get("spec") or {}

                def value(key, default=None):
                    field = spec.get(key)
                    return field.get("value", default) \
                        if isinstance(field, dict) else default

                if trigger == "distance":
                    spacing = (f"every {float(value('distance_m', 0)):g} m "
                               f"of track; {apart}")
                elif trigger == "proximity":
                    spacing = (f"within {float(value('distance_m', 0)):g} m "
                               f"of ({float(value('aim_north_m', 0)):g} N, "
                               f"{float(value('aim_east_m', 0)):g} E), "
                               f"refractory "
                               f"{float(value('refractory_s', 0)):g} s; "
                               f"{apart}")
                elif trigger == "event":
                    spacing = (f"on {value('event_channel', '?')} "
                               f"{value('event_direction', '?')} "
                               f"{float(value('event_threshold', 0)):g}, "
                               f"refractory "
                               f"{float(value('refractory_s', 0)):g} s; "
                               f"{apart}")
                else:
                    spacing = (f"spaced {min(gaps):.3f}..{max(gaps):.3f} s "
                               f"(sample-snapped, not uniform)")
            else:
                spacing = "a single instant"
            lines.append(f"{indent}  {records[0]['index']}.."
                         f"{records[-1]['index']} {spacing} {span}")
            continue
        lines.append(f"{indent}  {'idx':>4}  {'t_s':>8}  {'sample':>6}  "
                     f"{'cam north m':>12}  {'cam east m':>11}  "
                     f"{'cam alt m':>10}  aircraft px (u, v)")
        for r in records:
            if r["aircraft_u_px"] is None:
                pixel = f"behind ({r['aircraft_depth_m']:.1f} m)"
            else:
                pixel = f"({r['aircraft_u_px']:.1f}, {r['aircraft_v_px']:.1f})"
            lines.append(f"{indent}  {r['index']:>4}  {r['t_s']:>8.3f}  "
                         f"{r['sample_index']:>6}  {r['north_m']:>12.3f}  "
                         f"{r['east_m']:>11.3f}  {r['alt_m']:>10.3f}  {pixel}")
    return lines, {"columns": list(SCHEDULE_HEAD), "cameras": rows}


def verification_block(report, indent: str = "  ") -> List[str]:
    """The verifier's table, its detail lines and its summary, as lines
    (VerificationReport.render, split)."""
    return report.render().splitlines()
