"""Batch execution: a matrix of specs, run and verified, one ledger.

A matrix file names a base spec, the factors to vary (spec field
addresses and their levels -- ``altitude``, ``cameras[0].focal_length_mm``,
``randomization.enabled`` all work, through the spec's own ``set()``),
and the run seeds each cell is flown at::

    base: examples/cameras_multi.yaml
    design: factorial            # or one-at-a-time
    factors:
      - field: altitude
        levels: [1500, 3000]
      - field: randomization.enabled
        levels: [true]
    seeds: [1, 2, 3]
    workers: 2
    capture: {card: true, render: false, max_previews: 0}

Every cell x seed is a spec; its run id is the spec's own digest, so
the same cell flown twice lands in the same directory and a resumed
batch skips it (content-addressed, not positional: inserting a level
recomputes nothing that did not change). Each run is one
``flightsim.capture`` subprocess with the matrix's capture options,
then verified in-process and its ``verification.json`` written -- the
export refuses a run without one. The ledger (``ledger.jsonl``) gets
one line per run, flushed as it completes, failures included: a batch
that drops its failures reports a success rate of 100%. ``workers``
caps how many captures run at once.

Nothing here is a second implementation of a capture or a verify: the
capture is the CLI, the verifier is ``core.capture.verify.verify_run``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from core.experiments.sweep import Design, Factor, ResultLog
from core.scenario.randomization import RandomizationError, sample_randomization
from core.scenario.spec import ScenarioSpec

REPO = Path(__file__).resolve().parents[2]

MATRIX_KEYS = {"base", "factors", "seeds", "design", "workers", "capture"}
CAPTURE_OPTIONS = {"card": bool, "render": bool, "void": bool,
                   "no_host_flight": bool, "max_previews": int}
LEDGER = "ledger.jsonl"
BATCH_RECORD = "batch.json"


class BatchError(ValueError):
    """A named refusal (``constraint``) before any run is started."""

    def __init__(self, constraint: str, message: str):
        super().__init__(message)
        self.constraint = constraint
        self.message = message


@dataclass
class Matrix:
    base: Path
    factors: List[Factor]
    seeds: List[int]
    design: str = Design.FACTORIAL
    workers: int = 1
    capture: Dict[str, Any] = dc_field(default_factory=dict)
    path: Optional[Path] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base": str(self.base),
            "design": self.design,
            "factors": [f.to_dict() for f in self.factors],
            "seeds": list(self.seeds),
            "workers": self.workers,
            "capture": dict(self.capture),
        }


def read_matrix(path) -> Matrix:
    """Parse and refuse by name: unknown keys, a missing base, seeds
    that are not integers, a workers count below one, a capture
    option the CLI does not have."""
    path = Path(path)
    if not path.is_file():
        raise BatchError("batch.matrix", f"no matrix file at {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise BatchError("batch.matrix", f"{path.name} is not a mapping")
    unknown = set(data) - MATRIX_KEYS
    if unknown:
        raise BatchError("batch.matrix",
                         f"{path.name} carries unknown keys {sorted(unknown)}; "
                         f"known: {sorted(MATRIX_KEYS)}")
    if "base" not in data:
        raise BatchError("batch.base", f"{path.name} names no base spec")
    base = Path(data["base"])
    if not base.is_absolute():
        base = (path.parent / base).resolve()
    if not base.is_file():
        raise BatchError("batch.base", f"base spec {base} does not exist")
    factors = []
    for entry in data.get("factors") or []:
        if (not isinstance(entry, dict) or "field" not in entry
                or not isinstance(entry.get("levels"), list) or not entry["levels"]):
            raise BatchError("batch.factors",
                             f"each factor needs 'field' and a non-empty "
                             f"'levels' list; got {entry!r}")
        factors.append(Factor(field=str(entry["field"]),
                              levels=list(entry["levels"]),
                              centre=entry.get("centre")))
    seeds = data.get("seeds")
    if seeds is None:
        seeds = [0]
    if (not isinstance(seeds, list) or not seeds
            or not all(isinstance(s, int) and not isinstance(s, bool) for s in seeds)):
        raise BatchError("batch.seeds",
                         f"'seeds' must be a non-empty list of integers, "
                         f"got {seeds!r}")
    if len(set(seeds)) != len(seeds):
        raise BatchError("batch.seeds", f"'seeds' repeats a value: {seeds}")
    design = str(data.get("design", Design.FACTORIAL))
    if design not in (Design.FACTORIAL, Design.OAT):
        raise BatchError("batch.design",
                         f"design {design!r} is not one of "
                         f"{Design.FACTORIAL!r}, {Design.OAT!r}")
    workers = data.get("workers", 1)
    if not isinstance(workers, int) or isinstance(workers, bool) or workers < 1:
        raise BatchError("batch.workers", f"'workers' must be an integer >= 1")
    capture = data.get("capture") or {}
    if not isinstance(capture, dict):
        raise BatchError("batch.capture", "'capture' must be a mapping")
    for key, value in capture.items():
        kind = CAPTURE_OPTIONS.get(key)
        if kind is None:
            raise BatchError("batch.capture",
                             f"capture option {key!r} is not one of "
                             f"{sorted(CAPTURE_OPTIONS)}")
        if kind is bool and not isinstance(value, bool):
            raise BatchError("batch.capture", f"capture.{key} must be true/false")
        if kind is int and (not isinstance(value, int) or isinstance(value, bool)):
            raise BatchError("batch.capture", f"capture.{key} must be an integer")
    return Matrix(base=base, factors=factors, seeds=list(seeds), design=design,
                  workers=workers, capture=dict(capture), path=path)


@dataclass
class BatchCase:
    overrides: Dict[str, Any]
    seed: int
    spec: ScenarioSpec

    @property
    def spec_digest(self) -> str:
        return self.spec.digest()

    @property
    def run_id(self) -> str:
        """Content-addressed: the spec's own digest, shortened."""
        return self.spec_digest[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {"run_id": self.run_id, "spec_digest": self.spec_digest,
                "seed": self.seed,
                **{f"factor.{k}": v for k, v in self.overrides.items()}}


def _cells(matrix: Matrix) -> List[Dict[str, Any]]:
    if not matrix.factors:
        return [{}]
    return Design(matrix.factors, kind=matrix.design).cells()


def build_cases(matrix: Matrix, base: Optional[ScenarioSpec] = None
                ) -> List[BatchCase]:
    """Every cell x seed as a spec. A factor naming a field the spec
    does not have refuses by name here, before any run starts."""
    if base is None:
        try:
            base = ScenarioSpec.read(matrix.base)
        except ValueError as exc:
            raise BatchError("batch.base", f"{matrix.base}: {exc}") from exc
    cases: List[BatchCase] = []
    seen: Dict[str, BatchCase] = {}
    for cell in _cells(matrix):
        for seed in matrix.seeds:
            spec = ScenarioSpec.from_dict(base.to_dict())
            for name, level in cell.items():
                try:
                    spec.set(name, level, frm=f"batch factor {name}")
                except (AttributeError, ValueError) as exc:
                    raise BatchError(
                        "batch.factors",
                        f"factor {name!r} is not a spec field ({exc})") from exc
            spec.set("seed", int(seed), frm="batch seed")
            # The planners the capture CLI runs, run HERE too, so the
            # run id is the digest the run's manifest records: the
            # randomisation block writes its draws back into the spec,
            # and an id taken before that would name a spec no run has.
            try:
                sample_randomization(spec)
            except RandomizationError as exc:
                raise BatchError(
                    exc.constraint,
                    f"cell {cell} seed {seed}: {exc.message}") from exc
            case = BatchCase(overrides=dict(cell), seed=int(seed), spec=spec)
            if case.run_id in seen:
                # Two cells that command one spec (a factor whose level
                # equals the base value, say) are one run; the ledger
                # would otherwise carry it twice.
                continue
            seen[case.run_id] = case
            cases.append(case)
    return cases


def capture_command(spec_path: Path, run_dir: Path,
                    capture: Dict[str, Any]) -> List[str]:
    """The exact ``flightsim.capture`` invocation for one case."""
    command = [sys.executable, "-m", "flightsim.capture", str(spec_path),
               "--out", str(run_dir)]
    if "max_previews" in capture:
        command += ["--max-previews", str(int(capture["max_previews"]))]
    for flag in ("card", "render", "void"):
        if capture.get(flag):
            command.append(f"--{flag}")
    if capture.get("no_host_flight"):
        command.append("--no-host-flight")
    return command


def run_case(case: BatchCase, out_dir: Path, capture: Dict[str, Any]
             ) -> Dict[str, Any]:
    """One run: the spec written, the capture as a subprocess with its
    log kept, then the verifier over the result and verification.json
    written. Returns the ledger row. Never raises for a failed capture
    -- the row says so."""
    from core.capture.verify import verify_run, write_verification

    run_dir = Path(out_dir) / case.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    spec_path = run_dir / "spec.yaml"
    case.spec.write(spec_path)
    command = capture_command(spec_path, run_dir, capture)
    log = run_dir / "capture.log"
    started = time.monotonic()
    with log.open("w", encoding="utf-8") as sink:
        completed = subprocess.run(command, stdout=sink, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, cwd=str(REPO))
    row: Dict[str, Any] = {
        **case.to_dict(),
        "case_id": case.run_id,          # ResultLog keys on this name
        "run_dir": str(run_dir),
        "command": command,
        "capture_exit": completed.returncode,
        "wall_seconds": round(time.monotonic() - started, 3),
    }
    manifest = run_dir / "capture_manifest.json"
    if completed.returncode != 0 or not manifest.is_file():
        row["ok"] = False
        row["error"] = (f"flightsim.capture exited {completed.returncode}; "
                        f"its log is {log}")
        row["verified"] = False
        return row
    report = verify_run(run_dir)
    write_verification(report, run_dir)
    summary = report.to_dict()
    row["verified"] = bool(summary["ok"])
    row["verification"] = {k: summary[k] for k in ("ok", "passed", "failed", "not_run")}
    row["ok"] = True
    if not summary["ok"]:
        row["error"] = "verification failed: " + "; ".join(
            f"{c['name']}: {c['detail']}" for c in summary["checks"]
            if c["status"] == "FAIL")
    return row


@dataclass
class BatchResult:
    out_dir: Path
    cases: int
    completed: int
    skipped: int
    failed: int
    unverified: int
    rows: List[Dict[str, Any]]


def run_batch(matrix: Matrix, out_dir, resume: bool = True,
              workers: Optional[int] = None,
              progress: Optional[Callable[[str], None]] = None,
              runner: Callable[..., Dict[str, Any]] = run_case) -> BatchResult:
    """The batch. ``resume`` skips runs the ledger already records as
    captured (a failed capture is retried; a failed VERIFICATION is
    not, it is a finding); ``workers`` caps concurrent captures."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = build_cases(matrix)
    log = ResultLog(out_dir / LEDGER)
    if resume:
        done = {row["run_id"] for row in log.rows() if row.get("ok")}
    else:
        log.truncate()
        done = set()
    from core.experiments.manifest import git_provenance

    (out_dir / BATCH_RECORD).write_text(json.dumps({
        "matrix": matrix.to_dict(),
        "matrix_file": str(matrix.path) if matrix.path else None,
        "base_spec_digest": ScenarioSpec.read(matrix.base).digest(),
        "cases": len(cases),
        "run_ids": [c.run_id for c in cases],
        "git": git_provenance(),
    }, indent=1), encoding="utf-8")

    pending = [c for c in cases if c.run_id not in done]
    skipped = len(cases) - len(pending)
    completed = failed = unverified = 0
    n_workers = max(1, int(workers or matrix.workers))
    index = 0

    def note(row: Dict[str, Any]) -> None:
        nonlocal completed, failed, unverified, index
        index += 1
        log.append(row)
        if row.get("ok"):
            completed += 1
            if not row.get("verified"):
                unverified += 1
        else:
            failed += 1
        if progress:
            state = ("ok" if row.get("ok") and row.get("verified")
                     else "UNVERIFIED" if row.get("ok") else "FAILED")
            progress(f"[{index}/{len(pending)}] {row['run_id']} seed "
                     f"{row['seed']} {state} ({row.get('wall_seconds', 0):.1f} s)")

    if n_workers == 1 or len(pending) <= 1:
        for case in pending:
            note(runner(case, out_dir, matrix.capture))
    else:
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(runner, case, out_dir, matrix.capture): case
                       for case in pending}
            for future in as_completed(futures):
                note(future.result())
    return BatchResult(out_dir=out_dir, cases=len(cases), completed=completed,
                       skipped=skipped, failed=failed, unverified=unverified,
                       rows=log.rows())
