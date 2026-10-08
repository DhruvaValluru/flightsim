"""The weather a render draws as weather: rain particles, the storm cell, lightning, thunder.

core/scene/{rain_field,storm_cell,lightning,thunder,storm_weather}.py are
the references; the GPU halves (assets/shaders/weather/*.hlsl) are pinned to
their constants here, and the C++ port's closed forms (FlightSimWeather.cpp)
are COMPILED here with a stand-in for the engine's math types and run
against the Python -- the one part of the Unreal side this container can
execute. Whether the engine draws what the numbers say is docs/WEATHER.md's
Windows clauses (WX.1-WX.6).
"""

from __future__ import annotations

import json
import math
import random
import re
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from core.scene import lightning, precipitation, rain_field, storm_cell, thunder, storm_weather

REPO = Path(__file__).resolve().parents[1]
SHADERS = REPO / "assets" / "shaders" / "weather"
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
WEATHER_CPP = (BRIDGE / "Private" / "FlightSimWeather.cpp").read_text(encoding="utf-8")
WEATHER_H = (BRIDGE / "Public" / "FlightSimWeather.h").read_text(encoding="utf-8")

CELL = storm_cell.card_block(1000.0, 40.0, 200.0, 270.0, 8.0, None, 42)


def _quad(f, a, b, n=20000):
    h = (b - a) / n
    return sum(f(a + (i + 0.5) * h) for i in range(n)) * h


# -- rain particles ------------------------------------------------------------------

def test_the_truncated_density_is_the_integral_of_the_distribution():
    lam = precipitation.fitted_lambda(10.0)
    closed = rain_field.truncated_number_density(lam)
    numeric = _quad(lambda d: precipitation.MP_N0 * math.exp(-lam * d),
                    rain_field.D_RENDER_MIN_MM, rain_field.D_MAX_MM)
    assert closed == pytest.approx(numeric, rel=1e-6)


def test_the_sampled_diameters_follow_the_truncated_exponential():
    lam = precipitation.fitted_lambda(10.0)
    lo, hi = rain_field.D_RENDER_MIN_MM, rain_field.D_MAX_MM
    samples = [rain_field.sample_diameter_mm(rain_field.unit(7, i, 3), lam)
               for i in range(20000)]
    assert min(samples) >= lo and max(samples) <= hi
    # The truncated exponential's mean, closed form.
    span = hi - lo
    mean = lo + 1.0 / lam - span * math.exp(-lam * span) / (1.0 - math.exp(-lam * span))
    assert sum(samples) / len(samples) == pytest.approx(mean, rel=0.01)
    assert rain_field.sample_diameter_mm(0.0, lam) == pytest.approx(lo)


def test_the_number_flux_is_the_closed_form_of_n_v():
    lam = precipitation.fitted_lambda(25.0)
    closed = rain_field.number_flux_per_m2_s(lam)
    numeric = _quad(lambda d: precipitation.MP_N0 * math.exp(-lam * d)
                    * precipitation.terminal_velocity_mps(d),
                    rain_field.D_RENDER_MIN_MM, rain_field.D_MAX_MM)
    assert closed == pytest.approx(numeric, rel=1e-6)


def test_big_drops_flatten_and_drops_fall_faster_aloft():
    assert rain_field.axis_ratio(1.0) == pytest.approx(0.98, abs=0.01)
    assert rain_field.axis_ratio(5.0) == pytest.approx(0.706, abs=0.005)
    assert rain_field.presented_width_mm(5.0) > 5.0
    assert rain_field.fall_speed_factor(0.0) == pytest.approx(1.0)
    assert rain_field.fall_speed_factor(3000.0) > 1.1


def test_a_drop_is_fixed_in_the_air_while_the_camera_flies_through_it():
    p0 = (3.0, -2.0, 1.0)
    half = rain_field.BOX_HALF_M
    # Still air, no fall: the drop's world place does not depend on the camera
    # as long as it stays inside the box around it.
    first = rain_field.drop_position(p0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0.0, 0.0)
    moved = rain_field.drop_position(p0, (0.0, 0.0, 0.0), (1.5, 0.5, 0.0), 0.0, 0.0)
    assert moved == pytest.approx(first)
    # Far away the box folds it back around the camera.
    far = rain_field.drop_position(p0, (0.0, 0.0, 0.0), (100.0, 0.0, 0.0), 0.0, 0.0)
    assert abs(far[0] - 100.0) <= half[0]
    # It falls at its own speed and drifts with the air.
    later = rain_field.drop_position(p0, (2.0, 0.0, 0.0), (0.0, 0.0, 0.0), 6.5, 0.1)
    assert later[0] - first[0] == pytest.approx(2.0)
    assert later[2] - first[2] == pytest.approx(-0.65)


def test_the_streak_opacity_is_garg_and_nayar_coverage():
    # A 2 mm drop at 6.5 m/s over 1/500 s sweeps 13 mm: covered 2/13 of it.
    assert rain_field.streak_opacity(2.0, 6.5, 0.002) == pytest.approx(2.0 / 13.0)
    assert rain_field.streak_opacity(2.0, 6.5, 0.002, weight=100.0) == 1.0


def test_the_rain_block_is_in_its_fixed_order_and_its_selftest_reproduces():
    block = rain_field.card_block(12.0, "stated", 1234, 1500.0, (2.0, -1.0, 0.0), 55.0)
    assert tuple(block) == rain_field.CARD_KEYS
    assert block["ambient_fraction"] == pytest.approx(1.0)
    assert block["particles"] <= rain_field.PARTICLE_BUDGET
    assert block["weight"] >= 1.0
    for entry, again in zip(block["selftest"], rain_field.drops(block, len(block["selftest"]))):
        assert entry["d_mm"] == pytest.approx(again["d_mm"], abs=1e-11)
        assert entry["p0_m"] == pytest.approx(again["p0_m"], abs=1e-11)
    assert json.loads(json.dumps(block)) == block


def test_outside_a_storms_shaft_only_the_stated_rain_falls():
    storm = rain_field.card_block(50.0, "storm_default", 1, 0.0, (0, 0, 0), 60.0,
                                      ambient_rate_mmh=None)
    assert storm["ambient_fraction"] == 0.0
    light = rain_field.card_block(50.0, "storm_default", 1, 0.0, (0, 0, 0), 60.0,
                                      ambient_rate_mmh=2.0)
    assert 0.0 < light["ambient_fraction"] < 0.2


def test_the_splash_slots_are_the_shaders_hash():
    for slot, cycle in ((0, 0), (17, 3), (4095, 123456)):
        x, y = rain_field.splash_position(slot, cycle, 10.0)
        h = rain_field.pcg32(slot * 65536 + cycle)
        assert x == pytest.approx(((h & 0xFFFF) / 65535.0 * 2 - 1) * 10.0)
        assert -10.0 <= x <= 10.0 and -10.0 <= y <= 10.0
    text = (SHADERS / "rain_splash_offset.hlsl").read_text(encoding="utf-8")
    assert "S.Pcg((uint)Slot * 65536u + (uint)cycle)" in text
    assert "float2(h & 0xFFFFu, h >> 16u) / 65535.0 * 2.0 - 1.0" in text


def test_the_glass_holds_drops_below_the_shedding_speed():
    assert rain_field.windshield(500.0, 15.0)["runoff_mps"] == 0.0
    fast = rain_field.windshield(500.0, 60.0)
    assert fast["runoff_mps"] == pytest.approx(rain_field.RUNOFF_GAIN * (60.0 - 22.0), abs=1e-4)
    assert fast["impinge_per_m2_s"] == pytest.approx(500.0 * 60.0 * 0.5, rel=1e-6)


def test_the_hashes_are_the_published_ones():
    # SplitMix64 from state 0: the first output of Vigna's reference.
    assert rain_field.splitmix64(0) == 0xE220A8397B1DCDAF
    assert 0.0 <= rain_field.unit(1, 2, 3) < 1.0
    assert rain_field.pcg32(0) == rain_field.pcg32(0)


# -- the storm cell --------------------------------------------------------------------

def test_cloud_extinction_is_three_lwc_over_two_rho_re():
    assert storm_cell.extinction_per_m(1.5, 12.0, 1000.0) == pytest.approx(0.1875)
    assert CELL["extinction_anvil_per_m"] < 0.01 < CELL["extinction_core_per_m"]


def test_the_cell_is_placed_and_sized_by_the_storm_the_physics_flies():
    assert tuple(CELL) == storm_cell.CARD_KEYS
    assert CELL["tower_radius_m"] == 2500.0          # 2.5 x the 1 km downburst core
    assert CELL["shaft"]["radius_m"] == 1000.0       # the downdraft core
    assert CELL["shaft"]["rate_source"] == "storm_default"
    assert CELL["anvil_offset_enu_m"][0] > 0.0       # wind FROM 270: the anvil east
    # The tower is solid inside, clear far outside; the shaft under the base.
    assert storm_cell.extinction_at(CELL, 0.0, 0.0, 5000.0) == pytest.approx(0.1875)
    assert storm_cell.extinction_at(CELL, 20000.0, 0.0, 5000.0) == 0.0
    shaft = storm_cell.extinction_at(CELL, 0.0, 0.0, 300.0)
    assert 0.6 * CELL["shaft"]["extinction_per_m"] <= shaft <= CELL["shaft"]["extinction_per_m"]
    assert storm_cell.extinction_at(CELL, 3000.0, 0.0, 300.0) == 0.0


def test_the_shafts_transmittance_is_the_atlas_rain_across_it():
    t = storm_cell.transmittance(CELL, (-3000.0, 0.0, 300.0), (3000.0, 0.0, 300.0))
    sigma = CELL["shaft"]["extinction_per_m"]
    # The shaft is 2 km across (soft edge from 0.6 R): between 1.2 and 2 km of rain.
    assert math.exp(-sigma * 2000.0) <= t <= math.exp(-sigma * 0.6 * 1200.0)


def test_the_towers_boil_upward_with_time():
    a = storm_cell.extinction_at(CELL, 2000.0, 300.0, 6000.0, t=0.0)
    b = storm_cell.extinction_at(CELL, 2000.0, 300.0, 6000.0 + 15.0 * 10.0, t=10.0)
    assert a == pytest.approx(b, abs=1e-12)   # the noise moved up at the updraft speed


def test_the_storm_shader_is_the_python_twin_constant_for_constant():
    text = (SHADERS / "storm_cell.hlsl").read_text(encoding="utf-8")
    for constant in ("747796405u", "2891336453u", "277803737u", "(word >> 22u) ^ word",
                     "amp *= 0.5", "freq *= 2.03", "k < 4", "const float Edge = 250.0",
                     "1.0 - 0.25 * 0.5 + 0.25 * f", "0.5 * towerR", "Edge * 4.0", "* 0.6 * (ra / anvilR)",
                     "shaftR * 0.6", "u / (billow * 8.0)", "seed + 1u", "seed + 2u",
                     "t * t * t * (t * (t * 6.0 - 15.0) + 10.0)", "0.6 + 0.4 * curtain"):
        assert constant in text, constant
    assert storm_cell.NOISE_OCTAVES == 4 and storm_cell.NOISE_GAIN == 0.5
    assert storm_cell.NOISE_LACUNARITY == 2.03 and storm_cell.EDGE_M == 250.0
    assert storm_cell.TOWER_FLARE == 0.25 and storm_cell.OVERSHOOT_RADIUS_FRACTION == 0.5
    assert storm_cell.SHAFT_NOISE_STRETCH == 8.0
    glow = (SHADERS / "storm_glow.hlsl").read_text(encoding="utf-8")
    assert "max(length(Rel - FlashRel) / 100.0, Edge)" in glow and "exp(-d / Flash.y)" in glow


@pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler on this machine")
def test_the_shaders_hash_and_lattice_are_the_pythons(tmp_path):
    """The HLSL Pcg and Lattice methods (storm_cell.hlsl), compiled as C++
    with HLSL's uint / asuint, against rain_field.pcg32 and
    storm_cell.lattice."""
    text = (SHADERS / "storm_cell.hlsl").read_text(encoding="utf-8")
    methods = "".join(_extract(text, f"\t{sig}", "\n\t}\n") + "\n\t}\n"
                      for sig in ("uint Pcg(uint v)", "float Lattice(int ix, int iy, int iz, uint seed)"))
    cases = [(0, 0, 0, 0), (-1, 2, -3, 5), (123, -456, 789, 42), (-70000, 3, 1, 16777215)]
    source = ("#include <cstdint>\n#include <cstdio>\n#include <cstring>\nusing uint = uint32_t;\n"
              "static uint asuint(int v) { uint u; std::memcpy(&u, &v, 4); return u; }\n"
              "struct S {\n" + methods + "};\nint main() { S s;\n"
              + "".join(f"printf(\"%u\\n\", s.Pcg({v}u));\n" for v in (0, 1, 2891336453, 4294967295))
              + "".join(f"printf(\"%.9g\\n\", (double)s.Lattice({x}, {y}, {z}, {seed}u));\n"
                        for x, y, z, seed in cases)
              + "return 0; }\n")
    (tmp_path / "hash.cpp").write_text(source, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-o", str(tmp_path / "hash"), str(tmp_path / "hash.cpp")],
                   check=True, capture_output=True, text=True)
    out = subprocess.run([str(tmp_path / "hash")], check=True, capture_output=True,
                         text=True).stdout.split()
    assert [int(v) for v in out[:4]] == [rain_field.pcg32(v) for v in (0, 1, 2891336453, 4294967295)]
    for value, (x, y, z, seed) in zip(out[4:], cases):
        # The shader returns a float: the lattice to single precision.
        assert float(value) == pytest.approx(storm_cell.lattice(x, y, z, seed), rel=1e-7)


# -- lightning --------------------------------------------------------------------------

def test_the_schedule_is_poisson_and_seeded():
    times = [t for t, _ in lightning.schedule(3, 1800.0)]
    assert len(times) < lightning.MAX_FLASHES
    assert len(times) == pytest.approx(lightning.FLASH_RATE_PER_MIN * 30.0, rel=0.2)
    assert lightning.schedule(3, 600.0) == lightning.schedule(3, 600.0)
    kinds = [k for seed in range(20) for _, k in lightning.schedule(seed, 1800.0)]
    share = kinds.count("cg") / len(kinds)
    assert share == pytest.approx(1.0 / (1.0 + lightning.IC_CG_RATIO), abs=0.03)


def test_a_bolt_lands_exactly_on_its_strike_point_and_never_climbs():
    rng = random.Random(5)
    start = (100.0, -200.0, 2500.0)
    channel = lightning.cg_main_channel(rng, start, (1500.0, 800.0))
    assert channel[0] == start
    assert channel[-1] == (1500.0, 800.0, 0.0)
    assert all(b[2] <= a[2] + 1e-9 for a, b in zip(channel, channel[1:]))
    length = lightning._length(channel)
    assert length > math.dist(start, (1500.0, 800.0, 0.0))   # tortuous


def test_the_exposure_sees_the_stroke_integral():
    flash = {"t_s": 0.0, "strokes": [{"t_s": 0.01, "peak_w_per_m": 6e5}], "leader": None,
             "continuing": None}
    p = lightning.window_power(flash, 0.0, 0.02)
    numeric = _quad(lambda t: 6e5 * (lightning.PEAK_NORM * (math.exp(-t / lightning.FALL_S)
                                                            - math.exp(-t / lightning.RISE_S))
                                     + lightning.GLOW_FRACTION * math.exp(-t / lightning.GLOW_S)),
                    0.0, 0.01, 200000)
    assert p["main_w_per_m"] * 0.02 == pytest.approx(numeric, rel=1e-4)
    assert p["main_w_per_m"] * 0.02 == pytest.approx(lightning.stroke_total_energy(6e5), rel=1e-4)
    # A 1/500 s exposure that closes before the stroke sees nothing of it.
    assert lightning.window_power(flash, 0.0, 0.008)["main_w_per_m"] == 0.0
    # The double exponential peaks at Pp.
    t_star = math.log(lightning.FALL_S / lightning.RISE_S) * lightning.FALL_S * lightning.RISE_S / (
        lightning.FALL_S - lightning.RISE_S)
    peak = lightning.PEAK_NORM * (math.exp(-t_star / lightning.FALL_S) - math.exp(-t_star / lightning.RISE_S))
    assert peak == pytest.approx(1.0)


def test_a_channel_widened_to_a_pixel_keeps_its_light():
    assert lightning.line_luminance(1e4, 0.1) * 0.1 == pytest.approx(lightning.line_luminance(1e4, 2.0) * 2.0)


def test_the_lightning_block_is_in_its_fixed_order():
    block = lightning.card_block(9, 600.0, CELL)
    assert tuple(block) == lightning.CARD_KEYS
    assert all(tuple(f) == lightning.FLASH_KEYS for f in block["flashes"])
    assert block["selftest"]
    cg = [f for f in block["flashes"] if f["kind"] == "cg"]
    assert cg and all(f["channels"][0]["points"][-1][2] == 0.0 for f in cg)
    assert all(f["leader"][1] == f["strokes"][0]["t_s"] for f in cg)


# -- thunder ------------------------------------------------------------------------------

def test_sound_speed_and_the_first_clap():
    assert thunder.sound_speed_mps(288.15) == pytest.approx(340.3, abs=0.1)
    flash = thunder.SELFTEST_FLASH
    c = 340.0
    samples, first = thunder.synthesise(flash, thunder.SELFTEST_LISTENER, c, 8000)
    window = thunder.arrival_window(flash, thunder.SELFTEST_LISTENER, c)
    assert first == pytest.approx(window[0])
    onset = next(i for i, v in enumerate(samples) if v != 0.0)
    assert onset / 8000.0 == pytest.approx(first, abs=1.0 / 8000.0)
    assert max(abs(v) for v in samples) > 0.1


def test_thunder_beyond_earshot_is_silent():
    far = (40000.0, 0.0, 2.0)
    samples, first = thunder.synthesise(thunder.SELFTEST_FLASH, far, 340.0, 8000)
    assert samples == [] and first == math.inf


def test_the_wav_is_written_at_full_scale_and_counts_its_clipping(tmp_path):
    record = thunder.write_wav(str(tmp_path / "t.wav"), [0.0, 50.0, 200.0, -200.0], 8000)
    assert record["clipped"] == 2
    with wave.open(str(tmp_path / "t.wav")) as handle:
        assert handle.getnframes() == 4 and handle.getframerate() == 8000


# -- the card block ------------------------------------------------------------------------

class _Q:
    def __init__(self, value, detail=None):
        self.value = value
        self.detail = detail or {}


class _Spec:
    def __init__(self, event="none", rate=None):
        self.weather_event = _Q(event)
        self.precipitation_rate_mmh = _Q(rate)
        self.seed = _Q(7)
        self.terrain_elevation = _Q(150.0)
        self.wind_speed = _Q(10.0)
        self.wind_direction = _Q(250.0)
        self.airspeed = _Q(110.0)
        self.altitude = _Q(900.0)
        self.latitude = _Q(35.0)
        self.duration = _Q(90.0)


def test_the_block_is_absent_canonical():
    assert storm_weather.card_block(_Spec()) is None
    assert storm_weather.card_block(_Spec(event="tornado")) is None


def test_stated_rain_without_a_storm_is_rain_everywhere():
    block = storm_weather.card_block(_Spec(rate=6.0))
    assert tuple(block) == ("version", "rain")
    assert block["rain"]["rate_source"] == "stated" and block["rain"]["ambient_fraction"] == 1.0


def test_a_thunderstorm_carries_every_element_deterministically():
    a = storm_weather.card_block(_Spec(event="thunderstorm"))
    b = storm_weather.card_block(_Spec(event="thunderstorm"))
    assert tuple(a) == storm_weather.CARD_KEYS
    assert json.dumps(a) == json.dumps(b)
    assert a["rain"]["rate_source"] == "storm_default" and a["rain"]["ambient_fraction"] == 0.0
    assert tuple(a["thunder"]) == thunder.CARD_KEYS
    stated = storm_weather.card_block(_Spec(event="thunderstorm", rate=20.0))
    assert stated["cell"]["shaft"]["rate_mmh"] == 20.0
    assert stated["rain"]["ambient_fraction"] == 1.0


def test_the_run_card_carries_the_block_for_a_thunderstorm(tmp_path):
    from core.nl.compiler import compile_prompt
    from core.scenario.card import write_run_card

    storm = json.loads(write_run_card(compile_prompt("fly the 747 through a thunderstorm at 3000 m"),
                                      tmp_path / "storm.json").read_text(encoding="utf-8"))
    assert tuple(storm["weather"]) == storm_weather.CARD_KEYS
    calm = json.loads(write_run_card(compile_prompt("fly the c172 at 1500 m"),
                                     tmp_path / "calm.json").read_text(encoding="utf-8"))
    assert "weather" not in calm


def test_the_soundtrack_script_writes_the_cards_storm(tmp_path):
    card = {"duration_s": 3.0, "weather": storm_weather.card_block(_Spec(event="thunderstorm"))}
    # One flash early enough to be heard in a short clip.
    card["weather"]["lightning"]["flashes"] = [dict(thunder.SELFTEST_FLASH)]
    (tmp_path / "card.json").write_text(json.dumps(card), encoding="utf-8")
    out = subprocess.run(
        ["python", str(REPO / "scripts" / "storm_soundtrack.py"), str(tmp_path / "card.json"),
         str(tmp_path / "out.wav"), "--listener", "800,0,2", "--sample-rate", "8000",
         "--no-rain"], capture_output=True, text=True, check=True)
    record = json.loads(out.stdout)
    assert record["samples"] == 3 * 8000 and record["flashes"] == 1


# -- the C++ port, compiled --------------------------------------------------------------------

SHIM = r"""
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <vector>
#include <algorithm>
using int32 = int32_t; using int64 = int64_t; using uint64 = uint64_t;
struct FVector {
    double X = 0, Y = 0, Z = 0;
    FVector() {}
    FVector(double x, double y, double z) : X(x), Y(y), Z(z) {}
    FVector operator-(const FVector& o) const { return FVector(X - o.X, Y - o.Y, Z - o.Z); }
    static const FVector ZeroVector;
};
const FVector FVector::ZeroVector(0, 0, 0);
template <class T> struct TArray {
    std::vector<T> V;
    int32 Num() const { return (int32)V.size(); }
    T& operator[](int32 i) { return V[i]; }
    const T& operator[](int32 i) const { return V[i]; }
    void Add(const T& x) { V.push_back(x); }
    void Reset() { V.clear(); }
    void SetNumZeroed(int32 n) { V.assign(n, T()); }
    typename std::vector<T>::const_iterator begin() const { return V.begin(); }
    typename std::vector<T>::const_iterator end() const { return V.end(); }
};
template <class T> struct TNumericLimits { static T Max() { return std::numeric_limits<T>::max(); } };
struct FMath {
    static double Exp(double x) { return std::exp(x); }
    static double Loge(double x) { return std::log(x); }
    static double Sqrt(double x) { return std::sqrt(x); }
    static double Abs(double x) { return std::fabs(x); }
    static double Pow(double a, double b) { return std::pow(a, b); }
    static double CeilToDouble(double x) { return std::ceil(x); }
    static double RoundHalfToEven(double x) { return std::nearbyint(x); }
    template <class T> static T Max(T a, T b) { return a > b ? a : b; }
    template <class T> static T Min(T a, T b) { return a < b ? a : b; }
    template <class T> static T Clamp(T x, T lo, T hi) { return x < lo ? lo : (x > hi ? hi : x); }
};
"""


def _extract(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


def _port_source() -> str:
    structs = "".join(_extract(WEATHER_H, f"struct {name}\n", "};\n") + "};\n"
                      for name in ("FFlightSimLightCurve", "FFlightSimStroke", "FFlightSimChannel",
                                   "FFlightSimFlash", "FFlightSimFlashPower",
                                   "FFlightSimThunderConstants"))
    constants = "\n".join(re.findall(
        r"constexpr double Weather(?:Pi|AtlasA|AtlasB|AtlasC|ThunderRMinM|ThunderTailTimeConstants)"
        r" = [^;]+;", WEATHER_CPP))
    helpers = "".join(_extract(WEATHER_CPP, f"\tdouble {name}(", "\n\t}\n") + "\n\t}\n"
                      for name in ("WeatherExpIntegral", "WeatherOverlap"))
    declarations = """
class FFlightSimWeather {
public:
    static uint64 SplitMix64(uint64 X);
    static double Unit(uint64 Seed, uint64 Index, uint64 Channel);
    static double TerminalVelocityMps(double DiameterMm);
    static double SampleDiameterMm(double U, double Lambda, double DMinMm, double DMaxMm);
    static double AxisRatio(double DiameterMm);
    static double PresentedWidthMm(double DiameterMm);
    static double StrokeEnergy(const FFlightSimLightCurve& Curve, double Peak, double A, double B);
    static FFlightSimFlashPower WindowPower(const FFlightSimLightCurve& Curve,
                                            const FFlightSimFlash& Flash, double A, double B);
    static double IntensityCd(const FFlightSimLightCurve& Curve, const FFlightSimFlash& Flash,
                              const FFlightSimFlashPower& Power);
    static double SynthesiseThunder(const FFlightSimThunderConstants& Constants,
                                    const FFlightSimFlash& Flash, const FVector& Listener,
                                    int32 SampleRateHz, TArray<double>& OutSamples);
};
"""
    body = _extract(WEATHER_CPP, "uint64 FFlightSimWeather::SplitMix64",
                    "bool FFlightSimWeather::ParseFlash")
    return (SHIM + structs + "namespace {\n" + constants + "\n" + helpers + "}\n" + declarations
            + body)


def _cpp_flash(name, flash):
    lines = [f"FFlightSimFlash {name};", f"{name}.Index = {int(flash.get('index', 0))};",
             f"{name}.TimeS = {flash['t_s']!r};",
             f"{name}.bCloudToGround = {'true' if flash.get('kind') == 'cg' else 'false'};"]
    if flash.get("leader"):
        lines += [f"{name}.bLeader = true;", f"{name}.LeaderStartS = {flash['leader'][0]!r};",
                  f"{name}.LeaderEndS = {flash['leader'][1]!r};"]
    for stroke in flash["strokes"]:
        lines.append(f"{{ FFlightSimStroke S; S.TimeS = {stroke['t_s']!r}; "
                     f"S.PeakWPerM = {stroke['peak_w_per_m']!r}; {name}.Strokes.Add(S); }}")
    if flash.get("continuing"):
        c = flash["continuing"]
        lines += [f"{name}.bContinuing = true;", f"{name}.ContinuingStartS = {c['t_s']!r};",
                  f"{name}.ContinuingDurationS = {c['duration_s']!r};",
                  f"{name}.ContinuingWPerM = {float(c['w_per_m'])!r};"]
    for channel in flash["channels"]:
        points = " ".join(f"C.PointsEnu.Add(FVector({float(p[0])!r}, {float(p[1])!r}, {float(p[2])!r}));"
                          for p in channel["points"])
        lines.append(f"{{ FFlightSimChannel C; C.bBranch = {'true' if channel['kind'] == 'branch' else 'false'}; "
                     f"C.LengthM = {float(channel['length_m'])!r}; {points} {name}.Channels.Add(C); }}")
    return "\n".join(lines)


@pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler on this machine")
def test_the_cpp_port_computes_what_the_python_computes(tmp_path):
    block = storm_weather.card_block(_Spec(event="thunderstorm"))
    rain = block["rain"]
    flashes = block["lightning"]["flashes"]
    curve = block["lightning"]["light_curve"]
    k = block["thunder"]
    cg = next(f for f in flashes if f["kind"] == "cg")
    listener = (3000.0, -500.0, 2.0)
    windows = [(w["a_s"], w["b_s"]) for w in block["lightning"]["selftest"]]
    t0 = cg["strokes"][0]["t_s"]
    windows += [(t0 + 0.05, t0 + 0.1), (cg["t_s"] - 0.01, cg["t_s"] + 0.5)]
    main = ["int main() {",
            f"FFlightSimLightCurve K; K.RiseS = {curve['rise_s']!r}; K.FallS = {curve['fall_s']!r};",
            f"K.PeakNorm = {curve['peak_norm']!r}; K.GlowFraction = {curve['glow_fraction']!r};",
            f"K.GlowS = {curve['glow_s']!r}; K.LeaderWPerM = {float(curve['leader_w_per_m'])!r};",
            f"K.BranchStrokeShare = {curve['branch_stroke_share']!r};",
            f"K.EfficacyLmPerW = {float(curve['luminous_efficacy_lm_per_w'])!r};",
            _cpp_flash("F", cg), _cpp_flash("T", thunder.SELFTEST_FLASH),
            "FFlightSimThunderConstants Q;",
            f"Q.SoundSpeedMps = {k['sound_speed_mps']!r}; Q.RelaxationRadiusM = {k['relaxation_radius_m']!r};",
            f"Q.T0S = {k['t0_s']!r}; Q.Lengthening = {k['lengthening']!r};",
            f"Q.DirectivityFloor = {k['directivity_floor']!r}; Q.PressureRefPaM = {k['pressure_ref_pa_m']!r};",
            f"Q.AbsorptionF0Hz = {k['absorption_f0_hz']!r}; Q.AbsorptionRM = {k['absorption_r_m']!r};",
            f"Q.AudibleFullM = {k['audible_full_m']!r}; Q.AudibleMaxM = {k['audible_max_m']!r};"]
    for i in range(16):
        main.append(
            f"{{ double D = FFlightSimWeather::SampleDiameterMm(FFlightSimWeather::Unit({rain['seed']}ull, {i}ull, 3ull), "
            f"{rain['lambda']!r}, {rain['d_render_min_mm']!r}, {rain['d_max_mm']!r}); "
            f"printf(\"drop %.17g %.17g %.17g %.17g %.17g\\n\", D, FFlightSimWeather::PresentedWidthMm(D), "
            f"FFlightSimWeather::TerminalVelocityMps(D) * {rain['fall_speed_factor']!r}, "
            f"FFlightSimWeather::Unit({rain['seed']}ull, {i}ull, 4ull), "
            f"FFlightSimWeather::Unit({rain['seed']}ull, {i}ull, 0ull)); }}")
    for a, b in windows:
        main.append(f"{{ FFlightSimFlashPower P = FFlightSimWeather::WindowPower(K, F, {a!r}, {b!r}); "
                    f"printf(\"window %.17g %.17g %.17g %.17g\\n\", P.MainWPerM, P.BranchWPerM, "
                    f"P.LeaderProgress, FFlightSimWeather::IntensityCd(K, F, P)); }}")
    for flash_name, where, rate in (("T", thunder.SELFTEST_LISTENER, 8000), ("F", listener, 8000)):
        main.append(f"{{ TArray<double> S; double First = FFlightSimWeather::SynthesiseThunder(Q, {flash_name}, "
                    f"FVector({where[0]!r}, {where[1]!r}, {where[2]!r}), {rate}, S); "
                    f"printf(\"thunder %d %.17g\\n\", S.Num(), First); "
                    f"for (int32 I = 0; I < S.Num(); I += 97) printf(\"s %d %.17g\\n\", I, S[I]); }}")
    main.append("return 0; }")
    source = tmp_path / "port.cpp"
    source.write_text(_port_source() + "\n".join(main), encoding="utf-8")
    binary = tmp_path / "port"
    subprocess.run(["g++", "-std=c++17", "-O1", "-o", str(binary), str(source)], check=True,
                   capture_output=True, text=True)
    lines = subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout.splitlines()

    drops = [list(map(float, line.split()[1:])) for line in lines if line.startswith("drop ")]
    for i, (d, width, vt, phase, u0) in enumerate(drops):
        ref = rain_field.drop(i, rain["seed"], rain["lambda"], rain["box_half_m"], rain["fall_speed_factor"])
        assert d == pytest.approx(ref["d_mm"], rel=1e-12)
        assert width == pytest.approx(ref["width_mm"], rel=1e-12)
        assert vt == pytest.approx(ref["v_t_mps"], rel=1e-12)
        assert phase == pytest.approx(ref["phase"], rel=1e-15)
        assert u0 == pytest.approx(rain_field.unit(rain["seed"], i, 0), rel=1e-15)
    got = [list(map(float, line.split()[1:])) for line in lines if line.startswith("window ")]
    for (a, b), (m, br, prog, cd) in zip(windows, got):
        ref = lightning.window_power(cg, a, b)
        assert m == pytest.approx(ref["main_w_per_m"], rel=1e-9, abs=1e-12)
        assert br == pytest.approx(ref["branch_w_per_m"], rel=1e-9, abs=1e-12)
        assert prog == pytest.approx(ref["leader_progress"], abs=1e-12)
        assert cd == pytest.approx(lightning.intensity_cd(cg, ref), rel=1e-9, abs=1e-9)
    heads = [i for i, line in enumerate(lines) if line.startswith("thunder ")]
    for head, (flash, where) in zip(heads, ((thunder.SELFTEST_FLASH, thunder.SELFTEST_LISTENER),
                                            (cg, listener))):
        ref, first = thunder.synthesise(flash, where, k["sound_speed_mps"], 8000)
        count, cpp_first = lines[head].split()[1:]
        assert int(count) == len(ref)
        assert float(cpp_first) == pytest.approx(first, rel=1e-12)
        for line in lines[head + 1:]:
            if not line.startswith("s "):
                break
            _, index, value = line.split()
            assert float(value) == pytest.approx(ref[int(index)], rel=1e-9, abs=1e-9)
