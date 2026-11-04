"""Staleness oracle for the double-click launcher (Phase 3 E6).

    .venv\\Scripts\\python.exe scripts\\launch_check.py build
    .venv\\Scripts\\python.exe scripts\\launch_check.py materials [--stamp]
    .venv\\Scripts\\python.exe scripts\\launch_check.py aircraft

One step per call. Prints exactly one line, ``<step> up to date`` (exit 0)
or ``<step> stale (<reason>)`` (exit 1); the launcher
(scripts/launch_windows.ps1) copies the line into logs/launch.log and
runs the step's real work only on exit 1. ``materials --stamp`` records
the launcher-owned materials stamp after a clean commandlet run and
prints ``materials stamp written``.

Why a stamp for materials: the generation stamp of each material lives
INSIDE its .uasset (ue_create_materials.py graph_stale), readable only by
the editor, and starting the editor costs minutes. The launcher-owned
stamp (sha256 of scripts/ue_create_materials.py + the pinned engine
version, plus every expected asset present on disk) is the editor-free
signal the launcher's "only if missing or stale" needs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Where the launcher's materials stamp lives (ue/Saved is editor scratch,
#: git-ignored; a fresh clone has no stamp, so the first launch creates).
MATERIALS_STAMP_REL = Path("ue/Saved/launch/materials_stamp.json")
MATERIALS_ASSET_DIR = Path("ue/Content/FlightSim")
MATERIALS_SCRIPT_REL = Path("scripts/ue_create_materials.py")

#: The assets the launcher requires on disk, every one created by
#: scripts/ue_create_materials.py (A6): the render commandlet's two
#: required materials, the physical-sky three, and the storm, overlay and
#: classification materials the render path reads.
EXPECTED_MATERIALS = (
    "M_VertexColor", "M_TerrainImagery", "M_Moon", "M_StarEmissive",
    "M_TerrainImageryNight", "M_LandcoverID", "M_LensDrops", "M_GreyCard",
    "M_RainStreaks", "M_Ground_City", "M_CustomStencilID",
)

STEPS = ("build", "materials", "aircraft")


def _engine_version() -> str:
    from core.util.platform import UE_ENGINE_VERSION
    return str(UE_ENGINE_VERSION)


def materials_fingerprint(repo: Path, engine_version: Optional[str] = None) -> str:
    """sha256 of the material script's bytes followed by the engine
    version: a changed graph or a changed engine both invalidate."""
    if engine_version is None:
        engine_version = _engine_version()
    digest = hashlib.sha256()
    digest.update((Path(repo) / MATERIALS_SCRIPT_REL).read_bytes())
    digest.update(b"\n" + engine_version.encode("utf-8"))
    return digest.hexdigest()


def missing_materials(repo: Path) -> List[str]:
    folder = Path(repo) / MATERIALS_ASSET_DIR
    return [name for name in EXPECTED_MATERIALS
            if not (folder / f"{name}.uasset").is_file()]


def check_materials(repo: Path, engine_version: Optional[str] = None) -> Optional[str]:
    """None when current, else the reason: no stamp, a fingerprint that
    differs (script or engine changed), or a missing asset."""
    repo = Path(repo)
    missing = missing_materials(repo)
    if missing:
        return "missing " + ", ".join(missing)
    stamp_path = repo / MATERIALS_STAMP_REL
    if not stamp_path.is_file():
        return f"no stamp at {MATERIALS_STAMP_REL.as_posix()}"
    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
        stamped = stamp["fingerprint"]
    except (ValueError, KeyError, TypeError):
        return f"stamp unreadable at {MATERIALS_STAMP_REL.as_posix()}"
    current = materials_fingerprint(repo, engine_version)
    if stamped != current:
        return (f"stamp {stamped[:12]} differs from {current[:12]} "
                "(ue_create_materials.py or the engine changed)")
    return None


def write_materials_stamp(repo: Path, engine_version: Optional[str] = None) -> Path:
    """Record the current fingerprint; called by the launcher only after a
    commandlet run with no MATERIAL-FAILED line."""
    repo = Path(repo)
    if engine_version is None:
        engine_version = _engine_version()
    path = repo / MATERIALS_STAMP_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fingerprint": materials_fingerprint(repo, engine_version),
        "engine": engine_version,
        "script": MATERIALS_SCRIPT_REL.as_posix(),
        "materials": list(EXPECTED_MATERIALS),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def check_build(repo: Path) -> Optional[str]:
    """None when the plugin binary matches its A4 stamp, else
    binary_stale_reason's message (engine.binary_stale)."""
    from core.util.platform import binary_stale_reason
    return binary_stale_reason(Path(repo))


def check_aircraft() -> List[str]:
    """Configured aircraft (minus the licence-unavailable ones) that are
    not imported, or whose import is older than its inputs (A7)."""
    from assets_pipeline import importer
    stale = []
    for name in sorted(importer.configured_aircraft()):
        if importer.unavailable_reason(name):
            continue
        if not importer.is_imported(name) or importer.older_than_inputs_reason(name) is not None:
            stale.append(name)
    return stale


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=STEPS)
    ap.add_argument("--stamp", action="store_true",
                    help="materials only: write the launcher's stamp")
    ap.add_argument("--repo", default=str(REPO),
                    help="repository root (default: this checkout)")
    args = ap.parse_args(argv)
    repo = Path(args.repo)

    if args.step == "build":
        reason = check_build(repo)
    elif args.step == "materials":
        if args.stamp:
            write_materials_stamp(repo)
            print("materials stamp written")
            return 0
        reason = check_materials(repo)
    else:
        names = check_aircraft()
        reason = ", ".join(names) if names else None

    if reason is None:
        print(f"{args.step} up to date")
        return 0
    print(f"{args.step} stale ({reason})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
