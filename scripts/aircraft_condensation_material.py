"""M_AircraftCondensation (visual overhaul, module "condensation-solver"):
the translucent master FlightSimCondensation.cpp draws the humidity-gated
vapour sites with -- tip vortex ribbons, the upper-wing sheet, the transonic
cone and the LEX vortices.

Built from scripts/ue_aircraft_master_materials.py build_all() (one call to
:func:`build`), inside UnrealEditor's Python, with that module's helpers.

The graph: a Custom node running assets/shaders/aircraft/condensation_opacity.hlsl
(per-site shape, the vertex colour R weight, a world-space Noise node's
lumpiness, the Opacity scalar the C++ drives every step and the Shape
scalar it sets once), through a DepthFade node (the cloud softens where it
meets the skin instead of cutting a hard line), into Opacity. Lit
translucent (volumetric non-directional, like the contrail), two-sided,
a near-white base colour, rough.

Labels match pixels: BLEND_TRANSLUCENT (the label passes draw no
translucency), no refraction, no world position offset -- it moves no pixel
of the geometry behind it. UNCALIBRATED: the colour, the fade distance and
the noise scale are look choices (probe: docs/visual/PROBE_LOG.md
"## condensation-solver").
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0]))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

NAME = "M_AircraftCondensation"
#: The scalars the C++ sets (aircraft_look.FX_PARAMETERS[NAME], pinned by test).
PARAMETERS = ("Opacity", "Shape")
SHADER = "condensation_opacity"
#: The Custom node's inputs, in order (documented in the .hlsl, pinned by test).
SHADER_INPUTS = ("UV", "Weight", "Noise", "Opacity", "Shape")
#: UNCALIBRATED look choices.
BASE_COLOUR = (0.93, 0.95, 0.98)
ROUGHNESS = 1.0
DEPTH_FADE_CM = 60.0
NOISE_SCALE_PER_CM = 0.006
NOISE_LEVELS = 4


def _custom(m, material, inputs, x, y):
    """A Custom node running the committed shader body (the masters' own
    ``_custom`` checks aircraft_look.SHADER_INPUTS, which this module keeps
    out of)."""
    unreal = m._u()
    node = m._node(material, unreal.MaterialExpressionCustom, x, y)
    node.set_editor_property("code", m._shader(SHADER))
    node.set_editor_property("description", SHADER)
    node.set_editor_property("output_type", m._enum(unreal.CustomMaterialOutputType, "CMOT_FLOAT1"))
    if tuple(inputs) != SHADER_INPUTS:
        raise RuntimeError(f"{SHADER}: inputs {tuple(inputs)} are not {SHADER_INPUTS}")
    pins = []
    for pin in inputs:
        entry = unreal.CustomInput()
        entry.set_editor_property("input_name", pin)
        pins.append(entry)
    node.set_editor_property("inputs", pins)
    for pin, (source, source_out) in inputs.items():
        m._link(source, source_out, node, pin)
    return node


def build():
    """Create MASTER_ROOT/M_AircraftCondensation once (None when it exists at
    this generation), with the masters builder's helpers."""
    import ue_aircraft_master_materials as m
    unreal = m._u()
    material = m._fx(NAME, "BLEND_TRANSLUCENT", unlit=False)
    if material is None:
        return None
    lighting = getattr(unreal.TranslucencyLightingMode, "TLM_VOLUMETRIC_NON_DIRECTIONAL", None)
    if lighting is not None:
        material.set_editor_property("translucency_lighting_mode", lighting)
    opacity_name, shape_name = PARAMETERS

    weight = m._mask(material, m._node(material, unreal.MaterialExpressionVertexColor, -1000, 100),
                     "r", -800, 100)
    noise = m._node(material, unreal.MaterialExpressionNoise, -800, 200)
    noise.set_editor_property("scale", NOISE_SCALE_PER_CM)
    noise.set_editor_property("levels", NOISE_LEVELS)
    noise.set_editor_property("output_min", 0.0)
    noise.set_editor_property("output_max", 1.0)
    # Position left unconnected: the Noise node then samples absolute world
    # position, so the lumps stay in the air as the aircraft flies through.
    shaped = _custom(m, material, {
        "UV": (m._uv(material, -800, 0), ""),
        "Weight": (weight, ""),
        "Noise": (noise, ""),
        "Opacity": (m._scalar(material, opacity_name, 0.0, -800, 300), ""),
        "Shape": (m._scalar(material, shape_name, 0.0, -800, 400), "")}, -500, 100)
    fade = m._node(material, unreal.MaterialExpressionDepthFade, -250, 100)
    fade.set_editor_property("fade_distance_default", DEPTH_FADE_CM)
    m._link(shaped, "", fade, ("Opacity", "InOpacity"))

    lib = unreal.MaterialEditingLibrary
    lib.connect_material_property(m._const3(material, BASE_COLOUR, -250, -100), "",
                                  unreal.MaterialProperty.MP_BASE_COLOR)
    lib.connect_material_property(m._const(material, ROUGHNESS, -250, 0), "",
                                  unreal.MaterialProperty.MP_ROUGHNESS)
    lib.connect_material_property(fade, "", unreal.MaterialProperty.MP_OPACITY)
    m._finish(material, NAME)
    return material
