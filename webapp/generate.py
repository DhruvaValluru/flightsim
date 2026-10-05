"""The campaign-facing service layer behind ``webapp/static/generate.html``
(contracts §8; brainstorm §8; Phase 2 package I, part 2).

Six page states -- ask, clarify, preview, generate, review, download --
over the campaign object (``core.campaign``, package G) and the message
catalogue (``core.messages``, package I part 1). Nothing here decides
whether a scenario is refused, draws a case, renders a pixel or
verifies one: the compilers ask the questions, the validator and the
sampler refuse by name, ``core.campaign.workers.run_index`` runs the one
sample case the preview shows through the same ``flightsim.capture``
command every campaign case runs, and ``Campaign.run`` runs the campaign.
This module PRESENTS: it turns every refusal into the catalogue's
sentence (:func:`words`), every progress state into the catalogue's
words, and the ledger into numbers a person can read
(:func:`progress`).

Three rules the page is graded on, and where each lives:

* **The catalogue only.** :func:`words` is the ONE place a refusal is
  rendered for the page: ``sentence`` and ``hint`` come from the
  catalogue, and the rule name goes under ``details`` -- never into a
  default field. A name the catalogue does not know renders the
  producer's own message as the sentence, still with the rule under
  ``details`` and ``catalogued: false`` so the gap shows; no sentence
  is invented here. (Every name this module raises -- ``campaign.*``,
  ``export.*``, ``compile.*`` -- has its entry today.)
* **Progress from the ledger.** :func:`progress` reads
  ``ledger.jsonl`` through ``core.campaign.ledger`` every time it is
  asked; the service keeps no counter. A ledger written by hand (the
  test does) is reported exactly as written.
* **Measured, not asserted.** The per-case cost (frames, bytes,
  seconds) is measured from the preview run and from completed cases,
  never from the recorder-cadence estimate alone; where nothing has
  been measured the estimate says so (``basis``) and the projection is
  ``None``.

What is NOT claimed: pixels on this platform (the preview and every
frame in the gallery are the geometry previews unless an engine drew
frames; the response says which); a plan compiled by the language
model is compiled AGAIN by ``Campaign.create`` when the campaign
starts (the campaign object compiles its own prompt), so the start
response carries both digests and says when they differ -- with the
offline compiler they are identical by construction; more than one
campaign per server process (the second is refused while the first
runs); the server-sent event stream is one-way progress, not control.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import threading
import time
import uuid
import zipfile
from copy import deepcopy
from pathlib import Path

from assets_pipeline.importer import is_imported
from core.util.platform import ue_available
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from core.campaign import Campaign, CampaignError
from core.campaign.campaign import (
    CANCELLED, DONE, FAILED, PAUSED, PLANNED, RUNNING, estimate_frames,
    reconcile_images, release_stated_counts, stated_images,
)
from core.campaign.ledger import STATUS_REFUSED, STATUSES, latest_by_index, summarise
from core.campaign.workers import RUNS_DIR, run_index, utc_now
from core.dataset.export import CARD_JSON, FORMATS, ExportError
from core.messages import explain, is_catalogued, name_of, technical
from core.nl.compiler import camera_questions, compile_prompt
from core.nl.llm_compiler import LLMCompileError, compile_prompt_llm
from core.scenario.randomization import RandomizationError, sample_randomization
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate

REPO = Path(__file__).resolve().parents[1]

#: Where the page's campaigns live; tests point this at a temp dir.
DEFAULT_ROOT = REPO / "runs" / "campaigns"
#: ``"package.module:function"`` with ``run_with_watchdog``'s signature,
#: handed to ``Campaign.run`` / ``run_index`` so a test can stand in for
#: the capture CLI; None runs the real one.
CAPTURE_RUNNER: Optional[str] = None
#: The compilers' question round is at most this long (llm_compiler
#: MAX_QUESTIONS is 3; the regex path asks one).
MAX_QUESTIONS = 3
DEFAULT_IMAGES = 100
DEFAULT_FORMAT = "coco"
#: Terminal campaign states: the event stream stops after reporting one.
TERMINAL = (DONE, FAILED, CANCELLED)
#: Gallery cap: overlays first (pixels drawn), then geometry previews.
MAX_GALLERY = 60
#: Histogram bins for a numeric leaf's realised values.
HISTOGRAM_BINS = 6
#: The page's one sentence for a download with no pictures in it (a
#: headless campaign: the export is labels only). The download says it
#: as ``X-Dataset-Labels-Only: 1`` and the page says this, before the
#: download (from the card) and after it (from the header).
LABELS_ONLY_WORDS = "Labels only: no picture was drawn on this machine."
#: The preview's plain sentence when the picture is the geometry
#: preview: masks and boxes are drawn only on an engine's pixels.
MASKS_ONLY_WITH_ENGINE = ("Masks and boxes appear only when an engine draws the picture; "
                          "this one is the geometry preview, so it shows where the camera "
                          "and the aircraft are, with no mask or box on it.")

_ID_RE = re.compile(r"^[a-f0-9]{12}$")
_CASE_RE = re.compile(r"^[a-f0-9]{16}$")
_CAMERA_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_IMAGE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}\.png$")
IMAGE_KINDS = ("overlays", "previews", "frames")



def render_here(spec) -> Tuple[bool, str]:
    """Whether THIS machine can draw the spec's pixels, and why not when
    it cannot: the engine half AND an imported model for every airframe
    the scene draws. ``ue_available()`` alone is not the test -- it is
    true on every Mac by design (the sources build there), and a page
    that asked for ``--render`` on that alone sent the capture into its
    ``aircraft.mesh`` refusal on a machine with no model (measured: the
    macOS CI runner, every preview and campaign refused). The headless
    path is the honest fallback, and the sentence says which."""
    if not ue_available():
        return False, ("no engine on this machine: the geometry preview stands in "
                       "for the picture")
    names = [str(spec.aircraft.value)]
    for entry in getattr(spec, "traffic", None) or []:
        names.append(str(entry.aircraft.value))
    missing = [name for name in names if not is_imported(name)]
    if missing:
        return False, (f"the {', '.join(missing)} model is not imported on this "
                       f"machine, so nothing is rendered; the geometry preview "
                       f"stands in for the picture (scripts/import_aircraft.py "
                       f"{' '.join(missing)} imports it)")
    return True, "an engine and every airframe's model are present: the picture is rendered"


class GenerateRefusal(Exception):
    """A refusal the endpoint returns as a 409, already in words
    (:func:`words`); ``payload`` is the response body."""

    def __init__(self, payload: Dict[str, Any], status_code: int = 409):
        super().__init__(payload.get("sentence", "refused"))
        self.payload = payload
        self.status_code = status_code


# -- the catalogue, and only the catalogue ------------------------------------

def words(obj: Any, **extra: Any) -> Dict[str, Any]:
    """A refusal in words for the page: ``{"sentence", "hint",
    "details": {"rule", "message", ...}}``.

    The default fields (``sentence``, ``hint``) carry the catalogue's
    sentence and hint; the rule name and the producer's technical
    message are under ``details``, which the page shows only when the
    disclosure is opened. A rule with no catalogue entry gets the
    producer's own message as its sentence (the technical text is not
    a rule name) and ``details.catalogued: false`` so the gap is
    visible; nothing is invented.
    """
    explained = explain(obj, **extra)
    rule = explained.get("rule") or (name_of(obj) or "")
    message = technical(obj)
    if rule and is_catalogued(rule):
        sentence = explained["sentence"]        # the catalogue sentence, never the name
        hint = explained["hint"]
        catalogued = True
    else:
        sentence = message or "The request was refused."
        hint = ""
        catalogued = False
    details: Dict[str, Any] = {"rule": rule, "message": message, "catalogued": catalogued}
    if hasattr(obj, "detail") and isinstance(getattr(obj, "detail"), dict):
        details["detail"] = _jsonable(obj.detail)
    for key in ("actual", "limit", "unit"):
        value = getattr(obj, key, None) if not isinstance(obj, dict) else obj.get(key)
        if value is not None:
            details[key] = _jsonable(value)
    return {"sentence": sentence, "hint": hint, "details": details}


def state_words(name: str, **params: Any) -> str:
    """A progress state in the catalogue's words (``progress.*``)."""
    return explain(name, **params)["sentence"]


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


# -- compiling: the question round --------------------------------------------

def compile_round(prompt: str, tier: str = "llm", questions=None, answers=None
                  ) -> Dict[str, Any]:
    """The compilers' clarification protocol, exactly as ``/compile``
    runs it: the LLM tier when asked and available (falling back to
    the regex compiler with the reason recorded), else the regex
    compiler, whose questions are ``camera_questions``'s -- at most
    two: the aircraft (a kind of aircraft, or a name the vocabulary
    lacks) and the view (imagery with no view named). Returns
    ``{spec, questions, tier, model, note, note_details}``;
    ``questions`` is non-empty when the round wants an answer first.
    ``note`` is the fallback's catalogue sentence (``compile.*``: it
    already says the offline compiler was used), the producer's text
    under ``note_details`` -- never the two run together."""
    if tier not in ("llm", "regex"):
        raise CampaignError("campaign.arguments",
                            f"tier {tier!r} is not one of 'regex', 'llm'")
    model = note = note_details = None
    asked: List[Dict[str, Any]] = []
    tier_used = tier
    if tier == "llm":
        try:
            result = compile_prompt_llm(prompt, questions=questions, answers=answers)
            spec, model = result.spec, result.model
            asked = [dict(q) for q in result.questions]
        except LLMCompileError as exc:
            spec = compile_prompt(prompt, answers=answers)
            tier_used = "regex"
            said = words(exc)
            if not said["details"]["catalogued"]:
                # A nameless failure is the model's answer refused: the
                # catalogue's compile.rejected, the producer's text beside.
                said = words({"constraint": "compile.rejected", "message": str(exc)})
            note, note_details = said["sentence"], said["details"]
            asked = [] if answers else camera_questions(prompt)
    else:
        spec = compile_prompt(prompt, answers=answers)
        asked = [] if answers else camera_questions(prompt)
    return {"spec": spec, "questions": asked[:MAX_QUESTIONS], "tier": tier_used,
            "model": model, "note": note, "note_details": note_details}


# -- the plan preview in words ----------------------------------------------------

def _leaf_words(name: str, leaf: Any) -> str:
    pretty = name.replace("_", " ")
    for unit in ("km", "m", "deg", "kt"):
        if pretty.endswith(" " + unit):
            pretty = pretty[:-len(unit) - 1] + f" ({unit})"
    if isinstance(leaf, dict):
        if "choice" in leaf:
            options = ", ".join(str(v) for v in leaf["choice"])
            return f"{pretty} chosen among {options}"
        if "uniform" in leaf:
            lo, hi = leaf["uniform"][:2] if isinstance(leaf["uniform"], (list, tuple)) else ("?", "?")
            return f"{pretty} anywhere between {lo} and {hi}"
        if "lognormal" in leaf:
            median = (leaf["lognormal"] or {}).get("median") if isinstance(leaf["lognormal"], dict) else None
            return f"{pretty} spread around {median}" if median is not None else f"{pretty} spread"
        if "beta" in leaf:
            return f"{pretty} spread across its range"
        if "normal" in leaf:
            return f"{pretty} scattered around a typical value"
        for key in leaf:
            return f"{pretty} varied ({key})"
    return f"{pretty} fixed at {leaf}"


def paragraph(spec: ScenarioSpec, images: int, fmt: str) -> str:
    """One plain-language paragraph: airframes, places, conditions,
    viewpoints, count, format -- read off the compiled spec, with the
    policy's leaves in words. Says what is varied and what is fixed."""
    policy = (spec.randomization_policy.value
              if spec.randomization_policy is not None else None)
    policy = policy if isinstance(policy, dict) else {}
    aircraft = str(spec.aircraft.value)
    # Places, and the ground under the flight AS A HEADLESS CASE FLIES IT
    # (flightsim.capture with no terrain flag): the ridge
    # scene.terrain_source: synthesised states, the bake ``baked`` names,
    # else the flat slab at terrain_elevation -- a mountain word raises
    # that datum (the compiler's "mountainous terrain"), not the ground,
    # so the paragraph says no hills are in the pictures rather than
    # calling a 2000 m slab "sea level".
    drawn_place = isinstance(policy.get("location"), dict) and policy["location"].get("choice")
    terrain_source = str(spec.scene.terrain_source.value)
    datum = float(spec.terrain_elevation.value)
    if terrain_source == "synthesised":
        ground = "over a synthesised ridge (hills of prescribed shape, not a real place)"
    elif terrain_source == "baked":
        ground = "over the named terrain bake"
    elif drawn_place:
        ground = ("over flat ground raised to each drawn place's datum; "
                  "no hills or mountains are in the pictures")
    elif datum > 0:
        ground = (f"over flat ground raised to a {datum:g} m datum "
                  f"({spec.terrain_elevation.frm}); no hills or mountains are "
                  f"in the pictures")
    else:
        ground = "over flat ground at sea level"
    if drawn_place:
        places = (f"{ground}, at " + ", ".join(str(p) for p in policy["location"]["choice"])
                  + " (a place drawn per scenario)")
    elif str(spec.latitude.source) != "default" or str(spec.longitude.source) != "default":
        places = (f"{ground}, near {float(spec.latitude.value):.2f} N, "
                  f"{float(spec.longitude.value):.2f} E ({spec.latitude.frm})")
    else:
        places = f"{ground} (no place was named)"
    # Conditions.
    conditions: List[str] = []
    wind = float(spec.wind_speed.value)
    conditions.append(f"{wind:g} kt of wind from {float(spec.wind_direction.value):g} degrees"
                      if wind > 0 else "still air")
    turbulence = str(spec.turbulence.value)
    if turbulence != "none":
        conditions.append(f"{turbulence} turbulence")
    event = str(spec.weather_event.value)
    if event != "none":
        conditions.append(f"a {event}")
    if str(spec.weather_date.value) != "none":
        conditions.append(f"the weather of {spec.weather_date.value}")
    for name, leaf in policy.items():
        if name == "location":
            continue
        conditions.append(_leaf_words(name, leaf))
    block = spec.randomization
    if bool(block.enabled.value) and not policy:
        conditions.append("time of day and haze varied")
    # Viewpoints.
    if spec.cameras:
        presets = [str(c.preset.value) for c in spec.cameras]
        seen: List[str] = []
        for p in presets:
            if p not in seen:
                seen.append(p)
        views = ", ".join(seen) + (" views" if len(presets) > 1 else " view")
    else:
        views = "a chase view (the default when none is named)"
    duration = float(spec.duration.value)
    return (f"{images} {'image' if images == 1 else 'images'} of the {aircraft}, "
            f"{places}; conditions: {', '.join(conditions)}; "
            f"{views}; each scenario flies for {duration:g} s; "
            f"exported as {fmt.upper()}.")


# -- estimates --------------------------------------------------------------------

def estimate(spec: ScenarioSpec, images: int, measured: Optional[Dict[str, Any]] = None,
             workers: int = 1, directory: Optional[Path] = None) -> Dict[str, Any]:
    """Cases, disk and time for ``images`` frames. ``measured`` is a
    completed case's ``{frames, bytes, wall_seconds}`` (the preview, or
    the mean over completed cases); without it the frames per case are
    the recorder-cadence estimate and the projections are ``None`` --
    unmeasured is no claim."""
    frames_estimate = estimate_frames(spec)
    frames_measured = int(measured["frames"]) if measured and measured.get("frames") else None
    per_case = frames_measured or frames_estimate
    cases = int(math.ceil(images / per_case)) if per_case else None
    bytes_per_case = int(measured["bytes"]) if measured and measured.get("bytes") else None
    seconds_per_case = (float(measured["wall_seconds"])
                        if measured and measured.get("wall_seconds") else None)
    free = _free_bytes(Path(directory) if directory else DEFAULT_ROOT)
    projected_bytes = bytes_per_case * cases if (bytes_per_case and cases) else None
    projected_seconds = (seconds_per_case * cases / max(1, int(workers))
                         if (seconds_per_case and cases) else None)
    return {
        "frames_per_case": {"estimate": frames_estimate, "measured": frames_measured,
                            "basis": ("measured from a completed case" if frames_measured
                                      else "the recorder cadence (0.1 s); not measured yet")},
        "cases_needed": cases,
        "bytes_per_case": bytes_per_case,
        "seconds_per_case": seconds_per_case,
        "projected_bytes": projected_bytes,
        "projected_seconds": projected_seconds,
        "free_bytes": int(free),
        "within_free": (projected_bytes <= free) if projected_bytes is not None else None,
        "basis": ("measured from one sample case" if measured
                  else "not measured yet: the preview runs one case and measures it"),
    }


def _free_bytes(directory: Path) -> int:
    """Free space on the volume ``directory`` will live on (its nearest
    existing ancestor when it does not exist yet)."""
    probe = Path(directory)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return int(shutil.disk_usage(str(probe if probe.exists() else REPO)).free)


# -- the service ------------------------------------------------------------------

class GenerateService:
    """Campaign directories under ``root``, one worker thread per
    running campaign in this process. Every read goes to the files."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else DEFAULT_ROOT
        self.threads: Dict[str, threading.Thread] = {}
        self.errors: Dict[str, str] = {}
        self._lock = threading.Lock()

    # -- helpers ---------------------------------------------------------------

    def _dir(self, campaign_id: str) -> Path:
        if not _ID_RE.match(campaign_id or ""):
            raise GenerateRefusal({"error": "no such campaign"}, 404)
        return self.root / campaign_id

    def open(self, campaign_id: str) -> Campaign:
        directory = self._dir(campaign_id)
        if not (directory / "campaign.json").is_file():
            raise GenerateRefusal({"error": "no such campaign"}, 404)
        return Campaign.open(directory)

    def list_campaigns(self, limit: int = 100) -> Dict[str, Any]:
        """Every campaign under the root, newest first: its prompt, state
        (in words), target and images verified so far, format and times
        -- read from each campaign's own record and ledger, so a campaign
        started before a server restart (or from the command line into
        the same root) is listed and can be reopened."""
        rows = []
        if self.root.is_dir():
            for directory in self.root.iterdir():
                if not (directory / "campaign.json").is_file():
                    continue
                try:
                    campaign = Campaign.open(directory)
                    status = campaign.status()
                except Exception:          # one unreadable campaign hides no other
                    continue
                record = campaign.record
                state = str(status["state"])
                rows.append({
                    "id": record["id"], "prompt": record.get("prompt"),
                    "state": state,
                    "state_words": state_words(f"progress.campaign.{state}",
                                               done=status["frames_verified"],
                                               total=status["images_target"],
                                               drawn=False,
                                               frames_verified=status["frames_verified"],
                                               images_target=status["images_target"],
                                               cases_verified=int(
                                                   (status.get("cases") or {}).get(
                                                       "verified", 0))),
                    "images_target": status["images_target"],
                    "frames_verified": status["frames_verified"],
                    "fraction": status["fraction"],
                    "format": record.get("format"), "seed": record.get("seed"),
                    "created_utc": record.get("created_utc"),
                    "updated_utc": record.get("updated_utc"),
                    "running_here": self._running_id() == record["id"],
                    "can": {"pause": state == "running",
                            "resume": state in ("planned", "paused", "failed"),
                            "cancel": state not in ("done", "cancelled"),
                            "download": status["frames_verified"] > 0},
                })
        rows.sort(key=lambda r: str(r.get("updated_utc") or ""), reverse=True)
        return {"campaigns": rows[:limit], "total": len(rows), "root": str(self.root)}

    def _running_id(self) -> Optional[str]:
        with self._lock:
            for cid, thread in list(self.threads.items()):
                if thread.is_alive():
                    return cid
                self.threads.pop(cid, None)
        return None

    def _spawn(self, campaign: Campaign, workers: Optional[int], resume: bool) -> None:
        cid = campaign.record["id"]

        def body() -> None:
            try:
                if resume:
                    campaign.resume(workers=workers, capture_runner=CAPTURE_RUNNER)
                else:
                    campaign.run(workers=workers, capture_runner=CAPTURE_RUNNER)
            except CampaignError as exc:
                self.errors[cid] = f"{exc.constraint}: {exc.message}"
            except Exception as exc:                          # recorded, never lost
                self.errors[cid] = f"{type(exc).__name__}: {exc}"

        thread = threading.Thread(target=body, name=f"campaign-{cid}", daemon=True)
        with self._lock:
            self.threads[cid] = thread
        thread.start()

    def wait(self, campaign_id: str, timeout: float = 60.0) -> None:
        """Join the campaign's thread (tests)."""
        thread = self.threads.get(campaign_id)
        if thread is not None:
            thread.join(timeout)

    # -- ask / clarify / preview ------------------------------------------------

    def plan(self, prompt: str, answers=None, questions=None,
             images: Optional[int] = None, fmt: str = DEFAULT_FORMAT, tier: str = "llm",
             seed: Optional[int] = None) -> Dict[str, Any]:
        """Prompt -> questions (clarify) or the plan preview: the
        paragraph, the refusals in words, the estimate, the expert
        commands. Nothing is written.

        ``images`` None (the page's count left blank) takes the count
        the prompt states, every view's added (``Campaign.create``'s own
        rule, :func:`core.campaign.campaign.reconcile_images`), else
        ``DEFAULT_IMAGES``; a stated count and an ``images`` that
        disagree are a refusal in the preview (``campaign.image_count``),
        exactly the one ``start`` would raise. ``images`` in the reply
        is the target the campaign would run to; ``images_stated`` the
        prompt's own count, or None.

        ``llm_used`` says whether the language model compiled THIS plan
        (the tier that answered), not whether one is configured -- a
        configured but unreachable model is not available to anyone."""
        prompt = str(prompt or "").strip()
        if not prompt:
            raise GenerateRefusal({"error": "empty prompt"}, 400)
        explicit = _images_arg(images)
        if fmt not in FORMATS and fmt != ALL_FORMATS:
            raise GenerateRefusal(words(ExportError(
                "export.format", f"format {fmt!r} is not one of {list(FORMATS)}")))
        compiled = compile_round(prompt, tier=tier, questions=questions, answers=answers)
        base = {"prompt": prompt, "answers": [dict(a) for a in (answers or [])],
                "tier": compiled["tier"], "model": compiled["model"],
                "note": compiled["note"], "note_details": compiled["note_details"],
                "llm_used": compiled["tier"] == "llm",
                "images": explicit, "images_given": explicit, "format": fmt}
        if compiled["questions"]:
            return {**base, "state": "clarify",
                    "headline": state_words("progress.page.clarify"),
                    "questions": compiled["questions"],
                    "expert": [expert_campaign(prompt, explicit, fmt, seed, answers=answers,
                                               tier=compiled["tier"], plan=True)]}
        spec: ScenarioSpec = compiled["spec"]
        refusals = plan_refusals(spec)
        stated = stated_images(spec)
        try:
            images = reconcile_images(spec, explicit, DEFAULT_IMAGES)
        except CampaignError as exc:
            refusals.append(words(exc))
            images = int(explicit)
        # The estimate counts what the campaign will fly: a stated count is
        # the dataset's size, so each case captures at its default cadence.
        flown = ScenarioSpec.from_dict(spec.to_dict())
        if stated is not None:
            release_stated_counts(flown, stated)
        est = estimate(flown, images, None, directory=self.root)
        return {**base, "state": "preview",
                "headline": state_words("progress.page.preview"),
                "images": images,
                "images_stated": stated["total"] if stated else None,
                "paragraph": paragraph(spec, images, fmt),
                "refusals": refusals,
                "ok": not refusals,
                "estimate": est,
                "spec": spec.to_dict(), "spec_digest": spec.digest(),
                "expert": [expert_campaign(prompt, explicit, fmt, seed, answers=answers,
                                           tier=compiled["tier"], plan=True)]}

    def preview(self, spec_dict: Dict[str, Any], images: Optional[int] = None,
                seed: int = 1, workers: int = 1) -> Dict[str, Any]:
        """ONE sample case (slot 0 of the campaign this spec would
        start) run headless through the campaign's own worker function
        with ``--max-previews 1`` -- and ``--render`` when an engine is
        present, in which case the overlay PNG (mask and box drawn on
        the pixels) is the picture; otherwise the geometry preview is,
        and the response says which. The case is measured (frames,
        bytes, seconds) and the estimate is recomputed from it.

        Masks and boxes are drawn only on an engine's pixels: when the
        picture is the geometry preview, ``masks_note`` says so in
        plain words (and None when the overlay is the picture), so the
        page never lets a shaded preview pass for a labelled frame."""
        try:
            spec = ScenarioSpec.from_dict(spec_dict)
        except (ValueError, KeyError) as exc:
            # By name where the catalogue knows the sentence (spec.version);
            # the producer's text under details otherwise, never a traceback.
            raise GenerateRefusal(words(exc), 400)
        refusals = plan_refusals(spec)
        try:
            images = reconcile_images(spec, _images_arg(images), DEFAULT_IMAGES)
        except CampaignError as exc:
            refusals.append(words(exc))
        if refusals:
            raise GenerateRefusal({**refusals[0], "refusals": refusals})
        stated = stated_images(spec)
        if stated is not None:      # the sample is one case of the campaign
            release_stated_counts(spec, stated)
        engine, render_note = render_here(spec)
        record = {"spec": spec.to_dict(), "seed": int(seed),
                  "capture": {"max_previews": 1, "card": True, **({"render": True} if engine else {})}}
        preview_id = uuid.uuid4().hex[:12]
        out = self.root / "previews" / preview_id
        out.mkdir(parents=True, exist_ok=True)
        row = run_index(0, record, str(out), attempt=1, stall_seconds=None,
                        capture_runner=CAPTURE_RUNNER)
        if row.get("status") == STATUS_REFUSED:
            raise GenerateRefusal(words(RandomizationError(
                str((row.get("refusals") or ["randomization.infeasible"])[0]),
                str(row.get("reason") or ""))))
        run_dir = Path(row["run_dir"])
        if not row.get("ok"):
            # The capture CLI refused (by name, in its log) or failed: the
            # names it printed, in words; the log's last words otherwise.
            refusals = capture_refusals(run_dir / "capture.log")
            if not refusals:
                refusals = [{"sentence": "The sample scenario could not be flown.",
                             "hint": "", "details": {"rule": "", "catalogued": False,
                                                     "message": str(row.get("reason") or ""),
                                                     "log_tail": log_tail(run_dir / "capture.log")}}]
            raise GenerateRefusal({**refusals[0], "refusals": refusals,
                                   "preview_id": preview_id, "case_id": row.get("case_id"),
                                   "expert": [" ".join(str(part) for part in (row.get("command") or []))]})
        picture = first_picture(run_dir)
        measured = {"frames": row.get("frames"), "bytes": row.get("bytes"),
                    "wall_seconds": row.get("wall_seconds")} if row.get("ok") else None
        verification = row.get("verification")
        return {
            "state": "preview",
            "headline": state_words("progress.page.preview"),
            "preview_id": preview_id,
            "case_id": row.get("case_id"),
            "ok": bool(row.get("ok")),
            "status": row.get("status"),
            "status_words": state_words(f"progress.case.{row.get('status')}"),
            "reason": row.get("reason"),
            "engine": engine,
            "render_note": render_note,
            "drawn": bool(row.get("drawn")),
            "picture": ({"kind": picture["kind"], "camera_id": picture["camera_id"],
                         "name": picture["name"],
                         "url": f"/generate/preview/{preview_id}/{picture['kind']}/"
                                f"{picture['camera_id']}/{picture['name']}",
                         "what": ("the rendered frame with the mask and box drawn on it"
                                  if picture["kind"] == "overlays" else
                                  "the geometry preview: the camera's view of the recorded "
                                  "flight, shaded from the scenario"),
                         "masks_note": (None if picture["kind"] == "overlays"
                                        else MASKS_ONLY_WITH_ENGINE)}
                        if picture else None),
            "masks_note": (None if picture and picture["kind"] == "overlays"
                           else MASKS_ONLY_WITH_ENGINE),
            "measured": measured,
            "verification": verification,
            "verification_words": ({"passed": verification.get("passed"),
                                    "failed": verification.get("failed"),
                                    "not_run": verification.get("not_run"),
                                    "verdict": state_words(
                                        "verdict.pass" if verification.get("ok") else "verdict.fail")}
                                   if isinstance(verification, dict) else None),
            "estimate": estimate(spec, images, measured, workers=workers, directory=self.root),
            "sampled": row.get("sampled") or {},
            "expert": [" ".join(str(part) for part in (row.get("command") or []))],
        }

    def preview_image(self, preview_id: str, kind: str, camera_id: str, name: str) -> Path:
        if not _ID_RE.match(preview_id or ""):
            raise GenerateRefusal({"error": "no such image"}, 404)
        return _guarded_image(self.root / "previews" / preview_id / RUNS_DIR, None,
                              kind, camera_id, name)

    # -- generate -----------------------------------------------------------------

    def start(self, prompt: str, answers=None, images: Optional[int] = None,
              fmt: str = DEFAULT_FORMAT, seed: Optional[int] = None, workers: int = 1,
              tier: str = "regex", plan_digest: Optional[str] = None,
              disk_budget_bytes: Optional[int] = None) -> Dict[str, Any]:
        """Create the campaign (``Campaign.create``: compiles, refuses
        by name -- ``campaign.image_count`` among them, when the page's
        count and the prompt's disagree) and run it in a thread. One
        running campaign per server process. ``images`` None takes the
        prompt's stated count, else ``DEFAULT_IMAGES``."""
        prompt = str(prompt or "").strip()
        if not prompt:
            raise GenerateRefusal({"error": "empty prompt"}, 400)
        images = _images_arg(images)
        running = self._running_id()
        if running is not None:
            raise GenerateRefusal(words(CampaignError(
                "campaign.state",
                f"campaign {running} is still running in this server; pause or cancel "
                f"it before starting another")))
        # Rendering is decided once the prompt has compiled (the airframe
        # is known then): render_here() below, never ue_available() alone.
        capture = {"max_previews": 1, "card": True}
        campaign_id = uuid.uuid4().hex[:12]
        try:
            campaign = Campaign.create(
                prompt, answers=answers, images=images, seed=seed,
                out=self.root / campaign_id, format=fmt, workers=workers,
                disk_budget_bytes=disk_budget_bytes,
                tier=tier if tier in ("llm", "regex") else "regex",
                capture=capture)
            render, render_note = render_here(campaign._spec())
            if render:
                campaign.record["capture"]["render"] = True
                campaign._save()
            plan = campaign.plan()          # refuses by name before a worker starts
        except CampaignError as exc:
            raise GenerateRefusal(words(exc))
        self._spawn(campaign, workers, resume=False)
        digest = campaign.record["spec_digest"]
        return {"id": campaign_id, "state": RUNNING,
                "headline": state_words("progress.page.generate"),
                "spec_digest": digest, "plan_digest": plan_digest,
                "recompiled": bool(plan_digest and plan_digest != digest),
                "tier": campaign.record["tier"], "plan": plan,
                "render": render, "render_note": render_note,
                "images": campaign.target,
                "directory": str(campaign.dir),
                "expert": [expert_campaign(prompt, images, fmt, seed, answers=answers,
                                           tier=tier, out=campaign.dir, workers=workers)]}

    def control(self, campaign_id: str, request: str) -> Dict[str, Any]:
        campaign = self.open(campaign_id)
        try:
            if request == "pause":
                campaign.pause()
            elif request == "cancel":
                campaign.cancel()
            elif request == "resume":
                running = self._running_id()
                if running is not None:
                    raise CampaignError("campaign.state",
                                        f"campaign {running} is still running in this "
                                        f"server; wait for it to pause or finish")
                campaign._reload()
                if campaign.state not in (PLANNED, PAUSED, FAILED):
                    raise CampaignError("campaign.state",
                                        f"a {campaign.state} campaign cannot resume "
                                        f"(planned, paused or failed can)")
                self._spawn(campaign, None, resume=True)
            else:
                raise GenerateRefusal({"error": f"no such control {request!r}"}, 404)
        except CampaignError as exc:
            raise GenerateRefusal(words(exc))
        return {**self.progress(campaign_id), "requested": request,
                "expert": [f"python -m flightsim.campaign --out {campaign.dir} --{request}"]}

    # -- reading ----------------------------------------------------------------

    def progress(self, campaign_id: str) -> Dict[str, Any]:
        """Progress in human terms FROM THE LEDGER: images so far, what
        is varying (histograms of the realised draws), refused and why
        (catalogue sentences), the time estimate from the measured
        per-case cost. Nothing from memory: the record is re-read and
        the ledger re-summarised on every call."""
        campaign = self.open(campaign_id)
        campaign._reload()
        rows = campaign.ledger.rows()        # the ledger file, never a counter
        return progress_from(campaign.record, rows, campaign.dir,
                             thread_error=self.errors.get(campaign_id))

    def events(self, campaign_id: str, interval: float = 1.0,
               limit: Optional[int] = None) -> Iterator[str]:
        """Server-sent events: one ``progress`` event now, then one
        whenever the ledger or the record changes (polled every
        ``interval`` s), a final one on a terminal state; ``limit``
        caps the count (the plain-polling fallback is GET /generate/{id})."""
        sent = 0
        last = None
        while True:
            payload = self.progress(campaign_id)
            key = json.dumps({k: payload.get(k) for k in ("state", "frames_verified",
                                                           "frames_captured", "cases",
                                                           "indices", "reason")},
                             sort_keys=True, default=str)
            if key != last or sent == 0:
                last = key
                sent += 1
                yield f"event: progress\ndata: {json.dumps(payload, default=str)}\n\n"
            if payload["state"] in TERMINAL or (limit is not None and sent >= limit):
                yield f"event: end\ndata: {json.dumps({'state': payload['state']})}\n\n"
                return
            if payload["state"] != RUNNING and self._running_id() != campaign_id:
                # Nothing will change until someone resumes: say so and stop;
                # the page reconnects on resume.
                yield f"event: idle\ndata: {json.dumps({'state': payload['state']})}\n\n"
                return
            time.sleep(interval)

    def frames(self, campaign_id: str) -> Dict[str, Any]:
        """The gallery: every captured case's pictures, read off the
        run directories (overlays when pixels were drawn, geometry
        previews otherwise), each beside its case's draw and verdict."""
        campaign = self.open(campaign_id)
        rows = campaign.ledger.rows()
        latest = latest_by_index(rows)
        items: List[Dict[str, Any]] = []
        for index in sorted(latest):
            row = latest[index]
            if not row.get("run_dir") or not row.get("case_id"):
                continue
            run_dir = Path(row["run_dir"])
            if not run_dir.is_dir():
                continue
            views = camera_views(run_dir)
            for picture in pictures(run_dir, per_camera=1):
                items.append({
                    "camera_words": views.get(picture["camera_id"])
                                    or _camera_id_words(picture["camera_id"]),
                    "index": index, "case_id": row["case_id"],
                    "status": row.get("status"),
                    "status_words": state_words(f"progress.case.{row.get('status')}"),
                    "verified": bool(row.get("verified")),
                    "verification": row.get("verification"),
                    "sampled": row.get("sampled") or {},
                    "seed": row.get("seed"),
                    "kind": picture["kind"], "camera_id": picture["camera_id"],
                    "name": picture["name"],
                    "url": (f"/generate/{campaign_id}/frames/{row['case_id']}/"
                            f"{picture['kind']}/{picture['camera_id']}/{picture['name']}"),
                })
                if len(items) >= MAX_GALLERY:
                    break
            if len(items) >= MAX_GALLERY:
                break
        drawn = any(r.get("drawn") for r in latest.values())
        return {"id": campaign_id, "items": items, "drawn": drawn,
                "headline": state_words("progress.page.review"),
                "what": ("rendered frames with the recorded geometry drawn on them" if drawn
                         else "geometry previews (no engine drew pixels on this machine)"),
                "expert": [f"python -m flightsim.campaign --out {campaign.dir} --report",
                           f"python -m flightsim.verify {campaign.dir / RUNS_DIR}/<case_id>"]}

    def frame_image(self, campaign_id: str, case_id: str, kind: str, camera_id: str,
                    name: str) -> Path:
        directory = self._dir(campaign_id)
        if not _CASE_RE.match(case_id or ""):
            raise GenerateRefusal({"error": "no such image"}, 404)
        return _guarded_image(directory / RUNS_DIR, case_id, kind, camera_id, name)

    def download(self, campaign_id: str, fmt: Optional[str] = None) -> Dict[str, Any]:
        """Export the verified cases as ``fmt`` (the campaign's own
        format when none is given) through ``Campaign.export`` and zip
        the dataset with its card (``dataset.json`` records the format).
        The export's refusals stand, in words."""
        campaign, fmt, result, card = self._export(campaign_id, fmt)
        dataset = Path(result["dataset_path"])
        downloads = campaign.dir / "downloads"
        downloads.mkdir(exist_ok=True)
        archive = downloads / f"{campaign_id}_{fmt}.zip"
        pictures_in = 0
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(p for p in dataset.rglob("*") if p.is_file()):
                zf.write(path, arcname=str(Path(fmt) / path.relative_to(dataset)))
                pictures_in += path.suffix.lower() in PICTURE_SUFFIXES
        # Labels only when the export says so OR the zip holds no picture
        # at all -- what the person receives, not only what was asked.
        labels_only = bool(result["labels_only"]) or pictures_in == 0
        return {"archive": archive, "format": fmt, "card": card,
                "filename": f"{campaign_id}_{fmt}.zip", "runs": result["runs"],
                "labels_only": labels_only, "pictures": pictures_in,
                "labels_only_words": LABELS_ONLY_WORDS if labels_only else None,
                "expert": [f"python -m flightsim.export {campaign.dir / RUNS_DIR}/* "
                           f"--out {dataset} --format {fmt}"]}

    def card(self, campaign_id: str, fmt: Optional[str] = None) -> Dict[str, Any]:
        """The dataset's card, read for a person before the download:
        the same export the download zips (``Campaign.export`` into
        ``datasets/<fmt>``), its ``dataset.json`` put into plain words
        by :func:`card_words`. The export's refusals stand, in words."""
        campaign, fmt, result, card = self._export(campaign_id, fmt)
        # The download's own rule: labels only when the export says so or
        # no picture file is in what the zip would hold.
        pictured = any(p.suffix.lower() in PICTURE_SUFFIXES
                       for p in Path(result["dataset_path"]).rglob("*") if p.is_file())
        said = card_words(card, labels_only=bool(result["labels_only"]) or not pictured)
        return {"id": campaign_id, **said,
                "expert": [f"python -m flightsim.campaign --out {campaign.dir} --export",
                           f"cat {Path(result['dataset_path']) / CARD_JSON}"]}

    def export_result(self, campaign_id: str, fmt: Optional[str] = None) -> Dict[str, Any]:
        """The campaign exported in ``fmt`` (as the download does); its
        result, for the card page."""
        return self._export(campaign_id, fmt)[2]

    def _export(self, campaign_id: str, fmt: Optional[str]
                ) -> Tuple[Campaign, str, Dict[str, Any], Dict[str, Any]]:
        """Export the verified cases as ``fmt`` (the campaign's own
        format when none is given); the card read back off the file."""
        campaign = self.open(campaign_id)
        fmt = fmt or str(campaign.record.get("format") or DEFAULT_FORMAT)
        if fmt not in FORMATS and fmt != ALL_FORMATS:
            raise GenerateRefusal(words(ExportError(
                "export.format", f"format {fmt!r} is not one of {list(FORMATS)}")))
        try:
            # The format the person picked on the page, recorded in the
            # card's choices with where it was picked.
            result = campaign.export(format=fmt, choices={
                "chosen_on": "the web app's Generate a dataset page (download)",
                "campaign_format": campaign.record.get("format")})
        except (ExportError, CampaignError) as exc:
            raise GenerateRefusal(words(exc))
        card_path = Path(result["dataset_path"]) / CARD_JSON
        card = json.loads(card_path.read_text(encoding="utf-8")) if card_path.is_file() else {}
        return campaign, fmt, result, card


# -- the card in words ----------------------------------------------------------------

#: Picture files a dataset zip can hold (the export copies PNGs; VOC
#: names the directory JPEGImages and keeps the PNGs as they are).
PICTURE_SUFFIXES = (".png", ".jpg", ".jpeg")
#: Each format in a person's words: what the files are, not the layout spec.
FORMAT_WORDS = {
    "coco": "COCO: one file of labels for each part of the dataset (training, "
            "validation, testing), a box and an outline for each aircraft",
    "yolo": "YOLO: one small text file of boxes beside each picture, ready for "
            "Ultralytics",
    "voc": "Pascal VOC: one file of boxes for each picture",
    "kitti": "KITTI: one text file for each picture, with boxes in the picture and "
             "in 3-D",
    "webdataset": "WebDataset: the samples packed into archive shards for streaming",
}
#: One download holding every format, each in its own folder.
ALL_FORMATS = "all"
FORMAT_WORDS[ALL_FORMATS] = ("All five formats: COCO, KITTI, WebDataset, YOLO and Pascal "
                             "VOC, each in its own folder")
FORMAT_WORDS[",".join(FORMATS)] = FORMAT_WORDS[ALL_FORMATS]
SPLIT_WORDS = {"train": "training", "val": "validation", "test": "testing"}
#: Conditions the card records that are bookkeeping, not a condition a
#: person asked for (the seed, the solar algorithm's citation, the same
#: hour in UTC, the engine's own copy of the sun): in the details only.
CARD_BOOKKEEPING = ("seed", "solar_source", "hour_utc")
CARD_BOOKKEEPING_PREFIXES = ("engine_",)
#: Plain names for the conditions a campaign varies most; any other
#: name is read as words with its unit (``_leaf_words``' rule).
CONDITION_WORDS = {
    "cloud_cover": ("cloud cover (share of the sky)", lambda v: f"{100 * v:.0f}%"),
    "hour_local": ("time of day", lambda v: f"{int(v):02d}:{int(round((v % 1) * 60)) % 60:02d}"),
    "day_of_year": ("day of the year", lambda v: f"{v:.0f}"),
    "visibility_km": ("visibility", lambda v: f"{v:.0f} km"),
    "sun_elevation_deg": ("the sun's height", lambda v: f"{v:.0f} degrees"),
    "sun_azimuth_deg": ("the sun's direction", lambda v: f"{v:.0f} degrees"),
    "wind_speed": ("wind", lambda v: f"{v:g} kt"),
    "year": ("year", lambda v: f"{v:.0f}"),
}


def _condition_name(name: str) -> str:
    pretty = name.replace("_", " ")
    for unit in ("km", "m", "deg", "kt"):
        if pretty.endswith(" " + unit):
            pretty = pretty[:-len(unit) - 1] + f" ({unit})"
    return pretty


def card_words(card: Dict[str, Any], labels_only: Optional[bool] = None) -> Dict[str, Any]:
    """A dataset card (``dataset.json``) in a person's words -- pure, so
    a test can hand it any card. The default fields hold sentences
    only: how many images and labelled objects, the balance of
    classes, the conditions the scenarios actually drew, the checks
    and their verdicts, what the dataset does NOT claim, and the format.
    Every rule name, check name and the card's own technical lines go
    under ``details`` (the page's disclosure), never into a sentence.

    ``labels_only`` (the export's own flag; the card's when None) adds
    :data:`LABELS_ONLY_WORDS` first under ``not_claimed`` and as
    ``labels_only_words``."""
    if labels_only is None:
        labels_only = bool(card.get("labels_only"))
    images = int(card.get("images") or card.get("frames") or 0)
    instances = int(card.get("instances") or 0)
    fmt = str(card.get("format") or "")
    runs = [r for r in card.get("runs") or [] if isinstance(r, dict)]
    scenarios = len(runs)
    # Contents and the split.
    contents = [f"{images} {'image' if images == 1 else 'images'} with {instances} "
                f"labelled {'object' if instances == 1 else 'objects'}, from {scenarios} "
                f"{'scenario' if scenarios == 1 else 'scenarios'} flown."]
    splits = card.get("frames_per_split") or {}
    if splits:
        contents.append("Split for "
                        + ", ".join(f"{SPLIT_WORDS.get(k, k)} {v}" for k, v in splits.items())
                        + "; every image of one flight stays in the same part.")
    # The balance of classes: the classes with something in them, and
    # the ones the class list carries with nothing.
    balance = card.get("class_balance") or {}
    present = [(name, c) for name, c in balance.items()
               if isinstance(c, dict) and int(c.get("instances") or 0) > 0]
    empty = [name for name, c in balance.items()
             if isinstance(c, dict) and not int(c.get("instances") or 0)]
    classes = [f"{name}: {int(c['instances'])} labelled "
               f"{'object' if int(c['instances']) == 1 else 'objects'} in "
               f"{int(c.get('images') or 0)} {'image' if int(c.get('images') or 0) == 1 else 'images'}"
               + (f" ({round(100 * int(c['instances']) / instances)}% of all objects)"
                  if instances and len(present) > 1 else "") + "."
               for name, c in present]
    if empty:
        classes.append(f"In the class list but not in any image: {', '.join(empty)}.")
    aircraft = card.get("aircraft") or []
    if aircraft:
        classes.append(f"Aircraft models: {', '.join(str(a) for a in aircraft)}.")
    # The conditions the scenarios drew (the card's ``conditions.sampled``).
    sampled = ((card.get("conditions") or {}).get("sampled") or {})
    conditions: List[str] = []
    for name, summary in sampled.items():
        if name in CARD_BOOKKEEPING or name.startswith(CARD_BOOKKEEPING_PREFIXES):
            continue
        label, fmt_value = CONDITION_WORDS.get(name, (_condition_name(name), None))
        if isinstance(summary, dict) and "min" in summary and "max" in summary:
            lo, hi = float(summary["min"]), float(summary["max"])
            show = fmt_value or (lambda v: f"{v:.3g}")
            n = int(summary.get("n") or 0)
            if lo == hi:
                conditions.append(f"{label.capitalize()}: {show(lo)} in every scenario.")
            else:
                conditions.append(f"{label.capitalize()}: from {show(lo)} to {show(hi)} "
                                  f"across {n} {'scenario' if n == 1 else 'scenarios'}.")
        elif isinstance(summary, dict) and summary:
            counts = ", ".join(f"{value} in {count} {'scenario' if count == 1 else 'scenarios'}"
                               for value, count in summary.items())
            conditions.append(f"{label.capitalize()}: {counts}.")
    if not conditions:
        conditions.append("Nothing was varied between the scenarios.")
    # The checks.
    passed_runs = [r for r in runs if (r.get("verification") or {}).get("ok")]
    checks: List[str] = []
    if scenarios:
        if len(passed_runs) == scenarios:
            checks.append(f"{'The scenario' if scenarios == 1 else f'All {scenarios} scenarios'} "
                          f"passed every check that ran.")
        else:
            checks.append(f"{len(passed_runs)} of {scenarios} scenarios passed every check "
                          f"that ran; the others had a failed check.")
        passed = sum(int((r.get("verification") or {}).get("passed") or 0) for r in runs)
        failed = sum(int((r.get("verification") or {}).get("failed") or 0) for r in runs)
        not_run = max((int((r.get("verification") or {}).get("not_run") or 0) for r in runs),
                      default=0)
        checks.append(f"{passed} {'check' if passed == 1 else 'checks'} passed and {failed} "
                      f"failed in all.")
        if not_run:
            checks.append(f"Up to {not_run} {'check' if not_run == 1 else 'checks'} per scenario "
                          f"could not run on this machine (most need an engine's pictures), "
                          f"so what they would check is not claimed.")
        unbound = [r for r in runs if r.get("verification_bound_to_manifest") is False]
        if unbound:
            checks.append(f"{len(unbound)} {'scenario' if len(unbound) == 1 else 'scenarios'} "
                          f"carry a verdict that does not say which recording it checked.")
    else:
        checks.append("No checked scenario is in this dataset.")
    # What it does not claim, in words; the card's own lines under details.
    not_claimed: List[str] = []
    if labels_only:
        not_claimed.append(LABELS_ONLY_WORDS)
        not_claimed.append("The labels say where each aircraft is in each view, worked out "
                           "from the recorded flight, not read off a picture.")
    if any(not r.get("render") for r in runs) and not labels_only:
        not_claimed.append("Some scenarios were not drawn by an engine; their labels come "
                           "from the recorded flight alone.")
    not_claimed.append("Drawing the same scenario twice has not been shown to give the "
                       "same picture.")
    not_claimed.append("Sun, fog and exposure are not calibrated against a real camera.")
    extent = card.get("not_claimed_extent_px")
    if extent:
        not_claimed.append(f"Objects smaller than {extent} pixels across are labelled, but "
                           f"their labels are not claimed accurate.")
    not_claimed.append("The label files have been read back by independent readers, not "
                       "used to train a model.")
    if card.get("licence_gate"):
        not_claimed.append("The licences listed are the assets' own records, not legal advice.")
    format_words = FORMAT_WORDS.get(fmt, fmt.upper() if fmt else "")
    return {
        "format": fmt, "format_words": format_words,
        "images": images, "instances": instances, "scenarios": scenarios,
        "labels_only": bool(labels_only),
        "labels_only_words": LABELS_ONLY_WORDS if labels_only else None,
        "verified": bool(scenarios) and len(passed_runs) == scenarios,
        "contents": contents, "classes": classes, "conditions": conditions,
        "checks": checks, "not_claimed": not_claimed,
        # What the exported frames actually hold, beside what was asked
        # (core/dataset/realised.py) -- the request alone is not the dataset.
        "variety": {"headline": (card.get("realised_words") or {}).get("headline"),
                    "lines": [item["sentence"] for item in
                              (card.get("realised_words") or {}).get("fields") or []],
                    "narrow": (card.get("realised_words") or {}).get("narrow") or []},
        "files": (f"The zip holds the dataset laid out as {format_words.split(':')[0]}, "
                  f"beside its card: a page to read and the same facts as data."),
        "details": {
            "not_claimed": [str(line) for line in card.get("not_claimed") or []],
            "checks_not_run": sorted({str(name) for r in runs for name in r.get("not_run") or []}),
            "conditions": sampled,
            "class_order": card.get("class_order"),
            "card_files": [CARD_JSON, "DATASET_CARD.md", "DATASET_CARD.html"],
        },
    }


# -- pure helpers ------------------------------------------------------------------

def _images_arg(value: Any) -> Optional[int]:
    """The page's image count: None when left blank (the prompt's
    stated count, else the default, decides), else a whole number of at
    least 1 -- anything else refused ``campaign.arguments`` in words."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    if isinstance(value, bool) or number < 1:
        raise GenerateRefusal(words(CampaignError(
            "campaign.arguments", f"images must be a whole number of at least 1, got {value!r}")))
    return number


def plan_refusals(spec: ScenarioSpec) -> List[Dict[str, Any]]:
    """Every refusal the campaign's own plan would raise, each in
    words: the validator's violations and the sampler's policy defects
    (an exhausted slot is not a defect; ``Campaign.plan`` says the same)."""
    out: List[Dict[str, Any]] = []
    report = validate(spec)
    for violation in report.violations:
        out.append(words(violation))
    probe = deepcopy(spec)
    try:
        sample_randomization(probe, draw_index=0)
    except RandomizationError as exc:
        said = words(exc)
        # The validator now runs the sampler's own policy checks (shape
        # and gates), so the probe's refusal can be one already listed:
        # said once, not twice.
        if exc.constraint != "randomization.infeasible" and not any(
                (r["details"].get("rule"), r["details"].get("message"))
                == (said["details"]["rule"], said["details"]["message"]) for r in out):
            out.append(said)
    return out


def expert_campaign(prompt: str, images: Optional[int], fmt: str, seed: Optional[int],
                    answers=None, tier: str = "regex", plan: bool = False, out: Any = None,
                    workers: int = 1) -> str:
    quoted = json.dumps(prompt)
    # No --images when none was given: the CLI then takes the prompt's
    # stated count (or its default), exactly as the page does.
    parts = [f"python -m flightsim.campaign {quoted}"
             + (f" --images {int(images)}" if images is not None else ""),
             f"--out {out if out else 'campaigns/<name>'}", f"--format {fmt}"]
    if seed is not None:
        parts.append(f"--seed {int(seed)}")
    if workers and int(workers) > 1:
        parts.append(f"--workers {int(workers)}")
    if tier == "llm":
        parts.append("--tier llm")
    for answer in answers or []:
        if isinstance(answer, dict) and answer.get("id"):
            parts.append(f"--answer {json.dumps(str(answer['id']) + '=' + str(answer.get('answer', '')))}")
    if plan:
        parts.append("--plan")
    return " ".join(parts)


def pictures(run_dir: Path, per_camera: int = 1) -> List[Dict[str, str]]:
    """The pictures a run directory holds, read off the directories:
    overlays first (pixels with geometry drawn), else previews, else
    bare frames; at most ``per_camera`` per camera."""
    run_dir = Path(run_dir)
    for kind in IMAGE_KINDS:
        root = run_dir / kind
        if not root.is_dir():
            continue
        found: List[Dict[str, str]] = []
        for camera_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            names = sorted(p.name for p in camera_dir.glob("*.png")
                           if _IMAGE_RE.match(p.name))
            if kind == "frames":
                names = [n for n in names if re.match(r"^frame_\d{4}\.png$", n)]
            for name in names[:per_camera]:
                found.append({"kind": kind, "camera_id": camera_dir.name, "name": name})
        if found:
            return found
    return []


def first_picture(run_dir: Path) -> Optional[Dict[str, str]]:
    found = pictures(run_dir, per_camera=1)
    return found[0] if found else None


def _guarded_image(root: Path, case_id: Optional[str], kind: str, camera_id: str,
                   name: str) -> Path:
    """The image route's discipline: a fixed kind, matched names and
    ``resolve().relative_to`` the run root, so nothing climbs out."""
    if kind not in IMAGE_KINDS or not _IMAGE_RE.match(name or "") or not _CAMERA_RE.match(camera_id or ""):
        raise GenerateRefusal({"error": "no such image"}, 404)
    try:
        base = root.resolve()
        run_root = base if case_id is None else (base / case_id)
        if case_id is None:
            # A preview holds one run under runs/<case_id>; find it.
            candidates = [p for p in base.iterdir() if p.is_dir()] if base.is_dir() else []
            if len(candidates) != 1:
                raise GenerateRefusal({"error": "no such image"}, 404)
            run_root = candidates[0]
        resolved = (run_root / kind / camera_id / name).resolve()
        resolved.relative_to(base)
    except (OSError, ValueError):
        raise GenerateRefusal({"error": "no such image"}, 404)
    if not resolved.is_file():
        raise GenerateRefusal({"error": "no such image"}, 404)
    return resolved


#: The capture CLI's refusal lines: ``REFUSED -- <name>: ...`` (the name
#: dotted, or bare as the catalogue spells ``trim``) and the validator's
#: ``[<name>] message`` rows under ``REFUSED -- by name:``. Whether the
#: head IS a name is the catalogue's question (``is_catalogued``), not
#: the regex's shape; a line that names no rule (``REFUSED -- <exception
#: text>``) is read by its sentence where the catalogue recognises one.
_LOG_REFUSED = re.compile(r"^REFUSED\s*--\s*([a-z_]+(?:\.[a-z_]+)*)\s*:\s*(.*)$")
_LOG_BRACKET = re.compile(r"^\s*\[([a-z_]+(?:\.[a-z_]+)*)\]\s*(.*)$")
_LOG_NAMELESS = re.compile(r"^REFUSED\s*--\s*(.+)$")
_LOG_NUMBERS = re.compile(r"\(requested\s+(-?[0-9.]+)\s*([^,]*),\s*limit\s+(-?[0-9.]+)\s*([^)]*)\)\s*$")


def capture_refusals(log: Path) -> List[Dict[str, Any]]:
    """The refusals a ``flightsim.capture`` log names, each in words
    (the CLI prints ``REFUSED -- <name>: ...`` or ``[<name>] message
    (requested X unit, limit Y unit)``); [] when it names none."""
    try:
        text = Path(log).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for line in text.splitlines():
        match = _LOG_REFUSED.match(line.strip()) or _LOG_BRACKET.match(line)
        if match and (is_catalogued(match.group(1)) or "." in match.group(1)):
            # A dotted head is a rule name as spelled (catalogued or not:
            # words() shows the gap); a bare head is one only when the
            # catalogue keeps it bare (``trim``), else it is a sentence.
            rule, message = match.group(1), match.group(2).strip()
        else:
            nameless = _LOG_NAMELESS.match(line.strip())
            named = name_of(nameless.group(1).strip()) if nameless else None
            if not named or not is_catalogued(named):
                continue                # no name the catalogue knows: the log tail says it
            rule, message = named, nameless.group(1).strip()
        refusal: Dict[str, Any] = {"constraint": rule, "message": message}
        numbers = _LOG_NUMBERS.search(message)
        if numbers:
            try:
                refusal["actual"] = float(numbers.group(1))
                refusal["limit"] = float(numbers.group(3))
                refusal["unit"] = numbers.group(4).strip() or numbers.group(2).strip()
            except ValueError:
                pass
        out.append(words(refusal))
    return out


def log_tail(log: Path, lines: int = 12) -> List[str]:
    try:
        text = Path(log).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    kept = [l for l in text.splitlines() if l.strip() and "JSBSim" not in l]
    return kept[-lines:]


def camera_views(run_dir: Path) -> Dict[str, str]:
    """``{camera_id: "<preset> view"}`` from the run's own manifest, so
    the gallery names the view a person asked for (the preset word) and
    not the directory name the capture gave it; {} when no manifest."""
    path = Path(run_dir) / "capture_manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: Dict[str, str] = {}
    for camera in manifest.get("cameras") or []:
        if isinstance(camera, dict) and camera.get("camera_id") and camera.get("preset"):
            out[str(camera["camera_id"])] = f"{camera['preset']} view"
    return out


def _camera_id_words(camera_id: str) -> str:
    """A camera id with no manifest preset, read as words: ``tower_0``
    -> ``tower view``."""
    stem = re.sub(r"[_-]?\d+$", "", str(camera_id)).replace("_", " ").strip()
    return f"{stem} view" if stem else str(camera_id)


def histograms(rows: List[Dict[str, Any]], bins: int = HISTOGRAM_BINS) -> Dict[str, Any]:
    """What is varying: for every leaf the ledger's rows recorded as
    ``sampled`` (the policy draw of each non-refused slot, latest row
    per index) plus each case's run seed, a histogram -- numeric leaves
    in ``bins`` equal-width bins over the realised range, words by
    count."""
    latest = latest_by_index(rows)
    values: Dict[str, List[Any]] = {}
    for row in latest.values():
        if row.get("status") == STATUS_REFUSED:
            continue
        for leaf, value in (row.get("sampled") or {}).items():
            values.setdefault(str(leaf), []).append(value)
    out: Dict[str, Any] = {}
    for leaf, drawn in sorted(values.items()):
        numeric = [v for v in drawn if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if drawn and len(numeric) == len(drawn):
            lo, hi = float(min(numeric)), float(max(numeric))
            width = (hi - lo) / bins if hi > lo else 0.0
            counts = [0] * bins
            for v in numeric:
                slot = int((float(v) - lo) / width) if width else 0
                counts[min(bins - 1, max(0, slot))] += 1
            edges = [round(lo + i * width, 4) for i in range(bins + 1)] if width else [lo, hi]
            out[leaf] = {"kind": "numeric", "n": len(numeric), "min": lo, "max": hi,
                         "edges": edges, "counts": counts}
        else:
            counts_by: Dict[str, int] = {}
            for v in drawn:
                counts_by[str(v)] = counts_by.get(str(v), 0) + 1
            out[leaf] = {"kind": "categorical", "n": len(drawn),
                         "counts": dict(sorted(counts_by.items()))}
    return out


def _reason_words(reason: Optional[str], state: str = FAILED, **numbers: Any
                  ) -> Optional[Dict[str, Any]]:
    """A campaign record's ``reason`` (or a worker thread's error) in
    words. A head the catalogue knows (``campaign.target_unreachable:
    ...``) renders as that refusal. Any other text -- the ledger's own
    tally on ``done``, a control request, an exception's ``TypeName:
    message`` -- is NOT a sentence for the page: the state's catalogue
    sentence (``progress.campaign.<state>``) is, and the producer's text
    stays under ``details.message`` for the disclosure."""
    if not reason:
        return None
    head, sep, tail = str(reason).partition(":")
    rule = head.strip()
    if sep and is_catalogued(rule):
        return words({"constraint": rule, "message": tail.strip()})
    state_rule = f"progress.campaign.{state}"
    if not is_catalogued(state_rule):
        state_rule = f"progress.campaign.{FAILED}"
    explained = explain(state_rule, **numbers)
    return {"sentence": explained["sentence"], "hint": explained["hint"],
            "details": {"rule": state_rule, "message": str(reason), "catalogued": True,
                        **{k: v for k, v in numbers.items() if v is not None}}}


def progress_from(record: Dict[str, Any], rows: List[Dict[str, Any]], directory: Path,
                  thread_error: Optional[str] = None) -> Dict[str, Any]:
    """The progress payload from a campaign record and its ledger rows
    -- pure, so a test can hand it a ledger it wrote."""
    summary = summarise(rows)
    latest = latest_by_index(rows)
    target = int(record["images_target"])
    state = str(record["state"])
    verified = summary["frames_verified"]
    # The measured per-case cost: mean frames and seconds over
    # completed captures (ok rows), the ledger's own numbers.
    completed = [r for r in latest.values() if r.get("ok") and int(r.get("frames") or 0) > 0]
    walls = [float(r["wall_seconds"]) for r in latest.values()
             if isinstance(r.get("wall_seconds"), (int, float)) and r.get("case_id")]
    frames_per_case = (int(round(sum(int(r["frames"]) for r in completed) / len(completed)))
                       if completed else None)
    seconds_per_case = (sum(walls) / len(walls)) if walls else None
    remaining_frames = max(0, target - verified)
    remaining_cases = (int(math.ceil(remaining_frames / frames_per_case))
                       if frames_per_case and remaining_frames else (0 if not remaining_frames else None))
    workers = max(1, int(record.get("workers") or 1))
    seconds_remaining = (seconds_per_case * remaining_cases / workers
                         if (seconds_per_case is not None and remaining_cases is not None) else None)
    refused_words = [{**words({"constraint": name, "message": f"{count} slot(s)"}, count=count),
                      "count": count}
                     for name, count in summary["refusals"].items()]
    drawn = any(bool(r.get("drawn")) for r in latest.values())
    cases_verified = sum(1 for r in latest.values() if r.get("verified"))
    numbers = {"done": verified, "total": target, "drawn": drawn,
               "frames_verified": verified, "images_target": target,
               "cases_verified": cases_verified}
    cases_words = {status: {"count": summary["cases"][status],
                            "sentence": state_words(f"progress.case.{status}", drawn=drawn)}
                   for status in STATUSES}
    headline = state_words(f"progress.campaign.{state}", **numbers)
    return {
        "id": record["id"], "state": state, "headline": headline,
        "reason": record.get("reason"),
        "reason_words": _reason_words(record.get("reason"), state, **numbers),
        "thread_error": thread_error,
        "thread_error_words": _reason_words(thread_error, FAILED),
        "cases_verified": cases_verified, "drawn": drawn,
        "images_target": target, "frames_verified": verified,
        "frames_captured": summary["frames_captured"],
        "fraction": round(min(1.0, verified / target), 4) if target else 0.0,
        "cases": summary["cases"], "cases_words": cases_words,
        "indices": summary["indices"],
        "refusals": summary["refusals"], "refusals_words": refused_words,
        "varying": histograms(rows),
        # The requested variety the verified cases have filled SO FAR,
        # field by field (core/dataset/realised.py) -- the request is not
        # the dataset, and the page says how far apart they are while
        # it runs.
        "coverage": live_coverage(directory, summary["verified_run_dirs"],
                                  record.get("policy")),
        "timing": {"frames_per_case": frames_per_case,
                   "seconds_per_case": (round(seconds_per_case, 3)
                                        if seconds_per_case is not None else None),
                   "remaining_cases": remaining_cases,
                   "seconds_remaining": (round(seconds_remaining, 1)
                                         if seconds_remaining is not None else None),
                   "workers": workers,
                   "basis": ("measured over completed cases" if completed
                             else "no case has completed yet; nothing is estimated")},
        "disk": {"bytes_per_case": summary["bytes_per_case"],
                 "measured_over": summary["bytes_measured_over"],
                 "budget_bytes": record.get("disk_budget_bytes")},
        "format": record.get("format"), "seed": record.get("seed"),
        "prompt": record.get("prompt"), "tier": record.get("tier"),
        "control": _control_request(directory),
        "updated_utc": utc_now(),
        "expert": [f"python -m flightsim.campaign --out {directory} --status",
                   f"python -m flightsim.campaign --out {directory} --report"],
    }


_COVERAGE_CACHE: Dict[str, Tuple[int, Dict[str, Any]]] = {}


def live_coverage(directory: Path, run_dirs: Sequence, policy: Any) -> Optional[Dict[str, Any]]:
    """The realised variety over the verified cases so far, in words:
    ``{headline, coverage, fields: [{label, sentence, coverage, narrow}]}``.
    Recomputed only when the number of verified cases changes (progress
    is polled every second). None before the first verified case."""
    from core.dataset.realised import realised_for_runs, realised_words

    dirs = [str(d) for d in run_dirs or []]
    if not dirs:
        return None
    key = str(directory)
    cached = _COVERAGE_CACHE.get(key)
    if cached is not None and cached[0] == len(dirs):
        return cached[1]
    try:
        realised = realised_for_runs(dirs, policy)
    except Exception:                      # a reader for the page, never a gate
        return None
    worded = realised_words(realised, frames_noun="checked")
    payload = {"headline": worded["headline"], "coverage": realised.get("coverage"),
               "narrow": worded["narrow"],
               "fields": [{k: item[k] for k in ("label", "sentence", "coverage", "narrow",
                                                "requested")}
                          for item in worded["fields"]]}
    _COVERAGE_CACHE[key] = (len(dirs), payload)
    return payload


def _control_request(directory: Path) -> Optional[str]:
    path = Path(directory) / "control.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("request")
    except (OSError, ValueError, AttributeError):
        return None


__all__ = ["GenerateService", "GenerateRefusal", "words", "state_words", "compile_round",
           "paragraph", "estimate", "plan_refusals", "histograms", "progress_from",
           "card_words", "LABELS_ONLY_WORDS", "MASKS_ONLY_WITH_ENGINE",
           "pictures", "camera_views", "expert_campaign", "capture_refusals",
           "CAPTURE_RUNNER", "DEFAULT_ROOT", "FORMATS"]
