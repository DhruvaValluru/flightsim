"""The engine a build used, and whether the built binary is today's source.

Phase 3 A3 and A4 (tasks/phase3_todo.md). The Windows review of 24-25
October found two silent failures on the Unreal side:

* R1 -- a machine with another engine built (or tried to) against it,
  because ``scripts/build_ue.ps1`` fell back to "the newest UE_5.* found".
  A3: the build and every render read ``Engine/Build/Build.version`` and
  refuse ``engine.version_mismatch`` unless it is the pinned patch
  (``UE_ENGINE_PATCH``, docs/TOOLCHAIN.md).
* R4 -- a September binary drew the frames because nothing checked that
  the plugin DLL was built from the current source. A4: a successful build
  writes ``build_stamp.json`` beside the binaries (the engine it built
  against and a hash of every source file UnrealBuildTool compiles); before
  any render, a missing stamp, a stamp from another engine, or a stamp
  whose hash is not today's source refuses ``engine.binary_stale`` and
  names both hashes.

``scripts/build_ue.ps1`` (and ``build_ue.sh``) call ``write`` after a
successful build; ``scripts/ue_preflight.ps1`` and the launcher (E6) call
``check``. One implementation, so the build and the render can never
disagree on what "current" means.

    python -m core.util.build_stamp write [--ue-root PATH]
    python -m core.util.build_stamp check [--ue-root PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

REPO = Path(__file__).resolve().parents[2]

#: Where the stamp lives: beside the plugin's built binaries, which git
#: ignores, so a fresh clone has no stamp and refuses until it is built.
STAMP_RELATIVE = Path("ue/Plugins/FlightSimBridge/Binaries/build_stamp.json")

#: Every tree UnrealBuildTool compiles into the editor the render runs:
#: the game module, the bridge plugin and the vendored JSBSim plugin.
SOURCE_ROOTS = (
    Path("ue/Source"),
    Path("ue/Plugins/FlightSimBridge/Source"),
    Path("ue/Plugins/JSBSimFlightDynamicsModel/Source"),
)

#: Files outside the source roots whose change also changes the build.
BUILD_FILES = (
    Path("ue/FlightSim.uproject"),
    Path("ue/Plugins/FlightSimBridge/FlightSimBridge.uplugin"),
    Path("ue/Plugins/JSBSimFlightDynamicsModel/JSBSimFlightDynamicsModel.uplugin"),
)

#: What counts as source. The vendored plugin also carries a prebuilt
#: JSBSim.dll/.lib under Source/ThirdParty; those are inputs vendored by
#: scripts/vendor_ue_plugin.ps1, tracked by VENDORED.json, and hashing
#: tens of MB of binaries on every render buys nothing the headers miss.
SOURCE_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".cs", ".h", ".hh",
                             ".hpp", ".inl", ".ini"})

STAMP_VERSION = 1


def stamp_path(repo: Path = REPO) -> Path:
    return repo / STAMP_RELATIVE


def _source_files(repo: Path) -> Iterable[Path]:
    for root in SOURCE_ROOTS:
        base = repo / root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES:
                yield path
    for rel in BUILD_FILES:
        path = repo / rel
        if path.is_file():
            yield path


def source_hash(repo: Path = REPO) -> str:
    """SHA-256 over every compiled source file: its repo-relative path
    (forward slashes) and its bytes with CRLF folded to LF, in sorted path
    order. Line endings are folded because git's autocrlf rewrites them on
    Windows checkouts; the code the compiler sees is the same either way."""
    digest = hashlib.sha256()
    files = sorted(_source_files(repo),
                   key=lambda p: p.relative_to(repo).as_posix())
    for path in files:
        rel = path.relative_to(repo).as_posix()
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()


def engine_build_version(ue_root: Optional[Path]) -> Optional[Dict[str, str]]:
    """``{"version": "5.7.4", "changelist": "..."}`` from
    ``<UE_ROOT>/Engine/Build/Build.version``, or None when there is no
    readable file there."""
    if ue_root is None:
        return None
    path = Path(ue_root) / "Engine" / "Build" / "Build.version"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        version = (f"{int(data['MajorVersion'])}.{int(data['MinorVersion'])}."
                   f"{int(data['PatchVersion'])}")
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return {"version": version, "changelist": str(data.get("Changelist", ""))}


def version_refusal(ue_root: Optional[Path]) -> Optional[Dict[str, str]]:
    """``engine.version_mismatch`` unless the engine at ``ue_root`` is the
    pinned patch; None when it is."""
    from core.util.platform import UE_ENGINE_PATCH

    found = engine_build_version(ue_root)
    if found is not None and found["version"] == UE_ENGINE_PATCH:
        return None
    seen = found["version"] if found else "no readable Engine/Build/Build.version"
    return {
        "constraint": "engine.version_mismatch",
        "message": (f"engine.version_mismatch: found {seen}, pinned "
                    f"{UE_ENGINE_PATCH} (at {ue_root}). Every machine builds "
                    f"and renders with Unreal Engine {UE_ENGINE_PATCH} "
                    f"(docs/TOOLCHAIN.md): install it from the Epic Games "
                    f"Launcher, or point UE_ROOT at that install."),
    }


def write_stamp(repo: Path = REPO, ue_root: Optional[Path] = None) -> Dict:
    """Record the engine and the source hash after a successful build.
    Refuses (ValueError) to stamp a build made with an unpinned engine."""
    if ue_root is None:
        from core.util.platform import find_ue_root
        ue_root = find_ue_root()
    refusal = version_refusal(ue_root)
    if refusal is not None:
        raise ValueError(refusal["message"])
    engine = engine_build_version(ue_root)
    stamp = {
        "stamp_version": STAMP_VERSION,
        "engine_version": engine["version"],
        "engine_changelist": engine["changelist"],
        "source_sha256": source_hash(repo),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path = stamp_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
    return stamp


def read_stamp(repo: Path = REPO) -> Optional[Dict]:
    try:
        return json.loads(stamp_path(repo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def stale_refusal(repo: Path = REPO,
                  ue_root: Optional[Path] = None) -> Optional[Dict[str, str]]:
    """``engine.binary_stale`` unless the stamp names this engine and
    today's source; None when the binary is current."""
    current = source_hash(repo)
    stamp = read_stamp(repo)
    rebuild = ("Rebuild with scripts\\build_ue.ps1 (the launcher does this "
               "itself when the stamp does not match).")
    if not stamp or "source_sha256" not in stamp:
        return {"constraint": "engine.binary_stale",
                "message": (f"engine.binary_stale: no build stamp at "
                            f"{STAMP_RELATIVE.as_posix()}, so nothing shows "
                            f"the plugin binary was built from the current "
                            f"source (current {current[:12]}). {rebuild}")}
    if stamp["source_sha256"] != current:
        return {"constraint": "engine.binary_stale",
                "message": (f"engine.binary_stale: the plugin binary was "
                            f"built from source {stamp['source_sha256'][:12]}, "
                            f"but the source is now {current[:12]}; an old "
                            f"binary would draw the frames. {rebuild}")}
    if ue_root is not None:
        engine = engine_build_version(ue_root)
        if engine is not None and engine["version"] != stamp.get("engine_version"):
            return {"constraint": "engine.binary_stale",
                    "message": (f"engine.binary_stale: the plugin binary was "
                                f"built against Unreal Engine "
                                f"{stamp.get('engine_version')}, but this "
                                f"engine is {engine['version']}. {rebuild}")}
    return None


def render_refusal(repo: Path = REPO,
                   ue_root: Optional[Path] = None) -> Optional[Dict[str, str]]:
    """The first reason the engine half must not draw frames on this
    machine -- the wrong engine (A3), then an outdated binary (A4) -- or
    None. Called before any flight wherever a render is about to start."""
    if ue_root is None:
        from core.util.platform import find_ue_root
        ue_root = find_ue_root()
    return version_refusal(ue_root) or stale_refusal(repo, ue_root)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("write", "check"))
    parser.add_argument("--ue-root", type=Path, default=None,
                        help="engine install (default: UE_ROOT or the pinned path)")
    args = parser.parse_args(argv)
    if args.action == "write":
        try:
            stamp = write_stamp(REPO, args.ue_root)
        except ValueError as exc:
            print(f"REFUSED -- {exc}")
            return 2
        print(f"build stamp written: UE {stamp['engine_version']}, "
              f"source {stamp['source_sha256'][:12]}")
        return 0
    refusal = render_refusal(REPO, args.ue_root)
    if refusal is not None:
        print(f"REFUSED -- {refusal['message']}")
        return 2
    print(f"OK build stamp current (source {source_hash(REPO)[:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
