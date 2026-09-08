"""The single verification command: alignment, recovery, consistency.

    python -m flightsim.demo [--out runs/demo] [--terrain <bake stem>]
                             [--spec examples/cameras_multi.yaml]

Package I of the phase asks for "a single verification command that runs
the alignment, recovery, and consistency checks and prints a pass or
fail summary". ``flightsim.verify`` grades ONE run directory, so it can
report recovery, cross-view consistency and count exactness -- but
temporal alignment is a statement about TWO runs of the same simulation
captured with different cameras, and there is no way to make it from a
single directory. This command captures both and grades all three.

What it does, in order:

1. captures the given specification (two cameras by default, so the
   cross-view triangulation check is exercised rather than reported not
   exercised);
2. captures the SAME simulation again with a different camera set -- a
   cockpit view, one camera, same image count -- into a second
   directory;
3. verifies each run and then the alignment BETWEEN them;
4. prints one pass/fail summary.

Runs on macOS, Windows and Linux: nothing here renders pixels. Where the
engine exists the same directories are what a render pass would write
its frames into.

Exit code 0 when every check passed, 1 when any failed, 2 on a named
refusal (a spec that cannot be captured).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

DEFAULT_SPEC = REPO / "examples" / "cameras_multi.yaml"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="capture a specification twice with different cameras "
                    "and verify alignment, geometry recovery and "
                    "cross-view consistency")
    parser.add_argument("--spec", default=str(DEFAULT_SPEC),
                        help="scenario spec YAML (default: the committed "
                             "multi-camera example)")
    parser.add_argument("--out", default="runs/demo",
                        help="run directory for the first capture; the "
                             "camera variant lands beside it as "
                             "<out>_variant")
    parser.add_argument("--terrain", default=None,
                        help="baked heightfield stem for real-raster "
                             "physics and camera checks")
    parser.add_argument("--max-previews", type=int, default=8,
                        help="cap preview images per run (default 8; the "
                             "geometry is complete either way)")
    args = parser.parse_args(argv)

    from core.capture.verify import verify_alignment, verify_run
    from core.capture.manifest import read_capture_manifest
    from core.scenario.camera import CameraSpec
    from core.scenario.spec import ScenarioSpec
    from flightsim.capture import main as capture_main

    out = Path(args.out)
    variant_out = out.parent / f"{out.name}_variant"
    common = ["--max-previews", str(args.max_previews)]
    if args.terrain:
        common += ["--terrain", args.terrain]

    print(f"[1/4] capturing {args.spec} -> {out}")
    code = capture_main([args.spec, "--out", str(out), *common])
    if code != 0:
        return code

    # The SAME simulation, a different camera set. Only the cameras
    # change, so the simulation and telemetry digests must not.
    spec = ScenarioSpec.read(args.spec)
    counts = {int(c.capture_count.value) for c in spec.cameras
              if int(c.capture_count.value) > 0}
    count = sorted(counts)[0] if counts else 24
    cockpit = CameraSpec.defaulted(camera_id="shoulder", preset="cockpit",
                                   aircraft=str(spec.aircraft.value),
                                   terrain_elevation_m=float(
                                       spec.terrain_elevation.value))
    cockpit.set("capture_count", count,
                frm="the demo's camera variant: same count, different view")
    spec.cameras = [cockpit]
    variant_spec = variant_out.parent / f"{variant_out.name}.yaml"
    variant_spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write(variant_spec)

    print(f"[2/4] capturing the SAME simulation with a cockpit camera "
          f"-> {variant_out}")
    code = capture_main([str(variant_spec), "--out", str(variant_out),
                         *common])
    if code != 0:
        return code

    print(f"[3/4] verifying {out}")
    first = verify_run(out)
    print(first.render())
    print(f"[3/4] verifying {variant_out}")
    second = verify_run(variant_out)
    print(second.render())

    print("[4/4] temporal alignment between the two camera sets")
    alignment = verify_alignment(
        read_capture_manifest(out / "capture_manifest.json"),
        read_capture_manifest(variant_out / "capture_manifest.json"))
    print(f"  [{'PASS' if alignment.ok else 'FAIL'}] {alignment.name}: "
          f"{alignment.detail}")

    checks = list(first.checks) + list(second.checks) + [alignment]
    passed = sum(c.ok for c in checks)
    ok = first.ok and second.ok and alignment.ok
    print()
    print(f"DEMO {'PASSED' if ok else 'FAILED'} "
          f"({passed}/{len(checks)} checks across two runs)")
    if not ok:
        return 1
    from core.util.platform import UE_PLATFORM_REFUSAL, ue_available

    if not ue_available():
        print()
        print(UE_PLATFORM_REFUSAL)
        print("(the manifests, geometry previews and every check above "
              "are complete on this platform; only the pixels are "
              "refused)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
