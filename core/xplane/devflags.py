"""Developer-only X-Plane comparison switches (E5).

These three environment variables are a developer's and the test
suite's, never a settings-panel row: the web path (webapp/) calls the
functions here and spells none of the names itself, so a grep of
webapp/*.py for the three X-Plane switch names stays empty. The semantics
are the ones webapp/runs.py had before the move:

* ``FLIGHTSIM_XPLANE_TERRAIN=off`` keeps the scene's own texture
  (Sentinel-2 drape where one was baked, the engine's vertex
  classification otherwise). The test suite sets it.
* ``FLIGHTSIM_XPLANE_LIGHTING=off`` disables the lighting flags (the test
  suite sets it so pinned render commands do not depend on whether this
  machine has an X-Plane extraction).
* ``FLIGHTSIM_XPLANE_SKY`` chooses where the clear-sky colours come from:
  "model" (the default) computes them from the simulator's atmosphere
  model (core.xplane.atmosphere: Bruneton's parameter set, the one its
  atmosphere shader takes) for a sun high enough for single scattering
  to be trusted; "tables" reads the decoded sky_colors tables for every
  sun. Overcast (the storm look), haze and twilight always read the
  tables: the model has no clouds, no haze knob and no multiple
  scattering, and the tables were measured for exactly those.
"""

from __future__ import annotations

import os
from typing import Optional

XPLANE_TERRAIN_ENV = "FLIGHTSIM_XPLANE_TERRAIN"
XPLANE_LIGHTING_ENV = "FLIGHTSIM_XPLANE_LIGHTING"
XPLANE_SKY_ENV = "FLIGHTSIM_XPLANE_SKY"
XPLANE_SKY_SOURCES = ("model", "tables")


def terrain_off() -> bool:
    """True when the developer switch keeps the scene's own texture."""
    return os.environ.get(XPLANE_TERRAIN_ENV, "").strip().lower() == "off"


def lighting_off() -> bool:
    """True when the developer switch disables the X-Plane lighting flags."""
    return os.environ.get(XPLANE_LIGHTING_ENV, "").strip().lower() == "off"


def sky_choice() -> Optional[str]:
    """The clear-sky colour source the environment names, lower-cased, or
    None when it names none (the caller's default is "model"); the word
    is not validated here, the caller refuses an unknown one by name."""
    raw = os.environ.get(XPLANE_SKY_ENV, "").strip().lower()
    return raw or None
