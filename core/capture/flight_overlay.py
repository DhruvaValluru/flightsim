"""The 3-D box picture as an engineering readout, and its JSON twin.

On top of the frame this draws, per aircraft, the 3-D box (glowing edges,
corner brackets, the nose face, the length / span / height along its
edges, the body axes at the CG) and, for the aircraft the flight model
flew:

* the airflow -- streamlines past the airframe from
  :func:`core.capture.flight_physics.airflow_streamlines`, coloured by the
  local airspeed against the free stream (blue slow -> red fast);
* the forces from the CG -- lift, weight, thrust, drag (and the net force
  when it is not negligible), each an arrow in 3-D, projected with the
  frame's own intrinsics, with its value in kN; and the velocity vector
  off the nose;
* two panels: the flight state (position, altitude, speeds, Mach,
  attitude, alpha / beta / gamma, load factor, air data, wind) and the
  forces (bars to one scale, L/D, T/W, CL, CD, specific excess power),
  plus the colour key.

:func:`overlay_geometry` computes everything the picture draws, in
camera metres AND pixels, without drawing; :func:`draw_flight_frame`
draws exactly that. The frame's JSON carries the same geometry, so the
JSON is the picture in numbers: every arrow, line and panel value in it
is what is on the image.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .box3d import EDGES, NOSE_FACE, _intrinsics, clip_segment, facing, project, rebuild_corners
from .flight_physics import G0, KT, FT, airflow_streamlines, frame_physics

#: The arrow scale, stated in the JSON: a force F is drawn
#: ARROW_K x reference length x sqrt(F / weight) long (sqrt so thrust and
#: drag, a tenth of the weight, still read beside lift and weight).
ARROW_K = 0.55
ARROW_MIN_FRACTION = 0.004          # forces under 0.4 % of weight are not drawn
NET_MIN_FRACTION = 0.03             # the net force is drawn above 3 % of weight

COLOURS = {
    "box": (0, 229, 255), "nose": (255, 60, 170), "lift": (70, 255, 120),
    "weight": (255, 150, 40), "thrust": (60, 150, 255), "drag": (255, 64, 64),
    "net": (245, 245, 245), "velocity": (255, 232, 60), "text": (215, 240, 255),
    "dim": (120, 170, 190), "panel": (6, 12, 20), "axis_x": (255, 80, 80),
    "axis_y": (80, 255, 110), "axis_z": (90, 150, 255),
}
#: Streamline colour ramp over speed ratio (blue slow, cyan, green, yellow, red fast).
RAMP = [(20, 70, 255), (0, 200, 255), (60, 255, 150), (255, 230, 40), (255, 60, 30)]
#: The speed-ratio window the ramp spans (|u| / V; 1 = free stream).
RAMP_RANGE = (0.94, 1.06)


def ramp(ratio: float, window: Sequence[float] = RAMP_RANGE) -> Tuple[int, int, int]:
    lo, hi = window
    t = min(1.0, max(0.0, (ratio - lo) / (hi - lo))) * (len(RAMP) - 1)
    i = min(int(t), len(RAMP) - 2)
    f = t - i
    return tuple(int(RAMP[i][k] + (RAMP[i + 1][k] - RAMP[i][k]) * f) for k in range(3))


def _r(v, nd=2):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return [_r(x, nd) for x in v]
    return round(float(v), nd)


def _entries(record: Dict, manifest: Optional[Dict]):
    labels = record.get("labels") or {}
    entries = labels.get("objects")
    if not isinstance(entries, list):
        entries = [{"id": f"aircraft:{(manifest or {}).get('aircraft')}:0",
                    "bbox_3d_camera": labels.get("bbox_3d_camera")}]
    classes = {str(o.get("id")): str(o.get("class"))
               for o in (manifest or {}).get("objects") or [] if isinstance(o, dict)}
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if classes.get(str(entry.get("id")), "aircraft") != "aircraft":
            continue
        box = entry.get("bbox_3d_camera")
        if isinstance(box, dict) and box.get("body_axes_in_camera"):
            out.append(entry)
    return out


def _main_id(manifest: Optional[Dict], entries) -> Optional[str]:
    want = f"aircraft:{(manifest or {}).get('aircraft')}:0"
    ids = [str(e.get("id")) for e in entries]
    return want if want in ids else (ids[0] if ids else None)


def overlay_geometry(manifest: Optional[Dict], record: Dict) -> Dict:
    """Everything the picture draws, in camera metres and pixels (see the
    module doc). Pure numbers; no image is read."""
    K = _intrinsics(record)
    width = int(record.get("width_px") or (K[0][2] * 2 if K else 0))
    height = int(record.get("height_px") or (K[1][2] * 2 if K else 0))
    near = max(float(record.get("near_m", 0.1) or 0.1), 0.01)
    entries = _entries(record, manifest)
    main = _main_id(manifest, entries)
    out = {"image_size_px": [width, height], "aircraft": []}

    def px(p):
        if K is None or p[2] < near:
            return None
        q = project(K, p)
        return None if q is None else [round(q[0], 2), round(q[1], 2)]

    for entry in entries:
        box_label = entry["bbox_3d_camera"]
        shape = entry.get("bbox_3d_camera_shape")
        box = shape if isinstance(shape, dict) and shape.get("body_axes_in_camera") else box_label
        axes = [[float(v) for v in row] for row in box["body_axes_in_camera"]]
        corners = rebuild_corners(box)
        extents = [float(v) for v in box["extents_m"]]
        ref = max(extents[0], extents[1])
        cg = [float(v) for v in (box.get("cg_m") or box_label.get("cg_m") or box["centre_m"])]
        centre = [float(v) for v in box["centre_m"]]

        def cam(body):
            return [cg[k] + sum(body[a] * axes[a][k] for a in range(3)) for k in range(3)]

        def body_of(c):
            d = [c[k] - cg[k] for k in range(3)]
            return [sum(d[k] * axes[a][k] for k in range(3)) for a in range(3)]

        item = {"id": str(entry.get("id")),
                "box_drawn": "shape_box (measured mesh)" if box is shape else "stated dimensions",
                "corners_m": [_r(c, 4) for c in corners],
                "corners_px": [px(c) for c in corners],
                "edges": EDGES, "nose_face_edges": NOSE_FACE,
                "extents_m": {"length": _r(extents[0], 3), "width": _r(extents[1], 3),
                              "height": _r(extents[2], 3)},
                "cg_camera_m": _r(cg, 4), "cg_px": px(cg),
                "range_m": _r(math.sqrt(sum(v * v for v in cg)), 3),
                "orientation": facing(box)}
        # Dimension labels: the midpoints of three edges meeting at a corner.
        item["dimension_labels"] = [
            {"text": f"L {extents[0]:.2f} m", "at_px": px([(corners[1][k] + corners[5][k]) / 2 for k in range(3)])},
            {"text": f"W {extents[1]:.2f} m", "at_px": px([(corners[5][k] + corners[7][k]) / 2 for k in range(3)])},
            {"text": f"H {extents[2]:.2f} m", "at_px": px([(corners[6][k] + corners[7][k]) / 2 for k in range(3)])},
        ]
        tri = 0.16 * ref
        item["body_axes"] = [
            {"axis": name, "from_px": px(cg), "to_px": px(cam(vec)),
             "to_camera_m": _r(cam(vec), 4)}
            for name, vec in (("x_body (forward)", (tri, 0, 0)), ("y_body (right)", (0, tri, 0)),
                              ("z_body (down)", (0, 0, tri)))]
        if item["id"] == main and manifest is not None:
            physics = frame_physics(manifest, record, box)
        else:
            physics = None
        item["has_physics"] = physics is not None
        if physics is not None:
            weight = physics["mass"]["weight_n"]
            arrows = []
            for name in ("lift", "weight", "thrust", "drag", "net"):
                f = physics["forces"][name]
                mag = float(f["magnitude_n"])
                frac = mag / weight if weight else 0.0
                limit = NET_MIN_FRACTION if name == "net" else ARROW_MIN_FRACTION
                if frac < limit:
                    continue
                length = min(ARROW_K * ref * math.sqrt(frac), 1.1 * ref)
                d = f["direction_body"]
                tip = cam([d[k] * length for k in range(3)])
                arrows.append({"force": name, "magnitude_n": f["magnitude_n"],
                               "magnitude_kn": f["magnitude_kn"],
                               "label": f"{name.upper()}  {mag / 1000.0:,.2f} kN",
                               "length_m": _r(length, 3),
                               "from_camera_m": _r(cg, 4), "to_camera_m": _r(tip, 4),
                               "from_px": px(cg), "to_px": px(tip),
                               "colour_rgb": list(COLOURS[name])})
            vdir = physics["velocity"]["relative_wind_direction_body"]
            nose = cam([body_of(centre)[0] + extents[0] / 2.0, 0, 0])
            vtip_body = [body_of(nose)[k] - vdir[k] * 0.7 * ref for k in range(3)]
            vel = physics["velocity"]
            arrows.append({"force": "velocity", "label":
                           f"V  {vel['true_airspeed_kt']:.0f} kt TAS",
                           "from_camera_m": _r(nose, 4), "to_camera_m": _r(cam(vtip_body), 4),
                           "from_px": px(nose), "to_px": px(cam(vtip_body)),
                           "length_m": _r(0.7 * ref, 3), "dashed": True,
                           "colour_rgb": list(COLOURS["velocity"])})
            item["arrows"] = arrows
            item["arrow_scale"] = (f"length = {ARROW_K} x {ref:.2f} m x sqrt(F / weight), "
                                   f"capped at 1.1 x {ref:.2f} m; velocity arrow fixed "
                                   f"0.7 x {ref:.2f} m along the relative wind")
            flow = airflow_streamlines(physics, extents, body_of(centre))
            if flow is not None:
                lines = []
                for line in flow["lines"]:
                    pts = [cam(p) for p in line["points_body_m"]]
                    lines.append({"points_camera_m": pts, "points_px": [px(p) for p in pts],
                                  "speed_ratio": line["speed_ratio"]})
                every = sorted(x for ln in lines for x in ln["speed_ratio"])
                lo = every[int(0.03 * (len(every) - 1))]
                hi = every[int(0.97 * (len(every) - 1))]
                spread = max(hi - 1.0, 1.0 - lo, 0.01)
                window = [round(1.0 - spread, 4), round(1.0 + spread, 4)]
                item["airflow"] = {"model": flow["model"], "parameters": flow["parameters"],
                                   "colour_ramp": {"speed_ratio_range": window,
                                                   "range_basis": "symmetric about 1.0, "
                                                   "covering the 3rd-97th percentile of this "
                                                   "frame's speed ratios",
                                                   "colours_rgb_slow_to_fast": [list(c) for c in RAMP]},
                                   "lines": lines}
            item["physics_values"] = physics
        out["aircraft"].append(item)
    return out


def _panel_rows(physics: Dict) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """The two panels' rows, (label, value) as printed."""
    v, air, att, ang = (physics["velocity"], physics["air"], physics["attitude"],
                        physics["aerodynamic_angles"])
    pos, bal, co, en = (physics["position"], physics["force_balance"],
                        physics.get("coefficients") or {}, physics["energy"])

    D = "\u00b0"

    def f(x, fmt, unit=""):
        return "--" if x is None else f"{x:{fmt}}{unit}"

    wind = (f"{air['wind_from_deg']:03.0f}\u00b0 / {air['wind_speed_kt']:.0f} kt"
            if air.get("wind_from_deg") is not None else "calm")
    state_rows = [
        ("AIRCRAFT", f"{physics['aircraft_type']}"),
        ("LAT / LON", f"{f(pos['latitude_deg'], '.4f')} / {f(pos['longitude_deg'], '.4f')}"),
        ("ALT MSL", f"{f(pos['altitude_msl_m'], ',.0f', ' m')}  {f(pos['altitude_msl_ft'], ',.0f', ' ft')}"),
        ("ALT AGL", f(pos["height_above_ground_m"], ",.0f", " m")),
        ("TAS / CAS", f"{f(v['true_airspeed_kt'], '.0f', ' kt')} / {f(v['calibrated_airspeed_kt'], '.0f', ' kt')}"),
        ("GND SPD", f"{f(v['ground_speed_kt'], '.0f', ' kt')}  TRK {f(v['track_deg'], '03.0f', D)}"),
        ("MACH", f(v["mach"], ".3f")),
        ("V/S", f(v["vertical_speed_fpm"], "+,.0f", " fpm")),
        ("HDG/PIT/ROL", f"{f(att['heading_deg'] % 360.0, '03.0f')}{D} {f(att['pitch_deg'], '+.1f')}{D} {f(att['roll_deg'], '+.1f')}{D}"),
        ("\u03b1 / \u03b2 / \u03b3", f"{f(ang['alpha_deg'], '+.2f')}{D} {f(ang['beta_deg'], '+.2f')}{D} {f(ang['flight_path_angle_deg'], '+.2f')}{D}"),
        ("LOAD n_z", f(bal["load_factor_nz_flight_model"], ".3f", " g")),
        ("q\u0305 DYN PRESS", f(air["dynamic_pressure_pa"], ",.0f", " Pa")),
        ("\u03c1 DENSITY", f(air["density_kg_m3"], ".4f", " kg/m\u00b3")),
        ("P STATIC", f(air["static_pressure_pa"] / 1000.0 if air["static_pressure_pa"] else None, ".2f", " kPa")),
        ("TEMP", f(air["temperature_c"], "+.1f", " \u00b0C")),
        ("WIND", wind),
    ]
    forces = physics["forces"]
    force_rows = [(name.upper(), f"{forces[name]['magnitude_kn']:,.2f} kN")
                  for name in ("lift", "weight", "thrust", "drag")]
    force_rows += [
        ("NET", f"{forces['net']['magnitude_kn']:,.2f} kN"),
        ("L / D", f(co.get("lift_to_drag"), ".2f")),
        ("T / W", f(bal["thrust_to_weight"], ".3f")),
        ("CL / CD", f"{f(co.get('CL'), '.3f')} / {f(co.get('CD'), '.4f')}"),
        ("ACCEL", f(bal["acceleration_g"], ".3f", " g")),
        ("Ps", f(en["specific_excess_power_mps"], "+.2f", " m/s")),
        ("MASS", f(physics["mass"]["mass_kg"], ",.0f", " kg")),
    ]
    return state_rows, force_rows


# -- drawing -------------------------------------------------------------------

def _font(size: int):
    from PIL import ImageFont

    for name in ("consola.ttf", "Consolas.ttf", "DejaVuSansMono.ttf", "Menlo.ttc",
                 "/System/Library/Fonts/Menlo.ttc", "C:/Windows/Fonts/consola.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def draw_flight_frame(record: Dict, source, target, manifest: Optional[Dict] = None,
                      geometry: Optional[Dict] = None) -> Path:
    """Write ``target``: ``source`` with the box, airflow, forces and panels
    of :func:`overlay_geometry` drawn on (2x supersampled, with glow)."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    base = Image.open(source).convert("RGB")
    W, H = base.size
    geo = geometry or overlay_geometry(manifest, record)
    gw, gh = geo.get("image_size_px") or (W, H)
    sx, sy = W / float(gw or W), H / float(gh or H)
    SS = 2
    u = max(H / 720.0, 0.45)                    # UI scale (1 at 720p)
    k = SS * u

    # A slightly darker, cooler plate so the readout reads.
    plate = ImageEnhance.Brightness(ImageEnhance.Color(base).enhance(0.88)).enhance(0.86)
    big = plate.resize((W * SS, H * SS), Image.BICUBIC).convert("RGBA")
    # Two layer pairs: the airflow (and the box floor) under the aircraft,
    # everything else over it. The aircraft's own pixels go back on top of
    # the airflow at full brightness, so the plane stays crisp.
    fglow = Image.new("RGBA", big.size, (0, 0, 0, 0))
    fsharp = Image.new("RGBA", big.size, (0, 0, 0, 0))
    fgd, fsd = ImageDraw.Draw(fglow), ImageDraw.Draw(fsharp)
    glow = Image.new("RGBA", big.size, (0, 0, 0, 0))
    sharp = Image.new("RGBA", big.size, (0, 0, 0, 0))
    gd, sd = ImageDraw.Draw(glow), ImageDraw.Draw(sharp)
    limit = 8.0 * max(W, H) * SS

    def P(p):
        if p is None:
            return None
        return (max(-limit, min(limit, p[0] * sx * SS)), max(-limit, min(limit, p[1] * sy * SS)))

    def line(a, b, colour, w, alpha=255, glow_on=True):
        if a is None or b is None:
            return
        sd.line([a, b], fill=colour + (alpha,), width=max(1, int(w)))
        if glow_on:
            gd.line([a, b], fill=colour + (min(255, alpha),), width=max(1, int(w * 3)))

    def dashed(a, b, colour, w, dash):
        if a is None or b is None:
            return
        L = math.dist(a, b)
        n = max(1, int(L // dash))
        for i in range(0, n, 2):
            t0, t1 = i / n, min(1.0, (i + 1) / n)
            line((a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                 (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1), colour, w)

    def arrowhead(a, b, colour, size):
        L = math.dist(a, b)
        if L < 1:
            return
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        s = min(size, L * 0.45)
        left = (b[0] - ux * s - uy * s * 0.5, b[1] - uy * s + ux * s * 0.5)
        right = (b[0] - ux * s + uy * s * 0.5, b[1] - uy * s - ux * s * 0.5)
        sd.polygon([b, left, right], fill=colour + (255,))
        gd.polygon([b, left, right], fill=colour + (200,))

    font = _font(int(12 * k))
    small = _font(int(10 * k))
    title = _font(int(13 * k))

    placed = []

    def tag(at, text, colour, fnt=None, anchor_left=True):
        if at is None:
            return
        fnt = fnt or font
        x0, y0, x1, y1 = sd.textbbox((0, 0), text, font=fnt)
        tw, th = x1 - x0, y1 - y0
        pad = 4 * k
        x = at[0] + (6 * k if anchor_left else -tw - 2 * pad - 6 * k)
        y = at[1] - th / 2 - pad
        x = max(2 * k, min(x, W * SS - tw - 2 * pad - 2 * k))
        y = max(2 * k, min(y, H * SS - th - 2 * pad - 2 * k))
        bw, bh = tw + 2 * pad, th + 2 * pad
        for step in range(40):
            hit = next((q for q in placed if x < q[2] and x + bw > q[0]
                        and y < q[3] + 2 * k and y + bh + 2 * k > q[1]), None)
            if hit is None:
                break
            y = hit[3] + 3 * k if step % 2 == 0 or y + bh < H * SS - 30 * k else hit[1] - bh - 3 * k
        placed.append((x, y, x + bw, y + bh))
        if math.dist((x, y + bh / 2), at) > 14 * k:
            sd.line([at, (x, y + bh / 2)], fill=colour + (160,), width=max(1, int(k)))
        sd.rectangle([x, y, x + tw + 2 * pad, y + th + 2 * pad],
                     fill=COLOURS["panel"] + (190,))
        sd.rectangle([x, y, x + 2 * k, y + th + 2 * pad], fill=colour + (255,))
        sd.text((x + pad + 2 * k - x0, y + pad - y0), text, font=fnt, fill=colour + (255,))

    main_physics = None
    aircraft_pixels = _aircraft_pixels(record, source, geo, big.size)
    plane_rect = _main_rect(record, geo)
    fallback_rect = None if aircraft_pixels is not None else plane_rect
    if plane_rect is not None:
        # Labels keep off the plane itself (they hang off leader lines).
        placed.append((plane_rect[0] * sx * SS, plane_rect[1] * sy * SS,
                       plane_rect[2] * sx * SS, plane_rect[3] * sy * SS))
    for item in geo["aircraft"]:
        flow = item.get("airflow")
        if flow:
            window = flow["colour_ramp"]["speed_ratio_range"]
            for ln in flow["lines"]:
                pts, spd = ln["points_px"], ln["speed_ratio"]
                for i in range(len(pts) - 1):
                    a, b = P(pts[i]), P(pts[i + 1])
                    if a is None or b is None:
                        continue
                    over = (fallback_rect is not None and pts[i] is not None
                            and fallback_rect[0] <= pts[i][0] <= fallback_rect[2]
                            and fallback_rect[1] <= pts[i][1] <= fallback_rect[3])
                    fade = min(1.0, i / 10.0) * min(1.0, (len(pts) - 1 - i) / 10.0)
                    alpha = int((45 if over else 185) * fade)
                    colour = ramp(spd[i], window)
                    fsd.line([a, b], fill=colour + (alpha,), width=max(1, int(1.1 * k)))
                    if not over:
                        fgd.line([a, b], fill=colour + (int(alpha * 0.7),),
                                 width=max(1, int(3.3 * k)))
        c = [P(p) for p in item["corners_px"]]
        floor = [c[i] for i in (1, 3, 7, 5)]
        if all(p is not None for p in floor):
            fsd.polygon(floor, fill=COLOURS["box"] + (24,))

    for item in geo["aircraft"]:
        c = [P(p) for p in item["corners_px"]]
        # Edges, corner brackets and the nose face.
        for a, b in EDGES:
            line(c[a], c[b], COLOURS["box"], 1.4 * k, alpha=170)
        for i in range(8):
            if c[i] is None:
                continue
            for a, b in EDGES:
                if i in (a, b):
                    j = b if i == a else a
                    if c[j] is None:
                        continue
                    t = 0.22
                    line(c[i], (c[i][0] + (c[j][0] - c[i][0]) * t,
                                c[i][1] + (c[j][1] - c[i][1]) * t), COLOURS["box"], 3.2 * k)
        for a, b in NOSE_FACE:
            line(c[a], c[b], COLOURS["nose"], 2.2 * k)
        for d in item["dimension_labels"]:
            tag(P(d["at_px"]), d["text"], COLOURS["box"], small)
        for ax, colour in zip(item["body_axes"], ("axis_x", "axis_y", "axis_z")):
            a, b = P(ax["from_px"]), P(ax["to_px"])
            line(a, b, COLOURS[colour], 1.6 * k)
            if a and b:
                arrowhead(a, b, COLOURS[colour], 7 * k)
        for arrow in item.get("arrows", []):
            colour = tuple(arrow["colour_rgb"])
            a, b = P(arrow["from_px"]), P(arrow["to_px"])
            if a is None or b is None:
                continue
            if arrow.get("dashed"):
                dashed(a, b, colour, 2.2 * k, 9 * k)
            else:
                line(a, b, colour, 3.4 * k)
            if math.dist(a, b) < 10 * k:          # pointing at / away from the camera
                r = 7 * k
                sd.ellipse([b[0] - r, b[1] - r, b[0] + r, b[1] + r], outline=colour + (255,),
                           width=int(2 * k))
            else:
                arrowhead(a, b, colour, 16 * k)
            tag(b, arrow["label"], colour, font, anchor_left=b[0] >= a[0])
        cg = P(item["cg_px"])
        if cg is not None:
            r = 6 * k
            sd.ellipse([cg[0] - r, cg[1] - r, cg[0] + r, cg[1] + r], outline=(255, 255, 255, 255),
                       width=int(1.6 * k))
            sd.pieslice([cg[0] - r, cg[1] - r, cg[0] + r, cg[1] + r], 0, 90, fill=(255, 255, 255, 255))
            sd.pieslice([cg[0] - r, cg[1] - r, cg[0] + r, cg[1] + r], 180, 270, fill=(255, 255, 255, 255))
        if not item.get("has_physics"):
            vis = [p for p in c if p is not None]
            if vis:
                tag((min(p[0] for p in vis), min(p[1] for p in vis) - 10 * k),
                    f"{item['id']}  {item['range_m']:.0f} m", COLOURS["box"], small)
        if item.get("physics_values"):
            main_physics = (item, item["physics_values"])

    # Panels.
    pad = 10 * k
    if main_physics:
        item, physics = main_physics
        state_rows, force_rows = _panel_rows(physics)
        _panel(sd, (pad, pad + 26 * k), "FLIGHT STATE // " + item["id"].upper(), state_rows,
               font, title, k, COLOURS["box"])
        _force_panel(sd, (W * SS - pad, pad + 26 * k), physics, force_rows, font, title, small,
                     k, item.get("airflow"))
    # Header and footer bars.
    header = (f"FLIGHTSIM // AERO-ANALYSIS   CAM {str(record.get('camera_id')).upper()}   "
              f"FRAME {int(record.get('index', 0)):04d}   T+{float(record.get('t_s') or 0):.3f} s")
    sd.rectangle([0, 0, W * SS, 22 * k], fill=COLOURS["panel"] + (200,))
    sd.line([0, 22 * k, W * SS, 22 * k], fill=COLOURS["box"] + (160,), width=max(1, int(k)))
    sd.text((pad, 4 * k), header, font=title, fill=COLOURS["box"] + (255,))
    foot = ("box: 3-D extents (cyan) \u00b7 nose face (magenta) \u00b7 body axes x/y/z at CG"
            "   forces: JSBSim state at this frame   airflow: potential-flow + lifting-line model")
    sd.rectangle([0, H * SS - 20 * k, W * SS, H * SS], fill=COLOURS["panel"] + (200,))
    sd.text((pad, H * SS - 16 * k), foot, font=small, fill=COLOURS["dim"] + (255,))

    out = Image.alpha_composite(big, fglow.filter(ImageFilter.GaussianBlur(4 * k)))
    out = Image.alpha_composite(out, fsharp)
    if aircraft_pixels is not None:
        crisp = base.resize(big.size, Image.BICUBIC).convert("RGBA")
        out.paste(crisp, (0, 0), aircraft_pixels)
    glow = glow.filter(ImageFilter.GaussianBlur(5 * k))
    out = Image.alpha_composite(out, glow)
    out = Image.alpha_composite(out, sharp)
    out = out.convert("RGB").resize((W, H), Image.LANCZOS)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    out.save(target)
    return target


def _aircraft_pixels(record: Dict, source, geo: Dict, size):
    """An L mask (at ``size``) of every aircraft's pixels, from the frame's
    ID image when the run wrote one (``frame_NNNN_mask.png`` beside it);
    None when there is none."""
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        return None
    src = Path(source)
    mask_path = src.with_name(src.stem + "_mask.png")
    if not mask_path.is_file():
        return None
    entries = (record.get("labels") or {}).get("objects") or []
    wanted = {str(a["id"]) for a in geo["aircraft"]}
    ids = sorted({int(e["int_id"]) for e in entries if isinstance(e, dict)
                  and str(e.get("id")) in wanted and e.get("int_id") is not None})
    if not ids:
        return None
    try:
        mask = Image.open(mask_path).convert("L")
    except OSError:
        return None
    table = [255 if v in ids else 0 for v in range(256)]
    picked = mask.point(table)
    if picked.getbbox() is None:
        return None
    return picked.resize(size, Image.NEAREST).filter(ImageFilter.GaussianBlur(1.2))


def _main_rect(record: Dict, geo: Dict):
    """The main aircraft's 2-D box (pixels) when there is no ID image: the
    airflow is drawn faint over it so the plane is not buried."""
    main = next((a["id"] for a in geo["aircraft"] if a.get("has_physics")), None)
    for e in (record.get("labels") or {}).get("objects") or []:
        if isinstance(e, dict) and str(e.get("id")) == main:
            box = e.get("bbox_2d_tight") or e.get("bbox_2d")
            if isinstance(box, (list, tuple)) and len(box) == 4:
                return [float(v) for v in box]
    return None


def _panel(draw, origin, heading, rows, font, title, k, accent):
    x, y = origin
    lw = max(draw.textbbox((0, 0), r[0], font=font)[2] for r in rows) + 12 * k
    vw = max(draw.textbbox((0, 0), r[1], font=font)[2] for r in rows)
    hw = draw.textbbox((0, 0), heading, font=title)[2]
    w = max(lw + vw, hw) + 20 * k
    rh = 16 * k
    h = 26 * k + rh * len(rows) + 8 * k
    draw.rectangle([x, y, x + w, y + h], fill=(6, 12, 20, 175), outline=accent + (140,),
                   width=max(1, int(k)))
    draw.rectangle([x, y, x + w, y + 20 * k], fill=accent + (40,))
    draw.text((x + 8 * k, y + 4 * k), heading, font=title, fill=accent + (255,))
    for i, (label, value) in enumerate(rows):
        ty = y + 26 * k + i * rh
        draw.text((x + 10 * k, ty), label, font=font, fill=(120, 170, 190, 255))
        draw.text((x + 10 * k + lw, ty), value, font=font, fill=(225, 245, 255, 255))
    return (x, y, x + w, y + h)


def _force_panel(draw, right_top, physics, rows, font, title, small, k, flow):
    """Force bars to one scale, the ratios, and the airflow colour key."""
    forces = physics["forces"]
    names = ("lift", "weight", "thrust", "drag")
    top = max(float(forces[n]["magnitude_n"]) for n in names) or 1.0
    w = 300 * k
    rh = 16 * k
    bars_h = len(names) * 20 * k
    extra = rows[len(names):]
    h = 26 * k + bars_h + 8 * k + rh * len(extra) + (52 * k if flow else 0) + 8 * k
    x1, y = right_top
    x = x1 - w
    accent = COLOURS["box"]
    draw.rectangle([x, y, x1, y + h], fill=(6, 12, 20, 175), outline=accent + (140,),
                   width=max(1, int(k)))
    draw.rectangle([x, y, x1, y + 20 * k], fill=accent + (40,))
    draw.text((x + 8 * k, y + 4 * k), "FORCES & AERODYNAMICS", font=title, fill=accent + (255,))
    bx0 = x + 78 * k
    bx1 = x1 - 96 * k
    for i, n in enumerate(names):
        ty = y + 28 * k + i * 20 * k
        mag = float(forces[n]["magnitude_n"])
        colour = COLOURS[n]
        draw.text((x + 10 * k, ty), n.upper(), font=font, fill=colour + (255,))
        draw.rectangle([bx0, ty + 2 * k, bx1, ty + 12 * k], fill=(255, 255, 255, 22))
        draw.rectangle([bx0, ty + 2 * k, bx0 + (bx1 - bx0) * mag / top, ty + 12 * k],
                       fill=colour + (220,))
        draw.text((bx1 + 8 * k, ty), f"{mag / 1000.0:,.2f} kN", font=font, fill=(225, 245, 255, 255))
    ty = y + 28 * k + bars_h + 4 * k
    for label, value in extra:
        draw.text((x + 10 * k, ty), label, font=font, fill=(120, 170, 190, 255))
        draw.text((x + 110 * k, ty), value, font=font, fill=(225, 245, 255, 255))
        ty += rh
    if flow:
        lo_w, hi_w = flow["colour_ramp"]["speed_ratio_range"]
        ty += 6 * k
        draw.text((x + 10 * k, ty), "AIRFLOW  local speed / free stream", font=small,
                  fill=(120, 170, 190, 255))
        ty += 16 * k
        gx0, gx1 = x + 10 * k, x1 - 10 * k
        steps = 60
        for i in range(steps):
            r = lo_w + (hi_w - lo_w) * i / (steps - 1)
            xa = gx0 + (gx1 - gx0) * i / steps
            draw.rectangle([xa, ty, xa + (gx1 - gx0) / steps + 1, ty + 8 * k],
                           fill=ramp(r, (lo_w, hi_w)) + (255,))
        ty += 11 * k
        draw.text((gx0, ty), f"{lo_w:.3f} slow", font=small, fill=(150, 190, 210, 255))
        mid = "1.00 = " + f"{physics['velocity']['true_airspeed_kt']:.0f} kt"
        mw = draw.textbbox((0, 0), mid, font=small)[2]
        draw.text(((gx0 + gx1) / 2 - mw / 2, ty), mid, font=small, fill=(150, 190, 210, 255))
        fast = f"fast {hi_w:.3f}"
        fw = draw.textbbox((0, 0), fast, font=small)[2]
        draw.text((gx1 - fw, ty), fast, font=small, fill=(150, 190, 210, 255))


# -- the JSON twin -----------------------------------------------------------

def overlay_json(geometry: Dict, keep_every: int = 3) -> Dict:
    """The geometry as it goes in the frame's JSON: everything drawn, with
    the streamlines thinned to every ``keep_every``-th point (pixels and
    camera metres, rounded) so the file stays readable."""
    out = {"image_size_px": geometry.get("image_size_px"), "aircraft": []}
    for item in geometry["aircraft"]:
        entry = {k: v for k, v in item.items() if k not in ("airflow", "physics_values")}
        flow = item.get("airflow")
        if flow:
            lines = []
            for ln in flow["lines"]:
                idx = list(range(0, len(ln["points_px"]), keep_every))
                if idx[-1] != len(ln["points_px"]) - 1:
                    idx.append(len(ln["points_px"]) - 1)
                lines.append({
                    "points_px": [_r(ln["points_px"][i], 1) for i in idx],
                    "points_camera_m": [_r(ln["points_camera_m"][i], 3) for i in idx],
                    "speed_ratio": [_r(ln["speed_ratio"][i], 4) for i in idx],
                })
            entry["airflow"] = {k: v for k, v in flow.items() if k != "lines"}
            entry["airflow"]["points_kept"] = f"every {keep_every}th integration step"
            entry["airflow"]["lines"] = lines
        out["aircraft"].append(entry)
    return out


def frame_sidecar(manifest: Dict, record: Dict, box_3d: Dict) -> Dict:
    """The full per-frame JSON: the frame, the camera, the box section
    (unchanged), the flight physics and the overlay geometry."""
    geometry = overlay_geometry(manifest, record)
    physics = next((a["physics_values"] for a in geometry["aircraft"]
                    if a.get("physics_values")), None)
    state_rows, force_rows = _panel_rows(physics) if physics else ([], [])
    conditions = manifest.get("conditions") or {}
    return {
        "camera_id": record.get("camera_id"),
        "frame_index": record.get("index"),
        "t_s": record.get("t_s"),
        "about": ("This file is the picture beside it in numbers: the 3-D box "
                  "(box_3d), the flight physics of the frame (flight_physics: every "
                  "force as a vector in body / NED / camera axes with its magnitude, "
                  "velocity, air data, coefficients, energy) and every element drawn "
                  "(overlay: the box corners, the force and velocity arrows, the "
                  "airflow streamlines and the panel values, in camera metres and "
                  "pixels)."),
        "panels": {"flight_state": dict(state_rows), "forces": dict(force_rows)},
        "flight_physics": physics,
        "box_3d": box_3d,
        "overlay": overlay_json(geometry),
        "camera": {
            "width_px": record.get("width_px"), "height_px": record.get("height_px"),
            "focal_length_mm": record.get("focal_length_mm"),
            "fx_px": record.get("fx_px"), "fy_px": record.get("fy_px"),
            "principal_point_px": record.get("principal_point_px"),
            "position_ned_m": [record.get("position_north_m"), record.get("position_east_m"),
                               record.get("position_alt_m")],
            "yaw_pitch_roll_deg": [record.get("yaw_deg"), record.get("pitch_deg"),
                                   record.get("roll_deg")],
            "quaternion_wxyz": record.get("quaternion_wxyz"),
        },
        "scene": {k: (v.get("value") if isinstance(v, dict) else v)
                  for k, v in conditions.items()},
    }
