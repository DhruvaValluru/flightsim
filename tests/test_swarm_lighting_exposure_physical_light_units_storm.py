"""lighting_exposure.physical_light_units.storm: what is checkable on the Mac.

Arithmetic, determinism and agreement with the project's own storm look. No
test here stands in for a rendered frame (the pixel gate runs on Windows).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path

import pytest

LANE = Path(__file__).resolve().parents[1] / "swarm/lanes/lighting_exposure/physical_light_units/storm"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"swarm_plu_storm_{name}", LANE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load("generate")
measure = _load("measure_frame")
PLAN = gen.build()


def test_exposure_within_gate_of_the_calibrated_look():
    e = PLAN["exposure"]
    assert e["ev100"] == PLAN["calibrated_look"]["ev100"] == 12.5
    assert abs(e["incident_minus_look_ev"]) <= gen.GATE_EV
    assert abs(e["reflected_minus_look_ev"]) <= gen.GATE_EV


def test_lights_sum_to_the_metered_illuminance():
    total = PLAN["directional"]["ground_horizontal_lux"] + PLAN["sky"]["horizontal_lux"]
    assert total == pytest.approx(PLAN["ambient"]["horizontal_lux"], abs=0.2)
    d = PLAN["directional"]
    assert d["ground_normal_lux"] * math.sin(math.radians(d["elevation_deg"])) == pytest.approx(
        d["ground_horizontal_lux"], rel=1e-3)
    assert d["light_lux_outer_space"] * d["atmosphere_transmittance_model"] == pytest.approx(
        d["ground_normal_lux"], rel=1e-3)
    assert d["cast_shadows"] is False


def test_exposure_does_not_depend_on_the_directional_share(monkeypatch):
    before = PLAN["exposure"]["incident_meter_ev100"]
    monkeypatch.setattr(gen, "DIRECTIONAL_SHARE", 0.4)
    assert gen.build()["exposure"]["incident_meter_ev100"] == before


def test_cie_overcast_sky_closed_form():
    lz = gen.cie_overcast_zenith_luminance(1000.0)
    n = 4000
    acc = 0.0
    for i in range(n):
        g = (i + 0.5) * (math.pi / 2) / n
        acc += lz * (1 + 2 * math.sin(g)) / 3 * math.sin(g) * math.cos(g) * (math.pi / 2 / n) * 2 * math.pi
    assert acc == pytest.approx(1000.0, rel=1e-4)
    assert PLAN["sky"]["horizon_luminance_cd_m2"] * 3 == pytest.approx(
        PLAN["sky"]["zenith_luminance_cd_m2"], rel=1e-3)


def test_baked_hdr_is_normalised_and_pinned():
    prov = json.loads((LANE / "PROVENANCE.json").read_text())
    for row in prov["generated"]:
        assert hashlib.sha256((LANE / row["path"]).read_bytes()).hexdigest() == row["sha256"], row["path"]
    data = (LANE / "baked" / gen.HDR_NAME).read_bytes()
    assert data == gen.hdr_bytes(PLAN["sky"]["lower_hemisphere_relative"])  # deterministic
    w, h, rows = gen.read_hdr_rows(data)
    assert (w, h) == (256, 128)
    # SkyLight intensity x this integral = horizontal lux
    assert gen.horizontal_integral(rows) == pytest.approx(math.pi, rel=0.01)
    assert PLAN["sky"]["skylight_intensity_cd_m2"] * math.pi == pytest.approx(
        PLAN["sky"]["horizontal_lux"], rel=1e-3)
    assert rows[0] > rows[h // 2 - 1] > rows[-1] > 0.0  # zenith > horizon > ground


def test_baked_json_matches_the_generator():
    on_disk = json.loads((LANE / "baked" / gen.PLU_NAME).read_text())
    on_disk.pop("baked")
    assert on_disk == json.loads(json.dumps(PLAN))
    assert "UNMEASURED" in on_disk["status"]


def test_tiers_and_fog_ceiling():
    tiers = PLAN["tiers"]
    assert [t["tier"] for t in tiers] == [0, 1, 2, 3]
    assert all(a["est_vram_mb"] < b["est_vram_mb"] for a, b in zip(tiers, tiers[1:]))
    assert tiers[0]["est_vram_mb"] < 1.0 and not any(t["realtime_capture"] for t in tiers)
    assert PLAN["shared_params"]["fog_inscatter_ceiling_cd_m2"] == PLAN["sky"]["horizon_luminance_cd_m2"]
    assert PLAN["exposure"]["scene_linear_before_tonemap"]["sky_zenith"] < 1.0  # the sky does not clip


def test_lightning_inverse_square():
    rows = PLAN["lightning"]["by_distance"]
    cd = PLAN["lightning"]["peak_intensity_cd"]
    for r in rows:
        assert r["peak_lux_facing"] == pytest.approx(cd / r["distance_m"] ** 2, rel=1e-3)


def test_project_constants_have_not_moved():
    pytest.importorskip("numpy")  # core.sky.plan needs it
    from core.scene import beauty_look as b
    from core.scene import hero_lighting as h
    from core.scene import lightning
    from core.scenario.solar import illuminance_lux

    p = gen.PROJECT
    intent = h.INTENTS["storm_soft_sheen"] if hasattr(h, "INTENTS") else None
    if intent is not None:
        assert p["sun_elevation_deg"] in tuple(vars(intent).values())
    el = p["sun_elevation_deg"]
    assert b.clear_sky_horizontal_lux(el) == pytest.approx(p["clear_horizontal_lux"], rel=1e-6)
    assert illuminance_lux(el).illuminance_lux == pytest.approx(p["clear_direct_normal_lux"], rel=1e-6)
    assert b.SUN_OUTER_SPACE_LUX == p["sun_outer_space_lux"]
    assert h.OVERCAST_ILLUMINANCE_FRACTION == p["deck_fraction"]
    assert b.ev100_band(el)[0] == p["ev100_band"]
    light = b.scene_light(el, world_preset="storm", deck=True)
    assert b.exposure_target(p["ev100_band"], light, b.GRADES["storm"]["ev100_offset"], 0.0) == p["ev100_look"]
    assert light["horizontal_lux"] == pytest.approx(PLAN["ambient"]["horizontal_lux"], abs=0.2)
    assert b.METER_CALIBRATION_C == p["meter_c"]
    assert b.meter_ev100(light["horizontal_lux"]) == pytest.approx(
        PLAN["exposure"]["incident_meter_ev100"], abs=2e-3)
    assert b.EXPOSURE_METER_TARGET_P90["storm"] == p["meter_target_p90_srgb"] == measure.TARGET_P90
    assert b.GRADES["storm"]["WhiteTemp"] == p["grade_white_temp_k"]
    assert lightning.FIRST_STROKE_PEAK_W_PER_M == p["lightning_peak_w_per_m"]
    assert lightning.LUMINOUS_EFFICACY_LM_PER_W == p["lightning_lm_per_w"]


def test_pixel_gate_arithmetic():
    def hist(level: int, clipped: int = 0):
        out = [0] * 256
        out[level] = 1000 - clipped
        out[255] = clipped
        return out

    on = measure.frame_stats(hist(102))            # 102/255 = 0.40
    assert on["ev_error"] == pytest.approx(0.0, abs=0.01)
    assert measure.verdict(on)["pass"]
    dark = measure.frame_stats(hist(70))
    assert dark["ev_error"] < -measure.GATE_EV and not measure.verdict(dark)["pass"]
    near = measure.frame_stats(hist(110))
    assert abs(near["ev_error"]) <= measure.GATE_EV
    assert measure.verdict(near, reference=dark)["pass"]
    assert not measure.verdict(near, reference=on)["pass"]  # worse than the reference
    assert not measure.verdict(measure.frame_stats(hist(102, clipped=50)))["pass"]
    assert measure.GATE_EV == gen.GATE_EV
