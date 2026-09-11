"""The Phase 8 front door: prompt -> spec table -> confirm -> run -> clip.

§2.6 with a UI on it: the prompt compiles to a provenanced spec, the spec is
RENDERED AND CONFIRMED before anything runs, validation refusals are
first-class results (shown by name, never buried as errors), and the run
that finally executes is content-addressed by the spec digest -- the prompt
is a historical note in the provenance sidecar.

Run:  .venv/bin/uvicorn webapp.server:app --host 127.0.0.1 --port 8008
Then open http://127.0.0.1:8008/

The compiler is the LLM one when the anthropic SDK and ANTHROPIC_API_KEY are
available, and the offline regex compiler otherwise; the response always
states which one ran and, for the LLM, which model.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(REPO))

from core.nl.compiler import compile_prompt  # noqa: E402
from core.nl.llm_compiler import (  # noqa: E402
    LLMCompileError,
    compile_prompt_llm,
    llm_available,
)
from core.scenario.spec import ScenarioSpec  # noqa: E402
from core.scenario.validate import validate  # noqa: E402
from webapp.runs import (  # noqa: E402
    CLIP_SECONDS,
    RunManager,
    apply_historical_weather,
    apply_weather_event,
    bake_on_demand,
    camera_scene_violations,
    coupling_needs_seed,
    derive_seed,
    needs_dynamic_bake,
    pick_scene,
    place_on_scene,
    plan_camera_defaults,
    plan_flyable_defaults,
    plan_scene_setting,
    plan_terrain_environment,
    plan_terrain_flight,
    plan_trim_recovery,
    project_for_ue_host,
    refuse_placeholder_mesh,
)

app = FastAPI(title="flightsim", docs_url=None, redoc_url=None)
manager = RunManager()

STATIC = Path(__file__).resolve().parent / "static"


class CompileRequest(BaseModel):
    prompt: str
    compiler: str = "llm"      # "llm" | "regex"
    # The answer round: the page echoes the question round's questions back
    # alongside the user's answers. Round-ness is carried entirely by
    # ``answers`` being present -- the server keeps no conversation state.
    questions: Optional[List[Dict[str, Any]]] = None
    answers: Optional[List[Dict[str, str]]] = None
    #: The answer round echoes round 1's compiled spec (payload spec.dict)
    #: so nothing that round decided can silently revert to a default.
    prior_spec: Optional[Dict[str, Any]] = None
    #: Clip length selector: an explicit UI choice, applied as a USER edit
    #: of the run duration. None = whatever the prompt/default says.
    clip_seconds: Optional[float] = None


class RunRequest(BaseModel):
    spec: Dict[str, Any]       # ScenarioSpec.to_dict(), possibly edited
    provenance: Dict[str, Any] = {}


class CameraRequest(BaseModel):
    """Add or remove one camera on the spec the page is holding.

    The page sends the whole spec dict and gets the whole payload back,
    so the 32 defaults of a new camera come from ``CameraSpec.defaulted``
    -- the one place that knows them -- rather than being duplicated in
    JavaScript where they would drift.
    """

    spec: Dict[str, Any]
    #: Add: the preset the new camera takes (CAMERA_PRESETS).
    preset: Optional[str] = None
    #: Remove: the index to drop. Exactly one of preset/remove.
    remove: Optional[int] = None


def _spec_payload(spec: ScenarioSpec) -> Dict[str, Any]:
    fields = []
    for section, name, quantity in spec.quantities():
        fields.append({
            "section": section, "name": name,
            "value": quantity.value, "unit": quantity.unit,
            "source": str(quantity.source), "from": quantity.frm,
            "std": quantity.std, "detail": quantity.detail,
        })
    # Cameras render as their own labeled blocks with per-field sources,
    # editable exactly like the scalar rows (the page writes edits into
    # dict.cameras[i] and /run re-parses the whole spec).
    cameras = []
    for index, camera in enumerate(spec.cameras):
        cameras.append({
            "index": index,
            "camera_id": str(camera.camera_id.value),
            # The header names the view, so the page does not have to dig
            # it out of the field list to say what this block is.
            "preset": str(camera.preset.value),
            "fields": [{
                "name": name, "value": quantity.value,
                "unit": quantity.unit, "source": str(quantity.source),
                "from": quantity.frm, "std": quantity.std,
                "detail": quantity.detail,
            } for name, quantity in camera.quantities()],
            "moves": [dict(m) for m in camera.moves],
        })
    return {"digest": spec.digest(), "name": spec.name,
            "prompt": spec.prompt, "notes": spec.notes,
            "fields": fields, "cameras": cameras, "dict": spec.to_dict(),
            "table": spec.render_table()}


def _validation_payload(spec: ScenarioSpec) -> Dict[str, Any]:
    report = validate(spec)
    return {
        "ok": report.ok,
        "violations": [{
            "constraint": v.constraint, "message": v.message,
            "actual": v.actual, "limit": v.limit, "unit": v.unit,
        } for v in report.violations],
        "warnings": list(report.warnings),
        "derived_speeds": report.speeds.summary() if report.speeds else None,
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.post("/compile")
def compile_endpoint(request: CompileRequest) -> JSONResponse:
    prompt = request.prompt.strip()
    if not prompt:
        return JSONResponse({"error": "empty prompt"}, status_code=400)

    compiler_used = request.compiler
    model = None
    llm_note = None
    questions: List[Dict[str, Any]] = []
    transcript = None
    if request.compiler == "llm":
        try:
            result = compile_prompt_llm(prompt, questions=request.questions,
                                        answers=request.answers)
            spec, model = result.spec, result.model
            questions = [dict(q) for q in result.questions]
            transcript = ([dict(m) for m in result.transcript]
                          if result.transcript else None)
        except LLMCompileError as exc:
            # The offline compiler is the documented fallback; the UI states
            # the switch and why, never silently. The regex compiler never
            # asks and never sees answers: it compiles the ORIGINAL prompt,
            # even when the LLM died between the question and answer rounds.
            spec = compile_prompt(prompt)
            compiler_used = "regex (llm unavailable)"
            llm_note = str(exc)
    else:
        spec = compile_prompt(prompt)
        compiler_used = "regex"

    # The answer round must never LOSE the question round. The protocol is
    # stateless: round 2 re-extracts everything from the whole conversation,
    # so a field the model drops -- or the WHOLE round, when the LLM dies
    # and the regex fallback compiles the original prompt -- silently
    # reverts to its default (measured: an answered location question came
    # back with the first round's settings gone). The page echoes round 1's
    # spec; any field that round DECIDED (user/inferred/model) and this
    # round left at default is restored with its provenance intact. A field
    # this round decided wins -- an answer legitimately changes things --
    # and derived fields are left to the planners below to re-derive.
    if request.answers and request.prior_spec is not None:
        try:
            prior = ScenarioSpec.from_dict(request.prior_spec)
        except (ValueError, KeyError):
            prior = None        # a malformed echo restores nothing
        if prior is not None:
            for _section, name, current in list(spec.quantities()):
                previous = getattr(prior, name)
                if (str(current.source) == "default"
                        and str(previous.source) in ("user", "inferred",
                                                     "model")):
                    setattr(spec, name, replace(
                        previous,
                        frm=f"{previous.frm} (kept from the question round)"))

    # Clip length selector: the clip is min(duration, CLIP_SECONDS), so a
    # shorter scenario renders proportionally fewer frames. An explicit UI
    # choice is a USER edit of the duration, provenance and all -- it wins
    # over a duration stated in the prompt, and the table shows that.
    if request.clip_seconds is not None:
        seconds = float(request.clip_seconds)
        if not (0.0 < seconds <= CLIP_SECONDS):
            return JSONResponse(
                {"error": f"clip length must be in (0, {CLIP_SECONDS:g}] s"},
                status_code=400)
        spec.set("duration", seconds, frm="clip length selector (web UI)")

    # Planning happens BEFORE the table and verdict are built, so what the
    # user reviews is what will run: the weather event's documented
    # composition edits (a tornado descends a defaulted altitude into the
    # vortex band; a thunderstorm sets the defaulted turbulence word),
    # then the envelope floors -- a prompt whose numbers the system chose
    # must not be refused over the system's own choices. Every move is a
    # recorded edit (source becomes ``derived``); stated values never
    # move. /run applies the same planners again: value-idempotent.
    plan_scene_setting(spec)
    apply_weather_event(spec)
    # Terrain-aware environment (cross-ridge wind, along-ridge heading):
    # shown in the review table when the scene's raster is already baked
    # locally; /run applies the same planner, so run-time is never a
    # surprise relative to the table.
    try:
        plan_terrain_environment(spec)
    except (OSError, ValueError):
        pass    # no local raster yet (dynamic bake): /run plans it after /bake
    plan_flyable_defaults(spec)
    plan_trim_recovery(spec)
    # Defaulted world-anchored cameras follow the staged scene (the
    # tower does not stay at flat-ground height under planned
    # mountains); stated placements never move.
    plan_camera_defaults(spec)

    payload = {
        "compiler": compiler_used, "model": model, "llm_note": llm_note,
        "llm_available": llm_available(),
        # A question round still carries the partial spec + verdict below:
        # the table under the questions shows what is already decided, and
        # the user may run it as-is (defaults are documented, not guesses).
        "needs_clarification": bool(questions),
        "questions": questions,
        "transcript": transcript,
        "spec": _spec_payload(spec),
        "validation": _validation_payload(spec),
    }
    return JSONResponse(payload)


@app.post("/cameras")
def cameras_endpoint(request: CameraRequest) -> JSONResponse:
    """One more point of view, or one fewer.

    Camera Phase 1 made the camera a spec element and the page learned to
    EDIT one; it could never add a second, because the compiler builds at
    most one CameraSpec and nothing else appended to the list. So the
    phase's own flagship demonstration -- several views of one flight --
    was reachable from a YAML file and not from the app. Everything
    downstream already handled N cameras: the planners enumerate them,
    the capture stage solves a track each, and the render runs one
    commandlet pass per camera.

    Refusals are the validator's, by name. A duplicate or unusable
    ``camera_id`` is refused rather than silently renamed, for the reason
    every stated field is: the id names the directory the frames land in
    and the manifest labels them by it.
    """
    from core.capture.validate import validate_cameras
    from core.scenario.camera import CameraSpec, plan_full_capture

    try:
        spec = ScenarioSpec.from_dict(request.spec)
    except (ValueError, KeyError) as exc:
        return JSONResponse({"error": f"spec did not parse: {exc}"},
                            status_code=400)

    if request.remove is not None:
        if not 0 <= request.remove < len(spec.cameras):
            return JSONResponse(
                {"error": f"camera[{request.remove}] does not exist; the "
                          f"spec states {len(spec.cameras)}"},
                status_code=400)
        spec.cameras.pop(request.remove)
        return JSONResponse(_spec_payload(spec))

    # The preset is NOT checked here. core.capture.validate owns that
    # vocabulary and its refusal already names the modelled set --
    # duplicating it would be a second place to keep in step, and a
    # check that cannot fire (measured: disabling it changed nothing,
    # because validate_cameras below caught every case first).
    preset = str(request.preset or "")

    # A NEW id, not a renamed one. Ids name directories, so a collision
    # would put two cameras' frames in one place; picking the next free
    # suffix keeps them distinct without touching any id already stated.
    taken = {str(camera.camera_id.value) for camera in spec.cameras}
    camera_id = preset
    suffix = 0
    while camera_id in taken:
        suffix += 1
        camera_id = f"{preset}{suffix}"

    camera = CameraSpec.defaulted(
        camera_id=camera_id, preset=preset,
        aircraft=str(spec.aircraft.value),
        terrain_elevation_m=float(spec.terrain_elevation.value),
        frm=f"added from the page as a {preset} view")
    # A view added from the page captures CONTINUOUSLY: every recorded
    # sample, for as long as the clip lasts. Picking a viewpoint and a
    # clip length should give that many seconds of that view -- a
    # simulation from that angle -- not the three stills the one-per-
    # second default produced on a three-second clip. Planned rather
    # than set: the page chose it, the user did not state it, so an
    # edit in the review table still wins.
    plan_full_capture(
        camera, frm="a view added from the page captures the whole clip")
    spec.cameras.append(camera)

    violations = validate_cameras(spec)
    if violations:
        spec.cameras.pop()
        first = violations[0]
        return JSONResponse(
            {"refused": first.constraint,
             "error": "; ".join(v.render() for v in violations)},
            status_code=409)
    return JSONResponse(_spec_payload(spec))


@app.post("/run")
def run_endpoint(request: RunRequest) -> JSONResponse:
    try:
        spec = ScenarioSpec.from_dict(request.spec)
    except (ValueError, KeyError) as exc:
        return JSONResponse({"error": f"spec did not parse: {exc}"},
                            status_code=400)

    # The recorded transformations happen BEFORE the digest is answered, so
    # the response content-addresses exactly what will run: the derived
    # turbulence seed and the UE-host projection (open loop, mass held) are
    # spec edits with provenance, and the digest of the projected spec is
    # the one the card, the manifest and the provenance sidecar all carry.
    # USER-stated coordinates with no bake yet refuse by name BEFORE any
    # spec edit: the page bakes via POST /bake and simply runs again --
    # never a silent flat slab standing in for a real place the user named.
    # Scene-setting first (idempotent: a compile-planned location arrives
    # source derived and is left alone), so the placement, bake check and
    # every later planner see the staged scene like any named one.
    plan_scene_setting(spec)
    unbaked = needs_dynamic_bake(spec)
    if unbaked is not None:
        return JSONResponse({"refused": "terrain.unbaked", **unbaked},
                            status_code=409)
    place_on_scene(spec)
    # Severe-weather composition edits (thunderstorm -> severe turbulence
    # when the word was defaulted): recorded, pre-digest, like every other
    # transformation.
    apply_weather_event(spec)
    # Historical weather (ERA5) applies AFTER placement (coordinates are
    # final) and BEFORE the seed/digest: the reanalysis wind is a recorded
    # spec edit like every other transformation, or a named refusal.
    weather_refusal = apply_historical_weather(spec)
    if weather_refusal is not None:
        return JSONResponse({"refused": "weather", **weather_refusal},
                            status_code=409)
    # PLANNER ORDER (load-bearing, pinned by tests): place_on_scene ->
    # apply_weather_event -> apply_historical_weather ->
    # plan_terrain_environment -> derive_seed -> plan_terrain_flight ->
    # plan_flyable_defaults -> plan_trim_recovery ->
    # plan_camera_defaults -> project_for_ue_host -> validate.
    # Rationale: placement fixes coordinates; the event composes its
    # environment; DATED real weather wins over composition (ERA5 wind is
    # source user, so the terrain planner then refuses to touch it);
    # cross-ridge wind and along-ridge heading must exist BEFORE the
    # clearance pre-flight so the track is flown through the SAME planned
    # wind and orographic field it will record; envelope floors come last
    # because they depend on the final altitude.
    plan_terrain_environment(spec)
    # The seed derives BEFORE the digest is answered. A run can be
    # stochastic even with turbulence word "none" -- lee-rotor over windy
    # terrain, or surface thermals whose positions draw from the seed --
    # and coupling_needs_seed is the ONE predicate both this endpoint and
    # the render flow consult, so the card's digest is always the digest
    # this response advertises.
    derive_seed(spec, terrain_coupled=coupling_needs_seed(spec))
    # Terrain scenes: pre-fly the scripted track over the scene's own
    # raster (a defaulted altitude may be raised, recorded; a stated
    # altitude that cannot keep clearance refuses by name below).
    clearance_refusal = plan_terrain_flight(spec)
    # The track planner may have raised a system-chosen altitude into air
    # where the system-chosen airspeed no longer flies: re-plan the
    # defaults at the final altitude (stated values still never move),
    # then give physics the last word over any surviving guess.
    plan_flyable_defaults(spec)
    plan_trim_recovery(spec)
    # Camera placements last among the planners: they depend on the
    # FINAL scene and terrain datum (a defaulted tower camera moves onto
    # the raster under it; stated placements never move and refuse by
    # name in the verdict below).
    plan_camera_defaults(spec)
    project_for_ue_host(spec)

    # Validation governs the edited spec too: the run endpoint re-validates
    # everything it is handed, whatever the page claimed.
    verdict = _validation_payload(spec)
    if clearance_refusal is not None:
        verdict["ok"] = False
        verdict["violations"].append(clearance_refusal)
    # Scene-coupled camera checks (Camera Phase 1): world-anchored
    # cameras against the scene raster, its bounds and the modelled
    # tornado core -- the plan_terrain_flight pattern, refused by name
    # in the same verdict before any editor time is spent.
    camera_refusals = camera_scene_violations(spec, pick_scene(spec))
    if camera_refusals:
        verdict["ok"] = False
        verdict["violations"].extend(camera_refusals)
    if not verdict["ok"]:
        return JSONResponse({"refused": "validation", **verdict},
                            status_code=409)

    # REFUSAL ORDER after validation (load-bearing, pinned by test):
    # ue.platform BEFORE aircraft.mesh. A machine with no engine build
    # must hear that first -- measured 2026-08-31 on a fresh Windows
    # clone, which was told to import aircraft models when the real
    # blocker was that no Unreal host existed there at all.
    from core.util.platform import ue_available, ue_platform_refusal

    if not ue_available():
        return JSONResponse({"refused": ue_platform_refusal(),
                             "constraint": "ue.platform"}, status_code=409)
    # Placeholder airframes never render (owner's rule, extended
    # 2026-08-31: on ANY machine). Checked AFTER validation on purpose:
    # a scenario that cannot fly refuses on the physics first; the asset
    # refusal names the import command only once the flight itself is
    # sound.
    mesh_refusal = refuse_placeholder_mesh(spec)
    if mesh_refusal is not None:
        return JSONResponse({"refused": "aircraft.mesh", **mesh_refusal},
                            status_code=409)

    outcome = manager.start(spec, provenance={
        "prompt": spec.prompt,
        **{k: v for k, v in request.provenance.items()
           if k in ("compiler", "model", "transcript")},
    })
    if "refused" in outcome:
        return JSONResponse(outcome, status_code=409)
    return JSONResponse({**outcome, "digest": spec.digest()})


@app.get("/status")
def status_endpoint() -> JSONResponse:
    # llm_available is a presence check (SDK + key in THIS process's
    # environment) so the page can state the compiler up front instead of
    # discovering a fallback after a spin. platform/render_available are
    # the same pattern for the UE half: off-mac the page says so up front
    # and a run refuses ue.platform by name instead of 500ing.
    from core.util.platform import os_name, ue_available

    return JSONResponse({**manager.status(), "llm_available": llm_available(),
                         "platform": os_name(),
                         "render_available": ue_available()})


@app.get("/runs/{run_id}")
def run_state(run_id: str) -> JSONResponse:
    run = manager.get(run_id)
    if run is None:
        return JSONResponse({"error": "no such run"}, status_code=404)
    return JSONResponse(run.as_dict())


@app.get("/runs/{run_id}/clip.mp4")
def run_clip(run_id: str):
    run = manager.get(run_id)
    if run is None or not run.clip or not Path(run.clip).is_file():
        return JSONResponse({"error": "no clip"}, status_code=404)
    return FileResponse(run.clip, media_type="video/mp4")


@app.get("/runs/{run_id}/telemetry.json")
def run_telemetry(run_id: str):
    """The run's recorded telemetry: the shared recorder's own file, passed
    through verbatim -- no resampling, no smoothing; t is FDM sim time as
    recorded. 404 until the run completes, like the clip."""
    run = manager.get(run_id)
    path = manager.out_root / run_id / "telemetry.json"
    if run is None or run.status != "done" or not path.is_file():
        return JSONResponse({"error": "no telemetry"}, status_code=404)
    return FileResponse(path, media_type="application/json")


class BakeRequest(BaseModel):
    latitude: float
    longitude: float


@app.post("/bake")
def bake_endpoint(request: BakeRequest) -> JSONResponse:
    """Fetch + bake + verify GLO-30 for arbitrary coordinates (the page
    calls this when /run refuses terrain.unbaked). Synchronous: the first
    fetch downloads 1x1 degree tiles and takes minutes; cached afterwards.
    Failure is a named error -- open ocean has no tiles, an unverified
    bake is never written."""
    try:
        entry = bake_on_demand(request.latitude, request.longitude)
    except Exception as exc:
        return JSONResponse(
            {"error": f"{type(exc).__name__}: {exc}"}, status_code=502)
    return JSONResponse(entry)


@app.get("/runs/{run_id}/card.json")
def run_card(run_id: str):
    """The run card, verbatim: what the hosts were actually handed. The
    page's flight-path chart reads the tornado/downburst placement from
    it (positions the card computed, never re-derived client-side)."""
    run = manager.get(run_id)
    path = manager.out_root / run_id / "card.json"
    if run is None or run.status != "done" or not path.is_file():
        return JSONResponse({"error": "no card"}, status_code=404)
    return FileResponse(path, media_type="application/json")


@app.get("/runs/{run_id}/effect.json")
def run_effect(run_id: str):
    """The conditions-effect report: this run's telemetry against a headless
    still-air baseline of the same spec (written only for terrain runs with
    wind -- the coupled ones). 404 until the run completes, or when the run
    carries no coupling to report on."""
    run = manager.get(run_id)
    path = manager.out_root / run_id / "effect.json"
    if run is None or run.status != "done" or not path.is_file():
        return JSONResponse({"error": "no effect report"}, status_code=404)
    return FileResponse(path, media_type="application/json")


#: Image kinds the page may fetch, and where each lives under the run.
#: A fixed map, not a caller-supplied path: these routes take names from
#: the browser, so the only defence that actually holds is refusing to
#: build a path out of anything but a known directory plus a matched
#: filename.
_IMAGE_KINDS = {"frames": "frames", "overlays": "overlays",
                "previews": "previews"}
#: A frame image, or a frame's own label sidecar beside it.
_IMAGE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}\.(png|json)$")
_SERVED_TYPES = {".png": "image/png", ".json": "application/json"}
_CAMERA_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@app.get("/runs/{run_id}/images")
def run_images(run_id: str):
    """What images this run produced, per camera and per kind.

    The page renders its gallery from this. Read off the directories
    rather than the manifest: a frame the manifest names but the
    renderer never wrote must not appear as an image the page then
    fails to load.
    """
    from webapp.capture import inventory

    run = manager.get(run_id)
    out = manager.out_root / run_id
    if run is None or not out.is_dir():
        return JSONResponse({"error": "no such run"}, status_code=404)
    return JSONResponse(inventory(out))


@app.get("/runs/{run_id}/cameras/{camera_id}/manifest.json")
def run_camera_manifest(run_id: str, camera_id: str):
    """ONE camera's labels: its block, its frames, and their context.

    The whole-run manifest carries every camera's frames in one list,
    which is right for verification and wrong for a person -- or a
    training pipeline -- that wants "the tower view". This is that view
    on its own, self-contained: the camera's own spec block, only its
    frame records, and the shared context those records are meaningless
    without (the CRS the metres are in, the scene and its raster digest,
    the landmarks, which flight the labels were solved over, and the
    digests that identify the run).

    DECLARED BEFORE the generic image route on purpose: that route's
    path pattern also matches this one, and while its .png check would
    404 rather than serve anything wrong, the 404 would be the answer.
    """
    if not _CAMERA_NAME.match(camera_id):
        return JSONResponse({"error": "no such camera"}, status_code=404)
    path = manager.out_root / run_id / "capture_manifest.json"
    if not path.is_file():
        return JSONResponse(
            {"error": "this run stated no cameras, so it took the legacy "
                      "single-clip path and wrote no capture manifest"},
            status_code=404)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return JSONResponse({"error": f"manifest unreadable: {exc}"},
                            status_code=500)

    from webapp.capture import camera_view

    view = camera_view(manifest, camera_id)
    if view is None:
        return JSONResponse(
            {"error": f"this run has no camera {camera_id!r}; it states "
                      f"{[c.get('camera_id') for c in manifest.get('cameras', [])]}"},
            status_code=404)
    return JSONResponse({**view, "run_id": run_id})


@app.get("/runs/{run_id}/cameras/{camera_id}/frames.zip")
def run_camera_archive(run_id: str, camera_id: str):
    """ONE view as a download: every frame, each frame's own labels
    beside it, the camera's manifest and a README.

    The page shows frames; this is how they leave it. A consumer who
    wants "the wingman view" gets a folder in which every PNG sits next
    to a JSON carrying where the camera was, which way it pointed, the
    lens, and everything the flight recorder logged at that instant --
    not a folder of pictures and a manifest to cross-reference by hand.

    Same name discipline as the image route, and DECLARED BEFORE it for
    the same reason the manifest route is.
    """
    from webapp.capture import frames_archive

    if not _CAMERA_NAME.match(camera_id):
        return JSONResponse({"error": "no such camera"}, status_code=404)
    out = manager.out_root / run_id
    if not out.is_dir():
        return JSONResponse({"error": "no such run"}, status_code=404)
    archive = frames_archive(out, camera_id)
    if archive is None:
        return JSONResponse(
            {"error": f"camera {camera_id!r} has no frames on disk in "
                      f"this run"},
            status_code=404)
    return FileResponse(archive, media_type="application/zip",
                        filename=f"{run_id}_{camera_id}_frames.zip")


@app.get("/frames.html", response_class=HTMLResponse)
def frames_page() -> str:
    """The per-camera frame browser: every image beside its own labels."""
    return (STATIC / "frames.html").read_text(encoding="utf-8")


@app.get("/runs/{run_id}/clips/{camera_id}.mp4")
def run_camera_clip(run_id: str, camera_id: str):
    """One camera's own clip: that many seconds of THAT view.

    Guarded exactly like the image routes -- the id comes off a URL and
    names a file -- and declared before the generic image route, whose
    pattern also matches this path.
    """
    if not _CAMERA_NAME.match(camera_id):
        return JSONResponse({"error": "no such clip"}, status_code=404)
    root = (manager.out_root / run_id / "clips").resolve()
    path = root / f"{camera_id}.mp4"
    try:
        resolved = path.resolve()
        resolved.relative_to(root)        # the clip stays inside the run
    except (OSError, ValueError):
        return JSONResponse({"error": "no such clip"}, status_code=404)
    if not resolved.is_file():
        return JSONResponse({"error": "no such clip"}, status_code=404)
    return FileResponse(resolved, media_type="video/mp4")


@app.get("/runs/{run_id}/{kind}/{camera_id}/{name}")
def run_image(run_id: str, kind: str, camera_id: str, name: str):
    """One rendered frame, overlay or preview.

    The frames a run renders have always survived on disk; until now
    nothing served them, so the only visual output the page could show
    was a single mp4. Every path component is validated against a
    pattern and the resolved path is required to stay inside the run
    directory -- a name like ``..%2f..%2fetc%2fpasswd`` gets a 404, not
    a file.
    """
    if kind not in _IMAGE_KINDS or not _IMAGE_NAME.match(name):
        return JSONResponse({"error": "no such image"}, status_code=404)
    if camera_id != "-" and not _CAMERA_NAME.match(camera_id):
        return JSONResponse({"error": "no such image"}, status_code=404)
    root = (manager.out_root / run_id / _IMAGE_KINDS[kind]).resolve()
    path = (root if camera_id == "-" else root / camera_id) / name
    try:
        resolved = path.resolve()
        resolved.relative_to(root)        # the image stays inside the run
    except (OSError, ValueError):
        return JSONResponse({"error": "no such image"}, status_code=404)
    if not resolved.is_file():
        return JSONResponse({"error": "no such image"}, status_code=404)
    # A sidecar only lives beside a FRAME; overlays and previews carry
    # no labels of their own, and a .json under them is not ours.
    if resolved.suffix == ".json" and kind != "frames":
        return JSONResponse({"error": "no such image"}, status_code=404)
    return FileResponse(resolved, media_type=_SERVED_TYPES[resolved.suffix])


@app.get("/runs/{run_id}/capture_manifest.json")
def run_capture_manifest(run_id: str):
    """The capture manifest: every frame's camera pose, full intrinsics,
    the aircraft state at that instant and the scene's landmarks. This is
    what makes the images usable as labelled data rather than just
    pictures, and it is written for camera-carrying runs."""
    path = manager.out_root / run_id / "capture_manifest.json"
    if not path.is_file():
        return JSONResponse(
            {"error": "no capture manifest: this run stated no cameras, so "
                      "it took the legacy single-clip path"},
            status_code=404)
    return FileResponse(path, media_type="application/json")


@app.get("/runs/{run_id}/verify.json")
def run_verify(run_id: str):
    """The verification summary for a captured run: which checks passed,
    which failed, and which could not run and why."""
    path = manager.out_root / run_id / "verify.json"
    if not path.is_file():
        return JSONResponse({"error": "no verification summary"},
                            status_code=404)
    return FileResponse(path, media_type="application/json")


@app.get("/runs/{run_id}/provenance.json")
def run_provenance(run_id: str):
    path = manager.out_root / run_id / "provenance.json"
    if not path.is_file():
        return JSONResponse({"error": "no provenance"}, status_code=404)
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


@app.websocket("/telemetry")
async def telemetry(socket: WebSocket) -> None:
    """Run status pushed once a second. For the clip pipeline this is
    orchestration progress; the interactive host will stream real telemetry
    through the same channel."""
    await socket.accept()
    try:
        while True:
            await socket.send_json(manager.status())
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
