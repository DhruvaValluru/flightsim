"""The pixel gate of lane aircraft_exterior.pbr_materials.night_ifr.

Runs on the Windows laptop over frames it rendered (numpy + Pillow, and the
repo's own 16-bit reader for the albedo pass). It measures; it renders
nothing. On the Mac it is only unit-tested on synthetic images and on a fake
run folder, which is not a visual result.

NOT RUNNABLE END TO END TODAY. It compares two renders of one night scene,
and both of these are still missing from the repository (INTEGRATION.md,
changes 1-4): the ``-aircraft-night-pbr`` switch, and a night scene in the
visual round list. Until an integrator lands them there is no candidate
frame to give it.

By round (the usual way; paths are resolved from what the rounds wrote):

    python swarm\\lanes\\aircraft_exterior\\pbr_materials\\night_ifr\\measure_gate.py ^
        --reference-round 90 --candidate-round 91 --scene 16 ^
        --out runs\\swarm\\night_pbr_gate.json

By file:

    python ...\\measure_gate.py --reference <ref frame.png> --candidate <cand frame.png> ^
        --mask <cand frame_NNNN_mask.png> ^
        [--reference-albedo <ref frame_NNNN_albedo.png> --albedo <cand frame_NNNN_albedo.png>]

Where the inputs come from (read in the source on the Mac, not observed in a
run):

- ``frame_NNNN_mask.png``: the web app's camera pass states ``-labels`` itself
  on every run (webapp/capture.py render_passes), so a visual round writes the
  ID image beside every frame without any extra switch. It is an 8-bit grey
  PNG whose value is the object's int_id; the primary airframe is always 1
  (core/capture/labels.py). Aircraft pixels are those equal to
  ``--aircraft-id`` (default 1).
- ``frame_NNNN_albedo.png``: written only when the round ran with
  ``FLIGHTSIM_CAPTURE_PASSES=albedo`` in the environment. 16-bit, LINEAR base
  colour * 65535.

Exit 0 = PASS, 1 = FAIL, 2 = VOID (the measurement could not be made; a VOID
is never a pass).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[4]
LANE = "aircraft_exterior.pbr_materials.night_ifr"

#: experiments/gate6_visual.py "night_min_mean_luminance": below this the
#: frame is black and nothing can be said about it.
NIGHT_MIN_LUMA = 2.0
#: The candidate's aircraft may not be darker than the reference's (the
#: dark-aircraft regression).
MIN_MEDIAN_DELTA = 0.0
#: Share of aircraft pixels at or below luma 1: crushed to black.
MAX_CRUSHED_FRACTION_RISE = 0.0
#: Albedo bounds, LINEAR, the bake's own clamp (bake_night_pbr.py ALBEDO_MIN /
#: ALBEDO_MAX), which is what the albedo pass stores.
ALBEDO_LINEAR = (0.023, 0.9)
ALBEDO_SLACK = 0.002                     # 16-bit rounding plus the engine's own
#: A pixel whose base colour moved by more than this between the two renders
#: is one the night branch touched.
ALBEDO_CHANGED = 0.002
ALBEDO_MAX_OUTSIDE_FRACTION = 0.001      # gate6_visual "albedo_max_changed_fraction"
MIN_MASK_PIXELS = 400
PRIMARY_AIRFRAME_ID = 1


def luma(path: Path) -> np.ndarray:
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)
    return rgb @ np.array([0.2126, 0.7152, 0.0722])


def aircraft_mask(path: Path, aircraft_ids=(PRIMARY_AIRFRAME_ID,)) -> np.ndarray:
    """The ID image's pixels that carry one of ``aircraft_ids``."""
    ids = np.asarray(Image.open(path))
    if ids.ndim == 3:                    # an RGB copy of the grey ID image
        ids = ids[..., 0]
    return np.isin(ids, [int(i) for i in aircraft_ids])


def read_albedo(path: Path) -> np.ndarray:
    """``frame_NNNN_albedo.png`` as (h, w, 3) linear base colour in [0, 1],
    through the repo's reader (Pillow drops the low byte of a 16-bit RGBA)."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from core.capture.labels import read_albedo_png

    return np.asarray(read_albedo_png(Path(path)), dtype=np.float64)


def measure(reference, candidate, mask, albedo=None, reference_albedo=None) -> dict:
    """Luma arrays HxW (0-255), mask HxW bool, albedo arrays HxWx3 LINEAR
    [0, 1] or None (candidate and reference render)."""
    out = {"lane": LANE, "mask_pixels": int(mask.sum())}
    if reference.shape != candidate.shape or reference.shape != mask.shape:
        return {**out, "verdict": "VOID", "why": "frames and mask differ in size"}
    if out["mask_pixels"] < MIN_MASK_PIXELS:
        return {**out, "verdict": "VOID", "why": f"fewer than {MIN_MASK_PIXELS} aircraft pixels"}
    ref, cand = reference[mask], candidate[mask]
    if np.array_equal(ref, cand):
        return {**out, "verdict": "VOID",
                "why": "the aircraft is pixel-identical in both frames: the switch changed "
                       "nothing (not built, not applied, or the same run given twice)"}
    out.update({
        "reference_median_luma": float(np.median(ref)), "candidate_median_luma": float(np.median(cand)),
        "reference_mean_luma": float(ref.mean()), "candidate_mean_luma": float(cand.mean()),
        "reference_crushed_fraction": float((ref <= 1.0).mean()),
        "candidate_crushed_fraction": float((cand <= 1.0).mean()),
        "background_mean_abs_change": float(np.abs(candidate[~mask] - reference[~mask]).mean())
        if (~mask).any() else 0.0,
    })
    out["median_delta"] = out["candidate_median_luma"] - out["reference_median_luma"]
    if out["reference_mean_luma"] < NIGHT_MIN_LUMA and out["candidate_mean_luma"] < NIGHT_MIN_LUMA:
        return {**out, "verdict": "VOID",
                "why": f"both aircraft are under luma {NIGHT_MIN_LUMA}: the shot is black"}
    clauses = {
        "not_darker": out["median_delta"] >= MIN_MEDIAN_DELTA,
        "above_night_floor": out["candidate_mean_luma"] >= NIGHT_MIN_LUMA,
        "not_more_crushed": out["candidate_crushed_fraction"] - out["reference_crushed_fraction"]
        <= MAX_CRUSHED_FRACTION_RISE,
    }
    if albedo is not None:
        if albedo.shape[:2] != mask.shape:
            return {**out, "verdict": "VOID", "why": "albedo and mask differ in size"}
        lo, hi = ALBEDO_LINEAR[0] - ALBEDO_SLACK, ALBEDO_LINEAR[1] + ALBEDO_SLACK
        px = albedo[mask]
        outside = ((px < lo) | (px > hi)).any(axis=-1)
        # Reported, never gated: glass, tyres, lights and markings sit outside
        # the paint range by design and this lane does not touch them.
        out["albedo_outside_fraction_whole_aircraft"] = float(outside.mean())
        if reference_albedo is None:
            out["albedo"] = ("range reported, not gated: no --reference-albedo, so the pixels "
                             "the night branch changed cannot be told from glass and tyres")
        elif reference_albedo.shape != albedo.shape:
            return {**out, "verdict": "VOID", "why": "the two albedo passes differ in size"}
        else:
            changed = (np.abs(px - reference_albedo[mask]) > ALBEDO_CHANGED).any(axis=-1)
            out["albedo_changed_fraction"] = float(changed.mean())
            out["albedo_changed_outside_fraction"] = float((changed & outside).mean())
            clauses["changed_albedo_in_range"] = (out["albedo_changed_outside_fraction"]
                                                  <= ALBEDO_MAX_OUTSIDE_FRACTION)
    else:
        out["albedo"] = "not measured: no albedo pass given"
    out["clauses"] = {k: bool(v) for k, v in clauses.items()}
    out["verdict"] = "PASS" if all(clauses.values()) else "FAIL"
    return out


# -- finding what a visual round wrote -----------------------------------------

def _has_key(node, key: str) -> bool:
    if isinstance(node, dict):
        return key in node or any(_has_key(v, key) for v in node.values())
    if isinstance(node, list):
        return any(_has_key(v, key) for v in node)
    return False


def round_inputs(round_number: int, scene: int, repo: Path = REPO) -> dict:
    """One scene of one visual round: its frame, ID image, albedo pass (or
    None), spec hash and whether its render.json records the night branch.
    Raises FileNotFoundError naming what is missing."""
    summary = repo / "docs" / "visual" / f"round_{round_number}" / "summary.json"
    if not summary.is_file():
        raise FileNotFoundError(f"{summary}: round {round_number} wrote no summary")
    rows = [r for r in json.loads(summary.read_text(encoding="utf-8"))
            if isinstance(r, dict) and int(r.get("number", -1)) == int(scene)]
    if not rows or not rows[0].get("run_id"):
        raise FileNotFoundError(f"{summary}: no run for scene {scene}")
    frames = repo / "runs" / "webapp" / str(rows[0]["run_id"]) / "frames"
    cameras = sorted(d for d in frames.glob("*") if d.is_dir()) if frames.is_dir() else []
    if not cameras:
        raise FileNotFoundError(f"{frames}: no camera folder")
    folder = cameras[0]

    def first(pattern, needed=True):
        found = sorted(folder.glob(pattern))
        if not found and needed:
            raise FileNotFoundError(f"{folder}: no {pattern}")
        return found[0] if found else None

    render = folder / "render.json"
    return {"frame": first("frame_*[0-9].png"), "mask": first("frame_*_mask.png"),
            "albedo": first("frame_*_albedo.png", needed=False),
            "spec_sha256": rows[0].get("spec_sha256"),
            "night_pbr_recorded": render.is_file() and _has_key(
                json.loads(render.read_text(encoding="utf-8")), "night_pbr")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference-round", type=int)
    parser.add_argument("--candidate-round", type=int)
    parser.add_argument("--scene", type=int)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--mask", type=Path)
    parser.add_argument("--albedo", type=Path)
    parser.add_argument("--reference-albedo", type=Path)
    parser.add_argument("--aircraft-id", type=int, nargs="+", default=[PRIMARY_AIRFRAME_ID],
                        help="int_id(s) of the airframe in the ID image (default 1, the primary)")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    void = None
    by_round = args.reference_round is not None or args.candidate_round is not None
    if by_round:
        if None in (args.reference_round, args.candidate_round, args.scene):
            parser.error("--reference-round, --candidate-round and --scene go together")
        try:
            ref = round_inputs(args.reference_round, args.scene)
            cand = round_inputs(args.candidate_round, args.scene)
        except FileNotFoundError as exc:
            void = str(exc)
        else:
            args.reference, args.candidate, args.mask = ref["frame"], cand["frame"], cand["mask"]
            args.albedo, args.reference_albedo = cand["albedo"], ref["albedo"]
            if ref["spec_sha256"] != cand["spec_sha256"]:
                void = "the two rounds rendered different pinned specs: not the same shot"
            elif not cand["night_pbr_recorded"]:
                void = ("the candidate's render.json records no night_pbr: the switch was not "
                        "applied (INTEGRATION.md change 3 not built?)")
            elif ref["night_pbr_recorded"]:
                void = "the reference's render.json records night_pbr: it is not the reference"
    elif None in (args.reference, args.candidate, args.mask):
        parser.error("give --reference-round/--candidate-round/--scene, or "
                     "--reference, --candidate and --mask")

    if void is None:
        result = measure(luma(args.reference), luma(args.candidate),
                         aircraft_mask(args.mask, args.aircraft_id),
                         read_albedo(args.albedo) if args.albedo else None,
                         read_albedo(args.reference_albedo) if args.reference_albedo else None)
    else:
        result = {"lane": LANE, "verdict": "VOID", "why": void}
    result["inputs"] = {k: str(v) for k, v in vars(args).items() if v is not None}
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return {"PASS": 0, "FAIL": 1}.get(result["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
