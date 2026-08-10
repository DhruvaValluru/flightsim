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

    def push(self, status: str, detail: str = "") -> None:
        self.status = status
        self.detail = detail
        self.events.append({"t": time.time(), "status": status,
                            "detail": detail})

    def as_dict(self) -> Dict:
        return {"run_id": self.run_id, "status": self.status,
                "detail": self.detail, "spec_digest": self.spec_digest,
                "scene": self.scene, "clip": self.clip,
                "started": self.started, "events": self.events[-20:]}


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
                         f"physics ground is the spec's flat slab",
            }
    if float(spec.terrain_elevation.value) > 0.0:
        if (terrain_dir / "control_ridge.r16").is_file():
            return {
                "key": "control", "kind": "synthesised control ridge",
                "terrain": str(terrain_dir / "control_ridge"),
                "imagery": None,
                "label": "synthesised ridge (prescribed statistics, not a "
                         "place); physics ground is the spec's flat slab",
            }
    return {"key": "flat", "kind": "flat", "terrain": None, "imagery": None,
            "label": "no terrain requested; flat slab at the spec's "
                     "elevation"}


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
        return self.runs.get(run_id)

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
                aircraft: str) -> bool:
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
        card = write_run_card(
            spec, out / "card.json",
            control_inputs=SHOWCASE_DOUBLET if calm else (),
            duration_s=min(float(spec.duration.value), CLIP_SECONDS),
            orographic=orographic,
        )
        # Prompt/model provenance in a Python-written UTF-8 sidecar; the
        # UE-written manifest stays ASCII (gotcha 13).
        (out / "provenance.json").write_text(json.dumps({
            **provenance, "spec_digest": spec.digest(),
            "scene": scene, "clip_seconds_cap": CLIP_SECONDS,
        }, indent=1))

        run.push("rendering", "editor is rendering frames (a few minutes)")
        frames = out / "frames"
        if not self._render(card, frames, scene, mesh, aircraft):
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
