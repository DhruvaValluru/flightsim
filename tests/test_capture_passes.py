"""E5: the capture_passes setting (Normals / Flow / Amodal checkboxes)
is the one source of a web capture's extra passes; the developer
override is resolved by E2's ``effective()``; the X-Plane developer
switches are read in core/xplane/devflags.py, never in webapp/."""

import glob
import itertools
import json
import re
from pathlib import Path

import pytest

from core.util import settings
from webapp.capture import (
    CAPTURE_PASSES_ALL, CAPTURE_PASSES_ENV, PASS_WORDS, CaptureError,
    apply_capture_passes, requested_capture_passes,
)

REPO = Path(__file__).resolve().parents[1]
WEBAPP_PY = sorted(glob.glob(str(REPO / "webapp" / "*.py")))


@pytest.fixture
def clean(monkeypatch, tmp_path):
    """A private settings file and no developer override in the shell."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    monkeypatch.delenv(CAPTURE_PASSES_ENV, raising=False)
    return path


def test_no_setting_no_passes(clean):
    assert requested_capture_passes() == []
    assert requested_capture_passes({}) == []
    assert settings.effective("capture_passes", {}) == ([], "default")


@pytest.mark.parametrize("n", [1, 2, 3])
def test_checked_words_map_to_engine_words(clean, n):
    for combo in itertools.combinations(sorted(PASS_WORDS), n):
        settings.save_settings({"capture_passes": list(combo)})
        got = requested_capture_passes({})
        assert got == [w for w in CAPTURE_PASSES_ALL if w in {PASS_WORDS[c] for c in combo}]
        assert set(got) == {PASS_WORDS[c] for c in combo}
        assert "normals" not in got  # the engine takes the singular


def test_unknown_word_refused_sensing_pass(clean):
    with pytest.raises(CaptureError) as info:
        requested_capture_passes({CAPTURE_PASSES_ENV: "normal,depth"})
    assert info.value.constraint == "sensing.pass"
    assert "['depth']" in info.value.message and CAPTURE_PASSES_ENV in info.value.message
    # a hand-edited settings file with a word the panel never offers is
    # refused by E2's reader, by key and word, before the capture sees it
    clean.write_text(json.dumps({"capture_passes": ["normals", "disparity"]}), encoding="utf-8")
    with pytest.raises(settings.SettingsError, match=r"settings\.capture_passes: \['disparity'\]"):
        requested_capture_passes({})


def test_env_override_wins_over_setting(clean):
    settings.save_settings({"capture_passes": ["normals"]})
    assert requested_capture_passes({}) == ["normal"]
    env = {CAPTURE_PASSES_ENV: "albedo, velocity"}
    assert requested_capture_passes(env) == ["velocity", "albedo"]
    assert requested_capture_passes({CAPTURE_PASSES_ENV: "all"}) == list(CAPTURE_PASSES_ALL)
    assert requested_capture_passes({CAPTURE_PASSES_ENV: "normals;flow"}) == ["normal", "flow"]


class _Camera:
    def __init__(self, passes=None):
        from core.scenario.fields import Quantity
        self.passes = Quantity.inferred(passes, frm="test") if passes is not None else Quantity.inferred(None, frm="test")


class _Spec:
    def __init__(self, *cameras):
        self.cameras = list(cameras)


def test_apply_names_the_setting_or_the_override_as_provenance(clean):
    settings.save_settings({"capture_passes": ["amodal", "normals"]})
    spec = _Spec(_Camera(), _Camera(["albedo"]))
    assert apply_capture_passes(spec, {}) == ["normal", "amodal"]
    assert spec.cameras[0].passes.value == ["normal", "amodal"]
    assert spec.cameras[0].passes.frm == "settings.capture_passes"
    assert spec.cameras[1].passes.value == ["albedo"]
    spec = _Spec(_Camera())
    assert apply_capture_passes(spec, {CAPTURE_PASSES_ENV: "points"}) == ["points"]
    assert spec.cameras[0].passes.frm == CAPTURE_PASSES_ENV
    # an empty override is no override: the file still speaks
    assert apply_capture_passes(_Spec(_Camera()), {CAPTURE_PASSES_ENV: ""}) == ["normal", "amodal"]


def test_webapp_names_capture_passes_env_once():
    lines = [(f, i, line) for f in WEBAPP_PY
             for i, line in enumerate(Path(f).read_text(encoding="utf-8").splitlines(), 1)
             if "FLIGHTSIM_CAPTURE_PASSES" in line]
    assert len(lines) == 1, lines
    assert lines[0][0].endswith("capture.py") and lines[0][2].startswith("CAPTURE_PASSES_ENV = ")


def test_webapp_never_names_xplane_env():
    hits = [(f, i) for f in WEBAPP_PY
            for i, line in enumerate(Path(f).read_text(encoding="utf-8").splitlines(), 1)
            if "FLIGHTSIM_XPLANE" in line]
    assert hits == []


def test_devflags_read_the_developer_switches(monkeypatch):
    from core.xplane import devflags
    monkeypatch.delenv(devflags.XPLANE_TERRAIN_ENV, raising=False)
    monkeypatch.delenv(devflags.XPLANE_LIGHTING_ENV, raising=False)
    monkeypatch.delenv(devflags.XPLANE_SKY_ENV, raising=False)
    assert devflags.terrain_off() is False and devflags.lighting_off() is False
    assert devflags.sky_choice() is None
    monkeypatch.setenv(devflags.XPLANE_TERRAIN_ENV, "OFF")
    monkeypatch.setenv(devflags.XPLANE_LIGHTING_ENV, " off ")
    monkeypatch.setenv(devflags.XPLANE_SKY_ENV, "Tables")
    assert devflags.terrain_off() is True and devflags.lighting_off() is True
    assert devflags.sky_choice() == "tables"
    from webapp.runs import xplane_sky_source
    assert xplane_sky_source() == "tables"
    monkeypatch.setenv(devflags.XPLANE_SKY_ENV, "nonsense")
    with pytest.raises(ValueError, match="FLIGHTSIM_XPLANE_SKY"):
        xplane_sky_source()


def test_index_has_three_pass_checkboxes():
    page = (REPO / "webapp" / "static" / "index.html").read_text(encoding="utf-8")
    slot = page[page.index('<div id="settings-capture-passes">'):]
    slot = slot[:slot.index("</div>")]
    assert 'id="passPicker"' in slot
    for box, word in (("passNormals", "normals"), ("passFlow", "flow"), ("passAmodal", "amodal")):
        assert page.count(f'id="{box}"') == 1, box
        assert re.search(rf'<input type="checkbox" id="{box}" value="{word}">', slot), box
        assert word in PASS_WORDS
    assert page.count("async function loadPasses()") == 1
    assert page.count("async function savePasses()") == 1
    assert 'JSON.stringify({settings: {capture_passes: words}})' in page
    assert 'fetch("/settings", {method: "PUT"' in page
