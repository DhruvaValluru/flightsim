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
    summary.write_text(json.dumps(batch))
    out = visual_round.write_round(3, gallery, summary, tmp_path / "visual")
    jpgs = sorted(p.name for p in out.glob("0*.jpg"))
    # 05's frame is stale, from an earlier batch: this batch refused it
    assert jpgs == [f"0{n}_shot_{n}.jpg" for n in (1, 2, 3, 4)]
    assert Image.open(out / "01_shot_1.jpg").width == 1280
    sheet = Image.open(out / "contact.jpg")
    assert sheet.width == 4 * 480
    assert json.loads((out / "summary.json").read_text())[0] == {
        "number": 1, "name": "shot 1", "prompt": "p", "outcome": "done",
        "why": None, "run_id": "abc", "lighting": None}
