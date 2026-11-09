"""Wet airframe, airflow rain streaks and canopy micro-scratches (visual
overhaul, module "wet-airframe-canopy"). BEAUTY ONLY, shading only.

The airframe takes the weather's wetness:

* the paint and bare-metal albedo darkens, ``lerp(albedo, albedo^2,
  wet * porosity)`` (a water film fills the surface's micro-pores, so less
  light leaves it diffusely; the squared albedo is the usual cheap closed
  form of that, Lagarde 2013 "water drop 3b", from memory);
* the roughness falls, ``lerp(r, min(r, WetRoughness), wet)``;
* the paint's clear coat goes toward 1 with a low clear-coat roughness;
* rain rivulets: a tiled hash noise of thin lines stretched along the
  object's -X axis and panned aft at ``StreakSpeedPerKt * airspeed`` (cm/s);
  below ``BeadingMaxKts`` the airflow no longer drives the water, the lines
  turn into slow gravity runs along world -Z (expressed in the object's own
  frame, so the pattern stays on the airframe) and the glass (and, less, the
  waxed paint) carries round beads.

The canopy glass gets an anisotropic micro-scratch layer: tangents on
circles about the canopy centre (the wipe swirls), negative anisotropy so
the highlight stretches across the scratches (radially), as a wiped
windscreen does into the sun. It needs ``r.AnisotropicMaterials`` (on at
the Cinematic shading scalability the beauty path uses: BaseScalability.ini
[ShadingQuality@Cine], UE 5.7.4), legacy shading (Substrate stays off) and a
world-space tangent, so the glass master's normal becomes world space with
the vertex normal wired in explicitly.

Labels match pixels: nothing here moves a vertex (no World Position
Offset), every master stays OPAQUE (the canopy glass included: the
documented "glass is opaque" decision), so silhouette, class, mask and depth
are unchanged and ``render.json`` needs no ``pixel_moving_effects`` entry.
The optional MakeHuman pilot and a translucent canopy are NOT part of this
module (label-unsafe; rejected).

Who sets what:

* the four dynamic scalars (:data:`WET_DYNAMIC_PARAMETERS`) are set per
  captured step by FlightSimAircraftWet.cpp on every look MID, from the FDM
  (``velocities/vtrue-kts``, ``simulation/sim-time-sec``) and the weather
  record (``rain.rate_mmh``, ``rain.beauty_readability_gain``);
* every other constant is a master scalar whose default is the value in
  :data:`WET_DEFAULTS` (copied into each look manifest, group ``wet``, with
  its UNCALIBRATED stamp), except ``WetSaturationMmh`` and ``WetDryTauS``,
  which only the C++ uses (the wetness integration).

Plain Python (stdlib only at import, so it also runs inside UnrealEditor's
Python). The numpy twins at the bottom are what tests/test_aircraft_wet.py
checks; numpy is imported lazily there.

UNCOMPILED and UNRENDERED when written (the authoring Mac cannot build or
render UE 5.7). Engine names used here were grepped in the UE 5.7.4 headers
(scripts/check_bridge_api.sh, block "WET-AIRFRAME-CANOPY").
"""

from __future__ import annotations

import math

#: The word every number in this module carries until a probe render sets it.
UNCALIBRATED = "UNCALIBRATED: set by probe render on the render machine"

#: Every look constant of this module, with its default. Each one is a look
#: choice, not a measurement: UNCALIBRATED (probe: a storm-weather beauty
#: chase at shot c range, and a canopy close-up into the sun).
WET_DEFAULTS = {
    # rivulets: cm/s of aft streak travel per knot of true airspeed
    "StreakSpeedPerKt": 0.5,
    # below this true airspeed the water runs by gravity and beads
    "BeadingMaxKts": 60.0,
    # the film's roughness (the surface is never made rougher by the film)
    "WetRoughness": 0.08,
    # the wet paint's clear-coat roughness
    "WetCoatRoughness": 0.03,
    # rain rate that fully wets the airframe: wet = saturate(rate / this)
    "WetSaturationMmh": 4.0,
    # dry-off time constant on the FDM's time (wetting is immediate)
    "WetDryTauS": 90.0,
    # how far the film darkens each class (wet x porosity is the lerp to albedo^2).
    # No rubber entry: M_AircraftRubber takes no wet layer (tests pin that).
    "PorosityPaint": 0.3,
    "PorosityBareMetal": 0.12,
    "PorosityGlass": 0.0,
    # round beads in the gravity regime (glass sheds into beads, waxed paint less)
    "BeadAmountPaint": 0.3,
    "BeadAmountBareMetal": 0.0,
    "BeadAmountGlass": 1.0,
    # rivulet line pitch and segment length (object cm)
    "StreakPitchCm": 2.5,
    "StreakLengthCm": 30.0,
    # rain rate at which every rivulet cell carries water
    "RivuletFullMmh": 10.0,
    # canopy micro-scratches: how much of the glass is scratched, how strongly
    "ScratchDensity": 0.6,
    "ScratchAnisotropy": 0.5,
    # the canopy centre in the mesh's local frame (cm). Default: the mesh
    # origin -- concentric circles about a distant centre read as long,
    # gently curved wipe lines; a per-type centre is a probe item.
    "CanopyCentreXCm": 0.0,
    "CanopyCentreYCm": 0.0,
    "CanopyCentreZCm": 0.0,
}

#: Literals inside aircraft_wet.hlsl (a Custom node cannot read a parameter it
#: is not given and the WetParams/WetShape packs are full); pinned to the
#: HLSL text by the tests. UNCALIBRATED like the rest.
HLSL_GRAVITY_RUN_CM_S = 3.0
HLSL_BEAD_ROUGHNESS = 0.3
#: canopy_scratch.hlsl: scratches clump on rings this wide (cm) about the centre.
HLSL_SCRATCH_RING_CM = 0.8

#: The scalars FlightSimAircraftWet.cpp sets per step on each look MID
#: (pinned to the C++ text by tests/test_aircraft_wet.py).
WET_DYNAMIC_PARAMETERS = ("Wetness", "RainRateMmh", "AirspeedKts", "TimeS")

#: The constant master scalars and the WET_DEFAULTS key each one defaults to
#: ({cls} is the slot class's porosity / bead key).
WET_MASTER_SCALARS = {
    "WetPorosity": "Porosity{cls}",
    "WetRoughness": "WetRoughness",
    "WetStreakSpeedPerKt": "StreakSpeedPerKt",
    "WetBeadingMaxKts": "BeadingMaxKts",
    "WetBeadAmount": "BeadAmount{cls}",
    "WetStreakPitchCm": "StreakPitchCm",
    "WetStreakLengthCm": "StreakLengthCm",
    "WetRivuletFullMmh": "RivuletFullMmh",
    "WetCoatRoughness": "WetCoatRoughness",
}
SCRATCH_MASTER_SCALARS = {"ScratchDensity": "ScratchDensity",
                          "ScratchAnisotropy": "ScratchAnisotropy"}
SCRATCH_CENTRE_PARAMETER = "CanopyCentreCm"

#: The Custom-node bodies of this module and their inputs, in order (merged
#: into scripts/aircraft_look.py SHADER_INPUTS, whose test checks each HLSL
#: file documents exactly these).
WET_SHADER_INPUTS = {
    "aircraft_wet": ("LocalPos", "NormalWS", "AxisX", "AxisY", "AxisZ", "Albedo", "Roughness",
                     "Wetness", "RainRateMmh", "AirspeedKts", "TimeS", "WetParams", "WetShape"),
    "canopy_scratch": ("LocalPos", "NormalWS", "AxisX", "AxisY", "AxisZ", "CanopyCentre",
                       "ScratchDensity", "ScratchAnisotropy"),
}
#: aircraft_wet.hlsl's one additional output (the clear-coat mask).
WET_COAT_OUTPUT = "WetCoat"

#: The classes that take the wet layer, and the WET_DEFAULTS suffix of each.
CLASS_KEYS = {"paint": "Paint", "bare_metal": "BareMetal", "glass": "Glass"}
#: The classes whose master has a clear coat (the wet coat is wired only there).
COATED_CLASSES = ("paint",)

#: The attributes the inserted MakeMaterialAttributes takes straight from the
#: master's own (everything the class masters connect, never a WPO).
PASS_THROUGH = ("Metallic", "Specular", "Normal", "AmbientOcclusion")
_PIN_ALIASES = {
    "BaseColor": ("BaseColor", "Base Color"),
    "AmbientOcclusion": ("AmbientOcclusion", "Ambient Occlusion"),
    "ClearCoat": ("ClearCoat", "Clear Coat"),
    "ClearCoatRoughness": ("ClearCoatRoughness", "Clear Coat Roughness"),
}


def class_default(template, cls):
    """WET_DEFAULTS value of one master scalar for one slot class."""
    if cls not in CLASS_KEYS:
        raise ValueError(f"slot class {cls!r} is not one of {tuple(CLASS_KEYS)}")
    key = template.format(cls=CLASS_KEYS[cls])
    if key not in WET_DEFAULTS:
        # bare-metal beads: none unless stated
        return 0.0
    return float(WET_DEFAULTS[key])


# -- the master-graph builders (only these touch unreal) ----------------------
# ``lib`` is scripts/ue_aircraft_master_materials.py (its node helpers), passed
# in so this module never imports it (no import cycle, and the masters' own
# helpers stay the only spelling of each node).

def _pin(name):
    return _PIN_ALIASES.get(name, name)


def _graft(material, lib, x, y):
    """Break the master's current attributes and start a new Make node:
    (break, make). The caller wires make and calls _commit."""
    unreal = lib._u()
    editing = unreal.MaterialEditingLibrary
    prop = lib._enum(unreal.MaterialProperty, "MP_MATERIAL_ATTRIBUTES")
    old = editing.get_material_property_input_node(material, prop)
    if old is None:
        raise RuntimeError("wet layer: the master has no MaterialAttributes output to graft onto "
                           "(call after _use_attributes)")
    old_out = editing.get_material_property_input_node_output_name(material, prop) or ""
    brk = lib._node(material, unreal.MaterialExpressionBreakMaterialAttributes, x, y)
    lib._link(old, old_out, brk, "")
    make = lib._attributes(material, x + 900, y)
    return brk, make


def _commit(lib, material, make):
    unreal = lib._u()
    unreal.MaterialEditingLibrary.connect_material_property(
        make, "", lib._enum(unreal.MaterialProperty, "MP_MATERIAL_ATTRIBUTES"))


def _append(material, lib, a, b, x, y):
    return lib._binary(material, lib._u().MaterialExpressionAppendVector, a, b, x, y)


def _pack4(material, lib, nodes, x, y):
    out = nodes[0]
    for i, node in enumerate(nodes[1:], 1):
        out = _append(material, lib, out, node, x + 120 * i, y)
    return out


def add_wet_layer(material, lib, slot_class):
    """Graft the wet layer onto a built class master (after its attributes
    are wired, before _finish): Break -> aircraft_wet.hlsl -> Make. Opaque,
    no WPO; the paint's clear coat follows the wet coat mask."""
    unreal = lib._u()
    x, y = 600, 1600
    brk, make = _graft(material, lib, x, y)
    dyn = {name: lib._scalar(material, name, 0.0, x, y + 300 + 100 * i)
           for i, name in enumerate(WET_DYNAMIC_PARAMETERS)}
    const = {name: lib._scalar(material, name, class_default(key, slot_class), x, y + 800 + 100 * i)
             for i, (name, key) in enumerate(WET_MASTER_SCALARS.items())}
    params = _pack4(material, lib, [const["WetPorosity"], const["WetRoughness"],
                                    const["WetStreakSpeedPerKt"], const["WetBeadingMaxKts"]],
                    x + 200, y + 1800)
    shape = _pack4(material, lib, [const["WetBeadAmount"], const["WetStreakPitchCm"],
                                   const["WetStreakLengthCm"], const["WetRivuletFullMmh"]],
                   x + 200, y + 1950)
    local = lib._node(material, unreal.MaterialExpressionLocalPosition, x, y - 400)
    normal = lib._node(material, unreal.MaterialExpressionVertexNormalWS, x, y - 300)
    wet = lib._custom(material, "aircraft_wet", "CMOT_FLOAT4", {
        "LocalPos": (local, ""), "NormalWS": (normal, ""),
        "AxisX": (lib._local_axis(material, "x", x + 200, y - 700), ""),
        "AxisY": (lib._local_axis(material, "y", x + 200, y - 600), ""),
        "AxisZ": (lib._local_axis(material, "z", x + 200, y - 500), ""),
        "Albedo": (brk, "BaseColor"), "Roughness": (brk, "Roughness"),
        "Wetness": (dyn["Wetness"], ""), "RainRateMmh": (dyn["RainRateMmh"], ""),
        "AirspeedKts": (dyn["AirspeedKts"], ""), "TimeS": (dyn["TimeS"], ""),
        "WetParams": (params, ""), "WetShape": (shape, "")}, x + 450, y)
    coat_out = unreal.CustomOutput()
    coat_out.set_editor_property("output_name", WET_COAT_OUTPUT)
    coat_out.set_editor_property("output_type", lib._enum(unreal.CustomMaterialOutputType, "CMOT_FLOAT1"))
    # Setting the property runs PostEditChangeProperty -> RebuildOutputs:
    # output 0 becomes "return", output 1 "WetCoat" (MaterialExpressions.cpp, 5.7.4).
    wet.set_editor_property("additional_outputs", [coat_out])
    for name in PASS_THROUGH:
        lib._link(brk, name, make, _pin(name))
    lib._link(lib._mask(material, wet, "rgb", x + 650, y - 100), "", make, _pin("BaseColor"))
    lib._link(lib._mask(material, wet, "a", x + 650, y), "", make, "Roughness")
    if slot_class in COATED_CLASSES:
        one = lib._const(material, 1.0, x + 650, y + 100)
        coat = lib._lerp(material, brk, one, wet, x + 750, y + 150, a_out="ClearCoat",
                         alpha_out=WET_COAT_OUTPUT)
        coat_rough = lib._lerp(material, brk, const["WetCoatRoughness"], wet, x + 750, y + 250,
                               a_out="ClearCoatRoughness", alpha_out=WET_COAT_OUTPUT)
        lib._link(coat, "", make, _pin("ClearCoat"))
        lib._link(coat_rough, "", make, _pin("ClearCoatRoughness"))
    _commit(lib, material, make)
    return wet


def add_canopy_scratch(material, lib):
    """Graft the anisotropic micro-scratch layer onto the glass master (after
    add_wet_layer): circular-swirl tangents about CanopyCentreCm, world-space
    normal and tangent. Opaque, no WPO, legacy Default Lit."""
    unreal = lib._u()
    x, y = 2000, 1600
    # The anisotropy tangent is read in the normal's space
    # (MaterialTemplate.ush CalculateAnisotropyTangent): world space here, so
    # the vertex normal is wired explicitly (an unconnected world-space normal
    # would default to world +Z).
    material.set_editor_property("tangent_space_normal", False)
    brk, make = _graft(material, lib, x, y)
    scalars = {name: lib._scalar(material, name, WET_DEFAULTS[key], x, y + 300 + 100 * i)
               for i, (name, key) in enumerate(SCRATCH_MASTER_SCALARS.items())}
    centre = lib._mask(material, lib._vector(material, SCRATCH_CENTRE_PARAMETER, (
        WET_DEFAULTS["CanopyCentreXCm"], WET_DEFAULTS["CanopyCentreYCm"],
        WET_DEFAULTS["CanopyCentreZCm"], 0.0), x - 200, y + 600), "rgb", x, y + 600)
    local = lib._node(material, unreal.MaterialExpressionLocalPosition, x, y - 400)
    normal = lib._node(material, unreal.MaterialExpressionVertexNormalWS, x, y - 300)
    scratch = lib._custom(material, "canopy_scratch", "CMOT_FLOAT4", {
        "LocalPos": (local, ""), "NormalWS": (normal, ""),
        "AxisX": (lib._local_axis(material, "x", x + 200, y - 700), ""),
        "AxisY": (lib._local_axis(material, "y", x + 200, y - 600), ""),
        "AxisZ": (lib._local_axis(material, "z", x + 200, y - 500), ""),
        "CanopyCentre": (centre, ""),
        "ScratchDensity": (scalars["ScratchDensity"], ""),
        "ScratchAnisotropy": (scalars["ScratchAnisotropy"], "")}, x + 450, y)
    for name in ("BaseColor", "Metallic", "Specular", "Roughness", "AmbientOcclusion"):
        lib._link(brk, name, make, _pin(name))
    lib._link(normal, "", make, "Normal")
    lib._link(lib._mask(material, scratch, "rgb", x + 650, y - 100), "", make, "Tangent")
    lib._link(lib._mask(material, scratch, "a", x + 650, y), "", make, "Anisotropy")
    _commit(lib, material, make)
    return scratch


# -- the numpy twins (tests/test_aircraft_wet.py) -----------------------------

def target_wetness(rain_rate_mmh, saturation_mmh=None):
    """The wetness the rain drives the airframe to: saturate(rate / sat)."""
    sat = WET_DEFAULTS["WetSaturationMmh"] if saturation_mmh is None else saturation_mmh
    if sat <= 0.0:
        return 1.0 if rain_rate_mmh > 0.0 else 0.0
    return min(max(rain_rate_mmh / sat, 0.0), 1.0)


def dry_off(wetness, target, dt_s, tau_s=None):
    """One step of the wetness integration (FlightSimAircraftWet.cpp DryOff):
    wetting is immediate; drying is the exact exponential toward the target,
    so N steps over T equal one step of T (replay- and frame-rate-independent)."""
    tau = WET_DEFAULTS["WetDryTauS"] if tau_s is None else tau_s
    if target >= wetness or tau <= 0.0:
        return target
    return target + (wetness - target) * math.exp(-max(dt_s, 0.0) / tau)


def regime(airspeed_kts, beading_max_kts=None):
    """'airflow' at or above BeadingMaxKts, else 'gravity' (aircraft_wet.hlsl)."""
    limit = WET_DEFAULTS["BeadingMaxKts"] if beading_max_kts is None else beading_max_kts
    return "airflow" if airspeed_kts >= limit else "gravity"


def wet_surface(albedo, roughness, wetness, porosity, wet_roughness=None,
                rivulet=0.0, bead=0.0, bead_amount=0.0):
    """numpy twin of aircraft_wet.hlsl's closing lines: (albedo, roughness,
    coat) from the surface, the film and the rivulet / bead masks."""
    import numpy as np
    wr = WET_DEFAULTS["WetRoughness"] if wet_roughness is None else wet_roughness
    a_in = np.asarray(albedo, dtype=np.float64)
    r_in = np.asarray(roughness, dtype=np.float64)
    wet = np.clip(wetness, 0.0, 1.0)
    k = wet * np.clip(porosity, 0.0, 1.0)
    a = np.clip(a_in, 0.0, 1.0)
    albedo_out = a_in + (a * a - a_in) * k
    r = r_in + (np.minimum(r_in, wr) - r_in) * wet
    streak_target = (0.5 * wr) + (HLSL_BEAD_ROUGHNESS - 0.5 * wr) * np.clip(bead_amount, 0.0, 1.0)
    r = r + (streak_target - r) * rivulet
    r = r + (np.maximum(r, HLSL_BEAD_ROUGHNESS) - r) * bead
    coat = np.clip(np.maximum(wet, rivulet), 0.0, 1.0)
    return albedo_out, r, coat


def scratch_tangent(local_pos, normal_ws, centre=(0.0, 0.0, 0.0), axes=None):
    """numpy twin of canopy_scratch.hlsl's tangent: on the circle about the
    centre, in the surface (orthogonal to the normal and to the radial)."""
    import numpy as np
    ax = np.eye(3) if axes is None else np.asarray(axes, dtype=np.float64)
    d = np.asarray(local_pos, dtype=np.float64) - np.asarray(centre, dtype=np.float64)
    d_ws = d[0] * ax[0] + d[1] * ax[1] + d[2] * ax[2]
    n = np.asarray(normal_ws, dtype=np.float64)
    n = n / np.linalg.norm(n)
    t = np.cross(n, d_ws)
    if np.linalg.norm(t) < 1e-3:
        t = np.cross(n, ax[0])
    length = np.linalg.norm(t)
    return t / length if length > 1e-6 else ax[1] / np.linalg.norm(ax[1])


def constants_group(probe="a storm-weather beauty chase at shot c range and a canopy "
                          "close-up into the sun"):
    """The look manifest's ``wet`` constants group (aircraft_look._constants form)."""
    return {key: {"value": float(value), "calibration": UNCALIBRATED, "probe": probe}
            for key, value in WET_DEFAULTS.items()}
