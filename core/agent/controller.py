"""The loop (contracts §7; brainstorm §7.2): interpret the request
into a campaign plan, execute through the tools, read the results,
re-sample only system-chosen fields on a named refusal, verify the
yield against the request (count, coverage, annotation validity),
continue or escalate in one plain sentence. Budgets end the loop.

The controller is a deterministic planner: the compiler (the regex
tier, or the LLM tier when ``Tools(tier="llm")`` is configured -- the
model interprets the PROMPT into a spec; it does not choose tools)
turns the request into a spec, the policy words and the image count
become the campaign plan, and every step after that is decided from
what the tools returned. Every decision is a line of the trace with
its reason in one sentence, so the trace reads as the story of the
request. It runs with NO model in the tests.

What it never does: write ``capture_manifest.json`` (only
``build_capture_manifest``), ``verification.json`` (only
``write_verification``), a campaign's state (only ``Campaign.run``
writes ``done``), or a stated field; it never calls a library
function around the tool layer, so the policy sees every call.

Not claimed: an agent runtime (Pydantic AI, the Claude Agent SDK --
brainstorm §7.4) driving this loop; the loop here is the deterministic
one the plan says must exist whether or not a runtime is added.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .tools import Tools


@dataclass
class Request:
    """What the person asked for: the prompt, the number of images,
    the policy words (the prompt vocabulary; may be empty when the
    prompt itself asks for variation), the export format."""

    prompt: str
    images: int = 100
    words: str = ""
    format: str = "coco"
    seed: Optional[int] = None
    answers: Optional[List[Dict[str, str]]] = None
    render: bool = False
    #: An explicit policy (contracts §5.2) the assistant chooses when the
    #: request states none; planned as a recorded edit, never over a
    #: stated one.
    policy: Optional[Dict[str, Any]] = None


@dataclass
class Outcome:
    """How the loop ended: ``done`` (the export exists) or
    ``escalated`` (one sentence says why, in catalogue language), with
    the campaign id when one was planned and the sentences the loop
    decided along the way."""

    state: str
    sentence: str
    campaign_id: Optional[str] = None
    trace_path: Optional[str] = None
    steps: List[str] = field(default_factory=list)
    yield_frames: int = 0
    dataset_path: Optional[str] = None
    rule: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"state": self.state, "sentence": self.sentence,
                "campaign_id": self.campaign_id, "trace_path": self.trace_path,
                "steps": list(self.steps), "yield_frames": self.yield_frames,
                "dataset_path": self.dataset_path, "rule": self.rule}


def _refused(result: Dict[str, Any]) -> bool:
    return isinstance(result, dict) and bool(result.get("refused"))


class Controller:
    """The loop over one :class:`Tools`. ``preview`` is how many slots
    are sampled and run one at a time (each read and explained) before
    the campaign runs to its target through its own exit criterion."""

    def __init__(self, tools: Tools, preview: int = 2) -> None:
        self.tools = tools
        self.preview = max(0, int(preview))
        self.steps: List[str] = []

    # -- narration ---------------------------------------------------------------------

    def _decide(self, sentence: str, **detail: Any) -> None:
        """A decision of the controller's own, in the trace."""
        self.steps.append(sentence)
        self.tools.trace.record("controller", detail, {"decision": sentence}, sentence,
                                {"ok": True})

    def _escalate(self, sentence: str, campaign_id: Optional[str] = None,
                  rule: Optional[str] = None) -> Outcome:
        self._decide("Escalate: " + sentence, rule=rule or "")
        return Outcome("escalated", sentence, campaign_id=campaign_id,
                       trace_path=str(self.tools.trace.path), steps=list(self.steps),
                       rule=rule)

    @staticmethod
    def _sentence(result: Dict[str, Any]) -> str:
        name = result.get("refused") or (result.get("refusals") or [""])[0]
        words = result.get("sentence") or result.get("message") or result.get("reason") or name
        return f"{words} ({name})" if name and name not in words else str(words)

    # -- the loop -------------------------------------------------------------------------

    def run(self, request: Request) -> Outcome:
        self.steps = []
        call = self.tools.call
        images = int(request.images)

        compiled = call("compile", prompt=request.prompt, answers=request.answers,
                        reason="Interpret the request as a scenario with provenance; "
                               "nothing runs yet.")
        if _refused(compiled):
            return self._escalate(self._sentence(compiled), rule=compiled["refused"])
        if compiled["questions"]:
            q = compiled["questions"][0]
            options = ", ".join(str(o) for o in q.get("options", [])) or "free text"
            return self._escalate(
                f"The request needs an answer before anything runs: {q['question']} "
                f"(options: {options}; answer with --answer {q['id']}=<choice>).")
        if compiled["refusals"]:
            first = compiled["refusals"][0]
            return self._escalate(f"The scenario cannot run as stated: {first['sentence']} "
                                  f"({first['constraint']})", rule=first["constraint"])
        digest = compiled["spec_digest"]

        validated = call("validate", spec=compiled["spec"],
                         reason="Validate the scenario exactly as compiled; the token "
                                "binds every run, render and export to this digest.")
        if _refused(validated):
            return self._escalate(self._sentence(validated), rule=validated["refused"])
        if not validated["ok"]:
            first = validated["violations"][0]
            return self._escalate(f"{first['sentence']} ({first['constraint']})",
                                  rule=first["constraint"])
        token = validated["validation_token"]

        planned = call("plan_campaign", spec=compiled["spec"], words=request.words,
                       images=images, seed=request.seed, format=request.format,
                       render=request.render, policy=request.policy,
                       reason=f"Plan {images} images"
                              + (f" varying {request.words!r}" if request.words else "")
                              + "; the estimate decides how many cases to draw.")
        if _refused(planned):
            return self._escalate(self._sentence(planned), rule=planned["refused"])
        campaign_id = planned["campaign_id"]
        if planned["refusals"]:
            first = planned["refusals"][0]
            return self._escalate(f"{first['sentence']} ({first['refused']})",
                                  campaign_id, rule=first["refused"])
        estimate = planned["estimate"]
        need = int(estimate.get("cases_needed") or 1)
        self._decide(f"The plan needs about {need} case(s) of "
                     f"~{estimate['frames_per_case']['estimate']} frames each for "
                     f"{images} images; {estimate['probe']}.", campaign_id=campaign_id)

        # -- preview: sample and run a few slots one at a time -------------------------
        cases: List[Dict[str, Any]] = []
        want = min(self.preview, need)
        resamples = 0
        while len(cases) < want:
            drawn = call("sample", campaign_id=campaign_id, n=want - len(cases),
                         reason=f"Draw the next {want - len(cases)} slot(s) by index so a "
                                f"refused draw is seen before anything runs.")
            if _refused(drawn):
                return self._escalate(self._sentence(drawn), campaign_id, rule=drawn["refused"])
            cases.extend(drawn["cases"])
            for slot in drawn["refused_slots"]:
                resamples += 1
                name = (slot.get("refusals") or ["refused"])[0]
                self._decide(f"Slot {slot['index']} was refused {name} ({slot.get('sentence')}); "
                             f"the sampler re-draws only system-chosen leaves and every stated "
                             f"value stays, so the next slot is drawn.", slot=slot["index"])
            if drawn["refused_slots"] and resamples > self.tools.policy.budget.max_resamples_per_slot:
                from core.messages import render

                return self._escalate(
                    f"{resamples} slots in a row were refused. "
                    f"{render('campaign.target_unreachable')} (campaign.target_unreachable)",
                    campaign_id, rule="campaign.target_unreachable")

        for case in cases:
            result = call("run", case_id=case["case_id"], validation_token=token,
                          reason=f"Run case {case['case_id']} (slot {case['index']}) with the "
                                 f"token minted for digest {digest[:16]}.")
            if _refused(result):
                return self._escalate(self._sentence(result), campaign_id, rule=result["refused"])
            status = result.get("status")
            if status == "verified":
                self._decide(f"Case {case['case_id']} verified with {result['frames']} frames.",
                             case_id=case["case_id"])
                verdict = call("verify", run_id=case["case_id"],
                               reason="Re-check the verdict independently of the run's own record.")
                if _refused(verdict) or verdict.get("verdict") != "pass":
                    return self._escalate(
                        f"The verifier does not pass case {case['case_id']}: "
                        f"{self._sentence(verdict) if _refused(verdict) else verdict.get('failures')}",
                        campaign_id)
                drawn_result = call("render", run_id=case["case_id"], validation_token=token,
                                    reason="Ask for the frames and whether pixels exist for them.")
                if _refused(drawn_result):
                    return self._escalate(self._sentence(drawn_result), campaign_id,
                                          rule=drawn_result["refused"])
                self._decide(f"Case {case['case_id']}: {drawn_result['frames']} frames, "
                             f"{drawn_result['note']}.", case_id=case["case_id"])
            elif status == "refused":
                self._decide(f"Slot {case['index']} was refused "
                             f"{(result.get('refusals') or ['-'])[0]} "
                             f"({result.get('sentence') or result.get('reason')}); the campaign "
                             f"draws on.", case_id=case["case_id"])
            else:
                self._decide(f"Case {case['case_id']} ended {status}: {result.get('reason')}; a "
                             f"failed capture is retried once by the campaign and a failed "
                             f"verification is a finding, never retried.", case_id=case["case_id"])

        # -- the campaign runs to its target through its own exit criterion ---------------
        final = call("run", case_id=campaign_id, validation_token=token,
                     reason="Run the campaign to its target through its own exit criterion; "
                            "done is written only from the ledger's verified frames.")
        if _refused(final):
            return self._escalate(self._sentence(final), campaign_id, rule=final["refused"])
        if final.get("status") != "done":
            return self._escalate(
                f"The campaign ended {final.get('status')}: {self._sentence(final)}",
                campaign_id, rule=(final.get("refusals") or [None])[0])

        # -- verify the yield against the request ----------------------------------------
        report = call("report", campaign_id=campaign_id,
                      reason="Read the yield, coverage and refusals from the ledger and the "
                             "manifests, never from memory.")
        if _refused(report):
            return self._escalate(self._sentence(report), campaign_id, rule=report["refused"])
        got = int(report["yield"]["frames_verified"])
        rendered_not_verified = int(report["yield"]["cases"].get("rendered", 0))
        coverage = report.get("coverage")
        if got < images:
            return self._escalate(f"{got} verified frames of {images} requested; the campaign "
                                  f"says done but the ledger disagrees.", campaign_id)
        if rendered_not_verified:
            self._decide(f"{rendered_not_verified} captured case(s) did not verify; they are "
                         f"findings, excluded from the yield and the export.", campaign_id=campaign_id)
        self._decide(f"Yield {got} verified frames of {images} in "
                     f"{report['yield']['verified_cases']} case(s)"
                     + (f"; coverage {coverage:.0%} of the requested bins"
                        if isinstance(coverage, (int, float)) else "; no policy, no coverage claim")
                     + "; every exported case passed the verifier.", campaign_id=campaign_id)

        exported = call("export", campaign_id=campaign_id, format=request.format,
                        validation_token=token,
                        reason=f"Export the verified cases as {request.format} with the card.")
        if _refused(exported):
            return self._escalate(self._sentence(exported), campaign_id, rule=exported["refused"])
        sentence = (f"Done: {got} verified frames of {images} in "
                    f"{report['yield']['verified_cases']} case(s), exported as "
                    f"{request.format} to {exported['dataset_path']}"
                    + (" (labels only: no pixels were drawn)." if exported["labels_only"] else "."))
        self._decide(sentence, campaign_id=campaign_id)
        return Outcome("done", sentence, campaign_id=campaign_id,
                       trace_path=str(self.tools.trace.path), steps=list(self.steps),
                       yield_frames=got, dataset_path=exported["dataset_path"])


__all__ = ["Request", "Outcome", "Controller"]
