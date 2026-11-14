"""The aircraft look (visual overhaul, aircraft lane): which master material
every imported material slot takes, and where the beauty-only lights,
nozzles and trails sit on the drawn airframe. Plain Python (stdlib only,
so it also runs inside UnrealEditor's Python); tested without an engine
by tests/test_aircraft_look.py.

Inputs, per aircraft:

* ``assets/aircraft_config/look/<NAME>.json`` -- the look config (schema
  :data:`LOOK_SCHEMA`). It lives in its OWN folder, not in
  ``assets/aircraft_config/<NAME>.json``, on purpose: that file's sha256 is
  recorded in every run manifest as label provenance
  (core/capture/manifest.py asset_digests), and a look tweak must not move
  a label record. The non-recursive ``*.json`` globs that read the
  aircraft configs (importer, licence and config tests) never see it.
* the converted model ``assets/generated/<NAME>/`` (the *.mtl files and
  the body OBJ the converters wrote, and mesh_manifest.json);
* the flown FDM XML (thruster stations, engine thrust).

Output: ``assets/generated/<NAME>/look_manifest.json``
(:data:`LOOK_MANIFEST_MAGIC`), which FlightSimAircraftFX.cpp reads on a
-quality=beauty render. Every position in it is in the UE ACTOR frame
(cm, +X forward, +Y right, +Z up, about the JSBSim structural datum: the
frame BuildMeshAirframe hangs the mesh in), every one says how it was
obtained (``basis``), and every look number that no probe render has set
yet carries the word UNCALIBRATED with the probe that should set it.

Nothing here changes a ``-quality=measure`` render: the C++ builds none of
it outside beauty, and the mesh assets' own materials are never edited
(the look instances are separate assets under <asset root>/Look).

    python scripts/aircraft_look.py J11          # write the look manifest
    python scripts/aircraft_look.py --check-all  # validate every look config
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

# wet-airframe-canopy module: its shader inputs and constants (stdlib only).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aircraft_wet_layer import WET_SHADER_INPUTS, constants_group as _wet_constants  # noqa: E402
# canopy reflection (swarm lane aircraft_exterior.glass.coastal, tiers 0-1;
# beauty only, -canopy-reflect=on): its shader inputs and masters (stdlib only).
from aircraft_glass_reflect import GLASS_REFLECT_SHADER_INPUTS, MASTERS as _reflect_masters  # noqa: E402
# round 5 (L4): the vendored Physically Based API database (CC0, pinned by
# sha256 in assets/looks/physically_based/PIN.json), the measured constants.
import physically_based as _pb  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(REPO, "assets", "aircraft_config")
LOOK_DIR = os.path.join(CONFIG_DIR, "look")
GENERATED = os.path.join(REPO, "assets", "generated")
FDM_AIRCRAFT = os.path.join(REPO, "ue", "Plugins", "JSBSimFlightDynamicsModel",
                            "Resources", "JSBSim", "aircraft")

LOOK_SCHEMA = "flightsim-aircraft-look/1"
LOOK_MANIFEST_MAGIC = "flightsim-aircraft-look-manifest"
LOOK_MANIFEST_VERSION = 1
LOOK_MANIFEST_NAME = "look_manifest.json"

#: The word every look number not yet set by a probe render carries.
UNCALIBRATED = "UNCALIBRATED: set by probe render on the render machine"

CM_PER_IN = 2.54
CM_PER_M = 100.0

# -- material classes ----------------------------------------------------------

#: The master material of each slot class (scripts/ue_aircraft_master_materials.py
#: builds them; FlightSimAircraftFX.cpp never loads these by path -- it loads
#: the per-model instances -- so they live outside /Game/FlightSim on purpose).
MASTER_ROOT = "/Game/FlightSim/Aircraft"
CLASS_MASTERS = {
    "paint": "M_AircraftPaint",
    "bare_metal": "M_AircraftBareMetal",
    "glass": "M_AircraftGlass",
    "rubber": "M_AircraftRubber",
}
#: The beauty-only FX masters (FlightSimAircraftFX.cpp loads these by path).
FX_MASTERS = ("M_NavLightEmissive", "M_AircraftContrail", "M_AircraftAfterburner",
              "M_AircraftHeatHaze", "M_AircraftCondensation")
SLOT_CLASSES = tuple(CLASS_MASTERS)
#: The per-model instance folder and name: <asset root>/Look/MI_<slot>.
LOOK_INSTANCE_FOLDER = "Look"
LOOK_INSTANCE_PREFIX = "MI_"

#: round 5 (L4): the measured constants, read from the vendored Physically
#: Based API database (linear sRGB; for a metal the base colour IS its F0).
#: Aluminium 0.916 0.923 0.924, titanium 0.441 0.400 0.361, stainless steel
#: 0.669 0.639 0.598; tyre rubber albedo 0.023, roughness 0.7, n 1.5; car
#: paint n 1.5 (a dielectric: F0 0.04, UE Specular 0.5). Pinned by test to
#: the database rows, so a re-vendor that moves a number moves these.
ALUMINIUM_F0 = _pb.metal_f0("Aluminum")
TITANIUM_F0 = _pb.metal_f0("Titanium")
STEEL_F0 = _pb.metal_f0("Stainless Steel")
TIRE = _pb.material("Tire")
TIRE_ALBEDO = _pb.linear_color(TIRE)
TIRE_ROUGHNESS = float(TIRE["roughness"])
TIRE_IOR = float(TIRE["ior"])
PAINT_IOR = float(_pb.material("Car Paint")["ior"])
#: The named bare metals a slot rule may pick (``"metal": "titanium"`` on a
#: bare_metal rule: the nozzle petals, a leading-edge strip, the spinner).
METALS = {"aluminium": ALUMINIUM_F0, "titanium": TITANIUM_F0, "stainless_steel": STEEL_F0}

#: Every scalar each class master exposes, with its default. Each value is a
#: look choice unless it says "measured" -- UNCALIBRATED otherwise (probe:
#: the V7 side-by-side of each type against a reference photo at matched sun,
#: reader's judgment).
#: Why paint is NOT metallic: a painted panel is a dielectric under a clear
#: coat (F0 0.04 at n 1.5, the database's car paint), and any metallic on
#: paint reads as chrome under reflections; round 5 drops the old 0.15
#: "flake". Bare metal is Metallic 1 with the measured F0 as its colour (the
#: P-51D's polished skin, exhaust and leading-edge panels); its roughness
#: 0.25-0.45 band comes from RoughnessBreakup's low-frequency noise. Paint's
#: AlbedoMax caps a livery's pure white (a linear 1.0 reflects more than any
#: paint; 0.9 is a fresh white enamel, from memory). The panel lines are
#: kept low (PanelDepth, PanelDarkening): a hint, never a grid.
#: PanelNormalAmount and PanelAoAmount (round 23, LOOK_GENERATION 5) are the
#: bisect probes' handles, 1 = the gen-4 graph: the Normal output lerps from the
#: vertex normal to panel_lines' (0 = the vertex normal) and the groove's AO
#: term scales by the second (0 = AO exactly 1); -aircraft-probe=nonormal,noao.
CLASS_SCALARS = {
    "paint": {
        "Metallic": 0.0, "Roughness": 0.4, "RoughnessBreakup": 0.12,
        "ClearCoat": 0.8, "ClearCoatRoughness": 0.1,
        "PanelDepth": 0.2, "PanelWidthCm": 0.35, "PanelDarkening": 0.15,
        "WearAmount": 0.25, "GrimeAmount": 0.2, "Specular": 0.5,
        "NoiseCm": 35.0, "EdgeStart": 0.02, "EdgeEnd": 0.2,
        "AlbedoMax": 0.9, "SootAmount": 0.45, "SootLengthRadii": 10.0,
        "PanelNormalAmount": 1.0, "PanelAoAmount": 1.0,
    },
    "bare_metal": {
        "Metallic": 1.0, "Roughness": 0.35, "RoughnessBreakup": 0.2,
        "PanelDepth": 0.25, "PanelWidthCm": 0.3, "PanelDarkening": 0.15,
        "WearAmount": 0.1, "GrimeAmount": 0.25, "Specular": 0.5,
        "NoiseCm": 60.0, "EdgeStart": 0.02, "EdgeEnd": 0.2,
        "MetalColourWeight": 0.7, "SootAmount": 0.45, "SootLengthRadii": 10.0,
        "PanelNormalAmount": 1.0, "PanelAoAmount": 1.0,
    },
    # Canopy acrylic (PMMA, n 1.49): F0 = ((n - 1) / (n + 1))^2 = 0.039, and
    # UE's F0 is 0.08 x Specular, so Specular 0.5 (polycarbonate, n 1.586,
    # would be 0.64). The engine's BRDF already applies Schlick's grazing
    # Fresnel to that F0; ReflectionBoost x pow(1 - N.V, FresnelExponent) on
    # top is a NON-PHYSICAL look gain (a cockpit glass reads glossier than
    # its F0 at mid angles), kept at most 1 - Specular so the saturate never
    # swallows it: face-on F0 stays GLASS_F0 (the master sets the Fresnel
    # node's own base reflect fraction to 0), grazing Specular <= 1.
    "glass": {
        "Metallic": 0.0, "Roughness": 0.04, "Specular": 0.5, "FresnelExponent": 5.0,
        "ReflectionBoost": 0.5,
    },
    # Measured tyre rubber (the database's "Tire": roughness 0.7, n 1.5 so
    # Specular 0.5); the master floors the MTL's Kd at the measured albedo
    # (RubberFloor), because a pure-black Kd reflects nothing, which no tyre does.
    "rubber": {
        "Metallic": 0.0, "Roughness": TIRE_ROUGHNESS,
        "Specular": round(_pb.specular_from_ior(TIRE_IOR), 4), "RoughnessBreakup": 0.08,
    },
}
#: UE's dielectric F0 per unit Specular (ShadingCommon.ush
#: DielectricSpecularToF0: 0.08 x Specular, UE 5.7.4) and the canopy F0 the
#: glass Specular above is meant to give (acrylic, n 1.49: 0.039).
UE_F0_PER_SPECULAR = _pb.UE_F0_PER_SPECULAR
GLASS_IOR = 1.49
GLASS_F0 = ((GLASS_IOR - 1.0) / (GLASS_IOR + 1.0)) ** 2

#: The nozzle vectors the soot reads (exhaust_soot.hlsl): xyz the exit centre
#: in the mesh's LOCAL frame (cm), w the exit radius (cm; 0 = none). The
#: master default is "no nozzle"; create_look_instances sets them per model
#: from the look manifest (nozzle_vectors).
SOOT_NOZZLE_PARAMETERS = ("Nozzle0", "Nozzle1", "Nozzle2", "Nozzle3")
NO_NOZZLE = (0.0, 0.0, 0.0, 0.0)

#: Every vector each class master exposes (linear RGBA), with its default.
#: WearColour: the bare metal a chipped edge exposes (the measured aluminium
#: F0; the wear lerps to Metallic 1 with this as its colour). MetalF0: the
#: bare_metal class's own metal (aluminium unless a slot rule names another).
CLASS_VECTORS = {
    "paint": {"PanelPitchCm": (120.0, 90.0, 45.0, 0.0), "WearColour": (*ALUMINIUM_F0, 1.0),
              **{name: NO_NOZZLE for name in SOOT_NOZZLE_PARAMETERS}},
    "bare_metal": {"PanelPitchCm": (90.0, 60.0, 35.0, 0.0), "WearColour": (*ALUMINIUM_F0, 1.0),
                   "MetalF0": (*ALUMINIUM_F0, 1.0),
                   **{name: NO_NOZZLE for name in SOOT_NOZZLE_PARAMETERS}},
    "glass": {"GlassTint": (0.018, 0.022, 0.026, 1.0)},
    "rubber": {"RubberFloor": (*TIRE_ALBEDO, 1.0)},
}

# -- round 5 (L4): the Thin Translucent canopy ----------------------------------
#
# A second instance for every GLASS slot, MI_<slot>_thin, parented to
# M_AircraftGlassThin: blend Translucent, shading model Thin Translucent,
# lighting mode Surface ForwardShading (what MaterialShared.cpp requires of
# the model, UE 5.7.4), screen-space reflections on, no refraction (a thin
# pane with parallel faces shifts nothing), n 1.5 so Specular 0.5, roughness
# 0.02, and a Transmittance tint through the ThinTranslucentMaterialOutput
# node. D3D11 SM5 supports it: the base pass has a dual-source-blend path
# (PCD3D_SM5 bSupportsDualSourceBlending=true) and a single-target fallback.
#
# LABELS: a translucent surface writes no scene depth, and the ID and depth
# label captures draw no translucency at all, so a thin canopy in a labelled
# frame would put the far wall (or the sky) in the labels where the beauty
# shows the canopy. FlightSimAircraftFX.cpp therefore applies MI_<slot>_thin
# ONLY when the render carries no -labels; with -labels the opaque
# MI_<slot> (M_AircraftGlass, which writes depth) stays, as before. The
# opaque glass master is unchanged: it is the label-safe canopy.
THIN_GLASS_MASTER = "M_AircraftGlassThin"
THIN_CLASS = "glass_thin"
THIN_INSTANCE_SUFFIX = "_thin"
THIN_GLASS_IOR = 1.5
THIN_SCALARS = {
    "Metallic": 0.0, "Roughness": 0.02,
    "Specular": round(_pb.specular_from_ior(THIN_GLASS_IOR), 4),
    # the pane's own diffuse: the imported colour x this (a clear canopy is
    # nearly black diffusely; a film of dirt lifts it). UNCALIBRATED.
    "GlassDiffuse": 0.03,
}
#: Transmittance (linear RGB): a lightly tinted acrylic canopy, UNCALIBRATED
#: (the measured soda-lime glass is 0.98-0.99 per cm; canopies are tinted).
THIN_VECTORS = {"Transmittance": (0.80, 0.84, 0.82, 1.0)}


def thin_instance_name(slot):
    return instance_name(slot) + THIN_INSTANCE_SUFFIX
#: The texture/colour parameters every class master shares (the names the
#: imported Interchange instances use, so the MTL wiring of
#: ue_aircraft_materials.plan carries straight over).
BASE_PARAMETERS = ("BaseColorMap", "BaseColor", "BaseColorMapWeight")
#: The FX masters' parameters, by the names FlightSimAircraftFX.cpp sets
#: (pinned to its text by tests/test_aircraft_look.py).
FX_PARAMETERS = {
    "M_NavLightEmissive": ("LightColour", "Intensity", "Strobe", "BeamDirection", "BeamCos"),
    "M_AircraftContrail": ("Opacity", "Formation", "FormationRamp"),
    "M_AircraftAfterburner": ("Intensity", "CoreColour", "TipColour", "Shocks"),
    "M_AircraftHeatHaze": ("TimeS", "Strength"),
    # condensation-solver (scripts/aircraft_condensation_material.py PARAMETERS).
    "M_AircraftCondensation": ("Opacity", "Shape"),
}
#: The committed Custom-node bodies (assets/shaders/aircraft/<name>.hlsl) and
#: their inputs, in order.
SHADER_DIR = "assets/shaders/aircraft"
SHADER_INPUTS = {
    "panel_lines": ("LocalPos", "NormalWS", "AxisX", "AxisY", "AxisZ", "Pitch", "WidthCm", "Depth"),
    "aircraft_wear": ("LocalPos", "NormalWS", "WorldPosCm", "NoiseCm", "EdgeStart", "EdgeEnd"),
    # round 5 (L4): exhaust soot aft of the nozzles (twin: soot_mask).
    "exhaust_soot": ("LocalPos", *SOOT_NOZZLE_PARAMETERS, "LengthRadii", "Noise"),
    "nav_bulb": ("UV", "LightColour", "Intensity", "Strobe", "CameraDir", "BeamDir", "BeamCos"),
    "contrail_opacity": ("UV", "LocalPos", "Opacity", "Formation", "FormationRamp"),
    "afterburner_glow": ("UV", "Intensity", "CoreColour", "TipColour", "Shocks"),
    "heat_haze": ("UV", "LocalPos", "TimeS", "Strength"),
    # wet-airframe-canopy: "aircraft_wet" and "canopy_scratch".
    **WET_SHADER_INPUTS,
    # canopy reflection: "glass_reflect_uv", "glass_reflect", "glass_micro_uv".
    **GLASS_REFLECT_SHADER_INPUTS,
}
#: The opaque canopy-reflect masters by tier (scripts/aircraft_glass_reflect.py):
#: drawn only under -canopy-reflect=on, on a glass slot's opaque instance.
CANOPY_REFLECT_MASTERS = dict(_reflect_masters)

#: Automatic slot rules, applied after a config's own ``slot_rules``:
#: an MTL ``d`` below this is glass (the converters write ``d`` only for a
#: transparent .ac material: convert.py ObjWriter; measured here, the A320's
#: windows rgb_707070 d 0.173 and the B747's rgb_6b6b6b d 0.200); an
#: untextured material whose Kd never exceeds this is rubber (tyres, seals).
GLASS_MAX_DISSOLVE = 0.95
RUBBER_MAX_KD = 0.06


class LookError(ValueError):
    """A look config or input that cannot be used, by name."""


def parse_mtl(text):
    """{name: {"kd": (r, g, b), "map_kd": file or None, "d": float}} --
    ue_aircraft_materials.parse_mtl plus the dissolve the converters write."""
    materials = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        word, _, rest = line.partition(" ")
        rest = rest.strip()
        if word == "newmtl":
            current = {"kd": (0.8, 0.8, 0.8), "map_kd": None, "d": 1.0}
            materials[rest] = current
        elif current is None:
            continue
        elif word == "Kd":
            values = [float(v) for v in rest.split()[:3]]
            if len(values) == 3:
                current["kd"] = tuple(values)
        elif word == "d" and rest:
            current["d"] = float(rest.split()[0])
        elif word == "map_Kd" and rest:
            current["map_kd"] = os.path.basename(rest.split()[-1].replace("\\", "/"))
    return materials


def read_mtl_dir(directory):
    materials = {}
    for name in sorted(os.listdir(directory)):
        if name.lower().endswith(".mtl"):
            with open(os.path.join(directory, name), encoding="utf-8") as handle:
                materials.update(parse_mtl(handle.read()))
    return materials


def classify_slot(name, material, config):
    """(class, rule) for one MTL material: the config's ``slot_rules``
    (regex over the name, first full match wins), then glass by dissolve,
    rubber by a dark untextured Kd, then the config's ``default_class``."""
    cls, rule, _ = classify_slot_rule(name, material, config)
    return cls, rule


def classify_slot_rule(name, material, config):
    """:func:`classify_slot` plus the matching slot rule itself (None when a
    built-in rule classified the slot): a rule may carry per-slot choices
    such as ``metal``."""
    for rule in config.get("slot_rules", []):
        if re.fullmatch(rule["match"], name):
            return rule["class"], f"slot_rules {rule['match']!r}", rule
    if material.get("d", 1.0) < GLASS_MAX_DISSOLVE:
        return "glass", f"MTL d {material['d']:.3f} < {GLASS_MAX_DISSOLVE}", None
    if not material.get("map_kd") and max(material.get("kd", (1, 1, 1))) <= RUBBER_MAX_KD:
        return "rubber", f"untextured, Kd max <= {RUBBER_MAX_KD}", None
    default = config.get("default_class", "paint")
    return default, "default_class", None


def instance_name(slot):
    return LOOK_INSTANCE_PREFIX + slot


#: ue_aircraft_materials.INVALID_ASSET_NAME_CHARACTERS (pinned equal by
#: tests/test_aircraft_materials.py): UE replaces each with "_" in an
#: imported asset's name, so panel.wcs.png is TEX_panel_wcs.
INVALID_ASSET_NAME_CHARACTERS = "\"' ,/.:|&!~\n\r\t@#(){}[]=;^%$`\\*?<>"


def texture_asset_name(file_name):
    """ue_aircraft_materials.texture_asset_name: the imported texture of an
    MTL ``map_Kd`` file."""
    name = "TEX_" + os.path.splitext(os.path.basename(file_name))[0]
    for character in INVALID_ASSET_NAME_CHARACTERS:
        name = name.replace(character, "_")
    return name


# -- FlightGear material -> PBR (j11-package lane) ------------------------------
#
# A FlightGear .ac MATERIAL is fixed-function Phong: rgb (diffuse), spec
# (specular colour) and shi (Phong exponent, 0-128). The converter records,
# per MTL material, the .ac materials its triangles came from
# (assets/generated/<NAME>/material_sources.json); a look config with an
# ``fg_material`` block derives per-slot PBR scalars from them:
#
# * Roughness from shi: the Blinn-Phong exponent n and a microfacet
#   distribution of the same lobe width are related by alpha^2 = 2 / (n + 2)
#   (Walter et al. 2007's Phong <-> Beckmann match, from memory), and UE's
#   roughness r has alpha = r^2, so r = (2 / (n + 2)) ** 0.25: shi 128 ->
#   0.35, 64 -> 0.42, 10 -> 0.64, 0 -> 1.0. Triangle-weighted over the .ac
#   materials of the slot, then clamped to the config's range.
# * Specular from spec: the mean of the specular colour (UE Specular 0.5 is
#   F0 4 %, a plain dielectric) -- off unless the config lists it, because
#   FlightGear authors set spec 0 or 1 by habit.
# * Metallic is NEVER derived: Phong carries no metal term, and the package
#   ships no specular or metalness map (docs/visual/J11_PACKAGE.md), so a
#   metallic would be invented; the class master's value stays.
#
# Precedence, least to most specific: the master's default, the config's
# class_scalars (a class-wide look choice), the derived per-slot value (a
# fact about this slot's own source material). Every derived value is a
# formula applied to an artist's Phong number: UNCALIBRATED as a look.

FG_DERIVABLE = ("Roughness", "Specular")
FG_MATERIAL_KEYS = {"parameters", "classes", "roughness_min", "roughness_max", "source"}
MATERIAL_SOURCES_NAME = "material_sources.json"
MATERIAL_SOURCES_MAGIC = "flightsim-aircraft-material-sources"


def roughness_from_shininess(shininess):
    """UE roughness of a Phong exponent: (2 / (n + 2)) ** 0.25."""
    n = max(float(shininess), 0.0)
    return (2.0 / (n + 2.0)) ** 0.25


def read_material_sources(directory):
    """The converter's per-material record beside the OBJs, or {} when the
    conversion predates it (nothing is derived then)."""
    path = os.path.join(directory, MATERIAL_SOURCES_NAME)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("magic") != MATERIAL_SOURCES_MAGIC:
        raise LookError(f"{path} is not a material sources file")
    return data.get("materials", {})


def derive_fg_scalars(source, cls, fg_config):
    """(scalars, record) derived for one slot from its material source row,
    or ({}, None) when the config derives nothing for this class."""
    if not fg_config or not source or cls not in fg_config.get("classes", ()):
        return {}, None
    rows = [r for r in source.get("ac_materials", {}).values() if r.get("triangles", 0) > 0]
    total = sum(r["triangles"] for r in rows)
    if not total:
        return {}, None
    out, record = {}, {"ac_materials": sorted(source["ac_materials"]), "triangles": total}
    wanted = fg_config.get("parameters", ())
    if "Roughness" in wanted:
        raw = sum(roughness_from_shininess(r["shininess"]) * r["triangles"] for r in rows) / total
        lo = float(fg_config.get("roughness_min", 0.0))
        hi = float(fg_config.get("roughness_max", 1.0))
        out["Roughness"] = round(min(max(raw, lo), hi), 4)
        record["roughness_from_shininess"] = round(raw, 4)
    if "Specular" in wanted:
        raw = sum(sum(r["specular"][:3]) / 3.0 * r["triangles"] for r in rows) / total
        out["Specular"] = round(min(max(raw, 0.0), 1.0), 4)
        record["specular_from_spec"] = round(raw, 4)
    record["derived"] = dict(out)
    record["basis"] = ("FlightGear .ac MATERIAL spec / shi, triangle-weighted "
                       "(scripts/aircraft_look.py derive_fg_scalars); " + UNCALIBRATED)
    return out, record


def plan_slots(materials, config, sources=None):
    """{slot: {"class", "rule", "master", "instance", "texture", "base_color",
    "weight", "scalars", "vectors", "derived"}} -- what each look instance is
    made of. ``sources`` is the converter's material_sources record
    (:func:`read_material_sources`); without it nothing is derived."""
    from_texture = {}
    out = {}
    sources = sources or {}
    for name, material in sorted(materials.items()):
        cls, rule, matched = classify_slot_rule(name, material, config)
        if cls not in CLASS_MASTERS:
            raise LookError(f"slot {name!r}: class {cls!r} is not one of {SLOT_CLASSES}")
        scalars = dict(CLASS_SCALARS[cls])
        scalars.update(config.get("class_scalars", {}).get(cls, {}))
        derived, derived_record = derive_fg_scalars(sources.get(name), cls,
                                                    config.get("fg_material"))
        scalars.update(derived)
        vectors = {k: tuple(v) for k, v in CLASS_VECTORS[cls].items()}
        vectors.update({k: tuple(v) for k, v in config.get("class_vectors", {}).get(cls, {}).items()})
        metal = (matched or {}).get("metal")
        if metal:
            # a bare_metal rule naming its metal: the measured F0 of that metal
            vectors["MetalF0"] = (*METALS[metal], 1.0)
        if material.get("map_kd"):
            texture = texture_asset_name(material["map_kd"])
            base, weight = (1.0, 1.0, 1.0, 1.0), 1.0
        else:
            texture = None
            r, g, b = material["kd"]
            base, weight = (r, g, b, 1.0), 0.0
        from_texture[name] = texture
        out[name] = {"class": cls, "rule": rule,
                     "master": f"{MASTER_ROOT}/{CLASS_MASTERS[cls]}",
                     "instance": instance_name(name), "texture": texture,
                     "base_color": base, "weight": weight,
                     "scalars": scalars, "vectors": vectors, "derived": derived_record}
        if metal:
            out[name]["metal"] = metal
        if cls == "glass":
            # round 5 (L4): the Thin Translucent twin of the opaque canopy,
            # applied by the C++ only on a render without -labels.
            thin_scalars = dict(THIN_SCALARS)
            thin_scalars.update(config.get("class_scalars", {}).get(THIN_CLASS, {}))
            thin_vectors = {k: tuple(v) for k, v in THIN_VECTORS.items()}
            thin_vectors.update({k: tuple(v) for k, v in
                                 config.get("class_vectors", {}).get(THIN_CLASS, {}).items()})
            out[name]["thin"] = {"master": f"{MASTER_ROOT}/{THIN_GLASS_MASTER}",
                                 "instance": thin_instance_name(name),
                                 "scalars": thin_scalars, "vectors": thin_vectors}
    return out


# -- round 5 (L4): exhaust soot and the nozzle vectors ----------------------------

def soot_mask(local_pos, nozzles, length_radii, noise=1.0):
    """Python twin of exhaust_soot.hlsl: the soot mask (0..1) at a local
    position (cm) for ``nozzles`` = [(x, y, z, radius_cm), ...] (radius <= 0
    = none), fading over ``length_radii`` radii aft (-X) of each exit."""
    px, py, pz = (float(v) for v in local_pos)
    soot = 0.0
    for nozzle in list(nozzles)[:len(SOOT_NOZZLE_PARAMETERS)]:
        cx, cy, cz, r = (float(v) for v in nozzle)
        if r <= 0.0:
            continue
        aft = cx - px
        lateral = math.hypot(py - cy, pz - cz)
        length_cm = max(float(length_radii), 0.5) * r
        along = min(max((aft + 0.5 * r) / (length_cm + 0.5 * r), 0.0), 1.0)
        width = r * (2.0 + max(aft, 0.0) / (3.0 * r))
        lobe = math.exp(-(lateral * lateral) / (width * width))
        fade = (1.0 - along) * (1.0 - along)
        gate = 1.0 if aft >= -0.5 * r else 0.0
        soot = max(soot, gate * fade * lobe)
    n = min(max(float(noise), 0.0), 1.0)
    return soot * (0.6 + 0.4 * n)


def nozzle_vectors(nozzles, mesh_origin_cm):
    """{Nozzle0..3: (x, y, z, radius_cm)} in the mesh's LOCAL frame from the
    look manifest's nozzle rows (actor cm about the datum): the body mesh
    hangs under MeshOrigin at mesh_origin_actor_cm with no rotation
    (FlightSimRenderCommandlet.cpp BuildMeshAirframe), and the imported
    asset lands in the actor frame's orientation (assets_pipeline/obj_frame.py),
    so local = actor - origin. Rows past the fourth are left out, and said
    (:func:`nozzle_vectors_overflow`)."""
    out = {name: NO_NOZZLE for name in SOOT_NOZZLE_PARAMETERS}
    for name, row in zip(SOOT_NOZZLE_PARAMETERS, nozzles):
        x, y, z = row["actor_cm"]
        out[name] = (round(x - mesh_origin_cm[0], 2) + 0.0, round(y - mesh_origin_cm[1], 2) + 0.0,
                     round(z - mesh_origin_cm[2], 2) + 0.0, float(row["radius_cm"]))
    return out


def nozzle_vectors_overflow(nozzles):
    """The ids of the nozzle rows the four soot vectors cannot carry."""
    return [row["id"] for row in list(nozzles)[len(SOOT_NOZZLE_PARAMETERS):]]


def labels_requested(params):
    """Twin of FParse::Param(*Params, TEXT("labels")) as FFlightSimAircraftFXOptions
    ::ParseParams reads it: a ``-labels`` (or ``/labels``) word of its own.
    The C++ applies the thin canopy only when this is False."""
    return re.search(r"(?:^|\s)[-/]labels(?=\s|$)", params) is not None


# -- the config ----------------------------------------------------------------

LIGHT_KINDS = {
    # kind: (linear colour, candela, strobe). The candela values are the
    # regulatory minimums, from memory of 14 CFR 25.1391 (forward red /
    # green 40 cd, rear white 20 cd) and 25.1401 (anti-collision 400 cd
    # EFFECTIVE: a flashing kind's lamp is driven at the Blondel-Rey peak,
    # strobe_peak_candela); the landing lamp is the order of a PAR-64 lamp,
    # from memory. What the frame shows is these times LightVisualGain.
    # Aviation red (25.1397(a), from memory: y <= 0.335) is linear sRGB
    # (1, 0, 0), CIE y 0.330; (1, 0.05, 0.02) was y 0.343, orange of it.
    # NOT modelled: the 25.1385/25.1387 horizontal sectors (red / green
    # 110 degrees forward, white 140 aft) -- the nav lamps are omnidirectional.
    "nav_red": ((1.0, 0.0, 0.0), 40.0, False),
    "nav_green": ((0.05, 1.0, 0.25), 40.0, False),
    "nav_white": ((1.0, 0.95, 0.9), 20.0, False),
    "strobe": ((1.0, 1.0, 1.0), 400.0, True),
    # Flashing beacons (j11-package lane): the J-11A package's own
    # BeaconRed / BeaconGreen at its wingtip nav stations (LightPack.xml),
    # 400 cd as the anti-collision minimum above, from memory.
    "beacon_red": ((1.0, 0.0, 0.0), 400.0, True),
    "beacon_green": ((0.05, 1.0, 0.25), 400.0, True),
    "landing": ((1.0, 0.95, 0.85), 200000.0, False),
}
ANCHORS = ("mesh_extreme", "fdm_thruster", "structural_in", "package_model_m")
AXES = {"+x": (0, 1.0), "-x": (0, -1.0), "+y": (1, 1.0), "-y": (1, -1.0),
        "+z": (2, 1.0), "-z": (2, -1.0)}
REQUIRED_KEYS = ("schema", "name", "default_class")
KNOWN_KEYS = set(REQUIRED_KEYS) | {"note", "slot_rules", "class_scalars", "class_vectors",
                                   "lights", "nozzles", "contrail", "vapour", "light_constants",
                                   "condensation", "fg_material"}


def validate(config, path="look config"):
    """Refuse, by name, a look config the importer or the C++ could not use."""
    problems = []
    for key in REQUIRED_KEYS:
        if key not in config:
            problems.append(f"lacks {key!r}")
    unknown = set(config) - KNOWN_KEYS
    if unknown:
        problems.append(f"unknown keys {sorted(unknown)}")
    if config.get("schema") != LOOK_SCHEMA:
        problems.append(f"schema {config.get('schema')!r} is not {LOOK_SCHEMA!r}")
    if config.get("default_class") not in CLASS_MASTERS:
        problems.append(f"default_class {config.get('default_class')!r} not in {SLOT_CLASSES}")
    for rule in config.get("slot_rules", []):
        if rule.get("class") not in CLASS_MASTERS:
            problems.append(f"slot rule {rule!r}: class not in {SLOT_CLASSES}")
        try:
            re.compile(rule.get("match", ""))
        except re.error as exc:
            problems.append(f"slot rule {rule!r}: bad regex ({exc})")
        if not rule.get("source"):
            problems.append(f"slot rule {rule.get('match')!r} has no source")
        if "metal" in rule:
            if rule.get("class") != "bare_metal":
                problems.append(f"slot rule {rule.get('match')!r}: metal is a bare_metal choice")
            if rule["metal"] not in METALS:
                problems.append(f"slot rule {rule.get('match')!r}: metal {rule['metal']!r} not in "
                                f"{sorted(METALS)}")
    for cls, values in list(config.get("class_scalars", {}).items()) + list(
            config.get("class_vectors", {}).items()):
        if cls == THIN_CLASS:
            allowed, master = set(THIN_SCALARS) | set(THIN_VECTORS), THIN_GLASS_MASTER
        elif cls in CLASS_MASTERS:
            allowed, master = set(CLASS_SCALARS[cls]) | set(CLASS_VECTORS[cls]), CLASS_MASTERS[cls]
        else:
            problems.append(f"class override for unknown class {cls!r}")
            continue
        for name in values:
            if name not in allowed:
                problems.append(f"{cls}.{name} is not a parameter of {master}")
            elif name in SOOT_NOZZLE_PARAMETERS:
                problems.append(f"{cls}.{name} is set from the manifest's nozzles, not the config")
    problems += _validate_fg_material(config.get("fg_material"))
    ids = set()
    for light in config.get("lights", []):
        problems += _validate_anchor(light, "light")
        if light.get("kind") not in LIGHT_KINDS:
            problems.append(f"light {light.get('id')!r}: kind not in {sorted(LIGHT_KINDS)}")
        if light.get("id") in ids:
            problems.append(f"duplicate id {light.get('id')!r}")
        ids.add(light.get("id"))
    for nozzle in config.get("nozzles", []):
        problems += _validate_anchor(nozzle, "nozzle")
        if not isinstance(nozzle.get("radius_m"), (int, float)) or nozzle["radius_m"] <= 0:
            problems.append(f"nozzle {nozzle.get('id')!r}: radius_m must be > 0")
        if nozzle.get("id") in ids:
            problems.append(f"duplicate id {nozzle.get('id')!r}")
        ids.add(nozzle.get("id"))
    if problems:
        raise LookError(f"{path}: " + "; ".join(problems))
    return config


def _validate_anchor(row, what):
    out = []
    if not row.get("id"):
        out.append(f"{what} without id")
    anchor = row.get("anchor")
    if anchor not in ANCHORS:
        out.append(f"{what} {row.get('id')!r}: anchor {anchor!r} not in {ANCHORS}")
    if anchor == "mesh_extreme" and row.get("axis") not in AXES:
        out.append(f"{what} {row.get('id')!r}: axis {row.get('axis')!r} not in {sorted(AXES)}")
    if anchor == "fdm_thruster" and not isinstance(row.get("index"), int):
        out.append(f"{what} {row.get('id')!r}: fdm_thruster needs an integer index")
    if anchor == "structural_in" and (len(row.get("structural_in", [])) != 3 or not row.get("source")):
        out.append(f"{what} {row.get('id')!r}: structural_in needs [x, y, z] and a source")
    if anchor == "package_model_m" and (len(row.get("package_model_m", [])) != 3
                                        or not row.get("source")):
        out.append(f"{what} {row.get('id')!r}: package_model_m needs [x, y, z] and a source")
    offset = row.get("offset_m", [0, 0, 0])
    if len(offset) != 3:
        out.append(f"{what} {row.get('id')!r}: offset_m needs three numbers")
    return out


def _validate_fg_material(block):
    if block is None:
        return []
    out = []
    unknown = set(block) - FG_MATERIAL_KEYS
    if unknown:
        out.append(f"fg_material: unknown keys {sorted(unknown)}")
    for parameter in block.get("parameters", []):
        if parameter == "Metallic":
            out.append("fg_material: Metallic is never derived (Phong has no metal term)")
        elif parameter not in FG_DERIVABLE:
            out.append(f"fg_material: {parameter!r} is not one of {FG_DERIVABLE}")
    for cls in block.get("classes", []):
        if cls not in CLASS_MASTERS:
            out.append(f"fg_material: class {cls!r} not in {SLOT_CLASSES}")
    lo, hi = block.get("roughness_min", 0.0), block.get("roughness_max", 1.0)
    if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and 0.0 <= lo <= hi <= 1.0):
        out.append("fg_material: needs 0 <= roughness_min <= roughness_max <= 1")
    if not block.get("source"):
        out.append("fg_material has no source")
    return out


def look_config_path(name):
    return os.path.join(LOOK_DIR, f"{name}.json")


def load_config(name, path=None):
    path = path or look_config_path(name)
    with open(path, encoding="utf-8") as handle:
        config = json.load(handle)
    validate(config, os.path.basename(path))
    if config["name"] != name:
        raise LookError(f"{path}: name {config['name']!r} is not {name!r}")
    return config


# -- frames and anchors --------------------------------------------------------

def structural_to_actor_cm(point_in):
    """JSBSim structural (in, x AFT, y right, z up) -> UE actor (cm, x
    forward): (-x, y, z) about the datum, the map UJSBSimMovementComponent
    uses (NEXT.md gotcha 31)."""
    x, y, z = point_in
    return (-x * CM_PER_IN + 0.0, y * CM_PER_IN + 0.0, z * CM_PER_IN + 0.0)


def read_obj_vertices(path):
    """Every ``v`` of an OBJ the converters wrote, back in the ACTOR frame
    about the model origin (assets_pipeline/obj_frame.py: obj = (x, -y, z))."""
    out = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("v "):
                x, y, z = (float(v) for v in line.split()[1:4])
                out.append((x, -y + 0.0, z))
    return out


def mesh_vertices_actor(generated_dir, manifest):
    """The body part's vertices in the actor frame (cm): the OBJ's
    vertices plus mesh_origin_actor_cm, the point BuildMeshAirframe hangs
    MeshOrigin at. The body is the part named "body", else the first."""
    parts = manifest.get("parts") or []
    part = "body" if "body" in parts else (parts[0] if parts else None)
    if part is None:
        raise LookError("mesh manifest lists no parts")
    origin = manifest.get("mesh_origin_actor_cm")
    if not (isinstance(origin, list) and len(origin) == 3):
        raise LookError("mesh manifest carries no mesh_origin_actor_cm (version >= 3)")
    obj = os.path.join(generated_dir, f"{part}.obj")
    verts = read_obj_vertices(obj)
    if not verts:
        raise LookError(f"{obj} has no vertices")
    return part, [(v[0] + origin[0], v[1] + origin[1], v[2] + origin[2]) for v in verts]


def mesh_extreme(vertices, axis):
    """The vertex furthest along a signed actor axis ("-y" = the left
    wingtip, "-x" = the tail)."""
    index, sign = AXES[axis]
    return max(vertices, key=lambda v: sign * v[index])


def _length_in(element):
    """A JSBSim <location> in inches (unit IN, M, FT; IN by default)."""
    unit = (element.get("unit") or "IN").upper()
    scale = {"IN": 1.0, "M": 39.3700787, "FT": 12.0}.get(unit)
    if scale is None:
        raise LookError(f"<location unit={unit!r}> is not IN, M or FT")
    return tuple(float(element.find(axis).text) * scale for axis in ("x", "y", "z"))


def read_fdm(fdm_xml):
    """{"thrusters": [(x, y, z) in], "engines": [file], "dir": aircraft dir}
    from the flown FDM (comments are not elements: a commented-out engine
    is not read)."""
    root = ET.parse(fdm_xml).getroot()
    thrusters, engines = [], []
    for engine in root.iter("engine"):
        thruster = engine.find("thruster")
        if thruster is None or thruster.find("location") is None:
            continue
        thrusters.append(_length_in(thruster.find("location")))
        engines.append(engine.get("file"))
    return {"thrusters": thrusters, "engines": engines, "dir": os.path.dirname(fdm_xml)}


def engine_thrust(fdm, index):
    """(milthrust, maxthrust) lbf from the engine file, or (None, None)."""
    if index >= len(fdm["engines"]) or not fdm["engines"][index]:
        return None, None
    path = os.path.join(fdm["dir"], "Engines", f"{fdm['engines'][index]}.xml")
    if not os.path.isfile(path):
        return None, None
    root = ET.parse(path).getroot()
    mil, mx = root.find("milthrust"), root.find("maxthrust")
    return (float(mil.text) if mil is not None else None,
            float(mx.text) if mx is not None else None)


#: How far aft of the FDM thruster station a snapped nozzle exit may lie.
#: Without the window the B747's outboard snap took a vertex 6.1 m aft of
#: the station (the wing's trailing edge behind the nacelle, not the
#: nozzle; measured here on the converted model, 2026-11-09).
SNAP_MAX_AFT_M = 4.0


def snap_nozzle(vertices, station_cm, radius_cm, max_aft_cm=SNAP_MAX_AFT_M * CM_PER_M):
    """The aftmost body vertex within ``radius_cm`` of the thruster's
    line (same y, z) and no more than ``max_aft_cm`` aft of its station:
    the nozzle exit as the mesh draws it. None when no vertex lies that
    close (the FDM station is then used, and said)."""
    near = [v for v in vertices
            if abs(v[1] - station_cm[1]) <= radius_cm and abs(v[2] - station_cm[2]) <= radius_cm
            and station_cm[0] - max_aft_cm <= v[0] <= station_cm[0] + max_aft_cm]
    if not near:
        return None
    return min(near, key=lambda v: v[0])


def package_model_to_actor_cm(point_m, mesh_origin_cm):
    """A point the package's model XML states (FlightGear model frame,
    metres: +x aft, +y right, +z up, about the model origin) in the UE actor
    frame (cm): x negated, then mesh_origin_actor_cm, the same map the
    converter applies to every vertex and part offset."""
    x, y, z = (float(v) for v in point_m)
    return (-x * CM_PER_M + mesh_origin_cm[0], y * CM_PER_M + mesh_origin_cm[1],
            z * CM_PER_M + mesh_origin_cm[2])


def resolve_anchor(row, vertices, fdm, mesh_origin_cm=(0.0, 0.0, 0.0)):
    """(actor_cm, basis) for one light or nozzle row."""
    offset = [float(v) * CM_PER_M for v in row.get("offset_m", (0.0, 0.0, 0.0))]
    anchor = row["anchor"]
    if anchor == "package_model_m":
        point = package_model_to_actor_cm(row["package_model_m"], mesh_origin_cm)
        basis = (f"the package's own position {row['package_model_m']} m (FlightGear model "
                 f"frame) mapped to the actor frame about mesh_origin_actor_cm: {row['source']}")
    elif anchor == "mesh_extreme":
        point = mesh_extreme(vertices, row["axis"])
        basis = (f"measured from vertices: the body vertex furthest along {row['axis']} "
                 f"(actor frame)")
    elif anchor == "structural_in":
        point = structural_to_actor_cm(row["structural_in"])
        basis = f"stated structural point: {row['source']}"
    else:
        index = row["index"]
        if index >= len(fdm["thrusters"]):
            raise LookError(f"{row['id']}: the FDM has {len(fdm['thrusters'])} thruster(s)")
        station = structural_to_actor_cm(fdm["thrusters"][index])
        snapped = None
        if row.get("snap_radius_m"):
            snapped = snap_nozzle(vertices, station, float(row["snap_radius_m"]) * CM_PER_M,
                                  float(row.get("snap_max_aft_m", SNAP_MAX_AFT_M)) * CM_PER_M)
        if snapped is not None:
            point = (snapped[0], station[1], station[2])
            basis = (f"FDM thruster {index} line (y, z), x snapped to the aftmost body vertex "
                     f"within {row['snap_radius_m']} m of it ({(station[0] - snapped[0]) / 100.0:.2f} m "
                     f"aft of the FDM station)")
        else:
            point = station
            basis = f"FDM thruster {index} station (no body vertex near its line: not snapped)"
    actor = tuple(round(point[i] + offset[i], 2) + 0.0 for i in range(3))
    if any(offset):
        basis += f", plus the config's offset_m {row['offset_m']}"
    return actor, basis


# -- trails, the afterburner and the lights: the beauty-only constants ---------

#: Contrail formation (Schmidt-Appleman, from memory: for kerosene at the
#: usual overall propulsion efficiency the threshold is about -40 C near
#: 250 hPa in saturated air). No humidity is modelled here, so a trail is
#: drawn whenever the FDM's own air temperature is below the threshold and
#: the aircraft is above the floor; persistence (ice supersaturation) is not
#: modelled -- trails fade over LifetimeS.
CONTRAIL_DEFAULTS = {
    "MaxTemperatureK": 233.15, "MinAltitudeM": 7500.0, "LifetimeS": 25.0,
    "FormationDelayS": 0.15, "StartWidthM": 1.2, "SpreadMPerS": 0.9,
    "Opacity": 0.55, "PreseedS": 8.0,
    # Round 47 (#13's four light lines): the trail forms over this many seconds
    # after FormationDelayS (the material ramp was 0.04 of LifetimeS: 1 s, 250 m at
    # cruise). About one wingspan of a 747 at 250 m/s. UNCALIBRATED.
    "FormationRampS": 0.25,
    # Round 93 (r92's #13: four hard straight rulers from the engines to the frame
    # edge): a trail fades in with distance from the CAMERA (saturate((depth - offset) /
    # length) on the opacity), invisible nearer than CameraFadeOffsetM and full beyond
    # + CameraFadeLengthM, so the stretch passing beside a chase camera no longer
    # runs to the frame edge at full strength. M_AircraftContrail's
    # CameraFadeOffset / CameraFadeLength defaults (cm). UNCALIBRATED.
    "CameraFadeOffsetM": 30.0, "CameraFadeLengthM": 120.0,
}
#: Wingtip vapour: short trails from the wingtip anchors above a load factor.
VAPOUR_DEFAULTS = {"MinNz": 4.0, "LifetimeS": 0.8, "StartWidthM": 0.25,
                   "SpreadMPerS": 1.5, "Opacity": 0.35}
#: Lights: what the frame shows is candela x LightVisualGain; the strobe
#: flashes StrobeFlashS every StrobePeriodS (25.1401: 40-100 flashes a
#: minute, from memory) on the FDM's own time (replay-identical).
#: BulbRadiusCm is the half-size of the glow sprite and the point light's
#: source radius: 18 cm is an airliner's wingtip lens and glare, a fighter's
#: lamp is far smaller (the J-11's look config overrides it). The bulb's
#: luminance is NOT a constant: it is the candela over the sprite's effective
#: area (bulb_luminance_nits), so the lamp the camera sees and the light it
#: throws are one number. BlondelReyS is the Blondel-Rey constant a (0.2 s,
#: from memory) that turns a flash's effective intensity into its peak.
LIGHT_DEFAULTS = {"LightVisualGain": 1.0, "BulbRadiusCm": 18.0, "StrobePeriodS": 1.0,
                  "StrobeFlashS": 0.12, "LandingMaxAglM": 450.0,
                  "LandingConeDeg": 12.0, "NavAttenuationM": 40.0,
                  "LandingAttenuationM": 900.0, "BlondelReyS": 0.2}
#: The afterburner: glow = saturate((thrust / maxthrust - mil / max) / (1 - mil / max)),
#: static sea-level ratings from the engine file (a lapse with altitude and
#: Mach the ratio does not correct for), the plume a cone PlumeLengthRadii
#: nozzle radii long, its light AfterburnerCandela at full glow. The flame's
#: own luminance is derived from the same candela (plume_luminance), so the
#: plume the camera sees and the light it throws agree; Shocks is the number
#: of shock diamonds afterburner_glow.hlsl draws (the master's default).
AFTERBURNER_DEFAULTS = {"PlumeLengthRadii": 7.0, "AfterburnerCandela": 6.0e4,
                        "GlowGain": 1.0, "AttenuationM": 25.0, "Shocks": 5.0}
#: The plume's hue at the nozzle and at the tip (linear sRGB), normalised so
#: the core's Rec.709 luminance is 1: the flame's colour, never its
#: brightness (that is plume_luminance's). The old fixed emissives
#: (30, 22, 18) and (20, 6, 1.5) divided by the core's luminance 23.41.
AFTERBURNER_CORE_HUE = (1.2815, 0.9398, 0.7689)
AFTERBURNER_TIP_HUE = (0.8543, 0.2563, 0.0641)
#: FlightSimAircraftFX.cpp's plume cone: radius 0.85 R at the nozzle to 0.3 R
#: at the tip (R the nozzle radius); pinned to the C++ text by test.
AFTERBURNER_CONE_RADII = (0.85, 0.3)
#: nav_bulb.hlsl's falloff over its quad (c = UV * 2 - 1, half-size
#: BulbRadiusCm): exp(-18 r^2) + 0.15 exp(-3 r^2); pinned to the HLSL by test.
NAV_BULB_CORE_K = 18.0
NAV_BULB_HALO_K = 3.0
NAV_BULB_HALO_WEIGHT = 0.15
#: Rec.709 / sRGB luminance weights (the engine's Luminance()).
REC709_Y = (0.2126, 0.7152, 0.0722)


def _gauss_1d(k):
    """The integral of exp(-k x^2) over x in [-1, 1]."""
    return math.sqrt(math.pi / k) * math.erf(math.sqrt(k))


def nav_bulb_area_factor():
    """The integral of nav_bulb.hlsl's falloff over its quad, in units of
    the half-size squared (both terms are separable Gaussians: exact). One
    quad face-on emits L x this x R^2 candela for a core luminance L; the
    two crossed quads edge-on add nothing, a diagonal view up to sqrt(3)."""
    return _gauss_1d(NAV_BULB_CORE_K) ** 2 + NAV_BULB_HALO_WEIGHT * _gauss_1d(NAV_BULB_HALO_K) ** 2


def bulb_luminance_nits(candela, gain, radius_cm):
    """The bulb's core luminance (cd/m^2) whose face-on intensity is the
    lamp's own candela x gain: one source for the light and its sprite."""
    radius_m = max(float(radius_cm), 0.01) / CM_PER_M
    return float(candela) * float(gain) / (nav_bulb_area_factor() * radius_m * radius_m)


def strobe_peak_candela(effective_cd, flash_s, blondel_rey_s):
    """The instantaneous intensity a flash of ``flash_s`` needs for its
    Blondel-Rey effective intensity I_e = I t / (a + t) to be ``effective_cd``."""
    t = max(float(flash_s), 1e-3)
    return float(effective_cd) * (float(blondel_rey_s) + t) / t


def _luminance(rgb):
    return sum(w * c for w, c in zip(REC709_Y, rgb))


def afterburner_glow_profile(u, shocks):
    """afterburner_glow.hlsl's emission along the plume at UV.x = u (per
    unit core luminance, colour and all): (colour, body x diamonds)."""
    along = min(max(u, 0.0), 1.0)
    body = (1.0 - along) ** 2
    diamonds = 0.7 + 0.3 * abs(math.cos(along * shocks * math.pi)) ** 6.0
    colour = tuple(c + (t - c) * along for c, t in zip(AFTERBURNER_CORE_HUE, AFTERBURNER_TIP_HUE))
    return colour, body * diamonds


def afterburner_effective_area_m2(radius_cm, length_radii, shocks, steps=4000):
    """The plume's luminance-weighted projected area seen side-on (m^2):
    I = L_core x this. The cone is two-sided and additive, so a ring of
    radius r and length dx shows 4 r dx of emitting surface from the side
    (the integral of |cos| around it, front and back faces both drawn)."""
    r0, r1 = AFTERBURNER_CONE_RADII
    radius_m = float(radius_cm) / CM_PER_M
    length_m = float(length_radii) * radius_m
    total = 0.0
    for i in range(steps):
        u = (i + 0.5) / steps
        colour, weight = afterburner_glow_profile(u, shocks)
        r = (r0 + (r1 - r0) * u) * radius_m
        total += _luminance(colour) * weight * 4.0 * r * (length_m / steps)
    return total


def plume_luminance(radius_cm, constants):
    """(core luminance cd/m^2, effective area m^2): the flame at full glow
    whose side-on intensity is AfterburnerCandela, the plume light's own."""
    area = afterburner_effective_area_m2(radius_cm, constants["PlumeLengthRadii"], constants["Shocks"])
    return constants["AfterburnerCandela"] / max(area, 1e-6), area


#: heat_haze.hlsl's envelope: fade = (1 - u) x saturate(8 u) peaks at u = 1/8
#: (0.875); each offset component is a product of a sine and a cosine (<= 1).
HEAT_HAZE_FADE_PEAK = 0.875
#: UE 5.7.4 DistortionCommon.ush: a 2D-offset refraction is scaled by the
#: view's width x OffsetFudgeFactor (0.00023) x the projection's M[0][0]
#: (1 / tan(hFOV / 2)) on x, and by the same times the aspect on y in
#: height units -- i.e. the same pixel count per unit on both axes.
UE_DISTORTION_OFFSET_FUDGE = 0.00023


#: FFlightSimAircraftFXOptions::ParseParams's switches: (key, default). A
#: word other than these is refused by name (aircraft_look.switch).
FX_SWITCHES = (("aircraft-look=", True), ("aircraft-materials=", True), ("aircraft-lights=", True),
               ("contrails=", True), ("afterburner=", True), ("heat-haze=", False),
               # Round 47 (#13): the contrail's formation ramp in seconds (on) or
               # generation 6's 0.04 of the lifetime (off, the A/B).
               ("contrail-formation-ramp=", True),
               # The canopy reflection (aircraft_glass_reflect.py): OFF unless
               # -canopy-reflect=on, so Windows can A/B it (tier: -canopy-reflect-tier=0|1).
               ("canopy-reflect=", False))
SWITCH_ON = ("on", "1", "true")
SWITCH_OFF = ("off", "0", "false")


def parse_fx_switches(params):
    """Twin of FFlightSimAircraftFXOptions::ParseParams (FParse::Value reads
    the word after ``-key=`` up to whitespace): {key: bool}, every element
    off under -aircraft-look=off; LookError("aircraft_look.switch: ...") for
    any other word (it used to read as on: -heat-haze=no drew the haze)."""
    words = {}
    for key, default in FX_SWITCHES:
        match = re.search(re.escape(key) + r'"?([^\s"]*)', params)
        if match is None:
            words[key] = default
            continue
        word = match.group(1)
        if word in SWITCH_ON:
            words[key] = True
        elif word in SWITCH_OFF:
            words[key] = False
        else:
            raise LookError(f"aircraft_look.switch: -{key}{word} is not on/1/true or off/0/false")
    every = words.pop("aircraft-look=")
    return {key[:-1]: every and value for key, value in words.items()}


#: Round 23 (2026-11-11): the bisect probes inside the look masters, for a
#: render with -aircraft-materials=on (round 22: the gen-4 instances drew the
#: A-4 tan and the C172 near-black, each in the ground's colour). Read by
#: FFlightSimAircraftFXOptions::ParseParams from ``-aircraft-probe=`` (a comma
#: list, no spaces) and applied to the paint and bare-metal slots' MIDs by
#: FFlightSimAircraftFX::ApplyMaterials; recorded in render.json
#: aircraft_look.materials.probes. Word -> what it does:
AIRCRAFT_PROBES = {
    "nocoat": "ClearCoat 0 (the coat lobe and its refraction off; paint only)",
    "noao": "PanelAoAmount 0 (the material AO output is exactly 1)",
    "nonormal": "PanelNormalAmount 0 (the Normal output is the vertex normal, the panel_lines lean bypassed)",
    "nowear": "WearAmount, GrimeAmount and SootAmount 0 (no edge metal, no cavity darkening)",
    "flat": ("M_AircraftProbeFlat: a plain Default Lit dielectric (Metallic 0, Specular 0.5, Roughness 0.5, "
             "no Normal, AO, coat or wet layer) with the look instance's own BaseColor, BaseColorMap and "
             "BaseColorMapWeight"),
    "measured-mesh": ("the beauty mesh swap is skipped: the measured body (Interchange's recomputed normals, "
                      "no two-sided back faces) wears the look instances"),
    # Round 24 (LOOK_GENERATION 6; the handles are aircraft_wet_layer.PROBE_SCALARS):
    "nowet": "WetLayerAmount 0: Make takes Break's BaseColor, Roughness and ClearCoat (the wet graft bypassed)",
    "rawbase": ("RawBaseAmount 1: Make.BaseColor straight from _base_colour (no AlbedoMax, cavity, wear "
                "or wet)"),
    "defaultlit": ("paint slots on M_AircraftPaintDefaultLit (the same graph on MSM_DEFAULT_LIT), the look "
                   "instance's overrides copied"),
    "basecolor-debug": ("BaseDebug 1: the lit base colour is 0 and the final base colour x BaseDebugNits "
                        "is emitted (read with -subject-meter=off)"),
    "tangentnormal": ("paint slots on M_AircraftPaintTangentNormal (the same clear-coat graph, its normal in "
                      "tangent space as (0, 0, 1): the imported materials' normal path), overrides copied"),
    # Round 25 (LOOK_GENERATION 7):
    "coat": ("M_AircraftPaintCoat: a plain Clear Coat master with no Custom node (the flat probe's base colour, "
             "the instance's Metallic / Specular / Roughness / ClearCoat / ClearCoatRoughness overrides copied); "
             "also the host's fallback when a class master fails to compile"),
}
AIRCRAFT_PROBE_KEY = "aircraft-probe="
#: The masters a probe acts on (glass and rubber keep their instances).
PROBE_MASTERS = ("M_AircraftPaint", "M_AircraftBareMetal")
PROBE_FLAT_MASTER = "M_AircraftProbeFlat"
PROBE_DEFAULT_LIT_MASTER = "M_AircraftPaintDefaultLit"
PROBE_TANGENT_NORMAL_MASTER = "M_AircraftPaintTangentNormal"
#: Round 25: the Custom-node-free clear-coat paint (scripts/
#: ue_aircraft_master_materials.py create_aircraft_paint_coat) and its
#: parameter defaults: the paint class's numbers, no albedo cap (its base
#: colour is the flat probe's exactly, so it is never darker than flat).
PROBE_COAT_MASTER = "M_AircraftPaintCoat"
COAT_SCALARS = {key: CLASS_SCALARS["paint"][key]
                for key in ("Metallic", "Specular", "Roughness", "ClearCoat", "ClearCoatRoughness")}
#: Round 25: what the host draws on a paint / bare-metal slot with no
#: -aircraft-probe=flat / coat: the class master when it compiled on the
#: render platform, else the coat master, else the flat one
#: (FlightSimAircraftFX.cpp AircraftFxCompileProblem; render.json
#: aircraft_look.materials.master_compile and slots_fallback).
MASTER_FALLBACK_ORDER = ("class master", PROBE_COAT_MASTER, PROBE_FLAT_MASTER)


#: The probes applied when -aircraft-probe= is absent (the host's ParseParams
#: else branch). Round 25: none -- the class masters (gen 7, compile-checked,
#: MASTER_FALLBACK_ORDER); the final sweep's flat default (1e5ba438) is
#: -aircraft-probe=flat.
DEFAULT_AIRCRAFT_PROBES = ()


def parse_aircraft_probes(params):
    """Twin of the host's -aircraft-probe= parse: the probe words in the order
    given (duplicates once), () when absent, ``none`` or empty;
    LookError("aircraft_look.switch: ...") for an unknown word."""
    match = re.search(r"(?:^|\s)-?" + re.escape(AIRCRAFT_PROBE_KEY) + r'"?([^\s"]*)', params)
    if match is None:
        return DEFAULT_AIRCRAFT_PROBES
    out = []
    for word in match.group(1).split(","):
        word = word.strip()
        if word in ("", "none"):
            continue
        if word not in AIRCRAFT_PROBES:
            raise LookError(f"aircraft_look.switch: -{AIRCRAFT_PROBE_KEY}{match.group(1)}: {word!r} is not one "
                            f"of {', '.join(AIRCRAFT_PROBES)}")
        if word not in out:
            out.append(word)
    return tuple(out)


WET_POROSITY_KEY = "wet-porosity="


def parse_wet_porosity(params):
    """Twin of the host's -wet-porosity= parse (FFlightSimAircraftFXOptions::
    ParseParams): {"word", "paint", "bare_metal"} -- ``low`` (absent, the
    default since round 85: aircraft_wet_layer.WET_POROSITY_LOW on the paint
    and bare-metal look MIDs) or ``default`` (the masters' own WetPorosity,
    aircraft_wet_layer.WET_DEFAULTS); LookError("aircraft_look.switch: ...")
    for any other word.
    Shading only: the slots, silhouettes and labels are unchanged."""
    from aircraft_wet_layer import WET_DEFAULTS, WET_POROSITY_LOW, WET_POROSITY_WORDS

    match = re.search(r"(?:^|\s)-?" + re.escape(WET_POROSITY_KEY) + r'"?([^\s"]*)', params)
    word = "low" if match is None else match.group(1)
    if word not in WET_POROSITY_WORDS:
        raise LookError(f"aircraft_look.switch: -{WET_POROSITY_KEY}{word} is not one of "
                        f"{', '.join(WET_POROSITY_WORDS)}")
    source = WET_POROSITY_LOW if word == "low" else WET_DEFAULTS
    return {"word": word, "paint": float(source["PorosityPaint"]),
            "bare_metal": float(source["PorosityBareMetal"])}


def heat_haze_max_material_offset(strength):
    """The largest |component| heat_haze.hlsl returns (refraction units)."""
    return float(strength) * 0.01 * HEAT_HAZE_FADE_PEAK


def heat_haze_max_displacement_px(material_offset, width_px, height_px, hfov_deg):
    """The engine's bound on how far a pixel moves (px, along the diagonal):
    UV_x = v_x W k / tan(hFOV/2) of the width, UV_y = v_y W k / tan(hFOV/2)
    of the WIDTH too (the aspect cancels the height), so per axis
    v W^2 k / tan in x and v W H k / tan in y. Twin of
    FFlightSimAircraftFX::HeatHazeMaxDisplacementPx."""
    scale = float(width_px) * UE_DISTORTION_OFFSET_FUDGE / math.tan(math.radians(float(hfov_deg)) / 2.0)
    return float(material_offset) * scale * math.hypot(float(width_px), float(height_px))
#: Heat haze behind the nozzles: OFF unless -heat-haze=on (it refracts, so it
#: moves pixels: recorded in render.json aircraft_look.heat_haze, never on in a
#: measured shot).
HEAT_HAZE_DEFAULTS = {"LengthRadii": 14.0, "Strength": 0.6}


def _condensation_defaults():
    """condensation-solver: core/scene/condensation.py CONDENSATION_DEFAULTS,
    read as a literal (this module is stdlib-only and also runs inside
    UnrealEditor's Python, where core's own imports do not)."""
    import ast
    path = os.path.join(REPO, "core", "scene", "condensation.py")
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    for node in tree.body:
        target = getattr(node, "target", None) or (getattr(node, "targets", None) or [None])[0]
        if getattr(target, "id", "") == "CONDENSATION_DEFAULTS":
            return ast.literal_eval(node.value)
    raise LookError(f"{path} defines no CONDENSATION_DEFAULTS")


CONDENSATION_DEFAULTS = _condensation_defaults()


def _constants(defaults, overrides, probe):
    out = {}
    for key, value in defaults.items():
        out[key] = {"value": float(overrides.get(key, value)), "calibration": UNCALIBRATED,
                    "probe": probe}
    unknown = set(overrides) - set(defaults)
    if unknown:
        raise LookError(f"unknown constants {sorted(unknown)}")
    return out


#: An omnidirectional lamp's beam cosines (nav_bulb.hlsl: outer <= -1 = no beam).
OMNI_BEAM_COS = (-2.0, -2.0)


def lamp_row(row, actor, basis, light_constants):
    """One manifest lamp: where, what colour, its intensity (the peak for a
    flashing kind, with the effective value it meets) and the bulb's
    luminance derived from that intensity (one source for both)."""
    colour, candela, strobe = LIGHT_KINDS[row["kind"]]
    out = {"id": row["id"], "kind": row["kind"], "actor_cm": list(actor), "basis": basis,
           "colour": list(colour), "candela": candela, "strobe": strobe}
    if strobe:
        peak = strobe_peak_candela(candela, light_constants["StrobeFlashS"], light_constants["BlondelReyS"])
        out["effective_candela"] = candela
        out["candela"] = round(peak, 3)
        out["candela_basis"] = (f"peak = effective x (a + t) / t (Blondel-Rey, a "
                                f"{light_constants['BlondelReyS']} s, flash t "
                                f"{light_constants['StrobeFlashS']} s): {candela} cd effective")
    radius = light_constants["BulbRadiusCm"]
    out["bulb_luminance_nits"] = round(bulb_luminance_nits(out["candela"], light_constants["LightVisualGain"],
                                                           radius), 3)
    out["bulb_basis"] = (f"candela x LightVisualGain / ({nav_bulb_area_factor():.5f} x BulbRadiusCm^2): "
                         f"nav_bulb.hlsl's falloff integrated over one quad face-on")
    if row["kind"] == "landing":
        out["direction_actor"] = list(row.get("direction_actor", (1.0, 0.0, -0.08)))
        # the spot light's own cone (FlightSimAircraftFX.cpp: inner half the outer)
        cone = math.radians(light_constants["LandingConeDeg"])
        out["beam_cos"] = [round(math.cos(0.5 * cone), 6), round(math.cos(cone), 6)]
    else:
        out["beam_cos"] = list(OMNI_BEAM_COS)
    return out


def nozzle_row(row, actor, basis, fdm, afterburner_constants):
    mil, mx = engine_thrust(fdm, row["index"]) if isinstance(row.get("index"), int) else (None, None)
    radius_cm = round(float(row["radius_m"]) * CM_PER_M, 2)
    out = {"id": row["id"], "actor_cm": list(actor), "basis": basis,
           "axis_actor": [-1.0, 0.0, 0.0], "radius_cm": radius_cm,
           "afterburner": bool(row.get("afterburner", False)) and mx is not None,
           "thrust_property": f"propulsion/engine[{row.get('index', 0)}]/thrust-lbs",
           "mil_thrust_lbs": mil, "max_thrust_lbs": mx}
    if out["afterburner"]:
        nits, area = plume_luminance(radius_cm, afterburner_constants)
        out["plume_luminance_nits"] = round(nits, 3)
        out["plume_effective_area_m2"] = round(area, 6)
        out["plume_core_colour"] = [round(c * nits, 3) for c in AFTERBURNER_CORE_HUE]
        out["plume_tip_colour"] = [round(c * nits, 3) for c in AFTERBURNER_TIP_HUE]
        out["plume_basis"] = ("AfterburnerCandela / the plume's luminance-weighted side-on area "
                              "(afterburner_glow.hlsl over the cone, both faces): the flame and its "
                              "light are one number at full glow")
    return out


def _values(defaults, overrides):
    return {key: float(overrides.get(key, value)) for key, value in defaults.items()}


def build_manifest(name, config, generated_dir, fdm_xml, materials=None, config_path=None):
    """The look manifest for one converted aircraft (dict, JSON-ready)."""
    manifest_path = os.path.join(generated_dir, "mesh_manifest.json")
    with open(manifest_path, encoding="utf-8") as handle:
        mesh_manifest = json.load(handle)
    part, vertices = mesh_vertices_actor(generated_dir, mesh_manifest)
    origin = mesh_manifest["mesh_origin_actor_cm"]
    fdm = read_fdm(fdm_xml)
    if materials is None:
        materials = read_mtl_dir(generated_dir)
    slots = plan_slots(materials, config, read_material_sources(generated_dir))
    light_constants = _values(LIGHT_DEFAULTS, config.get("light_constants", {}))
    afterburner_constants = _values(AFTERBURNER_DEFAULTS, {})
    lights = []
    for row in config.get("lights", []):
        actor, basis = resolve_anchor(row, vertices, fdm, origin)
        lights.append(lamp_row(row, actor, basis, light_constants))
    nozzles = []
    for row in config.get("nozzles", []):
        actor, basis = resolve_anchor(row, vertices, fdm, origin)
        nozzles.append(nozzle_row(row, actor, basis, fdm, afterburner_constants))
    config_path = config_path or look_config_path(name)
    soot = nozzle_vectors(nozzles, origin)
    thin_slots = sorted(slot for slot, row in slots.items() if row.get("thin"))
    return {
        "magic": LOOK_MANIFEST_MAGIC, "version": LOOK_MANIFEST_VERSION, "name": name,
        # round 5 (L4): the soot nozzles every paint / bare-metal instance
        # carries (local cm), and the thin-canopy rule the C++ follows.
        "soot_nozzles_local_cm": {key: list(value) for key, value in soot.items()},
        "soot_nozzles_left_out": nozzle_vectors_overflow(nozzles),
        "thin_glass": {
            "master": f"{MASTER_ROOT}/{THIN_GLASS_MASTER}", "suffix": THIN_INSTANCE_SUFFIX,
            "slots": thin_slots,
            "instances": [thin_instance_name(slot) for slot in thin_slots],
            "rule": ("applied by FlightSimAircraftFX.cpp only on a render without -labels; "
                     "with -labels the opaque MI_<slot> stays, so the ID and depth labels "
                     "(captures that draw no translucency) keep the canopy"),
        },
        "look_config": os.path.relpath(config_path, REPO).replace(os.sep, "/"),
        # sha256 of the named file (as every other *_sha256 here), and of the
        # config as used (canonical JSON: the same unless a caller edited it).
        "look_config_sha256": sha256_file(config_path) if os.path.isfile(config_path) else None,
        "look_config_canonical_json_sha256": sha256_text(json.dumps(config, sort_keys=True)),
        "mesh_manifest_sha256": sha256_file(manifest_path),
        "body_part": part, "frame": "UE actor frame, cm, +X forward +Y right +Z up, "
                                    "about the JSBSim structural datum",
        "instance_root": f"{mesh_manifest.get('asset_path_root')}/{LOOK_INSTANCE_FOLDER}",
        "slots": {slot: dict({"class": row["class"], "instance": row["instance"], "rule": row["rule"]},
                             **({"derived": row["derived"]} if row.get("derived") else {}),
                             **({"metal": row["metal"]} if row.get("metal") else {}),
                             **({"thin_instance": row["thin"]["instance"]} if row.get("thin") else {}))
                  for slot, row in slots.items()},
        "lights": lights, "nozzles": nozzles,
        "constants": {
            "lights": _constants(LIGHT_DEFAULTS, config.get("light_constants", {}),
                                 "a dusk and a noon beauty probe of the type at chase range"),
            "contrail": _constants(CONTRAIL_DEFAULTS, config.get("contrail", {}),
                                   "a cruise beauty probe above 9 km, chase and side views"),
            "vapour": _constants(VAPOUR_DEFAULTS, config.get("vapour", {}),
                                 "a 5 g pull-up beauty probe"),
            "condensation": _constants(CONDENSATION_DEFAULTS, config.get("condensation", {}),
                                       "a humid low pass at M 0.95 and a 5 g pull-up in the forest "
                                       "rain scene (docs/visual/PROBE_LOG.md condensation-solver)"),
            "afterburner": _constants(AFTERBURNER_DEFAULTS, {},
                                      "a full-reheat take-off beauty probe, rear quarter"),
            "heat_haze": _constants(HEAT_HAZE_DEFAULTS, {},
                                    "a -heat-haze=on beauty probe at idle, rear view"),
            # wet-airframe-canopy (scripts/aircraft_wet_layer.py WET_DEFAULTS).
            "wet": _wet_constants(),
        },
    }


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fdm_xml_for(name):
    """The flown FDM XML of an aircraft config (convert.py's path rule)."""
    with open(os.path.join(CONFIG_DIR, f"{name}.json"), encoding="utf-8") as handle:
        fdm = json.load(handle)["fdm"]
    return os.path.join(FDM_AIRCRAFT, fdm, f"{fdm}.xml")


def build_manifest_for(name, generated_dir=None, config_path=None):
    """(manifest, generated_dir) for one converted aircraft from its look
    config and flown FDM -- what :func:`write_manifest` writes."""
    generated_dir = generated_dir or os.path.join(GENERATED, name)
    config = load_config(name, config_path)
    return build_manifest(name, config, generated_dir, fdm_xml_for(name), config_path=config_path), generated_dir


def write_manifest_dict(manifest, generated_dir):
    """Write a built manifest to <generated_dir>/look_manifest.json; its path."""
    out = os.path.join(generated_dir, LOOK_MANIFEST_NAME)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="ascii") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, out)
    return out


def write_manifest(name, generated_dir=None, config_path=None):
    """Build and write <generated>/<NAME>/look_manifest.json; returns its path."""
    manifest, generated_dir = build_manifest_for(name, generated_dir, config_path)
    return write_manifest_dict(manifest, generated_dir)


def main(argv):
    if argv[:1] == ["--check-all"]:
        names = sorted(n[:-5] for n in os.listdir(LOOK_DIR) if n.endswith(".json"))
        for name in names:
            load_config(name)
            print(f"LOOK-OK {name}")
        return 0
    if not argv:
        print(__doc__)
        return 2
    status = 0
    for name in argv:
        try:
            print(f"LOOK-MANIFEST {write_manifest(name)}")
        except (OSError, LookError, ValueError) as exc:
            print(f"LOOK-FAILED {name}: {exc}")
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
