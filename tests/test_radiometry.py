"""S1: the calibration chain, the band proxy over the cached tables, and
the sun in lux -- every number checked by hand or recomputed from the
tables, every refusal by name, every table absence refused rather than
invented.

Measured here (2026-09-29): the daylight triple's luminance per unit
29 951.6 cd/m^2 with A = 0.78 (38 399.5 without); an 18 % card under the
engine's 8.0 sun reads 1.53e-5 of full scale; under the clear-sky sun at
50 deg (95 788 lx) it reads 0.183; the ASTM G173-03 direct spectrum's
luminous efficacy under V(lambda) is 107.92 lm/W; the extraterrestrial
direct normal illuminance is 133 100 lx; K_band blue 0.0596, green
0.7588, red 0.3412.
"""

from __future__ import annotations

import copy
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from core.capture import radiometry as R
from core.capture.exposure import ev100
from core.records import AppliedVariable, records_block
from core.scenario import solar

REPO = Path(__file__).resolve().parents[1]
DAYLIGHT_EV100 = ev100(8.0, 1.0 / 500.0, 100.0)


# -- the chain ------------------------------------------------------------------------------

def test_the_constant_is_iso_12232_over_iso_2720_by_hand():
    """L_max = 2^EV100 x 78 / (q x 100) with q = 0.65: 78 / 65 = 1.2."""
    assert R.CALIBRATION_CONSTANT == pytest.approx(78.0 / (0.65 * 100.0), abs=1e-12)
    assert R.CALIBRATION_CONSTANT == 1.2


def test_the_daylight_triple_s_luminance_per_unit_by_hand():
    """1.2 x 0.78 x 2^14.9658 = 0.936 x 32000 = 29 952 cd/m^2 per unit; the
    blueprint's 38 400 is the figure WITHOUT the lens attenuation."""
    per_unit = R.luminance_per_unit(DAYLIGHT_EV100)
    assert per_unit == pytest.approx(0.936 * 32000.0, rel=1e-9)
    assert per_unit == pytest.approx(29951.6, abs=0.5)
    assert R.luminance_per_unit(DAYLIGHT_EV100, 0.0, 1.0) == pytest.approx(38400.0, rel=1e-9)
    assert R.LENS_ATTENUATION_DEFAULT == 0.78


def test_exposure_compensation_plus_one_halves_the_luminance_per_unit():
    """The EC sign: +1 EC means the picture is one stop brighter, so one
    unit stands for HALF the luminance. Measured on a synthetic frame."""
    frame = np.linspace(0.0, 1.0, 12).reshape(3, 4)[..., None].repeat(3, axis=2)
    without = R.luminance_from_frame(frame, DAYLIGHT_EV100, 0.0)
    with_ec = R.luminance_from_frame(frame, DAYLIGHT_EV100, 1.0)
    assert np.allclose(with_ec, without / 2.0)
    assert R.luminance_per_unit(DAYLIGHT_EV100, -1.0) == pytest.approx(2.0 * R.luminance_per_unit(DAYLIGHT_EV100))
    # The record's null test carries that measurement and grades it.
    block = R.radiometry_block(DAYLIGHT_EV100, 0.0)
    record = R.radiometry_record(block, null_with=R.luminance_per_unit(DAYLIGHT_EV100, 1.0),
                                 null_without=R.luminance_per_unit(DAYLIGHT_EV100, 0.0))
    assert record.null_test.ok and record.null_test.kind == "reached"
    assert record.null_test.with_value == pytest.approx(record.null_test.without_value / 2.0)
    again = AppliedVariable.from_dict(record.to_dict())
    assert again.to_dict() == record.to_dict()
    assert records_block([record])["applied_variables"][0]["name"] == "sensing.radiometry"


@pytest.mark.parametrize("bad", [0.0, -0.5, 1.5, "x", None, True, float("nan")])
def test_a_lens_attenuation_outside_the_unit_interval_refuses_by_name(bad):
    with pytest.raises(R.RadiometryError) as info:
        R.luminance_per_unit(DAYLIGHT_EV100, 0.0, bad)
    assert info.value.constraint == "sensing.radiometry"


def test_the_grey_card_under_the_engine_s_sun_is_black_and_under_a_physical_one_is_grey():
    """The defect this item names, in numbers: 0.18 x 8 / pi = 0.458
    cd/m^2 over 29 952 = 1.5e-5 (black); under the clear-sky sun at 50
    deg, 95 788 lx, 0.18 x 95788 / pi = 5488 cd/m^2 over 29 952 = 0.183."""
    black = R.grey_card_prediction(R.ENGINE_SUN_TODAY, DAYLIGHT_EV100)
    assert black == pytest.approx(0.18 * 8.0 / math.pi / 29951.6, rel=1e-3)
    assert black < 2e-5
    sun = solar.illuminance_lux(50.0).illuminance_lux
    grey = R.grey_card_prediction(sun, DAYLIGHT_EV100)
    assert grey == pytest.approx(0.183, abs=0.002)
    assert R.grey_card_luminance(1000.0) == pytest.approx(0.18 * 1000.0 / math.pi)


def test_exposure_units_are_refused_by_name_until_the_sun_is_physical():
    with pytest.raises(R.RadiometryError) as info:
        R.exposure_units_check({"sun": {"intensity": 8.0, "light_units": "unitless"}}, DAYLIGHT_EV100)
    assert info.value.constraint == "sensing.exposure_units"
    assert "1.53e-05" in info.value.message and "black" in info.value.message
    with pytest.raises(R.RadiometryError, match="sensing.exposure_units"):
        R.exposure_units_check(None, DAYLIGHT_EV100)          # no render.json at all
    numbers = R.exposure_units_check({"sun": {"intensity": 95788.0, "light_units": "physical"}},
                                     DAYLIGHT_EV100)
    assert numbers["light_units"] == "physical" and numbers["grey_card_value"] == pytest.approx(0.183, abs=0.002)


def test_the_lens_attenuation_is_read_back_from_render_json_when_present():
    a, basis = R.read_back_lens_attenuation({"console": {R.LENS_ATTENUATION_CVAR: 0.9}})
    assert a == 0.9 and "read back" in basis
    a, basis = R.read_back_lens_attenuation(None)
    assert a == R.LENS_ATTENUATION_DEFAULT and "unverified here" in basis
    with pytest.raises(R.RadiometryError, match="sensing.radiometry"):
        R.read_back_lens_attenuation({"console": {R.LENS_ATTENUATION_CVAR: 2.0}})
    block = R.radiometry_block(DAYLIGHT_EV100, 0.5, {"console": {R.LENS_ATTENUATION_CVAR: 0.9},
                                                     "working_colour_space": "ACEScg"})
    assert block["lens_attenuation"] == 0.9 and block["working_colour_space"] == "ACEScg"
    assert block["luminance_cd_m2_per_unit"] == pytest.approx(1.2 * 0.9 * 2 ** (DAYLIGHT_EV100 - 0.5))
    assert block["calibration_status"] == "predicted" and block["grey_card_predicted"] is None
    measured = R.radiometry_block(DAYLIGHT_EV100, 0.0, calibration={"ratio": 1.01},
                                  sun_lux={"value": 95788.0, "source": "model"})
    assert measured["calibration_status"] == "measured" and measured["grey_card_measured_ratio"] == 1.01
    assert measured["grey_card_predicted"] == pytest.approx(0.183, abs=0.002)
    record = R.radiometry_record(measured, 1.0, 2.0)
    assert record.readback.agrees and record.readback.property == R.LENS_ATTENUATION_CVAR
    assert "predicted" in record.not_claimed[0]


# -- the cached tables ------------------------------------------------------------------------

def test_the_cached_tables_load_and_pin_their_digests():
    v = R.load_vlambda()
    assert len(v.wavelength_nm) == 471 and v.wavelength_nm[0] == 360 and v.wavelength_nm[-1] == 830
    assert dict(zip(v.wavelength_nm, v.values))[555] == 1.0
    assert v.sha256 == (REPO / "assets/cie/vlambda_1nm.csv.sha256").read_text(encoding="utf-8").split()[0]
    g = R.load_illuminant()
    assert len(g.wavelength_nm) == 2002 and g.wavelength_nm[0] == 280 and g.wavelength_nm[-1] == 4000
    assert g.unit == "W m^-2 nm^-1" and min(g.values) >= 0.0
    for stem in ("assets/cie/vlambda_1nm", "assets/illuminants/astm_g173_direct"):
        provenance = json.loads((REPO / f"{stem}.provenance.json").read_text(encoding="utf-8"))
        assert provenance["primary_verified"] is False           # honest: mirrors answered here
        assert "raw.githubusercontent.com" in provenance["fetched_from"]
        assert provenance["primary_source"].startswith("http")
        assert provenance["sha256"] == (REPO / f"{stem}.csv.sha256").read_text(encoding="utf-8").split()[0]


def test_the_direct_sun_s_efficacy_is_recomputed_from_the_tables_and_is_the_declared_constant():
    """683 x int(S V) / int(S) over ASTM G173-03 direct: 107.92 lm/W; the
    extraterrestrial spectrum gives 98.74 lm/W and 133 100 lx, the ceiling
    solar.py refuses above."""
    v, g = R.load_vlambda(), R.load_illuminant()
    efficacy = R.luminous_efficacy(g, v)
    assert efficacy == pytest.approx(107.92, abs=0.01)
    assert solar.DIRECT_LUMINOUS_EFFICACY_LM_PER_W == pytest.approx(efficacy, abs=0.01)
    rows = np.loadtxt(REPO / "assets/illuminants/astm_g173_direct.csv", delimiter=",", skiprows=1)
    wl, e0 = rows[:, 0], rows[:, 1]
    vl = np.interp(wl, np.asarray(v.wavelength_nm), np.asarray(v.values), left=0.0, right=0.0)
    lux0 = 683.0 * np.trapezoid(e0 * vl, wl)
    assert lux0 == pytest.approx(133100.0, abs=50.0)
    assert solar.SUN_LUX_MAX == pytest.approx(lux0, abs=50.0)


def _tables_copy(tmp_path):
    cie = tmp_path / "cie"
    cie.mkdir()
    for name in ("vlambda_1nm.csv", "vlambda_1nm.csv.sha256"):
        shutil.copy(REPO / "assets/cie" / name, cie / name)
    return cie / "vlambda_1nm.csv"


def test_an_absent_or_corrupt_table_refuses_sensing_radiometry_and_invents_nothing(tmp_path):
    path = _tables_copy(tmp_path)
    assert R.load_vlambda(path).sha256
    (path.with_name(path.name + ".sha256")).unlink()
    with pytest.raises(R.RadiometryError) as info:
        R.load_vlambda(path)
    assert info.value.constraint == "sensing.radiometry" and "sidecar" in info.value.message
    path.with_name(path.name + ".sha256").write_text("0" * 64 + "  vlambda_1nm.csv\n", encoding="utf-8")
    with pytest.raises(R.RadiometryError) as info:
        R.load_vlambda(path)
    assert info.value.constraint == "sensing.radiometry" and "digests" in info.value.message
    path.unlink()
    with pytest.raises(R.RadiometryError) as info:
        R.load_vlambda(path)
    assert info.value.constraint == "sensing.radiometry" and R.FETCH_STEP in info.value.message
    with pytest.raises(R.RadiometryError, match="sensing.radiometry"):
        R.load_illuminant("astm_g173_direct", tmp_path)         # no illuminant dir here


def test_the_band_factors_refuse_when_a_table_is_absent(monkeypatch, tmp_path):
    """The band path needs both tables; with V(lambda) pointed at nothing
    it refuses sensing.radiometry and computes no K_band."""
    monkeypatch.setattr(R, "VLAMBDA_FILE", tmp_path / "missing.csv")
    with pytest.raises(R.RadiometryError) as info:
        R.band_factors(R.load_bands())
    assert info.value.constraint == "sensing.radiometry" and R.FETCH_STEP in info.value.message
    with pytest.raises(R.RadiometryError, match="sensing.radiometry"):
        R.bands_block(R.load_bands())


# -- the band proxy --------------------------------------------------------------------------

def test_the_band_file_is_a_declared_proxy_with_identity_weights():
    table = R.load_bands()
    assert table.proxy is True and table.is_identity and table.channels == ("R", "G", "B")
    assert set(table.bands) == {"red", "green", "blue"}
    assert table.bands["green"]["window_nm"] == [490.0, 580.0]
    assert "no spectral rendering" in table.not_claimed[0]
    assert table.sha256 and R.available_bands() == ["rgb_proxy"]


def test_k_band_is_the_illuminant_s_luminous_efficiency_in_the_window_by_hand():
    """K_green = int(S V) / int(S) over 490..580 nm on the 1 nm grid, done
    here with the trapezoid rule straight from the two CSVs."""
    v = np.loadtxt(REPO / "assets/cie/vlambda_1nm.csv", delimiter=",", skiprows=1)
    g = np.loadtxt(REPO / "assets/illuminants/astm_g173_direct.csv", delimiter=",", skiprows=1)
    grid, vl = v[:, 0], v[:, 1]
    s = np.interp(grid, g[:, 0], g[:, 3])
    w = ((grid >= 490.0) & (grid <= 580.0)).astype(float)
    by_hand = np.trapezoid(s * vl * w, grid) / np.trapezoid(s * w, grid)
    factors = R.band_factors(R.load_bands())
    assert factors["green"] == pytest.approx(by_hand, rel=1e-12)
    assert factors["blue"] == pytest.approx(0.0596, abs=5e-4)
    assert factors["green"] == pytest.approx(0.7588, abs=5e-4)
    assert factors["red"] == pytest.approx(0.3412, abs=5e-4)
    block = R.bands_block(R.load_bands())
    assert block["efficacy_lm_per_w"]["green"] == pytest.approx(683.0 * by_hand, rel=1e-12)
    assert block["proxy"] is True and block["identity_weights"] is True


def test_band_radiance_divides_the_channel_luminance_by_683_k_band():
    table = R.load_bands()
    factors = R.band_factors(table)
    luminance = np.full((2, 2, 3), 1000.0)                # cd/m^2 per channel
    radiance = R.band_radiance(luminance, table, factors)
    assert radiance["green"][0, 0] == pytest.approx(1000.0 / (683.0 * factors["green"]))
    assert radiance["red"][1, 1] == pytest.approx(1000.0 / (683.0 * factors["red"]))
    with pytest.raises(R.RadiometryError, match="sensing.band"):
        R.band_radiance(luminance, table, dict(factors, red=0.0))


def test_identity_weights_reproduce_the_frame_bit_for_bit_the_null():
    table = R.load_bands()
    frame = np.random.default_rng(3).random((5, 7, 3))
    same = R.apply_band_weights(frame, table)
    assert same is frame
    record = R.bands_record(R.bands_block(table), float(np.abs(np.asarray(same) - frame).max()), frame.shape)
    assert record.null_test.ok and record.null_test.kind == "bounded" and record.null_test.with_value == 0.0
    assert record.readback.agrees
    mixed = R.BandTable(**{**table.__dict__, "weights": ((0.5, 0.5, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))})
    out = R.apply_band_weights(frame, mixed)
    assert not mixed.is_identity and np.allclose(out[..., 0], 0.5 * (frame[..., 0] + frame[..., 1]))
    assert np.array_equal(out[..., 1], frame[..., 1])


def _band_copy(tmp_path, **edits):
    data = json.loads((REPO / "assets/sensor_bands/rgb_proxy.json").read_text(encoding="utf-8"))
    for key, value in edits.items():
        data[key] = value
    directory = tmp_path / "bands"
    directory.mkdir(exist_ok=True)
    (directory / "rgb_proxy.json").write_text(json.dumps(data), encoding="utf-8")
    return directory


@pytest.mark.parametrize("edits, fragment", [
    ({"proxy": False}, "proxy"),
    ({"source": " "}, "source"),
    ({"channels": ["R", "G"]}, "three channels"),
    ({"weights": [[1, 0], [0, 1]]}, "3 x 3"),
    ({"bands": {"uv": {"channel": "B", "window_nm": [300, 400]}}}, "360-830"),
    ({"bands": {"nir": {"channel": "N", "window_nm": [700, 800]}}}, "channel"),
    ({"bands": {}}, "no bands"),
])
def test_a_malformed_band_file_refuses_sensing_band(tmp_path, edits, fragment):
    directory = _band_copy(tmp_path, **edits)
    with pytest.raises(R.RadiometryError) as info:
        R.load_bands("rgb_proxy", directory)
    assert info.value.constraint == "sensing.band" and fragment in info.value.message
    with pytest.raises(R.RadiometryError, match="sensing.band"):
        R.load_bands("nowhere", directory)


# -- the sun in lux ------------------------------------------------------------------------------

def test_the_clear_sky_sun_by_hand_at_the_zenith():
    """Bird & Hulstrom at sea level, sun overhead, the stated column
    amounts: the five transmittances multiplied by hand and by the code."""
    m = solar.kasten_air_mass(0.0)
    assert m == pytest.approx(1.0 / (1.0 + 0.15 * 93.885 ** -1.253), rel=1e-12)
    t_r = math.exp(-0.0903 * m ** 0.84 * (1.0 + m - m ** 1.01))
    xo = 0.3 * m
    t_o = 1.0 - 0.1611 * xo * (1.0 + 139.48 * xo) ** -0.3035 - 0.002715 * xo / (1.0 + 0.044 * xo + 0.0003 * xo * xo)
    t_um = math.exp(-0.0127 * m ** 0.26)
    xw = 1.5 * m
    t_w = 1.0 - 2.4959 * xw / ((1.0 + 79.034 * xw) ** 0.6828 + 6.385 * xw)
    tau = 0.2758 * 0.15 + 0.35 * 0.1
    t_a = math.exp(-(tau ** 0.873) * (1.0 + tau - tau ** 0.7088) * m ** 0.9108)
    dni = 1353.0 * 0.9662 * t_r * t_a * t_w * t_o * t_um
    sun = solar.illuminance_lux(90.0)
    assert sun.direct_normal_w_m2 == pytest.approx(dni, rel=1e-12)
    assert sun.direct_normal_w_m2 == pytest.approx(943.0, abs=0.5)
    assert sun.illuminance_lux == pytest.approx(dni * 107.92, rel=1e-12)
    assert sun.illuminance_lux == pytest.approx(101769.0, abs=1.0)
    assert sun.transmittances["rayleigh"] == pytest.approx(t_r) and sun.note == ""
    assert solar.illuminance_lux(50.0).illuminance_lux == pytest.approx(95788.0, abs=1.0)
    assert solar.illuminance_lux(50.0, altitude_m=1500.0).illuminance_lux > solar.illuminance_lux(50.0).illuminance_lux


def test_a_sun_below_the_horizon_is_zero_lux_with_its_reason_not_a_refusal():
    for elevation in (0.0, -5.0, -90.0):
        sun = solar.illuminance_lux(elevation)
        assert sun.illuminance_lux == 0.0 and "twilight" in sun.note
    assert solar.illuminance_lux(10.0).illuminance_lux < solar.illuminance_lux(30.0).illuminance_lux


@pytest.mark.parametrize("kwargs", [
    {"elevation_deg": 100.0}, {"elevation_deg": float("nan")}, {"elevation_deg": "noon"},
    {"elevation_deg": 50.0, "efficacy_lm_per_w": 0.0}, {"elevation_deg": 50.0, "pressure_hpa": -1.0},
    {"elevation_deg": 50.0, "efficacy_lm_per_w": 1e6},
])
def test_a_sun_that_cannot_be_lit_refuses_sensing_sun_lux(kwargs):
    with pytest.raises(solar.SunLuxError) as info:
        solar.illuminance_lux(**kwargs)
    assert info.value.constraint == "sensing.sun_lux"


def test_a_stated_sun_is_checked_against_the_extraterrestrial_ceiling():
    assert solar.sun_lux_problem(None) is None and solar.sun_lux_problem(95788.0) is None
    assert "exceeds" in solar.sun_lux_problem(200000.0)
    assert "positive" in solar.sun_lux_problem(-1.0) and "positive" in solar.sun_lux_problem(0.0)
    assert "number" in solar.sun_lux_problem("bright") and "number" in solar.sun_lux_problem(True)


def test_scene_sun_lux_states_its_provenance():
    stated = R.scene_sun_lux(50000.0, 30.0)
    assert stated["source"] == "user" and stated["value"] == 50000.0
    model = R.scene_sun_lux(None, 50.0, altitude_m=0.0)
    assert model["source"] == "model" and model["value"] == pytest.approx(95788.0, abs=1.0)
    assert "Bird" in model["basis"] and model["air_mass"] == pytest.approx(1.304, abs=1e-3)
    unstated = R.scene_sun_lux(None, None)
    assert unstated["value"] is None and unstated["source"] == "derived" and "8.0" in unstated["basis"]
    with pytest.raises(solar.SunLuxError, match="sensing.sun_lux"):
        R.scene_sun_lux(1e7, 50.0)


def test_every_sentence_this_item_emits_is_ascii():
    for module in (R, solar):
        assert Path(module.__file__).read_text(encoding="utf-8").isascii(), module.__file__
    assert (REPO / "assets/sensor_bands/rgb_proxy.json").read_text(encoding="utf-8").isascii()
    assert (REPO / "scripts/fetch_sensing_tables.py").read_text(encoding="utf-8").isascii()


# -- the verifier's three sensing checks: the patch text (returned to the integrator),
#    executed here against verify.py's own Check and pinned once integrated ----------------

VERIFY_SENSING_PATCH = r'''
# -- S1: the sensing checks -- the PSF on the calibration edge, the blur against
#    the flow, the grey card against the predicted chain ---------------------------

#: The checker's own e-SFR MTF50 against the manifest's predicted one, as a
#: fraction (the producer measured 0.45 % and 1.3 % on synthetic edges; 5 % is
#: the blueprint's clause).
PSF_MTF50_TOL = 0.05
#: A recorded streak against the flow's prediction: the larger of this many
#: pixels and this fraction of the prediction (the producer's own estimator
#: holds 0.25 px for streaks of 2 px and longer).
BLUR_TOL_PX = 0.25
BLUR_TOL_FRACTION = 0.10
#: The grey card's measured / predicted ratio (S4's calibration.json) must sit
#: within this of one.
GREY_CARD_TOL = 0.02
FAIL_PSF = "annotation.psf"
FAIL_BLUR = "annotation.blur"
FAIL_RADIOMETRY = "annotation.radiometry"


def _sensing_cameras(manifest, key):
    """{camera_id: sensing block} over the camera blocks whose ``sensing``
    carries a ``key`` block (the capture manifest's cameras[i].sensing)."""
    out = {}
    for block in manifest.get("cameras", []) or []:
        sensing = block.get("sensing") if isinstance(block, dict) else None
        if isinstance(sensing, dict) and isinstance(sensing.get(key), dict):
            out[str(block.get("camera_id"))] = sensing
    return out


def _sensing_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sensing_read_linear_gray(path):
    """An 8-bit sRGB PNG as linear gray in [0, 1] by the checker's own sRGB
    inverse (IEC 61966-2-1: c / 12.92 below 0.04045, ((c + 0.055) / 1.055)^2.4
    above), channels averaged; None when it cannot be read."""
    import numpy as np

    try:
        from PIL import Image

        with Image.open(path) as image:
            rgb = np.asarray(image.convert("RGB"), dtype=np.float64) / 255.0
    except (OSError, ImportError):
        return None
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return linear.mean(axis=2)


def _sensing_own_mtf50(gray, oversample=4):
    """The checker's OWN e-SFR (ISO 12233 from the definition, written apart
    from the producer's): each row's edge at the half-level crossing between
    the row's 10th and 90th percentile levels, linearly interpolated; a
    least-squares line through the crossings; every pixel's distance along
    the edge normal binned at 1 / oversample px into the edge spread
    function; the line spread function by finite difference under a
    Hamming window; the MTF by FFT; MTF50 at the first half crossing.
    None when no edge is found."""
    import numpy as np

    image = np.asarray(gray, dtype=np.float64)
    height, width = image.shape
    rows, crossings = [], []
    for y in range(height):
        row = image[y]
        lo, hi = np.percentile(row, 10), np.percentile(row, 90)
        if hi - lo <= 1e-9:
            continue
        level = 0.5 * (lo + hi)
        rising = row[-1] > row[0]
        above = row >= level if rising else row <= level
        idx = np.flatnonzero(above)
        if idx.size == 0 or idx[0] == 0:
            continue
        i = int(idx[0])
        v0, v1 = row[i - 1], row[i]
        if v1 == v0:
            continue
        crossings.append((i - 1) + (level - v0) / (v1 - v0))
        rows.append(float(y))
    if len(rows) < 3:
        return None
    slope, intercept = np.polyfit(np.asarray(rows), np.asarray(crossings), 1)
    cos_theta = 1.0 / math.sqrt(1.0 + slope * slope)
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float64)
    distance = (xs - (intercept + slope * ys)) * cos_theta
    bins = np.floor(distance * oversample).astype(int)
    bins -= bins.min()
    counts = np.bincount(bins.ravel())
    sums = np.bincount(bins.ravel(), weights=image.ravel())
    esf = np.full(len(counts), np.nan)
    esf[counts > 0] = sums[counts > 0] / counts[counts > 0]
    first = esf[counts > 0][0]
    for i in range(len(esf)):
        if np.isnan(esf[i]):
            esf[i] = esf[i - 1] if i > 0 else first
    lsf = np.diff(esf) * np.hamming(len(esf) - 1)
    spectrum = np.abs(np.fft.rfft(lsf))
    if spectrum[0] <= 0.0:
        return None
    mtf = spectrum / spectrum[0]
    freqs = np.fft.rfftfreq(len(lsf), d=1.0 / oversample)
    below = np.flatnonzero(mtf < 0.5)
    if below.size == 0:
        return float(freqs[-1])
    i = int(below[0])
    if i == 0:
        return 0.0
    return float(freqs[i - 1] + (0.5 - mtf[i - 1]) * (freqs[i] - freqs[i - 1]) / (mtf[i] - mtf[i - 1]))


def verify_psf_slanted_edge(manifest: Dict, run_dir=None) -> Check:
    """The PSF the sensor post-pass applied, measured by the checker's own
    e-SFR on the calibration frame's slanted-edge quad (render.json root
    ``calibration.slanted_edge {frame, quad_px}``, S4) and held to the
    manifest's predicted MTF50 within PSF_MTF50_TOL; the kernel sensor.json
    says it applied must be the manifest's. NOT RUN without a sensing.optics
    block, a run directory or a calibration edge; FAIL annotation.psf."""
    import numpy as np

    cameras = _sensing_cameras(manifest, "optics")
    if not cameras:
        return Check("psf_slanted_edge", NOT_RUN,
                     "no camera carries a sensing.optics block: no PSF was applied")
    if run_dir is None:
        return Check("psf_slanted_edge", NOT_RUN, "no run directory: the sensor frames are not here")
    graded, details = 0, []
    for camera, sensing in cameras.items():
        folder = Path(run_dir) / "frames" / camera
        render = _sensing_json(folder / "render.json") or {}
        calibration = render.get("calibration") if isinstance(render, dict) else None
        edge = calibration.get("slanted_edge") if isinstance(calibration, dict) else None
        if not isinstance(edge, dict) or not edge.get("frame") or not edge.get("quad_px"):
            details.append(f"{camera}: no calibration frame with a slanted-edge quad "
                           f"(render with -calibration on Windows, S4)")
            continue
        frame_name = str(edge["frame"])
        sensor_json = _sensing_json(folder / "sensor.json") or {}
        item = next((f for f in sensor_json.get("frames", []) if f.get("frame") == frame_name), None)
        if item is None or not item.get("sensor"):
            return Check("psf_slanted_edge", FAIL,
                         f"{camera}: the calibration frame {frame_name} has no sensor frame in "
                         f"sensor.json, so the PSF was never applied to the edge", failure=FAIL_PSF)
        applied = ((item.get("sensing") or {}).get("psf") or {}).get("kernel_sha256")
        expected = sensing["optics"].get("kernel_sha256")
        if applied != expected:
            return Check("psf_slanted_edge", FAIL,
                         f"{camera}: the kernel applied to {frame_name} ({str(applied)[:16]}..) is "
                         f"not the manifest's ({str(expected)[:16]}..)", failure=FAIL_PSF)
        gray = _sensing_read_linear_gray(folder / str(item["sensor"]))
        if gray is None:
            return Check("psf_slanted_edge", FAIL,
                         f"{camera}: the sensor frame {item['sensor']} cannot be read", failure=FAIL_PSF)
        quad = np.asarray(edge["quad_px"], dtype=np.float64).reshape(-1, 2)
        u0 = max(0, int(math.floor(quad[:, 0].min())))
        u1 = min(gray.shape[1], int(math.ceil(quad[:, 0].max())))
        v0 = max(0, int(math.floor(quad[:, 1].min())))
        v1 = min(gray.shape[0], int(math.ceil(quad[:, 1].max())))
        crop = gray[v0:v1, u0:u1]
        if crop.shape[0] < 8 or crop.shape[1] < 8:
            return Check("psf_slanted_edge", FAIL,
                         f"{camera}: the slanted-edge quad is {crop.shape[1]} x {crop.shape[0]} px, "
                         f"too small to measure", failure=FAIL_PSF)
        measured = _sensing_own_mtf50(crop)
        if measured is None:
            return Check("psf_slanted_edge", FAIL,
                         f"{camera}: no edge was found inside the slanted-edge quad of {frame_name}",
                         failure=FAIL_PSF)
        predicted = float(sensing["optics"]["mtf50_predicted_cyc_per_px"])
        error = abs(measured - predicted) / predicted if predicted > 0.0 else math.inf
        if error > PSF_MTF50_TOL:
            return Check("psf_slanted_edge", FAIL,
                         f"{camera}: the checker's own e-SFR reads MTF50 {measured:.4f} cycles/px on "
                         f"the calibration edge against the manifest's predicted {predicted:.4f} "
                         f"({error * 100:.1f} %, tolerance {PSF_MTF50_TOL * 100:.0f} %)",
                         failure=FAIL_PSF)
        graded += 1
        details.append(f"{camera}: MTF50 {measured:.4f} cycles/px by the checker's own e-SFR against "
                       f"{predicted:.4f} predicted ({error * 100:.1f} %)")
    if graded == 0:
        return Check("psf_slanted_edge", NOT_RUN, "; ".join(details))
    return Check("psf_slanted_edge", PASS, "; ".join(details))


def _sensing_read_flow(path, width, height):
    """frame_NNNN_flow.f32 as (h, w, 2) float64 pixels; None when the size
    is not width x height x 2 float32 values."""
    import numpy as np

    try:
        raw = np.fromfile(path, dtype="<f4")
    except OSError:
        return None
    if raw.size != width * height * 2:
        return None
    return raw.reshape(height, width, 2).astype("float64")


def verify_blur_vs_flow(manifest: Dict, run_dir=None) -> Check:
    """The streak the sensor post-pass recorded per frame (sensor.json
    ``sensing.blur.blur_px_max``) against the checker's own prediction from
    the engine's flow pass: the 95th percentile of |flow| over the frame
    (pixels since the previous captured frame) divided by the capture
    interval, times the exposure. Held within the larger of BLUR_TOL_PX and
    BLUR_TOL_FRACTION of the prediction. NOT RUN without a sensing.motion_blur
    block, a run directory, or any frame with a flow file (S2's pass); a
    frame the engine accumulated (S4) is not graded here and says so.
    FAIL annotation.blur."""
    import numpy as np

    cameras = _sensing_cameras(manifest, "motion_blur")
    if not cameras:
        return Check("blur_vs_flow", NOT_RUN,
                     "no camera carries a sensing.motion_blur block: no blur was applied")
    if run_dir is None:
        return Check("blur_vs_flow", NOT_RUN, "no run directory: the flow files are not here")
    graded, worst, notes = 0, 0.0, []
    for camera, sensing in cameras.items():
        folder = Path(run_dir) / "frames" / camera
        render = _sensing_json(folder / "render.json") or {}
        records = render.get("frame_records") if isinstance(render, dict) else None
        engine = {r.get("frame"): r for r in records if isinstance(r, dict)} if isinstance(records, list) else {}
        sensor_json = _sensing_json(folder / "sensor.json") or {}
        applied = {f.get("frame"): f for f in sensor_json.get("frames", []) if isinstance(f, dict)}
        frames = sorted((f for f in manifest.get("frames", []) if str(f.get("camera_id")) == camera),
                        key=lambda f: float(f.get("t_s", 0.0)))
        for previous, record in zip(frames, frames[1:]):
            name = Path(str(record.get("file"))).name
            flow_file = ((engine.get(name) or {}).get("labels") or {}).get("flow_f32")
            if not flow_file:
                continue
            blur = ((applied.get(name) or {}).get("sensing") or {}).get("blur")
            if not isinstance(blur, dict):
                continue
            if blur.get("applied_by") == "engine_accumulation":
                notes.append(f"{camera}/{name}: the engine accumulated k = {blur.get('k')} sub-exposures; "
                             f"graded on Windows against the accumulation (S4), not here")
                continue
            width, height = int(record["width_px"]), int(record["height_px"])
            flow = _sensing_read_flow(folder / str(flow_file), width, height)
            if flow is None:
                return Check("blur_vs_flow", FAIL,
                             f"{camera}/{name}: {flow_file} is not {width} x {height} x 2 float32 values",
                             failure=FAIL_BLUR)
            speed = np.hypot(flow[..., 0], flow[..., 1])
            finite = speed[np.isfinite(speed)]
            if finite.size == 0:
                return Check("blur_vs_flow", FAIL, f"{camera}/{name}: the flow holds no finite value",
                             failure=FAIL_BLUR)
            interval = float(record.get("t_s", 0.0)) - float(previous.get("t_s", 0.0))
            if interval <= 0.0:
                return Check("blur_vs_flow", FAIL,
                             f"{camera}/{name}: the capture interval before this frame is {interval} s",
                             failure=FAIL_BLUR)
            predicted = float(np.percentile(finite, 95)) * float(blur.get("exposure_s", 0.0)) / interval
            recorded = blur.get("blur_px_max")
            if not isinstance(recorded, (int, float)):
                return Check("blur_vs_flow", FAIL, f"{camera}/{name}: no streak length recorded",
                             failure=FAIL_BLUR)
            tolerance = max(BLUR_TOL_PX, BLUR_TOL_FRACTION * predicted)
            error = abs(float(recorded) - predicted)
            worst = max(worst, error)
            if error > tolerance:
                return Check("blur_vs_flow", FAIL,
                             f"{camera}/{name}: the recorded streak {float(recorded):.2f} px against "
                             f"{predicted:.2f} px from the flow's 95th percentile over {interval:g} s "
                             f"at {float(blur.get('exposure_s', 0.0)):g} s exposure (tolerance "
                             f"{tolerance:.2f} px)", failure=FAIL_BLUR)
            graded += 1
    if graded == 0:
        reason = ("no frame with a flow file (render with -labels -passes=velocity; the flow pass is "
                  "I6's, its keypoint check S2's)")
        if notes:
            reason = reason + "; " + "; ".join(notes)
        return Check("blur_vs_flow", NOT_RUN, reason)
    return Check("blur_vs_flow", PASS,
                 f"{graded} frame(s): the recorded streak within {worst:.3f} px of the flow's prediction "
                 f"(tolerance max({BLUR_TOL_PX} px, {BLUR_TOL_FRACTION * 100:.0f} %))"
                 + ("; " + "; ".join(notes) if notes else ""))


def verify_radiometry_grey_card(manifest: Dict, run_dir=None) -> Check:
    """The calibration chain's constant against the grey card the engine
    rendered (S4's frames/<camera>/calibration.json {predicted, measured,
    ratio}): the file's prediction must be the manifest's grey_card_predicted
    (1e-6 relative), the ratio the file's own measured / predicted (1e-6),
    within GREY_CARD_TOL of one, and the manifest's calibration_status
    'measured'. NOT RUN without a sensing.radiometry block, a run directory
    or a calibration file, and when the chain was refused
    sensing.exposure_units (the sun is not in lux). FAIL annotation.radiometry."""
    cameras = _sensing_cameras(manifest, "radiometry")
    if not cameras:
        return Check("radiometry_grey_card", NOT_RUN,
                     "no camera carries a sensing.radiometry block")
    if run_dir is None:
        return Check("radiometry_grey_card", NOT_RUN, "no run directory: no calibration file is here")
    graded, details = 0, []
    for camera, sensing in cameras.items():
        block = sensing["radiometry"]
        if block.get("calibration_status") == "refused":
            details.append(f"{camera}: the chain was refused by name -- {block.get('calibration_basis')}")
            continue
        calibration = _sensing_json(Path(run_dir) / "frames" / camera / "calibration.json")
        if calibration is None:
            details.append(f"{camera}: no calibration.json (render with -calibration on Windows, S4): "
                           f"the constant stays {block.get('calibration_status')}")
            continue
        try:
            predicted = float(calibration["predicted"])
            measured = float(calibration["measured"])
            ratio = float(calibration["ratio"])
        except (KeyError, TypeError, ValueError):
            return Check("radiometry_grey_card", FAIL,
                         f"{camera}: calibration.json lacks predicted / measured / ratio",
                         failure=FAIL_RADIOMETRY)
        own = block.get("grey_card_predicted")
        if not isinstance(own, (int, float)) or predicted <= 0.0 \
                or abs(predicted - float(own)) > 1e-6 * abs(predicted):
            return Check("radiometry_grey_card", FAIL,
                         f"{camera}: calibration.json predicts {predicted!r} for the grey card where the "
                         f"manifest's chain predicts {own!r}", failure=FAIL_RADIOMETRY)
        if abs(ratio - measured / predicted) > 1e-6 * max(1.0, abs(ratio)):
            return Check("radiometry_grey_card", FAIL,
                         f"{camera}: calibration.json's ratio {ratio:.6f} is not its own measured / "
                         f"predicted {measured / predicted:.6f}", failure=FAIL_RADIOMETRY)
        if block.get("calibration_status") != "measured":
            return Check("radiometry_grey_card", FAIL,
                         f"{camera}: a calibration file exists but the manifest's chain is "
                         f"{block.get('calibration_status')!r}, not measured", failure=FAIL_RADIOMETRY)
        if abs(ratio - 1.0) > GREY_CARD_TOL:
            return Check("radiometry_grey_card", FAIL,
                         f"{camera}: the grey card measured {ratio:.4f} of its prediction "
                         f"(tolerance {GREY_CARD_TOL * 100:.0f} %)", failure=FAIL_RADIOMETRY)
        graded += 1
        details.append(f"{camera}: grey card measured / predicted {ratio:.4f}")
    if graded == 0:
        return Check("radiometry_grey_card", NOT_RUN, "; ".join(details))
    return Check("radiometry_grey_card", PASS, "; ".join(details))
'''


def _sensing_namespace():
    from core.capture import verify

    namespace = {"Check": verify.Check, "PASS": verify.PASS, "FAIL": verify.FAIL,
                 "NOT_RUN": verify.NOT_RUN, "Path": Path, "math": math, "json": json,
                 "Dict": dict, "__file__": str(verify.__file__)}
    exec(compile(VERIFY_SENSING_PATCH, "<verify_sensing patch>", "exec"), namespace)
    return namespace


def _checks():
    """verify.py's own three checks once the patch is applied, else the
    patch text executed against verify.py's Check."""
    from core.capture import verify

    if hasattr(verify, "verify_psf_slanted_edge"):
        return (verify.verify_psf_slanted_edge, verify.verify_blur_vs_flow,
                verify.verify_radiometry_grey_card)
    ns = _sensing_namespace()
    return ns["verify_psf_slanted_edge"], ns["verify_blur_vs_flow"], ns["verify_radiometry_grey_card"]


def test_the_verifier_patch_imports_nothing_from_the_producers_and_is_pinned():
    import inspect

    from core.capture import verify

    for source in (VERIFY_SENSING_PATCH, (REPO / "core/capture/verify.py").read_text(encoding="utf-8")):
        for forbidden in ("core.capture.radiometry", "core.capture.optics", "core.capture.blur",
                          "from .radiometry", "from .optics", "from .blur", "from ..capture"):
            assert forbidden not in source
    assert VERIFY_SENSING_PATCH.isascii()
    text = (REPO / "core/capture/verify.py").read_text(encoding="utf-8")
    if hasattr(verify, "verify_psf_slanted_edge"):
        for name in ("_sensing_cameras", "_sensing_own_mtf50", "verify_psf_slanted_edge",
                     "verify_blur_vs_flow", "verify_radiometry_grey_card"):
            assert inspect.getsource(getattr(verify, name)) in VERIFY_SENSING_PATCH, name
        assert verify.PSF_MTF50_TOL == 0.05 and verify.BLUR_TOL_PX == 0.25 and verify.GREY_CARD_TOL == 0.02
        assert verify.FAIL_PSF == "annotation.psf" and verify.FAIL_BLUR == "annotation.blur"
        assert verify.FAIL_RADIOMETRY == "annotation.radiometry"
        for line in ('run("psf_slanted_edge", verify_psf_slanted_edge, manifest, run_dir)',
                     'run("blur_vs_flow", verify_blur_vs_flow, manifest, run_dir)',
                     'run("radiometry_grey_card", verify_radiometry_grey_card, manifest, run_dir)'):
            assert line in text


def _sensing_bundle(tmp_path, sigma_px: float = 1.0, streak_px: float = 4.0):
    """A synthetic bundle: one camera with the three sensing blocks, a
    calibration edge frame blurred by the manifest's own kernel and written
    as the sensor frame, a flow file whose 95th percentile predicts the
    recorded streak, and a calibration.json whose ratio is 1.01."""
    from PIL import Image

    from core.capture import optics as O
    from core.capture.profile import linear_to_srgb

    pitch = 36e-3 / 1280
    psf, meta = O.kernel(550e-9, 8.0, sigma_px * pitch, pitch)
    edge = O.slanted_edge_image(160, 120, 5.0, 0.2, 0.8)
    blurred = O.convolve(edge, psf)
    frame = np.clip(np.round(linear_to_srgb(blurred[..., None].repeat(3, axis=2)) * 255.0), 0, 255).astype(np.uint8)
    folder = tmp_path / "frames" / "c0"
    folder.mkdir(parents=True)
    Image.fromarray(frame, mode="RGB").save(folder / "frame_0000_sensor.png")
    Image.fromarray(frame, mode="RGB").save(folder / "frame_0001_sensor.png")
    exposure_s, interval_s = 0.002, 1.0
    flow = np.zeros((120, 160, 2), dtype="<f4")
    flow[..., 0] = streak_px * interval_s / exposure_s          # px per capture interval
    flow.tofile(folder / "frame_0001_flow.f32")
    (folder / "render.json").write_text(json.dumps({
        "calibration": {"slanted_edge": {"frame": "frame_0000.png", "angle_deg": 5.0,
                                         "quad_px": [[0, 0], [160, 0], [160, 120], [0, 120]]}},
        "frame_records": [{"frame": "frame_0000.png", "labels": {}},
                          {"frame": "frame_0001.png", "labels": {"flow_f32": "frame_0001_flow.f32"}}],
    }), encoding="utf-8")
    predicted_card = 0.183
    (folder / "calibration.json").write_text(json.dumps({
        "grey_card_nits": 5488.0, "predicted": predicted_card, "measured": predicted_card * 1.01,
        "ratio": 1.01}), encoding="utf-8")
    (folder / "sensor.json").write_text(json.dumps({"frames": [
        {"frame": "frame_0000.png", "sensor": "frame_0000_sensor.png",
         "sensing": {"psf": {"kernel_sha256": meta["kernel_sha256"]}, "blur": None}},
        {"frame": "frame_0001.png", "sensor": "frame_0001_sensor.png",
         "sensing": {"psf": {"kernel_sha256": meta["kernel_sha256"]},
                     "blur": {"applied_by": "python_velocity_line", "exposure_s": exposure_s,
                              "blur_px_max": streak_px}}}]}), encoding="utf-8")
    manifest = {
        "cameras": [{"camera_id": "c0", "sensing": {
            "optics": {"kernel_sha256": meta["kernel_sha256"],
                       "mtf50_predicted_cyc_per_px": meta["mtf50_predicted_cyc_per_px"]},
            "motion_blur": {"model": "velocity_line", "dt_s": 0.1},
            "radiometry": {"calibration_status": "measured", "grey_card_predicted": predicted_card,
                           "calibration_basis": "measured: calibration.json's grey-card ratio (S4)"}}}],
        "frames": [{"camera_id": "c0", "file": "frames/c0/frame_0000.png", "t_s": 0.0,
                    "width_px": 160, "height_px": 120},
                   {"camera_id": "c0", "file": "frames/c0/frame_0001.png", "t_s": interval_s,
                    "width_px": 160, "height_px": 120}],
    }
    return manifest, folder, meta


def test_the_three_checks_pass_a_clean_synthetic_bundle_and_report_not_run_on_absence(tmp_path):
    psf_check, blur_check, card_check = _checks()
    manifest, folder, meta = _sensing_bundle(tmp_path)
    check = psf_check(manifest, tmp_path)
    assert check.status == "PASS", check.detail
    assert "checker's own e-SFR" in check.detail
    check = blur_check(manifest, tmp_path)
    assert check.status == "PASS", check.detail
    check = card_check(manifest, tmp_path)
    assert check.status == "PASS" and "1.0100" in check.detail
    # Absence is NOT RUN, never a pass.
    bare = {"cameras": [{"camera_id": "c0"}], "frames": []}
    for check_fn in (psf_check, blur_check, card_check):
        assert check_fn(bare, tmp_path).status == "NOT RUN"
        assert check_fn(manifest, None).status == "NOT RUN"
    (folder / "render.json").write_text(json.dumps({"frame_records": []}), encoding="utf-8")
    assert "no calibration frame" in psf_check(manifest, tmp_path).detail
    assert psf_check(manifest, tmp_path).status == "NOT RUN"
    assert "no frame with a flow file" in blur_check(manifest, tmp_path).detail
    (folder / "calibration.json").unlink()
    check = card_check(manifest, tmp_path)
    assert check.status == "NOT RUN" and "no calibration.json" in check.detail


def test_a_wrong_psf_a_wrong_kernel_or_a_missing_sensor_frame_fails_annotation_psf(tmp_path):
    psf_check, _, _ = _checks()
    manifest, folder, meta = _sensing_bundle(tmp_path)
    bad = copy.deepcopy(manifest)
    bad["cameras"][0]["sensing"]["optics"]["mtf50_predicted_cyc_per_px"] *= 1.5
    check = psf_check(bad, tmp_path)
    assert check.status == "FAIL" and check.failure == "annotation.psf" and "e-SFR" in check.detail
    bad = copy.deepcopy(manifest)
    bad["cameras"][0]["sensing"]["optics"]["kernel_sha256"] = "0" * 64
    check = psf_check(bad, tmp_path)
    assert check.status == "FAIL" and check.failure == "annotation.psf" and "not the manifest's" in check.detail
    # The sensor frame the PSF was applied to is gone: the picture cannot be graded.
    (folder / "frame_0000_sensor.png").unlink()
    check = psf_check(manifest, tmp_path)
    assert check.status == "FAIL" and check.failure == "annotation.psf"


def test_a_streak_that_does_not_match_the_flow_fails_annotation_blur(tmp_path):
    _, blur_check, _ = _checks()
    manifest, folder, meta = _sensing_bundle(tmp_path, streak_px=4.0)
    sensor = json.loads((folder / "sensor.json").read_text(encoding="utf-8"))
    sensor["frames"][1]["sensing"]["blur"]["blur_px_max"] = 6.0          # the flow says 4
    (folder / "sensor.json").write_text(json.dumps(sensor), encoding="utf-8")
    check = blur_check(manifest, tmp_path)
    assert check.status == "FAIL" and check.failure == "annotation.blur" and "6.00 px" in check.detail
    sensor["frames"][1]["sensing"]["blur"] = {"applied_by": "engine_accumulation", "k": 4}
    (folder / "sensor.json").write_text(json.dumps(sensor), encoding="utf-8")
    check = blur_check(manifest, tmp_path)
    assert check.status == "NOT RUN" and "accumulated" in check.detail
    # A truncated flow file is a bundle defect, named.
    sensor["frames"][1]["sensing"]["blur"] = {"applied_by": "python_velocity_line", "exposure_s": 0.002,
                                              "blur_px_max": 4.0}
    (folder / "sensor.json").write_text(json.dumps(sensor), encoding="utf-8")
    (folder / "frame_0001_flow.f32").write_bytes((folder / "frame_0001_flow.f32").read_bytes()[:-8])
    check = blur_check(manifest, tmp_path)
    assert check.status == "FAIL" and check.failure == "annotation.blur" and "float32" in check.detail


def test_a_grey_card_off_by_more_than_two_percent_or_a_stale_status_fails_annotation_radiometry(tmp_path):
    _, _, card_check = _checks()
    manifest, folder, meta = _sensing_bundle(tmp_path)
    calibration = json.loads((folder / "calibration.json").read_text(encoding="utf-8"))
    off = dict(calibration, measured=calibration["predicted"] * 1.1, ratio=1.1)
    (folder / "calibration.json").write_text(json.dumps(off), encoding="utf-8")
    check = card_check(manifest, tmp_path)
    assert check.status == "FAIL" and check.failure == "annotation.radiometry" and "1.1000" in check.detail
    (folder / "calibration.json").write_text(json.dumps(calibration), encoding="utf-8")
    stale = copy.deepcopy(manifest)
    stale["cameras"][0]["sensing"]["radiometry"]["calibration_status"] = "predicted"
    check = card_check(stale, tmp_path)
    assert check.status == "FAIL" and check.failure == "annotation.radiometry" and "not measured" in check.detail
    other = copy.deepcopy(manifest)
    other["cameras"][0]["sensing"]["radiometry"]["grey_card_predicted"] = 0.5
    check = card_check(other, tmp_path)
    assert check.status == "FAIL" and "predicts" in check.detail
    lying = dict(calibration, ratio=1.0)                       # not its own measured / predicted
    (folder / "calibration.json").write_text(json.dumps(lying), encoding="utf-8")
    assert card_check(manifest, tmp_path).status == "FAIL"
    refused = copy.deepcopy(manifest)
    refused["cameras"][0]["sensing"]["radiometry"]["calibration_status"] = "refused"
    refused["cameras"][0]["sensing"]["radiometry"]["calibration_basis"] = "refused sensing.exposure_units: the sun is 8.0"
    check = card_check(refused, tmp_path)
    assert check.status == "NOT RUN" and "sensing.exposure_units" in check.detail
