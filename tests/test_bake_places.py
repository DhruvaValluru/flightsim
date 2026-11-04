"""Phase 3 D5: the two places are prepared once.

``python scripts/bake_terrain.py --places`` bakes ``grand_canyon`` and
``yosemite`` from GLO-30 on the first launch and, on every launch after,
prints ``bake <key> up to date`` without a single network request. "Up to
date" is decided on disk by ``bake_stale_reason``: the sidecar sha256
against the .r16 samples, the datum block, the dataset, the tile stems.

Every fetcher is faked here (the bake, the Sentinel-2 drape, urlopen
itself): the suite streams nothing. Google tiles and weather are outside
this command and this file asserts the script never names them.
"""

from __future__ import annotations

import importlib.util
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from core.terrain.geoid import datum_block
from core.terrain.glo30 import LOCATIONS
from core.terrain.heightfield import Heightfield
from core.terrain.synthesis import ridge_for_origin

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "bake_terrain.py"
PLACES = ("grand_canyon", "yosemite")


def _load_script():
    spec = importlib.util.spec_from_file_location("bake_terrain_d5", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_bake_field(key: str) -> Heightfield:
    """What core.terrain.glo30.bake writes for a curated place, in small:
    a raster centred on the place's origin whose provenance carries the
    GLO-30 dataset, the tile stems with their shas and the datum block."""
    location = LOCATIONS[key]
    field = ridge_for_origin(location.origin_lat, location.origin_lon,
                             name=key, size=32)
    field.provenance.update({
        "dataset": "Copernicus GLO-30 DSM (30 m surface model)",
        "tiles": {stem: "0" * 64 for stem in location.tiles},
        "origin_lat_deg": location.origin_lat,
        "origin_lon_deg": location.origin_lon,
        "datum": datum_block(location.origin_lat, location.origin_lon,
                             1500.0, location_key=key),
    })
    return field


@pytest.fixture
def places(tmp_path, monkeypatch):
    """The script with every fetcher faked and REPO moved to tmp, so
    runs/terrain and data/glo30 are the test's own. Returns the module,
    the terrain dir and the call log."""
    module = _load_script()
    monkeypatch.setattr(module, "REPO", tmp_path)
    calls = {"bake": [], "drape": []}

    def fake_bake(location, cache_dir, out_dir, ground_sample_distance_m=30.0,
                  geoid_model="auto"):
        calls["bake"].append(location.key)
        raw = _fake_bake_field(location.key).write(Path(out_dir) / location.key)
        return raw, {"ok": True}

    def fake_drape(location, stem, cache_dir, out_dir):
        calls["drape"].append(location.key)
        texture = Path(out_dir) / f"{location.key}_imagery.png"
        texture.write_bytes(b"png")
        (Path(out_dir) / f"{location.key}_imagery.json").write_text(
            json.dumps({"key": location.key, "texture": texture.name}),
            encoding="utf-8")
        return texture, {"ok": True}

    def no_network(*args, **kwargs):
        raise AssertionError("the suite must not open a URL")

    import core.terrain.imagery as imagery

    monkeypatch.setattr(module, "bake", fake_bake)
    monkeypatch.setattr(imagery, "drape", fake_drape)
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    return module, tmp_path / "runs" / "terrain", calls


def _lines(capsys):
    return capsys.readouterr().out.splitlines()


def test_places_first_run_bakes_both_and_writes_sidecar(places, capsys):
    module, terrain, calls = places
    assert module.PLACE_KEYS == PLACES
    assert module.main(["--places"]) == 0
    out = _lines(capsys)
    assert calls["bake"] == list(PLACES) and calls["drape"] == list(PLACES)
    for key in PLACES:
        assert f"bake {key} baked" in out
        baking = [line for line in out if line.startswith(f"bake {key} baking (")]
        assert len(baking) == 1 and "missing" in baking[0]
        assert out.index(baking[0]) < out.index(f"bake {key} baked")
        sidecar = json.loads((terrain / f"{key}.json").read_text(encoding="utf-8"))
        assert sidecar["sha256"] == Heightfield.read(terrain / key).digest()
        assert set(sidecar["provenance"]["tiles"]) == set(LOCATIONS[key].tiles)
        assert (terrain / f"{key}_imagery.json").is_file()
    assert out.index("bake grand_canyon baked") < out.index("bake yosemite baking (no bake: yosemite.r16 is missing)")


def test_places_second_run_logs_up_to_date_and_does_not_fetch(places, capsys):
    module, terrain, calls = places
    assert module.main(["--places"]) == 0
    capsys.readouterr()
    before = {k: list(v) for k, v in calls.items()}
    assert module.main(["--places"]) == 0
    out = _lines(capsys)
    assert "bake grand_canyon up to date" in out
    assert "bake yosemite up to date" in out
    assert not any("baking" in line or "baked" in line or "FAILED" in line
                   for line in out)
    assert calls == before
    assert any("imagery: drape present" in line for line in out)


def test_places_corrupted_sidecar_rebakes_with_reason(places, capsys):
    module, terrain, calls = places
    assert module.main(["--places"]) == 0
    capsys.readouterr()

    sidecar = terrain / "grand_canyon.json"
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    meta["sha256"] = "0" * 64
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    assert module.main(["--places"]) == 0
    out = _lines(capsys)
    reason = [line for line in out if line.startswith("bake grand_canyon baking (")]
    assert len(reason) == 1 and "sha256" in reason[0]
    assert "bake grand_canyon baked" in out and "bake yosemite up to date" in out
    assert calls["bake"] == ["grand_canyon", "yosemite", "grand_canyon"]

    raw = terrain / "yosemite.r16"
    data = bytearray(raw.read_bytes())
    data[10] ^= 0xFF
    raw.write_bytes(bytes(data))
    assert module.main(["--places"]) == 0
    out = _lines(capsys)
    reason = [line for line in out if line.startswith("bake yosemite baking (")]
    assert len(reason) == 1 and "sha256" in reason[0] and "yosemite.r16" in reason[0]
    assert "bake grand_canyon up to date" in out and "bake yosemite baked" in out
    assert calls["bake"] == ["grand_canyon", "yosemite", "grand_canyon", "yosemite"]
    assert calls["drape"] == ["grand_canyon", "yosemite"]


def _rewrite_provenance(terrain, key, edit):
    sidecar = terrain / f"{key}.json"
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    edit(meta["provenance"])
    sidecar.write_text(json.dumps(meta), encoding="utf-8")


def test_places_missing_datum_or_other_source_is_stale(places, capsys):
    module, terrain, calls = places
    assert module.main(["--places"]) == 0
    capsys.readouterr()
    assert module.bake_stale_reason("grand_canyon", terrain) is None

    _rewrite_provenance(terrain, "grand_canyon", lambda p: p.pop("datum"))
    assert "no datum block" in module.bake_stale_reason("grand_canyon", terrain)

    _rewrite_provenance(terrain, "yosemite",
                        lambda p: p.update(dataset="USGS 3DEP 1/3 arc-second"))
    reason = module.bake_stale_reason("yosemite", terrain)
    assert "3DEP" in reason and "not glo30" in reason
    assert module.bake_stale_reason("yosemite", terrain, source="3dep") is None

    assert module.main(["--places"]) == 0
    out = _lines(capsys)
    assert any(line.startswith("bake grand_canyon baking (no datum block")
               for line in out)
    assert any(line.startswith("bake yosemite baking (its sidecar names dataset")
               for line in out)
    assert calls["bake"] == ["grand_canyon", "yosemite", "grand_canyon", "yosemite"]
    capsys.readouterr()

    _rewrite_provenance(terrain, "yosemite",
                        lambda p: p.update(tiles={"N00_00_E000_00": "0" * 64}))
    reason = module.bake_stale_reason("yosemite", terrain)
    assert "N00_00_E000_00" in reason and "N37_00_W120_00" in reason
    _rewrite_provenance(terrain, "yosemite", lambda p: p.pop("tiles"))
    assert "no GLO-30 tiles" in module.bake_stale_reason("yosemite", terrain)
    (terrain / "yosemite.json").unlink()
    assert "yosemite.json is missing" in module.bake_stale_reason("yosemite", terrain)
    (terrain / "yosemite.r16").unlink()
    assert "yosemite.r16 is missing" in module.bake_stale_reason("yosemite", terrain)


def test_places_failure_is_named_and_exit_1(places, capsys, monkeypatch):
    module, terrain, calls = places
    good = module.bake

    def failing(location, *args, **kwargs):
        if location.key == "grand_canyon":
            raise urllib.error.URLError("the GLO-30 bucket is unreachable")
        return good(location, *args, **kwargs)

    monkeypatch.setattr(module, "bake", failing)
    assert module.main(["--places"]) == 1
    out = _lines(capsys)
    failed = [line for line in out if line.startswith("bake grand_canyon FAILED ")]
    assert failed == ["bake grand_canyon FAILED URLError: <urlopen error "
                      "the GLO-30 bucket is unreachable>"]
    assert "bake yosemite baked" in out
    assert not (terrain / "grand_canyon.r16").exists()
    assert (terrain / "yosemite.r16").is_file()


def test_bake_stale_reason_none_when_whole(places):
    module, terrain, calls = places
    assert module.bake_stale_reason("grand_canyon", terrain) is not None
    for key in PLACES:
        _fake_bake_field(key).write(terrain / key)
    for key in PLACES:
        assert module.bake_stale_reason(key, terrain) is None
        assert module.bake_stale_reason(key, terrain, source="glo30") is None
    assert "not 3dep" in module.bake_stale_reason("yosemite", terrain, source="3dep")


def test_places_rejects_extra_keys_exit_2(places, capsys):
    module, terrain, calls = places
    assert module.main(["--places", "yosemite"]) == 2
    assert module.main(["--places", "--all"]) == 2
    assert module.main(["--places", "--source", "3dep"]) == 2
    out = capsys.readouterr().out
    assert out.count("--places takes no keys") == 3
    assert calls["bake"] == [] and not terrain.exists()
    assert module.main(["nowhere"]) == 2


def test_cli_keys_use_the_same_skip_rule(places, capsys):
    """The positional path shares bake_stale_reason: a whole bake is
    'up to date', a corrupted one is re-baked with the reason named, and
    the old 'already baked' phrase is gone."""
    module, terrain, calls = places
    assert module.main(["yosemite"]) == 0
    assert module.main(["yosemite"]) == 0
    out = capsys.readouterr().out
    assert "yosemite           up to date (" in out
    assert "already baked" not in out and "already baked" not in SCRIPT.read_text(encoding="utf-8")
    meta = json.loads((terrain / "yosemite.json").read_text(encoding="utf-8"))
    meta["sha256"] = "f" * 64
    (terrain / "yosemite.json").write_text(json.dumps(meta), encoding="utf-8")
    assert module.main(["yosemite"]) == 0
    out = capsys.readouterr().out
    assert "re-baking (sidecar sha256 does not match" in out
    assert calls["bake"] == ["yosemite", "yosemite"]


def test_webapp_reads_what_places_wrote(places, monkeypatch):
    """The web app finds a place --places prepared: baked() is true,
    bake_curated fetches nothing, and the scene picker earns the bake
    for a spec at the place's origin."""
    import webapp.runs as runs
    from core.nl.llm_compiler import compile_prompt_llm
    from tests.test_llm_compiler import entry, fake_client

    module, terrain, calls = places
    assert module.main(["--places"]) == 0
    monkeypatch.setattr(runs, "TERRAIN_DIR", terrain)

    def never(*args, **kwargs):
        raise AssertionError("the web app re-fetched a prepared place")

    monkeypatch.setattr(runs, "bake", never)
    for key in PLACES:
        assert runs.baked(terrain / key)
        entry_ = runs.bake_curated(key)
        assert entry_["imagery"] == "present"
        assert entry_["terrain"] == str(terrain / key)
    location = LOCATIONS["grand_canyon"]
    spec = compile_prompt_llm(
        "a c172p over the grand canyon", client=fake_client({
            "fields": {"latitude": entry(location.origin_lat, "model", "grand canyon"),
                       "longitude": entry(location.origin_lon, "model", "grand canyon")},
            "notes": [], "questions": []})).spec
    scene = runs._earned_scene(spec)
    assert scene is not None and scene["key"] == "grand_canyon"
    assert scene["terrain"] == str(terrain / "grand_canyon")
    assert scene["imagery"] == str(terrain / "grand_canyon_imagery.json")


def test_places_do_not_touch_google_tiles_or_weather():
    """Google tiles stream at render time with the key (CLAUDE.md) and the
    storm weather default is the web app's; --places names neither."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.isascii()
    for name in ("FLIGHTSIM_" + "GOOGLE_" + "TILES", "GOOGLE", "WEATHER_" + "BACKEND",
                 "weather", "environ", "getenv"):
        assert name not in text, name
    assert "Google tiles are not part of this" in text
