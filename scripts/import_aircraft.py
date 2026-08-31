"""Real aircraft models, one command, any OS: fetch -> convert -> import.

    .venv/bin/python scripts/import_aircraft.py            # every configured aircraft
    .venv/bin/python scripts/import_aircraft.py c172p B747 # just these
    .venv/bin/python scripts/import_aircraft.py --no-import  # skip the UE step

Placeholder airframes never render (owner's rule, extended 2026-08-31:
on ANY machine -- "always use a real model"), so a fresh machine must be
one command from real models. Per aircraft config under
assets/aircraft_config/ this:

1. fetches the FlightGear model source at the config's PINNED commit
   into assets/aircraft_src/ (the license file is verified on disk by
   the converter, per section 3.3 -- nothing renders unattributed);
2. runs assets_pipeline/convert.py -- per-part OBJs + mesh_manifest.json
   under assets/generated/, refusing any mesh/FDM mismatch (section 1.4);
3. imports every produced manifest into the Unreal project in ONE
   editor invocation (scripts/ue_import_aircraft.py inside
   UnrealEditor-Cmd), which re-verifies each imported mesh's bounds.

Steps already done are skipped, so re-running is safe. --no-import stops
after (2) for machines without the engine.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.util.platform import ue_editor_path  # noqa: E402


def fetch_source(config: dict, config_path: Path) -> Path:
    """The model repo at the PINNED commit -- shallow, verified, idempotent."""
    source_dir = (config_path.parent / config["source_dir"]).resolve()
    repo_url = config["license"]["repo"]
    commit = config["license"]["commit"]
    head = source_dir / ".git"
    if head.is_dir():
        actual = subprocess.run(["git", "-C", str(source_dir), "rev-parse",
                                 "HEAD"], capture_output=True, text=True)
        if actual.returncode == 0 and actual.stdout.strip() == commit:
            print(f"    source already at {commit[:12]}")
            return source_dir
        print(f"    source present but not at the pinned commit; re-fetching")
    source_dir.mkdir(parents=True, exist_ok=True)
    if not head.is_dir():
        subprocess.run(["git", "init", "-q", str(source_dir)], check=True)
        subprocess.run(["git", "-C", str(source_dir), "remote", "add",
                        "origin", repo_url], check=True)
    print(f"    fetching {repo_url} @ {commit[:12]} (shallow)")
    fetched = subprocess.run(["git", "-C", str(source_dir), "fetch",
                              "--depth", "1", "origin", commit])
    if fetched.returncode != 0:
        # A host that refuses arbitrary-SHA shallow fetches gets the full
        # history instead; the checkout below still pins the commit.
        print("    shallow fetch refused; fetching full history")
        subprocess.run(["git", "-C", str(source_dir), "fetch", "origin"],
                       check=True)
    subprocess.run(["git", "-C", str(source_dir), "checkout", "-q", commit],
                   check=True)
    return source_dir


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("names", nargs="*",
                    help="aircraft to build (default: every config)")
    ap.add_argument("--no-import", action="store_true",
                    help="fetch + convert only; skip the Unreal import step")
    args = ap.parse_args(argv)

    config_dir = REPO / "assets" / "aircraft_config"
    configs = {p.stem: p for p in sorted(config_dir.glob("*.json"))}
    names = args.names or sorted(configs)
    unknown = [n for n in names if n not in configs]
    if unknown:
        print(f"no config for: {', '.join(unknown)} -- "
              f"configured: {', '.join(sorted(configs))}")
        return 2

    python = sys.executable
    manifests = []
    failed = []
    skipped = []
    for name in names:
        print(f"  {name}")
        config_path = configs[name]
        config = json.loads(config_path.read_text(encoding="utf-8"))
        # Section 3.3: an airframe whose upstream ships no license file
        # cannot render at all, and says so ONCE here rather than dying
        # at the guard on every run.
        unavailable = config["license"].get("unavailable")
        if unavailable:
            print(f"    SKIPPED -- {unavailable}")
            skipped.append(name)
            continue
        manifest = (REPO / "assets" / "generated" / config["name"]
                    / "mesh_manifest.json")
        if manifest.is_file():
            print(f"    already converted ({manifest.relative_to(REPO)})")
            manifests.append(manifest)
            continue
        try:
            fetch_source(config, config_path)
        except subprocess.CalledProcessError as exc:
            print(f"    FETCH FAILED ({exc}) -- continuing with the rest")
            failed.append(name)
            continue
        print(f"    converting (license-verified, FDM-matched)")
        converted = subprocess.run(
            [python, str(REPO / "assets_pipeline" / "convert.py"),
             str(config_path)], cwd=REPO)
        # One aircraft's failure must not cost the others their fetch and
        # convert: report it at the end, by name, and keep going.
        if converted.returncode != 0 or not manifest.is_file():
            print(f"    CONVERT FAILED for {name} -- continuing with the rest")
            failed.append(name)
            continue
        manifests.append(manifest)

    def summary() -> None:
        if skipped:
            print(f"\nskipped (no upstream license, section 3.3): "
                  f"{', '.join(skipped)}")
        if failed:
            print(f"FAILED: {', '.join(failed)} -- scroll up for each "
                  f"reason; the rest are unaffected")

    if not manifests:
        print("\nnothing converted.")
        summary()
        return 1

    if args.no_import:
        print("\nConverted. Import later with the same command, minus "
              "--no-import.")
        summary()
        return 1 if failed else 0

    editor = ue_editor_path()
    if editor is None or not editor.is_file():
        print(f"\nno UnrealEditor-Cmd at {editor} (set UE_ROOT, or use "
              f"--no-import on a machine without the engine)")
        return 1
    # One editor invocation for every manifest: ue_import_aircraft.py
    # re-verifies each imported mesh by loading it back (empty-import
    # protection), and fails THERE, not at render time.
    script_arg = " ".join([str(REPO / "scripts" / "ue_import_aircraft.py")]
                          + [str(m) for m in manifests])
    print(f"\n  importing {len(manifests)} aircraft into the Unreal project")
    imported = subprocess.run(
        [str(editor), str(REPO / "ue" / "FlightSim.uproject"),
         "-run=pythonscript", f"-script={script_arg}",
         "-unattended", "-nopause", "-nosplash", "-stdout"], cwd=REPO)
    if imported.returncode != 0:
        print(f"import FAILED ({imported.returncode}) -- scroll up for the "
              f"editor's error")
        return imported.returncode
    print(f"\nImported {len(manifests)} aircraft. Renders now use the real "
          f"models; aircraft without one refuse by name instead of showing "
          f"placeholders.")
    summary()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
