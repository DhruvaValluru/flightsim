"""Gate 5 -- the same scenario, both hosts, matching trajectories.

    Identical scenario run headless and in UE produces matching trajectories
    within stated numerical tolerance. Control surfaces visibly articulate.
    Commanded roll is visible on screen. (§5 Phase 5)

Three clauses, three measurements
---------------------------------
All from one spec, which is the point.

1. This harness compiles the prompt to a :class:`ScenarioSpec`, runs it headless
   and writes ``headless.json``.
2. It projects the same spec twice: to ``ue_scenario.json`` (the trajectory
   card, hands off from trim) and to ``ue_render_scenario.json`` (the same
   spec plus the roll doublet the on-screen clauses need).
3. ``scripts/run_ue_scenario.sh`` flies the first card and writes
   ``unreal.json``; ``scripts/render_ue_scenario.sh`` flies the second with the
   renderer up and writes frames plus ``render.json``.
4. This harness, given both, decides all three clauses.

The trajectory comparison is on the time base both recorders write, not on
sample index -- see :func:`compare`, where the reason is measured rather than
assumed. The on-screen clauses are decided by reading the PNGs back, not by
reading what the engine said about them -- see :func:`measure_frames`.

What it will not do is report a pass on the evidence it happens to have. §5 is
explicit -- "Do not mark a gate passed on partial evidence" -- and a gate that
passes when a third of its evidence is missing is precisely the §1.7 failure
that let a broken run ship against a green suite. With no ``--unreal-telemetry``
it exits 2 = BLOCKED, which is neither a pass nor a failure on the merits, and
with no ``--unreal-render`` it says so and exits 2 again.

Scope of the claim
------------------
This gate tests the *integration*, not the physics and not visual realism.

Both hosts run the same JSBSim commit and byte-identical aircraft and engine
files -- ``ue_preflight.sh`` checks the first and ``docs/VALIDITY.md`` records
the second -- so trajectory agreement says the UE host steps and transforms the
same model correctly. It says nothing about whether that model matches a real
747.

The rendered aircraft is a placeholder built from boxes. It is the right scope
for this gate, which asks whether surfaces articulate and whether roll is
visible, and the wrong scope for Phase 6, which asks whether any of it looks
like anything.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.nl.compiler import compile_prompt  # noqa: E402
from core.scenario.card import (  # noqa: E402,F401 -- re-exported: every
    # experiment and test historically imported these from here; the code
    # moved to core/scenario/card.py in Phase 8 (it stopped being an
    # experiment helper the day the showcase matrix shipped) and the names
    # remain importable from this module unchanged.
    SAMPLE_INTERVAL_S,
    discovered_engine_mixture,
    write_run_card,
)
from core.scenario.runner import run_spec  # noqa: E402
from core.scenario.spec import ScenarioSpec  # noqa: E402

RULE = "=" * 96

#: Stated numerical tolerance for host parity, declared before any comparison.
#:
#: Both hosts run the same JSBSim version -- the vendoring script pins it to the
#: headless core's 1.2.4 precisely so this comparison is about the integration
#: rather than about two different physics libraries. What can still differ is
#: the substep accumulator (the plugin's own README calls its fixed rate
#: "pseudo fixed") and the ECEF round trip the plugin performs every tick.
TOLERANCE = {
    "altitude_m": 5.0,
    "tas_kt": 2.0,
    "roll_deg": 1.0,
    "pitch_deg": 1.0,
    "heading_deg": 1.0,
    "n_z": 0.05,
    # Ground track, added when the comparison was extended to wind. Position
    # is what closes the loop on wind actually acting in BOTH hosts: a host
    # that silently flew still air would match every attitude channel of a
    # crosswind case (a uniform wind changes no air-relative quantity) and
    # drift 770 m off the other's track in a minute. 1e-4 degrees is about
    # 11 m at the equator. These are additional channels, not a loosening of
    # the six originally declared.
    "lat_deg": 1e-4,
    "lon_deg": 1e-4,
}

#: Channels that live on a circle, where 359.9 and 0.1 differ by 0.2 rather
#: than 359.8. Unwrapped before interpolation and compared with wrapping --
#: see :func:`compare`.
WRAPPED_CHANNELS = frozenset({"heading_deg"})

#: Channels the UE recorder writes, matching core/telemetry/recorder.py.
COMPARED = tuple(TOLERANCE)

#: How much of the headless run the UE run has to cover before a comparison
#: means anything. A UE run that stopped after five seconds would otherwise
#: "match" over those five seconds and report a pass.
MIN_OVERLAP_FRACTION = 0.95

#: Thresholds for the two on-screen clauses, declared before any frame is
#: measured, for the same reason TOLERANCE is.
#:
#: The one that carries the weight is ``bank_correlation``. §1.5's failure was a
#: chase camera welded to the aircraft: real roll of +7 to -7 degrees happened
#: and was invisible, because in the body frame the aircraft never moves. The
#: test for that is not "the camera was configured correctly" -- it is that the
#: aircraft's bank *in the pixels* moves with the FDM's roll.
ON_SCREEN = {
    #: Fraction of the frame the aircraft must cover. A frame of empty sky is
    #: a file, not evidence.
    "min_lit_fraction": 0.005,
    #: Degrees. A camera that inherits any roll is re-introducing the §1.5
    #: failure, so this is essentially zero rather than a tolerance.
    "max_camera_roll_deg": 0.01,
    #: How many surfaces have to be attached to geometry and actually move.
    "min_moving_surfaces": 2,
    #: Degrees of travel before a surface counts as having articulated.
    "min_surface_travel_deg": 1.0,
    #: Degrees of apparent bank, peak to peak, in the image. Below this the
    #: roll is technically present and not something a viewer would see.
    "min_image_bank_range_deg": 10.0,
    #: Correlation between FDM roll and measured image bank.
    "min_bank_correlation": 0.98,
}

#: Any channel of a pixel above this counts as the aircraft rather than the
#: background. The scene is deliberately unlit apart from the aircraft, so the
#: silhouette is not a segmentation problem.
BACKGROUND_LEVEL = 24


@dataclass(frozen=True)
class Overlap:
    """The window in which both hosts have samples."""

    start: float
    end: float
    headless_span: float
    unreal_span: float
    samples: int

    @property
    def fraction(self) -> float:
        span = self.end - self.start
        return span / self.headless_span if self.headless_span > 0 else 0.0

    @property
    def ok(self) -> bool:
        return self.fraction >= MIN_OVERLAP_FRACTION

    def render(self) -> str:
        return (f"  [{'ok  ' if self.ok else 'FAIL'}] {'time overlap':14s} "
                f"{self.start:.3f}..{self.end:.3f} s "
                f"({self.fraction * 100:.1f}% of the headless run's "
                f"{self.headless_span:.3f} s; UE ran {self.unreal_span:.3f} s)")


@dataclass
class Parity:
    channel: str
    max_difference: float
    tolerance: float
    samples: int

    @property
    def ok(self) -> bool:
        return self.max_difference <= self.tolerance

    def render(self) -> str:
        return (f"  [{'ok  ' if self.ok else 'FAIL'}] {self.channel:14s} "
                f"max difference {self.max_difference:>10.4g} "
                f"(tolerance {self.tolerance:g}, {self.samples} samples)")


def reference_spec(prompt: str) -> ScenarioSpec:
    spec = compile_prompt(prompt)
    # Mass held, so a divergence between hosts is the integration and not a
    # fuel-burn difference compounding over the run.
    spec.set("mass_held", True, frm="host parity comparison")
    # Open loop in both hosts. The headless host holds a commanded state with
    # the TECS autopilot in core/control; the UE host has no autopilot and
    # nothing in §5 asks it to grow one. Leaving hold_state on would compare a
    # controlled aircraft against an uncontrolled one and attribute the
    # difference to the integration, which is the one thing this gate is trying
    # to measure. Hands off from trim is also the sharper test: there is no
    # feedback loop pulling the two hosts back together.
    spec.set("hold_state", False, frm="open loop in both hosts")
    return spec


def write_reference(spec: ScenarioSpec, out_dir: Path) -> Path:
    """Run headless and write the trajectory the UE run is compared against."""
    result = run_spec(spec)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec.write(out_dir / "scenario.yaml")
    payload = {
        "host": "headless",
        "spec_digest": spec.digest(),
        "output_digest": result.output_digest,
        "samples": len(result.telemetry),
        "interval_s": result.telemetry.interval_s,
        "columns": result.telemetry.columns,
    }
    path = out_dir / "headless.json"
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return path


#: The on-screen scenario: a roll doublet, hands otherwise off.
#:
#: "Commanded roll is visible on screen" needs a commanded roll, and this host
#: has no autopilot to command one -- so it is a scripted aileron input, held
#: rather than pulsed, with a neutral pause between the two directions. The
#: pause is deliberate: an aircraft that only ever rolls while the stick is over
#: could be a graphical effect keyed off the input, whereas one that holds bank
#: with the stick centred and then rolls back is being flown.
#:
#: Deliberately NOT the parity scenario. The parity comparison is against a
#: headless run that is hands off from trim, and the telemetry commandlet
#: refuses a card carrying control inputs for exactly that reason.
ROLL_DOUBLET = (
    {"t_s": 4.0, "aileron": 0.25},
    {"t_s": 8.0, "aileron": 0.0},
    {"t_s": 12.0, "aileron": -0.25},
    {"t_s": 16.0, "aileron": 0.0},
)

#: Long enough for the doublet plus a settled tail, short enough that a
#: 5 Hz capture is a manageable number of PNGs.
RENDER_DURATION_S = 22.0


def _interpolate(times: Sequence[float], values: Sequence[float], t: float) -> float:
    """Linear interpolation of a channel at ``t``. ``times`` must be increasing."""
    i = bisect.bisect_left(times, t)
    if i == 0:
        return values[0]
    if i >= len(times):
        return values[-1]
    t0, t1 = times[i - 1], times[i]
    if t1 == t0:
        return values[i]
    weight = (t - t0) / (t1 - t0)
    return values[i - 1] + weight * (values[i] - values[i - 1])


def _unwrap_degrees(values: Sequence[float]) -> List[float]:
    """Make an angle series continuous across the 0/360 seam.

    A heading drifting from 0.01 to 359.99 has moved 0.02 degrees, and linear
    interpolation across those two raw samples passes through 180 -- an
    aircraft momentarily pointing south that neither host ever flew. Any
    comparison of a wrapped channel therefore runs on the unwrapped series.
    The still-air scenarios never cross the seam, which is the only reason the
    original comparison got away without this.
    """
    out = [float(values[0])] if values else []
    for value in values[1:]:
        step = (float(value) - out[-1] + 180.0) % 360.0 - 180.0
        out.append(out[-1] + step)
    return out


def _wrapped_difference(a: float, b: float) -> float:
    """|a - b| on the circle, so 359.9 vs 0.1 is 0.2 and never 359.8."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def compare(headless: Path, unreal: Path) -> Tuple[List[Parity], Overlap]:
    """Compare the two hosts on the time base each one recorded for itself.

    Not by sample index. The two recorders have the same nominal sampling
    period and do *not* sample at the same times: the headless recorder
    schedules the next sample from the time of the last one, so it accumulates
    a step of slack every time the FDM clock lands just short of the deadline,
    while the UE recorder counts down a float accumulator against the frame
    time. Measured on this build the headless period comes out at ~0.1075 s
    against the UE recorder's 0.1 s -- a 7% stretch that reaches a full 4
    seconds of skew by the end of a 60 s run.

    Comparing those two arrays element by element would have compared 60 s of
    one host against 56 s of the other and reported the difference as a
    physics divergence. Both recorders write a ``t`` column; this uses it.
    """
    a = json.loads(headless.read_text(encoding="utf-8"))["columns"]
    b = json.loads(unreal.read_text(encoding="utf-8"))["columns"]

    for name, columns in (("headless", a), ("unreal", b)):
        if "t" not in columns or not columns["t"]:
            raise ValueError(
                f"the {name} trajectory has no 't' column, so the two runs "
                f"cannot be put on a common time base. Refusing to compare by "
                f"sample index."
            )

    at, bt = a["t"], b["t"]
    # The comparison starts at each host's SECOND sample. The first sample is
    # the trim snapshot: the headless recorder takes it by force before the
    # environment loop has run, so in a wind scenario it records the aircraft
    # an instant before the wind switches on -- measured, 288.0 kt TAS against
    # 301.1 kt one sample later in a 13 kt headwind. Grading that instant
    # grades the switch-on artifact, which is the §1.1 mistake (scoring the
    # initialisation transient) in miniature. Exactly one sample is skipped
    # per host, never more: a real divergence from the second sample onward is
    # still a divergence, and there is a test holding that line.
    first_a = at[1] if len(at) > 1 else at[0]
    first_b = bt[1] if len(bt) > 1 else bt[0]
    start, end = max(first_a, first_b), min(at[-1], bt[-1])
    grid = [t for t in at if start <= t <= end]
    overlap = Overlap(start=start, end=end,
                      headless_span=at[-1] - at[0], unreal_span=bt[-1] - bt[0],
                      samples=len(grid))

    results = []
    for channel in COMPARED:
        if channel not in a or channel not in b or not grid:
            results.append(Parity(channel, math.inf, TOLERANCE[channel], 0))
            continue
        if channel in WRAPPED_CHANNELS:
            # Unwrap each host's own series so interpolation never crosses the
            # seam, then compare on the circle so a whole-turn offset between
            # the two unwrapped series cannot masquerade as 360 degrees of
            # divergence.
            series_a = _unwrap_degrees(a[channel])
            series_b = _unwrap_degrees(b[channel])
            worst = max(
                (_wrapped_difference(_interpolate(at, series_a, t),
                                     _interpolate(bt, series_b, t))
                 for t in grid),
                default=math.inf,
            )
        else:
            worst = max(
                (abs(_interpolate(at, a[channel], t) - _interpolate(bt, b[channel], t))
                 for t in grid),
                default=math.inf,
            )
        results.append(Parity(channel, worst, TOLERANCE[channel], len(grid)))
    return results, overlap


@dataclass(frozen=True)
class Check:
    """One on-screen claim, and the measurement behind it."""

    name: str
    ok: bool
    detail: str

    def render(self) -> str:
        return f"  [{'ok  ' if self.ok else 'FAIL'}] {self.name:28s} {self.detail}"


def silhouette_bank_degrees(path: Path) -> Tuple[float, float]:
    """Apparent bank of the aircraft in one frame, and how much of it is lit.

    The aircraft is a bright silhouette on black, so the second moment of the
    lit pixels has its long axis along the wing. The angle of that axis is what
    a viewer reads as bank. Image rows increase downward, which is why the
    angle comes out already in the same sense as a positive (right-wing-down)
    roll.

    This is measured from the PNG, not from anything the engine reported. A
    render that wrote the right numbers into its manifest and the wrong pixels
    into its frames has to fail, and only an independent read of the frames can
    make it.
    """
    import numpy as np
    import rasterio

    with rasterio.open(path) as dataset:
        bands = dataset.read()[:3]
    lit = bands.max(axis=0) > BACKGROUND_LEVEL
    fraction = float(lit.mean())
    rows, columns = np.nonzero(lit)
    if rows.size < 2:
        return math.nan, fraction
    x = columns - columns.mean()
    y = rows - rows.mean()
    cxx = float((x * x).mean())
    cyy = float((y * y).mean())
    cxy = float((x * y).mean())
    return math.degrees(0.5 * math.atan2(2.0 * cxy, cxx - cyy)), fraction


def measure_frames(manifest_path: Path) -> List[Check]:
    """Read the rendered run back and decide the two on-screen clauses."""
    import numpy as np

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest["frame_records"]
    directory = manifest_path.parent

    # -- every frame shows the aircraft ---------------------------------
    banks, fractions = [], []
    for record in records:
        bank, fraction = silhouette_bank_degrees(directory / record["frame"])
        banks.append(bank)
        fractions.append(fraction)
    worst = min(fractions) if fractions else 0.0
    checks = [Check(
        "frames show the aircraft",
        bool(records) and worst >= ON_SCREEN["min_lit_fraction"],
        f"{len(records)} frames, aircraft covers "
        f"{worst * 100:.2f}%-{max(fractions) * 100:.2f}% of the frame "
        f"(floor {ON_SCREEN['min_lit_fraction'] * 100:.1f}%)",
    )]

    # -- the camera never inherits roll ---------------------------------
    camera_roll = max((abs(r["camera_roll_deg"]) for r in records), default=math.inf)
    checks.append(Check(
        "camera never inherits roll",
        camera_roll <= ON_SCREEN["max_camera_roll_deg"],
        f"max |camera roll| {camera_roll:.6f} deg over the run, preset "
        f"{manifest.get('camera_preset')}",
    ))

    # -- control surfaces articulate ------------------------------------
    # Travel is read from surface_component_deg, which the commandlet measures
    # off the scene component's transform rather than recomputing from the
    # JSBSim property. A binding that read a deflection and moved no geometry
    # therefore reads zero here, which is the failure worth catching.
    travel: Dict[str, Tuple[float, float]] = {}
    for record in records:
        for surface, degrees in record["surface_component_deg"].items():
            lo, hi = travel.get(surface, (degrees, degrees))
            travel[surface] = (min(lo, degrees), max(hi, degrees))
    spans = {name: hi - lo for name, (lo, hi) in travel.items()}
    moving = {n: s for n, s in spans.items() if s >= ON_SCREEN["min_surface_travel_deg"]}
    checks.append(Check(
        "control surfaces articulate",
        len(moving) >= ON_SCREEN["min_moving_surfaces"],
        f"{manifest.get('bound_surfaces')} bound to geometry, {len(moving)} moved: "
        + ", ".join(f"{n} {s:.2f} deg" for n, s in sorted(spans.items())),
    ))

    # -- commanded roll is visible on screen ----------------------------
    roll = [r["roll_deg"] for r in records]
    finite = [(a, b) for a, b in zip(roll, banks) if not math.isnan(b)]
    if len(finite) < 3:
        checks.append(Check("commanded roll is visible", False,
                            "too few measurable frames"))
        return checks
    fdm = np.array([a for a, _ in finite])
    image = np.array([b for _, b in finite])
    image_range = float(image.max() - image.min())
    if image_range < ON_SCREEN["min_image_bank_range_deg"]:
        # Checked before the correlation, because a frame sequence in which the
        # aircraft never moves has no correlation to compute -- and a NaN
        # falling through a `>=` is not a reason anyone should have to infer.
        # This is the §1.5 shape exactly: the FDM rolled, the pixels did not.
        checks.append(Check(
            "commanded roll is visible", False,
            f"the aircraft's apparent bank moves over only {image_range:.2f} deg "
            f"in the pixels while the FDM rolled "
            f"{fdm.max() - fdm.min():.2f} deg (floor "
            f"{ON_SCREEN['min_image_bank_range_deg']:g})",
        ))
        return checks
    correlation = float(np.corrcoef(fdm, image)[0, 1])
    checks.append(Check(
        "commanded roll is visible",
        correlation >= ON_SCREEN["min_bank_correlation"],
        f"apparent bank in the pixels tracks FDM roll at r={correlation:.5f}, "
        f"over {image.min():+.1f}..{image.max():+.1f} deg "
        f"(FDM {fdm.min():+.1f}..{fdm.max():+.1f})",
    ))
    return checks


def preflight() -> Tuple[bool, str]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "ue_preflight.sh"
    if not script.is_file():
        return False, "scripts/ue_preflight.sh is missing"
    proc = subprocess.run([str(script)], capture_output=True, text=True)
    return proc.returncode == 0, proc.stdout


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 5")
    ap.add_argument("--prompt",
                    default="fly the 747 at 3000 m and 250 kt for 60 seconds")
    ap.add_argument("--out", default="runs/gate5")
    ap.add_argument("--unreal-telemetry", default=None,
                    help="trajectory written by the UE host")
    ap.add_argument("--unreal-render", default=None,
                    help="render.json written by scripts/render_ue_scenario.sh|.ps1")
    args = ap.parse_args(argv)
    out = Path(args.out)

    print(f"\n{RULE}\n1. headless reference trajectory\n{RULE}")
    spec = reference_spec(args.prompt)
    reference = write_reference(spec, out)
    payload = json.loads(reference.read_text(encoding="utf-8"))
    card = write_run_card(spec, out / "ue_scenario.json")
    render_card = write_run_card(spec, out / "ue_render_scenario.json",
                                 control_inputs=ROLL_DOUBLET,
                                 duration_s=RENDER_DURATION_S)
    print(f"  prompt      \"{args.prompt}\"")
    print(f"  spec digest {payload['spec_digest'][:16]}")
    print(f"  wrote       {reference} ({payload['samples']} samples)")
    print(f"  wrote       {card} (the same spec, for the UE host)")
    print(f"  wrote       {render_card} (the same spec plus a roll doublet, "
          f"for the on-screen clauses)")

    # The run card tells the UE recorder how often to sample. If the headless
    # runner ever changes its own period, the card would quietly ask the other
    # host for a different one.
    if payload["interval_s"] != SAMPLE_INTERVAL_S:
        print(f"\n  the headless run sampled at {payload['interval_s']} s but the "
              f"run card asks the UE host for {SAMPLE_INTERVAL_S} s.")
        print("  Fix SAMPLE_INTERVAL_S, or the two hosts are not being asked "
              "for the same recording.")
        return 1

    print(f"\n{RULE}\n2. Unreal host\n{RULE}")
    can_build, diagnosis = preflight()
    for line in diagnosis.splitlines():
        print(f"  {line}" if line.strip() else "")

    unreal_path = Path(args.unreal_telemetry) if args.unreal_telemetry else None
    if unreal_path is None or not unreal_path.is_file():
        print(f"\n{RULE}\nGATE 5\n{RULE}")
        print("  [BLOCKED] no Unreal trajectory to compare against")
        print()
        print("  The headless half of this gate ran and is correct. There is no")
        print("  second trajectory, so there is nothing to compare.")
        print()
        from core.util.platform import os_name
        ext = "ps1" if os_name() == "windows" else "sh"
        print("  Produce one with:")
        print(f"    scripts/run_ue_scenario.{ext} {card} {out}/unreal.json")
        print(f"    scripts/render_ue_scenario.{ext} {render_card} {out}/frames")
        print()
        print("  GATE 5: BLOCKED -- not passed, and not failed on the merits.")
        print("  §5: do not mark a gate passed on partial evidence.")
        return 2

    unreal_payload = json.loads(unreal_path.read_text(encoding="utf-8"))
    print(f"  trajectory  {unreal_path} ({unreal_payload.get('samples')} samples)")

    print(f"\n{RULE}\n3. host parity\n{RULE}")
    results, overlap = compare(reference, unreal_path)
    print(overlap.render())
    for result in results:
        print(result.render())

    trajectories = overlap.ok and all(r.ok for r in results)

    # §5 Phase 5 has three clauses. The two below are about what a viewer sees,
    # and no number in a telemetry file can answer them.
    render_path = Path(args.unreal_render) if args.unreal_render else None
    on_screen: List[Check] = []
    if render_path is not None and render_path.is_file():
        print(f"\n{RULE}\n4. on screen\n{RULE}")
        manifest = json.loads(render_path.read_text(encoding="utf-8"))
        print(f"  {manifest['frames']} frames at {manifest['width']}x"
              f"{manifest['height']}, airframe: {manifest['airframe']}")
        on_screen = measure_frames(render_path)
        for check in on_screen:
            print(check.render())

    print(f"\n{RULE}\nGATE 5\n{RULE}")
    if not overlap.ok:
        print("  [FAIL] the two runs barely overlap in time; the channel "
              "comparisons above")
        print("         cover only part of the scenario and do not stand on "
              "their own.")
    print(f"  [{'PASS' if trajectories else 'FAIL'}] "
          f"identical scenario, both hosts, matching trajectories within "
          f"stated tolerance")

    if not on_screen:
        print("  [ -- ] control surfaces visibly articulate")
        print("  [ -- ] commanded roll is visible on screen")
        from core.util.platform import os_name
        ext = "ps1" if os_name() == "windows" else "sh"
        print("         No rendered run was given. Produce one with")
        print(f"         scripts/render_ue_scenario.{ext} {render_card} "
              f"{out}/frames")
        print("         and pass --unreal-render.")
    else:
        surfaces = next(c for c in on_screen if c.name == "control surfaces articulate")
        roll = next(c for c in on_screen if c.name == "commanded roll is visible")
        support = [c for c in on_screen if c not in (surfaces, roll)]
        print(f"  [{'PASS' if surfaces.ok else 'FAIL'}] control surfaces "
              f"visibly articulate")
        print(f"  [{'PASS' if roll.ok else 'FAIL'}] commanded roll is visible "
              f"on screen")
        for check in support:
            if not check.ok:
                print(f"         and {check.name} did not hold: {check.detail}")

    everything = trajectories and bool(on_screen) and all(c.ok for c in on_screen)
    if not trajectories:
        print("\n  GATE 5: FAIL -- the trajectories do not match.")
        return 1
    if not on_screen:
        print("\n  GATE 5: trajectory parity PASS. The gate as a whole is NOT "
              "passed:")
        print("  two of its three clauses have no evidence, and §5 says not to "
              "mark a gate")
        print("  passed on partial evidence.")
        return 2
    if not everything:
        print("\n  GATE 5: FAIL -- the run rendered, and what it shows does not "
              "meet the clause.")
        return 1
    print("\n  GATE 5: PASS -- all three clauses, each measured.")
    print("  Scope: one airframe, one envelope point, still air, flat terrain,")
    print("  and a placeholder box airframe. Visual realism is Phase 6 and is")
    print("  not what this gate asked for.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
