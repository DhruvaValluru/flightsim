"""The per-asset licence gate (blueprint section 4, work item W4).

A dataset ships more than labels: the pixels show an airframe mesh, its
livery, the terrain heights and the imagery draped on them, the building
blocks; the labels carry the land cover. Every one of those is somebody's
asset under somebody's licence, and whether the dataset may be
distributed -- and used for machine learning -- is a fact PER ASSET,
recorded and refusable, never a line of prose at the end of a card.

The licence record
------------------
Every asset carries ``{asset, kind, licence, spdx, source, attribution,
ml_use, sha256, reaches, note}``:

* ``licence`` the name as the asset's own record states it; ``spdx`` its
  SPDX identifier (``LicenseRef-...`` where SPDX has none) from
  :func:`normalise_licence`; both null when nothing states a licence;
* ``source`` where the asset came from (repository and commit, dataset
  and bucket, cache key), ``attribution`` the line its licence asks for;
* ``ml_use`` one of :data:`ML_USE`: ``allowed``, ``forbidden`` or
  ``unknown`` -- the record's own statement when it makes one, else the
  allow-list's reading of the licence (``unknown`` where the licence text
  is silent: recorded as unstated, never as yes);
* ``reaches`` what of the dataset the asset is in: ``pixels`` (the engine
  draws it), ``label_files`` (the engine's ID, class or depth image of it),
  ``labels`` (a label derived from it, as the land-cover image is).

Where each record comes from: an airframe from its config's ``license``
block (``assets/aircraft_config/<name>.json``; the config's optional
``ml_use`` key is honoured); a livery from the same config (a variant
material of the airframe's own files); the terrain from the bake
sidecar's provenance (Copernicus GLO-30 -> the Copernicus DEM licence; a
synthesised ridge -> the project's own; anything else -> no record); the
imagery from its sidecar's ``license``; the land cover from its
``landcover.json``; the buildings from their document's provenance; the
runway markings raster -> the project's own (drawn by core/scene/runway.py).
The capture manifest carries the scene assets' records under
``licences[]`` (absent for a flat scene with none); the airframes' ride
on ``objects[].licence`` and are re-read from the config here.

The allow-list for distribution (:data:`ALLOW_LIST`)
-----------------------------------------------------
CC BY 4.0, CC BY-SA 4.0 (share-alike: the dataset inherits the terms for
the pixels, stated as an obligation), CC0 1.0, public domain, CDLA
Permissive 2.0, ODbL 1.0 (share-alike), the Copernicus DEM licence
(attribution), the project's own and the synthetic fixtures. Each entry
names its obligations (attribution, share-alike) and its default
``ml_use``. The GPL family (:func:`is_copyleft_code`) is NOT on it: the
GPL airframes render internally and refuse export.

The gate (:func:`gate`)
-----------------------
Per asset, over every run of the export: SHIPPED when the export carries
what the asset reaches -- rendered pixels or engine label files of a run
the engine drew (for an airframe: only when a MESH was drawn, the
render record's ``drawn.kind`` or a recorded ``mesh_sha256``; a
placeholder box or a physics-only airframe ships no licensed geometry),
or a derived label that reads it. A shipped asset is refused, by name and
in this order:

* ``asset.licence`` -- no licence record (nothing states one);
* ``aircraft.licence_noai`` -- an airframe or livery whose record forbids
  machine-learning use (``ml_use: forbidden``); any other asset that
  forbids it refuses ``asset.licence``;
* ``aircraft.licence_dataset`` -- an airframe or livery whose licence is
  not on the allow-list (every GPL airframe in this tree);
* ``asset.licence`` -- any other asset whose licence is not on it.

An asset not shipped gets the verdict ``not shipped`` with the reason (a
GPL airframe that flew physics-only, a land cover no exported label
reads) -- recorded, never silent. The export runs the gate BEFORE any
file is written, so a refused dataset leaves nothing behind.

NOT claimed: the verdicts are the records' words, not legal advice --
whether a rendered image or a label is a derivative work of a mesh is a
question for a lawyer, and this gate answers the conservative way (a
drawn GPL mesh refuses). No licence text is parsed; the allow-list is a
stated table. ``ml_use: unknown`` is what a silent licence says, not a
permission.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO / "assets" / "aircraft_config"

#: What a licence record says about machine-learning use.
ML_USE = ("allowed", "forbidden", "unknown")
#: The verdicts the gate writes per asset.
VERDICTS = ("allowed", "refused", "not shipped")
#: What of a dataset an asset can be in.
REACHES = ("pixels", "label_files", "labels")

#: The asset kinds that are an airframe's (their refusals are aircraft.*).
AIRCRAFT_KINDS = ("airframe", "livery")

#: The project's own assets (a synthesised ridge, the runway markings
#: raster, the labels themselves): no third-party licence applies.
OWN = "LicenseRef-flightsim-own"
SYNTHETIC = "LicenseRef-synthetic"
PUBLIC_DOMAIN = "LicenseRef-public-domain"
COPERNICUS_DEM = "LicenseRef-Copernicus-DEM"

#: The allow-list for distributing a dataset, per SPDX id: the
#: obligations each carries and the ml_use a licence that states nothing
#: about machine learning is read as. A stated table, not parsed text.
ALLOW_LIST: Dict[str, Dict[str, Any]] = {
    "CC-BY-4.0": {
        "name": "Creative Commons Attribution 4.0", "attribution_required": True,
        "share_alike": False, "ml_use": "unknown",
        "basis": "the CC BY 4.0 deed: share and adapt with attribution; silent on "
                 "machine learning"},
    "CC-BY-SA-4.0": {
        "name": "Creative Commons Attribution-ShareAlike 4.0", "attribution_required": True,
        "share_alike": True, "ml_use": "unknown",
        "basis": "the CC BY-SA 4.0 deed: adaptations carry the same licence, so the "
                 "dataset's pixels inherit it; silent on machine learning"},
    "CC0-1.0": {
        "name": "Creative Commons Zero 1.0", "attribution_required": False,
        "share_alike": False, "ml_use": "allowed",
        "basis": "a public-domain dedication"},
    PUBLIC_DOMAIN: {
        "name": "public domain", "attribution_required": False, "share_alike": False,
        "ml_use": "allowed", "basis": "no rights reserved"},
    "CDLA-Permissive-2.0": {
        "name": "Community Data License Agreement - Permissive 2.0",
        "attribution_required": False, "share_alike": False, "ml_use": "allowed",
        "basis": "permissive data licence; the text permits use of the data to train "
                 "models (as core/scene/buildings.py records it)"},
    "ODbL-1.0": {
        "name": "Open Data Commons Open Database License 1.0", "attribution_required": True,
        "share_alike": True, "ml_use": "unknown",
        "basis": "share-alike applies to a derived database; silent on machine learning"},
    COPERNICUS_DEM: {
        "name": "Copernicus DEM licence (free use and redistribution with attribution)",
        "attribution_required": True, "share_alike": False, "ml_use": "unknown",
        "basis": "as core/terrain/glo30.py records it: free to use and redistribute "
                 "with the attribution line; silent on machine learning"},
    OWN: {
        "name": "the project's own", "attribution_required": False, "share_alike": False,
        "ml_use": "allowed", "basis": "written by this code; no third-party asset"},
    SYNTHETIC: {
        "name": "synthetic fixture", "attribution_required": False, "share_alike": False,
        "ml_use": "allowed", "basis": "written by hand as a stand-in (the record says "
                                      "synthetic)"},
}

#: Spellings the records use -> SPDX id (case- and space-insensitive).
_ALIASES = {
    "CCBY4.0": "CC-BY-4.0", "CCBY40": "CC-BY-4.0",
    "CCBYSA4.0": "CC-BY-SA-4.0", "CCBYSA40": "CC-BY-SA-4.0",
    "CC01.0": "CC0-1.0", "CC0": "CC0-1.0",
    "PUBLICDOMAIN": PUBLIC_DOMAIN, "PD": PUBLIC_DOMAIN,
    "CDLAPERMISSIVE2.0": "CDLA-Permissive-2.0",
    "ODBL1.0": "ODbL-1.0", "ODBL": "ODbL-1.0",
    "SYNTHETIC": SYNTHETIC, "OWN": OWN, "FLIGHTSIM": OWN,
    "COPERNICUSDEMLICENCE": COPERNICUS_DEM, "COPERNICUSDEM": COPERNICUS_DEM,
}

NOT_CLAIMED = (
    "the verdicts are the records' words, not legal advice: whether a rendered image or a "
    "label is a derivative work of an asset is a question for a lawyer, and the gate "
    "answers the conservative way (a drawn GPL mesh refuses)",
    "no licence text is parsed: the allow-list is a stated table",
    "ml_use unknown is what a licence silent on machine learning says, not a permission",
)


class LicenceError(ValueError):
    """An asset the export would ship is refused, by name (``.constraint``:
    ``aircraft.licence_dataset``, ``aircraft.licence_noai`` or
    ``asset.licence``)."""

    def __init__(self, constraint: str, message: str) -> None:
        super().__init__(f"{constraint}: {message}")
        self.constraint = constraint
        self.message = message


# -- names -----------------------------------------------------------------

def _squash(name: str) -> str:
    return "".join(ch for ch in str(name).upper() if ch not in " -_")


def normalise_licence(name: Any) -> Optional[str]:
    """The SPDX id (or ``LicenseRef-``) of a stated licence name, or the
    name itself when it is not one this table knows (it is then off the
    allow-list, and says so); None for no name."""
    if not isinstance(name, str) or not name.strip():
        return None
    name = name.strip()
    for spdx in ALLOW_LIST:
        if name == spdx or _squash(name) == _squash(spdx):
            return spdx
    alias = _ALIASES.get(_squash(name))
    if alias:
        return alias
    squashed = _squash(name)
    for family in ("AGPL", "LGPL", "GPL"):
        if squashed.startswith(family):
            return name.replace(" ", "-")
    return name


def is_copyleft_code(spdx: Optional[str]) -> bool:
    """The GPL family (GPL, LGPL, AGPL): software licences whose copyleft
    a dataset of rendered meshes cannot honour -- off the allow-list."""
    return bool(spdx) and _squash(spdx).startswith(("GPL", "LGPL", "AGPL"))


def allow_list_entry(spdx: Optional[str]) -> Optional[Dict[str, Any]]:
    return None if spdx is None else ALLOW_LIST.get(spdx)


def default_ml_use(spdx: Optional[str]) -> str:
    entry = allow_list_entry(spdx)
    return str(entry["ml_use"]) if entry else "unknown"


def record(asset: str, kind: str, licence: Optional[str], source: Optional[str],
           attribution: Optional[str], reaches: Sequence[str], ml_use: Optional[str] = None,
           sha256: Optional[str] = None, note: Optional[str] = None) -> Dict[str, Any]:
    """One asset's licence record (the shape the manifest's ``licences[]``
    and the card carry). ``ml_use`` None is the allow-list's reading."""
    spdx = normalise_licence(licence)
    use = ml_use if ml_use in ML_USE else default_ml_use(spdx)
    return {"asset": str(asset), "kind": str(kind),
            "licence": None if licence is None else str(licence), "spdx": spdx,
            "source": source, "attribution": attribution, "ml_use": use,
            "sha256": sha256, "reaches": [r for r in REACHES if r in set(reaches)],
            "note": note}


# -- where each record comes from --------------------------------------------

def airframe_record(aircraft: str, config_dir: Optional[Path] = None,
                    kind: str = "airframe", asset: Optional[str] = None) -> Dict[str, Any]:
    """An airframe's record from its config's ``license`` block; no record
    (licence null, with the reason) when the config or the block is absent."""
    import hashlib

    path = Path(config_dir or CONFIG_DIR) / f"{aircraft}.json"
    name = asset or f"airframe:{aircraft}"
    reaches = ("pixels", "label_files")
    if not path.is_file():
        return record(name, kind, None, None, None, reaches,
                      note=f"no config {path.name} on this machine; no licence is stated")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return record(name, kind, None, None, None, reaches,
                      note=f"{path.name} is not readable JSON ({exc})")
    block = config.get("license") if isinstance(config, dict) else None
    if not isinstance(block, dict) or not block.get("license_name"):
        return record(name, kind, None, None, None, reaches,
                      note=f"{path.name} carries no license block")
    repo, commit = block.get("repo"), block.get("commit")
    source = f"{repo}@{commit}" if repo and commit else (repo or None)
    authors = block.get("authors_file")
    attribution = (f"the authors listed in {authors} of {repo}" if authors and repo else None)
    note = block.get("unavailable")
    return record(name, kind, str(block["license_name"]), source, attribution, reaches,
                  ml_use=block.get("ml_use"),
                  sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  note=str(note) if note else None)


def terrain_record(stem) -> Optional[Dict[str, Any]]:
    """The terrain's record from the bake sidecar's provenance, or None
    for no terrain. GLO-30 -> the Copernicus DEM licence; a synthesised
    raster -> the project's own; a runway pad -> its parent's source;
    any other provenance -> no licence (refused when shipped)."""
    if not stem:
        return None
    sidecar = Path(str(stem)).with_suffix(".json")
    name = f"terrain:{Path(str(stem)).name}"
    reaches = ("pixels", "label_files")
    if not sidecar.is_file():
        return record(name, "terrain", None, None, None, reaches,
                      note=f"the bake sidecar {sidecar.name} is not on this machine")
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return record(name, "terrain", None, None, None, reaches,
                      note=f"{sidecar.name} is not readable JSON ({exc})")
    provenance = meta.get("provenance") or {}
    digest = meta.get("sha256")
    dataset = str(provenance.get("dataset") or "")
    if dataset.startswith("Copernicus GLO-30"):
        return record(name, "terrain", "Copernicus DEM licence", dataset,
                      provenance.get("attribution"), reaches, sha256=digest)
    if provenance.get("producer") == "spectral synthesis" or provenance.get("synthetic"):
        return record(name, "terrain", OWN, "synthesised by core/terrain/synthesis.py"
                      if provenance.get("producer") else "a synthetic fixture bake",
                      None, reaches, sha256=digest)
    return record(name, "terrain", None, provenance.get("source"), None, reaches,
                  sha256=digest, note="the bake's provenance states no licence")


def imagery_record(sidecar) -> Optional[Dict[str, Any]]:
    if not sidecar:
        return None
    path = Path(str(sidecar))
    name = f"imagery:{path.stem}"
    if not path.is_file():
        return record(name, "imagery", None, None, None, ("pixels",),
                      note=f"the imagery sidecar {path.name} is not on this machine")
    meta = json.loads(path.read_text(encoding="utf-8"))
    return record(name, "imagery", meta.get("license"), meta.get("dataset"),
                  meta.get("attribution"), ("pixels",))


def landcover_record(document) -> Optional[Dict[str, Any]]:
    """The land cover's record from its ``landcover.json``. It reaches the
    labels only: nothing engine-side draws it yet (W5)."""
    if not document:
        return None
    path = Path(str(document))
    if not path.is_file():
        return record("land_cover", "land_cover", None, None, None, ("labels",),
                      note=f"{path} is not on this machine")
    meta = json.loads(path.read_text(encoding="utf-8"))
    return record(f"land_cover:{path.parent.name}", "land_cover", meta.get("license"),
                  meta.get("dataset"), meta.get("attribution"), ("labels",),
                  sha256=meta.get("sha256"))


def buildings_record(document) -> Optional[Dict[str, Any]]:
    """The footprint set's record from the buildings document (its cached
    provenance): drawn by the engine, and the building:all label."""
    if not document:
        return None
    path = Path(str(document))
    if not path.is_file():
        return record("buildings", "buildings", None, None, None,
                      ("pixels", "label_files"), note=f"{path} is not on this machine")
    meta = json.loads(path.read_text(encoding="utf-8"))
    provenance = meta.get("provenance") or {}
    verdict = meta.get("licence_verdict") or {}
    ai = verdict.get("ai_training_permitted")
    ml = "allowed" if ai is True else ("forbidden" if ai is False else None)
    return record(f"buildings:{meta.get('key')}", "buildings", meta.get("licence"),
                  provenance.get("source"), provenance.get("attribution"),
                  ("pixels", "label_files"), ml_use=ml, sha256=meta.get("sha256"))


def runway_record(document) -> Optional[Dict[str, Any]]:
    """The runway markings raster: drawn by core/scene/runway.py from the
    Annex 14 table, the project's own; the pad's heights are the parent
    bake's, whose record is the terrain's."""
    if not document:
        return None
    path = Path(str(document))
    if not path.is_file():
        return None
    meta = json.loads(path.read_text(encoding="utf-8"))
    designator = (meta.get("spec") or {}).get("designator")
    return record(f"runway:{designator}", "runway_markings", OWN,
                  "core/scene/runway.py markings raster", None, ("pixels",),
                  sha256=(meta.get("markings") or {}).get("sha256"))


def scene_licence_records(scene: Optional[Dict[str, Any]],
                          landcover_document=None) -> List[Dict[str, Any]]:
    """The licence records of every scene asset a capture's scene dict
    names (terrain, imagery, land cover, buildings, runway markings), in
    that order; [] for a flat scene with none (the manifest then carries
    no ``licences[]``: absent-canonical)."""
    scene = scene or {}
    out = [terrain_record(scene.get("terrain")),
           imagery_record(scene.get("imagery")),
           landcover_record(landcover_document),
           buildings_record(scene.get("buildings_document")),
           runway_record(scene.get("runway_document"))]
    return [r for r in out if r is not None]


# -- the assets a run ships, and the gate ---------------------------------------

def _aircraft_names(manifest: Dict[str, Any]) -> List[str]:
    names = [str(manifest.get("aircraft"))] if manifest.get("aircraft") else []
    for entry in manifest.get("objects") or []:
        if isinstance(entry, dict) and entry.get("class") == "aircraft":
            parts = str(entry.get("id", "")).split(":")
            if len(parts) == 3 and parts[1] and parts[1] not in names:
                names.append(parts[1])
    return names


def mesh_drawn(manifest: Dict[str, Any], render: Optional[Dict[str, Any]]) -> bool:
    """A licensed airframe mesh is in the run's engine output: a camera's
    render record says it drew a mesh, or an aircraft object records the
    imported mesh's digest on a run the engine rendered."""
    render = render or {}
    for provenance in render.values():
        drawn = (provenance or {}).get("drawn")
        if isinstance(drawn, dict) and drawn.get("kind") == "mesh":
            return True
    if not render:
        return False
    return any(isinstance(o, dict) and o.get("class") == "aircraft" and o.get("mesh_sha256")
               for o in manifest.get("objects") or [])


def run_assets(manifest: Dict[str, Any], config_dir: Optional[Path] = None
               ) -> List[Dict[str, Any]]:
    """Every asset one run's dataset content can carry, as licence records:
    each airframe (from its config), a non-default livery of the primary,
    and the scene assets -- the manifest's ``licences[]`` when it carries
    one, else re-read from the scene it names (a manifest written before
    the block)."""
    out = [airframe_record(name, config_dir) for name in _aircraft_names(manifest)]
    livery = (manifest.get("randomization") or {}).get("livery")
    if livery and str(livery) != "default" and manifest.get("aircraft"):
        aircraft = str(manifest["aircraft"])
        out.append(airframe_record(aircraft, config_dir, kind="livery",
                                   asset=f"livery:{aircraft}:{livery}"))
    stated = manifest.get("licences")
    if isinstance(stated, list):
        out.extend(dict(r) for r in stated if isinstance(r, dict))
    else:
        scene = manifest.get("scene") or {}
        document = (manifest.get("landcover") or {}).get("document") \
            if isinstance(manifest.get("landcover"), dict) else None
        out.extend(scene_licence_records(
            {"terrain": scene.get("terrain"),
             "buildings_document": (scene.get("buildings") or {}).get("document")
             if isinstance(scene.get("buildings"), dict) else None,
             "runway_document": (scene.get("runway") or {}).get("document")
             if isinstance(scene.get("runway"), dict) else None}, document))
    return out


def shipped_reason(entry: Dict[str, Any], ships: Dict[str, bool]) -> Tuple[bool, str]:
    """(shipped, why) for one asset in one run: what the export carries of
    what the asset reaches."""
    kind = entry.get("kind")
    reaches = set(entry.get("reaches") or ())
    engine = [w for w in ("pixels", "label_files") if w in reaches and ships.get(w)]
    if kind in AIRCRAFT_KINDS:
        if not engine:
            return False, "no rendered pixels or engine label files of this run ship"
        if not ships.get("mesh_drawn"):
            return False, ("the run's render drew no mesh of it (physics-only, or a "
                           "placeholder): no licensed geometry is in the pixels")
        return True, f"a drawn mesh in the shipped {' and '.join(w.replace('_', ' ') for w in engine)}"
    if engine:
        return True, f"in the shipped {' and '.join(w.replace('_', ' ') for w in engine)}"
    if "labels" in reaches and ships.get("labels"):
        return True, "a label derived from it ships"
    return False, "nothing the export carries is drawn from it"


def verdict_for(entry: Dict[str, Any], shipped: bool) -> Dict[str, Any]:
    """The verdict on one (merged) asset record: allowed, refused (with
    the refusal's name) or not shipped."""
    spdx = entry.get("spdx")
    allowed = allow_list_entry(spdx)
    aircraft = entry.get("kind") in AIRCRAFT_KINDS
    obligations = []
    if allowed:
        if allowed["attribution_required"]:
            obligations.append("attribution: " + (entry.get("attribution") or "as the licence states"))
        if allowed["share_alike"]:
            obligations.append(f"share-alike: the content drawn from it is under {spdx}")
    error: Optional[LicenceError] = None
    if entry.get("licence") is None:
        error = LicenceError("asset.licence",
                             f"{entry['asset']} has no licence record"
                             + (f" ({entry['note']})" if entry.get("note") else ""))
    elif entry.get("ml_use") == "forbidden":
        reason = f"{entry['asset']} is under {entry['licence']}, which forbids machine-learning use"
        error = (LicenceError("aircraft.licence_noai", reason) if aircraft
                 else LicenceError("asset.licence", reason))
    elif allowed is None:
        reason = (f"{entry['asset']} is under {entry['licence']}, which is not on the allow-list "
                  f"for distributing a dataset"
                  + (" (a GPL airframe renders internally and refuses export)"
                     if is_copyleft_code(spdx) else ""))
        error = (LicenceError("aircraft.licence_dataset", reason) if aircraft
                 else LicenceError("asset.licence", reason))
    refusal = None if error is None else error.constraint
    reason = None if error is None else error.message
    if not shipped:
        verdict = "not shipped"
    else:
        verdict = "refused" if refusal else "allowed"
    return {"verdict": verdict, "refusal": refusal if shipped else None,
            "would_refuse": refusal, "reason": reason,
            "distribution": dict(allowed) if allowed else None,
            "obligations": obligations}


def gate(runs: Iterable[Tuple[str, Sequence[Dict[str, Any]], Dict[str, bool]]]
         ) -> Dict[str, Any]:
    """The per-asset verdicts over ``(run name, its asset records, what the
    export ships of it)``: one verdict per distinct (asset, licence),
    shipped when any run ships it, each with its runs and why. Returns
    ``{"verdicts": [...], "refused": [...]}``; :func:`enforce` raises."""
    merged: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
    for run_name, assets, ships in runs:
        for entry in assets:
            key = (str(entry["asset"]), entry.get("licence"))
            shipped, why = shipped_reason(entry, ships)
            slot = merged.setdefault(key, {**entry, "runs": [], "shipped": False,
                                           "shipped_as": []})
            slot["runs"].append(run_name)
            if shipped:
                slot["shipped"] = True
                if why not in slot["shipped_as"]:
                    slot["shipped_as"].append(why)
            elif not slot["shipped"] and why not in slot["shipped_as"]:
                slot["shipped_as"].append(why)
    verdicts = []
    for key in sorted(merged, key=lambda k: (k[0], str(k[1]))):
        slot = merged[key]
        if slot["shipped"]:
            slot["shipped_as"] = [w for w in slot["shipped_as"]
                                  if not w.startswith(("no ", "the run's", "nothing"))]
        slot.update(verdict_for(slot, slot["shipped"]))
        verdicts.append(slot)
    return {"verdicts": verdicts,
            "refused": [v for v in verdicts if v["verdict"] == "refused"],
            "allow_list": {k: dict(v) for k, v in ALLOW_LIST.items()},
            "rule": ("an asset ships when the export carries what it reaches (rendered "
                     "pixels or engine label files of a run the engine drew -- for an "
                     "airframe, only a drawn mesh -- or a label derived from it); a shipped "
                     "asset with no licence record, one forbidding machine-learning use, "
                     "or one off the allow-list refuses the export by name before any "
                     "file is written"),
            "not_claimed": list(NOT_CLAIMED)}


def enforce(result: Dict[str, Any]) -> None:
    """Raise the first refusal (sorted by asset) by its name, naming every
    refused asset; nothing when every shipped asset is allowed."""
    refused = result["refused"]
    if not refused:
        return
    first = refused[0]
    others = "; ".join(f"{v['asset']} ({v['refusal']})" for v in refused[1:])
    raise LicenceError(first["refusal"],
                       f"{first['reason']}; it would ship as {', '.join(first['shipped_as'])}"
                       + (f". Also refused: {others}" if others else "")
                       + ". Nothing was written (the verdicts are the records' words, "
                         "not legal advice)")


def gate_record(result: Dict[str, Any], labels_changed: int, labels_total: int):
    """The ``dataset.licences`` record (record 2): the per-asset verdicts,
    and the null test ``bounded`` -- the gate changes no label (the label
    records that differ before and after the gate ran, measured by the
    export, against 0)."""
    from ..records import AppliedVariable, Model, NullTest

    counts = {v: sum(1 for e in result["verdicts"] if e["verdict"] == v) for v in VERDICTS}
    return AppliedVariable(
        name="dataset.licences", value="refused" if result["refused"] else "allowed",
        unit="verdict", source="derived",
        model="per-asset licence gate: records against a stated allow-list",
        parameters={"verdicts": [{k: e.get(k) for k in ("asset", "kind", "licence", "spdx",
                                                        "ml_use", "verdict", "refusal")}
                                 for e in result["verdicts"]],
                    "counts": counts, "labels_total": int(labels_total)},
        references=("core/assets/licence.py ALLOW_LIST (a stated table)",),
        null_test=NullTest(
            quantity="exported label records changed by the gate", unit="record",
            with_value=float(labels_changed), without_value=0.0, threshold=0.0,
            kind="bounded",
            note=f"the {labels_total} label records' digests before and after the gate ran; "
                 f"the gate reads licence records and writes none of a label"),
        model_block=Model(name="per-asset licence gate", standard="none (a stated allow-list)",
                          version="W4", parameters={"allow_list": sorted(ALLOW_LIST)},
                          references=("core/assets/licence.py",)),
        frm="the assets' own licence records (configs, sidecars, documents)",
        std="none: the records' words, not legal advice",
        not_claimed=NOT_CLAIMED)
