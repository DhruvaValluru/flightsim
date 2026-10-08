"""Re-wire an already imported aircraft's materials to its MTL colours and
textures (scripts/ue_aircraft_materials.py says why). Runs inside UE:

    UnrealEditor-Cmd <project> -run=pythonscript \
        -script="scripts/ue_fix_aircraft_materials.py B747 [A320 ...]"

Every line also goes to runs/fix_aircraft_materials.txt (a commandlet's
console shows nothing quieter than a warning).
"""

import os
import sys

import unreal

_SCRIPT = globals().get("__file__") or sys.argv[0]
SCRIPTS = os.path.dirname(os.path.abspath(_SCRIPT))
REPO = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from ue_aircraft_materials import fix_materials  # noqa: E402

REPORT = os.path.join(REPO, "runs", "fix_aircraft_materials.txt")
os.makedirs(os.path.dirname(REPORT), exist_ok=True)
open(REPORT, "w", encoding="utf-8").close()


def say(text):
    line = f"MATERIALS {text}"
    unreal.log_warning(line)
    with open(REPORT, "a", encoding="utf-8") as out:
        out.write(line + "\n")


failed = False
for aircraft in sys.argv[1:] or ["B747"]:
    mtl_dir = os.path.join(REPO, "assets", "generated", aircraft)
    if not os.path.isdir(mtl_dir):
        say(f"{aircraft}: no converted model at {mtl_dir}")
        failed = True
        continue
    try:
        fixed, problems = fix_materials(f"/Game/Aircraft/{aircraft}", mtl_dir, say)
    except Exception as exc:
        say(f"{aircraft}: failed: {exc!r}")
        failed = True
        continue
    for problem in problems:
        say(f"{aircraft}: PROBLEM {problem}")
    say(f"{aircraft}: {fixed} material(s) set, {len(problems)} problem(s)")
    failed = failed or bool(problems)

if failed:
    raise SystemExit(1)
