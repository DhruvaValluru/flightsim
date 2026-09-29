"""The campaign object (contracts §6.1): ``campaign.json``, the state
machine, sampling by index, the worker pool, control polling, the
disk budget, and the one rule the plan names as the exit criterion --
a campaign never reports ``done`` below its target.

Library first: the agent (package H) and the page (package I) call
``Campaign.create(...)``, ``.plan()``, ``.sample(n)``, ``.run(workers)``,
``.pause()``, ``.resume()``, ``.cancel()``, ``.status()``, ``.report()``,
``.export(format)``; ``flightsim.campaign`` is a thin CLI over them.

Refusals are by name (``CampaignError.constraint``): the validator's
own constraint for a spec that cannot fly, the sampler's for a policy
that cannot draw, ``storage.budget_exceeded``, ``campaign.target_unreachable``
(the terminal reason of a campaign that ends ``failed``),
``campaign.state`` (an illegal transition), ``campaign.arguments``
(an argument the campaign cannot honour), ``campaign.duplicate_case``
(a slot that drew a spec another slot already produced -- a prompt
with no variation cannot yield two distinct cases).

Progress, yield and the done/failed verdict are computed FROM THE
LEDGER (:func:`core.campaign.ledger.summarise`) every time they are
asked for; the object holds no counter that could disagree with the
file. A restarted process reports the truth.

Not claimed: the throughput knee for parallel engine instances on one
GPU (no engine here; ``workers`` is a cap, not a measured optimum);
crash recovery of a case killed together with the campaign process
(its ``running`` row stays the latest and ``--resume`` retries it, but
the half-written run directory is overwritten, not inspected);
concurrent campaigns sharing one directory.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from core.dataset.batch import CAPTURE_OPTIONS
from core.scenario.randomization import (
    MAX_SEED, RandomizationError, sample_randomization,
)
from core.scenario.spec import ScenarioSpec

from .ledger import (
    LEDGER, STATUS_FAILED, STATUS_REFUSED, STATUS_RUNNING, STATUS_SAMPLED,
    STATUS_VERIFIED, Ledger, summarise,
)
from .workers import (
    DEFAULT_STALL_SECONDS, RUNS_DIR, build_case, draw_record, run_index,
    sampled_values, utc_now,
)

CAMPAIGN_RECORD = "campaign.json"
CONTROL_FILE = "control.json"
REPORT_FILE = "report.json"
CAMPAIGN_VERSION = 1

PLANNED, RUNNING, PAUSED, FAILED, DONE, CANCELLED = (
    "planned", "running", "paused", "failed", "done", "cancelled")
STATES = (PLANNED, RUNNING, PAUSED, FAILED, DONE, CANCELLED)
#: Every legal move. ``done`` and ``cancelled`` are terminal; ``failed``
#: may resume (the reason is recorded; a resume retries what failed
#: and refuses again by name if nothing changed).
TRANSITIONS: Dict[str, frozenset] = {
    PLANNED: frozenset({RUNNING, CANCELLED}),
    RUNNING: frozenset({PAUSED, FAILED, DONE, CANCELLED}),
    PAUSED: frozenset({RUNNING, CANCELLED}),
    FAILED: frozenset({RUNNING, CANCELLED}),
    DONE: frozenset(),
    CANCELLED: frozenset(),
}
CONTROL_REQUESTS = ("pause", "resume", "cancel")

DEFAULT_SEED = 1
DEFAULT_FORMAT = "coco"
#: The recorder samples every 0.1 s (core/scenario/runner.py L260); a
#: continuous camera captures every sample. Only an ESTIMATE for the
#: first round; the measured count from completed cases replaces it.
RECORDER_INTERVAL_S = 0.1
#: A slot exhausted (``randomization.infeasible``) is a refused row and
#: the campaign draws the next index; after this many refused slots it
#: stops and ends ``failed`` (``campaign.target_unreachable``).
MAX_REFUSED_SLOTS = 20
#: A failed capture is retried this many times in all (a resume counts).
MAX_ATTEMPTS = 2
#: Rounds that added no verified frame before the campaign gives up.
MAX_ROUNDS_WITHOUT_PROGRESS = 2


class CampaignError(ValueError):
    """A named refusal (``constraint``); never a stack trace."""

    def __init__(self, constraint: str, message: str,
                 detail: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.constraint = constraint
        self.message = message
        self.detail = dict(detail or {})


def _write_atomic(path: Path, payload: Dict[str, Any]) -> None:
    """tmp + os.replace (NEXT.md gotcha 30): a reader never sees half."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True, default=str),
                   encoding="utf-8")
    os.replace(tmp, path)


def estimate_frames(spec: ScenarioSpec) -> int:
    """Frames one case is EXPECTED to record, from the spec: per camera,
    a continuous trigger fires every recorder sample; interval fires
    its count or every period; the other triggers at least once. An
    estimate, replaced by the measured count after the first case."""
    from core.scenario.camera import default_cameras

    duration = float(spec.duration.value)
    samples = int(duration / RECORDER_INTERVAL_S) + 1
    total = 0
    for camera in (spec.cameras or default_cameras(spec)):
        trigger = str(camera.trigger.value)
        count = int(camera.capture_count.value)
        if trigger == "continuous":
            total += samples
        elif trigger == "interval":
            if count > 0:
                total += count
            else:
                period = float(camera.period_s.value)
                total += int(duration / period) + 1 if period > 0 else samples
        else:
            total += max(count, 1)
    return max(total, 1)


def _compile(prompt: str, answers, tier: str):
    """The compiled spec and the tier that compiled it. The LLM tier
    falls back to the regex compiler exactly as the web app does, and
    says so in the recorded tier -- never silently."""
    from core.nl.compiler import compile_prompt

    if tier == "llm":
        from core.nl.llm_compiler import LLMCompileError, compile_prompt_llm

        try:
            result = compile_prompt_llm(prompt, answers=answers)
            return result.spec, f"llm ({result.model})"
        except LLMCompileError as exc:
            return (compile_prompt(prompt, answers=answers),
                    f"regex (llm unavailable: {exc})")
    if tier != "regex":
        raise CampaignError("campaign.arguments",
                            f"tier {tier!r} is not one of 'regex', 'llm'")
    return compile_prompt(prompt, answers=answers), "regex"


class Campaign:
    """One campaign directory. Construct through :meth:`create` or
    :meth:`open`; every method reads and writes the directory's files
    so any process holding the path sees the same campaign."""

    def __init__(self, directory, record: Dict[str, Any]) -> None:
        self.dir = Path(directory)
        self.record = record

    # -- construction --------------------------------------------------------

    @classmethod
    def create(cls, prompt: str, answers=None, images: int = 100,
               seed: Optional[int] = None, policy: Optional[Dict[str, Any]] = None,
               out=None, format: str = DEFAULT_FORMAT, workers: int = 1,
               disk_budget_bytes: Optional[int] = None, tier: str = "regex",
               capture: Optional[Dict[str, Any]] = None,
               stall_seconds: Optional[float] = DEFAULT_STALL_SECONDS,
               max_refused_slots: int = MAX_REFUSED_SLOTS) -> "Campaign":
        """Compile the prompt (plus the answer round), apply an explicit
        policy as a user edit, and write ``campaign.json`` in state
        ``planned``. Refuses by name before anything is drawn or run."""
        from core.dataset.export import FORMATS

        if out is None:
            raise CampaignError("campaign.arguments", "an output directory is required")
        out = Path(out)
        if (out / CAMPAIGN_RECORD).is_file():
            raise CampaignError(
                "campaign.arguments",
                f"{out} already holds a campaign; open it (Campaign.open / "
                f"--resume) or choose another directory")
        if not isinstance(images, int) or isinstance(images, bool) or images < 1:
            raise CampaignError("campaign.arguments",
                                f"--images must be an integer >= 1, got {images!r}")
        if not isinstance(workers, int) or isinstance(workers, bool) or workers < 1:
            raise CampaignError("campaign.arguments",
                                f"--workers must be an integer >= 1, got {workers!r}")
        if format not in FORMATS:
            raise CampaignError("export.format",
                                f"format {format!r} is not one of {list(FORMATS)}")
        if disk_budget_bytes is not None and (
                not isinstance(disk_budget_bytes, int) or disk_budget_bytes < 1):
            raise CampaignError("campaign.arguments",
                                "the disk budget must be a positive number of bytes")
        capture = dict(capture or {})
        for key, value in capture.items():
            kind = CAPTURE_OPTIONS.get(key)
            if kind is None or not isinstance(value, kind) or (
                    kind is int and isinstance(value, bool)):
                raise CampaignError("campaign.arguments",
                                    f"capture option {key!r}={value!r} is not one "
                                    f"the capture CLI has ({sorted(CAPTURE_OPTIONS)})")
        capture.setdefault("max_previews", 0)
        capture.setdefault("card", True)

        spec, tier_used = _compile(str(prompt), answers, tier)
        if policy is not None:
            spec.set("randomization.policy", policy, frm="campaign policy (given)")

        # The campaign seed IS the block's seed (contracts §5.6): a seed
        # the prompt states is kept; an argument that disagrees with it
        # is refused rather than moving a stated value.
        block_seed = spec.randomization.seed
        stated = str(block_seed.source) in ("user", "inferred")
        if seed is None:
            seed = int(block_seed.value) if stated else DEFAULT_SEED
        if not isinstance(seed, int) or isinstance(seed, bool) or not (1 <= seed <= MAX_SEED):
            raise CampaignError("campaign.arguments",
                                f"--seed must be an integer in 1..{MAX_SEED}, got {seed!r}")
        if stated and int(block_seed.value) != seed:
            raise CampaignError(
                "campaign.arguments",
                f"the prompt states randomization.seed {int(block_seed.value)} "
                f"({block_seed.frm}) and --seed says {seed}; a stated value is "
                f"never moved -- drop one")

        from core.experiments.manifest import git_provenance

        record = {
            "campaign_version": CAMPAIGN_VERSION,
            "id": out.name,
            "prompt": str(prompt),
            "answers": [dict(a) for a in (answers or [])],
            "tier": tier_used,
            "spec": spec.to_dict(),
            "spec_digest": spec.digest(),
            "policy": (spec.randomization_policy.value
                       if spec.randomization_policy is not None else None),
            "images_target": int(images),
            "seed": int(seed),
            "state": PLANNED,
            "reason": None,
            "workers": int(workers),
            "disk_budget_bytes": disk_budget_bytes,
            "format": format,
            "capture": capture,
            "stall_seconds": stall_seconds,
            "max_refused_slots": int(max_refused_slots),
            "created_utc": utc_now(),
            "updated_utc": utc_now(),
            "started_utc": None,
            "finished_utc": None,
            "plan": None,
            "git": git_provenance(),
        }
        out.mkdir(parents=True, exist_ok=True)
        (out / RUNS_DIR).mkdir(exist_ok=True)
        campaign = cls(out, record)
        campaign._save()
        return campaign

    @classmethod
    def open(cls, directory) -> "Campaign":
        directory = Path(directory)
        path = directory / CAMPAIGN_RECORD
        if not path.is_file():
            raise CampaignError("campaign.arguments",
                                f"{directory} holds no {CAMPAIGN_RECORD}")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CampaignError("campaign.arguments",
                                f"{path} is not readable JSON: {exc}") from exc
        if not isinstance(record, dict) or record.get("state") not in STATES:
            raise CampaignError("campaign.arguments",
                                f"{path} is not a campaign record")
        return cls(directory, record)

    # -- files ---------------------------------------------------------------

    @property
    def ledger(self) -> Ledger:
        return Ledger(self.dir / LEDGER)

    @property
    def state(self) -> str:
        return str(self.record["state"])

    @property
    def target(self) -> int:
        return int(self.record["images_target"])

    def _save(self) -> None:
        self.record["updated_utc"] = utc_now()
        _write_atomic(self.dir / CAMPAIGN_RECORD, self.record)

    def _reload(self) -> None:
        self.record = json.loads((self.dir / CAMPAIGN_RECORD).read_text(encoding="utf-8"))

    def _transition(self, new_state: str, reason: Optional[str] = None) -> None:
        current = self.state
        if new_state not in TRANSITIONS.get(current, frozenset()):
            raise CampaignError(
                "campaign.state",
                f"a {current} campaign cannot become {new_state} (legal: "
                f"{sorted(TRANSITIONS.get(current, ()))})")
        self.record["state"] = new_state
        self.record["reason"] = reason
        if new_state == RUNNING and not self.record.get("started_utc"):
            self.record["started_utc"] = utc_now()
        if new_state in (DONE, FAILED, CANCELLED):
            self.record["finished_utc"] = utc_now()
        self._save()

    def _spec(self) -> ScenarioSpec:
        return ScenarioSpec.from_dict(self.record["spec"])

    # -- control.json ---------------------------------------------------------

    def _control(self) -> Optional[str]:
        path = self.dir / CONTROL_FILE
        if not path.is_file():
            return None
        try:
            request = json.loads(path.read_text(encoding="utf-8")).get("request")
        except (OSError, ValueError, AttributeError):
            return None
        return request if request in CONTROL_REQUESTS else None

    def _write_control(self, request: str) -> None:
        _write_atomic(self.dir / CONTROL_FILE,
                      {"request": request, "requested_utc": utc_now()})

    def _clear_control(self) -> None:
        try:
            (self.dir / CONTROL_FILE).unlink()
        except FileNotFoundError:
            pass

    # -- the plan -------------------------------------------------------------

    def plan(self) -> Dict[str, Any]:
        """Validate the compiled spec (refused by the violation's name),
        probe the policy once (a defect -- shape, vocabulary, a range
        with no bake -- is refused by name before any worker starts;
        an exhausted slot is not a defect, it is the run's business),
        and estimate: frames per case, cases needed, the disk picture.
        Recorded in ``campaign.json`` under ``plan``."""
        from core.scenario.validate import validate

        spec = self._spec()
        report = validate(spec)
        if not report.ok:
            first = report.violations[0]
            raise CampaignError(
                first.constraint,
                "; ".join(f"{v.constraint}: {v.render()}" for v in report.violations))
        probe = deepcopy(spec)
        try:
            sample_randomization(probe, draw_index=0)
            probe_note = "slot 0 draws"
        except RandomizationError as exc:
            if exc.constraint != "randomization.infeasible":
                raise CampaignError(exc.constraint, exc.message,
                                    detail=exc.detail) from exc
            probe_note = f"slot 0 refused {exc.constraint}; the run draws on"
        summary = summarise(self.ledger.rows())
        frames_estimate = estimate_frames(spec)
        measured = self._measured_frames(summary)
        per_case = measured or frames_estimate
        remaining_frames = max(0, self.target - summary["frames_verified"])
        plan = {
            "spec_digest": self.record["spec_digest"],
            "policy": self.record.get("policy"),
            "images_target": self.target,
            "frames_per_case": {"estimate": frames_estimate, "measured": measured,
                                "basis": ("measured over completed cases" if measured
                                          else f"recorder cadence {RECORDER_INTERVAL_S} s")},
            "cases_needed": int(math.ceil(remaining_frames / per_case)) if remaining_frames else 0,
            "frames_verified": summary["frames_verified"],
            "probe": probe_note,
            "disk": self._disk_picture(summary, per_case),
            "seed_derivation": "SeedSequence([index, campaign_seed])",
        }
        self.record["plan"] = plan
        self._save()
        return plan

    def _measured_frames(self, summary: Dict[str, Any]) -> Optional[int]:
        rows = [r for r in self.ledger.latest().values()
                if r.get("ok") and int(r.get("frames") or 0) > 0]
        if not rows:
            return None
        return int(round(sum(int(r["frames"]) for r in rows) / len(rows)))

    def _disk_picture(self, summary: Dict[str, Any], per_case: int) -> Dict[str, Any]:
        usage = shutil.disk_usage(str(self.dir))
        bytes_per_case = summary.get("bytes_per_case")
        remaining_frames = max(0, self.target - summary["frames_verified"])
        remaining_cases = int(math.ceil(remaining_frames / per_case)) if remaining_frames else 0
        projected = (bytes_per_case * remaining_cases) if bytes_per_case else None
        budget = self.record.get("disk_budget_bytes")
        limit = usage.free if budget is None else min(int(budget), usage.free)
        return {"bytes_per_case": bytes_per_case,
                "measured_over": summary.get("bytes_measured_over", 0),
                "remaining_cases": remaining_cases,
                "projected_bytes": projected,
                "budget_bytes": budget, "free_bytes": usage.free,
                "limit_bytes": limit,
                "within_budget": (projected <= limit) if projected is not None else None}

    def _check_disk(self, summary: Dict[str, Any], per_case: int) -> None:
        """Refuse ``storage.budget_exceeded`` by name when the measured
        bytes per case times the cases still to run exceed the budget
        or the free space. Unmeasured (no completed case) -> no claim."""
        picture = self._disk_picture(summary, per_case)
        if picture["within_budget"] is False:
            raise CampaignError(
                "storage.budget_exceeded",
                f"{picture['remaining_cases']} case(s) still to run at a measured "
                f"{picture['bytes_per_case']} bytes each need "
                f"{picture['projected_bytes']} bytes; the limit is "
                f"{picture['limit_bytes']} bytes ("
                + ("the stated budget" if picture["budget_bytes"] is not None
                   and picture["limit_bytes"] == picture["budget_bytes"]
                   else "free disk")
                + ")", detail=picture)

    # -- sampling ---------------------------------------------------------------

    def sample(self, n: int, start: Optional[int] = None,
               record: bool = True) -> Dict[str, Any]:
        """Draw slots ``start .. start+n-1`` in this process (the same
        function the workers run): the cases and the refused slots by
        name. With ``record``, a slot the ledger has never seen gets a
        ``sampled`` or ``refused`` row; a slot already past that stage
        is never regressed."""
        if start is None:
            start = summarise(self.ledger.rows())["next_index"]
        known = self.ledger.latest() if record else {}
        cases: List[Dict[str, Any]] = []
        refused: List[Dict[str, Any]] = []
        for index in range(int(start), int(start) + int(n)):
            try:
                spec, seed = build_case(index, self.record)
            except RandomizationError as exc:
                row = {"index": index, "status": STATUS_REFUSED,
                       "refusals": [exc.constraint], "reason": exc.message,
                       "refused_attempts": exc.detail.get("refusals", []),
                       "campaign_seed": self.record["seed"],
                       "ok": False, "verified": False, "frames": 0, "yield": 0,
                       "started_utc": utc_now(), "finished_utc": utc_now()}
                refused.append(row)
            else:
                draws = draw_record(spec)
                row = {"index": index, "status": STATUS_SAMPLED,
                       "case_id": spec.digest()[:16], "run_id": spec.digest()[:16],
                       "spec_digest": spec.digest(), "seed": seed,
                       "campaign_seed": self.record["seed"],
                       "sampled": sampled_values(spec),
                       "policy_attempts": int(draws.get("attempts", 0)) if draws else 0,
                       "refusals": sorted({str(r.get("refusal_name"))
                                           for r in draws.get("refused", [])}) if draws else [],
                       "started_utc": utc_now()}
                cases.append(row)
            if record and index not in known:
                self.ledger.append(row)
        return {"cases": cases, "refused": refused,
                "next_index": int(start) + int(n)}

    # -- the run ---------------------------------------------------------------

    def run(self, workers: Optional[int] = None,
            progress: Optional[Callable[[str], None]] = None,
            capture_runner: Optional[str] = None) -> Dict[str, Any]:
        """Run to the target or to a named end. Returns :meth:`status`.

        Cases are pulled BY INDEX from a queue by ``workers`` processes
        (``spawn``); each completion appends its row, then the control
        file is polled (pause / cancel) and the disk budget re-checked.
        Rounds: the indices a round runs are decided from the ledger
        when it starts, so the sequence is the same at any worker
        count; a round ends when its last case returns. A campaign
        ends ``done`` only when the ledger's verified frames reach the
        target; otherwise ``failed`` with ``campaign.target_unreachable``
        and the reasons, ``paused`` or ``cancelled`` on request, or
        ``failed`` with ``storage.budget_exceeded``.
        """
        self._reload()
        if self.record.get("plan") is None or self.state in (PLANNED, FAILED, PAUSED):
            self.plan()
        n_workers = max(1, int(workers or self.record.get("workers") or 1))
        if self._control() == "cancel":
            self._clear_control()
            self._transition(CANCELLED, "cancel requested before the run started")
            return self.status()
        self._clear_control()
        self._transition(RUNNING)
        self.record["workers"] = n_workers
        self._save()
        try:
            self._rounds(n_workers, progress, capture_runner)
        except CampaignError as exc:
            if self.state == RUNNING:
                self._transition(FAILED, f"{exc.constraint}: {exc.message}")
            raise
        except BaseException as exc:
            # Not a named refusal (a broken pool, a KeyboardInterrupt):
            # the record must not go on saying "running" for a process
            # that is gone. The ledger's running rows are retried on
            # resume.
            if self.state == RUNNING:
                self._transition(FAILED, f"{type(exc).__name__}: {exc}")
            raise
        return self.status()

    def _rounds(self, n_workers: int, progress, capture_runner) -> None:
        stalled_rounds = 0
        while True:
            summary = summarise(self.ledger.rows())
            verified = summary["frames_verified"]
            if verified >= self.target:
                # The one place ``done`` is written: yield measured from
                # the ledger at or above the target, nothing else.
                self._transition(DONE, f"{verified} verified frame(s) of {self.target}")
                return
            refused_slots = summary["cases"][STATUS_REFUSED]
            reasons = self._unreachable_reasons(summary, refused_slots, stalled_rounds)
            if reasons:
                self._transition(FAILED, "campaign.target_unreachable: " + "; ".join(reasons))
                raise CampaignError("campaign.target_unreachable", "; ".join(reasons),
                                    detail={"summary": summary})
            per_case = self._measured_frames(summary) or estimate_frames(self._spec())
            self._check_disk(summary, per_case)          # before starting / per round
            need = int(math.ceil((self.target - verified) / per_case))
            indices = self._round_indices(summary, need)
            before = verified
            outcome = self._execute(indices, n_workers, per_case, progress, capture_runner)
            if outcome in ("paused", "cancelled"):
                return
            after = summarise(self.ledger.rows())["frames_verified"]
            stalled_rounds = stalled_rounds + 1 if after <= before else 0

    def _unreachable_reasons(self, summary, refused_slots, stalled_rounds) -> List[str]:
        reasons: List[str] = []
        limit = int(self.record.get("max_refused_slots") or MAX_REFUSED_SLOTS)
        if refused_slots >= limit:
            # The slot's own name first, then the constraints its draws
            # hit (what the policy must be narrowed against).
            within = summary.get("refused_attempt_names") or {}
            reasons.append(f"{refused_slots} slot(s) refused "
                           f"({', '.join(f'{k} x{v}' for k, v in summary['refusals'].items()) or 'no names'}"
                           + (f"; their draws were refused "
                              f"{', '.join(f'{k} x{v}' for k, v in within.items())}"
                              if within else "")
                           + f"); the limit is {limit} -- narrow the policy"
                           + (f" against {', '.join(within)}" if within else ""))
        if stalled_rounds >= MAX_ROUNDS_WITHOUT_PROGRESS:
            reasons.append(f"{stalled_rounds} round(s) added no verified frame: "
                           f"{summary['failed_captures']} failed capture(s), "
                           f"{summary['unverified']} captured but not verified, "
                           f"{summary['frames_verified']} of {self.target} frames")
        return reasons

    def _round_indices(self, summary: Dict[str, Any], need: int) -> List[int]:
        """Retries first, then fresh indices. Retried: a ``sampled``
        preview that never ran; a ``running`` row a dead process left
        (one more go); a ``failed`` capture with attempts left. Never
        retried: a refused slot, a verified case, a captured-but-
        unverified case (a finding, batch semantics)."""
        if need <= 0:
            return []
        latest = self.ledger.latest()
        retries: List[int] = []
        for index in sorted(latest):
            row = latest[index]
            status, attempt = row.get("status"), int(row.get("attempt") or 0)
            if status == STATUS_SAMPLED:
                retries.append(index)
            elif status == STATUS_RUNNING and attempt <= MAX_ATTEMPTS:
                retries.append(index)
            elif status == STATUS_FAILED and attempt < MAX_ATTEMPTS:
                retries.append(index)
        fresh = list(range(summary["next_index"],
                           summary["next_index"] + max(0, need - len(retries))))
        return (retries + fresh)[:need]

    def _execute(self, indices: Sequence[int], n_workers: int, per_case: int,
                 progress, capture_runner) -> str:
        """One round: a window of ``n_workers`` cases in flight, pulled
        from ``indices`` in order. Returns 'completed', 'paused' or
        'cancelled'; raises the disk refusal AFTER every case in flight
        has returned and been ledgered."""
        latest = self.ledger.latest()
        queue = list(indices)
        stall = self.record.get("stall_seconds")
        attempts = {i: int(latest.get(i, {}).get("attempt") or 0) for i in queue}
        # {case_id: the LOWEST index holding it}: the keeper of a spec two
        # slots drew is decided by index, never by which finished first,
        # so the ledger is the same at any worker count.
        seen_case_ids: Dict[str, int] = {}
        for i in sorted(latest):
            r = latest[i]
            if r.get("case_id") and r.get("status") != STATUS_REFUSED:
                seen_case_ids.setdefault(str(r["case_id"]), i)
        stop: Any = None             # None | 'paused' | 'cancelled' | CampaignError

        def dispatch_row(index: int) -> int:
            attempts[index] = attempts.get(index, 0) + 1
            self.ledger.append({"index": index, "status": STATUS_RUNNING,
                                "attempt": attempts[index],
                                "campaign_seed": self.record["seed"],
                                "started_utc": utc_now()})
            return attempts[index]

        def claim_case(index: int) -> None:
            """Before a slot is dispatched beside slots still in flight:
            its case id (built from the index, deterministic) is claimed
            for the lowest index that drew it, so a duplicate dispatched
            in the same window refuses itself in the worker before
            running -- the same row, at the same index, as at one worker.
            A slot the sampler refuses claims nothing (the worker
            writes its refused row)."""
            try:
                spec, _seed = build_case(index, self.record)
            except RandomizationError:
                return
            case_id = spec.digest()[:16]
            seen_case_ids[case_id] = min(index, seen_case_ids.get(case_id, index))

        def collect(row: Dict[str, Any]) -> Optional[int]:
            """Append the row; return an index to re-queue, if any."""
            index = int(row["index"])
            case_id = row.get("case_id") if row.get("status") != STATUS_REFUSED else None
            other = seen_case_ids.get(case_id, index) if case_id else index
            if case_id and other < index:
                # The safety net for a case that was in flight beside its
                # keeper: the lower index keeps the spec, whatever finished
                # first.
                row = {**row, "status": STATUS_REFUSED, "yield": 0,
                       "refusals": ["campaign.duplicate_case"],
                       "reason": (f"slot {index} drew the spec slot {other} already "
                                  f"produced ({case_id}); the prompt leaves nothing "
                                  f"to vary between them")}
            elif case_id:
                seen_case_ids[case_id] = index
            self.ledger.append(row)
            if progress:
                progress(f"[{index}] {row.get('case_id', '-')} {row['status']} "
                         f"frames={row.get('frames', 0)} yield={row.get('yield', 0)} "
                         f"({float(row.get('wall_seconds', 0)):.1f} s)"
                         + (f" -- {row['reason']}" if row.get("reason") else ""))
            if row.get("requeue") and attempts.get(index, 1) < MAX_ATTEMPTS:
                return index
            return None

        def after_completion() -> Any:
            """Between cases: the control file, then the disk budget."""
            request = self._control()
            if request == "cancel":
                return "cancelled"
            if request == "pause":
                return "paused"
            summary = summarise(self.ledger.rows())
            try:
                self._check_disk(summary, self._measured_frames(summary) or per_case)
            except CampaignError as exc:
                return exc
            return None

        if n_workers == 1:
            while queue and stop is None:
                index = queue.pop(0)
                attempt = dispatch_row(index)
                row = run_index(index, self.record, str(self.dir), attempt, stall,
                                capture_runner, dict(seen_case_ids))
                again = collect(row)
                if again is not None:
                    queue.insert(0, again)
                stop = after_completion()
        else:
            import multiprocessing

            context = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(max_workers=n_workers, mp_context=context) as pool:
                in_flight: Dict[Any, int] = {}
                while queue or in_flight:
                    while queue and len(in_flight) < n_workers and stop is None:
                        index = queue.pop(0)
                        claim_case(index)      # by index, before anything is in flight with it
                        attempt = dispatch_row(index)
                        future = pool.submit(run_index, index, self.record, str(self.dir),
                                             attempt, stall, capture_runner,
                                             dict(seen_case_ids))
                        in_flight[future] = index
                    if not in_flight:
                        break
                    finished, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
                    for future in finished:
                        del in_flight[future]
                        again = collect(future.result())
                        if again is not None and stop is None:
                            queue.insert(0, again)
                    if stop is None:
                        stop = after_completion()
        if isinstance(stop, CampaignError):
            raise stop
        if stop == "paused":
            self._clear_control()
            self._transition(PAUSED, "pause requested")
        elif stop == "cancelled":
            self._clear_control()
            self._transition(CANCELLED, "cancel requested")
        return stop or "completed"

    # -- control -----------------------------------------------------------------

    def pause(self) -> Dict[str, Any]:
        """Ask the running process to stop after the cases in flight.
        Only a running campaign can pause (``campaign.state``)."""
        self._reload()
        if self.state != RUNNING:
            raise CampaignError("campaign.state",
                                f"a {self.state} campaign cannot pause; only running")
        self._write_control("pause")
        return self.status()

    def resume(self, workers: Optional[int] = None, **kw) -> Dict[str, Any]:
        """Continue from the ledger: verified cases are kept, failed
        captures retried (once), refused slots stay refused; the target
        is still the target."""
        self._reload()
        if self.state not in (PLANNED, PAUSED, FAILED):
            raise CampaignError("campaign.state",
                                f"a {self.state} campaign cannot resume "
                                f"(planned, paused or failed can)")
        self._clear_control()
        return self.run(workers=workers, **kw)

    def cancel(self) -> Dict[str, Any]:
        """Cancel: a running campaign is asked to stop after the cases
        in flight (control.json); any other resumable state is cancelled
        here and now. Terminal."""
        self._reload()
        if self.state == RUNNING:
            self._write_control("cancel")
            return self.status()
        self._transition(CANCELLED, "cancelled")
        return self.status()

    # -- reading ---------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """The state and the ledger's numbers -- nothing from memory."""
        self._reload()
        summary = summarise(self.ledger.rows())   # the ledger, never a counter
        return {
            "id": self.record["id"], "state": self.state,
            "reason": self.record.get("reason"),
            "images_target": self.target,
            "frames_verified": summary["frames_verified"],
            "frames_captured": summary["frames_captured"],
            "fraction": round(min(1.0, summary["frames_verified"] / self.target), 4),
            "cases": summary["cases"], "indices": summary["indices"],
            "refusals": summary["refusals"],
            "refused_attempt_names": summary["refused_attempt_names"],
            "control": self._control(),
            "workers": self.record.get("workers"),
        }

    def report(self) -> Dict[str, Any]:
        from .report import build_report

        payload = build_report(self)
        _write_atomic(self.dir / REPORT_FILE, payload)
        return payload

    def verified_run_dirs(self) -> List[Path]:
        return [Path(p) for p in summarise(self.ledger.rows())["verified_run_dirs"]]

    def export(self, format: Optional[str] = None, labels_only: Optional[bool] = None,
               out=None, **kw) -> Dict[str, Any]:
        """Export every VERIFIED case through ``core.dataset.export``
        into ``<campaign>/datasets/<format>`` (the export's own refusals
        stand: unverified, missing frames, an unknown format). Frames
        drawn on no case -> a labels-only export unless told otherwise."""
        from core.dataset.export import export as export_dataset

        fmt = format or self.record.get("format") or DEFAULT_FORMAT
        runs = self.verified_run_dirs()
        if labels_only is None:
            drawn = any(r.get("drawn") for r in self.ledger.latest().values()
                        if r.get("status") == STATUS_VERIFIED)
            labels_only = not drawn
        target = Path(out) if out else self.dir / "datasets" / fmt
        card = export_dataset(runs, target, fmt, labels_only=labels_only, **kw)
        return {"dataset_path": str(target), "card": card, "runs": len(runs),
                "labels_only": labels_only}
