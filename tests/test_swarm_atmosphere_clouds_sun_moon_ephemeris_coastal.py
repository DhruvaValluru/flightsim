"""Source-level checks for swarm lane atmosphere_clouds.sun_moon_ephemeris.coastal.

These run on the Mac and check the bake's maths and files. They never stand in
for a Windows render or the pixel gate (CLAUDE.md, 2026-11-12).
"""
import hashlib
import importlib.util
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm/lanes/atmosphere_clouds/sun_moon_ephemeris/coastal"
OUT = LANE / "out"

_spec = importlib.util.spec_from_file_location("swarm_ephemeris_coastal_bake", LANE / "bake_ephemeris.py")
bake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bake)

DOC = json.loads((OUT / "ephemeris_coastal.json").read_text())
PROV = json.loads((LANE / "PROVENANCE.json").read_text())


def test_zenith_optical_depth_matches_the_closed_form():
    a = bake.ATMOS
    top = a["atmosphere_height_km"]
    ray = a["rayleigh_scale_height_km"] * (1 - math.exp(-top / a["rayleigh_scale_height_km"]))
    mie = a["mie_scale_height_km"] * (1 - math.exp(-top / a["mie_scale_height_km"]))
    ozo = a["ozone_tent_half_width_km"]                       # area of the tent
    tau = (np.array(a["rayleigh_scattering_per_km"]) * ray
           + (a["mie_scattering_per_km"] + a["mie_absorption_per_km"]) * mie
           + np.array(a["ozone_absorption_per_km"]) * ozo)
    assert bake.transmittance(90.0) == pytest.approx(np.exp(-tau), rel=1e-4)


def test_atmosphere_matches_what_the_bridge_sets():
    cpp = (REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimVisualScene.cpp").read_text()
    assert "BottomRadius = 6360.0f" in cpp and "AtmosphereHeight = 60.0f" in cpp
    assert "SceneMieScatteringDefaultPerKm = 0.003996" in cpp
    assert "SceneMieAbsorptionDefaultPerKm = 0.000444" in cpp
    assert bake.ATMOS["bottom_radius_km"] == 6360.0 and bake.ATMOS["atmosphere_height_km"] == 60.0
    assert bake.ATMOS["mie_scattering_per_km"] == 0.003996 and bake.ATMOS["mie_absorption_per_km"] == 0.000444


def test_transmittance_reddens_and_dims_toward_the_horizon():
    el = np.array([0.0, 2, 5, 12, 30, 60, 90])
    t = bake.transmittance(el)
    assert (np.diff(t, axis=0) > 0).all()                      # brighter as the sun climbs
    assert (t[:, 0] > t[:, 1]).all() and (t[:, 1] > t[:, 2]).all()
    assert (np.diff(t[:, 2] / t[:, 0]) > 0).all()              # and bluer
    assert (bake.transmittance(-5.0) == 0).all()               # the ground is in the way
    assert (bake.transmittance(-1.0, 3.0) > 0).all()           # but not from 3 km up


def test_thinner_air_aloft_and_converged_integral():
    assert (bake.transmittance(12.0, 3.0) > bake.transmittance(12.0, 0.0)).all()
    assert bake.transmittance(3.0, steps=4096) == pytest.approx(bake.transmittance(3.0), rel=2e-4)
    assert (bake.transmittance(12.0, mie_scale=10.0) < bake.transmittance(12.0)).all()


def test_key_instant_is_the_low_sun_over_the_water():
    k = DOC["key_instant"]
    assert k["sun"]["elevation_deg"] == pytest.approx(bake.KEY_SUN_ELEVATION_DEG, abs=0.01)
    assert 180 < k["sun"]["azimuth_deg"] < 360                 # evening: west
    when = datetime.strptime(k["utc"], "%Y-%m-%dT%H:%M:%S%z")
    sun = bake.astro.sun_position(when, DOC["site"]["lat_deg"], DOC["site"]["lon_deg"])
    assert sun.elevation_deg == pytest.approx(k["sun"]["elevation_deg"], abs=1e-3)
    assert sun.azimuth_deg == pytest.approx(k["sun"]["azimuth_deg"], abs=1e-3)
    # independent of core/sky: the scenario module's own Meeus sun (geometric)
    doy = when.timetuple().tm_yday
    hours = when.hour + when.minute / 60 + when.second / 3600
    other = bake.solar.solar_position(DOC["site"]["lat_deg"], DOC["site"]["lon_deg"], when.year, doy, hours)
    assert other.azimuth_deg == pytest.approx(k["sun"]["azimuth_deg"], abs=0.1)
    assert other.elevation_deg == pytest.approx(k["sun"]["elevation_deg"], abs=0.15)   # refraction ~0.07


def test_track_descends_and_events_are_ordered():
    els = [r["sun"]["elevation_deg"] for r in DOC["track"]]
    assert all(b < a for a, b in zip(els, els[1:]))
    e = DOC["events_utc"]
    assert k_lt(DOC["key_instant"]["utc"], e["sunset_apparent_upper_limb"])
    assert k_lt(e["sunset_apparent_upper_limb"], e["civil_dusk"])
    assert k_lt(e["civil_dusk"], e["nautical_dusk"]) and k_lt(e["nautical_dusk"], e["astronomical_dusk"])
    for r in DOC["track"]:
        if r["sun"]["elevation_deg"] < -1.5:
            assert r["sun"]["ground_normal_lux_skyatmosphere"] == 0


def k_lt(a, b):
    return a < b            # ISO-8601 UTC strings sort as times


def test_lux_is_bounded_and_conserved():
    for r in DOC["track"]:
        s, m = r["sun"], r["moon"]
        assert 0.96 * bake.solar.SUN_LUX_MAX < s["toa_lux"] < 1.04 * bake.solar.SUN_LUX_MAX
        assert s["ground_normal_lux_skyatmosphere"] <= s["toa_lux"]
        assert s["ground_normal_lux_skyatmosphere"] == pytest.approx(
            s["toa_lux"] * bake.luminance(s["transmittance_rgb"]), rel=1e-3, abs=0.1)
        assert 0 <= m["ground_normal_lux_skyatmosphere"] <= m["toa_lux"] <= 0.4
        assert 0 <= m["illuminated_fraction"] <= 1
    # the default atmosphere is clearer than Bird & Hulstrom's (no water vapour), never the reverse by much
    k = DOC["key_instant"]["sun"]
    assert 0.5 < k["ground_normal_lux_bird_hulstrom"] / k["ground_normal_lux_skyatmosphere"] < 1.1


def test_table_and_lookup_agree_with_the_integral():
    t = DOC["transmittance_table"]
    assert bake.lookup(t, 12.0, 0.0) == pytest.approx(bake.transmittance(12.0), abs=2e-5)
    assert bake.lookup(t, 13.5, 1.5) == pytest.approx(bake.transmittance(13.5, 1.5), abs=0.01)
    assert bake.lookup(t, 200.0, 99.0) == pytest.approx(bake.transmittance(90.0, 12.0), abs=2e-5)   # clamped


def test_lut_png_decodes_to_the_integral():
    img = np.asarray(Image.open(OUT / "T_SunMoonTransmittance_64x16.png").convert("RGB"), dtype=float) / 255.0
    assert img.shape == (bake.LUT_H, bake.LUT_W, 3)
    for i, j in ((20, 0), (40, 5), (63, 15)):
        u, v = (i + 0.5) / bake.LUT_W, (j + 0.5) / bake.LUT_H
        want = bake.transmittance(bake.LUT_ELEV_MIN + bake.LUT_ELEV_SPAN * u * u, v * bake.LUT_ALT_MAX_KM)
        assert img[j, i] ** 2 == pytest.approx(want, abs=0.01)


def test_gate_metric_passes_the_reference_and_fails_an_untinted_sun():
    ref = DOC["gate_reference"]
    lo, hi = np.array(ref["t_low_rgb"]), np.array(ref["t_high_rgb"])
    s12, s60 = math.sin(math.radians(12)), math.sin(math.radians(60))
    good = bake.gate_errors(0.3 * lo * s12, 0.3 * hi * s60, ref)       # albedo and exposure cancel
    assert max(good.values()) < 1e-3
    flat = bake.gate_errors(hi * s12, hi * s60, ref)                   # zenith-like tint at 12 deg
    assert max(flat["r_over_g_stops"], flat["b_over_g_stops"]) > 3 * bake.GATE_CHROMA_STOPS


def test_measure_reads_frames(tmp_path, capsys):
    ref = DOC["gate_reference"]
    lo, hi = np.array(ref["t_low_rgb"]), np.array(ref["t_high_rgb"])

    def frame(name, direct):
        a = np.full((40, 80, 3), 0.05)                                  # shadow: fill only
        a[:, :40] += direct                                            # left half sunlit
        enc = np.where(a <= 0.0031308, a * 12.92, 1.055 * a ** (1 / 2.4) - 0.055)
        Image.fromarray(np.round(enc * 255).astype(np.uint8)).save(tmp_path / name)
        return str(tmp_path / name)

    s12, s60 = math.sin(math.radians(12)), math.sin(math.radians(60))
    args = ["measure", "--lit-rect", "5,5,30,30", "--shadow-rect", "45,5,30,30",
            "--low", frame("lo.png", 0.8 * lo * s12), "--high", frame("hi.png", 0.8 * hi * s60),
            "--ref-low", frame("rlo.png", 0.8 * hi * s12), "--ref-high", frame("rhi.png", 0.8 * hi * s60)]
    assert bake.main(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pass"] and out["candidate"]["chroma_stops"] < 0.05 < out["reference"]["chroma_stops"]
    swapped = ["measure", "--lit-rect", "5,5,30,30", "--shadow-rect", "45,5,30,30",
               "--low", args[args.index("--ref-low") + 1], "--high", args[args.index("--ref-high") + 1]]
    assert bake.main(swapped) == 1


def test_provenance_hashes_and_honesty():
    assert PROV["fetched_assets"] == [] and "UNMEASURED" in PROV["status"]
    for g in PROV["generated"]:
        assert hashlib.sha256((LANE / g["path"]).read_bytes()).hexdigest() == g["sha256"]
    assert all(s.get("licence") for s in PROV["sources"])
    assert DOC["measured"] is False
    assert [t["tier"] for t in DOC["tiers"]] == [0, 1, 2, 3] and DOC["tiers"][0]["est_vram_mb"] == 0
    text = (LANE / "INTEGRATION.md").read_text()
    assert "UNMEASURED" in text and "render_ue_scenario.ps1" in text


def test_bake_is_deterministic(tmp_path, monkeypatch):
    doc = bake.build(bake.SITE["lat_deg"], bake.SITE["lon_deg"], bake.DATE, bake.SITE["name"], bake.SITE["source"])
    assert json.dumps(doc, indent=1, sort_keys=True) + "\n" == (OUT / "ephemeris_coastal.json").read_text()
