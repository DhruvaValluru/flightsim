"""Package E measurement: the altitude setpoint is raised ahead of terrain.

A synthetic east-west ridge is placed on a 500 m plain some kilometres
north of the aircraft, which flies north under the altitude hold. The
run is flown twice through the SAME runner: once with the look-ahead
(the shipped path) and once with it switched off (``--pre``, the
pre-Package-E behaviour: the hold keeps the spec altitude and the
contact check reports the impact). Every number in the Phase 2 report's
Package E row comes from this script.

    .venv/bin/python -m experiments.airborne.terrain_lookahead
    .venv/bin/python -m experiments.airborne.terrain_lookahead --pre
    .venv/bin/python -m experiments.airborne.terrain_lookahead --crest 5000

Nothing here writes physical state; the ridge is an input raster and the
look-ahead's only output is the altitude setpoint.
"""

from __future__ import annotations

import argparse
import json

import numpy as np

from core.nl.compiler import compile_prompt
from core.scenario.runner import run_spec
from core.terrain.contact import TerrainImpactError
from core.terrain.ground import TerrainGround
from core.terrain.heightfield import Georeference, Heightfield
from core.terrain.lookahead import RTC_M, TerrainLookaheadError

UTM = "EPSG:32633"
PIXEL_M = 100.0
SIZE_PX = 400          # 40 km square
PLAIN_M = 500.0


def ridge_ground(crest_m: float, north_m: float, sigma_m: float = 400.0,
                 plain_m: float = PLAIN_M) -> TerrainGround:
    """An east-west Gaussian ridge ``north_m`` north of the raster centre."""
    extent = SIZE_PX * PIXEL_M
    # Pixel centres, north-up: row 0 is the northern edge.
    y = extent - (np.arange(SIZE_PX) + 0.5) * PIXEL_M
    crest_y = extent / 2.0 + north_m
    profile = plain_m + (crest_m - plain_m) * np.exp(
        -((y - crest_y) / sigma_m) ** 2 / 2.0)
    z = np.repeat(profile[:, None], SIZE_PX, axis=1)
    field = Heightfield.from_elevations(
        z, Georeference(UTM, origin_x_m=0.0, origin_y_m=extent,
                        pixel_size_m=PIXEL_M),
        name=f"ridge-{crest_m:.0f}m-at-{north_m:.0f}m")
    return TerrainGround(field)


def ridge_spec(ground: TerrainGround, altitude_m: float, cas_kt: float,
               duration_s: float, aircraft: str = "747"):
    lon, lat = ground.centre_lonlat()
    spec = compile_prompt(
        f"fly the {aircraft} at {altitude_m:.0f} m and {cas_kt:.0f} kt "
        f"heading north for {duration_s:.0f} seconds")
    spec.set("latitude", round(lat, 6))
    spec.set("longitude", round(lon, 6))
    spec.set("hold_state", True, frm="closed loop: the altitude hold flies")
    return spec


def measure(crest_m: float, north_m: float, altitude_m: float, cas_kt: float,
            duration_s: float, pre: bool, aircraft: str = "747") -> dict:
    ground = ridge_ground(crest_m, north_m)
    spec = ridge_spec(ground, altitude_m, cas_kt, duration_s, aircraft)
    out = {"crest_m": crest_m, "ridge_north_m": north_m,
           "altitude_m": altitude_m, "cas_kt": cas_kt, "pre": pre}
    if pre:
        import core.terrain.lookahead as la

        # The pre-Package-E runner: the look-ahead never guides. The
        # contact check still ends the run on the impact.
        guide = la.TerrainLookahead.guide
        la.TerrainLookahead.guide = (
            lambda self, state, autopilot:
            la.LookaheadResult(state.t, 0, None, None))
        try:
            return _fly(spec, ground, out)
        finally:
            la.TerrainLookahead.guide = guide
    return _fly(spec, ground, out)


def _fly(spec, ground, out):
    try:
        result = run_spec(spec, validate_first=False, terrain_ground=ground)
    except TerrainLookaheadError as exc:
        out.update(outcome="refused", constraint=exc.constraint,
                   message=str(exc), refused_at_s=exc.threat.time_s,
                   ahead_s=exc.threat.ahead_s,
                   required_hdot_mps=exc.threat.required_hdot_mps,
                   available_hdot_mps=exc.threat.available_hdot_mps)
        return out
    except TerrainImpactError as exc:
        out.update(outcome="impact", time_s=exc.impact.time_s,
                   station=exc.impact.station,
                   penetration_m=exc.impact.penetration_m)
        return out
    alt = result.telemetry.series("altitude_m")
    agl = result.telemetry.series("agl_m")
    la = result.manifest["terrain_lookahead"]
    out.update(
        outcome="flew",
        min_agl_m=min(agl), max_altitude_m=max(alt),
        final_altitude_m=alt[-1],
        raises=la["raises"], events=la["events"],
        hdot_capability_mps=la["hdot_capability_mps"],
        evaluations=la["evaluations"], samples=la["samples"],
        closure_ok=result.closure.ok,
        closure=[{"name": c.name, "commanded": c.commanded,
                  "achieved": c.achieved} for c in result.closure.checks],
        rtc_m=RTC_M,
    )
    if la["events"]:
        first = la["events"][0]
        out["first_raise_t_s"] = first["t"]
        out["first_raise_lead_s"] = first["ahead_s"]
        out["first_raise_setpoint_m"] = first["setpoint_m"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crest", type=float, default=3300.0)
    ap.add_argument("--north", type=float, default=8000.0)
    ap.add_argument("--altitude", type=float, default=3000.0)
    ap.add_argument("--cas", type=float, default=250.0)
    ap.add_argument("--duration", type=float, default=100.0)
    ap.add_argument("--aircraft", default="747")
    ap.add_argument("--pre", action="store_true",
                    help="fly with the look-ahead disabled (pre-Package-E)")
    args = ap.parse_args()
    print(json.dumps(measure(args.crest, args.north, args.altitude, args.cas,
                             args.duration, args.pre, args.aircraft),
                     indent=1))


if __name__ == "__main__":
    main()
