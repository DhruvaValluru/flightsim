"""Sun shafts and sky occlusion: the beauty look's crepuscular rays, cloud
shadow on the atmosphere, cloud ambient occlusion on the sky light, a
deterministic full-resolution real-time sky capture and, for stills, a finer
volumetric-fog grid.

Visual overhaul, module ``sun-shafts-sky-occlusion`` (2026-11-09). BEAUTY ONLY:
``FFlightSimWorldBeauty::Build`` (FlightSimClouds.cpp) applies it once after the
world presets, and the render commandlet calls ``Build`` only under
``-quality=beauty`` or ``-quality=pathtrace``; ``-quality=measure`` never
constructs it. Nothing here reaches an equation of motion.

This module is the Python twin of the pure block in
``ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimSunShafts.cpp``
(between ``FLIGHTSIM-SUNSHAFTS-PURE-BEGIN`` and ``FLIGHTSIM-SUNSHAFTS-PURE-END``).
``tests/test_sun_shafts.py`` parses (and, where a C++ compiler exists, compiles)
that block and checks it against this file, row for row.

VALUE-ONLY. Everything here changes radiance (how bright a pixel is), never
where a surface is drawn: no geometry, no camera, no post-process warp. It is
NOT in ``PIXEL_MOVING_KEYS``. The label captures read stencil, depth, normal or
base colour through their own post-process materials, and draw no fog,
atmosphere or cloud. The module spec said a Gate V bloom-ceiling check already
measures the mean mask-edge luminance change; no such clause exists
(``experiments/gate_v_visual.py`` has no bloom metric, grepped 2026-11-09).
What does cover it: ``experiments/look_label_check.py`` measures the mask edge
against the beauty's silhouette, and a radiance change symmetric about an edge
does not move it; the probe log asks for a label-bytes A/B with the module on
and off (## sun-shafts-sky-occlusion).

EVERY number below is UNCALIBRATED: chosen on a Mac that cannot render, from
the engine's own defaults and orders of magnitude, never from a frame. The
probes that should set them are in ``docs/visual/PROBE_LOG.md``
(## sun-shafts-sky-occlusion).

The sun's apparent position needs nothing here: ``core/environment/sun.py``
already applies the NOAA piecewise refraction (``_refraction_deg``) and
``solar_position`` returns the apparent elevation.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

#: The world presets, in FlightSimWorldPure order (core/scene/world_beauty.PRESETS).
PRESETS: Tuple[str, ...] = ("clear", "hazy", "overcast", "rain", "storm")

#: The cost tiers. still = the frame accumulates (-still-samples, the path
#: tracer, -accumulate, or -sun-shafts-tier=still); interactive = engine
#: defaults for anything that costs per frame.
TIERS: Tuple[str, ...] = ("still", "interactive")

#: The table's columns, in the C++ enum's order (FlightSimSunShaftsPure::Field*).
FIELDS: Tuple[str, ...] = (
    "shaft_occlusion_darkness",       # UDirectionalLightComponent::OcclusionMaskDarkness (1 = no darkening)
    "shaft_occlusion_depth_range_m",  # OcclusionDepthRange (cm in the engine): nearer than this occludes shafts
    "shaft_bloom_scale",              # ULightComponent::BloomScale
    "shaft_bloom_threshold",          # BloomThreshold (scene colour, after exposure)
    "shaft_bloom_max",                # BloomMaxBrightness
    "cloud_shadow_on_atmosphere",     # CloudShadowOnAtmosphereStrength: the crepuscular rays
    "cloud_shadow_on_surface",        # CloudShadowOnSurfaceStrength
    "cloud_shadow_extent_km",         # CloudShadowExtent (km radius around the camera)
    "cloud_shadow_map_res_scale",     # CloudShadowMapResolutionScale (base 512)
    "cloud_shadow_ray_sample_scale",  # CloudShadowRaySampleCountScale
    "sky_ao_strength",                # USkyLightComponent::CloudAmbientOcclusionStrength
    "sky_ao_extent_km",               # CloudAmbientOcclusionExtent (km)
    "sky_ao_map_res_scale",           # CloudAmbientOcclusionMapResolutionScale (base 512)
    "sky_ao_aperture_scale",          # CloudAmbientOcclusionApertureScale (1 = whole hemisphere)
    "vfog_grid_px",                   # r.VolumetricFog.GridPixelSize (still tier only)
    "vfog_grid_z",                    # r.VolumetricFog.GridSizeZ (still tier only)
)

# Engine defaults (UE 5.7.4), for scale: OcclusionMaskDarkness 0.05, OcclusionDepthRange
# 100000 cm, BloomScale 0.2, BloomThreshold 8, BloomMaxBrightness 100, cloud shadow
# strengths 1, CloudShadowExtent 150 km, cloud AO strength 1, extent 150 km, aperture
# 0.05, r.VolumetricFog.GridPixelSize 16, GridSizeZ 64.
#
# Clear and hazy: a visible sun, so a strong atmosphere cloud shadow (the shafts under
# cumulus and at golden hour) and a light-shaft bloom about the engine's 0.2; the sky
# AO light (the ground under fair cumulus stays lit). Overcast, rain, storm: no sun
# disc, so the shaft bloom is (near) zero, and the sky AO full (darker ground under the
# deck). Every value UNCALIBRATED.
SHAFT_PRESETS: Dict[str, Dict[str, float]] = {
    "clear": {
        "shaft_occlusion_darkness": 0.4,
        "shaft_occlusion_depth_range_m": 20000.0,
        "shaft_bloom_scale": 0.2,
        "shaft_bloom_threshold": 8.0,
        "shaft_bloom_max": 100.0,
        "cloud_shadow_on_atmosphere": 1.0,
        "cloud_shadow_on_surface": 1.0,
        "cloud_shadow_extent_km": 150.0,
        "cloud_shadow_map_res_scale": 2.0,
        "cloud_shadow_ray_sample_scale": 2.0,
        "sky_ao_strength": 0.5,
        "sky_ao_extent_km": 150.0,
        "sky_ao_map_res_scale": 2.0,
        "sky_ao_aperture_scale": 0.05,
        "vfog_grid_px": 4.0,
        "vfog_grid_z": 128.0,
    },
    "hazy": {
        "shaft_occlusion_darkness": 0.3,
        "shaft_occlusion_depth_range_m": 20000.0,
        "shaft_bloom_scale": 0.25,
        "shaft_bloom_threshold": 6.0,
        "shaft_bloom_max": 100.0,
        "cloud_shadow_on_atmosphere": 1.0,
        "cloud_shadow_on_surface": 1.0,
        "cloud_shadow_extent_km": 150.0,
        "cloud_shadow_map_res_scale": 2.0,
        "cloud_shadow_ray_sample_scale": 2.0,
        "sky_ao_strength": 0.6,
        "sky_ao_extent_km": 150.0,
        "sky_ao_map_res_scale": 2.0,
        "sky_ao_aperture_scale": 0.05,
        "vfog_grid_px": 4.0,
        "vfog_grid_z": 128.0,
    },
    "overcast": {
        "shaft_occlusion_darkness": 0.6,
        "shaft_occlusion_depth_range_m": 5000.0,
        "shaft_bloom_scale": 0.0,
        "shaft_bloom_threshold": 16.0,
        "shaft_bloom_max": 10.0,
        "cloud_shadow_on_atmosphere": 0.6,
        "cloud_shadow_on_surface": 0.8,
        "cloud_shadow_extent_km": 100.0,
        "cloud_shadow_map_res_scale": 2.0,
        "cloud_shadow_ray_sample_scale": 2.0,
        "sky_ao_strength": 1.0,
        "sky_ao_extent_km": 100.0,
        "sky_ao_map_res_scale": 2.0,
        "sky_ao_aperture_scale": 0.1,
        "vfog_grid_px": 4.0,
        "vfog_grid_z": 128.0,
    },
    "rain": {
        "shaft_occlusion_darkness": 0.6,
        "shaft_occlusion_depth_range_m": 5000.0,
        "shaft_bloom_scale": 0.02,
        "shaft_bloom_threshold": 16.0,
        "shaft_bloom_max": 10.0,
        "cloud_shadow_on_atmosphere": 0.5,
        "cloud_shadow_on_surface": 0.8,
        "cloud_shadow_extent_km": 80.0,
        "cloud_shadow_map_res_scale": 2.0,
        "cloud_shadow_ray_sample_scale": 2.0,
        "sky_ao_strength": 1.0,
        "sky_ao_extent_km": 80.0,
        "sky_ao_map_res_scale": 2.0,
        "sky_ao_aperture_scale": 0.1,
        "vfog_grid_px": 4.0,
        "vfog_grid_z": 128.0,
    },
    "storm": {
        "shaft_occlusion_darkness": 0.7,
        "shaft_occlusion_depth_range_m": 5000.0,
        "shaft_bloom_scale": 0.0,
        "shaft_bloom_threshold": 16.0,
        "shaft_bloom_max": 10.0,
        "cloud_shadow_on_atmosphere": 0.5,
        "cloud_shadow_on_surface": 0.9,
        "cloud_shadow_extent_km": 80.0,
        "cloud_shadow_map_res_scale": 2.0,
        "cloud_shadow_ray_sample_scale": 2.0,
        "sky_ao_strength": 1.0,
        "sky_ao_extent_km": 80.0,
        "sky_ao_map_res_scale": 2.0,
        "sky_ao_aperture_scale": 0.1,
        "vfog_grid_px": 4.0,
        "vfog_grid_z": 128.0,
    },
}

#: The fog-grid cvars, fed from the preset row, written on the still tier only.
VFOG_GRID_CVARS: Dict[str, str] = {
    "vfog_grid_px": "r.VolumetricFog.GridPixelSize",
    "vfog_grid_z": "r.VolumetricFog.GridSizeZ",
}

#: Still tier: the frame accumulates, so the per-frame cost buys quality. Each
#: name was grepped in the UE 5.7.4 Renderer source (2026-11-09):
#: VolumetricFog.cpp, VolumetricCloudRendering.cpp,
#: ReflectionEnvironmentRealTimeCapture.cpp, LightShaftRendering.cpp.
#: Values UNCALIBRATED. The commandlet's beauty block also sets
#: r.VolumetricCloud.HighQualityAerialPerspective 1 later (the same value).
STILL_CVARS: Dict[str, float] = {
    "r.VolumetricFog.HistoryMissSupersampleCount": 16.0,   # default 4, valid [1, 16]
    "r.VolumetricCloud.ShadowMap": 1.0,
    "r.VolumetricCloud.SkyAO": 1.0,
    "r.VolumetricCloud.HighQualityAerialPerspective": 1.0,
    "r.VolumetricCloud.Shadow.SampleAtmosphericLightShadowmap": 1.0,
    "r.SkyLight.RealTimeReflectionCapture.TimeSlice": 0.0,  # the whole capture every frame: deterministic
    "r.SkyLight.RealTimeReflectionCapture.VolumetricCloudResolutionDivider": 1.0,  # default 2
    "r.SkyLight.RealTimeReflectionCapture.ShadowFromOpaque": 1.0,  # default 0
    "r.LightShaftQuality": 1.0,
    "r.LightShaftDownSampleFactor": 1.0,                    # default 2, range 1..8
}

#: Interactive tier: engine defaults, written only to pin them against a
#: scalability group that turned them off. No fog-grid cvar, nothing that costs.
INTERACTIVE_CVARS: Dict[str, float] = {
    "r.VolumetricCloud.ShadowMap": 1.0,
    "r.VolumetricCloud.SkyAO": 1.0,
    "r.LightShaftQuality": 1.0,
}

#: Asked for by the module spec, dropped after the 5.7.4 source was read.
DROPPED_CVARS: Dict[str, str] = {
    "r.LightShaftNumSamples": "ECVF_ReadOnly in LightShaftRendering.cpp: a runtime Set is refused",
}

CALIBRATION = "UNCALIBRATED"
BASIS = "value-only: radiance, no surface moves"


def cvars(preset: str, tier: str) -> Dict[str, float]:
    """The cvars the module writes for this preset and tier, in write order."""
    row = SHAFT_PRESETS[preset]
    if tier == "still":
        out = {name: float(row[field]) for field, name in VFOG_GRID_CVARS.items()}
        out.update(STILL_CVARS)
        return out
    if tier == "interactive":
        return dict(INTERACTIVE_CVARS)
    raise ValueError(f"sun_shafts: tier {tier!r} is not one of {', '.join(TIERS)}")


def parameters(preset: str, tier: str) -> Dict[str, Any]:
    """What FFlightSimSunShafts::Apply sets, grouped as render.json records it."""
    if preset not in SHAFT_PRESETS:
        raise ValueError(f"sun_shafts: preset {preset!r} is not one of {', '.join(PRESETS)}")
    row = SHAFT_PRESETS[preset]
    return {
        "preset": preset,
        "tier": tier,
        "sun": {
            "light_shaft_occlusion": True,
            "occlusion_mask_darkness": row["shaft_occlusion_darkness"],
            "occlusion_depth_range_m": row["shaft_occlusion_depth_range_m"],
            "light_shaft_bloom": row["shaft_bloom_scale"] > 0.0,
            "bloom_scale": row["shaft_bloom_scale"],
            "bloom_threshold": row["shaft_bloom_threshold"],
            "bloom_max_brightness": row["shaft_bloom_max"],
            "cloud_shadow_on_atmosphere_strength": row["cloud_shadow_on_atmosphere"],
            "cloud_shadow_on_surface_strength": row["cloud_shadow_on_surface"],
            "cloud_shadow_extent_km": row["cloud_shadow_extent_km"],
            "cloud_shadow_map_resolution_scale": row["cloud_shadow_map_res_scale"],
            "cloud_shadow_ray_sample_count_scale": row["cloud_shadow_ray_sample_scale"],
        },
        "sky_light": {
            "cloud_ambient_occlusion": row["sky_ao_strength"] > 0.0,
            "cloud_ambient_occlusion_strength": row["sky_ao_strength"],
            "cloud_ambient_occlusion_extent_km": row["sky_ao_extent_km"],
            "cloud_ambient_occlusion_map_resolution_scale": row["sky_ao_map_res_scale"],
            "cloud_ambient_occlusion_aperture_scale": row["sky_ao_aperture_scale"],
        },
        "cvars": cvars(preset, tier),
        "show_flags": {"light_shafts": True, "volumetric_fog": True},
        "pixel_moving": False,
        "basis": BASIS,
        "calibration": CALIBRATION,
    }
