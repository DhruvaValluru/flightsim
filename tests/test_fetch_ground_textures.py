"""scripts/fetch_ground_textures.py against a fake Poly Haven (no network):
the choice of asset per surface, the three maps, the md5 check, the
provenance, and the refusals by name."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fetch_ground_textures",
                                              REPO / "scripts" / "fetch_ground_textures.py")
ft = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ft)

ASSETS = {
    "sand_close": {"name": "Sand close", "tags": ["sand"], "categories": ["natural"],
                   "download_count": 9000},
    "aerial_sand_dunes": {"name": "Aerial dunes", "tags": ["sand", "aerial"],
                          "categories": ["terrain"], "download_count": 10},
    "snow_field": {"name": "Snow", "tags": ["snow"], "categories": [], "download_count": 5},
    "brick_wall": {"name": "Bricks", "tags": ["brick"], "categories": ["man made"],
                   "download_count": 99999},
}
BYTES = {name: f"{name}-bytes".encode() for name in ("d", "n", "r")}


def files_for(asset_id, md5_ok=True, missing=None):
    out = {}
    for key, short in (("Diffuse", "d"), ("nor_gl", "n"), ("Rough", "r")):
        if key == missing:
            continue
        data = BYTES[short]
        out[key] = {"1k": {"jpg": {"url": f"https://dl/{asset_id}/{short}.jpg",
                                   "md5": hashlib.md5(data).hexdigest() if md5_ok else "0" * 32}}}
    return out


def fake(files):
    def fetch(url):
        if url.endswith("/assets?t=textures"):
            return json.dumps(ASSETS).encode()
        if "/files/" in url:
            return json.dumps(files(url.rsplit("/", 1)[1])).encode()
        return BYTES[url.rsplit("/", 1)[1][0]]
    return fetch


def test_aerial_texture_is_preferred_over_downloads():
    ranked = [a for a, _ in ft.candidates(ASSETS, "desert")]
    assert ranked == ["aerial_sand_dunes", "sand_close"]
    assert ft.candidates(ASSETS, "city") == []


def test_fetch_writes_three_maps_and_provenance(tmp_path):
    record = ft.fetch_surface("desert", ASSETS, fake(files_for), out_dir=tmp_path)
    assert record["asset_id"] == "aerial_sand_dunes"
    assert record["licence"] == "CC0-1.0" and "Poly Haven" in record["credit"]
    for name in ("diffuse", "normal", "rough"):
        assert (tmp_path / "desert" / f"{name}.jpg").is_file()
    saved = json.loads((tmp_path / "desert" / "provenance.json").read_text(encoding="utf-8"))
    assert saved["files"]["normal"]["polyhaven_map"] == "nor_gl"


def test_md5_mismatch_refuses(tmp_path):
    with pytest.raises(ft.TextureError) as exc:
        ft.fetch_surface("snow", ASSETS, fake(lambda a: files_for(a, md5_ok=False)),
                         out_dir=tmp_path)
    assert exc.value.constraint == "textures.digest"


def test_missing_map_falls_through_then_refuses(tmp_path):
    with pytest.raises(ft.TextureError) as exc:
        ft.fetch_surface("snow", ASSETS, fake(lambda a: files_for(a, missing="Rough")),
                         out_dir=tmp_path)
    assert exc.value.constraint == "textures.map_missing"


def test_no_candidate_and_unknown_pick_refuse(tmp_path):
    with pytest.raises(ft.TextureError) as exc:
        ft.fetch_surface("city", ASSETS, fake(files_for), out_dir=tmp_path)
    assert exc.value.constraint == "textures.no_candidate"
    with pytest.raises(ft.TextureError) as exc:
        ft.fetch_surface("desert", ASSETS, fake(files_for), pick="nope", out_dir=tmp_path)
    assert exc.value.constraint == "textures.unknown_asset"


def test_existing_file_with_other_bytes_needs_force(tmp_path):
    (tmp_path / "desert").mkdir()
    (tmp_path / "desert" / "diffuse.jpg").write_bytes(b"other")
    with pytest.raises(ft.TextureError):
        ft.fetch_surface("desert", ASSETS, fake(files_for), out_dir=tmp_path)
    ft.fetch_surface("desert", ASSETS, fake(files_for), out_dir=tmp_path, force=True)


def test_main_refuses_an_unknown_surface(capsys):
    assert ft.main(["--only", "moon"], fetch=fake(files_for)) == 2
    assert "textures.surface" in capsys.readouterr().out
