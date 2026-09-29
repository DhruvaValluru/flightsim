"""WGS 84 geodesy for the interoperability feed, own implementation.

Three things a DIS Entity State PDU needs that the telemetry does not
carry (the telemetry is geodetic latitude/longitude, a height above the
JSBSim sea level, NED velocity and the NED Euler angles heading, pitch,
roll):

* :func:`geodetic_to_ecef` / :func:`ecef_to_geodetic` -- the WGS 84
  ellipsoid (a = 6378137 m, 1/f = 298.257223563), closed form forward,
  fixed-point iteration back (converges to < 1e-12 rad here; the tests
  measure the round trip);
* :func:`ecef_from_ned_matrix` -- the local north-east-down axes at a
  point, as columns in ECEF, so a NED vector (velocity) becomes ECEF;
* :func:`dis_euler_from_ned` / :func:`ned_from_dis_euler` -- the IEEE
  1278.1 orientation: the Euler angles (psi, theta, phi) that carry the
  WORLD (ECEF) axes onto the ENTITY (body: x forward, y right, z down)
  axes by a yaw about Z, then a pitch about the new Y, then a roll about
  the new X. The body-from-ECEF matrix is therefore
  ``Rx(phi) . Ry(theta) . Rz(psi)`` (passive rotations), and equals
  ``body_from_ned(heading, pitch, roll) . ned_from_ecef(lat, lon)``;
  the angles are read off that product. Nothing here is a formula
  copied from a reference: the tests reconstruct the body axes in ECEF
  along both routes and require them to agree.

Every function takes degrees where the telemetry uses degrees and
returns radians where the PDU uses radians; each signature says which.
Matrices are 3-tuples of 3-tuples, row-major, plain floats: no numpy,
so the arithmetic is the same on every platform and readable by eye.

What is NOT claimed: no geoid model lives here (the ellipsoidal height
is the caller's business -- core/terrain/geoid.py and the datum block);
no datum other than WGS 84; no gimbal-lock handling beyond ``atan2``
(at |theta| = 90 deg exactly, psi and phi are not separable and the
values returned are one valid pair).
"""

from __future__ import annotations

import math
from typing import Tuple

Vec3 = Tuple[float, float, float]
Mat3 = Tuple[Vec3, Vec3, Vec3]

#: WGS 84 defining constants (NIMA TR8350.2, Table 3.1).
WGS84_A = 6378137.0
WGS84_INV_F = 298.257223563
WGS84_F = 1.0 / WGS84_INV_F
WGS84_B = WGS84_A * (1.0 - WGS84_F)
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)          # first eccentricity squared

#: The back-conversion stops when the latitude moves less than this.
ECEF_TO_GEODETIC_TOLERANCE_RAD = 1e-13
ECEF_TO_GEODETIC_MAX_ITERATIONS = 50


# -- matrices ------------------------------------------------------------

def matmul(a: Mat3, b: Mat3) -> Mat3:
    return tuple(  # type: ignore[return-value]
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
        for i in range(3))


def transpose(a: Mat3) -> Mat3:
    return tuple(tuple(a[j][i] for j in range(3)) for i in range(3))  # type: ignore[return-value]


def matvec(a: Mat3, v: Vec3) -> Vec3:
    return tuple(sum(a[i][k] * v[k] for k in range(3)) for i in range(3))  # type: ignore[return-value]


def rot_x(angle_rad: float) -> Mat3:
    """Passive rotation about X: coordinates of a fixed vector in a frame
    turned by ``angle`` about X."""
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return ((1.0, 0.0, 0.0), (0.0, c, s), (0.0, -s, c))


def rot_y(angle_rad: float) -> Mat3:
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return ((c, 0.0, -s), (0.0, 1.0, 0.0), (s, 0.0, c))


def rot_z(angle_rad: float) -> Mat3:
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return ((c, s, 0.0), (-s, c, 0.0), (0.0, 0.0, 1.0))


# -- the ellipsoid -------------------------------------------------------

def prime_vertical_radius(lat_rad: float) -> float:
    """N(phi): the radius of curvature in the prime vertical."""
    s = math.sin(lat_rad)
    return WGS84_A / math.sqrt(1.0 - WGS84_E2 * s * s)


def geodetic_to_ecef(lat_deg: float, lon_deg: float, h_m: float) -> Vec3:
    """WGS 84 geodetic (degrees, ELLIPSOIDAL height in metres) -> ECEF
    metres. The height is above the ellipsoid: an orthometric height must
    have its geoid undulation added first."""
    lat = math.radians(float(lat_deg))
    lon = math.radians(float(lon_deg))
    n = prime_vertical_radius(lat)
    cos_lat = math.cos(lat)
    x = (n + h_m) * cos_lat * math.cos(lon)
    y = (n + h_m) * cos_lat * math.sin(lon)
    z = (n * (1.0 - WGS84_E2) + h_m) * math.sin(lat)
    return (x, y, z)


def ecef_to_geodetic(x: float, y: float, z: float) -> Vec3:
    """ECEF metres -> (lat_deg, lon_deg, ellipsoidal h_m), by fixed-point
    iteration on the latitude (starting from the spherical guess),
    stopped at :data:`ECEF_TO_GEODETIC_TOLERANCE_RAD`."""
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    if p == 0.0:
        # On the polar axis: the latitude is a sign, the height the
        # distance from the pole along the axis.
        lat = math.copysign(math.pi / 2.0, z)
        return (math.degrees(lat), math.degrees(lon), abs(z) - WGS84_B)
    lat = math.atan2(z, p * (1.0 - WGS84_E2))
    for _ in range(ECEF_TO_GEODETIC_MAX_ITERATIONS):
        n = prime_vertical_radius(lat)
        h = p / math.cos(lat) - n
        new_lat = math.atan2(z, p * (1.0 - WGS84_E2 * n / (n + h)))
        if abs(new_lat - lat) < ECEF_TO_GEODETIC_TOLERANCE_RAD:
            lat = new_lat
            break
        lat = new_lat
    n = prime_vertical_radius(lat)
    if abs(math.cos(lat)) > 1e-9:
        h = p / math.cos(lat) - n
    else:
        h = abs(z) / abs(math.sin(lat)) - n * (1.0 - WGS84_E2)
    return (math.degrees(lat), math.degrees(lon), h)


# -- frames --------------------------------------------------------------

def ecef_from_ned_matrix(lat_deg: float, lon_deg: float) -> Mat3:
    """The matrix whose COLUMNS are the local north, east and down unit
    vectors in ECEF at (lat, lon): ``ecef_vector = M . ned_vector``."""
    lat = math.radians(float(lat_deg))
    lon = math.radians(float(lon_deg))
    sl, cl = math.sin(lat), math.cos(lat)
    so, co = math.sin(lon), math.cos(lon)
    north = (-sl * co, -sl * so, cl)
    east = (-so, co, 0.0)
    down = (-cl * co, -cl * so, -sl)
    return ((north[0], east[0], down[0]),
            (north[1], east[1], down[1]),
            (north[2], east[2], down[2]))


def ned_from_ecef_matrix(lat_deg: float, lon_deg: float) -> Mat3:
    """Rows are north, east, down in ECEF: ``ned_vector = M . ecef_vector``."""
    return transpose(ecef_from_ned_matrix(lat_deg, lon_deg))


def ned_to_ecef_vector(lat_deg: float, lon_deg: float, ned: Vec3) -> Vec3:
    """A NED vector (a velocity, say) at (lat, lon) expressed in ECEF."""
    return matvec(ecef_from_ned_matrix(lat_deg, lon_deg), ned)


def body_from_ned_matrix(heading_deg: float, pitch_deg: float,
                         roll_deg: float) -> Mat3:
    """The aircraft body axes from NED: yaw (heading) about down, pitch
    about the new right axis, roll about the new forward axis; rows are
    the body x, y, z axes in NED."""
    return matmul(rot_x(math.radians(float(roll_deg))),
                  matmul(rot_y(math.radians(float(pitch_deg))),
                         rot_z(math.radians(float(heading_deg)))))


def body_from_ecef_via_ned(lat_deg: float, lon_deg: float, heading_deg: float,
                           pitch_deg: float, roll_deg: float) -> Mat3:
    """ROUTE 1: body-from-ECEF composed from the NED attitude and the
    place. Rows are the body axes in ECEF."""
    return matmul(body_from_ned_matrix(heading_deg, pitch_deg, roll_deg),
                  ned_from_ecef_matrix(lat_deg, lon_deg))


def body_from_ecef_via_dis(psi_rad: float, theta_rad: float,
                           phi_rad: float) -> Mat3:
    """ROUTE 2: body-from-ECEF from the DIS Euler angles alone:
    ``Rx(phi) . Ry(theta) . Rz(psi)``. Rows are the body axes in ECEF."""
    return matmul(rot_x(phi_rad), matmul(rot_y(theta_rad), rot_z(psi_rad)))


def euler_from_matrix(r: Mat3) -> Tuple[float, float, float]:
    """(psi, theta, phi) in radians such that
    ``rot_x(phi) . rot_y(theta) . rot_z(psi) == r`` (r orthonormal)."""
    theta = math.asin(max(-1.0, min(1.0, -r[0][2])))
    psi = math.atan2(r[0][1], r[0][0])
    phi = math.atan2(r[1][2], r[2][2])
    return (psi, theta, phi)


def dis_euler_from_ned(lat_deg: float, lon_deg: float, heading_deg: float,
                       pitch_deg: float, roll_deg: float) -> Tuple[float, float, float]:
    """The IEEE 1278.1 entity orientation (psi, theta, phi, radians) of
    an aircraft at (lat, lon) with NED heading, pitch and roll (degrees)."""
    return euler_from_matrix(body_from_ecef_via_ned(
        lat_deg, lon_deg, heading_deg, pitch_deg, roll_deg))


def ned_from_dis_euler(lat_deg: float, lon_deg: float, psi_rad: float,
                       theta_rad: float, phi_rad: float) -> Tuple[float, float, float]:
    """The inverse: (heading_deg in [0, 360), pitch_deg, roll_deg) of an
    entity at (lat, lon) whose DIS orientation is (psi, theta, phi)."""
    body_from_ecef = body_from_ecef_via_dis(psi_rad, theta_rad, phi_rad)
    body_from_ned = matmul(body_from_ecef, ecef_from_ned_matrix(lat_deg, lon_deg))
    heading, pitch, roll = euler_from_matrix(body_from_ned)
    return (math.degrees(heading) % 360.0, math.degrees(pitch), math.degrees(roll))


def rotation_vector_between(r_from: Mat3, r_to: Mat3) -> Vec3:
    """The rotation (axis times angle, radians) that carries the body
    axes of ``r_from`` onto those of ``r_to``, expressed in the FIRST
    body frame -- both are body-from-ECEF matrices. Divided by the time
    between them it is the mean body angular velocity (p, q, r)."""
    a = matmul(r_from, transpose(r_to))
    trace = a[0][0] + a[1][1] + a[2][2]
    cos_angle = max(-1.0, min(1.0, (trace - 1.0) / 2.0))
    angle = math.acos(cos_angle)
    axis_times_two_sin = (a[2][1] - a[1][2], a[0][2] - a[2][0], a[1][0] - a[0][1])
    if angle < 1e-12:
        return (0.0, 0.0, 0.0)
    if math.sin(angle) < 1e-9:
        # angle near pi: the antisymmetric part vanishes; fall back to
        # the symmetric part (a step this large never occurs between two
        # telemetry samples at 10 Hz; stated, not exercised)
        scale = angle / 2.0
        return tuple(scale * math.copysign(math.sqrt(max(0.0, (a[i][i] + 1.0) / 2.0)),
                                           axis_times_two_sin[i]) for i in range(3))  # type: ignore[return-value]
    scale = angle / (2.0 * math.sin(angle))
    return (axis_times_two_sin[0] * scale, axis_times_two_sin[1] * scale,
            axis_times_two_sin[2] * scale)
