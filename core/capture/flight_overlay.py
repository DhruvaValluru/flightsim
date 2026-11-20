"""The 3-D box pictures of a frame, and their JSON twin.

Two pictures per frame, one look (a restrained green instrument style,
no neon, no glow), and the plane always readable underneath:

* PLAIN (``frame_NNNN_box3d.png``): the frame with each aircraft's 3-D
  box -- thin edges, corner brackets, the nose face -- and a small tag
  (id, length x span x height, range). Nothing else.
* DETAILED (``frame_NNNN_box3d_detailed.png``): the same box plus, for
  the aircraft the flight model flew,
  - the airflow: streamlines round the airframe from
    :func:`core.capture.flight_physics.airflow_streamlines` (fuselage
    body + aerofoil sections carrying the frame's lift + tip vortices),
    shaded by local airspeed; hidden where the rendered aircraft is in
    front of them (the frame's depth image), faint where they cross it;
  - the forces from the CG -- lift, weight, thrust, drag, and the net
    force when it is not negligible -- to one scale, each labelled in kN,
    and the velocity off the nose; the labels keep off the plane;
  - the FLIGHT STATE and FORCES & AERODYNAMICS panels.

Every number drawn is the flight model's state at that frame
(:func:`core.capture.flight_physics.frame_physics`). Over the aircraft's
own pixels (the frame's ID image) every overlay is drawn at reduced
strength, so the plane is never buried.

:func:`overlay_geometry` computes everything drawn, in camera metres AND
pixels; the frame's JSON carries exactly that, so it is the pictures in
numbers.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .box3d import EDGES, NOSE_FACE, _intrinsics, facing, project, rebuild_corners
from .flight_physics import airflow_streamlines, frame_physics

#: The arrow scale, stated in the JSON: a force F is drawn
#: ARROW_K x reference length x sqrt(F / weight) long (sqrt so thrust and
#: drag, a tenth of the weight, still read beside lift and weight).
ARROW_K = 0.5
ARROW_MIN_FRACTION = 0.004          # forces under 0.4 % of weight are not drawn
NET_MIN_FRACTION = 0.03             # the net force is drawn above 3 % of weight

#: The palette: one green family for the instrument (box, text, panels)
#: and muted, distinguishable tints for the four forces.
COLOURS = {
    "box": (110, 225, 150), "bracket": (150, 245, 180), "nose": (200, 255, 210),
    "lift": (140, 240, 160), "weight": (225, 205, 120), "thrust": (120, 215, 205),
    "drag": (235, 150, 130), "net": (235, 245, 235), "velocity": (200, 235, 140),
    "text": (215, 240, 220), "dim": (130, 175, 145), "panel": (5, 16, 10),
    "header": (3, 10, 6), "axis_x": (235, 150, 130), "axis_y": (140, 240, 160),
    "axis_z": (120, 215, 205),
}
#: Airflow shading over speed ratio: deep sea-green (slow) -> green ->
#: pale lime -> near white (fast).
RAMP = [(40, 120, 110), (70, 175, 130), (120, 225, 150), (200, 245, 165), (245, 255, 235)]
#: The default window the shading spans (|u| / V; 1 = free stream); each
#: frame states the window it used.
RAMP_RANGE = (0.94, 1.06)
#: Overlay strength over the aircraft's own pixels (1 = full).
OVER_PLANE = 0.45


def ramp(ratio: float, window: Sequence[float] = RAMP_RANGE) -> Tuple[int, int, int]:
    lo, hi = window
    t = min(1.0, max(0.0, (ratio - lo) / ((hi - lo) or 1.0))) * (len(RAMP) - 1)
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


_MEMO: List = []


def overlay_geometry(manifest: Optional[Dict], record: Dict, airflow: bool = True) -> Dict:
    """Memoised :func:`_overlay_geometry` (one zip build draws two pictures
    and writes the JSON from the same numbers; the airflow is the cost)."""
    for m_, r_, a_, out_ in _MEMO:
        if m_ is manifest and r_ is record and a_ == airflow:
            return out_
    out_ = _overlay_geometry(manifest, record, airflow)
    _MEMO.append((manifest, record, airflow, out_))
    del _MEMO[:-6]
    return out_


def _overlay_geometry(manifest: Optional[Dict], record: Dict, airflow: bool = True) -> Dict:
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

        tight = entry.get("bbox_2d_tight") or entry.get("bbox_2d")
        item = {"id": str(entry.get("id")),
                "bbox_2d_px": ([round(float(v), 2) for v in tight]
                               if isinstance(tight, (list, tuple)) and len(tight) == 4 else None),
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
            flow = (airflow_streamlines(physics, extents, body_of(centre),
                                        (manifest or {}).get("airframe"))
                    if airflow else None)
            if flow is not None:
                lines = []
                for line in flow["lines"]:
                    pts = [cam(p) for p in line["points_body_m"]]
                    lines.append({"kind": line.get("kind"), "points_camera_m": pts,
                                  "points_px": [px(p) for p in pts],
                                  "speed_ratio": line["speed_ratio"]})
                every = sorted(x for ln in lines for x in ln["speed_ratio"])
                lo = every[int(0.03 * (len(every) - 1))]
                hi = every[int(0.97 * (len(every) - 1))]
                spread = max(hi - 1.0, 1.0 - lo, 0.01)
                window = [round(1.0 - spread, 4), round(1.0 + spread, 4)]
                item["airflow"] = {"model": flow["model"], "parameters": flow["parameters"],
                                   "geometry": flow.get("geometry"),
                                   "occlusion": ("segments behind the frame's depth image "
                                                 "(the rendered aircraft or terrain in front) "
                                                 "are not drawn; over the aircraft's own pixels "
                                                 f"every overlay is drawn at {OVER_PLANE} strength"),
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

SS = 2                                  # supersampling factor


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


def _passes(record: Dict, source, geo: Dict):
    """(aircraft mask L-image at the frame size or None, depth getter or
    None) from the frame's ID image and depth pass beside it."""
    from PIL import Image

    src = Path(source)
    mask = None
    mask_path = src.with_name(src.stem + "_mask.png")
    if mask_path.is_file():
        entries = (record.get("labels") or {}).get("objects") or []
        wanted = {str(a["id"]) for a in geo["aircraft"]}
        ids = sorted({int(e["int_id"]) for e in entries if isinstance(e, dict)
                      and str(e.get("id")) in wanted and e.get("int_id") is not None})
        if ids:
            try:
                picked = Image.open(mask_path).convert("L").point(
                    [255 if v in ids else 0 for v in range(256)])
                mask = picked if picked.getbbox() is not None else None
            except OSError:
                mask = None
    depth = None
    depth_path = src.with_name(src.stem + "_depth.f32")
    gw, gh = geo.get("image_size_px") or (0, 0)
    if depth_path.is_file() and gw and gh:
        try:
            import numpy as np

            raw = np.fromfile(depth_path, dtype="<f4")
            if raw.size == gw * gh:
                grid = raw.reshape(gh, gw)

                def depth(p):
                    x, y = int(p[0]), int(p[1])
                    if 0 <= x < gw and 0 <= y < gh:
                        z = float(grid[y, x])
                        return z if math.isfinite(z) else None
                    return None
        except (OSError, ValueError, ImportError):
            depth = None
    return mask, depth


class _Canvas:
    """The supersampled drawing surface: the frame plate and three layers
    (airflow, instrument, labels/panels), composited with the plane kept
    readable."""

    def __init__(self, base, geo, mask):
        from PIL import Image, ImageDraw, ImageEnhance

        self.base = base
        self.W, self.H = base.size
        gw, gh = geo.get("image_size_px") or (self.W, self.H)
        self.sx, self.sy = self.W / float(gw or self.W), self.H / float(gh or self.H)
        self.u = max(self.H / 720.0, 0.45)
        self.k = SS * self.u
        size = (self.W * SS, self.H * SS)
        plate = ImageEnhance.Brightness(base).enhance(0.9)
        if mask is not None:
            plate.paste(base, (0, 0), mask.resize(base.size, Image.NEAREST))
        self.plate = plate.resize(size, Image.BICUBIC).convert("RGBA")
        self.mask = (mask.resize(size, Image.NEAREST) if mask is not None else None)
        self.layers = {n: Image.new("RGBA", size, (0, 0, 0, 0)) for n in ("flow", "inst", "top")}
        self.draw = {n: ImageDraw.Draw(img) for n, img in self.layers.items()}
        self.limit = 8.0 * max(self.W, self.H) * SS
        self.placed = []

    def P(self, p):
        if p is None:
            return None
        lim = self.limit
        return (max(-lim, min(lim, p[0] * self.sx * SS)), max(-lim, min(lim, p[1] * self.sy * SS)))

    def avoid(self, rect_px):
        if rect_px:
            x0, y0, x1, y1 = rect_px
            m = 4 * self.k
            self.placed.append((x0 * self.sx * SS - m, y0 * self.sy * SS - m,
                                x1 * self.sx * SS + m, y1 * self.sy * SS + m))

    def line(self, layer, a, b, colour, w, alpha=255, outline=False):
        if a is None or b is None:
            return
        d = self.draw[layer]
        if outline:
            d.line([a, b], fill=(0, 0, 0, int(alpha * 0.45)), width=max(1, int(w + 2 * self.k)))
        d.line([a, b], fill=colour + (int(alpha),), width=max(1, int(w)))

    def arrowhead(self, layer, a, b, colour, size, alpha=255):
        L = math.dist(a, b)
        if L < 1:
            return
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        s = min(size, L * 0.4)
        left = (b[0] - ux * s - uy * s * 0.36, b[1] - uy * s + ux * s * 0.36)
        right = (b[0] - ux * s + uy * s * 0.36, b[1] - uy * s - ux * s * 0.36)
        self.draw[layer].polygon([b, left, right], fill=colour + (int(alpha),),
                                 outline=(0, 0, 0, int(alpha * 0.5)))

    def tag(self, at, text, colour, font, leader=True):
        if at is None:
            return
        d, k = self.draw["top"], self.k
        x0, y0, x1, y1 = d.textbbox((0, 0), text, font=font)
        tw, th = x1 - x0, y1 - y0
        pad = 3.5 * k
        bw, bh = tw + 2 * pad + 3 * k, th + 2 * pad
        Wd, Hd = self.W * SS, self.H * SS
        x = max(2 * k, min(at[0] + 8 * k, Wd - bw - 2 * k))
        y = max(26 * k, min(at[1] - bh / 2, Hd - bh - 24 * k))
        for step in range(60):
            hit = next((q for q in self.placed if x < q[2] and x + bw > q[0]
                        and y < q[3] and y + bh > q[1]), None)
            if hit is None:
                break
            # Step past the obstacle: below it, or above when below is full.
            if hit[3] + 3 * k + bh < Hd - 24 * k and step < 30:
                y = hit[3] + 3 * k
            else:
                y = hit[1] - bh - 3 * k
        self.placed.append((x, y, x + bw, y + bh))
        if leader and math.dist((x, y + bh / 2), at) > 12 * k:
            d.line([at, (x, y + bh / 2)], fill=colour + (150,), width=max(1, int(0.8 * k)))
        d.rectangle([x, y, x + bw, y + bh], fill=COLOURS["panel"] + (205,),
                    outline=colour + (90,), width=max(1, int(0.7 * k)))
        d.rectangle([x, y, x + 2 * k, y + bh], fill=colour + (230,))
        d.text((x + pad + 3 * k - x0, y + pad - y0), text, font=font, fill=colour + (255,))

    def finish(self, target):
        from PIL import Image, ImageChops

        out = self.plate
        for name in ("flow", "inst", "top"):
            layer = self.layers[name]
            if self.mask is not None and name != "top":
                keep = self.mask.point(lambda v: 255 - int(v * (1.0 - OVER_PLANE)))
                r, g, b, a = layer.split()
                layer = Image.merge("RGBA", (r, g, b, ImageChops.multiply(a, keep)))
            out = Image.alpha_composite(out, layer)
        out = out.convert("RGB").resize((self.W, self.H), Image.LANCZOS)
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        out.save(target)
        return target


def _draw_box(cv: _Canvas, item: Dict, detailed: bool):
    k = cv.k
    c = [cv.P(p) for p in item["corners_px"]]
    for a, b in EDGES:
        cv.line("inst", c[a], c[b], COLOURS["box"], 1.1 * k, alpha=165)
    for i in range(8):
        if c[i] is None:
            continue
        for a, b in EDGES:
            if i in (a, b):
                j = b if i == a else a
                if c[j] is None:
                    continue
                t = 0.18
                cv.line("inst", c[i], (c[i][0] + (c[j][0] - c[i][0]) * t,
                                       c[i][1] + (c[j][1] - c[i][1]) * t),
                        COLOURS["bracket"], 2.4 * k, alpha=235)
    for a, b in NOSE_FACE:
        cv.line("inst", c[a], c[b], COLOURS["nose"], 1.6 * k, alpha=210)
    return c


def draw_plain_frame(record: Dict, source, target, manifest: Optional[Dict] = None,
                     geometry: Optional[Dict] = None) -> Path:
    """Write ``target``: the frame with each aircraft's 3-D box only."""
    from PIL import Image

    base = Image.open(source).convert("RGB")
    geo = geometry or overlay_geometry(manifest, record, airflow=False)
    mask, _ = _passes(record, source, geo)
    cv = _Canvas(base, geo, mask)
    small = _font(int(10.5 * cv.k))
    for item in geo["aircraft"]:
        cv.avoid(item.get("bbox_2d_px"))
    for item in geo["aircraft"]:
        c = _draw_box(cv, item, detailed=False)
        vis = [p for p in c if p is not None]
        if vis:
            e = item["extents_m"]
            text = (f"{item['id']}   {e['length']:.1f} x {e['width']:.1f} x "
                    f"{e['height']:.1f} m   {item['range_m']:.0f} m")
            top = min(vis, key=lambda p: p[1])
            cv.tag((min(p[0] for p in vis), top[1] - 6 * cv.k), text, COLOURS["box"], small,
                   leader=False)
    return cv.finish(target)


def draw_flight_frame(record: Dict, source, target, manifest: Optional[Dict] = None,
                      geometry: Optional[Dict] = None) -> Path:
    """Write ``target``: the detailed picture (box, airflow, forces,
    velocity, panels) of :func:`overlay_geometry`."""
    from PIL import Image

    base = Image.open(source).convert("RGB")
    geo = geometry or overlay_geometry(manifest, record)
    mask, depth = _passes(record, source, geo)
    cv = _Canvas(base, geo, mask)
    k = cv.k
    font = _font(int(11 * k))
    small = _font(int(9.5 * k))
    title = _font(int(11.5 * k))
    for item in geo["aircraft"]:
        cv.avoid(item.get("bbox_2d_px"))

    main = None
    for item in geo["aircraft"]:
        flow = item.get("airflow")
        if flow:
            window = flow["colour_ramp"]["speed_ratio_range"]
            for ln in flow["lines"]:
                pts, cams, spd = ln["points_px"], ln["points_camera_m"], ln["speed_ratio"]
                n = len(pts)
                strong = ln.get("kind") in ("wing", "wingtip")
                width = (1.35 if strong else 1.0) * k
                peak = 215.0 if strong else 160.0
                for i in range(n - 1):
                    a, b = cv.P(pts[i]), cv.P(pts[i + 1])
                    if a is None or b is None:
                        continue
                    alpha = peak * min(1.0, i / 14.0) * min(1.0, (n - 1 - i) / 14.0)
                    if depth is not None:
                        z_surface = depth(pts[i])
                        if z_surface is not None and cams[i][2] > z_surface + 0.1 + 0.004 * z_surface:
                            continue            # the aircraft (or terrain) is in front
                    # A faint dark underlay keeps the line legible on bright ground.
                    cv.line("flow", a, b, ramp(spd[i], window), width, alpha=alpha,
                            outline=True)
        _draw_box(cv, item, detailed=True)
        for d in item.get("dimension_labels", []):
            cv.tag(cv.P(d["at_px"]), d["text"], COLOURS["dim"], small, leader=False)
        for ax, colour in zip(item.get("body_axes", []), ("axis_x", "axis_y", "axis_z")):
            a, b = cv.P(ax["from_px"]), cv.P(ax["to_px"])
            cv.line("inst", a, b, COLOURS[colour], 1.2 * k, alpha=200)
            if a and b:
                cv.arrowhead("inst", a, b, COLOURS[colour], 6 * k, alpha=200)
        for arrow in item.get("arrows", []):
            colour = tuple(arrow["colour_rgb"])
            a, b = cv.P(arrow["from_px"]), cv.P(arrow["to_px"])
            if a is None or b is None:
                continue
            if arrow.get("dashed"):
                L = math.dist(a, b)
                steps = max(1, int(L // (7 * k)))
                for i in range(0, steps, 2):
                    t0, t1 = i / steps, min(1.0, (i + 1) / steps)
                    cv.line("inst", (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                            (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1),
                            colour, 1.6 * k, alpha=230, outline=True)
            else:
                cv.line("inst", a, b, colour, 2.2 * k, alpha=240, outline=True)
            if math.dist(a, b) < 10 * k:
                r = 6 * k
                cv.draw["inst"].ellipse([b[0] - r, b[1] - r, b[0] + r, b[1] + r],
                                        outline=colour + (240,), width=max(1, int(1.6 * k)))
            else:
                cv.arrowhead("inst", a, b, colour, 13 * k, alpha=245)
            cv.tag(b, arrow["label"], colour, font)
        cg = cv.P(item.get("cg_px"))
        if cg is not None and item.get("has_physics"):
            r = 4.5 * k
            d = cv.draw["inst"]
            d.ellipse([cg[0] - r, cg[1] - r, cg[0] + r, cg[1] + r],
                      outline=(235, 245, 235, 255), width=max(1, int(1.2 * k)))
            d.pieslice([cg[0] - r, cg[1] - r, cg[0] + r, cg[1] + r], 0, 90, fill=(235, 245, 235, 255))
            d.pieslice([cg[0] - r, cg[1] - r, cg[0] + r, cg[1] + r], 180, 270,
                       fill=(235, 245, 235, 255))
        if item.get("physics_values"):
            main = item

    pad = 10 * k
    top = cv.draw["top"]
    if main is not None:
        physics = main["physics_values"]
        state_rows, force_rows = _panel_rows(physics)
        _panel(top, (pad, 30 * k), "FLIGHT STATE  " + main["id"], state_rows, font, title, k)
        _force_panel(top, (cv.W * SS - pad, 30 * k), physics, force_rows, font, title, small, k,
                     main.get("airflow"))
    header = (f"FLIGHTSIM  AERODYNAMICS   cam {record.get('camera_id')}   "
              f"frame {int(record.get('index', 0)):04d}   t {float(record.get('t_s') or 0):.3f} s")
    top.rectangle([0, 0, cv.W * SS, 20 * k], fill=COLOURS["header"] + (215,))
    top.line([0, 20 * k, cv.W * SS, 20 * k], fill=COLOURS["box"] + (120,), width=max(1, int(0.8 * k)))
    top.text((pad, 4 * k), header, font=title, fill=COLOURS["text"] + (255,))
    foot = ("forces & state: JSBSim flight model at this frame   airflow: potential flow "
            "(fuselage + aerofoil sections carrying this lift + tip vortices), shaded by "
            "local speed")
    top.rectangle([0, cv.H * SS - 18 * k, cv.W * SS, cv.H * SS], fill=COLOURS["header"] + (215,))
    top.text((pad, cv.H * SS - 15 * k), foot, font=small, fill=COLOURS["dim"] + (255,))
    return cv.finish(target)


def _panel(draw, origin, heading, rows, font, title, k):
    x, y = origin
    lw = max(draw.textbbox((0, 0), r[0], font=font)[2] for r in rows) + 12 * k
    vw = max(draw.textbbox((0, 0), r[1], font=font)[2] for r in rows)
    hw = draw.textbbox((0, 0), heading, font=title)[2]
    w = max(lw + vw, hw) + 20 * k
    rh = 14.5 * k
    h = 24 * k + rh * len(rows) + 6 * k
    draw.rectangle([x, y, x + w, y + h], fill=COLOURS["panel"] + (195,),
                   outline=COLOURS["box"] + (90,), width=max(1, int(0.8 * k)))
    draw.rectangle([x, y, x + w, y + 18 * k], fill=COLOURS["header"] + (235,))
    draw.line([x, y + 18 * k, x + w, y + 18 * k], fill=COLOURS["box"] + (150,),
              width=max(1, int(0.8 * k)))
    draw.text((x + 8 * k, y + 3.5 * k), heading, font=title, fill=COLOURS["bracket"] + (255,))
    for i, (label, value) in enumerate(rows):
        ty = y + 23 * k + i * rh
        draw.text((x + 9 * k, ty), label, font=font, fill=COLOURS["dim"] + (255,))
        draw.text((x + 9 * k + lw, ty), value, font=font, fill=COLOURS["text"] + (255,))


def _force_panel(draw, right_top, physics, rows, font, title, small, k, flow):
    """Force bars to one scale, the ratios, and the airflow shading key."""
    forces = physics["forces"]
    names = ("lift", "weight", "thrust", "drag")
    topv = max(float(forces[n]["magnitude_n"]) for n in names) or 1.0
    w = 270 * k
    rh = 14.5 * k
    extra = rows[len(names):]
    h = 24 * k + len(names) * 17 * k + 6 * k + rh * len(extra) + (44 * k if flow else 0) + 6 * k
    x1, y = right_top
    x = x1 - w
    draw.rectangle([x, y, x1, y + h], fill=COLOURS["panel"] + (195,),
                   outline=COLOURS["box"] + (90,), width=max(1, int(0.8 * k)))
    draw.rectangle([x, y, x1, y + 18 * k], fill=COLOURS["header"] + (235,))
    draw.line([x, y + 18 * k, x1, y + 18 * k], fill=COLOURS["box"] + (150,),
              width=max(1, int(0.8 * k)))
    draw.text((x + 8 * k, y + 3.5 * k), "FORCES & AERODYNAMICS", font=title,
              fill=COLOURS["bracket"] + (255,))
    bx0, bx1 = x + 70 * k, x1 - 86 * k
    for i, n in enumerate(names):
        ty = y + 25 * k + i * 17 * k
        mag = float(forces[n]["magnitude_n"])
        colour = COLOURS[n]
        draw.text((x + 9 * k, ty), n.upper(), font=font, fill=colour + (255,))
        draw.rectangle([bx0, ty + 3 * k, bx1, ty + 10 * k], fill=(255, 255, 255, 18))
        draw.rectangle([bx0, ty + 3 * k, bx0 + (bx1 - bx0) * mag / topv, ty + 10 * k],
                       fill=colour + (210,))
        draw.text((bx1 + 7 * k, ty), f"{mag / 1000.0:,.2f} kN", font=font,
                  fill=COLOURS["text"] + (255,))
    ty = y + 25 * k + len(names) * 17 * k + 3 * k
    for label, value in extra:
        draw.text((x + 9 * k, ty), label, font=font, fill=COLOURS["dim"] + (255,))
        draw.text((x + 100 * k, ty), value, font=font, fill=COLOURS["text"] + (255,))
        ty += rh
    if flow:
        lo_w, hi_w = flow["colour_ramp"]["speed_ratio_range"]
        ty += 5 * k
        draw.text((x + 9 * k, ty), "AIRFLOW  local speed / free stream", font=small,
                  fill=COLOURS["dim"] + (255,))
        ty += 14 * k
        gx0, gx1 = x + 9 * k, x1 - 9 * k
        steps = 60
        for i in range(steps):
            r = lo_w + (hi_w - lo_w) * i / (steps - 1)
            xa = gx0 + (gx1 - gx0) * i / steps
            draw.rectangle([xa, ty, xa + (gx1 - gx0) / steps + 1, ty + 6 * k],
                           fill=ramp(r, (lo_w, hi_w)) + (255,))
        ty += 9 * k
        mid = "1.00 = " + f"{physics['velocity']['true_airspeed_kt']:.0f} kt"
        mw = draw.textbbox((0, 0), mid, font=small)[2]
        fast = f"{hi_w:.3f} fast"
        fw = draw.textbbox((0, 0), fast, font=small)[2]
        draw.text((gx0, ty), f"slow {lo_w:.3f}", font=small, fill=COLOURS["dim"] + (255,))
        draw.text(((gx0 + gx1) / 2 - mw / 2, ty), mid, font=small, fill=COLOURS["dim"] + (255,))
        draw.text((gx1 - fw, ty), fast, font=small, fill=COLOURS["dim"] + (255,))


# -- the JSON twin -----------------------------------------------------------

def overlay_json(geometry: Dict, keep_every: int = 4) -> Dict:
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
                    "kind": ln.get("kind"),
                    "points_px": [_r(ln["points_px"][i], 1) for i in idx],
                    "points_camera_m": [_r(ln["points_camera_m"][i], 3) for i in idx],
                    "speed_ratio": [_r(ln["speed_ratio"][i], 4) for i in idx],
                })
            entry["airflow"] = {k: v for k, v in flow.items() if k != "lines"}
            entry["airflow"]["points_kept"] = f"every {keep_every}th integration step"
            entry["airflow"]["lines"] = lines
        out["aircraft"].append(entry)
    return out


def frame_sidecar(manifest: Dict, record: Dict, box_3d: Dict,
                  pictures: Optional[Dict] = None, airflow: bool = True) -> Dict:
    """The full per-frame JSON: what is in both pictures, the flight
    physics, the box section (unchanged), the camera and the scene."""
    geometry = overlay_geometry(manifest, record, airflow=airflow)
    physics = next((a["physics_values"] for a in geometry["aircraft"]
                    if a.get("physics_values")), None)
    state_rows, force_rows = _panel_rows(physics) if physics else ([], [])
    conditions = manifest.get("conditions") or {}
    detailed = overlay_json(geometry)
    plain = {"image_size_px": detailed["image_size_px"],
             "aircraft": [{k: item[k] for k in ("id", "box_drawn", "corners_m", "corners_px",
                                                 "edges", "nose_face_edges", "extents_m",
                                                 "range_m", "orientation") if k in item}
                          for item in detailed["aircraft"]]}
    return {
        "camera_id": record.get("camera_id"),
        "frame_index": record.get("index"),
        "t_s": record.get("t_s"),
        "about": ("This file is the two pictures beside it in numbers. pictures: which "
                  "file is which. panels: the detailed picture's two panels as printed. "
                  "flight_physics: the flight model's state at this frame -- every force "
                  "as a vector in body / NED / camera axes with its magnitude, the force "
                  "balance, velocity, angles, air data, coefficients, energy, controls. "
                  "box_3d: each aircraft's 3-D box, orientation and rebuild check. "
                  "overlay.plain / overlay.detailed: every element each picture draws, "
                  "in camera metres and pixels (box corners, force and velocity arrows "
                  "with their scale, airflow streamlines with the local speed ratio)."),
        "pictures": pictures or {},
        "palette_rgb": {k: list(v) for k, v in COLOURS.items()
                        if k in ("box", "lift", "weight", "thrust", "drag", "net", "velocity")},
        "panels": {"flight_state": dict(state_rows), "forces": dict(force_rows)},
        "flight_physics": physics,
        "box_3d": box_3d,
        "overlay": {"plain": plain, "detailed": detailed},
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
