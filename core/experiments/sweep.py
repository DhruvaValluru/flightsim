"""Parameter sweeps: factorial and one-at-a-time, crash-safe and resumable.

Ported from the previous build's ``experiment.py``, which §8 marks as the
strongest work in that repository and worth keeping largely as-is. What is kept
is the design; what changes is that cases are now built from the Phase 1
scenario spec rather than from a bespoke dict, so a sweep case *is* a spec and
inherits its validation, its provenance and its digest.

The crash-safe append log
-------------------------
Results are appended to a JSONL file, one line per completed case, flushed
immediately. A sweep that dies at case 63 of 108 leaves 62 usable results and
resumes at 63. Nothing is held in memory until the end, and no case is ever
recomputed because a later one failed.

Resumption keys on a **content-derived case id**, not on position. Re-running a
sweep whose design has changed therefore recomputes the cases that actually
changed and reuses the rest, instead of silently pairing new parameters with old
results because they happen to be the seventh line.

Degenerate replication
----------------------
Replicates only buy information if the condition being repeated is actually
stochastic. The previous build found that a "turbulence sweep" produced
bit-identical replicates because JSBSim's Dryden turbulence was not seeded from
the spec's seed at all -- three times the compute for one result. That is
measured here rather than assumed away: :func:`degenerate_replicates` reports
any case whose replicates agree exactly on every metric.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence

from ..scenario.spec import ScenarioSpec
from .seeds import SeedSet, derive


@dataclass(frozen=True)
class Factor:
    """One swept parameter: a spec field and the levels it takes."""

    field: str
    levels: Sequence[Any]
    #: Level used when this factor is not the one being varied, in an OAT
    #: design. Defaults to the middle level.
    centre: Optional[Any] = None

    def centre_level(self) -> Any:
        if self.centre is not None:
            return self.centre
        return self.levels[len(self.levels) // 2]

    def to_dict(self) -> Dict[str, Any]:
        return {"field": self.field, "levels": list(self.levels),
                "centre": self.centre_level()}


@dataclass(frozen=True)
class Case:
    """One cell of the design, at one replicate."""

    overrides: Dict[str, Any]
    replicate: int
    seeds: SeedSet

    @property
    def case_id(self) -> str:
        """Content-derived identity.

        Position in the design would be fragile: inserting a level shifts every
        later case and a resumed sweep would pair new parameters with old
        results.
        """
        payload = json.dumps(
            {"overrides": self.overrides, "replicate": self.replicate},
            sort_keys=True, separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def apply_to(self, base: ScenarioSpec) -> ScenarioSpec:
        """A copy of ``base`` with this case's overrides applied."""
        spec = ScenarioSpec.from_dict(base.to_dict())
        for field_name, value in self.overrides.items():
            spec.set(field_name, value, frm=f"swept ({self.case_id})")
        spec.set("seed", self.seeds.for_subsystem("turbulence"),
                 frm=f"derived for replicate {self.replicate}")
        return spec

    def to_dict(self) -> Dict[str, Any]:
        return {"case_id": self.case_id, "replicate": self.replicate,
                **{f"factor.{k}": v for k, v in self.overrides.items()}}


class Design:
    """A set of factors and a rule for combining them."""

    FACTORIAL = "factorial"
    OAT = "one-at-a-time"

    def __init__(self, factors: Sequence[Factor], kind: str = FACTORIAL,
                 replicates: int = 1, experiment_seed: int = 20260805) -> None:
        if kind not in (self.FACTORIAL, self.OAT):
            raise ValueError(f"unknown design {kind!r}")
        if not factors:
            raise ValueError("a design needs at least one factor")
        if replicates < 1:
            raise ValueError("replicates must be at least 1")
        self.factors = list(factors)
        self.kind = kind
        self.replicates = replicates
        self.experiment_seed = experiment_seed

    def cells(self) -> List[Dict[str, Any]]:
        """The parameter combinations, before replication."""
        if self.kind == self.FACTORIAL:
            names = [f.field for f in self.factors]
            return [dict(zip(names, combo))
                    for combo in itertools.product(*(f.levels for f in self.factors))]

        # One-at-a-time: vary each factor around a common centre. Cheap and
        # linear in the number of factors, but it measures no interactions --
        # which is why §7.5 uses it for screening rather than for attribution.
        centre = {f.field: f.centre_level() for f in self.factors}
        cells = [dict(centre)]
        for factor in self.factors:
            for level in factor.levels:
                if level == factor.centre_level():
                    continue
                cell = dict(centre)
                cell[factor.field] = level
                cells.append(cell)
        return cells

    def cases(self) -> List[Case]:
        out = []
        for cell in self.cells():
            for replicate in range(self.replicates):
                out.append(Case(overrides=cell, replicate=replicate,
                                seeds=derive(self.experiment_seed, replicate)))
        return out

    def size(self) -> int:
        return len(self.cells()) * self.replicates

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "replicates": self.replicates,
            "experiment_seed": self.experiment_seed,
            "factors": [f.to_dict() for f in self.factors],
            "cells": len(self.cells()),
            "cases": self.size(),
        }


class ResultLog:
    """An append-only JSONL log, flushed per line.

    Flushing every line is the difference between a sweep that survives a crash
    and one that loses everything after the last buffer flush. A sweep is long
    and the failure it must tolerate is being killed part-way.
    """

    def __init__(self, path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def completed_ids(self) -> set:
        """Case ids already recorded. Tolerates a truncated final line.

        A process killed mid-write leaves a partial line. Discarding it and
        keeping everything before is correct; refusing to load the file at all
        would throw away a whole sweep because of one interrupted append.
        """
        if not self.path.exists():
            return set()
        done = set()
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(json.loads(line)["case_id"])
                except (json.JSONDecodeError, KeyError):
                    continue
        return done

    def truncate(self) -> None:
        """Discard the log. Used when a sweep is explicitly NOT resuming.

        ``resume=False`` has to mean "start fresh", not merely "do not skip".
        Appending to an existing log leaves stale rows from the previous run in
        the dataset, and since analysis groups by factor level rather than by
        row position, those duplicates are silently folded into every mean and
        every eta-squared. Measured: a re-run of an 18-case design produced a
        32-row dataset that still looked plausible.
        """
        if self.path.exists():
            self.path.unlink()

    def append(self, record: Dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            fh.flush()

    def rows(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out


@dataclass
class SweepResult:
    design: Design
    log: ResultLog
    completed: int
    skipped: int
    failed: int

    @property
    def rows(self) -> List[Dict[str, Any]]:
        return self.log.rows()

    def duplicate_case_ids(self) -> List[str]:
        """Case ids appearing more than once. Should always be empty.

        A duplicated case is a silently double-counted observation.
        """
        seen, duplicates = set(), []
        for row in self.rows:
            case_id = row.get("case_id")
            if case_id in seen:
                duplicates.append(case_id)
            seen.add(case_id)
        return duplicates


def run_sweep(
    design: Design,
    base_spec: ScenarioSpec,
    evaluate: Callable[[ScenarioSpec, Case], Dict[str, Any]],
    out_dir,
    resume: bool = True,
    progress: Optional[Callable[[str], None]] = None,
) -> SweepResult:
    """Execute a design, appending one line per case.

    ``evaluate`` runs a case and returns its metrics. It is passed in rather
    than hardcoded so a sweep can measure whatever the experiment is about,
    and so the harness itself is testable without running a simulation.
    """
    out_dir = Path(out_dir)
    log = ResultLog(out_dir / "dataset.jsonl")
    if resume:
        done = log.completed_ids()
    else:
        # Not resuming means starting fresh, which means the previous dataset
        # goes away rather than being appended to.
        log.truncate()
        done = set()

    (out_dir / "design.json").write_text(json.dumps(design.to_dict(), indent=1), encoding="utf-8")

    completed = skipped = failed = 0
    for index, case in enumerate(design.cases(), start=1):
        if case.case_id in done:
            skipped += 1
            continue
        spec = case.apply_to(base_spec)
        record: Dict[str, Any] = {
            **case.to_dict(),
            "spec_digest": spec.digest(),
            "seeds": case.seeds.to_dict(),
        }
        started = time.monotonic()
        try:
            record.update(evaluate(spec, case))
            record["ok"] = True
            completed += 1
        except Exception as exc:
            # A failed case is recorded, not dropped. A sweep that silently
            # omits its failures reports a success rate of 100%.
            record["ok"] = False
            record["error"] = f"{type(exc).__name__}: {exc}"
            failed += 1
        record["wall_seconds"] = round(time.monotonic() - started, 4)
        log.append(record)
        if progress:
            progress(f"[{index}/{design.size()}] {case.case_id} "
                     f"{'ok' if record['ok'] else 'FAILED'}")

    return SweepResult(design, log, completed, skipped, failed)


def degenerate_replicates(rows: Sequence[Dict[str, Any]],
                          metrics: Sequence[str]) -> List[Dict[str, Any]]:
    """Cases whose replicates agree exactly on every metric.

    Zero spread across replicates means the condition is not stochastic and the
    replication bought nothing. The previous build paid 3x compute for this on
    a turbulence sweep whose turbulence was not seeded from the spec at all, so
    it is measured rather than assumed.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        if not row.get("ok"):
            continue
        factors = {k: v for k, v in row.items() if k.startswith("factor.")}
        key = json.dumps(factors, sort_keys=True)
        groups.setdefault(key, []).append(row)

    degenerate = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        varying = []
        for metric in metrics:
            values = [r.get(metric) for r in group if isinstance(r.get(metric), (int, float))]
            if len(values) >= 2 and max(values) != min(values):
                varying.append(metric)
        if not varying:
            degenerate.append({
                "factors": json.loads(key),
                "replicates": len(group),
                "note": "every metric identical across replicates; "
                        "this condition is not stochastic",
            })
    return degenerate
