"""The flight physics of ONE frame, from that frame's own record.

Every frame record carries ``state``: the JSBSim flight model's state at
the sample the frame shows (lift, drag, side force and the body-axis
aerodynamic force, engine thrust, weight, the velocity and the wind in
north/east/down, angle of attack and sideslip, dynamic pressure, Mach,
temperature, load factor, control surfaces ...). This module turns that
into the per-frame physics the 3-D box picture draws and its JSON states:

* :func:`frame_physics` -- every force as a vector in the body, NED and
  camera frames with its magnitude, the force balance (net force,
  acceleration, load factor recomputed from the forces and compared with
  the flight model's own), velocity and air data (density from the
  dynamic pressure, ISA pressure, speed of sound), the aerodynamic
  coefficients over the flown model's wing area, energy, and the
  lifting-line numbers behind the drawn airflow;
* :func:`airflow_streamlines` -- streamlines of the air past the
  airframe, integrated through a potential-flow model: a Rankine body for
  the fuselage plus a horseshoe vortex for the wing whose circulation is
  the frame's own lift (Kutta-Joukowski, elliptic loading). The model is
  stated in the JSON; it is a fast analytic model, not a CFD solve.

Frames: body = (forward, right, down) metres about the CG; NED = (north,
east, down); camera = (x right, y down, z forward along the view). The
body -> camera rotation is the frame's own ``body_axes_in_camera``, the
same one the drawn box uses, so the arrows sit on the box exactly.
"""

from __future__ import annotations

import functools
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

G0 = 9.80665                      # m/s^2, standard gravity
KT = 0.514444                     # m/s per knot
FT = 0.3048                       # m per foot
R_AIR = 287.05287                 # J/(kg K)
GAMMA_AIR = 1.4
#: The Oswald efficiency used ONLY for the induced-drag estimate (stated).
OSWALD_E = 0.8

Vec = Tuple[float, float, float]


# -- small vector helpers ---------------------------------------------------

def _add(*vs: Sequence[float]) -> Vec:
    return tuple(sum(v[k] for v in vs) for k in range(3))


def _scale(v: Sequence[float], s: float) -> Vec:
    return (v[0] * s, v[1] * s, v[2] * s)


def _norm(v: Sequence[float]) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _unit(v: Sequence[float]) -> Vec:
    n = _norm(v)
    return (0.0, 0.0, 0.0) if n <= 0 else (v[0] / n, v[1] / n, v[2] / n)


def _mat_vec(m: Sequence[Sequence[float]], v: Sequence[float]) -> Vec:
    return tuple(m[r][0] * v[0] + m[r][1] * v[1] + m[r][2] * v[2] for r in range(3))


def _r(v, nd=4):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return [_r(x, nd) for x in v]
    return round(float(v), nd)


def ned_from_body(roll_deg: float, pitch_deg: float, heading_deg: float):
    """The body -> NED rotation (aerospace Z-Y'-X''), rows = NED axes."""
    r, p, y = (math.radians(roll_deg), math.radians(pitch_deg),
               math.radians(heading_deg))
    cr, sr, cp, sp, cy, sy = (math.cos(r), math.sin(r), math.cos(p),
                              math.sin(p), math.cos(y), math.sin(y))
    return [[cp * cy, sr * sp * cy - cr * sy, cr * sp * cy + sr * sy],
            [cp * sy, sr * sp * sy + cr * cy, cr * sp * sy - sr * cy],
            [-sp, sr * cp, cr * cp]]


def _transpose(m):
    return [[m[c][r] for c in range(3)] for r in range(3)]


def isa_pressure_pa(pressure_altitude_m: float) -> float:
    """ISA static pressure at a pressure altitude (troposphere and the
    isothermal layer above it)."""
    h = float(pressure_altitude_m)
    if h <= 11000.0:
        return 101325.0 * (1.0 - 2.25577e-5 * h) ** 5.25588
    return 22632.06 * math.exp(-(h - 11000.0) / 6341.62)


def isa_density(pressure_altitude_m: float, temperature_k: float) -> float:
    return isa_pressure_pa(pressure_altitude_m) / (R_AIR * temperature_k)


# -- the flown model's wing ----------------------------------------------------

_UNIT_M = {"FT": FT, "M": 1.0, "IN": 0.0254}
_UNIT_M2 = {"FT2": FT * FT, "M2": 1.0}


@functools.lru_cache(maxsize=32)
def _wing_from_xml(path: str) -> Optional[Dict]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    metrics = root.find("metrics")
    if metrics is None:
        return None

    def read(tag, units):
        el = metrics.find(tag)
        if el is None or el.text is None:
            return None
        try:
            return float(el.text.split()[0]) * units.get(el.get("unit", "FT").upper(), 1.0)
        except ValueError:
            return None

    area = read("wingarea", {**_UNIT_M2, "FT": FT * FT})
    span = read("wingspan", _UNIT_M)
    chord = read("chord", _UNIT_M)
    if not area or not span:
        return None
    return {"area_m2": area, "span_m": span, "chord_m": chord,
            "source": f"{Path(path).name} <metrics> (wingarea, wingspan, chord)"}


def wing_metrics(manifest: Dict) -> Optional[Dict]:
    """Wing area, span and chord of the model that flew: the manifest's
    recorded FDM XML when this machine has it, else the same file found
    the way the flight model resolves it."""
    airframe = manifest.get("airframe") or {}
    candidates: List[str] = []
    recorded = airframe.get("fdm_xml")
    if isinstance(recorded, dict):
        recorded = recorded.get("path")
    if recorded:
        candidates.append(str(recorded))
    name = airframe.get("aircraft") or manifest.get("aircraft")
    if name:
        try:
            from .airframe import fdm_xml_path

            candidates.append(str(fdm_xml_path(str(name))))
        except Exception:            # noqa: BLE001 -- no FDM install here
            pass
        repo = Path(__file__).resolve().parents[2]
        candidates += [str(repo / "assets" / "fdm_root" / "aircraft" / name / f"{name}.xml"),
                       str(repo / "ue" / "Plugins" / "JSBSimFlightDynamicsModel" / "Resources"
                           / "JSBSim" / "aircraft" / name / f"{name}.xml")]
    for path in candidates:
        if Path(path).is_file():
            wing = _wing_from_xml(path)
            if wing:
                return dict(wing)
    span = airframe.get("span_m")
    return None if not span else {"area_m2": None, "span_m": float(span),
                                  "chord_m": None,
                                  "source": "manifest airframe span_m (no FDM XML here)"}


# -- the physics of one frame -------------------------------------------------

def _f(state: Dict, key: str) -> Optional[float]:
    v = state.get(key)
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _force(name: str, body: Vec, ned_of, cam_of, source: str, **extra) -> Dict:
    mag = _norm(body)
    out = {"name": name, "magnitude_n": _r(mag, 3), "magnitude_kn": _r(mag / 1000.0, 4),
           "vector_body_n": _r(body, 3), "direction_body": _r(_unit(body), 6),
           "vector_ned_n": _r(ned_of(body), 3)}
    if cam_of is not None:
        out["vector_camera_n"] = _r(cam_of(body), 3)
        out["direction_camera"] = _r(_unit(cam_of(body)), 6)
    out.update(extra)
    out["source"] = source
    return out


def frame_physics(manifest: Dict, record: Dict, box: Optional[Dict] = None) -> Optional[Dict]:
    """The physics of this frame's main aircraft (see the module doc), or
    None when the record carries no flight-model state."""
    state = record.get("state")
    if not isinstance(state, dict) or _f(state, "weight_kg") is None:
        return None
    s = lambda k, d=0.0: _f(state, k) if _f(state, k) is not None else d  # noqa: E731
    roll, pitch, heading = s("roll_deg"), s("pitch_deg"), s("heading_deg")
    R_nb = ned_from_body(roll, pitch, heading)
    R_bn = _transpose(R_nb)
    ned_of = lambda v: _mat_vec(R_nb, v)  # noqa: E731
    cam_of = None
    if isinstance(box, dict) and box.get("body_axes_in_camera"):
        axes = [[float(x) for x in row] for row in box["body_axes_in_camera"]]
        cam_of = lambda v: tuple(sum(v[a] * axes[a][k] for a in range(3))  # noqa: E731
                                 for k in range(3))

    mass = s("weight_kg")
    weight = mass * G0
    alpha, beta = math.radians(s("alpha_deg")), math.radians(s("beta_deg"))
    ca, sa, cb, sb = math.cos(alpha), math.sin(alpha), math.cos(beta), math.sin(beta)
    x_w = (ca * cb, sb, sa * cb)              # wind axes, in body
    y_w = (-ca * sb, cb, -sa * sb)
    z_w = (-sa, 0.0, ca)
    lift_n, drag_n, side_n = s("lift_n"), s("drag_n"), s("side_force_n")
    lift_b = _scale(z_w, -lift_n)
    drag_b = _scale(x_w, -drag_n)
    side_b = _scale(y_w, side_n)
    from_wind = _add(lift_b, drag_b, side_b)
    recorded_aero = (None if _f(state, "f_aero_x_n") is None else
                     (s("f_aero_x_n"), s("f_aero_y_n"), s("f_aero_z_n")))
    aero_b = recorded_aero or from_wind
    engines = sorted((int(m.group(1)), float(v)) for k, v in state.items()
                     if (m := re.fullmatch(r"engine(\d+)_thrust_n", k)) and v is not None)
    thrust = sum(v for _, v in engines)
    thrust_b = (thrust, 0.0, 0.0)
    weight_b = _mat_vec(R_bn, (0.0, 0.0, weight))
    net_b = _add(aero_b, thrust_b, weight_b)
    accel_b = _scale(net_b, 1.0 / mass)
    nz_forces = -(aero_b[2] + thrust_b[2]) / weight if weight else None

    # Velocity, wind and the air.
    v_ground = (s("v_north_mps"), s("v_east_mps"), s("v_down_mps"))
    wind = (s("wind_north_mps") + s("gust_north_mps"), s("wind_east_mps") + s("gust_east_mps"),
            s("wind_down_mps") + s("gust_down_mps"))
    v_air_ned = tuple(v_ground[k] - wind[k] for k in range(3))
    tas = s("tas_kt") * KT if _f(state, "tas_kt") is not None else _norm(v_air_ned)
    gs = math.hypot(v_ground[0], v_ground[1])
    track = math.degrees(math.atan2(v_ground[1], v_ground[0])) % 360.0 if gs > 0.1 else None
    temp = s("temperature_k", 288.15)
    p_alt = s("pressure_altitude_m", s("altitude_m"))
    qbar = s("qbar_pa")
    rho = (2.0 * qbar / (tas * tas)) if tas > 1.0 and qbar > 0 else isa_density(p_alt, temp)
    rho_basis = ("2 qbar / TAS^2 from the flight model's dynamic pressure"
                 if tas > 1.0 and qbar > 0 else "ISA at the pressure altitude")
    mach = s("mach")
    a_sound = (tas / mach) if mach > 0.01 else math.sqrt(GAMMA_AIR * R_AIR * temp)
    wind_speed = math.hypot(wind[0], wind[1])
    wind_from = (math.degrees(math.atan2(-wind[1], -wind[0])) % 360.0
                 if wind_speed > 0.05 else None)

    wing = wing_metrics(manifest)
    area = (wing or {}).get("area_m2")
    span = (wing or {}).get("span_m") or (manifest.get("airframe") or {}).get("span_m")
    coeffs = None
    lifting = None
    if area and qbar > 1.0:
        cl, cd, cy = lift_n / (qbar * area), drag_n / (qbar * area), side_n / (qbar * area)
        ar = (span * span / area) if span else None
        cdi = (cl * cl / (math.pi * OSWALD_E * ar)) if ar else None
        coeffs = {"wing_area_m2": _r(area, 3), "span_m": _r(span, 3),
                  "mean_chord_m": _r((wing or {}).get("chord_m"), 3),
                  "aspect_ratio": _r(ar, 3),
                  "CL": _r(cl, 5), "CD": _r(cd, 5), "CY": _r(cy, 5),
                  "lift_to_drag": _r(lift_n / drag_n, 3) if drag_n > 1e-6 else None,
                  "CDi_estimate": _r(cdi, 5),
                  "CDi_basis": (f"CL^2 / (pi e AR) with e = {OSWALD_E} (stated "
                                "estimate, not from the model)"),
                  "source": (wing or {}).get("source")}
    if span and tas > 5.0 and rho > 0:
        b_eff = math.pi * span / 4.0
        gamma0 = 4.0 * lift_n / (rho * tas * math.pi * span)
        ar = coeffs["aspect_ratio"] if coeffs else None
        cl = coeffs["CL"] if coeffs else None
        lifting = {
            "root_circulation_m2_s": _r(gamma0, 3),
            "horseshoe_circulation_m2_s": _r(lift_n / (rho * tas * b_eff), 3),
            "vortex_span_m": _r(b_eff, 3),
            "downwash_angle_deg": _r(math.degrees(2.0 * cl / (math.pi * ar)), 4)
            if cl is not None and ar else None,
            "basis": ("elliptic loading: L = rho V Gamma0 pi b / 4; the trailing "
                      "vortices sit pi b / 4 apart; far-field downwash 2 CL / (pi AR)")}

    vs = -v_ground[2]
    energy_h = s("altitude_m") + tas * tas / (2.0 * G0)
    ps = (thrust - drag_n) * tas / weight if weight else None

    out = {
        "id": f"aircraft:{manifest.get('aircraft')}:0",
        "aircraft_type": manifest.get("aircraft"),
        "time_s": _r(s("t", record.get("t_s") or 0.0), 6),
        "source": ("JSBSim flight-model state at this frame's sample (the frame "
                   "record's 'state'); vectors rotated with the recorded attitude "
                   "and the box's body_axes_in_camera"),
        "frames": {"body": "x forward, y right, z down; metres about the CG",
                   "ned": "x north, y east, z down",
                   "camera": "x right, y down, z forward along the view"},
        "mass": {"mass_kg": _r(mass, 3), "weight_n": _r(weight, 3), "g_mps2": G0},
        "forces": {
            "lift": _force("lift", lift_b, ned_of, cam_of,
                           "state lift_n, perpendicular to the relative wind "
                           "(wind-axes -z through alpha, beta)"),
            "drag": _force("drag", drag_b, ned_of, cam_of,
                           "state drag_n, along the relative wind (wind-axes -x)"),
            "side_force": _force("side_force", side_b, ned_of, cam_of,
                                 "state side_force_n, wind-axes y"),
            "thrust": _force("thrust", thrust_b, ned_of, cam_of,
                             "sum of state engineN_thrust_n along the body x axis",
                             engines=[{"engine": i, "thrust_n": _r(v, 3)} for i, v in engines]),
            "weight": _force("weight", weight_b, ned_of, cam_of,
                             "mass x g, straight down (NED +z)"),
            "aerodynamic_total": _force(
                "aerodynamic_total", aero_b, ned_of, cam_of,
                "state f_aero_x/y/z_n (body axes)" if recorded_aero
                else "lift + drag + side force rotated to body axes"),
            "net": _force("net", net_b, ned_of, cam_of,
                          "aerodynamic total + thrust + weight"),
        },
        "force_balance": {
            "lift_to_weight": _r(lift_n / weight, 5) if weight else None,
            "thrust_to_weight": _r(thrust / weight, 5) if weight else None,
            "thrust_minus_drag_n": _r(thrust - drag_n, 3),
            "acceleration_body_mps2": _r(accel_b, 5),
            "acceleration_ned_mps2": _r(ned_of(accel_b), 5),
            "acceleration_g": _r(_norm(accel_b) / G0, 5),
            "load_factor_nz_flight_model": _r(_f(state, "n_z"), 5),
            "load_factor_nz_from_forces": _r(nz_forces, 5),
            "aero_axes_check": {
                "max_component_error_n": _r(max(abs(from_wind[k] - recorded_aero[k])
                                                for k in range(3)), 4) if recorded_aero else None,
                "about": ("lift/drag/side force rotated through alpha and beta vs the "
                          "model's own body-axis aerodynamic force"),
            },
        },
        "velocity": {
            "ground_ned_mps": _r(v_ground, 4), "ground_speed_mps": _r(gs, 4),
            "ground_speed_kt": _r(gs / KT, 3), "track_deg": _r(track, 3),
            "vertical_speed_mps": _r(vs, 4), "vertical_speed_fpm": _r(vs / FT * 60.0, 2),
            "air_relative_ned_mps": _r(v_air_ned, 4),
            "true_airspeed_mps": _r(tas, 4), "true_airspeed_kt": _r(tas / KT, 3),
            "calibrated_airspeed_kt": _r(_f(state, "cas_kt"), 3),
            "mach": _r(mach, 5),
            "relative_wind_direction_body": _r(_scale(x_w, -1.0), 6),
            "velocity_direction_camera": _r(_unit(cam_of(x_w)), 6) if cam_of else None,
        },
        "aerodynamic_angles": {
            "alpha_deg": _r(s("alpha_deg"), 4), "beta_deg": _r(s("beta_deg"), 4),
            "flight_path_angle_deg": _r(_f(state, "flight_path_angle_deg"), 4),
            "crab_deg": _r(((track - heading + 180.0) % 360.0) - 180.0, 3)
            if track is not None else None,
        },
        "attitude": {"roll_deg": _r(roll, 4), "pitch_deg": _r(pitch, 4),
                     "heading_deg": _r(heading, 4),
                     "roll_rate_dps": _r(_f(state, "roll_rate_dps"), 4)},
        "air": {
            "density_kg_m3": _r(rho, 6), "density_basis": rho_basis,
            "static_pressure_pa": _r(isa_pressure_pa(p_alt), 2),
            "static_pressure_basis": "ISA at the flight model's pressure altitude",
            "temperature_k": _r(temp, 3), "temperature_c": _r(temp - 273.15, 3),
            "speed_of_sound_mps": _r(a_sound, 3),
            "dynamic_pressure_pa": _r(qbar, 3),
            "pressure_altitude_m": _r(p_alt, 2),
            "density_altitude_m": _r(_f(state, "density_altitude_m"), 2),
            "relative_humidity_pct": _r(_f(state, "rh_pct"), 2),
            "wind_ned_mps": _r(wind, 4), "wind_speed_mps": _r(wind_speed, 4),
            "wind_speed_kt": _r(wind_speed / KT, 3), "wind_from_deg": _r(wind_from, 2),
            "gust_ned_mps": _r((s("gust_north_mps"), s("gust_east_mps"),
                                s("gust_down_mps")), 4),
            "wind_shear_per_s": _r(_f(state, "shear_dv_dz_per_s"), 5),
        },
        "coefficients": coeffs,
        "lifting_line": lifting,
        "energy": {
            "kinetic_j": _r(0.5 * mass * tas * tas, 1),
            "potential_j_msl": _r(mass * G0 * s("altitude_m"), 1),
            "energy_height_m": _r(energy_h, 2),
            "specific_excess_power_mps": _r(ps, 4),
            "specific_excess_power_basis": "(thrust - drag) x TAS / weight",
        },
        "position": {"latitude_deg": _r(_f(state, "lat_deg"), 7),
                     "longitude_deg": _r(_f(state, "lon_deg"), 7),
                     "altitude_msl_m": _r(_f(state, "altitude_m"), 3),
                     "altitude_msl_ft": _r(s("altitude_m") / FT, 1),
                     "height_above_ground_m": _r(_f(state, "agl_m"), 3)},
        "controls": {"elevator_deg": _r(_f(state, "elevator_deg"), 4),
                     "aileron_deg": _r(_f(state, "aileron_deg"), 4),
                     "rudder_deg": _r(_f(state, "rudder_deg"), 4),
                     "engines_rpm": [_r(float(v), 2) for k, v in sorted(state.items())
                                     if re.fullmatch(r"engine\d+_rpm", k) and v is not None]},
    }
    effects = {k: _r(_f(state, k), 5) for k in (
        "icing_eta", "icing_lift_factor", "icing_drag_factor", "wake_v_mps",
        "wake_w_mps", "wake_gamma_m2_s") if _f(state, k) is not None}
    if effects:
        out["environment_effects"] = effects
    return out


# -- airflow -------------------------------------------------------------------

def _rankine_velocity(P, a, m, x0):
    """Velocity (N,3) of a source +m at x = x0 + a and sink -m at x0 - a
    on the body x axis (point sources: m / (4 pi) r / |r|^3)."""
    import numpy as np

    out = np.zeros_like(P)
    for xs, strength in ((x0 + a, m), (x0 - a, -m)):
        r = P - np.array([xs, 0.0, 0.0])
        d = np.sqrt((r * r).sum(axis=1)) + 1e-9
        out += strength / (4.0 * math.pi) * r / (d ** 3)[:, None]
    return out


def _segment_velocity(P, A, B, gamma, core):
    """Biot-Savart velocity (N,3) of a straight vortex segment A -> B of
    circulation gamma, with a smoothed core (no singularity)."""
    import numpy as np

    r0 = B - A
    r1 = P - A
    r2 = P - B
    cross = np.cross(r1, r2)
    c2 = (cross * cross).sum(axis=1) + (core * core) * (r0 @ r0)
    n1 = np.sqrt((r1 * r1).sum(axis=1)) + 1e-9
    n2 = np.sqrt((r2 * r2).sum(axis=1)) + 1e-9
    k = gamma / (4.0 * math.pi) * ((r1 @ r0) / n1 - (r2 @ r0) / n2) / c2
    return cross * k[:, None]


def airflow_streamlines(physics: Dict, extents: Sequence[float], centre_body: Sequence[float],
                        rings: Sequence[Tuple[float, int]] = ((0.28, 8), (0.55, 14),
                                                              (0.82, 18), (1.05, 20)),
                        ) -> Optional[Dict]:
    """Streamlines of the air past the aircraft, in BODY metres about the CG.

    Free stream: the relative wind (-V along wind-axes x). Fuselage: a
    Rankine body (source at the nose, sink at the tail) sized to the box.
    Wing: a horseshoe vortex of circulation L / (rho V b'), b' = pi b / 4,
    bound at the CG and trailing downstream -- so the lines show the
    upwash ahead of the wing, the downwash behind it and the tip vortices,
    all in proportion to the frame's own lift. Returns the lines with the
    local speed ratio |u| / V at every point, and the model's parameters.
    """
    import numpy as np

    vel = physics.get("velocity") or {}
    tas = float(vel.get("true_airspeed_mps") or 0.0)
    if tas < 5.0:
        return None
    flow_dir = np.array(vel.get("relative_wind_direction_body") or (-1.0, 0.0, 0.0), float)
    flow_dir /= np.linalg.norm(flow_dir) or 1.0
    U = flow_dir * tas
    length, width, height = (float(v) for v in extents)
    ref = max(length, width)
    radius = max(0.05, min(0.18 * height, 0.075 * length))
    a = 0.42 * length
    m = math.pi * tas * radius * radius * math.sqrt(a * a + radius * radius) / a
    x0 = float(centre_body[0])
    lift = (physics.get("forces") or {}).get("lift") or {}
    lift_n = float(lift.get("magnitude_n") or 0.0)
    rho = float((physics.get("air") or {}).get("density_kg_m3") or 1.2)
    span = width
    b_eff = math.pi * span / 4.0
    gamma = lift_n / (rho * tas * b_eff) if lift_n > 0 else 0.0
    core = 0.07 * span
    far = 40.0 * ref
    tip_l = np.array([0.0, -b_eff / 2.0, 0.0])
    tip_r = np.array([0.0, b_eff / 2.0, 0.0])
    far_l = tip_l + flow_dir * far
    far_r = tip_r + flow_dir * far
    # The horseshoe's sense: lift up (-z body) needs downwash (+z) behind
    # the wing; the order far_l -> tip_l -> tip_r -> far_r with a positive
    # gamma gives it when the air moves aft. Checked, and flipped if not.
    def wing_v(P, g):
        return (_segment_velocity(P, far_l, tip_l, g, core)
                + _segment_velocity(P, tip_l, tip_r, g, core)
                + _segment_velocity(P, tip_r, far_r, g, core))
    behind = np.array([[0.0, 0.0, 0.0]]) + flow_dir * (0.6 * span)
    if gamma and wing_v(behind, gamma)[0, 2] < 0:
        gamma = -gamma

    def field(P):
        return U + _rankine_velocity(P, a, m, x0) + (wing_v(P, gamma) if gamma else 0.0)

    # Seeds: rings in the plane square to the flow, upstream of the nose.
    side = np.cross(flow_dir, np.array([0.0, 0.0, 1.0]))
    if np.linalg.norm(side) < 1e-6:
        side = np.array([0.0, 1.0, 0.0])
    side /= np.linalg.norm(side)
    up = np.cross(side, flow_dir)
    up /= np.linalg.norm(up)
    origin = np.array([x0, 0.0, 0.0]) - flow_dir * (0.5 * length + 0.55 * ref)
    half_w = 0.6 * max(width, length * 0.6)
    half_h = max(0.9 * height, 0.22 * width)
    seeds = []
    # Rings round the fuselage axis (an ellipse spanning the wing and the
    # fin), so the flow reads as a tube from any camera; a fixed stagger
    # between rings keeps the lines off a visible grid (same every run).
    for ring, (frac, count) in enumerate(rings):
        for i in range(count):
            th = 2.0 * math.pi * (i + 0.5 * (ring % 2)) / count
            seeds.append(origin + side * math.cos(th) * frac * half_w
                         + up * math.sin(th) * frac * half_h)
    P = np.array(seeds, float)
    ds = 0.02 * ref
    # Upstream run-in, past the airframe, and a short wake behind the tail
    # (a long wake runs at a chase camera and fans over the picture).
    steps = int((0.5 * length + 0.55 * ref + 0.5 * length + 0.3 * ref) / ds)
    paths = [P.copy()]
    speeds = [np.linalg.norm(field(P), axis=1) / tas]
    alive = np.ones(len(P), bool)
    for _ in range(steps):
        v1 = field(P)
        d1 = v1 / (np.linalg.norm(v1, axis=1)[:, None] + 1e-9)
        mid = P + d1 * (ds / 2.0)
        v2 = field(mid)
        sp2 = np.linalg.norm(v2, axis=1)
        d2 = v2 / (sp2[:, None] + 1e-9)
        alive &= sp2 > 0.05 * tas
        P = np.where(alive[:, None], P + d2 * ds, P)
        paths.append(P.copy())
        speeds.append(np.linalg.norm(field(P), axis=1) / tas)
    paths = np.stack(paths, axis=1)          # (N, steps+1, 3)
    speeds = np.stack(speeds, axis=1)
    lines = [{"points_body_m": paths[n].tolist(), "speed_ratio": speeds[n].tolist()}
             for n in range(len(seeds))]
    return {
        "lines": lines,
        "model": ("potential flow: free stream (relative wind) + Rankine body for "
                  "the fuselage + lifting-line horseshoe vortex for the wing, "
                  "circulation from this frame's lift. Analytic and fast; an "
                  "illustration of the flow the forces imply, not a CFD solution"),
        "parameters": {"free_stream_mps": _r(tas, 3),
                       "relative_wind_direction_body": _r(flow_dir.tolist(), 6),
                       "fuselage_radius_m": _r(radius, 3),
                       "source_sink_half_spacing_m": _r(a, 3),
                       "source_strength_m3_s": _r(m, 3),
                       "horseshoe_circulation_m2_s": _r(abs(gamma), 3),
                       "vortex_span_m": _r(b_eff, 3), "vortex_core_m": _r(core, 3),
                       "seeds": len(seeds), "step_m": _r(ds, 4), "steps": steps},
    }
