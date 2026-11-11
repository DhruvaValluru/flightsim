"""The landing gear at the start of an airborne run: one rule for the headless
FDM (core.fdm.FlightDynamics) and the Unreal host (the run card's
``start_gear_up``), so the two cannot drift.

An aircraft that STARTS in the air above GEAR_UP_AGL_FT with retractable gear
(its JSBSim XML declares ``<retractable>1</retractable>``) starts gear-up:
JSBSim's own default is gear extended, which flew a 747 cruising at 10 km with
its gear down (visual round 10, #13) -- a wrong initial condition, not
physics: the flight is still JSBSim's, from a clean configuration. A prompt
or scenario name that says the gear is down, or an approach, landing,
touchdown, final, take-off or departure, keeps JSBSim's default. Fixed gear
(c172p, DHC6) never retracts.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Optional

#: Above this height over the terrain an airborne start retracts the gear
#: (the value the repo-owned airframes already used).
GEAR_UP_AGL_FT = 100.0
#: Words that keep the gear down (whole words, case-insensitive).
GEAR_DOWN_WORDS = re.compile(
    r"\b(gear[\s-]*down|land(?:s|ing|ed)?|approach(?:es|ing)?|touch[\s-]*down|final|"
    r"take[\s-]*off|takeoff|departure|departing|go[\s-]*around)\b", re.IGNORECASE)
_RETRACTABLE = re.compile(r"<retractable>\s*1\s*</retractable>")


@functools.lru_cache(maxsize=64)
def _xml_has_retractable_gear(xml_path: str) -> bool:
    try:
        return bool(_RETRACTABLE.search(Path(xml_path).read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return False


def has_retractable_gear(aircraft: str) -> bool:
    """Whether the airframe's own JSBSim XML declares a retractable gear unit."""
    from . import aircraft as ac

    try:
        return _xml_has_retractable_gear(str(ac.resolve(aircraft).xml_path))
    except Exception:   # an unknown airframe: validate() names it; never retract a guess
        return False


#: A/B override (round 50, #09's GPU hang bisect): ``-start-gear=down`` in
#: FLIGHTSIM_RENDER_SWITCHES (what visual_fix_round.ps1 -Switches sets) keeps
#: JSBSim's gear-down start for every airframe, in the headless FDM and the
#: run card alike, so the two cannot drift. ``auto`` (or absent) is the rule.
START_GEAR_SWITCH = re.compile(r"(?:^|\s)-start-gear=(\S+)")


def start_gear_override() -> Optional[str]:
    """``"down"`` or ``"auto"`` from FLIGHTSIM_RENDER_SWITCHES; a bad word is refused."""
    import os

    m = START_GEAR_SWITCH.search(os.environ.get("FLIGHTSIM_RENDER_SWITCHES", ""))
    if not m:
        return None
    word = m.group(1).lower()
    if word not in ("down", "auto"):
        raise ValueError(f"-start-gear={m.group(1)}: expected down or auto")
    return word


def gear_down_requested(*texts: Optional[str]) -> bool:
    """Whether any of the texts (the prompt, the scenario name) asks for the gear
    down, or the -start-gear=down A/B switch is set."""
    if start_gear_override() == "down":
        return True
    return any(t and GEAR_DOWN_WORDS.search(t) for t in texts)


def start_gear_up(aircraft: str, altitude_m: float, terrain_m: float, *texts: Optional[str]) -> bool:
    """The rule: airborne above GEAR_UP_AGL_FT, retractable gear, no gear-down words."""
    agl_ft = (float(altitude_m) - float(terrain_m)) / 0.3048
    return agl_ft > GEAR_UP_AGL_FT and has_retractable_gear(aircraft) and not gear_down_requested(*texts)
