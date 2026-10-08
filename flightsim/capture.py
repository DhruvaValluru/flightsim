"""Capture a scenario: spec -> validate -> run -> solved geometry.

    .venv/bin/python -m flightsim.capture examples/cameras_multi.yaml \
        --out runs/demo [--terrain runs/terrain/matterhorn] [--max-previews N]

What happens, in order (each step refuses by name rather than
approximating):

1. the spec is read (spec_version 9; 8 reads when it states no
   version-9 block -- older versions, and a version-9 block under 8,
   refuse by name);
2. scene-free validation runs (the full validate(), cameras included);
3. world-anchored cameras are checked against the scene BEFORE the run
   (terrain clearance, scene bounds, the tornado core);
4. the scenario runs HEADLESSLY (core.scenario.runner.run_spec, the
   real flight dynamics -- with --terrain, over the real raster);
5. every camera's pose track is solved and its capture schedule
   computed from the recorded telemetry (a spec with no cameras gets
   the documented default camera);
6. the solved tracks are re-checked against the scene along the whole
   run -- steps 4-6 are the cheap pre-flight gate, so a camera inside
   a mountain refuses before any engine time is spent;
7. with --render, THE HOST FLIES THE CARD FIRST (the telemetry-only
   commandlet, no renderer) and steps 5-6 run again over the host's
   own telemetry. The labels then describe the flight the pixels will
   show rather than a second, very similar one -- see
   core.capture.hostflight. --no-host-flight keeps the old behaviour
   deliberately;
8. capture_manifest.json (carrying solve_source, which says WHICH of
   those flights the aircraft labels came from), telemetry.json,
   scenario.yaml and one geometry preview per scheduled frame;
9. on a machine with the UE render half, pixels render beside them,
   one commandlet pass per camera; anywhere else rendering REFUSES BY
   NAME (ue.platform) while steps 1-8 stand -- the manifest and
   previews are the engine-less deliverable.

Exit codes: 0 = captured (even when rendering was refused by name);
2 = a named validation/schedule refusal; 1 = unexpected failure.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.capture.objects import compose_objects  # noqa: E402
from core.util.platform import UE_ENGINE_VERSION  # noqa: E402

#: The lines the JSBSim library prints from C++ on every FGFDMExec
#: construction (three banner lines and, once, a "startup beginning"
#: line, each wrapped in blank lines). Measured: 12 banners on the
#: two-camera example before the spec line, burying "spec ... valid"
#: and the refusal a non-technical reader is looking for.
#: FGJSBBase.debug_lvl = 0 does not gate them (core/fdm/fdm.py), so
#: they are filtered at the file-descriptor level by
#: quiet_library_banners below; --verbose keeps them.
LIBRARY_BANNER_PREFIXES = (
    b"JSBSim Flight Dynamics Model",
    b"[JSBSim-ML",
    b"JSBSim startup beginning",
)


def _is_library_banner(line: bytes) -> bool:
    return line.strip().startswith(LIBRARY_BANNER_PREFIXES)


class _BannerFilter:
    """A line filter over a byte stream: every line reaches ``out_fd``
    except the library banner lines and the blank lines that frame
    them. Blank lines are held until the next line says whether they
    framed a banner, so a program's own blank line still arrives.
    ``feed`` takes the stream in any chunking; ``close`` releases what
    a stream without a final newline still holds."""

    def __init__(self, out_fd: int) -> None:
        self.out_fd = out_fd
        self.pending_blank = 0
        self.after_banner = False
        self.tail = b""

    def emit(self, line: bytes) -> None:
        if _is_library_banner(line):
            self.pending_blank = 0
            self.after_banner = True
            return
        if not line.strip():
            if not self.after_banner:
                self.pending_blank += 1
            return
        os.write(self.out_fd, b"\n" * self.pending_blank + line)
        self.pending_blank = 0
        self.after_banner = False

    def feed(self, chunk: bytes) -> None:
        self.tail += chunk
        while b"\n" in self.tail:
            line, self.tail = self.tail.split(b"\n", 1)
            self.emit(line + b"\n")

    def close(self) -> None:
        if self.tail:
            self.emit(self.tail)
            self.tail = b""
        if self.pending_blank and not self.after_banner:
            os.write(self.out_fd, b"\n" * self.pending_blank)
        self.pending_blank = 0


def _relay_without_banners(read_end: int, out_fd: int) -> None:
    """Copy a pipe to ``out_fd`` through the filter until every writer
    has closed it. The tests push bytes through this form; the command
    itself spools to a FILE (``quiet_library_banners`` says why a pipe
    is the wrong channel for a writer that holds the GIL)."""
    stream = _BannerFilter(out_fd)
    try:
        while True:
            chunk = os.read(read_end, 65536)
            if not chunk:
                break
            stream.feed(chunk)
        stream.close()
    finally:
        os.close(read_end)


def _tail_without_banners(path: str, out_fd: int, stop: threading.Event,
                          poll_seconds: float = 0.05,
                          opened: Optional[threading.Event] = None) -> None:
    """Follow the spool file at ``path`` from its start, relaying every
    new byte through the filter, until ``stop`` is set and the file has
    been read to its end. ``stop`` is set only after the last write, so
    an empty read that FOLLOWS the flag means nothing is left.
    ``opened`` is set once the reader holds the file (or failed to), so
    the caller can drop the file's name where the OS allows it."""
    stream = _BannerFilter(out_fd)
    try:
        source = open(path, "rb", buffering=0)
    finally:
        if opened is not None:
            opened.set()          # on failure too: the caller's wait must return
    with source:
        while True:
            stopping = stop.is_set()
            chunk = source.read(65536)
            if chunk:
                stream.feed(chunk)
                continue
            if stopping:
                break
            stop.wait(poll_seconds)
    stream.close()


def _flush_c_stdout() -> None:
    """Flush the C runtime's stdout, where a library's last unflushed
    bytes can sit, so they reach the spool before fd 1 is restored.
    Best effort: a runtime that cannot be reached changes nothing."""
    try:
        import ctypes

        runtime = ctypes.CDLL("ucrtbase" if sys.platform.startswith("win") else None)
        runtime.fflush(None)
    except (ImportError, OSError, AttributeError):
        pass


@contextlib.contextmanager
def quiet_library_banners(enabled: bool = True):
    """Run a block with the JSBSim startup banners kept off stdout.

    The banners are written by C++ straight to file descriptor 1, so
    no Python-level redirection sees them: for the block, fd 1 is
    pointed at a SPOOL FILE, a thread follows the file and relays every
    line but the banner lines (LIBRARY_BANNER_PREFIXES) to the real
    stdout, and fd 1 is restored before the block's caller prints
    again. Everything else -- the spec line, the refusals, a
    subprocess's own words -- arrives in order, up to ``poll_seconds``
    (50 ms) after it was written; stderr is not held, so it can run
    ahead of stdout by that much. With ``enabled`` false (--verbose)
    the block runs untouched; so does a process with no usable stdout,
    no usable temp directory or no thread to spare (then the banner
    shows, and nothing is lost).

    A file, never a pipe. The first version of this used os.pipe(). A
    pipe has a fixed buffer that a writer fills and then BLOCKS on
    until the reader drains it, and the library writes while holding
    the GIL (its C++ never releases it), so the relay thread could not
    run to drain it and the process hung with the writer waiting for
    the reader and the reader waiting for the GIL. Linux pipes hold
    64 KB and a run's output is smaller, so it passed here; Windows
    anonymous pipes hold 4 KB and the aircraft description JSBSim
    prints while loading a model is 16 KB in one call, so on Windows
    CI every capture under the campaign deadlocked until the watchdog
    killed it (run 36217163564: the token test failed after one 120 s
    stall, the end-to-end test hung past pytest's 15 min). A write to
    a file never waits for a reader; the deadlock test in
    tests/test_capture_cli_words.py writes more than any pipe holds
    while holding the GIL and must return.
    """
    if not enabled:
        yield
        return
    try:
        sys.stdout.flush()
        saved = os.dup(1)
    except (OSError, ValueError, AttributeError):
        yield
        return
    try:
        spool_fd, spool_path = tempfile.mkstemp(prefix="flightsim-stdout-", suffix=".spool")
    except OSError:
        os.close(saved)            # no usable temp directory: the banner shows
        yield
        return
    os.dup2(spool_fd, 1)
    os.close(spool_fd)
    stop = threading.Event()
    opened = threading.Event()
    relay = threading.Thread(target=_tail_without_banners,
                             args=(spool_path, saved, stop, 0.05, opened), daemon=True)
    try:
        relay.start()
    except RuntimeError:           # no thread to follow the spool: fd 1 back, banner shows
        os.dup2(saved, 1)
        os.close(saved)
        with contextlib.suppress(OSError):
            os.unlink(spool_path)
        yield
        return
    if os.name != "nt":
        # Both handles are open, so the name can go now and a process
        # killed inside the block (the campaign's watchdog) leaves no
        # file behind. Windows refuses to unlink an open file without
        # FILE_SHARE_DELETE, so there the name goes at the end.
        opened.wait()
        with contextlib.suppress(OSError):
            os.unlink(spool_path)
    # A Windows console: sys.stdout writes with WriteConsoleW on fd 1's
    # CURRENT handle (winconsoleio.c re-reads it per write), which is
    # now the spool file, and WriteConsole fails on a file. For the
    # block, print through a plain file object on fd 1 instead; the
    # relay's os.write on the saved console handle takes bytes.
    raw = getattr(getattr(sys.stdout, "buffer", None), "raw", None)
    console = sys.stdout if type(raw).__name__ == "_WindowsConsoleIO" else None
    if console is not None:
        sys.stdout = open(1, "w", buffering=1, closefd=False,
                          encoding="utf-8", errors="backslashreplace")
    try:
        yield
    finally:
        try:
            sys.stdout.flush()
        finally:
            if console is not None:
                sys.stdout = console
            _flush_c_stdout()
            os.dup2(saved, 1)      # this process's last writer to the spool is gone
            stop.set()             # after the writes: the relay reads to the end, then stops
            relay.join()
            os.close(saved)
            with contextlib.suppress(OSError):
                os.unlink(spool_path)


def _tornado_hazard_block(spec):
    """The straight-line severe-event placement, in the scene frame:
    45% of the still-air run ahead along the heading, the recorded
    aim's abeam offset applied -- the same figures the headless
    runner's environment uses. (The webapp's terrain runs refine this
    onto the pre-flown banked track; the headless CLI flies straight
    and the straight-line point IS its track.)"""
    if str(spec.weather_event.value) != "tornado":
        return None
    from core.environment.tornado import FADE_TOP_M, R_CORE_M
    from core.fdm import units as u

    seconds = float(spec.duration.value)
    ahead = 0.45 * u.kt_to_mps(float(spec.airspeed.value)) * seconds
    heading = math.radians(float(spec.heading.value))
    aim = str(spec.weather_event.detail.get("aim", "abeam"))
    offset = 0.0 if aim == "core" else 2.5 * R_CORE_M
    return {
        "centre_north_m": (ahead * math.cos(heading)
                           + offset * math.cos(heading + math.pi / 2)),
        "centre_east_m": (ahead * math.sin(heading)
                          + offset * math.sin(heading + math.pi / 2)),
        "r_core_m": R_CORE_M, "fade_top_m": FADE_TOP_M,
    }


def _mesh_manifest_path(spec) -> Path:
    """Where the imported model's manifest lives for this spec's aircraft
    (the web app resolves the same path for its -mesh= argument)."""
    return (REPO / "assets" / "generated" / str(spec.aircraft.value)
            / "mesh_manifest.json")


def _traffic_mesh_refusal(spec):
    """The ``aircraft.mesh`` refusal for the first traffic airframe whose
    model is not imported on this machine, or None. The web app's own
    words where its refusal applies (no config, no upstream licence);
    the build command where the model can be built."""
    from assets_pipeline.importer import (
        configured_aircraft, is_imported, unavailable_reason,
    )

    for index, entry in enumerate(spec.traffic):
        aircraft = str(entry.aircraft.value)
        if is_imported(aircraft):
            continue
        reason = unavailable_reason(aircraft)
        if reason:
            message = (f"traffic[{index}] names the {aircraft}, which has "
                       f"flight physics but can never render: {reason}")
        elif aircraft not in configured_aircraft():
            message = (f"traffic[{index}] names the {aircraft}, for which no "
                       f"licensed 3-D model is configured; placeholder "
                       f"airframes never render, for traffic as for the "
                       f"primary")
        else:
            message = (f"traffic[{index}] names the {aircraft}, whose model "
                       f"is not imported on this machine (no current "
                       f"assets/generated/{aircraft}/mesh_manifest.json backed "
                       f"by its ue/Content assets). Build it once with "
                       f"`python scripts/import_aircraft.py {aircraft}`; a "
                       f"scripted traffic actor is drawn from the same "
                       f"imported mesh as a primary would be")
        return {"constraint": "aircraft.mesh", "message": message}
    return None


def _after_name(exc: Exception) -> str:
    """The text of an error whose str() begins with its own rule name
    (``ScheduleError``: "camera.schedule: ..."), without that head, so
    a REFUSED line prints the name once."""
    text = str(exc)
    head = f"{getattr(exc, 'constraint', '')}: "
    return text[len(head):] if head != ": " and text.startswith(head) else text


def _scene_members(scene_path, terrain_stem):
    """W5: the world-block members of the scene document
    scripts/ue_build_scene.py wrote (its ``world_card_members``), or
    ``{"violations": [...]}``: world.scene_missing when the document is
    not here or there is no bake to draw it on."""
    import importlib.util

    from core.scenario.validate import Violation

    path = Path(scene_path)
    if terrain_stem is None or not path.is_file():
        return {"violations": [Violation(
            "world.scene_missing",
            (f"--scene {path} is not on this machine" if not path.is_file() else
             "--scene loads a Landscape over a terrain bake; this capture has none "
             "(pass --terrain)"))]}
    builder = Path(__file__).resolve().parents[1] / "scripts" / "ue_build_scene.py"
    module_spec = importlib.util.spec_from_file_location("ue_build_scene", builder)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    try:
        members = module.world_card_members(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"violations": [Violation(
            "world.scene_missing", f"--scene {path} is not a scene document ({exc})")]}
    return members


def _with_scene(block, scene_members):
    """The card's world block with the scene's members merged in (W5);
    the block unchanged when no scene was named."""
    if block is None or not scene_members:
        return block
    return {**block, **scene_members}


def _world_documents(spec, terrain_stem, landcover_json=None):
    """W2's world, built for a capture (wired by W4): the runway's
    flatten pad and its record (core/scene/runway.py; the flight then
    flies over the PAD, the heights the host draws), and the buildings
    document over the flown bake (core/scene/buildings.py; the vintage
    fraction against the land cover's built-up class when the bake has
    land cover). Returns ``{"terrain", "buildings_document",
    "runway_document"}`` or ``{"violations": [...]}`` -- each refusal by
    its own name, before any flight. A spec stating neither returns the
    terrain unchanged and two Nones (absent-canonical)."""
    from core.scenario.validate import Violation
    from core.scene import runway as rw

    out = {"terrain": terrain_stem, "buildings_document": None, "runway_document": None}
    try:
        runway = rw.RunwaySpec.from_block(getattr(spec, "runway", None))
    except rw.RunwayError as exc:
        return {"violations": [Violation(exc.constraint, exc.message)]}
    key = getattr(getattr(spec, "scene", None), "buildings", None)
    key = None if key is None else key.value
    if runway is None and key is None:
        return out
    if not terrain_stem:
        return {"violations": [Violation(
            "runway.terrain_mismatch" if runway is not None else "scene.terrain",
            ("the runway does not lie on any terrain: a flat scene has no bake to "
             "flatten it into; state scene.terrain_source synthesised or baked"
             if runway is not None else
             "scene.buildings needs a terrain bake to seat its blocks on; a flat scene "
             "has none (state scene.terrain_source synthesised or baked)"))]}
    if runway is not None:
        from core.terrain.glo30 import ensure_runway_pad
        from core.terrain.heightfield import Heightfield

        try:
            pad_stem = ensure_runway_pad(terrain_stem, runway)
        except rw.RunwayError as exc:
            return {"violations": [Violation(exc.constraint, exc.message)]}
        pad = Heightfield.read(pad_stem)
        parent = Heightfield.read(Path(terrain_stem))
        meta = json.loads(Path(pad_stem).with_suffix(".json").read_text(encoding="utf-8"))
        statistics = ((meta.get("provenance") or {}).get("runway_pad") or {}).get("statistics")
        raster, rects, counts = rw.markings_raster(runway)
        measurement = rw.measure_markings(raster, rects)
        png = rw.write_markings_png(raster, rw.markings_path_for(pad_stem))
        lights, light_counts = rw.light_positions(runway)
        document = rw.runway_document(
            runway, rw.RunwayGeometry.for_spec(runway, pad.georeference.crs),
            rw.markings_block(runway, png, counts, measurement),
            {"counts": light_counts, "positions": lights},
            {"key": pad.name, "stem": str(pad_stem), "sha256": pad.digest(),
             "parent_stem": str(terrain_stem), "parent_sha256": parent.digest(),
             "statistics": statistics or {}},
            None, null_test_basis=("not measured by the capture: scripts/bake_runway.py "
                                   "--null-test flies the pad against its parent"))
        out["runway_document"] = str(rw.write_runway_document(
            document, rw.document_path_for(pad_stem)))
        out["terrain"] = str(pad_stem)
    if key is not None:
        from core.scene.buildings import BuildingsError, ensure_buildings_document

        codes = None
        if landcover_json is not None:
            import numpy as np
            from PIL import Image

            document = json.loads(Path(landcover_json).read_text(encoding="utf-8"))
            class_map = Path(landcover_json).parent / str(
                (document.get("class_map") or {}).get("file", "class_map.png"))
            if class_map.is_file():
                with Image.open(class_map) as image:
                    codes = np.asarray(image)
        try:
            out["buildings_document"] = str(ensure_buildings_document(
                str(key), out["terrain"], built_codes=codes))
        except BuildingsError as exc:
            return {"violations": [Violation(exc.constraint, exc.message)]}
    return out


def _refuse(violations) -> int:
    print("REFUSED -- by name:")
    for v in violations:
        print(f"  {v.render() if hasattr(v, 'render') else v}")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="validate, run headlessly, and capture a scenario's "
                    "camera geometry")
    parser.add_argument("spec", help="scenario spec YAML (spec_version 9, or 8 without "
                                     "a version-9 block)")
    parser.add_argument("--out", required=True, help="run directory")
    parser.add_argument("--terrain", default=None,
                        help="baked heightfield stem (<stem>.r16 + .json) "
                             "for real-raster physics and camera checks")
    parser.add_argument("--synth-terrain", action="store_true",
                        help="synthesise a raster CENTRED on the spec's "
                             "own origin and fly over that -- real "
                             "terrain physics and real raster camera "
                             "checks with no network and no account, "
                             "deterministic from its seed. Ignored when "
                             "--terrain names a bake. Since spec 8 this "
                             "flag is an ALIAS for the spec's own "
                             "scene.terrain_source: synthesised, which "
                             "needs no flag.")
    parser.add_argument("--max-previews", type=int, default=8,
                        help="cap geometry preview images per run "
                             "(default 8; they are near-identical frame "
                             "to frame and each draws a full shaded "
                             "scene). 0 writes none.")
    parser.add_argument("--render", action="store_true",
                        help="also render the frames through the solved "
                             f"poses (Windows with UE {UE_ENGINE_VERSION} "
                             "and the bridge built; refuses by name "
                             "anywhere else). Implies --card.")
    parser.add_argument("--void", action="store_true",
                        help="render in the black-void scene instead of "
                             "the visual one: no sky, no horizon, no "
                             "terrain, just the lit airframe. What the "
                             "silhouette measurements want, and nothing "
                             "else")
    parser.add_argument("--passes", default=None, metavar="WORDS",
                        help="with --render, also write the ground-truth "
                             "passes beside the label bundle: a comma list "
                             "of normal, velocity, albedo (I6; each optional; "
                             "frame_NNNN_normal.png / _flow.f32 / "
                             "_albedo.png). None by default.")
    # S1: the sensing opt-ins (core/render/flags.py sensing_flags; S4
    # honours them in the commandlet, uncompiled here).
    parser.add_argument("--scene", default=None,
                        help="with --render and --terrain, the scene document "
                             "scripts/ue_build_scene.py wrote for the bake "
                             "(<stem>_scene.json): the render loads that Landscape "
                             "scene level (-scene=) and the card's world block carries "
                             "its level, terrain sha256, sidecar and layer digests, "
                             "matched by the host at load (world.scene_stale). Off by "
                             "default: the procedural terrain.")
    parser.add_argument("--calibration", action="store_true",
                        help="with --render, also render the calibration frame per camera: an "
                             "emissive grey card, a Lambertian white quad under the sun alone "
                             "and a 5 degree slanted-edge quad (calibration.json beside the "
                             "bundle; the grey-card ratio makes the radiometry 'measured' and "
                             "the edge quad runs the verifier's psf_slanted_edge). Off by "
                             "default.")
    parser.add_argument("--sun-lux", default=None, metavar="LUX|auto",
                        help="with --render, set the sun in physical units: a number of lux, "
                             "or 'auto' for the spec's scene.sun_lux, else the clear-sky model "
                             "at the look's sun elevation (core/scenario/solar.py, provenance "
                             "model). Refused by name (sensing.sun_lux) outside (0, 133100]. "
                             "Off by default: the engine's own sun (8.0, unitless) stands and "
                             "the radiometry chain records sensing.exposure_units.")
    parser.add_argument("--accumulate", type=int, default=None, metavar="K",
                        help="with --render, ask the engine for K sub-exposure captures per "
                             "frame on a dedicated AA-off capture (motion blur by "
                             "accumulation; the Python velocity-line blur is then recorded, "
                             "not applied). Off by default.")
    parser.add_argument("--no-host-flight", action="store_true",
                        help="with --render, skip the host's own solve "
                             "flight and solve the poses over the "
                             "headless pre-run instead. Faster by one "
                             "commandlet pass, and the aircraft labels "
                             "then describe a DIFFERENT flight from the "
                             "one the pixels show (1.38 m measured). "
                             "Only for when you want the old behaviour "
                             "deliberately.")
    parser.add_argument("--card", action="store_true",
                        help="also write card.json carrying each camera's "
                             "solved pose track, for the UE commandlet's "
                             "consume-poses mode on a render-capable "
                             "machine (-camera-index=N, one pass per "
                             "camera)")
    parser.add_argument("--instruments", default=None, metavar="PROFILE",
                        help="instrument error profile (assets/instrument_"
                             "profiles/<PROFILE>.json: ideal, tactical, "
                             "consumer_mems) applied to the recorded "
                             "telemetry AFTER the run as an observer: an "
                             "IMU, a GPS receiver, a pitot-static system "
                             "and a magnetometer, each writing a "
                             "<truth>_meas channel beside the truth into "
                             "telemetry_measured.json. The default, ideal, "
                             "writes nothing and says so; an unknown "
                             "profile refuses by name before any flight.")
    parser.add_argument("--null-tests", action="store_true",
                        help="R1: after the flight, fly the identical case once per "
                             "registered variable the spec states (core/registry.py) "
                             "with that variable at its null value, and write the "
                             "measured effect per channel, both digests and the "
                             "verdict into run.json and the capture manifest "
                             "(null_tests; the record's null_test when the variable "
                             "has a record). Off by default: no extra flight.")
    parser.add_argument("--uncertainty", action="store_true",
                        help="R1: after the flight, fly the dt/2 twin (rate doubled, "
                             "turbulence off) and write the ASME V&V 20 block -- u_num "
                             "per SRQ, u_input per registered variable, u_val, u_D "
                             "absent -- into run.json and the capture manifest "
                             "(uncertainty). Off by default: no extra flight.")
    # D2: the interoperability exports (core/interop/dis_stream.py).
    parser.add_argument("--dis", action="store_true",
                        help="after the flight, write the full-rate IEEE 1278.1-2012 "
                             "Entity State PDU log dis_entity_state.bin and its index "
                             "dis_entity_state.json into the run directory, attach the "
                             "dis.entity_state record and the per-frame PDU keys to the "
                             "capture manifest. The spec's dis block labels it; the entity "
                             "type comes from the standard table and is refused by name "
                             "while that table is empty (--dis-entity-type chooses "
                             "otherwise). Off by default.")
    parser.add_argument("--dis-udp", default=None, metavar="HOST:PORT",
                        help="with --dis: also send one datagram per PDU to HOST:PORT "
                             "after the file is written. Off by default; refused by name "
                             "in a campaign case (dis.udp_in_campaign).")
    parser.add_argument("--dis-entity-type", choices=("standard", "fallback", "unspecified"),
                        default="standard",
                        help="with --dis: the entity type's source -- the standard table "
                             "(assets/dis_entity_types.yaml; refused while its row is "
                             "empty), the remembered fallback row (marked unverified), or "
                             "0 = Other with the septuplet recorded as absent")
    parser.add_argument("--dis-epoch", default=None, metavar="ISO",
                        help="with --dis and a spec dis.timestamp_mode of absolute: the "
                             "UTC instant of simulation time 0 (e.g. 2026-09-29T10:00:00Z); "
                             "refused by name when absolute is asked without it")
    parser.add_argument("--dis-emitter", choices=("full_rate", "thresholded"),
                        default="full_rate",
                        help="with --dis: one PDU per telemetry sample, or the dead-"
                             "reckoning thresholded emitter (1 m, 3 deg, 5 s heartbeat, "
                             "recorded with its measured reconstruction)")
    parser.add_argument("--cigi", action="store_true",
                        help="refused by name (interop.cigi_not_implemented): no CIGI "
                             "session exists; the run card is the documented offline "
                             "image-generator interface")
    parser.add_argument("--hla", action="store_true",
                        help="refused by name (interop.hla_not_implemented): no HLA "
                             "federation or RPR FOM exists; the DIS log is the "
                             "interoperability product")
    parser.add_argument("--verbose", action="store_true",
                        help="keep the flight model's own startup lines "
                             "(the JSBSim banner it prints once per "
                             "flight model it builds) on the output. "
                             "Off by default so what this command says "
                             "-- the spec line, the results, a refusal "
                             "-- is not buried under them.")
    return parser


def _run_unattended(command, log):
    """An engine pass with no window, no OS error box and no stdin, under
    the stall watchdog (core/render/headless.py), its output kept in
    ``log`` and its last lines echoed. A stall or timeout kills the whole
    process tree and is reported by name; the return carries a
    ``returncode`` like subprocess.run's (124 when stopped)."""
    from types import SimpleNamespace

    from core.render.headless import HEADLESS_FLAGS, run_headless

    print(f"  engine pass logging to {log} (unattended; stalls are stopped)")
    result = run_headless(list(command) + list(HEADLESS_FLAGS), Path(log))
    try:
        tail = Path(log).read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
        print("\n".join("    " + line for line in tail))
    except OSError:
        pass
    if result.refusal:
        print(f"REFUSED -- {result.sentence()}")
        return SimpleNamespace(returncode=124)
    return SimpleNamespace(returncode=result.returncode if result.returncode is not None else 1)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    # D2: the two interfaces this build does not speak are refused by name
    # before any flight, never approximated.
    if args.cigi:
        print("REFUSED -- interop.cigi_not_implemented: no CIGI session is implemented; "
              "the run card (card.json) is the documented offline image-generator "
              "interface (docs/ADVANCEMENTS_CONTRACTS.md, D2)")
        return 2
    if args.hla:
        print("REFUSED -- interop.hla_not_implemented: no HLA federation and no RPR FOM "
              "is implemented; the Entity State PDU log (--dis) is the interoperability "
              "product")
        return 2
    if args.dis_udp and not args.dis:
        args.dis = True
    with quiet_library_banners(enabled=not args.verbose):
        return _run(args)


def _run(args: argparse.Namespace) -> int:
    from core.capture.manifest import (
        build_capture_manifest, write_capture_manifest,
        write_frame_sidecars,
    )
    from core.capture.poses import SceneFrame, solve_pose_track
    from core.capture.preview import render_previews
    from core.capture.schedule import ScheduleError, solve_schedule
    from core.capture.validate import (
        static_camera_violations, track_violations,
    )
    from core.scenario.camera import default_cameras
    from core.scenario.runner import run_spec
    from core.scenario.spec import ScenarioSpec
    from core.scenario.validate import Violation, validate

    try:
        spec = ScenarioSpec.read(args.spec)
    except ValueError as exc:
        # A file that is not a spec (unreadable YAML, a missing field,
        # a version this build does not read): named, so the catalogue
        # can put it into words like every other refusal.
        print(f"REFUSED -- spec.read: {exc}")
        return 2

    # The instrument profile is a pre-flight gate like the cameras: a
    # name this build has no file for refuses before any engine or
    # flight time is spent.
    from core.telemetry.instruments import (
        InstrumentProfileError, describe as describe_instruments,
        load_profile as load_instrument_profile, measure as measure_instruments,
        write_measured,
    )

    try:
        instrument_profile = load_instrument_profile(args.instruments or "ideal")
    except InstrumentProfileError as exc:
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        return 2

    # D2: the Entity State PDU log's own pre-flight gate -- the entity type
    # (the standard table refuses while empty), an absolute mode's epoch,
    # the marking, the block's ids, the UDP target and the campaign rule --
    # so a refusal is printed before any flight, and the write after the
    # flight cannot refuse on anything the user chose.
    dis_options = None
    dis_udp = None
    if args.dis:
        from core.interop.dis import DisError
        from core.interop.dis_stream import (
            in_campaign_worker, options_from_spec, parse_udp_target, preflight,
        )

        try:
            dis_udp = parse_udp_target(args.dis_udp)
            if dis_udp is not None and in_campaign_worker(Path(args.out)):
                raise DisError("dis.udp_in_campaign",
                               f"{args.out} is a campaign case's run directory; a campaign "
                               f"writes the stream file and sends nothing")
            dis_options = options_from_spec(
                spec, epoch=args.dis_epoch, emitter=args.dis_emitter,
                entity_type_policy=args.dis_entity_type)
            preflight(str(spec.aircraft.value), dis_options)
        except DisError as exc:
            print(f"REFUSED -- {exc.constraint}: {exc.message}")
            return 2

    if args.render:
        # The render hosts have no autopilot, take only calibrated
        # airspeed, and hold mass for the clip. The webapp has projected
        # every spec through this before handing it to the commandlet
        # since Gate 8.3; --render did not, so a spec with the DEFAULT
        # hold_state (true) flew headlessly, solved every pose, launched
        # the engine, and only then hit the commandlet's named refusal.
        # Project first, say what moved, and solve the poses over the
        # flight the host will actually fly.
        from core.util.platform import ue_available
        from webapp.runs import project_for_ue_host

        # spec.quantities() yields (section, name, quantity).
        before = {name: q.value for _, name, q in spec.quantities()}
        project_for_ue_host(spec)
        moved = [f"{name}: {before[name]!r} -> {q.value!r}"
                 for _, name, q in spec.quantities()
                 if before.get(name) != q.value]
        if moved:
            print("projected for the render host (no autopilot; "
                  "calibrated airspeed only):")
            for line in moved:
                print(f"  {line}")

        # The MESH the frames will draw, checked here for the same reason
        # the projection is: before any flight. The web app has passed
        # -mesh= since the placeholder rule; this command never did, so a
        # CLI --render drew the placeholder boxes -- forbidden on any
        # machine (owner's rule 2026-08-31) -- under a manifest whose
        # assets block named the real mesh. Imported (a CURRENT manifest
        # AND its .uassets) -> the render pass gets -mesh=; otherwise
        # REFUSE by name, with the web app's own words where its refusal
        # applies (no config, no upstream license) and the build command
        # where the model can be built. Only where the engine is: off
        # Windows/Mac the render is refused later as ue.platform and the
        # manifest is the deliverable, exactly as before.
        if ue_available():
            from assets_pipeline.importer import is_imported
            from webapp.runs import refuse_placeholder_mesh

            aircraft = str(spec.aircraft.value)
            mesh_manifest = _mesh_manifest_path(spec)
            if not is_imported(aircraft):
                refusal = refuse_placeholder_mesh(spec)
                if refusal is None:
                    refusal = {
                        "constraint": "aircraft.mesh",
                        "message": (
                            f"the {aircraft} model is not imported on this "
                            f"machine (no current "
                            f"{mesh_manifest.relative_to(REPO)} backed by "
                            f"its ue/Content assets), and placeholder "
                            f"airframes never render. Build it once with "
                            f"`python scripts/import_aircraft.py "
                            f"{aircraft}` (fetch at the pinned commit, "
                            f"convert, import into the Unreal project), or "
                            f"render through the web app, which provisions "
                            f"it itself; a manifest older than version 2 "
                            f"(no mesh origin -- the mesh would be drawn at "
                            f"the structural datum, 25-30 m off its label) "
                            f"re-converts with `python "
                            f"assets_pipeline/convert.py "
                            f"assets/aircraft_config/{aircraft}.json`"),
                    }
                print(f"REFUSED -- {refusal['constraint']}: "
                      f"{refusal['message']}")
                print("(--render asked for pixels of a model this machine "
                      "does not have; refused before any flight, so "
                      "nothing was run or rendered)")
                return 2
            # Phase 2 (package B, contracts §2.2): every TRAFFIC airframe
            # is held to the same rule as the primary -- its mesh must be
            # imported on this machine or the render refuses aircraft.mesh
            # by name before any flight. A scripted actor drawn as boxes
            # under a label that names a type is the same lie.
            traffic_refusal = _traffic_mesh_refusal(spec)
            if traffic_refusal is not None:
                print(f"REFUSED -- {traffic_refusal['constraint']}: "
                      f"{traffic_refusal['message']}")
                print("(--render asked for pixels of a traffic model this "
                      "machine does not have; refused before any flight)")
                return 2

    heightfield = None
    terrain_ground = None
    landcover_json = None
    terrain_stem = args.terrain
    # Spec 8: the spec's own scene.terrain_source names the terrain, so
    # a committed example refuses (or flies) AS ITS HEADER SAYS with no
    # flag. "auto" is exactly the flag behaviour this block always had;
    # the flags stay as aliases. A flag that CONTRADICTS a stated source
    # refuses by name (scene.terrain) rather than dropping either in
    # silence. Whether the value is one of the four is validate()'s
    # question (scene.terrain_source); here an unknown value falls
    # through to validation below, which refuses it.
    terrain_source = str(spec.scene.terrain_source.value)
    if terrain_source == "flat":
        if terrain_stem is not None or args.synth_terrain:
            return _refuse([Violation(
                "scene.terrain",
                "the spec states scene.terrain_source: flat, but "
                + ("--terrain names a bake" if terrain_stem is not None
                   else "--synth-terrain asks for a raster")
                + "; edit the spec or drop the flag -- neither is "
                  "dropped in silence")])
        print("terrain: flat at the spec's datum (scene.terrain_source: "
              "flat)")
    elif terrain_source == "baked":
        stated = spec.scene.terrain.value
        if terrain_stem is None and stated:
            terrain_stem = str(stated)
        if terrain_stem is None:
            return _refuse([Violation(
                "scene.terrain",
                "scene.terrain_source is baked but no bake is named: "
                "state scene.terrain (a <stem>.r16 + .json bake) or pass "
                "--terrain <stem>")])
        stem = Path(terrain_stem)
        if not (stem.with_suffix(".r16").is_file()
                and stem.with_suffix(".json").is_file()):
            return _refuse([Violation(
                "scene.terrain",
                f"scene.terrain_source is baked but {terrain_stem} is not "
                f"a whole bake on this machine (<stem>.r16 + .json; "
                f"scripts/bake_terrain.py fetches a curated one)")])
    elif terrain_source == "synthesised" and terrain_stem is not None:
        return _refuse([Violation(
            "scene.terrain",
            "the spec states scene.terrain_source: synthesised, but "
            "--terrain names a bake; edit the spec or drop the flag")])
    if terrain_stem is None and (args.synth_terrain
                                 or terrain_source == "synthesised"):
        # Synthesised, not fetched: the same Heightfield a DEM bakes to,
        # centred on this spec's origin so the flight is actually over
        # it, deterministic from its seed, and available on a fresh
        # clone with no network. Real geography still comes from a real
        # bake through --terrain.
        from core.terrain.synthesis import ensure_ridge_for_origin

        terrain_stem = str(ensure_ridge_for_origin(
            REPO / "runs" / "terrain",
            float(spec.latitude.value), float(spec.longitude.value),
            name=f"synth_{spec.name or 'scene'}"))
        print(f"synthesised terrain: {terrain_stem} (deterministic; no "
              f"network; scene.terrain_source: {terrain_source}"
              f"{' + --synth-terrain' if args.synth_terrain else ''})")
    if terrain_stem:
        # W1: the bake's land cover (scripts/bake_landcover.py), when baked,
        # lets the runner infer the roughness of an unstated surface. Found
        # beside the PARENT bake: a runway pad (below) shares its grid.
        from core.terrain.landcover import scene_dir_for

        candidate = scene_dir_for(Path(terrain_stem)) / "landcover.json"
        landcover_json = candidate if candidate.is_file() else None
    # W2 (wired by W4): the runway's pad and record, the buildings document;
    # the flight flies over the pad when the spec states a runway.
    world_documents = _world_documents(spec, terrain_stem, landcover_json)
    if "violations" in world_documents:
        return _refuse(world_documents["violations"])
    terrain_stem = world_documents["terrain"]
    if world_documents["runway_document"]:
        print(f"runway: {world_documents['runway_document']} (the flight flies over the "
              f"pad {terrain_stem})")
    if world_documents["buildings_document"]:
        print(f"buildings: {world_documents['buildings_document']}")
    # W5: the editor-built scene (opt-in): its members ride the card's world
    # block and -scene= reaches the render.
    scene_members = None
    if getattr(args, "scene", None):
        scene_members = _scene_members(args.scene, terrain_stem)
        if "violations" in scene_members:
            return _refuse(scene_members["violations"])
        print(f"scene: {args.scene} (level {scene_members['scene_level']})")
    if terrain_stem:
        from core.terrain.ground import TerrainGround
        from core.terrain.heightfield import Heightfield

        heightfield = Heightfield.read(Path(terrain_stem))
        terrain_ground = TerrainGround(heightfield)
    if args.render:
        # Google's tiles draw the real place; the physics flies this run's
        # ground. Over the slab or a synthesised raster they are different
        # places, so the render refuses before any flight.
        from core.scenario.card import google_tiles_terrain_refusal

        chosen = "default" not in (str(spec.latitude.source), str(spec.longitude.source))
        tiles_refusal = google_tiles_terrain_refusal(
            heightfield, *((float(spec.latitude.value), float(spec.longitude.value),
                            float(spec.terrain_elevation.value)) if chosen else ()))
        if tiles_refusal is not None:
            return _refuse([Violation("google_tiles.terrain", tiles_refusal)])

    frame = SceneFrame.for_spec(spec, heightfield)
    tornado = _tornado_hazard_block(spec)

    report = validate(spec)
    if not report.ok:
        return _refuse(report.violations)
    # R2: the spec's record block asks for the extra flights the options
    # --null-tests / --uncertainty ask for (either side asking is honoured;
    # the options stay), and its convergence rates for the three-rate
    # study. An uncertainty block needs a u_x rule for every stated
    # variable: refused by name before any flight when one has none.
    record_asks = spec.record.asks(null_tests=args.null_tests, uncertainty=args.uncertainty)
    if record_asks["uncertainty"]:
        from core.scenario.validate import uncertainty_basis_violations

        basis_violations = uncertainty_basis_violations(spec)
        if basis_violations:
            return _refuse(basis_violations)
    # Phase 10: the randomisation block draws its values here too (the
    # web planners are not on this path); off by default -> no-op. A
    # window with no daylight refuses by name before any flight.
    from core.scenario.randomization import (
        RandomizationError, card_block as randomization_card_block,
        render_look, sample_randomization,
    )

    try:
        sample_randomization(spec)
    except RandomizationError as exc:
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        return 2
    if spec.randomization.is_enabled():
        block = spec.randomization
        print(f"randomization: seed {int(block.seed.value)}, sun "
              f"{float(block.sun_elevation_deg.value):.1f} deg elevation / "
              f"{float(block.sun_azimuth_deg.value):.1f} deg azimuth, fog "
              f"{float(block.fog_density.value):g} 1/m, livery "
              f"{block.livery.value}")
    static = static_camera_violations(
        spec, heightfield, frame, tornado,
        )
    if static:
        return _refuse(static)

    print(f"spec {spec.digest()[:16]} valid; running headlessly...")
    # A terrain impact or an untrimmable state is a NAMED outcome of the
    # scenario, not a bug in the tool: report it the way every other
    # refusal is reported instead of unwinding a stack trace at the
    # instructor. (Measured: flying a 1200 m example over a raster whose
    # ridge reaches 3043 m printed a traceback.)
    from core.control.autopilot import ClosureError
    from core.fdm.errors import TrimError
    from core.registry import RecordError
    from core.telemetry.instruments import InstrumentError
    from core.terrain.contact import TerrainImpactError

    try:
        result = run_spec(spec, terrain_ground=terrain_ground, landcover_json=landcover_json)
    except TerrainImpactError as exc:
        print(f"REFUSED -- terrain.impact: {exc}")
        return 2
    except (RecordError, InstrumentError) as exc:
        # R2: a registered write that read back outside its tolerance
        # (record.readback), or an instruments block the runner refuses.
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        return 2
    except TrimError as exc:
        print(f"REFUSED -- trim: {exc}")
        return 2
    except ClosureError as exc:
        # The held state was not reached (a 747 asked to hold altitude
        # in severe turbulence, measured): the runner's own refusal to
        # emit output, named, with its closure table -- not a traceback.
        print(f"REFUSED -- run.closure: {exc}")
        print("(the commanded state was not achieved within the declared "
              "tolerances, so no run was recorded; state hold_state: "
              "false for the open-loop flight, or ease the conditions)")
        return 2
    columns = result.telemetry.columns

    # R1 (opt-in): the null pairs and the dt/2 twin, each an extra flight
    # of the same spec through run_spec, measured after the recorded one.
    # Neither touches the recorded flight or its digest.
    # R2: asked by the options OR by the spec's record block (record_asks).
    null_pairs = {}
    uncertainty_block = None
    if record_asks["null_tests"] or record_asks["uncertainty"]:
        import functools
        from core.record_null import null_pairs_for_spec
        from core.uncertainty import uncertainty_for_run

        extra_runner = functools.partial(run_spec, assert_closure=False,
                                         terrain_ground=terrain_ground,
                                         landcover_json=landcover_json)
        if record_asks["null_tests"]:
            null_pairs = null_pairs_for_spec(spec, runner=extra_runner)
            print(f"  null tests: {len(null_pairs)} pair(s) flown"
                  + "".join(f"; {name}: {pair.verdict}" for name, pair in null_pairs.items())
                  + ("" if null_pairs else " (this spec states no registered variable)")
                  + f" [asked by {record_asks['asked_by']['null_tests'].lstrip('+')}]")
        if record_asks["uncertainty"]:
            # R2: record.convergence's three rates run the three-rate
            # study (dt, dt/2, dt/4 from the first rate, turbulence off);
            # its observed order per SRQ feeds u_num instead of p = 1.
            convergence = None
            if record_asks["convergence_rates_hz"]:
                from core.uncertainty import three_rate_study

                study_spec = ScenarioSpec.from_dict(spec.to_dict())
                study_spec.set("rate", record_asks["convergence_rates_hz"][0],
                               frm="record.convergence: the three-rate study's first rate")
                convergence = three_rate_study(study_spec, runner=extra_runner)
                print(f"  convergence: three-rate study at {convergence['rates_hz']} Hz; "
                      f"observed order {convergence['observed_p']}")
            uncertainty_block = uncertainty_for_run(
                spec, runner=extra_runner, base_result=result,
                observed_p=None if convergence is None else convergence["observed_p"])
            if convergence is not None:
                uncertainty_block["convergence"] = convergence
            alt = uncertainty_block["u_num"]["srq"]["altitude_m"]
            print(f"  uncertainty: dt/2 twin flown; u_num altitude {alt['value']:.3e} m "
                  f"({uncertainty_block['form']}) "
                  f"[asked by {record_asks['asked_by']['uncertainty'].lstrip('+')}]")

    cameras = spec.cameras or default_cameras(spec)
    if not spec.cameras:
        print("no camera stated: capturing with the documented default "
              "camera (the chase view)")
    # S2: each stated stereo rig's right camera, materialised and appended
    # (core/capture/stereo.py); its track and schedule are derived from the
    # left's in solve_over, and it meets the same scene checks.
    from core.capture.stereo import is_stereo_right, solve_rig, with_stereo_right

    cameras = with_stereo_right(cameras)
    terrain_datum = float(spec.terrain_elevation.value)

    from core.capture.poses import solve_traffic_track

    traffic_objects = [o for o in compose_objects(spec) if o.role == "traffic"]
    # P7: the wake generator is the last traffic-role object when the spec
    # states one; its track is the straight line the physics placed it on
    # (the run manifest's wake card geometry), solved beside the traffic.
    wake_geometry = ((result.manifest.get("wake") or {}).get("card") or {}).get("generator")
    wake_object = (traffic_objects[len(spec.traffic)]
                   if wake_geometry and len(traffic_objects) > len(spec.traffic) else None)

    def solve_traffic(flight):
        """The scripted traffic tracks over one recorded flight (Phase
        2, package B): solved beside the cameras, from the same
        telemetry, so the second aircraft's keyframes and the labels
        that describe it come out of one flight. The wake generator's
        track (P7) rides last."""
        tracks = [solve_traffic_track(flight, str(entry.track.value),
                                      float(entry.range_m.value), frame, obj.id,
                                      placement=entry.placement())
                  for entry, obj in zip(spec.traffic, traffic_objects)]
        if wake_object is not None:
            tracks.append(solve_traffic_track(flight, "wake_generator", 0.0, frame,
                                              wake_object.id, wake=wake_geometry))
        return tracks

    def solve_over(flight):
        """Pose tracks, schedules and their scene violations over one
        recorded flight. Runs twice when the host flies its own: once
        over the headless pre-run as the cheap pre-flight gate, once
        over the host's telemetry for the labels that ship."""
        tracks, schedules = [], []
        for camera in cameras:
            if is_stereo_right(camera):
                tracks.append(None)            # derived below from the left's
                schedules.append(None)
                continue
            tracks.append(solve_pose_track(flight, camera, frame))
            schedules.append(solve_schedule(flight, camera, frame))
        solve_rig(cameras, tracks, schedules)
        violations = []
        for track in tracks:
            violations.extend(track_violations(
                track, heightfield=heightfield, scene_frame=frame,
                tornado=tornado, terrain_elevation_m=terrain_datum))
        return tracks, schedules, violations

    try:
        tracks, schedules, solved_violations = solve_over(columns)
        traffic_tracks = solve_traffic(columns)
    except ScheduleError as exc:
        # The name once, at the head: str(exc) already begins with it.
        print(f"REFUSED -- {exc.constraint}: {_after_name(exc)}")
        return 2
    if solved_violations:
        return _refuse(solved_violations)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from core.capture.manifest import (
        SOLVE_HOST_FLIGHT, SOLVE_PRE_RUN, georeference_card_block,
    )
    from core.util.platform import (
        os_name, ue_available, ue_platform_refusal, ue_runner_command,
    )

    def write_card(path, tracks, schedules, landmarks, traffic_tracks=()):
        """The card the hosts read: spec fields + solved pose tracks,
        the labelled objects and the scripted traffic tracks."""
        from core.capture.airframe import load_airframe
        from core.capture.objects import (
            mesh_manifest_path, objects_block, taxonomy_classes,
        )
        from core.capture.poses import traffic_card_block
        from core.scenario.card import write_run_card
        from core.scene.runway import world_card_block

        # W4: the land cover's aggregates ride in objects[] exactly as the
        # manifest composes them (the same land-cover document decides).
        objects = compose_objects(spec, landcover=landcover_json is not None)
        traffic_objs = [o for o in objects if o.role == "traffic"]
        traffic_blocks = []
        for entry, obj, track in zip(spec.traffic, traffic_objs, traffic_tracks):
            name = str(entry.aircraft.value)
            mesh = mesh_manifest_path(name)
            traffic_blocks.append(traffic_card_block(
                track, entry, obj, frame,
                load_airframe(name).cg_structural_in,
                str(mesh) if mesh.is_file() else None))
        if wake_object is not None and len(traffic_tracks) > len(spec.traffic):
            # P7: the wake generator, drawn on the track the physics stated.
            from core.capture.poses import wake_generator_card_block

            name = str(wake_geometry["aircraft"])
            mesh = mesh_manifest_path(name)
            traffic_blocks.append(wake_generator_card_block(
                traffic_tracks[len(spec.traffic)], name, wake_geometry, wake_object, frame,
                load_airframe(name).cg_structural_in,
                str(mesh) if mesh.is_file() else None))
        return write_run_card(
            spec, path,
            cameras=[track.card_block(camera, schedule, frame)
                     for camera, track, schedule
                     in zip(cameras, tracks, schedules)],
            landmarks=landmarks,
            scene_crs=frame.crs if frame.declared else None,
            randomization=randomization_card_block(spec),
            objects=objects_block(objects),
            taxonomy=taxonomy_classes(spec),
            traffic=traffic_blocks,
            # W2 (wired by W4, absent-canonical): the world the host draws --
            # the flown terrain, the buildings and runway documents with
            # their sha256s -- only when the spec states either.
            world=_with_scene(
                world_card_block(terrain_stem,
                                 heightfield.digest() if heightfield else None,
                                 world_documents["buildings_document"],
                                 world_documents["runway_document"])
                if (world_documents["buildings_document"]
                    or world_documents["runway_document"] or scene_members) else None,
                scene_members),
            # The frame and datum the manifest records, for the host to
            # copy into render.json (check.georeference grades the copy).
            georeference=georeference_card_block(frame, heightfield, terrain_datum))

    solve_source = SOLVE_PRE_RUN
    solve_digest = result.output_digest

    # ------------------------------------------------------------------
    # ONE FLIGHT, NOT TWO.
    #
    # Everything above solved the poses over the HEADLESS pre-run -- the
    # jsbsim Python package. The host then flies the same card through
    # UE's vendored JSBSim, and two builds stepping one scenario do not
    # agree: 1.38 m worst, measured. The camera poses survive that (the
    # host consumes them verbatim) but the AIRCRAFT state in every frame
    # record described the pre-run while the pixels showed the host's
    # flight, which for labelled data is the defect that matters.
    #
    # So when there are pixels to take, the host flies FIRST -- the
    # telemetry-only commandlet, no renderer -- and everything is solved
    # again over ITS telemetry. The render passes then re-fly the same
    # card and, because the host is bit-deterministic, fly the identical
    # flight. Manifest and pixels describe one flight by construction.
    #
    # The pre-run is not wasted and is not skipped: it stays the cheap
    # pre-flight gate, so a camera inside a mountain still refuses
    # BEFORE a UE pass is spent rather than after one.
    # ------------------------------------------------------------------
    host_flight = args.render and not args.no_host_flight and ue_available()
    if host_flight:
        import subprocess

        from core.capture.hostflight import (
            HostFlightError, digest_columns, host_telemetry_path,
            read_all_host_columns, read_host_record,
        )

        host_dir = out / "host_flight"
        host_dir.mkdir(parents=True, exist_ok=True)
        # The card the SOLVE pass flies. It carries the pre-run's tracks;
        # the scenario commandlet ignores the cameras block entirely (it
        # renders nothing), and the card that the render passes consume
        # is rewritten below from the re-solved tracks.
        # No landmarks: this pass renders nothing and projects
        # nothing, so it has no use for them.
        write_card(host_dir / "card.json", tracks, schedules, None,
                   traffic_tracks)
        host_telemetry = host_telemetry_path(out)
        command = ue_runner_command(REPO, "run_ue_scenario")
        command += [str(host_dir / "card.json"), str(host_telemetry)]
        # Physics-affecting flags only. -Visual builds the RENDER scene
        # and this pass has no renderer; the terrain is what the ground
        # callback reads, so it has to match what the render passes fly
        # over or the two flights differ for a reason that is not the
        # host's determinism. verify_host_determinism is precisely the
        # check that grades this choice: if it ever FAILs on a run whose
        # passes differ only in -Visual, then -Visual perturbs the
        # flight and this pass has to carry it too.
        if terrain_stem:
            command.append(f"-terrain={terrain_stem}")
            command.append("-GeorefTerrain")
        print("flying the card in the host first, so the labels "
              "describe the flight the pixels show ...")
        completed = _run_unattended(command, host_telemetry.parent / "host_flight_pass.log")
        if completed.returncode != 0:
            print(f"REFUSED -- capture.host_flight: the scenario "
                  f"commandlet exited {completed.returncode} and recorded "
                  f"no flight; nothing was rendered. The wrapper printed "
                  f"its last words above and kept them in "
                  f"{host_telemetry.with_suffix('.log')}. Re-run with "
                  f"--no-host-flight to solve over the pre-run instead, "
                  f"knowing the labels will then describe a different "
                  f"flight from the one the pixels show")
            return 1
        try:
            # The whole record: every frame's ``state`` is cut from it.
            host_columns = read_host_record(host_telemetry)
            tracks, schedules, solved_violations = solve_over(host_columns)
            traffic_tracks = solve_traffic(host_columns)
        except HostFlightError as exc:
            print(f"REFUSED -- {exc.constraint}: {exc.message}")
            return 2
        except ScheduleError as exc:
            # The name once, at the head: str(exc) already begins with it.
            print(f"REFUSED -- {exc.constraint}: {_after_name(exc)}")
            return 2
        # The host's flight is a different flight, so the scene checks
        # run again over it. A camera that cleared the ridge on the
        # pre-run and does not on the host's own track must refuse --
        # this is the flight the frames would be taken on.
        if solved_violations:
            return _refuse(solved_violations)
        columns = host_columns
        solve_source = SOLVE_HOST_FLIGHT
        # Over EVERY column the host recorded, so output_digest means
        # the same thing whichever flight the manifest describes.
        solve_digest = digest_columns(read_all_host_columns(host_telemetry))
        print(f"  host flight: {len(host_columns['t'])} samples, digest "
              f"{solve_digest[:16]} -- poses re-solved over it")

    manifest = build_capture_manifest(
        spec, columns, frame, tracks, schedules,
        output_digest=solve_digest,
        solve_source=solve_source,
        scene={"key": "terrain" if heightfield else "flat",
               "terrain": terrain_stem,
               # W2 / W4 (absent-canonical): the world documents and the
               # land cover (found beside the parent bake), only when present.
               **{name: str(value) for name, value in (
                   ("buildings_document", world_documents["buildings_document"]),
                   ("runway_document", world_documents["runway_document"]),
                   ("landcover_document", landcover_json)) if value}},
        terrain_sha256=heightfield.digest() if heightfield else None,
        # The cameras that actually flew (default_cameras for a
        # camera-less spec); the digests stay the spec's own.
        cameras=cameras,
        # The scene's own known landmarks ride into the manifest so the
        # verifier has off-axis points that are not the aircraft.
        heightfield=heightfield, terrain_elevation_m=terrain_datum,
        # Phase 2 (package B): the scripted traffic's solved tracks, so
        # every frame carries a label record for the second aircraft.
        traffic_tracks=traffic_tracks[:len(spec.traffic)],
        # P7: the wake generator's object, airframe and track, labelled
        # like a traffic aircraft (None when no generator is stated).
        wake_generator=(None if wake_object is None else
                        (wake_object, str(wake_geometry["aircraft"]), traffic_tracks[len(spec.traffic)])),
        # R1: the V&V 20 block, or None (then no key: absent-canonical).
        uncertainty=uncertainty_block,
        # R2: the FDM-rate instruments block of the headless flight when
        # the spec stated an instrument (instruments.npz is written beside
        # the manifest below); None -- no key -- for the default ideal set.
        instruments=(result.manifest.get("instruments")
                     if result.instruments is not None and result.instruments.stated else None))
    if null_pairs:
        from core.record_null import attach_null_pair, null_pairs_block

        manifest["null_tests"] = null_pairs_block(null_pairs)
        for pair in null_pairs.values():
            attach_null_pair(manifest, pair)
            attach_null_pair(result.manifest, pair)
    # The instrument models over the HEADLESS recording (the flight
    # telemetry.json describes); the record rides in the capture manifest
    # (ADVANCEMENTS_CONTRACTS rule 0) and the measured file, if any, is
    # written beside telemetry.json below.
    from core.scenario.runner import attach_record

    measured = measure_instruments(
        result.telemetry.to_dict(), instrument_profile, int(spec.seed.value),
        source="user" if args.instruments is not None else "default")
    attach_record(manifest, measured.record)
    # The headless flight's own applied variables (the limits monitor, the
    # atmosphere; core/scenario/runner.py) ride in the capture manifest too,
    # one record per name, never repeated (they are already in run.json).
    flown = (result.manifest.get("applied_variables") or {}).get("applied_variables", [])
    if flown:
        from core.records import RECORD_VERSION

        block = manifest.setdefault(
            "applied_variables", {"record_version": RECORD_VERSION, "applied_variables": []})
        # D1: the headless flight's scene.geoid_undulation_m record carries
        # the appended channels' readback and the measured invariance; it
        # replaces the manifest's block-only record of the same name.
        flown_by_name = {r["name"]: r for r in flown}
        block["applied_variables"] = [
            flown_by_name.get(r["name"], r) if r["name"] == "scene.geoid_undulation_m" else r
            for r in block["applied_variables"]]
        present = {r["name"] for r in block["applied_variables"]}
        block["applied_variables"].extend(r for r in flown if r["name"] not in present)
    # D2: the Entity State PDU log beside the manifest, from the recorded
    # telemetry (the geoid applied at export through D1's hae_m column) and
    # labelled by the spec's dis block; its record rides in the capture
    # manifest and run.json, its PDU keys in every frame record.
    if dis_options is not None:
        from core.interop.dis import DisError
        from core.interop.dis_stream import INDEX_FILE, STREAM_FILE, attach_frame_keys, write_stream
        from core.records import AppliedVariable

        try:
            dis_index = write_stream(out, telemetry=result.telemetry.to_dict(),
                                     datum=manifest.get("datum"),
                                     aircraft=str(spec.aircraft.value),
                                     options=dis_options, udp=dis_udp)
        except DisError as exc:
            print(f"REFUSED -- {exc.constraint}: {exc.message}")
            return 2
        dis_record = AppliedVariable.from_dict(
            dis_index["applied_variables"]["applied_variables"][0])
        attach_record(manifest, dis_record)
        attach_record(result.manifest, dis_record)
        keyed = attach_frame_keys(manifest, dis_index)
        print(f"  dis:      {dis_index['pdu_count']} Entity State PDU(s) "
              f"({dis_index['emitter']['kind']}) in {out / STREAM_FILE}, index "
              f"{INDEX_FILE}, keys on {keyed} frame(s); entity type "
              f"{dis_index['entity_type']['source']}; timestamps "
              f"{dis_index['timestamp_mode']}; udp "
              f"{'sent ' + str(dis_index['udp']['datagrams']) if dis_index['udp']['sent'] else 'off'}")
    manifest_path = write_capture_manifest(manifest, out)
    write_frame_sidecars(manifest, out)
    result.telemetry.write_json(out / "telemetry.json")
    write_measured(measured, out)
    print("  " + describe_instruments(measured))
    # R2: the FDM-rate truth_* / meas_* file of the headless flight, when
    # the spec stated an instrument (its sha256 is the manifest's block's).
    if result.instruments is not None and result.instruments.write(out) is not None:
        fdm_block = result.manifest["instruments"]
        print(f"  instruments at the FDM rate: {fdm_block['steps']} steps at "
              f"{fdm_block['rate_hz']:g} Hz, {fdm_block['fixes']} GPS fixes -> "
              f"{fdm_block['file']} (sha256 {fdm_block['sha256'][:16]})")
    spec.write(out / "scenario.yaml")
    (out / "run.json").write_text(json.dumps({
        "spec_digest": result.spec_digest,
        # The HEADLESS pre-run's, always -- run.json describes the
        # flight run_spec flew. When the host flew its own and the
        # manifest was solved over that, the manifest's output_digest
        # is the host's and these two differ ON PURPOSE, which is the
        # visible trace of P10's real size.
        "output_digest": result.output_digest,
        "samples": len(result.telemetry),
        "solve_source": solve_source,
        "solve_digest": solve_digest,
        # The limits monitor's block and the applied-variable records of
        # the headless flight (core/telemetry/limits.py, core/records.py),
        # so a campaign report can count exceedances per case.
        "limits": result.manifest.get("limits"),
        "applied_variables": result.manifest.get("applied_variables"),
        # R1 (opt-in; null when the option was off): the null pairs and
        # the uncertainty block of the headless flight.
        "null_tests": manifest.get("null_tests"),
        "uncertainty": uncertainty_block,
        # R2: the FDM-rate instruments block of the headless flight (file
        # null for the default ideal set).
        "instruments": result.manifest.get("instruments"),
    }, indent=1), encoding="utf-8")

    if args.card or args.render:
        # The run-card projection with the cameras block: spec fields +
        # solved pose tracks, computed HERE, consumed verbatim by the
        # commandlet's consume-poses mode. The commandlet's own named
        # refusals still govern anything it cannot honour (hold_state,
        # airspeed_kind, a track that does not cover the run).
        #
        # After a host flight these are the RE-SOLVED tracks, so the
        # card the render passes consume and the manifest that labels
        # their output came out of one flight.
        write_card(out / "card.json", tracks, schedules,
                   manifest.get("landmarks"), traffic_tracks)
        print(f"  card:     {out / 'card.json'} (consume-poses; one "
              f"commandlet pass per camera via -camera-index=N)")

    previews = render_previews(manifest, out, heightfield=heightfield,
                               scene_frame=frame,
                               terrain_elevation_m=terrain_datum,
                               max_frames=args.max_previews)
    total = sum(len(s) for s in schedules)
    print(f"captured: {total} frames across {len(cameras)} camera(s)")
    print(f"  manifest: {manifest_path}")
    print(f"  previews: {len(previews)} geometry preview(s) under "
          f"{out / 'previews'}")

    if not args.render:
        if ue_available():
            print(f"UE render half present on this {os_name()} machine: add "
                  f"--render to produce the frames through these solved "
                  f"poses, one commandlet pass per camera.")
        else:
            print(ue_platform_refusal())
            print("(pixels only; the manifest and every verification check "
                  "that does not need them are complete here)")
        return 0

    if not ue_available():
        print(ue_platform_refusal())
        print("(--render asked for pixels; everything else in this run "
              "completed and is on disk)")
        return 0

    import subprocess

    frames_dir = out / "frames"
    from core.render.flags import (
        DEFAULT_FPS, DEFAULT_HEIGHT, DEFAULT_WIDTH, for_wrapper, render_flags,
    )
    from core.capture.passes import engine_words as engine_pass_words

    command = ue_runner_command(REPO, "render_ue_scenario")
    command += [str(out / "card.json"), str(frames_dir)]
    # Phase 2 (package A, contracts §9): the flags come from the ONE
    # builder the web app also uses, so the two render paths cannot
    # disagree by one of them forgetting a flag (measured: this command
    # never passed -mesh= until the placeholder rule, and neither path
    # passed -deterministic). The wrapper adds -scenario= -frames= per
    # run and -camera-index=N -telemetry= per camera pass, plus the
    # launcher tokens; for_wrapper() strips exactly those.
    #
    # The scene the frames are taken in. Gate 5's tier is a black void
    # -- deliberately, because its silhouette measurements need one --
    # and the camera phase inherited it by never asking for anything
    # else. The result was a grey airframe on black: no sky, no
    # horizon, no ground. -Visual builds the real scene (sun, sky,
    # atmosphere, fog, and terrain when a bake is present), and the
    # aircraft is then IN something. --void keeps the old tier for
    # anyone measuring silhouettes (no -Visual, no terrain, no look).
    #
    # The look: the sampled one when the randomisation block is on;
    # off, the builder's DEFAULT_LOOK (the harness's noon, the web
    # app's default since the showcase matrix). Before the builder this
    # command passed NO look when the block was off and the commandlet's
    # own defaults lit the frames (no sun override, fog 0.0025, bias
    # 11.0); one builder means one default, and the web app's is the
    # one pinned by test. render.json records the sun either way.
    #
    # -labels: the engine half of the labels beside every frame of
    # every camera pass (Phase 10). -deterministic: the texture/LOD
    # pins Gate 10-R proves the frame digests need. -mesh=: the
    # imported model checked above; the commandlet refuses a mesh/FDM
    # mismatch itself. The size and rate flags are the legacy path's;
    # every card this command writes carries cameras, so the commandlet
    # takes the size from the card's own camera and they are inert
    # (core/render/flags.py says what is and is not claimed).
    # S1: the sun in lux the render is handed -- the stated number, or
    # 'auto' (the spec's scene.sun_lux, else the clear-sky model at the
    # look's sun elevation), refused sensing.sun_lux by name here, before
    # any render time is spent. None = the option was not given.
    sun_lux_flag = None
    if args.sun_lux is not None:
        from core.capture.radiometry import sun_lux_for_spec
        from core.scenario.solar import SunLuxError, sun_lux_problem

        try:
            if str(args.sun_lux).strip().lower() == "auto":
                sun_block = sun_lux_for_spec(spec)
                if sun_block.get("value") is None:
                    raise SunLuxError(f"no sun to evaluate: {sun_block.get('from')}")
                sun_lux_flag = float(sun_block["value"])
            else:
                try:
                    sun_lux_flag = float(args.sun_lux)
                except ValueError:
                    raise SunLuxError(f"--sun-lux takes a number of lux or 'auto', not {args.sun_lux!r}")
                problem = sun_lux_problem(sun_lux_flag)
                if problem:
                    raise SunLuxError(problem)
        except SunLuxError as exc:
            print(f"REFUSED -- {exc.constraint}: {exc.message}")
            return 2
    command += for_wrapper(render_flags(
        out / "card.json", frames_dir,
        scene={"terrain": terrain_stem},
        mesh=_mesh_manifest_path(spec),
        look=render_look(spec), camera_flags=None,
        labels=True, deterministic=True, void=bool(args.void),
        width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, fps=DEFAULT_FPS,
        # S2: the engine words any camera's passes[] names ride beside --passes.
        passes=sorted({w for w in (args.passes or "").split(",") if w.strip()}
                      | set(engine_pass_words(cameras))),
        calibration=bool(args.calibration), sun_lux=sun_lux_flag,
        accumulate=args.accumulate,
        scene_document=str(args.scene) if getattr(args, "scene", None) else None))
    print(f"rendering {len(cameras)} camera pass(es) into {frames_dir} "
          f"{'in the black void (--void)' if args.void else 'in the visual scene'} ...")
    completed = _run_unattended(command, out / "render_pass.log")
    if completed.returncode != 0:
        # The renderer drew no pictures: the catalogue's camera.render.
        print(f"REFUSED -- camera.render: the render wrapper exited "
              f"{completed.returncode} and drew no pictures; the manifest "
              f"and verification above still stand")
        return 1
    rendered = sorted(p for p in frames_dir.rglob("frame_*.png")
                      if p.stem[-4:].isdigit())
    print(f"  frames:   {len(rendered)} rendered under {frames_dir}")

    # Phase 2 (package C): complete every frame's per-object records
    # from the bundle the engine just wrote -- the tight box from the
    # ID image, the visible fraction from the alone pass, occluded_by,
    # the depth under the mask -- and write the manifest and sidecars
    # back. A frame with no bundle keeps its nulls and says why.
    from core.capture.labels import attach_engine_labels

    from core.capture.passes import PassError

    try:
        attached = attach_engine_labels(out)
    except PassError as exc:
        # S2: a derived pass the bundle cannot supply, refused by its name.
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(f"  labels:   engine bundle attached on {attached['attached']} of "
          f"{attached['frames']} frames ({attached['objects']} object "
          f"records; {attached['without_bundle']} without a bundle)")
    derived = attached.get("derived_passes")
    if derived and derived.get("derived"):
        print(f"  passes:   flow / disparity / points derived on {derived['derived']} "
              f"frame(s); passes.json under {', '.join(derived['cameras'])}")

    # Phase 10: the sensor model as a seeded post-pass, for every camera
    # whose profile is not the ideal pinhole.
    from core.capture.profile import apply_profile_to_run

    sensor_written = apply_profile_to_run(out, manifest, int(spec.seed.value))
    if sensor_written:
        print("  sensor:   " + ", ".join(f"{cam} x{n} sensor frames"
                                        for cam, n in sorted(sensor_written.items())))

    # S1: the radiometry chain after the render -- the lens attenuation
    # read back, the sun's light units checked (sensing.exposure_units by
    # name when the engine's sun is not in lux), the grey card's ratio
    # when a calibration frame exists (S4) -- written back per camera and
    # per frame.
    from core.capture.radiometry import attach_render_radiometry

    radiometry = attach_render_radiometry(out, manifest)
    if radiometry["cameras"]:
        write_capture_manifest(manifest, out)
        write_frame_sidecars(manifest, out)
        print(f"  sensing:  radiometry on {radiometry['cameras']} camera(s); "
              f"{len(radiometry['measured'])} measured by a grey card, "
              f"{len(radiometry['refused'])} refused sensing.exposure_units (the sun is not in lux)")

    # S3: the IR proxy per frame from the render's ID image and depth, on
    # every camera whose manifest block carries sensing.ir (a declared
    # proxy: frame_NNNN_ir.f32 beside its frame_NNNN_ir.json declaration).
    from core.capture.thermal import render_ir_frames

    ir_frames = render_ir_frames(out, manifest)
    if ir_frames["cameras"]:
        write_capture_manifest(manifest, out)
        write_frame_sidecars(manifest, out)
        print(f"  ir proxy: {ir_frames['written']} frame(s) on {ir_frames['cameras']} camera(s), "
              f"{ir_frames['without_bundle']} without an ID image and depth (a proxy, not "
              f"sensor imagery); previews under {out / 'ir_preview'}")

    from core.capture.overlay import draw_overlays

    overlays = draw_overlays(manifest, out, max_frames=args.max_previews)
    print(f"  overlays: {len(overlays)} under {out / 'overlays'} -- the "
          f"recorded geometry drawn ON the rendered pixels; the circle "
          f"(manifest) and the cross (engine) should coincide")
    print(f"  verify:   python -m flightsim.verify {out}")
    print("  (with pixels present, verification exercises the landmark "
          "reprojection and two-view checks that report NOT RUN without "
          "them)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
