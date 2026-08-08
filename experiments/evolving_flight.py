"""The evolving-conditions long flight: calm dawn to storm, in one recording.

One continuous 150 s clip over the control ridge: calm at dawn, wind
building, gusts, then a storm with severe turbulence -- the sun rising
through the flight and the telemetry panel narrating plan against actual
with phase labels. Every mechanism was individually null-tested before this
composition, and the phases are VERIFIED from the recording afterward:

* windowed n_z RMS must RISE phase over phase (calm < building < gusts <
  storm) -- the atmosphere the FDM integrated, not the one the card claims;
* the FDM's horizontal wind must track the schedule (the recorded
  ``atmosphere/wind-*`` against the card's own floats);
* the recorded W20 must follow the turbulence schedule -- W20 only, seed
  written once, severity pinned (JSBSIM_CORRECTIONS §13; the machinery is
  ScheduledDrydenTurbulence + the card's turbulence_schedule, re-implemented
  COMPLETELY this phase after being reverted mid-6B).

The aircraft flies 280 m above the spec's slab, inside the W20 route's
measured 300 m AGL validity ceiling, so the scheduled intensity actually
governs. The visual terrain is the control ridge; the physics ground is the
labeled flat slab.

Usage: .venv/bin/python experiments/evolving_flight.py [--skip-render]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.environment.gust import DiscreteGust  # noqa: E402
from core.environment.turbulence import ScheduledDrydenTurbulence  # noqa: E402
from core.fdm import units as u  # noqa: E402
from core.terrain.glo30 import orographic_card_block  # noqa: E402
from core.terrain.heightfield import Heightfield  # noqa: E402
from experiments.gate5_ue_parity import reference_spec, write_run_card  # noqa: E402
from experiments.showcase_matrix import (  # noqa: E402
    AIRFRAMES, ensure_terrains, microburst_track,
)
from experiments.showcase_panel import build_panel_clip  # noqa: E402

RULE = "=" * 96

DURATION_S = 150.0
AGL_M = 280.0     # inside the W20 route's measured 300 m validity ceiling
FPS = 30

#: The plan: phase starts, labels, and what each phase commands.
PHASES = (
    (0.0, "calm dawn"),
    (40.0, "wind building"),
    (80.0, "gusty"),
    (115.0, "storm, severe turbulence"),
)
TURBULENCE_SEGMENTS = (
    (0.0, "none"), (60.0, "light"), (95.0, "moderate"), (120.0, "severe"),
)
SEED = 62999

#: Verification bars, stated before the render:
CHECKS = {
    #: Each phase's windowed n_z RMS (5 s settle skipped after each boundary)
    #: must exceed the previous phase's by at least this factor.
    "min_phase_rms_growth": 1.15,
    #: The FDM's written wind against the card's schedule, fps.
    "max_wind_tracking_error_fps": 0.5,
    #: Recorded W20 against the schedule, fps.
    "max_w20_error_fps": 0.5,
}


def wind_speed_kt(t: float) -> float:
    """The storyline's steady wind: calm, linear build, plateau, storm."""
    if t < 40.0:
        return 0.0
    if t < 80.0:
        return 15.0 * (t - 40.0) / 40.0
    if t < 115.0:
        return 15.0
    return min(15.0 + 10.0 * (t - 115.0) / 20.0, 25.0)


def build_wind_schedule(from_deg: float, rate_hz: float,
                        airspeed_mps: float) -> List[Dict[str, float]]:
    """Per-step NED wind: the storyline speed + 1-cosine gusts, one model."""
    surges = [
        DiscreteGust(peak_mps=u.kt_to_mps(peak), start_s=start,
                     gradient_m=gradient, airspeed_mps=airspeed_mps,
                     axis="north")
        for start, peak, gradient in (
            (84.0, 10.0, 120.0), (93.0, 7.0, 350.0), (104.0, 9.0, 120.0),
            (118.0, 14.0, 120.0), (127.0, 10.0, 350.0), (136.0, 13.0, 120.0),
            (144.0, 15.0, 120.0),
        )
    ]
    down_gusts = [
        DiscreteGust(peak_mps=peak, start_s=start, gradient_m=120.0,
                     airspeed_mps=airspeed_mps, axis="down")
        for start, peak in ((100.0, 3.0), (132.0, 5.0))
    ]
    radians = math.radians(from_deg)
    steps = int(round(DURATION_S * rate_hz))
    schedule = []
    for step in range(steps):
        t = step / rate_hz
        speed = u.kt_to_mps(wind_speed_kt(t)) \
            + sum(g.magnitude_at(t) for g in surges)
        schedule.append({
            "t_s": round(t, 6),
            "north_fps": u.mps_to_fps(-speed * math.cos(radians)),
            "east_fps": u.mps_to_fps(-speed * math.sin(radians)),
            "down_fps": u.mps_to_fps(sum(g.magnitude_at(t)
                                         for g in down_gusts)),
        })
    return schedule


def windowed_rms(records: Sequence[Dict], t0: float, t1: float,
                 settle_s: float = 5.0) -> float:
    xs = [r["n_z"] - 1.0 for r in records
          if t0 + settle_s <= r["t"] < t1]
    return math.sqrt(sum(x * x for x in xs) / len(xs)) if xs else 0.0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="the evolving-conditions flight")
    ap.add_argument("--out", default="runs/evolving_flight")
    ap.add_argument("--skip-render", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    print(f"\n{RULE}\n1. the card: every phase from the one set of providers\n{RULE}")
    terrains = ensure_terrains(out)
    terrain = terrains["control"]
    airframe = AIRFRAMES["c172p"]
    altitude = terrain["ground_m"] + AGL_M
    airspeed_mps = u.kt_to_mps(100.0)
    heading = microburst_track(terrain, altitude, airspeed_mps)

    spec = reference_spec(
        f"fly the c172 at {int(altitude)} m and 100 kt for 30 seconds")
    spec.set("latitude", terrain["lat"], frm="control scene origin")
    spec.set("longitude", terrain["lon"], frm="control scene origin")
    spec.set("heading", heading, frm="terrain-clearance scan")
    spec.set("terrain_elevation", terrain["ground_m"],
             frm="slab at the raster origin elevation")
    spec.set("wind_speed", 0.0, frm="calm at t=0; the schedule builds it")
    spec.set("wind_direction", round(heading), frm="headwind storyline")
    spec.set("seed", SEED, frm="evolving flight")

    schedule = ScheduledDrydenTurbulence(TURBULENCE_SEGMENTS, seed=SEED)
    wind_schedule = build_wind_schedule(round(heading), float(spec.rate.value),
                                        airspeed_mps)
    orographic = orographic_card_block(terrain["path"], terrain["lat"],
                                       terrain["lon"], 0.0, round(heading))
    card_path = write_run_card(
        spec, out / "card.json", duration_s=DURATION_S,
        wind_schedule=wind_schedule,
        orographic=orographic, orographic_follow_schedule=True,
        turbulence_schedule=schedule.card_schedule(),
        turbulence_provider=schedule,
    )
    print(f"  {DURATION_S:.0f} s at {altitude:.0f} m ({AGL_M:.0f} m above the "
          f"slab), heading {heading:.0f}; phases: "
          + " -> ".join(f"{t:g}s {label}" for t, label in PHASES))

    frames = out / "frames"
    if not args.skip_render:
        print(f"\n{RULE}\n2. the render (150 s, sun rising 8 -> 30 deg)\n{RULE}")
        import subprocess

        editor = Path("/Users/Shared/Epic Games/UE_5.5/Engine/Binaries/Mac/UnrealEditor-Cmd")
        project = Path(__file__).resolve().parents[1] / "ue" / "FlightSim.uproject"
        frames.mkdir(parents=True, exist_ok=True)
        (frames / "render.json").unlink(missing_ok=True)
        command = [
            str(editor), str(project), "-run=FlightSimBridge.FlightSimRender",
            f"-scenario={card_path}", f"-frames={frames}",
            "-Visual", "-GeorefTerrain", "-shot=showcase",
            f"-terrain={terrain['path']}",
            f"-mesh={Path(airframe['manifest']).resolve()}",
            f"-chase={airframe['chase']}",
            f"-fps={FPS}", "-width=1280", "-height=720",
            "-sun-elev=8.0", "-sun-azim=95.0",
            "-sun-elev-end=30.0", "-sun-azim-end=130.0",
            "-exposure-bias=10.5", "-fog-density=0.0012",
            "-unattended", "-nopause", "-nosplash",
            "-stdout", "-FullStdOutLogOutput",
            "-RenderOffScreen", "-AllowCommandletRendering",
        ]
        log = out / "render.log"
        with log.open("w") as sink:
            proc = subprocess.run(command, stdout=sink,
                                  stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL)
        if not (frames / "render.json").is_file():
            raise RuntimeError(f"render wrote no manifest (exit "
                               f"{proc.returncode}); see {log}")

    manifest = json.loads((frames / "render.json").read_text())
    records = manifest["frame_records"]
    card = json.loads(card_path.read_text())

    print(f"\n{RULE}\n3. the phases, verified from the recording\n{RULE}")
    report: Dict = {"phases": []}
    boundaries = [t for t, _ in PHASES] + [DURATION_S]
    rms_values = []
    for i, (start, label) in enumerate(PHASES):
        value = windowed_rms(records, start, boundaries[i + 1])
        rms_values.append(value)
        report["phases"].append({"phase": label, "start_s": start,
                                 "n_z_rms": value})
        print(f"  {label:28s} n_z RMS {value:.4f} g")
    growth_ok = all(rms_values[i + 1] >= rms_values[i]
                    * CHECKS["min_phase_rms_growth"]
                    for i in range(len(rms_values) - 1))
    print(f"  [{'ok  ' if growth_ok else 'FAIL'}] each phase rougher than the "
          f"last (factor >= {CHECKS['min_phase_rms_growth']})")

    # The FDM's written wind against the card's own schedule.
    times = card["wind_schedule"]
    def commanded_at(t):
        entry = times[0]
        for e in times:
            if e["t_s"] <= t:
                entry = e
            else:
                break
        return entry
    wind_err = max(
        math.hypot(r["wind_north_fps"] - commanded_at(r["t"])["north_fps"],
                   r["wind_east_fps"] - commanded_at(r["t"])["east_fps"])
        for r in records)
    wind_ok = wind_err <= CHECKS["max_wind_tracking_error_fps"]
    print(f"  [{'ok  ' if wind_ok else 'FAIL'}] FDM wind tracks the schedule: "
          f"max error {wind_err:.3f} fps")

    w20_err = max(abs(r["w20_fps"] - schedule.w20_fps_at(r["t"]))
                  for r in records)
    w20_ok = w20_err <= CHECKS["max_w20_error_fps"]
    print(f"  [{'ok  ' if w20_ok else 'FAIL'}] W20 follows the turbulence "
          f"schedule: max error {w20_err:.3f} fps")

    sun = manifest.get("scene", {})
    print(f"  sun animated: {sun.get('sun_animated')} "
          f"({sun.get('sun_elevation_deg')} -> {sun.get('sun_elevation_end_deg')} deg)")

    print(f"\n{RULE}\n4. encode + panel with phase labels\n{RULE}")
    import subprocess

    raw = out / "evolving_raw.mp4"
    subprocess.run([
        "/opt/homebrew/bin/ffmpeg", "-y", "-framerate", str(FPS),
        "-i", str(frames / "frame_%04d.png"),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-pix_fmt", "yuv420p", str(raw),
    ], capture_output=True)
    conditions = {
        "wind_note": "calm dawn -> building -> gusts -> storm (schedule)",
        "phases": [[t, label] for t, label in PHASES],
    }
    final = out / "evolving_conditions.mp4"
    panel_ok = build_panel_clip(card_path, frames / "render.json", conditions,
                                raw, final, fps=FPS)
    print(f"  {'wrote' if panel_ok else 'PANEL FAILED for'} {final}")

    ok = growth_ok and wind_ok and w20_ok and panel_ok
    report.update({
        "wind_tracking_max_error_fps": wind_err,
        "w20_max_error_fps": w20_err,
        "checks": CHECKS, "sun": sun, "ok": bool(ok),
    })
    (out / "report.json").write_text(json.dumps(report, indent=1))
    print(f"\n  EVOLVING FLIGHT: {'PASS' if ok else 'FAIL'} -> {out / 'report.json'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
