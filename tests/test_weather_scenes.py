"""Visual round 2, the weather scenes (2026-11-10): what must hold without an
engine for the three round-1 failures.

* #09 "747 through a thunderstorm" was a flat blue frame: the 747 flew at
  2000 m, 350 m behind the microburst the storm cell is centred on, inside the
  0.19 /m tower and the look's 1200-2700 m storm deck. Its body was gone; only
  its translucent nav lights were drawn over the cloud (two dots 880 px apart
  in a 1280 px frame: the aircraft was framed, it was buried). The beauty frame
  now DRAWS the cell ahead of the clip's track and its deck above the aircraft,
  and rains on the aircraft (storm_cell.beauty_vantage_shift_m,
  world_beauty.aircraft_clear_layer; FFlightSimWeather::ApplyBeautyStormVantage).
* #07 "tower view, heavy rain" was a flat grey frame: the A320 at 1000 m flew
  inside the commandlet's 800-3000 m rain deck (0.045 /m nimbostratus): every
  redrawn beauty deck now moves clear of the aircraft
  (FFlightSimWorldBeauty::KeepAircraftClearOfClouds).
* #08 "C172 over Fuji, sunrise, light rain" was blown white: the beauty
  exposure was opened two stops for a deck that 1 mm/h rain never draws
  (beauty_look.deck_drawn_for_card), and the meter could only open; a beauty
  meter now also closes a CLIPPING frame (the highlight guard).

The measure quality must stay byte-identical: every new path is beauty-only
and every new number defaults to "no change".
"""

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core.scene import beauty_look as bl
from core.scene import storm_cell
from core.scene import world_beauty as wb

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
CLOUDS_CPP = (SOURCE / "Private" / "FlightSimClouds.cpp").read_text(encoding="utf-8")
CLOUDS_H = (SOURCE / "Public" / "FlightSimClouds.h").read_text(encoding="utf-8")
WEATHER_CPP = (SOURCE / "Private" / "FlightSimWeather.cpp").read_text(encoding="utf-8")
WEATHER_H = (SOURCE / "Public" / "FlightSimWeather.h").read_text(encoding="utf-8")
RENDER_CPP = (SOURCE / "Private" / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
NEEDS_CXX = pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler on this machine")


def _block(text, begin, end):
    return text[text.index(begin) + len(begin):text.index(end)]


def _function(text, signature):
    """The body of a C++ function from its signature to the matching brace."""
    start = text.index(signature)
    open_at = text.index("{", start)
    depth = 0
    for index in range(open_at, len(text)):
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        if depth == 0:
            return text[start:index + 1]
    raise ValueError(signature)


def _compile_and_run(tmp_path, source_text):
    source = tmp_path / "pure.cpp"
    source.write_text(source_text, encoding="utf-8")
    binary = tmp_path / "pure"
    # -Wall -Werror as the world lane's test, less the unused-constant warnings: this
    # main reads only the functions under test, not every constant of the block.
    subprocess.run(["g++", "-std=c++17", "-O1", "-Wall", "-Werror", "-Wno-unused-const-variable",
                    "-Wno-unused-function", "-o", str(binary), str(source)],
                   check=True, capture_output=True, text=True)
    return subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout.splitlines()


# -- the deck kept clear of the aircraft (#07, #09's deck, #06) -------------------


def test_round_one_tower_view_deck_moves_above_the_a320():
    # #07: the commandlet's rain deck (cover 0.98, 800-3000 m) around an A320 at 1000 m.
    out = wb.aircraft_clear_layer(800.0, 3000.0, 1000.0, rain_deck=True)
    assert out["moved"] and out["above"]
    assert out["base_m"] == 1000.0 + wb.AIRCRAFT_LAYER_CLEARANCE_M
    assert out["top_m"] - out["base_m"] == pytest.approx(2200.0)     # thickness kept
    # #06: an A320 at 3000 m at the same deck's top: below the deck, in its rain.
    out = wb.aircraft_clear_layer(800.0, 3000.0, 3000.0, rain_deck=True)
    assert out["moved"] and out["above"] and out["base_m"] == 3400.0


def test_a_deck_well_clear_of_the_aircraft_stays_where_the_card_puts_it():
    for z in (0.0, 300.0, 3400.1, 10000.0):
        out = wb.aircraft_clear_layer(800.0, 3000.0, z, rain_deck=True)
        assert not out["moved"] and (out["base_m"], out["top_m"]) == (800.0, 3000.0), z
    assert not wb.aircraft_clear_layer(1000.0, 1000.0, 1000.0)["moved"]   # an empty slab


def test_a_fair_weather_deck_moves_to_the_nearer_side():
    below = wb.aircraft_clear_layer(1500.0, 2500.0, 2300.0)          # the upper half
    assert below["moved"] and not below["above"]
    assert below["top_m"] == 1900.0 and below["base_m"] == 900.0
    above = wb.aircraft_clear_layer(1500.0, 2500.0, 1700.0)          # the lower half
    assert above["above"] and above["base_m"] == 2100.0
    # Never pushed under the ground: an aircraft too low for "below" goes under the deck.
    low = wb.aircraft_clear_layer(0.0, 2000.0, 300.0)
    assert low["above"] and low["base_m"] == 700.0


@NEEDS_CXX
def test_the_cpp_deck_clearance_is_the_python_one(tmp_path):
    block = _block(CLOUDS_CPP, "// FLIGHTSIM-WORLD-PURE-BEGIN", "// FLIGHTSIM-WORLD-PURE-END")
    cases = [(b, t, z, r) for b, t in ((800.0, 3000.0), (1200.0, 2700.0), (0.0, 2000.0), (1500.0, 1500.0))
             for z in (0.0, 300.0, 799.0, 1000.0, 1900.0, 2300.0, 3000.0, 3400.0, 3401.0, 9000.0)
             for r in (0, 1)]
    main = ["using namespace FlightSimWorldPure;", "int main() {",
            "printf(\"clear %.17g\\n\", AircraftLayerClearanceM);"]
    for b, t, z, r in cases:
        main.append(f"{{ FLayerClear C = AircraftClearLayer({b!r}, {t!r}, {z!r}, AircraftLayerClearanceM, "
                    f"{'true' if r else 'false'}); printf(\"row %.17g %.17g %d %d\\n\", C.BaseM, C.TopM, "
                    "C.bMoved ? 1 : 0, C.bAbove ? 1 : 0); }")
    main.append("return 0; }")
    lines = _compile_and_run(tmp_path, "#include <cmath>\n#include <cstdint>\n#include <cstdio>\n"
                             "#include <cstring>\n" + block + "\n" + "\n".join(main))
    assert float(lines[0].split()[1]) == wb.AIRCRAFT_LAYER_CLEARANCE_M
    rows = [line.split()[1:] for line in lines if line.startswith("row ")]
    assert len(rows) == len(cases)
    for (b, t, z, r), (base, top, moved, above) in zip(cases, rows):
        ref = wb.aircraft_clear_layer(b, t, z, rain_deck=bool(r))
        assert (float(base), float(top), bool(int(moved)), bool(int(above))) == (
            ref["base_m"], ref["top_m"], ref["moved"], ref["above"]), (b, t, z, r)


def test_the_world_lane_keeps_every_redrawn_deck_clear_and_records_it():
    build = _function(CLOUDS_CPP, "bool FFlightSimWorldBeauty::Build(")
    clouds_at = build.index("ApplyClouds(World, Scene, Weather")
    clear_at = build.index("KeepAircraftClearOfClouds(Card, Aircraft, Weather);")
    assert clouds_at < clear_at < build.index("ApplyTiles(World, Tiles, CardWetness);")
    body = _function(CLOUDS_CPP, "void FFlightSimWorldBeauty::KeepAircraftClearOfClouds(")
    # the aircraft's height above the datum, the frame of the decks and the cell
    assert 'WorldNumber(Card, TEXT("altitude_m"), 0.0)' in body
    assert 'WorldNumber(Card, TEXT("terrain_elevation_m"), 0.0)' in body
    assert "Preset == PresetRain || Preset == PresetStorm" in body
    # the drawn slab and the occlusion row's slab move together
    for needle in ("SetLayerBottomAltitude(static_cast<float>(Clear.BaseM / 1000.0))",
                   "SetLayerHeight(static_cast<float>((Clear.TopM - Clear.BaseM) / 1000.0))",
                   "State.BaseM = Clear.BaseM;", "State.TopM = Clear.TopM;",
                   'Record->SetObjectField(TEXT("aircraft_clearance"), Out);'):
        assert needle in body, needle
    assert "void KeepAircraftClearOfClouds(const TSharedPtr<FJsonObject>& Card, AActor* Aircraft," in CLOUDS_H


# -- the storm drawn ahead of the track (#09) --------------------------------------


def _round_one_747_cell():
    """The 747 thunderstorm card's cell: 1000 m microburst core, latitude 37."""
    return storm_cell.card_block(1000.0, 37.6, 0.0, 270.0, 0.0, None, 1234)


def _track_clearance(shift, start, heading_deg, track, centre_radius):
    """The closest the track comes to the moved centre, less the tower's radius."""
    h = math.radians(heading_deg)
    de, dn = math.sin(h), math.cos(h)
    cx, cy = shift * de, shift * dn
    best = math.inf
    for i in range(201):
        s = track * i / 200.0
        px, py = start[0] + s * de, start[1] + s * dn
        best = min(best, math.hypot(px - cx, py - cy))
    return best - centre_radius


def test_round_one_747_is_inside_the_tower_and_the_vantage_moves_it_out():
    cell = _round_one_747_cell()
    airspeed = 250.0 * 1852.0 / 3600.0
    track = airspeed * 6.0
    ahead = 0.45 * track                                    # webapp severe_event_centre
    start = (ahead, 0.0)                                    # flying west, the centre ahead
    up = 2000.0
    radius = storm_cell.tower_radius_at(cell, up)
    assert math.hypot(*start) < radius                      # round 1: the start is inside the tower
    shift = storm_cell.beauty_vantage_shift_m(start[0], start[1], 270.0, track, up, cell["base_m"],
                                              cell["top_m"], cell["overshoot_m"], cell["tower_radius_m"])
    assert shift > 0.0
    clearance = _track_clearance(shift, start, 270.0, track, radius)
    assert clearance == pytest.approx(storm_cell.BEAUTY_VANTAGE_CLEARANCE_M, abs=1.0)


def test_a_track_already_clear_of_the_tower_moves_nothing():
    cell = _round_one_747_cell()
    args = (cell["base_m"], cell["top_m"], cell["overshoot_m"], cell["tower_radius_m"])
    # "a thunderstorm 12 km ahead": the clip never reaches the tower
    assert storm_cell.beauty_vantage_shift_m(12000.0, 0.0, 270.0, 772.0, 2000.0, *args) == 0.0
    # abeam, farther than the tower and the clearance
    assert storm_cell.beauty_vantage_shift_m(0.0, 6000.0, 270.0, 772.0, 2000.0, *args) == 0.0
    # flying away from a tower already behind
    assert storm_cell.beauty_vantage_shift_m(-6000.0, 0.0, 270.0, 772.0, 2000.0, *args) == 0.0
    # under the base (in the shaft's rain, no cloud) and over the overshooting top
    assert storm_cell.beauty_vantage_shift_m(300.0, 0.0, 270.0, 772.0, 500.0, *args) == 0.0
    over = cell["top_m"] + cell["overshoot_m"] + storm_cell.EDGE_M + 1.0
    assert storm_cell.beauty_vantage_shift_m(300.0, 0.0, 270.0, 772.0, over, *args) == 0.0


@NEEDS_CXX
def test_the_cpp_vantage_is_the_python_one(tmp_path):
    body = _function(WEATHER_CPP, "double FFlightSimWeather::BeautyVantageShiftM(")
    body = body.replace("FFlightSimWeather::", "")
    shim = """
#include <cmath>
#include <cstdio>
struct FMath {
    static double Max(double A, double B) { return A > B ? A : B; }
    static double Min(double A, double B) { return A < B ? A : B; }
    static double Clamp(double V, double L, double H) { return V < L ? L : (V > H ? H : V); }
    static double Abs(double V) { return std::fabs(V); }
    static double Sqrt(double V) { return std::sqrt(V); }
    static double Sin(double V) { return std::sin(V); }
    static double Cos(double V) { return std::cos(V); }
    static double DegreesToRadians(double V) { return V * (3.14159265358979323846 / 180.0); }
};
"""
    cell = _round_one_747_cell()
    geo = (cell["base_m"], cell["top_m"], cell["overshoot_m"], cell["tower_radius_m"])
    cases = [(e, n, h, t, z) for e, n in ((347.0, 0.0), (0.0, -347.0), (200.0, 900.0), (12000.0, 0.0),
                                          (-6000.0, 0.0), (0.0, 6000.0), (1500.0, -1500.0))
             for h in (0.0, 90.0, 225.0, 270.0) for t in (0.0, 772.0) for z in (500.0, 2000.0, 9000.0)]
    main = ["int main() {"]
    for e, n, h, t, z in cases:
        main.append(f"printf(\"%.17g\\n\", BeautyVantageShiftM({e!r}, {n!r}, {h!r}, {t!r}, {z!r}, "
                    f"{geo[0]!r}, {geo[1]!r}, {geo[2]!r}, {geo[3]!r}, 2500.0));")
    main.append("return 0; }")
    lines = _compile_and_run(tmp_path, shim + body + "\n" + "\n".join(main))
    for (e, n, h, t, z), line in zip(cases, lines):
        ref = storm_cell.beauty_vantage_shift_m(e, n, h, t, z, *geo, clearance_m=2500.0)
        assert float(line) == pytest.approx(ref, rel=1e-12, abs=1e-9), (e, n, h, t, z)


def test_the_cpp_vantage_constants_are_the_pythons():
    shift = _function(WEATHER_CPP, "double FFlightSimWeather::BeautyVantageShiftM(")
    assert f"constexpr double WeatherVantageTowerFlare = {storm_cell.TOWER_FLARE};" in shift
    assert f"constexpr double WeatherVantageEdgeM = {storm_cell.EDGE_M};" in shift
    apply = _function(WEATHER_CPP, "void FFlightSimWeather::ApplyBeautyStormVantage(")
    assert (f"constexpr double WeatherBeautyVantageClearanceM = {storm_cell.BEAUTY_VANTAGE_CLEARANCE_M};"
            in apply)
    assert f"constexpr double WeatherBeautyRainShareFloor = {storm_cell.BEAUTY_RAIN_SHARE_FLOOR};" in apply


def test_the_vantage_moves_what_is_drawn_and_never_the_physics():
    apply = _function(WEATHER_CPP, "void FFlightSimWeather::ApplyBeautyStormVantage(")
    assert 'SetVectorParameterValue(TEXT("CellCentreCm"), WeatherColour(CentreEngineCm + BeautyCellOffsetCm))' \
        in apply
    assert "LightningActor->SetActorLocation(LightningActor->GetActorLocation() + BeautyCellOffsetCm);" in apply
    assert 'SetVectorParameterValue(TEXT("Layer")' in apply
    # the physics' frame and the downburst are never touched
    for forbidden in ("CentreEngineCm =", "Downburst.", "CentreNorthMetres =", "CentreEastMetres ="):
        assert forbidden not in apply, forbidden
    # the bolts' light and the flash's lux follow the drawn cell
    assert "FlashLight->SetWorldLocation(EnuToEngineCm(Best->CentroidEnu) + BeautyCellOffsetCm);" in WEATHER_CPP
    assert "EnuToEngineCm(Flash.CentroidEnu) + BeautyCellOffsetCm" in WEATHER_CPP
    # the rain floor
    assert "const double Share = FMath::Max(ShaftShare(CameraEnu), BeautyRainShareFloor);" in WEATHER_CPP


def test_the_vantage_is_beauty_only_and_off_by_default():
    # defaults that draw exactly what the measure path drew
    assert "FVector BeautyCellOffsetCm = FVector::ZeroVector;" in WEATHER_H
    assert "double BeautyRainShareFloor = 0.0;" in WEATHER_H
    # only the world lane (built under -quality=beauty only) calls it
    assert "ApplyBeautyStormVantage(" not in RENDER_CPP
    assert CLOUDS_CPP.count("Weather.ApplyBeautyStormVantage(") == 1
    keep = _function(CLOUDS_CPP, "void FFlightSimWorldBeauty::KeepAircraftClearOfClouds(")
    assert "Weather.ApplyBeautyStormVantage(" in keep
    assert "AircraftClearLayer(LayerBaseM, LayerTopM, AircraftUpM, AircraftLayerClearanceM, true)" in keep
    assert "if (bBeauty && !WorldBeauty.Build(" in RENDER_CPP


# -- the exposure (#08) -------------------------------------------------------------


def _card(rain=None, look_rain=None, storm=None, layer=None):
    card = {"look": {}, "weather_look": {}}
    if look_rain is not None:
        card["look"].update(precipitation="rain", precipitation_rate_mmh=look_rain)
    if rain is not None:
        card["weather_look"]["rain_rate_mmh"] = rain
    if storm is not None:
        card["weather_look"]["storm"] = storm
    if layer is not None:
        card["look"]["clouds"] = [layer]
    return card


def test_light_rain_draws_no_deck_and_heavy_rain_does():
    assert bl.deck_drawn_for_card(_card(rain=1.0)) is False             # round 1's Fuji sunrise
    assert bl.deck_drawn_for_card(_card(rain=bl.RAIN_DECK_MIN_MMH)) is True
    assert bl.deck_drawn_for_card(_card(look_rain=12.0)) is True
    assert bl.deck_drawn_for_card(_card(storm="thunderstorm")) is True
    assert bl.deck_drawn_for_card(_card(storm="tornado")) is True      # a storm keeps its exposure
    assert bl.deck_drawn_for_card(_card(layer={"cover": 0.9, "base_m": 800.0, "top_m": 2000.0})) is True
    assert bl.deck_drawn_for_card(_card(rain=1.0, layer={"cover": 0.3, "base_m": 800.0,
                                                         "top_m": 2000.0})) is False
    # the same rain deck threshold the commandlet draws from
    assert f"constexpr double RainDeckMinMmh = {bl.RAIN_DECK_MIN_MMH};" in RENDER_CPP


def test_round_one_fuji_sunrise_is_no_longer_opened_for_a_missing_deck():
    # #08's look: sun 3.18 deg, rain look sun x0.6 and fill x1.3, terrain at 1465 m.
    kw = dict(fps=30, width_px=1920, world_preset="rain", altitude_m=1465.0,
              sun_intensity_scale=0.6, sky_light_scale=1.3, brightness_ev=-0.2)
    before = bl.plan_beauty_look(3.18, **kw)["exposure"]
    after = bl.plan_beauty_look(3.18, deck_drawn=False, **kw)["exposure"]
    assert before["scene_light_stops"] == pytest.approx(math.log2(0.25), abs=1e-3)
    assert after["scene_light_stops"] > -0.5          # the open sky's light, not a deck's
    assert after["ev100"] - before["ev100"] > 1.5     # about two stops less exposure
    assert after["meter"]["deck"] is False
    assert after["meter"]["target_p90_luma"] == bl.EXPOSURE_METER_TARGET_P90["no_lumen_gi"]
    assert "no deck drawn" in after["scene_light_basis"]
    # a drawn deck (or no card at all) keeps the round-2 exposure exactly
    assert bl.plan_beauty_look(3.18, deck_drawn=True, **kw)["exposure"] == before


def test_the_web_app_hands_the_drawn_deck_to_the_beauty_look(tmp_path, monkeypatch):
    import webapp.runs as runs
    from core.nl.compiler import compile_prompt

    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "beauty")
    spec = compile_prompt("chase view of the c172p at 3000 m in light rain for 6 seconds")
    for rate, deck in ((1.0, False), (10.0, True)):
        (tmp_path / "card.json").write_text(json.dumps(_card(rain=rate)), encoding="utf-8")
        path = runs.write_beauty_look_plan(spec, tmp_path, {"sun_elev": 3.18})
        exposure = json.loads(path.read_text(encoding="utf-8"))["exposure"]
        assert exposure["world_preset"] == "rain"
        assert exposure["meter"]["deck"] is deck, rate


def test_the_beauty_meter_closes_only_a_clipping_frame():
    loop = RENDER_CPP[RENDER_CPP.index("if ((Weather.DrawsCell() || bBeautyMeter) && !bAutoExposure)"):]
    loop = loop[:loop.index("StormMeterOpened = Opened;")]
    # beauty only: measure keeps the open-only meter
    assert "const bool bMeterMayClose = bVisual && bBeauty;" in loop
    assert "const bool bBlown = bMeterMayClose && Bright > BeautyMeterHighlightP90;" in loop
    # a frame that is merely bright is never closed: the floor is 0 or where it stands
    assert "const double Lowest = bBlown ? -BeautyMeterMaxCloseStops : FMath::Min(0.0, Opened);" in loop
    assert "const double Next = FMath::Clamp(Opened + Step, Lowest, StormMeterMaxStops);" in loop
    assert "Step = FMath::Min(Step, -BeautyMeterSaturatedStepStops);" in loop
    consts = dict(re.findall(r"constexpr double (BeautyMeter\w+) = ([0-9.]+);", RENDER_CPP))
    assert float(consts["BeautyMeterHighlightP90"]) < 1.0
    assert max(bl.EXPOSURE_METER_TARGET_P90.values()) + 0.05 < float(consts["BeautyMeterHighlightTarget"]) \
        < float(consts["BeautyMeterHighlightP90"])
    assert 0.0 < float(consts["BeautyMeterMaxCloseStops"]) <= 8.0
    # the guard is recorded on beauty renders only
    assert 'MeterRow->SetObjectField(TEXT("highlight_guard"), Guard);' in RENDER_CPP
    guard = RENDER_CPP[RENDER_CPP.index("if (bMeterMayClose)\n"):]
    assert guard.index('TEXT("highlight_guard")') < guard.index('MeterRow->SetStringField(TEXT("basis")')


def _meter(bright_at, may_close, target=0.45):
    """The commandlet's meter loop, step for step (FlightSimRenderCommandlet.cpp),
    over a frame whose p90 luma at an exposure offset is bright_at(stops)."""
    opened = measured = 0.0
    bright = None
    for rounds in range(5):
        bright = bright_at(opened)
        measured = opened
        blown = may_close and bright > 0.92
        if not blown and abs(bright - target) <= 0.05:
            break
        if rounds + 1 == 5:
            break
        want = 0.80 if blown else target
        step = 2.2 * 0.8 * math.log2(want / max(bright, 1.0 / 255.0))
        if blown and bright >= 254.0 / 255.0:
            step = min(step, -2.0)
        lowest = -6.0 if blown else min(0.0, opened)
        nxt = min(max(opened + step, lowest), 8.0)
        if abs(nxt - opened) <= 0.01:
            break
        opened = nxt
    return measured, bright_at(measured)


def _filmic(over_stops):
    """A p90 that clips: sRGB luma of a scene `over_stops` above mid grey, with a shoulder."""
    def bright(opened):
        x = 0.18 * 2.0 ** (over_stops + opened)
        return min(1.0, (x / (1.0 + x)) ** (1.0 / 2.2) * 1.25)
    return bright


def test_the_meter_design_lands_a_blown_frame_and_leaves_a_bright_one():
    # #08: far over, the p90 pinned at 255 (fixed steps down, then the target)
    opened, bright = _meter(_filmic(6.0), may_close=True)
    assert opened < -1.0 and bright <= 0.92
    # a frame just over the bound comes back under it
    opened, bright = _meter(_filmic(3.0), may_close=True)
    assert opened < 0.0 and bright <= 0.92
    # measure never closes either frame
    assert _meter(_filmic(6.0), may_close=False)[0] == 0.0
    assert _meter(_filmic(3.0), may_close=False)[0] == 0.0
    # a bright but unclipped clear sky (p90 0.75) is left as the look exposed it
    assert _meter(lambda opened: min(1.0, 0.75 * 2.0 ** (opened / 2.2)), may_close=True)[0] == 0.0
    # a dark frame still opens exactly as before
    dark = lambda opened: min(1.0, 0.1 * 2.0 ** (opened / 2.2))
    assert _meter(dark, may_close=True) == _meter(dark, may_close=False)
