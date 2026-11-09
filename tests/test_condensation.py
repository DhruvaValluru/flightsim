"""Humidity-gated condensation (core/scene/condensation.py and its C++ twin
FlightSimCondensation.cpp): the physics' self-gating, the twin's constants
pinned to the C++ by text, and the labels-match-pixels wiring by grep."""
from __future__ import annotations

import ast
import math
import re
from pathlib import Path

import pytest

from core.environment import atmosphere as atm
from core.scene import condensation as cond

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
CPP = BRIDGE / "Private" / "FlightSimCondensation.cpp"
HEADER = BRIDGE / "Public" / "FlightSimCondensation.h"
FX_CPP = BRIDGE / "Private" / "FlightSimAircraftFX.cpp"
FX_H = BRIDGE / "Public" / "FlightSimAircraftFX.h"
MATERIAL = REPO / "scripts" / "aircraft_condensation_material.py"
MASTERS = REPO / "scripts" / "ue_aircraft_master_materials.py"
LOOK = REPO / "scripts" / "aircraft_look.py"
SHADER = REPO / "assets" / "shaders" / "aircraft" / "condensation_opacity.hlsl"
CHECK = REPO / "scripts" / "check_bridge_api.sh"
CATALOG = REPO / "core" / "messages" / "catalog.yaml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# -- a fighter in an ISA atmosphere (J-11 class numbers; SI) ------------------

def _isa(h_m: float):
    t = max(288.15 - 0.0065 * min(h_m, 11000.0), 216.65)
    if h_m <= 11000.0:
        p = 101325.0 * (t / 288.15) ** 5.2559
    else:
        p = 22632.0 * math.exp(-(h_m - 11000.0) / 6341.6)
    return t, p


def state(h_m=0.0, rh=80.0, mach=0.6, nz=1.0, alpha=5.0, t_k=None,
          weight_n=245e3, b_m=14.7, s_m2=62.0):
    t, p = _isa(h_m)
    if t_k is not None:
        t = t_k
    rho = p / (287.05 * t)
    v = mach * math.sqrt(1.4 * 287.05 * t)
    return {"t_k": t, "p_pa": p, "rho_kgm3": rho, "mach": mach, "v_mps": v,
            "qbar_pa": 0.5 * rho * v * v, "nz": nz, "weight_n": weight_n,
            "b_m": b_m, "s_m2": s_m2, "alpha_deg": alpha, "rh_pct": rh}


LEX_ON = {"LexEnabled": 1.0}


def _opacities(s, overrides=None):
    return {k: v["opacity"] for k, v in cond.solve(s, overrides).items()}


# -- the physics --------------------------------------------------------------

def test_the_saturation_is_atmosphere_pys_magnus():
    t = 288.15
    assert cond.saturation_vapour_pressure_pa(t) == pytest.approx(
        atm.saturated_vapour_pressure_psf(t * 1.8) * atm.JSBSIM_PSF_TO_PA)
    assert cond.saturation_vapour_pressure_pa(273.15) == pytest.approx(611.2, rel=1e-9)
    assert cond.EPSILON == pytest.approx(0.622, abs=1e-3)


@pytest.mark.parametrize("mach,nz,alpha", [(0.95, 5.0, 25.0), (0.6, 7.0, 20.0), (0.3, 1.0, 5.0)])
def test_dry_air_gives_no_cloud_anywhere(mach, nz, alpha):
    got = _opacities(state(rh=0.0, mach=mach, nz=nz, alpha=alpha), LEX_ON)
    assert got == {"tip": 0.0, "sheet": 0.0, "lex": 0.0, "cone": 0.0}


@pytest.mark.parametrize("mach,nz", [(0.85, 1.0), (0.95, 5.0), (0.9, 3.0)])
def test_high_air_at_30_pct_gives_nothing(mach, nz):
    got = _opacities(state(h_m=12000.0, rh=30.0, mach=mach, nz=nz, alpha=20.0), LEX_ON)
    assert got == {"tip": 0.0, "sheet": 0.0, "lex": 0.0, "cone": 0.0}


def test_the_transonic_cone_forms_at_m095_and_not_at_m080():
    humid = dict(h_m=0.0, rh=90.0, t_k=288.15)
    at95 = cond.solve(state(mach=0.95, **humid))["cone"]
    at80 = cond.solve(state(mach=0.80, **humid))["cone"]
    assert at95["dq_gkg"] > 0.0 and at95["opacity"] > 0.0
    assert at80["dq_gkg"] is None and at80["opacity"] == 0.0


def test_a_5g_pull_gives_tip_vortices_and_1g_does_not():
    pull = cond.solve(state(rh=80.0, mach=0.6, nz=5.0))["tip"]
    level = cond.solve(state(rh=80.0, mach=0.6, nz=1.0))["tip"]
    assert pull["opacity"] > 0.0
    assert level["opacity"] == 0.0 and level["dq_gkg"] < 0.0


def test_the_upper_wing_sheet_needs_lift_not_just_humidity():
    assert cond.solve(state(rh=80.0, mach=0.6, nz=5.0))["sheet"]["opacity"] > 0.0
    assert cond.solve(state(rh=80.0, mach=0.6, nz=1.0))["sheet"]["opacity"] == 0.0


def test_the_lex_vortex_only_on_a_lex_airframe_above_onset():
    hi = state(rh=80.0, mach=0.4, nz=4.0, alpha=24.0)
    lo = state(rh=80.0, mach=0.4, nz=4.0, alpha=8.0)
    assert cond.solve(hi)["lex"]["dq_gkg"] is None             # LexEnabled 0 by default
    assert cond.solve(hi, LEX_ON)["lex"]["opacity"] > 0.0
    assert cond.solve(lo, LEX_ON)["lex"]["dq_gkg"] is None      # below LexAlphaOnsetDeg


@pytest.mark.parametrize("site,kw", [("tip", dict(mach=0.6, nz=5.0)),
                                     ("sheet", dict(mach=0.6, nz=3.0)),
                                     ("cone", dict(mach=0.95, nz=1.0)),
                                     ("lex", dict(mach=0.4, nz=4.0, alpha=24.0))])
def test_opacity_is_monotonic_in_humidity(site, kw):
    prev_dq, prev_op = -math.inf, 0.0
    for rh in range(0, 101, 5):
        row = cond.solve(state(rh=float(rh), **kw), LEX_ON)[site]
        assert row["dq_gkg"] >= prev_dq and row["opacity"] >= prev_op, (site, rh)
        prev_dq, prev_op = row["dq_gkg"], row["opacity"]
    assert prev_op > 0.0


def test_an_absent_or_nan_read_drops_the_site_and_says_which():
    s = state(rh=80.0, mach=0.95, nz=5.0)
    s["b_m"] = float("nan")
    s["s_m2"] = None
    got = cond.solve(s)
    assert got["tip"]["dq_gkg"] is None and got["tip"]["dropped"] == ["b_m"]
    assert got["sheet"]["dq_gkg"] is None and got["sheet"]["dropped"] == ["s_m2"]
    assert got["cone"]["opacity"] > 0.0 and "dropped" not in got["cone"]
    s["rh_pct"] = None
    assert all(row["dq_gkg"] is None for row in cond.solve(s).values())


def test_the_lamb_oseen_factor_is_the_peak_swirl_radius_form():
    r_peak = 1.12091   # Lamb-Oseen: v_theta peaks at 1.12091 x the Gaussian width
    assert cond.LAMB_OSEEN_CORE_FACTOR == pytest.approx(math.log(2.0) * r_peak ** 2, abs=0.005)


def test_state_from_fdm_converts_jsbsim_units():
    s = cond.state_from_fdm({"atmosphere/T-R": 518.67, "atmosphere/P-psf": 2116.228,
                             "velocities/vtrue-kts": 100.0, "metrics/bw-ft": 10.0,
                             "inertia/weight-lbs": 1.0}, 50.0)
    assert s["t_k"] == pytest.approx(288.15)
    assert s["p_pa"] == pytest.approx(101325.0, rel=1e-4)
    assert s["v_mps"] == pytest.approx(51.4444)
    assert s["b_m"] == pytest.approx(3.048)
    assert s["weight_n"] == pytest.approx(4.448221615)
    assert s["mach"] is None and s["rh_pct"] == 50.0


def test_no_prandtl_glauert_anywhere():
    for path in (Path(cond.__file__), CPP, HEADER, MATERIAL, SHADER):
        assert "prandtl" not in _read(path).lower(), path


# -- the C++ twin -------------------------------------------------------------

def _cpp_defaults():
    """CondensationDefault(TEXT("Name"), value) pairs in the C++."""
    text = _read(CPP)
    return {m.group(1): float(m.group(2)) for m in re.finditer(
        r'\{\s*TEXT\("(\w+)"\)\s*,\s*([-+0-9.eE]+)\s*\}', text)}


def test_the_cpp_constant_names_and_defaults_are_the_twins():
    got = _cpp_defaults()
    assert got == {k: pytest.approx(v) for k, v in cond.CONDENSATION_DEFAULTS.items()}


def test_the_cpp_physics_constants_are_the_twins():
    text = _read(CPP)
    assert re.search(r"CondensationLambOseen\s*=\s*0\.87;", text)
    assert re.search(r"CondensationPoisson\s*=\s*0\.2857;", text)
    assert "611.2" in text and "17.62" in text and "243.12" in text
    for prop in cond.FDM_READS:
        assert f'TEXT("{prop}")' in text, prop


def test_the_actors_are_beauty_only_and_never_aircraft_components():
    text = _read(CPP)
    assert "BeautyOnlyActors.Add(" in text
    assert not re.search(r"NewObject<\w+>\(\s*Aircraft\b", text)
    assert "AttachToActor(Aircraft, FAttachmentTransformRules::KeepRelativeTransform)" in text
    # no refraction, no vertex motion in the material
    mat = _read(MATERIAL)
    assert "REFRACTION" not in mat and "WORLD_POSITION_OFFSET" not in mat
    assert "BLEND_TRANSLUCENT" in mat


def test_the_record_carries_the_label_convention_and_calibration():
    text = _read(CPP)
    assert cond.LABEL_CONVENTION in text
    assert f'TEXT("{cond.MODEL}")' in text
    for key in ("fallback_used", "constants", "per_frame", "label_convention",
                "pixel_moving", "calibration", "dq_gkg", "opacity"):
        assert f'TEXT("{key}")' in text, key
    assert "UNCALIBRATED" in text
    assert re.search(r'SetBoolField\(TEXT\("pixel_moving"\),\s*false\)', text)


def test_the_hooks_are_in_place():
    fx = _read(FX_CPP)
    assert re.search(r"const bool bVapour = Condensation\.Advance\(ReadProperty, Record\) \|\|\s*"
                     r"\(!Condensation\.HasHumidity\(\) &&", fx)
    assert "Condensation.Build(World, Aircraft, Constants," in fx
    assert "FFlightSimCondensation Condensation;" in _read(FX_H)
    look = _read(LOOK)
    assert '"condensation": _constants(CONDENSATION_DEFAULTS' in look
    masters = _read(MASTERS)
    assert "aircraft_condensation_material" in masters


def test_the_material_and_shader_agree_with_the_cpp():
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    import aircraft_condensation_material as m
    import aircraft_look as look
    assert m.NAME == "M_AircraftCondensation"
    assert m.NAME in look.FX_MASTERS
    assert look.FX_PARAMETERS[m.NAME] == m.PARAMETERS
    text = _read(CPP)
    assert f'TEXT("{look.MASTER_ROOT}/{m.NAME}.{m.NAME}")' in text
    for p in m.PARAMETERS:
        assert f'TEXT("{p}")' in text, p
    shader = _read(SHADER)
    assert tuple(re.findall(r"^//\s{2,}(\w+)\s+float", shader, re.M)) == m.SHADER_INPUTS
    assert "return" in shader


def test_the_engine_symbols_are_in_the_check_script_block():
    text = _read(CHECK)
    begin = text.index("# -- CONDENSATION (condensation-solver)")
    block = text[begin:text.index("# -- CONDENSATION -- end")]
    for symbol in ("GetRenderData", "PositionVertexBuffer", "GetVertexData",
                   "GetRelativeTransform", "UMaterialExpressionDepthFade",
                   "UMaterialExpressionNoise"):
        assert symbol in block, symbol


def test_the_refusal_is_catalogued():
    assert "aircraft_look.condensation:" in _read(CATALOG)
    assert "aircraft_look.condensation:" in _read(CPP)


def test_anonymous_names_are_file_unique():
    text = _read(CPP)
    start = text.index("namespace\n{")
    ns = text[start:text.index("\n}\n", start)]
    names = re.findall(r"^\t(?:constexpr |const )?[\w:<>*& ]+?\b(\w+)\s*(?:=|\()", ns, re.M)
    assert len(names) > 10
    for name in names:
        if name in ("if", "for", "return"):
            continue
        assert name.startswith("Condensation"), name
