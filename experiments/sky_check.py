"""The physical sky, measured from rendered pixels on THIS machine.

The physical sky (core/sky/plan.py, -sky=) was written without an engine
to render it; its values are computed and unit-tested, but whether UE turns
them into the intended picture is decided here, the way Gate 6 decides its
clauses: render, read the PNGs, compare against stated criteria. Run it
once after building; a green result is this machine's claim that the
physical sky renders, and the point at which FLIGHTSIM_SKY=physical may be
made the default here.

Four cells over flat ground at the Matterhorn's coordinates (so the sky
geometry is a real place's), same card, same camera:

* noon         -- sun high: a blue, bright sky; ground exposed mid-grey.
* sunset       -- sun at +0.5 deg: a darker frame than noon, warmer sky.
* night_full   -- 2024-01-25 full moon: dark, stars drawn, moon up.
* night_new    -- 2024-02-09 new moon: darker still, more stars visible.

The claims checked, stated first
--------------------------------
1. Every frame is non-blank and the manifest carries the sky block the
   plan asked for (stars drawn at night, none by day; exposure recorded).
2. Sky brightness orders noon > sunset > night_full >= night_new (upper
   third of the frame, mean luma), each step by a stated margin: the sun,
   atmosphere and EV100 together must make night look like night.
3. Noon is exposed, not clipped or crushed: frame mean luma inside a band,
   and < 2 % of pixels at 255.
4. Moonless night shows stars: isolated bright pixels in the sky region
   (a pixel >= 3x the local median, above an absolute floor), at least a
   stated count -- and noon shows (essentially) none of them.

Usage: .venv/bin/python experiments/sky_check.py [--skip-renders]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from core.sky.plan import plan_sky  # noqa: E402
from core.util.platform import ue_editor_path  # noqa: E402
from experiments.gate5_ue_parity import reference_spec, write_run_card  # noqa: E402

RULE = "=" * 96
LAT, LON = 45.9763, 7.6586

CELLS = {
    "noon": ("noon", "2026-03-20"),
    "sunset": ("sunset", "2026-03-20"),
    "night_full": ("2024-01-25T23:00", "none"),
    "night_new": ("2024-02-09T23:00", "none"),
}

CHECKS = {
    #: Sky-region mean luma ratios between successive cells.
    "min_noon_over_sunset": 1.3,
    "min_sunset_over_night": 3.0,
    #: Noon exposure band (frame mean luma, 0-255) and clipping.
    "noon_mean_band": (70.0, 200.0),
    "max_clipped_fraction": 0.02,
    #: Star detection: pixels this many times their neighbourhood median,
    #: above this absolute luma.
    "star_contrast": 3.0,
    "star_floor": 40.0,
    "min_stars_moonless": 25,
    "max_stars_noon": 3,
}


def render(card: Path, frames: Path, sky: Path) -> Dict:
    project = Path(__file__).resolve().parents[1] / "ue" / "FlightSim.uproject"
    frames.mkdir(parents=True, exist_ok=True)
    (frames / "render.json").unlink(missing_ok=True)
    command = [
        str(ue_editor_path()), str(project),
        "-run=FlightSimBridge.FlightSimRender",
        f"-scenario={card}", f"-frames={frames}",
        "-Visual", "-shot=showcase", "-chase=-40:0:5",
        # Look up a little so the sky fills the upper third.
        "-camera=chase", "-width=1280", "-height=720", "-fps=2",
        "-seconds=3", f"-sky={sky}", "-fog-density=0.0012",
        "-unattended", "-nopause", "-nosplash",
        "-stdout", "-FullStdOutLogOutput",
        "-RenderOffScreen", "-AllowCommandletRendering",
    ]
    log = frames.parent / f"{frames.name}.log"
    with log.open("w") as sink:
        proc = subprocess.run(command, stdout=sink, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL)
    manifest = frames / "render.json"
    if not manifest.is_file():
        raise RuntimeError(f"render into {frames} wrote no manifest (exit "
                           f"{proc.returncode}); see {log}")
    return json.loads(manifest.read_text(encoding="utf-8"))


def luma(image: np.ndarray) -> np.ndarray:
    return (0.2126 * image[..., 0] + 0.7152 * image[..., 1]
            + 0.0722 * image[..., 2])


def star_count(sky_luma: np.ndarray) -> int:
    """Isolated bright points: brighter than CHECKS['star_contrast'] times
    the median of their 9x9 neighbourhood and above the absolute floor."""
    from numpy.lib.stride_tricks import sliding_window_view

    padded = np.pad(sky_luma, 4, mode="edge")
    local = np.median(sliding_window_view(padded, (9, 9)), axis=(-1, -2))
    hits = ((sky_luma >= CHECKS["star_floor"])
            & (sky_luma >= CHECKS["star_contrast"] * np.maximum(local, 1.0)))
    return int(hits.sum())


def main() -> int:
    from PIL import Image

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-renders", action="store_true",
                    help="re-measure existing frames only")
    args = ap.parse_args()
    out = Path("runs/sky_check")
    out.mkdir(parents=True, exist_ok=True)

    spec = reference_spec("fly the c172p at 1000 m and 100 kt for 30 seconds")
    spec.set("latitude", LAT, frm="sky check: a real place's sky")
    spec.set("longitude", LON, frm="sky check: a real place's sky")
    card = write_run_card(spec, out / "card.json")

    measured: Dict[str, Dict] = {}
    for name, (time_value, weather_date) in CELLS.items():
        plan = plan_sky(time_value, weather_date, LAT, LON,
                        float(spec.altitude.value),
                        float(spec.terrain_elevation.value))
        sky = out / f"{name}_sky.json"
        sky.write_text(json.dumps(plan, indent=1), encoding="ascii")
        frames = out / name
        if args.skip_renders:
            manifest = json.loads(
                (frames / "render.json").read_text(encoding="utf-8"))
        else:
            print(f"rendering {name} ({plan['instant_utc']}) ...", flush=True)
            manifest = render(card, frames, sky)
        pngs = sorted(frames.glob("frame_*.png"))
        image = np.asarray(Image.open(pngs[len(pngs) // 2]).convert("RGB"),
                           dtype=np.float64)
        y = luma(image)
        sky_region = y[: y.shape[0] // 3]
        measured[name] = {
            "plan_ev100": plan["exposure"]["ev100"],
            "plan_stars": plan["stars"]["count"],
            "manifest_sky": manifest.get("scene", {}).get("sky", {}),
            "blank_frames": manifest.get("blank_frames"),
            "frame_mean": float(y.mean()),
            "sky_mean": float(sky_region.mean()),
            "clipped_fraction": float((image >= 254.5).all(axis=2).mean()),
            "star_pixels": star_count(sky_region),
        }

    m = measured
    results = []

    def clause(label, ok, detail):
        results.append((label, bool(ok), detail))

    for name, cell in m.items():
        sky_block = cell["manifest_sky"]
        expect_stars = name.startswith("night")
        clause(f"1 {name}: sky block + stars as planned",
               sky_block and (sky_block.get("stars_drawn", 0) > 0)
               == expect_stars and not cell["blank_frames"],
               f"stars_drawn {sky_block.get('stars_drawn')}, blank "
               f"{cell['blank_frames']}")
    r1 = m["noon"]["sky_mean"] / max(m["sunset"]["sky_mean"], 1e-3)
    r2 = m["sunset"]["sky_mean"] / max(m["night_full"]["sky_mean"], 1e-3)
    clause("2 noon sky brighter than sunset",
           r1 >= CHECKS["min_noon_over_sunset"], f"ratio {r1:.2f}")
    clause("2 sunset sky brighter than full-moon night",
           r2 >= CHECKS["min_sunset_over_night"], f"ratio {r2:.2f}")
    clause("2 moonless night no brighter than full-moon night",
           m["night_new"]["sky_mean"] <= m["night_full"]["sky_mean"] + 1.0,
           f"{m['night_new']['sky_mean']:.1f} vs "
           f"{m['night_full']['sky_mean']:.1f}")
    low, high = CHECKS["noon_mean_band"]
    clause("3 noon exposed inside the band",
           low <= m["noon"]["frame_mean"] <= high,
           f"mean {m['noon']['frame_mean']:.1f} in [{low}, {high}]")
    clause("3 noon not clipped",
           m["noon"]["clipped_fraction"] < CHECKS["max_clipped_fraction"],
           f"{m['noon']['clipped_fraction']:.2%} at 255")
    clause("4 moonless night shows stars",
           m["night_new"]["star_pixels"] >= CHECKS["min_stars_moonless"],
           f"{m['night_new']['star_pixels']} star pixels")
    clause("4 noon shows none",
           m["noon"]["star_pixels"] <= CHECKS["max_stars_noon"],
           f"{m['noon']['star_pixels']} star pixels")

    print(RULE)
    print("Physical sky check (rendered pixels, this machine)")
    print(RULE)
    for label, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label:52s} {detail}")
    (out / "report.json").write_text(json.dumps(
        {"checks": CHECKS, "measured": measured,
         "clauses": [{"clause": c, "pass": ok, "detail": d}
                     for c, ok, d in results]}, indent=1, default=str), encoding="utf-8")
    passed = all(ok for _, ok, _ in results)
    print(RULE)
    print("PASS -- FLIGHTSIM_SKY=physical may be made this machine's default"
          if passed else "FAIL -- see runs/sky_check/*.log and the frames")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
