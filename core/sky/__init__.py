"""The sky: where the sun, moon and stars are, and how the camera exposes.

Visual-only by construction. Nothing here feeds the flight dynamics; it
decides what the render host draws and how it meters, from the spec's
place, date and time, and every value rides into the render manifest.

* :mod:`core.sky.astro` -- solar, lunar and stellar positions (Meeus /
  NOAA low-precision series, no ephemeris dependency).
* :mod:`core.sky.plan` -- the ``sky.json`` sidecar the UE host reads:
  sun and moon directions and illuminances, the star field, EV100
  exposure, the cloud layer and per-camera post-processing.
"""
