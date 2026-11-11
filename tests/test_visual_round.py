"""scripts/visual_round.py: a round's frames become small committed copies."""

import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import visual_round  # noqa: E402


def test_a_round_writes_each_frame_a_contact_sheet_and_the_summary(tmp_path):
    gallery = tmp_path / "g"
    gallery.mkdir()
    for n in (1, 2, 3, 4, 5):
        Image.new("RGB", (1920, 1080), (n * 40, 90, 120)).save(gallery / f"0{n}_shot_{n}_frame.png")
    Image.new("RGB", (100, 100)).save(gallery / "01_shot_1_boxes.png")
    summary = tmp_path / "s.json"
    batch = [{"number": n, "name": f"shot {n}", "prompt": "p", "outcome": "done",
              "run_id": "abc"} for n in (1, 2, 3, 4)]
    batch.append({"number": 5, "name": "shot 5", "prompt": "p", "outcome": "refused"})
    summary.write_text(json.dumps(batch), encoding="utf-8")
    out = visual_round.write_round(3, gallery, summary, tmp_path / "visual", tmp_path / "runs")
    jpgs = sorted(p.name for p in out.glob("0*.jpg"))
    # 05's frame is stale, from an earlier batch: this batch refused it
    assert jpgs == [f"0{n}_shot_{n}.jpg" for n in (1, 2, 3, 4)]
    assert Image.open(out / "01_shot_1.jpg").width == 1280
    sheet = Image.open(out / "contact.jpg")
    assert sheet.width == 4 * 480
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))[0] == {
        "number": 1, "name": "shot 1", "prompt": "p", "outcome": "done",
        "why": None, "run_id": "abc", "lighting": None, "seconds": None, "spec_sha256": None, "render_json": False}


def test_the_look_report_names_missing_keys(tmp_path):
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "render.json").write_text(json.dumps({
        "beauty_look": {}, "render_settings": {"beauty_path": "x", "world_beauty": 1},
        "aircraft_look": 1, "hero_lighting": [{"pixel_moving_effects": 0}]}), encoding="utf-8")
    assert visual_round.look_report("r1", tmp_path / "runs") == {
        "render_json": True, "look_keys_missing": [], "new_look_ran": True, "beauty_post": False}
    (run / "render.json").write_text(json.dumps({"render_settings": {"quality": "beauty"}}), encoding="utf-8")
    report = visual_round.look_report("r1", tmp_path / "runs")
    assert report["new_look_ran"] is False and "beauty_look" in report["look_keys_missing"]
    assert visual_round.look_report("nope", tmp_path / "runs") == {"render_json": False}


def test_the_look_report_reads_the_per_camera_render_json(tmp_path):
    """Round 1: renders write runs/webapp/<id>/frames/<camera>/render.json."""
    camera = tmp_path / "runs" / "r2" / "frames" / "chase"
    camera.mkdir(parents=True)
    (camera / "render.json").write_text(json.dumps({k: {} for k in visual_round.LOOK_KEYS}), encoding="utf-8")
    assert visual_round.look_report("r2", tmp_path / "runs") == {
        "render_json": True, "look_keys_missing": [], "new_look_ran": True, "beauty_post": False}


def test_a_ghost_copy_of_the_aircraft_is_scored_and_a_clean_frame_is_not():
    import numpy as np

    from visual_round import GHOST_SUSPECT, ghost_score

    rng = np.random.default_rng(7)
    frame = rng.normal(120, 4, (200, 300, 3)).clip(0, 255)
    mask = np.zeros((200, 300), np.uint8)
    plane = np.zeros((30, 60)); plane[12:18, :] = 90; plane[:, 26:34] = 90
    frame[80:110, 120:180] += plane[..., None]
    mask[80:110, 120:180][plane > 0] = 1
    clean, _ = ghost_score(frame, mask)
    ghosted = frame.copy()
    ghosted[30:60, 40:100] += 0.35 * plane[..., None]       # a faint copy up-left
    score, offset = ghost_score(ghosted, mask)
    assert clean < GHOST_SUSPECT < score
    assert abs(offset[0] + 80) <= 4 and abs(offset[1] + 50) <= 4    # one search stride
