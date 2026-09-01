"""The Zermatt valley run: a scripted banked path over the real Matterhorn bake.

Waypoint flying without an autopilot claim: the flight is a SCRIPT -- timed
aileron/elevator inputs through the existing control_inputs mechanism, the
same step-held offsets the UE host applies on top of the latched trim -- so
it is exactly reproducible and makes no claim of guidance. The script banks
the c172p through a series of S-turns down the valley.

Honesty gates, in order:
1. The scripted flight is flown HEADLESS first, applying the same inputs on
   the same JSBSim, and the actual track's clearance above the baked raster
   is measured. A run that would tunnel through a mountainside on screen is
   refused before any render (the showcase's microburst rule).
2. The render then flies the SAME card, and the frame records carry the
   FDM's own roll: the verification asserts the commanded banks actually
   happened (peak |roll| above the bar in both directions) and that the
   camera did what its preset declares -- the chase render keeps camera
   roll at zero (§1.5) while the optional shoulder render declares
   camera_inherits_roll=true in its manifest.

Usage: .venv/bin/python experiments/zermatt_run.py [--skip-renders]
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

from core.util.platform import ue_editor_path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.fdm import FlightDynamics, TrimMode  # noqa: E402
from core.fdm import units as u  # noqa: E402
from core.terrain.glo30 import LOCATIONS  # noqa: E402
from core.terrain.ground import TerrainGround  # noqa: E402
from core.terrain.heightfield import Heightfield  # noqa: E402
from experiments.gate5_ue_parity import reference_spec, write_run_card  # noqa: E402

RULE = "=" * 96

DURATION_S = 45.0
ALTITUDE_M = 2900.0     # above the valley, below the ridgelines
AIRSPEED_KT = 100.0
MIN_CLEARANCE_M = 60.0
MIN_PEAK_ROLL_DEG = 12.0

#: Aileron that holds the c172p wings-level at this power setting, measured
#: by sweep (0.02 rolls to -14 deg over 20 s, 0.04 to +5 deg): the propeller
#: torque the longitudinal-only trim leaves uncancelled. The script's
#: "neutral" is this bias, not zero -- with zero, every hold accumulated
#: left roll and the run ended -60 deg over.
TORQUE_BIAS = 0.033

#: The script: S-turns down the valley about the measured neutral, with a
#: counter-pulse after each bank so the roll rate is arrested rather than
#: left to run (measured: uncorrected holds spiralled to -116 deg).
VALLEY_SCRIPT = (
    {"t_s": 4.0, "aileron": TORQUE_BIAS + 0.19},
    {"t_s": 7.0, "aileron": TORQUE_BIAS - 0.12},
    {"t_s": 8.5, "aileron": TORQUE_BIAS},
    {"t_s": 12.0, "aileron": TORQUE_BIAS - 0.18},
    {"t_s": 14.5, "aileron": TORQUE_BIAS + 0.12},
    {"t_s": 16.5, "aileron": TORQUE_BIAS},
    {"t_s": 20.0, "aileron": TORQUE_BIAS + 0.19},
    {"t_s": 23.0, "aileron": TORQUE_BIAS - 0.12},
    {"t_s": 24.5, "aileron": TORQUE_BIAS},
    {"t_s": 28.0, "aileron": TORQUE_BIAS - 0.18},
    {"t_s": 30.5, "aileron": TORQUE_BIAS + 0.12},
    {"t_s": 32.5, "aileron": TORQUE_BIAS},
    {"t_s": 36.0, "aileron": TORQUE_BIAS + 0.19},
    {"t_s": 39.0, "aileron": TORQUE_BIAS - 0.12},
    {"t_s": 40.5, "aileron": TORQUE_BIAS},
)


def fly_headless(spec, ground: TerrainGround):
    """The scripted flight on the same JSBSim, for the clearance measurement."""
    fdm = FlightDynamics(str(spec.aircraft.value), rate_hz=float(spec.rate.value))
    fdm.set_initial_conditions(
        {"h-sl-ft": u.m_to_ft(float(spec.altitude.value)),
         "vc-kts": float(spec.airspeed.value), "gamma-deg": 0.0,
         "phi-deg": 0.0, "psi-true-deg": float(spec.heading.value),
         "beta-deg": 0.0, "lat-geod-deg": float(spec.latitude.value),
         "long-gc-deg": float(spec.longitude.value),
         "terrain-elevation-ft": u.m_to_ft(float(spec.terrain_elevation.value))}
    )
    fdm.start_engines()
    fdm.trim(TrimMode.LONGITUDINAL)
    fdm.hold_mass(True)
    trimmed_aileron = fdm.props.get("fcs/aileron-cmd-norm")

    track = []
    applied = -1
    steps = int(round(DURATION_S * fdm.rate_hz))
    for i in range(steps):
        t = fdm.sim_time
        current = applied
        for j, entry in enumerate(VALLEY_SCRIPT):
            if entry["t_s"] <= t:
                current = j
        if current != applied:
            applied = current
            fdm.set_controls(aileron=trimmed_aileron
                             + VALLEY_SCRIPT[applied]["aileron"])
        fdm.step()
        if i % 12 == 0:
            s = fdm.state()
            elevation = (ground.elevation_at(s.lat_deg, s.lon_deg)
                         if ground.contains(s.lat_deg, s.lon_deg) else 0.0)
            track.append({"t": s.t, "lat": s.lat_deg, "lon": s.lon_deg,
                          "altitude_m": s.altitude_m, "roll_deg": s.roll_deg,
                          "terrain_m": elevation,
                          "clearance_m": s.altitude_m - elevation})
    return track


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Zermatt valley run")
    ap.add_argument("--out", default="runs/zermatt_run")
    ap.add_argument("--terrain", default="runs/terrain/matterhorn")
    ap.add_argument("--skip-renders", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    terrain = Path(args.terrain).resolve()

    location = LOCATIONS["matterhorn"]
    baked = Heightfield.read(terrain)
    ground = TerrainGround(baked)

    print(f"\n{RULE}\n1. the script, flown headless for the clearance gate\n{RULE}")
    spec = reference_spec(
        f"fly the c172 at {ALTITUDE_M:.0f} m and {AIRSPEED_KT:.0f} kt for 30 seconds")
    spec.set("latitude", location.origin_lat, frm="matterhorn scene origin")
    spec.set("longitude", location.origin_lon, frm="matterhorn scene origin")
    spec.set("heading", 200.0, frm="down the Mattertal toward Zermatt")
    spec.set("terrain_elevation",
             round(ground.elevation_at(location.origin_lat, location.origin_lon), 1),
             frm="baked raster at origin")

    track = fly_headless(spec, ground)
    min_clearance = min(p["clearance_m"] for p in track)
    peak_left = min(p["roll_deg"] for p in track)
    peak_right = max(p["roll_deg"] for p in track)
    print(f"  actual-track clearance above the raster: min {min_clearance:.0f} m "
          f"(gate {MIN_CLEARANCE_M:.0f} m)")
    print(f"  banks flown: {peak_left:.1f} deg left, {peak_right:.1f} deg right")
    if min_clearance < MIN_CLEARANCE_M:
        print("\n  REFUSED: the scripted track does not clear the terrain; "
              "no render will show an aircraft inside a mountain.")
        return 1
    banks_ok = (peak_right >= MIN_PEAK_ROLL_DEG
                and peak_left <= -MIN_PEAK_ROLL_DEG)
    if not banks_ok:
        print("\n  REFUSED: the script never reached its banks; a 'valley run' "
              "flying straight would be a mislabeled clip.")
        return 1

    card_path = write_run_card(spec, out / "card.json",
                               control_inputs=VALLEY_SCRIPT,
                               duration_s=DURATION_S)

    renders = {}
    for preset in ("chase", "shoulder"):
        frames = out / f"frames_{preset}"
        if not args.skip_renders:
            print(f"\n{RULE}\n2. render: {preset} preset\n{RULE}")
            editor = ue_editor_path()
            project = Path(__file__).resolve().parents[1] / "ue" / "FlightSim.uproject"
            frames.mkdir(parents=True, exist_ok=True)
            (frames / "render.json").unlink(missing_ok=True)
            command = [
                str(editor), str(project), "-run=FlightSimBridge.FlightSimRender",
                f"-scenario={card_path}", f"-frames={frames}",
                "-Visual", "-GeorefTerrain", "-shot=showcase",
                f"-terrain={terrain}",
                f"-mesh={Path('assets/generated/c172p/mesh_manifest.json').resolve()}",
                "-chase=-40:0:5", f"-camera={preset}",
                f"-imagery={Path('runs/terrain/matterhorn_imagery.json').resolve()}",
                "-fps=30", "-width=1280", "-height=720",
                "-sun-elev=35.0", "-sun-azim=140.0",
                "-exposure-bias=9.5", "-fog-density=0.0012",
                "-unattended", "-nopause", "-nosplash",
                "-stdout", "-FullStdOutLogOutput",
                "-RenderOffScreen", "-AllowCommandletRendering",
            ]
            log = out / f"render_{preset}.log"
            with log.open("w") as sink:
                proc = subprocess.run(command, stdout=sink,
                                      stderr=subprocess.STDOUT,
                                      stdin=subprocess.DEVNULL)
            if not (frames / "render.json").is_file():
                raise RuntimeError(f"{preset} render wrote no manifest (exit "
                                   f"{proc.returncode}); see {log}")
        renders[preset] = json.loads((frames / "render.json").read_text(encoding="utf-8"))

    print(f"\n{RULE}\n3. verification from the recordings\n{RULE}")
    checks = {}
    chase = renders["chase"]["frame_records"]
    rolls = [r["roll_deg"] for r in chase]
    cam_roll = max(abs(r["camera_roll_deg"]) for r in chase)
    checks["banks_on_screen"] = (max(rolls) >= MIN_PEAK_ROLL_DEG
                                 and min(rolls) <= -MIN_PEAK_ROLL_DEG)
    checks["chase_camera_roll_zero"] = cam_roll < 1e-4
    checks["chase_declares_level"] = (
        renders["chase"]["scene"]["camera_inherits_roll"] is False)
    checks["shoulder_declares_roll"] = (
        renders["shoulder"]["scene"]["camera_inherits_roll"] is True)
    shoulder_cam = max(abs(r["camera_roll_deg"])
                       for r in renders["shoulder"]["frame_records"])
    checks["shoulder_actually_rolls"] = shoulder_cam >= MIN_PEAK_ROLL_DEG

    for name, ok in checks.items():
        print(f"  [{'ok  ' if ok else 'FAIL'}] {name}")
    print(f"  chase camera peak |roll| {cam_roll:.6f} deg; shoulder "
          f"{shoulder_cam:.1f} deg (the declared exception)")

    report = {
        "script": [dict(e) for e in VALLEY_SCRIPT],
        "headless_gate": {"min_clearance_m": min_clearance,
                          "peak_roll_left_deg": peak_left,
                          "peak_roll_right_deg": peak_right},
        "checks": checks,
        "ok": all(checks.values()),
    }
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n  ZERMATT RUN: {'PASS' if report['ok'] else 'FAIL'} -> "
          f"{out / 'report.json'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
