"""Reproduce a storm render OUTSIDE the web app, keeping every log.

    python scripts/debug_storm_render.py [--backend off|procedural|niagara ...]
        [--prompt "..."] [--seconds S] [--out DIR] [--terrain STEM]

The web app's page names the wrong log for a failed host flight and clears
its frame scratch, so the lines that say WHY it failed are hard to find.
This writes a run card from the prompt the way the web app does (the same
compiler; hold_state off for the host, which has no autopilot; the storm
placed on the track by severe_event_centre, so the card carries the
downburst block the storm cell is centred on), then runs the
FlightSimRender commandlet once per backend with the same flags
(core/render/flags.py) for a few seconds of flight, into <out>/<backend>/,
and prints the decisive lines of each log: every weather / cloud / storm
exposure line, every material that failed to compile, and the engine's
assertion if it still crashes. A run that survives prints "RENDERED" with
the first and last frame's luma (0..255; the mean and the 90th
percentile) -- a bright end under DARK_LUMA makes the verdict
"RENDERED-DARK": a frame nobody can see anything in is not a pass (the
owner's first storm frame, 2026-10-08).

Windows, from the repo root, the engine built (scripts/build_ue.ps1):

    .\\.venv\\Scripts\\python.exe scripts\\debug_storm_render.py --backend off --backend procedural

The scene is the web app's for the prompt (plan_scene_setting stages a
curated bake for a prompt that names no place; pick_scene; the aircraft's
own mesh when assets/generated/<aircraft>/mesh_manifest.json exists, else
the commandlet's placeholder boxes, said so), unless --terrain names a bake
stem under runs/terrain or --flat asks for the bare slab (the owner's
first debug frame, 2026-10-09: a flat world and a box aircraft in fog,
which told him nothing about the storm).

To SEE the cell from outside instead of starting inside its rain shaft,
place it at a distance in the prompt: "... towards a thunderstorm 5 km
ahead ..." (core/nl/compiler.py event_ahead_m; the 45 %-of-the-run point
of a 3-second clip is 70 m ahead, inside the shaft).
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
    r"|storm exposure|Failed to compile Material|Missing If|Assertion failed|Fatal error|appError"
    r"|LogFlightSimRender: Error|refused|frames written|MATERIAL-|Engine exit requested")
#: A frame whose bright end (the 90th percentile of its luma, 0..255) is
#: under this is one nobody can see anything in: the storm meter
#: (FlightSimRenderCommandlet.cpp) exists so no storm frame is. The mean is
#: the dark ground's and does not separate them (measured 2026-10-09: the
#: web app's storm look, visible, mean 24 / p95 82; the black frame, not,
#: mean 17 / p95 28). Stated: 32 is an eighth of white.
DARK_LUMA = 32.0
FRAME = re.compile(r"frame_\d+\.png")


def frame_luma(path: Path):
    """(mean, 90th percentile) of a frame's 8-bit luma: Rec. 709 weights on
    the PNG's sRGB bytes, the same measure the storm meter opens the
    exposure by (it reports 0..1; this reports 0..255)."""
    import numpy as np
    from PIL import Image

    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)
    luma = rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722
    return float(luma.mean()), float(np.percentile(luma, 90))


def frame_report(frames: Path):
    """The first and last beauty frame's luma, and whether either is DARK."""
    files = sorted(p for p in frames.glob("frame_*.png") if FRAME.fullmatch(p.name))
    if not files:
        return [], False
    lines = []
    dark = False
    for label, path in (("first", files[0]), ("last", files[-1])):
        mean, p90 = frame_luma(path)
        dark = dark or p90 < DARK_LUMA
        lines.append(f"{label} frame {path.name}: luma mean {mean:.1f}/255, p90 {p90:.1f}"
                     f"{' DARK' if p90 < DARK_LUMA else ''}")
    return lines, dark


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", action="append", default=None,
                        help="off | procedural | niagara (repeatable; default: off then procedural)")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--seconds", type=float, default=2.0, help="flight seconds to render")
    parser.add_argument("--out", type=Path, default=REPO / "runs" / "debug_storm")
    parser.add_argument("--terrain", default=None,
                        help="a bake stem under runs/terrain (default: the web app's scene for the prompt)")
    parser.add_argument("--flat", action="store_true", help="the bare slab, no terrain")
    parser.add_argument("--no-google-tiles", action="store_true",
                        help="the baked ground instead of Google's tiles (the web app's own render "
                             "draws the tiles; its throw-away solve pass does not)")
    # 1280 x 720: at 640 x 360 a drop a metre from the camera is under a
    # pixel and the rain cannot be judged.
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args(argv)
    backends = args.backend or ["off", "procedural"]

    from core.nl.compiler import compile_prompt
    from core.render.flags import render_flags
    from core.render.headless import HEADLESS_FLAGS, run_headless
    from core.scenario.card import write_run_card
    from core.util.platform import ue_editor_path
    from webapp.runs import (CLIP_SECONDS, TERRAIN_DIR, _projected_origin, baked, pick_scene,
                             plan_scene_setting, project_for_ue_host, render_look_for,
                             severe_event_centre, webapp_chase_flag)

    args.out.mkdir(parents=True, exist_ok=True)
    spec = compile_prompt(args.prompt)
    # The web app's stage for a prompt that names no place (a curated bake),
    # its projection for the render host (hold_state off: it has no
    # autopilot) and its storm placement (the downburst block the storm
    # cell is centred on), so this card is the card the web app renders.
    plan_scene_setting(spec)
    project_for_ue_host(spec)
    if args.flat:
        scene = {}
    elif args.terrain:
        stem = TERRAIN_DIR / args.terrain
        scene = {"terrain": str(stem) if baked(stem) else args.terrain}
    else:
        scene = pick_scene(spec)
    seconds = min(float(spec.duration.value), CLIP_SECONDS)
    origin_x, origin_y, scene_crs = _projected_origin(spec, scene)
    downburst = None
    # The look the web app gives the commandlet for this spec (the storm look
    # for a thunderstorm: its dim low sun, bias and fog), so the light the
    # storm meter meters is the light the web app's frame has.
    look = render_look_for(spec, "thunderstorm" if str(spec.weather_event.value) == "thunderstorm"
                           else None)
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
    print(f"  look: {look if look is None else {k: look[k] for k in look if k != 'note'}}")
    aircraft = str(spec.aircraft.value)
    mesh = REPO / "assets" / "generated" / aircraft / "mesh_manifest.json"
    if not mesh.is_file():
        print(f"  mesh: none at {mesh} -- the commandlet draws its placeholder boxes for the "
              f"{aircraft} (the web app builds the mesh on its first render)")
        mesh = None
    else:
        print(f"  mesh: {mesh}")
    print(f"  scene: terrain={scene.get('terrain') if scene else None} "
          f"({scene.get('kind') if scene else 'flat slab'}); imagery="
          f"{scene.get('imagery') if scene else None} (none: the land-cover material colours "
          f"the ground); Google tiles {'off (-NoGoogleTiles)' if args.no_google_tiles else 'on'}")
    camera_flags = ([f"-chase={webapp_chase_flag(aircraft)}", "-camera=chase"], [])

    editor = ue_editor_path()
    if editor is None or not editor.is_file():
        print(json.dumps({"error": f"no UnrealEditor-Cmd at {editor} (set UE_ROOT)"}))
        return 2
    scene = scene or None
    verdicts = {}
    for backend in backends:
        frames = args.out / backend / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        # A previous run's frames and manifest would be read as this run's
        # (measured: a refused run reported the frames of the run before).
        for stale in [frames / "render.json"] + list(frames.glob("frame_*.png")):
            stale.unlink(missing_ok=True)
        extra = [f"-seconds={args.seconds}"] + (["-NoGoogleTiles"] if args.no_google_tiles else [])
        if backend != "off":
            extra.append(f"-weather-backend={backend}")
        command = [str(editor), str(REPO / "ue" / "FlightSim.uproject"),
                   "-run=FlightSimBridge.FlightSimRender"] + render_flags(
            card, frames, scene=scene, mesh=mesh, look=look, camera_flags=camera_flags,
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
        verdicts[backend] = "CRASHED" if crashed else ("RENDERED" if rendered else "REFUSED/NO FRAMES")
        if rendered and not crashed:
            # The storm meter's record and the frames' own brightness: a
            # frame that rendered black is not a pass.
            try:
                manifest = json.loads((frames / "render.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                manifest = {}
            meter = (manifest.get("look_applied") or {}).get("storm_exposure")
            if meter:
                print(f"  storm_exposure: opened {meter.get('stops_opened')} stops, p90 luma "
                      f"{meter.get('p90_luma_before')} -> {meter.get('p90_luma_after')} "
                      f"(target {meter.get('target_p90_luma')}; mean "
                      f"{meter.get('mean_luma_before')} -> {meter.get('mean_luma_after')}): "
                      f"{meter.get('note')}")
            report, dark = frame_report(frames)
            for line in report:
                print("  " + line)
            if dark:
                verdicts[backend] = "RENDERED-DARK"
        # The editor exits 1 whenever any error was logged (the project's
        # Water Body Collision profile error, on every run); the verdict is
        # whether render.json was written, as the web app judges it.
        print(f"  -> {verdicts[backend]} (editor exit code {result.returncode}, {result.seconds:.0f} s)")
    print("\n" + json.dumps(verdicts))
    return 0 if all(v == "RENDERED" for v in verdicts.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
