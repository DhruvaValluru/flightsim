"""An immutable snapshot of aircraft state.

This is the top of the observer tier (§2.1): state flows JSBSim -> observers and
never back. The dataclass is frozen, so a telemetry writer, HUD, camera or
sensor model cannot mutate what it was handed. The previous build's
``fs_kinematics.py`` sat in this position and rewrote the trajectory with
post-hoc "roll inertia, adverse yaw, pitch overshoot, energy bleed" filters --
all of which JSBSim already produces from the aero coefficients and inertia
tensor, and all of which are what made the output move like a game.

Load factor
-----------
``load_factor`` and the body accelerations are read from JSBSim's own
accelerometer properties. They are **not** finite-differenced from velocity.
The previous build differenced velocity at the telemetry output rate and
produced a G trace that swung 0.5-1.5 g in air the HUD reported as dead calm,
while the altitude trace stayed perfectly smooth -- a physically impossible
combination (§1.3).

Crab angle
----------
``crab_deg`` is track minus heading. Its absence is why the previous build's
advertised 25 kt crosswind was unverifiable from the output (§1.6): at 250 kt a
near-full 25 kt crosswind produces about 5.7 degrees of crab, which is plainly
visible in this field and invisible without it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict

from . import units as u

# Properties read for every snapshot. Validated once against the catalog when
# an observer is constructed, so a model that lacks one fails loudly up front.
REQUIRED_PROPERTIES = (
    "simulation/sim-time-sec",
    "position/lat-geod-deg",
    "position/long-gc-deg",
    "position/h-sl-meters",
    "position/h-agl-ft",
    "position/terrain-elevation-asl-ft",
    "attitude/phi-rad",
    "attitude/theta-rad",
    "attitude/psi-rad",
    "velocities/vtrue-kts",
    "velocities/vc-kts",
    "velocities/mach",
    "velocities/h-dot-fps",
    "velocities/u-fps",
    "velocities/v-fps",
    "velocities/w-fps",
    "velocities/v-north-fps",
    "velocities/v-east-fps",
    "velocities/v-down-fps",
    "velocities/vg-fps",
    "velocities/p-rad_sec",
    "velocities/q-rad_sec",
    "velocities/r-rad_sec",
    "aero/alpha-deg",
    "aero/beta-deg",
    "aero/qbar-psf",
    # Aero force components, body axes (fb*) and wind axes (fw*: fwx drag,
    # fwy side force, fwz lift). All six verified against the live catalog
    # (hazard 1) -- lift and drag are the FDM's own outputs, never a
    # transform this repo performs.
    "forces/fbx-aero-lbs",
    "forces/fby-aero-lbs",
    "forces/fbz-aero-lbs",
    "forces/fwx-aero-lbs",
    "forces/fwy-aero-lbs",
    "forces/fwz-aero-lbs",
    "accelerations/Nx",
    "accelerations/Ny",
    "accelerations/Nz",
    "inertia/weight-lbs",
    "propulsion/total-fuel-lbs",
    "atmosphere/rho-slugs_ft3",
    "atmosphere/T-R",
    "atmosphere/P-psf",
    "atmosphere/total-wind-north-fps",
    "atmosphere/total-wind-east-fps",
    "atmosphere/total-wind-down-fps",
    "fcs/elevator-pos-rad",
    "fcs/rudder-pos-rad",
    "fcs/throttle-cmd-norm",
)

#: Control-surface positions, read for mesh articulation (§5 Phase 5) and for
#: the burn-in. Not every airframe defines every one, so these are resolved
#: opportunistically rather than required.
SURFACE_PROPERTIES = (
    "fcs/elevator-pos-rad",
    "fcs/left-aileron-pos-rad",
    "fcs/right-aileron-pos-rad",
    "fcs/rudder-pos-rad",
    "fcs/flap-pos-deg",
    "fcs/speedbrake-pos-norm",
    "gear/gear-pos-norm",
)


def wrap180(deg: float) -> float:
    """Wrap an angle to (-180, 180]."""
    wrapped = math.fmod(deg + 180.0, 360.0)
    if wrapped <= 0.0:
        wrapped += 360.0
    return wrapped - 180.0


@dataclass(frozen=True)
class AircraftState:
    """One instant of aircraft state, in SI unless the field name says otherwise.

    Frozen by design: observers read, they do not modify (§2.1).
    """

    # -- time
    t: float                      # s, simulation time

    # -- position
    lat_deg: float                # geodetic
    lon_deg: float
    altitude_m: float             # MSL
    agl_m: float
    terrain_elev_m: float

    # -- attitude
    roll_deg: float
    pitch_deg: float
    heading_deg: float            # true, 0..360

    # -- airspeed / groundspeed
    tas_kt: float                 # true airspeed
    cas_kt: float                 # calibrated airspeed
    mach: float
    groundspeed_kt: float
    climb_rate_mps: float         # positive up

    # -- body-frame velocity
    u_mps: float
    v_mps: float
    w_mps: float

    # -- NED velocity (inertial, i.e. ground track)
    v_north_mps: float
    v_east_mps: float
    v_down_mps: float

    # -- body rates
    roll_rate_dps: float
    pitch_rate_dps: float
    yaw_rate_dps: float

    # -- aerodynamic angles
    alpha_deg: float
    beta_deg: float
    qbar_pa: float                # dynamic pressure

    # -- aero force on the aircraft: body axes, and the FDM's own wind-axis
    #    resolution (drag along the relative wind, lift normal to it). All
    #    read from JSBSim's force outputs, never recomputed here.
    f_aero_x_n: float
    f_aero_y_n: float
    f_aero_z_n: float
    drag_n: float
    side_force_n: float
    lift_n: float

    # -- accelerometer-derived (never finite-differenced; §1.3)
    n_x: float
    n_y: float
    n_z: float                    # body normal load factor, g

    # -- mass
    weight_kg: float
    fuel_kg: float

    # -- atmosphere as the FDM sees it
    density_kgm3: float
    temperature_k: float
    pressure_pa: float

    # -- total wind actually reaching the FDM: steady + gust + turbulence.
    #    Reading the *total* rather than the commanded wind is what makes an
    #    environmental condition verifiable from the output rather than
    #    merely advertised (§1.6).
    wind_north_mps: float
    wind_east_mps: float
    wind_down_mps: float

    # -- control surface positions, for articulation and burn-in
    surfaces: Dict[str, float] = field(default_factory=dict)

    # -- derived ------------------------------------------------------

    @property
    def load_factor(self) -> float:
        """Body normal load factor in g, from the accelerometer."""
        return self.n_z

    @property
    def track_deg(self) -> float:
        """Ground track, degrees true. Undefined at zero groundspeed."""
        return math.degrees(math.atan2(self.v_east_mps, self.v_north_mps)) % 360.0

    @property
    def crab_deg(self) -> float:
        """Track minus heading. Direct evidence that wind reached the FDM."""
        return wrap180(self.track_deg - self.heading_deg)

    @property
    def wind_speed_mps(self) -> float:
        return math.hypot(self.wind_north_mps, self.wind_east_mps)

    @property
    def wind_from_deg(self) -> float:
        """Meteorological wind direction: the bearing the wind blows *from*."""
        if self.wind_speed_mps < 1e-9:
            return 0.0
        return (math.degrees(math.atan2(-self.wind_east_mps, -self.wind_north_mps))) % 360.0

    @property
    def flight_path_angle_deg(self) -> float:
        """Inertial flight path angle, from the NED velocity vector."""
        horizontal = math.hypot(self.v_north_mps, self.v_east_mps)
        if horizontal < 1e-9 and abs(self.v_down_mps) < 1e-9:
            return 0.0
        return math.degrees(math.atan2(-self.v_down_mps, horizontal))

    def is_finite(self) -> bool:
        """False if any core field has gone NaN or infinite."""
        return all(
            math.isfinite(v)
            for v in (
                self.lat_deg, self.lon_deg, self.altitude_m,
                self.roll_deg, self.pitch_deg, self.heading_deg,
                self.tas_kt, self.n_z, self.u_mps, self.v_mps, self.w_mps,
            )
        )

    @classmethod
    def from_properties(cls, props, surface_names=()) -> "AircraftState":
        """Read one snapshot through a :class:`PropertyAccess`.

        ``surface_names`` is the pre-resolved subset of :data:`SURFACE_PROPERTIES`
        the loaded model actually defines; resolving it once at observer
        construction avoids a catalog lookup per surface per frame.
        """
        g = props.get
        return cls(
            t=g("simulation/sim-time-sec"),
            lat_deg=g("position/lat-geod-deg"),
            lon_deg=g("position/long-gc-deg"),
            altitude_m=g("position/h-sl-meters"),
            agl_m=u.ft_to_m(g("position/h-agl-ft")),
            terrain_elev_m=u.ft_to_m(g("position/terrain-elevation-asl-ft")),
            roll_deg=math.degrees(g("attitude/phi-rad")),
            pitch_deg=math.degrees(g("attitude/theta-rad")),
            heading_deg=math.degrees(g("attitude/psi-rad")) % 360.0,
            tas_kt=g("velocities/vtrue-kts"),
            cas_kt=g("velocities/vc-kts"),
            mach=g("velocities/mach"),
            groundspeed_kt=u.fps_to_kt(g("velocities/vg-fps")),
            climb_rate_mps=u.fps_to_mps(g("velocities/h-dot-fps")),
            u_mps=u.fps_to_mps(g("velocities/u-fps")),
            v_mps=u.fps_to_mps(g("velocities/v-fps")),
            w_mps=u.fps_to_mps(g("velocities/w-fps")),
            v_north_mps=u.fps_to_mps(g("velocities/v-north-fps")),
            v_east_mps=u.fps_to_mps(g("velocities/v-east-fps")),
            v_down_mps=u.fps_to_mps(g("velocities/v-down-fps")),
            roll_rate_dps=math.degrees(g("velocities/p-rad_sec")),
            pitch_rate_dps=math.degrees(g("velocities/q-rad_sec")),
            yaw_rate_dps=math.degrees(g("velocities/r-rad_sec")),
            alpha_deg=g("aero/alpha-deg"),
            beta_deg=g("aero/beta-deg"),
            qbar_pa=u.psf_to_pa(g("aero/qbar-psf")),
            f_aero_x_n=u.lbf_to_n(g("forces/fbx-aero-lbs")),
            f_aero_y_n=u.lbf_to_n(g("forces/fby-aero-lbs")),
            f_aero_z_n=u.lbf_to_n(g("forces/fbz-aero-lbs")),
            drag_n=u.lbf_to_n(g("forces/fwx-aero-lbs")),
            side_force_n=u.lbf_to_n(g("forces/fwy-aero-lbs")),
            lift_n=u.lbf_to_n(g("forces/fwz-aero-lbs")),
            n_x=g("accelerations/Nx"),
            n_y=g("accelerations/Ny"),
            n_z=g("accelerations/Nz"),
            weight_kg=u.lb_to_kg(g("inertia/weight-lbs")),
            fuel_kg=u.lb_to_kg(g("propulsion/total-fuel-lbs")),
            density_kgm3=u.slugft3_to_kgm3(g("atmosphere/rho-slugs_ft3")),
            temperature_k=u.rankine_to_kelvin(g("atmosphere/T-R")),
            pressure_pa=u.psf_to_pa(g("atmosphere/P-psf")),
            wind_north_mps=u.fps_to_mps(g("atmosphere/total-wind-north-fps")),
            wind_east_mps=u.fps_to_mps(g("atmosphere/total-wind-east-fps")),
            wind_down_mps=u.fps_to_mps(g("atmosphere/total-wind-down-fps")),
            surfaces={n.split("/")[-1]: g(n) for n in surface_names},
        )
