"""2026-11-15 (hyperreal light lane tornado): -tornado-shade=funnel, the vdb card shaded
as a condensation funnel (M_TornadoFlipbook 3). p3-windows drew #10's card as a near-black
sooty plume with a wispy outline, no striations, no rope foot and a brown wash over the
desert. These tests run the material's actual HLSL (straight-line code, translated to
numpy) over the committed atlas and check the numbers that defect was made of, and that
-tornado-shade=smoke (the material's defaults) is generation 2 exactly."""
import ast
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest

from core.scene import weather_look

REPO = Path(__file__).resolve().parents[1]
SHADERS = REPO / "assets/shaders/weather"
PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
PUBLIC = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public"
BEAUTY_CPP = (PRIVATE / "FlightSimTornadoBeauty.cpp").read_text(encoding="utf-8")
RENDER_CPP = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
WORLD_H = (PUBLIC / "FlightSimScenarioWorld.h").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts/ue_create_materials.py").read_text(encoding="utf-8")
FUNNEL = weather_look.BEAUTY_TORNADO_FLIPBOOK_FUNNEL


def _assigned(name):
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value
    raise KeyError(name)


def _literal(name):
    return ast.literal_eval(_assigned(name))


# -- the HLSL, run in numpy ---------------------------------------------------------------

def _hlsl(name):
    """A straight-line Custom-node body as a numpy function of its named inputs."""
    code = (SHADERS / f"{name}.hlsl").read_text(encoding="utf-8")
    lines = [l.split("//")[0].strip() for l in code.splitlines()]
    body = []
    for line in filter(None, lines):
        line = line.rstrip(";")
        line = re.sub(r"^float[234]?\s+(\w+)\s*=", r"\1 =", line)
        line = re.sub(r"^return\s+", "_ret = ", line)
        line = re.sub(r"\b(\w+)\.([xyzw])\b", lambda m: f"{m.group(1)}[{'xyzw'.index(m.group(2))}]", line)
        line = re.sub(r"\bfloat[234]\(", "_vec(", line)
        line = re.sub(r"=\s*(.+?)\s*\?\s*(\S+)\s*:\s*(\S+)$", r"= np.where(\1, \2, \3)", line)
        body.append(line)
    env = {"np": np, "saturate": lambda x: np.clip(x, 0.0, 1.0), "lerp": lambda a, b, t: a + (b - a) * t,
           "clamp": np.clip, "max": np.maximum, "abs": np.abs, "sqrt": np.sqrt, "sin": np.sin,
           "asin": np.arcsin, "pow": np.power, "_vec": lambda *a: tuple(a)}
    source = "\n".join(body)

    def run(**inputs):
        scope = dict(env, **inputs)
        exec(source, scope)  # noqa: S102 -- the repo's own shader text
        return scope["_ret"]
    return run


SHAPE = _hlsl("tornado_flipbook_shape")
SPIN = _hlsl("tornado_flipbook_spin")
TONE = _hlsl("tornado_flipbook_tone")
CROP = _literal("TORNADO_FLIPBOOK_CROP_V")
TAPER = _literal("TORNADO_FLIPBOOK_TAPER")
TOP_FADE = _literal("TORNADO_FLIPBOOK_TOP_FADE")
SHADE_FLOOR = _literal("TORNADO_FLIPBOOK_SHADE_FLOOR")
DUST_SHARE = _literal("TORNADO_FLIPBOOK_DUST_SHARE")
DUST_TINT = np.array(_literal("TORNADO_FLIPBOOK_DUST_TINT"))


def _cpp_float(name):
    match = re.search(rf"constexpr (?:float|double) {name} = ([0-9.]+)f?;", BEAUTY_CPP)
    assert match, name
    return float(match.group(1))


def _gen2_parameters():
    """The material's defaults, from the script's literal (each is generation 2's value)."""
    out = _literal("TORNADO_FLIPBOOK_GEN2_DEFAULTS")
    assert (out["ShadeFloor"], out["BottomWidth"], out["DustShare"]) == \
        (SHADE_FLOOR, TAPER["bottom_width"], DUST_SHARE)              # the generation-2 constants
    return out


def _funnel_parameters(card_height_m, omega_rad_s=50.0 / 150.0):
    return {"ShadeFloor": FUNNEL["shade_floor"], "AlphaLo": FUNNEL["alpha_lo"], "AlphaHi": FUNNEL["alpha_hi"],
            "SheathLift": FUNNEL["sheath_lift"], "Spin": -omega_rad_s, "Bands": FUNNEL["bands"],
            "Contrast": FUNNEL["contrast"], "Corrugate": FUNNEL["corrugate"],
            "BottomWidth": FUNNEL["bottom_width"], "DustShare": weather_look.flipbook_dust_share(card_height_m)}


def _card(params, tint, texel_lookup, n_v=210, n_u=172, time=0.0):
    """The card's (base colour, opacity) on an n_v x n_u grid through the three shaders."""
    v, u = np.meshgrid((np.arange(n_v) + 0.5) / n_v, (np.arange(n_u) + 0.5) / n_u, indexing="ij")
    shape = SHAPE(UV=(u, v), CropTop=CROP[0], CropBottom=CROP[1], TopWidth=TAPER["top_width"],
                  BottomWidth=params["BottomWidth"], TaperPower=TAPER["power"], TopFade=TOP_FADE,
                  DustShare=params["DustShare"])
    spin = SPIN(Shape=shape, Time=time, Spin=params["Spin"], Bands=params["Bands"], CropTop=CROP[0],
                CropBottom=CROP[1], Contrast=params["Contrast"], Corrugate=params["Corrugate"])
    grey, alpha = texel_lookup(spin[0], spin[1])
    shade, opacity = TONE(TexelA=alpha, TexelR=grey, Weight=shape[2], Striation=spin[2],
                          ShadeFloor=params["ShadeFloor"], AlphaLo=params["AlphaLo"], AlphaHi=params["AlphaHi"],
                          SheathLift=params["SheathLift"], Opacity=1.0)
    dust = shape[3][..., None]
    colour = (np.asarray(tint)[None, None, :] * (1.0 - dust) + DUST_TINT[None, None, :] * dust) * shade[..., None]
    return colour, opacity, v


@pytest.fixture(scope="module")
def frame0():
    pin = json.loads((REPO / "assets/looks/tornado_vdb/PIN.json").read_text(encoding="utf-8"))
    if not pin["files"]:
        pytest.skip("no bake on this checkout")
    image = pytest.importorskip("PIL.Image")
    plan = json.loads((REPO / "assets/looks/tornado_vdb/tornado_flipbook.json").read_text(encoding="utf-8"))
    atlas = np.asarray(image.open(REPO / "assets/looks/tornado_vdb/T_TornadoFlipbook.png").convert("RGBA"))
    fw, fh = plan["frame_px"]
    frames = [atlas[(i // plan["cols"]) * fh:(i // plan["cols"] + 1) * fh,
                    (i % plan["cols"]) * fw:(i % plan["cols"] + 1) * fw] / 255.0 for i in range(plan["frames"])]
    return plan, frames


def _lookup(frame):
    fh, fw = frame.shape[:2]

    def at(u, v):
        x = np.clip((np.asarray(u) * fw).astype(int), 0, fw - 1)
        y = np.clip((np.asarray(v) * fh).astype(int), 0, fh - 1)
        return frame[y, x, 0], frame[y, x, 3]
    return at


def _default_card_m(plan):
    funnel_top = weather_look.FUNNEL_TOP_SHARE * 1500.0          # core/environment/tornado.py TOP_M
    height = weather_look.BEAUTY_TORNADO_FLIPBOOK_HEIGHT_SHARE * funnel_top
    return height, height * plan["frame_aspect"] / (CROP[1] - CROP[0])


# -- smoke = generation 2 exactly ------------------------------------------------------------

def test_the_material_defaults_are_generation_2_bit_for_bit():
    rng = np.random.default_rng(15)
    p = _gen2_parameters()
    assert p == {"ShadeFloor": 0.35, "AlphaLo": 0.0, "AlphaHi": 1.0, "SheathLift": 0.0, "Spin": 0.0,
                 "Bands": 0.0, "Contrast": 0.0, "Corrugate": 0.0, "BottomWidth": 0.5, "DustShare": 0.35}
    shape = tuple(rng.random(4000) for _ in range(4))
    spin = SPIN(Shape=shape, Time=rng.random(4000) * 600.0, Spin=p["Spin"], Bands=p["Bands"],
                CropTop=CROP[0], CropBottom=CROP[1], Contrast=p["Contrast"], Corrugate=p["Corrugate"])
    assert np.array_equal(spin[0], shape[0]) and np.array_equal(spin[1], shape[1])
    assert np.array_equal(spin[2], np.ones(4000))
    a, r, w = rng.random(4000), rng.random(4000), rng.random(4000)
    shade, alpha = TONE(TexelA=a, TexelR=r, Weight=w, Striation=spin[2], ShadeFloor=p["ShadeFloor"],
                        AlphaLo=p["AlphaLo"], AlphaHi=p["AlphaHi"], SheathLift=p["SheathLift"], Opacity=1.0)
    # Generation 2's graph: shade = lerp(0.35, 1, r); alpha = a x weight x opacity.
    assert np.array_equal(shade, 0.35 + (1.0 - 0.35) * r) and np.array_equal(alpha, a * w * 1.0)


def test_the_switch_parses_refuses_and_smoke_sets_nothing_new():
    call = RENDER_CPP.index("Scenario.BuildBeautyTornado(")
    block = RENDER_CPP[RENDER_CPP.index('FString TornadoShade = TEXT("funnel");'):call]
    assert 'TEXT("tornado-shade="), TornadoShade);' in block and "FLIGHTSIM_RENDER_SWITCHES" in block
    assert 'if (bBeauty && TornadoShade != TEXT("funnel") && TornadoShade != TEXT("smoke"))' in block
    assert "render.tornado_shade:" in block and "Scenario.TornadoShade = TornadoShade;" in block
    assert 'FString TornadoShade = TEXT("funnel");' in WORLD_H
    catalog = (REPO / "core/messages/catalog.yaml").read_text(encoding="utf-8")
    assert "\nrender.tornado_shade:\n" in catalog
    assert weather_look.BEAUTY_TORNADO_FLIPBOOK_SHADES == ("funnel", "smoke")
    vdb = BEAUTY_CPP[BEAUTY_CPP.index('if (TornadoLook == TEXT("vdb"))'):BEAUTY_CPP.index("if (Record.IsValid())\n\t{\n\t\tTSharedPtr")]
    assert 'const bool bFunnelShade = TornadoShade != TEXT("smoke");' in vdb
    # Every generation-3 parameter is set only inside the funnel branch, so smoke keeps the defaults.
    funnel = vdb[vdb.index("if (bFunnelShade)\n"):vdb.index("UMaterialBillboardComponent* Board")]
    for name in ("ShadeFloor", "AlphaLo", "AlphaHi", "SheathLift", "Spin", "Bands", "Contrast", "Corrugate",
                 "BottomWidth", "DustShare"):
        assert f'FName(TEXT("{name}"))' in funnel, name
        assert vdb.count(f'FName(TEXT("{name}"))') == 1, name
    assert 'Row->SetStringField(TEXT("tornado_shade"), TornadoShade);' in BEAUTY_CPP


# -- the C++ and the Python twin --------------------------------------------------------------

def test_the_cpp_numbers_are_the_python_twins_and_the_albedo_is_two_stream():
    colour = tuple(_cpp_float(f"BeautyFlipbookFunnelColour{c}") for c in "RGB")
    assert colour == FUNNEL["colour"]
    for cpp, key in (("ShadeFloor", "shade_floor"), ("AlphaLo", "alpha_lo"), ("AlphaHi", "alpha_hi"),
                     ("SheathLift", "sheath_lift"), ("Bands", "bands"), ("Contrast", "contrast"),
                     ("Corrugate", "corrugate"), ("BottomWidth", "bottom_width"), ("DustShareMax", "dust_share_max")):
        assert _cpp_float(f"BeautyFlipbookFunnel{cpp}") == FUNNEL[key], cpp
    # tau = 3 LWC L / (2 rho_w r_e) = 15 for 0.5 g/m^3, 10 um, 200 m; R = 2.25 / 4.25 = 0.53.
    assert weather_look.tornado_flipbook_albedo() == pytest.approx(0.53, abs=0.005)
    assert FUNNEL["colour"][0] == pytest.approx(weather_look.tornado_flipbook_albedo(), abs=0.005)
    assert len(set(FUNNEL["colour"])) == 1                                     # water cloud is grey
    assert min(FUNNEL["colour"]) > 3.0 * max(weather_look.BEAUTY_WALL_CLOUD_COLOUR)
    assert FUNNEL["dust_share_max"] == DUST_SHARE
    assert weather_look.dust_whirl_top_m() == _cpp_float("BeautyDustTopM") + 0.75 * _cpp_float("BeautyDustSizeMaxM")
    assert "const double DustWhirlTopM = BeautyDustTopM + 0.75 * BeautyDustSizeMaxM;" in BEAUTY_CPP
    assert ("FlipbookDustSortOffsetM = 0.5 * FlipbookHeightM\n\t\t\t\t\t+ RCore * (BeautyDustRadiiMax + "
            "BeautyDustJitterRadii) + DustWhirlTopM;") in BEAUTY_CPP
    assert weather_look.flipbook_dust_sort_offset_m(1050.0, 150.0) == pytest.approx(525.0 + 222.0 + 87.5)
    # Spin: the core's solid-body rate, the sign flipped from UE yaw to the card's right.
    assert "static_cast<float>(-FMath::DegreesToRadians(TornadoOmegaDegPerSec))" in BEAUTY_CPP


def test_the_whirl_sorts_over_the_card_from_every_camera():
    """No dust puff can sort behind the card's centre: the triangle inequality bound the
    offset rests on, checked over random cameras and the whirl's extreme puffs."""
    rng = np.random.default_rng(7)
    height, rcore = 1050.0, 150.0
    offset = weather_look.flipbook_dust_sort_offset_m(height, rcore)
    reach = rcore * weather_look.dust_whirl_extent_radii()
    top = weather_look.dust_whirl_top_m()
    card = np.array([0.0, 0.0, 0.5 * height])
    for _ in range(2000):
        cam = rng.uniform([-6000, -6000, 2], [6000, 6000, 4000])
        ang = rng.uniform(0, 2 * math.pi)
        puff = np.array([reach * math.cos(ang), reach * math.sin(ang), rng.uniform(0, top)])
        assert np.linalg.norm(puff - cam) - offset < np.linalg.norm(card - cam)
    # Only the dust actor's puffs move, only under funnel, only in the vdb block.
    vdb = BEAUTY_CPP[BEAUTY_CPP.index('if (TornadoLook == TEXT("vdb"))'):]
    assert "if (bFunnelShade && TornadoDust != nullptr)" in vdb
    assert BEAUTY_CPP.count("SetTranslucencySortDistanceOffset(") == 1
    assert "TornadoDust->GetComponents<UPrimitiveComponent>(DustPuffs);" in vdb


# -- the atlas through the shaders: the defect's numbers -------------------------------------

def _visible(opacity):
    return opacity > 0.02


def test_funnel_is_lighter_than_the_storm_base_and_has_a_crisp_edge(frame0):
    plan, frames = frame0
    height, _ = _default_card_m(plan)
    wall = max(weather_look.BEAUTY_WALL_CLOUD_COLOUR)
    smoke = dict(_gen2_parameters())
    funnel = _funnel_parameters(height)
    stats = {}
    for name, params, tint in (("smoke", smoke, weather_look.BEAUTY_TORNADO_FLIPBOOK_COLOUR),
                               ("funnel", funnel, FUNNEL["colour"])):
        albedo, wisp = [], []
        for frame in frames[::8]:
            colour, opacity, v = _card(params, tint, _lookup(frame))
            body = (opacity > 0.5) & (v < 0.85)                  # above the dust tint
            albedo.append(colour[body].mean())
            vis = _visible(opacity)
            wisp.append(((opacity < 0.3) & vis).sum() / max(vis.sum(), 1))
        stats[name] = (float(np.mean(albedo)), float(np.mean(wisp)))
    # Generation 2: the funnel's albedo is the wall cloud's own (the near-black plume).
    assert stats["smoke"][0] < 1.2 * wall
    # Funnel: grey, at least 2x the storm base's albedo (the look-dev tune of 2026-11-15 took it
    # from ~3x, which read paper-white on #10, to ~2.2x) and never white.
    # Round 147: ~4x (the r144 near-black cap), still below 0.6, never white.
    assert 2.0 * wall < stats["funnel"][0] < 0.6
    # The wispy outline: the share of the visible card that is faint (opacity < 0.3) smoke,
    # 0.38 in generation 2, cut by at least 40 % (what remains is the taper and top fade's edge).
    assert stats["smoke"][1] > 0.3 and stats["funnel"][1] < 0.6 * stats["smoke"][1]


def test_funnel_narrows_to_a_rope_at_the_ground(frame0):
    """The card's VISIBLE outline (alpha > 0.02) at 40, 60, 75, 90 and 97 % of its height
    down: generation 2's hazy foot (83 m at the ground, 120 m at 10 % up) against the mesh
    look's 48 m rope (0.16 x 150 m x 2)."""
    plan, frames = frame0
    height, width = _default_card_m(plan)
    widths = {}
    for name, params in (("smoke", _gen2_parameters()), ("funnel", _funnel_parameters(height))):
        rows = []
        for frame in frames[::8]:
            _, opacity, v = _card(params, (0.5, 0.5, 0.5), _lookup(frame), n_v=100, n_u=400)
            rows.append([_visible(opacity[i]).mean() * width for i in (40, 60, 75, 90, 97)])
        widths[name] = np.mean(rows, axis=0)
    funnel, smoke = widths["funnel"], widths["smoke"]
    assert all(np.diff(funnel) < 0)                             # narrowing all the way down
    assert all(funnel < smoke)                                  # narrower than generation 2 everywhere
    assert smoke[-1] > 75.0 and smoke[-2] > 110.0               # the defect: a hazy foot
    assert funnel[-1] < 50.0 and funnel[-2] < 80.0              # the rope: the mesh look's 48 m
    assert funnel[0] > 6.0 * funnel[-1]                         # flaring into the wall cloud


def test_the_striations_band_the_funnel_and_turn_with_time(frame0):
    plan, frames = frame0
    height, _ = _default_card_m(plan)
    params = _funnel_parameters(height)
    flat = dict(params, Contrast=0.0, Corrugate=0.0)
    lookup = _lookup(frames[0])
    banded, opacity, v = _card(params, (0.5, 0.5, 0.5), lookup, n_v=420, n_u=86)
    plain, _, _ = _card(flat, (0.5, 0.5, 0.5), lookup, n_v=420, n_u=86)
    centre = banded.shape[1] // 2
    rows = (opacity[:, centre] > 0.5) & (v[:, centre] > 0.3) & (v[:, centre] < 0.8)
    ratio = banded[rows, centre, 0] / plain[rows, centre, 0]
    # Bands: the brightness swings +-Contrast about 1 along the axis (several crossings).
    assert ratio.max() == pytest.approx(1.0 + FUNNEL["contrast"], abs=0.02)
    assert ratio.min() == pytest.approx(1.0 - FUNNEL["contrast"], abs=0.02)
    crossings = np.count_nonzero(np.diff(np.sign(ratio - 1.0)) != 0)
    assert crossings >= 4
    # Turning: a quarter turn of the core (pi / 2 / omega s) moves the bands a quarter period.
    omega = 50.0 / 150.0
    later, _, _ = _card(params, (0.5, 0.5, 0.5), lookup, n_v=420, n_u=86, time=0.5 * math.pi / omega)
    later_ratio = later[rows, centre, 0] / plain[rows, centre, 0]
    assert not np.allclose(later_ratio, ratio, atol=0.01)
    full, _, _ = _card(params, (0.5, 0.5, 0.5), lookup, n_v=420, n_u=86, time=2.0 * math.pi / omega)
    assert np.allclose(full[rows, centre, 0] / plain[rows, centre, 0], ratio, atol=1e-3)


def test_the_dust_tint_stays_within_the_whirl(frame0):
    plan, frames = frame0
    height, _ = _default_card_m(plan)
    share = weather_look.flipbook_dust_share(height)
    assert share == pytest.approx(87.5 / height) and share < DUST_SHARE / 3.0
    v = np.linspace(0.0, 1.0, 2001)
    shape = SHAPE(UV=(np.full_like(v, 0.5), v), CropTop=CROP[0], CropBottom=CROP[1], TopWidth=1.0,
                  BottomWidth=FUNNEL["bottom_width"], TaperPower=TAPER["power"], TopFade=TOP_FADE, DustShare=share)
    tinted_m = (1.0 - v[shape[3] > 0.0].min()) * height
    assert tinted_m <= weather_look.dust_whirl_top_m() + 1.0
    old = SHAPE(UV=(np.full_like(v, 0.5), v), CropTop=CROP[0], CropBottom=CROP[1], TopWidth=1.0,
                BottomWidth=0.5, TaperPower=TAPER["power"], TopFade=TOP_FADE, DustShare=DUST_SHARE)
    assert (1.0 - v[old[3] > 0.0].min()) * height > 350.0       # generation 2: a brown 370 m


def test_the_plume_half_width_in_the_spin_shader_is_the_atlas_measurement(frame0):
    """tornado_flipbook_spin.hlsl's hw(av): 0.59 of the frame at atlas v 0.35, 0.15 at 0.75
    (the plume's full width at alpha > 0.3, mean over the frames)."""
    plan, frames = frame0
    fh = plan["frame_px"][1]
    stack = np.stack([f[..., 3] for f in frames])
    for av, expected in ((0.35, 0.59), (0.75, 0.15)):
        band = stack[:, int((av - 0.05) * fh):int((av + 0.05) * fh)]
        width = ((band > 0.3).mean(axis=1) > 0.5).sum(-1).mean() / band.shape[-1]
        assert width == pytest.approx(expected, abs=0.03), av
    code = (SHADERS / "tornado_flipbook_spin.hlsl").read_text(encoding="utf-8")
    assert "float hw = 0.5 * lerp(0.59, 0.15, saturate((av - 0.35) / 0.40));" in code


# -- the material ------------------------------------------------------------------------------

def test_generation_3_wires_spin_and_tone_into_the_graph():
    assert _literal("STORM_GENERATIONS")["M_TornadoFlipbook"] == "3"
    body = SCRIPT[SCRIPT.index("def create_tornado_flipbook"):SCRIPT.index("def create_rain_drop():")]
    assert body.index('"tornado_flipbook_shape"') < body.index('"tornado_flipbook_spin"') \
        < body.index('"tornado_flipbook_uv"') < body.index('"tornado_flipbook_tone"')
    assert '"UV": (mask(material, lib, spin, "rg"' in body
    assert '"Striation": (mask(material, lib, spin, "b"' in body
    assert 'alpha = mask(material, lib, tone, "g"' in body and 'shade = mask(material, lib, tone, "r"' in body
    for name in ("tornado_flipbook_spin", "tornado_flipbook_tone"):
        code = (SHADERS / f"{name}.hlsl").read_text(encoding="utf-8")
        inputs = re.findall(r"^//\s{3}(\w+)\s+float", code, flags=re.M)
        call = body[body.index(f'"{name}"'):]
        call = call[:call.index("}, ")]
        assert inputs and [p for p in re.findall(r'"(\w+)": \(', call)] == inputs, name
        stripped = "\n".join(l for l in code.splitlines() if not l.strip().startswith("//"))
        for forbidden in (r"\bfor\s*\(", r"\bwhile\s*\(", r"\.Sample\(", r"Texture", r"SceneColor"):
            assert not re.search(forbidden, stripped), (name, forbidden)   # no march, no extra read
    for name in _gen2_parameters():
        assert name in _literal("TORNADO_FLIPBOOK_PARAMETERS"), name


def test_the_markers_are_one_method_populate_and_the_lookdev_harness_share():
    world = (PRIVATE / "FlightSimScenarioWorld.cpp").read_text(encoding="utf-8")
    populate = world[world.index("bool FFlightSimScenarioWorld::Populate"):world.index("// -- the aircraft ---")]
    assert "SpawnTornadoMarkers(Card);" in populate and "SpawnMarker(TEXT(\"TornadoFunnel\"))" not in populate
    body = world[world.index("void FFlightSimScenarioWorld::SpawnTornadoMarkers"):]
    assert body.index("if (Card.bTornado)") < body.index('SpawnMarker(TEXT("TornadoWallCloud"))')
    lookdev = (PRIVATE / "FlightSimLookDev.cpp").read_text(encoding="utf-8")
    # markers before the visual scene dresses them; the beauty tornado before the world lane
    assert lookdev.index("SpawnTornadoMarkers(S.Card)") < lookdev.index("S.Visual->Build(World, Options, Error)")
    assert lookdev.index("BuildBeautyTornado(") < lookdev.index("S.WorldBeauty->Build(World, *P,")
    assert 'TEXT("tornado-shade="), TornadoShade' in lookdev
