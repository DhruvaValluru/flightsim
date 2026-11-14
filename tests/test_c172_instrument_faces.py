"""Round 92, scene 12: the C172 cockpit view showed terrain through every
gauge hole, because c172p-interior.ac holds only the panel board and its
bezels. The dial faces are separate instrument models that the panel XML
loads with no <offsets>. Each one is now a beauty_only interior part.
Checked here without the engine or the package checkout."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C172 = json.loads((ROOT / "assets/aircraft_config/c172p.json").read_text(encoding="utf-8"))
INSTR = "Models/Interior/Panel/Instruments/"
#: the six-pack must be there; the rest of the stack is radios and engine gauges
SIX_PACK = ("asi/asi.ac", "AI/AI.ac", "alt/alt.ac", "tc/tc.ac", "hi/hi.ac", "VSI/VSI.ac")


def _instrument_rows():
    return [p for p in C172["parts"] if p["file"].startswith(INSTR)]


def test_the_six_pack_faces_are_converted():
    files = {p["file"][len(INSTR):] for p in _instrument_rows()}
    assert set(SIX_PACK) <= files
    assert len(files) == len(_instrument_rows())          # no instrument twice


def test_instrument_rows_are_beauty_only_interior_without_offsets():
    for row in _instrument_rows():
        assert row["interior"] is True and row["beauty_only"] is True, row["file"]
        # the panel XML loads them at the model origin; textures sit beside each .ac
        assert "offset_m" not in row and "pitch_deg" not in row and "texture_dir" not in row
        assert "fg1000" not in row["file"] and "gear-ctl" not in row["file"]


def test_the_instruments_follow_the_panel_board():
    files = [p["file"] for p in C172["parts"]]
    board = files.index("Models/Interior/Panel/c172p-panel/c172p-interior.ac")
    rows = [i for i, f in enumerate(files) if f.startswith(INSTR)]
    assert rows == list(range(board + 1, board + 1 + len(rows)))


def test_instrument_glass_is_left_out():
    # opaque glass (M_AircraftGlass) in front of a dial would hide it again
    excluded = {p["file"][len(INSTR):]: p.get("exclude", []) for p in _instrument_rows()}
    for part, name in (("AI/AI.ac", "RollRefGlass"), ("kt76a/kt76a.ac", "glass_panel"),
                       ("hobbs/hobbs.ac", "glass_panel"), ("mag-compass/mag-compass.ac", "Glass"),
                       ("digital-clock/digital-clock.ac", "glass_panel")):
        assert any(re.fullmatch(p, name) for p in excluded[part]), (part, name)
    assert any(re.fullmatch(p, "COM1Up") for p in excluded["kma20/kma20.ac"])
