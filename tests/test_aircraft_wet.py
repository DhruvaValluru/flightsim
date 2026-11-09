"""The wet airframe and the canopy micro-scratches (visual overhaul, module
wet-airframe-canopy), without an engine: the numpy twins of the HLSL
closing lines, the wetness integration, the regime switch, and the
contracts between scripts/aircraft_wet_layer.py, the HLSL bodies, the masters
builder, the look manifest and FlightSimAircraftWet.cpp.

Nothing here measures a rendered frame: every wet number is UNCALIBRATED
until a probe render on the render machine sets it.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import aircraft_look as look  # noqa: E402
import aircraft_wet_layer as wet  # noqa: E402

BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
WET_CPP = BRIDGE / "Private" / "FlightSimAircraftWet.cpp"
WET_H = BRIDGE / "Public" / "FlightSimAircraftWet.h"
FX_CPP = BRIDGE / "Private" / "FlightSimAircraftFX.cpp"
FX_H = BRIDGE / "Public" / "FlightSimAircraftFX.h"
COMMANDLET = BRIDGE / "Private" / "FlightSimRenderCommandlet.cpp"
MASTERS = REPO / "scripts" / "ue_aircraft_master_materials.py"
LAYER = REPO / "scripts" / "aircraft_wet_layer.py"
WET_HLSL = REPO / look.SHADER_DIR / "aircraft_wet.hlsl"
SCRATCH_HLSL = REPO / look.SHADER_DIR / "canopy_scratch.hlsl"
J11_FDM = REPO / "assets" / "fdm_root" / "aircraft" / "J11" / "J11.xml"


# -- the film -----------------------------------------------------------------

ALBEDO = np.linspace(0.0, 1.0, 41)
ROUGH = np.linspace(0.02, 1.0, 41)


def test_dry_leaves_albedo_and_roughness_unchanged():
    for porosity in (0.0, 0.3, 1.0):
        a, r, coat = wet.wet_surface(ALBEDO, ROUGH, 0.0, porosity)
        assert np.array_equal(a, ALBEDO) and np.array_equal(r, ROUGH)
        assert np.all(coat == 0.0)


def test_wet_darkening_is_monotonic_and_never_brightens():
    previous = ALBEDO.copy()
    for w in np.linspace(0.0, 1.0, 21):
        a, _, _ = wet.wet_surface(ALBEDO, ROUGH, w, 0.6)
        assert np.all(a <= ALBEDO + 1e-15)
        assert np.all(a <= previous + 1e-15)
        previous = a
    # an over-bright (HDR) albedo is darkened too, never brightened
    a, _, _ = wet.wet_surface(np.array([1.4]), np.array([0.5]), 1.0, 1.0)
    assert a[0] <= 1.4
    # porosity 0 (glass): no darkening at all
    a, _, _ = wet.wet_surface(ALBEDO, ROUGH, 1.0, 0.0)
    assert np.array_equal(a, ALBEDO)


def test_the_film_never_makes_a_surface_rougher_and_the_coat_follows_it():
    for w in (0.25, 0.5, 1.0):
        _, r, coat = wet.wet_surface(ALBEDO, ROUGH, w, 0.3)
        assert np.all(r <= ROUGH + 1e-15)
        assert np.all(coat == pytest.approx(w))
    _, r, _ = wet.wet_surface(ALBEDO, ROUGH, 1.0, 0.3)
    assert np.all(r <= wet.WET_DEFAULTS["WetRoughness"] + 1e-12)


def test_beads_on_glass_scatter_and_rivulets_on_paint_smooth():
    _, r_glass, _ = wet.wet_surface(np.array([0.02]), np.array([0.04]), 1.0, 0.0,
                                    bead=1.0, bead_amount=1.0)
    assert r_glass[0] == pytest.approx(wet.HLSL_BEAD_ROUGHNESS)
    _, r_paint, _ = wet.wet_surface(np.array([0.5]), np.array([0.42]), 1.0, 0.3, rivulet=1.0)
    assert r_paint[0] == pytest.approx(0.5 * wet.WET_DEFAULTS["WetRoughness"])


# -- regime and the wetness integration ---------------------------------------

def test_the_regime_switches_at_beading_max_kts():
    limit = wet.WET_DEFAULTS["BeadingMaxKts"]
    assert wet.regime(limit) == "airflow"
    assert wet.regime(limit + 1e-6) == "airflow"
    assert wet.regime(limit - 1e-6) == "gravity"
    assert wet.regime(0.0) == "gravity" and wet.regime(450.0) == "airflow"
    hlsl = WET_HLSL.read_text(encoding="utf-8")
    assert "bool airflow = AirspeedKts >= beadMaxKts;" in hlsl
    assert "return AirspeedKts >= BeadingMaxKts;" in WET_CPP.read_text(encoding="utf-8")


def test_target_wetness_saturates():
    sat = wet.WET_DEFAULTS["WetSaturationMmh"]
    assert wet.target_wetness(0.0) == 0.0
    assert wet.target_wetness(0.5 * sat) == pytest.approx(0.5)
    assert wet.target_wetness(10 * sat) == 1.0


def _integrate(dt, total, start=1.0, target=0.0):
    w, t = start, 0.0
    while t < total - 1e-12:
        step = min(dt, total - t)
        w = wet.dry_off(w, target, step)
        t += step
    return w


def test_the_dry_off_is_step_size_independent():
    total = 137.0
    one = wet.dry_off(1.0, 0.0, total)
    for dt in (0.01, 0.2, 1.0 / 3.0, 7.0, 50.0):
        assert _integrate(dt, total) == pytest.approx(one, rel=1e-12)
    assert one == pytest.approx(np.exp(-total / wet.WET_DEFAULTS["WetDryTauS"]))
    # partial target, too
    assert _integrate(0.05, 40.0, 0.9, 0.3) == pytest.approx(wet.dry_off(0.9, 0.3, 40.0), rel=1e-12)
    # wetting is immediate; a zero step changes nothing
    assert wet.dry_off(0.1, 0.8, 0.0) == 0.8
    assert wet.dry_off(0.7, 0.2, 0.0) == 0.7


def test_the_cpp_integration_is_the_twins_closed_form():
    text = WET_CPP.read_text(encoding="utf-8")
    assert "if (Target >= InWetness || TauS <= 0.0)" in text
    assert "return Target + (InWetness - Target) * FMath::Exp(-FMath::Max(DtS, 0.0) / TauS);" in text
    assert "FMath::Clamp(RainRateMmh / SaturationMmh, 0.0, 1.0)" in text
    # the FDM's time, never the wall clock
    assert "FPlatformTime" not in text and "GetTimeSeconds" not in text


def test_the_cpp_fallbacks_equal_wet_defaults():
    text = WET_CPP.read_text(encoding="utf-8")
    pins = {"SaturationMmh": "WetSaturationMmh", "DryTauS": "WetDryTauS",
            "BeadingMaxKts": "BeadingMaxKts", "ScratchDensity": "ScratchDensity",
            "ScratchAnisotropy": "ScratchAnisotropy"}
    for cpp, key in pins.items():
        m = re.search(rf"constexpr double AircraftWetDefault{cpp} = ([0-9.eE+-]+);", text)
        assert m and float(m.group(1)) == wet.WET_DEFAULTS[key], cpp
        assert f'TEXT("{key}")' in text, key


# -- the canopy scratches -------------------------------------------------------

def test_scratch_tangents_run_on_circles_about_the_centre_in_the_surface():
    rng = np.random.default_rng(7)
    centre = np.array([120.0, -4.0, 80.0])
    for _ in range(200):
        normal = rng.normal(size=3)
        normal /= np.linalg.norm(normal)
        p = centre + rng.normal(size=3) * 40.0
        t = wet.scratch_tangent(p, normal, centre)
        assert np.linalg.norm(t) == pytest.approx(1.0)
        assert abs(np.dot(t, normal)) < 1e-9
        radial = p - centre
        if np.linalg.norm(np.cross(normal, radial)) > 1e-3:
            assert abs(np.dot(t, radial)) < 1e-9 * np.linalg.norm(radial)
    # at the centre: still a unit tangent in the surface
    t = wet.scratch_tangent(centre, (0.0, 0.0, 1.0), centre)
    assert np.linalg.norm(t) == pytest.approx(1.0) and abs(t[2]) < 1e-12


def test_the_scratch_anisotropy_is_negative_and_bounded():
    text = SCRATCH_HLSL.read_text(encoding="utf-8")
    assert "return float4(t, -saturate(ScratchAnisotropy) * clump);" in text
    assert "float clump = saturate(" in text
    assert f"const float RingCm = {wet.HLSL_SCRATCH_RING_CM};" in text


# -- contracts between the files -------------------------------------------------

def _documented(text):
    return tuple(re.findall(r"^//\s{2,}(\w+)\s+float", text, re.M))


def test_the_hlsl_input_names_match_shader_inputs():
    for name, path in (("aircraft_wet", WET_HLSL), ("canopy_scratch", SCRATCH_HLSL)):
        text = path.read_text(encoding="utf-8")
        assert _documented(text) == wet.WET_SHADER_INPUTS[name] == look.SHADER_INPUTS[name], name
        body = "\n".join(line for line in text.splitlines() if not line.startswith("//"))
        for pin in wet.WET_SHADER_INPUTS[name]:
            assert re.search(rf"\b{pin}\b", body), (name, pin)
    text = WET_HLSL.read_text(encoding="utf-8")
    assert f"{wet.WET_COAT_OUTPUT} = saturate(" in text
    assert f"const float GravityRunCmS = {wet.HLSL_GRAVITY_RUN_CM_S};" in text
    assert f"const float BeadRoughness = {wet.HLSL_BEAD_ROUGHNESS};" in text


def test_the_hlsl_is_exact_when_dry():
    """Wetness 0: no rivulet cell is present (strict <, never step()), the
    beads are skipped, every lerp has alpha 0."""
    text = WET_HLSL.read_text(encoding="utf-8")
    assert "float present = h2 < coverage ? 1.0 : 0.0;" in text
    assert "float coverage = wet * saturate(RainRateMmh / rivFull);" in text
    assert "if (!airflow && beadAmount > 0.0 && wet > 0.0)" in text
    assert "float3 albedoOut = lerp(Albedo, sat * sat, wet * porosity);" in text
    assert "float roughOut = lerp(Roughness, min(Roughness, wetRough), wet);" in text
    assert not re.search(r"(?<!smooth)step\(", text)


def test_nothing_moves_a_vertex_and_the_masters_stay_opaque():
    for path in (LAYER, WET_HLSL, SCRATCH_HLSL):
        text = path.read_text(encoding="utf-8")
        assert "WorldPositionOffset" not in text and "WORLD_POSITION_OFFSET" not in text, path
        assert "blend_mode" not in text and "TRANSLUCENT" not in text, path
    assert "Substrate" not in LAYER.read_text(encoding="utf-8").replace("Substrate stays off", "")
    for name in wet.PASS_THROUGH:
        assert name != "WorldPositionOffset"


def test_the_masters_builder_calls_the_layer_once_per_master():
    text = MASTERS.read_text(encoding="utf-8")
    surface = text[text.index("def _surface"):text.index("def create_aircraft_paint")]
    glass = text[text.index("def create_aircraft_glass"):text.index("def create_aircraft_rubber")]
    rubber = text[text.index("def create_aircraft_rubber"):text.index("def _fx(")]
    assert surface.count("aircraft_wet_layer.add_wet_layer(material, sys.modules[__name__], cls)") == 1
    assert glass.count('aircraft_wet_layer.add_wet_layer(material, sys.modules[__name__], "glass")') == 1
    assert glass.count("aircraft_wet_layer.add_canopy_scratch(material, sys.modules[__name__])") == 1
    assert "aircraft_wet_layer" not in rubber
    # each graft after the attributes are wired, before the asset is saved
    for body in (surface, glass):
        assert body.index("_use_attributes(material, out)") < body.index("aircraft_wet_layer.") \
            < body.index("_finish(")
    tree = ast.parse(text)
    generation = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                      and any(getattr(t, "id", "") == "LOOK_GENERATION" for t in n.targets))
    assert generation != "1"    # the masters rebuild once with the layer


def test_the_layer_uses_only_helpers_the_masters_builder_defines():
    tree = ast.parse(MASTERS.read_text(encoding="utf-8"))
    defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    used = set(re.findall(r"\blib\.(\w+)\(", LAYER.read_text(encoding="utf-8")))
    assert used and used <= defined, used - defined


def test_the_master_scalars_default_to_wet_defaults_and_do_not_collide():
    for cls in ("paint", "bare_metal", "glass"):
        names = set(wet.WET_MASTER_SCALARS) | set(wet.WET_DYNAMIC_PARAMETERS)
        assert not names & set(look.CLASS_SCALARS[cls]), cls
        assert not names & set(look.CLASS_VECTORS[cls]), cls
        assert not names & set(look.BASE_PARAMETERS), cls
        for template in wet.WET_MASTER_SCALARS.values():
            value = wet.class_default(template, cls)
            assert 0.0 <= value
    assert wet.class_default("Porosity{cls}", "paint") == wet.WET_DEFAULTS["PorosityPaint"]
    assert wet.class_default("Porosity{cls}", "glass") == 0.0
    assert wet.class_default("BeadAmount{cls}", "glass") == 1.0
    with pytest.raises(ValueError):
        wet.class_default("Porosity{cls}", "chrome")


def test_the_four_scalars_the_cpp_sets_are_the_material_parameter_list():
    text = WET_CPP.read_text(encoding="utf-8")
    names = tuple(re.findall(r'const TCHAR\* const AircraftWetParam\w+ = TEXT\("(\w+)"\);', text))
    assert names == wet.WET_DYNAMIC_PARAMETERS
    assert text.count("Mid->SetScalarParameterValue(FName(AircraftWetParam") == 4
    # the layer creates exactly these as dynamic scalars
    assert "for i, name in enumerate(WET_DYNAMIC_PARAMETERS)" in LAYER.read_text(encoding="utf-8")


def test_the_fx_hooks_are_the_small_ones():
    fx = FX_CPP.read_text(encoding="utf-8")
    assert fx.count("Wet.Advance(LookMids, *Weather, ReadProperty(TEXT(\"velocities/vtrue-kts\")), "
                    "ReadProperty(TEXT(\"simulation/sim-time-sec\")), Record);") == 1
    assert "UMaterialInstanceDynamic::Create(LookInstance, Part)" in fx
    header = FX_H.read_text(encoding="utf-8")
    assert "FFlightSimAircraftWet Wet;" in header
    assert "const FFlightSimWeather* Weather = nullptr;" in header
    assert '#include "FlightSimAircraftWet.h"' in header
    commandlet = COMMANDLET.read_text(encoding="utf-8")
    assert commandlet.count("AircraftFXOptions.Weather = Weather.IsBuilt() ? &Weather : nullptr;") == 1
    # the weather is built before the aircraft look reads its pointer
    assert commandlet.index("if (!Weather.Build(World, WeatherOptions, Error))") < \
        commandlet.index("AircraftFXOptions.Weather = ")


def test_the_cpp_reads_only_the_weathers_public_surface():
    text = WET_CPP.read_text(encoding="utf-8")
    assert "Weather.RainRateMmh" not in text and "Weather.BeautyRainGain" not in text
    assert 'TryGetObjectField(TEXT("rain"), Rain)' in text
    assert 'TryGetNumberField(TEXT("rate_mmh"), RainRateMmh)' in text
    assert 'TryGetNumberField(TEXT("beauty_readability_gain"), BeautyRainGain)' in text
    weather = (BRIDGE / "Private" / "FlightSimWeather.cpp").read_text(encoding="utf-8")
    assert 'Row->SetNumberField(TEXT("rate_mmh"), RateMmh);' in weather
    assert 'SetNumberField(TEXT("beauty_readability_gain"), BeautyRainGain);' in weather


def test_the_record_carries_the_wet_group_fields():
    text = WET_CPP.read_text(encoding="utf-8")
    for field in ("wetness", "rain_rate_mmh", "airspeed_kts", "regime", "constants",
                  "canopy_scratch", "density", "anisotropy", "pixel_moving", "calibration"):
        assert f'TEXT("{field}")' in text, field
    assert 'Row->SetBoolField(TEXT("pixel_moving"), false);' in text
    assert 'Out->SetObjectField(TEXT("wet"), Row);' in text
    assert f'TEXT("{wet.UNCALIBRATED}")' in text


def test_anonymous_namespace_names_are_file_unique():
    text = WET_CPP.read_text(encoding="utf-8")
    ns = text[text.index("namespace\n{"):text.index("\n}\n")]
    names = set(re.findall(r"\b(AircraftWet\w+)\b", ns))
    others = "".join(p.read_text(encoding="utf-8") for p in (BRIDGE / "Private").glob("*.cpp")
                     if p.name != WET_CPP.name)
    for name in names:
        assert name not in others, name
    for name in re.findall(r"^\t(?:constexpr|const)\s[^=]*?\b(\w+)\s*=", ns, re.M):
        assert name.startswith("AircraftWet"), name


# -- the look manifest ------------------------------------------------------------

def _write_model(root, vertices, origin):
    import json
    (root / "body.obj").write_text("".join(f"v {x} {-y} {z}\n" for x, y, z in vertices), encoding="utf-8")
    (root / "mesh_manifest.json").write_text(json.dumps({
        "parts": ["body"], "mesh_origin_actor_cm": list(origin),
        "asset_path_root": "/Game/Aircraft/J11"}), encoding="utf-8")
    (root / "body.mtl").write_text("newmtl rgb_6b6b6b\nKd 0.42 0.42 0.42\nd 0.2\n", encoding="utf-8")


def test_the_look_manifest_carries_the_wet_group(tmp_path):
    _write_model(tmp_path, [(0, 0, 0), (-10, -5, 0), (-10, 5, 0)], (0.0, 0.0, 0.0))
    manifest = look.build_manifest("J11", look.load_config("J11"), str(tmp_path), str(J11_FDM))
    group = manifest["constants"]["wet"]
    assert set(group) == set(wet.WET_DEFAULTS)
    for key, entry in group.items():
        assert entry["value"] == float(wet.WET_DEFAULTS[key])
        assert entry["calibration"] == look.UNCALIBRATED == wet.UNCALIBRATED
        assert entry["probe"]


def test_every_wet_default_reaches_a_master_or_the_cpp():
    # No dead UNCALIBRATED constant: each WET_DEFAULTS key is a master scalar's
    # default for a class that takes the layer, a scratch / centre default, or
    # a constant the C++ integration reads.
    # the classes whose masters call add_wet_layer (pinned by
    # test_the_masters_builder_calls_the_layer_once_per_master; rubber does not)
    layered = ("paint", "bare_metal", "glass")
    assert set(wet.CLASS_KEYS) == set(layered)
    used = {template.format(cls=wet.CLASS_KEYS[cls]) for template in wet.WET_MASTER_SCALARS.values()
            for cls in layered}
    used |= set(wet.SCRATCH_MASTER_SCALARS.values())
    used |= {"CanopyCentreXCm", "CanopyCentreYCm", "CanopyCentreZCm"}
    cpp = WET_CPP.read_text(encoding="utf-8")
    used |= {key for key in ("WetSaturationMmh", "WetDryTauS") if f'TEXT("{key}")' in cpp}
    assert set(wet.WET_DEFAULTS) - used == set()
