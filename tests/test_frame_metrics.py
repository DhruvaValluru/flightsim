"""scripts/frame_metrics.py and its wiring into visual_fix_round.ps1.

Synthetic frames only: a check of the arithmetic on this machine, never a
visual result. The thresholds are uncalibrated and the report never fails a
round, which the ps1 checks below pin.
"""

import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import frame_metrics as fm  # noqa: E402

ROUND_PS1 = (REPO / "scripts" / "visual_fix_round.ps1").read_text(encoding="utf-8")


def _scene(seed=1, h=96, w=128):
    rng = np.random.default_rng(seed)
    base = np.linspace(40, 200, w)[None, :, None] + rng.normal(0, 12, (h, w, 3))
    return base.clip(0, 255).astype(np.uint8)


def test_a_black_and_a_flat_frame_are_blank_and_nothing_else():
    black = np.zeros((64, 64, 3), np.uint8)
    flat = np.full((64, 64, 3), 128, np.uint8)
    assert fm.health_flags(fm.frame_health(black)) == ["blank"]
    assert fm.health_flags(fm.frame_health(flat)) == ["blank"]
    assert fm.health_flags(fm.frame_health(_scene())) == []


def test_clipped_highlights_and_crushed_blacks_are_named():
    frame = _scene()
    frame[:20] = 255                      # ~21 % blown
    h = fm.frame_health(frame)
    assert h["clipped"] > fm.LIMITS["clipped_max"] and "clipped" in fm.health_flags(h)
    frame = _scene()
    frame[:20] = 0                        # ~21 % crushed
    h = fm.frame_health(frame)
    assert h["crushed"] > fm.LIMITS["crushed_max"] and "crushed" in fm.health_flags(h)
    assert "clipped" not in fm.health_flags(h)


def test_ssim_is_one_for_the_same_frame_and_low_for_another_shot():
    a = _scene(1)
    assert fm.ssim(fm.luma(a), fm.luma(a)) > 0.999
    other = _scene(2)[:, ::-1]
    assert fm.compare(a, other)["ssim"] < fm.compare(a, a)["ssim"]
    torn = np.random.default_rng(3).integers(0, 256, a.shape).astype(np.uint8)
    assert "ssim" in fm.compare(a, torn)["flags"]


def test_flicker_is_the_mean_luma_step_between_rounds():
    a = _scene(1)
    brighter = np.clip(a.astype(int) + 40, 0, 255).astype(np.uint8)
    same = fm.compare(a, a)
    assert same["flicker"] == 0 and same["flags"] == []
    got = fm.compare(brighter, a)
    assert got["flicker"] > fm.LIMITS["flicker_max"] and "flicker" in got["flags"]
    assert "shape_mismatch" in fm.compare(a, a[:64])["flags"]


def test_a_round_folder_is_matched_on_the_scene_number(tmp_path):
    prev, cur = tmp_path / "round_11", tmp_path / "round_12"
    prev.mkdir(); cur.mkdir()
    Image.fromarray(_scene(1)).save(prev / "11_matterhorn.jpg", quality=95)
    Image.fromarray(_scene(1)).save(cur / "11_matterhorn.jpg", quality=95)
    Image.fromarray(np.zeros((96, 128, 3), np.uint8)).save(cur / "15_night.jpg")
    Image.fromarray(_scene(4)).save(cur / "11_matterhorn_post.jpg")     # not the frame
    Image.fromarray(_scene(4)).save(cur / "contact.jpg")
    assert fm.main([str(cur), "--compare-with", str(prev)]) == 0
    got = json.loads((cur / "metrics.json").read_text(encoding="utf-8"))
    assert "uncalibrated" in got["calibration"] and got["compare_with_found"] is True
    assert set(got["scenes"]) == {"11", "15"}
    assert got["scenes"]["11"]["frame"] == "11_matterhorn.jpg"
    assert got["scenes"]["11"]["vs_previous"]["ssim"] > 0.95
    assert got["scenes"]["15"]["flags"] == ["blank"]
    assert got["scenes"]["15"]["vs_previous"] is None           # not in round 11
    # without a comparison there is no vs_previous at all
    no_cmp = fm.round_metrics(cur)
    assert "vs_previous" not in no_cmp["scenes"]["11"]


def test_an_unreadable_frame_is_said_not_fatal(tmp_path):
    (tmp_path / "11_x.jpg").write_bytes(b"not a jpeg")
    got = fm.round_metrics(tmp_path)
    assert "error" in got["scenes"]["11"]


def test_the_round_script_runs_the_pixel_report_before_round_json():
    report = ROUND_PS1.index("@(\"scripts\\frame_metrics.py\", $out)")
    assert ROUND_PS1.index("scripts\\visual_round.py $Round") < report < ROUND_PS1.index('"ROUND.json"')
    assert "pixel_metrics = $pixel" in ROUND_PS1
    assert "ConvertTo-Json -Depth 10" in ROUND_PS1


def test_the_pixel_report_never_fails_or_refuses_the_round():
    start = ROUND_PS1.index("# 4b. the pixel report")
    end = ROUND_PS1.index("# 5. -Full")
    block = ROUND_PS1[start:end]
    assert "Refuse" not in block and "exit" not in block.replace("(exit $LASTEXITCODE)", "")
    assert "try {" in block and "catch {" in block


def test_compare_with_a_round_number_feeds_the_pixel_report_and_a_head_the_sheet():
    assert re.search(r"\$CompareWith -match '\^\(round_\)\?\(\\d\+\)\$'", ROUND_PS1)
    assert '"--compare-with", $prevRound' in ROUND_PS1
    assert "$CompareWith -notmatch '^head'" in ROUND_PS1


def test_the_round_script_forwards_the_compiler_and_spec_dir():
    assert '[ValidateSet("llm", "regex")][string]$Compiler = "llm"' in ROUND_PS1
    assert '"--spec-dir", $pinDir, "--compiler", $Compiler' in ROUND_PS1
    assert 'if ($SpecDir) { $SpecDir } else { Join-Path $repo "runs\\visual\\specs" }' in ROUND_PS1
