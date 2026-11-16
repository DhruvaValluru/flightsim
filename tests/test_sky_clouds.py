"""Sky step 5 (the owner's X-Plane-12 brief, 2026-11-15): the sky plan's cloud
fields. ``sky.json`` "clouds" gains cloud_type, coverage, density, detail,
cirrus_coverage, coverage_source, cover_inputs, cloud_type_basis, seed,
seed_source and march_tier (core/sky/clouds.py), from the ERA5 level cover at
the plan's instant (core/environment/era5.py fetch_reanalysis_cloud_cover) when
the web app fetched one, else stated defaults recorded as defaults. The
altocumulus CLOUDS row exists on both sides (index 4). The beauty host reads
the fields through FFlightSimSkyPlan (step 2) and weighs the plan's march_tier
under -cloud-march=auto (FlightSimWorldPure::CloudMarchWordInForce). These
tests pin the plan's determinism, ranges, defaults, the type law, the measure
byte-identity (enabled/bottom_km/thickness_km/exposure unchanged), SKY_VERSION
on both sides, and the C++ to the Python twins by regex and by g++.
UNMEASURED: nothing here was rendered."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core.environment import era5
from core.scene import world_beauty as wb
from core.sky import clouds
from core.sky import plan as sky_plan

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
PUBLIC = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public"
CPP = PRIVATE / "FlightSimClouds.cpp"
HEADER = PUBLIC / "FlightSimClouds.h"
SKY_CPP = PRIVATE / "FlightSimSky.cpp"
SKY_H = PUBLIC / "FlightSimSky.h"
VFP = ROOT / "docs/VISUAL_FIDELITY_PLAN.md"
DESIGN = ROOT / "docs/visual/XPLANE_SKY_DESIGN.md"

NEEDS_CXX = pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler on this machine")

STEP5_KEYS = {"cloud_type", "coverage", "density", "detail", "cirrus_coverage", "coverage_source",
              "cover_inputs", "cloud_type_basis", "volumetric_row", "seed", "seed_source", "march_tier",
              "march_tier_basis", "fields_basis"}
V1_KEYS = {"enabled", "bottom_km", "thickness_km", "basis"}

#: The four positional call shapes the suite used before this step, with the
#: {enabled, bottom_km, thickness_km} each wrote (pinned literals: a measure
#: render reads only these).
V1_CALLS = [
    (("dusk", "none", 45.98, 7.66, 4500.0, 1600.0), {"enabled": True, "bottom_km": 3.9, "thickness_km": 3.0}),
    (("noon", "none", 0, 0, 3000, 0), {"enabled": True, "bottom_km": 4.0, "thickness_km": 3.0}),
    (("12:00", None, 37.6, -122.4, 1000.0, 0.0), {"enabled": True, "bottom_km": 2.0, "thickness_km": 3.0}),
    (("noon", None, 37.7275, -119.61, 1700.0, 1200.0), {"enabled": True, "bottom_km": 2.0, "thickness_km": 3.0}),
]

COVER = {"low": 0.2, "mid": 0.6, "high": 0.1, "total": 0.7, "source": "test stub", "date": "2024-01-15",
         "hour_utc": 17}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _plan(**kw):
    return sky_plan.plan_sky("12:00", "2024-01-15", 40.7, -74.0, 600.0, 4.0, **kw)


# -- the plan ------------------------------------------------------------------------------

def test_the_plan_is_deterministic_with_a_cover_and_a_seed():
    a = _plan(cloud_cover=dict(COVER), seed=7)
    b = _plan(cloud_cover=dict(COVER), seed=7)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    json.dumps(a).encode("ascii")
    c = _plan(cloud_cover=dict(COVER), seed=8)
    assert c["clouds"]["seed"] == 8 and a["clouds"]["seed"] == 7
    # the seed is the only byte that moved
    a["clouds"]["seed"] = 8
    assert a == c


def test_every_v1_call_shape_writes_the_same_placement_and_exposure():
    """Measure byte-identity: enabled / bottom_km / thickness_km and the whole
    exposure block are what they were before this step (the measure host reads
    only the placement; FlightSimSky.cpp Build is untouched, test_cloud_type)."""
    for args, placement in V1_CALLS:
        plan = sky_plan.plan_sky(*args)
        assert {k: plan["clouds"][k] for k in placement} == placement
        assert V1_KEYS | STEP5_KEYS == set(plan["clouds"])
        assert "VISUAL ONLY" in plan["clouds"]["basis"]
        assert plan["clouds"]["bottom_km"] >= max(args[4] - args[5], 0.0) / 1000.0 + 1.0
        with_cover = sky_plan.plan_sky(*args, cloud_cover=dict(COVER), seed=3)
        assert with_cover["exposure"] == plan["exposure"]
        assert {k: with_cover["clouds"][k] for k in placement} == placement
        for key in ("sun", "moon", "stars", "post_process", "fog", "lighting", "instant_utc"):
            assert with_cover[key] == plan[key], key


def test_the_defaults_are_recorded_as_defaults_and_equal_the_rows():
    plan = sky_plan.plan_sky("dusk", "none", 45.98, 7.66, 4500.0, 1600.0)
    block = plan["clouds"]
    assert block["cloud_type"] == clouds.DEFAULT_CLOUD_TYPE == "cumulus"
    assert block["coverage"] == wb.CLOUDS["cumulus"]["default_cover"] == 0.35
    assert block["coverage_source"] == "default (no weather_date): CLOUDS[cumulus].default_cover"
    assert block["cover_inputs"] is None and block["cirrus_coverage"] == 0.0
    assert block["density"] == 1.0 and block["detail"] == 1.0
    assert block["cloud_type_basis"].startswith("default: no cloud cover")
    assert block["volumetric_row"] == "cumulus"
    assert block["march_tier"] == "auto" and "-cloud-march=" in block["march_tier_basis"]
    assert "BEAUTY ONLY" in block["fields_basis"] and "UNCALIBRATED" in block["fields_basis"]
    assert "UNMEASURED" in block["fields_basis"]
    # a dated spec whose cover never arrived: the default, with the reason
    dated = _plan(cloud_cover_note="fetch failed: offline (test)")
    assert dated["clouds"]["cloud_type"] == "cumulus"
    assert dated["clouds"]["coverage_source"] == "default (fetch failed: offline (test)): CLOUDS[cumulus].default_cover"
    plain = _plan()
    assert plain["clouds"]["coverage_source"] == ("default (no cloud cover given for weather_date 2024-01-15): "
                                                  "CLOUDS[cumulus].default_cover")


def test_a_storm_spec_is_nimbostratus_with_todays_slab():
    for cover in (None, dict(COVER)):
        plan = sky_plan.plan_sky("noon", "none", 40.0, -100.0, 3000.0, 300.0, weather_event="thunderstorm",
                                 cloud_cover=cover)
        block = plan["clouds"]
        assert block["cloud_type"] == "nimbostratus"
        assert block["coverage"] == wb.CLOUDS["nimbostratus"]["default_cover"] == 0.98
        assert block["bottom_km"] == 3.7 and block["thickness_km"] == 6.0   # max(1.2, 2.7 + 1): the >= 1 km rule
    tornado = sky_plan.plan_sky("noon", "none", 40.0, -100.0, 1000.0, 300.0, weather_event="tornado")
    assert tornado["clouds"]["cloud_type"] == "nimbostratus" and tornado["clouds"]["bottom_km"] == 1.7


def test_the_ranges():
    for low in (0.0, 0.3, 1.0):
        for mid in (0.0, 0.5, 1.0):
            for high in (0.0, 0.4, 1.0):
                cover = {"low": low, "mid": mid, "high": high, "total": max(low, mid, high)}
                block = _plan(cloud_cover=cover, seed=1)["clouds"]
                assert block["cloud_type"] in wb.PLAN_CLOUD_TYPES
                assert 0.0 <= block["coverage"] <= 1.0
                assert 0.0 <= block["cirrus_coverage"] <= 1.0 and block["cirrus_coverage"] == high
                assert wb.PLAN_DENSITY_MIN <= block["density"] <= wb.PLAN_DENSITY_MAX
                assert 0.0 <= block["detail"] <= 1.0
                assert block["volumetric_row"] == wb.PLAN_CLOUD_SHAPES[block["cloud_type"]]
                assert block["cover_inputs"] == {k: round(cover[k], 4) for k in clouds.CLOUD_COVER_KEYS}
    # out-of-range inputs are clamped, NaN refuses
    assert _plan(cloud_cover={"low": 1.7, "mid": -0.2, "high": 2.0, "total": 9.0}, seed=1)["clouds"]["coverage"] == 1.0
    with pytest.raises(ValueError):
        clouds.cloud_type_from_cover(float("nan"), 0.0, 0.0, False)


@pytest.mark.parametrize("low,mid,high,storm,expected", [
    (0.0, 0.0, 0.0, False, ("clear", 0.0)),
    (0.0, 0.0, 0.19, False, ("clear", 0.0)),
    (0.0, 0.0, 0.2, False, ("cirrus", 0.2)),            # CIRRUS_MIN_HIGH_COVER boundary
    (0.09, 0.0, 0.9, False, ("cirrus", 0.9)),
    (0.1, 0.0, 0.0, False, ("cumulus", 0.1)),           # CUMULUS_MIN_LOW_COVER boundary
    (0.3, 0.3, 0.0, False, ("cumulus", 0.3)),           # mid not above low
    (0.2, 0.3, 0.0, False, ("altocumulus", 0.3)),       # ALTOCUMULUS_MIN_MID_COVER boundary
    (0.2, 0.29, 0.0, False, ("cumulus", 0.2)),
    (0.0, 0.29, 0.0, False, ("clear", 0.0)),
    (0.5, 0.8, 0.0, False, ("stratocumulus", 0.5)),     # STRATOCUMULUS_MIN_COVER boundary, low first
    (0.49, 0.6, 0.0, False, ("altocumulus", 0.6)),
    (0.85, 0.0, 0.0, False, ("overcast", 0.85)),        # CLOUD_OVERCAST_COVER boundary
    (0.0, 0.85, 0.0, False, ("overcast", 0.85)),
    (0.84, 0.84, 1.0, False, ("stratocumulus", 0.84)),
    (0.0, 0.0, 0.0, True, ("nimbostratus", 0.98)),
    (1.0, 1.0, 1.0, True, ("nimbostratus", 0.98)),
])
def test_the_type_law_table(low, mid, high, storm, expected):
    cloud_type, coverage, basis = clouds.cloud_type_from_cover(low, mid, high, storm)
    assert (cloud_type, coverage) == expected
    assert cloud_type in wb.PLAN_CLOUD_TYPES and basis
    assert clouds.CLOUD_OVERCAST_COVER == wb.CLOUD_OVERCAST_COVER == 0.85
    assert clouds.STRATOCUMULUS_MIN_COVER == wb.STRATOCUMULUS_MIN_COVER == 0.5
    assert clouds.CUMULUS_MIN_LOW_COVER == wb.FAIR_CLOUD_SHADOW_MIN_COVER == 0.1
    assert clouds.ALTOCUMULUS_MIN_MID_COVER == 0.3 and clouds.CIRRUS_MIN_HIGH_COVER == 0.2


def test_the_seed_is_the_specs_or_derived_from_the_inputs():
    stated = _plan(seed=4242)["clouds"]
    assert stated["seed"] == 4242 and stated["seed_source"] == "spec.seed"
    derived = _plan()["clouds"]
    assert derived["seed_source"].startswith("derived")
    assert derived["seed"] == clouds.derive_seed(_plan()["instant_utc"], 40.7, -74.0, 600.0)
    assert 0 <= derived["seed"] < 2 ** 31
    # another place, another seed; the same place, the same seed
    assert sky_plan.plan_sky("12:00", "2024-01-15", 40.7, -74.1, 600.0, 4.0)["clouds"]["seed"] != derived["seed"]
    assert clouds.derive_seed("2024-01-15T17:00:00+00:00", 40.7, -74.0, 600.0) == \
        clouds.derive_seed("2024-01-15T17:00:00+00:00", 40.7, -74.0, 600.0)


def test_the_fetched_cover_is_copied_and_sourced():
    block = _plan(cloud_cover=dict(COVER), seed=7)["clouds"]
    assert block["cloud_type"] == "altocumulus" and block["coverage"] == 0.6
    assert block["cirrus_coverage"] == 0.1
    assert block["cover_inputs"] == {"low": 0.2, "mid": 0.6, "high": 0.1, "total": 0.7}
    assert block["coverage_source"] == "test stub, 2024-01-15T17Z, cloud_cover_low/mid/high"
    assert "ALTOCUMULUS_MIN_MID_COVER" in block["cloud_type_basis"]
    assert block["volumetric_row"] == "altocumulus"
    assert "from ERA5 cloud_cover_low/mid/high" in block["basis"]
    # the host's parser twin reads every field it knows
    read = wb.plan_cloud_fields(block)
    assert read["stated"] and read["cloud_type"] == "altocumulus" and read["coverage"] == 0.6
    assert read["seed"] == 7 and read["march_tier"] == "auto"
    assert wb.layer_source(None, None, False, read["cloud_type"], read["coverage"], "clear", 3000.0) == \
        (0.6, "altocumulus", "plan")


def test_coverage_source_stamps_the_covers_utc_day_not_weather_date():
    """Repair round 1: the web app fetches the cover for the plan INSTANT's UTC
    date and hour, which is the day after (or before) ``weather_date`` when the
    local time crosses the UTC day boundary (20:00 at New York on 2024-01-15 is
    2024-01-16T00:56Z). The provider dict's ``date`` is the day fetched, and the
    recorded ``coverage_source`` prints THAT day, never ``weather_date``; the
    default texts still name ``weather_date`` because that is what the spec said."""
    rolled = {**COVER, "date": "2024-01-16", "hour_utc": 0}
    assert clouds.coverage_source_text(rolled, "2024-01-15", "altocumulus", None) == \
        "test stub, 2024-01-16T00Z, cloud_cover_low/mid/high"
    plan = sky_plan.plan_sky("20:00", "2024-01-15", 40.7, -74.0, 9000.0, 4.0, cloud_cover=rolled, seed=7)
    assert plan["instant_utc"].startswith("2024-01-16T00:")
    assert plan["clouds"]["coverage_source"] == "test stub, 2024-01-16T00Z, cloud_cover_low/mid/high"
    assert "2024-01-15" not in plan["clouds"]["coverage_source"]
    # a cover without a date falls back to weather_date; the default names weather_date
    assert clouds.coverage_source_text({**COVER, "date": None}, "2024-01-15", "cumulus", None) == \
        "test stub, 2024-01-15T17Z, cloud_cover_low/mid/high"
    assert clouds.coverage_source_text(None, "2024-01-15", "cumulus", None) == \
        "default (no cloud cover given for weather_date 2024-01-15): CLOUDS[cumulus].default_cover"


def test_relight_leaves_the_clouds_block_byte_identical():
    plan = _plan(cloud_cover=dict(COVER), seed=7)
    lit = sky_plan.relight(plan, elevation_deg=30.0, azimuth_deg=200.0, basis="test")
    assert lit["clouds"] == plan["clouds"]
    assert lit["sun"]["elevation_deg"] == 30.0


def test_sky_version_is_the_hosts_and_unbumped():
    """Additive keys read with TryGet* need no bump (design §0.15): both sides say 1."""
    text = _read(SKY_CPP)
    assert sky_plan.SKY_VERSION == int(re.search(r"constexpr int32 SkySupportedVersion = (\d+);", text).group(1)) == 1
    assert _plan()["sky_version"] == 1


# -- the provider ----------------------------------------------------------------------------

def test_the_cloud_cover_fetch_reads_the_plans_hour_as_fractions(monkeypatch):
    seen = {}

    class _Response:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

    def fake_urlopen(url, timeout):
        seen["url"] = url
        hours = list(range(24))
        return _Response({"hourly": {
            "cloud_cover": [h * 4 for h in hours], "cloud_cover_low": [h * 2 for h in hours],
            "cloud_cover_mid": [h * 3 for h in hours], "cloud_cover_high": [h for h in hours]}})

    monkeypatch.setattr(era5.urllib.request, "urlopen", fake_urlopen)
    cover = era5.fetch_reanalysis_cloud_cover(40.7, -74.0, "2024-01-15", 17)
    assert cover == {"low": 0.34, "mid": 0.51, "high": 0.17, "total": 0.68, "hour_utc": 17,
                     "date": "2024-01-15", "source": era5.CLOUD_COVER_SOURCE}
    assert seen["url"].startswith(era5.ARCHIVE_URL)
    assert "hourly=cloud_cover%2Ccloud_cover_low%2Ccloud_cover_mid%2Ccloud_cover_high" in seen["url"]
    assert "start_date=2024-01-15" in seen["url"] and "latitude=40.7000" in seen["url"]
    # the wind keeps its noon convention; the clouds take the instant's hour
    assert era5.HOUR_UTC == 12
    with pytest.raises(era5.WeatherUnavailableError, match="not 0..23"):
        era5.fetch_reanalysis_cloud_cover(40.7, -74.0, "2024-01-15", 24)

    def null_urlopen(url, timeout):
        return _Response({"hourly": {f: [None] * 24 for f in era5.CLOUD_COVER_FIELDS}})

    monkeypatch.setattr(era5.urllib.request, "urlopen", null_urlopen)
    with pytest.raises(era5.WeatherUnavailableError, match="null cloud cover"):
        era5.fetch_reanalysis_cloud_cover(40.7, -74.0, "2024-01-15", 17)

    def offline(url, timeout):
        raise OSError("offline (test)")

    monkeypatch.setattr(era5.urllib.request, "urlopen", offline)
    with pytest.raises(era5.WeatherUnavailableError, match="offline"):
        era5.fetch_reanalysis_cloud_cover(40.7, -74.0, "2024-01-15", 17)


# -- the altocumulus row, both sides -------------------------------------------------------------

def test_the_altocumulus_row_exists_on_both_sides():
    assert wb.CLOUD_PRESETS == ("cumulus", "stratocumulus", "overcast", "nimbostratus", "altocumulus")
    row = wb.CLOUDS["altocumulus"]
    assert set(row) == set(wb.CLOUD_FIELDS)
    assert row["default_cover"] == 0.5 and row["shape_scale_km"] == 1.2
    assert wb.CLOUD_MAX_THICKNESS_M["altocumulus"] == 900.0
    assert wb.PLAN_CLOUD_SHAPES["altocumulus"] == "altocumulus"
    # the thickness law thins the plan's 3 km slab to the sheet's depth; a stated layer stands
    assert wb.cloud_capped_top_m("altocumulus", 2000.0, 5000.0, False) == 2900.0
    assert wb.cloud_capped_top_m("altocumulus", 2000.0, 5000.0, True) == 5000.0
    # select_cloud never picks it: the plan's mid-level law does
    for cover in (0.0, 0.5, 0.9):
        for thick in (500.0, 3000.0):
            assert wb.select_cloud(cover, thick, "clear") != "altocumulus"
    text = _read(CPP)
    assert "CloudAltocumulus = 4," in text and "CloudCount = 5" in text
    names = re.search(r'static const char\* const Names\[CloudCount\] = \{\s*((?:"[a-z]+",?\s*)+)\};', text)
    assert names and tuple(re.findall(r'"([a-z]+)"', names.group(1))) == wb.CLOUD_PRESETS
    row_text = re.search(r"\{([0-9., ]+)\},\s*// altocumulus", text).group(1)
    assert [float(v) for v in row_text.split(",")] == [row[f] for f in wb.CLOUD_FIELDS]
    caps = re.search(r"CloudMaxThicknessM\(int Cloud\)\s*\{[^{]*static const double Rows\[CloudCount\] = \{([0-9., ]+)\};",
                     text).group(1)
    assert [float(v) for v in caps.split(",")] == [wb.CLOUD_MAX_THICKNESS_M[s] for s in wb.CLOUD_PRESETS]
    assert "case 3: return CloudAltocumulus;" in text
    assert "case 3: return CloudStratocumulus;" not in text
    # the overrides file may name the new row (the loader accepts a partial section)
    assert wb.validate_overrides({"clouds": {"altocumulus": {"default_cover": 0.4}}}) == []


# -- the march tier, plan -> host --------------------------------------------------------------

def test_the_march_word_law():
    f = wb.cloud_march_word
    assert f("auto", "auto") == ("auto", "default auto")
    assert f("auto", "") == ("auto", "default auto") and f(None, None) == ("auto", "default auto")
    assert f("auto", "probe") == ("probe", "plan")
    assert f("probe", "discrete") == ("probe", "switch")
    assert f("constrained", "") == ("constrained", "switch")
    assert f("auto", "turbo") == ("auto", "default auto")      # unknown plan word: ignored, never a refusal
    assert wb.MARCH_WORD_SOURCES == ("switch", "plan", "default auto")
    assert clouds.DEFAULT_MARCH_TIER == "auto" and "auto" in wb.CLOUD_MARCH_SWITCH_WORDS


def test_load_reads_march_tier_and_the_host_weighs_it():
    sky_h = _read(SKY_H)
    assert "FString CloudMarchTier;" in sky_h
    load = _read(SKY_CPP)
    load = load[load.index("bool FFlightSimSkyPlan::Load("):load.index("void FFlightSimSky::EnableRendererFeatures()")]
    assert 'CloudsJson->TryGetStringField(TEXT("march_tier"), Out.CloudMarchTier) || Out.bCloudPlanFields' in load
    assert 'SkyNumber(CloudsJson, TEXT("march_tier")' not in load
    build = _read(SKY_CPP)
    build = build[build.index("bool FFlightSimSky::Build("):build.index("void FFlightSimSky::ApplyPostProcess(")]
    assert "CloudMarchTier" not in build        # the measure host never reads it
    header = _read(HEADER)
    assert 'FString CloudMarchSwitchGiven = TEXT("auto");' in header
    assert 'FString CloudMarchWordSource = TEXT("default auto");' in header
    cpp = _read(CPP)
    # the step 3 pins stand: the parse and the refusal are unchanged, and the
    # tier is still resolved from CloudMarchSwitch (now the word in force)
    assert 'CloudMarchSwitch = TEXT("auto");' in cpp
    assert 'FParse::Value(*Switches, TEXT("cloud-march="), CloudMarchSwitch);' in cpp
    assert "if (CloudMarchFor(TCHAR_TO_ANSI(*CloudMarchSwitch), false) < 0)" in cpp
    assert "const int32 MarchChosen = CloudMarchFor(TCHAR_TO_ANSI(*CloudMarchSwitch), bIntegratedGpu);" in cpp
    body = cpp[cpp.index("SkyPlanRef = SkyPlan;"):cpp.index("// The tables in force")]
    assert "CloudMarchSwitchGiven = CloudMarchSwitch;" in body
    assert "CloudMarchWordInForce(TCHAR_TO_ANSI(*CloudMarchSwitch)" in body
    assert "CloudMarchSwitch = WordSource == MarchWordPlan ? PlanTier" in body
    # the refusal of an unknown switch word runs BEFORE the plan is weighed
    assert cpp.index("if (CloudMarchFor(TCHAR_TO_ANSI(*CloudMarchSwitch), false) < 0)") < cpp.index("SkyPlanRef = SkyPlan;")
    for key in ("switch_given", "plan_march_tier", "word_source"):
        assert f'MarchOut->SetStringField(TEXT("{key}")' in cpp, key
    assert 'PlanOut->SetStringField(TEXT("march_tier"), SkyPlanRef != nullptr ? SkyPlanRef->CloudMarchTier : FString());' in cpp
    assert "seed, march_tier; core/sky/clouds.py writes them" in cpp
    # brace balance of the host file
    assert cpp.count("{") == cpp.count("}")


@NEEDS_CXX
def test_the_cpp_march_word_law_is_the_python_one(tmp_path):
    from tests.test_world_beauty import _block
    block = _block(_read(CPP), "// FLIGHTSIM-WORLD-PURE-BEGIN", "// FLIGHTSIM-WORLD-PURE-END")
    cases = [(s, p) for s in ("auto", "", "probe", "constrained", "discrete")
             for p in ("", "auto", "probe", "discrete", "constrained", "turbo")]
    main = ["using namespace FlightSimWorldPure;", "int main() {"]
    for s, p in cases:
        main.append(f'{{ const char* W = "x"; int Src = CloudMarchWordInForce("{s}", "{p}", &W);'
                    f' printf("word %s %s\\n", W, MarchWordSourceName(Src)); }}')
    main.append('{ const char* W = "x"; int Src = CloudMarchWordInForce(nullptr, nullptr, &W);'
                ' printf("word %s %s\\n", W, MarchWordSourceName(Src)); }')
    main.append("for (int i = 0; i < MarchWordSourceCount; ++i) printf(\"src %s\\n\", MarchWordSourceName(i));")
    main.append("for (int c = 0; c < CloudCount; ++c) printf(\"cap %s %.17g\\n\", CloudName(c), CloudMaxThicknessM(c));")
    main.append("return 0; }")
    source = tmp_path / "march_word.cpp"
    source.write_text("#include <cmath>\n#include <cstdint>\n#include <cstdio>\n#include <cstring>\n"
                      + block + "\n" + "\n".join(main), encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-O1", "-Wall", "-Werror", "-Wno-unused-const-variable",
                    "-Wno-unused-variable", "-o", str(tmp_path / "march_word"), str(source)],
                   check=True, capture_output=True, text=True)
    lines = subprocess.run([str(tmp_path / "march_word")], check=True, capture_output=True,
                           text=True).stdout.splitlines()
    words = [l.split(None, 2)[1:] for l in lines if l.startswith("word ")]
    expected = [list(wb.cloud_march_word(s or None, p or None)) for s, p in cases] + [["auto", "default auto"]]
    assert words == expected
    assert [l.split(None, 1)[1] for l in lines if l.startswith("src ")] == list(wb.MARCH_WORD_SOURCES)
    caps = [l.split() for l in lines if l.startswith("cap ")]
    assert [(c, float(v)) for _, c, v in caps] == [(s, wb.CLOUD_MAX_THICKNESS_M[s]) for s in wb.CLOUD_PRESETS]


# -- the docs ----------------------------------------------------------------------------------

def test_the_docs_say_unmeasured_and_name_the_windows_command():
    vfp = _read(VFP)
    entry = vfp[vfp.index("### Sky step 5"):]
    assert "UNMEASURED" in entry and "UNCALIBRATED" in entry
    assert "visual_fix_round.ps1" in entry and "-cloud-type=altocumulus" in entry
    assert "coverage_source" in entry and "weather_date" in entry
    # repair round 1: the plan path (ERA5 -> sky.json -> FFlightSimSkyPlan -> ApplyClouds)
    # has its own exact Windows command (the web app's /compile and /run for a dated
    # prompt) and the UTC-day rule is stated
    assert "/compile" in entry and "/run" in entry and "on 2024-01-15" in entry
    assert "UTC date" in entry and "2024-01-16" in entry
    assert "cloud_type_source" in entry and "sky.json" in entry
    design = _read(DESIGN)
    assert "Built (sky step 5" in design
    assert "Repair round 1" in design[design.index("Built (sky step 5"):]
