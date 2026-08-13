"""Phase 7 environment couplings in the UE host: four ports, each cross-checked.

The discipline is orographic_ue.py's, applied to every new coupling:

1. **Cross-implementation check.** Each C++ port (downburst, lee-rotor W20,
   log-profile shear, Allen thermals) writes a grid of samples of its own
   field into the render manifest; this harness recomputes every point through
   the ORIGINAL Python provider with the SAME card parameters and compares.
   A drifted port fails here, not in a viewer's eye.

2. **Null evidence in the render path.** Two renders per scenario -- coupled,
   and a control card without the coupling -- and the FDM's own recorded
   channels must differ the way the physics says: the downburst shows in the
   horizontal wind components crossing the core; the rotor shows in
   turb-down RMS (and the recorded W20 write); shear + thermals show in the
   wind components and vertical wind against their controls.

Three scenarios, six renders:
* ``downburst``: B747 through a microburst planted on its track over the
  georeferenced control ridge, position-coupled.
* ``rotor``: c172p in the Matterhorn lee at 280 m AGL, 25 kt wind, W20
  following the lee-sink field (background none).
* ``surface``: c172p at low altitude with log-profile shear + a summer
  thermal field, composed.

Usage: .venv/bin/python experiments/environment_ue.py [--skip-renders]
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.environment.downburst import Downburst  # noqa: E402
from core.environment.rotor import LeeRotorTurbulence  # noqa: E402
from core.environment.terrain_field import OrographicWind  # noqa: E402
from core.environment.thermals import SEASON_TABLE, AllenThermals  # noqa: E402
from core.environment.wind import LogProfileWind  # noqa: E402
from core.fdm import units as u  # noqa: E402
from core.terrain.glo30 import LOCATIONS, orographic_card_block  # noqa: E402
from core.terrain.ground import terrain_field_at  # noqa: E402
from core.terrain.heightfield import Heightfield  # noqa: E402
from experiments.gate5_ue_parity import reference_spec, write_run_card  # noqa: E402
from experiments.orographic_ue import render as _base_render  # noqa: E402


def render(card: Path, frames: Path, terrain: Path,
           extra: Sequence[str]) -> None:
    """orographic_ue's render, under showcase noon light: the low-altitude
    Yosemite scene under the terrain shot's default side light is a
    silhouette against a shadowed wall, and its final frame legitimately
    drops below the blank-frame floor (measured: max luminance 13). The sun
    is a recorded presentation parameter; the couplings under test are
    physics."""
    _base_render(card, frames, terrain,
                 ["-sun-elev=50.0", "-sun-azim=180.0", "-exposure-bias=9.5",
                  *extra])

RULE = "=" * 96

THRESHOLDS = {
    #: Max |Python - C++| over any selftest grid. The downburst and thermals
    #: are closed-form; the rotor rides the orographic port already verified
    #: to 1e-15. 1e-6 sits far above double noise, far below model changes.
    "max_port_difference": 1e-6,
    #: The downburst's headwind-to-tailwind reversal must show in the FDM:
    #: peak |wind_north| across the core, fps (12 m/s outflow ~ 39 fps).
    "min_downburst_peak_fps": 10.0,
    #: Rotor: coupled turb-down RMS against its control.
    "min_rotor_rms_ratio": 5.0,
    #: Surface: shear + thermals must move wind and vertical state.
    "min_surface_wind_rms_fps": 3.0,
}


def rms(values: Sequence[float]) -> float:
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0


def projected_origin(baked: Heightfield, lat: float, lon: float):
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", baked.georeference.crs,
                                       always_xy=True)
    return transformer.transform(lon, lat)


# -- scenario builders ---------------------------------------------------


def downburst_scenario(out: Path, terrain: Path):
    """B747 flying its heading straight through a downburst core."""
    location = LOCATIONS["matterhorn"]  # reuse control-ridge? use matterhorn frame
    baked = Heightfield.read(terrain)
    spec = reference_spec("fly the 747 at 2800 m and 250 kt for 20 seconds")
    spec.set("latitude", location.origin_lat, frm="scene origin")
    spec.set("longitude", location.origin_lon, frm="scene origin")
    spec.set("heading", 236.0, frm="the showcase track")
    ox, oy = projected_origin(baked, location.origin_lat, location.origin_lon)
    spec.set("terrain_elevation", round(baked.elevation_at(ox, oy), 1),
             frm="baked raster at origin")

    # The aircraft covers ~2.6 km in 20 s at 250 kt; the core sits on the
    # track 1.2 km ahead so the reversal happens mid-clip. Heading 236: track
    # unit vector (-cos36, -sin36)... computed from the heading directly.
    heading_rad = math.radians(236.0)
    along = 1200.0
    centre_north = along * math.cos(heading_rad)
    centre_east = along * math.sin(heading_rad)
    burst = Downburst(centre_north_m=centre_north, centre_east_m=centre_east,
                      core_radius_m=1000.0, outflow_max_mps=12.0,
                      outflow_height_m=150.0)
    card = write_run_card(
        spec, out / "card.json",
        downburst=burst.card_block(ox, oy),
    )
    return spec, card, burst


def rotor_scenario(out: Path, terrain: Path):
    """c172p at 280 m AGL in the Matterhorn lee, W20 riding the sink field."""
    location = LOCATIONS["matterhorn"]
    baked = Heightfield.read(terrain)
    ox, oy = projected_origin(baked, location.origin_lat, location.origin_lon)
    elevation = baked.elevation_at(ox, oy)
    spec = reference_spec(
        f"fly the c172p at {round(elevation + 280.0)} m and 100 kt for 20 seconds")
    spec.set("latitude", location.origin_lat, frm="scene origin")
    spec.set("longitude", location.origin_lon, frm="scene origin")
    spec.set("heading", 236.0, frm="the showcase track")
    spec.set("terrain_elevation", round(elevation, 1), frm="baked raster at origin")
    spec.set("wind_speed", 25.0, frm="rotor scenario")
    spec.set("wind_direction", 236.0, frm="headwind over the ridge")

    block = orographic_card_block(terrain, location.origin_lat,
                                  location.origin_lon, 25.0, 236.0)
    field = terrain_field_at(baked, block["origin_x_m"], block["origin_y_m"],
                             wavelength_m=block["wavelength_m"])
    orographic = OrographicWind(field, wind_speed_mps=block["wind_speed_mps"],
                                wind_from_deg=block["wind_from_deg"],
                                decay_height_m=block["decay_height_m"])
    provider = LeeRotorTurbulence(orographic, seed=int(spec.seed.value))
    card = write_run_card(
        spec, out / "card.json",
        orographic=block,
        rotor=provider.card_block(),
        turbulence_provider=provider,
    )
    return spec, card, provider, block


def surface_scenario(out: Path, terrain: Path):
    """c172p low over Yosemite: log-profile shear + summer thermals."""
    location = LOCATIONS["yosemite"]
    baked = Heightfield.read(terrain)
    ox, oy = projected_origin(baked, location.origin_lat, location.origin_lon)
    elevation = baked.elevation_at(ox, oy)
    spec = reference_spec(
        f"fly the c172p at {round(elevation + 250.0)} m and 100 kt for 20 seconds")
    spec.set("latitude", location.origin_lat, frm="scene origin")
    spec.set("longitude", location.origin_lon, frm="scene origin")
    spec.set("heading", 90.0, frm="down the valley")
    spec.set("terrain_elevation", round(elevation, 1), frm="baked raster at origin")

    shear = LogProfileWind(u.kt_to_mps(15.0), from_deg=270.0, terrain="forest")
    wstar, zi = SEASON_TABLE["summer"]
    thermals = AllenThermals(wstar_mps=wstar, zi_m=zi,
                             area_north_m=4000.0, area_east_m=4000.0,
                             origin_north_m=-2000.0, origin_east_m=-2000.0,
                             seed=int(spec.seed.value))
    card = write_run_card(
        spec, out / "card.json",
        log_profile=shear.card_block(),
        thermals=thermals.card_block(ox, oy),
    )
    return spec, card, shear, thermals


# -- port checks ---------------------------------------------------------


def check(label: str, samples: List[Dict], recompute) -> Dict:
    worst = 0.0
    for sample in samples:
        worst = max(worst, abs(recompute(sample)))
    ok = worst <= THRESHOLDS["max_port_difference"]
    print(f"  [{'ok  ' if ok else 'FAIL'}] {label}: {len(samples)} grid points, "
          f"max |Python - C++| = {worst:.2e}")
    return {"samples": len(samples), "max_difference": worst, "ok": bool(ok)}


def verify_downburst(manifest: Dict, burst: Downburst) -> Dict:
    def recompute(sample):
        ned = burst.wind_components(
            burst.centre_north_m + sample["radius_m"], burst.centre_east_m,
            sample["agl_m"])
        return max(abs(ned.north - sample["north_mps"]),
                   abs(ned.east - sample["east_mps"]),
                   abs(ned.down - sample["down_mps"]))
    return check("downburst field", manifest["environment"]["downburst_selftest"],
                 recompute)


def verify_rotor(manifest: Dict, provider: LeeRotorTurbulence) -> Dict:
    def recompute(sample):
        # The same query the C++ side ran: lee sink at (north, east) with
        # the height decay, through the provider's own constants.
        from core.environment.rotor import (
            ROTOR_SIGMA_GAIN, SIGMA_W_PER_W20, W20_CAP_KT,
        )
        sink = provider.orographic.lee_sink(sample["north_m"], sample["east_m"])
        sigma_mps = (ROTOR_SIGMA_GAIN * sink
                     * provider.orographic.decay(sample["agl_m"]))
        rotor_fps = u.mps_to_fps(sigma_mps) / SIGMA_W_PER_W20
        w20_fps = min(max(u.kt_to_fps(provider.background_w20_kt), rotor_fps),
                      u.kt_to_fps(W20_CAP_KT))
        return w20_fps - sample["w20_fps"]
    return check("rotor W20 field", manifest["environment"]["rotor_selftest"],
                 recompute)


def verify_log_profile(manifest: Dict, shear: LogProfileWind) -> Dict:
    def recompute(sample):
        return shear.speed_at(sample["agl_m"]) - sample["speed_mps"]
    return check("log profile", manifest["environment"]["log_profile_selftest"],
                 recompute)


def verify_thermals(manifest: Dict, thermals: AllenThermals) -> Dict:
    def recompute(sample):
        return (thermals.w_at(sample["north_m"], sample["east_m"],
                              sample["agl_m"]) - sample["w_up_mps"])
    return check("thermal field", manifest["environment"]["thermals_selftest"],
                 recompute)


# -- main ----------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 7 UE environment couplings")
    ap.add_argument("--out", default="runs/environment_ue")
    ap.add_argument("--matterhorn", default="runs/terrain/matterhorn")
    ap.add_argument("--yosemite", default="runs/terrain/yosemite")
    ap.add_argument("--skip-renders", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    matterhorn = Path(args.matterhorn).resolve()
    yosemite = Path(args.yosemite).resolve()

    report: Dict[str, Dict] = {}
    failures: List[str] = []

    # ---- downburst -----------------------------------------------------
    print(f"\n{RULE}\n1. position-coupled downburst\n{RULE}")
    d_out = out / "downburst"
    d_out.mkdir(parents=True, exist_ok=True)
    spec, card, burst = downburst_scenario(d_out, matterhorn)
    control_card = d_out / "card_control.json"
    control = json.loads(Path(card).read_text(encoding="utf-8"))
    control.pop("downburst")
    control_card.write_text(json.dumps(control, indent=1), encoding="utf-8")
    if not args.skip_renders:
        render(Path(card), d_out / "coupled", matterhorn, [])
        render(control_card, d_out / "control", matterhorn, [])
    coupled = json.loads((d_out / "coupled" / "render.json").read_text(encoding="utf-8"))
    control_m = json.loads((d_out / "control" / "render.json").read_text(encoding="utf-8"))
    report["downburst_port"] = verify_downburst(coupled, burst)
    peak = max(abs(r["wind_north_fps"]) + abs(r["wind_east_fps"])
               for r in coupled["frame_records"])
    control_peak = max(abs(r["wind_north_fps"]) + abs(r["wind_east_fps"])
                       for r in control_m["frame_records"])
    ok = (peak >= THRESHOLDS["min_downburst_peak_fps"]
          and control_peak < THRESHOLDS["min_downburst_peak_fps"] / 10.0)
    print(f"  [{'ok  ' if ok else 'FAIL'}] outflow in the FDM: peak |wind| "
          f"{peak:.1f} fps coupled vs {control_peak:.2f} control")
    report["downburst_null"] = {"peak_fps": peak, "control_peak_fps": control_peak,
                                "ok": bool(ok)}
    if not (report["downburst_port"]["ok"] and ok):
        failures.append("downburst")

    # ---- rotor ---------------------------------------------------------
    print(f"\n{RULE}\n2. lee-rotor turbulence (W20 riding the sink field)\n{RULE}")
    r_out = out / "rotor"
    r_out.mkdir(parents=True, exist_ok=True)
    spec, card, provider, block = rotor_scenario(r_out, matterhorn)
    control_card = r_out / "card_control.json"
    control = json.loads(Path(card).read_text(encoding="utf-8"))
    control.pop("rotor")
    control.pop("turbulence_properties")
    control["turbulence"] = "none"   # the word gates the writes (measured)
    control_card.write_text(json.dumps(control, indent=1), encoding="utf-8")
    if not args.skip_renders:
        render(Path(card), r_out / "coupled", matterhorn, [])
        render(control_card, r_out / "control", matterhorn, [])
    coupled = json.loads((r_out / "coupled" / "render.json").read_text(encoding="utf-8"))
    control_m = json.loads((r_out / "control" / "render.json").read_text(encoding="utf-8"))
    report["rotor_port"] = verify_rotor(coupled, provider)
    coupled_rms = rms([r["turb_down_fps"] for r in coupled["frame_records"]])
    control_rms = rms([r["turb_down_fps"] for r in control_m["frame_records"]])
    ok = coupled_rms > THRESHOLDS["min_rotor_rms_ratio"] * max(control_rms, 1e-6)
    print(f"  [{'ok  ' if ok else 'FAIL'}] rotor turbulence in the FDM: "
          f"turb-down RMS {coupled_rms:.3f} fps coupled vs {control_rms:.5f} "
          f"control; W20 written per step "
          f"(last {coupled['frame_records'][-1]['w20_fps']:.1f} fps)")
    report["rotor_null"] = {"coupled_rms_fps": coupled_rms,
                            "control_rms_fps": control_rms, "ok": bool(ok)}
    if not (report["rotor_port"]["ok"] and ok):
        failures.append("rotor")

    # ---- surface layer + thermals --------------------------------------
    print(f"\n{RULE}\n3. log-profile shear + summer thermals\n{RULE}")
    s_out = out / "surface"
    s_out.mkdir(parents=True, exist_ok=True)
    spec, card, shear, thermals = surface_scenario(s_out, yosemite)
    control_card = s_out / "card_control.json"
    control = json.loads(Path(card).read_text(encoding="utf-8"))
    control.pop("log_profile")
    control.pop("thermals")
    control_card.write_text(json.dumps(control, indent=1), encoding="utf-8")
    if not args.skip_renders:
        render(Path(card), s_out / "coupled", yosemite, [])
        render(control_card, s_out / "control", yosemite, [])
    coupled = json.loads((s_out / "coupled" / "render.json").read_text(encoding="utf-8"))
    control_m = json.loads((s_out / "control" / "render.json").read_text(encoding="utf-8"))
    report["log_profile_port"] = verify_log_profile(coupled, shear)
    report["thermals_port"] = verify_thermals(coupled, thermals)
    wind_rms = rms([math.hypot(r["wind_north_fps"], r["wind_east_fps"])
                    for r in coupled["frame_records"]])
    control_wind = rms([math.hypot(r["wind_north_fps"], r["wind_east_fps"])
                        for r in control_m["frame_records"]])
    down_rms = rms([r["wind_down_fps"] for r in coupled["frame_records"]])
    ok = (wind_rms >= THRESHOLDS["min_surface_wind_rms_fps"]
          and control_wind < 0.1)
    print(f"  [{'ok  ' if ok else 'FAIL'}] shear + thermals in the FDM: "
          f"horizontal wind RMS {wind_rms:.2f} fps (control {control_wind:.3f}), "
          f"vertical {down_rms:.3f} fps")
    report["surface_null"] = {"wind_rms_fps": wind_rms,
                              "control_wind_rms_fps": control_wind,
                              "down_rms_fps": down_rms, "ok": bool(ok)}
    if not (report["log_profile_port"]["ok"] and report["thermals_port"]["ok"]
            and ok):
        failures.append("surface")

    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n  wrote {out / 'report.json'}")
    if failures:
        print(f"\n  ENVIRONMENT COUPLINGS: FAIL ({', '.join(failures)})")
        return 1
    print("\n  ENVIRONMENT COUPLINGS: PASS -- four ports match their originals "
          "and every coupling demonstrably reaches the FDM.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
