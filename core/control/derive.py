"""Build a TECS-equipped aircraft from a stock one, without editing the stock file.

The autopilot has to live inside the aircraft model (§5 Phase 2) so it runs at
FDM rate and travels with the airframe. But editing a stock JSBSim XML in place
would destroy the thing that makes a run traceable: the SHA-256 of the model we
claim to have flown.

So the stock file is never touched. A *derived* aircraft is generated into
``build/aircraft/<name>-tecs/``, containing

    <name>-tecs.xml      the stock XML with one <system file="tecs"/> added
    Systems/tecs.xml     the controller, with per-airframe throttle outputs

and the manifest records the hash of the stock file, the hash of the controller
template, and the hash of the generated result. Anyone can regenerate it and
compare.

The controller is a template for exactly one reason: engine count is a property
of the airframe. The B747 has four engines and the global5000 two, and a
hand-written output list would silently drive only some of them -- a §2.7
failure that would look like an underpowered aircraft rather than a bug.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from ..fdm import aircraft as ac
from ..fdm.errors import FDMError

#: The controller template, versioned with the repository.
TECS_TEMPLATE = Path(__file__).parent / "systems" / "tecs.xml"

#: Where generated aircraft land. Gitignored: they are reproducible artefacts,
#: not source, and checking them in would invite editing the copy.
DEFAULT_BUILD_DIR = Path(__file__).resolve().parents[2] / "build" / "aircraft"

SUFFIX = "-tecs"


class DerivationError(FDMError):
    """The derived aircraft could not be built."""


@dataclass(frozen=True)
class DerivedAircraft:
    """A generated, TECS-equipped aircraft and everything needed to trust it."""

    name: str                  #: e.g. "B747-tecs"
    base_name: str             #: e.g. "B747"
    aircraft_path: Path        #: directory to hand JSBSim as the aircraft path
    xml_path: Path
    engine_path: Path
    systems_path: Path
    engine_count: int
    base_sha256: str
    template_sha256: str
    derived_sha256: str

    def provenance(self) -> Dict[str, object]:
        return {
            "derived_from": self.base_name,
            "base_sha256": self.base_sha256,
            "tecs_template_sha256": self.template_sha256,
            "derived_sha256": self.derived_sha256,
            "engine_count": self.engine_count,
        }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _count_engines(xml_text: str) -> int:
    """Engines declared in the stock model's <propulsion> section."""
    propulsion = re.search(r"<propulsion.*?</propulsion>", xml_text, re.S)
    if not propulsion:
        return 0
    return len(re.findall(r"<engine\b", propulsion.group(0)))


def _throttle_outputs(engine_count: int) -> str:
    """One <output> per engine, indexed the way JSBSim stores them.

    Index 0 is unsubscripted -- ``fcs/throttle-cmd-norm`` -- and only later
    engines carry a subscript. Writing ``[0]`` would work by aliasing but would
    not match the catalog, so the unsubscripted form is used.
    """
    lines = []
    for i in range(engine_count):
        prop = "fcs/throttle-cmd-norm" if i == 0 else f"fcs/throttle-cmd-norm[{i}]"
        lines.append(f"    <output> {prop} </output>")
    return "\n".join(lines)


def _insert_system(xml_text: str) -> str:
    """Add ``<system file="tecs"/>`` ahead of the aircraft's own flight control.

    Order matters. TECS writes ``fcs/*-cmd-norm``; the aircraft's
    ``<flight_control>`` reads those and drives the surfaces. Loading the
    controller first means a command reaches the actuator on the same step
    rather than one step late.
    """
    marker = '\n    <system file="tecs"/>\n'
    for anchor in ("<flight_control", "<autopilot", "<ground_reactions"):
        idx = xml_text.find(anchor)
        if idx != -1:
            line_start = xml_text.rfind("\n", 0, idx) + 1
            return xml_text[:line_start] + marker + xml_text[line_start:]
    raise DerivationError(
        "could not find <flight_control>, <autopilot> or <ground_reactions> in "
        "the stock aircraft; refusing to guess where the controller belongs"
    )


def derive(
    base_aircraft: str,
    build_dir: Optional[Path] = None,
    root_dir: Optional[Path] = None,
) -> DerivedAircraft:
    """Generate a TECS-equipped copy of ``base_aircraft``.

    Idempotent: regenerating from the same inputs produces byte-identical
    output, so the derived hash is a stable part of the run manifest.
    """
    base = ac.resolve(base_aircraft, root_dir)
    build_dir = Path(build_dir) if build_dir else DEFAULT_BUILD_DIR

    base_text = base.xml_path.read_text()
    template_text = TECS_TEMPLATE.read_text()

    engine_count = _count_engines(base_text)
    if engine_count == 0:
        raise DerivationError(
            f"{base_aircraft!r} declares no engines; TECS commands thrust and "
            f"cannot be attached to an unpowered model"
        )
    if "<!--THROTTLE_OUTPUTS-->" not in template_text:
        raise DerivationError(
            f"{TECS_TEMPLATE} has no THROTTLE_OUTPUTS placeholder; the throttle "
            f"would drive no engines at all"
        )

    system_text = template_text.replace(
        "<!--THROTTLE_OUTPUTS-->", _throttle_outputs(engine_count)
    )
    derived_text = _insert_system(base_text)

    name = f"{base.name}{SUFFIX}"
    aircraft_dir = build_dir / name
    systems_dir = aircraft_dir / "Systems"
    systems_dir.mkdir(parents=True, exist_ok=True)

    xml_path = aircraft_dir / f"{name}.xml"
    xml_path.write_text(derived_text)
    (systems_dir / "tecs.xml").write_text(system_text)

    # Aircraft-local files the stock model may reference by relative name.
    for sibling in base.xml_path.parent.iterdir():
        if sibling.is_file() and sibling != base.xml_path:
            shutil.copy2(sibling, aircraft_dir / sibling.name)

    return DerivedAircraft(
        name=name,
        base_name=base.name,
        aircraft_path=build_dir,
        xml_path=xml_path,
        engine_path=base.root_dir / "engine",
        systems_path=base.root_dir / "systems",
        engine_count=engine_count,
        base_sha256=base.sha256,
        template_sha256=_sha256_text(template_text),
        derived_sha256=_sha256_text(derived_text),
    )
