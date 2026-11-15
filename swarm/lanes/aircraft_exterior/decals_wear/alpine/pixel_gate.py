"""Pixel gate for the alpine airframe wear layer. Runs on the WINDOWS laptop.

Compares two capture runs of the same spec, both with `--passes albedo`:
the reference (wear off) and the candidate (wear on at some tier).

Wear footprint M = pixels whose albedo pass moved by more than 257/65535 in
any channel. On M:

  detail_gain   mean |Laplacian| of albedo luminance, candidate / reference.
                The improvement metric: >= 1.25.
  beauty_ratio  mean linear luminance of the beauty frame, candidate /
                reference. The dark-aircraft guard: >= 0.90.
  dark_fraction share of M whose candidate albedo luminance is below 0.03
                where the reference was not: <= 0.03.
  albedo_p99    99th percentile of candidate albedo luminance: <= 0.90
                (or the reference's own p99 when that is already higher).
  changed_fraction  |M| / frame: within [0.002, 0.35] (wear present, and not
                leaking onto the terrain tiles).

The functions take arrays, so the arithmetic is unit-tested on the Mac with
synthetic frames, and main() is run there on synthetic run folders. That is
a code check, NOT a visual result. The gate has never read a real capture.

BLOCKED until the integrator lands the switch (INTEGRATION.md item 4): the
repo has no FLIGHTSIM_AIRCRAFT_WEAR today. Run it through run_gate.cmd, which
refuses by name when the switch is missing instead of rendering twice.

Exit codes, so a missing switch never reads as a wear failure:
  0  pass
  1  wear was drawn and broke a threshold (a real wear failure)
  2  input files missing or unpaired
  3  NOT MEASURED: no proof the two runs differ in wear. Either render.json
     does not state `aircraft_wear` (`off` for the reference, `tier<N>` for
     the candidate), or no frame's albedo moved at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

import numpy as np

THRESHOLDS = {
    "detail_gain_min": 1.25,
    "beauty_ratio_min": 0.90,
    "dark_fraction_max": 0.03,
    "albedo_p99_max": 0.90,
    "changed_fraction_min": 0.002,
    "changed_fraction_max": 0.35,
}
ALBEDO_MOVED = 257.0 / 65535.0
_LUMA = np.array([0.2126, 0.7152, 0.0722])


def srgb_to_linear(u8) -> np.ndarray:
    c = np.asarray(u8, dtype=float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def laplacian_energy(lum: np.ndarray, mask: np.ndarray) -> float:
    lap = np.abs(4.0 * lum[1:-1, 1:-1] - lum[:-2, 1:-1] - lum[2:, 1:-1]
                 - lum[1:-1, :-2] - lum[1:-1, 2:])
    m = mask[1:-1, 1:-1]
    return float(lap[m].mean()) if m.any() else 0.0


def evaluate(albedo_ref, albedo_cand, beauty_ref_u8, beauty_cand_u8) -> Dict:
    """Albedo: linear float (H, W, 3) in [0, 1]. Beauty: sRGB uint8 (H, W, 3)."""
    a_ref, a_cand = np.asarray(albedo_ref, float), np.asarray(albedo_cand, float)
    mask = (np.abs(a_cand - a_ref) > ALBEDO_MOVED).any(axis=-1)
    out: Dict = {"changed_fraction": float(mask.mean())}
    t = THRESHOLDS
    if not mask.any():
        out.update(ok=False, failed=["changed_fraction"])
        return out
    l_ref, l_cand = a_ref @ _LUMA, a_cand @ _LUMA
    b_ref = srgb_to_linear(beauty_ref_u8)[..., :3] @ _LUMA
    b_cand = srgb_to_linear(beauty_cand_u8)[..., :3] @ _LUMA
    e_ref = laplacian_energy(l_ref, mask)
    out["detail_gain"] = laplacian_energy(l_cand, mask) / max(e_ref, 1e-6)
    out["beauty_ratio"] = float(b_cand[mask].mean() / max(b_ref[mask].mean(), 1e-6))
    out["dark_fraction"] = float(((l_cand < 0.03) & (l_ref >= 0.03))[mask].mean())
    out["albedo_p99"] = float(np.percentile(l_cand[mask], 99))
    p99_cap = max(t["albedo_p99_max"], float(np.percentile(l_ref[mask], 99))) + 1e-3
    checks = {
        "changed_fraction": t["changed_fraction_min"] <= out["changed_fraction"] <= t["changed_fraction_max"],
        "detail_gain": out["detail_gain"] >= t["detail_gain_min"],
        "beauty_ratio": out["beauty_ratio"] >= t["beauty_ratio_min"],
        "dark_fraction": out["dark_fraction"] <= t["dark_fraction_max"],
        "albedo_p99": out["albedo_p99"] <= p99_cap,
    }
    out["failed"] = sorted(k for k, v in checks.items() if not v)
    out["ok"] = not out["failed"]
    return out


def _load_pair(run: Path, albedo_png: Path, beauty_suffix: str):
    repo = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(repo))
    from core.capture.labels import read_rgb16_png  # rasterio: Pillow drops 16-bit RGB to 8
    from PIL import Image

    albedo = np.asarray(read_rgb16_png(albedo_png), dtype=float)
    if albedo.ndim == 3 and albedo.shape[0] in (3, 4) and albedo.shape[-1] not in (3, 4):
        albedo = np.moveaxis(albedo, 0, -1)
    if albedo.max() > 1.5:
        albedo = albedo / 65535.0
    beauty = run / albedo_png.name.replace("_albedo.png", beauty_suffix)
    return albedo[..., :3], np.asarray(Image.open(beauty).convert("RGB"))


WEAR_KEY = "aircraft_wear"
WEAR_VALUES = ("off", "tier0", "tier1", "tier2", "tier3")


def _find_key(node, key):
    if isinstance(node, dict):
        if key in node:
            yield node[key]
        for v in node.values():
            yield from _find_key(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from _find_key(v, key)


def stated_wear(run: Path):
    """The set of `aircraft_wear` values the run's render.json files state.
    Empty when the engine never wrote the key (switch not integrated)."""
    found = set()
    for path in sorted(Path(run).rglob("render.json")):
        try:
            found.update(str(v) for v in _find_key(json.loads(path.read_text()), WEAR_KEY))
        except (OSError, ValueError):
            continue
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reference", required=True, help="run directory, wear off")
    ap.add_argument("--candidate", required=True, help="run directory, wear on")
    ap.add_argument("--beauty-suffix", default=".png",
                    help="beauty frame name = albedo name with _albedo.png replaced by this")
    ap.add_argument("--expect", default="tier0", choices=WEAR_VALUES[1:],
                    help="the wear value the candidate's render.json must state")
    args = ap.parse_args(argv)
    ref, cand = Path(args.reference), Path(args.candidate)
    for run, want in ((ref, "off"), (cand, args.expect)):
        got = stated_wear(run)
        if got != {want}:
            print(f"pixel_gate.not_measured: {run} render.json states {WEAR_KEY}="
                  f"{sorted(got) or 'nothing'}, need exactly '{want}'. The wear switch is "
                  f"not integrated or did not reach the engine. This is not a wear result.")
            return 3
    names = sorted(p.relative_to(ref) for p in ref.rglob("frame_*_albedo.png"))
    if not names:
        print("pixel_gate.no_albedo: no frame_*_albedo.png under the reference run")
        return 2
    results, ok = {}, True
    for rel in names:
        if not (cand / rel).exists():
            print(f"pixel_gate.unpaired: {rel} missing from the candidate run")
            return 2
        a_r, b_r = _load_pair((ref / rel).parent, ref / rel, args.beauty_suffix)
        a_c, b_c = _load_pair((cand / rel).parent, cand / rel, args.beauty_suffix)
        results[str(rel)] = r = evaluate(a_r, a_c, b_r, b_c)
        ok = ok and r["ok"]
    if not any(r["changed_fraction"] > 0.0 for r in results.values()):
        print("pixel_gate.not_measured: no albedo pixel moved in any frame, so the two runs "
              "drew the same airframe. The wear layer was not applied. This is not a wear result.")
        return 3
    print(json.dumps({"ok": ok, "expect": args.expect, "thresholds": THRESHOLDS,
                      "frames": results}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
