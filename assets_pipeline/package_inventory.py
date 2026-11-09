"""The inventory of an upstream aircraft package, from the GitHub tree API.

Writes docs/visual/J11_PACKAGE.md: every blob of the package at the pinned
commit with its path, size, git blob sha1 and purpose, and whether the
conversion uses it (the config's ``package_files`` pins, which
assets_pipeline/package_pins.py checks against the bytes).

The tree JSON is what ``GET /repos/<owner>/<repo>/git/trees/<commit>
?recursive=1`` returns; nothing here touches the network::

    curl -s https://api.github.com/repos/yanes19/SU-27SK/git/trees/\\
925cb5317f3c66fa323a9e186e24d574e0b0881d?recursive=1 > tree.json
    python -m assets_pipeline.package_inventory tree.json \\
        assets/aircraft_config/J11.json docs/visual/J11_PACKAGE.md

The purpose column is a path rule (:data:`PURPOSE_RULES`, first full
match wins), each rule written from reading the package's model XML at
that commit; a file no rule matches says so rather than guessing.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

#: (regex over the package path, purpose). Ordered: first match wins.
PURPOSE_RULES: Tuple[Tuple[str, str], ...] = (
    (r"LICENSE|COPYING", "licence text (GPL-2.0)"),
    (r"README\.md|SU-27\.README|changelog", "package documentation / credits"),
    (r"J-11A-set\.xml", "J-11A aircraft set file: views (pilot eye), model path, liveries, systems"),
    (r"Su-27SK-set\.xml", "Su-27SK variant set file"),
    (r"J-11A\.xml", "J-11A JSBSim FDM (vendored as assets/fdm_root/aircraft/J11/J11.xml)"),
    (r"Su-27SK\.xml", "Su-27SK JSBSim FDM"),
    (r"thumbnail\.jpg|Su-27Splach-pic\.png", "launcher thumbnail / splash screen"),
    (r"Models/J-11A\.xml", "J-11A model XML: livery material animation, glass effect, panel, "
                           "nozzles, reheat, LightPack and effect placements"),
    (r"Models/SU-27\.xml", "Su-27SK model XML"),
    (r"Models/Su-27\.ac", "airframe mesh (AC3D), 43 objects, shared by both variants"),
    (r"Models/Su-27_Flanker_P01\.png", "airframe base colour (default scheme)"),
    (r"Models/su-27gears\.png", "undercarriage base colour"),
    (r"Models/Glass_Cockpit\.png", "canopy glass texture"),
    (r"Models/Eject_Seat\.png", "ejection seat texture (unused by J-11A.xml)"),
    (r"Models/SU-27-reheat\.rgb|Models/SU-27-Petal\.rgb", "reheat / nozzle petal texture (SGI rgb)"),
    (r"Models/(Elevation-marker|FuselageSection|Trajectory-Marker)\.(ac|xml)",
     "debug / helper marker model"),
    (r"Models/Liveries/default\.xml", "livery definition: default scheme"),
    (r"Models/Liveries/PLAAF2Div\.(xml|png)", "livery: PLAAF 2nd Division (the J-11A scheme)"),
    (r"Models/Liveries/Su-27_Flanker_P01\.png", "livery texture: default scheme copy"),
    (r"Models/Liveries/.*\.xml", "livery definition (non-PLAAF air force)"),
    (r"Models/Liveries/.*\.png", "livery texture (non-PLAAF air force), 4096x2048"),
    (r"Models/Interior/panel-zh\.xml", "J-11A (Chinese-label) cockpit model XML: panel, seat, pilot, instruments"),
    (r"Models/Interior/panel\.xml", "Su-27SK (Russian-label) cockpit model XML"),
    (r"Models/Interior/panel\.ac", "3D cockpit: instrument panel, consoles, tub"),
    (r"Models/Interior/seat2\.ac", "K-36DM ejection seat mesh"),
    (r"Models/Interior/panel-front-tex-2048-bevel\.png", "front instrument panel texture (used)"),
    (r"Models/Interior/panel-front-tex-2048\.png", "front instrument panel texture, unbevelled variant"),
    (r"Models/Interior/.*\.png", "cockpit / seat texture"),
    (r"Models/Interior/pilot/pilot(OLD)?\.xml", "pilot figure model XML (head / visor animation)"),
    (r"Models/Interior/pilot/fighter_default\.ac", "pilot figure mesh"),
    (r"Models/Interior/pilot/.*\.png", "pilot figure texture"),
    (r"Models/Interior/pilot/Read-Me\.txt", "pilot figure provenance"),
    (r"Models/Interior/Instruments/fuel-indicator/fuel_ind_AOmap\.png",
     "ambient-occlusion map of the fuel indicator (the package's only AO map)"),
    (r"Models/Interior/Instruments/Stick/.*", "control stick (animated sub-model)"),
    (r"Models/Interior/Instruments/hud/.*", "head-up display (animated / canvas sub-model)"),
    (r"Models/Interior/Instruments/mfd/.*", "multi-function display (canvas sub-model)"),
    (r"Models/Interior/Instruments/WarningLights/.*", "warning / LED panel (animated sub-model)"),
    (r"Models/Interior/Instruments/.*\.ac", "cockpit instrument mesh (animated sub-model)"),
    (r"Models/Interior/Instruments/.*\.xml", "cockpit instrument animation XML"),
    (r"Models/Interior/Instruments/.*", "cockpit instrument texture / asset"),
    (r"Models/Interior/LeftPanels/Throttle\.blocks/.*", "throttle block (animated sub-model)"),
    (r"Models/Interior/(Left|Right)Panels/.*\.ac", "side-console panel mesh (animated sub-model)"),
    (r"Models/Interior/(Left|Right)Panels/.*\.xml", "side-console panel animation XML"),
    (r"Models/Interior/(Left|Right)Panels/.*", "side-console panel texture / asset"),
    (r"Models/Lights/LightPack\.xml", "light positions: nav, beacons, landing, taxi (strobes, tail commented out)"),
    (r"Models/Lights/(Rembrandt)/.*", "Rembrandt-renderer light volume"),
    (r"Models/Lights/Flares/.*", "light flare billboard"),
    (r"Models/Lights/LightCone/.*", "landing / taxi light cone"),
    (r"Models/Lights/.*", "light model (nav / beacon / strobe / landing / taxi / probe)"),
    (r"Models/Effects/glass\.eff", "glass effect: reflections on, no normal map"),
    (r"Models/Effects/nozzles/.*", "variable nozzle petals: 18 animated segments per engine"),
    (r"Models/Effects/Afterburner/.*", "afterburner flame / turbine glow"),
    (r"Models/Effects/Contrail/.*", "contrail particle effect"),
    (r"Models/Effects/Vapour/.*", "wing vapour effect"),
    (r"Models/Effects/Vortex/.*", "tip vortex condensation"),
    (r"Models/Effects/(tiptrail|trail|smoke)/.*|Models/Effects/smoke\.rgb", "smoke / trail particle effect"),
    (r"Models/Effects/(Explosion|MissileExplosion|Flamme|flammes|boom)/.*", "explosion / fire / boom effect"),
    (r"Models/Effects/wash/.*", "ground wash effect"),
    (r"Models/Effects/gunsmoke\.xml", "gun smoke effect"),
    (r"Models/Stores/Missiles/R-27R/.*", "R-27R missile store (used: parts[1], parts[2])"),
    (r"Models/Stores/Missiles/R-27ER/.*", "R-27ER missile store"),
    (r"Models/Stores/Missiles/R-73/.*", "R-73 missile store"),
    (r"Models/Stores/Missiles/Smoke-generator/.*", "smoke-generator pod store"),
    (r"Models/Stores/Missiles/Weapons-load\.xml", "store placements by pylon"),
    (r"Models/Stores/Countermeasures/.*", "chaff / flare countermeasure"),
    (r"Models/Stores/DrogChute/.*", "drag chute"),
    (r"Models/Stores/submodels\.xml", "store submodel definitions"),
    (r"Models/sim-helpr-models/.*", "ground power trailer"),
    (r"Dialogs/.*", "FlightGear dialog / preview image"),
    (r"Doc/.*", "pilot manual / keyboard reference"),
    (r"Engines/.*", "engine definition"),
    (r"Hud/.*", "HUD definition"),
    (r"Nasal/.*", "Nasal script"),
    (r"Systems/.*", "systems XML"),
    (r"Panels/.*", "2D panel"),
    (r"Sounds/.*", "sound"),
    (r"start-states/.*", "start state"),
)


def purpose(path: str) -> str:
    for pattern, text in PURPOSE_RULES:
        if re.fullmatch(pattern, path):
            return text
    return "(no rule: not read)"


def load_tree(path: Path) -> Dict:
    tree = json.loads(Path(path).read_text(encoding="utf-8"))
    if tree.get("truncated"):
        raise ValueError(f"{path}: the tree API truncated the listing; it is not a full inventory")
    return tree


def blobs(tree: Dict) -> List[Dict]:
    return sorted((e for e in tree["tree"] if e.get("type") == "blob"), key=lambda e: e["path"])


def render(tree: Dict, config: Dict) -> str:
    rows = blobs(tree)
    pins = {row["file"]: row for row in config.get("package_files") or []}
    commit = config["license"]["commit"]
    repo = config["license"]["repo"]
    total = sum(e["size"] for e in rows)
    lines = [
        "# J-11A package inventory",
        "",
        f"Every file of {repo} at commit `{commit}`, from the GitHub",
        "tree API (`git/trees/<commit>?recursive=1`, not truncated). Generated by",
        "`python -m assets_pipeline.package_inventory <tree.json> assets/aircraft_config/J11.json"
        " docs/visual/J11_PACKAGE.md`;",
        "do not edit by hand. Licence GPL-2.0, owner-cleared (docs/phase3/decisions.md",
        "decisions 3 and 20). The binaries are fetched into the git-ignored",
        "`assets/aircraft_src/J11` by `assets_pipeline/importer.py fetch_source`, never committed.",
        "",
        f"{len(rows)} files, {total:,} bytes. **Used** marks the {len(pins)} files the conversion",
        "reads, each pinned in `assets/aircraft_config/J11.json package_files` by git blob",
        "sha1 AND sha256 and checked against the bytes before every convert.",
        "",
        "## What the package does and does not carry",
        "",
        "- Textures: diffuse (base colour) PNGs only, 4096x2048 for the airframe and each livery.",
        "- Normal maps: none (glass.eff sets `normalmap-enabled 0`).",
        "- Specular / metalness maps: none; FlightGear's .ac MATERIAL `spec` / `shi` are the only",
        "  specular data (scripts/aircraft_look.py derive_fg_scalars uses `shi` for the cockpit).",
        "- AO maps: one, `Models/Interior/Instruments/fuel-indicator/fuel_ind_AOmap.png`, for an",
        "  instrument sub-model this lane does not import.",
        "- Light maps: none (the instrument LED `.rgb` / `.png` are emissive textures of animated",
        "  sub-models).",
        "- Liveries: 14 schemes; one PLAAF (`PLAAF2Div`), used.",
        "- Cockpit: `panel.ac` + `seat2.ac` + the pilot (used, drawn in the body part); 85",
        "  animated instrument / console sub-model meshes (not imported: each is animated by Nasal or",
        "  canvas; the front panel texture carries the instrument faces).",
        "- Glass: Su-27.ac objects `canopy.glass` / `object.001` with `Glass_Cockpit.png` (used,",
        "  glass class).",
        "- Lights: `LightPack.xml` positions (used for the FX lamps); the light `.ac` / flare",
        "  models are FlightGear's own billboards, replaced by the FX lamps.",
        "- Nozzle petals: `Models/Effects/nozzles` (positions used for the FX nozzles; petals",
        "  not imported: J-11A.xml places Nozzles.xml twice and each holds two rings, so of the",
        "  four rings two sit on the nozzles (y -1.277 / +1.263 m), one inside the fuselage",
        "  (y +0.637 m) and one 3.2 m off the airframe (y +3.177 m); the petals are also",
        "  throttle-animated).",
        "- Afterburner / contrail / vapour effects: FlightGear particle and billboard",
        "  definitions; the FX lane draws its own.",
        "",
        "## Files",
        "",
        "| path | bytes | git blob sha1 | used | purpose |",
        "|---|---:|---|---|---|",
    ]
    for e in rows:
        pin = pins.get(e["path"])
        used = "**used**" if pin else ""
        if pin and pin["git_blob_sha1"] != e["sha"]:
            raise ValueError(f"{e['path']}: config pins blob {pin['git_blob_sha1']}, tree lists {e['sha']}")
        text = pin["role"] if pin else purpose(e["path"])
        text = text.replace("|", "/")
        lines.append(f"| `{e['path']}` | {e['size']} | `{e['sha']}` | {used} | {text} |")
    missing = sorted(set(pins) - {e["path"] for e in rows})
    if missing:
        raise ValueError(f"pinned files absent from the tree: {missing}")
    return "\n".join(lines) + "\n"


#: The table row shape the test parses back.
ROW = re.compile(r"^\| `(?P<path>[^`]+)` \| (?P<size>\d+) \| `(?P<sha>[0-9a-f]{40})` \| (?P<used>[^|]*) \|")


def parse(markdown: str) -> Dict[str, Dict]:
    """{path: {"size", "sha", "used"}} read back from the inventory."""
    out = {}
    for line in markdown.splitlines():
        m = ROW.match(line)
        if m:
            out[m["path"]] = {"size": int(m["size"]), "sha": m["sha"], "used": "used" in m["used"]}
    return out


def main(argv: Sequence[str]) -> int:
    tree_path, config_path, out_path = (Path(a) for a in argv[1:4])
    config = json.loads(config_path.read_text(encoding="utf-8"))
    out_path.write_text(render(load_tree(tree_path), config), encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
