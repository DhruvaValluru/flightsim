"""Aircraft resolution: one lookup, verified after load.

The previous build had two independent lookups for the aircraft -- one for the
flight model and one for the visual mesh -- with no consistency check between
them, and shipped a clip whose HUD read ``FDM JSBSIM F16 - MODEL F-15``
(§1.4). JSBSim ships both ``f15`` and ``f16``, so this was a silent
substitution, not a missing asset.

This module is the single lookup. It resolves a name to exactly one on-disk
model directory, refuses to guess when the name does not match, records the
hash and licence metadata needed for the provenance manifest (§7.4) and the
credibility scorecard (§7.1), and -- critically -- verifies after load that the
model JSBSim actually instantiated is the one that was asked for.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .errors import AircraftMismatchError, AircraftResolutionError


def default_root_dir() -> Path:
    """The aircraft/engine/systems root shipped with the installed jsbsim wheel."""
    import jsbsim

    return Path(jsbsim.get_default_root_dir())


@dataclass(frozen=True)
class AircraftModel:
    """An on-disk JSBSim aircraft, resolved and fingerprinted.

    Frozen: once resolved, nothing may retarget a run onto a different airframe.
    """

    name: str
    root_dir: Path
    xml_path: Path
    sha256: str
    #: ``release`` attribute of ``<fdm_config>``: ALPHA / BETA / PRODUCTION, or None.
    release: Optional[str]
    #: ``licenseName`` from ``<fileheader><license>``, or None if the file
    #: declares none. Stock aircraft are inconsistent here and the engine's
    #: LGPL does not cover them (§3.3).
    license_name: Optional[str]
    license_url: Optional[str]
    authors: List[str]
    description: Optional[str]
    #: The ``<note>`` block. Every stock model carries a disclaimer that it is
    #: validated "only to the extent that it seems to fly right". Surfaced so
    #: that docs/VALIDITY.md can quote it rather than paraphrase it.
    note: Optional[str]

    @property
    def has_declared_license(self) -> bool:
        return self.license_name is not None

    def provenance(self) -> dict:
        """The subset recorded in a run manifest (§7.4)."""
        return {
            "name": self.name,
            "xml_path": str(self.xml_path),
            "sha256": self.sha256,
            "release": self.release,
            "license_name": self.license_name,
            "license_url": self.license_url,
            "authors": list(self.authors),
        }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _text(node: Optional[ET.Element]) -> Optional[str]:
    if node is None or node.text is None:
        return None
    collapsed = " ".join(node.text.split())
    return collapsed or None


def available(root_dir: Optional[Path] = None) -> List[str]:
    """Every aircraft name under ``root_dir/aircraft`` that has a matching XML.

    A directory whose XML is missing or differently named is not listed, so it
    can never be resolved by accident.
    """
    root = Path(root_dir) if root_dir is not None else default_root_dir()
    ac_dir = root / "aircraft"
    if not ac_dir.is_dir():
        return []
    return sorted(
        d.name for d in ac_dir.iterdir() if d.is_dir() and (d / f"{d.name}.xml").is_file()
    )


def resolve(name: str, root_dir: Optional[Path] = None) -> AircraftModel:
    """Resolve ``name`` to exactly one on-disk model. Never substitutes.

    Raises
    ------
    AircraftResolutionError
        If the name does not correspond to a directory containing a matching
        XML. The message lists case-insensitive near-matches to make typos
        obvious, but the resolver will not silently accept any of them.
    """
    root = Path(root_dir) if root_dir is not None else default_root_dir()
    xml_path = root / "aircraft" / name / f"{name}.xml"

    if not xml_path.is_file():
        names = available(root)
        lowered = name.lower()
        near = [n for n in names if n.lower() == lowered] or [
            n for n in names if lowered in n.lower() or n.lower() in lowered
        ]
        hint = f" Did you mean one of {near}?" if near else ""
        raise AircraftResolutionError(
            f"No JSBSim aircraft named {name!r} under {root / 'aircraft'} "
            f"(expected {xml_path}).{hint} "
            f"{len(names)} models are available; this resolver does not "
            f"substitute a similar one."
        )

    tree = ET.parse(xml_path)
    cfg = tree.getroot()
    header = cfg.find("fileheader")
    lic = header.find("license") if header is not None else None

    return AircraftModel(
        name=name,
        root_dir=root,
        xml_path=xml_path,
        sha256=_sha256(xml_path),
        release=cfg.get("release"),
        license_name=lic.get("licenseName") if lic is not None else None,
        license_url=lic.get("licenseURL") if lic is not None else None,
        authors=[
            t
            for t in (_text(a) for a in (header.findall("author") if header is not None else []))
            if t
        ],
        description=_text(header.find("description")) if header is not None else None,
        note=_text(header.find("note")) if header is not None else None,
    )


def verify_loaded(exec_, model: AircraftModel) -> None:
    """Assert JSBSim instantiated the model we resolved. The §1.4 guard.

    ``FGFDMExec.load_model`` returns True on success, but the previous build's
    failure was not a failed load -- it was a *successful* load of the wrong
    airframe. This compares the name the executive reports against the name we
    resolved on disk.
    """
    loaded = exec_.get_model_name()
    if loaded != model.name:
        raise AircraftMismatchError(
            f"Requested aircraft {model.name!r} (from {model.xml_path}) but "
            f"JSBSim reports the loaded model as {loaded!r}. Refusing to run: "
            f"this is the aircraft-substitution failure that shipped F-16 "
            f"aerodynamics under an F-15 mesh."
        )
