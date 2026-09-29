"""The sensor model: what a real camera does to an ideal picture.

The engine renders through an ideal pinhole -- no distortion, a global
shutter, no noise, no fall-off -- which is exactly right for a label and
exactly wrong for a photograph. A camera profile
(``assets/camera_profiles/<name>.json``) says what one camera does, and
this module applies it as a DETERMINISTIC, SEEDED post-pass in Python
over the linear render, so the result is reproducible from the run's
provenance and checkable off-engine. Every profile cites its source; a
profile with no source refuses by name (``camera.profile``). The default
profile is the ideal pinhole, so a spec that names none is exactly the
previous behaviour.

What is modelled, and the stated basis of each part:

* **Lens distortion** -- Brown-Conrady (Brown 1966) in the OpenCV
  parameterisation: radial k1 k2 k3, tangential p1 p2, on normalised
  image coordinates. Forward: undistorted -> distorted (labels).
  Inverse: Newton iteration (image resampling, the verifier's
  undistortion).
* **Rolling shutter** -- a linear top-to-bottom readout of
  ``readout_s``; row r is exposed at t = readout_s * (r / H - 1/2)
  relative to the frame's nominal instant. Over that offset the camera
  turns by omega * t (its angular rate from the solved pose track), so
  the rows see a scene rotated by the inverse; translation over one
  readout is neglected (stated: at 20 ms and 140 m/s that is 2.8 m at
  ranges of hundreds, well under a pixel for every preset but a
  hypothetical wing camera).
* **Vignetting** -- the cos^4 law of natural fall-off, angle off axis
  from the intrinsics.
* **Exposure and noise** -- EMVA 1288's linear camera: the linear value
  L in [0, 1] is the full-well fraction at the profile's reference
  exposure; the actual exposure scales it by time and ISO; electrons
  are Poisson (shot noise) plus Gaussian read noise; the ADC quantises
  at ``bit_depth``. The RNG is seeded per (run seed, camera, frame), so
  the same run gives the same grain twice.
* **Colour** -- linear in, sRGB 8-bit PNG out. The linear input is the
  engine's EXR where a ``-linear`` pass wrote one, else the 8-bit sRGB
  PNG inverted through the sRGB transfer: a STATED approximation
  (already quantised, already tone-mapped) recorded in the output.

Labels follow the pixels: ``sensor_labels`` maps every pinhole label
pixel into the sensor frame (distortion, then rolling shutter, iterated
because the row decides the time), and the verifier undistorts them
with the manifest's own parameters and requires the pinhole labels
back.

S1 (gap S1/S2): four OPTIONAL blocks a profile may carry, each absent
from every shipped profile (their files and digests are unchanged,
pinned) and each refused by its own name when malformed:

* ``optics`` (``sensing.optics``; core/capture/optics.py) -- the
  diffraction x Gaussian PSF applied as one shift-invariant kernel;
* ``motion_blur`` (``sensing.motion_blur``; core/capture/blur.py) --
  the velocity-line integral over the exposure, skipped when the
  bundle says the engine accumulated (S4);
* ``radiometry`` (``sensing.radiometry``; core/capture/radiometry.py)
  -- the lens attenuation the calibration chain uses when no render
  read it back, and the working colour space;
* ``bands`` (``sensing.band``) -- the band file whose 3 x 3 weights the
  radiance stage mixes the channels by (identity in the shipped file).

The post-pass runs in ONE order, :data:`POST_PASS_ORDER`: radiance
(band weights) -> psf -> blur -> vignetting -> geometry (rolling
shutter + distortion) -> exposure -> noise -> adc. Radiance first
because the chain is linear in scene light; the PSF and the blur before
the geometric resampling because both are properties of the light
reaching the sensor plane, the resampling of where it lands; vignetting
on the ideal field as before; the sensor's own electronics last. A
stage whose block is absent is skipped and the frame passes through it
bit for bit (the null tests in tests/test_optics.py and
tests/test_blur.py measure that). NOT claimed: that the order matches
any particular camera's physics beyond the reasoning above (the PSF of
a distorting lens is field-dependent; one kernel is applied before the
distortion, stated).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
PROFILE_DIR = REPO / "assets" / "camera_profiles"
DEFAULT_PROFILE = "ideal_pinhole"
DISTORTION_MODELS = ("brown-conrady",)
NOISE_MODELS = ("none", "emva1288")
VIGNETTING_MODELS = ("none", "cos4")
#: Newton iterations for the inverse distortion; converges quadratically
#: from the distorted point for any lens this repo would call a lens.
UNDISTORT_ITERATIONS = 12
#: Rolling-shutter label fixed-point iterations (the row decides the
#: time decides the row).
ROLLING_ITERATIONS = 6
#: S1: the post-pass stages in the ONE order they run (see the module
#: docstring); pinned by tests/test_camera_profile.py and a guard.
POST_PASS_ORDER = ("radiance", "psf", "blur", "vignetting", "geometry",
                   "exposure", "noise", "adc")
#: S1: the optional profile blocks and the refusal name each carries.
OPTIONAL_BLOCKS = {"optics": "sensing.optics", "motion_blur": "sensing.motion_blur",
                   "radiometry": "sensing.radiometry", "bands": "sensing.band"}
#: The telemetry interval the blur's flow is measured over (the
#: recorder's 10 Hz); a profile's motion_blur block may state another.
DEFAULT_FLOW_DT_S = 0.1


class CameraProfileError(Exception):
    constraint = "camera.profile"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"camera.profile: {message}")


@dataclass(frozen=True)
class CameraProfile:
    name: str
    basis: str
    source: str
    k1: float
    k2: float
    k3: float
    p1: float
    p2: float
    readout_s: float
    exposure_s: float
    reference_exposure_s: float
    iso: float
    base_iso: float
    noise_model: str
    full_well_e: float
    read_noise_e: float
    vignetting_model: str
    vignetting_strength: float
    bit_depth: int
    colour: Dict[str, str] = field(default_factory=dict)
    sha256: str = ""
    #: S1: the optional blocks (None = absent, the shipped profiles' case).
    optics: Optional[Dict] = None
    motion_blur: Optional[Dict] = None
    radiometry: Optional[Dict] = None
    bands: Optional[Dict] = None

    @property
    def is_ideal(self) -> bool:
        """No stage moves a pixel: the pinhole, and none of the S1 blocks
        that would (a radiometry block records, it does not move; identity
        band weights reproduce the frame)."""
        mixes = self.bands is not None and not _identity_weights(self.bands.get("weights"))
        return (self.k1 == self.k2 == self.k3 == self.p1 == self.p2 == 0.0
                and self.readout_s == 0.0 and self.noise_model == "none"
                and self.vignetting_model == "none"
                and self.gain == 1.0
                and self.optics is None and self.motion_blur is None and not mixes)

    @property
    def gain(self) -> float:
        """Exposure scale relative to the profile's reference."""
        return ((self.exposure_s / self.reference_exposure_s)
                * (self.iso / self.base_iso))

    def to_dict(self) -> Dict:
        out = {
            "name": self.name, "basis": self.basis, "source": self.source,
            "distortion": {"model": "brown-conrady", "k1": self.k1,
                           "k2": self.k2, "k3": self.k3, "p1": self.p1,
                           "p2": self.p2},
            "rolling_shutter": {"readout_s": self.readout_s,
                                "direction": "top-to-bottom"},
            "exposure": {"time_s": self.exposure_s,
                         "reference_time_s": self.reference_exposure_s,
                         "iso": self.iso, "base_iso": self.base_iso,
                         "gain": self.gain},
            "noise": {"model": self.noise_model,
                      "full_well_e": self.full_well_e,
                      "read_noise_e": self.read_noise_e},
            "vignetting": {"model": self.vignetting_model,
                           "strength": self.vignetting_strength},
            "colour": dict(self.colour),
            "bit_depth": self.bit_depth,
            "sha256": self.sha256,
        }
        # S1: absent-canonical -- a block rides only when the profile
        # states it, so every shipped profile's dict is unchanged.
        for key in OPTIONAL_BLOCKS:
            block = getattr(self, key)
            if block is not None:
                out[key] = dict(block)
        return out

    def stages(self) -> Tuple[str, ...]:
        """The post-pass stages this profile actually runs, in
        :data:`POST_PASS_ORDER`: the ones whose block or parameter is
        present (the geometry stage when any distortion or readout is)."""
        active = {
            "radiance": self.bands is not None,
            "psf": self.optics is not None,
            "blur": self.motion_blur is not None,
            "vignetting": self.vignetting_model != "none",
            "geometry": bool(self.k1 or self.k2 or self.k3 or self.p1 or self.p2
                             or self.readout_s > 0.0),
            "exposure": self.gain != 1.0,
            "noise": self.noise_model != "none",
            "adc": True,
        }
        return tuple(stage for stage in POST_PASS_ORDER if active[stage])


def _identity_weights(weights) -> bool:
    try:
        return all(float(weights[i][j]) == (1.0 if i == j else 0.0) for i in range(3) for j in range(3))
    except (TypeError, IndexError, ValueError, KeyError):
        return False


def _optional_blocks(data: Dict, name: str) -> Dict[str, Optional[Dict]]:
    """S1: the four optional blocks of a profile file, each shape-checked
    by its own module and refused by its own name (sensing.optics,
    sensing.motion_blur, sensing.radiometry, sensing.band); a block that
    is not a mapping refuses camera.profile."""
    from .blur import check_motion_blur_block
    from .optics import check_optics_block
    from .radiometry import RadiometryError, REFUSAL_BAND, REFUSAL_RADIOMETRY, check_lens_attenuation, load_bands

    out: Dict[str, Optional[Dict]] = {key: None for key in OPTIONAL_BLOCKS}
    for key in OPTIONAL_BLOCKS:
        block = data.get(key)
        if block is None:
            continue
        if not isinstance(block, dict):
            raise CameraProfileError(f"profile {name!r}: {key} must be a mapping, not {block!r}")
        if key == "optics":
            out[key] = check_optics_block(block)
        elif key == "motion_blur":
            out[key] = check_motion_blur_block(block)
        elif key == "radiometry":
            unknown = sorted(set(block) - {"lens_attenuation", "working_colour_space"})
            if unknown:
                raise RadiometryError(REFUSAL_RADIOMETRY,
                                      f"profile {name!r}: the radiometry block carries unknown keys {unknown}")
            attenuation = block.get("lens_attenuation")
            out[key] = {"lens_attenuation": (None if attenuation is None
                                             else check_lens_attenuation(attenuation)),
                        "working_colour_space": (None if block.get("working_colour_space") is None
                                                 else str(block["working_colour_space"]))}
        elif key == "bands":
            band_name = block.get("name")
            if not isinstance(band_name, str) or not band_name.strip():
                raise RadiometryError(REFUSAL_BAND,
                                      f"profile {name!r}: the bands block names no band file")
            table = load_bands(band_name)
            out[key] = {"name": table.name, "sha256": table.sha256,
                        "weights": [list(r) for r in table.weights], "proxy": True}
    return out


def available_profiles(profile_dir: Optional[Path] = None) -> List[str]:
    directory = Path(profile_dir or PROFILE_DIR)
    return sorted(p.stem for p in directory.glob("*.json"))


def load_profile(name: str, profile_dir: Optional[Path] = None) -> CameraProfile:
    """A profile by name, or a named ``camera.profile`` refusal."""
    directory = Path(profile_dir or PROFILE_DIR)
    path = directory / f"{name}.json"
    if not path.is_file():
        raise CameraProfileError(
            f"no camera profile {name!r} in {directory} (available: "
            f"{', '.join(available_profiles(directory)) or 'none'})")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CameraProfileError(f"profile {name!r} unreadable: {exc}") from exc
    if not str(data.get("source", "")).strip():
        raise CameraProfileError(
            f"profile {name!r} cites no source; a sensor model with no "
            f"stated provenance is a guess dressed as a camera")
    if data.get("name") != name:
        raise CameraProfileError(
            f"profile file {path.name} names itself {data.get('name')!r}")
    dist = data.get("distortion") or {}
    if dist.get("model") not in DISTORTION_MODELS:
        raise CameraProfileError(
            f"profile {name!r}: distortion model {dist.get('model')!r} is "
            f"not modelled ({DISTORTION_MODELS})")
    noise = data.get("noise") or {}
    if noise.get("model") not in NOISE_MODELS:
        raise CameraProfileError(
            f"profile {name!r}: noise model {noise.get('model')!r} is not "
            f"modelled ({NOISE_MODELS})")
    vign = data.get("vignetting") or {}
    if vign.get("model") not in VIGNETTING_MODELS:
        raise CameraProfileError(
            f"profile {name!r}: vignetting model {vign.get('model')!r} is "
            f"not modelled ({VIGNETTING_MODELS})")
    rolling = data.get("rolling_shutter") or {}
    exposure = data.get("exposure") or {}
    optional = _optional_blocks(data, name)
    try:
        profile = CameraProfile(
            name=name, basis=str(data.get("basis", "stated")),
            source=str(data["source"]),
            k1=float(dist.get("k1", 0.0)), k2=float(dist.get("k2", 0.0)),
            k3=float(dist.get("k3", 0.0)), p1=float(dist.get("p1", 0.0)),
            p2=float(dist.get("p2", 0.0)),
            readout_s=float(rolling.get("readout_s", 0.0)),
            exposure_s=float(exposure.get("time_s", 1.0)),
            reference_exposure_s=float(exposure.get("reference_time_s",
                                                    exposure.get("time_s", 1.0))),
            iso=float(exposure.get("iso", 100.0)),
            base_iso=float(exposure.get("base_iso", 100.0)),
            noise_model=str(noise["model"]),
            full_well_e=float(noise.get("full_well_e", 0.0)),
            read_noise_e=float(noise.get("read_noise_e", 0.0)),
            vignetting_model=str(vign["model"]),
            vignetting_strength=float(vign.get("strength", 1.0)),
            bit_depth=int(data.get("bit_depth", 8)),
            colour={k: str(v) for k, v in (data.get("colour") or {}).items()},
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            **optional,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CameraProfileError(f"profile {name!r} malformed: {exc}") from exc
    if profile.readout_s < 0.0 or profile.exposure_s <= 0.0 \
            or profile.reference_exposure_s <= 0.0 or profile.iso <= 0.0 \
            or profile.base_iso <= 0.0:
        raise CameraProfileError(
            f"profile {name!r}: readout must be >= 0 and exposure, "
            f"reference exposure, ISO and base ISO > 0")
    if profile.noise_model == "emva1288" and (profile.full_well_e <= 0.0
                                              or profile.read_noise_e < 0.0):
        raise CameraProfileError(
            f"profile {name!r}: emva1288 needs full_well_e > 0 and "
            f"read_noise_e >= 0")
    if not 1 <= profile.bit_depth <= 16:
        raise CameraProfileError(
            f"profile {name!r}: bit_depth {profile.bit_depth} outside 1..16")
    return profile


# -- distortion (points) -------------------------------------------------

def distort_normalised(profile: CameraProfile, x: float, y: float
                       ) -> Tuple[float, float]:
    """Brown-Conrady forward: undistorted normalised -> distorted."""
    r2 = x * x + y * y
    radial = 1.0 + profile.k1 * r2 + profile.k2 * r2 * r2 + profile.k3 * r2 * r2 * r2
    xd = x * radial + 2.0 * profile.p1 * x * y + profile.p2 * (r2 + 2.0 * x * x)
    yd = y * radial + profile.p1 * (r2 + 2.0 * y * y) + 2.0 * profile.p2 * x * y
    return xd, yd


def undistort_normalised(profile: CameraProfile, xd: float, yd: float
                         ) -> Tuple[float, float]:
    """Inverse by Newton iteration on the 2x2 Jacobian."""
    x, y = xd, yd
    for _ in range(UNDISTORT_ITERATIONS):
        fx_, fy_ = distort_normalised(profile, x, y)
        ex, ey = fx_ - xd, fy_ - yd
        if abs(ex) < 1e-13 and abs(ey) < 1e-13:
            break
        # Numerical Jacobian (analytic is available but this is exact
        # enough at 1e-7 and cannot drift from the forward model).
        h = 1e-7
        fxx, fyx = distort_normalised(profile, x + h, y)
        fxy, fyy = distort_normalised(profile, x, y + h)
        j11, j21 = (fxx - fx_) / h, (fyx - fy_) / h
        j12, j22 = (fxy - fx_) / h, (fyy - fy_) / h
        det = j11 * j22 - j12 * j21
        if abs(det) < 1e-14:
            break
        dx = (j22 * ex - j12 * ey) / det
        dy = (-j21 * ex + j11 * ey) / det
        x, y = x - dx, y - dy
    return x, y


def pixel_to_normalised(record: Dict, u: float, v: float) -> Tuple[float, float]:
    cx, cy = record["principal_point_px"]
    return (u - cx) / float(record["fx_px"]), (v - cy) / float(record["fy_px"])


def normalised_to_pixel(record: Dict, x: float, y: float) -> Tuple[float, float]:
    cx, cy = record["principal_point_px"]
    return cx + float(record["fx_px"]) * x, cy + float(record["fy_px"]) * y


# -- rolling shutter ------------------------------------------------------

def row_time_s(profile: CameraProfile, v: float, height: float) -> float:
    """Exposure instant of image row v relative to the frame's nominal
    instant: a linear top-to-bottom readout centred on the frame."""
    if profile.readout_s <= 0.0:
        return 0.0
    return profile.readout_s * (v / height - 0.5)


def _rotate_small(direction: Sequence[float], omega: Sequence[float],
                  t: float) -> Tuple[float, float, float]:
    """Rotate a camera-frame direction by the camera's motion over t:
    the scene, seen from the camera, turns by -omega*t (Rodrigues)."""
    wx, wy, wz = (-omega[0] * t, -omega[1] * t, -omega[2] * t)
    angle = math.sqrt(wx * wx + wy * wy + wz * wz)
    if angle < 1e-15:
        return tuple(direction)
    kx, ky, kz = wx / angle, wy / angle, wz / angle
    dx, dy, dz = direction
    c, s = math.cos(angle), math.sin(angle)
    dot = kx * dx + ky * dy + kz * dz
    cross = (ky * dz - kz * dy, kz * dx - kx * dz, kx * dy - ky * dx)
    return (dx * c + cross[0] * s + kx * dot * (1.0 - c),
            dy * c + cross[1] * s + ky * dot * (1.0 - c),
            dz * c + cross[2] * s + kz * dot * (1.0 - c))


def sensor_pixel(profile: CameraProfile, record: Dict, camera_xyz: Sequence[float],
                 omega: Sequence[float]) -> Optional[Tuple[float, float]]:
    """Where a camera-frame point lands on THIS sensor: distortion, then
    the rolling-shutter row/time fixed point. None behind the camera."""
    if camera_xyz[2] <= 0.0:
        return None
    height = float(record["height_px"])

    def project(direction):
        if direction[2] <= 0.0:
            return None
        x, y = direction[0] / direction[2], direction[1] / direction[2]
        xd, yd = distort_normalised(profile, x, y)
        return normalised_to_pixel(record, xd, yd)

    pixel = project(camera_xyz)
    if pixel is None or profile.readout_s <= 0.0:
        return pixel
    for _ in range(ROLLING_ITERATIONS):
        t = row_time_s(profile, pixel[1], height)
        moved = _rotate_small(camera_xyz, omega, t)
        nxt = project(moved)
        if nxt is None:
            return None
        if abs(nxt[0] - pixel[0]) < 1e-9 and abs(nxt[1] - pixel[1]) < 1e-9:
            return nxt
        pixel = nxt
    return pixel


def pinhole_pixel_from_sensor(profile: CameraProfile, record: Dict,
                              u_s: float, v_s: float, depth_m: float,
                              omega: Sequence[float]) -> Tuple[float, float]:
    """The verifier's inverse: undo the rolling shutter at this row and
    the distortion, back to the ideal pinhole pixel."""
    height = float(record["height_px"])
    xd, yd = pixel_to_normalised(record, u_s, v_s)
    x, y = undistort_normalised(profile, xd, yd)
    if profile.readout_s <= 0.0:
        return normalised_to_pixel(record, x, y)
    # The row's instant, then rotate the direction BACK by the camera's
    # motion over it (the inverse of _rotate_small's rotation).
    t = row_time_s(profile, v_s, height)
    direction = (x * depth_m, y * depth_m, depth_m)
    back = _rotate_small(direction, tuple(-w for w in omega), t)
    return normalised_to_pixel(record, back[0] / back[2], back[1] / back[2])


def sensor_labels(profile: CameraProfile, record: Dict, labels: Dict,
                  omega: Sequence[float]) -> Dict:
    """The pinhole labels mapped onto this sensor: keypoints and the 3-D
    box's corners, as sensor pixels, plus the sensor-frame 2-D box."""
    width, height = float(record["width_px"]), float(record["height_px"])
    out: Dict = {"keypoints": {}, "corners_px": [], "bbox_2d": None,
                 "bbox_2d_unclipped": None}
    for name, kp in labels.get("keypoints", {}).items():
        pixel = sensor_pixel(profile, record, kp["camera_xyz_m"], omega)
        out["keypoints"][name] = {
            "u": pixel[0] if pixel else None,
            "v": pixel[1] if pixel else None,
            "in_frame": bool(pixel and 0.0 <= pixel[0] <= width
                             and 0.0 <= pixel[1] <= height)}
    corners = [sensor_pixel(profile, record, c, omega)
               for c in labels.get("bbox_3d_camera", {}).get("corners_m", [])]
    if corners and all(c is not None for c in corners):
        out["corners_px"] = [list(c) for c in corners]
        us = [c[0] for c in corners]
        vs = [c[1] for c in corners]
        box = (min(us), min(vs), max(us), max(vs))
        out["bbox_2d_unclipped"] = list(box)
        clipped = (max(box[0], 0.0), max(box[1], 0.0),
                   min(box[2], width), min(box[3], height))
        if clipped[2] > clipped[0] and clipped[3] > clipped[1]:
            out["bbox_2d"] = list(clipped)
    return out


# -- images -----------------------------------------------------------------

def srgb_to_linear(c):
    import numpy as np

    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    import numpy as np

    c = np.clip(np.asarray(c, dtype=np.float64), 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1.0 / 2.4) - 0.055)


def frame_seed(run_seed: int, camera_id: str, index: int) -> int:
    """One RNG seed per frame, from the run's own seed: the same run
    gives the same grain twice, and no two frames share a stream."""
    digest = hashlib.sha256(f"{run_seed}:{camera_id}:{index}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def apply_profile(linear_rgb, profile: CameraProfile, record: Dict,
                  omega: Sequence[float], seed: int, **sensing):
    """The post-pass over one LINEAR frame (H x W x 3 floats in [0, 1])
    in :data:`POST_PASS_ORDER`: radiance (band weights), PSF, motion
    blur, vignetting, then the geometric resampling (rolling shutter and
    distortion, one bilinear sample per output pixel), then exposure,
    shot and read noise, and the ADC. Returns linear floats in [0, 1];
    encode with :func:`linear_to_srgb` to write. ``sensing`` keywords
    (``flow``, ``exposure_s``, ``aperture_f``, ``engine_accumulation``)
    feed the S1 stages; see :func:`apply_profile_detailed` for the blocks
    those stages record."""
    return apply_profile_detailed(linear_rgb, profile, record, omega, seed, **sensing)[0]


def apply_profile_detailed(linear_rgb, profile: CameraProfile, record: Dict,
                           omega: Sequence[float], seed: int, flow=None,
                           exposure_s: Optional[float] = None,
                           aperture_f: Optional[float] = None,
                           engine_accumulation: Optional[Dict] = None):
    """:func:`apply_profile` plus the blocks: (image, {"stages": [...],
    "radiance": ..., "psf": ..., "blur": ...}) with each S1 block None
    when its stage did not run. ``flow`` is (fx, fy) or an H x W x 2
    field in pixels per the block's dt; ``exposure_s`` the shutter the
    blur integrates over (the profile's exposure when None);
    ``aperture_f`` the f-number the PSF takes when the optics block
    states none; ``engine_accumulation`` the bundle's accumulation block
    (k > 1) that makes the blur stage record rather than apply."""
    import numpy as np

    image = np.asarray(linear_rgb, dtype=np.float64)
    blocks: Dict[str, object] = {"stages": [], "radiance": None, "psf": None, "blur": None}
    for stage in POST_PASS_ORDER:
        image = _STAGES[stage](image, profile, record, omega, seed, blocks,
                               flow, exposure_s, aperture_f, engine_accumulation)
    return image, blocks


def _stage_radiance(image, profile, record, omega, seed, blocks, flow, exposure_s, aperture_f, acc):
    if profile.bands is None:
        return image
    from .radiometry import apply_band_weights, load_bands

    table = load_bands(str(profile.bands["name"]))
    out = apply_band_weights(image, table)
    blocks["stages"].append("radiance")
    blocks["radiance"] = {"bands": table.name, "sha256": table.sha256, "identity_weights": table.is_identity,
                          "weights": [list(r) for r in table.weights]}
    return out


def _stage_psf(image, profile, record, omega, seed, blocks, flow, exposure_s, aperture_f, acc):
    if profile.optics is None:
        return image
    from .optics import convolve, optics_block

    n_number = aperture_f if aperture_f is not None else profile.optics.get("f_number")
    if n_number is None:
        from .optics import OpticsError

        raise OpticsError("the optics block states no f-number and the camera's aperture was not given")
    psf, block = optics_block(profile.optics, record, n_number)
    blocks["stages"].append("psf")
    blocks["psf"] = block
    return convolve(image, psf)


def _stage_blur(image, profile, record, omega, seed, blocks, flow, exposure_s, aperture_f, acc):
    if profile.motion_blur is None:
        return image
    from .blur import engine_accumulation_block, velocity_line_blur

    shutter = float(profile.exposure_s if exposure_s is None else exposure_s)
    blocks["stages"].append("blur")
    if acc is not None:
        blocks["blur"] = engine_accumulation_block(acc, shutter)
        return image
    dt = float(profile.motion_blur.get("dt_s", DEFAULT_FLOW_DT_S))
    if flow is None:
        # No flow given: the camera's own rotation over dt moves the whole
        # image by (fx w_y dt, fy w_x dt) pixels (small angle; translation
        # neglected, as the rolling-shutter model states). A stated,
        # frame-wide flow -- not the scene's.
        flow = (float(record["fx_px"]) * float(omega[1]) * dt,
                float(record["fy_px"]) * float(omega[0]) * dt)
        source = "camera_angular_rate"
    else:
        source = None
    out, block = velocity_line_blur(image, flow, shutter, dt)
    if source is not None:
        block["flow_source"] = source
    blocks["blur"] = block
    return out


def _stage_vignetting(image, profile, record, omega, seed, blocks, flow, exposure_s, aperture_f, acc):
    import numpy as np

    # Vignetting on the IDEAL image (fall-off is a property of the lens
    # over the undistorted field angle).
    if profile.vignetting_model == "cos4":
        height, width = image.shape[0], image.shape[1]
        cx, cy = record["principal_point_px"]
        fx, fy = float(record["fx_px"]), float(record["fy_px"])
        ys, xs = np.mgrid[0:height, 0:width]
        xn = (xs + 0.5 - cx) / fx
        yn = (ys + 0.5 - cy) / fy
        cos_theta = 1.0 / np.sqrt(1.0 + xn * xn + yn * yn)
        image = image * ((cos_theta ** 4) ** profile.vignetting_strength)[..., None]
        blocks["stages"].append("vignetting")
    return image


def _stage_geometry(image, profile, record, omega, seed, blocks, flow, exposure_s, aperture_f, acc):
    import numpy as np

    geometric = (profile.k1 or profile.k2 or profile.k3 or profile.p1
                 or profile.p2 or profile.readout_s > 0.0)
    if not geometric:
        return image
    height, width = image.shape[0], image.shape[1]
    cx, cy = record["principal_point_px"]
    fx, fy = float(record["fx_px"]), float(record["fy_px"])
    # Geometry: for each OUTPUT (sensor) pixel find the source pixel in
    # the ideal image -- undistort, then unwind the rolling shutter.
    ys, xs = np.mgrid[0:height, 0:width]
    u_s = xs + 0.5
    v_s = ys + 0.5
    xd = (u_s - cx) / fx
    yd = (v_s - cy) / fy
    # Vectorised Newton for the inverse distortion.
    x, y = xd.copy(), yd.copy()
    for _ in range(UNDISTORT_ITERATIONS):
        r2 = x * x + y * y
        radial = 1.0 + profile.k1 * r2 + profile.k2 * r2 ** 2 + profile.k3 * r2 ** 3
        fxv = x * radial + 2.0 * profile.p1 * x * y + profile.p2 * (r2 + 2.0 * x * x)
        fyv = y * radial + profile.p1 * (r2 + 2.0 * y * y) + 2.0 * profile.p2 * x * y
        ex, ey = fxv - xd, fyv - yd
        h = 1e-7
        r2x = (x + h) ** 2 + y * y
        radx = 1.0 + profile.k1 * r2x + profile.k2 * r2x ** 2 + profile.k3 * r2x ** 3
        fxx = (x + h) * radx + 2.0 * profile.p1 * (x + h) * y + profile.p2 * (r2x + 2.0 * (x + h) ** 2)
        fyx = y * radx + profile.p1 * (r2x + 2.0 * y * y) + 2.0 * profile.p2 * (x + h) * y
        r2y = x * x + (y + h) ** 2
        rady = 1.0 + profile.k1 * r2y + profile.k2 * r2y ** 2 + profile.k3 * r2y ** 3
        fxy = x * rady + 2.0 * profile.p1 * x * (y + h) + profile.p2 * (r2y + 2.0 * x * x)
        fyy = (y + h) * rady + profile.p1 * (r2y + 2.0 * (y + h) ** 2) + 2.0 * profile.p2 * x * (y + h)
        j11, j21 = (fxx - fxv) / h, (fyx - fyv) / h
        j12, j22 = (fxy - fxv) / h, (fyy - fyv) / h
        det = j11 * j22 - j12 * j21
        det = np.where(np.abs(det) < 1e-14, 1e-14, det)
        x = x - (j22 * ex - j12 * ey) / det
        y = y - (-j21 * ex + j11 * ey) / det
    if profile.readout_s > 0.0:
        # Each row saw the scene rotated by -omega*t(row); the source
        # direction in the ideal frame is that rotation undone.
        t = profile.readout_s * (v_s / height - 0.5)
        wx, wy, wz = (float(w) for w in omega)
        dirs = np.stack([x, y, np.ones_like(x)], axis=-1)
        # Rodrigues with a per-pixel angle: small-angle exact form.
        ang = np.sqrt(wx * wx + wy * wy + wz * wz) * np.abs(t)
        if float(np.max(ang)) > 0.0:
            kx, ky, kz = (wx, wy, wz) / np.sqrt(wx * wx + wy * wy + wz * wz)
            theta = np.sqrt(wx * wx + wy * wy + wz * wz) * t   # signed
            c, s = np.cos(theta)[..., None], np.sin(theta)[..., None]
            k = np.array([kx, ky, kz])
            dot = (dirs @ k)[..., None]
            cross = np.cross(np.broadcast_to(k, dirs.shape), dirs)
            dirs = dirs * c + cross * s + k * dot * (1.0 - c)
        x = dirs[..., 0] / dirs[..., 2]
        y = dirs[..., 1] / dirs[..., 2]
    src_u = cx + fx * x - 0.5
    src_v = cy + fy * y - 0.5
    blocks["stages"].append("geometry")
    return _bilinear(image, src_u, src_v)


def _stage_exposure(image, profile, record, omega, seed, blocks, flow, exposure_s, aperture_f, acc):
    if profile.gain == 1.0:
        return image
    blocks["stages"].append("exposure")
    return image * profile.gain


def _stage_noise(image, profile, record, omega, seed, blocks, flow, exposure_s, aperture_f, acc):
    import numpy as np

    # EMVA 1288 shot + read noise in electrons.
    if profile.noise_model == "emva1288":
        rng = np.random.default_rng(seed)
        electrons = np.clip(image, 0.0, None) * profile.full_well_e
        electrons = rng.poisson(electrons).astype(np.float64)
        electrons += rng.normal(0.0, profile.read_noise_e, size=electrons.shape)
        image = electrons / profile.full_well_e
        blocks["stages"].append("noise")
    return image


def _stage_adc(image, profile, record, omega, seed, blocks, flow, exposure_s, aperture_f, acc):
    import numpy as np

    levels = float(2 ** profile.bit_depth - 1)
    blocks["stages"].append("adc")
    return np.round(np.clip(image, 0.0, 1.0) * levels) / levels


#: The stage functions by name; :func:`apply_profile_detailed` walks
#: POST_PASS_ORDER, so the order is the tuple's and nothing else's.
_STAGES = {
    "radiance": _stage_radiance, "psf": _stage_psf, "blur": _stage_blur,
    "vignetting": _stage_vignetting, "geometry": _stage_geometry,
    "exposure": _stage_exposure, "noise": _stage_noise, "adc": _stage_adc,
}


def _bilinear(image, u, v):
    """Sample image (H x W x C) at float pixel coords; outside is black
    (the sensor sees what the ideal frame did not render as nothing)."""
    import numpy as np

    height, width = image.shape[0], image.shape[1]
    u0 = np.floor(u).astype(int)
    v0 = np.floor(v).astype(int)
    du = (u - u0)[..., None]
    dv = (v - v0)[..., None]
    out = np.zeros_like(image)

    def fetch(uu, vv):
        inside = (uu >= 0) & (uu < width) & (vv >= 0) & (vv < height)
        picked = np.zeros_like(image)
        picked[inside] = image[vv[inside], uu[inside]]
        return picked

    out = (fetch(u0, v0) * (1 - du) * (1 - dv) + fetch(u0 + 1, v0) * du * (1 - dv)
           + fetch(u0, v0 + 1) * (1 - du) * dv + fetch(u0 + 1, v0 + 1) * du * dv)
    return out


def read_linear_frame(frame_png: Path) -> Tuple["object", str]:
    """The frame as linear floats and a note saying how it got there:
    the engine's EXR beside it when readable, else the 8-bit sRGB PNG
    inverted through the sRGB transfer (a stated approximation)."""
    import numpy as np
    from PIL import Image

    exr = frame_png.with_name(frame_png.stem + "_linear.exr")
    if exr.is_file():
        try:                                     # pragma: no cover - optional
            import OpenEXR  # type: ignore
            import Imath  # type: ignore

            handle = OpenEXR.InputFile(str(exr))
            header = handle.header()
            window = header["dataWindow"]
            width = window.max.x - window.min.x + 1
            height = window.max.y - window.min.y + 1
            kind = Imath.PixelType(Imath.PixelType.FLOAT)
            channels = [np.frombuffer(handle.channel(c, kind), dtype=np.float32)
                        .reshape(height, width) for c in ("R", "G", "B")]
            return np.stack(channels, axis=-1).astype(np.float64), \
                "engine linear EXR"
        except Exception:
            pass
    with Image.open(frame_png) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.float64) / 255.0
    return srgb_to_linear(rgb), \
        "8-bit sRGB PNG inverted through the sRGB transfer (stated approximation)"


def apply_profile_to_run(run_dir, manifest: Dict, run_seed: int) -> Dict:
    """The post-pass over every rendered frame the manifest names, for
    every camera whose profile is not the ideal one. Writes
    ``frame_NNNN_sensor.png`` beside each frame and a per-camera
    ``sensor.json`` naming the files, the profile, the seed and the
    linear source. Returns {camera_id: n_written}. Frames the renderer
    never wrote are skipped -- the manifest's own labels already say
    what they would have been."""
    from PIL import Image
    import numpy as np

    run_dir = Path(run_dir)
    profiles = {c["camera_id"]: c.get("profile") for c in manifest.get("cameras", [])}
    exposures = {c["camera_id"]: _camera_exposure(c) for c in manifest.get("cameras", [])}
    written: Dict[str, int] = {}
    per_camera: Dict[str, Dict] = {}
    for record in manifest.get("frames", []):
        camera = str(record["camera_id"])
        profile_name = (profiles.get(camera) or {}).get("name", DEFAULT_PROFILE)
        profile = load_profile(profile_name)
        if profile.is_ideal:
            continue
        frame = run_dir / str(record["file"])
        if not frame.is_file():
            continue
        sensor = record.get("sensor") or {}
        omega = sensor.get("angular_rate_rad_s") or [0.0, 0.0, 0.0]
        seed = frame_seed(run_seed, camera, int(record["index"]))
        linear, source_note = read_linear_frame(frame)
        # S1: the camera's own exposure triple feeds the PSF's f-number and
        # the blur's shutter; an engine flow pass (I6) feeds the blur's
        # flow field, an engine accumulation (S4) makes it record only.
        exposure = exposures.get(camera) or _camera_exposure({"preset": "chase"})
        aperture = exposure["aperture_f"]
        shutter = exposure["shutter_s"]
        flow = _frame_flow(frame, record) if profile.motion_blur is not None else None
        accumulation = _frame_accumulation(frame, record) if profile.motion_blur is not None else None
        out, blocks = apply_profile_detailed(
            linear, profile, record, omega, seed, flow=flow, exposure_s=shutter,
            aperture_f=aperture, engine_accumulation=accumulation)
        srgb = (np.round(linear_to_srgb(out) * 255.0)).astype(np.uint8)
        target = frame.with_name(frame.stem + "_sensor.png")
        Image.fromarray(srgb, mode="RGB").save(target)
        entry = per_camera.setdefault(camera, {
            "profile": profile.to_dict(), "frames": [], "linear_source": source_note,
            "post_pass_order": list(POST_PASS_ORDER)})
        item = {"frame": frame.name, "sensor": target.name,
                "seed": seed, "angular_rate_rad_s": list(omega)}
        if any(blocks[k] is not None for k in ("radiance", "psf", "blur")):
            item["sensing"] = {"stages": list(blocks["stages"]),
                               "radiance": blocks["radiance"], "psf": blocks["psf"],
                               "blur": blocks["blur"]}
        entry["frames"].append(item)
        written[camera] = written.get(camera, 0) + 1
    for camera, entry in per_camera.items():
        (run_dir / "frames" / camera / "sensor.json").write_text(
            json.dumps(entry, indent=1), encoding="utf-8")
    return written


def _camera_exposure(camera_block: Dict) -> Dict[str, float]:
    """The camera's exposure triple {aperture_f, shutter_s, iso} as plain
    numbers: the stated block when the manifest carries one, else the
    preset's documented default (an all-default exposure is omitted from
    the canonical camera, so absence IS the daylight triple)."""
    from .exposure import EXPOSURE_FIELDS, preset_default

    stated = ((camera_block.get("spec") or {}).get("exposure") or {})
    if all(name in stated for name in EXPOSURE_FIELDS):
        return {name: float(_quantity_value(stated[name])) for name in EXPOSURE_FIELDS}
    preset = str(camera_block.get("preset") or "chase")
    try:
        triple = preset_default(preset)
    except Exception:  # noqa: BLE001 -- an unknown preset word: the daylight triple
        triple = preset_default("chase")
    return dict(zip(EXPOSURE_FIELDS, (float(v) for v in triple)))


def _quantity_value(item):
    """A provenanced field's value out of a manifest camera spec, or None."""
    if isinstance(item, dict):
        return item.get("value")
    return item


def _frame_flow(frame: Path, record: Dict):
    """The engine's flow field for this frame (I6's frame_NNNN_flow.f32,
    float32 (dx, dy) pixels since the previous captured frame) when it
    exists and has the frame's size; None otherwise (the blur then takes
    the camera's own rotation)."""
    import numpy as np

    path = frame.with_name(frame.stem + "_flow.f32")
    if not path.is_file():
        return None
    width, height = int(record["width_px"]), int(record["height_px"])
    raw = np.fromfile(path, dtype="<f4")
    if raw.size != width * height * 2:
        return None
    return raw.reshape(height, width, 2).astype(np.float64)


def _frame_accumulation(frame: Path, record: Dict):
    """The bundle's accumulation block for this frame (render.json
    frame_records[].accumulation with k > 1, S4) or None."""
    from .blur import engine_accumulation_of

    path = frame.parent / "render.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    records = payload.get("frame_records")
    if not isinstance(records, list):
        return None
    for entry in records:
        if isinstance(entry, dict) and entry.get("frame") == frame.name:
            return engine_accumulation_of(entry)
    return None
