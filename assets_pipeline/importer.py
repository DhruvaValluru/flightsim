"""Real aircraft models as a FAIL-SAFE, shared by the command and the app.

Placeholder airframes never render (owner's rule 2026-08-14, extended
2026-08-31: on ANY machine). Until now the consequence of that rule was
a refusal that handed the user a command to run -- one command per fresh
machine, and the render they asked for lost. That is the same shape the
terrain fail-safe already rejected: a prerequisite the system can
produce itself should not be homework (user request 2026-09-01, "i cant
run commands for every single mesh they should upload by themselves").

So the provisioning lives here, callable two ways with identical steps
and identical verification:

* scripts/import_aircraft.py -- the explicit command, printing progress;
* the webapp's render flow -- the automatic one-time provisioning,
  reporting the same progress as run status lines.

The steps, per aircraft, each skipped when already done:

1. fetch the FlightGear model source at the config's PINNED commit into
   assets/aircraft_src/ (the license file is verified on disk by the
   converter, per VALIDITY 3.3 -- nothing renders unattributed);
2. convert -- per-part OBJs + mesh_manifest.json under assets/generated/,
   refusing any mesh/FDM mismatch (VALIDITY 1.4);
3. import the manifest into the Unreal project inside UnrealEditor-Cmd
   (scripts/ue_import_aircraft.py), which re-verifies each imported
   mesh's bounds.

WHAT AUTOMATION MAY NOT DO. Two refusals survive it untouched, because
no amount of running commands can satisfy them:

* an aircraft with no config has nothing to fetch (`aircraft.mesh`);
* an aircraft whose upstream ships no license file may never render at
  all (`aircraft.mesh`, VALIDITY 3.3) -- p51d today. This module refuses
  such an airframe BEFORE any fetch, so automation cannot become the
  path by which unattributed geometry reaches a frame.

And a failure at any step is a named failure, never a fall-through: the
caller hears `aircraft.mesh_import` with the step that failed. Nothing
here ever substitutes a different airframe or a placeholder.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO / "assets" / "aircraft_config"
GENERATED = REPO / "assets" / "generated"

#: Progress sink: called with one human-readable line per step.
Report = Callable[[str], None]


class AircraftAssetError(RuntimeError):
    """A NAMED asset failure -- constraint plus message, like every other
    refusal in this system. Raised instead of returning a falsy value so
    a caller cannot accidentally continue into a placeholder render."""

    def __init__(self, constraint: str, message: str) -> None:
        super().__init__(message)
        self.constraint = constraint
        self.message = message


def configured_aircraft() -> Dict[str, Path]:
    """name -> config path, for every airframe this repo knows how to build."""
    return {p.stem: p for p in sorted(CONFIG_DIR.glob("*.json"))}


def load_config(name: str) -> Optional[Dict]:
    path = configured_aircraft().get(name)
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def unavailable_reason(name: str) -> Optional[str]:
    """VALIDITY 3.3: upstream ships no license file, so this airframe can
    never render -- stated once in its config, honoured everywhere."""
    config = load_config(name)
    if config is None:
        return None
    return config["license"].get("unavailable") or None


def mesh_manifest_path(name: str) -> Path:
    return GENERATED / name / "mesh_manifest.json"


def missing_assets(manifest_path: Path) -> List[str]:
    """Which of a manifest's parts have no .uasset in the Unreal project.

    VERIFY THE ASSETS, don't trust the editor's exit code (measured
    2026-09-01: a cosmetic texture warning made a completely successful
    four-aircraft import report failure). Empty list == imported.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # /Game/Aircraft/<name> is ue/Content/Aircraft/<name> on disk.
    root = manifest["asset_path_root"].replace("/Game/", "", 1)
    content = REPO / "ue" / "Content"
    return [f"{manifest['name']}/{part}" for part in manifest["parts"]
            if not (content / root / f"{part}.uasset").is_file()]


def is_converted(name: str) -> bool:
    return mesh_manifest_path(name).is_file()


def is_imported(name: str) -> bool:
    """Converted AND present in the Unreal project. Both halves matter:
    a manifest with no .uasset behind it renders nothing real."""
    manifest = mesh_manifest_path(name)
    return manifest.is_file() and not missing_assets(manifest)


def fetch_source(config: Dict, config_path: Path,
                 report: Report = print) -> Path:
    """The model repo at the PINNED commit -- shallow, verified, idempotent."""
    source_dir = (config_path.parent / config["source_dir"]).resolve()
    repo_url = config["license"]["repo"]
    commit = config["license"]["commit"]
    head = source_dir / ".git"
    if head.is_dir():
        actual = subprocess.run(["git", "-C", str(source_dir), "rev-parse",
                                 "HEAD"], capture_output=True, text=True)
        if actual.returncode == 0 and actual.stdout.strip() == commit:
            report(f"source already at {commit[:12]}")
            return source_dir
        report("source present but not at the pinned commit; re-fetching")
    source_dir.mkdir(parents=True, exist_ok=True)
    if not head.is_dir():
        subprocess.run(["git", "init", "-q", str(source_dir)], check=True)
        subprocess.run(["git", "-C", str(source_dir), "remote", "add",
                        "origin", repo_url], check=True)
    report(f"fetching {repo_url} @ {commit[:12]} (shallow)")
    fetched = subprocess.run(["git", "-C", str(source_dir), "fetch",
                              "--depth", "1", "origin", commit])
    if fetched.returncode != 0:
        # A host that refuses arbitrary-SHA shallow fetches gets the full
        # history instead; the checkout below still pins the commit.
        report("shallow fetch refused; fetching full history")
        subprocess.run(["git", "-C", str(source_dir), "fetch", "origin"],
                       check=True)
    subprocess.run(["git", "-C", str(source_dir), "checkout", "-q", commit],
                   check=True)
    return source_dir


def convert(config_path: Path, report: Report = print) -> Path:
    """Source tree -> per-part OBJs + manifest. Raises if nothing lands."""
    name = config_path.stem
    report("converting (license-verified, FDM-matched)")
    converted = subprocess.run(
        [sys.executable, str(REPO / "assets_pipeline" / "convert.py"),
         str(config_path)], cwd=REPO)
    manifest = mesh_manifest_path(name)
    if converted.returncode != 0 or not manifest.is_file():
        raise AircraftAssetError(
            "aircraft.mesh_import",
            f"converting the {name} model failed (exit "
            f"{converted.returncode}); see the server log for the "
            f"converter's own reason -- a mesh/FDM mismatch and a missing "
            f"license both refuse here by design")
    return manifest


def import_manifests(manifests: List[Path], report: Report = print) -> None:
    """ONE editor invocation for every manifest, then verify the assets.

    ue_import_aircraft.py re-verifies each imported mesh by loading it
    back (empty-import protection) and fails THERE, not at render time.
    """
    from core.util.platform import ue_editor_path

    editor = ue_editor_path()
    if editor is None or not Path(editor).is_file():
        raise AircraftAssetError(
            "aircraft.mesh_import",
            f"no UnrealEditor-Cmd at {editor} -- set UE_ROOT, or convert "
            f"only (scripts/import_aircraft.py --no-import) on a machine "
            f"without the engine")
    # FORWARD SLASHES, always. UE parses the -script= value through its
    # own string unescaping, so a Windows path eats "\u" as an escape:
    # measured 2026-09-01, "scripts\ue_import_aircraft.py" reached the
    # engine as "scripts_import_aircraft.py" and could not be loaded.
    script_arg = " ".join(
        [(REPO / "scripts" / "ue_import_aircraft.py").as_posix()]
        + [Path(m).as_posix() for m in manifests])
    report(f"importing {len(manifests)} aircraft into the Unreal project")
    imported = subprocess.run(
        [str(editor), str(REPO / "ue" / "FlightSim.uproject"),
         "-run=pythonscript", f"-script={script_arg}",
         "-unattended", "-nopause", "-nosplash", "-stdout"], cwd=REPO)

    missing: List[str] = []
    for manifest_path in manifests:
        missing += missing_assets(Path(manifest_path))
    if missing:
        raise AircraftAssetError(
            "aircraft.mesh_import",
            f"the editor ran (exit {imported.returncode}) but these assets "
            f"are not on disk afterwards: {', '.join(missing[:12])}"
            + (" ..." if len(missing) > 12 else "")
            + " -- see the editor's output in the server log")
    if imported.returncode != 0:
        report(f"(the editor exited {imported.returncode}, but every "
               f"expected asset is on disk -- engine-level warnings, not "
               f"an import failure)")


def ensure_model(name: str, report: Report = print) -> Path:
    """The fail-safe: whatever step is missing for `name`, do it now.

    Idempotent -- an aircraft already converted and imported returns its
    manifest without touching the network or the editor. Raises
    AircraftAssetError (named) rather than ever returning a path that is
    not backed by real, licensed, verified geometry.
    """
    reason = unavailable_reason(name)
    if reason:
        # BEFORE any fetch: automation must not become the path by which
        # unattributed geometry reaches a frame.
        raise AircraftAssetError(
            "aircraft.mesh",
            f"the {name} can never render: {reason}")
    config_path = configured_aircraft().get(name)
    if config_path is None:
        raise AircraftAssetError(
            "aircraft.mesh",
            f"no model config for the {name} -- configured: "
            f"{', '.join(sorted(configured_aircraft()))}")
    manifest = mesh_manifest_path(name)
    if not manifest.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        try:
            fetch_source(config, config_path, report)
        except subprocess.CalledProcessError as exc:
            raise AircraftAssetError(
                "aircraft.mesh_import",
                f"fetching the {name} model source failed ({exc}) -- the "
                f"pinned commit is fetched from the upstream model "
                f"repository, so this step needs network access") from exc
        manifest = convert(config_path, report)
    if missing_assets(manifest):
        import_manifests([manifest], report)
    return manifest
