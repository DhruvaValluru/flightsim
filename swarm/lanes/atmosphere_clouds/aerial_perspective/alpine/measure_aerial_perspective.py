"""Aerial-perspective measurement for the alpine frame (scenario 11, the
Matterhorn). Visual-only. Run on the Windows laptop on rendered frames; the
Mac only unit-tests the arithmetic on synthetic images and never produces a
result.

Two frames of the same pinned scenario, both made with switches that exist
today (INTEGRATION.md has the exact commands):

  clear   FLIGHTSIM_RENDER_SWITCHES=-NoAerialPerspective  (atmosphere and height fog hidden)
  hazed   no switch: the frame the engine draws today

    python measure_aerial_perspective.py stash --scenario 11 --as clear|hazed
    python measure_aerial_perspective.py measure --clear C.png --hazed H.png ^
        --clear-json C.render.json --hazed-json H.render.json ^
        --box-near x0,y0,x1,y1 --near-km <km> --box-far x0,y0,x1,y1 --far-km <km> ^
        --altitude-m 5000

Inside each box (sunlit textured terrain at roughly one distance, no sky, no
aircraft) every channel of the hazed frame is fitted against the same pixels
of the clear frame:  hazed = slope * clear + offset.

Why two boxes. Hiding the atmosphere also removes the sun's own attenuation
and the sky light, so one box's slope is transmittance times an unknown
lighting ratio and cannot be compared with a transmittance. The ratio of two
slopes cancels that factor (and any constant exposure gain) when both boxes
are lit the same way:

    slope_far / slope_near  ~  T(far) / T(near)

Metric  ap_log_t_ratio_error = mean over R,G,B of
    | ln(slope_far / slope_near) - ln(T_model(far) / T_model(near)) |

T_model is bake_alpine_ap.reference() with the Mie layer the hazed run's
render.json recorded (mie_scattering_scale_per_km, mie_absorption_scale_per_km,
mie_scale_height_km, aerial_perspective_view_distance_scale). Rayleigh and
ozone stay the bake's ASSUMED constants; each constant's origin is printed.

What the number is NOT:
  * not a validated pass/fail. PROVISIONAL_THRESHOLD (0.15) was chosen before
    any engine frame existed. On synthetic frames pushed through a filmic
    curve (the ACES fit, 0.5x to 2x exposure) the metric's own bias was 0.015
    to 0.09, over half the threshold at worst, against 0.001 with no curve
    (tests/test_swarm_atmosphere_clouds_aerial_perspective_alpine.py). The
    engine's curve is not that fit. The first Windows run therefore
    calibrates the threshold; it does not pass or fail anything.
  * the model has no height fog; the engine frame does. Fog extinction lands
    in the measured ratio and in the error.
  * tonemapped 8-bit PNGs: pixels outside 0.02..0.60 (decoded) are dropped.

Exit: 0 measured and at or under the provisional threshold, 1 measured and
over it, 2 refused by name (inputs cannot support a measurement).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PROVISIONAL_THRESHOLD = 0.15
MID_LO, MID_HI = 0.02, 0.60
MIN_PIXELS = 200
MIN_R2 = 0.5
NO_ATMOSPHERE_PREFIX = "nothing: no visible sky atmosphere"

#: render.json key -> bake module constant it replaces in the model
RENDER_JSON_CONSTANTS = {
    "mie_scattering_scale_per_km": "MIE_SCATTERING",
    "mie_absorption_scale_per_km": "MIE_ABSORPTION",
    "mie_scale_height_km": "MIE_SCALE_HEIGHT_KM",
}
DISTANCE_SCALE_KEY = "aerial_perspective_view_distance_scale"


class Refused(Exception):
    def __init__(self, rule, message):
        super().__init__(message)
        self.rule = rule


def _bake():
    spec = importlib.util.spec_from_file_location("alpine_ap_bake_for_gate", HERE / "bake_alpine_ap.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# -- render.json --------------------------------------------------------------

def find_values(node, key):
    """Every value stored under ``key`` anywhere in a JSON document."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                out.append(v)
            out.extend(find_values(v, key))
    elif isinstance(node, list):
        for v in node:
            out.extend(find_values(v, key))
    return out


def atmosphere_is_hidden(doc):
    """True when the run records that -NoAerialPerspective took effect: the
    switch was on the command line AND the atmosphere pass says it applied
    nothing. The first alone only shows the token arrived."""
    flagged = any(v is True for v in find_values(doc, "aerial_perspective_off"))
    applied_nothing = any(isinstance(v, str) and v.startswith(NO_ATMOSPHERE_PREFIX)
                          for v in find_values(doc, "applied"))
    return flagged and applied_nothing


def check_runs(clear_doc, hazed_doc):
    if not atmosphere_is_hidden(clear_doc):
        raise Refused("ap_gate.clear_frame_not_clear",
                      "the clear run's render.json does not record aerial_perspective_off=true with an atmosphere "
                      f"record starting '{NO_ATMOSPHERE_PREFIX}': -NoAerialPerspective did not take effect on this "
                      "render path (check render.log's command line)")
    if any(v is True for v in find_values(hazed_doc, "aerial_perspective_off")):
        raise Refused("ap_gate.hazed_frame_has_no_atmosphere",
                      "the hazed run's render.json records aerial_perspective_off=true")


def model_constants(hazed_doc):
    """Bake-constant overrides from the hazed run, the distance scale, and
    where each number the model uses came from."""
    overrides, origin = {}, {}
    for key, name in RENDER_JSON_CONSTANTS.items():
        found = [v for v in find_values(hazed_doc, key) if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if found:
            overrides[name] = float(found[0])
            origin[name] = f"render.json {key}"
        else:
            origin[name] = "ASSUMED (bake constant; the run did not record it)"
    scales = [v for v in find_values(hazed_doc, DISTANCE_SCALE_KEY)
              if isinstance(v, (int, float)) and not isinstance(v, bool)]
    scale = float(scales[0]) if scales else 1.0
    origin["distance_scale"] = f"render.json {DISTANCE_SCALE_KEY}" if scales else "ASSUMED 1.0"
    for name in ("RAYLEIGH_SCATTERING", "RAYLEIGH_SCALE_HEIGHT_KM", "OZONE_ABSORPTION"):
        origin[name] = "ASSUMED (typed from memory of Hillaire 2020; never read from the engine)"
    return overrides, scale, origin


def model_transmittance(overrides, scale, altitude_m, view_elevation_deg, distance_km):
    """Rayleigh + Mie + ozone transmittance of the model over the distance the
    engine's aerial perspective uses (distance * view-distance scale)."""
    bake = _bake()
    for name, value in overrides.items():
        setattr(bake, name, value)
    # transmittance along the view ray does not depend on the sun; 30 is a dummy
    return bake.reference(altitude_m, 30.0, view_elevation_deg, distance_km * scale)["transmittance_rgb"]


# -- pixels -------------------------------------------------------------------

def srgb_to_linear(u8):
    v = np.asarray(u8, dtype=np.float64) / 255.0
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def fit_channel(clear, hazed):
    """Least-squares hazed = slope * clear + offset over mid-tone pixels."""
    keep = (clear > MID_LO) & (clear < MID_HI) & (hazed > MID_LO) & (hazed < MID_HI)
    x, y = clear[keep], hazed[keep]
    if x.size < MIN_PIXELS or float(np.var(x)) < 1e-6:
        raise Refused("ap_gate.box_unusable",
                      f"{x.size} mid-tone pixels, variance {float(np.var(x)) if x.size else 0:.2e}: "
                      "pick a box with textured, sunlit terrain")
    slope, offset = np.polyfit(x, y, 1)
    r2 = float(np.corrcoef(x, y)[0, 1] ** 2)
    if r2 < MIN_R2 or slope <= 0.0:
        raise Refused("ap_gate.frames_misaligned",
                      f"r^2 {r2:.2f}, slope {slope:.3f}: the two frames do not show the same pixels in this box "
                      "(different camera, time or scenario spec)")
    return float(slope), float(offset), int(x.size), r2


def fit(clear_rgb, hazed_rgb):
    out = [fit_channel(clear_rgb[..., c].ravel(), hazed_rgb[..., c].ravel()) for c in range(3)]
    return {"slope_rgb": [o[0] for o in out], "offset_rgb": [o[1] for o in out],
            "pixels": min(o[2] for o in out), "r2_min": min(o[3] for o in out)}


def ratio_error(near, far, t_near, t_far):
    measured = np.log(np.asarray(far["slope_rgb"]) / np.asarray(near["slope_rgb"]))
    model = np.log(np.asarray(t_far) / np.asarray(t_near))
    return float(np.mean(np.abs(measured - model))), measured.tolist(), model.tolist()


def evaluate(clear_near, hazed_near, clear_far, hazed_far, t_near, t_far):
    near, far = fit(clear_near, hazed_near), fit(clear_far, hazed_far)
    error, measured, model = ratio_error(near, far, t_near, t_far)
    return {"near": near, "far": far,
            "ln_t_ratio_measured_rgb": measured, "ln_t_ratio_model_rgb": model,
            "ap_log_t_ratio_error": error,
            "provisional_threshold": PROVISIONAL_THRESHOLD,
            "threshold_status": "PROVISIONAL: never checked against an engine frame",
            "at_or_under_provisional_threshold": bool(error <= PROVISIONAL_THRESHOLD)}


def _box(text):
    box = [int(v) for v in text.split(",")]
    if len(box) != 4 or box[2] <= box[0] or box[3] <= box[1]:
        raise Refused("ap_gate.box_unusable", f"box '{text}' is not x0,y0,x1,y1")
    return box


def _crop(path, box):
    from PIL import Image
    x0, y0, x1, y1 = box
    return srgb_to_linear(np.asarray(Image.open(path).convert("RGB"))[y0:y1, x0:x1])


# -- commands -----------------------------------------------------------------

def stash(scenario, label, summary_path=None, runs_dir=None, out_dir=None):
    """Copy scenario N's first frame and render.json out of the last batch
    (runs/test_scenarios.json) before the next batch overwrites the summary."""
    runs_dir = Path(runs_dir or REPO / "runs")     # run folders: runs/webapp/<run_id> (run_test_scenarios.RUNS)
    summary_path = Path(summary_path or runs_dir / "test_scenarios.json")
    out_dir = Path(out_dir or runs_dir / "alpine_ap")
    if not summary_path.is_file():
        raise Refused("ap_gate.no_batch", f"{summary_path} not found: run the scenario first")
    doc = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = doc if isinstance(doc, list) else next((v for v in doc.values() if isinstance(v, list)), [])
    row = next((r for r in rows if isinstance(r, dict) and int(r.get("number", -1)) == scenario), None)
    if row is None or not row.get("run_id"):
        raise Refused("ap_gate.no_run", f"scenario {scenario} has no run in {summary_path}")
    frames = runs_dir / "webapp" / str(row["run_id"]) / "frames"
    render_json = frames / "render.json"
    cameras = sorted(d for d in frames.glob("*") if d.is_dir()) if frames.is_dir() else []
    pngs = sorted(cameras[0].glob("frame_*[0-9].png")) if cameras else []
    if not pngs or not render_json.is_file():
        raise Refused("ap_gate.no_frame", f"no frame_*.png or render.json under {frames}")
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pngs[0], out_dir / f"{label}.png")
    shutil.copy2(render_json, out_dir / f"{label}.render.json")
    return {"run_id": row["run_id"], "name": row.get("name"), "frame": str(out_dir / f"{label}.png"),
            "render_json": str(out_dir / f"{label}.render.json")}


def measure(a):
    clear_doc = json.loads(Path(a.clear_json).read_text(encoding="utf-8"))
    hazed_doc = json.loads(Path(a.hazed_json).read_text(encoding="utf-8"))
    check_runs(clear_doc, hazed_doc)
    overrides, scale, origin = model_constants(hazed_doc)
    near_box, far_box = _box(a.box_near), _box(a.box_far)
    t_near = model_transmittance(overrides, scale, a.altitude_m, a.near_elevation_deg, a.near_km)
    t_far = model_transmittance(overrides, scale, a.altitude_m, a.far_elevation_deg, a.far_km)
    result = evaluate(_crop(a.clear, near_box), _crop(a.hazed, near_box),
                      _crop(a.clear, far_box), _crop(a.hazed, far_box), t_near, t_far)
    result.update(model_constants_used={**overrides, "distance_scale": scale}, model_constant_origin=origin,
                  model_omits="height fog, multiple scattering")
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description="alpine aerial-perspective measurement (visual-only)")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("stash")
    s.add_argument("--scenario", type=int, default=11)
    s.add_argument("--as", dest="label", choices=("clear", "hazed"), required=True)
    m = sub.add_parser("measure")
    for name in ("--clear", "--hazed", "--clear-json", "--hazed-json", "--box-near", "--box-far"):
        m.add_argument(name, required=True)
    m.add_argument("--near-km", type=float, required=True)
    m.add_argument("--far-km", type=float, required=True)
    m.add_argument("--altitude-m", type=float, default=5000.0)
    m.add_argument("--near-elevation-deg", type=float, default=0.0)
    m.add_argument("--far-elevation-deg", type=float, default=0.0)
    a = p.parse_args(argv)
    try:
        if a.command == "stash":
            print(json.dumps(stash(a.scenario, a.label), indent=1))
            return 0
        result = measure(a)
    except Refused as refusal:
        print(json.dumps({"refused": refusal.rule, "why": str(refusal)}))
        return 2
    print(json.dumps(result, indent=1))
    return 0 if result["at_or_under_provisional_threshold"] else 1


if __name__ == "__main__":
    sys.exit(main())
