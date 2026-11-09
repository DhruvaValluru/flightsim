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
import os
import re
import sys
import xml.etree.ElementTree as ET

# wet-airframe-canopy module: its shader inputs and constants (stdlib only).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aircraft_wet_layer import WET_SHADER_INPUTS, constants_group as _wet_constants  # noqa: E402

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

#: Every scalar each class master exposes, with its default. Each value is a
#: look choice, not a measurement -- UNCALIBRATED (probe: the V7 side-by-side
#: of each type against a reference photo at matched sun, reader's judgment).
#: Why paint is NOT metallic 0.6-0.9: a painted panel is a dielectric under a
#: clear coat (F0 ~0.04); a high metallic on paint reads as chrome under
#: Lumen reflections. The 0.6-0.9 band belongs to the bare_metal class (the
#: P-51D's polished skin, exhaust and leading-edge panels), where it is
#: physically right. Paint keeps a small "flake" metallic.
CLASS_SCALARS = {
    "paint": {
        "Metallic": 0.15, "Roughness": 0.42, "RoughnessBreakup": 0.12,
        "ClearCoat": 0.6, "ClearCoatRoughness": 0.12,
        "PanelDepth": 0.35, "PanelWidthCm": 0.35, "PanelDarkening": 0.25,
        "WearAmount": 0.25, "GrimeAmount": 0.2, "Specular": 0.5,
        "NoiseCm": 35.0, "EdgeStart": 0.02, "EdgeEnd": 0.2,
    },
    "bare_metal": {
        "Metallic": 0.9, "Roughness": 0.28, "RoughnessBreakup": 0.18,
        "PanelDepth": 0.45, "PanelWidthCm": 0.3, "PanelDarkening": 0.2,
        "WearAmount": 0.1, "GrimeAmount": 0.25, "Specular": 0.5,
        "NoiseCm": 35.0, "EdgeStart": 0.02, "EdgeEnd": 0.2,
    },
    "glass": {
        "Metallic": 0.0, "Roughness": 0.04, "Specular": 1.0, "FresnelExponent": 5.0,
        "ReflectionBoost": 0.6,
    },
    "rubber": {
        "Metallic": 0.0, "Roughness": 0.86, "Specular": 0.3, "RoughnessBreakup": 0.08,
    },
}
#: Every vector each class master exposes (linear RGBA), with its default.
CLASS_VECTORS = {
    "paint": {"PanelPitchCm": (120.0, 90.0, 45.0, 0.0), "WearColour": (0.56, 0.57, 0.6, 1.0)},
    "bare_metal": {"PanelPitchCm": (90.0, 60.0, 35.0, 0.0), "WearColour": (0.75, 0.75, 0.77, 1.0)},
    "glass": {"GlassTint": (0.018, 0.022, 0.026, 1.0)},
    "rubber": {},
}
#: The texture/colour parameters every class master shares (the names the
#: imported Interchange instances use, so the MTL wiring of
#: ue_aircraft_materials.plan carries straight over).
BASE_PARAMETERS = ("BaseColorMap", "BaseColor", "BaseColorMapWeight")
#: The FX masters' parameters, by the names FlightSimAircraftFX.cpp sets
#: (pinned to its text by tests/test_aircraft_look.py).
FX_PARAMETERS = {
    "M_NavLightEmissive": ("LightColour", "Intensity", "Strobe"),
    "M_AircraftContrail": ("Opacity", "Formation"),
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
    "nav_bulb": ("UV", "LightColour", "Intensity", "Strobe"),
    "contrail_opacity": ("UV", "LocalPos", "Opacity", "Formation"),
    "afterburner_glow": ("UV", "Intensity", "CoreColour", "TipColour", "Shocks"),
    "heat_haze": ("UV", "LocalPos", "TimeS", "Strength"),
    # wet-airframe-canopy: "aircraft_wet" and "canopy_scratch".
    **WET_SHADER_INPUTS,
}

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
    for rule in config.get("slot_rules", []):
        if re.fullmatch(rule["match"], name):
            return rule["class"], f"slot_rules {rule['match']!r}"
    if material.get("d", 1.0) < GLASS_MAX_DISSOLVE:
        return "glass", f"MTL d {material['d']:.3f} < {GLASS_MAX_DISSOLVE}"
    if not material.get("map_kd") and max(material.get("kd", (1, 1, 1))) <= RUBBER_MAX_KD:
        return "rubber", f"untextured, Kd max <= {RUBBER_MAX_KD}"
    default = config.get("default_class", "paint")
    return default, "default_class"


def instance_name(slot):
    return LOOK_INSTANCE_PREFIX + slot


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
        cls, rule = classify_slot(name, material, config)
        if cls not in CLASS_MASTERS:
            raise LookError(f"slot {name!r}: class {cls!r} is not one of {SLOT_CLASSES}")
        scalars = dict(CLASS_SCALARS[cls])
        scalars.update(config.get("class_scalars", {}).get(cls, {}))
        derived, derived_record = derive_fg_scalars(sources.get(name), cls,
                                                    config.get("fg_material"))
        scalars.update(derived)
        vectors = {k: tuple(v) for k, v in CLASS_VECTORS[cls].items()}
        vectors.update({k: tuple(v) for k, v in config.get("class_vectors", {}).get(cls, {}).items()})
        if material.get("map_kd"):
            texture = "TEX_" + os.path.splitext(material["map_kd"])[0]
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
    return out


# -- the config ----------------------------------------------------------------

LIGHT_KINDS = {
    # kind: (linear colour, candela, strobe). The candela values are the
    # regulatory minimums, from memory of 14 CFR 25.1391 (forward red /
    # green 40 cd, rear white 20 cd) and 25.1401 (anti-collision 400 cd
    # effective); the landing lamp is the order of a PAR-64 lamp, from
    # memory. What the frame shows is these times LIGHT_VISUAL_GAIN.
    "nav_red": ((1.0, 0.05, 0.02), 40.0, False),
    "nav_green": ((0.05, 1.0, 0.25), 40.0, False),
    "nav_white": ((1.0, 0.95, 0.9), 20.0, False),
    "strobe": ((1.0, 1.0, 1.0), 400.0, True),
    # Flashing beacons (j11-package lane): the J-11A package's own
    # BeaconRed / BeaconGreen at its wingtip nav stations (LightPack.xml),
    # 400 cd as the anti-collision minimum above, from memory.
    "beacon_red": ((1.0, 0.05, 0.02), 400.0, True),
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
    for cls, values in list(config.get("class_scalars", {}).items()) + list(
            config.get("class_vectors", {}).items()):
        if cls not in CLASS_MASTERS:
            problems.append(f"class override for unknown class {cls!r}")
            continue
        allowed = set(CLASS_SCALARS[cls]) | set(CLASS_VECTORS[cls])
        for name in values:
            if name not in allowed:
                problems.append(f"{cls}.{name} is not a parameter of {CLASS_MASTERS[cls]}")
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
}
#: Wingtip vapour: short trails from the wingtip anchors above a load factor.
VAPOUR_DEFAULTS = {"MinNz": 4.0, "LifetimeS": 0.8, "StartWidthM": 0.25,
                   "SpreadMPerS": 1.5, "Opacity": 0.35}
#: Lights: what the frame shows is candela x LIGHT_VISUAL_GAIN; the strobe
#: flashes StrobeFlashS every StrobePeriodS (25.1401: 40-100 flashes a
#: minute, from memory) on the FDM's own time (replay-identical).
LIGHT_DEFAULTS = {"LightVisualGain": 1.0, "BulbRadiusCm": 18.0, "StrobePeriodS": 1.0,
                  "StrobeFlashS": 0.12, "LandingMaxAglM": 450.0,
                  "LandingConeDeg": 12.0, "NavAttenuationM": 40.0,
                  "LandingAttenuationM": 900.0, "BulbEmissivePerCd": 2.0,
                  "BulbEmissiveMax": 3000.0}
#: The afterburner: glow = saturate((thrust / maxthrust - mil / max) / (1 - mil / max)),
#: static sea-level ratings from the engine file (a lapse with altitude and
#: Mach the ratio does not correct for), the plume a cone PlumeLengthRadii
#: nozzle radii long, its light AfterburnerCandela at full glow.
AFTERBURNER_DEFAULTS = {"PlumeLengthRadii": 7.0, "AfterburnerCandela": 6.0e4,
                        "GlowGain": 1.0, "AttenuationM": 25.0}
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


def build_manifest(name, config, generated_dir, fdm_xml, materials=None):
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
    lights = []
    for row in config.get("lights", []):
        actor, basis = resolve_anchor(row, vertices, fdm, origin)
        colour, candela, strobe = LIGHT_KINDS[row["kind"]]
        out = {"id": row["id"], "kind": row["kind"], "actor_cm": list(actor), "basis": basis,
               "colour": list(colour), "candela": candela, "strobe": strobe}
        if row["kind"] == "landing":
            out["direction_actor"] = list(row.get("direction_actor", (1.0, 0.0, -0.08)))
        lights.append(out)
    nozzles = []
    for row in config.get("nozzles", []):
        actor, basis = resolve_anchor(row, vertices, fdm, origin)
        mil, mx = engine_thrust(fdm, row["index"]) if isinstance(row.get("index"), int) else (None, None)
        nozzles.append({"id": row["id"], "actor_cm": list(actor), "basis": basis,
                        "axis_actor": [-1.0, 0.0, 0.0],
                        "radius_cm": round(float(row["radius_m"]) * CM_PER_M, 2),
                        "afterburner": bool(row.get("afterburner", False)) and mx is not None,
                        "thrust_property": f"propulsion/engine[{row.get('index', 0)}]/thrust-lbs",
                        "mil_thrust_lbs": mil, "max_thrust_lbs": mx})
    return {
        "magic": LOOK_MANIFEST_MAGIC, "version": LOOK_MANIFEST_VERSION, "name": name,
        "look_config": f"assets/aircraft_config/look/{name}.json",
        "look_config_sha256": sha256_text(json.dumps(config, sort_keys=True)),
        "mesh_manifest_sha256": sha256_file(manifest_path),
        "body_part": part, "frame": "UE actor frame, cm, +X forward +Y right +Z up, "
                                    "about the JSBSim structural datum",
        "instance_root": f"{mesh_manifest.get('asset_path_root')}/{LOOK_INSTANCE_FOLDER}",
        "slots": {slot: dict({"class": row["class"], "instance": row["instance"], "rule": row["rule"]},
                             **({"derived": row["derived"]} if row.get("derived") else {}))
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


def write_manifest(name, generated_dir=None, config_path=None):
    """Build and write <generated>/<NAME>/look_manifest.json; returns its path."""
    generated_dir = generated_dir or os.path.join(GENERATED, name)
    config = load_config(name, config_path)
    manifest = build_manifest(name, config, generated_dir, fdm_xml_for(name))
    out = os.path.join(generated_dir, LOOK_MANIFEST_NAME)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="ascii") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, out)
    return out


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
