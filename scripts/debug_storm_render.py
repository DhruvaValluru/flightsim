"""Reproduce a storm render OUTSIDE the web app, keeping every log.

    python scripts/debug_storm_render.py [--backend off|procedural|niagara ...]
        [--prompt "..."] [--seconds S] [--out DIR] [--terrain STEM]

The web app deletes a failed run's folder, so the log that says WHY it
failed goes with it. This writes a run card from the prompt the way the web
app does (the same compiler; hold_state off for the host, which has no
autopilot; the storm placed on the track by severe_event_centre, so the
card carries the downburst block the storm cell is centred on), then runs
the FlightSimRender
commandlet once per backend with the same flags (core/render/flags.py) for a
few seconds of flight, into <out>/<backend>/, and prints the decisive lines
of each log: every weather / cloud line, every material that failed to
compile, and the engine's assertion if it still crashes. A run that
survives prints "RENDERED".

Windows, from the repo root, the engine built (scripts/build_ue.ps1):

    .\\.venv\\Scripts\\python.exe scripts\\debug_storm_render.py --backend off --backend procedural

Flat scene (no terrain) unless --terrain names a bake stem under
runs/terrain; the storm, the rain and the clouds do not need one.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

DEFAULT_PROMPT = "fly the c172 through a thunderstorm at 900 m with 25 mm/h rain, chase camera"
#: The lines worth reading out of a commandlet log.
DECISIVE = re.compile(
    r"LogFlightSimWeather|weather\.|clouds\.|cloud |look\.clouds|LogFlightSimRender: Display: clouds"
    r"|Failed to compile Material|Missing If|Assertion failed|Fatal error|appError"
    r"|LogFlightSimRender: Error|refused|frames written|MATERIAL-|Engine exit requested")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", action="append", default=None,
                        help="off | procedural | niagara (repeatable; default: off then procedural)")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--seconds", type=float, default=2.0, help="flight seconds to render")
    parser.add_argument("--out", type=Path, default=REPO / "runs" / "debug_storm")
    parser.add_argument("--terrain", default=None, help="a bake stem under runs/terrain (default: flat)")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    args = parser.parse_args(argv)
    backends = args.backend or ["off", "procedural"]

    from core.nl.compiler import compile_prompt
    from core.render.flags import render_flags
    from core.render.headless import HEADLESS_FLAGS, run_headless
    from core.scenario.card import write_run_card
    from core.util.platform import ue_editor_path
    from webapp.runs import (CLIP_SECONDS, _projected_origin, project_for_ue_host,
                             severe_event_centre)

    args.out.mkdir(parents=True, exist_ok=True)
    spec = compile_prompt(args.prompt)
    # The web app's projection for the render host (hold_state off: it has
    # no autopilot) and its storm placement (the downburst block the storm
    # cell is centred on), so this card is the card the web app renders.
    project_for_ue_host(spec)
    scene = {"terrain": args.terrain} if args.terrain else {}
    seconds = min(float(spec.duration.value), CLIP_SECONDS)
    origin_x, origin_y, scene_crs = _projected_origin(spec, scene)
    downburst = None
    if str(spec.weather_event.value) == "thunderstorm":
        from core.environment.downburst import Downburst

        downburst = Downburst(*severe_event_centre(spec, scene, seconds)).card_block(origin_x, origin_y)
    card = write_run_card(spec, args.out / "card.json", duration_s=seconds, downburst=downburst,
                          scene_crs=scene_crs)
    text = json.loads(card.read_text(encoding="utf-8"))
    print(f"card: {card}")
    print(f"  weather_event={spec.weather_event.value} rain={spec.precipitation_rate_mmh.value} "
          f"hold_state={text.get('hold_state')} blocks: weather={'weather' in text} "
          f"weather_look={'weather_look' in text} rain_particles={'rain_particles' in text} "
          f"downburst={'downburst' in text}")

    editor = ue_editor_path()
    if editor is None or not editor.is_file():
        print(json.dumps({"error": f"no UnrealEditor-Cmd at {editor} (set UE_ROOT)"}))
        return 2
    scene = scene or None
    verdicts = {}
    for backend in backends:
        frames = args.out / backend / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        extra = [f"-seconds={args.seconds}", "-NoGoogleTiles"]
        if backend != "off":
            extra.append(f"-weather-backend={backend}")
        command = [str(editor), str(REPO / "ue" / "FlightSim.uproject"),
                   "-run=FlightSimBridge.FlightSimRender"] + render_flags(
            card, frames, scene=scene, mesh=None, look=None, camera_flags=None,
            labels=False, width=args.width, height=args.height, fps=5.0, extra=extra)
        log = args.out / backend / "render.log"
        print(f"\n=== {backend}: {log}")
        result = run_headless(list(command) + list(HEADLESS_FLAGS), log, watch=[frames])
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines() if log.is_file() else []
        for line in lines:
            if DECISIVE.search(line):
                print("  " + line.strip()[:300])
        rendered = (frames / "render.json").is_file()
        crashed = any("Assertion failed" in line or "Fatal error" in line for line in lines)
        verdicts[backend] = "RENDERED" if rendered else ("CRASHED" if crashed else "REFUSED/NO FRAMES")
        # The editor exits 1 whenever any error was logged (the project's
        # Water Body Collision profile error, on every run); the verdict is
        # whether render.json was written, as the web app judges it.
        print(f"  -> {verdicts[backend]} (editor exit code {result.returncode}, {result.seconds:.0f} s)")
    print("\n" + json.dumps(verdicts))
    return 0 if all(v == "RENDERED" for v in verdicts.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
