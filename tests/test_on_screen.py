"""Gate 5's two on-screen clauses: what a viewer actually sees.

The regression these exist for is ASSUMPTIONS §1.5, quoted in
FlightSimCameraDirector.h and worth quoting again because of how quietly it
passes every other kind of check:

    "A chase camera rigidly parented to the aircraft, so every attitude change
     happened to the aircraft and the camera simultaneously and cancelled out
     visually. The aircraft appeared motionless in frame for the entire clip.
     Real roll of +7 deg -> -7 deg was invisible."

Every number in that clip's telemetry was correct. The FDM rolled, the manifest
said so, and nothing was visible. So the test cannot be "the camera was
configured with the right preset" -- it has to be a measurement of the pixels,
and the measurement has to fail when the pixels do not move.

The frames here are synthetic: a bright bar on black, tilted to a known angle.
Real frames come from the Unreal host and are measured by the same function.
"""

import json
import math
import struct
import zlib

import numpy as np
import pytest

from experiments.gate5_ue_parity import (
    BACKGROUND_LEVEL, ON_SCREEN, measure_frames, silhouette_bank_degrees,
)


def write_png(path, pixels):
    """Minimal 8-bit RGB PNG. Avoids depending on an image library to *write*.

    Reading is rasterio's job (it is already a dependency for the DEM work);
    writing one by hand keeps the test's input under the test's control.
    """
    height, width = pixels.shape
    rgb = np.repeat(pixels[:, :, None], 3, axis=2).astype(np.uint8)
    raw = b"".join(b"\x00" + rgb[row].tobytes() for row in range(height))

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return path


def bar(angle_deg, width=320, height=180, half_thickness=3, half_span=110):
    """A bright bar through the centre at ``angle_deg``, rows increasing down.

    Stands in for the aircraft's silhouette: the wing is the long axis, so its
    image angle is what a viewer reads as bank.
    """
    image = np.zeros((height, width), dtype=np.uint8)
    cx, cy = width // 2, height // 2
    slope = math.tan(math.radians(angle_deg))
    for x in range(cx - half_span, cx + half_span + 1):
        y = int(round(cy + (x - cx) * slope))
        for dy in range(-half_thickness, half_thickness + 1):
            if 0 <= y + dy < height:
                image[y + dy, x] = 200
    return image


def render_run(tmp_path, rolls, image_angles=None, camera_roll=0.0,
               surfaces=None, blank=()):
    """Write a synthetic rendered run: frames plus the manifest beside them.

    ``image_angles`` defaults to ``rolls`` -- an honest render, in which what
    the pixels show is what the FDM did.
    """
    image_angles = rolls if image_angles is None else image_angles
    records = []
    for i, (roll, angle) in enumerate(zip(rolls, image_angles)):
        name = f"frame_{i:04d}.png"
        pixels = (np.zeros((180, 320), dtype=np.uint8) if i in blank
                  else bar(angle))
        write_png(tmp_path / name, pixels)
        records.append({
            "frame": name,
            "t": i * 0.2,
            "roll_deg": roll,
            "pitch_deg": 3.0,
            "aileron_cmd": 0.0,
            "camera_roll_deg": camera_roll,
            "lit_pixels": int((pixels > BACKGROUND_LEVEL).sum()),
            "surface_component_deg": (
                surfaces[i] if surfaces is not None
                else {"aileron_l": roll * 0.3, "aileron_r": -roll * 0.3,
                      "elevator": -5.55, "rudder": 0.0}
            ),
        })
    manifest = tmp_path / "render.json"
    manifest.write_text(json.dumps({
        "host": "unreal",
        "width": 320, "height": 180,
        "frames": len(records),
        "bound_surfaces": 4,
        "camera_preset": "LaggedChase",
        "airframe": "synthetic bar",
        "frame_records": records,
    }), encoding="utf-8")
    return manifest


DOUBLET = [0.0, 0.0, 3.0, 8.0, 14.0, 17.0, 16.0, 12.0, 5.0, -2.0, -2.0, -2.0]


def named(checks):
    return {check.name: check for check in checks}


# -- the measurement itself ----------------------------------------------


@pytest.mark.parametrize("angle", [-25.0, -12.0, 0.0, 7.0, 20.0])
def test_silhouette_bank_recovers_a_known_angle(tmp_path, angle):
    path = write_png(tmp_path / "f.png", bar(angle))
    measured, fraction = silhouette_bank_degrees(path)
    assert measured == pytest.approx(angle, abs=0.6)
    assert 0.0 < fraction < 1.0


def test_silhouette_bank_sign_matches_a_right_wing_down_roll(tmp_path):
    """Positive roll is right wing down, and image rows increase downward.

    If this sign were flipped the correlation below would come out at -0.999
    and the gate would fail a correct render, so it is pinned rather than
    inferred.
    """
    measured, _ = silhouette_bank_degrees(write_png(tmp_path / "f.png", bar(15.0)))
    assert measured > 0.0


# -- the §1.5 regression -------------------------------------------------


def test_a_render_where_the_aircraft_never_moves_in_frame_fails(tmp_path):
    """The exact failure: the FDM rolls, the manifest says so, the pixels do not.

    This is what a camera welded to the airframe produces. Every telemetry
    number is right. The clause is still not met.
    """
    manifest = render_run(tmp_path, DOUBLET, image_angles=[0.0] * len(DOUBLET))
    checks = named(measure_frames(manifest))
    assert not checks["commanded roll is visible"].ok


def test_an_honest_render_passes(tmp_path):
    manifest = render_run(tmp_path, DOUBLET)
    checks = named(measure_frames(manifest))
    assert all(check.ok for check in checks.values()), {
        name: check.detail for name, check in checks.items() if not check.ok
    }


def test_a_render_that_rotates_the_wrong_way_fails(tmp_path):
    """The pixels move plenty. They do not show what the FDM did.

    A sign error anywhere between the FDM's roll and the actor's transform
    produces exactly this: a convincing, well-framed, fully-articulated clip of
    an aircraft banking the opposite way from the one that was flown. It clears
    every threshold about how *much* the image moves, so the correlation is
    what has to catch it.
    """
    manifest = render_run(tmp_path, DOUBLET,
                          image_angles=[-value for value in DOUBLET])
    checks = named(measure_frames(manifest))
    assert not checks["commanded roll is visible"].ok
    assert "r=-1.00000" in checks["commanded roll is visible"].detail


def test_a_camera_that_inherits_roll_fails_even_when_the_pixels_rotate(tmp_path):
    """A camera rolling with the aircraft can make the image rotate too.

    The image would then track the FDM perfectly and show nothing about the
    aircraft, because the whole world rotated with it. Camera roll is checked
    separately for that reason.
    """
    manifest = render_run(tmp_path, DOUBLET, camera_roll=8.0)
    checks = named(measure_frames(manifest))
    assert not checks["camera never inherits roll"].ok


def test_a_roll_too_small_to_see_is_not_visible(tmp_path):
    """Present in the data, below the threshold declared for "visible"."""
    tiny = [value * 0.1 for value in DOUBLET]
    manifest = render_run(tmp_path, tiny)
    checks = named(measure_frames(manifest))
    assert not checks["commanded roll is visible"].ok


# -- surfaces ------------------------------------------------------------


def test_a_surface_that_reads_a_deflection_and_moves_nothing_fails(tmp_path):
    """The animator's original state: it computed deflections and rotated nothing.

    ``surface_component_deg`` is measured off the scene component rather than
    recomputed from the JSBSim property, so a binding attached to no geometry
    reads a flat zero here however much the FDM deflected.
    """
    frozen = [{"aileron_l": 0.0, "aileron_r": 0.0, "elevator": 0.0, "rudder": 0.0}
              for _ in DOUBLET]
    manifest = render_run(tmp_path, DOUBLET, surfaces=frozen)
    checks = named(measure_frames(manifest))
    assert not checks["control surfaces articulate"].ok


def test_one_moving_surface_is_not_enough(tmp_path):
    """A single surface could be an artefact of one binding; two is a mechanism."""
    one = [{"aileron_l": roll * 0.3, "aileron_r": 0.0, "elevator": -5.55,
            "rudder": 0.0} for roll in DOUBLET]
    manifest = render_run(tmp_path, DOUBLET, surfaces=one)
    checks = named(measure_frames(manifest))
    assert not checks["control surfaces articulate"].ok
    assert ON_SCREEN["min_moving_surfaces"] >= 2


# -- frames that are not frames ------------------------------------------


def test_a_blank_frame_is_not_evidence(tmp_path):
    manifest = render_run(tmp_path, DOUBLET, blank={4})
    checks = named(measure_frames(manifest))
    assert not checks["frames show the aircraft"].ok
