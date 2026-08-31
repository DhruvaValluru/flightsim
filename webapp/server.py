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
    # plan_flyable_defaults -> plan_trim_recovery -> project_for_ue_host
    # -> validate.
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
