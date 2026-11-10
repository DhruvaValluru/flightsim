"""scripts/visual_compare.py: two rounds become labelled before/after pairs."""

import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import visual_compare  # noqa: E402


def test_pairs_numbers_and_one_sided_scenes(tmp_path):
    for rnd, shade in ((0, 50), (1, 150)):
        folder = tmp_path / f"round_{rnd}"
        folder.mkdir()
        Image.new("RGB", (1280, 720), (shade,) * 3).save(folder / "01_a.jpg")
    Image.new("RGB", (1280, 720)).save(tmp_path / "round_1" / "02_new.jpg")
    out = visual_compare.compare(0, 1, tmp_path)
    rows = json.loads((out / "compare.json").read_text())
    assert rows[0]["scene"] == "01_a" and rows[0]["moved_share"] == 1.0
    assert rows[0]["mean_luma_0"] < rows[0]["mean_luma_1"]
    assert rows[1] == {"scene": "02_new", "only_in": "round_1"}
    assert (out / "01_a.jpg").is_file() and (out / "contact.jpg").is_file()
