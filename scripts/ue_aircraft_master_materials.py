"""The aircraft master materials (visual overhaul V7, aircraft lane). Built
inside UE by scripts/ue_create_materials.py's aircraft block (one call:
build_all()); the per-model instances are made by
scripts/ue_aircraft_materials.py create_look_instances() at import.

Legacy shading models only: Substrate is OFF in this project (NEXT.md
gotcha 32), so every master is a classic Material with a classic shading
model:

* M_AircraftPaint     -- Clear Coat. Base colour from the imported texture
  (BaseColorMap x weight, the Interchange instances' own names), panel
  lines (assets/shaders/aircraft/panel_lines.hlsl) in the normal and as a
  cavity darkening, edge wear toward a bare-metal colour and metallic,
  aft-running grime, roughness breakup (aircraft_wear.hlsl). The normal
  is WORLD space (tangent_space_normal off): the FlightGear meshes are
  imported with legacy tangents because MikkTSpace corrupts them
  (gotcha 5), so nothing here depends on a tangent basis.
* M_AircraftBareMetal -- Default Lit, the same graph without the coat.
* M_AircraftGlass     -- Default Lit, OPAQUE: a dark tinted canopy whose
  reflection comes from the specular lobe (Lumen reflections in beauty)
  with a Fresnel boost at grazing angles. Opaque ON PURPOSE: the label
  captures draw no translucency (FlightSimRenderCommandlet.cpp
  ConfigureLabelCapture SetTranslucency(false)) and a translucent canopy
  writes no custom depth, so a translucent glass would put sky in the
  beauty where the mask says aircraft. Opaque glass keeps beauty, mask,
  class and depth on the same silhouette.
* M_AircraftRubber    -- Default Lit, rough dark dielectric (tyres, seals).
* M_NavLightEmissive, M_AircraftAfterburner -- Unlit ADDITIVE (they add
  light, hide nothing). M_AircraftContrail -- lit translucent.
  M_AircraftHeatHaze -- translucent refraction (2D offset), pixel-moving,
  off unless -heat-haze=on. All four are drawn only by beauty-only actors.

No master uses World Position Offset: nothing here moves a vertex, so the
label passes, which draw the same components, keep the same geometry.
Custom depth / stencil is a COMPONENT setting the commandlet makes per
primitive, independent of the material, and every class master is opaque
(writes custom depth), so the -labels pass is unchanged by these
materials. Decals: the opaque deferred masters keep the engine's default
DBuffer decal response (nothing here disables it).

Assets live under /Game/FlightSim/Aircraft (scripts/aircraft_look.py
MASTER_ROOT), each stamped with LOOK_GENERATION; an older stamp (or
FLIGHTSIM_REBUILD_MATERIALS=all / a name list) rebuilds it. Every
parameter default is a look choice: UNCALIBRATED, set by probe render on
the render machine (docs/visual/PROBE_LOG.md, "## aircraft").

UNCOMPILED when written: no engine runs on the authoring machine. Every
class and property name used here was checked against the UE 5.7.4
headers there (docs/visual/PROBE_LOG.md lists them); the Python spellings
of a few enums are tried under each plausible name and a miss is reported
with the names the engine has (never silently skipped).
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0]))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import aircraft_look as look  # noqa: E402
import aircraft_wet_layer  # noqa: E402  (wet-airframe-canopy)

REPO = os.path.dirname(_HERE)
LOOK_GENERATION = "2"  # 2: wet-airframe-canopy wet layer and canopy scratches
LOOK_GENERATION_TAG = "FlightSimAircraftLookGeneration"
#: The engine's white texture, the default of every BaseColorMap
#: (Engine/Content/EngineResources/WhiteSquareTexture.uasset, present in 5.7.4).
WHITE_TEXTURE = "/Engine/EngineResources/WhiteSquareTexture"


def panel_groove(coord_cm, pitch_cm, width_cm, footprint_cm=0.0):
    """Python twin of one plane set of panel_lines.hlsl: the groove mask at
    a coordinate (1 on a line, 0 between), before the facing term."""
    import math
    p = max(pitch_cm, 1.0)
    frac = (coord_cm / p + 0.5) - math.floor(coord_cm / p + 0.5)
    d = (frac - 0.5) * p
    w = max(width_cm, 0.01)
    fw = max(footprint_cm, 1.0e-4)
    half = 0.5 * w + fw
    g = min(max(1.0 - abs(d) / half, 0.0), 1.0)
    return g * min(max(1.0 - fw / (2.0 * w), 0.0), 1.0)


# -- engine helpers (only these touch unreal) ----------------------------------

def _u():
    import unreal
    return unreal


def _enum(owner, *names):
    for name in names:
        value = getattr(owner, name, None)
        if value is not None:
            return value
    raise RuntimeError(f"none of {names} on {owner.__name__}; it has "
                       f"{[n for n in dir(owner) if n.isupper()]}")


def _path(name):
    return f"{look.MASTER_ROOT}/{name}"


def _stale(name):
    unreal = _u()
    full = _path(name)
    if not unreal.EditorAssetLibrary.does_asset_exist(full):
        return False
    stamped = unreal.EditorAssetLibrary.get_metadata_tag(
        unreal.EditorAssetLibrary.load_asset(full), LOOK_GENERATION_TAG)
    return str(stamped) != LOOK_GENERATION


def _rebuild_requested(name):
    wanted = os.environ.get("FLIGHTSIM_REBUILD_MATERIALS", "").strip()
    names = {token.strip() for token in wanted.split(",")} if wanted else set()
    return _stale(name) or "all" in names or name in names


def _new(name):
    """Create MASTER_ROOT/<name> once; None when it exists at this generation."""
    unreal = _u()
    full = _path(name)
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        if _rebuild_requested(name) and unreal.EditorAssetLibrary.delete_asset(full):
            print(f"MATERIAL-REBUILT: {full}")
        else:
            print(f"MATERIAL-EXISTS: {full}")
            return None
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset(name, look.MASTER_ROOT, unreal.Material, unreal.MaterialFactoryNew())
    if material is None:
        raise RuntimeError(f"could not create {full}")
    return material


def _finish(material, name):
    unreal = _u()
    unreal.EditorAssetLibrary.set_metadata_tag(material, LOOK_GENERATION_TAG, LOOK_GENERATION)
    unreal.MaterialEditingLibrary.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(_path(name))
    print(f"MATERIAL-CREATED: {_path(name)}")


def _node(material, kind, x, y):
    return _u().MaterialEditingLibrary.create_material_expression(material, kind, x, y)


def _link(source, source_out, node, names):
    """Connect to the first pin name the node accepts; the node's pins on a miss."""
    lib = _u().MaterialEditingLibrary
    for name in (names if isinstance(names, (tuple, list)) else (names,)):
        if lib.connect_material_expressions(source, source_out, node, name):
            return name
    have = []
    try:
        lib.get_inputs_for_material_expression(node, have)
    except Exception:
        have = ["(unlisted)"]
    raise RuntimeError(f"no input {names} on {node.get_class().get_name()}; it has {have}")


def _scalar(material, name, default, x, y):
    unreal = _u()
    node = _node(material, unreal.MaterialExpressionScalarParameter, x, y)
    node.set_editor_property("parameter_name", name)
    node.set_editor_property("default_value", float(default))
    return node


def _vector(material, name, default, x, y):
    unreal = _u()
    node = _node(material, unreal.MaterialExpressionVectorParameter, x, y)
    node.set_editor_property("parameter_name", name)
    node.set_editor_property("default_value", unreal.LinearColor(*default))
    return node


def _const(material, value, x, y):
    unreal = _u()
    node = _node(material, unreal.MaterialExpressionConstant, x, y)
    node.set_editor_property("r", float(value))
    return node


def _const3(material, rgb, x, y):
    unreal = _u()
    node = _node(material, unreal.MaterialExpressionConstant3Vector, x, y)
    node.set_editor_property("constant", unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0))
    return node


def _binary(material, kind, a, b, x, y, a_out="", b_out=""):
    node = _node(material, kind, x, y)
    _link(a, a_out, node, "A")
    _link(b, b_out, node, "B")
    return node


def _mul(material, a, b, x, y, a_out="", b_out=""):
    return _binary(material, _u().MaterialExpressionMultiply, a, b, x, y, a_out, b_out)


def _add(material, a, b, x, y, a_out="", b_out=""):
    return _binary(material, _u().MaterialExpressionAdd, a, b, x, y, a_out, b_out)


def _lerp(material, a, b, alpha, x, y, a_out="", b_out="", alpha_out=""):
    node = _node(material, _u().MaterialExpressionLinearInterpolate, x, y)
    _link(a, a_out, node, "A")
    _link(b, b_out, node, "B")
    _link(alpha, alpha_out, node, "Alpha")
    return node


def _mask(material, source, channels, x, y, source_out=""):
    node = _node(material, _u().MaterialExpressionComponentMask, x, y)
    for flag in ("r", "g", "b", "a"):
        node.set_editor_property(flag, flag in channels)
    _link(source, source_out, node, "")
    return node


def _saturate(material, source, x, y, source_out=""):
    node = _node(material, _u().MaterialExpressionSaturate, x, y)
    _link(source, source_out, node, "")
    return node


def _shader(name):
    path = os.path.join(REPO, look.SHADER_DIR, f"{name}.hlsl")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _custom(material, name, output, inputs, x, y):
    """A Custom node running assets/shaders/aircraft/<name>.hlsl; ``inputs``
    maps each input, in look.SHADER_INPUTS order, to (node, output pin)."""
    unreal = _u()
    if tuple(inputs) != look.SHADER_INPUTS[name]:
        raise RuntimeError(f"{name}: inputs {tuple(inputs)} are not {look.SHADER_INPUTS[name]}")
    node = _node(material, unreal.MaterialExpressionCustom, x, y)
    node.set_editor_property("code", _shader(name))
    node.set_editor_property("description", name)
    node.set_editor_property("output_type", _enum(unreal.CustomMaterialOutputType, output))
    pins = []
    for pin in inputs:
        entry = unreal.CustomInput()
        entry.set_editor_property("input_name", pin)
        pins.append(entry)
    node.set_editor_property("inputs", pins)
    for pin, (source, source_out) in inputs.items():
        _link(source, source_out, node, pin)
    return node


def _local_axis(material, axis, x, y):
    """The object's local axis in world space (a Transform of a constant)."""
    unreal = _u()
    rgb = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}[axis]
    node = _node(material, unreal.MaterialExpressionTransform, x, y)
    node.set_editor_property("transform_source_type",
                             unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_LOCAL)
    node.set_editor_property("transform_type", unreal.MaterialVectorCoordTransform.TRANSFORM_WORLD)
    _link(_const3(material, rgb, x - 200, y), "", node, "")
    return node


def _base_colour(material, x, y):
    """lerp(BaseColor, BaseColorMap, BaseColorMapWeight) -- the Interchange
    instances' parameter names, so the MTL wiring carries over."""
    unreal = _u()
    tex = _node(material, unreal.MaterialExpressionTextureSampleParameter2D, x, y)
    tex.set_editor_property("parameter_name", "BaseColorMap")
    white = unreal.load_asset(WHITE_TEXTURE)
    if white is not None:
        tex.set_editor_property("texture", white)
    # A vector parameter is four wide and a sample's first output three: the
    # colour is masked to RGB so the lerp's inputs agree.
    colour = _mask(material, _vector(material, "BaseColor", (1.0, 1.0, 1.0, 1.0), x - 200, y + 220),
                   "rgb", x, y + 220)
    weight = _scalar(material, "BaseColorMapWeight", 0.0, x, y + 330)
    return _lerp(material, colour, tex, weight, x + 250, y + 100)


def _attributes(material, x, y):
    return _node(material, _u().MaterialExpressionMakeMaterialAttributes, x, y)


def _use_attributes(material, attributes):
    unreal = _u()
    material.set_editor_property("use_material_attributes", True)
    unreal.MaterialEditingLibrary.connect_material_property(
        attributes, "", _enum(unreal.MaterialProperty, "MP_MATERIAL_ATTRIBUTES"))


def _surface(name, cls, coat):
    """M_AircraftPaint (coat) / M_AircraftBareMetal (no coat)."""
    unreal = _u()
    material = _new(name)
    if material is None:
        return
    material.set_editor_property("shading_model", _enum(
        unreal.MaterialShadingModel, "MSM_CLEAR_COAT" if coat else "MSM_DEFAULT_LIT"))
    material.set_editor_property("tangent_space_normal", False)
    s = {k: _scalar(material, k, v, -1800, 100 * i)
         for i, (k, v) in enumerate(look.CLASS_SCALARS[cls].items())}
    v = {k: _vector(material, k, d, -1800, 1300 + 120 * i)
         for i, (k, d) in enumerate(look.CLASS_VECTORS[cls].items())}
    local = _node(material, unreal.MaterialExpressionLocalPosition, -1500, -400)
    normal = _node(material, unreal.MaterialExpressionVertexNormalWS, -1500, -300)
    world = _node(material, unreal.MaterialExpressionWorldPosition, -1500, -200)
    panels = _custom(material, "panel_lines", "CMOT_FLOAT4", {
        "LocalPos": (local, ""), "NormalWS": (normal, ""),
        "AxisX": (_local_axis(material, "x", -1300, -700), ""),
        "AxisY": (_local_axis(material, "y", -1300, -600), ""),
        "AxisZ": (_local_axis(material, "z", -1300, -500), ""),
        "Pitch": (_mask(material, v["PanelPitchCm"], "rgb", -1300, -400), ""),
        "WidthCm": (s["PanelWidthCm"], ""), "Depth": (s["PanelDepth"], "")}, -1000, -500)
    wear = _custom(material, "aircraft_wear", "CMOT_FLOAT4", {
        "LocalPos": (local, ""), "NormalWS": (normal, ""), "WorldPosCm": (world, ""),
        "NoiseCm": (s["NoiseCm"], ""), "EdgeStart": (s["EdgeStart"], ""),
        "EdgeEnd": (s["EdgeEnd"], "")}, -1000, -200)
    groove = _mask(material, panels, "a", -800, -450)
    edge = _mul(material, _mask(material, wear, "r", -800, -250), s["WearAmount"], -650, -250)
    grime = _mul(material, _mask(material, wear, "g", -800, -150), s["GrimeAmount"], -650, -150)
    breakup = _mask(material, wear, "b", -800, -50)
    base = _base_colour(material, -1300, 200)
    # cavity: the groove and the grime darken the colour; the wear shows the metal.
    darken = _saturate(material, _add(material, _mul(material, groove, s["PanelDarkening"], -600, -450),
                                      grime, -450, -350), -300, -350)
    dark = _lerp(material, base, _mul(material, base, _const(material, 0.35, -600, 300), -450, 300),
                 darken, -250, 200)
    colour = _lerp(material, dark, _mask(material, v["WearColour"], "rgb", -300, 100), edge, -100, 200)
    metallic = _lerp(material, s["Metallic"], _const(material, 0.9, -300, 450), edge, -100, 450)
    rough = _saturate(material, _add(
        material, _add(material, s["Roughness"], _mul(material, breakup, s["RoughnessBreakup"], -450, 550),
                       -300, 550),
        _mul(material, grime, _const(material, 0.3, -450, 650), -300, 650), -150, 600), 0, 600)
    occlusion = _saturate(material, _add(material, _const(material, 1.0, -450, 750),
                                         _mul(material, groove, _const(material, -0.5, -600, 800),
                                              -450, 800), -300, 780), -150, 780)
    out = _attributes(material, 300, 200)
    _link(colour, "", out, ("BaseColor", "Base Color"))
    _link(metallic, "", out, "Metallic")
    _link(s["Specular"], "", out, "Specular")
    _link(rough, "", out, "Roughness")
    _link(_mask(material, panels, "rgb", -600, -600), "", out, "Normal")
    _link(occlusion, "", out, ("AmbientOcclusion", "Ambient Occlusion"))
    if coat:
        _link(s["ClearCoat"], "", out, ("ClearCoat", "Clear Coat"))
        _link(s["ClearCoatRoughness"], "", out, ("ClearCoatRoughness", "Clear Coat Roughness"))
    _use_attributes(material, out)
    # wet-airframe-canopy: the weather's wetness (shading only, opaque, no WPO).
    aircraft_wet_layer.add_wet_layer(material, sys.modules[__name__], cls)
    _finish(material, name)


def create_aircraft_paint():
    _surface("M_AircraftPaint", "paint", coat=True)


def create_aircraft_bare_metal():
    _surface("M_AircraftBareMetal", "bare_metal", coat=False)


def create_aircraft_glass():
    unreal = _u()
    material = _new("M_AircraftGlass")
    if material is None:
        return
    material.set_editor_property("shading_model", _enum(unreal.MaterialShadingModel, "MSM_DEFAULT_LIT"))
    s = {k: _scalar(material, k, v, -900, 100 * i)
         for i, (k, v) in enumerate(look.CLASS_SCALARS["glass"].items())}
    tint = _vector(material, "GlassTint", look.CLASS_VECTORS["glass"]["GlassTint"], -900, 700)
    base = _base_colour(material, -900, 900)
    fresnel = _node(material, unreal.MaterialExpressionFresnel, -600, 300)
    _link(s["FresnelExponent"], "", fresnel, ("ExponentIn", "Exponent"))
    spec = _saturate(material, _add(material, s["Specular"],
                                    _mul(material, fresnel, s["ReflectionBoost"], -450, 350),
                                    -300, 300), -150, 300)
    colour = _mul(material, _mask(material, tint, "rgb", -600, 700), base, -300, 700)
    out = _attributes(material, 100, 200)
    _link(colour, "", out, ("BaseColor", "Base Color"))
    _link(s["Metallic"], "", out, "Metallic")
    _link(spec, "", out, "Specular")
    _link(s["Roughness"], "", out, "Roughness")
    _use_attributes(material, out)
    # wet-airframe-canopy: wet glass (beads / streaks) and the anisotropic
    # micro-scratches; the glass stays opaque.
    aircraft_wet_layer.add_wet_layer(material, sys.modules[__name__], "glass")
    aircraft_wet_layer.add_canopy_scratch(material, sys.modules[__name__])
    _finish(material, "M_AircraftGlass")


def create_aircraft_rubber():
    unreal = _u()
    material = _new("M_AircraftRubber")
    if material is None:
        return
    material.set_editor_property("shading_model", _enum(unreal.MaterialShadingModel, "MSM_DEFAULT_LIT"))
    s = {k: _scalar(material, k, v, -900, 100 * i)
         for i, (k, v) in enumerate(look.CLASS_SCALARS["rubber"].items())}
    base = _base_colour(material, -900, 600)
    out = _attributes(material, 100, 200)
    _link(base, "", out, ("BaseColor", "Base Color"))
    _link(s["Metallic"], "", out, "Metallic")
    _link(s["Specular"], "", out, "Specular")
    _link(s["Roughness"], "", out, "Roughness")
    _use_attributes(material, out)
    _finish(material, "M_AircraftRubber")


def _fx(name, blend, unlit):
    unreal = _u()
    material = _new(name)
    if material is None:
        return None
    material.set_editor_property("blend_mode", _enum(unreal.BlendMode, blend))
    material.set_editor_property("shading_model", _enum(
        unreal.MaterialShadingModel, "MSM_UNLIT" if unlit else "MSM_DEFAULT_LIT"))
    material.set_editor_property("two_sided", True)
    return material


def _uv(material, x, y):
    unreal = _u()
    node = _node(material, unreal.MaterialExpressionTextureCoordinate, x, y)
    node.set_editor_property("coordinate_index", 0)
    return node


def _emissive(material, node):
    unreal = _u()
    unreal.MaterialEditingLibrary.connect_material_property(
        node, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)


def create_nav_light_emissive():
    material = _fx("M_NavLightEmissive", "BLEND_ADDITIVE", unlit=True)
    if material is None:
        return
    colour, intensity, strobe = look.FX_PARAMETERS["M_NavLightEmissive"]
    glow = _custom(material, "nav_bulb", "CMOT_FLOAT3", {
        "UV": (_uv(material, -700, 0), ""),
        "LightColour": (_mask(material, _vector(material, colour, (1.0, 1.0, 1.0, 1.0), -900, 150),
                              "rgb", -700, 150), ""),
        "Intensity": (_scalar(material, intensity, 1.0, -700, 300), ""),
        "Strobe": (_scalar(material, strobe, 1.0, -700, 400), "")}, -400, 100)
    _emissive(material, glow)
    _finish(material, "M_NavLightEmissive")


def create_aircraft_afterburner():
    material = _fx("M_AircraftAfterburner", "BLEND_ADDITIVE", unlit=True)
    if material is None:
        return
    intensity, core, tip, shocks = look.FX_PARAMETERS["M_AircraftAfterburner"]
    glow = _custom(material, "afterburner_glow", "CMOT_FLOAT3", {
        "UV": (_uv(material, -700, 0), ""),
        "Intensity": (_scalar(material, intensity, 0.0, -700, 100), ""),
        # UNCALIBRATED: a blue-white core going orange (reheat), emissive scale.
        "CoreColour": (_mask(material, _vector(material, core, (30.0, 22.0, 18.0, 1.0), -900, 200),
                             "rgb", -700, 200), ""),
        "TipColour": (_mask(material, _vector(material, tip, (20.0, 6.0, 1.5, 1.0), -900, 320),
                            "rgb", -700, 320), ""),
        "Shocks": (_scalar(material, shocks, 5.0, -700, 440), "")}, -400, 100)
    _emissive(material, glow)
    _finish(material, "M_AircraftAfterburner")


def create_aircraft_contrail():
    unreal = _u()
    material = _fx("M_AircraftContrail", "BLEND_TRANSLUCENT", unlit=False)
    if material is None:
        return
    lighting = getattr(unreal.TranslucencyLightingMode, "TLM_VOLUMETRIC_NON_DIRECTIONAL", None)
    if lighting is not None:
        material.set_editor_property("translucency_lighting_mode", lighting)
    opacity_name, formation_name = look.FX_PARAMETERS["M_AircraftContrail"]
    opacity = _custom(material, "contrail_opacity", "CMOT_FLOAT1", {
        "UV": (_uv(material, -700, 0), ""),
        "LocalPos": (_node(material, unreal.MaterialExpressionLocalPosition, -700, 100), ""),
        "Opacity": (_scalar(material, opacity_name, 0.55, -700, 200), ""),
        "Formation": (_scalar(material, formation_name, 0.01, -700, 300), "")}, -400, 100)
    lib = unreal.MaterialEditingLibrary
    lib.connect_material_property(_const3(material, (0.92, 0.94, 0.97), -400, -100), "",
                                  unreal.MaterialProperty.MP_BASE_COLOR)
    lib.connect_material_property(_const(material, 0.9, -400, 0), "", unreal.MaterialProperty.MP_ROUGHNESS)
    lib.connect_material_property(opacity, "", unreal.MaterialProperty.MP_OPACITY)
    _finish(material, "M_AircraftContrail")


def create_aircraft_heat_haze():
    unreal = _u()
    material = _fx("M_AircraftHeatHaze", "BLEND_TRANSLUCENT", unlit=False)
    if material is None:
        return
    material.set_editor_property("refraction_method", _enum(
        unreal.RefractionMode, "RM_2D_OFFSET", "RM_2DOFFSET", "RM_2D_Offset"))
    time_name, strength_name = look.FX_PARAMETERS["M_AircraftHeatHaze"]
    offset = _custom(material, "heat_haze", "CMOT_FLOAT2", {
        "UV": (_uv(material, -700, 0), ""),
        "LocalPos": (_node(material, unreal.MaterialExpressionLocalPosition, -700, 100), ""),
        "TimeS": (_scalar(material, time_name, 0.0, -700, 200), ""),
        "Strength": (_scalar(material, strength_name, 0.6, -700, 300), "")}, -400, 100)
    lib = unreal.MaterialEditingLibrary
    lib.connect_material_property(_const3(material, (0.0, 0.0, 0.0), -400, -100), "",
                                  unreal.MaterialProperty.MP_BASE_COLOR)
    lib.connect_material_property(_const(material, 0.0, -400, -50), "", unreal.MaterialProperty.MP_OPACITY)
    lib.connect_material_property(offset, "", unreal.MaterialProperty.MP_REFRACTION)
    _finish(material, "M_AircraftHeatHaze")


#: Every master this module builds, in build order (class masters, then FX).
CREATORS = (create_aircraft_paint, create_aircraft_bare_metal, create_aircraft_glass,
            create_aircraft_rubber, create_nav_light_emissive, create_aircraft_contrail,
            create_aircraft_afterburner, create_aircraft_heat_haze)
#: The asset each creator makes (pinned to look.CLASS_MASTERS / FX_MASTERS by test).
CREATED = ("M_AircraftPaint", "M_AircraftBareMetal", "M_AircraftGlass", "M_AircraftRubber",
           "M_NavLightEmissive", "M_AircraftContrail", "M_AircraftAfterburner",
           "M_AircraftHeatHaze",
           # condensation-solver: built by scripts/aircraft_condensation_material.py.
           "M_AircraftCondensation")


def build_all():
    """Build every master; returns the names that failed (each one's
    traceback printed). One failure does not stop the others: a beauty
    render records an absent instance, never a refusal."""
    import traceback
    failed = []
    for creator in CREATORS:
        try:
            creator()
        except Exception:
            traceback.print_exc()
            print(f"MATERIAL-FAILED: {creator.__name__}")
            failed.append(creator.__name__)
    try:  # condensation-solver: M_AircraftCondensation, its own module.
        __import__("aircraft_condensation_material").build()
    except Exception:
        traceback.print_exc()
        print("MATERIAL-FAILED: aircraft_condensation_material.build")
        failed.append("aircraft_condensation_material.build")
    return failed
