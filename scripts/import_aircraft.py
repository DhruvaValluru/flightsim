"""Real aircraft models, one command, any OS: fetch -> convert -> import.

    .venv/bin/python scripts/import_aircraft.py            # every configured aircraft
    .venv/bin/python scripts/import_aircraft.py c172p B747 # just these
    .venv/bin/python scripts/import_aircraft.py --no-import  # skip the UE step

You do NOT have to run this to get a render: since 2026-09-01 the webapp
provisions a missing model itself on the first run that needs it (the
terrain fail-safe's pattern, with a status line), so this command is for
priming a machine ahead of time or for building several airframes at
once. Every step, and every verification, is shared with that path --
assets_pipeline/importer.py is the one implementation.

Placeholder airframes never render (owner's rule, extended 2026-08-31:
on ANY machine -- "always use a real model"). Per aircraft config under
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
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from assets_pipeline.importer import (  # noqa: E402
    AircraftAssetError, configured_aircraft, convert, fetch_source,
    import_manifests, load_config, mesh_manifest_path, unavailable_reason,
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("names", nargs="*",
                    help="aircraft to build (default: every config)")
    ap.add_argument("--no-import", action="store_true",
                    help="fetch + convert only; skip the Unreal import step")
    args = ap.parse_args(argv)

    configs = configured_aircraft()
    names = args.names or sorted(configs)
    unknown = [n for n in names if n not in configs]
    if unknown:
        print(f"no config for: {', '.join(unknown)} -- "
              f"configured: {', '.join(sorted(configs))}")
        return 2

    manifests = []
    failed = []
    skipped = []
    for name in names:
        print(f"  {name}")
        report = lambda line: print(f"    {line}")   # noqa: E731
        # Section 3.3: an airframe whose upstream ships no license file
        # cannot render at all, and says so ONCE here rather than dying
        # at the guard on every run.
        reason = unavailable_reason(name)
        if reason:
            print(f"    SKIPPED -- {reason}")
            skipped.append(name)
            continue
        manifest = mesh_manifest_path(name)
        if manifest.is_file():
            print(f"    already converted ({manifest.relative_to(REPO)})")
            manifests.append(manifest)
            continue
        # One aircraft's failure must not cost the others their fetch and
        # convert: report it at the end, by name, and keep going.
        try:
            fetch_source(load_config(name), configs[name], report)
            manifests.append(convert(configs[name], report))
        except Exception as exc:
            print(f"    FAILED for {name} ({exc}) -- continuing with the rest")
            failed.append(name)

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

    print()
    try:
        import_manifests(manifests, lambda line: print(f"  {line}"))
    except AircraftAssetError as exc:
        print(f"\nimport FAILED -- {exc.message}")
        return 1
    print(f"\nImported {len(manifests)} aircraft. Renders now use the real "
          f"models; aircraft without one refuse by name instead of showing "
          f"placeholders.")
    summary()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
