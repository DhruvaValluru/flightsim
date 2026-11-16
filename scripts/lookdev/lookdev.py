"""Editor side of the look-dev harness. Run inside the ONE Mac editor (Monolith
editor_query run_python), never in a commandlet:

    exec(open("<repo>/scripts/lookdev/lookdev.py", encoding="utf-8").read())
    setup()                 # once per editor: materials + the scenes' aircraft
    build(1)                # the scene's beauty set-up in a blank editor map
    capture(1, "base")      # starts <OUT>/base/1.png (1280x720); written once the
                            # tiles stream, then <png>.status.json appears
                            # (scripts/lookdev/shoot.sh waits for it)

build() reads <OUT>/prep/<NN>/lookdev.json from scripts/lookdev/prepare.py and
calls the bridge's FlightSim.LookDev.Build (FlightSimLookDev.cpp), which runs
the render commandlet's own beauty classes with the commandlet's arguments.
Every function returns a dict (the C++ status) and raises on a failure.
"""
import json
import os
import sys

import unreal

REPO = os.path.abspath(os.path.join(
    unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()), ".."))
OUT = os.environ.get(
    "FLIGHTSIM_LOOKDEV_DIR",
    "/private/tmp/claude-501/-Users-dhruva-flightsim/"
    "1ee4c848-46ef-47be-bb8c-91917a93ad66/scratchpad/lookdev")


def _world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()


def _console(command):
    unreal.SystemLibrary.execute_console_command(_world(), command)


def _status(path):
    status_path = path + ".status.json"
    if not os.path.isfile(status_path):
        raise RuntimeError(f"lookdev: no status for {path} (is the bridge built with "
                           f"FlightSimLookDev.cpp?)")
    with open(status_path, encoding="utf-8") as handle:
        status = json.load(handle)
    os.remove(status_path)
    if not status.get("ok"):
        raise RuntimeError(f"lookdev: {status.get('error')}")
    return status


def _run_script(path, argv=()):
    """A repo editor script, as -run=pythonscript -script=<path> <argv> runs it."""
    saved = sys.argv
    sys.argv = [path] + list(argv)
    try:
        with open(path, encoding="utf-8") as handle:
            code = compile(handle.read(), path, "exec")
        exec(code, {"__file__": path, "__name__": "__main__"})
    finally:
        sys.argv = saved


def prep_path(scene):
    return os.path.join(OUT, "prep", f"{int(scene):02d}", "lookdev.json")


def setup(materials=True, scenes=(1, 3, 7, 9, 10, 13, 15)):
    """The prep a visual round does before its renders, in this editor:
    scripts/ue_create_materials.py (all of /Game/FlightSim's generated
    materials) and scripts/ue_import_aircraft.py for every manifest the
    prepared scenes name. Run prepare.py (host) first."""
    if materials:
        _run_script(os.path.join(REPO, "scripts", "ue_create_materials.py"))
    manifests = []
    for scene in scenes:
        if os.path.isfile(prep_path(scene)):
            with open(prep_path(scene), encoding="utf-8") as handle:
                manifests += json.load(handle).get("import_manifests", [])
    manifests = list(dict.fromkeys(manifests))
    if manifests:
        _run_script(os.path.join(REPO, "scripts", "ue_import_aircraft.py"), manifests)
    return {"materials": materials, "aircraft": manifests}


def build(scene):
    """A blank (unsaved, transient) editor map, then the scene's beauty set-up
    in it; the level viewport is moved to the beauty camera."""
    path = prep_path(scene)
    if not os.path.isfile(path):
        raise RuntimeError(f"lookdev: {path} missing; run scripts/lookdev/prepare.py {scene}")
    _console("FlightSim.LookDev.Clear")
    unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    _console(f"FlightSim.LookDev.Build {path}")
    status = _status(path)
    loc = status.get("camera_location_cm")
    rot = status.get("camera_rotation_pyr")
    if loc and rot:
        unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(
            unreal.Vector(*loc), unreal.Rotator(roll=rot[2], pitch=rot[0], yaw=rot[1]))
    return status


def capture(scene, tag, width=1280, height=720):
    """Start <OUT>/<tag>/<scene>.png from the beauty camera of the scene last
    built (build(scene) first). Returns at once: the editor has to keep
    ticking for Cesium to stream, so the still is written by an editor ticker
    and <png>.status.json appears when it is (read it with status(png))."""
    png = os.path.join(OUT, tag, f"{int(scene)}.png")
    os.makedirs(os.path.dirname(png), exist_ok=True)
    _console(f"FlightSim.LookDev.Capture {png} {int(width)} {int(height)}")
    return {"pending": png}


def status(png):
    """The finished capture's status (raises if it failed or is not done)."""
    return _status(png)
