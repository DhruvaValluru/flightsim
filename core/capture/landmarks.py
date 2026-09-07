"""Known static world points, so verification has something to grade against.

Phase 1's geometry check projected exactly one world point -- the
aircraft -- and for an aircraft-aimed camera that point sits within a
degree of the principal point. A projection model can be badly wrong at
the edges of the frame and still put a centred point where it belongs,
so a check built on it measures almost nothing.

Landmarks fix the coverage half of that. They are:

* **static** -- fixed in the scene, so two cameras looking at one
  landmark at the same instant are genuinely looking at the same thing
  (the aircraft state, by contrast, is copied into every camera's frame
  record from one array, which is why triangulating it returns its own
  input);
* **off-axis** -- spread across the scene, so a frame that contains them
  exercises the projection away from the optical centre;
* **known independently of any camera** -- derived from the flown
  track, the terrain raster and the scene datum, never from a pose.

They are anchored near the flown track rather than scattered across the
scene, because a landmark that never lands inside a frame grades
nothing: the cameras look at the aircraft, so the marks go where the
cameras look, spread abeam far enough to reach the edges of the frame
where a projection error is largest.

They are recorded in the capture manifest and handed to the render
commandlet, which projects the same points through its OWN
``ProjectToPixel`` and writes the pixels into ``render.json``. That
comparison -- Python's projection against the engine's, two
implementations in two languages -- is the independent reprojection the
phase exit criterion asks for. Everything the verifier can do without
the engine is weaker than that and says so.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

#: Offsets from the track, metres, at two scales. A close camera (a
#: 110 m chase) and a distant one (a tower a kilometre away) frame very
#: different amounts of world, so one scale would put marks off the
#: edge for one and on the optical axis for the other. Both scales are
#: laid out abeam and vertically about the aircraft, which is where an
#: aircraft-aimed camera is looking.
TRACK_SCALES_M = (40.0, 400.0)

#: How many stations along the flown track carry marks.
TRACK_STATIONS = 4


def track_landmarks(aircraft_track: Sequence[Dict],
                    terrain_elevation_m: float = 0.0,
                    heightfield=None, frame=None) -> List[Dict]:
    """Marks anchored to the flown track, at :data:`TRACK_STATIONS`
    evenly spaced stations: four marks abeam and above/below the
    aircraft at each scale in :data:`TRACK_SCALES_M`, plus one on the
    ground beneath.

    Static -- fixed once the flight is recorded, they do not move with
    any camera -- and known without reference to any pose, which is
    what makes them usable as a reference. They sit near the track
    because a landmark that never lands inside a frame grades nothing;
    the two scales and the four directions put them off the optical
    axis, where a projection error is largest.
    """
    import math

    if len(aircraft_track) < 2:
        return []
    points: List[Dict] = []
    last = len(aircraft_track) - 1
    for station in range(TRACK_STATIONS):
        index = round(station * last / max(TRACK_STATIONS - 1, 1))
        here = aircraft_track[index]
        ahead = aircraft_track[min(index + 1, last)]
        behind = aircraft_track[max(index - 1, 0)]
        # Course over the ground from the track itself, so "abeam" is
        # perpendicular to how the aircraft actually flew.
        course = math.atan2(ahead["east_m"] - behind["east_m"],
                            ahead["north_m"] - behind["north_m"])
        abeam_n = math.cos(course + math.pi / 2)
        abeam_e = math.sin(course + math.pi / 2)
        for scale in TRACK_SCALES_M:
            for label, abeam, up in (("l", -scale, 0.0), ("r", scale, 0.0),
                                     ("u", 0.0, scale), ("d", 0.0, -scale)):
                points.append({
                    "name": f"air_{station}_{scale:.0f}_{label}",
                    "north_m": float(here["north_m"] + abeam * abeam_n),
                    "east_m": float(here["east_m"] + abeam * abeam_e),
                    "alt_m": float(here["alt_m"] + up),
                })
        points.append({
            "name": f"ground_{station}",
            "north_m": float(here["north_m"]),
            "east_m": float(here["east_m"]),
            "alt_m": _ground_elevation(here["north_m"], here["east_m"],
                                       heightfield, frame,
                                       terrain_elevation_m),
        })
    return points


def _ground_elevation(north_m: float, east_m: float, heightfield, frame,
                      terrain_elevation_m: float) -> float:
    """The terrain height under a local point, or the scene datum."""
    if heightfield is None or frame is None:
        return float(terrain_elevation_m)
    try:
        x_m, y_m = frame.to_projected(north_m, east_m)
        return float(heightfield.elevation_at(x_m, y_m))
    except Exception:
        return float(terrain_elevation_m)


def terrain_landmarks(heightfield, frame) -> List[Dict]:
    """The raster's four corners at their own elevations, plus its
    highest cell. Read straight off the heightfield, so they are known
    without reference to any camera and reproducible from the raster
    digest alone."""
    import numpy as np

    z = heightfield.elevations()
    g = heightfield.georeference
    rows, cols = z.shape

    def at(row: int, col: int, name: str) -> Dict:
        x = g.origin_x_m + col * g.pixel_size_m
        y = g.origin_y_m - row * g.pixel_size_m
        return {"name": name,
                "north_m": float(y - frame.origin_y_m),
                "east_m": float(x - frame.origin_x_m),
                "alt_m": float(z[row, col])}

    peak_row, peak_col = np.unravel_index(int(np.argmax(z)), z.shape)
    return [
        at(0, 0, "terrain_nw"),
        at(0, cols - 1, "terrain_ne"),
        at(rows - 1, 0, "terrain_sw"),
        at(rows - 1, cols - 1, "terrain_se"),
        at(int(peak_row), int(peak_col), "terrain_peak"),
    ]


def scene_landmarks(frame, aircraft_track=(), heightfield=None,
                    terrain_elevation_m: float = 0.0) -> List[Dict]:
    """The landmark set for one captured run.

    Always the track-anchored ground marks, which are the ones that
    land inside the frames; plus, over a real raster, its corners and
    highest cell, which are scene-wide reference points a consumer can
    recompute from the raster digest alone. Positions are local
    north/east metres about the manifest's own projected origin plus
    altitude MSL -- the same frame every other position in the manifest
    uses.
    """
    points = list(track_landmarks(aircraft_track, terrain_elevation_m,
                                  heightfield, frame))
    if heightfield is not None:
        points.extend(terrain_landmarks(heightfield, frame))
    return points


def landmark_point(landmark: Dict):
    """(north, east, alt) of one landmark record."""
    return (float(landmark["north_m"]), float(landmark["east_m"]),
            float(landmark["alt_m"]))


def by_name(landmarks: Optional[List[Dict]]) -> Dict[str, Dict]:
    return {str(l["name"]): l for l in (landmarks or [])}
