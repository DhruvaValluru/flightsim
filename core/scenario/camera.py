"""The camera as a spec element: provenanced, validated, digest-relevant.

Phase 1 (Camera Control and Capture Geometry) promotes the camera out of
the render harness. Until now the camera was a render-time preset chosen
by the webapp (``-camera=`` / ``-chase=`` flags, hardcoded per airframe)
and computed per-frame in C++ -- it appeared in no spec, no digest and no
review table. A :class:`CameraSpec` is the same kind of object every
other condition already is: every field a frozen :class:`Quantity` with
its source recorded, serialized in canonical order, hashed into the spec
digest, refused by name when invalid.

The camera list rides on :class:`core.scenario.spec.ScenarioSpec` (spec
version 6). An EMPTY list is the documented default and must behave
EXACTLY like the pre-camera build: :func:`default_cameras` returns the
chase preset with the webapp's own per-airframe offsets, and the render
flow builds byte-identical commandlet arguments from it (pinned by
test).

Conventions, stated once
------------------------
* **Offsets** (``position_mode`` = ``"offset"``) are aircraft-relative
  metres in the heading-only frame, ``offset_forward_m`` /
  ``offset_right_m`` / ``offset_up_m`` -- exactly the UE director's
  FVector convention (X forward, so a chase camera is NEGATIVE forward)
  and exactly the ``-chase=`` flag's ``f:r:u`` triple. CHASE_OFFSETS
  below IS the webapp's measured table, moved here so the spec and the
  flag cannot drift apart.
* **Scene placement** (``position_mode`` = ``"scene"``) is local
  north/east metres about the spec origin -- the same projected frame
  every position-coupled card block (thermals, downburst, tornado) uses
  -- with altitude in metres MSL.
* **Geographic placement** (``position_mode`` = ``"geographic"``) is
  lat/lon degrees + altitude MSL, resolved through the scene's own CRS
  transformer by the pose solver (:mod:`core.capture.poses`).
* **Intrinsics** are canonical as focal length + physical sensor size
  (a stated field of view belongs in the focal quantity's ``detail``,
  converted by whoever states it); principal point is the image centre.
* **Keyframed moves** (``moves``) are data inside the camera record --
  serialized, digest-relevant -- each ``{"t_s": ..}`` plus any of the
  position triple for the camera's own mode, an aim point, or a focal
  length. Interpolation is the pose solver's job and is deterministic.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .fields import PLANNABLE_SOURCES, Quantity, Source

#: Same repo-root convention as core.capture.objects.GENERATED_DIR (not
#: imported from there: core.capture imports FROM core.scenario, so the
#: reverse import would be circular). Kept to the same path so the two
#: never drift.
_REPO = Path(__file__).resolve().parents[2]
_MESH_GENERATED_DIR = _REPO / "assets" / "generated"

#: The presets a camera may name. Five ported from the UE director
#: (chase/ground/wingman/tower/cockpit) plus "explicit": a stated
#: placement with no preset behaviour.
CAMERA_PRESETS = ("chase", "ground", "wingman", "tower", "cockpit",
                  "explicit")

POSITION_MODES = ("offset", "scene", "geographic")
AIM_MODES = ("aircraft", "point", "bearing")
#: Capture triggers a specification may name. "distance" and
#: "proximity" are the two halves of the phase's waypoint trigger --
#: by distance along the flown track, and by proximity to a stated
#: coordinate. (``proximity`` was implemented and tested in the
#: scheduler from the start but left out of this tuple, which made every
#: specification naming it refuse as an unknown trigger: the scheduler
#: half was unreachable from a spec, and its tests exercised a code path
#: no run could take.)
#: "continuous" captures EVERY recorded sample: the whole flight as a
#: sequence rather than a handful of stills, which is what "a
#: simulation from this angle" means. It is what a camera added from
#: the web page takes, so selecting a view and a clip length gives
#: that many seconds of that view.
TRIGGER_KINDS = ("continuous", "interval", "distance", "proximity",
                 "event")
EVENT_DIRECTIONS = ("above", "below", "rising", "falling")

#: Per-airframe chase offsets, forward:right:up metres in the heading
#: frame. THE webapp table (user preference 2026-08-14: tighter than the
#: showcase's), moved here verbatim; webapp.runs re-exports it as
#: WEBAPP_CHASE. These four are HAND-CALIBRATED against a real rendered
#: frame each (measured framing, not a formula) and always win when an
#: airframe is listed here.
CHASE_OFFSETS: Dict[str, tuple] = {
    "B747": (-110.0, 0.0, 12.0),
    "A320": (-95.0, 0.0, 10.0),
    "c172p": (-28.0, 0.0, 4.0),
    # The A-4 (12.2 m) used the B747 fallback, 110 m back, and rendered a
    # few pixels wide (the owner's first Matterhorn frame); scaled from the
    # c172p's framing by length -- which is exactly what
    # derive_chase_offset() below now does automatically for any OTHER
    # airframe, so this fix does not have to be hand-repeated per aircraft.
    "A4": (-42.0, 0.0, 6.0),
}
FALLBACK_CHASE_OFFSET = (-110.0, 0.0, 12.0)

#: The c172p is the calibration anchor for derive_chase_offset(): the
#: smallest airframe anyone framed by hand, so scaling its ratios up
#: undershoots less than scaling the B747's ratios down would.
_CHASE_CALIBRATION_AIRCRAFT = "c172p"
_CHASE_CALIBRATION_LENGTH_M = 8.28  # Cessna 172 overall length, metres
_CHASE_RATIO_BACK_PER_M = CHASE_OFFSETS[_CHASE_CALIBRATION_AIRCRAFT][0] / _CHASE_CALIBRATION_LENGTH_M
_CHASE_RATIO_UP_PER_M = CHASE_OFFSETS[_CHASE_CALIBRATION_AIRCRAFT][2] / _CHASE_CALIBRATION_LENGTH_M


def _measured_mesh_length_m(aircraft: str) -> Optional[float]:
    """The airframe's OWN measured mesh length (metres), from the mesh
    manifest the import pipeline writes (``assets_pipeline.convert.
    MeshExtents.to_manifest``, mesh manifest v3+ -- the same fix that
    corrected the Phase 1 aircraft-position offset). ``None`` when the
    aircraft has never been imported on this machine (nothing measured
    to derive a framing from, not a guess at zero) or the manifest
    predates the length field."""
    path = _MESH_GENERATED_DIR / str(aircraft) / "mesh_manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    length = data.get("mesh_length_m")
    return float(length) if isinstance(length, (int, float)) and length > 0 else None


def derive_chase_offset(aircraft: str) -> tuple:
    """Chase offset for an airframe with no hand-calibrated
    :data:`CHASE_OFFSETS` entry.

    Scales the c172p's measured framing by the airframe's OWN measured
    mesh length, the same scaling a human did by hand for the A-4
    before it got a table entry -- so a newly imported airframe is
    framed close to right on its FIRST render instead of silently
    inheriting the B747's -110 m chase distance (the bug that rendered
    the A-4 "a few pixels wide" the one time this fallback was hit).
    Falls back to :data:`FALLBACK_CHASE_OFFSET` only when the airframe
    has no mesh manifest yet -- nothing measured, so nothing to scale.
    """
    length_m = _measured_mesh_length_m(aircraft)
    if length_m is None:
        return FALLBACK_CHASE_OFFSET
    # _CHASE_RATIO_BACK_PER_M is already negative (c172p's forward offset
    # is -28.0 m): no second negation here.
    return (_CHASE_RATIO_BACK_PER_M * length_m, 0.0,
            _CHASE_RATIO_UP_PER_M * length_m)

#: The wingman formation slot the webapp measured: 180 m abeam clears
#: the tornado core's 150 m radius (the default 25 m sat INSIDE the
#: funnel -- run c33db2c326e0). Behind distance is the commandlet's own
#: abeam rule, -max(15, abeam * 0.25) = -45 m at 180 m abeam.
WINGMAN_OFFSET = (-45.0, 180.0, 0.0)

#: Cockpit-shoulder body-frame offset, the UE director's own figure
#: (forward, right, up metres; left seat).
SHOULDER_OFFSET = (-6.0, -0.5, 1.6)

#: World-anchored preset placements, local north/east metres about the
#: spec origin + height above the spec's terrain datum. Ported from the
#: UE director's ObserverLocationMetres (0, 1500, 30) and
#: TowerLocationMetres (-800, 900, 80) under the declared axis mapping
#: X -> east, Y -> north.
GROUND_OBSERVER_LOCAL = {"north_m": 1500.0, "east_m": 0.0, "up_m": 30.0}
TOWER_LOCAL = {"north_m": 900.0, "east_m": -800.0, "up_m": 80.0}

#: Documented default intrinsics: the render pipeline's 1280x720 clip
#: frame with a classic 35 mm lens on a 36 x 20.25 mm (16:9 full-frame
#: crop) sensor, so pixels are square. Horizontal FOV ~54.4 deg.
DEFAULT_FOCAL_MM = 35.0
DEFAULT_SENSOR_W_MM = 36.0
DEFAULT_SENSOR_H_MM = 20.25
DEFAULT_WIDTH_PX = 1280
DEFAULT_HEIGHT_PX = 720
DEFAULT_NEAR_M = 0.1
DEFAULT_FAR_M = 100_000.0

#: Default event refractory: one gust-driven roll excursion is one
#: capture, not a burst of ten at the telemetry rate.
DEFAULT_REFRACTORY_S = 2.0

#: Spec 8 (contracts §10, §12): the physical exposure triple per preset
#: -- (aperture f-number, shutter seconds, ISO). One daylight triple
#: (f/8, 1/500 s, ISO 100) is what the contracts state for every preset
#: today; the table is keyed per preset so the Look lane can
#: differentiate them without changing the field's shape. This package
#: carries and validates the triple; the EV100 mapping
#: (log2(N^2/t * 100/ISO)) and the engine's exposure are the Look lane's
#: and are NOT implemented here.
EXPOSURE_FIELDS = ("aperture_f", "shutter_s", "iso")
DEFAULT_EXPOSURE = (8.0, 1.0 / 500.0, 100.0)
EXPOSURE_DEFAULTS: Dict[str, tuple] = {preset: DEFAULT_EXPOSURE
                                       for preset in CAMERA_PRESETS}

#: S1 (spec 9: INT-final's bump): two per-camera sensing
#: fields, each a provenanced Quantity NOT in FIELD_ORDER and
#: absent-canonical like ``exposure``: ``exposure_compensation_ev`` (EC,
#: stops; +1 halves the luminance a unit of the linear frame stands
#: for, core/capture/radiometry.py) and ``bands`` (the band file the
#: radiance stage mixes by, assets/sensor_bands/<name>.json, or None).
#: The defaults are omitted from the canonical camera, so every
#: committed example keeps its digest (pinned by test); the registry
#: cannot claim a list element (its sections are mappings), so both are
#: recorded through the capture manifest's per-camera ``sensing`` block
#: with their own null tests (docs/SENSING.md).
SENSING_FIELDS = ("exposure_compensation_ev", "bands")
DEFAULT_EXPOSURE_COMPENSATION_EV = 0.0
DEFAULT_BANDS = None


def default_sensing_fields() -> Dict[str, Quantity]:
    """The two S1 camera fields at their documented defaults."""
    return {
        "exposure_compensation_ev": Quantity.default(
            DEFAULT_EXPOSURE_COMPENSATION_EV, "EV",
            frm="no exposure compensation: the manual EV100 as computed"),
        "bands": Quantity.default(
            DEFAULT_BANDS, frm="no band file stated: the three rendered channels as they are"),
    }


#: S2 (spec 9): the stereo rig and the ground-truth passes a camera
#: asks for, each a provenanced Quantity NOT in FIELD_ORDER and
#: absent-canonical like the S1 fields: ``stereo`` ({baseline_m, side}, or
#: None -- core/capture/stereo.py derives the right camera) and ``passes``
#: (a list of pass words, or None -- core/capture/passes.py). Addressed as
#: ``cameras[i].stereo`` / ``cameras[i].passes``; every committed example
#: states neither and keeps its digest (pinned by tests/test_stereo.py).
PASS_FIELDS = ("stereo", "passes")


def default_pass_fields() -> Dict[str, Quantity]:
    """The two S2 camera fields at their documented defaults."""
    return {
        "stereo": Quantity.default(None, frm="no stereo rig stated: one camera"),
        "passes": Quantity.default(None, frm="no ground-truth pass asked for"),
    }


#: S3 (spec 9): the IR proxy a camera asks for, ``cameras[i].ir`` =
#: {band, thermal_table} (core/capture/thermal.py: band LWIR or MWIR, the
#: table under assets/thermal/), or None -- a provenanced Quantity NOT in
#: FIELD_ORDER, absent-canonical like the S1 / S2 fields, so every committed
#: example keeps its digest (pinned by tests/test_thermal.py). Recorded
#: through the manifest's per-camera ``sensing.ir`` block.
IR_FIELD = "ir"


def default_ir_field() -> Quantity:
    """The S3 camera field at its documented default: no IR proxy."""
    return Quantity.default(None, frm="no IR proxy asked for: the visible frame only")


@dataclass
class ExposureSpec:
    """``cameras[].exposure``: aperture, shutter and ISO, each a
    provenanced :class:`Quantity`, addressable as
    ``cameras[0].exposure.aperture_f`` through the spec front door.

    Serialised like the randomisation block, not like the camera's
    other fields: an all-default exposure is OMITTED from the camera's
    canonical form, so a spec that states no exposure keeps the digest
    it had at spec 7 (the bump's one-spelling rule: absent IS the
    documented default).
    """

    aperture_f: Quantity
    shutter_s: Quantity
    iso: Quantity

    FIELD_ORDER = EXPOSURE_FIELDS

    def quantities(self):
        for name in self.FIELD_ORDER:
            yield name, getattr(self, name)

    def set(self, name: str, value: Any, frm: str = "edited by hand") -> None:
        current = self._field(name)
        setattr(self, name, Quantity(value=value, unit=current.unit,
                                     source=Source.USER, frm=frm,
                                     std=current.std,
                                     detail=dict(current.detail)))

    def plan(self, name: str, value: Any, frm: str) -> None:
        """Same doctrine as the camera's: a stated exposure field is
        never silently moved."""
        current = self._field(name)
        if current.source not in PLANNABLE_SOURCES:
            raise ValueError(
                f"plan() only moves defaulted/derived/model fields; camera "
                f"exposure.{name} is {current.source.value!r} -- a stated "
                f"value is never silently moved")
        setattr(self, name, Quantity(value=value, unit=current.unit,
                                     source=Source.DERIVED, frm=frm,
                                     std=current.std,
                                     detail=dict(current.detail)))

    def _field(self, name: str) -> Quantity:
        if name not in self.FIELD_ORDER:
            raise ValueError(f"{name!r} is not an exposure field")
        return getattr(self, name)

    def to_dict(self) -> Dict[str, Any]:
        return {name: q.to_dict() for name, q in self.quantities()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExposureSpec":
        if not isinstance(data, dict):
            raise ValueError("camera 'exposure' must be a mapping of "
                             "provenanced fields")
        kwargs = {}
        for name in cls.FIELD_ORDER:
            try:
                kwargs[name] = Quantity.from_dict(data[name])
            except KeyError as exc:
                raise ValueError(
                    f"camera exposure is missing required field "
                    f"{name}") from exc
        unknown = set(data) - set(cls.FIELD_ORDER)
        if unknown:
            raise ValueError(
                f"camera exposure carries unknown fields {sorted(unknown)}; "
                f"refusing to guess at their meaning")
        return cls(**kwargs)

    def is_default(self, preset: str = "chase") -> bool:
        """Field for field, source for source, the preset's documented
        default -- the spelling the canonical camera omits."""
        return self.to_dict() == self.defaulted(preset).to_dict()

    @classmethod
    def defaulted(cls, preset: str = "chase",
                  frm: str = "documented exposure default: daylight "
                             "f/8, 1/500 s, ISO 100") -> "ExposureSpec":
        aperture, shutter, iso = EXPOSURE_DEFAULTS.get(preset,
                                                       DEFAULT_EXPOSURE)
        d = Quantity.default
        return cls(aperture_f=d(float(aperture), "f-number", frm=frm),
                   shutter_s=d(float(shutter), "s", frm=frm),
                   iso=d(float(iso), "ISO", frm=frm))


@dataclass
class CameraSpec:
    """One camera: placement, aim, lens, output and capture schedule.

    Every field is a :class:`Quantity` so per-field provenance rides
    exactly as it does on the scenario spec: an edit is ``user``, a
    vocabulary mapping ``inferred``, a planner's move ``derived``, an
    untouched field ``default`` -- and a user-stated field is NEVER
    silently moved (:meth:`plan` refuses by name, same as the spec's).
    """

    camera_id: Quantity
    preset: Quantity
    position_mode: Quantity
    offset_forward_m: Quantity
    offset_right_m: Quantity
    offset_up_m: Quantity
    position_north_m: Quantity
    position_east_m: Quantity
    position_lat_deg: Quantity
    position_lon_deg: Quantity
    position_alt_m: Quantity
    aim_mode: Quantity
    aim_north_m: Quantity
    aim_east_m: Quantity
    aim_alt_m: Quantity
    aim_bearing_deg: Quantity
    aim_elevation_deg: Quantity
    focal_length_mm: Quantity
    sensor_width_mm: Quantity
    sensor_height_mm: Quantity
    width_px: Quantity
    height_px: Quantity
    near_m: Quantity
    far_m: Quantity
    trigger: Quantity
    capture_count: Quantity
    period_s: Quantity
    distance_m: Quantity
    event_channel: Quantity
    event_threshold: Quantity
    event_direction: Quantity
    refractory_s: Quantity
    #: Sensor-model profile name (core.capture.profile); the ideal
    #: pinhole by default, so a spec that names none is unchanged.
    profile: Quantity

    #: Keyframed moves: list of dicts, each {"t_s": float} plus any of
    #: the mode's position keys, aim keys, or "focal_length_mm". Data,
    #: not Quantitys: the WHOLE list is one recorded decision, carried
    #: verbatim and digest-relevant.
    moves: List[Dict[str, Any]] = dc_field(default_factory=list)

    #: Spec 8: the physical exposure triple (aperture_f, shutter_s,
    #: iso), a provenanced block. The preset's documented default is
    #: omitted from to_dict, so a camera that states none serialises
    #: exactly as it did at spec 7. NOT in FIELD_ORDER: it is a nested
    #: block, addressed as ``cameras[i].exposure.<field>``.
    exposure: "ExposureSpec" = dc_field(default_factory=ExposureSpec.defaulted)

    #: S1: exposure compensation (stops) and the band file, each a
    #: Quantity, absent-canonical (see SENSING_FIELDS); addressed as
    #: ``cameras[i].exposure_compensation_ev`` / ``cameras[i].bands``.
    exposure_compensation_ev: Quantity = dc_field(
        default_factory=lambda: default_sensing_fields()["exposure_compensation_ev"])
    bands: Quantity = dc_field(default_factory=lambda: default_sensing_fields()["bands"])
    #: S2: the stereo rig and the passes (see PASS_FIELDS), absent-canonical.
    stereo: Quantity = dc_field(default_factory=lambda: default_pass_fields()["stereo"])
    passes: Quantity = dc_field(default_factory=lambda: default_pass_fields()["passes"])
    #: S3: the IR proxy request (see IR_FIELD), absent-canonical.
    ir: Quantity = dc_field(default_factory=default_ir_field)

    #: Canonical field order for serialisation and the rendered table.
    FIELD_ORDER = (
        "camera_id", "preset", "position_mode",
        "offset_forward_m", "offset_right_m", "offset_up_m",
        "position_north_m", "position_east_m",
        "position_lat_deg", "position_lon_deg", "position_alt_m",
        "aim_mode", "aim_north_m", "aim_east_m", "aim_alt_m",
        "aim_bearing_deg", "aim_elevation_deg",
        "focal_length_mm", "sensor_width_mm", "sensor_height_mm",
        "width_px", "height_px", "near_m", "far_m",
        "trigger", "capture_count", "period_s", "distance_m",
        "event_channel", "event_threshold", "event_direction",
        "refractory_s",
        # Phase 10: the sensor model applied to this camera's frames
        # (assets/camera_profiles/<name>.json). "ideal_pinhole" is the
        # documented default and exactly the previous behaviour.
        "profile",
    )

    # -- access ---------------------------------------------------------

    def quantities(self):
        """(name, Quantity) in canonical order."""
        for name in self.FIELD_ORDER:
            yield name, getattr(self, name)

    def set(self, name: str, value: Any, frm: str = "edited by hand") -> None:
        """Override a camera field, recording that a human did it."""
        current = getattr(self, name)
        setattr(self, name,
                Quantity(value=value, unit=current.unit, source=Source.USER,
                         frm=frm, std=current.std,
                         detail=dict(current.detail)))

    def plan(self, name: str, value: Any, frm: str) -> None:
        """Move a camera field the SYSTEM chose. Same doctrine as the
        spec's: only defaulted/derived/model fields move; a user-stated
        or inferred camera field is never silently moved -- refuse by
        name instead."""
        current = getattr(self, name)
        if current.source not in (Source.DEFAULT, Source.DERIVED,
                                  Source.MODEL):
            raise ValueError(
                f"plan() only moves defaulted/derived/model fields; camera "
                f"{str(self.camera_id.value)!r} field {name} is "
                f"{current.source.value!r} -- a stated value is never "
                f"silently moved")
        setattr(self, name,
                Quantity(value=value, unit=current.unit,
                         source=Source.DERIVED, frm=frm, std=current.std,
                         detail=dict(current.detail)))

    # -- serialisation --------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Canonical mapping: fields in FIELD_ORDER, then moves."""
        out: Dict[str, Any] = {}
        for name, q in self.quantities():
            out[name] = q.to_dict()
        # Always present, so the canonical form has one spelling of
        # "no moves" (the empty-list discipline the cameras list itself
        # follows on the spec).
        out["moves"] = [dict(m) for m in self.moves]
        # Spec 8: the exposure block appears only when it differs from
        # the preset's documented default -- absent IS the default, one
        # spelling, and every spec-7 camera keeps its digest.
        if not self.exposure.is_default(str(self.preset.value)):
            out["exposure"] = self.exposure.to_dict()
        # S1: the two sensing fields ride only when they differ from the
        # documented default -- absent IS the default, one spelling.
        defaults = default_sensing_fields()
        for name in SENSING_FIELDS:
            q = getattr(self, name)
            if q.to_dict() != defaults[name].to_dict():
                out[name] = q.to_dict()
        # S2: the stereo rig and the passes, the same absent-canonical rule.
        pass_defaults = default_pass_fields()
        for name in PASS_FIELDS:
            q = getattr(self, name)
            if q.to_dict() != pass_defaults[name].to_dict():
                out[name] = q.to_dict()
        # S3: the IR request, the same absent-canonical rule.
        if self.ir_stated():
            out[IR_FIELD] = self.ir.to_dict()
        return out

    def ir_stated(self) -> bool:
        """Whether the S3 IR field differs from its default (no IR)."""
        return self.ir.to_dict() != default_ir_field().to_dict()

    def sensing_stated(self) -> bool:
        """Whether either S1 field differs from its default."""
        defaults = default_sensing_fields()
        return any(getattr(self, name).to_dict() != defaults[name].to_dict()
                   for name in SENSING_FIELDS)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CameraSpec":
        kwargs = {}
        for name in cls.FIELD_ORDER:
            try:
                kwargs[name] = Quantity.from_dict(data[name])
            except KeyError as exc:
                raise ValueError(
                    f"camera is missing required field {name}") from exc
        sensing = default_sensing_fields()
        for name in SENSING_FIELDS:
            if data.get(name) is not None:
                sensing[name] = Quantity.from_dict(data[name])
        kwargs.update(sensing)
        # S2: the stereo rig and the passes, absent = the default.
        pass_fields = default_pass_fields()
        for name in PASS_FIELDS:
            if data.get(name) is not None:
                pass_fields[name] = Quantity.from_dict(data[name])
        kwargs.update(pass_fields)
        # S3: the IR request, absent = no IR.
        kwargs[IR_FIELD] = (Quantity.from_dict(data[IR_FIELD]) if data.get(IR_FIELD) is not None
                            else default_ir_field())
        unknown = (set(data) - set(cls.FIELD_ORDER) - {"moves", "exposure"} - set(SENSING_FIELDS)
                   - set(PASS_FIELDS) - {IR_FIELD})
        if unknown:
            raise ValueError(
                f"camera carries unknown fields {sorted(unknown)}; "
                f"refusing to guess at their meaning")
        moves = data.get("moves", [])
        if not isinstance(moves, list) or not all(
                isinstance(m, dict) for m in moves):
            raise ValueError("camera 'moves' must be a list of keyframe "
                             "mappings")
        exposure_data = data.get("exposure")
        exposure = (ExposureSpec.defaulted(str(kwargs["preset"].value))
                    if exposure_data is None
                    else ExposureSpec.from_dict(exposure_data))
        return cls(moves=[dict(m) for m in moves], exposure=exposure,
                   **kwargs)

    # -- construction ---------------------------------------------------

    @classmethod
    def defaulted(cls, camera_id: str = "camera0", preset: str = "chase",
                  aircraft: Optional[str] = None,
                  terrain_elevation_m: float = 0.0,
                  frm: str = "documented camera default") -> "CameraSpec":
        """The documented default camera for a preset.

        Every field source ``default`` (the planners may move them; a
        later ``set()`` makes them the user's). Chase offsets come from
        the per-airframe table; the world-anchored presets take the
        ported UE placements above the spec's terrain datum.
        """
        d = Quantity.default
        chase_offset = CHASE_OFFSETS.get(aircraft or "")
        chase_derived = chase_offset is None
        if chase_derived:
            chase_offset = derive_chase_offset(aircraft or "")
        offset = {"chase": chase_offset,
                  "wingman": WINGMAN_OFFSET,
                  "cockpit": SHOULDER_OFFSET}.get(preset, (0.0, 0.0, 0.0))
        local = {"ground": GROUND_OBSERVER_LOCAL,
                 "tower": TOWER_LOCAL}.get(preset)
        mode = "scene" if local is not None else "offset"
        north = local["north_m"] if local else 0.0
        east = local["east_m"] if local else 0.0
        alt = (terrain_elevation_m + local["up_m"]) if local else 0.0
        if preset != "chase":
            offset_frm = frm
        elif chase_derived:
            offset_frm = ("chase offset derived from this airframe's own "
                           "measured mesh length (no calibrated table entry)")
        else:
            offset_frm = "per-airframe chase offset table"
        return cls(
            camera_id=d(camera_id, frm=frm),
            preset=d(preset, frm=frm),
            position_mode=d(mode, frm=frm),
            offset_forward_m=d(float(offset[0]), "m", frm=offset_frm),
            offset_right_m=d(float(offset[1]), "m", frm=offset_frm),
            offset_up_m=d(float(offset[2]), "m", frm=offset_frm),
            position_north_m=d(float(north), "m", frm=frm),
            position_east_m=d(float(east), "m", frm=frm),
            position_lat_deg=d(0.0, "deg", frm=frm),
            position_lon_deg=d(0.0, "deg", frm=frm),
            position_alt_m=d(float(alt), "m", frm=frm),
            aim_mode=d("aircraft", frm=frm),
            aim_north_m=d(0.0, "m", frm=frm),
            aim_east_m=d(0.0, "m", frm=frm),
            aim_alt_m=d(0.0, "m", frm=frm),
            aim_bearing_deg=d(0.0, "deg", frm=frm),
            aim_elevation_deg=d(0.0, "deg", frm=frm),
            focal_length_mm=d(DEFAULT_FOCAL_MM, "mm", frm=frm),
            sensor_width_mm=d(DEFAULT_SENSOR_W_MM, "mm", frm=frm),
            sensor_height_mm=d(DEFAULT_SENSOR_H_MM, "mm", frm=frm),
            width_px=d(DEFAULT_WIDTH_PX, "px", frm=frm),
            height_px=d(DEFAULT_HEIGHT_PX, "px", frm=frm),
            near_m=d(DEFAULT_NEAR_M, "m", frm=frm),
            far_m=d(DEFAULT_FAR_M, "m", frm=frm),
            trigger=d("interval", frm=frm),
            capture_count=d(0, "dimensionless",
                            frm="0 = no counted capture; the clip "
                                "convention (frames at the render fps)"),
            period_s=d(1.0, "s", frm=frm),
            distance_m=d(500.0, "m", frm=frm),
            event_channel=d("roll_deg", frm=frm),
            event_threshold=d(30.0, frm=frm),
            event_direction=d("above", frm=frm),
            refractory_s=d(DEFAULT_REFRACTORY_S, "s",
                           frm="one event is one capture"),
            profile=d("ideal_pinhole",
                      frm="the documented ideal pinhole; the engine's "
                          "frames are the sensor frames"),
            exposure=ExposureSpec.defaulted(preset),
        )

    # -- presentation ---------------------------------------------------

    def label(self) -> str:
        return (f"camera {self.camera_id.value} "
                f"({self.preset.value})")


def plan_full_capture(camera: "CameraSpec", frm: str) -> bool:
    """Plan CONTINUOUS capture for a camera that asked for no count.

    A camera nobody gave a count or a trigger to used to take the
    ``interval`` default: one frame per second. On a short clip that is
    three or four stills -- which is not a view of a flight, it is a
    contact sheet. Every path that builds a camera from a request that
    did not name a number should reach the same place the web page's
    picker does: every recorded sample, for as long as the clip lasts,
    ten frames per second of flight.

    Three things are left alone, and each of them matters:

    * a STATED count ("50 images") is a contract the ``continuous``
      trigger cannot honour -- it emits as many frames as there are
      samples -- so a camera carrying one keeps its interval trigger
      and this returns False rather than turning a count into a
      refusal at schedule time;
    * a MOVED ``period_s`` ("one every two seconds") is somebody asking
      for an interval capture by its rate instead of its count.
      ``continuous`` ignores the period entirely, so planning it over a
      stated one would drop a request silently -- the one outcome this
      repo does not allow. Only the untouched default period is
      overridden;
    * a stated TRIGGER is a stated field, so ``plan()`` refuses to move
      it. Only a defaulted/derived/model trigger is planned, which is
      why an edit in the review table still wins.

    Returns True when the trigger was moved.
    """
    if int(camera.capture_count.value or 0) > 0:
        return False
    if camera.period_s.source is not Source.DEFAULT:
        return False
    if camera.trigger.source not in (Source.DEFAULT, Source.DERIVED,
                                     Source.MODEL):
        return False
    camera.plan("trigger", "continuous", frm=frm)
    return True


#: Framing both aircraft: the default lens sees +-27.2 deg across and
#: +-15.5 deg up and down; the chase camera aims at the primary, so the
#: second aircraft must sit inside 75 % of those half-angles, plus a
#: margin for the airframes' own size.
_FRAME_TAN_H = math.tan(math.radians(0.75 * 27.2))
_FRAME_TAN_V = math.tan(math.radians(0.75 * 15.5))
_FRAME_MARGIN_M = 30.0
_FRAME_MAX_BACK_M = 3000.0


def frame_both_offset(base: tuple, ahead_m: float, right_m: float,
                      up_m: float) -> tuple:
    """The chase offset (forward, right, up) that keeps a second aircraft
    at (ahead, right, up) from the primary in view while the camera aims
    at the primary. Pulls the camera back until the sideways and
    vertical angles to the second aircraft fit inside the lens; never
    closer than ``base``, the single-aircraft framing."""
    back_h = (abs(right_m) + _FRAME_MARGIN_M) / _FRAME_TAN_H
    back_v = (abs(up_m) + _FRAME_MARGIN_M / 2.0) / _FRAME_TAN_V
    forward = min(base[0], ahead_m - max(back_h, back_v), -_FRAME_MARGIN_M)
    forward = max(forward, -_FRAME_MAX_BACK_M)
    up = base[2] + (abs(up_m) * 0.5 if up_m else 0.0) + 0.04 * (base[0] - forward)
    return (forward, base[1], up)


FRAMED_FOR_TRAFFIC = "framed to show both aircraft"


def frame_traffic(spec) -> int:
    """Re-plan every DEFAULT / DERIVED chase camera of a spec so the view
    shows every placed aircraft, or puts the single-aircraft framing back
    when none is left. A camera the user stated or edited keeps its
    numbers (plan() refuses a stated field); returns how many cameras
    moved."""
    placed = [e for e in spec.traffic if e.placed()]
    aircraft = str(spec.aircraft.value)
    base = CHASE_OFFSETS.get(aircraft) or derive_chase_offset(aircraft)
    moved = 0
    for camera in spec.cameras:
        if str(camera.preset.value) != "chase":
            continue
        fields = (camera.offset_forward_m, camera.offset_up_m)
        if any(q.source not in PLANNABLE_SOURCES for q in fields):
            continue
        offset = base
        for entry in placed:
            p = entry.placement()
            offset = frame_both_offset(offset, p["ahead_m"], p["right_m"],
                                       p["up_m"])
        if placed:
            frm = FRAMED_FOR_TRAFFIC
        elif any(q.frm == FRAMED_FOR_TRAFFIC for q in fields):
            frm = "per-airframe chase offset table"
        else:
            continue
        camera.plan("offset_forward_m", offset[0], frm=frm)
        camera.plan("offset_up_m", offset[2], frm=frm)
        moved += 1
    return moved


def default_cameras(spec) -> List["CameraSpec"]:
    """The documented default camera set for a camera-less spec.

    EXACTLY today's behaviour, as data: one lagged-chase camera with the
    webapp's per-airframe offset -- except a through-the-core tornado
    run, which is watched from the wingman slot (the chase camera would
    sit inside the funnel mesh; measured, run c33db2c326e0). The render
    flow builds its commandlet flags from this list, and a test pins the
    argument list byte-identical to the pre-camera build.
    """
    aircraft = str(spec.aircraft.value)
    terrain = float(spec.terrain_elevation.value)
    preset = "chase"
    if (str(spec.weather_event.value) == "tornado"
            and str(spec.weather_event.detail.get("aim")) == "core"):
        preset = "wingman"
    return [CameraSpec.defaulted(
        camera_id="camera0", preset=preset, aircraft=aircraft,
        terrain_elevation_m=terrain,
        frm="no camera stated; the documented default view")]
