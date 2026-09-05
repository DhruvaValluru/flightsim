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

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from .fields import Quantity, Source

#: The presets a camera may name. Five ported from the UE director
#: (chase/ground/wingman/tower/cockpit) plus "explicit": a stated
#: placement with no preset behaviour.
CAMERA_PRESETS = ("chase", "ground", "wingman", "tower", "cockpit",
                  "explicit")

POSITION_MODES = ("offset", "scene", "geographic")
AIM_MODES = ("aircraft", "point", "bearing")
TRIGGER_KINDS = ("interval", "distance", "event")
EVENT_DIRECTIONS = ("above", "below", "rising", "falling")

#: Per-airframe chase offsets, forward:right:up metres in the heading
#: frame. THE webapp table (user preference 2026-08-14: tighter than the
#: showcase's), moved here verbatim; webapp.runs re-exports it as
#: WEBAPP_CHASE. The fallback for unlisted airframes is the B747's.
CHASE_OFFSETS: Dict[str, tuple] = {
    "B747": (-110.0, 0.0, 12.0),
    "A320": (-95.0, 0.0, 10.0),
    "c172p": (-28.0, 0.0, 4.0),
}
FALLBACK_CHASE_OFFSET = (-110.0, 0.0, 12.0)

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

    #: Keyframed moves: list of dicts, each {"t_s": float} plus any of
    #: the mode's position keys, aim keys, or "focal_length_mm". Data,
    #: not Quantitys: the WHOLE list is one recorded decision, carried
    #: verbatim and digest-relevant.
    moves: List[Dict[str, Any]] = dc_field(default_factory=list)
    #: The moves list's provenance -- the WHOLE list is one recorded
    #: decision, so it carries one source word (a Source value: "user"
    #: when a person wrote the keyframes, "derived" when a planner
    #: did, ...) and one note, exactly like every field's, and both are
    #: serialised beside the list (digest-relevant, as every source
    #: is). None means the spec that carried the moves recorded no
    #: source, and the table says so -- it never paints the list as
    #: anybody's word.
    moves_source: Optional[str] = None
    moves_from: Optional[str] = None

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

    def set_moves(self, moves: List[Dict[str, Any]], frm: str,
                  source: Source = Source.USER) -> None:
        """Replace the keyframed moves, recording who wrote them and
        why: the list is one decision with one provenance."""
        words = [s.value for s in Source]
        word = getattr(source, "value", source)
        if word not in words:
            raise ValueError(f"moves source must be one of {words}, "
                             f"not {source!r}")
        self.moves = [dict(m) for m in moves]
        self.moves_source = word
        self.moves_from = frm

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
        # A list of keyframes carries its provenance beside it (None
        # when the spec recorded none); an empty list has nothing to
        # have a source, so its canonical form stays the one spelling.
        if self.moves:
            out["moves_source"] = self.moves_source
            out["moves_from"] = self.moves_from
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CameraSpec":
        kwargs = {}
        for name in cls.FIELD_ORDER:
            try:
                kwargs[name] = Quantity.from_dict(data[name])
            except KeyError as exc:
                raise ValueError(
                    f"camera is missing required field {name}") from exc
        unknown = (set(data) - set(cls.FIELD_ORDER)
                   - {"moves", "moves_source", "moves_from"})
        if unknown:
            raise ValueError(
                f"camera carries unknown fields {sorted(unknown)}; "
                f"refusing to guess at their meaning")
        moves = data.get("moves", [])
        if not isinstance(moves, list) or not all(
                isinstance(m, dict) for m in moves):
            raise ValueError("camera 'moves' must be a list of keyframe "
                             "mappings")
        source = data.get("moves_source")
        if source is not None and source not in [s.value for s in Source]:
            raise ValueError(
                f"camera 'moves_source' must be one of "
                f"{[s.value for s in Source]} or absent, not {source!r}; "
                f"refusing to guess who wrote the keyframes")
        frm = data.get("moves_from")
        if frm is not None and not isinstance(frm, str):
            raise ValueError("camera 'moves_from' must be a string")
        return cls(moves=[dict(m) for m in moves], moves_source=source,
                   moves_from=frm, **kwargs)

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
        offset = {"chase": CHASE_OFFSETS.get(aircraft or "",
                                             FALLBACK_CHASE_OFFSET),
                  "wingman": WINGMAN_OFFSET,
                  "cockpit": SHOULDER_OFFSET}.get(preset, (0.0, 0.0, 0.0))
        local = {"ground": GROUND_OBSERVER_LOCAL,
                 "tower": TOWER_LOCAL}.get(preset)
        mode = "scene" if local is not None else "offset"
        north = local["north_m"] if local else 0.0
        east = local["east_m"] if local else 0.0
        alt = (terrain_elevation_m + local["up_m"]) if local else 0.0
        offset_frm = (f"per-airframe chase offset table"
                      if preset == "chase" else frm)
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
        )

    # -- presentation ---------------------------------------------------

    def label(self) -> str:
        return (f"camera {self.camera_id.value} "
                f"({self.preset.value})")


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
