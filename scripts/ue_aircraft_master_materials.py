"""The aircraft master materials (visual overhaul V7, aircraft lane). Built
inside UE by scripts/ue_create_materials.py's aircraft block (one call:
build_all()); the per-model instances are made by
scripts/ue_aircraft_materials.py create_look_instances() at import.

Legacy shading models only: Substrate is OFF in this project (NEXT.md
gotcha 32), so every master is a classic Material with a classic shading
model:

* M_AircraftPaint     -- Clear Coat. Base colour from the imported texture
  (BaseColorMap x weight, the Interchange instances' own names), capped at
  AlbedoMax, Metallic 0 (a dielectric at n 1.5: Specular 0.5), panel
  lines (assets/shaders/aircraft/panel_lines.hlsl) in the normal and as a
  low cavity darkening, edge wear toward the measured aluminium F0 and
  Metallic 1, aft-running grime, roughness breakup (aircraft_wear.hlsl),
  and exhaust soot aft of the look manifest's nozzles (exhaust_soot.hlsl:
  darkens, roughens, kills the coat). The normal is WORLD space
  (tangent_space_normal off): the FlightGear meshes are imported with
  legacy tangents because MikkTSpace corrupts them (gotcha 5), so nothing
  here depends on a tangent basis. A matte fighter (PLAAF grey) is this
  master with ClearCoat 0 in its look config.
* M_AircraftBareMetal -- Default Lit, the same graph without the coat:
  Metallic 1, colour lerped toward the measured metal F0 (MetalF0:
  aluminium, or the metal a slot rule names: titanium, stainless steel),
  roughness 0.25-0.45 from low-frequency breakup.
* M_AircraftGlass     -- Default Lit, OPAQUE: a dark tinted canopy whose
  reflection comes from the specular lobe with a Fresnel boost at grazing
  angles. Opaque ON PURPOSE: the label captures draw no translucency
  (FlightSimRenderCommandlet.cpp ConfigureLabelCapture
  SetTranslucency(false)) and a translucent canopy writes no depth, so a
  translucent glass would put sky in the labels where the beauty shows the
  canopy. This is the LABEL-SAFE canopy: every -labels render keeps it.
* M_AircraftGlassReflect / M_AircraftGlassReflectFine -- generation 11:
  M_AircraftGlass's graph exactly plus the canopy reflection on Emissive
  (swarm lane aircraft_exterior.glass.coastal, tiers 0-1: a Fresnel LUT and a
  baked sky/sea strip, 2 / 4 taps). OPAQUE, so label-safe for the same
  reason; drawn only under -canopy-reflect=on (scripts/aircraft_glass_reflect.py).
* M_AircraftGlassThin -- round 5 (L4): Thin Translucent (blend Translucent,
  lighting mode Surface ForwardShading, the ThinTranslucentMaterialOutput
  node's Transmittance, screen-space reflections on, no refraction), n 1.5
  so Specular 0.5, roughness 0.02. Parented by MI_<slot>_thin beside every
  glass slot's opaque instance; FlightSimAircraftFX.cpp applies it ONLY on
  a render without -labels (aircraft_look.THIN_* and labels_requested).
  SM5 D3D11: the base pass dual-source-blends it (PCD3D_SM5
  bSupportsDualSourceBlending=true) and has a single-target fallback.
* M_AircraftRubber    -- Default Lit, the measured tyre (roughness 0.7,
  n 1.5 so Specular 0.5), the MTL colour floored at the measured albedo.
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
import aircraft_glass_reflect  # noqa: E402  (canopy reflection, tiers 0-1)

REPO = os.path.dirname(_HERE)
#: 2: wet-airframe-canopy wet layer and canopy scratches; 3: fix pass (acrylic
#: glass, physical bulbs and plume); 4: round 5 L4 -- measured metals and
#: rubber (Physically Based API), paint Metallic 0 with an albedo cap, low
#: panel lines, exhaust soot, the Thin Translucent canopy master; 5/6: the
#: round 23/24 probe handles; 7 (round 25): rebuilt IN PLACE (never deleted:
#: _new), a LookGeneration sentinel scalar the host reads back, and the
#: Custom-node-free clear-coat master M_AircraftPaintCoat (the host's
#: compile-checked fallback and -aircraft-probe=coat).
#: 8: both round-47 lanes -- M_AircraftContrail FormationRamp (#13) and the
#: round-25 in-place rebuild, sentinel and coat master.
#: 11: the canopy reflection masters M_AircraftGlassReflect (tier 0) and
#: M_AircraftGlassReflectFine (tier 1) beside M_AircraftGlass, and their lane
#: textures under MASTER_ROOT/Glass (scripts/aircraft_glass_reflect.py; drawn
#: only under -canopy-reflect=on). Every other graph is unchanged.
#: 12 (round 93): M_AircraftContrail's opacity fades in with the camera's
#: distance (CameraDepthFade; #13's four rulers). Every other graph is unchanged.
LOOK_GENERATION = "12"
#: Round 25: every paint / bare-metal master carries this scalar (default
#: LOOK_GENERATION), wired into its AO as x0, so FlightSimAircraftFX.cpp can
#: read which graph a render drew (render.json aircraft_look.materials.
#: master_generation): rounds 37-40 drew byte-identical frames under five
#: different probes, and nothing on the page said which graph was drawn.
LOOK_GENERATION_PARAMETER = "LookGeneration"
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
    """Create MASTER_ROOT/<name> once; None when it exists at this generation.

    Round 25: a stale (or FLIGHTSIM_REBUILD_MATERIALS-named) master is
    cleared and built again IN PLACE, the way scripts/ue_create_materials.py
    rebuilds a weather look (_weather_material), never deleted: every
    per-model look instance references it, and before this a delete that
    the editor refused printed MATERIAL-EXISTS and kept the old graph
    silently (the round-5 materials log: MATERIAL-EXISTS for M_AircraftPaint
    with no REBUILT line; delete-then-build also lost M_StormCell outright,
    2026-10-09)."""
    unreal = _u()
    full = _path(name)
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        if not _rebuild_requested(name):
            print(f"MATERIAL-EXISTS: {full}")
            return None
        material = unreal.EditorAssetLibrary.load_asset(full)
        if material is None or not isinstance(material, unreal.Material):
            raise RuntimeError(f"{full} exists but is not a Material: move it aside by hand "
                               f"(no editor open) and run again")
        unreal.MaterialEditingLibrary.delete_all_material_expressions(material)
        # The graph is gone; the flags the builders set are reset to the
        # factory's, so a builder that does not set one gets the default.
        material.set_editor_property("use_material_attributes", False)
        material.set_editor_property("tangent_space_normal", True)
        print(f"MATERIAL-UPDATED: {full} (graph cleared; built again in place, "
              f"look generation {LOOK_GENERATION})")
        return material
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


def _rgba(material, vector_parameter, x, y):
    """A float4 from a vector parameter: Append(its RGB output, its A output)."""
    node = _node(material, _u().MaterialExpressionAppendVector, x, y)
    _link(vector_parameter, "", node, "A")
    _link(vector_parameter, "A", node, "B")
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


def _min(material, a, b, x, y, a_out="", b_out=""):
    return _binary(material, _u().MaterialExpressionMin, a, b, x, y, a_out, b_out)


def _max(material, a, b, x, y, a_out="", b_out=""):
    return _binary(material, _u().MaterialExpressionMax, a, b, x, y, a_out, b_out)


def _set(target, value, *names):
    """Set the first editor property of ``names`` the object has; a miss is
    reported with the names tried (never silently skipped)."""
    errors = []
    for name in names:
        try:
            target.set_editor_property(name, value)
            return name
        except Exception as exc:  # the Python layer raises on an unknown property
            errors.append(f"{name}: {exc}")
    raise RuntimeError(f"none of {names} on {target.get_class().get_name()}: {errors}")


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


def _generation(material, x, y):
    """The LookGeneration sentinel scalar (round 25)."""
    return _scalar(material, LOOK_GENERATION_PARAMETER, float(LOOK_GENERATION), x, y)


def _attributes(material, x, y):
    return _node(material, _u().MaterialExpressionMakeMaterialAttributes, x, y)


def _use_attributes(material, attributes):
    unreal = _u()
    material.set_editor_property("use_material_attributes", True)
    unreal.MaterialEditingLibrary.connect_material_property(
        attributes, "", _enum(unreal.MaterialProperty, "MP_MATERIAL_ATTRIBUTES"))


def _surface(name, cls, coat, shading_model=None, tangent_normal=False):
    """M_AircraftPaint (coat) / M_AircraftBareMetal (no coat). ``shading_model``
    overrides the model (round 24: M_AircraftPaintDefaultLit, the paint graph
    on MSM_DEFAULT_LIT for -aircraft-probe=defaultlit). ``tangent_normal``
    (round 24: M_AircraftPaintTangentNormal, -aircraft-probe=tangentnormal):
    the material's normal is TANGENT space and the Normal output the constant
    (0, 0, 1), the imported materials' (and the flat probe's) normal path."""
    unreal = _u()
    material = _new(name)
    if material is None:
        return
    material.set_editor_property("shading_model", _enum(
        unreal.MaterialShadingModel, shading_model or ("MSM_CLEAR_COAT" if coat else "MSM_DEFAULT_LIT")))
    material.set_editor_property("tangent_space_normal", bool(tangent_normal))
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
    # round 5 (L4): exhaust soot aft of the look manifest's nozzles (the
    # instance's Nozzle0..3, local cm; the master default is none), broken up
    # by the wear noise (z + 0.5 -> 0..1).
    soot = _mul(material, _custom(material, "exhaust_soot", "CMOT_FLOAT1", {
        "LocalPos": (local, ""),
        # Round 51: a vector parameter's default output is its RGB (float3);
        # exhaust_soot reads float4 nozzles (w = radius), so each input is
        # Append(RGB, A) -- the compile error "expected 16 elements, have 12"
        # that sent every M_AircraftPaint slot to the fallback.
        **{name: (_rgba(material, v[name], -1150, 100 + 40 * i), "")
           for i, name in enumerate(look.SOOT_NOZZLE_PARAMETERS)},
        "LengthRadii": (s["SootLengthRadii"], ""),
        "Noise": (_add(material, breakup, _const(material, 0.5, -800, 50), -700, 50), "")}, -1000, 100),
        s["SootAmount"], -650, 100)
    base = _base_colour(material, -1300, 200)
    raw_base = base   # round 24: -aircraft-probe=rawbase feeds Make.BaseColor from here
    if coat:
        # a livery's pure white is capped at a paint's albedo
        base = _min(material, base, s["AlbedoMax"], -1000, 250)
    else:
        # bare metal: the measured F0 of its metal, the texture's shading through it
        base = _lerp(material, base, _mask(material, v["MetalF0"], "rgb", -1200, 350),
                     s["MetalColourWeight"], -1000, 250)
    # cavity: the groove, the grime and the soot darken the colour; the wear
    # shows the metal (Metallic 1 at the measured aluminium F0).
    darken = _saturate(material, _add(material, _add(
        material, _mul(material, groove, s["PanelDarkening"], -600, -450), grime, -450, -350),
        soot, -400, -300), -300, -350)
    dark = _lerp(material, base, _mul(material, base, _const(material, 0.35, -600, 300), -450, 300),
                 darken, -250, 200)
    colour = _lerp(material, dark, _mask(material, v["WearColour"], "rgb", -300, 100), edge, -100, 200)
    metallic = _lerp(material, s["Metallic"], _const(material, 1.0, -300, 450), edge, -100, 450)
    rough = _saturate(material, _add(material, _add(
        material, _add(material, s["Roughness"], _mul(material, breakup, s["RoughnessBreakup"], -450, 550),
                       -300, 550),
        _mul(material, grime, _const(material, 0.3, -450, 650), -300, 650), -150, 600),
        _mul(material, soot, _const(material, 0.35, -450, 700), -300, 700), -100, 620), 0, 600)
    # round 23 (LOOK_GENERATION 5): PanelAoAmount scales the groove's AO term
    # (0 = AO exactly 1: -aircraft-probe=noao).
    occlusion = _saturate(material, _add(material, _const(material, 1.0, -450, 750),
                                         _mul(material, _mul(material, groove, s["PanelAoAmount"], -750, 820),
                                              _const(material, -0.5, -600, 800),
                                              -450, 800), -300, 780), -150, 780)
    # round 25 (LOOK_GENERATION 7): the generation sentinel, x0 into the AO.
    occlusion = _add(material, occlusion, _mul(material, _generation(material, -450, 880),
                                               _const(material, 0.0, -600, 880), -300, 880), -100, 800)
    out = _attributes(material, 300, 200)
    _link(colour, "", out, ("BaseColor", "Base Color"))
    _link(metallic, "", out, "Metallic")
    _link(s["Specular"], "", out, "Specular")
    _link(rough, "", out, "Roughness")
    # round 23 (LOOK_GENERATION 5): PanelNormalAmount lerps the Normal from the
    # vertex normal (0: -aircraft-probe=nonormal) to panel_lines' (1, gen 4).
    if tangent_normal:
        _link(_const3(material, (0.0, 0.0, 1.0), -400, -650), "", out, "Normal")
    else:
        _link(_lerp(material, normal, _mask(material, panels, "rgb", -600, -600), s["PanelNormalAmount"],
                    -400, -650), "", out, "Normal")
    _link(occlusion, "", out, ("AmbientOcclusion", "Ambient Occlusion"))
    if coat:
        # soot sits on top of the coat: no gloss where it lies
        coat_amount = _mul(material, s["ClearCoat"], _saturate(material, _add(
            material, _const(material, 1.0, -450, 900), _mul(material, soot, _const(material, -1.0, -600, 950),
                                                              -450, 950), -300, 920), -150, 920), 0, 900)
        _link(coat_amount, "", out, ("ClearCoat", "Clear Coat"))
        _link(s["ClearCoatRoughness"], "", out, ("ClearCoatRoughness", "Clear Coat Roughness"))
    _use_attributes(material, out)
    # wet-airframe-canopy: the weather's wetness (shading only, opaque, no WPO).
    aircraft_wet_layer.add_wet_layer(material, sys.modules[__name__], cls, raw_base=raw_base)
    _finish(material, name)


def create_aircraft_paint():
    _surface("M_AircraftPaint", "paint", coat=True)


def create_aircraft_paint_default_lit():
    """M_AircraftPaintDefaultLit (round 24, -aircraft-probe=defaultlit): the
    paint graph exactly, on MSM_DEFAULT_LIT (its coat attributes are then
    ignored). FlightSimAircraftFX.cpp parents a MID to it and copies the
    look instance's overrides."""
    _surface(look.PROBE_DEFAULT_LIT_MASTER, "paint", coat=True, shading_model="MSM_DEFAULT_LIT")


def create_aircraft_paint_tangent_normal():
    """M_AircraftPaintTangentNormal (round 24, -aircraft-probe=tangentnormal):
    the paint graph exactly (clear coat), its normal in TANGENT space, (0, 0, 1)."""
    _surface(look.PROBE_TANGENT_NORMAL_MASTER, "paint", coat=True, tangent_normal=True)


def create_aircraft_probe_flat():
    """M_AircraftProbeFlat (round 23, the -aircraft-probe=flat bisect): a plain
    Default Lit dielectric -- the look instance's BaseColor / BaseColorMap /
    BaseColorMapWeight (copied onto a MID by FlightSimAircraftFX.cpp),
    Metallic 0, Specular 0.5, Roughness 0.5; no Normal (the mesh's own, in
    tangent space), no AO, no coat, no wet layer, no custom node. Opaque, no
    WPO: labels unchanged."""
    unreal = _u()
    name = look.PROBE_FLAT_MASTER
    material = _new(name)
    if material is None:
        return
    material.set_editor_property("shading_model", _enum(unreal.MaterialShadingModel, "MSM_DEFAULT_LIT"))
    lib = unreal.MaterialEditingLibrary
    lib.connect_material_property(_base_colour(material, -900, 0), "", unreal.MaterialProperty.MP_BASE_COLOR)
    lib.connect_material_property(_const(material, 0.0, -400, 300), "", unreal.MaterialProperty.MP_METALLIC)
    lib.connect_material_property(_const(material, 0.5, -400, 400), "", unreal.MaterialProperty.MP_SPECULAR)
    lib.connect_material_property(_const(material, 0.5, -400, 500), "", unreal.MaterialProperty.MP_ROUGHNESS)
    _finish(material, name)


def create_aircraft_paint_coat():
    """M_AircraftPaintCoat (round 25): the paint as a plain Clear Coat
    material with NO Custom node, no world-space normal, no attributes and
    no wet graft -- only engine nodes, so it compiles wherever the flat
    probe does. Base colour: the look instance's BaseColor / BaseColorMap /
    BaseColorMapWeight exactly as M_AircraftProbeFlat (no albedo cap, so it
    is never darker than flat); Metallic, Specular, Roughness, ClearCoat and
    ClearCoatRoughness are parameters of the paint's names, so
    FlightSimAircraftFX.cpp's CopyParameterOverrides carries the look
    config's numbers (the A-4's Roughness 0.5, ClearCoat 0.25). The normal
    is the mesh's own (tangent space, unconnected).

    Why: rounds 37-39 (-aircraft-probe=defaultlit / tangentnormal /
    nocoat,noao,nonormal,nowear,nowet,rawbase) drew byte-identical frames
    and round 40's basecolor-debug drew the same lit airframe, untextured
    (the A-4's red tail stripe gone) -- the engine's default material,
    which a material that fails to compile draws; only the flat master,
    the one without Custom nodes, changed pixels. The host compile-checks
    the class masters and falls back to this one (then to flat), recorded
    in render.json aircraft_look.materials.master_compile. Opaque, no WPO:
    labels unchanged."""
    unreal = _u()
    name = look.PROBE_COAT_MASTER
    material = _new(name)
    if material is None:
        return
    material.set_editor_property("shading_model", _enum(unreal.MaterialShadingModel, "MSM_CLEAR_COAT"))
    lib = unreal.MaterialEditingLibrary
    s = {key: _scalar(material, key, value, -500, 300 + 100 * i)
         for i, (key, value) in enumerate(look.COAT_SCALARS.items())}
    # Round 51: UE 5.7's Python MaterialProperty has no clear-coat pin
    # (MP_CUSTOM_DATA0 / MP_CLEAR_COAT absent), so the coat master goes
    # through MakeMaterialAttributes, the route the class masters use --
    # still no Custom node.
    out = _attributes(material, 0, 0)
    _link(_base_colour(material, -900, 0), "", out, ("BaseColor", "Base Color"))
    _link(s["Metallic"], "", out, "Metallic")
    _link(s["Specular"], "", out, "Specular")
    _link(s["Roughness"], "", out, "Roughness")
    _link(s["ClearCoat"], "", out, ("ClearCoat", "Clear Coat"))
    _link(s["ClearCoatRoughness"], "", out, ("ClearCoatRoughness", "Clear Coat Roughness"))
    # The sentinel, x0 into the AO (otherwise AO 1).
    _link(_add(material, _const(material, 1.0, -300, 900), _mul(
        material, _generation(material, -500, 1000), _const(material, 0.0, -500, 1100), -300, 1000), -150, 950),
        "", out, ("AmbientOcclusion", "Ambient Occlusion"))
    _use_attributes(material, out)
    _finish(material, name)


def create_aircraft_bare_metal():
    _surface("M_AircraftBareMetal", "bare_metal", coat=False)


def create_aircraft_glass():
    _glass("M_AircraftGlass")


def create_aircraft_glass_reflect():
    """Generation 11: tier 0 of the canopy reflection (aircraft_glass_reflect.py)."""
    _glass(aircraft_glass_reflect.MASTERS[0], reflect_tier=0)


def create_aircraft_glass_reflect_fine():
    """Generation 11: tier 1 of the canopy reflection (aircraft_glass_reflect.py)."""
    _glass(aircraft_glass_reflect.MASTERS[1], reflect_tier=1)


def _glass(name, reflect_tier=None):
    """The opaque glass graph; ``reflect_tier`` (0 / 1) grafts the canopy
    reflection after the canopy scratches. None is M_AircraftGlass exactly."""
    unreal = _u()
    material = _new(name)
    if material is None:
        return
    material.set_editor_property("shading_model", _enum(unreal.MaterialShadingModel, "MSM_DEFAULT_LIT"))
    s = {k: _scalar(material, k, v, -900, 100 * i)
         for i, (k, v) in enumerate(look.CLASS_SCALARS["glass"].items())}
    tint = _vector(material, "GlassTint", look.CLASS_VECTORS["glass"]["GlassTint"], -900, 700)
    base = _base_colour(material, -900, 900)
    fresnel = _node(material, unreal.MaterialExpressionFresnel, -600, 300)
    # pow(1 - N.V, e) alone: the node's default base reflect fraction (0.04)
    # would lift the face-on Specular above the class value, F0 above acrylic.
    fresnel.set_editor_property("base_reflect_fraction", 0.0)
    _link(s["FresnelExponent"], "", fresnel, ("ExponentIn", "Exponent"))
    # Specular 0.5 + ReflectionBoost 0.5 x Fresnel <= 1: the saturate is a
    # guard, never the shape (aircraft_look.CLASS_SCALARS["glass"]).
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
    if reflect_tier is not None:
        aircraft_glass_reflect.add_reflection(material, sys.modules[__name__], reflect_tier, aircraft_wet_layer)
    _finish(material, name)


def create_aircraft_rubber():
    unreal = _u()
    material = _new("M_AircraftRubber")
    if material is None:
        return
    material.set_editor_property("shading_model", _enum(unreal.MaterialShadingModel, "MSM_DEFAULT_LIT"))
    s = {k: _scalar(material, k, v, -900, 100 * i)
         for i, (k, v) in enumerate(look.CLASS_SCALARS["rubber"].items())}
    # round 5 (L4): the measured tyre albedo floors the MTL's colour (a
    # pure-black Kd reflects nothing; a tyre reflects 2.3 %).
    floor = _mask(material, _vector(material, "RubberFloor", look.CLASS_VECTORS["rubber"]["RubberFloor"],
                                    -1100, 500), "rgb", -900, 500)
    base = _max(material, _base_colour(material, -900, 600), floor, -500, 550)
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
    unreal = _u()
    colour, intensity, strobe, beam_direction, beam_cos = look.FX_PARAMETERS["M_NavLightEmissive"]
    # The beam axis is set in the ACTOR frame (the lamp actor hangs on the
    # aircraft with its rotation), turned to world here; the omni default
    # BeamCos (-2, -2) draws the bulb from every side.
    direction = _node(material, unreal.MaterialExpressionTransform, -900, 600)
    direction.set_editor_property("transform_source_type",
                                  unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_LOCAL)
    direction.set_editor_property("transform_type", unreal.MaterialVectorCoordTransform.TRANSFORM_WORLD)
    _link(_mask(material, _vector(material, beam_direction, (1.0, 0.0, 0.0, 0.0), -1300, 600),
                "rgb", -1100, 600), "", direction, "")
    beam_dir = _node(material, unreal.MaterialExpressionNormalize, -700, 600)
    _link(direction, "", beam_dir, "")
    glow = _custom(material, "nav_bulb", "CMOT_FLOAT3", {
        "UV": (_uv(material, -700, 0), ""),
        "LightColour": (_mask(material, _vector(material, colour, (1.0, 1.0, 1.0, 1.0), -900, 150),
                              "rgb", -700, 150), ""),
        # cd/m2 (aircraft_look.bulb_luminance_nits); the C++ always sets it.
        "Intensity": (_scalar(material, intensity, 1.0, -700, 300), ""),
        "Strobe": (_scalar(material, strobe, 1.0, -700, 400), ""),
        "CameraDir": (_node(material, unreal.MaterialExpressionCameraVectorWS, -700, 500), ""),
        "BeamDir": (beam_dir, ""),
        "BeamCos": (_mask(material, _vector(material, beam_cos, (*look.OMNI_BEAM_COS, 0.0, 0.0), -900, 700),
                          "rg", -700, 700), "")}, -400, 100)
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
        # The hue only (core luminance 1): the C++ sets hue x the plume's
        # luminance from the look manifest (aircraft_look.plume_luminance),
        # the same AfterburnerCandela its light throws. UNCALIBRATED hue.
        "CoreColour": (_mask(material, _vector(material, core, (*look.AFTERBURNER_CORE_HUE, 1.0), -900, 200),
                             "rgb", -700, 200), ""),
        "TipColour": (_mask(material, _vector(material, tip, (*look.AFTERBURNER_TIP_HUE, 1.0), -900, 320),
                            "rgb", -700, 320), ""),
        "Shocks": (_scalar(material, shocks, look.AFTERBURNER_DEFAULTS["Shocks"], -700, 440), "")},
        -400, 100)
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
    opacity_name, formation_name, ramp_name = look.FX_PARAMETERS["M_AircraftContrail"]
    opacity = _custom(material, "contrail_opacity", "CMOT_FLOAT1", {
        "UV": (_uv(material, -700, 0), ""),
        "LocalPos": (_node(material, unreal.MaterialExpressionLocalPosition, -700, 100), ""),
        "Opacity": (_scalar(material, opacity_name, 0.55, -700, 200), ""),
        "Formation": (_scalar(material, formation_name, 0.01, -700, 300), ""),
        # LOOK_GENERATION 7 (round 47, #13): the formation ramp as an age fraction;
        # 0.04 is generation 6's fixed ramp (the C++ sets FormationRampS / LifetimeS).
        "FormationRamp": (_scalar(material, ramp_name, 0.04, -700, 400), "")}, -400, 100)
    lib = unreal.MaterialEditingLibrary
    lib.connect_material_property(_const3(material, (0.92, 0.94, 0.97), -400, -100), "",
                                  unreal.MaterialProperty.MP_BASE_COLOR)
    lib.connect_material_property(_const(material, 0.9, -400, 0), "", unreal.MaterialProperty.MP_ROUGHNESS)
    # LOOK_GENERATION 12 (round 93, #13's rulers): the opacity fades in with the
    # camera's distance (aircraft_look CONTRAIL_DEFAULTS CameraFade*).
    fade = _node(material, unreal.MaterialExpressionCameraDepthFade, -150, 100)
    _link(opacity, "", fade, ("InOpacity", "Opacity"))
    _link(_scalar(material, "CameraFadeLength", 100.0 * look.CONTRAIL_DEFAULTS["CameraFadeLengthM"], -400, 250),
          "", fade, ("FadeLength", "Fade Length"))
    _link(_scalar(material, "CameraFadeOffset", 100.0 * look.CONTRAIL_DEFAULTS["CameraFadeOffsetM"], -400, 350),
          "", fade, ("FadeOffset", "Fade Offset"))
    lib.connect_material_property(fade, "", unreal.MaterialProperty.MP_OPACITY)
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


def create_aircraft_glass_thin():
    """round 5 (L4): M_AircraftGlassThin, the Thin Translucent canopy. Built
    beside (not instead of) the opaque M_AircraftGlass; applied by the C++
    only on a render without -labels (aircraft_look.THIN_GLASS_MASTER)."""
    unreal = _u()
    material = _new(look.THIN_GLASS_MASTER)
    if material is None:
        return
    # MaterialShared.cpp (5.7.4) requires of MSM_ThinTranslucent: a translucent
    # blend mode, TLM_SurfacePerPixelLighting, no other shading model, and a
    # ThinTranslucentMaterialOutput node; not the After-Motion-Blur pass (the
    # default pass is before DOF).
    material.set_editor_property("blend_mode", _enum(unreal.BlendMode, "BLEND_TRANSLUCENT"))
    material.set_editor_property("shading_model", _enum(unreal.MaterialShadingModel,
                                                        "MSM_THIN_TRANSLUCENT", "MSM_THINTRANSLUCENT"))
    material.set_editor_property("translucency_lighting_mode", _enum(
        unreal.TranslucencyLightingMode, "TLM_SURFACE_PER_PIXEL_LIGHTING", "TLM_SURFACEPERPIXELLIGHTING"))
    # SSR on the pane (L1's screen-space reflections), the canopy in custom
    # depth (its stencil id is the airframe's), one-sided like the opaque one,
    # no refraction: a thin pane with parallel faces shifts nothing (and a
    # refraction would move pixels).
    _set(material, True, "screen_space_reflections", "b_screen_space_reflections")
    _set(material, True, "allow_translucent_custom_depth_writes")
    material.set_editor_property("two_sided", False)
    material.set_editor_property("refraction_method", _enum(unreal.RefractionMode, "RM_NONE", "RM_None"))
    s = {k: _scalar(material, k, v, -900, 100 * i) for i, (k, v) in enumerate(look.THIN_SCALARS.items())}
    v = {k: _vector(material, k, d, -900, 700 + 120 * i) for i, (k, d) in enumerate(look.THIN_VECTORS.items())}
    base = _base_colour(material, -900, 900)
    colour = _mul(material, base, s["GlassDiffuse"], -300, 900)
    out = _attributes(material, 100, 200)
    _link(colour, "", out, ("BaseColor", "Base Color"))
    _link(s["Metallic"], "", out, "Metallic")
    _link(s["Specular"], "", out, "Specular")
    _link(s["Roughness"], "", out, "Roughness")
    # Opacity is left at the Make node's default (1: a whole pane; the
    # transmittance, not the opacity, is what the sky comes through).
    _use_attributes(material, out)
    thin = _node(material, unreal.MaterialExpressionThinTranslucentMaterialOutput, 100, 700)
    _link(_mask(material, v["Transmittance"], "rgb", -300, 700), "", thin,
          ("TransmittanceColor", "Transmittance Color"))
    # wet-airframe-canopy: rain beads and streaks on the pane (shading only).
    aircraft_wet_layer.add_wet_layer(material, sys.modules[__name__], "glass")
    _finish(material, look.THIN_GLASS_MASTER)


#: Every master this module builds, in build order (class masters, then FX).
CREATORS = (create_aircraft_paint, create_aircraft_bare_metal, create_aircraft_glass,
            create_aircraft_rubber, create_aircraft_glass_thin, create_aircraft_probe_flat,
            create_aircraft_paint_default_lit, create_aircraft_paint_tangent_normal,
            create_aircraft_paint_coat,
            create_aircraft_glass_reflect, create_aircraft_glass_reflect_fine,
            create_nav_light_emissive,
            create_aircraft_contrail, create_aircraft_afterburner, create_aircraft_heat_haze)
#: The asset each creator makes (pinned to look.CLASS_MASTERS / THIN_GLASS_MASTER /
#: FX_MASTERS by test).
CREATED = ("M_AircraftPaint", "M_AircraftBareMetal", "M_AircraftGlass", "M_AircraftRubber",
           "M_AircraftGlassThin", "M_AircraftProbeFlat", "M_AircraftPaintDefaultLit",
           "M_AircraftPaintTangentNormal", "M_AircraftPaintCoat",
           "M_AircraftGlassReflect", "M_AircraftGlassReflectFine",
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
