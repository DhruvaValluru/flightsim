"""Estimate control-surface hinge lines from the surface geometry itself.

The c172p and 747 configs carried hinge lines transcribed from each model's
FlightGear animation XML. The Phase 7 airframes (A320, DHC6, p51d) get them
from the geometry instead: a control surface's hinge is physically its
leading edge, so the estimator takes the surface object's vertices (in the
measured ac -> model frame mapping), finds the forward extreme, and returns
the leading-edge line across the span.

This is an ESTIMATE with a stated basis, not a transcription: the animation
XML of these models drives multi-axis linkages the converter does not model.
What keeps it honest is the downstream measurement -- gate5_realmesh renders
the deflected surfaces and measures the deflection ON SCREEN off the scene
component transforms, so a hinge line that is wrong shows up as a failed
on-screen clause, not as a quiet cosmetic error.

Usage:
    .venv/bin/python assets_pipeline/estimate_hinges.py <model.ac> <object> [...]
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assets_pipeline.acmodel import parse_ac, world_vertices  # noqa: E402


def ac_to_model(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """The measured mapping: model.x = ac.x, model.y = -ac.z, model.z = ac.y."""
    return (v[0], -v[2], v[1])


def estimate(path, object_names: Sequence[str]) -> Dict[str, List[List[float]]]:
    """Hinge line per object: the leading edge across the span, model metres.

    The span axis is whichever of y (horizontal surfaces) or z (vertical
    surfaces, i.e. rudders) the object extends further along. Because wings
    sweep and taper, the leading edge's x varies along the span, so a single
    forward band would catch only one corner (measured: the p51d aileron
    came out 5 cm long that way). Instead the hinge is the line through the
    per-slice leading edges at the two span extremes: vertices in the
    outermost 10% span slices, forward extreme of each.
    """
    model = parse_ac(path)
    wanted = {name.lower(): name for name in object_names}
    out: Dict[str, List[List[float]]] = {}
    for obj, vertices in world_vertices(model):
        if obj.name.lower() not in wanted or not vertices:
            continue
        pts = [ac_to_model(v) for v in vertices]
        ys = [p[1] for p in pts]
        zs = [p[2] for p in pts]
        span_axis = 1 if (max(ys) - min(ys)) >= (max(zs) - min(zs)) else 2
        span = [p[span_axis] for p in pts]
        s_min, s_max = min(span), max(span)
        width = max(s_max - s_min, 1e-6)
        lo_slice = [p for p in pts if p[span_axis] <= s_min + 0.10 * width]
        hi_slice = [p for p in pts if p[span_axis] >= s_max - 0.10 * width]
        lo = min(lo_slice, key=lambda p: p[0])
        hi = min(hi_slice, key=lambda p: p[0])
        out[wanted[obj.name.lower()]] = [
            [round(c, 4) for c in lo], [round(c, 4) for c in hi]]
    missing = [n for n in object_names if n not in out]
    if missing:
        raise SystemExit(f"objects not found in {path}: {missing}")
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print(__doc__)
        return 2
    path, names = argv[0], argv[1:]
    for name, line in estimate(path, names).items():
        print(f"{name}: {line[0]} -> {line[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
