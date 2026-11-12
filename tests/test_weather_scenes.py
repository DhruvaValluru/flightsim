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

import importlib.util
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
    assert clouds_at < clear_at < build.index("ApplyTiles(World, Tiles, CardWetness, SunElevationDeg);")
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


# -- visual rounds 3 and 4: #09's deck and tower read as cloud, not a box or a wireframe --
# Round 2's #09 (the cell drawn ahead, the deck above the 747): "the deck reads as a
# hard-edged flat slab with vertical walls (box-shaped, visible corners)". What the
# frame showed between the deck and the ground was the TOWER's lower part: a
# smoothstep cylinder (500 m edge) whose 0.19 /m core is opaque at the first few per
# cent of that edge, so the 600 m erosion moved its silhouette by tens of metres --
# a drum with a flat base, capped by the look's deck, itself a flat 100 m-edged band
# at cover 0.95. The beauty's Ragged block warps the wall, lifts the base and the
# deck's base unevenly and softens them.
# Round 3's #09 (the block's first cut): "thin white line-work (a hatched grid band)
# runs across the frame at wing height on both sides of the 747 and a white ribbon
# climbs to the top-right corner; it reads as wireframe, not cloud". The causes, from
# the shader: the base lift was one noise octave x 2.5 CLAMPED to 0..1, so the base
# and the deck's base sat at exactly 0 or 300 m lift over most of their area (flat
# plateaus) joined by risers of up to ~1.5 m per m (300 m steps seen edge-on: the
# ribbon); the wall warp's slope reached ~1.1 m per m (creases); the deck's 400 m
# base was eroded by a 4-octave noise sharpened 1 / (1 - 0.6) = 2.5x into thin,
# lit, low-density fringes; the tower kept the measure's 250-500 m edges. The
# constrained GPU marches 192 view samples over up to 80 km (~400 m steps,
# FlightSimClouds.cpp CloudMarch): thin, hard features step-sampled that coarsely
# draw as iso-lines, and the deck's underside, 300-400 m over the camera and seen
# at a grazing angle out to the horizon, piles them up at wing height.
# Round 4: unclamped gain-2 warps on one 5 km noise (larger than the frame's cloud),
# soft_m = 1 km ramps on the wall, the base and the deck's base, and no erosion on
# the deck's base. The march settings are untouched (raising them hung the iGPU).

STORM_HLSL = (REPO / "assets" / "shaders" / "weather" / "storm_cell.hlsl").read_text(encoding="utf-8")
MATERIALS_PY = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
HERO_CPP = (SOURCE / "Private" / "FlightSimHeroLighting.cpp").read_text(encoding="utf-8")
SCENE_H = (SOURCE / "Public" / "FlightSimVisualScene.h").read_text(encoding="utf-8")
#: The constrained GPU's view march, m per step (192 samples over up to 80 km).
MARCH_STEP_M = 80000.0 / 192.0
#: Round 3's Ragged block, for the comparison: gain 2.5, clamped, the base's noise
#: at half the scale, the deck's base eroded.
ROUND_THREE_RAGGED = {"warp_m": 800.0, "base_m": 300.0, "scale_m": 1800.0}


def _tower_edge_m(cell, ragged, azimuth_deg, up_m):
    """The outermost radius at which the tower's smooth shape reaches 0.5."""
    az = math.radians(azimuth_deg)
    for r in range(6000, 0, -25):
        if storm_cell.shapes(cell, r * math.sin(az), r * math.cos(az), up_m, ragged)["tower"] >= 0.5:
            return float(r)
    return 0.0


def _round_three_base_lift(cell, e, n):
    """Round 3's base lift fraction: saturate(0.5 + 2.5 (noise - 0.5)), the noise
    at half the warp's scale (seed + 5)."""
    scale = ROUND_THREE_RAGGED["scale_m"] * 0.5
    v = storm_cell.value_noise(e / scale, n / scale, 0.0, int(cell["noise"]["seed"]) + 5)
    return min(1.0, max(0.0, 0.5 + 2.5 * (v - 0.5)))


def _round_three_wall_warp(cell, e, n, u):
    """Round 3's wall warp fraction: clamp(2.5 (noise - 0.5), -1, 1)."""
    scale = ROUND_THREE_RAGGED["scale_m"]
    v = storm_cell.value_noise(e / scale, n / scale, u * 0.5 / scale, int(cell["noise"]["seed"]) + 4)
    return min(1.0, max(-1.0, 2.5 * (v - 0.5)))


def test_round_two_tower_is_a_drum_and_the_ragged_warp_billows_it():
    cell = _round_one_747_cell()
    smooth = [_tower_edge_m(cell, None, a, 2000.0) for a in range(0, 360, 10)]
    assert max(smooth) - min(smooth) == 0.0                       # round 2: a perfect cylinder
    ragged = [_tower_edge_m(cell, storm_cell.BEAUTY_RAGGED, a, 2000.0) for a in range(0, 360, 10)]
    assert max(ragged) - min(ragged) >= 300.0                     # beauty: a billowing wall
    # never out past the warp, so the vantage's clearance (2500 m) still holds
    assert max(ragged) <= max(smooth) + storm_cell.BEAUTY_RAGGED["warp_m"] + storm_cell.EDGE_M
    assert storm_cell.BEAUTY_RAGGED["warp_m"] < storm_cell.BEAUTY_VANTAGE_CLEARANCE_M / 2.0


def test_the_ragged_base_and_deck_lift_upward_only():
    cell = _round_one_747_cell()
    lift = storm_cell.BEAUTY_RAGGED["base_m"]
    cuts, lifts = [], []
    for a in range(0, 360, 7):
        for r in (300.0, 1500.0, 2400.0, 8000.0):
            e, n = r * math.sin(math.radians(a)), r * math.cos(math.radians(a))
            w = storm_cell.ragged_warp(cell, e, n, cell["base_m"] - 100.0, storm_cell.BEAUTY_RAGGED,
                                       layer_base_m=2400.0)
            cuts.append(w["base_cut"])
            lifts.append(w["deck_lift"])
    assert min(cuts) >= cell["base_m"] and max(cuts) <= cell["base_m"] + lift
    assert min(lifts) >= 0.0 and max(lifts) <= lift            # the deck never comes down on the aircraft
    assert max(cuts) - min(cuts) >= 0.5 * lift                 # an uneven base, not a flat one


def test_without_ragged_the_cell_is_the_measure_paths():
    cell = _round_one_747_cell()
    zero = dict(storm_cell.BEAUTY_RAGGED, warp_m=0.0)
    for e, n, u in ((0.0, 0.0, 3000.0), (2100.0, 300.0, 1100.0), (1800.0, -900.0, 2000.0),
                    (500.0, 200.0, 400.0), (900.0, 900.0, 15000.0)):
        w = storm_cell.ragged_warp(cell, e, n, u, None)
        assert w == {"rt": math.hypot(e, n), "base_cut": cell["base_m"], "deck_lift": 0.0}
        assert storm_cell.extinction_at(cell, e, n, u, 0.0) == storm_cell.extinction_at(cell, e, n, u, 0.0, zero)
    # the measure's ramps: 500 m wall, 250 m base, the deck's 100 m band
    measure = {"wall": storm_cell.EDGE_M * 2.0, "base": storm_cell.EDGE_M, "deck": 100.0}
    assert storm_cell.ragged_softness(None) == measure and storm_cell.ragged_softness(zero) == measure
    assert storm_cell.deck_band(2450.0, 2400.0, 3900.0) == pytest.approx(0.5)
    assert storm_cell.deck_band(2400.0, 2400.0, 3900.0) == 0.0 and storm_cell.deck_band(2500.0, 2400.0, 3900.0) == 1.0


def test_round_three_warps_were_plateaus_and_creases_and_round_four_is_smooth():
    cell = _round_one_747_cell()
    points = [(r * math.sin(math.radians(a)), r * math.cos(math.radians(a)))
              for a in range(0, 360, 5) for r in (500.0, 1500.0, 2400.0, 4000.0, 8000.0, 16000.0)]
    # round 3: the base lift sat on its clamps over most of the area ...
    three = [_round_three_base_lift(cell, e, n) for e, n in points]
    assert sum(1 for w in three if w in (0.0, 1.0)) / len(three) > 0.3
    # ... joined by risers steeper than 1 m per m (300 m steps, seen edge-on)
    riser = max(abs(_round_three_base_lift(cell, e + 1.0, n) - _round_three_base_lift(cell, e, n))
                for e, n in points) * ROUND_THREE_RAGGED["base_m"]
    assert riser > 1.0
    # ... and the wall warp's radial slope passed 1 m per m somewhere (a crease or fold)
    crease = max(abs(_round_three_wall_warp(cell, e + 1.0, n, 2000.0) - _round_three_wall_warp(cell, e, n, 2000.0))
                 for e, n in points) * ROUND_THREE_RAGGED["warp_m"]
    assert crease > 1.0
    # round 4: no clamp (no plateaus), one 5 km noise, slopes bounded well under 1
    ragged = storm_cell.BEAUTY_RAGGED
    bound = storm_cell.ragged_slope_bound(ragged)
    assert bound["wall"] < 1.0 and bound["base"] < 0.2
    assert ragged["scale_m"] >= 5000.0 and storm_cell.RAGGED_WARP_GAIN == 2.0
    four = [storm_cell.ragged_warp(cell, e, n, 900.0, ragged, layer_base_m=2400.0)["deck_lift"] / ragged["base_m"]
            for e, n in points]
    assert not any(w in (0.0, 1.0) for w in four)
    for (e, n), w in zip(points, four):
        step = storm_cell.ragged_warp(cell, e + 1.0, n, 900.0, ragged, layer_base_m=2400.0)["deck_lift"]
        assert abs(step - w * ragged["base_m"]) <= bound["base"] + 1e-9
    # the warped radius grows with the radius along every ray: the wall never folds
    for a in range(0, 360, 5):
        az = math.radians(a)
        previous = -1.0
        for r in range(0, 4000, 25):
            rt = storm_cell.ragged_warp(cell, r * math.sin(az), r * math.cos(az), 2000.0, ragged)["rt"]
            assert rt >= previous
            previous = rt


def test_the_soft_ramps_and_the_uneroded_deck_base_are_smooth_at_the_march_step():
    ragged = storm_cell.BEAUTY_RAGGED
    soft = storm_cell.ragged_softness(ragged)
    assert soft == {"wall": ragged["soft_m"], "base": ragged["soft_m"], "deck": ragged["soft_m"]}
    assert ragged["soft_m"] >= 2.0 * MARCH_STEP_M                 # a ramp spans several steps
    assert ragged["soft_m"] > storm_cell.EDGE_M * 2.0 and ragged["soft_m"] > 100.0
    # the deck's base: a monotone ramp, never more than 0.6 of its band per step
    cell = _round_one_747_cell()
    for e, n in ((0.0, 0.0), (3000.0, 1000.0), (-6000.0, 4000.0)):
        lift = storm_cell.ragged_warp(cell, e, n, 2400.0, ragged, layer_base_m=2400.0)["deck_lift"]
        us = [2400.0 + lift + k * 10.0 for k in range(0, 101)]
        bands = [storm_cell.deck_band(u, 2400.0, 3900.0, lift, ragged) for u in us]
        assert bands == sorted(bands) and bands[0] == 0.0 and bands[-1] == 1.0
        assert max(b - a for a, b in zip(bands, bands[40:])) <= 0.61   # over one 400 m step
    # the tower's wall ramps inward over soft_m and its base upward over soft_m
    radius = storm_cell.tower_radius_at(cell, 5000.0)
    inside = storm_cell.shapes(cell, radius - soft["wall"] - 1.0, 0.0, 5000.0,
                               dict(ragged, warp_m=1e-9))["tower"]
    assert inside == pytest.approx(1.0)
    # the shader: the ramps are the same names, and the deck's base is no longer eroded
    assert "float wallSoft = Edge * 2.0;" in STORM_HLSL and "float baseSoft = Edge;" in STORM_HLSL
    assert "wallSoft = max(Ragged.w, Edge * 2.0);" in STORM_HLSL
    assert "baseSoft = max(Ragged.w, Edge);" in STORM_HLSL
    assert "S.Eroded(band" not in STORM_HLSL and "seed + 6u" not in STORM_HLSL


def test_the_shader_ragged_block_is_the_python_twin_and_off_by_default():
    block = _block(STORM_HLSL, "float baseSoft = Edge;", "float f = saturate(")
    assert "if (Ragged.x > 0.0)" in block
    for constant in ("float wb = S.Value(float3(e, n, 0.0) / scale, (uint)Noise.x + 5u);",
                     "float wr = 2.0 * (S.Value(float3(e, n, u * 0.5) / scale, (uint)Noise.x + 4u) - 0.5);",
                     "r < towerR * 1.25 + Ragged.x + Edge * 2.0",
                     "u < max(base, Layer.y) + Ragged.y + max(Ragged.w, 100.0) + Edge"):
        assert constant in block, constant
    assert "clamp(" not in block and "saturate(" not in block        # no plateaus, no creases
    assert storm_cell.RAGGED_WARP_GAIN == 2.0
    # the tower and the dome read the warped radius and base; the shaft does not
    assert "S.Ss(radius, radius - wallSoft, rt) * S.Ss(baseCut, baseCut + baseSoft, u)" in STORM_HLSL
    assert "tower = max(tower, S.Ss(dome, dome - Edge, rt));" in STORM_HLSL
    assert "float shaft = S.Ss(shaftR, shaftR * 0.6, r)" in STORM_HLSL
    # the deck: the measure path's 100 m band when Ragged is 0
    assert "float deckSoft = Ragged.x > 0.0 ? max(Ragged.w, 100.0) : 100.0;" in STORM_HLSL
    assert "float band = S.Ss(deckBase, deckBase + deckSoft, u) * S.Ss(Layer.z, Layer.z - 100.0, u);" \
        in STORM_HLSL
    # the material exposes it (a float4, default 0) and is rebuilt on every machine
    assert '"ExtinctionScale", "Ragged", "Curtain")' in MATERIALS_PY
    assert '"Layer", "Flash", "Glass", "Ragged", "Curtain")' in MATERIALS_PY
    assert '"Time": params["Time"], "Ragged": params["Ragged"], "Curtain": params["Curtain"]}' in MATERIALS_PY
    assert '"M_StormCell": "6"' in MATERIALS_PY   # lane D: the beauty curtain and scud


def test_the_cpp_ragged_constants_are_the_pythons_and_beauty_only():
    apply = _function(WEATHER_CPP, "void FFlightSimWeather::ApplyBeautyStormVantage(")
    ragged = storm_cell.BEAUTY_RAGGED
    assert f"constexpr double WeatherRaggedWarpM = {ragged['warp_m']};" in apply
    assert f"constexpr double WeatherRaggedBaseM = {ragged['base_m']};" in apply
    assert f"constexpr double WeatherRaggedScaleM = {ragged['scale_m']};" in apply
    assert f"constexpr double WeatherRaggedSoftM = {ragged['soft_m']};" in apply
    assert f"constexpr double WeatherBeautyErosion = {storm_cell.BEAUTY_EROSION};" in apply
    assert 'SetVectorParameterValue(TEXT("Ragged")' in apply
    assert "static_cast<float>(WeatherRaggedScaleM), static_cast<float>(WeatherRaggedSoftM)" in apply
    assert 'Ragged->SetNumberField(TEXT("soft_m"), WeatherRaggedSoftM);' in apply
    assert "DeckSoft" not in WEATHER_CPP
    assert "FLinearColor(NoiseDrawn.R, NoiseDrawn.G, static_cast<float>(WeatherBeautyErosion), NoiseDrawn.A)" \
        in apply
    assert storm_cell.EROSION < storm_cell.BEAUTY_EROSION < 1.0
    # BuildCell (every render) never sets it: the material's default 0 is the measure shader
    build = _function(WEATHER_CPP, "bool FFlightSimWeather::BuildCell(")
    assert 'TEXT("Ragged")' not in build
    assert WEATHER_CPP.count('TEXT("Ragged")') == 1
    assert "FLinearColor NoiseDrawn = FLinearColor(0.0f, 0.0f, 0.0f, 0.0f);" in WEATHER_H


# -- visual rounds 3 and 4: #07's subject through the rain --------------------------------
# Round 2's #07: the A320 at 1000 m, the tower camera 80 m up at (-800 E, 900 N): a
# slant range of 1515 m at the start (37 deg up), ~30 px across at 35 mm, and within a
# few grey levels of the frame around it. The rain look's haze (FogDensity 0.012) is
# drawn by the beauty's volumetric fog at 0.1 x FogDensity per metre from the camera,
# twice the analytic fog's beta (0.1 ln(2)^2 x FogDensity, which also starts 1500 m out).
# Round 3's #07 (the extinction scaled by ln(2)^2): "a tiny bright speck, a few pixels,
# not a recognisable A320 silhouette". Round 4 gives the scenario a 250 mm lens: a
# tower spotter's telephoto, and the labels come from the same camera.

SCENARIOS_PY = REPO / "scripts" / "run_test_scenarios.py"


def _scenario_prompt(name):
    spec = importlib.util.spec_from_file_location("run_test_scenarios_round4", SCENARIOS_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return next(prompt for title, prompt, _ in module.SCENARIOS if title == name)


def test_round_two_tower_view_geometry():
    tower = (-800.0, 900.0, 80.0)
    aircraft = (0.0, 0.0, 1000.0)
    horizontal = math.hypot(aircraft[0] - tower[0], aircraft[1] - tower[1])
    slant = math.hypot(horizontal, aircraft[2] - tower[2])
    assert slant == pytest.approx(1515.0, abs=2.0)
    elevation = math.degrees(math.atan2(aircraft[2] - tower[2], horizontal))
    half_vfov = math.degrees(math.atan(20.25 / 2.0 / 35.0))
    # the aim is 37 deg up and the frame's bottom edge 21 deg up: no ground in the frame
    assert elevation - half_vfov > 20.0
    span_px = 34.1 * (1280.0 / 2.0 / (36.0 / 2.0 / 35.0)) / slant
    assert 25.0 < span_px < 32.0


def test_round_four_tower_view_is_a_telephoto_that_tracks_the_a320():
    from core.nl.compiler import compile_prompt
    prompt = _scenario_prompt("tower view, heavy rain")
    assert "with a 250 mm lens" in prompt
    spec = compile_prompt(prompt)
    camera = spec.cameras[0]
    assert camera.preset.value == "tower" and camera.aim_mode.value == "aircraft"
    assert camera.focal_length_mm.value == 250.0 and camera.focal_length_mm.source.value == "user"
    assert camera.sensor_width_mm.value == 36.0 and camera.width_px.value == 1280
    # the A320's 34 m span at the 1515 m slant fills a sensible share of the 1280 px
    span_px = 34.1 * (1280.0 / 2.0 / (36.0 / 2.0 / 250.0)) / 1515.0
    assert 150.0 < span_px < 300.0
    # the frame is 8 deg wide: only an aircraft-tracking aim keeps a 6 s pass in it
    assert math.degrees(2.0 * math.atan(18.0 / 250.0)) < 10.0
    # the same prompt without the lens is the round-2 framing (the 35 mm default)
    assert compile_prompt(prompt.replace(" with a 250 mm lens", "")).cameras[0].focal_length_mm.value == 35.0


def test_the_wet_rows_draw_the_analytic_haze_and_keep_the_subject():
    assert wb.WET_VFOG_EXTINCTION_SCALE == pytest.approx(math.log(2.0) ** 2, abs=0.005)
    for preset in ("rain", "storm"):
        assert wb.ATMOSPHERE[preset]["vfog_extinction_scale"] == wb.WET_VFOG_EXTINCTION_SCALE
    for preset in ("clear", "hazy", "overcast"):
        assert wb.ATMOSPHERE[preset]["vfog_extinction_scale"] == 1.0   # unchanged
    fog_density = 0.012                                                # lighting.rain_knobs(10 mm/h)
    volumetric = 0.1 * fog_density
    before = math.exp(-volumetric * 1.0 * 1515.0)
    after = math.exp(-volumetric * wb.WET_VFOG_EXTINCTION_SCALE * 1515.0)
    assert before < 0.2 and after > 0.4
    # one haze: the volumetric fog's beta is now the analytic fog's
    analytic = fog_density * 0.1 * math.log(2.0) ** 2
    assert volumetric * wb.WET_VFOG_EXTINCTION_SCALE == pytest.approx(analytic, rel=0.01)
    rows = _function(CLOUDS_CPP, "inline double AtmosphereDefault(int Preset, int Field)")
    assert rows.count("4000.0, 0.3, 0.48,") == 2


# -- visual round 4: #08 and head shot c went dark with the wet rows' extinction scale ----
# Round 3's #08 (C172 over Fuji, sunrise, 1 mm/h) fell from luma 181 to 142: the slope
# dark red-brown, the C172 a near-black silhouette under a sky that still clips; head
# shot c (J-11 over the forest in heavy rain) "much darker than head2 c; the forest and
# the J-11 near-black under a dark deck". The engine's volumetric fog scatters
# Albedo x Extinction, so scaling the extinction by 0.48 also halved the rain haze's
# IN-SCATTER: the veil that lifted the dark near slope, the forest and the airframe
# (optically thin there, in-scatter ~ sigma x distance) fell to 48 %, and a frame whose
# sky clips cannot be opened back up by the meter. The albedo is already white (an
# 8-bit colour, no headroom), so the in-scatter is put back on the lights: the sun's
# and the sky light's VolumetricScatteringIntensity x 1 / 0.48. The subject's own
# light still comes through the 1.5 km of rain at 42 %, not 17 %.


def test_the_wet_rows_put_the_in_scatter_back_on_the_lights():
    scale = wb.WET_VFOG_EXTINCTION_SCALE
    for preset in ("rain", "storm"):
        assert wb.vfog_scattering_compensation(preset) == pytest.approx(1.0 / scale)
    for preset in ("clear", "hazy", "overcast"):
        assert wb.vfog_scattering_compensation(preset) == 1.0
    # the thin-regime veil (in-scatter ~ albedo x sigma_s x d) is round 2's again ...
    sigma = 0.1 * 0.012
    for distance in (60.0, 300.0, 800.0):
        round_two = sigma * distance
        round_three = sigma * scale * distance
        round_four = sigma * scale * wb.vfog_scattering_compensation("rain") * distance
        assert round_three == pytest.approx(0.48 * round_two, rel=0.01)
        assert round_four == pytest.approx(round_two)
    # ... and the subject's transmittance is round 3's (the extinction alone is scaled)
    assert math.exp(-sigma * scale * 1515.0) > 0.4


def test_the_cpp_in_scatter_compensation_is_the_python_one_and_beauty_only():
    pure = _block(CLOUDS_CPP, "// FLIGHTSIM-WORLD-PURE-BEGIN", "// FLIGHTSIM-WORLD-PURE-END")
    assert "inline double VFogScatteringCompensation(double ExtinctionScale)" in pure
    assert "return ExtinctionScale > 0.0 && ExtinctionScale < 1.0 ? 1.0 / ExtinctionScale : 1.0;" in pure
    for value, expected in ((0.48, 1.0 / 0.48), (1.0, 1.0), (0.0, 1.0), (-1.0, 1.0), (2.0, 1.0)):
        assert (1.0 / value if 0.0 < value < 1.0 else 1.0) == expected
    # the world look (beauty only) sets it on the sky light and the sun, from the row's scale
    atmosphere = _function(CLOUDS_CPP, "void FFlightSimWorldBeauty::ApplyAtmosphere(")
    assert "const double Compensation = VFogScatteringCompensation(Row[AtmVFogExtinctionScale]);" in atmosphere
    assert "Scene.VolumetricFogScatteringScale = Compensation;" in atmosphere
    assert "Sky->SetVolumetricScatteringIntensity(static_cast<float>(Sky->VolumetricScatteringIntensity * Compensation));" \
        in atmosphere
    assert "Beam->SetVolumetricScatteringIntensity(static_cast<float>(Beam->VolumetricScatteringIntensity * Compensation));" \
        in atmosphere
    assert 'Out->SetObjectField(TEXT("volumetric_fog_inscatter"), Inscatter);' in atmosphere
    assert atmosphere.index("Fog->SetVolumetricFogExtinctionScale(") < atmosphere.index("Scene.VolumetricFogScatteringScale = ")
    # the hero lighting, which sets the sun's after the world lane, multiplies by it
    hero = _function(HERO_CPP, "bool FFlightSimHeroLighting::Apply(")
    assert "HeroLightingFogScattering * static_cast<float>(Scene.VolumetricFogScatteringScale);" in hero
    assert "SunLight->SetVolumetricScatteringIntensity(SunFogScattering);" in hero
    assert "constexpr float HeroLightingFogScattering = 1.0f;" in HERO_CPP   # the physics default, kept
    # the factor lives on the scene (1 by default: every other render is byte-identical)
    scene_class = SCENE_H[SCENE_H.index("class FLIGHTSIMBRIDGE_API FFlightSimVisualScene"):]
    assert "double VolumetricFogScatteringScale = 1.0;" in scene_class
    assert "VolumetricFogScatteringScale" not in SCENE_H[:SCENE_H.index("class FLIGHTSIMBRIDGE_API FFlightSimVisualScene")]
    assert SCENE_H.count("VolumetricFogScatteringScale") == 1
    assert "VolumetricFogScatteringScale" not in RENDER_CPP
    # the world lane runs before the hero lighting, so neither doubles the other
    assert RENDER_CPP.index("WorldBeauty.Build(") < RENDER_CPP.index("FFlightSimHeroLighting::Apply(VisualScene")
