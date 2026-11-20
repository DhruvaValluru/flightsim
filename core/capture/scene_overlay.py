"""The scene picture of a frame: the world round the aircraft, measured.

A third 3-D box picture (``frame_NNNN_box3d_scene.png``), in the same
green instrument style as the other two, with the plane left clear:

* HEIGHT CONTOURS traced on the real ground and buildings: every pixel's
  altitude from the frame's depth image (camera z per pixel) and the
  camera's pose, corrected for the earth's curvature; iso-lines every
  N metres, brighter with height, the tallest point in view marked;
* a GROUND GRID (north / east lines every 500 m or more) lying on the
  terrain in perspective;
* RANGE RINGS on the ground at 1, 2, 5, 10, 20 km round the point
  straight below the aircraft, and the DROP LINE to it with the height
  above ground;
* the FLIGHT PATH ahead: the flown positions when the run has later
  frames, else predicted from the current velocity and bank (a
  coordinated turn), ticked every 5 s, with its shadow on the ground;
* the true HORIZON (labels.horizon), a PITCH LADDER (elevation from the
  camera) and a HEADING TAPE with the aircraft's heading and track;
* an ENVIRONMENT panel: location, ground elevation, terrain in view,
  visible range, wind, turbulence, surface, sun, fog, geoid.

:func:`scene_geometry` computes all of it in numbers (pixels, metres);
the frame's JSON carries it under ``scene_overlay``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .box3d import _intrinsics, project
from .flight_overlay import COLOURS, _Canvas, _draw_box, _font, _panel, overlay_geometry

EARTH_R = 6371000.0
G0 = 9.80665
#: Contour interval candidates (m): the one giving ~6-16 levels in view.
CONTOUR_STEPS = (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000)
RING_KM = (1, 2, 5, 10, 20, 50)
CONTOUR_RANGE_M = 4000.0
PATH_SECONDS = 30
PATH_TICK_S = 5


def _r(v, nd=2):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return [_r(x, nd) for x in v]
    return round(float(v), nd)


def _camera_axes(q):
    from .labels import camera_axes

    return camera_axes(q)                    # (forward, right, up) in (north, east, up)


def _to_camera(record, neu):
    """A scene point (north, east, up-altitude) -> camera (x right, y down,
    z forward), metres."""
    fwd, rgt, up = _camera_axes(record["quaternion_wxyz"])
    d = (neu[0] - float(record["position_north_m"]), neu[1] - float(record["position_east_m"]),
         neu[2] - float(record["position_alt_m"]))
    dot = lambda a, b: a[0] * b[0] + a[1] * b[1] + a[2] * b[2]  # noqa: E731
    return (dot(d, rgt), -dot(d, up), dot(d, fwd))


def _depth_grid(source, width, height):
    import numpy as np

    path = Path(source).with_name(Path(source).stem + "_depth.f32")
    if not path.is_file():
        return None
    raw = np.fromfile(path, dtype="<f4")
    if raw.size != width * height:
        return None
    return raw.reshape(height, width).astype("f8")


def _mask_grid(source, record, width, height):
    """True on the aircraft's (and its parts') pixels, from the ID image."""
    import numpy as np
    from PIL import Image

    path = Path(source).with_name(Path(source).stem + "_mask.png")
    if not path.is_file():
        return None
    ids = {int(e["int_id"]) for e in (record.get("labels") or {}).get("objects") or []
           if isinstance(e, dict) and e.get("int_id") is not None
           and not str(e.get("id")).startswith("terrain")}
    img = Image.open(path).convert("L")
    if img.size != (width, height):
        img = img.resize((width, height), Image.NEAREST)
    a = np.array(img)
    return np.isin(a, sorted(ids)) if ids else None


def world_fields(record: Dict, depth):
    """Per pixel: north, east, altitude (m, curvature-corrected) and
    horizontal range from the camera, NaN where the depth is sky."""
    import numpy as np

    K = _intrinsics(record)
    h, w = depth.shape
    fwd, rgt, up = (np.array(v) for v in _camera_axes(record["quaternion_wxyz"]))
    u = np.arange(w) + 0.5
    v = np.arange(h) + 0.5
    uu, vv = np.meshgrid(u, v)
    z = np.where(np.isfinite(depth) & (depth > 0) & (depth < 1e6), depth, np.nan)
    x = (uu - K[0][2]) / K[0][0] * z
    y = (vv - K[1][2]) / K[1][1] * z
    n = x * rgt[0] - y * up[0] + z * fwd[0]
    e = x * rgt[1] - y * up[1] + z * fwd[1]
    a = x * rgt[2] - y * up[2] + z * fwd[2]
    horiz = np.hypot(n, e)
    north = float(record["position_north_m"]) + n
    east = float(record["position_east_m"]) + e
    # The scene frame is a tangent plane; a point d metres away on the
    # curved earth sits d^2 / 2R lower in it than its true altitude.
    alt = float(record["position_alt_m"]) + a + horiz * horiz / (2.0 * EARTH_R)
    return north, east, alt, horiz


def _iso_alpha(field, levels=None, step=None, width_px=1.3, max_density=0.45):
    """Anti-aliased iso-lines of ``field`` (H x W) as an alpha array 0..1:
    at the multiples of ``step`` or at the given ``levels``. Lines are
    dropped where the field changes by more than ``max_density`` levels
    per pixel (depth edges, noise)."""
    import numpy as np

    gy, gx = np.gradient(field)
    grad = np.hypot(gx, gy)
    if step:
        g = field / step
        dist = np.abs(g - np.round(g))
        per_px = grad / step
        dist_px = dist / np.maximum(per_px, 1e-9)
        level_idx = np.round(g)
    else:
        lv = np.array(levels, float)[:, None, None]
        diff = np.abs(field[None] - lv)
        which = np.nanargmin(np.where(np.isfinite(diff), diff, np.inf), axis=0)
        dist_px = np.take_along_axis(diff, which[None], 0)[0] / np.maximum(grad, 1e-9)
        per_px = grad / max(float(np.min(np.diff(sorted(levels)))) if len(levels) > 1 else 1.0, 1e-9)
        level_idx = which
    alpha = np.clip(1.0 - dist_px / (width_px / 2.0), 0.0, 1.0)
    alpha[~np.isfinite(alpha)] = 0.0
    alpha[(per_px > max_density) | ~np.isfinite(field)] = 0.0
    return alpha, level_idx


def _samples(alpha, level_idx, values, per_level=40, threshold=0.85):
    """Up to ``per_level`` pixel points on each iso-line (for the JSON)."""
    import numpy as np

    out = {}
    ys, xs = np.nonzero(alpha >= threshold)
    if not len(xs):
        return out
    lev = level_idx[ys, xs]
    for L in np.unique(lev):
        sel = np.nonzero(lev == L)[0]
        pick = sel[np.linspace(0, len(sel) - 1, min(per_level, len(sel))).astype(int)]
        key = values(L)
        out[key] = [[int(xs[i]), int(ys[i])] for i in pick]
    return out


def _conditions(manifest):
    return {k: (v.get("value") if isinstance(v, dict) else v)
            for k, v in (manifest.get("conditions") or {}).items()}


def _render_json(source) -> Optional[Dict]:
    path = Path(source).parent / "render.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def _path_points(manifest, record):
    """(points [(t, north, east, alt)], basis): the flown positions of the
    later frames of this camera when there are any, else a prediction."""
    ac = record.get("aircraft") or {}
    state = record.get("state") or {}
    t0 = float(record.get("t_s") or 0.0)
    later = [r for r in manifest.get("frames", [])
             if r.get("camera_id") == record.get("camera_id")
             and float(r.get("t_s") or 0.0) > t0 and r.get("aircraft")]
    pts = [(0.0, float(ac.get("north_m", 0.0)), float(ac.get("east_m", 0.0)),
            float(ac.get("alt_m", state.get("altitude_m", 0.0))))]
    if len(later) >= 3:
        for r in sorted(later, key=lambda r: float(r["t_s"])):
            dt = float(r["t_s"]) - t0
            if dt > PATH_SECONDS:
                break
            a = r["aircraft"]
            pts.append((dt, float(a["north_m"]), float(a["east_m"]), float(a["alt_m"])))
        return pts, "flown: the aircraft's positions in this camera's later frames"
    vn, ve, vd = (float(state.get(k) or 0.0) for k in ("v_north_mps", "v_east_mps", "v_down_mps"))
    gs = math.hypot(vn, ve)
    if gs < 1.0:
        return pts, "no ground speed to predict from"
    roll = math.radians(float(state.get("roll_deg") or 0.0))
    psi = math.atan2(ve, vn)
    rate = G0 * math.tan(roll) / gs            # coordinated turn, rad/s
    n, e, alt = pts[0][1], pts[0][2], pts[0][3]
    dt = 0.5
    t = 0.0
    while t < PATH_SECONDS - 1e-9:
        psi += rate * dt
        n += gs * math.cos(psi) * dt
        e += gs * math.sin(psi) * dt
        alt += -vd * dt
        t += dt
        if abs(t - round(t)) < 1e-6:
            pts.append((round(t, 3), n, e, alt))
    return pts, ("predicted: the current ground velocity and vertical speed held, "
                 "turning at g tan(bank) / ground speed (a coordinated turn)")


_MEMO: List = []


def scene_geometry(manifest: Dict, record: Dict, source) -> Dict:
    """Everything the scene picture draws, in numbers (memoised for the
    same manifest / record / frame, so the picture and the JSON of one
    zip build compute it once)."""
    key = str(source)
    for m_, r_, k_, out_ in _MEMO:
        if m_ is manifest and r_ is record and k_ == key:
            return out_
    out_ = _scene_geometry(manifest, record, source)
    _MEMO.append((manifest, record, key, out_))
    del _MEMO[:-4]
    return out_


def _scene_geometry(manifest: Dict, record: Dict, source) -> Dict:
    import numpy as np

    K = _intrinsics(record)
    W = int(record.get("width_px") or K[0][2] * 2)
    H = int(record.get("height_px") or K[1][2] * 2)
    near = max(float(record.get("near_m", 0.1) or 0.1), 0.01)
    state = record.get("state") or {}
    ac = record.get("aircraft") or {}
    cond = _conditions(manifest)
    out: Dict = {"image_size_px": [W, H], "method": {}}

    def px(cam):
        if K is None or cam[2] < near:
            return None
        q = project(K, cam)
        return None if q is None else [round(q[0], 2), round(q[1], 2)]

    depth = _depth_grid(source, W, H)
    plane = _mask_grid(source, record, W, H)
    ground_alt = None
    if state.get("agl_m") is not None:
        ground_alt = float(ac.get("alt_m", state.get("altitude_m", 0.0))) - float(state["agl_m"])
    fields = None
    if depth is not None:
        north, east, alt, horiz = world_fields(record, depth)
        if plane is not None:
            for f in (north, east, alt, horiz):
                f[plane] = np.nan
        fields = (north, east, alt, horiz)
        # Contours and the height tint stop at 15 km: farther, the depth
        # is too coarse per pixel to read a height from.
        alt_near = np.where(horiz < 15000.0, alt, np.nan)
        ok = np.isfinite(alt)
        near_ok = ok & (horiz < 15000.0)
        lo, hi = (float(np.nanpercentile(alt[near_ok], 1)), float(np.nanpercentile(alt[near_ok], 99.5))) \
            if near_ok.any() else (0.0, 0.0)
        span = max(hi - lo, 1.0)
        step = next((s for s in CONTOUR_STEPS if span / s <= 16), CONTOUR_STEPS[-1])
        out["method"]["world_from_depth"] = (
            "per pixel: camera point = ((u+0.5-cx)/fx z, (v+0.5-cy)/fy z, z) from the "
            "depth image; rotated to north/east/up by the camera quaternion and added to "
            "the camera position; altitude + d^2 / (2 x 6371 km) for the earth's curvature")
        # Tallest point in view (inside 15 km, off the plane).
        top = None
        if near_ok.any():
            masked = np.where(near_ok, alt, -np.inf)
            iy, ix = np.unravel_index(int(np.argmax(masked)), masked.shape)
            top = {"altitude_m": _r(alt[iy, ix], 1), "pixel": [int(ix), int(iy)],
                   "range_m": _r(horiz[iy, ix], 1),
                   "height_above_flight_model_ground_m": _r(alt[iy, ix] - ground_alt, 1)
                   if ground_alt is not None else None}
        out["terrain"] = {
            "altitude_range_in_view_m": [_r(lo, 1), _r(hi, 1)],
            "altitude_range_basis": "1st-99.5th percentile of the visible ground inside 15 km",
            "tint_range_m": 15000, "contour_range_m": 4000,
            "visible_range_m": _r(float(np.nanmax(horiz)), 1) if ok.any() else None,
            "sky_fraction": _r(float((~np.isfinite(depth) | (depth >= 1e6)).mean()), 4),
            "tallest_point": top,
        }
        # Contour lines only inside 4 km: farther, the ground is seen at a
        # grazing angle and a 20 m iso-line breaks into per-pixel speckle.
        a_c, idx_c = _iso_alpha(np.where(horiz < CONTOUR_RANGE_M, alt, np.nan), step=step)
        out["_alt"] = alt_near
        out["height_tint"] = {"from_m": _r(lo + 0.3 * span, 1), "full_m": _r(hi, 1),
                              "about": "ground and buildings above from_m tinted green, "
                                       "stronger with height (full at full_m)"}
        out["contours"] = {"interval_m": step, "datum": "altitude, flight-model datum (MSL)",
                           "points_px_by_level_m": _samples(a_c, idx_c, lambda L: str(int(L * step))),
                           "_alpha": a_c, "_level": idx_c}
        med = float(np.nanmedian(horiz[ok])) if ok.any() else 1000.0
        grid = 500 if med < 6000 else (1000 if med < 15000 else 2000)
        a_n, idx_n = _iso_alpha(north, step=grid, width_px=1.1, max_density=0.3)
        a_e, idx_e = _iso_alpha(east, step=grid, width_px=1.1, max_density=0.3)
        out["grid"] = {"spacing_m": grid, "axes": "scene north / east (the run's origin)",
                       "north_lines_points_px": _samples(a_n, idx_n, lambda L: f"N{int(L * grid):+d}", 25),
                       "east_lines_points_px": _samples(a_e, idx_e, lambda L: f"E{int(L * grid):+d}", 25),
                       "_alpha": np.maximum(a_n, a_e)}
        n0, e0 = float(ac.get("north_m", 0.0)), float(ac.get("east_m", 0.0))
        rng = np.hypot(north - n0, east - e0)
        radii = [k * 1000.0 for k in RING_KM if ok.any() and k * 1000.0 < float(np.nanmax(rng))]
        if radii:
            a_r, idx_r = _iso_alpha(rng, levels=radii, width_px=1.6, max_density=0.6)
            ring_labels = []
            for i, R in enumerate(radii):
                ys, xs = np.nonzero((idx_r == i) & (a_r > 0.9))
                if len(xs):
                    j = int(np.argmax(ys))          # the ring's point nearest the camera
                    ring_labels.append({"radius_m": R, "label": f"{int(R / 1000)} km",
                                        "at_px": [int(xs[j]), int(ys[j])]})
            out["range_rings"] = {"radii_m": radii, "centre": "the ground point below the aircraft",
                                  "labels": ring_labels, "_alpha": a_r}
    # Ground under the aircraft: the flight model's (its terrain bake, the
    # ground the physics flies over) and the one MEASURED in this frame
    # from the depth image -- directly below when that is in view, else
    # the street level round the point below.
    model_ground = ground_alt
    measured, basis_g = None, "not measurable: no depth image beside this frame"
    low_nearby = None
    direct = False
    if fields is not None:
        north, east, alt, horiz = fields
        n0, e0 = float(ac.get("north_m", 0.0)), float(ac.get("east_m", 0.0))
        d_nadir = np.hypot(north - n0, east - e0)
        below = np.isfinite(alt) & (d_nadir < 40.0)
        around = np.isfinite(alt) & (d_nadir < 2000.0)
        if below.sum() >= 20:
            measured = float(np.nanmedian(alt[below]))
            direct = True
            basis_g = "measured directly below the aircraft (depth image, within 40 m)"
        else:
            basis_g = "not in view: the ground straight below the aircraft is outside this frame"
        if around.sum() >= 200:
            low_nearby = float(np.nanpercentile(alt[around], 5))
    plane_alt = float(ac.get("alt_m", state.get("altitude_m", 0.0)))
    diff = (model_ground - measured) if (model_ground is not None and measured is not None) else None
    out["ground"] = {
        "flight_model_m": _r(model_ground, 1),
        "flight_model_basis": "aircraft altitude minus the flight model's AGL (its terrain bake)",
        "measured_m": _r(measured, 1), "measured_basis": basis_g,
        "difference_m": _r(diff, 1),
        "agl_flight_model_m": _r(state.get("agl_m"), 1),
        "agl_measured_m": _r(plane_alt - measured, 1) if measured is not None else None,
        "measured_directly_below": bool(measured is not None and direct),
        "lowest_visible_ground_within_2km_m": _r(low_nearby, 1),
        "lowest_visible_ground_basis": ("5th percentile of the visible ground within 2 km of "
                                        "the point below -- street / water level, not the "
                                        "ground under the aircraft"),
        "mismatch": bool(diff is not None and abs(diff) > 30.0),
        "mismatch_threshold_m": 30.0,
    }
    # The drop line uses the measured ground only when it was measured
    # straight below; an estimate from nearby ground is shown, not used.
    ground_draw = measured if (measured is not None and direct) else model_ground
    # Drop line and nadir.
    if ground_draw is not None:
        n0, e0 = float(ac.get("north_m", 0.0)), float(ac.get("east_m", 0.0))
        top_c = _to_camera(record, (n0, e0, plane_alt))
        foot_c = _to_camera(record, (n0, e0, ground_draw))
        agl = plane_alt - ground_draw
        label = f"AGL {agl:,.0f} m"
        g_ = out["ground"]
        if g_["mismatch"]:
            label += f"  (model {float(state['agl_m']):,.0f})"
        out["drop_line"] = {"from_px": px(top_c), "to_px": px(foot_c),
                            "ground_altitude_m": _r(ground_draw, 1),
                            "height_above_ground_m": _r(agl, 1),
                            "basis": "measured ground" if (measured is not None and direct)
                            else "flight-model ground",
                            "label": label}
    ground_alt = ground_draw
    # Flight path.
    pts, basis = _path_points(manifest, record)
    if len(pts) > 1:
        path, shadow, ticks = [], [], []
        for t, n, e, a in pts:
            c = _to_camera(record, (n, e, a))
            path.append({"t_s": t, "north_m": _r(n, 2), "east_m": _r(e, 2), "alt_m": _r(a, 2),
                         "px": px(c)})
            if ground_alt is not None:
                shadow.append(px(_to_camera(record, (n, e, ground_alt))))
            if t > 0 and abs(t / PATH_TICK_S - round(t / PATH_TICK_S)) < 1e-6:
                ticks.append({"t_s": t, "label": f"+{int(t)} s", "px": px(c)})
        out["flight_path"] = {"basis": basis, "seconds": PATH_SECONDS, "points": path,
                              "ground_shadow_px": shadow, "ticks": ticks}
    # Horizon, pitch ladder, heading tape.
    hz = (record.get("labels") or {}).get("horizon") or {}
    if hz.get("polyline_px"):
        out["horizon"] = {"polyline_px": hz["polyline_px"], "model": hz.get("model"),
                          "dip_deg": hz.get("dip_deg")}
    fwd, rgt, up = _camera_axes(record["quaternion_wxyz"])
    cam_az = math.degrees(math.atan2(fwd[1], fwd[0]))

    def dir_px(az_deg, el_deg):
        az, el = math.radians(az_deg), math.radians(el_deg)
        d = (math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el))
        dot = lambda a, b: a[0] * b[0] + a[1] * b[1] + a[2] * b[2]  # noqa: E731
        c = (dot(d, rgt) * 1e4, -dot(d, up) * 1e4, dot(d, fwd) * 1e4)
        return px(c)

    ladder = []
    for el in (-20, -15, -10, -5, 5, 10, 15, 20):
        centre = dir_px(cam_az, el)
        left = dir_px(cam_az - 4.0, el)
        if centre and left and 0 <= centre[1] <= H:
            ladder.append({"elevation_deg": el, "centre_px": centre, "left_px": left})
    out["pitch_ladder"] = {"rungs": ladder, "reference": "elevation from the camera, about "
                           "the camera's own azimuth (world-level, not the aircraft's pitch)"}
    tape = []
    for az in range(0, 360, 5):
        p = dir_px(az, 0.0)
        if p and 0 <= p[0] <= W:
            tape.append({"azimuth_deg": az, "x_px": p[0]})
    hdg = float(state.get("heading_deg", ac.get("heading_deg", 0.0)) or 0.0) % 360.0
    vn, ve = float(state.get("v_north_mps") or 0.0), float(state.get("v_east_mps") or 0.0)
    trk = math.degrees(math.atan2(ve, vn)) % 360.0 if math.hypot(vn, ve) > 1 else None
    out["heading_tape"] = {"ticks": tape, "camera_azimuth_deg": _r(cam_az % 360.0, 2),
                           "aircraft_heading_deg": _r(hdg, 2), "aircraft_track_deg": _r(trk, 2),
                           "heading_x_px": (dir_px(hdg, 0.0) or [None])[0],
                           "track_x_px": (dir_px(trk, 0.0) or [None])[0] if trk is not None else None}
    # Environment.
    render = _render_json(source) or {}
    sky = ((render.get("scene") or {}).get("sky") or {})
    hero = ((render.get("hero_lighting") or {}).get("sun") or {})
    fog = ((render.get("look_applied") or {}).get("fog") or {})
    sun_el, sun_az, sun_basis = None, None, "not recorded beside this frame"
    if sky.get("sun_elevation_deg") is not None:
        sun_el = float(sky["sun_elevation_deg"])
        sun_az = (float(sky["sun_azimuth_deg"]) % 360.0
                  if sky.get("sun_azimuth_deg") is not None else None)
        sun_basis = "render.json scene.sky (the sun the frame was lit with)"
    elif hero.get("sun_elevation_deg") is not None:
        sun_el = float(hero["sun_elevation_deg"])
        sun_basis = "render.json hero_lighting.sun"
    # (render.json look_applied.sun is a stale record of the level's
    # default light, not the frame's sun; it is not read.)
    wind_spd = float(state.get("wind_speed_mps") or 0.0) / 0.514444
    wn, we = float(state.get("wind_north_mps") or 0.0), float(state.get("wind_east_mps") or 0.0)
    wind_from = math.degrees(math.atan2(-we, -wn)) % 360.0 if wind_spd > 0.1 else None
    loc = ((manifest.get("conditions") or {}).get("latitude") or {}).get("from")
    if isinstance(loc, str) and loc == loc.lower():
        loc = loc.title()                    # "new york" -> "New York" (as typed in the prompt)
    out["environment"] = {
        "location": loc, "latitude_deg": state.get("lat_deg"), "longitude_deg": state.get("lon_deg"),
        "ground_elevation_below_m": _r(ground_alt, 1),
        "ground_basis": out["ground"]["measured_basis"]
        if out["ground"]["measured_directly_below"] else out["ground"]["flight_model_basis"],
        "scene_terrain_elevation_m": cond.get("terrain_elevation"),
        "surface": cond.get("surface"), "turbulence": cond.get("turbulence"),
        "weather_event": cond.get("weather_event"),
        "wind_from_deg": _r(wind_from, 1), "wind_speed_kt": _r(wind_spd, 1),
        "temperature_c": _r(float(state["temperature_k"]) - 273.15, 1)
        if state.get("temperature_k") is not None else None,
        "sun_elevation_deg": _r(sun_el, 1), "sun_azimuth_deg": _r(sun_az, 1),
        "sun_basis": sun_basis,
        "fog_density": fog.get("fog_density"),
        "geoid_undulation_m": _r((manifest.get("datum") or {}).get("undulation_m"), 2),
        "vertical_datum": (manifest.get("datum") or {}).get("vertical_datum_of_heights"),
    }
    return out


def _ground_text(geo: Dict) -> str:
    g = geo.get("ground") or {}
    if g.get("measured_m") is None:
        if g.get("flight_model_m") is None:
            return "--"
        return f"{g['flight_model_m']:,.0f} m model (not in view)"
    text = f"{g['measured_m']:,.0f} m measured"
    if g.get("mismatch"):
        text += f" \u26a0 model {g['flight_model_m']:,.0f}"
    return text


def _env_rows(geo: Dict) -> List[Tuple[str, str]]:
    env, ter = geo["environment"], geo.get("terrain") or {}
    def f(x, fmt, unit=""):
        return "--" if x is None else f"{x:{fmt}}{unit}"
    loc = env.get("location") or "--"
    rows = [("LOCATION", loc if len(loc) <= 30 else loc[:29] + "…"),
            ("LAT / LON", f"{f(env['latitude_deg'], '.4f')} / {f(env['longitude_deg'], '.4f')}"),
            ("GROUND BELOW", _ground_text(geo)),
            ("LOWEST NEARBY", f((geo.get("ground") or {}).get("lowest_visible_ground_within_2km_m"),
                                ",.0f", " m")),
            ("TERRAIN IN VIEW", (f"{ter['altitude_range_in_view_m'][0]:,.0f} – "
                                 f"{ter['altitude_range_in_view_m'][1]:,.0f} m")
             if ter.get("altitude_range_in_view_m") else "--"),
            ("TALLEST IN VIEW", f((ter.get("tallest_point") or {}).get("altitude_m"), ",.0f", " m")),
            ("VISIBLE RANGE", f((ter.get("visible_range_m") or 0) / 1000.0 if ter.get("visible_range_m") else None, ".1f", " km")),
            ("WIND", f"{env['wind_from_deg']:03.0f}° / {env['wind_speed_kt']:.0f} kt"
             if env.get("wind_from_deg") is not None else "calm"),
            ("TURBULENCE", str(env.get("turbulence") or "--")),
            ("SURFACE", str(env.get("surface") or "--")),
            ("SUN", (f"elev {env['sun_elevation_deg']}°" +
                     (f"  az {env['sun_azimuth_deg']:03.0f}°" if env.get("sun_azimuth_deg") is not None else ""))
             if env.get("sun_elevation_deg") is not None else "not recorded"),
            ("TEMP", f(env.get("temperature_c"), "+.1f", " °C")),
            ("GEOID N", f(env.get("geoid_undulation_m"), "+.1f", " m"))]
    if geo.get("contours"):
        rows.append(("CONTOURS", f"every {geo['contours']['interval_m']} m"))
    if geo.get("grid"):
        rows.append(("GRID", f"{geo['grid']['spacing_m']} m"))
    return rows


def draw_scene_frame(record: Dict, source, target, manifest: Optional[Dict] = None,
                     geometry: Optional[Dict] = None) -> Path:
    """Write ``target``: the scene picture of :func:`scene_geometry`."""
    import numpy as np
    from PIL import Image

    base = Image.open(source).convert("RGB")
    geo = geometry or scene_geometry(manifest or {}, record, source)
    box_geo = overlay_geometry(manifest, record, airflow=False)
    mask = None
    plane = _mask_grid(source, record, *geo["image_size_px"])
    if plane is not None:
        mask = Image.fromarray((plane * 255).astype("uint8"))
    cv = _Canvas(base, geo, mask)
    k = cv.k
    font, small, title = _font(int(11 * k)), _font(int(9.5 * k)), _font(int(11.5 * k))
    for item in box_geo["aircraft"]:
        cv.avoid(item.get("bbox_2d_px"))

    # Raster iso-lines (contours brighter with height, grid faint, rings).
    W, H = geo["image_size_px"]
    rgba = np.zeros((H, W, 4), dtype="f8")

    def over(colour, a):
        """Straight-alpha 'over': colour (H x W x 3 or 3,) at alpha a."""
        A = rgba[..., 3]
        out_a = a + A * (1.0 - a)
        safe = np.maximum(out_a, 1e-9)[..., None]
        col = np.nan_to_num(np.broadcast_to(np.asarray(colour, "f8"), rgba[..., :3].shape))
        a = np.nan_to_num(a)
        rgba[..., :3] = (col * a[..., None] + rgba[..., :3] * (A * (1.0 - a))[..., None]) / safe
        rgba[..., 3] = out_a

    def add(alpha, colour, strength):
        over(colour, np.clip(alpha * strength, 0.0, 1.0))

    if geo.get("height_tint") and geo.get("_alt") is not None:
        ht = geo["height_tint"]
        t_h = np.clip((geo["_alt"] - ht["from_m"]) / max(ht["full_m"] - ht["from_m"], 1.0), 0, 1)
        add(np.nan_to_num(t_h, nan=0.0), (110, 250, 160), 0.34)
    if geo.get("grid"):
        add(geo["grid"]["_alpha"], (175, 225, 190), 0.38)
    if geo.get("contours"):
        c = geo["contours"]
        lo, hi = (geo["terrain"]["altitude_range_in_view_m"] or [0, 1])
        step = c["interval_m"]
        lvl_alt = c["_level"] * step
        t = np.clip((lvl_alt - lo) / max(hi - lo, 1.0), 0.0, 1.0)
        strength = 0.6 + 0.4 * t
        major = (np.abs(np.round(c["_level"]) % 5) < 0.5)
        strength = np.where(major, np.minimum(1.0, strength + 0.2), strength)
        a = np.nan_to_num(np.clip(c["_alpha"] * strength, 0, 1), nan=0.0)
        col_lo, col_hi = np.array((60, 170, 110.0)), np.array((205, 255, 185.0))
        col = col_lo[None, None] + (col_hi - col_lo)[None, None] * t[..., None]
        over(col, a)
    if geo.get("range_rings"):
        add(geo["range_rings"]["_alpha"], (225, 245, 200), 0.85)
    if rgba[..., 3].max() > 0:
        rgba = np.nan_to_num(rgba, nan=0.0)
        img = Image.fromarray(np.clip(np.dstack([rgba[..., :3], rgba[..., 3:] * 255]), 0, 255)
                              .astype("uint8"), "RGBA")
        import os
        if os.environ.get("FS_SCENE_DEBUG"):
            img.save(os.environ["FS_SCENE_DEBUG"])
        img = img.resize(cv.layers["flow"].size, Image.BILINEAR)
        cv.layers["flow"] = Image.alpha_composite(cv.layers["flow"], img)
        from PIL import ImageDraw

        cv.draw["flow"] = ImageDraw.Draw(cv.layers["flow"])

    # Horizon and pitch ladder.
    hz = geo.get("horizon")
    if hz:
        pts = [cv.P(p) for p in hz["polyline_px"]]
        for a, b in zip(pts, pts[1:]):
            L = math.dist(a, b)
            n = max(1, int(L // (10 * k)))
            for i in range(0, n, 2):
                t0, t1 = i / n, min(1.0, (i + 1) / n)
                cv.line("inst", (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                        (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1),
                        COLOURS["text"], 1.2 * k, alpha=170)
        cv.tag(pts[-1] if pts[-1][0] < cv.W * SS_() - 140 * k else (cv.W * SS_() - 150 * k, pts[-1][1]),
               f"HORIZON  dip {hz.get('dip_deg', 0):.2f}°", COLOURS["dim"], small, leader=False)
    for rung in geo["pitch_ladder"]["rungs"]:
        c, l = cv.P(rung["centre_px"]), cv.P(rung["left_px"])
        dx, dy = c[0] - l[0], c[1] - l[1]
        gap = 0.35
        for sgn in (-1, 1):
            a = (c[0] + sgn * dx * gap, c[1] + sgn * dy * gap)
            b = (c[0] + sgn * dx, c[1] + sgn * dy)
            cv.line("inst", a, b, COLOURS["dim"], 1.0 * k, alpha=150)
            tip = (b[0], b[1] + (6 * k if rung["elevation_deg"] < 0 else -6 * k))
            cv.line("inst", b, tip, COLOURS["dim"], 1.0 * k, alpha=150)
        cv.draw["inst"].text((c[0] + dx + 4 * k, c[1] + dy - 6 * k), f"{rung['elevation_deg']:+d}",
                             font=small, fill=COLOURS["dim"] + (200,))

    # Drop line, nadir, tallest point.
    dl = geo.get("drop_line")
    if dl and dl.get("from_px") and dl.get("to_px"):
        a, b = cv.P(dl["from_px"]), cv.P(dl["to_px"])
        L = math.dist(a, b)
        n = max(1, int(L // (6 * k)))
        for i in range(0, n, 2):
            t0, t1 = i / n, min(1.0, (i + 1) / n)
            cv.line("inst", (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                    (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1),
                    COLOURS["bracket"], 1.4 * k, alpha=220, outline=True)
        r = 7 * k
        d = cv.draw["inst"]
        d.ellipse([b[0] - r, b[1] - r * 0.45, b[0] + r, b[1] + r * 0.45],
                  outline=COLOURS["bracket"] + (230,), width=max(1, int(1.4 * k)))
        cv.line("inst", (b[0] - r * 1.6, b[1]), (b[0] + r * 1.6, b[1]), COLOURS["bracket"], 1.0 * k, 200)
        cv.tag(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), dl["label"], COLOURS["bracket"], font)
    top = (geo.get("terrain") or {}).get("tallest_point")
    if top:
        p = cv.P(top["pixel"])
        s = 5 * k
        cv.draw["inst"].polygon([(p[0], p[1] - s * 1.6), (p[0] - s, p[1] - s * 3.2), (p[0] + s, p[1] - s * 3.2)],
                                fill=COLOURS["weight"] + (230,), outline=(0, 0, 0, 120))
        cv.tag((p[0], p[1] - s * 4), f"▲ {top['altitude_m']:,.0f} m  {top['range_m'] / 1000:.1f} km",
               COLOURS["weight"], small, leader=False)
    for lab in (geo.get("range_rings") or {}).get("labels", []):
        cv.tag(cv.P(lab["at_px"]), lab["label"], COLOURS["text"], small, leader=False)
    # Contour value labels: one per major level (every 5th), spread out.
    if geo.get("contours"):
        step = geo["contours"]["interval_m"]
        used = []
        for lvl, pts in sorted(geo["contours"]["points_px_by_level_m"].items(),
                               key=lambda x: -int(x[0])):
            if (int(lvl) % (5 * step) or not pts or len(used) >= 5
                    or int(lvl) <= geo["terrain"]["altitude_range_in_view_m"][0]):
                continue
            p = next((cv.P(q) for q in pts[len(pts) // 3:] + pts[:len(pts) // 3]
                      if all(math.dist(cv.P(q), u) > 120 * k for u in used)), None)
            if p is None:
                continue
            cv.tag(p, f"{int(lvl)} m", (150, 220, 165), small, leader=False)
            used.append(p)

    # Flight path and shadow.
    fp = geo.get("flight_path")
    if fp:
        pts = [cv.P(p["px"]) for p in fp["points"]]
        for a, b in zip(pts, pts[1:]):
            if a and b:
                cv.line("inst", a, b, COLOURS["velocity"], 1.8 * k, alpha=230, outline=True)
        sh = [cv.P(p) for p in fp.get("ground_shadow_px") or []]
        for i, (a, b) in enumerate(zip(sh, sh[1:])):
            if a and b and i % 2 == 0:
                cv.line("flow", a, b, COLOURS["velocity"], 1.2 * k, alpha=130)
        last = None
        for tk in fp["ticks"]:
            p = cv.P(tk["px"])
            if not p:
                continue
            r = 2.6 * k
            cv.draw["inst"].ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r],
                                    fill=COLOURS["velocity"] + (240,), outline=(0, 0, 0, 140))
            # Label a tick only when it sits clear of the last labelled one.
            if last is None or math.dist(p, last) > 40 * k or tk is fp["ticks"][-1]:
                cv.tag(p, tk["label"], COLOURS["velocity"], small, leader=False)
                last = p

    # The plain box, so the aircraft is named.
    for item in box_geo["aircraft"]:
        _draw_box(cv, item, detailed=False)

    # Heading tape (under the header).
    top_d = cv.draw["top"]
    pad = 10 * k
    y0 = 21 * k
    top_d.rectangle([0, y0, cv.W * SS_(), y0 + 22 * k], fill=COLOURS["panel"] + (170,))
    names = {0: "N", 45: "NE", 90: "E", 135: "SE", 180: "S", 225: "SW", 270: "W", 315: "NW"}
    for tk in geo["heading_tape"]["ticks"]:
        x = tk["x_px"] * cv.sx * SS_()
        az = tk["azimuth_deg"]
        big = az % 10 == 0
        top_d.line([x, y0, x, y0 + (7 if big else 4) * k], fill=COLOURS["dim"] + (220,),
                   width=max(1, int(0.9 * k)))
        if az % 30 == 0 or az in names:
            txt = names.get(az, f"{az:03d}")
            tw = top_d.textbbox((0, 0), txt, font=small)[2]
            top_d.text((x - tw / 2, y0 + 8 * k), txt, font=small, fill=COLOURS["text"] + (230,))
    for key, label, colour in (("heading_x_px", "HDG", COLOURS["bracket"]),
                               ("track_x_px", "TRK", COLOURS["velocity"])):
        x = geo["heading_tape"].get(key)
        if x is None:
            continue
        x = x * cv.sx * SS_()
        val = geo["heading_tape"]["aircraft_heading_deg" if key == "heading_x_px" else "aircraft_track_deg"]
        top_d.polygon([(x, y0 + 22 * k), (x - 5 * k, y0 + 30 * k), (x + 5 * k, y0 + 30 * k)],
                      fill=colour + (240,))
        txt = f"{label} {val:03.0f}"
        bx = top_d.textbbox((0, 0), txt, font=small)
        tw, th = bx[2] - bx[0], bx[3] - bx[1]
        ty = y0 + 32 * k + (0 if key == "heading_x_px" else 13 * k)
        top_d.rectangle([x - tw / 2 - 3 * k, ty - 1.5 * k, x + tw / 2 + 3 * k, ty + th + 3 * k],
                        fill=COLOURS["header"] + (215,))
        top_d.text((x - tw / 2, ty - bx[1]), txt, font=small, fill=colour + (255,))

    # Environment panel, header and footer.
    _panel(top_d, (pad, 64 * k), "ENVIRONMENT  " + str((record.get("camera_id"))), _env_rows(geo),
           font, title, k)
    header = (f"FLIGHTSIM  SCENE   cam {record.get('camera_id')}   "
              f"frame {int(record.get('index', 0)):04d}   t {float(record.get('t_s') or 0):.3f} s")
    top_d.rectangle([0, 0, cv.W * SS_(), 20 * k], fill=COLOURS["header"] + (215,))
    top_d.line([0, 20 * k, cv.W * SS_(), 20 * k], fill=COLOURS["box"] + (120,), width=max(1, int(0.8 * k)))
    top_d.text((pad, 4 * k), header, font=title, fill=COLOURS["text"] + (255,))
    foot = ("ground from the depth image + camera pose (curvature-corrected)   contours: altitude   "
            "rings round the point below the aircraft   path: " +
            ("flown" if fp and fp["basis"].startswith("flown") else "predicted from velocity + bank"))
    top_d.rectangle([0, cv.H * SS_() - 18 * k, cv.W * SS_(), cv.H * SS_()],
                    fill=COLOURS["header"] + (215,))
    top_d.text((pad, cv.H * SS_() - 15 * k), foot, font=small, fill=COLOURS["dim"] + (255,))
    return cv.finish(target)


def SS_():
    from .flight_overlay import SS

    return SS


def scene_json(geo: Dict) -> Dict:
    """The scene geometry for the frame's JSON (the raster alphas dropped)."""
    def clean(v):
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items() if not k.startswith("_")}
        if isinstance(v, list):
            return [clean(x) for x in v]
        return v
    return clean(geo)
