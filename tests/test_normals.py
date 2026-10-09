"""Stand-in normal maps derived from the drape textures."""
import json

import numpy as np
import pytest
from PIL import Image

from core.xplane import normals


def _tile(path, seed):
    rng = np.random.default_rng(seed)
    Image.fromarray(rng.integers(40, 200, (64, 64, 3), dtype=np.uint8)).save(path)


def test_flat_texture_gives_a_flat_normal():
    nrm = normals.derive_normal(np.full((32, 32, 3), 128, np.uint8), 100.0, 100.0, 10.0)
    assert np.all(nrm[..., 2] == 255)
    assert np.all(np.abs(nrm[..., :2].astype(int) - 128) <= 1)


def test_tilt_follows_the_target_and_the_map_tiles(tmp_path):
    _tile(tmp_path / "rock.png", 1)
    rgb = np.asarray(Image.open(tmp_path / "rock.png"))
    gentle = normals.derive_normal(rgb, 100.0, 100.0, 4.0)
    steep = normals.derive_normal(rgb, 100.0, 100.0, 16.0)
    assert gentle[..., 2].mean() > steep[..., 2].mean()
    # same input shifted by whole rows -> same normals shifted (wrapped)
    shifted = normals.derive_normal(np.roll(rgb, 5, axis=0), 100.0, 100.0, 16.0)
    assert np.array_equal(np.roll(steep, 5, axis=0), shifted)


def test_dark_is_low_in_the_directx_convention():
    # a bright row above a dark row: height falls toward the image bottom,
    # so the surface faces down the image: green above 128 (DirectX +y down)
    rgb = np.full((64, 64, 3), 120, np.uint8)
    rgb[30:34] = 220
    nrm = normals.derive_normal(rgb, 64.0, 64.0, 10.0)
    assert nrm[34, 10, 1] > 128 and nrm[29, 10, 1] < 128


def test_the_drape_falls_back_to_the_derived_normal(tmp_path):
    from core.xplane.drape import _role_normal

    _tile(tmp_path / "rock.png", 2)
    (tmp_path / "drape_textures.json").write_text(json.dumps(
        {"rock": {"file": "rock.png", "metres_x": 100.0, "metres_y": 100.0}}), encoding="utf-8")
    assert _role_normal(tmp_path, "rock", {"file": "rock.png"})["normal"] is None
    written = normals.derive_drape_normals(tmp_path)
    assert written["rock"]["file"] == "rock_nrm_derived.png"
    got = _role_normal(tmp_path, "rock", {"file": "rock.png"})
    assert got["normal"].endswith("rock_nrm_derived.png")
    assert got["normal_source"].startswith("derived")
    extracted = _role_normal(tmp_path, "rock", {"file": "rock.png", "normal": "real.png"})
    assert extracted["normal_source"] == "extracted"
