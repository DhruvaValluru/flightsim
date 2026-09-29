"""The typed tools (contracts §7; brainstorm §7.1): ten functions with
JSON schemas drawn from their own signatures, each a thin call into
the library that already exists, guarded by :class:`core.agent.policy.
Policy` on every call and written to ``trace.jsonl`` on every call.

    compile(prompt, answers?)            -> {spec, spec_digest, questions, refusals, tier}
    validate(spec)                       -> {ok, spec_digest, violations, validation_token}
    plan_campaign(spec, words, images..) -> {campaign_id, policy, estimate, refusals}
    sample(campaign_id, n, start?)       -> {cases, refused_slots, next_index}
    run(case_id, validation_token)       -> {run_id, status, ...}
    render(run_id, validation_token)     -> {frames, drawn}
    verify(run_id)                       -> {checks, verdict}
    export(campaign_id, format, token)   -> {dataset_path, card}
    inspect(run_id, frame?)              -> {overlay_png, records}
    report(campaign_id)                  -> {yield, coverage, refusals}

``validate`` is the tenth: the contract's nine plus the one that
MINTS the ``validation_token`` (``sha256(spec digest + "validated")``,
HMAC-free by contract) -- minted only here and only for a spec with no
refusal, so ``run``, ``render`` and ``export`` can require it.

``run`` takes a case id from ``sample`` (one slot, through the
campaign's own worker function, ledgered exactly as the campaign
ledgers it) or a campaign id (the campaign runs to its target or a
named end through ``Campaign.run`` -- the one place ``done`` is
written). ``render`` reports the frames of a run and whether pixels
exist; with no engine on the host nothing draws and the tool says so
rather than pretending. ``verify`` re-runs the verifier read-only;
it never writes ``verification.json`` (only ``write_verification``
does, inside the run stage).

Every call goes through :meth:`Tools.call`: the policy check first
(a denial is returned as ``{"refused": name, "sentence", "hint"}``
and traced), then the tool, whose own library refusals
(``CampaignError``, ``RandomizationError``, ``ExportError``,
``LLMCompileError``, a spec-version ``ValueError``) come back the same
way BY NAME; a programming error is not a refusal and is raised.

What is NOT claimed: the web app's compile-time planner sequence
(``plan_scene_setting`` ... ``plan_camera_defaults``, ``webapp/runs.py``)
is not applied by ``compile`` -- it lives in the web app's module, and
moving it to core edits files this package does not own; the campaign
runs the compiled spec exactly as ``flightsim.campaign`` does. No tool
launches an engine directly: pixels come from the capture CLI's own
``--render`` when the campaign is planned with ``render=True``.
"""

from __future__ import annotations

import hashlib
import inspect as _inspect
import json
import typing
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .policy import (
    RULE_STATED_FIELD, STATED_SOURCES, TOKEN_TOOLS, Budget, Denial, Policy,
)
from .trace import TRACE, Trace

TOOL_NAMES = ("compile", "validate", "plan_campaign", "sample", "run", "render",
              "verify", "export", "inspect", "report")
TOKEN_SALT = "validated"


def mint_token(spec_digest: str) -> str:
    """The validation token for a spec digest. Called by ``validate``
    only; ``policy.expected_token`` re-computes it independently."""
    return hashlib.sha256((str(spec_digest) + TOKEN_SALT).encode()).hexdigest()


# -- schemas from signatures -------------------------------------------------------

_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean",
               dict: "object", list: "array"}


def _json_type(annotation: Any) -> Dict[str, Any]:
    """A JSON-schema type for a Python annotation: the six scalars and
    containers, ``Optional[X]`` as ``[X, "null"]``, anything else as an
    unconstrained value."""
    if annotation in _JSON_TYPES:
        return {"type": _JSON_TYPES[annotation]}
    origin = typing.get_origin(annotation)
    if origin is typing.Union:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1 and args[0] in _JSON_TYPES:
            return {"type": [_JSON_TYPES[args[0]], "null"]}
    if origin in (list, typing.List):
        return {"type": "array"}
    if origin in (dict, typing.Dict):
        return {"type": "object"}
    return {}


def tool_schema(fn: Callable[..., Any], name: Optional[str] = None) -> Dict[str, Any]:
    """``{name, description, parameters}`` from a function's signature,
    annotations and docstring (first paragraph). Parameters without a
    default are required. No pydantic."""
    signature = _inspect.signature(fn)
    hints = typing.get_type_hints(fn)
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for param in signature.parameters.values():
        if param.name == "self":
            continue
        schema = _json_type(hints.get(param.name, param.annotation))
        if param.default is _inspect.Parameter.empty:
            required.append(param.name)
        else:
            schema = dict(schema, default=param.default)
        properties[param.name] = schema
    doc = _inspect.getdoc(fn) or ""
    description = " ".join(doc.split("\n\n")[0].split())
    return {"name": name or fn.__name__, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": required, "additionalProperties": False}}


#: What each tool is in the CLI and on the page (docs/COMMANDS.md).
EQUIVALENTS: Dict[str, Dict[str, str]] = {
    "compile": {"cli": 'python -m flightsim.campaign "<prompt>" --images N --out DIR --plan',
                "ui": "POST /compile; the generate page's ask and clarify states"},
    "validate": {"cli": 'python -m flightsim.campaign "<prompt>" --images N --out DIR --plan  (the plan validates)',
                 "ui": "the validation verdict under the spec table (POST /compile)"},
    "plan_campaign": {"cli": 'python -m flightsim.campaign "<prompt>" --images N --out DIR --plan',
                      "ui": "POST /generate/plan; the preview state"},
    "sample": {"cli": 'python -m flightsim.campaign "<prompt>" --images N --out DIR --sample N',
               "ui": "POST /generate/preview"},
    "run": {"cli": "python -m flightsim.campaign --out DIR --resume  (a campaign); python -m flightsim.capture runs/<case>/spec.yaml --out runs/<case>  (one case)",
            "ui": "POST /generate/start; POST /run for one case"},
    "render": {"cli": "python -m flightsim.capture spec.yaml --out DIR --render",
               "ui": "the frames gallery (GET /generate/{id}/frames)"},
    "verify": {"cli": "python -m flightsim.verify runs/<case>",
               "ui": "GET /runs/{id}/verification.json; the review state"},
    "export": {"cli": "python -m flightsim.export runs/* --out DIR --format FORMAT; python -m flightsim.campaign --out DIR --resume --export",
               "ui": "GET /generate/{id}/download?format="},
    "inspect": {"cli": "python -m flightsim.verify runs/<case> --render  (overlays)",
                "ui": "the overlays under the frames page"},
    "report": {"cli": "python -m flightsim.campaign --out DIR --report",
               "ui": "GET /generate/{id}; the review state"},
}


# -- the tools ---------------------------------------------------------------------

class Tools:
    """The tool layer over one output directory: the trace lives there
    and campaigns are planned into it. ``tier`` picks the compiler
    (``regex`` needs no model; ``llm`` uses the configured provider and
    falls back to regex, recorded); ``capture_runner`` and ``workers``
    pass through to the campaign; ``policy`` carries the budget."""

    def __init__(self, out, policy: Optional[Policy] = None,
                 trace: Optional[Trace] = None, tier: str = "regex",
                 workers: int = 1, capture_runner: Optional[str] = None,
                 stall_seconds: Optional[float] = None) -> None:
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.policy = policy or Policy(Budget())
        self.trace = trace or Trace(self.out / TRACE)
        self.tier = str(tier)
        self.workers = int(workers)
        self.capture_runner = capture_runner
        self.stall_seconds = stall_seconds
        self.campaigns: Dict[str, Path] = {}
        self._adopt_existing()

    def _adopt_existing(self) -> None:
        """A campaign already in ``out`` (or ``out`` itself) is known by
        its id, so a resumed session can report and export it."""
        for candidate in [self.out] + sorted(p for p in self.out.iterdir() if p.is_dir()):
            if (candidate / "campaign.json").is_file():
                self.campaigns[candidate.name] = candidate

    # -- the entry point every caller uses ------------------------------------------

    def call(self, tool: str, reason: str = "", **kwargs: Any) -> Dict[str, Any]:
        """Policy check, the tool, the trace line. A denial or a library
        refusal is returned as ``{"refused": name, ...}`` -- never raised
        past here, never silent."""
        if tool not in TOOL_NAMES:
            raise ValueError(f"{tool!r} is not a tool; the tools are {TOOL_NAMES}")
        digest = self._digest_for(tool, kwargs)
        try:
            verdict = self.policy.check(tool, kwargs, spec_digest=digest)
        except Denial as denial:
            return self._denied(tool, kwargs, reason, denial)
        fn = getattr(self, tool)
        try:
            output = fn(**kwargs)
        except Denial as denial:
            return self._denied(tool, kwargs, reason, denial)
        except Exception as exc:                # noqa: BLE001 -- named refusals only
            output = self._refusal_output(exc)
            if output is None:
                raise
        self.trace.record(tool, kwargs, output, reason, verdict)
        return output

    def _denied(self, tool, kwargs, reason, denial: Denial) -> Dict[str, Any]:
        output = denial.as_output()
        self.trace.record(tool, kwargs, output, reason,
                          {"ok": False, "rule": denial.constraint,
                           "sentence": output["sentence"]})
        return output

    @staticmethod
    def _refusal_output(exc: BaseException) -> Optional[Dict[str, Any]]:
        from core.messages import explain, name_of

        name = name_of(exc)
        if not name:
            return None
        words = explain(exc)
        return {"refused": name, "sentence": words["sentence"],
                "hint": words["hint"], "message": str(exc),
                "detail": dict(getattr(exc, "detail", {}) or {})}

    def _digest_for(self, tool: str, kwargs: Dict[str, Any]) -> Optional[str]:
        """The spec digest the token tools bind to: the campaign's
        compiled digest (a case is a sampled derivative of it)."""
        if tool not in TOKEN_TOOLS:
            return None
        try:
            if tool == "run":
                located = self._locate(kwargs.get("case_id"))
            elif tool == "render":
                located = self._locate(kwargs.get("run_id"))
            else:
                located = self._locate(kwargs.get("campaign_id"))
        except Exception:                        # noqa: BLE001 -- the tool names it
            return None
        return located[0].record.get("spec_digest") if located else None

    # -- lookups ---------------------------------------------------------------------

    def _campaign(self, campaign_id: str):
        from core.campaign import Campaign, CampaignError

        path = self.campaigns.get(str(campaign_id))
        if path is None:
            candidate = Path(str(campaign_id))
            if (candidate / "campaign.json").is_file():
                path = candidate
            elif (self.out / str(campaign_id) / "campaign.json").is_file():
                path = self.out / str(campaign_id)
            else:
                raise CampaignError("campaign.arguments",
                                    f"{campaign_id!r} is not a campaign this session knows "
                                    f"({sorted(self.campaigns) or 'none planned yet'})")
            self.campaigns[path.name] = path
        return Campaign.open(path)

    def _locate(self, ident: Any):
        """(campaign, index or None) for a campaign id or a case id."""
        from core.campaign import CampaignError

        ident = str(ident or "")
        if ident in self.campaigns or (Path(ident) / "campaign.json").is_file():
            return self._campaign(ident), None
        for path in self.campaigns.values():
            campaign = self._campaign(path.name)
            for index, row in campaign.ledger.latest().items():
                if row.get("case_id") == ident:
                    return campaign, int(index)
        raise CampaignError("campaign.arguments",
                            f"{ident!r} is neither a campaign nor a case id this session knows")

    def _run_dir(self, run_id: str) -> Path:
        from core.campaign import CampaignError

        campaign, index = self._locate(run_id)
        if index is None:
            raise CampaignError("campaign.arguments",
                                f"{run_id!r} is a campaign, not a run; name a case id")
        row = campaign.ledger.latest()[index]
        run_dir = row.get("run_dir") or str(campaign.dir / "runs" / run_id)
        return Path(run_dir)

    @staticmethod
    def _spec(spec: Dict[str, Any]):
        from core.scenario.spec import ScenarioSpec

        if not isinstance(spec, dict):
            raise ValueError("spec_version missing: a spec is the dict compile() returned")
        return ScenarioSpec.from_dict(deepcopy(spec))

    @staticmethod
    def _refusals_of(spec) -> List[Dict[str, Any]]:
        """The refusals a spec carries: the validator's violations and a
        policy DEFECT (shape, vocabulary, a range with no bake) found by
        probing slot 0 -- an exhausted slot is not a defect."""
        from core.messages import explain
        from core.scenario.randomization import RandomizationError, sample_randomization
        from core.scenario.validate import validate

        out: List[Dict[str, Any]] = []
        report = validate(spec)
        for v in report.violations:
            words = explain(v)
            out.append({"constraint": v.constraint, "message": v.message,
                        "sentence": words["sentence"], "hint": words["hint"]})
        if report.ok and spec.randomization_policy is not None:
            probe = deepcopy(spec)
            try:
                sample_randomization(probe, draw_index=0)
            except RandomizationError as exc:
                if exc.constraint != "randomization.infeasible":
                    words = explain(exc)
                    out.append({"constraint": exc.constraint, "message": exc.message,
                                "sentence": words["sentence"], "hint": words["hint"]})
        return out

    # -- 1. compile ------------------------------------------------------------------

    def compile(self, prompt: str, answers: Optional[list] = None) -> Dict[str, Any]:
        """Turn a prompt (plus an answer round) into a spec with
        provenance, the clarifying questions it needs, and the refusals
        it carries. Runs nothing; the spec's provenance becomes the
        reference every later spec input is compared with."""
        from core.nl.compiler import camera_questions, compile_prompt

        answers = list(answers or [])
        questions: List[Dict[str, Any]] = []
        tier_used = "regex"
        spec = None
        if self.tier == "llm":
            from core.nl.llm_compiler import LLMCompileError, compile_prompt_llm

            try:
                result = compile_prompt_llm(prompt, answers=answers or None)
                spec, tier_used = result.spec, f"llm ({result.model})"
                questions = [dict(q) for q in result.questions]
            except LLMCompileError as exc:
                tier_used = f"regex (llm unavailable: {exc})"
        elif self.tier != "regex":
            raise ValueError(f"tier {self.tier!r} is not one of 'regex', 'llm'")
        if spec is None:
            spec = compile_prompt(prompt, answers=answers or None)
            questions = [] if answers else camera_questions(prompt)
        refusals = self._refusals_of(spec)
        payload = spec.to_dict()
        self.policy.note_compiled(payload, spec.digest(), refusals)
        return {"spec": payload, "spec_digest": spec.digest(), "questions": questions,
                "refusals": refusals, "tier": tier_used, "notes": list(spec.notes)}

    # -- 2. validate (mints the token) -----------------------------------------------

    def validate(self, spec: dict) -> Dict[str, Any]:
        """Validate a spec exactly as it is and, when it carries no
        refusal, mint the validation_token that run, render and export
        require for this digest. A refused spec gets no token."""
        obj = self._spec(spec)
        refusals = self._refusals_of(obj)
        digest = obj.digest()
        token = None
        if not refusals:
            token = mint_token(digest)
            self.policy.note_validated(digest)
        else:
            self.policy.note_refused(digest, refusals)
        return {"ok": not refusals, "spec_digest": digest, "violations": refusals,
                "validation_token": token}

    # -- 3. plan_campaign ------------------------------------------------------------

    def plan_campaign(self, spec: dict, words: str = "", images: int = 100,
                      seed: Optional[int] = None, format: str = "coco",
                      policy: Optional[dict] = None, render: bool = False,
                      out: Optional[str] = None) -> Dict[str, Any]:
        """Plan a campaign from a spec: the policy words (the prompt
        vocabulary, e.g. 'varied weather at different times of day') or
        an explicit policy are applied as a RECORDED plan edit to a spec
        that states no policy of its own, the campaign directory is
        created and its plan (frames per case, cases needed, disk) is
        estimated. Refuses by name before anything runs."""
        from core.campaign import Campaign, CampaignError

        obj = self._spec(spec)
        obj = self._apply_policy_words(obj, words, policy)
        target = Path(out) if out else self.out
        prompt = obj.prompt or ""
        campaign = Campaign.create(
            prompt, images=int(images), seed=seed, out=target, format=format,
            workers=self.workers, tier="regex",
            capture={"max_previews": 0, "card": True, "render": bool(render)},
            stall_seconds=self.stall_seconds)
        if campaign.record["spec_digest"] != obj.digest():
            # The campaign compiled the prompt again on its own path; the
            # tool layer's spec (the LLM tier's, or with the policy words
            # planned on) is the one the cases are built from. Recorded.
            campaign.record["spec"] = obj.to_dict()
            campaign.record["spec_digest"] = obj.digest()
            campaign.record["policy"] = (obj.randomization_policy.value
                                         if obj.randomization_policy is not None else None)
            campaign.record["tier"] = f"agent ({self.tier}); spec adopted from the tool layer"
            campaign._save()
        self.campaigns[campaign.record["id"]] = campaign.dir
        try:
            plan = campaign.plan()
        except CampaignError as exc:
            refusal = self._refusal_output(exc)
            self.policy.note_refused(obj.digest(), [{"constraint": exc.constraint,
                                                     "sentence": refusal["sentence"]}])
            return {"campaign_id": campaign.record["id"], "campaign_dir": str(campaign.dir),
                    "spec_digest": obj.digest(), "policy": campaign.record.get("policy"),
                    "estimate": None, "refusals": [refusal]}
        return {"campaign_id": campaign.record["id"], "campaign_dir": str(campaign.dir),
                "spec_digest": obj.digest(), "policy": campaign.record.get("policy"),
                "estimate": plan, "refusals": []}

    def _apply_policy_words(self, obj, words: str, policy: Optional[dict]):
        """Policy words / an explicit policy as a plan edit (source
        ``derived``, the words quoted). A spec that already STATES a
        policy is never moved: ``authority.stated_field``."""
        from core.nl.compiler import apply_randomization_phrases

        words = str(words or "").strip()
        if not words and policy is None:
            return obj
        current = obj.randomization_policy
        if current is not None and str(current.source) in STATED_SOURCES:
            raise Denial(constraint="authority.stated_field",
                         message=f"randomization.policy is {current.source}-stated "
                         f"({current.frm}); the policy words {words!r} would move it",
                         detail={"path": "randomization.policy", "words": words})
        if policy is None:
            probe = deepcopy(obj)
            apply_randomization_phrases(probe, words)
            if probe.randomization_policy is None:
                from core.scenario.randomization import RandomizationError

                raise RandomizationError(
                    "randomization.vocabulary",
                    f"the policy words {words!r} name nothing the vocabulary maps")
            policy = dict(probe.randomization_policy.value)
            frm = f"policy words {words!r} planned by the assistant"
            detail = dict(probe.randomization_policy.detail)
        else:
            frm = "policy chosen by the assistant"
            detail = {}
        obj.plan("randomization.policy", dict(policy), frm=frm)
        if detail.get("unmapped"):
            obj.notes.append(f"policy words not in the vocabulary: {detail['unmapped']}")
        if not obj.randomization.is_enabled():
            obj.plan("randomization.enabled", True,
                     frm=f"{frm}: the randomisation block is on")
        return obj

    # -- 4. sample ----------------------------------------------------------------------

    def sample(self, campaign_id: str, n: int = 1, start: Optional[int] = None) -> Dict[str, Any]:
        """Draw the next n slots by index (or n from start): the cases
        with their sampled leaves, and the refused slots by name. A
        refused slot is a ledger row; the sampler draws only
        system-chosen leaves -- a stated value is never re-drawn."""
        from core.messages import explain

        campaign = self._campaign(campaign_id)
        drawn = campaign.sample(int(n), start=start, record=True)
        # The key ``refused`` is a refusal dict everywhere in the tool
        # layer ({"refused": name}); the refused SLOTS are ``refused_slots``.
        drawn["refused_slots"] = drawn.pop("refused")
        for slot in drawn["refused_slots"]:
            names = slot.get("refusals") or []
            attempts = slot.get("refused_attempts") or []
            slot["sentence"] = (explain(names[0], refused=len(attempts),
                                        draws=len(attempts))["sentence"] if names else "")
        return drawn

    # -- 5. run --------------------------------------------------------------------------

    def run(self, case_id: str, validation_token: str) -> Dict[str, Any]:
        """Run one case (a case id from sample: the slot is captured
        through the campaign's own worker function and ledgered as the
        campaign ledgers it) or a whole campaign (a campaign id: it runs
        to its target or a named end, the only way done is written).
        Needs the validation_token minted for the campaign's spec."""
        campaign, index = self._locate(case_id)
        if index is None:
            return self._run_campaign(campaign)
        return self._run_slot(campaign, index, case_id)

    def _run_campaign(self, campaign) -> Dict[str, Any]:
        from core.campaign import CampaignError
        from core.messages import explain

        try:
            status = campaign.run(workers=self.workers, capture_runner=self.capture_runner)
        except CampaignError as exc:
            status = campaign.status()
            words = explain(exc)
            return {"run_id": status["id"], "status": status["state"],
                    "reason": status.get("reason"), "refusals": [exc.constraint],
                    "sentence": words["sentence"], "hint": words["hint"],
                    "frames_verified": status["frames_verified"],
                    "images_target": status["images_target"], "cases": status["cases"]}
        return {"run_id": status["id"], "status": status["state"],
                "reason": status.get("reason"), "refusals": [],
                "frames_verified": status["frames_verified"],
                "images_target": status["images_target"], "cases": status["cases"]}

    def _run_slot(self, campaign, index: int, case_id: str) -> Dict[str, Any]:
        """One slot, as the campaign's single-worker round runs it: a
        running row, the worker function, the duplicate check, the
        result row. A slot already verified is not run again (idempotent
        on the case id)."""
        from core.campaign.ledger import STATUS_REFUSED, STATUS_VERIFIED
        from core.campaign.workers import run_index, utc_now
        from core.messages import explain
        from core.scenario.spec import ScenarioSpec

        latest = campaign.ledger.latest()
        row = latest.get(index, {})
        if row.get("status") == STATUS_VERIFIED:
            return self._row_output(row, note="already verified; not run again")
        attempt = int(row.get("attempt") or 0) + 1
        campaign.ledger.append({"index": index, "status": "running", "attempt": attempt,
                                "campaign_seed": campaign.record["seed"],
                                "started_utc": utc_now()})
        seen = {r.get("case_id"): i for i, r in latest.items()
                if r.get("case_id") and r.get("status") not in (STATUS_REFUSED, "sampled")
                and i != index}
        result = run_index(index, campaign.record, str(campaign.dir), attempt,
                           campaign.record.get("stall_seconds") if self.stall_seconds is None
                           else self.stall_seconds,
                           self.capture_runner, seen)
        campaign.ledger.append(result)
        output = self._row_output(result)
        # The case the worker built is compared with the reference AFTER
        # the fact: the sampler may add sampled leaves and plan the seeds,
        # and nothing else may have moved a stated field.
        if result.get("run_dir") and Path(result["run_dir"], "spec.yaml").is_file():
            case_spec = ScenarioSpec.read(Path(result["run_dir"]) / "spec.yaml").to_dict()
            self.policy.check_spec(case_spec, allow_new=("sampled",))
        names = output.get("refusals") or []
        if names:
            output["sentence"] = explain(names[0])["sentence"]
        return output

    @staticmethod
    def _row_output(row: Dict[str, Any], note: Optional[str] = None) -> Dict[str, Any]:
        out = {"run_id": row.get("case_id"), "status": row.get("status"),
               "index": row.get("index"), "frames": int(row.get("frames") or 0),
               "yield": int(row.get("yield") or 0), "verified": bool(row.get("verified")),
               "drawn": bool(row.get("drawn")), "refusals": list(row.get("refusals") or []),
               "reason": row.get("reason"), "run_dir": row.get("run_dir"),
               "verification": row.get("verification")}
        if note:
            out["note"] = note
        return out

    # -- 6. render -------------------------------------------------------------------------

    def render(self, run_id: str, validation_token: str) -> Dict[str, Any]:
        """The frames a run recorded and whether pixels exist for them.
        Pixels are drawn inside run() by the capture CLI when the
        campaign was planned with render=True and an engine is present;
        this tool reports, it does not launch an engine."""
        run_dir = self._run_dir(run_id)
        manifest_path = run_dir / "capture_manifest.json"
        if not manifest_path.is_file():
            return {"run_id": run_id, "frames": 0, "drawn": False,
                    "note": "no capture manifest: the run produced nothing to render"}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        frames = [f for f in (manifest.get("frames") or []) if isinstance(f, dict)]
        files = [str(f.get("file", "")) for f in frames]
        drawn = sum(1 for name in files if name and (run_dir / name).is_file())
        return {"run_id": run_id, "frames": len(frames), "drawn": drawn > 0,
                "frames_drawn": drawn,
                "note": ("pixels exist for every frame" if drawn == len(frames) and frames
                         else "no pixels: labels only (no engine on this host, or the "
                              "campaign was not planned with render=True)"
                         if drawn == 0 else f"{drawn} of {len(frames)} frames have pixels")}

    # -- 7. verify --------------------------------------------------------------------------

    def verify(self, run_id: str) -> Dict[str, Any]:
        """Re-run the verifier over a run directory, read-only: every
        check with its status and the verdict (pass / fail / not_run --
        NOT RUN is not a pass). verification.json is not written here."""
        from core.capture.verify import verify_run

        run_dir = self._run_dir(run_id)
        summary = verify_run(run_dir).to_dict()
        if summary["failed"]:
            verdict = "fail"
        elif summary["passed"]:
            verdict = "pass"
        else:
            verdict = "not_run"
        return {"run_id": run_id, "checks": summary["checks"], "verdict": verdict,
                "ok": summary["ok"], "passed": summary["passed"],
                "failed": summary["failed"], "not_run": summary["not_run"],
                "failures": [c.get("failure") for c in summary["checks"]
                             if c.get("status") == "FAIL" and c.get("failure")]}

    # -- 8. export ------------------------------------------------------------------------------

    def export(self, campaign_id: str, format: str, validation_token: str) -> Dict[str, Any]:
        """Export every verified case of a campaign in a format the
        export module lists (coco, kitti, webdataset, yolo, voc) into
        <campaign>/datasets/<format>, with the dataset card."""
        campaign = self._campaign(campaign_id)
        result = campaign.export(str(format))
        return {"dataset_path": result["dataset_path"], "card": result["card"],
                "runs": result["runs"], "labels_only": result["labels_only"]}

    # -- 9. inspect -----------------------------------------------------------------------------

    def inspect(self, run_id: str, frame: Optional[int] = None) -> Dict[str, Any]:
        """The per-frame records of a run (one frame, or all) and an
        overlay PNG drawn on the rendered frame where pixels exist."""
        run_dir = self._run_dir(run_id)
        manifest_path = run_dir / "capture_manifest.json"
        if not manifest_path.is_file():
            return {"run_id": run_id, "overlay_png": None, "records": [],
                    "note": "no capture manifest"}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        frames = [f for f in (manifest.get("frames") or []) if isinstance(f, dict)]
        if frame is not None:
            frames = [f for f in frames if int(f.get("index", -1)) == int(frame)] or \
                     frames[int(frame):int(frame) + 1]
        overlay = None
        if any((run_dir / str(f.get("file", ""))).is_file() for f in frames if f.get("file")):
            from core.capture.overlay import draw_overlays

            paths = draw_overlays(manifest, run_dir, max_frames=1 if frame is not None else None)
            overlay = str(paths[0]) if paths else None
        return {"run_id": run_id, "overlay_png": overlay, "records": frames,
                "note": None if overlay else "no pixels to overlay; the records are the labels"}

    # -- 10. report ------------------------------------------------------------------------------

    def report(self, campaign_id: str) -> Dict[str, Any]:
        """Write and return the campaign's report.json: yield against the
        target, coverage of the requested policy bins, refusals by name
        (slots and attempts), timing and disk -- every number from the
        ledger and the manifests."""
        campaign = self._campaign(campaign_id)
        payload = campaign.report()
        return {"campaign_id": payload["campaign"], "state": payload["state"],
                "reason": payload.get("reason"), "yield": payload["yield"],
                "coverage": payload.get("coverage"), "refusals": payload["refusals"],
                "realised_fields": sorted((payload.get("realised") or {}).get("fields") or {}),
                "report_path": str(campaign.dir / "report.json"),
                "not_claimed": payload.get("not_claimed")}


def schemas() -> List[Dict[str, Any]]:
    """The ten tool schemas, drawn from :class:`Tools`' signatures."""
    return [tool_schema(getattr(Tools, name), name) for name in TOOL_NAMES]


__all__ = ["TOOL_NAMES", "EQUIVALENTS", "Tools", "mint_token", "schemas", "tool_schema"]
