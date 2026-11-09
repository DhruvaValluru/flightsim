"""Hero lighting (core/scene/hero_lighting.py, FlightSimHeroLighting.cpp):
the per-shot lighting director, the sky-light ground sidecar, the web-app
and contact-sheet hooks, and source checks on the uncompiled C++ (the
authoring Mac cannot build UE 5.7)."""

import json
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.messages as messages
from core.environment import sun as sun_model
from core.scene import hero_lighting as hl

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge"
CPP = BRIDGE / "Private/FlightSimHeroLighting.cpp"
HEADER = BRIDGE / "Public/FlightSimHeroLighting.h"
COMMANDLET = BRIDGE / "Private/FlightSimRenderCommandlet.cpp"

#: The four contact-sheet places and dates (the compiled specs' own).
PLACES = {
    "golden_rim_backlight": (46.005, 7.72, date(2026, 3, 20)),     # Matterhorn
    "desert_cross_relief": (36.09, -112.0, date(2026, 7, 15)),     # Grand Canyon
    "storm_soft_sheen": (37.7275, -119.61, date(2026, 6, 21)),     # Yosemite
    "cockpit_canopy_glint": (46.005, 7.72, date(2026, 3, 20)),
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# -- the director --------------------------------------------------------------


@pytest.mark.parametrize("intent", sorted(hl.INTENTS))
def test_each_look_is_realised_within_a_degree(intent):
    lat, lon, day = PLACES[intent]
    solved = hl.solve(intent, lat, lon, day)
    row = hl.INTENTS[intent]
    assert abs(solved.elevation_error_deg) < 0.2
    # The heading is an integer degree, so half a degree plus rounding.
    assert abs(solved.relative_azimuth_error_deg) <= 0.6
    assert solved.date == day.isoformat()
    assert solved.time_of_day.startswith(day.isoformat() + "T")
    assert solved.time_of_day.endswith("Z")
    assert 0 <= solved.heading_deg < 360
    assert solved.wanted_elevation_deg == row.elevation_deg
    assert "no second sun" in solved.basis


@pytest.mark.parametrize("intent", sorted(hl.INTENTS))
def test_recorded_sun_is_the_sun_the_renderer_resolves(intent):
    """The web app's sun_look strips the date and resolves the clock on it."""
    lat, lon, day = PLACES[intent]
    solved = hl.solve(intent, lat, lon, day)
    clock = solved.time_of_day.split("T", 1)[1]
    placed = sun_model.resolve(clock, lat, lon, day)
    assert placed.elevation_deg == pytest.approx(solved.sun_elevation_deg, abs=1e-3)
    assert placed.azimuth_deg == pytest.approx(solved.sun_azimuth_deg, abs=1e-3)


@pytest.mark.parametrize("intent", sorted(hl.INTENTS))
def test_sky_plan_and_validator_read_the_solved_clock(intent):
    from core.sky.plan import resolve_instant

    lat, lon, day = PLACES[intent]
    solved = hl.solve(intent, lat, lon, day)
    instant = resolve_instant(solved.time_of_day, None, lat, lon)
    assert instant.utc.strftime("%Y-%m-%dT%H:%M") == solved.when_utc[:16]


def test_golden_rim_is_a_setting_backlight_and_cockpit_is_behind():
    lat, lon, day = PLACES["golden_rim_backlight"]
    rim = hl.solve("golden_rim_backlight", lat, lon, day)
    assert rim.sun_azimuth_deg > 180.0          # an evening (western) sun
    assert abs(rim.relative_azimuth_deg) < 90   # ahead of the lens: backlight
    glint = hl.solve("cockpit_canopy_glint", lat, lon, day)
    assert abs(glint.relative_azimuth_deg) > 90  # behind the pilot
    desert = hl.solve("desert_cross_relief", *PLACES["desert_cross_relief"])
    assert desert.sun_azimuth_deg < 180.0       # a morning sun
    assert desert.relative_azimuth_deg == pytest.approx(90.0, abs=0.6)


def test_camera_yaw_offset_moves_the_heading_not_the_sun():
    lat, lon, day = PLACES["desert_cross_relief"]
    plain = hl.solve("desert_cross_relief", lat, lon, day)
    offset = hl.solve("desert_cross_relief", lat, lon, day, camera_yaw_offset_deg=30.0)
    assert offset.time_of_day == plain.time_of_day
    assert (plain.heading_deg - offset.heading_deg) % 360 == 30


def test_unknown_look_refuses_by_name():
    with pytest.raises(hl.HeroLightingError) as caught:
        hl.solve("rembrandt", 46.0, 7.7, date(2026, 3, 20))
    assert caught.value.constraint == "hero_lighting.intent"


def test_unreachable_elevation_refuses_by_name():
    # A 35 deg sun in the high Arctic in midwinter does not happen.
    with pytest.raises(hl.HeroLightingError) as caught:
        hl.solve("cockpit_canopy_glint", 78.2, 15.6, date(2026, 12, 21))
    assert caught.value.constraint == "hero_lighting.unreachable"


def test_bad_direction_refuses():
    with pytest.raises(hl.HeroLightingError):
        hl.solve_time(46.0, 7.7, date(2026, 3, 20), 10.0, "sideways")


def test_refusal_names_are_catalogued():
    for name in ("hero_lighting.intent", "hero_lighting.unreachable", "hero_lighting.sidecar"):
        assert messages.is_catalogued(name), name


def test_scene_day_keeps_the_preset_season():
    assert hl.scene_day("2026-07-15T12:00") == date(2026, 7, 15)
    assert hl.scene_day("golden hour") == sun_model.DEFAULT_DATE
    assert hl.scene_day(None) == sun_model.DEFAULT_DATE


@pytest.mark.parametrize("prompt,expected", [
    ("chase view of the j11 at 3000 m over the matterhorn at golden hour, flying east, "
     "for 6 seconds",
     "chase view of the j11 at 3000 m over the matterhorn at golden hour, heading 229 "
     "for 6 seconds"),
    ("chase view of the j11 at 1600 m over the desert, flying southwest, for 6 seconds",
     "chase view of the j11 at 1600 m over the desert, heading 229 for 6 seconds"),
    ("cockpit view of the j11 at 3000 m, heading 090 for 6 seconds",
     "cockpit view of the j11 at 3000 m, heading 229 for 6 seconds"),
    ("chase view of the j11 over the forest", "chase view of the j11 over the forest, heading 229"),
])
def test_with_heading_replaces_any_direction(prompt, expected):
    assert hl.with_heading(prompt, 229) == expected


def test_apply_to_spec_changes_only_the_time_of_day():
    spec = {"initial": {"heading": {"value": 90.0}}, "environment": {"surface": {"value": "x"}}}
    solved = hl.solve("golden_rim_backlight", *PLACES["golden_rim_backlight"])
    out = hl.apply_to_spec(spec, solved)
    assert out["environment"]["time_of_day"]["value"] == solved.time_of_day
    assert out["environment"]["time_of_day"]["source"] == "user"
    assert out["initial"] == spec["initial"]
    assert "time_of_day" not in spec["environment"]          # not mutated
    assert "weather_date" not in out["environment"]          # ERA5 winds stay off


# -- the sidecar ---------------------------------------------------------------


def test_sidecar_is_lambertian_and_pure():
    one = hl.plan_sidecar(surface="desert", sun_elevation_deg=16.0, horizontal_lux=30000.0,
                          raining=False)
    two = hl.plan_sidecar(surface="desert", sun_elevation_deg=16.0, horizontal_lux=30000.0,
                          raining=False)
    assert one == two
    albedo = hl.GROUND_ALBEDO_RGB["desert"]
    lum = one["ground"]["lower_hemisphere_luminance_rgb"]
    assert lum[0] == pytest.approx(albedo[0] * 30000.0 / 3.141592653589793, abs=1e-2)
    assert one["hero_lighting_version"] == hl.HERO_LIGHTING_VERSION
    assert "GROUND_ALBEDO_RGB" in one["uncalibrated"]


def test_sidecar_rain_dims_the_ground_and_unknown_surface_falls_back():
    dry = hl.plan_sidecar(surface="forest", sun_elevation_deg=28.0, horizontal_lux=50000.0,
                          raining=False)
    wet = hl.plan_sidecar(surface="forest", sun_elevation_deg=28.0, horizontal_lux=50000.0,
                          raining=True)
    assert wet["ground"]["horizontal_lux"] == pytest.approx(
        dry["ground"]["horizontal_lux"] * hl.OVERCAST_ILLUMINANCE_FRACTION)
    odd = hl.plan_sidecar(surface="lava", sun_elevation_deg=10.0, horizontal_lux=None,
                          raining=False)
    assert odd["ground"]["albedo_rgb"] == list(hl.GROUND_ALBEDO_RGB["unspecified"])
    assert odd["ground"]["horizontal_lux"] > 0


def _spec(surface="desert", rate=0.0):
    value = lambda v: SimpleNamespace(value=v)  # noqa: E731
    return SimpleNamespace(surface=value(surface), precipitation_rate_mmh=value(rate),
                           terrain_elevation=value(1200.0),
                           time_of_day=SimpleNamespace(value="x", frm="hero lighting director"))


def test_measure_gets_no_sidecar_and_no_token(tmp_path):
    assert hl.write_sidecar_beside(_spec(), None) is None
    assert hl.flags_beside(None) == []
    # Beauty look present but no sidecar written: still no token.
    look = tmp_path / "beauty_look.json"
    look.write_text("{}", encoding="utf-8")
    assert hl.flags_beside(look) == []


def test_beauty_writes_the_sidecar_beside_the_look_and_names_it(tmp_path):
    look = tmp_path / "beauty_look.json"
    look.write_text(json.dumps({"sun_elevation_deg": 16.0, "grade": "golden",
                                "exposure": {"meter_horizontal_lux_reference": 30000.0}}),
                    encoding="utf-8")
    path = hl.write_sidecar_beside(_spec(rate=2.0), look)
    assert path == tmp_path / hl.SIDECAR_NAME
    plan = json.loads(path.read_text(encoding="utf-8"))
    assert plan["ground"]["surface"] == "desert"
    assert "under rain" in plan["ground"]["horizontal_lux_basis"]
    assert plan["time_of_day_basis"] == "hero lighting director"
    path.read_text(encoding="ascii")                         # ASCII only
    assert hl.flags_beside(look) == [f"{hl.HERO_LIGHTING_PREFIX}{path.resolve()}"]


def test_webapp_hooks_are_gated_on_the_beauty_look():
    source = _read(ROOT / "webapp/runs.py")
    assert "extra += flags_beside(beauty_look)" in source
    hook = source.index("write_sidecar_beside(spec, beauty_look)")
    assert "if beauty_look is not None:" in source[hook - 200:hook]


# -- the contact sheet ---------------------------------------------------------


def test_every_contact_sheet_shot_names_a_known_look():
    import experiments.visual_contact_sheet as sheet

    looks = {key: sheet.SHOTS[key].lighting for key in sheet.SHOT_ORDER}
    assert looks == {"a": "golden_rim_backlight", "b": "desert_cross_relief",
                     "c": "storm_soft_sheen", "d": "cockpit_canopy_glint"}
    assert all(look in hl.INTENTS for look in looks.values())


class _Reply:
    def __init__(self, code, payload):
        self.status_code, self._payload = code, payload

    def json(self):
        return self._payload


def test_light_shot_recompiles_with_the_heading_and_dates_the_clock():
    import experiments.visual_contact_sheet as sheet

    prompts = []

    class Client:
        def post(self, path, json=None):
            assert path == "/compile"
            prompts.append(json["prompt"])
            heading = float(re.search(r"heading (\d{3})", json["prompt"]).group(1))
            return _Reply(200, {"spec": {"dict": {
                "initial": {"latitude": {"value": 36.09}, "longitude": {"value": -112.0},
                            "heading": {"value": heading}},
                "environment": {"time_of_day": {"value": "2026-07-15T12:00"}}}},
                "validation": {"ok": True}})

    first = {"spec": {"dict": {
        "initial": {"latitude": {"value": 36.09}, "longitude": {"value": -112.0}},
        "environment": {"time_of_day": {"value": "2026-07-15T12:00"}}}}}
    body = {"prompt": sheet.SHOTS["b"].prompt, "compiler": "regex", "environment": "desert"}
    payload, record = sheet.light_shot(Client(), body, first, "desert_cross_relief")
    solved = hl.solve("desert_cross_relief", 36.09, -112.0, date(2026, 7, 15))
    assert prompts == [hl.with_heading(body["prompt"], solved.heading_deg)]
    assert "southwest" not in prompts[0]
    assert payload["spec"]["dict"]["environment"]["time_of_day"]["value"] == solved.time_of_day
    assert record["heading_compiled_deg"] == solved.heading_deg
    assert record["time_of_day"] == solved.time_of_day


def test_light_shot_refuses_by_name():
    import experiments.visual_contact_sheet as sheet

    first = {"spec": {"dict": {
        "initial": {"latitude": {"value": 78.2}, "longitude": {"value": 15.6}},
        "environment": {"time_of_day": {"value": "2026-12-21T12:00"}}}}}
    with pytest.raises(sheet.ShotRefused, match="hero_lighting.unreachable"):
        sheet.light_shot(None, {"prompt": "x"}, first, "cockpit_canopy_glint")


# -- the engine side (source checks: the Mac cannot compile UE 5.7) -------------


def test_cpp_never_adds_or_moves_a_light():
    source = _read(CPP)
    for banned in ("SpawnActor", "NewObject", "SetWorldRotation", "SetActorRotation",
                   "SetRelativeRotation", "AddComponent", "SetIntensity("):
        assert banned not in source, banned


def test_cpp_physics_and_uncalibrated_constants():
    source = _read(CPP)
    assert "HeroLightingSunDiscAngleDeg = 0.5357f" in source
    constants = re.findall(r"constexpr \w+ (HeroLighting\w+) =", source)
    assert len(constants) >= 15
    # Every tuned value names its probe (hl-*), except the stated physics.
    for name in constants:
        block = source[:source.index(f"{name} =")]
        tail = block[-700:]
        assert "UNCALIBRATED" in tail or "PHYSICS" in tail or name == "HeroLightingSidecarVersion" \
            or "cvar's own help text" in tail, name
    probes = set(re.findall(r"probe (hl-[a-z]+)", source))
    log = _read(ROOT / "docs/visual/PROBE_LOG.md")
    for probe in probes:
        assert probe in log, probe


def test_cpp_cvars_are_in_the_bridge_check():
    source = _read(CPP)
    check = _read(ROOT / "scripts/check_bridge_api.sh")
    block = check[check.index("BEGIN hero lighting"):check.index("END hero lighting")]
    for cvar in re.findall(r'HeroLightingCvar\(TEXT\("([^"]+)"\)', source):
        assert f"hl_cvar {cvar} " in block, cvar
    # Every engine setter on the sun and the sky light is re-checked there.
    for setter in set(re.findall(r"\b(?:SunLight|Sky)->(Set\w+)\(", source)):
        assert setter in block, setter


def test_cpp_label_exclusion_is_a_noop_before_apply():
    source = _read(CPP)
    body = source[source.index("void FFlightSimHeroLighting::ExcludeFromLabel"):]
    body = body[:body.index("\n}\n")]
    assert "!HeroLightingState().bApplied" in body
    assert "SetLightShafts(false)" in body and "SetContactShadows(false)" in body


def test_cpp_records_no_pixel_moving_effect_and_refuses_by_name():
    source = _read(CPP)
    assert 'TEXT("pixel_moving_effects"), TArray<TSharedPtr<FJsonValue>>()' in source
    assert 'TEXT("hero_lighting.sidecar: %s")' in source
    assert "IsRayTracingEnabled()" in source           # hit lighting only with RT
    assert "software fallback" in source


def test_cpp_anonymous_names_are_unique_to_this_file():
    source = _read(CPP)
    names = set(re.findall(r"\b(HeroLighting\w+)\b", source))
    others = [p for p in (BRIDGE / "Private").glob("*.cpp") if p.name != CPP.name]
    for other in others:
        text = _read(other)
        for name in names:
            assert re.search(rf"\b{name}\b", text) is None, (name, other.name)


def test_commandlet_hooks_are_small_and_beauty_gated():
    source = _read(COMMANDLET)
    lines = [line for line in source.splitlines() if "FFlightSimHeroLighting" in line
             or "FlightSimHeroLighting.h" in line]
    assert 1 <= len(lines) <= 5
    apply = next(line for line in lines if "::Apply(" in line)
    assert "bVisual && bBeauty" in apply
    assert any("ExcludeFromLabel(Label)" in line for line in lines)
    assert any("::Record()" in line and '"hero_lighting"' in line for line in lines)


def test_header_declares_what_the_commandlet_calls():
    header = _read(HEADER)
    for symbol in ("static bool Apply(", "static void ExcludeFromLabel(",
                   "static TSharedPtr<FJsonObject> Record()", "static const FString& LastError()"):
        assert symbol in header, symbol
