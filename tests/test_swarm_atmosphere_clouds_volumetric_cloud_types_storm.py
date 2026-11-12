"""atmosphere_clouds.volumetric_cloud_types.storm: what is checkable on the Mac.

Radiometric arithmetic, determinism, file layout and agreement with the storm
exposure lane. No test here stands in for a rendered frame (the pixel gate
runs on Windows); the synthetic images below only exercise the gate's code.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import struct
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / "swarm/lanes/atmosphere_clouds/volumetric_cloud_types/storm"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"swarm_cloud_types_storm_{name}", LANE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load("generate")
measure = _load("measure_frame")
FILES = gen.build()
PLAN = json.loads(FILES["storm_cloud_types.json"])


def test_bake_is_deterministic_and_pinned():
    prov = json.loads((LANE / "PROVENANCE.json").read_text())
    pinned = {g["path"]: g["sha256"] for g in prov["generated"]}
    assert set(pinned) == {f"baked/{n}" for n in FILES}
    again = gen.build()
    for name, data in FILES.items():
        digest = hashlib.sha256(data).hexdigest()
        assert hashlib.sha256(again[name]).hexdigest() == digest
        assert pinned[f"baked/{name}"] == digest, name
        assert (LANE / "baked" / name).read_bytes() == data, name
    assert prov["fetched_assets"] == []
    assert all(s.get("licence") for s in prov["sources"])


def test_phase_function_is_normalised_and_forward():
    fit = gen.mie_fit(20.0)
    # substitution mu = 1 - t^4 resolves the forward peak of g = 0.995
    t = np.linspace(0.0, 2.0 ** 0.25, 400001)
    mu = 1.0 - t ** 4
    for p in (gen.phase_mie(fit, mu), gen.phase_draine(fit["g_d"], fit["alpha"], mu)):
        y = 2.0 * math.pi * p * 4.0 * t ** 3
        assert float(((y[1:] + y[:-1]) / 2 * np.diff(t)).sum()) == pytest.approx(1.0, abs=2e-3)
    g = gen.mie_mean_cosine(fit)
    y = 2.0 * math.pi * gen.phase_mie(fit, mu) * mu * 4.0 * t ** 3
    assert float(((y[1:] + y[:-1]) / 2 * np.diff(t)).sum()) == pytest.approx(g, abs=2e-3)
    assert 0.84 < g < 0.90  # water-droplet asymmetry in the visible
    with pytest.raises(ValueError):
        gen.mie_fit(2.0)


def test_two_stream_and_calibration():
    g = PLAN["phase"]["mean_cosine"]
    tau = np.array([0.0, 1.0, 10.0, 100.0, 1000.0])
    t = gen.two_stream_transmittance(tau, g)
    assert t[0] == 1.0 and np.all(np.diff(t) < 0) and np.all(t > 0)
    scale = PLAN["extinction_scale"]
    assert scale["area_mean_transmittance"] == pytest.approx(gen.DECK_FRACTION, abs=1e-4)
    assert scale["core_transmittance_min"] < 0.5 * gen.DECK_FRACTION < scale["edge_transmittance_max"]
    types = PLAN["cloud_types"]
    assert gen.extinction_per_m(1.0, 10.0) == pytest.approx(0.15)
    assert types["cumulonimbus_core"]["optical_depth_physical"] > types["nimbostratus_deck"]["optical_depth_physical"]


def test_radiometry_against_skyatmosphere_reference():
    r = PLAN["radiometry"]
    assert abs(r["budget_residual_fraction"]) < 1e-3  # dome + patch = reference x deck fraction
    # no direction under the deck outshines a Lambert surface lit by the clear sky
    assert r["panorama_max_cd_m2"] < r["lambert_ceiling_cd_m2"]
    assert r["panorama_min_cd_m2"] > 0.0
    # the darkest sky is toward the core (column 0), not behind the observer
    pano = _read_hdr(FILES["storm_underdeck_256x64.hdr"])
    assert gen.cosine_mean(pano) == pytest.approx(1.0, abs=0.01)  # 8-bit mantissa
    low = pano[40:60]
    assert low[:, :8].mean() < low[:, 124:132].mean()


def test_agrees_with_the_storm_exposure_lane():
    path = ROOT / "swarm/lanes/lighting_exposure/physical_light_units/storm/baked/storm_plu.json"
    if not path.exists():
        pytest.skip("exposure lane not present")
    plu = json.loads(path.read_text())
    sp = PLAN["shared_params"]
    assert plu["ambient"]["clear_sky_horizontal_lux"] == gen.CLEAR_SKY_HORIZONTAL_LUX
    assert plu["ambient"]["deck_fraction"] == sp["deck_illuminance_fraction"]
    for key in ("exposure_ev", "sun_elevation_deg", "skylight_intensity_cd_m2", "ground_albedo",
                "assumed_visibility_m", "sky_colour_temperature_k"):
        assert plu["shared_params"][key] == sp[key], key
    assert sp["haze_density_per_m"] ==pytest.approx(3.912 / 3000.0, abs=1e-6)


def test_octaves_keep_the_interior_from_going_black():
    one, three = gen.octave_transmission(20.0, 1), gen.octave_transmission(20.0, 3)
    assert one < 1e-8 and three > 1e-3


def test_texture_layouts():
    for name, (w, h, bpp) in {"storm_weather_128.tga": (128, 128, 24), "storm_noise_64_atlas.tga": (512, 512, 8),
                              "storm_noise_32_atlas.tga": (256, 128, 8)}.items():
        data = FILES[name]
        head = struct.unpack("<BBBHHBHHHHBB", data[:18])
        assert (head[8], head[9], head[10], head[11]) == (w, h, bpp, 0x20), name
        assert len(data) == 18 + w * h * bpp // 8
    noise = np.frombuffer(FILES["storm_noise_64_atlas.tga"][18:], dtype=np.uint8)
    assert noise.min() < 40 and noise.max() > 215
    weather = np.frombuffer(FILES["storm_weather_128.tga"][18:], dtype=np.uint8).reshape(128, 128, 3)
    assert weather[64, 64, 0] > weather[4, 4, 0]      # B (rain) at the core, BGR order
    assert weather[:, :, 2].max() == 255              # R: optical depth normalised to its max


def test_tiers_are_estimates_and_tier0_marches_nothing():
    tiers = PLAN["tiers"]
    assert [t["tier"] for t in tiers] == [0, 1, 2, 3]
    assert tiers[0]["volumetric_cloud_component"] is False
    vram = [t["est_vram_mb"] for t in tiers]
    assert vram == sorted(vram) and vram[-1] < 491
    assert "UNMEASURED" in PLAN["status"] and "none is known to hold" in PLAN["tiers_note"]


def test_gate_arithmetic_on_synthetic_images():
    Image = pytest.importorskip("PIL.Image")
    gate = PLAN["gate"]
    assert gate["expected_sky_over_ground_stops"] == pytest.approx(
        math.log2(gate["sky_band_median_relative"] / gen.GROUND_ALBEDO_WET), abs=2e-3)

    def frame(sky: int, ground: int, black_rows: int = 0):
        img = Image.new("L", (64, 100), ground)
        img.paste(sky, (0, 0, 64, 50))
        if black_rows:
            img.paste(0, (0, 0, 64, black_rows))
        return img

    def encode(lin: float) -> int:
        return round(255 * (1.055 * lin ** (1 / 2.4) - 0.055))

    good = measure.measure(frame(encode(0.5), encode(0.5 * 2 ** -gate["expected_sky_over_ground_stops"])), 0.5, gate)
    flat = measure.measure(frame(128, 128), 0.5, gate)
    crushed = measure.measure(frame(encode(0.5), encode(0.04), black_rows=10), 0.5, gate)
    assert good["under_deck_error_ev"] < 0.1 and good["black_fraction"] == 0.0
    assert measure.verdict(good, flat, gate)["pass"] is True
    assert measure.verdict(flat, good, gate)["pass"] is False
    assert crushed["black_fraction"] > gate["max_black_fraction"]
    assert measure.verdict(crushed, None, gate)["checks"]["black_fraction"] is False
    assert measure.main([]) == 2


def _read_hdr(data: bytes):
    head, _, body = data.partition(b"\n\n")
    dims, _, pixels = body.partition(b"\n")
    assert head.startswith(b"#?RADIANCE") and dims == b"-Y 64 +X 256"
    px = np.frombuffer(pixels, dtype=np.uint8).reshape(64, 256, 4)
    return (px[:, :, 0].astype(np.float64) + 0.5) / 256.0 * np.exp2(px[:, :, 3].astype(np.float64) - 128.0)
