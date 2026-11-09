"""experiments/look_label_check.py on synthetic pictures: the offset is
found where it was put, a symmetric blur leaves it at zero, the control
trips on a metric that cannot see, and the CLI reads two bundles."""

import json

import numpy as np
import pytest

from experiments import look_label_check as llc


def scene(width=240, height=140, cx=120.0, cy=70.0, a=50.0, b=18.0):
    """A sky gradient with a dark ellipse 'aircraft'; (picture, mask)."""
    yy, xx = np.mgrid[0:height, 0:width]
    sky = np.stack([0.45 + 0.3 * yy / height, 0.6 + 0.2 * yy / height,
                    np.full(yy.shape, 0.9)], axis=-1)
    inside = ((xx - cx) / a) ** 2 + ((yy - cy) / b) ** 2 <= 1.0
    picture = sky.copy()
    picture[inside] = (0.15, 0.16, 0.18)
    return (picture * 255).round().astype(np.uint8), inside


def box_blur(picture, radius):
    out = np.zeros(picture.shape, dtype="float64")
    n = 0
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            out += llc.shift_image(picture, dx, dy).astype("float64")
            n += 1
    return (out / n).round().astype(np.uint8)


def test_an_aligned_picture_measures_no_offset():
    picture, mask = scene()
    got = llc.edge_alignment(picture, mask)
    assert got["offset_length_px"] <= 0.5
    assert got["edge_distance_median_px"] <= 1.0


@pytest.mark.parametrize("dx,dy", [(3, 0), (-2, 0), (0, 2), (2, -2)])
def test_a_shifted_picture_measures_its_shift(dx, dy):
    picture, mask = scene()
    got = llc.edge_alignment(llc.shift_image(picture, dx, dy), mask)
    assert got["offset_px"][0] == pytest.approx(dx, abs=0.6)
    assert got["offset_px"][1] == pytest.approx(dy, abs=0.6)


def test_a_symmetric_blur_does_not_move_the_edge():
    picture, mask = scene()
    got = llc.edge_alignment(box_blur(picture, 2), mask)
    assert got["offset_length_px"] <= 0.6


def test_the_control_recovers_its_shift_and_voids_a_blind_metric():
    picture, mask = scene()
    measured = llc.edge_alignment(picture, mask)
    good = llc.control(picture, mask, measured)
    assert not good["void"] and good["recovered_px"] == pytest.approx(llc.CONTROL_SHIFT_PX, abs=0.6)
    flat = np.full(picture.shape, 128, dtype=np.uint8)       # no silhouette to see
    blind = llc.control(flat, mask, llc.edge_alignment(flat, mask))
    assert blind["void"]


def test_compare_grades_beauty_against_the_tolerance_at_two_resolutions():
    m_pic, m_mask = scene(240, 140, 120, 70, 50, 18)
    b_pic, b_mask = scene(480, 280, 240, 140, 100, 36)        # beauty at twice the size
    report = llc.compare(m_pic, m_mask, b_pic, b_mask)
    assert report["verdict"] == "ALIGNED"
    assert report["mask_iou_at_measure_size"] > 0.95
    moved = llc.compare(m_pic, m_mask, llc.shift_image(b_pic, 4, 0), b_mask)
    assert moved["verdict"] == "NOT ALIGNED"
    assert moved["beauty"]["offset_length_px"] == pytest.approx(4, abs=0.6)
    assert moved["beauty_offset_in_measure_px"] == pytest.approx(2, abs=0.4)
    assert moved["uncalibrated"] == llc.UNCALIBRATED


def test_a_mismatched_or_empty_mask_is_refused():
    picture, mask = scene()
    with pytest.raises(ValueError):
        llc.edge_alignment(picture, mask[:-1])
    with pytest.raises(ValueError):
        llc.edge_alignment(picture, np.zeros_like(mask))


def write_bundle(root, picture, mask, int_id=1):
    from PIL import Image

    folder = root / "frames" / "chase"
    folder.mkdir(parents=True)
    Image.fromarray(picture).save(folder / "frame_0000.png")
    Image.fromarray((mask * int_id).astype(np.uint8)).save(folder / "frame_0000_mask.png")
    return root


def test_the_cli_reads_two_bundles_and_exits_by_verdict(tmp_path, capsys):
    m_pic, m_mask = scene()
    measure = write_bundle(tmp_path / "measure", m_pic, m_mask)
    beauty = write_bundle(tmp_path / "beauty", m_pic, m_mask)
    out = tmp_path / "report.json"
    assert llc.main(["--measure", str(measure), "--beauty", str(beauty), "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["verdict"] == "ALIGNED" and report["frame"] == "frame_0000.png"
    assert "UNCALIBRATED" in capsys.readouterr().out
    moved = write_bundle(tmp_path / "moved", llc.shift_image(m_pic, 4, 0), m_mask)
    assert llc.main(["--measure", str(measure), "--beauty", str(moved)]) == 1
    assert llc.main(["--measure", str(measure), "--beauty", str(tmp_path / "nowhere")]) == 2
    assert "REFUSED -- look_label_check" in capsys.readouterr().out


def test_a_radial_move_with_no_net_shift_is_not_aligned():
    """Lens distortion about the subject moves its silhouette out on every
    side: the best translation stays near zero, the edge spread does not."""
    measure, mask = scene()
    beauty, _ = scene(a=53.0, b=19.0)          # tips 3 px out, mask unchanged
    report = llc.compare(measure, mask, beauty, mask)
    assert report["beauty"]["offset_length_px"] <= llc.LOOK_ALIGNMENT_TOL_PX
    assert report["edge_p90_excess_over_measure_px"] > llc.LOOK_ALIGNMENT_TOL_PX
    assert report["verdict"] == "NOT ALIGNED"
