"""The scene picture (core/capture/scene_overlay.py) on the engine-bundle
fixture: ground altitudes from the depth image land on the terrain the
scene was baked on, the iso-lines exist, the predicted path holds the
current flight, and the zip carries the picture and its JSON."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import numpy as np
import pytest

from core.capture.scene_overlay import (_depth_grid, draw_scene_frame, scene_geometry,
                                        scene_json, world_fields)

BUNDLE = Path(__file__).parent / "fixtures" / "engine_bundle_min"
FRAME = BUNDLE / "frames" / "chase" / "frame_0000.png"


@pytest.fixture(scope="module")
def manifest():
    return json.loads((BUNDLE / "capture_manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def record(manifest):
    return manifest["frames"][0]


def test_ground_from_depth_sits_on_the_baked_terrain(record):
    depth = _depth_grid(FRAME, record["width_px"], record["height_px"])
    north, east, alt, horiz = world_fields(record, depth)
    ground = record["state"]["altitude_m"] - record["state"]["agl_m"]
    near = np.isfinite(alt) & (horiz < 3000)
    assert near.any()
    # The visible ground near the aircraft is the canyon round the
    # flight model's own ground height (the bake), within its relief.
    assert abs(float(np.nanmedian(alt[near])) - ground) < 400.0


def test_geometry_has_every_layer(manifest, record):
    geo = scene_geometry(manifest, record, FRAME)
    for key in ("terrain", "contours", "grid", "drop_line", "flight_path", "pitch_ladder",
                "heading_tape", "environment"):
        assert key in geo, key
    assert geo["contours"]["_alpha"].max() > 0.9
    assert geo["drop_line"]["height_above_ground_m"] == pytest.approx(
        record["state"]["agl_m"], abs=0.1)
    path = geo["flight_path"]
    assert path["basis"].startswith("predicted")
    alts = [p["alt_m"] for p in path["points"]]
    assert max(alts) - min(alts) < 1.0          # level flight stays level
    assert [t["t_s"] for t in path["ticks"]] == [5.0, 10.0, 15.0, 20.0, 25.0, 30.0]
    j = scene_json(geo)
    assert "_alpha" not in json.dumps(j) and json.dumps(j)


def test_the_scene_picture_is_drawn(manifest, record, tmp_path):
    from PIL import Image, ImageChops

    target = draw_scene_frame(record, FRAME, tmp_path / "s.png", manifest=manifest)
    a, b = Image.open(FRAME).convert("RGB"), Image.open(target).convert("RGB")
    assert a.size == b.size and ImageChops.difference(a, b).getbbox() is not None


def test_the_zip_carries_the_scene_picture_and_json(tmp_path):
    from webapp.capture import box3d_archive

    run = tmp_path / "run"
    shutil.copytree(BUNDLE, run)
    with zipfile.ZipFile(box3d_archive(run, "chase")) as zf:
        assert "chase_3d/frame_0000_box3d_scene.png" in zf.namelist()
        data = json.loads(zf.read("chase_3d/frame_0000_box3d.json"))
    assert "scene" in data["pictures"]
    assert data["scene_overlay"]["environment"]["surface"] is not None
    assert data["scene_overlay"]["contours"]["interval_m"] > 0
