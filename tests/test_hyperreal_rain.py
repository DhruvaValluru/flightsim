"""Hyperreal rain (2026-11-14, repaired 2026-11-15): the beauty rain reads as rain on camera.

The round-83 review: #07 (a tower view in heavy rain) is a flat grey screen with
sparse, short, opaque streaks; #06 and #09's rain reads as scratches. The causes were
in the code, and each fix is pinned here -- not by substring alone: the HLSL of the
drop shaders and the C++ of the twins are EVALUATED from their text against the
Python twins (core/scene/rain_drop_twin.py, weather_look, rain_veil), with no engine:

* the streak's length was the card camera's exposure on every frame (the documented
  daylight default 1/500 s: 2-6 px dashes). A beauty CLIP's drops now streak over the
  camera's motion-blur shutter (the plan's 180-degree shutter, from the capture); a
  beauty STILL has motion blur off (beauty_look.SHUTTER_POLICY) and its drops keep the
  view's shutter like everything else in it -- a still never carries a 1/48 s streak
  over a tack-sharp scene. The lightning's window and the measure path are unchanged.
  The weather record says which the drops used (streak_shutter_s), beside the view's;
* nothing defocused a near drop; M_RainDrops's Aperture (the pupil x a stated share,
  at most 2 px at the drop's range) grows the streak and spreads its light;
* the coverage cap flattened every near streak to a bar (applied after the soft
  profile); it is now the mean's, the profile over it;
* the drop was a lit white surface (the unshadowed sun under the deck); SceneLit of
  its radiance is the scene's luminance behind it (drop_scene_tone.hlsl);
* the curtain drew 2 px streaks at full alpha on every shell: the light of the drawn
  width is now the drop's, floored (a cell stands for its column's drops).

CALIBRATED NUMERICALLY against generation 6: a near drop's mean coverage on a beauty
still is within 0.5x..1.5x of generation 6's across diameters, ranges and weights,
the streak wider and longer, its Gaussian core kept under the cap.

BEAUTY ONLY: every term is a no-op at its material default, set only through
FFlightSimWeather::ApplyBeautyRainReadability (FFlightSimWorldBeauty, -quality=beauty)
or on the beauty veil's shells; the labels and a measure render are byte-identical.
UNCALIBRATED on a frame: no frame rendered on this machine.
"""

from __future__ import annotations

import ast
import math
import re
import struct
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

from core.scene import beauty_look, precipitation, rain_drop_twin as twin, rain_field, rain_veil, weather_look

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
WEATHER_CPP = (BRIDGE / "Private" / "FlightSimWeather.cpp").read_text(encoding="utf-8")
WEATHER_H = (BRIDGE / "Public" / "FlightSimWeather.h").read_text(encoding="utf-8")
COMMANDLET = (BRIDGE / "Private" / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
SHADERS = REPO / "assets" / "shaders" / "weather"
OFFSET = (SHADERS / "rain_drop_offset.hlsl").read_text(encoding="utf-8")
OPACITY = (SHADERS / "rain_drop_opacity.hlsl").read_text(encoding="utf-8")
TONE = (SHADERS / "drop_scene_tone.hlsl").read_text(encoding="utf-8")


def _assigned(name):
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def _function(text, signature):
    start = text.index(signature)
    return text[start:text.index("\n}\n", start)]


def _cpp_constant(text, name):
    match = re.search(rf"constexpr double {name} = ([0-9.eE+-]+);", text)
    assert match, name
    return float(match.group(1))


# -- evaluating the shaders and the C++ from their text -------------------------------------------

class Vec:
    """An HLSL float2/float3 for the evaluator: component-wise arithmetic, .x .y .z."""

    def __init__(self, *v):
        self.v = [float(x) for x in (v[0] if len(v) == 1 and isinstance(v[0], (list, tuple)) else v)]

    def _bin(self, other, op):
        if isinstance(other, Vec):
            return Vec(*[op(a, b) for a, b in zip(self.v, other.v)])
        return Vec(*[op(a, float(other)) for a in self.v])

    __add__ = lambda s, o: s._bin(o, lambda a, b: a + b)
    __sub__ = lambda s, o: s._bin(o, lambda a, b: a - b)
    __mul__ = lambda s, o: s._bin(o, lambda a, b: a * b)
    __truediv__ = lambda s, o: s._bin(o, lambda a, b: a / b)
    __radd__ = __add__
    __rmul__ = __mul__

    def __rsub__(self, other):
        return Vec(*[float(other) - a for a in self.v])

    def __neg__(self):
        return Vec(*[-a for a in self.v])

    def __abs__(self):
        return Vec(*[abs(a) for a in self.v])

    x = property(lambda s: s.v[0])
    y = property(lambda s: s.v[1])
    z = property(lambda s: s.v[2])

    @x.setter
    def x(self, value): self.v[0] = float(value)

    @y.setter
    def y(self, value): self.v[1] = float(value)

    @z.setter
    def z(self, value): self.v[2] = float(value)


def _asuint(f):
    return struct.unpack("<I", struct.pack("<f", float(f)))[0]


class _R:
    """The shaders' FRainPixel / FRainDrop structs (their bodies are skipped: PCG and
    smoothstep are rain_field.pcg32 and rain_drop_twin.smoothstep)."""

    @staticmethod
    def Pcg(v): return rain_field.pcg32(int(v) & 0xFFFFFFFF)

    @staticmethod
    def Ss(e0, e1, x): return twin.smoothstep(e0, e1, x)

    @staticmethod
    def Wrap(v, h): return Vec(*[a - 2.0 * b * math.floor((a + b) / (2.0 * b)) for a, b in zip(v.v, h.v)])


_HLSL_ENV: Dict[str, Any] = {
    "math": math, "float3": lambda *a: Vec(*a), "float2": lambda *a: Vec(*a),
    "saturate": twin.saturate, "lerp": twin.lerp, "exp": math.exp, "sqrt": math.sqrt, "sin": math.sin,
    "min": min, "max": max, "abs": abs, "floor": math.floor, "asuint": _asuint,
    "length": lambda v: math.sqrt(sum(a * a for a in v.v)),
    "dot": lambda a, b: sum(x * y for x, y in zip(a.v, b.v)),
    "cross": lambda a, b: Vec(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x),
    "normalize": lambda v: v / math.sqrt(sum(a * a for a in v.v)),
    "R": _R(),
}

_TERNARY = re.compile(r"^(\w+) = (.+?) \? (.+?) : (.+)$")


def _c_like_to_python(text: str, substitutions: List) -> str:
    """A straight-line C-like body (HLSL custom node or a small C++ function) to a
    Python function body: comments and struct definitions dropped, declarations
    stripped of their types, braces to indentation, ternaries and operators
    translated. Only what these sources use; anything else raises."""
    lines: List[str] = []
    depth = 0
    pending = False
    in_struct = False
    raw_lines = text.splitlines()
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i].split("//")[0].strip()
        i += 1
        if not line:
            continue
        if line.startswith("struct "):
            in_struct = True
            continue
        if in_struct:
            if line == "};":
                in_struct = False
            continue
        if re.match(r"^F\w+ R;$", line) or line.startswith("using namespace"):
            continue
        # A condition continued on the next line(s): join until the parentheses balance.
        while line.startswith("if (") and line.count("(") > line.count(")"):
            line += " " + raw_lines[i].split("//")[0].strip()
            i += 1
        if line == "{":
            assert pending, "a block without an if"
            pending = False
            depth += 1
            continue
        if line == "}":
            depth -= 1
            continue
        for kind, old, new in substitutions:
            line = re.sub(old, new, line) if kind == "re" else line.replace(old, new)
        assert line.endswith(";") or line.startswith("if "), line
        line = line[:-1] if line.endswith(";") else line
        for prefix in ("const float ", "const double ", "float3 ", "float2 ", "float ", "double ", "uint "):
            if line.startswith(prefix):
                line = line[len(prefix):]
                break
        if line.startswith("if (") and line.endswith(")"):
            line = "if " + line[3:] + ":"
            pending = True
        else:
            m = _TERNARY.match(line)
            if m:
                line = f"{m.group(1)} = ({m.group(3)}) if ({m.group(2)}) else ({m.group(4)})"
        assert "?" not in line and "::" not in line and "!" not in line.replace("!=", ""), line
        lines.append("    " * (depth + 1) + line)
    assert depth == 0 and not pending
    return "\n".join(lines)


_HLSL_SUBS = [("re", r"\b(0x[0-9A-Fa-f]+|\d+)u\b", r"\1"), ("str", "||", " or "), ("str", "&&", " and ")]
_CPP_SUBS = [("str", "FMath::DegreesToRadians", "math.radians"), ("str", "FMath::Tan", "math.tan"),
             ("str", "FMath::Max", "max"), ("str", "FMath::Min", "min"), ("str", "FMath::Pow", "pow"),
             ("str", "FMath::Exp", "math.exp"), ("str", "||", " or "), ("str", "&&", " and "),
             ("str", "!(", " not (")]


def _compile(body: str, name: str, params: List[str], env: Dict[str, Any]) -> Callable:
    source = f"def {name}({', '.join(params)}):\n{body}\n"
    scope = dict(env)
    exec(compile(source, f"<{name}>", "exec"), scope)   # noqa: S102 -- our own source text
    return scope[name]


def _hlsl_function(text: str, name: str, params: List[str]) -> Callable:
    return _compile(_c_like_to_python(text, _HLSL_SUBS), name, params, _HLSL_ENV)


OPACITY_PARAMS = ["Rel", "Drop", "Extra", "Index", "WindVel", "CamVel", "Shutter", "PixelAngle", "Weight",
                  "Active", "BoxHalf", "GroundRelZ", "MaxStreak", "MaxCoverage", "DepthFade", "Corner",
                  "Soft", "Vary", "Aperture"]
OFFSET_PARAMS = ["P0", "Corner", "Drop", "Extra", "Index", "Shift", "FallTime", "BoxHalf", "WindVel", "CamVel",
                 "Shutter", "PixelAngle", "Active", "Density", "NearThin", "MaxStreak", "Soft", "Vary",
                 "Aperture"]
HLSL_OPACITY = _hlsl_function(OPACITY, "opacity", OPACITY_PARAMS)
HLSL_OFFSET = _hlsl_function(OFFSET, "offset", OFFSET_PARAMS)


def _cpp_members(text: str) -> Dict[str, float]:
    """Every constexpr double of the file (the FlightSimRainVeil namespace and the
    file scope), by name."""
    return {m.group(1): float(m.group(2))
            for m in re.finditer(r"constexpr double (\w+) = ([0-9.eE+-]+);", text)}


def _cpp_function(signature: str, name: str, params: List[str], env: Dict[str, Any]) -> Callable:
    text = _function(WEATHER_CPP, signature)
    body = text[text.index("{") + 1:]
    return _compile(_c_like_to_python(body, _CPP_SUBS), name, params, env)


def _cpp_weather(**members: float) -> Dict[str, Callable]:
    """FFlightSimWeather's twins, evaluated from the C++ text with the members given
    (BeautyFNumber, BeautySensorMm, BeautyDefocusShare, D0Mm)."""
    env: Dict[str, Any] = {"math": math, "min": min, "max": max, "pow": pow}
    env.update(_cpp_members(WEATHER_CPP))
    env.update(members)
    env["AxisRatio"] = _cpp_function("double FFlightSimWeather::AxisRatio(", "AxisRatio", ["DiameterMm"], env)
    env["PresentedWidthMm"] = _cpp_function("double FFlightSimWeather::PresentedWidthMm(", "PresentedWidthMm",
                                            ["DiameterMm"], env)
    env["BeautyApertureCm"] = _cpp_function("double FFlightSimWeather::BeautyApertureCm(", "BeautyApertureCm",
                                            ["HorizontalFovDeg"], env)
    env["BeautyDefocusCm"] = _cpp_function("double FFlightSimWeather::BeautyDefocusCm(", "BeautyDefocusCm",
                                           ["HorizontalFovDeg"], env)
    env["CurtainStreakAlpha"] = _cpp_function("double FFlightSimWeather::CurtainStreakAlpha(", "CurtainStreakAlpha",
                                              ["ShellRadiusM", "PixelAngle"], env)
    return env


def _hash_u(index: float, salt: int) -> float:
    return (rain_field.pcg32(_asuint(index) ^ salt) & 0xFFFFFF) / 16777216.0


def _shader_case(seed: int) -> Dict[str, Any]:
    """One drop and one pixel of it, drawn from a hash: the shader's inputs."""
    u = [rain_field.unit(seed, k, 0) for k in range(16)]
    d_mm = 1.0 + 5.0 * u[0]
    speed = precipitation.terminal_velocity_mps(d_mm)
    range_cm = 60.0 + 1800.0 * u[1]
    direction = Vec(2.0 * u[2] - 1.0, 2.0 * u[3] - 1.0, 0.6 * (2.0 * u[4] - 1.0))
    direction = direction / math.sqrt(sum(a * a for a in direction.v))
    wind = Vec(300.0 * (2.0 * u[5] - 1.0), 300.0 * (2.0 * u[6] - 1.0), 0.0)
    cam = Vec(500.0 * (2.0 * u[7] - 1.0), 0.0, 100.0 * (2.0 * u[8] - 1.0))
    fov = 20.0 + 70.0 * u[9]
    index = 0.1 + 0.8 * u[10]
    return {
        "Rel": direction * range_cm, "Drop": Vec(d_mm, speed), "Extra": Vec(rain_field.presented_width_mm(d_mm), u[11]),
        "Index": index, "WindVel": wind, "CamVel": cam,
        "Shutter": twin.STILL_SHUTTER_S if u[12] < 0.5 else weather_look.BEAUTY_RAIN_CLIP_SHUTTER_S,
        "PixelAngle": twin.pixel_angle_rad(fov, 1280), "Weight": [1.0, 40.0, 240.0][int(u[13] * 3.0)],
        "Active": 1.0, "BoxHalf": Vec(1000.0, 1000.0, 800.0), "GroundRelZ": -1.0e9,
        "MaxStreak": rain_veil.streak_cap_rad(weather_look.BEAUTY_RAIN_STREAK_RAD_HEAVY, twin.pixel_angle_rad(fov, 1280)),
        "MaxCoverage": weather_look.BEAUTY_RAIN_MAX_COVERAGE, "DepthFade": 1200.0 if u[14] < 0.5 else 0.0,
        "Corner": Vec(u[15], rain_field.unit(seed, 17, 0)),
        "Soft": weather_look.BEAUTY_RAIN_SOFTNESS, "Vary": weather_look.BEAUTY_RAIN_VARIATION,
        "Aperture": weather_look.beauty_rain_defocus_cm(fov),
        "_fov": fov, "_range_cm": range_cm, "_d_mm": d_mm, "_speed_mps": speed,
    }


def _twin_of(case: Dict[str, Any], generation: int = 8) -> Dict[str, float]:
    rel = case["Rel"]
    vel = case["WindVel"] - Vec(0.0, 0.0, case["Drop"].y * 100.0) - case["CamVel"]
    speed_mps = math.sqrt(sum(a * a for a in vel.v)) / 100.0
    a = abs(rel) / case["BoxHalf"]
    edge = math.prod(1.0 - twin.smoothstep(0.8, 1.0, c) for c in a.v)
    shape = {"soft": case["Soft"], "vary": case["Vary"], "max_streak_rad": case["MaxStreak"],
             "max_coverage": case["MaxCoverage"], "depth_fade_cm": case["DepthFade"],
             "aperture_cm": case["Aperture"], "generation": generation}
    return twin.drop_pixel(case["Drop"].x, speed_mps, case["Shutter"], math.sqrt(sum(c * c for c in rel.v)),
                           case["PixelAngle"], case["Weight"], shape, corner_x=case["Corner"].x,
                           corner_y=case["Corner"].y, length_u=_hash_u(case["Index"], 0x68E31DA4),
                           bright_u=_hash_u(case["Index"], 0x1B56C4E9), width_mm=case["Extra"].x, edge=edge)


def _hlsl_args(case: Dict[str, Any], params: List[str], **extra: Any) -> List[Any]:
    merged = dict(case)
    merged.update(extra)
    return [merged[p] for p in params]


# -- the HLSL, evaluated: the opacity's arithmetic is the twin's, pixel for pixel ------------------

def test_the_opacity_shader_evaluates_to_the_python_twin_pixel_for_pixel():
    checked = 0
    for seed in range(400):
        case = _shader_case(seed)
        shown = HLSL_OPACITY(*_hlsl_args(case, OPACITY_PARAMS))
        expected = _twin_of(case)["shown"]
        assert shown == pytest.approx(expected, rel=1e-9, abs=1e-12), (seed, case["_fov"], case["_range_cm"])
        checked += shown > 0.0
    # Most sampled pixels carry coverage (the rest are past the box's face fade or thinned).
    assert checked > 200
    # The lens-near fade and the ground cut-off, as the shader has them.
    case = _shader_case(7)
    assert HLSL_OPACITY(*_hlsl_args(case, OPACITY_PARAMS, Rel=Vec(0.0, 4.0, 0.0))) == 0.0
    assert HLSL_OPACITY(*_hlsl_args(case, OPACITY_PARAMS, GroundRelZ=1.0e9)) == 0.0
    assert HLSL_OPACITY(*_hlsl_args(case, OPACITY_PARAMS, Index=1.5)) == 0.0


def test_the_offset_shader_draws_the_quad_the_opacity_spreads_its_light_over():
    """The quad's length and width (the offset's four corners) are the opacity's
    streak and width, so coverage x area is the drop's light in both shaders."""
    for seed in range(200):
        case = _shader_case(seed)
        # Inside the box (the offset wraps a seed outside it); Shift and FallTime 0: the drop
        # sits at its seed, and we read it there.
        range_cm = case["_range_cm"]
        if range_cm > 700.0:
            case = dict(case, Rel=case["Rel"] * (700.0 / range_cm))
        common = dict(P0=case["Rel"], Shift=Vec(0.0, 0.0, 0.0), FallTime=0.0, Density=1.0, NearThin=0.0)
        corners = {}
        for cx, cy in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)):
            out = HLSL_OFFSET(*_hlsl_args(case, OFFSET_PARAMS, Corner=Vec(cx, cy), **common))
            corners[(cx, cy)] = out + case["Rel"]   # the vertex's world position (minus the component)
        length = corners[(0.0, 1.0)] - corners[(0.0, 0.0)]
        width = corners[(1.0, 0.0)] - corners[(0.0, 0.0)]
        expected = _twin_of(case)
        assert math.sqrt(sum(a * a for a in length.v)) == pytest.approx(expected["streak_cm"], rel=1e-9)
        assert math.sqrt(sum(a * a for a in width.v)) == pytest.approx(expected["width_cm"], rel=1e-9)
        assert abs(sum(a * b for a, b in zip(length.v, width.v))) < 1e-6 * expected["streak_cm"] * expected["width_cm"]
    # Thinned near the lens and collapsed past the active share: the quad has no area.
    case = _shader_case(3)
    common = dict(P0=Vec(0.0, 100.0, 0.0), Shift=Vec(0.0, 0.0, 0.0), FallTime=0.0, Density=1.0, NearThin=400.0,
                  Extra=Vec(case["Extra"].x, 0.99))
    out = HLSL_OFFSET(*_hlsl_args(case, OFFSET_PARAMS, Corner=Vec(1.0, 1.0), **common))
    assert out.v == [-0.0, -100.0, -0.0] or out.v == [0.0, -100.0, 0.0]
    out = HLSL_OFFSET(*_hlsl_args(case, OFFSET_PARAMS, Corner=Vec(1.0, 1.0), Index=0.9, **dict(common, NearThin=0.0,
                                                                                               Density=0.5)))
    assert out.v[1] == -100.0


def test_every_hyperreal_term_is_a_no_op_at_its_default_value_for_value():
    """Aperture 0, MaxCoverage 1, Soft 0, Vary 0, SceneLit 0: the measure path's shader.
    The HLSL at those defaults equals Garg & Nayar's coverage directly, and generation
    6's arithmetic (the twin) gives the same."""
    for seed in range(100):
        case = _shader_case(seed)
        defaults = dict(Aperture=0.0, MaxCoverage=1.0, Soft=0.0, Vary=0.0, DepthFade=0.0, MaxStreak=0.0)
        shown = HLSL_OPACITY(*_hlsl_args(case, OPACITY_PARAMS, **defaults))
        rel = case["Rel"]
        dist = math.sqrt(sum(c * c for c in rel.v))
        vel = case["WindVel"] - Vec(0.0, 0.0, case["Drop"].y * 100.0) - case["CamVel"]
        speed = math.sqrt(sum(a * a for a in vel.v))
        d = case["Drop"].x * 0.1
        streak = max(speed * case["Shutter"], d)
        w = case["Extra"].x * 0.1
        width = max(w, dist * case["PixelAngle"])
        coverage = min(1.0, (d / streak) * (w / width) * case["Weight"])
        a = abs(rel) / case["BoxHalf"]
        edge = math.prod(1.0 - twin.smoothstep(0.8, 1.0, c) for c in a.v)
        expected = coverage * edge * twin.smoothstep(5.0, 30.0, dist)
        assert shown == pytest.approx(expected, rel=1e-9, abs=1e-12)
        case6 = dict(case, **defaults)
        assert _twin_of(case6, generation=6)["shown"] == pytest.approx(expected, rel=1e-9, abs=1e-12)
    assert '"Aperture": 0.0, "SceneLit": 0.0' in SCRIPT
    assert "float lum = dot(A, float3(0.2126, 0.7152, 0.0722));" in TONE
    assert "return float3(lum, lum, lum) * SceneLit;" in TONE


# -- the calibration: a near drop on a still within 0.5x..1.5x of generation 6, softer --------

NEAR_RANGES_M = (1.0, 2.0, 3.0, 5.0, 10.0)
DIAMETERS_MM = (1.0, 2.0, 4.0)
WEIGHTS = (1.0, 40.0, 240.0)   # a lone drop; a light rain's; a storm's x -rain-gain=4 x 1.5


@pytest.mark.parametrize("weight", WEIGHTS)
def test_a_near_drop_on_a_still_keeps_generation_6s_coverage_and_is_softer(weight):
    """The reference lens (54 deg over 1280 px), the view's 1/500 s shutter in both
    generations (a beauty still: motion blur off). Mean pixel coverage over the
    streak and over the drops' hashes."""
    for d in DIAMETERS_MM:
        for r in NEAR_RANGES_M:
            c = twin.near_drop_comparison(r, d, weight, samples=16, drops=8)
            label = (weight, d, r)
            assert 0.5 <= c["mean_ratio"] <= 1.5, (label, c)
            # Softer: never narrower or shorter than generation 6, and the quad grows near the lens.
            assert c["width_ratio"] >= 1.0 - 1e-12 and c["streak_ratio"] > 1.0, (label, c)
            # Never opaque, never a flat bar: a Gaussian core over a see-through streak.
            assert c["peak"] < 0.55, (label, c)
            assert c["core_contrast"] > 3.0, (label, c)
    near = twin.near_drop_comparison(2.0, 2.0, weight, samples=16, drops=8)
    assert near["width_ratio"] > 1.0 and near["streak_ratio"] > 1.1


def test_a_capped_storm_streak_keeps_its_core_and_most_of_generation_6s_mean():
    """At the storm's weight generation 6 drew a flat 0.22 bar; the capped mean is now
    the cap x the drops' mean brightness, 0.6x..0.7x of it, with a 2.3x core."""
    c = twin.near_drop_comparison(3.0, 2.0, 240.0, samples=24, drops=16)
    assert c["generation_6_mean"] == pytest.approx(twin.GENERATION_6_MAX_COVERAGE, abs=0.002)
    expected_mean = weather_look.BEAUTY_RAIN_MAX_COVERAGE * twin.vary_mean_brightness(weather_look.BEAUTY_RAIN_VARIATION)
    assert c["mean"] == pytest.approx(expected_mean, rel=0.03)
    assert 0.6 <= c["mean_ratio"] <= 0.7
    # The brightest sampled drop (hash 15.5/16) at the Gaussian's centre: cap x 2.27 x 1.31 x its brightness.
    brightest = twin.lerp(1.0, twin.BRIGHT_MIN + twin.BRIGHT_SPAN * (15.5 / 16.0), weather_look.BEAUTY_RAIN_VARIATION)
    assert c["peak"] == pytest.approx(weather_look.BEAUTY_RAIN_MAX_COVERAGE / twin.ACROSS_MEAN / twin.ALONG_MEAN
                                      * brightest, rel=0.03)
    assert c["peak"] < 0.55
    # The hash's brightness really averages what the closed form says.
    mean = sum(twin.lerp(1.0, twin.BRIGHT_MIN + twin.BRIGHT_SPAN * _hash_u(0.1 + 0.8 * k / 4096.0, 0x1B56C4E9),
                         weather_look.BEAUTY_RAIN_VARIATION) for k in range(4096)) / 4096.0
    assert mean == pytest.approx(twin.vary_mean_brightness(weather_look.BEAUTY_RAIN_VARIATION), abs=0.01)


def test_a_long_lens_near_drop_is_held_by_the_pixel_cap_not_smeared_into_nothing():
    """A 250 mm f/4 lens's pupil is 6 cm: unheld, a 3 m drop would be a 60 px smear
    (0.05x generation 6). The 2 px cap keeps the near drops within range; the far
    small drops of the box are the most defocused the beauty draws (stated)."""
    fov = math.degrees(2.0 * math.atan(18.0 / 250.0))
    assert weather_look.beauty_rain_aperture_cm(fov) == pytest.approx(6.25)
    for weight in WEIGHTS:
        for d in DIAMETERS_MM:
            for r in (1.0, 2.0, 3.0, 5.0):
                c = twin.near_drop_comparison(r, d, weight, horizontal_fov_deg=fov, samples=16, drops=8)
                assert 0.5 <= c["mean_ratio"] <= 1.5, ((weight, d, r), c)
    far = twin.near_drop_comparison(15.0, 1.0, 1.0, horizontal_fov_deg=fov, samples=16, drops=8)
    assert 0.4 <= far["mean_ratio"] < 0.5 and far["width_ratio"] <= 1.5
    # The cap: 2 px at the drop's range, never more than the smear itself.
    pixel = twin.pixel_angle_rad(fov)
    assert twin.defocus_blur_cm(6.25 * 0.25, 300.0, pixel) == pytest.approx(2.0 * 300.0 * pixel)
    assert twin.defocus_blur_cm(0.05, 300.0, pixel) == 0.05
    assert twin.defocus_blur_cm(0.0, 300.0, pixel) == 0.0


def test_the_light_is_conserved_where_the_cap_does_not_bind():
    """Garg & Nayar: a smeared or lengthened streak carries the same light (coverage x
    area), in both generations and over both shutters."""
    for shutter in (twin.STILL_SHUTTER_S, weather_look.BEAUTY_RAIN_CLIP_SHUTTER_S):
        for r in (2.0, 5.0, 10.0):
            c = twin.near_drop_comparison(r, 2.0, 1.0, shutter_s=shutter, samples=16, drops=8)
            assert c["light_ratio"] == pytest.approx(1.0, abs=0.03), (shutter, r, c)
    # A clip's streak is ~10x the still's and ~10x fainter per pixel: the same drop's light.
    still = twin.drop_pixel(2.0, precipitation.terminal_velocity_mps(2.0), twin.STILL_SHUTTER_S, 300.0,
                            twin.pixel_angle_rad(), 1.0, twin.current_shape(0.0, max_streak_rad=0.0))
    clip = twin.drop_pixel(2.0, precipitation.terminal_velocity_mps(2.0), weather_look.BEAUTY_RAIN_CLIP_SHUTTER_S,
                           300.0, twin.pixel_angle_rad(), 1.0, twin.current_shape(0.0, max_streak_rad=0.0))
    assert clip["streak_cm"] / still["streak_cm"] == pytest.approx(500.0 / 48.0, rel=1e-9)
    assert still["coverage"] / clip["coverage"] == pytest.approx(500.0 / 48.0, rel=1e-9)


# -- the shutter: a still's drops are the view's; a clip's streak over its motion blur -----------

def test_the_streak_shutter_follows_the_frames_motion_blur_still_sharp_clip_blurred():
    # The Python twin of Advance's StreakShutter.
    f = weather_look.beauty_rain_streak_shutter_s
    assert f(1.0 / 500.0) == 1.0 / 500.0                       # a still, a measure render: the view's
    assert f(1.0 / 500.0, 1.0 / 48.0) == 1.0 / 48.0            # a clip: the camera's motion blur
    assert f(1.0 / 500.0, 1.0 / 48.0, cinematic=True) == 1.0 / 15.0
    assert f(0.0) == 1.0e-5
    assert weather_look.BEAUTY_RAIN_CLIP_SHUTTER_S == beauty_look.shutter_seconds(24.0) == 1.0 / 48.0
    assert "shutter_s" not in weather_look.BEAUTY_RAIN_KEYS   # the shape carries no exposure
    assert tuple(weather_look.beauty_rain_shape(40.0, 262144)) == weather_look.BEAUTY_RAIN_KEYS
    # The C++: the view carries the motion-blur shutter; Advance uses it only when set.
    assert "double MotionBlurShutterSeconds = 0.0;" in WEATHER_H
    advance = _function(WEATHER_CPP, "void FFlightSimWeather::Advance(")
    assert ("const double StreakShutter = !bCinematicRain && View.MotionBlurShutterSeconds > 0.0\n"
            "\t\t? View.MotionBlurShutterSeconds : Shutter;") in advance
    assert 'TEXT("Shutter"), static_cast<float>(StreakShutter)' in advance
    assert "StepRainLayers(Wind, CameraVelocity, Share, StreakShutter, Dt, PixelAngle);" in advance
    assert 'TEXT("User.Shutter"), static_cast<float>(StreakShutter)' in advance
    # The lightning's window and the windscreen keep the view's shutter.
    assert "WindowPower(Curve, Flash, T - Shutter, T)" in advance
    assert "StepWindscreenBaked(T, View.ShutterSeconds, View.HorizontalFovDeg);" in advance
    assert ("const double Shutter = bCinematicRain ? WeatherCinematicShutterS : "
            "FMath::Max(View.ShutterSeconds, 1.0e-5);") in advance
    # No constant shutter anywhere in the weather: the shape, the readability, the members.
    for gone in ("BeautyShutterS", "Shape.ShutterS", "WeatherBeautyRainShutterS", "0.020833333333333332"):
        assert gone not in WEATHER_CPP and gone not in WEATHER_H, gone


def test_the_commandlet_sets_the_motion_blur_shutter_on_a_beauty_clip_only():
    site = COMMANDLET[COMMANDLET.index("WeatherView.MotionBlurShutterSeconds = 0.0;"):
                      COMMANDLET.index("Weather.Advance(WeatherView);")]
    assert ("if (bBeautyRaster && !bBeautyStill && Capture->ShowFlags.MotionBlur != 0 &&\n"
            "\t\t\t    Capture->PostProcessSettings.MotionBlurAmount > 0.0f)") in site
    assert ("const double BlurFps = Capture->PostProcessSettings.MotionBlurTargetFPS > 0\n"
            "\t\t\t\t\t? static_cast<double>(Capture->PostProcessSettings.MotionBlurTargetFPS) : FramesPerSecond;") in site
    assert "static_cast<double>(Capture->PostProcessSettings.MotionBlurAmount) / BlurFps;" in site
    # The same still/clip decision that turns motion blur off, declared before and in scope.
    assert "const bool bBeautyStill = bBeautyRaster && DeliveredFrames <= RenderBeautyStillMaxFrames;" in COMMANDLET
    assert COMMANDLET.index("FFlightSimBeautyLook::ApplyShutterPolicy(Capture, bBeautyStill);") < COMMANDLET.index(
        "WeatherView.MotionBlurShutterSeconds = 0.0;")
    assert COMMANDLET.count("WeatherView.MotionBlurShutterSeconds") == 3
    # The view's shutter itself is unchanged (tests/test_ue_weather_source.py pins the rule).
    assert ("WeatherView.ShutterSeconds = ExposureShutterSeconds > 0.0\n"
            "\t\t\t\t? ExposureShutterSeconds\n"
            "\t\t\t\t: FMath::Min(static_cast<double>(StepsPerFrame) * DeltaSeconds, WeatherDefaultShutterS);") in COMMANDLET
    # The host's motion blur IS the plan's 180-degree shutter: MotionBlurAmount over MotionBlurTargetFPS.
    plan = beauty_look.plan_beauty_look(30.0, fps=24.0, width_px=1280)
    camera = plan["camera"]
    assert camera["MotionBlurAmount"] / camera["MotionBlurTargetFPS"] == pytest.approx(beauty_look.shutter_seconds(24.0))


def test_the_record_names_the_shutter_the_drops_actually_used_beside_the_views():
    advance = _function(WEATHER_CPP, "void FFlightSimWeather::Advance(")
    assert 'Record->SetNumberField(TEXT("streak_shutter_s"), StreakShutter);' in advance
    assert 'TEXT("streak_shutter_basis")' in advance
    assert "StreakShutter != RecordedStreakShutterS" in advance and "RecordedStreakShutterS = StreakShutter;" in advance
    assert "double RecordedStreakShutterS = -1.0;" in WEATHER_H
    for basis in ("the cinematic style's stated 1/15 s",
                  "a beauty clip: the camera's motion-blur shutter (MotionBlurAmount / MotionBlurTargetFPS)",
                  "the view's shutter (weather.shutter_s): a beauty still has motion blur off"):
        assert basis in advance, basis
    site = COMMANDLET[COMMANDLET.index("if (!bWeatherShutterRecorded && Weather.Record.IsValid())"):
                      COMMANDLET.index("Weather.Advance(WeatherView);")]
    assert 'Weather.Record->SetNumberField(TEXT("shutter_s"), WeatherView.ShutterSeconds);' in site
    assert site.count("the drops' own is streak_shutter_s") == 2
    assert 'TEXT("motion_blur_shutter_s"), WeatherView.MotionBlurShutterSeconds' in site
    readability = _function(WEATHER_CPP, "void FFlightSimWeather::ApplyBeautyRainReadability(")
    assert 'TEXT("shutter_s")' not in readability
    assert 'TEXT("streak_shutter")' in readability and "weather.streak_shutter_s" in readability


# -- the C++ twins, evaluated from their text against the Python ----------------------------------

def test_the_cpp_lens_and_curtain_twins_give_the_python_values():
    d0 = 3.67 / precipitation.mp_lambda(40.0)
    cpp = _cpp_weather(BeautyFNumber=weather_look.BEAUTY_RAIN_F_NUMBER, BeautySensorMm=weather_look.BEAUTY_RAIN_SENSOR_MM,
                       BeautyDefocusShare=weather_look.BEAUTY_RAIN_DEFOCUS_SHARE, D0Mm=d0)
    for fov in (8.2, 20.0, 54.0, 90.0, 120.0):
        assert cpp["BeautyApertureCm"](fov) == pytest.approx(weather_look.beauty_rain_aperture_cm(fov), rel=1e-12)
        assert cpp["BeautyDefocusCm"](fov) == pytest.approx(weather_look.beauty_rain_defocus_cm(fov), rel=1e-12)
        pixel = twin.pixel_angle_rad(fov)
        for shell in rain_veil.VEIL_SHELL_RADII_M:
            expected = rain_veil.curtain_streak_alpha(shell, pixel, rain_field.presented_width_mm(max(d0, 0.5)))
            assert cpp["CurtainStreakAlpha"](shell, pixel) == pytest.approx(expected, rel=1e-12), (fov, shell)
    for d in (0.5, 1.0, 2.0, 4.0, 6.0):
        assert cpp["PresentedWidthMm"](d) == pytest.approx(rain_field.presented_width_mm(d), rel=1e-12)
    assert cpp["BeautyApertureCm"](0.0) == 0.0 and cpp["BeautyApertureCm"](180.0) == 0.0
    assert cpp["CurtainStreakAlpha"](25.0, 0.0) == rain_veil.VEIL_STREAK_ALPHA
    off = _cpp_weather(BeautyFNumber=0.0, BeautySensorMm=36.0, BeautyDefocusShare=0.25, D0Mm=d0)
    assert off["BeautyApertureCm"](54.0) == 0.0 and off["BeautyDefocusCm"](54.0) == 0.0
    # The C++ constants are the Python's.
    shape = _function(WEATHER_CPP, "FFlightSimBeautyRainShape FFlightSimWeather::BeautyRainShape(")
    assert _cpp_constant(shape, "WeatherBeautyRainMaxCoverage") == weather_look.BEAUTY_RAIN_MAX_COVERAGE == 0.18
    assert _cpp_constant(shape, "WeatherBeautyRainFNumber") == weather_look.BEAUTY_RAIN_F_NUMBER
    assert _cpp_constant(shape, "WeatherBeautyRainSensorMm") == weather_look.BEAUTY_RAIN_SENSOR_MM
    assert _cpp_constant(shape, "WeatherBeautyRainDefocusShare") == weather_look.BEAUTY_RAIN_DEFOCUS_SHARE
    assert _cpp_constant(shape, "WeatherBeautyRainSceneLit") == weather_look.BEAUTY_RAIN_SCENE_LIT
    assert _cpp_constant(WEATHER_CPP, "WeatherBeautyRainDefocusMaxPx") == weather_look.BEAUTY_RAIN_DEFOCUS_MAX_PX
    veil = WEATHER_CPP[WEATHER_CPP.index("namespace FlightSimRainVeil\n{\n\tconstexpr double VeilShellRadiusNearM"):]
    assert _cpp_constant(veil, "VeilStreakProfileMean") == rain_veil.VEIL_STREAK_PROFILE_MEAN
    assert _cpp_constant(veil, "VeilStreakKeepMin") == rain_veil.VEIL_STREAK_KEEP_MIN
    for name in ("FNumber", "SensorMm", "DefocusShare"):
        assert f"Beauty{name} = Shape.{name};" in _function(WEATHER_CPP, "void FFlightSimWeather::ApplyBeautyRainReadability(")
        assert WEATHER_CPP.count(f"Beauty{name} = Shape.") == 1, name
    # The shader's pixel cap is the same literal in both shaders and in the Python.
    for text in (OFFSET, OPACITY):
        assert f"const float RainDefocusMaxPx = {weather_look.BEAUTY_RAIN_DEFOCUS_MAX_PX:.1f};" in text
        assert "float blur = min(Aperture, RainDefocusMaxPx * dist * PixelAngle);" in text
        assert "streak += blur;" in text and "width = max(width, sharp + blur);" in text
    advance = _function(WEATHER_CPP, "void FFlightSimWeather::Advance(")
    assert 'TEXT("Aperture")' in advance and "BeautyDefocusCm(View.HorizontalFovDeg)" in advance
    assert WEATHER_CPP.count('TEXT("Aperture")') == 1


def test_the_curtain_streak_keeps_the_light_of_the_drops_width_floored():
    assert rain_veil.VEIL_STREAK_PROFILE_MEAN == 0.441
    xs = [i / 2000.0 - 0.5 for i in range(2001)]
    assert abs(sum(math.exp(-16.0 * x * x) for x in xs) / len(xs) - 0.441) < 0.002
    pixel = rain_veil.BEAUTY_REFERENCE_PIXEL_RAD
    alpha = rain_veil.VEIL_STREAK_ALPHA
    near, mid, far = (rain_veil.curtain_streak_alpha(r, pixel, 2.0) for r in rain_veil.VEIL_SHELL_RADII_M)
    # Unfloored, 25 m keeps 0.11 and 250 m 0.011 of the alpha: the floor holds every shell at 0.25.
    assert near == mid == far == pytest.approx(alpha * rain_veil.VEIL_STREAK_KEEP_MIN)
    unfloored = [2.0 / 10.0 / (r * 100.0 * 2.0 * 0.441 * pixel) for r in rain_veil.VEIL_SHELL_RADII_M]
    assert unfloored[0] == pytest.approx(0.114, abs=0.001) and unfloored[2] == pytest.approx(0.0114, abs=0.0001)
    assert all(u < rain_veil.VEIL_STREAK_KEEP_MIN for u in unfloored)
    # A 250 mm lens (7x the reference pixel) nearly resolves a 25 m drop and keeps most of it.
    long_lens = rain_veil.curtain_streak_alpha(25.0, pixel / 7.0, 2.0)
    assert alpha * 0.75 < long_lens <= alpha   # 7 x 0.114: 0.8 of the alpha
    assert rain_veil.curtain_streak_alpha(250.0, pixel / 7.0, 2.0) == pytest.approx(alpha * rain_veil.VEIL_STREAK_KEEP_MIN)
    assert rain_veil.curtain_streak_alpha(25.0, 0.0, 2.0) == alpha
    step = _function(WEATHER_CPP, "void FFlightSimWeather::StepBeautyRainVeil(")
    assert "CurtainStreakAlpha(VeilShellRadiiM[Shell], PixelAngle)" in step and 'TEXT("StreakAlpha")' in step
    assert "double CurtainStreakAlpha(double ShellRadiusM, double PixelAngle) const;" in WEATHER_H


# -- the light, the material, the generation -------------------------------------------------------

def test_the_drop_takes_its_radiance_from_the_scene_behind_it_beauty_only():
    assert 0.0 < weather_look.BEAUTY_RAIN_SCENE_LIT < 1.0
    assert weather_look.beauty_rain_shape(10.0, 262144)["scene_lit"] == weather_look.BEAUTY_RAIN_SCENE_LIT
    readability = _function(WEATHER_CPP, "void FFlightSimWeather::ApplyBeautyRainReadability(")
    assert 'RainMaterial->SetScalarParameterValue(TEXT("SceneLit")' in readability
    assert WEATHER_CPP.count('TEXT("SceneLit")') == 1
    for key in ("f_number", "sensor_mm", "defocus_share", "defocus_max_px", "scene_lit"):
        assert f'TEXT("{key}")' in readability, key
    assert re.search(r"//\s+A\s", TONE) and re.search(r"//\s+SceneLit\s", TONE)
    lit = SCRIPT[SCRIPT.index("def drop_lit"):SCRIPT.index("def _translucent_unlit")]
    assert "def drop_lit(material, lib, x, y, scene_lit=False):" in lit
    assert 'custom(material, lib, "drop_scene_tone"' in lit
    assert "unreal.MaterialExpressionOneMinus, lit_share" in lit
    assert 'tap.set_editor_property("const_input", unreal.Vector2D(0.0, 0.0))' in lit
    assert "MaterialExpressionAdd, glow, tone" in lit
    drops = SCRIPT[SCRIPT.index("def create_rain_drops"):SCRIPT.index("def _veil_lit")]
    assert "drop_lit(material, lib, -900, 800, scene_lit=True)" in drops
    splash = SCRIPT[SCRIPT.index("def create_rain_splash"):].split("\ndef ", 2)[0]
    assert "scene_lit=True" not in splash


def test_the_new_parameters_are_exposed_default_off_and_the_generation_is_bumped():
    params = _assigned("DROPS_PARAMETERS")
    assert "Aperture" in params and "SceneLit" in params
    defaults = _assigned("DROPS_BEAUTY_DEFAULTS")
    assert defaults["Aperture"] == 0.0 and defaults["SceneLit"] == 0.0
    # The shader body changed again (the defocus rule): the render machine rebuilds it.
    assert _assigned("STORM_GENERATIONS")["M_RainDrops"] == "8"
    drops = SCRIPT[SCRIPT.index("def create_rain_drops"):SCRIPT.index("def _veil_lit")]
    before, after = drops.split('lib, "rain_drop_opacity"')
    assert '"Aperture": params["Aperture"]' in before and '"Aperture": params["Aperture"]' in after
    assert '"FlashLux", "SceneLit")}' in drops
    assert _assigned("STORM_GENERATIONS")["M_RainCurtain"] == "6"   # the curtain's graph is unchanged
    for text in (OFFSET, OPACITY):
        assert text.count("if (Aperture > 0.0)") == 1
        assert text.index("width *= 1.0 + Soft;") < text.index("if (Aperture > 0.0)")
    cap = OPACITY.index("float shown = min(saturate(coverage), MaxCoverage);")
    assert cap < OPACITY.index("if (Soft > 0.0 || Vary > 0.0)"), "the cap is applied before the soft profile"
    assert "shown = saturate(shown * across * along * bright);" in OPACITY
