"""The owner's JangaFX tornado (2026-11-14): the CC0 "Tornado Looping" VDB fetched into a
cache outside git, baked offline by Blender into a flipbook atlas, and played by
M_TornadoFlipbook on a camera-facing card in the funnel's place in BEAUTY renders
(-tornado-look=vdb, the default; mesh falls back by name). The label captures keep the
funnel's mesh byte for byte: it is hidden from the beauty capture only. No network and no
Blender here: the pure-python halves are exercised, the C++ and the material graph pinned."""
import hashlib
import importlib.util
import io
import json
import re
import zipfile
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
PUBLIC = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public"
BEAUTY_CPP = (PRIVATE / "FlightSimTornadoBeauty.cpp").read_text(encoding="utf-8")
WORLD_CPP = (PRIVATE / "FlightSimScenarioWorld.cpp").read_text(encoding="utf-8")
WORLD_H = (PUBLIC / "FlightSimScenarioWorld.h").read_text(encoding="utf-8")
RENDER_CPP = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
SCRIPT = (SCRIPTS / "ue_create_materials.py").read_text(encoding="utf-8")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bake = _load("bake_tornado_flipbook")
fetch = _load("fetch_tornado_vdb")


# -- the bake's pure-python half --------------------------------------------------------

def test_the_bake_cli_takes_blenders_double_dash_and_defaults():
    ns = bake.parse_args(["blender", "-b", "-P", "x.py", "--", "--out", "o"])
    assert ns.vdb_dir is None and ns.out == Path("o")
    assert (ns.frames, ns.frame_w, ns.frame_h) == (64, 256, 512)
    with pytest.raises(SystemExit):
        bake.parse_args(["--out", "o", "--frames", "1"])
    with pytest.raises(ValueError):          # 64 frames of 4096 px cannot fit a 4096 atlas
        bake.parse_args(["--out", "o", "--frame-w", "4096", "--frame-h", "4096"])


def test_the_frame_plan_spans_one_loop_without_repeating_the_first_frame():
    used = bake.plan_frames(200, 64)
    assert len(used) == 64 and used[0] == 0 and used[-1] < 200 and used == sorted(set(used))
    assert bake.plan_frames(10, 64) == list(range(10))
    with pytest.raises(ValueError):
        bake.plan_frames(0, 64)


def test_the_atlas_is_the_squarest_grid_under_the_cap():
    cols, rows, w, h = bake.atlas_layout(64, 256, 512)
    assert (cols, rows, w, h) == (12, 6, 3072, 3072)    # square, <= 4096 both ways
    assert w <= bake.ATLAS_MAX_SIDE and h <= bake.ATLAS_MAX_SIDE and cols * rows >= 64
    assert (w, h) == (cols * 256, rows * 512)


def test_the_png_codec_round_trips_and_packs_in_reading_order():
    rng = np.random.default_rng(3)
    frames = [rng.integers(0, 256, (6, 4, 4), dtype=np.uint8) for _ in range(5)]
    atlas = bake.pack_atlas(frames, 3, 2)
    assert atlas.shape == (12, 12, 4)
    assert (atlas[6:12, 0:4] == frames[3]).all() and (atlas[6:12, 8:12] == 0).all()
    assert (bake.png_decode(bake.png_encode(atlas)) == atlas).all()
    # Blender writes filtered rows: every filter type decodes (checked against Pillow).
    PIL = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    PIL.fromarray(atlas, "RGBA").save(buf, "PNG", optimize=True)
    assert (bake.png_decode(buf.getvalue()) == atlas).all()


def test_the_flipbook_json_and_the_pin(tmp_path):
    rec = bake.flipbook_record(frames=64, cols=8, rows=8, frame_w=256, frame_h=512, vdb_count=200,
                               used=bake.plan_frames(200, 64), fps=24.0, bounds_min=[-1, -1, 0],
                               bounds_max=[1, 1, 6], metres_per_unit=1.0, grid="density", zip_sha256="ab")
    assert rec["source"]["licence"] == "CC0-1.0" and rec["source"]["zip_sha256"] == "ab"
    assert rec["frame_aspect"] == 0.5 and rec["atlas_px"] == [2048, 4096]
    assert abs(rec["loop_seconds"] - 200 / 24.0) < 1e-9 and "straight" in rec["alpha"]
    bake.write_json(tmp_path / bake.JSON_NAME, rec)
    (tmp_path / bake.ATLAS_NAME).write_bytes(bake.png_encode(np.zeros((2, 2, 4), np.uint8)))
    pin = bake.pin_record(tmp_path, "ab")
    row = pin["files"][bake.ATLAS_NAME]
    assert row["path"] == "assets/looks/tornado_vdb/T_TornadoFlipbook.png"
    assert row["sha256"] == hashlib.sha256((tmp_path / bake.ATLAS_NAME).read_bytes()).hexdigest()


def test_the_bake_fetches_first_when_no_vdb_dir_is_given(tmp_path):
    class Fake:
        PIN = {"zip_sha256": "cafe"}

        @staticmethod
        def fetch():
            return tmp_path

    ns = bake.parse_args(["--out", "o"])
    assert bake.resolve_vdb_dir(ns, fetcher=Fake) == tmp_path and ns.zip_sha256 == "cafe"
    ns = bake.parse_args(["--out", "o", "--vdb-dir", "v"])
    assert bake.resolve_vdb_dir(ns, fetcher=Fake) == Path("v")


# -- the fetch (no network) -------------------------------------------------------------

def _zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Tornado_Looping/tornado_0001.vdb", b"vdb1")
        z.writestr("Tornado_Looping/tornado_0002.vdb", b"vdb2")
    return buf.getvalue()


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_cache_path_override():
    assert fetch.cache_dir({"FLIGHTSIM_ASSETS_DIR": "/x/assets"}) == Path("/x/assets/jangafx_tornado")
    assert fetch.cache_dir({}) == fetch.REPO.parent / "flightsim_assets" / "jangafx_tornado"


def test_an_unpinned_fetch_is_refused_by_name(tmp_path):
    assert fetch.PIN["zip_sha256"] is None or re.fullmatch(r"[0-9a-f]{64}", fetch.PIN["zip_sha256"])
    with pytest.raises(fetch.FetchRefused, match=r"^tornado_vdb\.pin_missing"):
        fetch.fetch(tmp_path, pin=dict(fetch.PIN, zip_url=None, zip_sha256=None))


def test_the_pin_check_refuses_a_mismatch_and_extracts_nothing(tmp_path):
    data = _zip_bytes()
    pin = dict(fetch.PIN, zip_url="https://example.invalid/t.zip", zip_sha256="0" * 64)
    with pytest.raises(fetch.FetchRefused, match=r"^tornado_vdb\.sha_mismatch"):
        fetch.fetch(tmp_path, pin=pin, opener=lambda req: _Response(data))
    assert not list(tmp_path.rglob("*.vdb")) and not list(tmp_path.glob("*.part"))


def test_a_good_fetch_unzips_once_and_then_skips(tmp_path):
    data = _zip_bytes()
    pin = dict(fetch.PIN, zip_url="https://example.invalid/t.zip", zip_sha256=hashlib.sha256(data).hexdigest())
    calls = []

    def opener(req):
        calls.append(req.full_url)
        return _Response(data)

    found = fetch.fetch(tmp_path, pin=pin, opener=opener)
    assert found.name == "Tornado_Looping" and len(fetch.vdb_files(found)) == 2
    assert fetch.is_present(tmp_path, pin)
    again = fetch.fetch(tmp_path, pin=pin, opener=opener)
    assert again == found and len(calls) == 1                 # skip-if-present: no second download
    marker = json.loads((tmp_path / fetch.MARKER).read_text(encoding="utf-8"))
    assert marker["zip_sha256"] == pin["zip_sha256"] and marker["licence"] == "CC0-1.0"


# -- the material, the switch and the isolation -----------------------------------------

def _assigned(name):
    import ast
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


def test_the_flipbook_material_is_a_storm_material_built_only_from_a_bake():
    assert "M_TornadoFlipbook" in _assigned("STORM_MATERIALS")
    # 2: the card's shape; 3: -tornado-shade=funnel (both 2026-11-15, test_tornado_funnel_shade.py)
    assert _assigned("STORM_GENERATIONS")["M_TornadoFlipbook"] == "3"
    body = SCRIPT[SCRIPT.index("def create_tornado_flipbook"):SCRIPT.index("def create_rain_drop():")]
    assert 'finish_storm(material, "M_TornadoFlipbook")' in body and "BLEND_TRANSLUCENT" in body
    assert "tornado_flipbook_pin()" in body and "MATERIAL-NOTE" in body   # no bake: not built, said so
    assert "\ncreate_tornado_flipbook()" in SCRIPT     # called by the script
    for name in _assigned("TORNADO_FLIPBOOK_PARAMETERS") + _assigned("TORNADO_FLIPBOOK_BAKE_PARAMETERS"):
        assert f'"{name}"' in body, name
    # The C++ sets exactly the declared parameters and reads FrameAspect back.
    set_on = set(re.findall(r'Flipbook(?:Material)?->SetScalarParameterValue\(FName\(TEXT\("(\w+)"\)\)', BEAUTY_CPP + WORLD_CPP))
    set_on |= set(re.findall(r'Flipbook->SetVectorParameterValue\(FName\(TEXT\("(\w+)"\)\)', BEAUTY_CPP))
    set_on |= set(re.findall(r'TornadoFlipbookMaterial->SetScalarParameterValue\(FName\(TEXT\("(\w+)"\)\)', WORLD_CPP))
    assert set_on == set(_assigned("TORNADO_FLIPBOOK_PARAMETERS"))
    assert 'K2_GetScalarParameterValue(FName(TEXT("FrameAspect")))' in BEAUTY_CPP
    # Generation 2: the cropped card's aspect read back first, the bake's as the fallback.
    assert BEAUTY_CPP.index('K2_GetScalarParameterValue(FName(TEXT("CardAspect")))') \
        < BEAUTY_CPP.index('K2_GetScalarParameterValue(FName(TEXT("FrameAspect")))')
    assert "FlipbookWidthM = FlipbookHeightM * CardAspect;" in BEAUTY_CPP


def test_the_card_is_cropped_tapered_and_faded_into_the_wall_cloud():
    """2026-11-15 (hyperreal tornado-shape): the bake is a top-heavy plume floating in
    its frame. M_TornadoFlipbook 2 crops the card to the plume, squeezes its foot narrow,
    fades its cap out inside the wall cloud and tints its foot with ground dust, all in
    tornado_flipbook_shape.hlsl before the frame lookup; the C++ stands the card's top
    up in the wall cloud and tints it darker than the sheath."""
    from core.scene import weather_look
    body = SCRIPT[SCRIPT.index("def create_tornado_flipbook"):SCRIPT.index("def create_rain_drop():")]
    hlsl = (REPO / "assets/shaders/weather/tornado_flipbook_shape.hlsl").read_text(encoding="utf-8")
    for pin in ("UV", "CropTop", "CropBottom", "TopWidth", "BottomWidth", "TaperPower", "TopFade", "DustShare"):
        assert f'"{pin}":' in body and pin in hlsl, pin
    assert body.index('"tornado_flipbook_shape"') < body.index('"tornado_flipbook_uv"')
    # The lookup reads the shaped UV (through generation 3's spin, identity at its defaults).
    assert '"Shape": (shape, "")' in body and '"UV": (mask(material, lib, spin, "rg"' in body
    assert 'mask(material, lib, shape, "b"' in body                        # the weight gates the alpha
    assert 'mask(material, lib, shape, "a"' in body                        # the dust share lerps the tint
    assert 'constant3(material, lib, TORNADO_FLIPBOOK_DUST_TINT' in body
    assert 'scalar(material, lib, "CardAspect", tornado_flipbook_card_aspect(plan["frame_aspect"])' in body
    crop = _assigned("TORNADO_FLIPBOOK_CROP_V")
    taper = _assigned("TORNADO_FLIPBOOK_TAPER")
    top_fade = _assigned("TORNADO_FLIPBOOK_TOP_FADE")
    assert 0.0 <= crop[0] < crop[1] <= 1.0
    assert 0.0 < taper["bottom_width"] < taper["top_width"] <= 1.0 and taper["power"] > 0.0
    assert 0.0 < top_fade < 0.5 and 0.0 < _assigned("TORNADO_FLIPBOOK_DUST_SHARE") < 0.5
    # The cropped card keeps the texels' aspect: the bake's 0.5 over the crop's height.
    source = SCRIPT[SCRIPT.index("TORNADO_FLIPBOOK_CROP_V = "):SCRIPT.index("def weather_look_stale")]
    namespace = {}
    exec(compile(source, "shape", "exec"), namespace)
    assert namespace["tornado_flipbook_card_aspect"](0.5) == pytest.approx(0.5 / (crop[1] - crop[0]))
    # The card's top is in the wall cloud and the fade completes at or above its base, so
    # the funnel below the wall cloud is drawn whole and the cap dissolves into the deck.
    share = weather_look.BEAUTY_TORNADO_FLIPBOOK_HEIGHT_SHARE
    assert share * weather_look.FUNNEL_TOP_SHARE < weather_look.WALL_TOP_SHARE
    assert weather_look.flipbook_top_fade_end_share(top_fade) >= weather_look.FUNNEL_TOP_SHARE
    match = re.search(r"constexpr double TornadoFlipbookHeightShare = ([0-9.]+);", BEAUTY_CPP)
    assert match and float(match.group(1)) == share
    colour = tuple(float(re.search(rf"constexpr float BeautyFlipbookColour{c} = ([0-9.]+)f;", BEAUTY_CPP).group(1))
                   for c in "RGB")
    assert colour == weather_look.BEAUTY_TORNADO_FLIPBOOK_COLOUR
    assert max(colour) < min(weather_look.BEAUTY_TORNADO_SHEATH_COLOUR)      # darker than the sheath
    assert min(colour) > max(weather_look.BEAUTY_WALL_CLOUD_COLOUR)          # reads against the deck
    assert "FLinearColor(BeautyFlipbookColourR, BeautyFlipbookColourG, BeautyFlipbookColourB, 1.0f)" in BEAUTY_CPP
    # The crop brackets the plume in every frame of the committed atlas (needs Pillow).
    pin = json.loads((REPO / "assets/looks/tornado_vdb/PIN.json").read_text(encoding="utf-8"))
    if not pin["files"]:
        pytest.skip("no bake on this checkout")
    PIL = pytest.importorskip("PIL.Image")
    plan = json.loads((REPO / "assets/looks/tornado_vdb/tornado_flipbook.json").read_text(encoding="utf-8"))
    atlas = np.asarray(PIL.open(REPO / "assets/looks/tornado_vdb/T_TornadoFlipbook.png").convert("RGBA"))
    fw, fh = plan["frame_px"]
    for idx in range(0, plan["frames"], 9):
        c, r = idx % plan["cols"], idx // plan["cols"]
        alpha = atlas[r * fh:(r + 1) * fh, c * fw:(c + 1) * fw, 3] / 255.0
        rows = np.where(alpha.mean(axis=1) > 0.02)[0]
        assert crop[0] <= rows.min() / fh and (rows.max() + 1) / fh <= crop[1], idx


def test_the_placeholder_pin_names_no_files_until_the_bake():
    pin = json.loads((REPO / "assets/looks/tornado_vdb/PIN.json").read_text(encoding="utf-8"))
    assert pin["licence"] == "CC0-1.0"
    if pin["files"]:
        for name in ("T_TornadoFlipbook.png", "tornado_flipbook.json"):
            row = pin["files"][name]
            data = (REPO / row["path"]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == row["sha256"], name
    assert "CC0" in (REPO / "assets/looks/tornado_vdb/LICENSE").read_text(encoding="utf-8")
    assert "jangafx_tornado" in (REPO / "THIRD_PARTY_VISUAL.md").read_text(encoding="utf-8")
    assert "assets/looks/tornado_vdb/_frames/" in (REPO / ".gitignore").read_text(encoding="utf-8")


def test_the_switch_is_parsed_and_refused_by_name():
    call = RENDER_CPP.index("Scenario.BuildBeautyTornado(")
    block = RENDER_CPP[RENDER_CPP.rindex("FString TornadoLook = TEXT(\"vdb\");", 0, call):call]
    assert 'TEXT("tornado-look="), TornadoLook);' in block and 'FString TornadoLook = TEXT("vdb");' in block
    assert "FLIGHTSIM_RENDER_SWITCHES" in block and "render.tornado_look:" in block
    assert "Scenario.TornadoLook = TornadoLook;" in block
    catalog = (REPO / "core/messages/catalog.yaml").read_text(encoding="utf-8")
    for code in ("render.tornado_look", "tornado_vdb.pin_missing", "tornado_vdb.sha_mismatch",
                 "tornado_vdb.zip_path", "tornado_vdb.no_vdb"):
        assert f"\n{code}:\n" in catalog, code


def test_the_card_is_beauty_only_and_the_funnel_hidden_from_the_beauty_capture_alone():
    vdb = BEAUTY_CPP[BEAUTY_CPP.index('if (TornadoLook == TEXT("vdb"))'):]
    vdb = vdb[:vdb.index("if (Record.IsValid())")]
    # The card's actor comes from SpawnPuffActor, which adds it to BeautyOnlyActors.
    assert 'SpawnPuffActor(TEXT("TornadoFlipbook"))' in vdb
    assert "BeautyOnlyActors.Add(Actor);" in BEAUTY_CPP
    assert "TornadoBeautyHiddenFunnel = FunnelMesh;" in vdb and 'DrawnAs = TEXT("vdb_flipbook");' in vdb
    assert 'Row->SetStringField(TEXT("drawn_as"), DrawnAs);' in BEAUTY_CPP
    # Hidden on the beauty capture (and its linear / accumulate twins) only, never on a label capture.
    assert "Capture->HiddenComponents.AddUnique(Scenario.TornadoBeautyHiddenFunnel);" in RENDER_CPP
    assert "LinearCapture->HiddenComponents = Capture->HiddenComponents;" in RENDER_CPP
    assert "AccumulateCapture->HiddenComponents = Capture->HiddenComponents;" in RENDER_CPP
    assert "Label->HiddenComponents" not in RENDER_CPP
    # The flipbook plays on SIM time.
    assert 'TornadoFlipbookMaterial->SetScalarParameterValue(FName(TEXT("Time")), static_cast<float>(TimeSeconds));' in WORLD_CPP
    assert 'FString TornadoLook = TEXT("vdb");' in WORLD_H


def test_the_flipbook_shaders_are_sm5_straight_line_code():
    for name in ("tornado_flipbook_uv", "tornado_flipbook_blend", "tornado_flipbook_shape",
                 "tornado_flipbook_spin", "tornado_flipbook_tone"):
        code = (REPO / "assets/shaders/weather" / f"{name}.hlsl").read_text(encoding="utf-8")
        body = "\n".join(l for l in code.splitlines() if not l.strip().startswith("//"))
        for forbidden in (r"\bfor\s*\(", r"\bwhile\s*\(", r"\.Sample\(", r"\bWave\w+\("):
            assert not re.search(forbidden, body), (name, forbidden)


def test_the_pin_is_the_render_machines_download_and_a_hand_zip_installs(tmp_path):
    """2026-11-14: p3-windows downloaded the zip in a browser (MediaFire challenges scripts)."""
    import hashlib
    import importlib.util
    import zipfile
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "scripts" / "fetch_tornado_vdb.py"
    spec = importlib.util.spec_from_file_location("fetch_tornado_vdb_pin", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.PIN["zip_sha256"] == "492c99321ae911d0ad6c6ff3df6eb53c83e443ba91b6aab7b97ba86e536ac57c"
    assert mod.PIN["zip_bytes"] == 1797795595 and mod.PIN["frames"] == 128
    z = tmp_path / "hand.zip"
    with zipfile.ZipFile(z, "w") as archive:
        archive.writestr("TornadoLooping/TornadoVDB/tornado_0000.vdb", b"vdb")
    pin = dict(mod.PIN, zip_sha256=hashlib.sha256(z.read_bytes()).hexdigest())
    found = mod.install_zip(z, tmp_path / "cache", pin)
    assert found.name == "TornadoVDB" and mod.is_present(tmp_path / "cache", pin)
    bad = dict(mod.PIN, zip_sha256="0" * 64)
    try:
        mod.install_zip(z, tmp_path / "cache2", bad)
    except mod.FetchRefused as refusal:
        assert str(refusal).startswith("tornado_vdb.sha_mismatch")
    else:
        raise AssertionError("a wrong zip installed")
