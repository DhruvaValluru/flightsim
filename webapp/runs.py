"""The web app's run manager: spec in, honest clip out.

Everything here REUSES machinery that already passed a gate. The card comes
from core.scenario.card.write_run_card; the scene tables, render command and
encode step are the showcase matrix's own; the telemetry panel is the same
strip every showcase clip carries. What this module adds is orchestration:

* scene selection -- an existing bake is reused when the spec's lat/lon sits
  on it (matched against core.terrain.glo30.LOCATIONS); a mountainous spec
  with no location gets the synthesised control ridge, clearly labeled; a
  flat spec renders over the labeled flat slab with no scenery claim.
* turbulence seed derivation -- a turbulent spec whose seed is still the
  default gets one derived from the spec digest, recorded as derived.
* the single-instance editor lock (gotcha 9) -- one render at a time, and
  never while any other editor process (a matrix run) owns the editor.
* provenance -- prompt, compiler, model id and raw LLM response go into a
  UTF-8 sidecar written by Python. Nothing non-ASCII enters any UE-written
  manifest (gotcha 13).

The render duration is capped at the showcase's 22 s per clip so a casual
prompt cannot queue an hour of editor time; the cap is recorded in the run.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(REPO))

from core.scenario.card import write_run_card  # noqa: E402
from core.scenario.spec import ScenarioSpec  # noqa: E402
from core.scenario.validate import MIN_CLEARANCE_M  # noqa: E402
from core.terrain.glo30 import (  # noqa: E402
    LOCATIONS, bake, dynamic_location, orographic_card_block, utm_zone_crs,
)
from experiments.showcase_matrix import (  # noqa: E402
    AIRFRAMES,
    EDITOR,
    FPS,
    HEIGHT,
    SHOWCASE_DOUBLET,
    TIME_OF_DAY,
    VISIBILITY,
    WIDTH,
    encode_clip,
)
from experiments.showcase_panel import build_panel_clip  # noqa: E402

#: Render length cap, seconds. The showcase's own clip length; a spec asking
#: for more still records the full duration in its spec -- only the clip is
#: capped, and the run says so.
CLIP_SECONDS = 22.0

#: How close (degrees) the spec's origin must sit to a bake's origin for the
#: bake to be reused. ~0.1 deg is ~11 km: on the bake or not at all.
LOCATION_TOLERANCE_DEG = 0.1


@dataclass
class RunState:
    run_id: str
    status: str = "queued"      # queued|rendering|encoding|panel|done|failed
    detail: str = ""
    spec_digest: str = ""
    scene: Dict = field(default_factory=dict)
    clip: Optional[str] = None  # path when done
    started: float = field(default_factory=time.time)
    events: List[Dict] = field(default_factory=list)
    # For the aero panel: the model's measured reference speeds (display
    # marks with provenance) and the run's honesty strip (turbulence word +
    # seed + visual-only label, wind, physics ground).
    reference: Optional[Dict] = None
    conditions: Dict = field(default_factory=dict)

    def push(self, status: str, detail: str = "") -> None:
        self.status = status
        self.detail = detail
        self.events.append({"t": time.time(), "status": status,
                            "detail": detail})

    def as_dict(self) -> Dict:
        return {"run_id": self.run_id, "status": self.status,
                "detail": self.detail, "spec_digest": self.spec_digest,
                "scene": self.scene, "clip": self.clip,
                "started": self.started, "events": self.events[-20:],
                "reference": self.reference, "conditions": self.conditions}


def editor_running() -> bool:
    """Gotcha 9. Matches the engine's editor binaries only -- not the
    UnrealEditorServices helper or the Epic launcher, which live at other
    paths and hold no editor lock. Off-mac there is no editor to lock
    (the UE half refuses by name before this matters) and no pgrep to
    call on Windows."""
    from core.util.platform import is_mac

    if not is_mac():
        return False
    probe = subprocess.run(["pgrep", "-f", "Binaries/Mac/UnrealEditor"],
                           capture_output=True, text=True)
    return probe.returncode == 0 and probe.stdout.strip() != ""


def _dynamic_scenes(dynamic_dir: Path) -> List[Dict]:
    """Registry of on-demand GLO-30 bakes: one .scene.json per bake,
    written by bake_on_demand after verification passed. Scanned fresh on
    every call -- a bake finished mid-session is pickable immediately."""
    scenes = []
    if not Path(dynamic_dir).is_dir():
        return scenes
    for sidecar in sorted(Path(dynamic_dir).glob("*.scene.json")):
        entry = json.loads(sidecar.read_text(encoding="utf-8"))
        raster = Path(dynamic_dir) / f"{entry['key']}.r16"
        if raster.is_file():
            entry["terrain"] = str(raster.with_suffix(""))
            scenes.append(entry)
    return scenes


def needs_dynamic_bake(spec: ScenarioSpec) -> Optional[Dict]:
    """None, or the named refusal for USER-stated coordinates that no bake
    covers yet.

    Stated coordinates mean "fly at that real place": defaulted and
    placed-on-scene coordinates never trigger (this runs BEFORE
    place_on_scene), and coordinates already on a curated or dynamic bake
    pass through. The /bake endpoint clears the refusal; nothing here
    downloads anything -- an HTTP /run stays fast and its digest stays the
    digest of what actually runs.
    """
    if (str(spec.latitude.source) != "user"
            or str(spec.longitude.source) != "user"):
        return None
    scene = pick_scene(spec)
    # The synthesised control ridge is NOT a place (the ERA5 doctrine):
    # stated coordinates that fall on no real bake refuse here even when
    # a leftover terrain_elevation would otherwise select the control
    # scene (measured: a scene-set spec whose coordinates were then
    # edited to London silently picked the control ridge).
    if scene.get("terrain") is not None and scene.get("key") != "control":
        return None
    lat = float(spec.latitude.value)
    lon = float(spec.longitude.value)
    return {
        "constraint": "terrain.unbaked",
        "message": f"no GLO-30 bake covers the stated coordinates "
                   f"({lat:.4f}, {lon:.4f}); POST /bake with them to fetch "
                   f"and verify that terrain (first fetch downloads tiles, "
                   f"a few minutes), then run again",
        "latitude": lat, "longitude": lon,
    }


def bake_on_demand(lat: float, lon: float) -> Dict:
    """Fetch, bake and verify GLO-30 for arbitrary coordinates; register
    the scene. Raises (DEMError / URLError by name) rather than writing an
    unverified or empty bake -- open ocean has no tiles and says so."""
    location = dynamic_location(lat, lon)
    dynamic_dir = REPO / "runs" / "terrain" / "dynamic"
    raster = dynamic_dir / f"{location.key}.r16"
    if not raster.is_file():
        bake(location, REPO / "data" / "glo30", dynamic_dir)
    sidecar = dynamic_dir / f"{location.key}.scene.json"
    entry = {"key": location.key, "title": location.title,
             "origin_lat": location.origin_lat,
             "origin_lon": location.origin_lon, "crs": location.crs,
             "identity": "source-verified only (no named summits)"}
    sidecar.write_text(json.dumps(entry, indent=1), encoding="utf-8")
    entry["terrain"] = str(raster.with_suffix(""))
    return entry


def pick_scene(spec: ScenarioSpec) -> Dict:
    """Choose the scene the spec's geography earns -- never silently."""
    lat = float(spec.latitude.value)
    lon = float(spec.longitude.value)
    terrain_dir = REPO / "runs" / "terrain"
    for key, location in LOCATIONS.items():
        if (abs(lat - location.origin_lat) <= LOCATION_TOLERANCE_DEG
                and abs(lon - location.origin_lon) <= LOCATION_TOLERANCE_DEG
                and (terrain_dir / f"{key}.r16").is_file()):
            imagery = terrain_dir / f"{key}_imagery.json"
            return {
                "key": key, "kind": "real (Copernicus GLO-30)",
                "terrain": str(terrain_dir / key),
                "imagery": str(imagery) if imagery.is_file() else None,
                "label": f"georeferenced {key} raster at true position; "
                         f"physics ground is the heightfield raster "
                         f"(AGL parity measured); track pre-flown for "
                         f"clearance",
            }
    for scene in _dynamic_scenes(terrain_dir / "dynamic"):
        if (abs(lat - scene["origin_lat"]) <= LOCATION_TOLERANCE_DEG
                and abs(lon - scene["origin_lon"]) <= LOCATION_TOLERANCE_DEG):
            return {
                "key": scene["key"], "kind": "real (Copernicus GLO-30, "
                                             "on-demand bake)",
                "terrain": scene["terrain"], "imagery": None,
                "label": f"GLO-30 bake near {scene['origin_lat']:.3f}, "
                         f"{scene['origin_lon']:.3f}; identity "
                         f"source-verified only (no named summits); "
                         f"physics ground is the heightfield raster (AGL "
                         f"parity measured); track pre-flown for clearance",
            }
    if float(spec.terrain_elevation.value) > 0.0:
        if (terrain_dir / "control_ridge.r16").is_file():
            return {
                "key": "control", "kind": "synthesised control ridge",
                "terrain": str(terrain_dir / "control_ridge"),
                "imagery": None,
                "label": "synthesised ridge (prescribed statistics, not a "
                         "place); physics ground is the heightfield raster "
                         "(AGL parity measured); track pre-flown for "
                         "clearance",
            }
    return {"key": "flat", "kind": "flat", "terrain": None, "imagery": None,
            "label": "no terrain requested; flat slab at the spec's "
                     "elevation"}


def place_on_scene(spec: ScenarioSpec) -> None:
    """A spec that earns the control ridge flies AT the control ridge.

    The synthesised ridge is georeferenced at an arbitrary position (it is
    not a place); a mountainous spec carrying the default 0,0 origin would
    fly hundreds of km from the mesh and render empty sky (measured: run
    96147222ef39 -- 'why is there no mountains'). Same convention as the
    showcase matrix: the flight origin moves to the raster centre, recorded
    in the spec's own provenance, and -- like every recorded transformation
    -- BEFORE the digest is answered. Real bakes are untouched: their specs
    already sit on the bake or they would not have earned it.
    """
    scene = pick_scene(spec)
    if scene["key"] != "control":
        return
    from pyproj import Transformer

    from core.terrain.heightfield import Heightfield

    baked = Heightfield.read(Path(scene["terrain"]))
    min_x, min_y, max_x, max_y = baked.bounds_m()
    centre_x, centre_y = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0
    inverse = Transformer.from_crs(baked.georeference.crs, "EPSG:4326",
                                   always_xy=True)
    lon, lat = inverse.transform(centre_x, centre_y)
    frm = "control ridge centre (synthesised terrain is not a place)"
    spec.set("latitude", round(float(lat), 6), frm=frm)
    spec.set("longitude", round(float(lon), 6), frm=frm)


#: AGL the planner AIMS for when it may move a defaulted altitude:
#: comfortably above the validator's bare margin, in showcase territory.
PLANNED_CLEARANCE_M = 300.0
#: The planned cruise floor over the measured stall speed. Vref is 1.3 x Vs
#: by the same envelope code; 1.25 x sits between the validator's refusal
#: line (1.05 x) and Vref, and the definitive trim probe still runs after.
PLANNED_SPEED_MARGIN = 1.25
#: Sources the planners may move: the system's own choices. "default"
#: (nobody said it), "model" (the scene director's declared guess) and
#: "derived" (an earlier planner). NEVER "user" or "inferred" -- those are
#: the user's words, and a value they command that cannot fly is refused
#: by name, not silently moved. This line is load-bearing.
PLANNABLE_SOURCES = ("default", "model", "derived")


def _fly_clearance_track(spec: ScenarioSpec, ground, script,
                         seconds: float, orographic=None):
    """The scripted flight on the same JSBSim, for the clearance gate.

    The Zermatt valley run's fly_headless, generalised: the SAME control
    script the card will carry (deltas on the trimmed aileron, held until
    the next entry -- the parity-tested convention) and the SAME steady
    wind, so drift shapes the track that gets checked. Turbulence is not
    modelled here (visual-only realisations; the clearance margin covers
    the excursion scale the recordings show).

    Two couplings the real run enforces are pre-flown here too:

    * ``orographic`` (an OrographicWind built from the SAME card block the
      run will carry) writes the terrain-forced vertical wind every step,
      so a plan through lee sink descends in the plan the way the aircraft
      will descend in the run;
    * clearance_m is the MINIMUM over the airframe's span stations (the
      same stations, rotation and lookup as core.terrain.contact -- the
      check that ends the real run), not just the CG: a bank that lowers a
      wingtip toward a slope tightens the planned clearance. Sampled every
      12th step; the run checks every step.
    """
    from core.fdm import FlightDynamics, mode_for
    from core.fdm import units as u
    from core.scenario.runner import wind_components_fps
    from core.terrain.contact import station_offsets_ned

    fdm = FlightDynamics(str(spec.aircraft.value),
                         rate_hz=float(spec.rate.value))
    fdm.set_initial_conditions(
        {"h-sl-ft": u.m_to_ft(float(spec.altitude.value)),
         "vc-kts": float(spec.airspeed.value), "gamma-deg": 0.0,
         "phi-deg": 0.0, "psi-true-deg": float(spec.heading.value),
         "beta-deg": 0.0, "lat-geod-deg": float(spec.latitude.value),
         "long-gc-deg": float(spec.longitude.value),
         "terrain-elevation-ft": u.m_to_ft(
             float(spec.terrain_elevation.value))})
    wind_kt = float(spec.wind_speed.value)
    if wind_kt > 0.0:
        north_fps, east_fps = wind_components_fps(
            wind_kt, float(spec.wind_direction.value))
        fdm.props.set_many({"atmosphere/wind-north-fps": north_fps,
                            "atmosphere/wind-east-fps": east_fps,
                            "atmosphere/wind-down-fps": 0.0})
    fdm.start_engines()
    fdm.trim(mode_for(crosswind=wind_kt > 0.0))
    fdm.hold_mass(True)
    trimmed_aileron = fdm.props.get("fcs/aileron-cmd-norm")
    span_m = u.ft_to_m(fdm.props.get("metrics/bw-ft"))
    origin_x = origin_y = 0.0
    if orographic is not None:
        # The provider's local frame is north/east about the card origin --
        # the raster centre after place_on_scene -- exactly the UE host's
        # LocalSceneCoords frame.
        origin_x, origin_y = ground.project(float(spec.latitude.value),
                                            float(spec.longitude.value))

    track = []
    applied = -1
    for i in range(int(round(seconds * fdm.rate_hz))):
        t = fdm.sim_time
        current = applied
        for j, entry in enumerate(script):
            if entry["t_s"] <= t:
                current = j
        if current != applied:
            applied = current
            fdm.set_controls(aileron=trimmed_aileron
                             + script[applied]["aileron"])
        if orographic is not None:
            s = fdm.state()
            x, y = ground.project(s.lat_deg, s.lon_deg)
            agl = s.altitude_m - ground.heightfield.elevation_at(x, y)
            north, east = y - origin_y, x - origin_x
            w_up = ((orographic.linear_updraught(north, east)
                     - orographic.lee_sink(north, east))
                    * orographic.decay(agl))
            fdm.props.set("atmosphere/wind-down-fps", -w_up / 0.3048)
        fdm.step()
        if i % 12 == 0:
            s = fdm.state()
            terrain = (ground.elevation_at(s.lat_deg, s.lon_deg)
                       if ground.contains(s.lat_deg, s.lon_deg) else 0.0)
            clearance = s.altitude_m - terrain
            x, y = ground.project(s.lat_deg, s.lon_deg)
            if not track:
                origin_xy = (x, y)      # start position: the frame the
            for _, north, east, down in station_offsets_ned(  # card's
                    s.roll_deg, s.pitch_deg, s.heading_deg, span_m):
                px, py = x + east, y + north                  # event
                if not ground.heightfield.contains(px, py):   # blocks use
                    continue
                clearance = min(
                    clearance, (s.altitude_m - down)
                    - ground.heightfield.elevation_at(px, py))
            track.append({"terrain_m": terrain,
                          "cg_clearance_m": s.altitude_m - terrain,
                          "clearance_m": clearance,
                          # Position relative to the start, so an event
                          # aimed at the track can be placed ON the track
                          # the banked script actually flies.
                          "north_m": y - origin_xy[1],
                          "east_m": x - origin_xy[0]})
    return track


def _orographic_provider(spec: ScenarioSpec, scene: Dict):
    """The SAME orographic field the run card will carry, for the pre-flight.

    Built from orographic_card_block's own numbers (wind, wavelength, decay
    height, projected origin), so the plan and the run cannot model two
    different mountains. None in calm air: orographic forcing is wind over
    terrain, and with no wind there is honestly nothing to couple -- the
    conditions strip says so rather than inventing airflow.
    """
    wind_kt = float(spec.wind_speed.value)
    if not scene.get("terrain") or wind_kt <= 0.0:
        return None
    from core.environment.terrain_field import OrographicWind
    from core.terrain.ground import terrain_field_at
    from core.terrain.heightfield import Heightfield

    block = orographic_card_block(
        Path(scene["terrain"]), float(spec.latitude.value),
        float(spec.longitude.value), wind_kt,
        round(float(spec.wind_direction.value)))
    field = terrain_field_at(Heightfield.read(Path(scene["terrain"])),
                             block["origin_x_m"], block["origin_y_m"],
                             wavelength_m=block["wavelength_m"])
    return OrographicWind(field, wind_speed_mps=block["wind_speed_mps"],
                          wind_from_deg=block["wind_from_deg"],
                          decay_height_m=block["decay_height_m"])


#: Channels the effect report compares, all recorded by both sources.
EFFECT_CHANNELS = ("altitude_m", "agl_m", "n_z", "roll_deg", "pitch_deg",
                   "alpha_deg", "wind_down_mps", "tas_kt")


def _effect_report(spec: ScenarioSpec, scene: Dict, script, seconds: float,
                   telemetry_path: Path, out_path: Path) -> None:
    """Baseline-vs-actual: what the terrain-air coupling did to this run.

    The baseline is the SAME spec -- same trim, same steady wind, same
    control script, same raster under the ground model -- flown headlessly
    with the coupling severed (no orographic lift/sink, no lee-rotor), and
    sampled on the same 0.1 s clock as the run's telemetry. The comparison
    is cross-host by construction (the clip's telemetry comes from the UE
    host, the baseline from the headless one); the two hosts step the same
    JSBSim through the parity discipline Gate 5 measured, and the report
    says so rather than hiding it.
    """
    from core.fdm import FlightDynamics, mode_for
    from core.fdm import units as u
    from core.scenario.runner import wind_components_fps
    from core.terrain.ground import TerrainGround
    from core.terrain.heightfield import Heightfield

    ground = (TerrainGround(Heightfield.read(Path(scene["terrain"])))
              if scene.get("terrain") else None)
    fdm = FlightDynamics(str(spec.aircraft.value),
                         rate_hz=float(spec.rate.value))
    fdm.set_initial_conditions(
        {"h-sl-ft": u.m_to_ft(float(spec.altitude.value)),
         "vc-kts": float(spec.airspeed.value), "gamma-deg": 0.0,
         "phi-deg": 0.0, "psi-true-deg": float(spec.heading.value),
         "beta-deg": 0.0, "lat-geod-deg": float(spec.latitude.value),
         "long-gc-deg": float(spec.longitude.value),
         "terrain-elevation-ft": u.m_to_ft(
             float(spec.terrain_elevation.value))})
    wind_kt = float(spec.wind_speed.value)
    if wind_kt > 0.0:
        north_fps, east_fps = wind_components_fps(
            wind_kt, float(spec.wind_direction.value))
        fdm.props.set_many({"atmosphere/wind-north-fps": north_fps,
                            "atmosphere/wind-east-fps": east_fps,
                            "atmosphere/wind-down-fps": 0.0})
    fdm.start_engines()
    fdm.trim(mode_for(crosswind=wind_kt > 0.0))
    fdm.hold_mass(True)
    trimmed_aileron = fdm.props.get("fcs/aileron-cmd-norm")

    every = max(1, int(round(0.1 * fdm.rate_hz)))
    baseline: Dict[str, List[float]] = {ch: [] for ch in
                                        ("t",) + EFFECT_CHANNELS}
    applied = -1
    for i in range(int(round(seconds * fdm.rate_hz))):
        if i % every == 0:
            s = fdm.state()
            baseline["t"].append(round(i / fdm.rate_hz, 3))
            for ch in EFFECT_CHANNELS:
                baseline[ch].append(round(float(getattr(s, ch)), 5))
        t = fdm.sim_time
        current = applied
        for j, entry in enumerate(script):
            if entry["t_s"] <= t:
                current = j
        if current != applied:
            applied = current
            fdm.set_controls(aileron=trimmed_aileron
                             + script[applied]["aileron"])
        if ground is not None:
            ground.apply(fdm)
        fdm.step()

    actual = json.loads(Path(telemetry_path).read_text(encoding="utf-8"))["columns"]
    n = min(len(baseline["t"]), len(actual["t"]))

    def stats(xs):
        import math
        mean = sum(xs) / len(xs)
        return {"mean": round(mean, 5), "min": round(min(xs), 5),
                "max": round(max(xs), 5),
                "rms": round(math.sqrt(sum((x - mean) ** 2
                                           for x in xs) / len(xs)), 5)}

    channels, report = {"t": baseline["t"][:n]}, {}
    for ch in EFFECT_CHANNELS:
        b, a = baseline[ch][:n], [float(v) for v in actual[ch][:n]]
        channels[ch] = {"baseline": b, "actual": a}
        report[ch] = {"baseline": stats(b), "actual": stats(a)}
    out_path.write_text(json.dumps({
        "claim": "baseline = the same spec (same trim, steady wind, control "
                 "script, same ground model) flown HEADLESSLY with every "
                 "terrain- and surface-air coupling severed (no orographic "
                 "lift/sink, no lee-rotor, no surface shear or thermals); "
                 "actual = this clip's own recorded telemetry (UE host). "
                 "Cross-host comparison under the Gate 5 parity discipline. "
                 "The models' limits (VALIDITY 2.8, 2.10) apply to "
                 "everything shown.",
        "interval_s": 0.1, "samples": n,
        "channels": channels, "stats": report,
    }), encoding="utf-8")


def _ridge_axis_deg(samples, scale_m: float) -> float:
    """Gradient-weighted principal ridge axis, degrees true in [0, 180).

    The structure-tensor doubled-angle trick: every pixel's elevation
    gradient is a vector pointing ACROSS the local slope; summing
    w*sin(2b) / w*cos(2b) with w = |g|^2 averages the 180-deg-ambiguous
    gradient bearings coherently, and the ridge AXIS is perpendicular to
    that mean gradient. Row 0 is northernmost (Heightfield's own
    convention), so north = -d/drow; bearing b of (east, north) has
    w*sin(2b) = 2*ge*gn and w*cos(2b) = gn^2 - ge^2 -- no per-pixel atan.
    Deterministic: pure numpy on the baked raster, no RNG.
    """
    import math

    import numpy as np

    z = samples.astype(np.float64) * float(scale_m)
    # Orientation only: subsample large rasters (everest is ~3600^2); the
    # principal axis is a bulk statistic and survives a stride.
    stride = max(1, max(z.shape) // 512)
    z = z[::stride, ::stride]
    g_row, g_col = np.gradient(z)
    ge, gn = g_col, -g_row
    s2 = float(2.0 * (ge * gn).sum())
    c2 = float((gn * gn - ge * ge).sum())
    grad_bearing = math.degrees(0.5 * math.atan2(s2, c2)) % 180.0
    return (grad_bearing + 90.0) % 180.0


def plan_terrain_environment(spec: ScenarioSpec) -> None:
    """Mountains with wind are PHYSICALLY different from flatland with
    wind, not just relabeled: orographic lift/sink and lee rotors exist
    only for flow ACROSS the ridges (VALIDITY 2.8), and a track that
    never crosses the relief measures nothing. This planner points the
    SYSTEM-CHOSEN wind across the scene raster's principal ridge axis and
    the SYSTEM-CHOSEN heading along it, so the pre-flown clearance track
    (which flies this same wind through the same orographic field)
    actually samples what the prompt asked for.

    Rules, same discipline as every planner: flat scenes are a no-op;
    only PLANNABLE_SOURCES move (via spec.plan, recorded, re-plannable);
    a user-stated wind direction or heading is NEVER moved; a calm spec
    (wind 0) gets no invented wind direction. The along-axis heading is
    deliberately the seed of the open valley-following thread: a heading
    SCHEDULE derived from the raster is the natural extension of this
    exact computation.
    """
    scene = pick_scene(spec)
    if not scene.get("terrain"):
        return
    from core.terrain.heightfield import Heightfield

    heightfield = Heightfield.read(Path(scene["terrain"]))
    axis = _ridge_axis_deg(heightfield.samples, heightfield.scale_m)
    if (float(spec.wind_speed.value) > 0.0
            and str(spec.wind_direction.source) in PLANNABLE_SOURCES):
        # WHOLE degrees: the UE plugin's wind initial condition is
        # integral and the commandlet refuses fractional directions by
        # name (measured); a bulk raster statistic has no sub-degree
        # precision to lose.
        spec.plan(
            "wind_direction", float(round((axis + 90.0) % 360.0)),
            frm=f"across ridge axis {axis:.0f} deg computed from the "
                f"scene raster -- orographic forcing requires cross-ridge "
                f"flow (VALIDITY 2.8); a stated direction is never moved")
    if str(spec.heading.source) in PLANNABLE_SOURCES:
        spec.plan(
            "heading", float(round(axis)),
            frm=f"along ridge axis {axis:.0f} deg computed from the scene "
                f"raster, so the track samples the relief")


#: Scene-setting: surface class -> the curated bake that stages it.
#: city has no bake (flat + the city roughness class is the honest scene)
#: and ocean opts out entirely.
SCENE_SETTING_BAKES = {"desert": "grand_canyon", "grassland": "flint_hills",
                       "forest": "yosemite"}
#: Prompt words that opt OUT of scene-setting: the user asked for the flat
#: slab (or water) and gets exactly that.
SCENE_SETTING_OPT_OUT = ("flat", "featureless", "ocean", "open sea",
                         "over the sea", "over water", "offshore")


def renderable_aircraft() -> List[str]:
    """Aircraft with a REAL licensed 3-D model imported on this machine
    (a mesh_manifest.json under assets/generated). Everything else is
    physics-only: real JSBSim aerodynamics, no honest picture."""
    return sorted(p.parent.name for p in
                  (REPO / "assets" / "generated").glob("*/mesh_manifest.json"))


def refuse_placeholder_mesh(spec: ScenarioSpec) -> Optional[Dict]:
    """OWNER'S RULE (2026-08-14): a placeholder airframe never renders.

    On a machine with imported meshes, a render request for an aircraft
    without one refuses BY NAME instead of showing blocks (measured: an
    F-15 run rendered the placeholder and the owner rejected it). A
    machine with NO meshes imported (fresh clone, CI) is untouched --
    the render pipeline reports its own missing-assets state there.
    """
    have = renderable_aircraft()
    aircraft = str(spec.aircraft.value)
    if not have or aircraft in have:
        return None
    return {
        "constraint": "aircraft.mesh",
        "message": f"the {aircraft} has real flight physics but no "
                   f"licensed 3-D model, and placeholder airframes never "
                   f"render. Renderable aircraft on this machine: "
                   f"{', '.join(have)}.",
    }


def plan_scene_setting(spec: ScenarioSpec) -> None:
    """No featureless slabs unless asked for (user request 2026-08-13:
    "have the llm not infer flat land"). A spec whose location NOBODY
    chose -- coordinates still source default -- is placed on the
    best-fitting curated bake DETERMINISTICALLY from the spec's own
    fields, because the model proved erratic at this exact judgment
    (measured: it staged 'fly over flat ground' and left 'over the
    desert' flat, in the same session). Rules:

    * any stated/inferred/model/derived location wins -- this planner
      only ever touches all-default coordinates;
    * a prompt asking for flat/featureless/ocean ground opts out, as
      does an ocean surface (no ocean bake -- the flat slab IS the
      honest stage there, stated);
    * unnamed mountains keep their existing scene (the generic ridge
      via inferred terrain_elevation -- placed by place_on_scene);
    * surface class picks the bake (desert -> grand_canyon, grassland ->
      flint_hills, forest -> yosemite); anything else -- including a
      bare technical prompt -- gets the gentle prairie as the neutral
      stage. Recorded via spec.plan (derived, re-plannable, visible in
      the table with the opt-out stated).
    """
    if (str(spec.latitude.source) != "default"
            or str(spec.longitude.source) != "default"):
        return
    if str(spec.terrain_elevation.source) != "default":
        return          # unnamed mountains: the generic ridge is the scene
    prompt = (spec.prompt or "").lower()
    if any(word in prompt for word in SCENE_SETTING_OPT_OUT):
        return
    surface = str(spec.surface.value)
    if surface == "ocean" or surface == "city":
        return
    key = SCENE_SETTING_BAKES.get(surface, "flint_hills")
    location = LOCATIONS[key]
    from core.nl.llm_compiler import LOCATION_TERRAIN_ELEVATION_M

    frm = (f"scene-setting: no place stated, so the {key} bake stages the "
           f"scene (surface {surface!r}); say 'flat ground' to opt out")
    spec.plan("latitude", location.origin_lat, frm=frm)
    spec.plan("longitude", location.origin_lon, frm=frm)
    spec.plan("terrain_elevation", LOCATION_TERRAIN_ELEVATION_M[key], frm=frm)


def plan_flyable_defaults(spec: ScenarioSpec) -> None:
    """DEFAULTED numbers are planned into the flyable envelope, recorded.

    Measured complaint (2026-08-13): "rough wind over mountains" with the
    everest answer left the defaulted altitude/airspeed pair outside the
    B747's measured envelope, and the page refused a scenario whose every
    number the system itself had chosen. The discipline is
    plan_terrain_flight's: only system-chosen fields (source default or
    derived) move, every move is a recorded pre-digest edit
    (``spec.plan``: the source becomes ``derived``, and a later planner
    may refine it again), and a user-stated value is never touched -- its
    refusals stand, by name.

    Two floors, in dependency order:

    * altitude: a defaulted altitude below the location's terrain datum is
      raised to datum + PLANNED_CLEARANCE_M. This is the cheap, raster-free
      floor from the spec's own terrain_elevation field; the run's
      plan_terrain_flight still pre-flies the real track and raises further
      for the actual peaks.
    * airspeed: a defaulted airspeed below the validator's stall-margin
      line at the (possibly raised) altitude is raised to
      PLANNED_SPEED_MARGIN x the model's own measured Vs, rounded up to
      5 kt. The measurement is reference_speeds -- the same envelope code
      the validator refuses with -- and validate()'s trim probe still has
      the last word.
    """
    import math

    from core.fdm import FDMError, FlightDynamics
    from core.scenario.envelope import reference_speeds
    from core.scenario.validate import STALL_MARGIN

    plannable = PLANNABLE_SOURCES
    terrain = float(spec.terrain_elevation.value)
    if (str(spec.altitude.source) in plannable
            and float(spec.altitude.value) < terrain + MIN_CLEARANCE_M):
        spec.plan("altitude", float(round(terrain + PLANNED_CLEARANCE_M)),
                  frm=f"raised for the location's terrain datum "
                      f"({terrain:.0f} m + {PLANNED_CLEARANCE_M:.0f} m "
                      f"planned clearance)")
    if str(spec.airspeed.source) not in plannable:
        return
    # The defaulted cruise is filled BEFORE the model decides the
    # aircraft: "a plane" -> c172p leaves a B747's 250 kt default on a
    # Cessna (measured -- TrimError). A still-default airspeed is
    # re-planned to THIS airframe's own documented cruise default first.
    from core.nl.compiler import CRUISE_DEFAULT_KT

    aircraft = str(spec.aircraft.value)
    cruise = CRUISE_DEFAULT_KT.get(aircraft)
    if (str(spec.airspeed.source) == "default" and cruise is not None
            and float(spec.airspeed.value) != cruise):
        spec.plan("airspeed", cruise,
                  frm=f"the {aircraft}'s documented cruise default (the "
                      f"airspeed default was filled before the aircraft "
                      f"was decided)")
    try:
        mass_kg = FlightDynamics(str(spec.aircraft.value)).state().weight_kg
        speeds = reference_speeds(str(spec.aircraft.value), mass_kg,
                                  max(float(spec.altitude.value), 0.0))
    except (FDMError, ValueError):
        return          # validate() names the real problem next
    if float(spec.airspeed.value) < speeds.vs_kt * STALL_MARGIN:
        planned = math.ceil(speeds.vs_kt * PLANNED_SPEED_MARGIN / 5.0) * 5.0
        spec.plan("airspeed", planned,
                  frm=f"raised to {PLANNED_SPEED_MARGIN:g} x the measured "
                      f"stall speed ({speeds.vs_kt:.0f} kt CAS) at "
                      f"{float(spec.altitude.value):.0f} m")


def plan_trim_recovery(spec: ScenarioSpec) -> None:
    """Physics keeps the last word over guesses: a PLANNABLE airspeed the
    aero tables cannot trim (measured -- a model-guessed 120 kt is beyond
    the c172p's level-flight power at 2500 m; the stall floor cannot see
    an upper-envelope miss) is re-planned ONCE to the airframe's own
    documented mid-envelope cruise, recorded. If the trim probe still
    refuses, or the condition was user-stated, the named refusal stands
    untouched -- this is a single recovery step, never a search.
    """
    if str(spec.airspeed.source) not in PLANNABLE_SOURCES:
        return
    from core.nl.compiler import CRUISE_DEFAULT_KT
    from core.scenario.validate import validate

    cruise = CRUISE_DEFAULT_KT.get(str(spec.aircraft.value))
    if cruise is None or float(spec.airspeed.value) == cruise:
        return
    report = validate(spec)
    if report.ok or not any(v.constraint == "envelope.trim_feasible"
                            for v in report.violations):
        return
    old = float(spec.airspeed.value)
    spec.plan("airspeed", cruise,
              frm=f"the {old:g} kt condition could not be trimmed at "
                  f"{float(spec.altitude.value):g} m; re-planned to the "
                  f"airframe's documented mid-envelope cruise")


def plan_terrain_flight(spec: ScenarioSpec) -> Optional[Dict]:
    """Terrain scenes fly IN COORDINATION with the terrain, verifiably.

    Measured complaint: with a flat physics slab under visual mountains,
    a hands-off straight run at a defaulted 3000 m passed THROUGH ridge
    peaks (control ridge tops at 3299 m). This planner is the Zermatt
    discipline applied to every terrain run: the banked S-turn script the
    card will carry is pre-flown headlessly over the scene's own raster,
    wind included; a DEFAULTED altitude is raised to clear the track's
    terrain by the showcase margin (a recorded spec edit, before the
    digest is answered); a USER-stated altitude is never silently moved
    -- a track that cannot keep the validator's clearance is refused by
    name, exactly like the showcase matrix's clearance-scan refusals.
    Returns None (clear) or the violation dict for the refusal.
    """
    scene = pick_scene(spec)
    if not scene.get("terrain"):
        return None
    from core.terrain.ground import TerrainGround
    from core.terrain.heightfield import Heightfield

    ground = TerrainGround(Heightfield.read(Path(scene["terrain"])))
    seconds = min(float(spec.duration.value), CLIP_SECONDS)
    from experiments.showcase_matrix import SHOWCASE_DOUBLET

    orographic = _orographic_provider(spec, scene)
    try:
        track = _fly_clearance_track(spec, ground, SHOWCASE_DOUBLET,
                                     seconds, orographic=orographic)
    except Exception:
        # A spec that cannot even trim (e.g. commanded below its own flat
        # terrain) is not this planner's refusal to make: validate() runs
        # next in the same request and refuses by name, and the render
        # commandlet's VerifyTrimmedCondition guards the same ground.
        return None
    min_clearance = min(p["clearance_m"] for p in track)
    # System-chosen altitudes (default, a model guess, or derived by an
    # earlier planner) may be raised; a user-stated altitude is never
    # moved -- refusal below.
    plannable = str(spec.altitude.source) in PLANNABLE_SOURCES
    if min_clearance >= MIN_CLEARANCE_M and not plannable:
        return None
    if plannable:
        peak = max(p["terrain_m"] for p in track)
        planned = float(round(peak + PLANNED_CLEARANCE_M))
        if planned > float(spec.altitude.value) \
                or min_clearance < MIN_CLEARANCE_M:
            spec.plan("altitude", max(planned, float(spec.altitude.value)),
                      frm=f"raised to clear the terrain under the planned "
                          f"track (peak {peak:.0f} m + "
                          f"{PLANNED_CLEARANCE_M:.0f} m)")
            try:
                track = _fly_clearance_track(spec, ground,
                                             SHOWCASE_DOUBLET, seconds,
                                             orographic=orographic)
                min_clearance = min(p["clearance_m"] for p in track)
            except Exception:
                min_clearance = float("-inf")   # unverifiable = not clear
        if min_clearance >= MIN_CLEARANCE_M:
            return None
    return {
        "constraint": "terrain.clearance",
        "message": "the planned track descends below the clearance margin "
                   "over the scene's terrain (pre-flown headlessly on the "
                   "scene's own raster -- steady wind and orographic "
                   "lift/sink included, clearance taken as the minimum over "
                   "the airframe's span stations, not just the CG)",
        "actual": round(min_clearance, 1),
        "limit": MIN_CLEARANCE_M,
        "unit": "m AGL",
    }


def project_for_ue_host(spec: ScenarioSpec) -> None:
    """The UE hosts have no autopilot: a held state cannot be honoured and
    the commandlet refuses it (correctly -- measured by Gate 8.3's first
    run). Same projection reference_spec applies for every gate: open
    loop, mass held so the clip shows trim quality rather than fuel burn.
    Both edits are recorded in the spec's own provenance."""
    if bool(spec.hold_state.value):
        spec.set("hold_state", False,
                 frm="open loop: the render host has no autopilot")
    if not bool(spec.mass_held.value):
        spec.set("mass_held", True,
                 frm="rendered-clip convention (see reference_spec)")
    # The plugin's only speed initial condition is CALIBRATED airspeed;
    # the commandlet refuses "tas" by name (measured). A GUESSED kind is
    # plannable like any guess -- re-planned to what the host can honour,
    # recorded; a user-stated "true airspeed" keeps its named refusal.
    if (str(spec.airspeed_kind.value) == "tas"
            and str(spec.airspeed_kind.source) in PLANNABLE_SOURCES):
        spec.plan("airspeed_kind", "cas",
                  frm="the render host sets calibrated airspeed only; the "
                      "guessed kind was re-planned (a stated 'true "
                      "airspeed' refuses instead)")


def derive_seed(spec: ScenarioSpec, terrain_coupled: bool = False) -> None:
    """A stochastic spec with the default seed gets one from its digest.

    ``terrain_coupled``: a terrain run with wind carries lee-rotor
    turbulence even when the turbulence word is "none", so it needs a
    recorded seed for the same reason a worded spec does.
    """
    if ((str(spec.turbulence.value) != "none" or terrain_coupled)
            and str(spec.seed.source) == "default"):
        seed = int(spec.digest()[:8], 16) % 1_000_000
        spec.set("seed", seed, frm="derived from spec digest")


#: The storm look: dim low sun + dense grey fog, values probe-calibrated
#: (gotcha 6/7 -- picked by rendering frames, not theory). VISUAL ONLY and
#: labeled so; the storm's physics arrive as card blocks.
STORM_LOOK = {"sun_elev": 10.0, "sun_azim": 180.0, "exposure_bias": 9.6,
              "fog_density": 0.007}


def _projected_origin(spec: ScenarioSpec, scene: Dict):
    """(origin_x, origin_y, scene_crs_for_card): the projected anchor of
    the local north/east frame every position-coupled block uses. Terrain
    scenes project into the raster's own CRS (the terrain declares it to
    the UE host -> card crs None); flat scenes use the spec origin's UTM
    zone and DECLARE it on the card (scene_crs)."""
    from pyproj import Transformer

    if scene.get("terrain"):
        from core.terrain.heightfield import Heightfield

        crs = Heightfield.read(Path(scene["terrain"])).georeference.crs
        declared = None
    else:
        crs = utm_zone_crs(float(spec.latitude.value),
                           float(spec.longitude.value))
        declared = crs
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    ox, oy = transformer.transform(float(spec.longitude.value),
                                   float(spec.latitude.value))
    return float(ox), float(oy), declared


def apply_weather_event(spec: ScenarioSpec) -> None:
    """The thunderstorm COMPOSITION's spec edits, pre-digest and recorded.

    A thunderstorm is severe-turbulence air by the documented composition
    (microburst + severe turbulence + storm look); the word is set only
    when the spec's own word is still the default -- a stated turbulence
    word is never moved. A tornado with a DEFAULTED altitude descends into the
    vortex's modelled depth (plan_weather_event); stated fields never move.
    """
    if (str(spec.weather_event.value) == "thunderstorm"
            and str(spec.turbulence.source) in PLANNABLE_SOURCES):
        spec.plan("turbulence", "severe",
                  frm="thunderstorm composition (documented): microburst + "
                      "severe turbulence + storm look")
    # A tornado also rides violent air, not the smooth-air default: the
    # environment composition plans the SYSTEM-CHOSEN ambient fields to
    # match the event, from the vocabulary's own documented figures. The
    # vortex itself stays a position-coupled field on top of this
    # background -- these edits are the air AROUND it. Stated words and
    # numbers are never moved (plan() refuses them by name).
    if (str(spec.weather_event.value) == "tornado"
            and str(spec.turbulence.source) in PLANNABLE_SOURCES):
        spec.plan("turbulence", "severe",
                  frm="tornado environment (documented composition): the "
                      "vortex rides supercell air, not smooth air; a "
                      "stated turbulence word is never moved")
    if (str(spec.weather_event.value) in ("thunderstorm", "tornado")
            and str(spec.wind_speed.source) in PLANNABLE_SOURCES):
        from core.nl.compiler import WIND_STRENGTH

        spec.plan("wind_speed", WIND_STRENGTH["strong"],
                  frm=f"{spec.weather_event.value} environment (documented "
                      f"composition): background inflow at the vocabulary's "
                      f"own 'strong' figure; a stated wind is never moved")
    plan_weather_event(spec)


def apply_historical_weather(spec: ScenarioSpec) -> Optional[Dict]:
    """ERA5 reanalysis wind for a dated spec, as recorded pre-digest edits.

    None (applied, or nothing to do) or a named refusal dict. Rules, in
    order: no date -> nothing; a USER-stated wind is never moved (the date
    goes to notes instead); the synthesised control ridge is NOT A PLACE,
    so a dated spec there refuses by name; an unreachable archive refuses
    by name rather than guessing a wind.
    """
    date = str(spec.weather_date.value)
    if date == "none":
        return None
    if (str(spec.wind_speed.source) == "user"
            or str(spec.wind_direction.source) == "user"):
        spec.notes.append(
            f"weather_date {date}: the stated wind wins; ERA5 not applied "
            f"(a stated value is never silently moved)")
        return None
    if pick_scene(spec)["key"] == "control":
        return {
            "constraint": "weather.not_a_place",
            "message": "historical weather needs a real place; the "
                       "synthesised control ridge is not one. Name a real "
                       "location or state coordinates.",
        }
    from core.environment.era5 import (
        WeatherUnavailableError, fetch_reanalysis_wind,
    )

    try:
        wx = fetch_reanalysis_wind(
            float(spec.latitude.value), float(spec.longitude.value),
            date, float(spec.altitude.value))
    except WeatherUnavailableError as exc:
        return {"constraint": "weather.unavailable", "message": str(exc)}
    frm = (f"historical weather {date} {wx['hour_utc']:02d}Z at "
           f"{wx['level_note']}; {wx['source']}")
    spec.set("wind_speed", wx["speed_kt"], frm=frm)
    spec.set("wind_direction", wx["from_deg"], frm=frm)
    return None


def plan_weather_event(spec: ScenarioSpec) -> None:
    """A tornado's modelled depth tops out at 3000 m AGL (linear fade from
    1500 m): the DEFAULT 3000 m cruise would fly over a vortex that
    honestly cannot reach it, and the clip would show a tornado doing
    nothing. A DEFAULTED altitude drops into the full-strength band,
    recorded like every planner edit; a STATED altitude is never moved --
    flying above a tornado is a legitimate request and the effect report
    will honestly show near-zero coupling.
    """
    if (str(spec.weather_event.value) == "tornado"
            and str(spec.altitude.source) in ("default", "model")):
        # A still-DEFAULT altitude (or the director's guess) descends; an
        # altitude another planner already derived (terrain datum floor)
        # stays -- the vortex band is AGL and the terrain floor already
        # sits inside it.
        spec.plan("altitude", 800.0,
                  frm="lowered into the vortex's full-strength band (the "
                      "model fades from 1500 m AGL; a stated altitude is "
                      "never moved)")


def coupling_needs_seed(spec: ScenarioSpec) -> bool:
    """True when the run is stochastic even with turbulence word "none":
    a terrain scene with wind (lee-rotor) or a surface class with thermals
    (updraft positions are drawn from the seed). Both the /run endpoint and
    the render flow use THIS predicate, so the seed always derives before
    the digest is answered."""
    from core.environment.surface import surface_class

    try:
        surface = surface_class(str(spec.surface.value))
    except ValueError:
        surface = None      # validation refuses it by name; not our job
    scene = pick_scene(spec)
    return ((bool(scene["terrain"]) and float(spec.wind_speed.value) > 0.0)
            or (surface is not None and surface.thermals is not None))




class RunManager:
    """One render at a time, from card to panelled clip, in a worker thread."""

    def __init__(self, out_root: Optional[Path] = None) -> None:
        self.out_root = out_root or (REPO / "runs" / "webapp")
        self.runs: Dict[str, RunState] = {}
        self._lock = threading.Lock()
        self._active: Optional[str] = None

    def status(self) -> Dict:
        with self._lock:
            active = self.runs.get(self._active) if self._active else None
        return {
            "busy": active is not None and active.status not in
                    ("done", "failed"),
            "editor_running": editor_running(),
            "active": active.as_dict() if active else None,
        }

    def get(self, run_id: str) -> Optional[RunState]:
        run = self.runs.get(run_id)
        if run is not None:
            return run
        return self._recover_from_disk(run_id)

    def _recover_from_disk(self, run_id: str) -> Optional[RunState]:
        """A COMPLETED run outlives the process that ran it.

        A server restart kills the manager's in-memory state; without this,
        a finished clip on disk becomes unreachable and the page polls a
        run the new process never heard of (measured: a restart landed
        mid-run and orphaned it). Only runs with a finished clip are
        reconstructed -- an interrupted run has no worker thread to resume
        and stays absent, which the page reports honestly.
        """
        if not run_id.isalnum():          # run ids are hex; no path tricks
            return None
        out = self.out_root / run_id
        clip = out / "clip.mp4"
        if not clip.is_file():
            return None
        run = RunState(run_id=run_id, status="done",
                       detail="clip ready (recovered after a server restart)")
        run.clip = str(clip)
        provenance_path = out / "provenance.json"
        if provenance_path.is_file():
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            run.spec_digest = provenance.get("spec_digest", "")
            run.scene = provenance.get("scene") or {}
            run.reference = provenance.get("reference_speeds")
            run.conditions = provenance.get("conditions") or {}
        run.events.append({"t": run.started, "status": "done",
                           "detail": "recovered after a server restart"})
        self.runs[run_id] = run
        return run

    def start(self, spec: ScenarioSpec, provenance: Dict) -> Dict:
        """Refuses (with the reason) or starts a run and returns its id."""
        from core.util.platform import UE_PLATFORM_REFUSAL, ue_available

        if not ue_available():
            # The named platform refusal, not a 500: every render gotcha
            # was measured on Metal/macOS only. The headless half (spec,
            # provenance, validation, telemetry via run_spec) already
            # happened or remains available on this OS.
            return {"refused": UE_PLATFORM_REFUSAL,
                    "constraint": "ue.platform"}
        with self._lock:
            active = self.runs.get(self._active) if self._active else None
            if active is not None and active.status not in ("done", "failed"):
                return {"refused": f"a run is already {active.status} "
                                   f"({active.run_id}); one editor instance "
                                   f"at a time"}
            if editor_running():
                return {"refused": "another process owns the editor (a "
                                   "matrix render?); refusing a concurrent "
                                   "run"}
            run = RunState(run_id=uuid.uuid4().hex[:12],
                           spec_digest=spec.digest())
            self.runs[run.run_id] = run
            self._active = run.run_id
        thread = threading.Thread(target=self._execute,
                                  args=(run, spec, provenance), daemon=True)
        thread.start()
        return {"run_id": run.run_id}

    # -- the pipeline ------------------------------------------------------

    @staticmethod
    def _render(card: Path, frames: Path, scene: Dict, mesh: Path,
                aircraft: str, telemetry: Optional[Path] = None,
                look: Optional[Dict] = None,
                camera: str = "chase") -> bool:
        """The showcase render command, with terrain/imagery conditional.

        Same flags render_cell passes (gotcha 1: absolute paths, -stdout,
        -RenderOffScreen, -AllowCommandletRendering); the terrain, imagery
        and mesh arguments appear only when the scene earned them, so a flat
        spec renders the labeled slab rather than failing on an empty path.
        """
        project = REPO / "ue" / "FlightSim.uproject"
        frames.mkdir(parents=True, exist_ok=True)
        (frames / "render.json").unlink(missing_ok=True)
        tod = look or TIME_OF_DAY["noon"]
        command = [
            str(EDITOR), str(project), "-run=FlightSimBridge.FlightSimRender",
            f"-scenario={card}", f"-frames={frames}",
            "-Visual", "-shot=showcase",
            f"-chase={AIRFRAMES.get(aircraft, {}).get('chase', '-170:0:16')}",
            f"-camera={camera}",
            f"-fps={FPS}", f"-width={WIDTH}", f"-height={HEIGHT}",
            f"-sun-elev={tod['sun_elev']}", f"-sun-azim={tod['sun_azim']}",
            f"-exposure-bias={tod['exposure_bias']}",
            f"-fog-density={(look or {}).get('fog_density', VISIBILITY['clear'])}",
            "-unattended", "-nopause", "-nosplash",
            "-stdout", "-FullStdOutLogOutput",
            "-RenderOffScreen", "-AllowCommandletRendering",
        ]
        if scene.get("terrain"):
            command += ["-GeorefTerrain", f"-terrain={scene['terrain']}"]
        if scene.get("imagery"):
            command += [f"-imagery={scene['imagery']}"]
        if mesh.is_file():
            command += [f"-mesh={mesh}"]
        if telemetry is not None:
            # The SHARED recorder's own file (same component all three hosts
            # use), stamping the FDM's clock -- the aero panel reads it
            # verbatim, no resampling.
            command += [f"-telemetry={telemetry}"]
        log = frames.parent / "render.log"
        with log.open("w") as sink:
            subprocess.run(command, stdout=sink, stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL)
        return (frames / "render.json").is_file()

    def _execute(self, run: RunState, spec: ScenarioSpec,
                 provenance: Dict) -> None:
        try:
            self._render_flow(run, spec, provenance)
        except Exception as exc:   # surfaced to the UI, never swallowed
            run.push("failed", f"{type(exc).__name__}: {exc}")

    def _render_flow(self, run: RunState, spec: ScenarioSpec,
                     provenance: Dict) -> None:
        out = self.out_root / run.run_id
        out.mkdir(parents=True, exist_ok=True)
        scene = pick_scene(spec)
        run.scene = scene

        derive_seed(spec, terrain_coupled=coupling_needs_seed(spec))
        project_for_ue_host(spec)
        spec.write(out / "scenario.yaml")

        aircraft = str(spec.aircraft.value)
        mesh = REPO / "assets" / "generated" / aircraft / "mesh_manifest.json"
        wind_kt = float(spec.wind_speed.value)
        orographic = None
        if scene["terrain"] and wind_kt > 0.0:
            orographic = orographic_card_block(
                Path(scene["terrain"]), float(spec.latitude.value),
                float(spec.longitude.value), wind_kt,
                round(float(spec.wind_direction.value)))
        scene_crs = None
        rotor_provider = None
        if orographic is not None:
            # The mountains shape the turbulence too, not just the mean
            # wind: lee-rotor W20 riding the SAME orographic field the card
            # carries, background floor = the spec's own turbulence word.
            # In calm air there is no orographic field and honestly no
            # rotor -- the conditions strip states the reason.
            from core.environment.rotor import LeeRotorTurbulence

            rotor_provider = LeeRotorTurbulence(
                _orographic_provider(spec, scene),
                seed=int(spec.seed.value),
                background_intensity=str(spec.turbulence.value))
        # Phase 9.1 surface class: roughness shear (the log profile CARRIES
        # the base wind -- reference at the layer top, so cruise flies the
        # spec's wind) and thermal forcing, both from the class table with
        # their basis strings. The ocean attaches no thermals.
        from core.environment.surface import surface_class

        surface = surface_class(str(spec.surface.value))
        log_profile = None
        thermals_block = None
        surface_note = None
        if surface is not None:
            from core.fdm import units as u_
            if wind_kt > 0.0:
                from core.environment.wind import LogProfileWind

                shear = LogProfileWind(
                    u_.kt_to_mps(wind_kt),
                    float(spec.wind_direction.value),
                    reference_height_m=LogProfileWind.SURFACE_LAYER_TOP_M,
                    terrain=surface.roughness)
                log_profile = shear.card_block(carries_base=True)
            if surface.thermals is not None:
                from core.environment.thermals import AllenThermals

                wstar, zi = surface.thermals
                thermals = AllenThermals(
                    wstar_mps=wstar, zi_m=zi,
                    area_north_m=4000.0, area_east_m=4000.0,
                    origin_north_m=-2000.0, origin_east_m=-2000.0,
                    seed=int(spec.seed.value))
                ox, oy, declared = _projected_origin(spec, scene)
                scene_crs = scene_crs or declared
                thermals_block = thermals.card_block(ox, oy)
            thermal_note = ("no thermals modelled over water"
                            if surface.thermals is None else
                            f"thermals w* {surface.thermals[0]:g} m/s, "
                            f"zi {surface.thermals[1]:g} m "
                            f"({surface.thermal_basis})")
            surface_note = (f"{surface.word}: z0 {surface.z0_m:g} m "
                            f"(Stull Table 9-6); {thermal_note}")
        # Phase 9.2/9.3 severe-weather events: card blocks placed ahead on
        # the track, physics through the same position-coupled machinery as
        # Phase 7; the STORM LOOK is visual and labeled.
        event = str(spec.weather_event.value)
        tornado_block = None
        downburst_block = None
        event_note = None
        if event in ("thunderstorm", "tornado"):
            import math as _math

            from core.fdm import units as u2

            seconds_ = min(float(spec.duration.value), CLIP_SECONDS)
            ahead = (0.45 * u2.kt_to_mps(float(spec.airspeed.value))
                     * seconds_)
            hdg = _math.radians(float(spec.heading.value))
            centre_n = ahead * _math.cos(hdg)
            centre_e = ahead * _math.sin(hdg)
            if scene.get("terrain"):
                # Scripted terrain runs BANK (the S-turn doublet), so the
                # straight-line 45%-ahead point misses the curved track.
                # Measured on a 'through the tornado' Fuji run: closest
                # approach ~410 m to a 150 m core -- peak sampled wind
                # 18.3 m/s, exactly the 1/r field at that radius. Place
                # the event on the PRE-FLOWN track instead: same script,
                # same wind, same orographic field the clearance planner
                # flies. An untrimmable spec keeps the straight-line
                # placement and validate() rules next.
                try:
                    from core.terrain.ground import TerrainGround
                    from core.terrain.heightfield import Heightfield

                    ground_ = TerrainGround(
                        Heightfield.read(Path(scene["terrain"])))
                    track_ = _fly_clearance_track(
                        spec, ground_, SHOWCASE_DOUBLET, seconds_,
                        orographic=_orographic_provider(spec, scene))
                    point = track_[int(0.45 * (len(track_) - 1))]
                    centre_n = float(point["north_m"])
                    centre_e = float(point["east_m"])
                except Exception:
                    pass
            ox, oy, declared = _projected_origin(spec, scene)
            scene_crs = scene_crs or declared
            if event == "tornado":
                from core.environment.tornado import R_CORE_M, TornadoVortex

                # Abeam offset: the track clips the core's edge rather
                # than spearing the axis.
                # Placement follows the spec's recorded aim: "core" (the
                # prompt said through/into) puts the axis ON the track --
                # the camera will cross the funnel mesh and the frames
                # honestly show the inside of the marker; "abeam" is the
                # 2.5-core-radii flyby (at 1.2 radii the chase camera
                # lived inside the mesh, probe-measured).
                aim = str(spec.weather_event.detail.get("aim", "abeam"))
                offset = 0.0 if aim == "core" else 2.5 * R_CORE_M
                vortex = TornadoVortex(
                    centre_n + offset * _math.cos(hdg + _math.pi / 2),
                    centre_e + offset * _math.sin(hdg + _math.pi / 2))
                tornado_block = vortex.card_block(ox, oy)
                event_note = ("tornado: Rankine vortex (EF2-band, v_max "
                              "50 m/s, core 150 m) abeam the track; funnel "
                              "mesh is a VISUAL marker, not condensation; "
                              "wind point-sampled at the CG -- no "
                              "span-differential airloads")
            else:
                from core.environment.downburst import Downburst

                burst = Downburst(centre_n, centre_e)
                downburst_block = burst.card_block(ox, oy)
                event_note = ("thunderstorm (documented composition): "
                              "microburst 1000 m core / 12 m/s outflow "
                              "ahead on the track + severe turbulence + "
                              "storm look (VISUAL)")
        calm = wind_kt == 0.0 and str(spec.turbulence.value) == "none"
        # Terrain runs bank through the scene (the same S-turn script the
        # clearance planner pre-flew) and carry the raster as the PHYSICS
        # ground -- the picture and the physics agree, and the commandlet
        # verifies AGL against the raster under the aircraft.
        scripted = calm or bool(scene.get("terrain"))
        collision = scene.get("terrain")
        # The model's own measured reference speeds (§2.4), carried on the
        # card for the HUD/panel stall-margin marks. Display-only; a spec
        # the envelope machinery cannot measure simply omits the block.
        reference = None
        try:
            from core.scenario.validate import validate

            report = validate(spec)
            if report.speeds is not None:
                speeds = report.speeds
                reference = {
                    "vs_kt": round(speeds.vs_kt, 1),
                    "cl_max": round(speeds.cl_max, 3),
                    "alpha_stall_deg": (
                        round(speeds.alpha_stall_deg, 1)
                        if speeds.alpha_stall_deg is not None
                        and not speeds.clipped else None),
                    "basis": (f"{speeds.aircraft} model, CLmax "
                              f"{speeds.cl_max:.3f}, {speeds.mass_kg:.0f} kg"
                              + (" (CLmax not bracketed; Vs is a lower bound)"
                                 if speeds.clipped else "")),
                }
        except Exception:
            reference = None   # marks are optional; the run is not
        run.reference = reference
        run.conditions = {
            "wind_note": (f"{wind_kt:g} kt from "
                          f"{float(spec.wind_direction.value):g} deg"
                          if wind_kt > 0 else
                          ("calm; no terrain-driven airflow (orographic "
                           "forcing is wind over terrain)"
                           if scene["terrain"] else "calm")),
            "turbulence": (f"lee-rotor over terrain (background "
                           f"{spec.turbulence.value})"
                           if rotor_provider is not None
                           else str(spec.turbulence.value)),
            "turbulence_seed": (int(spec.seed.value)
                                if rotor_provider is not None
                                or thermals_block is not None
                                or str(spec.turbulence.value) != "none"
                                else None),
            "physics_ground": scene["label"],
            **({"surface": surface_note} if surface_note else {}),
            **({"weather": event_note} if event_note else {}),
        }
        card = write_run_card(
            spec, out / "card.json",
            control_inputs=SHOWCASE_DOUBLET if scripted else (),
            duration_s=min(float(spec.duration.value), CLIP_SECONDS),
            orographic=orographic,
            rotor=(rotor_provider.card_block()
                   if rotor_provider is not None else None),
            turbulence_provider=rotor_provider,
            log_profile=log_profile,
            thermals=thermals_block,
            downburst=downburst_block,
            tornado=tornado_block,
            scene_crs=scene_crs,
            collision_terrain=str(collision) if collision else None,
            reference_speeds=reference,
        )
        # Prompt/model provenance in a Python-written UTF-8 sidecar; the
        # UE-written manifest stays ASCII (gotcha 13).
        (out / "provenance.json").write_text(json.dumps({
            **provenance, "spec_digest": spec.digest(),
            "scene": scene, "clip_seconds_cap": CLIP_SECONDS,
            "reference_speeds": reference,
            # Also read back by _recover_from_disk after a server restart.
            "conditions": run.conditions,
        }, indent=1), encoding="utf-8")

        run.push("rendering", "editor is rendering frames (a few minutes)")
        frames = out / "frames"
                # A through-the-core tornado flight is watched from the tower:
        # the chase camera would spend seconds INSIDE the funnel mesh
        # and the blank-frame floor (correctly, never weakened) refused
        # those frames -- measured on run c33db2c326e0.
        camera = "chase"
        if (str(spec.weather_event.value) == "tornado"
                and str(spec.weather_event.detail.get("aim")) == "core"):
            camera = "tower"
            run.conditions["camera"] = ("tower (through-the-core "
                                        "flight; the chase camera "
                                        "would sit inside the funnel)")
        if not self._render(card, frames, scene, mesh, aircraft,
                            telemetry=out / "telemetry.json",
                            look=STORM_LOOK if event_note else None,
                            camera=camera):
            run.push("failed", "the render commandlet wrote no manifest; "
                               f"see {out / 'render.log'}")
            return

        run.push("encoding", "encoding frames to mp4")
        raw_clip = out / "raw.mp4"
        if not encode_clip(frames, raw_clip):
            run.push("failed", "ffmpeg could not encode the frames")
            return

        run.push("panel", "compositing the telemetry panel")
        manifest = frames / "render.json"
        seed = int(spec.seed.value)
        turbulent = (str(spec.turbulence.value) != "none"
                     or rotor_provider is not None)
        conditions = {
            "wind_note": (f"{wind_kt:g} kt from "
                          f"{float(spec.wind_direction.value):g} deg"
                          if wind_kt > 0 else "calm"),
            "turbulence_seed": seed if turbulent else None,
        }
        clip = out / "clip.mp4"
        if not build_panel_clip(card, manifest, conditions, raw_clip, clip,
                                fps=FPS):
            run.push("failed", "panel composition failed")
            return
        raw_clip.unlink(missing_ok=True)
        if (rotor_provider is not None or log_profile is not None
                or thermals_block is not None or tornado_block is not None
                or downburst_block is not None):
            # The conditions-effect report: what the coupling DID, measured
            # against a headless still-air-over-terrain baseline of the same
            # spec. Optional -- the clip stands on its own if this fails.
            run.push("report", "measuring the conditions' effect against a "
                               "still-air baseline (headless)")
            try:
                _effect_report(spec, scene,
                               SHOWCASE_DOUBLET if scripted else (),
                               min(float(spec.duration.value), CLIP_SECONDS),
                               out / "telemetry.json", out / "effect.json")
            except Exception as exc:
                run.push("report", f"effect report unavailable "
                                   f"({type(exc).__name__}: {exc}); the "
                                   f"clip stands on its own")
        run.clip = str(clip)
        run.push("done", "clip ready")
