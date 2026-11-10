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
   refusing any mesh/FDM mismatch (VALIDITY 1.4); a manifest older than
   version 3 (version 1: no ``mesh_origin_actor_cm``, the mesh would be
   attached at the structural datum, 25-30 m off its label; version 2:
   an origin ASSUMED from the staged FDM's VRP, 3.9 m off on the B747
   and 19.3 m on the A320, where version 3 MEASURES it from the
   vertices) is NOT converted and is re-converted here, geometry
   unchanged, no editor time;
3. import the manifest into the Unreal project inside UnrealEditor-Cmd
   (scripts/ue_import_aircraft.py), which re-verifies each imported
   mesh's bounds.

WHAT AUTOMATION MAY NOT DO. Two refusals survive it untouched, because
no amount of running commands can satisfy them:

* an aircraft with no config has nothing to fetch (`aircraft.mesh`);
* an aircraft whose upstream ships no license file may never render at
  all (`aircraft.mesh`, VALIDITY 3.3). This module refuses
  such an airframe BEFORE any fetch, so automation cannot become the
  path by which unattributed geometry reaches a frame.

And a failure at any step is a named failure, never a fall-through: the
caller hears `aircraft.mesh_import` with the step that failed. Nothing
here ever substitutes a different airframe or a placeholder.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from assets_pipeline.obj_frame import OBJ_FRAME, OBJ_FRAME_KEY

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


def imported_parts(manifest: Dict) -> List[str]:
    """Every mesh asset a manifest puts in the project: its ``parts`` (the
    meshes the commandlet attaches and every measure frame draws) and the
    beauty-only copies of ``beauty_parts`` (round 2, cockpit-airframe:
    ``body_beauty``, swapped in on -quality=beauty only)."""
    return list(manifest["parts"]) + [
        row["part"] for row in (manifest.get("beauty_parts") or {}).values()]


#: Written by scripts/ue_aircraft_materials.py write_import_record after
#: an import of a manifest with ``beauty_parts`` (same names there, pinned
#: by tests/test_cockpit_airframe.py): the manifest's sha256 and every
#: imported mesh slot's material.
IMPORT_RECORD_NAME = "import_record.json"
IMPORT_RECORD_MAGIC = "flightsim-aircraft-import-record"


def import_record_reason(manifest_path: Path) -> Optional[str]:
    """Why a manifest with ``beauty_parts`` is not imported yet, or None.

    Round 2 (cockpit-airframe lane). The render machine's first J-11 frames
    (2026-11-09) drew a grey, untextured airframe: 7 slots on look
    instances and one on WorldGridMaterial where the converted body has 25
    MTL materials. The re-import had run in a render the harness reaped
    for low memory, and every rule here is by mtime and file presence, so
    an import cut short after the body's .uasset was saved counted as
    done. The import script now writes a record only when it reaches the
    end; a missing record, or one written for another manifest, means the
    editor import must run again. Only manifests with ``beauty_parts``: no
    other airframe is re-imported by this rule."""
    manifest_path = Path(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not manifest.get("beauty_parts"):
        return None
    record_path = manifest_path.parent / IMPORT_RECORD_NAME
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"no import record at {record_path} (the editor import never finished)"
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if record.get("magic") != IMPORT_RECORD_MAGIC or record.get("manifest_sha256") != digest:
        return (f"the import record {record_path.name} was written for another "
                f"conversion of the mesh")
    if record.get("unbound"):
        # Imported again on the next render, and refused by name again
        # (import_manifests), rather than drawn grey.
        return (f"the last import left {len(record['unbound'])} mesh slot(s) without "
                f"their MTL material")
    return None


def unbound_slots(manifest_path: Path) -> List[str]:
    """The unbound slots of the import record written for THIS manifest
    (empty when there is none, or it was written for another conversion)."""
    manifest_path = Path(manifest_path)
    record_path = manifest_path.parent / IMPORT_RECORD_NAME
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    except (OSError, ValueError):
        return []
    if record.get("magic") != IMPORT_RECORD_MAGIC or record.get("manifest_sha256") != digest:
        return []
    return [str(row) for row in record.get("unbound") or []]


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
    return [f"{manifest['name']}/{part}" for part in imported_parts(manifest)
            if not (content / root / f"{part}.uasset").is_file()]


def stale_assets(manifest_path: Path) -> List[str]:
    """Which of a manifest's parts have a .uasset OLDER than the manifest.

    A re-convert writes new OBJs and a new manifest; the editor's import
    is what carries them into the project. Measured 2026-11-04 (packet
    C4-2): after decision 19 re-wrote every A-4 OBJ right-handed, the
    manifest was current and the .uassets present, so the import was
    skipped and the editor kept drawing the old mirrored asset against the
    new hulls. An asset older than its manifest is therefore not imported.
    Empty list == every present asset is at least as new as the manifest.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest["asset_path_root"].replace("/Game/", "", 1)
    content = REPO / "ue" / "Content"
    since = manifest_path.stat().st_mtime
    return [f"{manifest['name']}/{part}" for part in imported_parts(manifest)
            if (content / root / f"{part}.uasset").is_file()
            and (content / root / f"{part}.uasset").stat().st_mtime < since]


#: The manifest version the render commandlet needs to place the mesh
#: where the label is. Version 1 carried no ``mesh_origin_actor_cm``, so
#: the commandlet attached the body at the actor root -- the JSBSim
#: structural datum -- and drew the B747 33.7 m forward of its label
#: (the Camera Phase 1 initial run report measured 25-30 m along the
#: airframe's own axis). Version 2 (eb5c71d) carried an origin ASSUMED
#: to be the staged FDM's VRP, which put the B747 mesh 3.9 m aft of its
#: label and the A320 19.3 m aft (measured from the pinned vertices:
#: each FlightGear mesh was modelled against its own repository's FDM,
#: not the staged one). Version 3 MEASURES the origin from the mesh's
#: nose extreme and lowest gear vertex. Kept as a number here, not
#: imported from the converter, so a machine that only IMPORTS can still
#: tell a stale manifest from a current one.
MESH_MANIFEST_VERSION = 3

#: The version an airframe WITH a default loadout (``loading.loadout`` in
#: its config) must reach: its converter (``a4_mdl_convert``) writes the
#: loaded stations as ``components[]``, one OBJ each. A manifest below it
#: draws the airframe clean while the FDM carries the stores. Airframes
#: without a loadout stay at ``MESH_MANIFEST_VERSION``.
COMPONENTS_MANIFEST_VERSION = 4


def stale_manifest_reason(manifest_path: Path) -> Optional[str]:
    """Why an existing manifest must be re-converted, or None when it is
    current. A manifest without ``version`` 3 or without
    ``mesh_origin_actor_cm`` was written by a converter that either said
    nothing about where the model origin sits in the actor (version 1:
    the commandlet would attach its mesh at the structural datum and
    every mask would be offset by the whole origin-to-CG distance) or
    assumed it from the staged FDM's VRP (version 2: the mesh drawn
    3.9 m aft of its label on the B747, 19.3 m on the A320). Version 3
    measures it from the vertices."""
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"unreadable ({exc})"
    version = manifest.get("version")
    if not isinstance(version, int) or version < MESH_MANIFEST_VERSION:
        if isinstance(version, int) and version >= 2:
            return (f"manifest version {version!r} predates {MESH_MANIFEST_VERSION}: "
                    f"its mesh origin was assumed from the staged FDM's VRP, "
                    f"not measured from the vertices (3.9 m off on the B747, "
                    f"19.3 m on the A320), so the mesh would be drawn off its "
                    f"label")
        return (f"manifest version {version!r} predates {MESH_MANIFEST_VERSION}: "
                f"it records no mesh origin, so the mesh would be attached "
                f"at the structural datum instead of where the vertices "
                f"say the model origin sits")
    origin = manifest.get("mesh_origin_actor_cm")
    if (not isinstance(origin, list) or len(origin) != 3
            or not all(isinstance(v, (int, float)) for v in origin)):
        return (f"manifest version {version} carries no mesh_origin_actor_cm "
                f"(got {origin!r}); the mesh would be attached at the "
                f"structural datum")
    # Decision 19: an OBJ written in the UE left-handed actor frame is
    # mirrored by Unreal's right-handed OBJ import (the A-4's port store
    # drew to starboard), so a conversion without the exact stamp of the
    # current OBJ frame is re-converted and re-imported, every airframe.
    if manifest.get(OBJ_FRAME_KEY) != OBJ_FRAME:
        return (f"manifest version {version} carries no {OBJ_FRAME_KEY} "
                f"{OBJ_FRAME!r} (got {manifest.get(OBJ_FRAME_KEY)!r}): its OBJs "
                f"were written in the UE left-handed actor frame, which the "
                f"Interchange OBJ import mirrors, so the imported asset is a "
                f"mirror image of the manifest's frame (decision 19)")
    components = _missing_components_reason(manifest, version)
    if components:
        return components
    package = _package_pins_reason(manifest)
    if package:
        return package
    return _unimportable_output_reason(Path(manifest_path), manifest)


def _package_pins_reason(manifest: Dict) -> Optional[str]:
    """Stale when the airframe's config pins package files (j11-package
    lane: the livery, cockpit interior and pilot) that the manifest was
    not converted from: a conversion from before the pins draws the
    airframe without them, so it is converted and imported again (no
    fetch when the source is already at the pinned commit)."""
    name = manifest.get("name")
    config = load_config(name) if isinstance(name, str) else None
    pins = (config or {}).get("package_files") or []
    if not pins:
        return None
    wanted = {(row.get("file"), row.get("sha256")) for row in pins}
    have = {(row.get("file"), row.get("sha256")) for row in manifest.get("package_files") or []}
    if wanted != have:
        return (f"the {name} config pins {len(wanted)} package file(s) "
                f"(livery, cockpit interior, pilot) the manifest was not "
                f"converted from ({len(wanted - have)} missing or changed)")
    return None


def _missing_components_reason(manifest: Dict, version: int) -> Optional[str]:
    """Stale when the airframe's config states a default loadout
    (``loading.loadout``, the A-4) but the manifest predates
    ``COMPONENTS_MANIFEST_VERSION`` or carries no ``components`` list: the
    render would draw a clean airframe while the FDM flies the stores.
    An airframe whose config has no loadout is never stale for this."""
    name = manifest.get("name")
    config = load_config(name) if isinstance(name, str) else None
    loadout = ((config or {}).get("loading") or {}).get("loadout")
    if not loadout:
        return None
    if version < COMPONENTS_MANIFEST_VERSION or "components" not in manifest:
        stations = ", ".join(sorted((loadout.get("model_vars") or {}).keys())) or "?"
        return (f"manifest version {version} of the {name} carries no "
                f"components[] while its config states a default loadout "
                f"({stations}); the loaded stations would not be drawn "
                f"(needs version {COMPONENTS_MANIFEST_VERSION})")
    return None


def _png_size(path: Path) -> Optional[tuple]:
    """(width, height) from a PNG's IHDR, or None when it is not a PNG."""
    with path.open("rb") as handle:
        head = handle.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def _unimportable_output_reason(manifest_path: Path,
                                manifest: Dict) -> Optional[str]:
    """Converter output the Unreal import is measured to fail on.

    Measured 2026-10-05 (UE 5.7, the A320): Interchange refused a
    non-power-of-two texture, and renamed every "tex_<stem>" material
    because it names the texture asset "TEX_<stem>" (asset names are
    case-insensitive) -- after which the import commandlet asserted in
    the content browser and every part still queued was lost. The
    converter now writes neither; this sends an earlier conversion back
    through it (no fetch, no network: the source is already pinned).
    """
    directory = manifest_path.parent
    for part in manifest.get("parts", []):
        mtl = directory / f"{part}.mtl"
        if mtl.is_file() and any(
                line.startswith("newmtl tex_")
                for line in mtl.read_text(encoding="utf-8",
                                          errors="replace").splitlines()):
            return (f"{mtl.name} names materials 'tex_*', which collide with "
                    f"Interchange's 'TEX_*' texture assets on import")
    for texture in manifest.get("textures", []):
        path = directory / texture
        size = _png_size(path) if path.is_file() else None
        if size and not all(n > 0 and n & (n - 1) == 0 for n in size):
            return (f"texture {texture} is {size[0]}x{size[1]}; Unreal "
                    f"refuses non-power-of-two texture imports")
    return None


def is_converted(name: str) -> bool:
    """A CURRENT manifest is on disk. A version-1 manifest is not
    converted: ensure_model re-converts it (the source is already fetched
    at the pinned commit, so this costs one converter run and no
    network, no editor -- the OBJ geometry is unchanged, only the
    manifest gains the origin)."""
    manifest = mesh_manifest_path(name)
    return manifest.is_file() and stale_manifest_reason(manifest) is None


def is_imported(name: str) -> bool:
    """Converted (current) AND present in the Unreal project. Both halves
    matter: a manifest with no .uasset behind it renders nothing real,
    and a stale manifest renders the real mesh in the wrong place."""
    manifest = mesh_manifest_path(name)
    return (manifest.is_file() and stale_manifest_reason(manifest) is None
            and not missing_assets(manifest) and not stale_assets(manifest)
            and import_record_reason(manifest) is None)


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
    # The pinned bytes are the repository's own (package_pins: git blob sha1
    # and sha256 of the file as committed). A machine whose global git says
    # core.autocrlf=true checks text files out with CRLF, and every pin of a
    # text file then fails (measured on the Windows render machine,
    # 2026-11-09: 13 of the J-11's 29 pins). This checkout keeps LF.
    subprocess.run(["git", "-C", str(source_dir), "config", "core.autocrlf",
                    "false"], check=True)
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


def verify_source_pins(config: Dict, source_dir: Path,
                       report: Report = print) -> int:
    """Every ``package_files`` pin of the config (git blob sha1 and sha256,
    assets_pipeline/package_pins.py) holds on the fetched source, BEFORE
    it is converted. Returns the number of files verified; raises the
    named ``aircraft.package_pin`` refusal on the first mismatch set."""
    from assets_pipeline.package_pins import PackagePinError, verify

    try:
        rows = verify(config, source_dir)
    except PackagePinError as exc:
        # A checkout made before fetch_source set core.autocrlf=false holds
        # CRLF copies of the text files: rewrite the working tree from the
        # index with LF once, then verify again. Anything still differing
        # is a real mismatch.
        if not _rewrite_checkout_lf(source_dir, report):
            raise AircraftAssetError("aircraft.package_pin", exc.message) from exc
        try:
            rows = verify(config, source_dir)
        except PackagePinError as again:
            raise AircraftAssetError("aircraft.package_pin", again.message) from again
    if rows:
        report(f"{len(rows)} pinned package file(s) verified (git blob sha1 + sha256)")
    return len(rows)


def _rewrite_checkout_lf(source_dir: Path, report: Report = print) -> bool:
    """Set core.autocrlf=false on the source checkout and rewrite every
    tracked file from the index (git checkout-index -f -a). True when it
    ran; False when the source is not a git checkout or git failed."""
    source_dir = Path(source_dir)
    if not (source_dir / ".git").is_dir():
        return False
    current = subprocess.run(["git", "-C", str(source_dir), "config", "--get",
                              "core.autocrlf"], capture_output=True, text=True)
    if current.stdout.strip().lower() == "false":
        return False
    report("pins differ on a CRLF checkout; rewriting the source with LF line ends")
    try:
        subprocess.run(["git", "-C", str(source_dir), "config", "core.autocrlf",
                        "false"], check=True)
        subprocess.run(["git", "-C", str(source_dir), "checkout-index", "-f", "-a"],
                       check=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def convert(config_path: Path, report: Report = print) -> Path:
    """Source tree -> per-part OBJs + manifest. Raises if nothing lands."""
    name = config_path.stem
    report("converting (license-verified, FDM-matched)")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    # A model that lives in this repository (P3D .mdl) has its own converter;
    # everything else is a FlightGear tree.
    script = ("a4_mdl_convert.py" if config.get("converter") == "mdl"
              else "convert.py")
    converted = subprocess.run(
        [sys.executable, str(REPO / "assets_pipeline" / script),
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
    imported = _run_import(editor, script_arg)

    if len(manifests) > 1:
        # An editor crash on one aircraft loses every part still queued
        # behind it (measured 2026-10-05: the A320 took the whole DHC6
        # with it). Retry what is missing one aircraft per editor run, so
        # a failure is confined to the aircraft that causes it.
        for manifest_path in manifests:
            if missing_assets(Path(manifest_path)):
                report(f"retrying {Path(manifest_path).parent.name} in its "
                       f"own editor run")
                imported = _run_import(editor, " ".join(
                    [(REPO / "scripts" / "ue_import_aircraft.py").as_posix(),
                     Path(manifest_path).as_posix()]))

    missing: List[str] = []
    for manifest_path in manifests:
        missing += missing_assets(Path(manifest_path))
        # Round 2: an import that left a mesh slot without its MTL material
        # draws that part grey and untextured; refuse it by name.
        unbound = unbound_slots(Path(manifest_path))
        if unbound:
            raise AircraftAssetError(
                "aircraft.material_slots",
                f"the {Path(manifest_path).parent.name} import left {len(unbound)} mesh "
                f"slot(s) without their MTL material: {', '.join(unbound[:8])}"
                + (" ..." if len(unbound) > 8 else ""))
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


def _run_import(editor, script_arg: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(editor), str(REPO / "ue" / "FlightSim.uproject"),
         "-run=pythonscript", f"-script={script_arg}",
         "-unattended", "-nopause", "-nosplash", "-stdout"], cwd=REPO)


def _converter_path(name: str) -> Optional[Path]:
    """The converter script that builds ``name``'s manifest, or None when
    the config cannot be read."""
    config_path = CONFIG_DIR / f"{name}.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    script = ("a4_mdl_convert.py" if config.get("converter") == "mdl"
              else "convert.py")
    return REPO / "assets_pipeline" / script


def outdated_reason(name: str) -> Optional[str]:
    """Why ``name``'s mesh must be (re)built now, or None when current.

    Two reasons: the mesh manifest is missing, or it is OLDER BY MTIME
    than the aircraft config (``assets/aircraft_config/<name>.json``) or
    the converter that wrote it. A changed config or converter means the
    manifest describes geometry the current code would not produce."""
    manifest = mesh_manifest_path(name)
    if not manifest.is_file():
        return f"no mesh manifest at {manifest}"
    return older_than_inputs_reason(name)


def older_than_inputs_reason(name: str) -> Optional[str]:
    """The mtime half of :func:`outdated_reason`: a manifest older than
    the config or converter. None when there is no manifest to compare."""
    manifest = mesh_manifest_path(name)
    if not manifest.is_file():
        return None
    built = manifest.stat().st_mtime
    config_path = CONFIG_DIR / f"{name}.json"
    if config_path.is_file() and config_path.stat().st_mtime > built:
        return f"the mesh manifest is older than {config_path.name}"
    converter = _converter_path(name)
    if converter is not None and converter.is_file() \
            and converter.stat().st_mtime > built:
        return f"the mesh manifest is older than {converter.name}"
    return None


def _editor_present() -> bool:
    from core.util.platform import ue_editor_path

    editor = ue_editor_path()
    return editor is not None and Path(editor).is_file()


def provision_models(names: Iterable[str], report: Report = print,
                     ensure=None) -> List[str]:
    """Build, once each, every distinct airframe in ``names`` that is not
    current (missing mesh, outdated manifest, or no .uasset behind it).
    Returns the names built. Raises AircraftAssetError (named) on a real
    failure -- missing licence, converter error, import error.

    No editor file on this machine: a model that still needs the editor
    import is skipped, with a line saying so, and nothing is launched; a
    model that needs only a re-convert (assets already imported) is still
    re-converted. The caller's own check then decides what that means."""
    ensure = ensure_model if ensure is None else ensure
    built: List[str] = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        reason = older_than_inputs_reason(name)
        if reason is None and is_imported(name):
            continue
        manifest = mesh_manifest_path(name)
        needs_editor = ((not manifest.is_file()) or bool(missing_assets(manifest))
                        or bool(stale_assets(manifest))
                        or import_record_reason(manifest) is not None)
        if needs_editor and not _editor_present() and \
                unavailable_reason(name) is None:
            report(f"the {name} model needs the Unreal editor to import "
                   f"and none is installed here; nothing was run")
            continue
        report(f"the {name} model is not current ({reason or 'not imported'}); "
               f"building it once")
        ensure(name, report)
        built.append(name)
    return built


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
    stale = stale_manifest_reason(manifest) if manifest.is_file() else None
    if not stale and manifest.is_file():
        stale = outdated_reason(name)
    if stale:
        # Re-convert, then re-import: since decision 19 a re-convert can
        # change the geometry the editor holds (the OBJ frame), so the
        # .uassets behind a re-converted manifest are stale until the
        # editor imports them again (packet C4-2, 2026-11-04).
        report(f"the {name} mesh manifest is stale ({stale}); re-converting "
               f"and re-importing so the mesh is drawn where its label is")
    if not manifest.is_file() or stale:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        try:
            if config.get("converter") != "mdl":   # local models need no fetch
                source_dir = fetch_source(config, config_path, report)
                verify_source_pins(config, source_dir, report)
        except subprocess.CalledProcessError as exc:
            raise AircraftAssetError(
                "aircraft.mesh_import",
                f"fetching the {name} model source failed ({exc}) -- the "
                f"pinned commit is fetched from the upstream model "
                f"repository, so this step needs network access") from exc
        manifest = convert(config_path, report)
    if missing_assets(manifest) or stale_assets(manifest) or import_record_reason(manifest):
        import_manifests([manifest], report)
    return manifest
