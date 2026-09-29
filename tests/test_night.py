"""W3, night: the moon by Meeus ch. 47/48 pinned against the worked
examples, its K&S 1991 illuminance (monotone in phase, measured), the
night flag at -6 deg, the starfield from a sha256-checked catalogue or a
seeded procedural field recorded as such, the scene.night spec field
(absent-canonical, refused by name), the card's look.night block, the
scene.world record with both null kinds, and the verifier's
night_exposure check (PASS, FAIL by name, NOT RUN)."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.scene import night as n

REPO = Path(__file__).resolve().parents[1]
FULL_MOON = datetime(2024, 1, 25, 23, 0, tzinfo=timezone.utc)     # full moon 17:54 UTC
NEW_MOON = datetime(2024, 1, 11, 23, 0, tzinfo=timezone.utc)      # new moon 11:57 UTC
ZERMATT = (46.0, 7.7)


# -- Meeus, pinned against the worked examples ---------------------------------------

def test_meeus_example_47a_geocentric_and_apparent_moon():
    """1992 April 12, 0h TD (JDE 2448724.5): the three sums to the unit,
    lambda 133.162655, beta -3.229126, Delta 368409.7 km, pi 0.991990,
    apparent lambda 133.167265 with the nutation term, alpha 134.688470,
    delta 13.768368 (Meeus p. 342-343)."""
    moon = n.moon_geocentric(2448724.5)
    assert round(moon.sigma_l) == -1127527
    assert round(moon.sigma_b) == -3229126
    assert round(moon.sigma_r) == -16590875
    assert moon.longitude_deg == pytest.approx(133.162655, abs=2e-6)
    assert moon.latitude_deg == pytest.approx(-3.229126, abs=2e-6)
    assert moon.distance_km == pytest.approx(368409.7, abs=0.05)
    assert moon.parallax_deg == pytest.approx(0.991990, abs=2e-6)
    # The blueprint's separate pin: the apparent longitude WITH nutation.
    assert moon.nutation_longitude_deg == pytest.approx(0.004610, abs=5e-6)
    assert moon.apparent_longitude_deg == pytest.approx(133.167265, abs=5e-6)
    assert round(moon.apparent_longitude_deg, 4) == 133.1673
    assert moon.obliquity_deg == pytest.approx(23.440636, abs=5e-6)
    assert moon.right_ascension_deg == pytest.approx(134.688470, abs=1e-5)
    assert moon.declination_deg == pytest.approx(13.768368, abs=1e-5)


def test_meeus_nutation_sidereal_time_and_horizontal_examples():
    dpsi, deps, _eps = n.nutation(2446895.5)                  # example 22.a
    assert dpsi * 3600.0 == pytest.approx(-3.788, abs=0.01)
    assert deps * 3600.0 == pytest.approx(9.443, abs=0.01)
    assert n.mean_sidereal_deg(2446895.5) == pytest.approx(197.693195, abs=2e-6)       # 12.a
    assert n.apparent_sidereal_deg(2446895.5) == pytest.approx(197.692229, abs=1e-5)
    assert n.mean_sidereal_deg(2446896.30625) == pytest.approx(128.7378734, abs=2e-6)  # 12.b
    azimuth, altitude = n.horizontal(64.352133, -6.719892, 38.921389)                   # 13.b
    assert azimuth == pytest.approx(68.0337, abs=1e-4)
    assert altitude == pytest.approx(15.1249, abs=1e-4)
    longitude, distance = n.sun_ecliptic(2448908.5)                                     # 25.a
    assert longitude == pytest.approx(199.90895, abs=1e-4)
    assert distance == pytest.approx(0.99766, abs=1e-5)


def test_meeus_example_48a_phase():
    k, i, psi = n.moon_phase(2448724.5)
    assert k == pytest.approx(0.6786, abs=2e-4)
    assert i == pytest.approx(69.0756, abs=0.02)
    assert psi == pytest.approx(110.7929, abs=0.02)


def test_the_moon_on_the_local_sky_at_a_full_and_a_new_moon():
    full = n.moon_at(*ZERMATT, FULL_MOON)
    assert full.illuminated_fraction > 0.99 and full.elevation_deg > 50.0
    assert 0.05 <= full.illuminance_lux <= 0.3                  # Kyba, Mohar & Posch 2017
    new = n.moon_at(*ZERMATT, NEW_MOON)
    assert new.illuminated_fraction < 0.01
    assert new.elevation_deg < 0.0 and new.illuminance_lux == 0.0


# -- K&S 1991 ---------------------------------------------------------------------

def test_illuminance_is_monotone_in_phase_measured_and_zero_below_the_horizon():
    angles = [float(a) for a in range(0, 181, 5)]
    lux = [n.moon_illuminance_lux(a, 45.0) for a in angles]
    assert all(later < earlier for earlier, later in zip(lux, lux[1:])), lux
    # Full moon at the zenith: I* = 10^(-0.4 (-12.73 + 16.57)) fc x 10.7639,
    # through one air mass of k = 0.172.
    top = 10.0 ** (-0.4 * 3.84) * 10.763910417
    assert n.moon_illuminance_top_lux(0.0) == pytest.approx(top)
    assert n.moon_illuminance_lux(0.0, 90.0) == pytest.approx(top * 10.0 ** (-0.4 * 0.172), rel=1e-9)
    assert n.moon_illuminance_lux(0.0, 90.0) == pytest.approx(0.2674, abs=1e-4)
    assert n.moon_illuminance_lux(0.0, 0.0) == 0.0 and n.moon_illuminance_lux(0.0, -3.0) == 0.0
    # And monotone in the illuminated fraction (k up -> lux up).
    fractions = [(1.0 + math.cos(math.radians(a))) / 2.0 for a in angles]
    assert fractions == sorted(fractions, reverse=True)


def test_the_sky_luminance_is_the_dark_sky_plus_the_moonlit_term():
    dark = n.dark_sky_nl(0.0)
    assert dark == pytest.approx(79.0)                           # X(0) = 1
    sky = n.sky_luminance_cd_m2(0.0, 180.0, 45.0, 180.0, 60.0, moon=True)
    alone = n.sky_luminance_cd_m2(0.0, 180.0, 45.0, 180.0, 60.0, moon=False)
    assert alone["moon_cd_m2"] == 0.0 and sky["dark_cd_m2"] == alone["dark_cd_m2"]
    assert sky["total_cd_m2"] == pytest.approx(sky["dark_cd_m2"] + sky["moon_cd_m2"])
    assert sky["moon_cd_m2"] > 5.0 * sky["dark_cd_m2"]           # a full moon brightens the sky
    assert n.CD_M2_PER_NANOLAMBERT == pytest.approx(1e-5 / math.pi)


# -- the night flag -------------------------------------------------------------

def test_the_night_flag_is_at_minus_six_degrees():
    assert n.NIGHT_SUN_ELEVATION_DEG == -6.0
    assert n.is_night(-6.0) and n.is_night(-6.01) and n.is_night(-18.0)
    assert not n.is_night(-5.99) and not n.is_night(0.0)
    sky = n.night_sky(*ZERMATT, FULL_MOON, stars="off")
    assert sky.sun_elevation_deg < -18.0 and sky.night


# -- the starfield ------------------------------------------------------------------

def _catalogue(tmp_path, stars=(("06h 45m 08.9s", "-16° 42′ 58″", "-1.46"),
                                ("00h 05m 03.8s", "-00° 30′ 11″", "6.29"))):
    path = tmp_path / "bsc5-short.json"
    entries = [{"HR": str(i + 1), "RA": ra, "Dec": dec, "V": v} for i, (ra, dec, v) in enumerate(stars)]
    entries.append({"HR": "99", "RA": "01h 00m 00.0s", "Dec": "+10° 00′ 00″"})
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_catalogue_is_read_only_with_its_sha256_and_refused_otherwise(tmp_path):
    path, digest = _catalogue(tmp_path)
    rows = n.load_catalogue(path, digest)
    assert rows[0] == pytest.approx((101.2870833, -16.7161111, -1.46))
    assert rows[1][1] == pytest.approx(-0.5030556)                # the sign of "-00"
    assert len(rows) == 2                                         # no V: skipped
    field = n.starfield("catalogue", 0, path, digest)
    assert field.mode == "catalogue" and field.catalogue_sha256 == digest
    assert n.starfield("auto", 0, path, digest).mode == "catalogue"
    # A digest that differs is refused in every mode that reads the file.
    for mode in ("catalogue", "auto"):
        with pytest.raises(n.NightError) as caught:
            n.starfield(mode, 0, path, "0" * 64)
        assert caught.value.constraint == "look.stars"
    path.write_bytes(path.read_bytes().replace(b"-1.46", b"-1.47"))
    with pytest.raises(n.NightError, match="look.stars"):
        n.load_catalogue(path, digest)
    # The code's own pin is the measured mirror digest (assets/stars/README.md).
    readme = (REPO / "assets/stars/README.md").read_text(encoding="utf-8")
    assert n.CATALOGUE_SHA256 in readme and readme.isascii()


def test_an_absent_catalogue_gives_a_seeded_procedural_field_recorded_as_such(tmp_path):
    absent = tmp_path / "none.json"
    field = n.starfield("auto", 7, absent)
    assert field.mode == "procedural" and field.seed == 7 and "procedural" in field.source
    again = n.starfield("procedural", 7)
    assert again.sha256 == field.sha256 and again.stars == field.stars      # deterministic
    assert n.starfield("procedural", 8).sha256 != field.sha256
    assert field.count == n.PROCEDURAL_COUNT
    mags = [row[2] for row in field.stars]
    assert min(mags) >= n.STAR_BRIGHTEST_MAG and max(mags) <= n.STAR_LIMITING_MAG
    with pytest.raises(n.NightError, match="look.stars"):
        n.starfield("catalogue", 7, absent)
    assert n.starfield("off").count == 0 and n.starfield("off").sha256 is None
    above = n.stars_above_horizon(field, *ZERMATT, FULL_MOON)
    assert 0.3 * field.count < above < 0.7 * field.count


# -- the spec block, the rule, the card -------------------------------------------------

def _spec(night=None, sun_lux=None, exposure=False, seconds=1):
    from core.nl.compiler import compile_prompt

    spec = compile_prompt(f"fly the c172p at 1500 m and 100 kt for {seconds} seconds")
    spec.set("hold_state", False, frm="test")
    spec.set("latitude", ZERMATT[0], frm="test")
    spec.set("longitude", ZERMATT[1], frm="test")
    if night is not None:
        spec.set("scene.night", night, frm="test")
    if sun_lux is not None:
        spec.set("scene.sun_lux", sun_lux, frm="test")
    if exposure:
        from core.scenario.camera import CameraSpec

        spec.cameras = [CameraSpec.defaulted(camera_id="cam", preset="chase",
                                             aircraft="c172p", frm="test")]
        spec.set("cameras[0].exposure.aperture_f", 2.8, frm="test")
        spec.set("cameras[0].exposure.shutter_s", 1.0 / 30.0, frm="test")
        spec.set("cameras[0].exposure.iso", 3200.0, frm="test")
    return spec


MOONLIT = {"moon": "on", "stars": "procedural", "utc": "2024-01-25T23:00:00Z"}


def test_scene_night_is_absent_canonical_and_behind_the_front_door(tmp_path):
    from core.scenario.spec import ScenarioSpec
    from tests.test_registry import EXAMPLE_DIGESTS

    for path, digest in EXAMPLE_DIGESTS.items():
        assert ScenarioSpec.read(REPO / path).digest() == digest, path
    plain = _spec()
    assert "scene" not in plain.to_dict()
    stated = _spec(MOONLIT)
    assert stated.to_dict()["scene"]["night"]["value"] == MOONLIT
    assert stated.digest() != plain.digest()
    again = ScenarioSpec.read(stated.write(tmp_path / "night.yaml"))
    assert again.digest() == stated.digest() and again.scene.night.value == MOONLIT


def test_the_validator_refuses_the_night_by_name():
    from core.scenario.validate import validate

    def names(spec):
        return {v.constraint for v in validate(spec, check_feasibility=False).violations}

    assert names(_spec({"moon": "sometimes"})) >= {"look.moon"}
    assert names(_spec({"moon": "off", "stars": "twinkly", "utc": MOONLIT["utc"]})) == {"look.stars"}
    assert names(_spec({"moon": "off", "stars": "off", "utc": "yesterday"})) == {"look.moon"}
    assert names(_spec({"moon": "off", "stars": "off"})) == {"look.moon"}      # no moment
    # The rule: the moon's lux on the bias path, or beside a unitless sun.
    assert names(_spec(MOONLIT)) == {"night.sun_units"}
    assert names(_spec(MOONLIT, sun_lux=100000.0)) == {"night.sun_units"}
    assert names(_spec(MOONLIT, exposure=True)) == {"night.sun_units"}
    assert names(_spec(MOONLIT, sun_lux=100000.0, exposure=True)) == set()
    assert names(_spec(dict(MOONLIT, moon="off"))) == set()                    # stars only
    for rule in ("look.moon", "look.stars", "night.sun_units"):
        from core.messages import is_catalogued

        assert is_catalogued(rule), rule


def test_the_sun_units_rule_is_stated_once():
    assert n.sun_units_problem(False, "unitless", "manual_bias") is None
    assert "bias path" in n.sun_units_problem(True, "unitless", "manual_bias")
    assert "not in lux" in n.sun_units_problem(True, "unitless", "manual_ev100")
    assert "bias exposure" in n.sun_units_problem(True, "physical", "manual_bias")
    assert n.sun_units_problem(True, "physical", "manual_ev100") is None


def test_the_card_carries_look_night_in_its_fixed_key_order():
    from core.scenario.card import world_look_card_block

    assert world_look_card_block(_spec()) is None                   # absent-canonical
    spec = _spec(MOONLIT, sun_lux=100000.0, exposure=True)
    block = world_look_card_block(spec)
    assert list(block) == ["night", "cloud_drift"]
    night = block["night"]
    assert tuple(night) == n.CARD_KEYS
    sky = n.night_sky(*ZERMATT, FULL_MOON)                           # the spec's place and moment
    assert night["stars_mode"] == "procedural" and night["sun_units"] == "physical"
    assert 0.99 < night["phase"] <= 1.0 and 0.05 < night["illuminance_lux"] < 0.3
    assert sky.phase == pytest.approx(night["phase"], abs=1e-4)
    assert sky.moon_elevation_deg == pytest.approx(night["moon_elevation_deg"], abs=1e-3)
    assert json.dumps(block).isascii()
    with pytest.raises(n.NightError) as caught:
        world_look_card_block(_spec(MOONLIT))
    assert caught.value.constraint == "night.sun_units"


def test_the_world_record_carries_both_null_kinds_each_with_a_windows_clause():
    from core.scene.world_record import WINDOWS_CLAUSES, world_record

    spec = _spec(MOONLIT, sun_lux=100000.0, exposure=True)
    spec.set("precipitation_rate_mmh", 4.0, frm="test")
    record = world_record(spec)
    assert record.name == "scene.world" and record.source == "user"
    tests = record.parameters["null_tests"]
    assert {t["kind"] for t in tests} == {"reached", "bounded"}
    for test, clause in zip(tests, ("moon", "stars", "streaks", "drift", "labels")):
        assert WINDOWS_CLAUSES[clause] in test["note"]
        assert isinstance(test["with"], float) and isinstance(test["threshold"], float)
    moon, stars, streaks, drift, labels = tests
    assert moon["ok"] and moon["with"] > 2.0 * moon["without"]      # a full moon at 60 deg
    assert stars["ok"] and stars["with"] > 1000
    assert streaks["ok"] and drift["unit"] == "m"
    assert labels["kind"] == "bounded" and labels["difference"] == 0.0 and labels["ok"]
    assert record.null_test.kind == "reached"
    assert record.to_dict()["value"]["night"]["sun_units"] == "physical"


# -- the verifier's night_exposure check ------------------------------------------------

#: The EV100 chain of record the synthetic camera carries (cd/m^2 per unit).
PER_UNIT = 0.2


def _bundle(tmp_path, sky_linear, lux=0.2316, phase=0.99788):
    """A one-frame synthetic run: the sky rows at ``sky_linear`` (8-bit
    sRGB), a class image with the top half sky (0)."""
    import numpy as np
    from PIL import Image

    folder = tmp_path / "frames" / "cam"
    folder.mkdir(parents=True)
    code = 0 if sky_linear <= 0 else round(255 * (1.055 * sky_linear ** (1 / 2.4) - 0.055))
    beauty = np.full((32, 48, 3), 40, dtype=np.uint8)
    beauty[:16] = code
    Image.fromarray(beauty).save(folder / "frame_0000.png")
    classes = np.full((32, 48), 2, dtype=np.uint8)
    classes[:16] = 0
    Image.fromarray(classes).save(folder / "frame_0000_class.png")
    (folder / "render.json").write_text(json.dumps({"frame_records": [
        {"frame": "frame_0000.png", "labels": {"class_mask": "frame_0000_class.png"}}]}),
        encoding="utf-8")
    manifest = {
        "look": {"night": {"moon_elevation_deg": 63.8, "moon_azimuth_deg": 148.9, "phase": phase,
                           "illuminance_lux": lux, "stars_mode": "procedural",
                           "sun_units": "physical"},
                 "night_sky": {"sun_elevation_deg": -61.6, "night": True}},
        "cameras": [{"camera_id": "cam", "sensing": {"radiometry": {
            "luminance_cd_m2_per_unit": PER_UNIT}}}],
        "frames": [{"camera_id": "cam", "file": "frames/cam/frame_0000.png", "labels": {},
                    "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0]}],
    }
    return manifest


def _predicted(lux=0.2316, phase=0.99788):
    angle = math.degrees(math.acos(2 * phase - 1))
    sky = n.sky_luminance_cd_m2(angle, 148.9, 63.8, 0.0, 10.0, moon=lux > 0)
    return sky["total_cd_m2"] / PER_UNIT


def test_night_exposure_passes_fails_by_name_and_is_not_run_without_a_night(tmp_path):
    from core.capture.verify import FAIL_NIGHT_EXPOSURE, _night_sky_cd_m2, verify_night_exposure

    # The checker's own K&S agrees with the producer's (two readings, one model).
    dark, lit = _night_sky_cd_m2(5.277, 148.9, 63.8, 0.0, 10.0, True)
    own = n.sky_luminance_cd_m2(5.277, 148.9, 63.8, 0.0, 10.0)
    assert dark == pytest.approx(own["dark_cd_m2"], rel=1e-9)
    assert lit == pytest.approx(own["moon_cd_m2"], rel=1e-9)
    predicted = _predicted()
    assert 3.1e-4 * 8 < predicted < 1.0 / 8                     # both corruptions representable
    ok = verify_night_exposure(_bundle(tmp_path / "ok", predicted), tmp_path / "ok")
    assert ok.status == "PASS", ok.detail
    bright = verify_night_exposure(_bundle(tmp_path / "hi", predicted * 8), tmp_path / "hi")
    assert bright.status == "FAIL" and bright.failure == FAIL_NIGHT_EXPOSURE == "check.night_exposure"
    dim = verify_night_exposure(_bundle(tmp_path / "lo", predicted / 8), tmp_path / "lo")
    assert dim.status == "FAIL" and "moon did not light" in dim.detail
    # NOT RUN: no look.night, a sun above -6 deg, no EV100 chain, no run directory.
    manifest = _bundle(tmp_path / "nr", predicted)
    assert verify_night_exposure({}, tmp_path / "nr").status == "NOT RUN"
    day = json.loads(json.dumps(manifest))
    day["look"]["night_sky"]["sun_elevation_deg"] = -5.0
    assert verify_night_exposure(day, tmp_path / "nr").status == "NOT RUN"
    bare = dict(manifest, cameras=[{"camera_id": "cam"}])
    assert verify_night_exposure(bare, tmp_path / "nr").status == "NOT RUN"
    assert verify_night_exposure(manifest, None).status == "NOT RUN"
    from core.messages import is_catalogued

    assert is_catalogued("check.night_exposure")
    # Verifier independence: the check imports nothing from the producers.
    source = (REPO / "core/capture/verify.py").read_text(encoding="utf-8")
    for forbidden in ("from core.scene", "import core.scene", "from ..scene"):
        assert forbidden not in source
    assert 'run("night_exposure", verify_night_exposure, manifest, run_dir)' in source
