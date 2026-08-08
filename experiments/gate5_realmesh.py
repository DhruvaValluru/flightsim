"""Gate 5's on-screen clauses, re-run against the real aircraft meshes.

Phase 6B.1 replaces the placeholder boxes with properly-licensed FlightGear
airframes. Gate 5's original pass was measured against the boxes, so the
on-screen clauses are re-measured here against each real mesh, with the SAME
harness code deciding them (experiments.gate5_ue_parity.measure_frames):

* every frame shows the aircraft;
* the camera never inherits roll;
* control surfaces articulate, measured off the scene components;
* apparent bank in the pixels tracks FDM roll at r >= 0.98.

One run per (mesh, matching FDM) pairing -- the commandlet refuses a mesh
whose manifest names a different FDM than the card flies, so a wrong pairing
cannot produce frames here at all (§1.4).

Gate 5 itself (boxes) is untouched and must stay green; this harness proves
the REAL meshes clear the same bar, not that the bar moved.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.gate5_ue_parity import (  # noqa: E402
    RENDER_DURATION_S, ROLL_DOUBLET, measure_frames, reference_spec,
    write_run_card,
)

RULE = "=" * 96

#: A gentler doublet for the light airframe: at Gate 5's ±0.25 the Cessna
#: rolled through -63 degrees, turned off the chase camera's axis and shrank
#: to 0.06% of the frame (measured). The clause needs a >= 10 degree sweep,
#: not an aerobatic departure.
LIGHT_DOUBLET = (
    {"t_s": 4.0, "aileron": 0.10},
    {"t_s": 6.5, "aileron": 0.0},
    {"t_s": 10.0, "aileron": -0.10},
    {"t_s": 12.5, "aileron": 0.0},
)

#: Each airframe with its prompt, a chase framing scaled to its size -- a
#: Cessna framed like a 747 is eleven pixels wide and measures nothing --
#: and a doublet scaled to its roll response.
AIRFRAMES = (
    {
        "name": "B747",
        "prompt": "fly the 747 at 3000 m and 250 kt for 60 seconds",
        "manifest": "assets/generated/B747/mesh_manifest.json",
        "chase": "-170:0:16",
        "min_bound_surfaces": 7,
        "doublet": ROLL_DOUBLET,
    },
    {
        "name": "c172p",
        "prompt": "fly the c172 at 1500 m and 100 kt for 60 seconds",
        "manifest": "assets/generated/c172p/mesh_manifest.json",
        "chase": "-40:0:5",
        # Six hinged control surfaces plus the continuous propeller binding
        # (Phase 7 3.3).
        "min_bound_surfaces": 7,
        "doublet": LIGHT_DOUBLET,
    },
    {
        # Phase 7 3.2: the generic pipeline's third airframe. The FDM names
        # itself A320-200; §1.4 pairing is enforced by converter and
        # commandlet exactly as for the first two.
        "name": "A320",
        "prompt": "fly the a320 at 3000 m and 250 kt for 60 seconds",
        "manifest": "assets/generated/A320/mesh_manifest.json",
        # A 37 m airframe at the 747's 170 m chase covers 0.45% of frame
        # (measured, under the 0.5% floor); framed like the mid-size it is.
        "chase": "-110:0:11",
        "min_bound_surfaces": 5,
        "doublet": ROLL_DOUBLET,
    },
)


def render(card: Path, frames: Path, manifest: Path, chase: str) -> bool:
    editor = Path("/Users/Shared/Epic Games/UE_5.5/Engine/Binaries/Mac/UnrealEditor-Cmd")
    project = Path(__file__).resolve().parents[1] / "ue" / "FlightSim.uproject"
    frames.mkdir(parents=True, exist_ok=True)
    for stale in frames.glob("frame_*.png"):
        stale.unlink()
    (frames / "render.json").unlink(missing_ok=True)
    command = [
        str(editor), str(project), "-run=FlightSimBridge.FlightSimRender",
        f"-scenario={card}", f"-frames={frames}",
        f"-mesh={manifest}", f"-chase={chase}",
        "-unattended", "-nopause", "-nosplash",
        "-stdout", "-FullStdOutLogOutput",
        "-RenderOffScreen", "-AllowCommandletRendering",
    ]
    log = frames.parent / f"{frames.name}.log"
    with log.open("w") as sink:
        proc = subprocess.run(command, stdout=sink, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL)
    return (frames / "render.json").is_file()


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 5 on-screen, real meshes")
    ap.add_argument("--out", default="runs/gate5_realmesh")
    ap.add_argument("--skip-render", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    root = Path(__file__).resolve().parents[1]

    all_ok = True
    summary = {}
    for airframe in AIRFRAMES:
        name = airframe["name"]
        print(f"\n{RULE}\n{name}: the same roll doublet, the real mesh\n{RULE}")
        spec = reference_spec(airframe["prompt"])
        frames = out / name
        card = write_run_card(spec, out / f"{name}_card.json",
                              control_inputs=airframe["doublet"],
                              duration_s=RENDER_DURATION_S)
        manifest_path = (root / airframe["manifest"]).resolve()
        if not args.skip_render or not (frames / "render.json").is_file():
            if not render(card, frames, manifest_path, airframe["chase"]):
                print(f"  {name}: render did not complete -- BLOCKED")
                return 2

        manifest = json.loads((frames / "render.json").read_text())
        mesh = manifest.get("mesh", {})
        print(f"  mesh {mesh.get('mesh_airframe')} [{mesh.get('license')}] "
              f"fdm {mesh.get('fdm')}")
        bound = int(manifest.get("bound_surfaces", 0))
        checks = measure_frames(frames / "render.json")
        checks_ok = all(check.ok for check in checks)
        for check in checks:
            print(check.render())
        binding_ok = bound >= airframe["min_bound_surfaces"]
        print(f"  [{'ok  ' if binding_ok else 'FAIL'}] "
              f"{bound} surfaces bound to geometry "
              f"(mesh manifest promises {airframe['min_bound_surfaces']})")
        summary[name] = {
            "spec_digest": spec.digest(),
            "mesh": mesh,
            "bound_surfaces": bound,
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail}
                       for c in checks],
            "ok": bool(checks_ok and binding_ok),
        }
        all_ok = all_ok and summary[name]["ok"]

    (out / "report.json").write_text(json.dumps(summary, indent=1))
    print(f"\n{RULE}\nGATE 5 ON-SCREEN, REAL MESHES\n{RULE}")
    for name, entry in summary.items():
        print(f"  [{'PASS' if entry['ok'] else 'FAIL'}] {name}")
    print(f"  wrote {out / 'report.json'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
