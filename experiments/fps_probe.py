"""Phase 8B.0: the real-time frame-rate probe -- the go/no-go number for 8C.

The Mac has only ever rendered this scene offline, where a slow frame costs
wall time rather than correctness. Before anything depends on a windowed
interactive host, this probe flies the full Matterhorn scene (30 m heightfield
collision + georeferenced terrain + imagery drape + sky/fog/sun + the substep
ledger on screen) in a REAL window for a fixed wall-clock interval and records
what the frames actually cost. The budget gets measured, not assumed.

Thresholds, stated before measuring
-----------------------------------
* GO        -- fps_mean >= 30 and frame_ms_p95 <= 50: the interactive tier is
               viable at the probe's window size.
* MARGINAL  -- fps_mean >= 20: viable with the known mitigations (visual
               stride is already 2; smaller window; HUD cost bounded).
* NO-GO     -- below that, 8C degrades gracefully to the clip pipeline
               (8B.1), exactly as the brief planned.

The probe scene's airframe is a placeholder box and there is no full HUD yet;
the report says so, so the number cannot be quoted as covering either.

Usage: .venv/bin/python experiments/fps_probe.py [--seconds 60] [--skip-run]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.terrain.glo30 import LOCATIONS  # noqa: E402
from core.terrain.ground import TerrainGround  # noqa: E402
from core.terrain.heightfield import Heightfield  # noqa: E402
from experiments.gate5_ue_parity import reference_spec, write_run_card  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

RULE = "=" * 96

THRESHOLDS = {"go_fps_mean": 30.0, "go_frame_ms_p95": 50.0,
              "marginal_fps_mean": 20.0}

#: The GUI binary parks in the AppKit event loop when the console session
#: is locked (sampled: main thread in -[NSApplication run] forever, even
#: with -RenderOffScreen). The -Cmd binary runs the same engine without
#: NSApplication and works in a locked session -- it is what every
#: commandlet invocation in this repo already uses.
EDITOR_WINDOWED = Path(
    "/Users/Shared/Epic Games/UE_5.5/Engine/Binaries/Mac/UnrealEditor")
EDITOR_OFFSCREEN = Path(
    "/Users/Shared/Epic Games/UE_5.5/Engine/Binaries/Mac/UnrealEditor-Cmd")
PROJECT = Path(__file__).resolve().parents[1] / "ue" / "FlightSim.uproject"
MAP_URL = "/Engine/Maps/Entry?game=/Script/FlightSimBridge.FlightSimInteractiveMode"


def screen_locked() -> bool:
    """A GUI window cannot open while the console session is locked: the
    editor's main thread parks in the AppKit event loop forever (measured --
    two wedged launches at 6% CPU with the lock up). Detected so the probe
    can say WHY it is falling back to offscreen instead of hanging."""
    probe = subprocess.run(["ioreg", "-n", "Root", "-d1", "-a"],
                           capture_output=True, text=True)
    return "CGSSessionScreenIsLocked" in probe.stdout


def editor_already_running() -> bool:
    """Gotcha 9: one editor instance at a time, enforced rather than hoped.

    The pattern matches the engine's editor binaries only ("Binaries/Mac/
    UnrealEditor" and "...UnrealEditor-Cmd") -- NOT the always-on
    UnrealEditorServices helper or the Epic launcher's EpicWebHelper, which
    live at different paths and hold no editor lock.
    """
    probe = subprocess.run(["pgrep", "-f", "Binaries/Mac/UnrealEditor"],
                           capture_output=True, text=True)
    return probe.returncode == 0 and probe.stdout.strip() != ""


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="real-time fps probe (8B.0)")
    ap.add_argument("--out", default="runs/fps_probe")
    ap.add_argument("--terrain", default="runs/terrain/matterhorn")
    ap.add_argument("--imagery", default="runs/terrain/matterhorn_imagery.json")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--timeout", type=float, default=1800.0,
                    help="wall cap incl. first-launch shader compiles")
    ap.add_argument("--offscreen", action="store_true",
                    help="force the offscreen loop (no window)")
    ap.add_argument("--skip-run", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    terrain = Path(args.terrain).resolve()
    imagery = Path(args.imagery).resolve()
    report_path = out / "report.json"

    print(f"\n{RULE}\n8B.0 real-time fps probe: full Matterhorn scene, "
          f"{args.width}x{args.height} window\n{RULE}")

    # The same Matterhorn condition agl_parity measured: real collision
    # raster, real relief along the track, hands off from trim.
    location = LOCATIONS["matterhorn"]
    ground = TerrainGround(Heightfield.read(terrain))
    # 5200 m: the showcase's own B747 Matterhorn altitude, above every peak
    # of the raster (tops at 4540 m) -- the 3600 m first attempt flew INTO
    # the massif at t=51.8 s and crashed the probe.
    spec = reference_spec("fly the 747 at 5200 m and 250 kt for 300 seconds")
    spec.set("latitude", location.origin_lat, frm="matterhorn scene origin")
    spec.set("longitude", location.origin_lon, frm="matterhorn scene origin")
    spec.set("heading", 236.0, frm="toward the Matterhorn massif")
    start_elev = ground.elevation_at(location.origin_lat, location.origin_lon)
    spec.set("terrain_elevation", round(start_elev, 1),
             frm="baked raster at the start point")
    card = write_run_card(spec, out / "card.json",
                          collision_terrain=str(terrain))
    print(f"  spec {spec.digest()[:16]}, start ground {start_elev:.1f} m, "
          f"probe {args.seconds:.0f} s wall")

    if not args.skip_run:
        if editor_already_running():
            print("\n  REFUSED: an UnrealEditor process is already running "
                  "(gotcha 9: one editor instance at a time). Kill it or "
                  "wait, then re-run.")
            return 2
        offscreen = args.offscreen or screen_locked()
        if offscreen and not args.offscreen:
            print("  console session is LOCKED: a window cannot open, so the "
                  "loop runs offscreen.\n  The number excludes window "
                  "compositing; re-run unlocked for the windowed figure.")
        report_path.unlink(missing_ok=True)
        if offscreen:
            # -game cannot run under a locked console session on Mac (both
            # editor binaries park in the AppKit event loop; sampled). The
            # commandlet probe loop measures the same scene through the same
            # stepping path with one CaptureScene per frame, no readback --
            # the report's "display" field states what that excludes.
            scratch = out / "probe_frames"
            scratch.mkdir(exist_ok=True)
            mesh = REPO / "assets" / "generated" / "B747" / "mesh_manifest.json"
            command = [
                str(EDITOR_OFFSCREEN), str(PROJECT),
                "-run=FlightSimBridge.FlightSimRender",
                f"-scenario={card}", f"-frames={scratch}",
                "-Visual", "-GeorefTerrain", "-shot=showcase",
                f"-terrain={terrain}", f"-imagery={imagery}",
                f"-mesh={mesh}", "-chase=-170:0:16",
                f"-width={args.width}", f"-height={args.height}",
                "-sun-elev=50", "-sun-azim=180", "-exposure-bias=9.5",
                "-fog-density=0.0012",
                f"-probe-wall-seconds={args.seconds:.0f}",
                f"-probe-report={report_path}",
                "-unattended", "-nopause", "-nosplash",
                "-stdout", "-FullStdOutLogOutput",
                "-RenderOffScreen", "-AllowCommandletRendering",
            ]
        else:
            command = [
                str(EDITOR_WINDOWED), str(PROJECT), MAP_URL, "-game",
                f"-card={card}", f"-imagery={imagery}",
                f"-probe-seconds={args.seconds:.0f}",
                f"-report={report_path}",
                "-camera=chase", "-windowed",
                f"-ResX={args.width}", f"-ResY={args.height}",
                "-nosplash", "-stdout", "-FullStdOutLogOutput",
            ]
        log = out / "probe.log"
        print(f"  launching windowed host (log: {log})")
        with log.open("w") as sink:
            proc = subprocess.Popen(command, stdout=sink,
                                    stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL)
            deadline = time.time() + args.timeout
            while proc.poll() is None and time.time() < deadline:
                time.sleep(2.0)
            if proc.poll() is None:
                proc.terminate()
                print(f"  TIMED OUT after {args.timeout:.0f} s; see {log}")
                return 1

    if not report_path.is_file():
        print(f"\n  NO REPORT was written -- the host failed before or during "
              f"the probe. See {out / 'probe.log'}")
        return 1

    report = json.loads(report_path.read_text(encoding="utf-8"))
    fps = float(report.get("fps_mean", 0.0))
    p95 = float(report.get("frame_ms_p95", 1e9))
    outcome = str(report.get("outcome", ""))

    print(f"\n  outcome        {outcome}")
    print(f"  frames         {report.get('frames')} over "
          f"{report.get('wall_seconds', 0.0):.1f} s wall")
    print(f"  fps mean       {fps:.1f}")
    print(f"  frame ms       p50 {report.get('frame_ms_p50', 0.0):.1f}  "
          f"p95 {p95:.1f}  max {report.get('frame_ms_max', 0.0):.1f}")
    print(f"  substeps       {report.get('substeps')} "
          f"({report.get('sim_seconds', 0.0):.1f} s sim at "
          f"{report.get('substep_rate_hz', 0.0):.0f} Hz)")
    print(f"  behind         {report.get('deficit_seconds', 0.0):.3f} s over "
          f"{report.get('deficit_events')} capped frames")
    print(f"  scene          terrain {report.get('terrain')!r} "
          f"imagery {report.get('imagery_dataset')!r}")
    print(f"  not covered    {report.get('airframe')}")

    # Substep accounting sanity: steps must equal sim seconds at the fixed
    # rate exactly (whole substeps only), or the one-clock claim is broken.
    expected = round(float(report.get("sim_seconds", 0.0))
                     * float(report.get("substep_rate_hz", 120.0)))
    accounted = int(report.get("substeps", -1)) == expected
    print(f"  substep ledger {'consistent' if accounted else 'INCONSISTENT'} "
          f"({report.get('substeps')} vs {expected} expected)")

    if not outcome.startswith("probe complete"):
        print(f"\n  8B.0: FAILED -- the probe did not complete ({outcome})")
        return 1
    if fps >= THRESHOLDS["go_fps_mean"] and p95 <= THRESHOLDS["go_frame_ms_p95"]:
        verdict = "GO"
    elif fps >= THRESHOLDS["marginal_fps_mean"]:
        verdict = "MARGINAL -- viable with stated mitigations"
    else:
        verdict = "NO-GO -- 8C degrades to the clip pipeline"
    report["display"] = ("offscreen (window compositing excluded; "
                         "console session was locked)"
                         if args.offscreen or screen_locked()
                         else "windowed")
    report["thresholds"] = THRESHOLDS
    report["verdict"] = verdict
    report["substep_ledger_consistent"] = bool(accounted)
    report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n  8B.0 VERDICT: {verdict}")
    return 0 if accounted else 1


if __name__ == "__main__":
    raise SystemExit(main())
