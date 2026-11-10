"""The post-render beauty pipeline (round 5, lane L5, scripts/beauty_post.py)
with fake binaries: the switch, the argument and filter-graph builders, the
manifest record, the originals left untouched, the refusals by name, the
tool cache's digest check, the look's choices and the web app's wiring."""

import hashlib
import importlib.util
import json
import os
import stat
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bp = _load("beauty_post")

FAKE_FFMPEG = f'''#!{sys.executable}
import json, sys
from pathlib import Path
from PIL import Image
args = sys.argv[1:]
src = Path(args[args.index("-i") + 1]); dst = Path(args[-1])
if src.suffix == ".png":
    Image.open(src).convert("RGB").save(dst)
else:  # the 16-bit PPM hand-over: a known picture
    Image.new("RGB", (32, 16), (20, 40, 60)).save(dst)
if "-vf" in args and "scale=" in args[args.index("-vf") + 1]:
    w, h = args[args.index("-vf") + 1].split("=")[1].split(":")[:2]
    Image.open(dst).resize((int(w), int(h))).save(dst)
Path(str(dst) + ".args.json").write_text(json.dumps(args), encoding="utf-8")
'''

FAKE_OIDN = f'''#!{sys.executable}
import os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
device = args[args.index("-d") + 1]
if device == "sycl" and os.environ.get("FAKE_OIDN_NO_GPU"):
    sys.stderr.write("Error: no SYCL device\\n"); sys.exit(3)
shutil.copyfile(args[args.index("--ldr") + 1], args[args.index("-o") + 1])
Path(args[args.index("-o") + 1] + ".device").write_text(device, encoding="utf-8")
'''

FAKE_ESRGAN = f'''#!{sys.executable}
import os, sys
from pathlib import Path
from PIL import Image
args = sys.argv[1:]
if os.environ.get("FAKE_ESRGAN_FAIL"):
    sys.stderr.write("vkCreateInstance failed\\n"); sys.exit(255)
src = Path(args[args.index("-i") + 1]); dst = Path(args[args.index("-o") + 1])
img = Image.open(src); img.resize((img.width * 4, img.height * 4)).save(dst)
'''


@pytest.fixture
def tools(tmp_path):
    """Fake executables for the three tools, as an override map."""
    folder = tmp_path / "fake_tools"
    folder.mkdir()
    out = {}
    for name, text in (("ffmpeg", FAKE_FFMPEG), ("oidn", FAKE_OIDN), ("realesrgan", FAKE_ESRGAN)):
        exe = folder / f"{name}.py"
        exe.write_text(text, encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
        out[name] = exe
    (folder / "models").mkdir()
    return out


def _frame(directory: Path, name: str = "frame_0000.png", size=(32, 16)) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(1)
    Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)).save(directory / name)
    return directory / name


@pytest.fixture
def bundle(tmp_path):
    """A render bundle: a beauty frame, a label pass and the host's render.json."""
    frames = tmp_path / "run" / "frames" / "chase"
    _frame(frames)
    _frame(frames, "frame_0000_mask.png")
    (frames / "render.json").write_text(json.dumps(
        {"render_quality": "beauty", "look_applied": {"grade": "storm"}}), encoding="ascii")
    return frames


def _digests(directory: Path):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.iterdir()) if p.is_file()}


CUBE = REPO / "assets/looks/film/kodak_portra_160.cube"


# -- the switch ----------------------------------------------------------------------

@pytest.mark.parametrize("value, expect", [
    (None, None), ("", None), ("off", None), ("OFF", None), ("0", None),
    ("on", frozenset()), ("On", frozenset()),
    ("on,-halation,-upscale", frozenset({"halation", "upscale"})),
    ("on, no-grain ", frozenset({"grain"})),
])
def test_the_switch_parses(value, expect):
    assert bp.parse_switch(value) == expect


@pytest.mark.parametrize("value", ["maybe", "on,-bloom", "on,halation", "on,-"])
def test_a_bad_switch_is_refused_by_name(value):
    with pytest.raises(bp.BeautyPostError) as caught:
        bp.parse_switch(value)
    assert caught.value.constraint == "beauty_post.switch"
    assert "FLIGHTSIM_BEAUTY_POST" in str(caught.value)


def test_wanted_reads_the_environment(monkeypatch):
    monkeypatch.delenv("FLIGHTSIM_BEAUTY_POST", raising=False)
    assert bp.wanted() is None
    monkeypatch.setenv("FLIGHTSIM_BEAUTY_POST", "on,-upscale")
    assert bp.wanted() == frozenset({"upscale"})


# -- builders --------------------------------------------------------------------------

def test_the_filter_graph_has_every_step_in_order():
    graph = bp.filter_graph(cube=Path("C:/tools/x.cube"), halation=True, grain=True,
                            vignette=True, seed=1234)
    assert graph.startswith("[0:v]format=gbrp16le,lut3d=file='C\\:/tools/x.cube':interp=tetrahedral,")
    order = [graph.index(w) for w in ("lut3d", "split[a][b]", "colorlevels", "gblur=sigma=14",
                                      "colorchannelmixer=rr=1:gg=0.35:bb=0.12", "blend=all_mode=screen",
                                      "format=gbrp,", "noise=all_seed=1234:all_strength=6:all_flags=t+u",
                                      "vignette=angle=PI/8", "format=rgb24[out]")]
    assert order == sorted(order)
    assert graph.endswith("[out]")


def test_the_filter_graph_leaves_out_what_is_off():
    graph = bp.filter_graph(cube=None, halation=False, grain=False, vignette=False, seed=1)
    assert graph == "[0:v]format=gbrp16le,format=rgb24[out]"
    graph = bp.filter_graph(cube=Path("a.cube"), halation=False, grain=True, vignette=False, seed=7)
    assert "lut3d" in graph and "noise=all_seed=7" in graph
    assert "blend" not in graph and "vignette" not in graph


def test_the_tool_argument_lists():
    assert bp.denoise_args("oidn.exe", Path("in.pfm"), Path("out.pfm"), "sycl") == \
        ["oidn.exe", "--ldr", "in.pfm", "-o", "out.pfm", "-d", "sycl", "-q", "high"]
    with_aov = bp.denoise_args("o", Path("i"), Path("o2"), "cpu", albedo=Path("a.pfm"), normal=Path("n.pfm"))
    assert with_aov[-4:] == ["--alb", "a.pfm", "--nrm", "n.pfm"]
    assert bp.upscale_args("esr.exe", Path("in.png"), Path("x4.png"), "C:/m") == \
        ["esr.exe", "-i", "in.png", "-o", "x4.png", "-n", "realesrgan-x4plus", "-t", "128", "-g", "0",
         "-m", "C:/m"]
    resize = bp.resize_args("ffmpeg.exe", Path("x4.png"), Path("4k.png"))
    assert "-nostdin" in resize and resize[resize.index("-vf") + 1] == "scale=3840:2160:flags=lanczos"
    ff = bp.ffmpeg_args("ffmpeg.exe", Path("in.png"), "[0:v]x[out]", Path("out.png"))
    assert ff[:3] == ["ffmpeg.exe", "-nostdin", "-hide_banner"] and ff[-1] == "out.png"
    assert ff[ff.index("-map") + 1] == "[out]"


def test_the_grain_seed_is_the_frame_name():
    assert bp.frame_seed(Path("/a/frame_0000.png")) == bp.frame_seed(Path("/b/frame_0000.png"))
    assert bp.frame_seed(Path("frame_0000.png")) != bp.frame_seed(Path("frame_0001.png"))


def test_the_pinned_tools_are_release_zips_with_digests():
    for name, tool in bp.TOOLS.items():
        assert tool["url"].startswith("https://github.com/") and "/releases/download/" in tool["url"]
        assert tool["url"].endswith(".zip")
        assert len(tool["sha256"]) == 64 and int(tool["sha256"], 16) >= 0
        assert tool["exe"].endswith(".exe") and tool["licence"]
    assert bp.TOOLS["ffmpeg"]["licence"].startswith("LGPL")
    assert "lgpl" in bp.TOOLS["ffmpeg"]["url"]


def test_the_image_files_round_trip(tmp_path):
    rgb = np.random.default_rng(2).random((5, 7, 3)).astype(np.float32)
    bp.write_pfm(rgb, tmp_path / "t.pfm")
    assert np.array_equal(bp.read_pfm(tmp_path / "t.pfm"), rgb)
    bp.write_ppm16(rgb, tmp_path / "t.ppm")
    data = (tmp_path / "t.ppm").read_bytes()
    assert data.startswith(b"P6\n7 5\n65535\n") and len(data) == len(b"P6\n7 5\n65535\n") + 5 * 7 * 6


# -- one frame ------------------------------------------------------------------------------

def test_a_frame_runs_every_step_and_leaves_the_originals_alone(bundle, tools):
    before = _digests(bundle)
    record = bp.post_frame(bundle / "frame_0000.png", cube=CUBE, noisy=True, grain=True,
                           upscale=True, override=tools)
    assert record["output"] == "frame_0000_beauty_post.png"
    assert (bundle / "frame_0000_beauty_post.png").is_file()
    assert (bundle / "frame_0000_beauty_4k.png").is_file()
    with Image.open(bundle / "frame_0000_beauty_4k.png") as big:
        assert big.size == (3840, 2160)
    after = _digests(bundle)
    assert {k: after[k] for k in before} == before, "an original changed"
    ran = [s["step"] for s in record["steps"] if s.get("ran")]
    assert ran == ["denoise", "lut", "halation", "grain", "vignette", "ffmpeg_pass", "upscale"]
    denoise = record["steps"][0]
    assert denoise["device_ran"] == "sycl" and denoise["intermediate"] == "16-bit PPM"
    assert denoise["args"][0] == str(tools["oidn"])
    lut = next(s for s in record["steps"] if s["step"] == "lut")
    assert lut["params"]["cube"] == str(CUBE)
    assert lut["params"]["sha256"] == hashlib.sha256(CUBE.read_bytes()).hexdigest()
    grain = next(s for s in record["steps"] if s["step"] == "grain")
    assert grain["params"]["seed"] == bp.frame_seed(bundle / "frame_0000.png")
    for step in record["steps"]:
        if step.get("ran") and step["step"] != "ffmpeg_pass":
            assert step["version"] and step["sha256"] and step["args"], step["step"]
    ffmpeg_args = json.loads((bundle / "frame_0000_beauty_post.png.args.json").read_text(encoding="utf-8"))
    graph = ffmpeg_args[ffmpeg_args.index("-filter_complex") + 1]
    assert "lut3d" in graph and "noise=" in graph and "vignette" in graph
    assert ffmpeg_args[ffmpeg_args.index("-i") + 1].endswith("denoised.ppm")
    assert not list(bundle.glob("*_beauty_post_*")), "the scratch folder was removed"


def test_the_denoiser_falls_back_to_the_cpu_and_says_so(bundle, tools, monkeypatch):
    monkeypatch.setenv("FAKE_OIDN_NO_GPU", "1")
    record = bp.post_frame(bundle / "frame_0000.png", cube=None, noisy=True, grain=False,
                           upscale=False, override=tools)
    denoise = record["steps"][0]
    assert denoise["device_ran"] == "cpu"
    assert denoise["devices_failed"] and "sycl" in denoise["devices_failed"][0]


def test_a_quiet_frame_is_not_denoised_and_engine_grain_is_respected(bundle, tools):
    record = bp.post_frame(bundle / "frame_0000.png", cube=CUBE, noisy=False, grain=False,
                           upscale=False, override=tools)
    by = {s["step"]: s for s in record["steps"]}
    assert by["denoise"]["ran"] is False and "world preset" in by["denoise"]["why"]
    assert by["grain"]["ran"] is False and "engine" in by["grain"]["why"]
    assert by["upscale"]["ran"] is False
    args = json.loads((bundle / "frame_0000_beauty_post.png.args.json").read_text(encoding="utf-8"))
    assert args[args.index("-i") + 1].endswith("frame_0000.png")
    assert "noise=" not in args[args.index("-filter_complex") + 1]


def test_steps_switched_off_are_recorded_as_such(bundle, tools):
    record = bp.post_frame(bundle / "frame_0000.png", cube=CUBE, noisy=True, grain=True,
                           upscale=True, off=frozenset({"denoise", "halation", "upscale", "lut"}),
                           override=tools)
    by = {s["step"]: s for s in record["steps"]}
    for step in ("denoise", "halation", "upscale", "lut"):
        assert by[step]["ran"] is False and by[step]["why"] == "switched off", step
    assert by["grain"]["ran"] and by["vignette"]["ran"]
    assert not (bundle / "frame_0000_beauty_4k.png").exists()


def test_a_vulkan_failure_skips_the_upscale_by_name(bundle, tools, monkeypatch):
    monkeypatch.setenv("FAKE_ESRGAN_FAIL", "1")
    record = bp.post_frame(bundle / "frame_0000.png", cube=CUBE, noisy=False, grain=False,
                           upscale=True, override=tools)
    upscale = record["steps"][-1]
    assert upscale["step"] == "upscale" and upscale["ran"] is False
    assert upscale["skipped"] == "beauty_post.upscale_vulkan"
    assert "vkCreateInstance" in upscale["why"]
    assert (bundle / "frame_0000_beauty_post.png").is_file()


def test_a_failing_tool_is_a_named_refusal(bundle, tools, tmp_path):
    broken = tmp_path / "broken.py"
    broken.write_text(f"#!{sys.executable}\nimport sys; sys.stderr.write('boom'); sys.exit(1)\n",
                      encoding="utf-8")
    broken.chmod(broken.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(bp.BeautyPostError) as caught:
        bp.post_frame(bundle / "frame_0000.png", cube=CUBE, noisy=False, grain=False, upscale=False,
                      override={**tools, "ffmpeg": broken})
    assert caught.value.constraint == "beauty_post.step" and "boom" in str(caught.value)
    assert not (bundle / "frame_0000_beauty_post.png").exists()


# -- the bundle and the run ----------------------------------------------------------------

def test_the_bundle_record_goes_into_render_json(bundle, tools):
    record = bp.apply_to_bundle(bundle, cube=CUBE, noisy=True, grain=True, upscale=False,
                                override=tools, look={"world_preset": "storm", "grade": "storm"})
    payload = json.loads((bundle / "render.json").read_text(encoding="ascii"))
    assert payload["look_applied"] == {"grade": "storm"}, "the host's record is kept"
    assert payload["beauty_post"] == record
    assert record["frames"] == ["frame_0000_beauty_post.png"]
    assert record["output"] == "frame_NNNN_beauty_post.png"
    assert record["look"]["world_preset"] == "storm" and record["look"]["film_stock"] == str(CUBE)
    assert record["per_frame"][0]["grain_seed"] == bp.frame_seed(bundle / "frame_0000.png")
    assert "VISUAL ONLY" in record["note"]


def test_a_missing_tool_is_refused_by_name_and_recorded(bundle, tmp_path):
    with pytest.raises(bp.BeautyPostError) as caught:
        bp.apply_to_bundle(bundle, cube=CUBE, noisy=False, grain=False, upscale=False,
                           tools_dir=tmp_path / "cache", fetch=False)
    assert caught.value.constraint == "beauty_post.tool_missing"
    assert "ffmpeg" in str(caught.value) and bp.TOOLS["ffmpeg"]["url"] in str(caught.value)
    payload = json.loads((bundle / "render.json").read_text(encoding="ascii"))
    assert payload["beauty_post"]["refused"] == "beauty_post.tool_missing"
    assert not (bundle / "frame_0000_beauty_post.png").exists()


def test_an_empty_bundle_is_refused(tmp_path):
    empty = tmp_path / "frames"
    empty.mkdir()
    with pytest.raises(bp.BeautyPostError) as caught:
        bp.apply_to_bundle(empty, cube=None, noisy=False, grain=False, upscale=False)
    assert caught.value.constraint == "beauty_post.input"
    assert json.loads((empty / "beauty_post_record.json").read_text(encoding="utf-8"))["refused"] == "beauty_post.input"


def test_apply_to_run_reads_the_sidecar_and_every_camera(tmp_path, tools):
    run = tmp_path / "run"
    for camera in ("chase", "cockpit"):
        _frame(run / "frames" / camera)
        (run / "frames" / camera / "render.json").write_text("{}", encoding="ascii")
    from core.scene import beauty_look as bl

    plan = bl.plan_beauty_look(10.0, fps=30, width_px=1920, world_preset="storm")
    (run / "beauty_look.json").write_text(json.dumps(plan), encoding="ascii")
    records = bp.apply_to_run(run, off=frozenset({"upscale"}), override=tools)
    assert len(records) == 2
    for camera in ("chase", "cockpit"):
        assert (run / "frames" / camera / "frame_0000_beauty_post.png").is_file()
    by = {s["step"]: s for s in records[0]["steps"]}
    assert by["denoise"]["ran"], "a storm frame is noisy"
    assert by["lut"]["params"]["cube"].endswith(bl.film_stock_for("storm")["cube"].split("/")[-1])
    assert by["grain"]["ran"] is (not bl.FILM_GRAIN_IN_ENGINE)
    with pytest.raises(bp.BeautyPostError) as caught:
        bp.apply_to_run(tmp_path / "nothing", {}, override=tools)
    assert caught.value.constraint == "beauty_post.input"


def test_look_choices_follow_the_beauty_look():
    from core.scene import beauty_look as bl

    assert bp.look_choices(None) == {"cube": None, "stock": None, "noisy": False, "grain": True}
    storm = bl.plan_beauty_look(10.0, fps=30, width_px=1920, world_preset="storm")
    choice = bp.look_choices(storm)
    assert choice["noisy"] and choice["stock"] == bl.FILM_STOCKS["storm"]
    assert choice["cube"] == REPO / storm["film_stock"]["cube"] and choice["cube"].is_file()
    assert choice["grain"] is (not bl.FILM_GRAIN_IN_ENGINE)
    quiet = dict(storm, world_preset="clear", lens_post={"FilmGrainIntensity": 0.0})
    assert bp.look_choices(quiet)["noisy"] is False and bp.look_choices(quiet)["grain"] is True
    assert set(bp.NOISY_PRESETS) <= {"storm", "rain", "hazy", "overcast", "clear"}


# -- the tool cache -----------------------------------------------------------------------

def _zip_with(path: Path, member: str, data: bytes) -> str:
    with zipfile.ZipFile(path, "w") as zipped:
        zipped.writestr(member, data)
        zipped.writestr("../evil.txt", b"never extracted")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_fetched_zip_is_checked_and_extracted(tmp_path, monkeypatch):
    staged = tmp_path / "release.zip"
    digest = _zip_with(staged, "ffmpeg-x/bin/ffmpeg.exe", b"fake")
    monkeypatch.setitem(bp.TOOLS, "ffmpeg", {**bp.TOOLS["ffmpeg"], "sha256": digest})
    fetched = []

    def download(url, target):
        fetched.append(url)
        target.write_bytes(staged.read_bytes())

    record = bp.ensure_tool("ffmpeg", tmp_path / "cache", download=download)
    assert fetched == [bp.TOOLS["ffmpeg"]["url"]]
    assert Path(record["exe"]).name == "ffmpeg.exe" and Path(record["exe"]).is_file()
    assert record["sha256"] == digest and record["version"] == bp.TOOLS["ffmpeg"]["version"]
    assert not list((tmp_path / "cache").rglob("evil.txt"))
    again = bp.ensure_tool("ffmpeg", tmp_path / "cache", download=download, fetch=False)
    assert again["exe"] == record["exe"] and len(fetched) == 1, "cached: no second download"


def test_a_wrong_digest_is_refused_and_the_download_deleted(tmp_path):
    staged = tmp_path / "release.zip"
    _zip_with(staged, "oidn/bin/oidnDenoise.exe", b"fake")

    def download(url, target):
        target.write_bytes(staged.read_bytes())

    with pytest.raises(bp.BeautyPostError) as caught:
        bp.ensure_tool("oidn", tmp_path / "cache", download=download)
    assert caught.value.constraint == "beauty_post.tool_checksum"
    assert bp.TOOLS["oidn"]["sha256"] in str(caught.value)
    assert not list((tmp_path / "cache").glob("*.zip")), "the bad download is gone"


def test_a_failed_download_is_a_named_refusal(tmp_path):
    def download(url, target):
        raise OSError("no network")

    with pytest.raises(bp.BeautyPostError) as caught:
        bp.ensure_tool("realesrgan", tmp_path / "cache", download=download)
    assert caught.value.constraint == "beauty_post.tool_missing" and "no network" in str(caught.value)


def test_the_default_cache_is_localappdata_on_windows(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\x\\AppData\\Local")
    assert bp.default_tools_dir() == Path("C:\\Users\\x\\AppData\\Local") / "flightsim" / "tools"
    monkeypatch.delenv("LOCALAPPDATA")
    assert bp.default_tools_dir() == Path.home() / ".cache" / "flightsim" / "tools"


# -- the catalogue, the config surface and the wiring ---------------------------------------

def test_every_refusal_is_catalogued():
    from core.messages import is_catalogued

    for name in ("beauty_post.switch", "beauty_post.tool_missing", "beauty_post.tool_checksum",
                 "beauty_post.input", "beauty_post.step", "beauty_post.upscale_vulkan"):
        assert is_catalogued(name), name
    source = (REPO / "scripts/beauty_post.py").read_text(encoding="utf-8")
    for name in sorted(set(__import__("re").findall(r'"(beauty_post\.[a-z_]+)"', source))):
        assert is_catalogued(name), name


def test_the_switch_is_registered():
    from core.config_surface import SETTINGS

    row = next(s for s in SETTINGS if s.env == "FLIGHTSIM_BEAUTY_POST")
    assert row.bucket == "dev-only" and "scripts/beauty_post.py" in row.read_files
    assert "webapp/runs.py" in row.read_files


def test_the_web_app_runs_the_pipeline_after_the_render_and_before_the_manifest():
    source = (REPO / "webapp/runs.py").read_text(encoding="utf-8")
    call = source.index("self._beauty_post(run, out, beauty_look)")
    assert source.index("capture_display.apply_to_bundle(frames, run.look)") < call
    assert call < source.index('run.push("manifest", "writing the capture manifest')
    assert "def _beauty_post(run, out: Path, beauty_look: Path, **post_kw)" in source


def test_the_web_app_does_nothing_when_the_switch_is_off(monkeypatch, tmp_path):
    monkeypatch.delenv("FLIGHTSIM_BEAUTY_POST", raising=False)
    from webapp.runs import RunManager

    class Run:
        conditions = {}

        def push(self, *a):
            raise AssertionError("nothing to say when the switch is off")

    assert RunManager._beauty_post(Run(), tmp_path, tmp_path / "beauty_look.json") is None


def test_the_web_app_runs_it_when_on(monkeypatch, tmp_path, tools):
    monkeypatch.setenv("FLIGHTSIM_BEAUTY_POST", "on,-upscale")
    from core.scene import beauty_look as bl
    from webapp.runs import RunManager

    out = tmp_path / "run"
    _frame(out / "frames" / "chase")
    (out / "frames" / "chase" / "render.json").write_text("{}", encoding="ascii")
    plan = bl.plan_beauty_look(40.0, fps=30, width_px=1920)
    (out / "beauty_look.json").write_text(json.dumps(plan), encoding="ascii")
    events = []

    class Run:
        conditions = {}

        def push(self, status, detail=""):
            events.append((status, detail))

    records = RunManager._beauty_post(Run(), out, out / "beauty_look.json", override=tools)
    assert records and records[0]["frames"] == ["frame_0000_beauty_post.png"]
    assert (out / "frames" / "chase" / "frame_0000_beauty_post.png").is_file()
    assert any(s == "beauty_post" for s, _ in events)
    assert "post-render beauty" in Run.conditions["beauty_post"]
    assert "upscale" in json.loads((out / "frames" / "chase" / "render.json").read_text(encoding="utf-8"))["beauty_post"]["steps_off"]


def test_visual_round_carries_the_post_frames(tmp_path, tools, monkeypatch):
    monkeypatch.delenv("FLIGHTSIM_BEAUTY_POST", raising=False)
    vr = _load("visual_round")
    gallery = tmp_path / "gallery"
    _frame(gallery, "01_golden_frame.png", size=(64, 36))
    _frame(gallery, "02_noon_frame.png", size=(64, 36))
    _frame(gallery, "02_noon_frame_beauty_post.png", size=(64, 36))   # the web app's own
    runs = tmp_path / "runs"
    from core.scene import beauty_look as bl

    (runs / "r1").mkdir(parents=True)
    (runs / "r1" / "beauty_look.json").write_text(
        json.dumps(bl.plan_beauty_look(5.0, fps=30, width_px=1920)), encoding="ascii")
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps([{"number": 1, "name": "golden", "outcome": "done", "run_id": "r1"},
                                   {"number": 2, "name": "noon", "outcome": "done", "run_id": "r2"}]),
                       encoding="utf-8")
    before = _digests(gallery)
    out = vr.write_round(5, gallery, summary, tmp_path / "docs", runs, post=frozenset({"upscale"}),
                         override=tools)
    assert (out / "01_golden.jpg").is_file() and (out / "01_golden_post.jpg").is_file()
    assert (out / "02_noon_post.jpg").is_file() and (out / "contact_post.jpg").is_file()
    posted = json.loads((out / "beauty_post.json").read_text(encoding="utf-8"))
    assert posted["frames"]["01_golden"]["source"] == "01_golden_frame_beauty_post.png"
    assert posted["frames"]["02_noon"]["source"] == "02_noon_frame_beauty_post.png"
    assert {k: _digests(gallery)[k] for k in before} == before
    record = json.loads((gallery / "01_golden_frame_beauty_post.beauty_post.json").read_text(encoding="utf-8"))
    assert record["look"]["stock"] == bl.FILM_STOCKS["golden_hour"]
    # Off: the round is written as before, no post files.
    out = vr.write_round(6, gallery, summary, tmp_path / "docs", runs, post=None)
    assert not (out / "contact_post.jpg").exists() and (out / "contact.jpg").is_file()
