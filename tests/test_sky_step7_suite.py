"""Sky step 7 (the owner's X-Plane-12 brief, 2026-11-15): the tests the earlier
steps did not land with themselves, and the pins that hold the suite together.

What the branch carries when this step is built: steps 0, 2, 3 and 5 (steps 1,
4 and 6 are being built on their own branches and are NOT on claude/xplane-sky
yet, so nothing here pins their shader, material or atmosphere code; the design
doc's "tests that legitimately move" list for them did not apply: nothing moved).

Pinned here, beyond tests/test_sky_clouds.py, test_cloud_type.py and
test_sky_step3_cvars.py:

* the plan's "clouds" block as a GOLDEN: every byte, including key order (the
  web app writes ``json.dumps(plan, indent=1)`` without ``sort_keys``, so the
  order is part of the file), for one covered input and one default input;
* the derived seed as a CRC-32 literal (a platform-stable bytes pin), and the
  ``seed=0`` edge (stated, not treated as "none");
* the exposure's independence from the cloud fields, by source order AND by a
  grid of covers (EV100 in core/sky/plan.py is unchanged by every step);
* the plan's rounding, clamping and purity on its inputs;
* the ERA5 provider's clamp of out-of-range percent, its negative-hour and
  missing-field refusals, and that its dict carries every key the plan reads;
* render.json recording: every "clouds" key ``FFlightSimSkyPlan::Load`` reads
  is recorded by ``ApplyClouds`` under ``look_applied.world_beauty.clouds.plan``,
  and the record's key set is exactly the pinned one; the web app's
  ``run.conditions["sky"]`` names the type, cover and source;
* ``FFlightSimWeather::VerifyCloudMaterials``: the beauty cloud material is
  built to pass it (Volume domain, ``used_with_volumetric_cloud``, lit by the
  multiple-scattering node), the swap runs before the check and a missing
  material keeps the stock one and records it (no refusal there; the verify
  refuses by name only on a bad material), the check's order mirrors the
  engine's and its report lands in render.json ``look_applied.cloud_materials``.

UNMEASURED: nothing here was rendered; every pin is a source or a Python pin.
"""
import json
import re
import zlib
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
SKY_CPP = PRIVATE / "FlightSimSky.cpp"
SKY_H = PUBLIC / "FlightSimSky.h"
WEATHER_CPP = PRIVATE / "FlightSimWeather.cpp"
COMMANDLET = PRIVATE / "FlightSimRenderCommandlet.cpp"
INTERACTIVE = PRIVATE / "FlightSimInteractiveMode.cpp"
SCRIPT = ROOT / "scripts/ue_create_materials.py"
RUNS = ROOT / "webapp/runs.py"
PLAN_PY = ROOT / "core/sky/plan.py"
CLOUDS_PY = ROOT / "core/sky/clouds.py"
VFP = ROOT / "docs/VISUAL_FIDELITY_PLAN.md"
DESIGN = ROOT / "docs/visual/XPLANE_SKY_DESIGN.md"

COVER = {"low": 0.2, "mid": 0.6, "high": 0.1, "total": 0.7, "source": "test stub", "date": "2024-01-15",
         "hour_utc": 17}

MARCH_TIER_BASIS = ("the sky step 3 cvar set the beauty host applies (-cloud-march=auto|constrained|discrete|probe); "
                    "auto is the GPU class; a -cloud-march= word on the render command line wins")
FIELDS_BASIS = ("BEAUTY ONLY (FFlightSimWorldBeauty::ApplyClouds under -quality=beauty); the measure host reads "
                "enabled/bottom_km/thickness_km only. density and detail are multipliers of core/scene/world_beauty.py "
                "CLOUDS[cloud_type] (1 = the row). UNCALIBRATED; UNMEASURED until a Windows render")

#: plan_sky("12:00", "2024-01-15", 40.7, -74.0, 600.0, 4.0, cloud_cover=COVER, seed=7)["clouds"],
#: byte for byte and in key order. A change here is a change to every dated beauty
#: sky.json; move it only with the step that means to, and say so in this docstring.
GOLDEN_WITH_COVER = {
    "enabled": True,
    "bottom_km": 2.0,
    "thickness_km": 3.0,
    "basis": ("VISUAL ONLY, not from weather data: UE volumetric cloud layer, base placed >= 1 km above the "
              "flight so the camera stays clear; cloud_type/coverage from ERA5 cloud_cover_low/mid/high (the "
              "place and hour), BEAUTY ONLY"),
    "cloud_type": "altocumulus",
    "coverage": 0.6,
    "density": 1.0,
    "detail": 1.0,
    "cirrus_coverage": 0.1,
    "coverage_source": "test stub, 2024-01-15T17Z, cloud_cover_low/mid/high",
    "cover_inputs": {"low": 0.2, "mid": 0.6, "high": 0.1, "total": 0.7},
    "cloud_type_basis": "mid 0.60 >= ALTOCUMULUS_MIN_MID_COVER 0.3 and above low 0.20",
    "volumetric_row": "altocumulus",
    "seed": 7,
    "seed_source": "spec.seed",
    "march_tier": "auto",
    "march_tier_basis": MARCH_TIER_BASIS,
    "fields_basis": FIELDS_BASIS,
}

#: plan_sky("dusk", "none", 45.98, 7.66, 4500.0, 1600.0)["clouds"]: the undated default
#: (round 95's frame by construction). The instant is the plan's fixed default date
#: (the March 2026 equinox), so the derived seed is a constant too.
GOLDEN_DEFAULT = {
    "enabled": True,
    "bottom_km": 3.9,
    "thickness_km": 3.0,
    "basis": ("VISUAL ONLY, not from weather data: UE volumetric cloud layer, base placed >= 1 km above the "
              "flight so the camera stays clear; cloud_type/coverage are stated defaults, BEAUTY ONLY"),
    "cloud_type": "cumulus",
    "coverage": 0.35,
    "density": 1.0,
    "detail": 1.0,
    "cirrus_coverage": 0.0,
    "coverage_source": "default (no weather_date): CLOUDS[cumulus].default_cover",
    "cover_inputs": None,
    "cloud_type_basis": "default: no cloud cover (cumulus, the round-95 frame by construction)",
    "volumetric_row": "cumulus",
    "seed": 1601526400,
    "seed_source": "derived: CRC-32 of instant_utc, latitude, longitude, altitude (no spec seed given)",
    "march_tier": "auto",
    "march_tier_basis": MARCH_TIER_BASIS,
    "fields_basis": FIELDS_BASIS,
}

#: Every key ApplyClouds writes under look_applied.world_beauty.clouds.plan (the
#: render.json record of the plan's fields), exactly.
PLAN_RECORD_KEYS = (
    "fields_source", "cloud_type", "cloud_type_known", "coverage", "density", "detail", "cirrus_coverage",
    "coverage_source", "seed", "seed_stated", "march_tier", "card_seed", "seed_matches_card", "cloud_type_switch",
    "precedence", "owner_parameters", "exposure_sees_plan_clouds", "measure_path", "calibration",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _between(text: str, begin: str, end: str) -> str:
    start = text.index(begin)
    return text[start:text.index(end, start)]


def _plan(**kw):
    return sky_plan.plan_sky("12:00", "2024-01-15", 40.7, -74.0, 600.0, 4.0, **kw)


# -- the plan's block, byte for byte ---------------------------------------------------------

def test_the_clouds_block_is_the_golden_byte_for_byte_and_in_key_order():
    with_cover = _plan(cloud_cover=dict(COVER), seed=7)["clouds"]
    assert json.dumps(with_cover, indent=1) == json.dumps(GOLDEN_WITH_COVER, indent=1)
    assert list(with_cover) == list(GOLDEN_WITH_COVER)
    default = sky_plan.plan_sky("dusk", "none", 45.98, 7.66, 4500.0, 1600.0)["clouds"]
    assert json.dumps(default, indent=1) == json.dumps(GOLDEN_DEFAULT, indent=1)
    assert list(default) == list(GOLDEN_DEFAULT)
    # the web app's file encoding: ASCII, so every basis string must be ASCII too
    json.dumps(with_cover, indent=1).encode("ascii")
    json.dumps(default, indent=1).encode("ascii")
    # and the block is the host's parser's whole vocabulary plus the stated bases
    assert set(wb.PLAN_CLOUD_DEFAULTS) <= set(GOLDEN_WITH_COVER)


def test_the_plans_top_level_key_order_is_stable():
    """The order the web app writes; "clouds" follows "exposure", which it never feeds."""
    assert list(_plan()) == ["sky_version", "instant_utc", "time_of_day", "time_basis", "date_source", "observer",
                             "sun", "moon", "stars", "exposure", "clouds", "fog", "lighting", "post_process"]
    assert list(_plan(cloud_cover=dict(COVER), seed=1)) == list(_plan())


def test_the_derived_seed_is_a_pinned_crc32_and_zero_is_a_stated_seed():
    text = "2024-01-15T17:00:00+00:00|40.700000|-74.000000|600.0"
    assert clouds.derive_seed("2024-01-15T17:00:00+00:00", 40.7, -74.0, 600.0) == 864852549
    assert zlib.crc32(text.encode("ascii")) & 0x7FFFFFFF == 864852549
    # the same place to 6 decimals and the same altitude to 0.1 m: the same seed
    assert clouds.derive_seed("2024-01-15T17:00:00+00:00", 40.7000004, -74.0, 600.04) == 864852549
    assert clouds.derive_seed("2024-01-15T17:00:00+00:00", 40.7, -74.0, 600.2) != 864852549
    # seed=0 is the spec's seed, not "none"
    zero = _plan(seed=0)["clouds"]
    assert zero["seed"] == 0 and zero["seed_source"] == "spec.seed"
    # a float seed is recorded as an int (sky.json is read back as a number by the host)
    assert _plan(seed=7.0)["clouds"]["seed"] == 7 and isinstance(_plan(seed=7.0)["clouds"]["seed"], int)


def test_the_exposure_never_sees_the_cloud_fields_by_source_and_by_value():
    """Design §2: the plan's cloud fields are computed after the exposure dict and
    never read into it. Source: ev100 is computed before plan_cloud_block is called,
    the call's keywords are exactly the inputs it declares, and core/sky/clouds.py
    never mentions the exposure. Value: the exposure block is identical across
    every cover, note and seed."""
    plan_src = _read(PLAN_PY)
    body = _between(plan_src, "def plan_sky(", "def relight(")
    assert body.index("ev100 = ev100_for(horizontal)") < body.index("**plan_cloud_block(")
    assert body.index('"exposure": {') < body.index('"clouds": {') < body.index("**plan_cloud_block(")
    call = _between(body, "**plan_cloud_block(", "seed=seed),") + "seed=seed"
    # timespec= belongs to the inner isoformat(...) call, not to plan_cloud_block
    keywords = set(re.findall(r"\b(\w+)=", call)) - {"timespec"}
    assert keywords == {"storm", "weather_date", "instant_utc", "lat", "lon", "altitude_msl_m", "cloud_cover",
                        "cloud_cover_note", "seed"}
    clouds_src = _read(CLOUDS_PY)
    assert not re.search(r"\bev100\b|\bexposure\b|\blux\b", clouds_src)
    base = _plan()["exposure"]
    for cover in (None, dict(COVER), {"low": 1.0, "mid": 1.0, "high": 1.0, "total": 1.0},
                  {"low": 0.0, "mid": 0.0, "high": 0.0, "total": 0.0}):
        for seed in (None, 0, 99):
            for note in (None, "fetch failed: offline (test)"):
                plan = _plan(cloud_cover=cover, seed=seed, cloud_cover_note=note)
                assert plan["exposure"] == base
                assert plan["exposure"]["ev100"] == base["ev100"]
    # the host records the same fact
    assert 'PlanOut->SetBoolField(TEXT("exposure_sees_plan_clouds"), false);' in _read(CPP)


def test_the_plan_rounds_to_four_places_and_the_coverage_is_the_named_level():
    cover = {"low": 0.123456, "mid": 0.654321, "high": 0.00004, "total": 0.99999}
    block = _plan(cloud_cover=cover, seed=1)["clouds"]
    assert block["cover_inputs"] == {"low": 0.1235, "mid": 0.6543, "high": 0.0, "total": 1.0}
    assert block["cloud_type"] == "altocumulus" and block["coverage"] == 0.6543
    assert block["cirrus_coverage"] == 0.0
    for low, mid, high, level in ((0.55, 0.0, 0.0, "low"), (0.0, 0.9, 0.0, "mid"), (0.0, 0.0, 0.5, "high"),
                                  (0.2, 0.3, 0.0, "mid"), (0.15, 0.1, 0.0, "low")):
        got = _plan(cloud_cover={"low": low, "mid": mid, "high": high, "total": 1.0}, seed=1)["clouds"]
        assert got["coverage"] == got["cover_inputs"][level], (low, mid, high)
        assert got["cirrus_coverage"] == got["cover_inputs"]["high"]
    # "total" is recorded, never decides
    a = _plan(cloud_cover={"low": 0.2, "mid": 0.0, "high": 0.0, "total": 0.0}, seed=1)["clouds"]
    b = _plan(cloud_cover={"low": 0.2, "mid": 0.0, "high": 0.0, "total": 1.0}, seed=1)["clouds"]
    assert (a["cloud_type"], a["coverage"]) == (b["cloud_type"], b["coverage"]) == ("cumulus", 0.2)


def test_plan_cloud_block_is_pure_on_its_inputs_and_refuses_only_nan():
    cover = {"low": 1.7, "mid": -0.2, "high": "0.3", "total": 9.0, "source": "s", "date": "2024-01-15",
             "hour_utc": 3}
    before = json.dumps(cover, sort_keys=True)
    block = _plan(cloud_cover=cover, seed=1)["clouds"]
    assert json.dumps(cover, sort_keys=True) == before          # the caller's dict is untouched
    assert block["cover_inputs"] == {"low": 1.0, "mid": 0.0, "high": 0.3, "total": 1.0}
    assert block["coverage_source"] == "s, 2024-01-15T03Z, cloud_cover_low/mid/high"
    # a missing level reads as 0 (recorded as 0), never a refusal
    sparse = _plan(cloud_cover={"low": 0.4}, seed=1)["clouds"]
    assert sparse["cover_inputs"] == {"low": 0.4, "mid": 0.0, "high": 0.0, "total": 0.0}
    assert sparse["cloud_type"] == "cumulus" and sparse["coverage"] == 0.4
    with pytest.raises(ValueError):
        _plan(cloud_cover={"low": float("nan"), "mid": 0.0, "high": 0.0, "total": 0.0}, seed=1)
    with pytest.raises(ValueError):
        _plan(cloud_cover={"low": "cloudy"}, seed=1)


# -- the provider ----------------------------------------------------------------------------

class _Response:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def test_the_provider_clamps_percent_refuses_a_negative_hour_and_a_missing_field(monkeypatch):
    def over_range(url, timeout):
        return _Response({"hourly": {"cloud_cover": [150] * 24, "cloud_cover_low": [-5] * 24,
                                     "cloud_cover_mid": [100] * 24, "cloud_cover_high": [0.5] * 24}})

    monkeypatch.setattr(era5.urllib.request, "urlopen", over_range)
    cover = era5.fetch_reanalysis_cloud_cover(40.7, -74.0, "2024-01-15", 0)
    assert cover["total"] == 1.0 and cover["low"] == 0.0 and cover["mid"] == 1.0 and cover["high"] == 0.005
    # the dict carries every key the plan reads, plus the provenance the plan copies
    assert set(clouds.CLOUD_COVER_KEYS) <= set(cover)
    assert {"source", "date", "hour_utc"} <= set(cover)
    assert cover["source"] == era5.CLOUD_COVER_SOURCE and "ERA5" in cover["source"]
    block = clouds.plan_cloud_block(storm=False, weather_date="2024-01-15", instant_utc="2024-01-15T00:00:00+00:00",
                                    lat=40.7, lon=-74.0, altitude_msl_m=600.0, cloud_cover=cover, seed=1)
    assert block["cloud_type"] == "overcast" and block["coverage"] == 1.0
    assert block["coverage_source"].startswith(era5.CLOUD_COVER_SOURCE) and "2024-01-15T00Z" in block["coverage_source"]
    with pytest.raises(era5.WeatherUnavailableError, match="not 0..23"):
        era5.fetch_reanalysis_cloud_cover(40.7, -74.0, "2024-01-15", -1)

    def missing_field(url, timeout):
        return _Response({"hourly": {"cloud_cover": [10] * 24}})

    monkeypatch.setattr(era5.urllib.request, "urlopen", missing_field)
    with pytest.raises(era5.WeatherUnavailableError, match="KeyError"):
        era5.fetch_reanalysis_cloud_cover(40.7, -74.0, "2024-01-15", 12)
    # the field order the archive is asked for is the order total/low/mid/high are read
    assert era5.CLOUD_COVER_FIELDS == ("cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high")


# -- render.json and the manifest -----------------------------------------------------------

def test_the_host_records_every_clouds_key_load_reads_and_only_the_pinned_set():
    """``FFlightSimSkyPlan::Load`` reads the step 2/5 keys with TryGet*; ApplyClouds
    writes each one it keeps under look_applied.world_beauty.clouds.plan. The record's
    key set is exactly PLAN_RECORD_KEYS (a new key is a contract change: add it here
    and in docs/VISUAL_FIDELITY_PLAN.md §8)."""
    load = _between(_read(SKY_CPP), "bool FFlightSimSkyPlan::Load(", "void FFlightSimSky::EnableRendererFeatures()")
    read_keys = set(re.findall(r'CloudsJson->TryGet\w+Field\(TEXT\("(\w+)"\)', load))
    assert read_keys == {"enabled", "cloud_type", "coverage", "density", "detail", "cirrus_coverage",
                         "coverage_source", "march_tier", "seed", "cover_inputs"}
    # sky step 6: cover_inputs only says whether the cover came from data
    # (bCloudCoverFromData); the cirrus record carries it, not the plan record
    read_keys -= {"cover_inputs"}
    apply = _between(_read(CPP), "void FFlightSimWorldBeauty::ApplyClouds(",
                     "void FFlightSimWorldBeauty::KeepAircraftClearOfClouds(")
    plan_out = _between(apply, "TSharedPtr<FJsonObject> PlanOut = MakeShared<FJsonObject>();",
                        'Out->SetObjectField(TEXT("plan"), PlanOut);')
    recorded = re.findall(r'PlanOut->Set\w+Field\(TEXT\("(\w+)"\)', plan_out)
    assert tuple(recorded) == PLAN_RECORD_KEYS
    assert read_keys - {"enabled"} <= set(recorded)       # enabled is the measure host's v1 key
    # the recorded field names are the plan's names (the Python writes them)
    assert (read_keys - {"enabled"}) <= set(GOLDEN_WITH_COVER)
    fields_source = re.search(r'sky\.json clouds \(([^)]*);', plan_out).group(1)
    assert set(k.strip() for k in fields_source.split(",")) == read_keys - {"enabled"}
    # the header's defaults are what a v1 plan records
    header = _read(SKY_H)
    for field in ("CloudType", "CloudCoverage", "CloudDensity", "CloudDetail", "CloudCirrusCoverage",
                  "CloudCoverageSource", "CloudSeed", "CloudMarchTier", "bCloudPlanFields", "bCloudSeedStated"):
        assert re.search(rf"\b{field}\b", header), field
        assert re.search(rf"\b{field}\b", load), field


def test_the_web_apps_run_conditions_name_the_type_cover_and_source():
    """The web app's manifest line (run.conditions["sky"]) gains the plan's cloud
    type, its cover to two places and its coverage_source, only when the plan has
    them (a plan written before step 5 still reads). The pinned call moved in
    step 5's repair round 1: write_sky_plan now passes the plan's INSTANT
    (``instant.utc``, so the archive is asked for its UTC date AND hour, not
    weather_date at the hour: 24 h off across the UTC day boundary) and the
    scene dict it already holds, instead of ``instant.utc.hour`` alone."""
    runs = _read(RUNS)
    line = _between(runs, 'run.conditions["sky"] = (', "# The beauty look (beauty quality only")
    assert "plan['clouds']['cloud_type']" in line
    assert "plan['clouds']['coverage']:.2f" in line
    assert "plan['clouds']['coverage_source']" in line
    assert 'if "cloud_type" in plan.get("clouds", {}) else ""' in line
    assert "clouds VISUAL ONLY" in line
    # the plan is written with the spec's seed and the fetched cover, encoded ASCII
    write = _between(runs, "def write_sky_plan(", "def historical_cloud_cover(")
    assert "cloud_cover=cover, cloud_cover_note=cover_note," in write
    assert "seed=int(spec.seed.value))" in write
    assert 'path.write_text(json.dumps(plan, indent=1), encoding="ascii")' in write
    assert "cover, cover_note = historical_cloud_cover(spec, instant.utc, scene=scene, push=push)" in write
    assert "historical_cloud_cover(spec, instant.utc.hour" not in write
    # the fetch never refuses the run: one except, one default
    fetch = _between(runs, "def historical_cloud_cover(", "def _projected_origin(")
    assert "except WeatherUnavailableError as exc:" in fetch
    assert 'return None, f"fetch failed: {exc}"' in fetch
    assert "raise" not in fetch.replace("raises", "")


# -- VerifyCloudMaterials ----------------------------------------------------------------------

def test_the_beauty_cloud_material_is_built_to_pass_verify_cloud_materials():
    """VerifyCloudMaterials refuses a cloud whose material is not Volume domain or
    not flagged used_with_volumetric_cloud, or that fails to compile. The beauty
    host swaps M_FlightSimCloudLayers onto every engine cloud, so the script must
    build it to pass: MD_VOLUME, the flag, additive, the multiple-scattering node
    (without it the engine's cloud shadow pass asserts, docs/WEATHER.md), and the
    host's path must be the script's asset."""
    script = _read(SCRIPT)
    builder = _between(script, "def create_world_cloud_layers(lit=False):", "\ndef ")
    assert 'material.set_editor_property("material_domain", unreal.MaterialDomain.MD_VOLUME)' in builder
    assert "material.set_editor_property(STORM_USAGE_PROPERTY, True)" in builder
    assert 'material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_ADDITIVE)' in builder
    assert "storm_scattering(material, lib," in builder
    assert 'STORM_USAGE_PROPERTY = "used_with_volumetric_cloud"' in script
    assert '"M_FlightSimCloudLayers"' in _between(script, "WORLD_BEAUTY_MATERIALS = (", ")")
    assert 'PATH = "/Game/FlightSim"' in script
    cpp = _read(CPP)
    assert ('const TCHAR* const WorldCloudMaterialPath =\n'
            '\t\tTEXT("/Game/FlightSim/M_FlightSimCloudLayers.M_FlightSimCloudLayers");') in cpp
    # the storm's own cloud keeps its own material and the same flag (the verify sees both)
    storm = _between(script, "def create_storm_cell", "def create_windshield_rain")
    assert 'material.set_editor_property("material_domain", unreal.MaterialDomain.MD_VOLUME)' in storm
    assert "material.set_editor_property(STORM_USAGE_PROPERTY, True)" in storm
    assert "M_StormCell kept" in cpp


def test_verify_cloud_materials_mirrors_the_engine_and_runs_after_the_beauty_swap():
    """The check's order is the engine's (VolumetricCloudRendering.cpp walks the
    fallback chain): no material is "draws nothing", not a refusal; then Volume
    domain, then the usage flag, then compile errors, then the shader map. The first
    bad cloud names the refusal (clouds.material). The commandlet runs it AFTER
    WorldBeauty.Build (so it sees the swapped material) and records every line
    under look_applied.cloud_materials; the interactive host runs it before its
    first frame. A missing M_FlightSimCloudLayers is NOT a refusal: ApplyClouds
    keeps the stock material, records why, and returns before any SetMaterial."""
    weather = _read(WEATHER_CPP)
    verify = _between(weather, "bool FFlightSimWeather::VerifyCloudMaterials(", "\n}\n")
    no_material = _between(verify, "if (Material == nullptr)", "else")
    assert 'Line += TEXT("no material (draws nothing)");' in no_material and "Why" not in no_material
    # (the log line prints the flag before the checks; the CHECKS are the if/else chain)
    order = [verify.index(s) for s in ("if (Base->MaterialDomain != MD_Volume)",
                                       "else if (!Base->GetUsageByFlag(MATUSAGE_VolumetricCloud))",
                                       "Resource->FinishCompilation();", "if (Resource->GetCompileErrors().Num() > 0)",
                                       "else if (Resource->GetGameThreadShaderMap() == nullptr)")]
    assert order == sorted(order)
    assert 'TEXT("clouds.material: the volumetric cloud %s of %s carries %s, which %s; ")' in verify
    assert "if (bOk)   // the first bad cloud names the refusal" in verify
    assert "if (Cloud->GetWorld() != World || !Cloud->IsRegistered())" in verify
    commandlet = _read(COMMANDLET)
    build = commandlet.index("WorldBeauty.Build(")
    check = commandlet.index("FFlightSimWeather::VerifyCloudMaterials(World, CloudError, &CloudReport)")
    assert build < check < commandlet.index("for (int32 i = 0; i < WarmupCaptures; ++i)")
    site = commandlet[check:check + 600]
    assert "return Fail(CloudError);" in site
    assert 'VisualScene.LookApplied->SetArrayField(TEXT("cloud_materials"), Lines);' in site
    assert "VerifyCloudMaterials(GetWorld(), Error)" in _read(INTERACTIVE)
    apply = _between(_read(CPP), "void FFlightSimWorldBeauty::ApplyClouds(",
                     "void FFlightSimWorldBeauty::KeepAircraftClearOfClouds(")
    missing = apply.index("M_FlightSimCloudLayers did not load (run scripts/ue_create_materials.py)")
    assert apply.index("LoadObject<UMaterialInterface>(nullptr, WorldCloudMaterialPath);") < missing
    assert missing < apply.index("Cloud->SetMaterial(State.Material);")
    missing_block = apply[apply.index("if (Base == nullptr)"):missing + 200]
    assert "return;" in missing_block and "UnmodelledClouds = CountWorldClouds();" in missing_block
    assert 'Record->SetObjectField(TEXT("clouds"), Out);' in missing_block


# -- the docs ----------------------------------------------------------------------------------

def test_the_step_7_docs_say_what_the_branch_carries_and_what_is_unmeasured():
    vfp = _read(VFP)
    entry = vfp[vfp.index("### Sky step 7"):]
    assert "UNMEASURED" in entry and "visual_fix_round.ps1" in entry
    assert "check_bridge_api.sh" in entry and "test_sky_step7_suite.py" in entry
    assert "1, 4 and 6" in entry        # steps not on the branch when this step was built
    design = _read(DESIGN)
    assert "Built (sky step 7" in design
