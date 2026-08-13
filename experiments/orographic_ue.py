"""Orographic wind in the render path: cross-checked port, null-tested coupling.

Phase 6B.2's wind-terrain coupling, held to Gate 3's discipline inside the
Unreal host:

1. **Cross-implementation check.** The C++ orographic field is a port of
   core/environment/terrain_field.py, and two implementations of one model is
   §1.4-shaped risk. At startup the render commandlet samples its field at a
   fixed grid and writes the values into the manifest; this harness recomputes
   every point through the ORIGINAL Python provider over the SAME baked raster
   with the SAME card parameters and compares. Tolerance is 1e-3 m/s -- puts a
   formula drift far above it and PROJ round-trip noise far below.

2. **Null test in the render path.** The same windy card is rendered twice:
   coupled, and with -NoOrographic severing the coupling. The FDM's own
   ``atmosphere/wind-down-fps`` recorded per frame must show vertical wind in
   the coupled run and essentially none in the control. What darkens when the
   coupling exists IS the coupling.

The scenario flies low over the Zermatt valley toward the Matterhorn in a
25 kt westerly, where the ridges force updraughts the model considers real.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.environment.terrain_field import OrographicWind  # noqa: E402
from core.terrain.glo30 import LOCATIONS, orographic_card_block  # noqa: E402
from core.terrain.ground import terrain_field_at  # noqa: E402
from core.terrain.heightfield import Heightfield  # noqa: E402
from experiments.gate5_ue_parity import reference_spec, write_run_card  # noqa: E402

RULE = "=" * 96

PROMPT = "fly the 747 at 2800 m and 250 kt for 20 seconds"
WIND_KT = 25.0
WIND_FROM_DEG = 270.0

THRESHOLDS = {
    #: Max |Python - C++| over the selftest grid, m/s.
    "max_port_difference_mps": 1e-3,
    #: RMS vertical wind the coupled run must show, fps. The scenario's
    #: ridges under a 25 kt wind force metre-per-second updraughts; 0.3 fps
    #: is far below what coupling delivers and far above numerical residue.
    "min_coupled_rms_fps": 0.3,
    #: What the severed control may show, fps.
    "max_control_rms_fps": 0.01,
}


def rms(values: Sequence[float]) -> float:
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0


def render(card: Path, frames: Path, terrain: Path, extra: Sequence[str]) -> None:
    editor = Path("/Users/Shared/Epic Games/UE_5.5/Engine/Binaries/Mac/UnrealEditor-Cmd")
    project = Path(__file__).resolve().parents[1] / "ue" / "FlightSim.uproject"
    frames.mkdir(parents=True, exist_ok=True)
    (frames / "render.json").unlink(missing_ok=True)
    command = [
        str(editor), str(project), "-run=FlightSimBridge.FlightSimRender",
        f"-scenario={card}", f"-frames={frames}",
        "-Visual", "-GeorefTerrain", "-shot=terrain", f"-terrain={terrain}",
        "-fps=2", "-seconds=12",
        "-unattended", "-nopause", "-nosplash",
        "-stdout", "-FullStdOutLogOutput",
        "-RenderOffScreen", "-AllowCommandletRendering",
        *extra,
    ]
    log = frames.parent / f"{frames.name}.log"
    with log.open("w") as sink:
        proc = subprocess.run(command, stdout=sink, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL)
    if not (frames / "render.json").is_file():
        raise RuntimeError(f"render into {frames} wrote no manifest (exit "
                           f"{proc.returncode}); see {log}")


def verify_port(manifest: Dict, card: Dict) -> Dict:
    """Recompute the C++ selftest grid through the original Python provider."""
    block = card["orographic"]
    baked = Heightfield.read(Path(block["terrain"]))
    field = terrain_field_at(baked, block["origin_x_m"], block["origin_y_m"],
                             wavelength_m=block["wavelength_m"])
    provider = OrographicWind(
        field, wind_speed_mps=block["wind_speed_mps"],
        wind_from_deg=block["wind_from_deg"],
        decay_height_m=block["decay_height_m"], enable_lee=block["lee"])

    samples = manifest["environment"]["orographic_selftest"]
    worst = 0.0
    for sample in samples:
        north, east = sample["north_m"], sample["east_m"]
        updraught = provider.linear_updraught(north, east)
        sink = provider.lee_sink(north, east)
        w_down = -((updraught - sink) * provider.decay(sample["agl_m"]))
        worst = max(worst, abs(w_down - sample["wind_down_mps"]))
        elevation = field.elevation_m(north, east)
        worst_elev = abs(elevation - sample["elevation_m"])
        if worst_elev > 0.5:
            worst = max(worst, worst_elev)   # a raster mismatch is a fail too
    return {
        "samples": len(samples),
        "max_difference_mps": worst,
        "tolerance_mps": THRESHOLDS["max_port_difference_mps"],
        "ok": bool(worst <= THRESHOLDS["max_port_difference_mps"]),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="UE orographic coupling")
    ap.add_argument("--out", default="runs/orographic_ue")
    ap.add_argument("--terrain", default="runs/terrain/matterhorn")
    ap.add_argument("--skip-renders", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    terrain = Path(args.terrain).resolve()

    location = LOCATIONS["matterhorn"]
    baked = Heightfield.read(terrain)

    print(f"\n{RULE}\n1. the windy scenario over the real ridge\n{RULE}")
    spec = reference_spec(PROMPT)
    spec.set("latitude", location.origin_lat, frm="matterhorn scene origin")
    spec.set("longitude", location.origin_lon, frm="matterhorn scene origin")
    spec.set("heading", 236.0, frm="toward the Matterhorn")
    from pyproj import Transformer
    transformer = Transformer.from_crs("EPSG:4326", baked.georeference.crs,
                                       always_xy=True)
    ox, oy = transformer.transform(location.origin_lon, location.origin_lat)
    spec.set("terrain_elevation", round(baked.elevation_at(ox, oy), 1),
             frm="baked raster at origin")
    spec.set("wind_speed", WIND_KT, frm="orographic scenario")
    spec.set("wind_direction", WIND_FROM_DEG, frm="orographic scenario")

    block = orographic_card_block(terrain, location.origin_lat,
                                  location.origin_lon, WIND_KT, WIND_FROM_DEG)
    card_path = write_run_card(spec, out / "card.json", orographic=block)
    card = json.loads(card_path.read_text(encoding="utf-8"))
    print(f"  spec {spec.digest()[:16]}, wind {WIND_KT:g} kt from "
          f"{WIND_FROM_DEG:g}, decay {block['decay_height_m']:.0f} m, "
          f"wavelength {block['wavelength_m']:.0f} m")

    if not args.skip_renders:
        print(f"\n{RULE}\n2. renders: coupled, then the severed control\n{RULE}")
        render(card_path, out / "coupled", terrain, [])
        render(card_path, out / "control", terrain, ["-NoOrographic"])
        print("  both rendered")

    coupled = json.loads((out / "coupled" / "render.json").read_text(encoding="utf-8"))
    control = json.loads((out / "control" / "render.json").read_text(encoding="utf-8"))

    print(f"\n{RULE}\n3. the port, checked against the original\n{RULE}")
    port = verify_port(coupled, card)
    print(f"  [{'ok  ' if port['ok'] else 'FAIL'}] {port['samples']} grid points: "
          f"max |Python - C++| = {port['max_difference_mps']:.2e} m/s "
          f"(tolerance {port['tolerance_mps']:g})")

    print(f"\n{RULE}\n4. the null test in the render path\n{RULE}")
    coupled_down = [r["wind_down_fps"] for r in coupled["frame_records"]]
    control_down = [r["wind_down_fps"] for r in control["frame_records"]]
    coupled_rms = rms(coupled_down)
    control_rms = rms(control_down)
    null_ok = (coupled_rms >= THRESHOLDS["min_coupled_rms_fps"]
               and control_rms <= THRESHOLDS["max_control_rms_fps"])
    print(f"  [{'ok  ' if null_ok else 'FAIL'}] vertical wind inside the FDM: "
          f"coupled RMS {coupled_rms:.3f} fps, severed control {control_rms:.5f} fps")
    print(f"         (coupled must exceed {THRESHOLDS['min_coupled_rms_fps']}, "
          f"control must stay under {THRESHOLDS['max_control_rms_fps']})")

    report = {
        "spec_digest": spec.digest(),
        "card_orographic": block,
        "port_check": port,
        "null_test": {
            "coupled_rms_fps": coupled_rms,
            "control_rms_fps": control_rms,
            "thresholds": {k: v for k, v in THRESHOLDS.items()
                           if k != "max_port_difference_mps"},
            "ok": bool(null_ok),
        },
    }
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n  wrote {out / 'report.json'}")

    if port["ok"] and null_ok:
        print("\n  OROGRAPHIC COUPLING: PASS -- the port matches the original "
              "and the ridge's wind demonstrably reaches the FDM.")
        return 0
    print("\n  OROGRAPHIC COUPLING: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
