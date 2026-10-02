"""S1: the diffraction x Gaussian MTF, its kernel (energy 1, sha256, the
predicted MTF50) and the slanted-edge measurement that shows the kernel
did what its MTF says -- within 5 % of the analytic MTF50 in both
regimes; an absent block leaves the frame bit-identical (the null).

Measured here (2026-09-29): sigma = 1 px at the default 28.1 um pitch,
analytic MTF50 0.1823 cycles/px, e-SFR 0.1815 (0.45 % off); diffraction
alone at a 2 um pitch, f/8, 550 nm, analytic 0.1836, e-SFR 0.1812
(1.3 % off); a sigma = 0.5 px kernel has MTF 0.27 at Nyquist, aliases,
and is flagged rather than claimed (4.7 % off, at the tolerance's edge).
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from core.capture import optics as O
from core.capture.profile import apply_profile, apply_profile_detailed, load_profile
from core.records import AppliedVariable

PITCH_M = 36e-3 / 1280           # the default camera's 28.125 um pixel
RECORD = {"width_px": 1280, "height_px": 720, "sensor_width_mm": 36.0, "sensor_height_mm": 20.25,
          "fx_px": 1244.4, "fy_px": 1244.4, "principal_point_px": [640.0, 360.0]}


# -- the MTF by hand ----------------------------------------------------------------------------

def test_the_diffraction_cutoff_and_mtf_by_hand():
    """nu_c = 1 / (550 nm x 8) = 227 272.7 cycles/m; at nu_c / 2 the MTF is
    (2/pi)(acos 0.5 - 0.5 sqrt 0.75) = 0.3910; 0 beyond the cutoff."""
    nu_c = O.diffraction_cutoff(550e-9, 8.0)
    assert nu_c == pytest.approx(1.0 / (550e-9 * 8.0), rel=1e-12)
    assert nu_c == pytest.approx(227272.7, abs=0.1)
    half = float(O.diffraction_mtf(nu_c / 2.0, 550e-9, 8.0))
    assert half == pytest.approx((2.0 / math.pi) * (math.acos(0.5) - 0.5 * math.sqrt(0.75)), rel=1e-12)
    assert half == pytest.approx(0.3910, abs=1e-4)
    assert float(O.diffraction_mtf(0.0, 550e-9, 8.0)) == pytest.approx(1.0)
    assert float(O.diffraction_mtf(nu_c * 1.5, 550e-9, 8.0)) == 0.0
    assert float(O.gaussian_mtf(1000.0, 10e-6)) == pytest.approx(math.exp(-2 * math.pi ** 2 * 1e-4), rel=1e-12)
    assert float(O.gaussian_mtf(1000.0, 0.0)) == 1.0
    with pytest.raises(O.OpticsError, match="sensing.optics"):
        O.gaussian_mtf(1.0, -1e-6)


def test_the_analytic_mtf50_of_a_gaussian_is_the_closed_form():
    """exp(-2 pi^2 s^2 nu^2) = 1/2 at nu = sqrt(ln 2 / (2 pi^2)) / s: with s =
    1 px that is 0.1874 cycles/px, before the (negligible) diffraction term."""
    sigma = PITCH_M
    nu50 = O.mtf50_cyc_per_m(550e-9, 8.0, sigma) * PITCH_M
    closed = math.sqrt(math.log(2.0) / (2.0 * math.pi ** 2)) / 1.0
    assert nu50 == pytest.approx(closed, rel=0.03)              # diffraction takes 2.7 %
    assert nu50 == pytest.approx(0.1823, abs=1e-3)


# -- the kernel -----------------------------------------------------------------------------------

def test_the_kernel_has_energy_one_an_odd_support_and_a_stable_digest():
    psf, meta = O.kernel(550e-9, 8.0, PITCH_M, PITCH_M)
    assert psf.shape == (meta["support_px"], meta["support_px"]) and meta["support_px"] % 2 == 1
    assert float(psf.sum()) == pytest.approx(1.0, abs=1e-12) and meta["kernel_energy"] == pytest.approx(1.0, abs=1e-12)
    assert (psf >= 0.0).all()
    assert meta["kernel_sha256"] == O.kernel_sha256(psf) and len(meta["kernel_sha256"]) == 64
    again, _ = O.kernel(550e-9, 8.0, PITCH_M, PITCH_M)
    assert O.kernel_sha256(again) == meta["kernel_sha256"]
    assert meta["cutoff_cyc_per_px"] == pytest.approx(227272.7 * PITCH_M, rel=1e-6)
    assert meta["sub_pixel_diffraction"] is True and meta["aliased"] is False
    # A different sigma is a different kernel and digest.
    other, other_meta = O.kernel(550e-9, 8.0, 2 * PITCH_M, PITCH_M)
    assert other_meta["kernel_sha256"] != meta["kernel_sha256"]
    for bad in (8, 4, 131):
        with pytest.raises(O.OpticsError, match="sensing.optics"):
            O.kernel(550e-9, 8.0, PITCH_M, PITCH_M, support_px=bad)
    with pytest.raises(O.OpticsError, match="sensing.optics"):
        O.kernel(550e-9, 8.0, -1.0, PITCH_M)
    with pytest.raises(O.OpticsError, match="sensing.optics"):
        O.kernel(0.0, 8.0, 0.0, PITCH_M)


def test_convolution_conserves_the_mean_of_a_flat_frame():
    psf, _ = O.kernel(550e-9, 8.0, PITCH_M, PITCH_M)
    flat = np.full((24, 32, 3), 0.37)
    out = O.convolve(flat, psf)
    assert out.shape == flat.shape and np.allclose(out, 0.37, atol=1e-12)
    gray = O.convolve(flat[..., 0], psf)
    assert gray.shape == (24, 32) and np.allclose(gray, 0.37, atol=1e-12)


# -- the slanted edge: measured, not asserted ------------------------------------------------------

@pytest.mark.parametrize("sigma_m, pitch_m, label", [
    (PITCH_M, PITCH_M, "aberration-dominated, sigma 1 px at 28.1 um"),
    (0.0, 2e-6, "diffraction-dominated, 2 um pitch at f/8"),
])
def test_the_esfr_mtf50_agrees_with_the_analytic_one_within_5_percent(sigma_m, pitch_m, label):
    psf, meta = O.kernel(550e-9, 8.0, sigma_m, pitch_m)
    edge = O.slanted_edge_image(160, 120, 5.0)
    assert O.esfr_mtf50(edge) > 1.5                    # the unblurred edge is the sampling's own
    measured = O.esfr_mtf50(O.convolve(edge, psf))
    analytic = meta["mtf50_predicted_cyc_per_px"]
    assert abs(measured - analytic) / analytic < 0.05, (label, measured, analytic)
    assert abs(measured - analytic) / analytic < 0.02, (label, measured, analytic)   # measured: 0.45 %, 1.3 %


def test_a_sub_pixel_gaussian_aliases_and_says_so():
    psf, meta = O.kernel(550e-9, 8.0, 0.5 * PITCH_M, PITCH_M)
    assert meta["mtf_at_nyquist"] > O.ALIASING_MTF_AT_NYQUIST and meta["aliased"] is True
    assert meta["clipped_negative_energy"] > 0.0


def test_the_esfr_reads_the_edge_angle_and_refuses_a_frame_without_one():
    frequencies, mtf = O.esfr(O.slanted_edge_image(96, 64, 5.0))
    assert frequencies[0] == 0.0 and mtf[0] == pytest.approx(1.0)
    assert O.mtf50_from_curve([0.0, 0.1, 0.2], [1.0, 0.75, 0.25]) == pytest.approx(0.15)
    assert O.mtf50_from_curve([0.0, 0.1], [1.0, 0.9]) == 0.1
    with pytest.raises(O.OpticsError, match="sensing.optics"):
        O.esfr(np.full((32, 32), 0.5))


# -- the block, the null and the record -------------------------------------------------------------

@pytest.mark.parametrize("block, fragment", [
    ({"model": "airy"}, "not modelled"),
    ({"model": "diffraction_gaussian", "focal": 1}, "unknown keys"),
    ({"model": "diffraction_gaussian", "sigma_um": -2.0}, "non-negative"),
    ({"model": "diffraction_gaussian", "support_px": 10}, "odd"),
    ({"model": "diffraction_gaussian", "wavelength_nm": 0}, "positive"),
    ("gaussian", "mapping"),
])
def test_a_malformed_optics_block_refuses_sensing_optics(block, fragment):
    with pytest.raises(O.OpticsError) as info:
        O.check_optics_block(block)
    assert info.value.constraint == "sensing.optics" and fragment in info.value.message


def test_the_block_takes_the_camera_s_aperture_when_it_states_none():
    psf, block = O.optics_block({"model": "diffraction_gaussian", "sigma_um": 28.125}, RECORD, 5.6)
    assert block["f_number"] == 5.6 and "camera" in block["f_number_basis"]
    assert block["pixel_pitch_um"] == pytest.approx(28.125)
    own, own_block = O.optics_block({"model": "diffraction_gaussian", "f_number": 11.0}, RECORD, 5.6)
    assert own_block["f_number"] == 11.0 and "profile" in own_block["f_number_basis"]
    record = O.optics_record(block, 0.0)
    assert record.readback.agrees and record.readback.property == "kernel_energy"
    assert record.null_test.ok and record.null_test.kind == "bounded"
    assert AppliedVariable.from_dict(record.to_dict()).to_dict() == record.to_dict()
    assert record.unit == "cycles/px" and record.value == block["mtf50_predicted_cyc_per_px"]


def _profile_with(tmp_path, **blocks):
    data = json.loads((Path(__file__).resolve().parents[1] / "assets/camera_profiles/ideal_pinhole.json")
                      .read_text(encoding="utf-8"))
    data["name"] = "optics_test"
    data.update(blocks)
    (tmp_path / "optics_test.json").write_text(json.dumps(data), encoding="utf-8")
    return load_profile("optics_test", profile_dir=tmp_path)


def test_an_absent_block_leaves_the_frame_bit_identical_and_a_present_one_blurs_it_the_null(tmp_path):
    rng = np.random.default_rng(1)
    frame = np.round(rng.random((36, 48, 3)) * 255.0) / 255.0        # already at the 8-bit ADC
    rec = {**RECORD, "width_px": 48, "height_px": 36, "fx_px": 46.7, "fy_px": 46.7,
           "principal_point_px": [24.0, 18.0]}
    absent = _profile_with(tmp_path)
    out, blocks = apply_profile_detailed(frame, absent, rec, (0, 0, 0), 1)
    assert np.array_equal(out, frame) and blocks["psf"] is None and blocks["stages"] == ["adc"]
    present = _profile_with(tmp_path, optics={"model": "diffraction_gaussian", "sigma_um": 750.0})
    assert present.optics is not None and not present.is_ideal and absent.is_ideal
    blurred, blocks = apply_profile_detailed(frame, present, rec, (0, 0, 0), 1, aperture_f=8.0)
    assert not np.array_equal(blurred, frame) and blocks["stages"] == ["psf", "adc"]
    assert blocks["psf"]["kernel_sha256"] == O.kernel(550e-9, 8.0, 750e-6, O.pixel_pitch_m(rec))[1]["kernel_sha256"]
    # The whole-frame mean is conserved (energy 1) up to the ADC rounding.
    assert abs(float(blurred.mean()) - float(frame.mean())) < 0.01
    assert np.array_equal(apply_profile(frame, absent, rec, (0, 0, 0), 1), frame)
    with pytest.raises(O.OpticsError, match="no f-number"):
        apply_profile_detailed(frame, present, rec, (0, 0, 0), 1)
