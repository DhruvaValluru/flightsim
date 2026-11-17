"""Look-dev recipe, batches 1+2 (p3-monolith, 2026-11-15): sky, haze and
default-cumulus values found live in the editor (runs/lookdev/LOG.md).

Pure Python, no Unreal. p3-mac ports these to core/scene/world_beauty.py and
the C++ twins in FlightSimClouds.cpp (FlightSimWorldPure). Every value is
RELATIVE (editor viewport) and UNMEASURED until measure_lookdev.ps1 has run on
the Windows laptop.

Run the self-check:  python runs/lookdev/recipes/lookdev_sky.py
"""
from typing import Dict

# -- 1. altitude blend --------------------------------------------------------
# At cruise the camera looks DOWN through the ~1.2 km aerosol layer to a
# ~350 km horizon; at 600 m it sits inside it. The same haze numbers cannot
# serve both (s03_ld002: batch-1 cruise haze at 600 m = grey smog, ~15 km).
LOW_AGL_M = 1000.0        # at or below: the low-altitude row
CRUISE_AGL_M = 6000.0     # at or above: the cruise row
FOG_ZERO_AGL_M = 4000.0   # the height fog is gone by here (dark-horizon fix)

LOW = dict(fog_density=0.0003,            # was 0.0012 (s03_ld003)
           mie_scattering_per_km=0.0455,  # unchanged at low altitude
           aerial_perspective_scale=1.0)  # unchanged at low altitude
CRUISE = dict(fog_density=0.0,             # was 0.0012 (s13_ld002: the dark band)
              mie_scattering_per_km=0.09,  # was 0.0455 (s13_ld003)
              aerial_perspective_scale=2.0)  # was 1.0 (s13_ld003)


def _smooth(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def haze_for_agl(agl_m: float) -> Dict[str, float]:
    """Fog density, Mie scattering (1/km) and aerial-perspective scale for a
    camera height above ground. Fog fades on its own (faster) ramp."""
    t = _smooth((agl_m - LOW_AGL_M) / (CRUISE_AGL_M - LOW_AGL_M))
    tf = _smooth((agl_m - LOW_AGL_M) / (FOG_ZERO_AGL_M - LOW_AGL_M))
    return dict(
        fog_density=LOW["fog_density"] * (1.0 - tf),
        mie_scattering_per_km=LOW["mie_scattering_per_km"]
        + (CRUISE["mie_scattering_per_km"] - LOW["mie_scattering_per_km"]) * t,
        aerial_perspective_scale=LOW["aerial_perspective_scale"]
        + (CRUISE["aerial_perspective_scale"] - LOW["aerial_perspective_scale"]) * t,
    )
# Note: the Mie ABSORPTION keeps its share (mie_split: absorption follows
# scattering at mie_share 0.6), i.e. scale it with the same factor.


# -- 2. global sky changes (both altitudes held: s13_ld004, s03_ld003) ---------
MIE_ANISOTROPY = 0.6                  # was 0.8 (world_beauty atmosphere row)
SKY_MULTI_SCATTERING_CLEAR = 1.5      # was 1.25 in SKY_MULTI_SCATTERING["clear"]
# AND apply it on the constrained GPU too: FlightSimClouds.cpp ~1787 skips
# SetMultiScatteringFactor when CloudConstrainedGpu(), so the render laptop
# (Intel iGPU) renders 1.0 (render.json multi_scattering_factor = 1). It only
# scales the multi-scattering LUT: no per-pixel cost.

# -- 3. default cumulus (world_beauty CLOUD_ROWS["cumulus"] + the billow row) --
# The rendered row is the BILLOW row (-look-cloud-billow=on default):
# contrast = 0.9 x CloudBillowContrastGain (2.25), detail 0.15 km, erosion 0.5.
CUMULUS = dict(
    shape_scale_km=1.2,       # was 2.5  : 2-5 km pancakes -> 0.5-1.5 km cells
    coverage_contrast=1.2,    # was 2.25 rendered (billow gain) : hard cookie-cutter edges
    detail_scale_km=0.12,     # was 0.15 rendered (billow) : cauliflower turrets
    detail_erosion=0.85,      # was 0.5 rendered (billow)
    top_rounding=0.5,         # was 0.75 : every cell a smooth pillow
    extinction_per_m=0.08,    # was 0.05 : shaded grey sides under bright tops
    default_cover=0.45,       # was 0.35 : cruise view (scene 13); scene 3 judged at 0.35
)
# With billow on, set the BILLOW constants so the rendered row is the above:
#   CloudBillowContrastGain -> 1.2 / 0.9 = 1.333 (or contrast row 1.2 with gain 1)
#   CloudBillowDetailScaleKm -> 0.12 ; CloudBillowErosion -> 0.85
CUMULUS_MAX_THICKNESS_M = 1800.0      # was 2000 (CLOUD_MAX_THICKNESS_M["cumulus"]);
#   the lowered default layer 1500-2700 m -> 1500-3300 m (scene 13); scene 3's
#   2000-5000 m layer must also be capped to 1.8 km (it drew a 3 km wall).
CLOUD_HEIGHT_DENSITY = 0.6            # KEEP: 0 gives boxy columns (s03_ld005)
SUN_CAST_CLOUD_SHADOWS_CLEAR = True   # was False (sun_shafts.sun.cast_cloud_shadows)

# -- 4. not changed, open --------------------------------------------------------
# Exposure: editor +1 EV matched the photo (s13_ld007), but the editor lacks the
#   hero lighting and beauty fallback; decide only from a Windows render.
# Mid-height dark streaks in cells (s03_ld004-008): probably the editor's
#   UNJITTERED fixed-slice march (world_beauty clouds round 6: the render
#   jitters it, cloud_march_jittered). Check them on the Windows frame first;
#   only if they show there, look at cloud_layers.hlsl body/wisp transition.
# Sun block: RESOLVED (LOG.md "Sun-block check"): look_applied.sun is a stale record;
#   the sky plan (89.88 deg / 120000 lux) lights scene 13 (FlightSimSky.cpp:235-239).


if __name__ == "__main__":
    for agl in (300, 600, 1000, 2000, 3000, 4000, 6000, 10000):
        h = haze_for_agl(agl)
        print("%6d m  fog %.5f  mie %.4f /km  AP %.2f" % (
            agl, h["fog_density"], h["mie_scattering_per_km"], h["aerial_perspective_scale"]))
    assert haze_for_agl(600) == dict(fog_density=0.0003, mie_scattering_per_km=0.0455,
                                     aerial_perspective_scale=1.0)
    assert haze_for_agl(10000)["fog_density"] == 0.0
    assert abs(haze_for_agl(10000)["mie_scattering_per_km"] - 0.09) < 1e-9
    print("ok")
