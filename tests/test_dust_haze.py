"""Dust and humidity haze (visual overhaul, module dust-humidity-haze): what
must hold without an engine.

* Hanel's growth law: f(0) = 1, monotonic, capped at RH 0.95;
* the row follows the card: desert -> dust, forest -> none, METAR codes, the
  card's own word (an unknown one refused by name);
* the overlay keeps the card's Koschmieder visibility within 5 %;
* the second fog's Beer-Lambert transmittance: 1 for a path far above the
  layer, flagged (a cloud_path / cloud_occlusion row) inside a dense one;
* the C++ table is the Python table (text parse), and where a C++ compiler
  exists the pure block's laws are run against Python number for number;
* the hooks are where the module says, beauty only, and every engine symbol
  is in check_bridge_api.sh.
"""

import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core.scene import dust_haze as dh
from core.scene import world_beauty as wb

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
DUST_CPP = (SOURCE / "Private" / "FlightSimDustHaze.cpp").read_text(encoding="utf-8")
DUST_H = (SOURCE / "Public" / "FlightSimDustHaze.h").read_text(encoding="utf-8")
CLOUDS_CPP = (SOURCE / "Private" / "FlightSimClouds.cpp").read_text(encoding="utf-8")
CLOUDS_H = (SOURCE / "Public" / "FlightSimClouds.h").read_text(encoding="utf-8")
CHECK = (REPO / "scripts" / "check_bridge_api.sh").read_text(encoding="utf-8")
PROBE_LOG = (REPO / "docs" / "visual" / "PROBE_LOG.md").read_text(encoding="utf-8")
CXX = shutil.which("g++") or shutil.which("clang++")
NEEDS_CXX = pytest.mark.skipif(CXX is None, reason="no C++ compiler on this machine")
BEGIN, END = "// FLIGHTSIM-DUSTHAZE-PURE-BEGIN", "// FLIGHTSIM-DUSTHAZE-PURE-END"


def _pure():
    return DUST_CPP[DUST_CPP.index(BEGIN) + len(BEGIN):DUST_CPP.index(END)]


def _cpp_number(text):
    """A C++ number literal or a quotient of two (the ozone colour)."""
    text = text.strip()
    if "/" in text:
        a, b = text.split("/")
        return float(a) / float(b)
    return float(text)


# -- Hanel's growth ----------------------------------------------------------------

def test_growth_is_one_in_dry_air():
    for gamma in dh.RH_GAMMA.values():
        assert dh.growth_factor(0.0, gamma) == 1.0
    assert dh.growth_factor(-0.3, 0.5) == 1.0


def test_growth_is_monotonic_and_capped_at_95_percent():
    for gamma in dh.RH_GAMMA.values():
        values = [dh.growth_factor(rh / 100.0, gamma) for rh in range(0, 101)]
        assert all(b >= a for a, b in zip(values, values[1:]))
        capped = dh.growth_factor(dh.RH_CAP, gamma)
        assert dh.growth_factor(0.99, gamma) == capped == dh.growth_factor(1.0, gamma)
        assert capped == pytest.approx(0.05 ** -gamma)


def test_gamma_orders_dust_below_continental_below_maritime():
    assert dh.RH_GAMMA["dust"] < dh.RH_GAMMA["continental"] < dh.RH_GAMMA["maritime"]
    assert dh.aerosol_for("none", "ocean") == "maritime"
    assert dh.aerosol_for("haze", "forest") == "continental"
    assert dh.aerosol_for("dust", "ocean") == "dust"


# -- the row -----------------------------------------------------------------------

def test_desert_selects_dust_and_forest_none():
    assert dh.select_dust("desert") == "dust"
    assert dh.select_dust("forest") == "none"
    assert dh.select_dust(None) == "none"


def test_metar_codes_select_the_row():
    assert dh.select_dust("forest", ["BLSA"]) == "dust"
    assert dh.select_dust("forest", "+DU VCSS") == "dust"
    assert dh.select_dust("forest", ["HZ"]) == "haze"
    assert dh.select_dust("forest", "-RA BR") == "haze"
    assert dh.select_dust("desert", ["HZ"]) == "dust"     # the dust selectors outrank haze
    assert dh.select_dust("forest", ["RA"]) == "none"


def test_the_card_word_wins_and_an_unknown_one_is_refused_by_name():
    assert dh.select_dust("forest", None, True) == "dust"
    assert dh.select_dust("desert", None, False) == "none"
    assert dh.select_dust("desert", None, "haze") == "haze"
    with pytest.raises(ValueError, match=r"^dust_haze\.row: "):
        dh.select_dust("forest", None, "sandy")
    with pytest.raises(ValueError, match=r"^dust_haze\.row: "):
        dh.parameters(50.0, 20.0, "smog")


# -- visibility --------------------------------------------------------------------

@pytest.mark.parametrize("row", dh.ROWS)
@pytest.mark.parametrize("visibility", [0.5, 3.0, 10.0, 20.0, 50.0, 100.0])
@pytest.mark.parametrize("rh", [0.0, 40.0, 80.0, 99.0])
def test_the_overlay_keeps_the_card_visibility(row, visibility, rh):
    for biome in ("forest", "ocean", "desert"):
        p = dh.parameters(rh, visibility, row, biome=biome)
        assert p["visibility_model_km"] == pytest.approx(visibility, rel=dh.VISIBILITY_TOLERANCE)
        assert 0.0 <= p["fog_factor_after"] <= 1.0
        assert 0.0 < p["renormalised"] <= 1.0
        assert p["mie_after"] >= 0.0 and p["second_fog_ground_extinction_per_km"] >= 0.0
        # the three terms and the atmosphere's Rayleigh sum to the Koschmieder beta of the card
        total = (wb.RAYLEIGH_GREEN_PER_KM + p["mie_after"] + p["second_fog_ground_extinction_per_km"]
                 + p["fog_factor_after"] * p["koschmieder_beta_per_km"])
        assert wb.KOSCHMIEDER / total == pytest.approx(visibility, rel=dh.VISIBILITY_TOLERANCE)


def test_humid_air_moves_haze_into_the_mie_layer():
    dry = dh.parameters(0.0, 20.0, "none", biome="forest")
    wet = dh.parameters(90.0, 20.0, "none", biome="forest")
    assert dry["mie_after"] == pytest.approx(dry["mie_before"])
    assert wet["mie_after"] > dry["mie_after"]
    assert wet["fog_factor_after"] < dry["fog_factor_after"]


def test_no_visibility_keeps_the_mie_and_the_main_fog():
    p = dh.parameters(None, None, "dust", biome="desert")
    assert p["visibility_target_km"] is None and p["mie_after"] is None
    assert p["fog_density_ratio"] == 1.0
    assert p["rh_basis"] == "default" and p["rh_pct"] == dh.DEFAULT_RH_PCT
    assert p["second_fog"]["density"] == dh.DUST_ROWS["dust"]["second_fog_density"]


def test_the_record_shape():
    p = dh.parameters(60.0, 15.0, "dust", biome="desert", inversion_height_m=2200.0)
    for key in ("row", "rh", "gamma", "f_rh", "mie_before", "mie_after", "second_fog",
                "visibility_target_km", "visibility_model_km", "subject_transmittance",
                "pixel_moving", "calibration"):
        assert key in p
    assert set(p["second_fog"]) == {"density", "falloff", "offset_m"}
    assert p["second_fog"]["offset_m"] == 2200.0
    assert p["pixel_moving"] is False
    assert p["calibration"].startswith("UNCALIBRATED")
    # dust absorbs blue more than red: the warm tint
    r, g, b = p["mie_absorption_rgb"]
    assert b > g == 1.0 > r
    assert p["vfog_albedo_rgb"][0] > p["vfog_albedo_rgb"][2]


# -- the second fog's transmittance -----------------------------------------------

def test_a_path_far_above_the_layer_is_clear():
    second = {"density": 0.0004, "falloff": 0.015, "offset_m": 1500.0}
    row = dh.subject_occlusion(9000.0, 8000.0, 1500.0, second)
    assert row["transmittance"] == pytest.approx(1.0, abs=1e-4)
    assert row["path_m"] == 0.0 and not row["flagged"]
    assert dh.cloud_occlusion_entry(9000.0, 8000.0, 1500.0, second) is None
    # no layer drawn: exactly 1
    assert dh.subject_occlusion(100.0, 50.0, 5000.0, {**second, "density": 0.0})["transmittance"] == 1.0


def test_a_subject_inside_a_dense_layer_is_flagged_like_a_cloud():
    second = {"density": 0.004, "falloff": 0.015, "offset_m": 1500.0}
    entry = dh.cloud_occlusion_entry(300.0, 200.0, 8000.0, second)
    assert entry is not None and entry["flagged"]
    assert entry["transmittance"] < wb.OCCLUSION_FLAG_TRANSMITTANCE
    assert entry["layer"] == dh.LAYER_NAME
    assert set(entry) >= {"path_m", "tau", "transmittance", "flagged"}   # the cloud_path row's keys
    assert entry["path_m"] == pytest.approx(8000.0)


def test_the_exponential_integral_matches_a_riemann_sum():
    d, f, h = 0.0004, 0.015, 1500.0
    a, b, length = 200.0, 2600.0, 9000.0
    n = 20000
    tau = sum(dh.second_fog_extinction_per_m(d, f, h, a + (b - a) * (i + 0.5) / n)
              for i in range(n)) * length / n
    assert dh.second_fog_tau(d, f, h, a, b, length) == pytest.approx(tau, rel=1e-6)
    assert dh.second_fog_tau(d, f, h, b, a, length) == pytest.approx(tau, rel=1e-6)


def test_parameters_record_the_subject_transmittance_when_given_the_geometry():
    p = dh.parameters(50.0, 10.0, "dust", biome="desert", camera_z_m=2500.0, subject_z_m=2400.0,
                      length_m=400.0)
    assert 0.0 < p["subject_transmittance"] <= 1.0
    assert p["subject_path"]["layer"] == dh.LAYER_NAME


# -- the card ----------------------------------------------------------------------

def test_card_inputs_read_the_card_like_the_cpp():
    card = {"look": {"visibility_km": 12.0, "present_weather": ["BLSA"]},
            "weather_look": {"surface": "forest"},
            "atmosphere_properties": {"stated": {"dew_point_c": {"value": 5.0},
                                                 "temperature_deviation_c": {"value": 5.0},
                                                 "relative_humidity_pct": None}}}
    i = dh.card_inputs(card)
    assert i["rh_pct"] == pytest.approx(dh.magnus_rh_pct(20.0, 5.0))
    assert 35.0 < i["rh_pct"] < 40.0
    assert i["biome"] == "forest" and i["visibility_km"] == 12.0
    p = dh.card_parameters(card)
    assert p["row"] == "dust"
    card["look"]["rh_pct"] = 85.0
    assert dh.card_inputs(card)["rh_pct"] == 85.0
    assert dh.card_parameters({"weather": {"dust": "haze"}})["row"] == "haze"


def test_spec_parameters_runs_on_a_compiled_spec():
    from core.nl.compiler import compile_prompt
    spec = compile_prompt("fly the c172p at 1500 m and 100 kt")
    p = dh.spec_parameters(spec)
    assert p["row"] in dh.ROWS and p["pixel_moving"] is False


# -- the C++ twin ------------------------------------------------------------------

def test_the_cpp_table_is_the_python_table():
    body = _pure()
    match = re.search(r"Rows\[DustRowCount\]\[DustFieldCount\]\s*=\s*\{(.*?)\};", body, re.S)
    assert match
    rows = re.findall(r"\{([^{}]*)\}", match.group(1))
    assert len(rows) == len(dh.ROWS)
    for row, want in zip(rows, dh.table_rows()):
        got = [_cpp_number(x) for x in row.split(",")]
        assert got == pytest.approx(want, rel=1e-12), row
    names = re.search(r'Names\[DustRowCount\]\s*=\s*\{([^}]*)\}', body).group(1)
    assert tuple(re.findall(r'"(\w+)"', names)) == dh.ROWS
    gammas = re.search(r"Gammas\[AerosolCount\]\s*=\s*\{([^}]*)\}", body).group(1)
    assert [float(x) for x in gammas.split(",")] == [dh.RH_GAMMA[a] for a in dh.AEROSOLS]
    assert f"constexpr int DustFieldCount = {len(dh.DUST_FIELDS)};" in body
    assert f"DustRhCap = {dh.RH_CAP};" in body
    assert f"DustDefaultRhPct = {dh.DEFAULT_RH_PCT};" in body
    assert f"DustRayleighGreenPerKm = {wb.RAYLEIGH_GREEN_PER_KM};" in body
    assert f"DustMieSingleScatterAlbedo = {wb.MIE_SINGLE_SCATTER_ALBEDO};" in body
    assert f"DustFalloffToPerM = {dh.FALLOFF_TO_PER_M};" in body


def test_the_cpp_table_is_labelled_uncalibrated():
    assert "UNCALIBRATED" in _pure()
    assert "UNCALIBRATED" in dh.CALIBRATION


@NEEDS_CXX
def test_the_cpp_laws_are_the_python_laws(tmp_path):
    source = tmp_path / "pure.cpp"
    main = r'''
int main() {
    using namespace FlightSimDustHazePure;
    const double rhs[] = {0.0, 0.4, 0.8, 0.99};
    for (double rh : rhs) for (int a = 0; a < AerosolCount; ++a)
        std::printf("g %.17g\n", DustGrowthFactor(rh, RhGamma(a)));
    std::printf("t %.17g\n", DustSecondTau(0.0004, 0.015, 1500.0, 200.0, 2600.0, 9000.0));
    std::printf("t %.17g\n", DustSecondTau(0.0004, 0.015, 1500.0, 700.0, 700.0, 3000.0));
    std::printf("e %.17g\n", DustSecondExtinctionPerM(0.0004, 0.015, 1800.0, 0.0));
    const double slabs[][5] = {{200.0, 2600.0, 9000.0, 0.0, 1500.0}, {700.0, 700.0, 3000.0, 0.0, 1500.0},
                               {9000.0, 8000.0, 1500.0, 0.0, 1500.0}, {-50.0, 300.0, 800.0, -50.0, 1500.0}};
    for (const auto& s : slabs)
        std::printf("p %.17g\n", DustSlabPathM(s[0], s[1], s[2], s[3], s[4]));
    FDustRenorm R = DustRenormalise(%BETA%, %MIE%, %FF%, %FRH%, %DENS%, %GROUND%);
    std::printf("r %.17g %.17g %.17g %.17g %.17g %.17g\n", R.MieAfter, R.SecondGroundPerKm,
                R.SecondDensity, R.FogFactorAfter, R.Scale, R.VisibilityModelKm);
    return 0;
}
'''
    p = dh.parameters(85.0, 8.0, "dust", biome="desert")
    split = wb.mie_split(8.0, wb.ATMOSPHERE[p["preset"]]["mie_share"],
                         wb.ATMOSPHERE[p["preset"]]["mie_cap_per_km"])
    row = dh.DUST_ROWS["dust"]
    ground = 1000.0 * dh.second_fog_extinction_per_m(row["second_fog_density"], row["second_fog_falloff"],
                                                     row["inversion_height_m"], 0.0)
    for key, value in (("%BETA%", split["beta_per_km"]), ("%MIE%", split["mie_extinction_per_km"]),
                       ("%FF%", split["fog_factor"]), ("%FRH%", p["f_rh"]),
                       ("%DENS%", row["second_fog_density"]), ("%GROUND%", ground)):
        main = main.replace(key, repr(float(value)))
    source.write_text("#include <cmath>\n#include <cstdio>\n" + _pure() + main, encoding="utf-8")
    binary = tmp_path / "pure"
    subprocess.run([CXX, "-std=c++17", "-O1", "-Wall", "-Werror", "-Wno-unused-const-variable", "-o", str(binary), str(source)],
                   check=True, capture_output=True, text=True)
    lines = subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout.splitlines()
    want = [dh.growth_factor(rh, dh.RH_GAMMA[a]) for rh in (0.0, 0.4, 0.8, 0.99) for a in dh.AEROSOLS]
    got = [float(line.split()[1]) for line in lines if line.startswith("g ")]
    assert got == pytest.approx(want, rel=1e-12)
    taus = [float(line.split()[1]) for line in lines if line.startswith("t ")]
    assert taus == pytest.approx([dh.second_fog_tau(0.0004, 0.015, 1500.0, 200.0, 2600.0, 9000.0),
                                  dh.second_fog_tau(0.0004, 0.015, 1500.0, 700.0, 700.0, 3000.0)],
                                 rel=1e-12)
    e = [float(line.split()[1]) for line in lines if line.startswith("e ")][0]
    assert e == pytest.approx(dh.second_fog_extinction_per_m(0.0004, 0.015, 1800.0, 0.0), rel=1e-12)
    paths = [float(line.split()[1]) for line in lines if line.startswith("p ")]
    assert paths == pytest.approx([wb.slab_path_m(*s) for s in ((200.0, 2600.0, 9000.0, 0.0, 1500.0),
                                                                (700.0, 700.0, 3000.0, 0.0, 1500.0),
                                                                (9000.0, 8000.0, 1500.0, 0.0, 1500.0),
                                                                (-50.0, 300.0, 800.0, -50.0, 1500.0))],
                                  rel=1e-12, abs=1e-12)
    r = [float(x) for x in next(line for line in lines if line.startswith("r ")).split()[1:]]
    assert r == pytest.approx([p["mie_after"], p["second_fog_ground_extinction_per_km"],
                               p["second_fog"]["density"], p["fog_factor_after"], p["renormalised"],
                               p["visibility_model_km"]], rel=1e-12)


# -- the hooks and the engine surface ---------------------------------------------

def test_the_hooks_are_in_the_world_beauty_only():
    after = CLOUDS_CPP.index("ApplyAtmosphere(World, Scene, VisibilityKm);")
    hook = CLOUDS_CPP.index("DustHaze.Apply(World, Scene, Params, Card, VisibilityKm,")
    assert 0 < hook - after < 300
    assert 'Record->SetObjectField(TEXT("dust_haze"), DustOut);' in CLOUDS_CPP
    assert CLOUDS_CPP.index("DustHaze.FrameRow(") < CLOUDS_CPP.index('Frame->SetArrayField(TEXT("cloud_path")')
    # the C++ row carries the Python row's keys (subject_occlusion)
    for key in ("layer", "path_m", "tau", "transmittance", "flagged"):
        assert f'TEXT("{key}")' in DUST_CPP.split("FFlightSimDustHaze::FrameRow")[1], key
    assert "FFlightSimDustHaze DustHaze;" in CLOUDS_H
    assert '#include "FlightSimDustHaze.h"' in CLOUDS_H
    # the commandlet never calls it directly: the measure quality cannot reach it
    commandlet = (SOURCE / "Private" / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
    assert "DustHaze" not in commandlet


def test_every_engine_setter_is_in_check_bridge_api():
    assert "# -- dust-humidity-haze" in CHECK
    for symbol in ("SetMieScatteringScale", "SetMieAbsorptionScale", "SetMieAbsorption(",
                   "SetOtherAbsorption(", "SetOtherAbsorptionScale(", "SetSecondFogData(",
                   "SetVolumetricFogAlbedo(", "SetFogDensity("):
        assert symbol in DUST_CPP
        assert symbol.rstrip("(") in CHECK, symbol


def test_the_record_says_no_pixel_moves_and_names_its_rows():
    assert 'SetBoolField(TEXT("pixel_moving"), false)' in DUST_CPP
    assert 'TEXT("dust_haze_second_fog")' in DUST_CPP
    assert dh.LAYER_NAME == "dust_haze_second_fog"


def test_the_probe_log_has_a_section():
    assert "## dust-humidity-haze" in PROBE_LOG
