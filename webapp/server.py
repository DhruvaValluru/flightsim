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

from core.nl.compiler import (  # noqa: E402
    camera_questions, compile_prompt, rescale_moves,
)
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
    sample_randomization_or_refuse,
    plan_flyable_defaults,
    plan_scene_setting,
    plan_terrain_environment,
    plan_terrain_flight,
    plan_trim_recovery,
    plan_water_surface,
    project_for_ue_host,
    refuse_placeholder_mesh,
)

app = FastAPI(title="flightsim", docs_url=None, redoc_url=None)


def _plain(refusal: Dict[str, Any]) -> Dict[str, Any]:
    """A refusal dict with the plain-language sentence and hint added
    (core/messages catalogue, via webapp.generate.words): ``sentence`` and
    ``hint`` for the page to show first, ``details`` (rule name, technical
    message) for the disclosure underneath. The original keys stay."""
    from webapp.generate import words

    rule = refusal.get("refused") or refusal.get("constraint")
    if not isinstance(rule, str) or refusal.get("sentence"):
        return refusal
    message = refusal.get("message") or refusal.get("error") or ""
    worded = words({"constraint": rule, "message": message,
                    **{k: refusal[k] for k in ("actual", "limit", "unit") if k in refusal}})
    return {**refusal, "sentence": worded["sentence"], "hint": worded["hint"],
            "details": {**worded["details"], **(refusal.get("details") or {})}}


@app.middleware("http")
async def plain_language_refusals(request, call_next):
    """Every refused answer this server gives (a 4xx JSON body naming a
    rule) carries the plain sentence beside the rule name, so no page has
    to show a rule name first."""
    response = await call_next(request)
    if response.status_code < 400 or not str(
            response.headers.get("content-type", "")).startswith("application/json"):
        return response
    body = b"".join([chunk async for chunk in response.body_iterator])
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if isinstance(data, dict) and (data.get("refused") or data.get("constraint")):
        data = _plain(data)
        return JSONResponse(data, status_code=response.status_code)
    from fastapi.responses import Response

    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
    return Response(body, status_code=response.status_code, headers=headers,
                    media_type=response.media_type)
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
    #: "1 frame (preview)": every camera captures exactly one image (a
    #: counted interval capture of 1, a USER edit shown in the table).
    still: bool = False


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
    # The render's time of day (spec 9, optional, absent-canonical): always
    # a row, so a stated one is visible and an unstated one can be typed.
    environment_at = max(i for i, f in enumerate(fields) if f["section"] == "environment") + 1
    fields.insert(environment_at, {
        "section": "environment", "name": "time_of_day",
        "value": spec.time_of_day.value, "unit": spec.time_of_day.unit,
        "source": str(spec.time_of_day.source), "from": spec.time_of_day.frm,
        "std": spec.time_of_day.std, "detail": spec.time_of_day.detail,
    })
    # The rain / snow rate (spec 9, optional, absent-canonical): always a
    # row too, so a prompt's "rain" the compiler did not set can be typed
    # here (the prompt.not_set refusal points at this row).
    fields.insert(environment_at + 1, {
        "section": "environment", "name": "precipitation_rate_mmh",
        "value": spec.precipitation_rate_mmh.value,
        "unit": spec.precipitation_rate_mmh.unit,
        "source": str(spec.precipitation_rate_mmh.source),
        "from": spec.precipitation_rate_mmh.frm,
        "std": spec.precipitation_rate_mmh.std,
        "detail": spec.precipitation_rate_mmh.detail,
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
    # The randomisation block: one labeled block of provenanced rows,
    # editable like the others. The page's dict ALWAYS carries the block
    # (the canonical spec omits a default one) so an edit has a row to
    # land in; from_dict normalises a default block back to absent.
    randomization = [{
        "name": name, "value": quantity.value, "unit": quantity.unit,
        "source": str(quantity.source), "from": quantity.frm,
        "std": quantity.std, "detail": quantity.detail,
    } for name, quantity in spec.randomization.quantities()]
    # The lighting block (core/scene/lighting.py): the same shape, so the
    # page's lighting panel and its table rows have entries to edit.
    lighting = [{
        "name": name, "value": quantity.value, "unit": quantity.unit,
        "source": str(quantity.source), "from": quantity.frm,
        "std": quantity.std, "detail": quantity.detail,
    } for name, quantity in spec.lighting.quantities()]
    spec_dict = spec.to_dict()
    # The block's own dict (always present for the page) MERGED with the
    # policy the canonical form carries under the same key: the policy
    # lives on ScenarioSpec.randomization_policy, not on the block, so
    # replacing the section wholesale dropped it and the page's digest
    # (of this dict, re-read by /run) forked from the one shown here.
    randomization_section = spec.randomization.to_dict()
    # Every row the page shows needs an entry to edit: the spec-8 policy
    # leaves are absent from to_dict() at their placeholders, so the page
    # read entry.value of undefined and every camera button failed with
    # "could not reach the server" (measured on the owner's machine).
    # A placeholder read back is the placeholder, so the digest is unmoved.
    for name, quantity in spec.randomization.quantities():
        randomization_section.setdefault(name, quantity.to_dict())
    canonical_section = spec_dict.get("randomization") or {}
    if "policy" in canonical_section:
        randomization_section["policy"] = canonical_section["policy"]
    spec_dict["randomization"] = randomization_section
    # The lighting section, always present for the page (the canonical form
    # omits a default block; from_dict reads a default one back as absent,
    # so the digest is unmoved).
    spec_dict["lighting"] = spec.lighting.to_dict()
    # The time-of-day row's entry (omitted from the canonical form while
    # unstated; read back unstated, so the digest is unmoved).
    spec_dict.setdefault("environment", {}).setdefault(
        "time_of_day", spec.time_of_day.to_dict())
    spec_dict["environment"].setdefault(
        "precipitation_rate_mmh", spec.precipitation_rate_mmh.to_dict())
    return {"digest": spec.digest(), "name": spec.name,
            "prompt": spec.prompt, "notes": spec.notes,
            "fields": fields, "cameras": cameras,
            "randomization": randomization, "lighting": lighting,
            "lighting_presets": _lighting_presets(), "dict": spec_dict,
            "table": spec.render_table()}


def _lighting_presets() -> Dict[str, Any]:
    """The preset table and ranges for the page's lighting panel (one
    source: core/scene/lighting.py)."""
    from core.scene.lighting import PRESETS, RANGES

    return {"presets": PRESETS,
            "ranges": {name: list(bounds) for name, bounds in RANGES.items()}}


def _validation_payload(spec: ScenarioSpec) -> Dict[str, Any]:
    report = validate(spec)
    return {
        "ok": report.ok,
        # Each violation in plain words first (sentence, hint), the rule
        # name and the technical message beside it for the disclosure.
        "violations": [_plain({
            "constraint": v.constraint, "message": v.message,
            "actual": v.actual, "limit": v.limit, "unit": v.unit,
        }) for v in report.violations],
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
            # the switch and why, never silently. It compiles the ORIGINAL
            # prompt plus whatever the answer round said to its questions
            # (the aircraft, the camera view), even when the LLM died
            # between the question and answer rounds.
            spec = compile_prompt(prompt, answers=request.answers)
            compiler_used = "regex (llm unavailable)"
            llm_note = str(exc)
            questions = [] if request.answers else camera_questions(prompt)
    else:
        # The regex path asks at most two clarifying questions
        # (camera_questions): which aircraft, when the prompt names a kind
        # of aircraft or one the vocabulary lacks; which view, when it
        # speaks of imagery and names none. Asked once; the answer round
        # compiles with the answers and asks nothing.
        spec = compile_prompt(prompt, answers=request.answers)
        compiler_used = "regex"
        questions = [] if request.answers else camera_questions(prompt)

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
        previous = float(spec.duration.value)
        spec.set("duration", seconds, frm="clip length selector (web UI)")
        # A move phrase spans the whole flight: keyframes that ended at
        # the old duration end at the new one (stated keyframe times
        # elsewhere are left alone).
        rescale_moves(spec, previous, seconds)
    if request.still:
        # One image per camera: the shortest clip, and a counted capture
        # of 1 (interval trigger; count_exactness grades it). Cameras the
        # prompt did not name get the default view first.
        previous = float(spec.duration.value)
        spec.set("duration", 3.0, frm="1-frame preview (web UI)")
        rescale_moves(spec, previous, 3.0)
        if not spec.cameras:
            from core.scenario.camera import default_cameras

            spec.cameras = list(default_cameras(spec))
        for camera in spec.cameras:
            camera.set("trigger", "interval", frm="1-frame preview (web UI)")
            camera.set("capture_count", 1, frm="1-frame preview (web UI)")

    # Planning happens BEFORE the table and verdict are built, so what the
    # user reviews is what will run: the weather event's documented
    # composition edits (a tornado descends a defaulted altitude into the
    # vortex band; a thunderstorm sets the defaulted turbulence word),
    # then the envelope floors -- a prompt whose numbers the system chose
    # must not be refused over the system's own choices. Every move is a
    # recorded edit (source becomes ``derived``); stated values never
    # move. /run applies the same planners again: value-idempotent.
    plan_scene_setting(spec)
    plan_water_surface(spec)
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
    # Phase 10: the randomisation block draws its values (off by
    # default -> no-op); a window with no daylight refuses by name in
    # the verdict rather than rendering an uncalibrated night.
    randomization_refusal = sample_randomization_or_refuse(spec)

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
    if randomization_refusal is not None:
        payload["validation"]["ok"] = False
        # validate() already names an unmapped variation; do not say it twice.
        named = {v.get("constraint") for v in payload["validation"]["violations"]}
        if randomization_refusal.get("constraint") not in named:
            payload["validation"]["violations"].append(_plain(randomization_refusal))
    return JSONResponse(payload)


class AircraftPlacement(BaseModel):
    """One extra aircraft: where it is relative to the primary and how it
    moves. Offsets are in the primary's heading frame (metres): ahead is
    forward, right is to its right, up is above it."""

    aircraft: Optional[str] = None
    ahead_m: float = 0.0
    right_m: float = 0.0
    up_m: float = 0.0
    #: How much faster (+) or slower (-) than the primary, in knots.
    speed_delta_kt: float = 0.0
    #: The aircraft just sits at its offset instead of flying with the
    #: primary (so the primary can pass it, or it can block the view).
    hold: bool = False


class AircraftRequest(BaseModel):
    """Set how many aircraft the scene holds on the spec the page is
    holding: the primary plus ``others`` (at most two more)."""

    spec: Dict[str, Any]
    others: List[AircraftPlacement] = []


@app.post("/aircraft")
def aircraft_endpoint(request: AircraftRequest) -> JSONResponse:
    """One aircraft, or two or three in one scene.

    Replaces the spec's traffic list with the stated placements (each a
    user-stated field, so a later edit in the review table still wins),
    re-frames every default chase view so the camera shows all the
    aircraft, and re-validates. Refusals are the validator's, by name; a
    refused request leaves the page's spec untouched.
    """
    from core.scenario.blocks import MAX_TRAFFIC, TrafficSpec
    from core.scenario.camera import frame_traffic
    from core.scenario.validate import validate_blocks

    try:
        spec = ScenarioSpec.from_dict(request.spec)
    except (ValueError, KeyError) as exc:
        return JSONResponse({"error": f"spec did not parse: {exc}"},
                            status_code=400)
    if len(request.others) > MAX_TRAFFIC:
        return JSONResponse(
            {"refused": "traffic.count",
             "error": f"at most {MAX_TRAFFIC + 1} aircraft in one scene "
                      f"(the primary and {MAX_TRAFFIC} more)"},
            status_code=409)

    frm = "stated on the page: aircraft in the scene"
    entries = []
    for other in request.others:
        entry = TrafficSpec.defaulted(
            other.aircraft or str(spec.aircraft.value), frm=frm)
        entry.set("track", "stationary" if other.hold else "offset", frm=frm)
        for name in ("ahead_m", "right_m", "up_m", "speed_delta_kt"):
            entry.set(name, float(getattr(other, name)), frm=frm)
        entries.append(entry)
    spec.traffic = entries
    frame_traffic(spec)

    violations = validate_blocks(spec)
    if violations:
        first = violations[0]
        return JSONResponse(
            {"refused": first.constraint,
             "error": "; ".join(v.render() for v in violations)},
            status_code=409)
    return JSONResponse(_spec_payload(spec))


class CameraPromptRequest(BaseModel):
    """A sentence describing where the camera should be, on the spec the
    page is holding."""

    spec: Dict[str, Any]
    prompt: str


@app.post("/cameras/prompt")
def camera_prompt_endpoint(request: CameraPromptRequest) -> JSONResponse:
    """Place a camera from a sentence ("behind and above both planes,
    about 300 m back").

    A language model (the rule parser when none is reachable) reads the
    sentence into an offset; the spec's own geometry then widens the lens
    and pulls the camera back until every aircraft is in frame, and says
    so. The camera is added like any picked view, with the user's words
    as the provenance of every number, and refused by the validator's
    names if it is unusable.
    """
    from core.capture.validate import validate_cameras
    from core.nl.camera_prompt import CameraPromptError, build_camera, read_intent

    try:
        spec = ScenarioSpec.from_dict(request.spec)
    except (ValueError, KeyError) as exc:
        return JSONResponse({"error": f"spec did not parse: {exc}"},
                            status_code=400)
    sentence = request.prompt.strip()
    if not sentence or len(sentence) > 500:
        return JSONResponse(
            {"error": "describe the camera in 1 to 500 characters"},
            status_code=400)
    try:
        intent, skipped = read_intent(sentence, spec)
    except CameraPromptError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    taken = {str(c.camera_id.value) for c in spec.cameras}
    camera_id, suffix = "prompt", 0
    while camera_id in taken:
        suffix += 1
        camera_id = f"prompt{suffix}"
    camera, notes = build_camera(spec, intent, camera_id)
    spec.cameras.append(camera)
    violations = validate_cameras(spec)
    if violations:
        first = violations[0]
        return JSONResponse(
            {"refused": first.constraint,
             "error": "; ".join(v.render() for v in violations)},
            status_code=409)
    payload = _spec_payload(spec)
    payload["camera_prompt"] = {
        "camera_id": camera_id, "intent": intent.to_dict(), "notes": notes,
        "model_skipped": skipped}
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
    from core.scenario.camera import CameraSpec, frame_traffic, plan_full_capture

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
    spec.cameras.append(camera)
    frame_traffic(spec)
    spec.cameras.pop()
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
    # Mapped water under the stated place plans the water surface class
    # (X-Plane mask, when extracted on this machine): before placement,
    # so the control ridge's arbitrary georeference is never looked up.
    plan_water_surface(spec)
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
    # Randomisation draws AFTER the camera planner (its jitter is about
    # the planned placement) and BEFORE the host projection; off by
    # default. Same sampler as /compile: value-idempotent.
    randomization_refusal = sample_randomization_or_refuse(spec)
    project_for_ue_host(spec)

    # Validation governs the edited spec too: the run endpoint re-validates
    # everything it is handed, whatever the page claimed.
    verdict = _validation_payload(spec)
    if clearance_refusal is not None:
        verdict["ok"] = False
        verdict["violations"].append(clearance_refusal)
    if randomization_refusal is not None:
        verdict["ok"] = False
        verdict["violations"].append(randomization_refusal)
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
    # the same pattern for the UE half: without the Windows host the page says so up front
    # and a run refuses ue.platform by name instead of 500ing.
    from core.scenario.blocks import DEFAULT_CLASSES, labelled_airframes
    from core.util.platform import os_name, ue_available

    # The class list is written down ahead of time (taxonomy.classes, the
    # documented default unless a spec states its own): stated up front
    # with its exact values, 0 reserved for sky / nothing, so the page
    # never shows categories made up from what a scene happens to hold.
    classes = [{"class_id": 0, "name": "sky"}] + [
        {"class_id": i + 1, "name": name}
        for i, name in enumerate(DEFAULT_CLASSES)]
    return JSONResponse({**manager.status(), "llm_available": llm_available(),
                         "platform": os_name(),
                         "render_available": ue_available(),
                         "taxonomy": classes,
                         "airframes": labelled_airframes()})


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
                "boxed": "boxed", "boxed3d": "boxed3d", "previews": "previews"}
#: A frame image, a frame's own label sidecar beside it, or the metric
#: depth the label bundle declares under ``labels.depth_f32`` (raw
#: little-endian float32, contracts §8): the one bundle member that is
#: neither a PNG nor JSON, served as bytes.
_IMAGE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}\.(png|json|f32)$")
_SERVED_TYPES = {".png": "image/png", ".json": "application/json",
                 ".f32": "application/octet-stream"}
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

    from core.capture.frame_checks import read_frame_checks
    from webapp.capture import camera_view

    view = camera_view(manifest, camera_id,
                       read_frame_checks(manager.out_root / run_id))
    if view is None:
        return JSONResponse(
            {"error": f"this run has no camera {camera_id!r}; it states "
                      f"{[c.get('camera_id') for c in manifest.get('cameras', [])]}"},
            status_code=404)
    return JSONResponse({**view, "run_id": run_id})


@app.get("/runs/{run_id}/dataset_card.html")
def run_dataset_card(run_id: str, format: str = "coco",
                     cameras: Optional[str] = None, image: str = "ideal",
                     labels_only: bool = False, train: float = 0.8,
                     val: float = 0.1, test: float = 0.1, seed: int = 0,
                     tabular: bool = False, box_pictures: bool = False,
                     box3d_pictures: bool = False):
    """The dataset card's summary page for exactly the choices given (the
    same export the zip holds): image counts, class balance, conditions,
    seeds, check results and what the dataset does not promise."""
    response = run_dataset_archive(run_id, format, cameras, image, labels_only,
                                   train, val, test, seed, tabular, box_pictures,
                                   box3d_pictures, _want_card=True)
    return response


@app.get("/runs/{run_id}/dataset.zip")
def run_dataset_archive(run_id: str, format: str = "coco",
                        cameras: Optional[str] = None, image: str = "ideal",
                        labels_only: bool = False, train: float = 0.8,
                        val: float = 0.1, test: float = 0.1, seed: int = 0,
                        tabular: bool = False, box_pictures: bool = False,
                        box3d_pictures: bool = False, _want_card: bool = False):
    """The whole run exported as a dataset with the choices made on the
    page -- format (coco, kitti, webdataset, yolo, voc or all), cameras
    (comma list; all when absent), image (ideal | sensor), labels only,
    the train / val / test split and its seed, the tabular flight table,
    and the 2-D / 3-D box pictures -- every one written into the dataset
    card's ``choices``. The export's refusals stand, in words, as a 409;
    ``X-Dataset-Labels-Only: 1`` when the zip holds labels only."""
    from core.dataset.export import ExportError
    from webapp.capture import dataset_archive

    out = manager.out_root / run_id
    if not (out / "capture_manifest.json").is_file():
        return JSONResponse({"error": "this run has no capture manifest (no "
                                      "cameras were stated), so there is "
                                      "nothing to export"}, status_code=404)
    picked = [c.strip() for c in (cameras or "").split(",") if c.strip()]
    if any(not _CAMERA_NAME.match(c) for c in picked):
        return JSONResponse({"error": "no such camera"}, status_code=404)
    try:
        result = dataset_archive(
            out, format, cameras=picked or None, image=image,
            labels_only=labels_only, fractions=(train, val, test), seed=seed,
            tabular=tabular, box_pictures=box_pictures,
            box3d_pictures=box3d_pictures,
            chosen_on="the web app's run page (dataset download)")
    except ExportError as exc:
        return JSONResponse({"refused": exc.constraint, "error": exc.message},
                            status_code=409)
    if _want_card:
        from core.dataset.card_page import CARD_HTML

        page = Path(result["dataset"]) / CARD_HTML
        if not page.is_file():
            return JSONResponse({"error": "the export wrote no card page"}, status_code=404)
        return HTMLResponse(page.read_text(encoding="utf-8"))
    response = FileResponse(result["archive"], media_type="application/zip",
                            filename=f"{run_id}_dataset_{result['format']}.zip")
    if result["labels_only"]:
        response.headers["X-Dataset-Labels-Only"] = "1"
    return response


@app.get("/runs/{run_id}/cameras/{camera_id}/box3d.zip")
def run_camera_box3d_archive(run_id: str, camera_id: str):
    """ONE view's 3-D boxes as a download: per frame the 3-D box picture
    and that frame's box_3d JSON. Declared before the generic image route
    for the same reason the frames zip is."""
    from webapp.capture import box3d_archive

    if not _CAMERA_NAME.match(camera_id):
        return JSONResponse({"error": "no such camera"}, status_code=404)
    out = manager.out_root / run_id
    if not out.is_dir():
        return JSONResponse({"error": "no such run"}, status_code=404)
    archive = box3d_archive(out, camera_id)
    if archive is None:
        return JSONResponse({"error": f"camera {camera_id!r} has no frames in "
                                      f"this run"}, status_code=404)
    return FileResponse(archive, media_type="application/zip",
                        filename=f"{run_id}_{camera_id}_3d_boxes.zip")


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
    # no labels of their own, and a .json or .f32 under them is not ours.
    if resolved.suffix in (".json", ".f32") and kind != "frames":
        return JSONResponse({"error": "no such image"}, status_code=404)
    return FileResponse(resolved, media_type=_SERVED_TYPES[resolved.suffix])


_SCHEMA_NAME = re.compile(r"^capture_manifest\.v\d+\.schema\.json$")


@app.get("/schemas/{name}")
def schema_file(name: str):
    """The published capture-manifest schema (docs/schemas/), so the
    frames page can link the contract every manifest it shows was
    validated against. Only a schema file's own name is served."""
    from core.capture.schema import SCHEMA_DIR

    if not _SCHEMA_NAME.match(name):
        return JSONResponse({"error": "no such schema"}, status_code=404)
    path = SCHEMA_DIR / name
    if not path.is_file():
        return JSONResponse({"error": "no such schema"}, status_code=404)
    return FileResponse(path, media_type="application/json")


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
        # A run verified by `flightsim.verify` (or the batch runner)
        # keeps the same verdict as verification.json.
        path = manager.out_root / run_id / "verification.json"
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


# -- Phase 2, package I part 2: the guided page and its endpoints ---------------
#
# Every route below is a thin wrapper over webapp/generate.py (the
# campaign-facing service layer): the service raises GenerateRefusal
# carrying the response body already in the catalogue's words, and the
# route only picks the status code. Nothing above this line changed.

from webapp import generate as generate_module  # noqa: E402

generator = generate_module.GenerateService()


class GeneratePlanRequest(BaseModel):
    prompt: str
    #: The clarification round, exactly the /compile protocol: the page
    #: echoes the questions with the answers; the server keeps no state.
    questions: Optional[List[Dict[str, Any]]] = None
    answers: Optional[List[Dict[str, str]]] = None
    #: None (the page's count left blank): the prompt's stated count,
    #: every view's added, else DEFAULT_IMAGES; both stated and
    #: disagreeing is refused campaign.image_count.
    images: Optional[int] = None
    format: str = generate_module.DEFAULT_FORMAT
    tier: str = "llm"
    seed: Optional[int] = None


class GeneratePreviewRequest(BaseModel):
    #: The plan's compiled spec (payload ``spec``), unchanged.
    spec: Dict[str, Any]
    images: Optional[int] = None
    seed: int = 1
    workers: int = 1


class GenerateStartRequest(BaseModel):
    prompt: str
    answers: Optional[List[Dict[str, str]]] = None
    images: Optional[int] = None
    format: str = generate_module.DEFAULT_FORMAT
    seed: Optional[int] = None
    workers: int = 1
    tier: str = "regex"
    #: The plan's spec digest, so the response can say whether the
    #: campaign's own compile (Campaign.create) produced the same spec.
    plan_digest: Optional[str] = None
    disk_budget_bytes: Optional[int] = None


def _generate_call(function, *args, **kwargs):
    """Run a service call; a GenerateRefusal becomes its status code
    with the body the service already put into words."""
    try:
        return JSONResponse(function(*args, **kwargs))
    except generate_module.GenerateRefusal as exc:
        return JSONResponse(exc.payload, status_code=exc.status_code)


@app.get("/generate.html", response_class=HTMLResponse)
def generate_page() -> str:
    """The guided page: ask, clarify, preview, generate, review, download."""
    return (STATIC / "generate.html").read_text(encoding="utf-8")


@app.post("/generate/plan")
def generate_plan(request: GeneratePlanRequest) -> JSONResponse:
    """Prompt -> the compilers' questions (at most three), or the plan
    preview: a paragraph, the refusals in the catalogue's words (rule
    name under ``details``), the estimate, the expert command."""
    return _generate_call(generator.plan, request.prompt, answers=request.answers,
                          questions=request.questions, images=request.images,
                          fmt=request.format, tier=request.tier, seed=request.seed)


@app.post("/generate/preview")
def generate_preview(request: GeneratePreviewRequest) -> JSONResponse:
    """One sample case, run headless with --max-previews 1 (rendered
    with overlays when an engine is present): the picture's URL and
    the measured per-case cost."""
    return _generate_call(generator.preview, request.spec, images=request.images,
                          seed=request.seed, workers=request.workers)


@app.get("/generate/preview/{preview_id}/{kind}/{camera_id}/{name}")
def generate_preview_image(preview_id: str, kind: str, camera_id: str, name: str):
    """The preview's picture (overlay or geometry preview), guarded like
    the run image route."""
    try:
        path = generator.preview_image(preview_id, kind, camera_id, name)
    except generate_module.GenerateRefusal as exc:
        return JSONResponse(exc.payload, status_code=exc.status_code)
    return FileResponse(path, media_type="image/png")


@app.post("/generate/start")
def generate_start(request: GenerateStartRequest) -> JSONResponse:
    """Create the campaign (refused by name before a worker starts) and
    run it in the background; returns its id and the expert command."""
    return _generate_call(generator.start, request.prompt, answers=request.answers,
                          images=request.images, fmt=request.format, seed=request.seed,
                          workers=request.workers, tier=request.tier,
                          plan_digest=request.plan_digest,
                          disk_budget_bytes=request.disk_budget_bytes)


@app.post("/generate/{campaign_id}/pause")
def generate_pause(campaign_id: str) -> JSONResponse:
    return _generate_call(generator.control, campaign_id, "pause")


@app.post("/generate/{campaign_id}/resume")
def generate_resume(campaign_id: str) -> JSONResponse:
    return _generate_call(generator.control, campaign_id, "resume")


@app.post("/generate/{campaign_id}/cancel")
def generate_cancel(campaign_id: str) -> JSONResponse:
    return _generate_call(generator.control, campaign_id, "cancel")


@app.get("/generate/campaigns")
def generate_campaigns() -> JSONResponse:
    """Every campaign, newest first, for the page's campaign list. Declared
    before /generate/{campaign_id}, which would otherwise take the word
    'campaigns' as an id."""
    return _generate_call(generator.list_campaigns)


@app.get("/generate/{campaign_id}")
def generate_status(campaign_id: str) -> JSONResponse:
    """Progress from the ledger in human terms (the polling fallback)."""
    return _generate_call(generator.progress, campaign_id)


@app.get("/generate/{campaign_id}/events")
def generate_events(campaign_id: str, interval: float = 1.0,
                    limit: Optional[int] = None):
    """Server-sent events through StreamingResponse (no sse-starlette):
    a ``progress`` event now and on every change, ``end`` on a terminal
    state, ``idle`` when nothing will change until a resume."""
    from fastapi.responses import StreamingResponse

    try:
        generator.open(campaign_id)
    except generate_module.GenerateRefusal as exc:
        return JSONResponse(exc.payload, status_code=exc.status_code)
    stream = generator.events(campaign_id, interval=max(0.05, float(interval)), limit=limit)
    return StreamingResponse(stream, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/generate/{campaign_id}/frames")
def generate_frames(campaign_id: str) -> JSONResponse:
    """The gallery: each case's picture with overlays where pixels
    were drawn, its draw and its verdict."""
    return _generate_call(generator.frames, campaign_id)


@app.get("/generate/{campaign_id}/frames/{case_id}/{kind}/{camera_id}/{name}")
def generate_frame_image(campaign_id: str, case_id: str, kind: str, camera_id: str,
                         name: str):
    try:
        path = generator.frame_image(campaign_id, case_id, kind, camera_id, name)
    except generate_module.GenerateRefusal as exc:
        return JSONResponse(exc.payload, status_code=exc.status_code)
    return FileResponse(path, media_type="image/png")


@app.get("/generate/{campaign_id}/card")
def generate_card(campaign_id: str, format: Optional[str] = None) -> JSONResponse:
    """The dataset's card in plain words for the Download screen
    (images, labelled objects, class balance, conditions drawn, checks,
    what it does not claim, format); rule and check names only under
    ``details``. The export's own refusals stand, in words, as a 409."""
    return _generate_call(generator.card, campaign_id, format)


@app.get("/generate/{campaign_id}/card.html")
def generate_card_page(campaign_id: str, format: Optional[str] = None):
    """The dataset card's summary page for the campaign's export in the
    chosen format (the same export the download zips)."""
    from core.dataset.card_page import CARD_HTML

    try:
        result = generator.export_result(campaign_id, format)
    except generate_module.GenerateRefusal as exc:
        return JSONResponse(exc.payload, status_code=exc.status_code)
    page = Path(result["dataset_path"]) / CARD_HTML
    if not page.is_file():
        return JSONResponse({"error": "the export wrote no card page"}, status_code=404)
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/generate/{campaign_id}/download")
def generate_download(campaign_id: str, format: Optional[str] = None):
    """A zip of the export plus its card (the card records the format).
    ``X-Dataset-Labels-Only: 1`` when the zip holds no picture (a
    headless campaign), so the page can say so after the download.
    The export's own refusals stand, in words, as a 409."""
    try:
        result = generator.download(campaign_id, format)
    except generate_module.GenerateRefusal as exc:
        return JSONResponse(exc.payload, status_code=exc.status_code)
    return FileResponse(result["archive"], media_type="application/zip",
                        filename=result["filename"],
                        headers={"X-Dataset-Format": result["format"],
                                 "X-Dataset-Runs": str(result["runs"]),
                                 "X-Dataset-Labels-Only": "1" if result["labels_only"] else "0"})
