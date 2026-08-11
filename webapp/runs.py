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
from core.terrain.glo30 import LOCATIONS, orographic_card_block  # noqa: E402
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
    paths and hold no editor lock."""
    probe = subprocess.run(["pgrep", "-f", "Binaries/Mac/UnrealEditor"],
                           capture_output=True, text=True)
    return probe.returncode == 0 and probe.stdout.strip() != ""


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


def _fly_clearance_track(spec: ScenarioSpec, ground, script,
                         seconds: float):
    """The scripted flight on the same JSBSim, for the clearance gate.

    The Zermatt valley run's fly_headless, generalised: the SAME control
    script the card will carry (deltas on the trimmed aileron, held until
    the next entry -- the parity-tested convention) and the SAME steady
    wind, so drift shapes the track that gets checked. Turbulence is not
    modelled here (visual-only realisations; the clearance margin covers
    the excursion scale the recordings show).
    """
    from core.fdm import FlightDynamics, mode_for
    from core.fdm import units as u
    from core.scenario.runner import wind_components_fps

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
        fdm.step()
        if i % 12 == 0:
            s = fdm.state()
            terrain = (ground.elevation_at(s.lat_deg, s.lon_deg)
                       if ground.contains(s.lat_deg, s.lon_deg) else 0.0)
            track.append({"terrain_m": terrain,
                          "clearance_m": s.altitude_m - terrain})
    return track


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

    try:
        track = _fly_clearance_track(spec, ground, SHOWCASE_DOUBLET,
                                     seconds)
    except Exception:
        # A spec that cannot even trim (e.g. commanded below its own flat
        # terrain) is not this planner's refusal to make: validate() runs
        # next in the same request and refuses by name, and the render
        # commandlet's VerifyTrimmedCondition guards the same ground.
        return None
    min_clearance = min(p["clearance_m"] for p in track)
    if min_clearance >= MIN_CLEARANCE_M \
            and str(spec.altitude.source) != "default":
        return None
    if str(spec.altitude.source) == "default":
        peak = max(p["terrain_m"] for p in track)
        planned = float(round(peak + PLANNED_CLEARANCE_M))
        if planned > float(spec.altitude.value) \
                or min_clearance < MIN_CLEARANCE_M:
            spec.set("altitude", max(planned, float(spec.altitude.value)),
                     frm=f"raised to clear the terrain under the planned "
                         f"track (peak {peak:.0f} m + "
                         f"{PLANNED_CLEARANCE_M:.0f} m)")
            try:
                track = _fly_clearance_track(spec, ground,
                                             SHOWCASE_DOUBLET, seconds)
                min_clearance = min(p["clearance_m"] for p in track)
            except Exception:
                min_clearance = float("-inf")   # unverifiable = not clear
        if min_clearance >= MIN_CLEARANCE_M:
            return None
    return {
        "constraint": "terrain.clearance",
        "message": "the planned track descends below the clearance margin "
                   "over the scene's terrain (pre-flown headlessly on the "
                   "scene's own raster, wind included)",
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


def derive_seed(spec: ScenarioSpec) -> None:
    """A turbulent spec with the default seed gets one from its digest."""
    if (str(spec.turbulence.value) != "none"
            and str(spec.seed.source) == "default"):
        seed = int(spec.digest()[:8], 16) % 1_000_000
        spec.set("seed", seed, frm="derived from spec digest")


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
            provenance = json.loads(provenance_path.read_text())
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
                aircraft: str, telemetry: Optional[Path] = None) -> bool:
        """The showcase render command, with terrain/imagery conditional.

        Same flags render_cell passes (gotcha 1: absolute paths, -stdout,
        -RenderOffScreen, -AllowCommandletRendering); the terrain, imagery
        and mesh arguments appear only when the scene earned them, so a flat
        spec renders the labeled slab rather than failing on an empty path.
        """
        project = REPO / "ue" / "FlightSim.uproject"
        frames.mkdir(parents=True, exist_ok=True)
        (frames / "render.json").unlink(missing_ok=True)
        tod = TIME_OF_DAY["noon"]
        command = [
            str(EDITOR), str(project), "-run=FlightSimBridge.FlightSimRender",
            f"-scenario={card}", f"-frames={frames}",
            "-Visual", "-shot=showcase",
            f"-chase={AIRFRAMES.get(aircraft, {}).get('chase', '-170:0:16')}",
            f"-fps={FPS}", f"-width={WIDTH}", f"-height={HEIGHT}",
            f"-sun-elev={tod['sun_elev']}", f"-sun-azim={tod['sun_azim']}",
            f"-exposure-bias={tod['exposure_bias']}",
            f"-fog-density={VISIBILITY['clear']}",
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

        derive_seed(spec)
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
                          if wind_kt > 0 else "calm"),
            "turbulence": str(spec.turbulence.value),
            "turbulence_seed": (int(spec.seed.value)
                                if str(spec.turbulence.value) != "none"
                                else None),
            "physics_ground": scene["label"],
        }
        card = write_run_card(
            spec, out / "card.json",
            control_inputs=SHOWCASE_DOUBLET if scripted else (),
            duration_s=min(float(spec.duration.value), CLIP_SECONDS),
            orographic=orographic,
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
        }, indent=1))

        run.push("rendering", "editor is rendering frames (a few minutes)")
        frames = out / "frames"
        if not self._render(card, frames, scene, mesh, aircraft,
                            telemetry=out / "telemetry.json"):
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
        turbulent = str(spec.turbulence.value) != "none"
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
        run.clip = str(clip)
        run.push("done", "clip ready")
