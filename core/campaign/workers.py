"""The worker side of a campaign: a case built BY INDEX, run through
the existing headless pipeline under a watchdog, and returned as one
ledger row (contracts §6.1).

Everything a worker needs travels as plain data (the campaign record
and an index) so the pool can use the ``spawn`` start method -- the
only one Windows has -- and so nothing about a case depends on which
worker took it or when: the run seed and every draw come from
``SeedSequence([index, campaign_seed])``, never from completion order.

Nothing here is a second implementation of a capture or a verify: the
capture is the ``flightsim.capture`` CLI (``core.dataset.batch``'s
command), the verifier is ``core.capture.verify.verify_run`` through
``core.dataset.batch.case_row``, exactly as a batch run.

Not claimed: the watchdog measures the renderer's OUTPUT (bytes
written under the run directory and to its log), not its CPU or GPU;
a renderer that writes a heartbeat while producing nothing useful is
not caught here -- the verifier catches what it produced.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from core.dataset.batch import REPO, capture_command, case_row
from core.scenario.fields import Source
from core.scenario.randomization import (
    MAX_SEED, PLANNABLE, RandomizationError, RandomizationSpec,
    sample_randomization,
)
from core.scenario.spec import ScenarioSpec

from .ledger import (
    STATUS_FAILED, STATUS_REFUSED, STATUS_RENDERED, STATUS_VERIFIED,
)

#: How a case's run seed is derived; recorded in every row's provenance.
CASE_SEED_DERIVATION = ("SeedSequence(entropy=[index, campaign_seed]); "
                        "seed = 1 + first uint64 mod MAX_SEED")
#: A case whose renderer writes nothing for this long is killed and
#: re-queued once (contracts §6.1 watchdog). Minutes, as the brainstorm
#: states it; the campaign record carries the value actually used.
DEFAULT_STALL_SECONDS = 20 * 60
#: The run directories live here inside the campaign directory.
RUNS_DIR = "runs"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def case_seed(index: int, campaign_seed: int) -> int:
    """The run seed of case ``index``: index first, root seed last
    (NumPy's own rule for independent streams), folded to 1..MAX_SEED."""
    sequence = np.random.SeedSequence(entropy=[int(index), int(campaign_seed)])
    return 1 + int(sequence.generate_state(1, dtype=np.uint64)[0]) % MAX_SEED


def build_case(index: int, record: Dict[str, Any]) -> Tuple[ScenarioSpec, int]:
    """The spec of case ``index``: the campaign's compiled spec with
    its run seed planned from the index (a stated seed is never
    moved), the block's seed set to the campaign seed (the sampler's
    ``campaign_seed``), then the one sampler with ``draw_index=index``.
    Raises ``RandomizationError`` for a refused slot (by name)."""
    spec = ScenarioSpec.from_dict(record["spec"])
    campaign_seed = int(record["seed"])
    seed = case_seed(index, campaign_seed)
    if spec.seed.source in PLANNABLE:
        spec.plan("seed", seed,
                  frm=f"campaign case {index}: {CASE_SEED_DERIVATION} "
                      f"(campaign seed {campaign_seed})")
    else:
        seed = int(spec.seed.value)      # stated in the prompt: kept
    block = spec.randomization
    if block.seed.source in PLANNABLE and int(block.seed.value) != campaign_seed:
        block.plan("seed", campaign_seed,
                   frm=f"the campaign seed ({campaign_seed}); every policy "
                       f"draw is seeded from (case index, this)")
    sample_randomization(spec, draw_index=int(index))
    return spec, seed


def sampled_values(spec: ScenarioSpec) -> Dict[str, Any]:
    """{leaf: value} for every block leaf the policy drew (``sampled``
    provenance), plus the block seed. What a row records of the draw."""
    block = spec.randomization
    out: Dict[str, Any] = {}
    for name in RandomizationSpec.POLICY_FIELDS:
        if name == "policy_draws":
            continue
        q = getattr(block, name)
        if q.source == Source.SAMPLED:
            out[name] = q.value
    return json.loads(json.dumps(out, default=str))


def draw_record(spec: ScenarioSpec) -> Dict[str, Any]:
    """The block's ``policy_draws`` record when a policy drew, else {}."""
    value = spec.randomization.policy_draws.value
    return dict(value) if isinstance(value, dict) else {}


def _newest_write(watch_dir: Path, log: Path) -> Tuple[float, int]:
    """(newest mtime under watch_dir, log size): the activity signal."""
    newest = 0.0
    try:
        for root, _dirs, files in os.walk(watch_dir):
            for name in files:
                try:
                    newest = max(newest, os.stat(os.path.join(root, name)).st_mtime)
                except OSError:
                    continue
    except OSError:
        pass
    try:
        size = log.stat().st_size
    except OSError:
        size = 0
    return newest, size


def run_with_watchdog(command: List[str], log: Path, watch_dir: Path,
                      stall_seconds: Optional[float],
                      poll_seconds: float = 0.25) -> Tuple[int, bool]:
    """The capture subprocess with a watchdog: if nothing under
    ``watch_dir`` and nothing in ``log`` changes for ``stall_seconds``,
    the process is killed. Returns (exit code, stalled). ``None`` or 0
    disables the watchdog (then this is ``batch.run_capture``)."""
    log = Path(log)
    watch_dir = Path(watch_dir)
    with log.open("w", encoding="utf-8") as sink:
        process = subprocess.Popen(command, stdout=sink, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, cwd=str(REPO))
        if not stall_seconds or stall_seconds <= 0:
            return process.wait(), False
        last_signal = _newest_write(watch_dir, log)
        last_activity = time.monotonic()
        while True:
            try:
                return process.wait(timeout=poll_seconds), False
            except subprocess.TimeoutExpired:
                pass
            signal = _newest_write(watch_dir, log)
            now = time.monotonic()
            if signal != last_signal:
                last_signal, last_activity = signal, now
            elif now - last_activity > float(stall_seconds):
                process.kill()
                process.wait()
                return process.returncode if process.returncode is not None else -9, True


def bundle_digest(run_dir: Path) -> Optional[str]:
    """sha256 over every camera's render.json frame_records[].sha256
    (the engine's own digests), or None when no render.json exists (a
    headless run, or an older build). Reads the engine's record; does
    not re-hash pixels (the verifier's Gate 10-R check does that)."""
    from core.capture.repro import engine_digests

    frames_dir = Path(run_dir) / "frames"
    if not frames_dir.is_dir():
        return None
    parts: List[str] = []
    for camera_dir in sorted(p for p in frames_dir.iterdir() if p.is_dir()):
        for frame, digest in sorted(engine_digests(camera_dir).items()):
            parts.append(f"{camera_dir.name}/{frame}:{digest}")
    if not parts:
        return None
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def directory_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.stat(os.path.join(root, name)).st_size
            except OSError:
                continue
    return total


def _manifest_facts(run_dir: Path) -> Dict[str, Any]:
    path = Path(run_dir) / "capture_manifest.json"
    if not path.is_file():
        return {"frames": 0, "drawn": False}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"frames": 0, "drawn": False}
    frames = manifest.get("frames") or []
    drawn = any((Path(run_dir) / str(f.get("file", ""))).is_file()
                for f in frames if isinstance(f, dict))
    return {
        "frames": len(frames),
        "drawn": bool(drawn),
        "simulation_digest": manifest.get("simulation_digest"),
        "output_digest": manifest.get("output_digest"),
        "solve_source": manifest.get("solve_source"),
    }


def run_index(index: int, record: Dict[str, Any], out_dir: str,
              attempt: int = 1,
              stall_seconds: Optional[float] = DEFAULT_STALL_SECONDS,
              capture_runner: Optional[str] = None,
              seen_case_ids: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """One slot, start to finish, as a ledger row: the case built from
    the index (a refused slot is a ``refused`` row), the spec written
    to ``runs/<case_id>/spec.yaml``, the capture CLI run under the
    watchdog with its log kept, the verifier over the result,
    ``verification.json`` written. Never raises for a failed capture.

    ``capture_runner`` names a module-level function
    (``"package.module:function"``) with ``run_with_watchdog``'s
    signature, for tests that stand in for the CLI; the real one is
    the default. A name, not a callable, so the pool can pickle it.
    ``seen_case_ids`` ({case_id: index} the ledger already holds) lets
    a slot that drew a spec another slot produced refuse
    ``campaign.duplicate_case`` before running it again; the campaign
    checks again on collection for cases that were in flight together.
    """
    started_utc = utc_now()
    started = time.monotonic()
    campaign_seed = int(record["seed"])
    base: Dict[str, Any] = {"index": int(index), "attempt": int(attempt),
                            "campaign_seed": campaign_seed,
                            "started_utc": started_utc}
    try:
        spec, seed = build_case(index, record)
    except RandomizationError as exc:
        refused = (exc.detail or {}).get("refusals") if hasattr(exc, "detail") else None
        return {**base, "status": STATUS_REFUSED, "ok": False, "verified": False,
                "refusals": [exc.constraint], "reason": exc.message,
                "refused_attempts": refused or [],
                "frames": 0, "yield": 0,
                "finished_utc": utc_now(),
                "wall_seconds": round(time.monotonic() - started, 3)}
    case_id = spec.digest()[:16]
    other = (seen_case_ids or {}).get(case_id)
    if other is not None and int(other) != int(index):
        return {**base, "status": STATUS_REFUSED, "ok": False, "verified": False,
                "case_id": case_id, "run_id": case_id, "spec_digest": spec.digest(),
                "seed": int(seed), "sampled": sampled_values(spec),
                "refusals": ["campaign.duplicate_case"],
                "reason": (f"slot {index} drew the spec slot {other} already "
                           f"produced ({case_id}); the prompt leaves nothing to "
                           f"vary between them"),
                "frames": 0, "yield": 0, "finished_utc": utc_now(),
                "wall_seconds": round(time.monotonic() - started, 3)}
    run_dir = Path(out_dir) / RUNS_DIR / case_id
    run_dir.mkdir(parents=True, exist_ok=True)
    spec_path = run_dir / "spec.yaml"
    spec.write(spec_path)
    capture = dict(record.get("capture") or {})
    command = capture_command(spec_path, run_dir, capture)
    log = run_dir / "capture.log"
    draws = draw_record(spec)
    row: Dict[str, Any] = {
        **base,
        "run_id": case_id, "case_id": case_id,
        "spec_digest": spec.digest(), "seed": int(seed),
        "seed_derivation": CASE_SEED_DERIVATION,
        "sampled": sampled_values(spec),
        "policy_attempts": int(draws.get("attempts", 0)) if draws else 0,
        "refusals": sorted({str(r.get("refusal_name"))
                            for r in draws.get("refused", [])}) if draws else [],
        "run_dir": str(run_dir), "command": command,
    }
    runner = run_with_watchdog
    if capture_runner:
        import importlib

        module, _, name = capture_runner.partition(":")
        runner = getattr(importlib.import_module(module), name)
    returncode, stalled = runner(command, log, run_dir, stall_seconds)
    row = case_row(row, run_dir, returncode, log)
    facts = _manifest_facts(run_dir)
    row.update({k: v for k, v in facts.items() if k != "frames"})
    row["frames"] = int(facts["frames"])
    row["bundle_digest"] = bundle_digest(run_dir) if row.get("ok") else None
    row["bytes"] = directory_bytes(run_dir)
    if stalled:
        row["reason"] = (f"watchdog: the capture wrote nothing for "
                         f"{stall_seconds:g} s and was killed; re-queued")
        row["requeue"] = True
        row["ok"] = False
        row["verified"] = False
    if row.get("ok") and row.get("verified"):
        row["status"] = STATUS_VERIFIED
        row["yield"] = row["frames"]
    elif row.get("ok"):
        # Captured (and drawn when an engine was present) but the
        # verifier said no: a finding, not a retry (batch semantics).
        row["status"] = STATUS_RENDERED
        row["yield"] = 0
        row.setdefault("reason", row.get("error"))
    else:
        row["status"] = STATUS_FAILED
        row["yield"] = 0
        row.setdefault("reason", row.get("error"))
    row["finished_utc"] = utc_now()
    row["wall_seconds"] = round(time.monotonic() - started, 3)
    return row
