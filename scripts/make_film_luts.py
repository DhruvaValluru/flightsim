#!/usr/bin/env python3
"""Generate the film-stock LUTs (assets/looks/film/*.cube + film_luts.json).

Visual round 5, lane L2. Each LUT is a 33^3 display-referred sRGB -> sRGB
.cube made with spectral_film_lut (Jan Lohse, MIT; pinned below), so it is
applied AFTER the tonemapper: by scripts/beauty_post.py (ffmpeg lut3d,
tetrahedral) on the beauty frame, or in-engine through
scripts/cube_to_ue_lut.py. The stock per grade is core/scene/beauty_look.py
FILM_STOCKS.

The generator is NOT a repo dependency: it needs numba, colour-science and
opencv, so it runs from a scratch venv:

    python3 -m venv /tmp/sfl && /tmp/sfl/bin/pip install \\
        "spectral_film_lut @ git+https://github.com/JanLohse/spectral_film_lut@a15043f6fe2d365d0c359d22e0868076800916d9"
    /tmp/sfl/bin/python scripts/make_film_luts.py [--out assets/looks/film] [--size 33]

(The tarball of that commit has no git metadata; hatch-vcs then needs
SETUPTOOLS_SCM_PRETEND_VERSION=0.18.14 and ``pip install --no-deps``.)

The beauty frame is already tonemapped, and a film stock exposed on
display-linear values stacks its S-curve on the tonemapper's (measured:
input 0.25 came out 0.16, the toe crushed). So each node is first taken
back to scene-linear through the inverse of the ACES fit the engine's
filmic tonemapper approximates (Narkowicz 2015, x(2.51x+0.03)/(x(2.43x+0.59)+0.14);
display white recovers 7.2 scene-linear, display 0.267 recovers 0.18 grey),
and THAT exposes the film: the stock's curve replaces the tonemapper's
instead of compounding it. Recorded as ``scene_recovery``.

Two corrections are then applied to the raw emulation, both recorded per LUT:

* **Grey-axis neutralisation.** Every stock's raw grey ramp carries a cast
  (Portra 160's toe is 75 % warm, Ektachrome 100D's highlights 6 % cyan).
  The owner's rule since the round-2 #02 blue cast is NO global tint, and
  the test (tests/test_film_luts.py) holds neutral grey within 2 %. So each
  node is scaled per channel by the gain that takes the film's rendering of
  a grey of the same luma onto that grey's channel mean: the grey axis is
  neutral by construction, and a colour keeps the stock's hue and
  saturation RELATIVE to its grey (what "white-balancing the print" does).
* **Tone-curve normalisation.** A print's paper white (0.85 for Portra)
  and fog (0.03) are an affine range on screen; the neutral curve is
  stretched so input black stays black and input white stays white. The
  curve's shape (the stock's contrast and shoulder) is kept.

Deterministic for the pinned library versions (recorded in the JSON);
tests/test_film_luts.py checks the shipped files against their sha256 and
does not regenerate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "assets" / "looks" / "film"
SIZE = 33
LICENCE = "CC0-1.0"

#: The generator, pinned. Tag v0.18.14 is this commit.
GENERATOR = {
    "name": "spectral_film_lut",
    "url": "https://github.com/JanLohse/spectral_film_lut",
    "commit": "a15043f6fe2d365d0c359d22e0868076800916d9",
    "tag": "v0.18.14",
    "licence": "MIT",
}

#: Input and output of every LUT: the tonemapped, sRGB-encoded beauty frame
#: in, the same encoding out. The generator decodes the sRGB curve itself
#: (FilmSpectral.input_transform, colour.RGB_to_XYZ apply_cctf_decoding) and
#: exposes the film as if the display-linear values were the scene.
SPACE_IN = "sRGB (display-referred, sRGB curve, Rec. 709 primaries)"
SPACE_OUT = "sRGB (display-referred, sRGB curve, Rec. 709 primaries)"

#: The stocks. ``negative`` / ``print`` are spectral_film_lut's stock
#: constants; ``params`` go to film_conversion verbatim (its own defaults
#: otherwise). ``exp_comp`` (stops) is the exposure match: chosen on the
#: grey ramp so display mid-grey (0.5 in) comes back within 0.05 of 0.5
#: (Portra at +0 returned 0.35, the slide and the print 0.43-0.45), and
#: the stock's toe, shoulder and mid slope (0.9-1.1) are what is left. ``custom_inversion`` is False everywhere: the pinned commit's
#: optimised inversion calls input_transform with a stale upsampling name
#: and raises.
STOCKS: Dict[str, Dict[str, Any]] = {
    "kodak_portra_160": {
        "negative": "KODAK_PORTRA_160",
        "print": None,
        "description": ("Kodak Portra 160 colour negative, scanned (ACES-like inversion): "
                        "soft, natural daylight stock for golden-hour and overcast frames"),
        "params": {"inversion": True, "custom_inversion": False, "inversion_gamma": 3.0,
                   "exp_comp": 0.5, "exp_kelvin": 6500, "projector_kelvin": 6500},
    },
    "kodak_ektachrome_100d": {
        "negative": "KODAK_EKTACHROME_100D",
        "print": None,
        "description": ("Kodak Ektachrome 100D slide, projected: punchier, saturated "
                        "stock for clear desert-noon frames"),
        "params": {"white_balance": 1, "color_masking": 0.3, "white_clip": True,
                   "exp_comp": 0.3, "exp_kelvin": 6500, "projector_kelvin": 6500},
    },
    "kodak_vision3_250d_2383": {
        "negative": "KODAK_5207",
        "print": "KODAK_2383",
        "description": ("Kodak Vision3 250D 5207 negative printed on Vision 2383: the "
                        "muted motion-picture print look for storm frames"),
        "params": {"exp_comp": 0.3, "exp_kelvin": 6500, "projector_kelvin": 6500,
                   "white_clip": True},
    },
}

#: Rec. 709 luma weights (the LUT's own primaries).
_LUMA = np.array([0.2126, 0.7152, 0.0722])
#: Per-channel gain clamp of the neutralisation: a toe node whose channel is
#: near zero would otherwise ask for a huge gain.
_GAIN_CLAMP = (0.2, 5.0)


def srgb_decode(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def srgb_encode(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


#: The ACES fit (Narkowicz 2015) whose inverse recovers scene-linear light
#: from the tonemapped frame. UE's filmic tonemapper is a close relative
#: (core/scene/beauty_look.py TONEMAP states its curve); the recovery need
#: only be close, since the film's own curve is what the LUT then carries.
_ACES_FIT = (2.51, 0.03, 2.43, 0.59, 0.14)
SCENE_RECOVERY = ("inverse Narkowicz ACES fit x(2.51x+0.03)/(x(2.43x+0.59)+0.14) on "
                  "display-linear, so the stock's curve replaces the tonemapper's")


def aces_fit(x: np.ndarray) -> np.ndarray:
    a, b, c, d, e = _ACES_FIT
    return np.clip(x * (a * x + b) / (x * (c * x + d) + e), 0.0, 1.0)


def inverse_aces_fit(y: np.ndarray) -> np.ndarray:
    """Scene-linear ``x`` with ``aces_fit(x) == y`` (the positive root)."""
    a, b, c, d, e = _ACES_FIT
    y = np.clip(y, 0.0, 0.999)
    qa = a - c * y
    qb = b - d * y
    qc = -e * y
    return (-qb + np.sqrt(qb * qb - 4.0 * qa * qc)) / (2.0 * qa)


def scene_linear_xyz(nodes: np.ndarray) -> np.ndarray:
    """sRGB-encoded nodes -> recovered scene-linear light as CIE XYZ."""
    import colour

    scene = inverse_aces_fit(srgb_decode(nodes))
    return colour.RGB_to_XYZ(scene, "sRGB", apply_cctf_decoding=False)


def grey_level(nodes: np.ndarray) -> np.ndarray:
    """The sRGB-encoded grey of the same luma as each node ``(..., 3)``."""
    return srgb_encode(srgb_decode(nodes) @ _LUMA)


def neutralise(table: np.ndarray, nodes: np.ndarray, film_grey: np.ndarray,
               ramp: np.ndarray) -> tuple:
    """Grey-axis neutralisation and black/white normalisation (module doc).

    ``film_grey`` is the raw emulation of the greys ``ramp`` (sRGB-encoded,
    ascending, ``ramp[0] == 0`` and ``ramp[-1] == 1``). Returns the
    corrected table and the record of what was done."""
    neutral = film_grey.mean(axis=-1)
    level = grey_level(nodes)
    # Each node's grey, interpolated per channel along the ramp.
    at = np.stack([np.interp(level, ramp, film_grey[:, c]) for c in range(3)], axis=-1)
    target = np.interp(level, ramp, neutral)[..., None]
    gain = np.clip(target / np.maximum(at, 1e-6), *_GAIN_CLAMP)
    out = table * gain
    black, white = float(neutral[0]), float(neutral[-1])
    out = np.clip((out - black) / max(white - black, 1e-6), 0.0, 1.0)
    raw_cast = np.abs(film_grey - neutral[:, None]).max(axis=-1) / np.maximum(neutral, 1e-6)
    usable = ramp >= 0.05
    record = {
        "grey_axis_neutralised": True,
        "raw_grey_cast_max_pct": round(float(raw_cast[usable].max() * 100.0), 2),
        "raw_grey_cast_max_at": round(float(ramp[usable][raw_cast[usable].argmax()]), 3),
        "gain_clamp": list(_GAIN_CLAMP),
        "tone_curve_normalised": {"raw_black": round(black, 4), "raw_white": round(white, 4)},
        "neutral_curve": [round(float(v), 4) for v in
                          np.interp(np.linspace(0, 1, 11), ramp, (neutral - black) / (white - black))],
    }
    return out, record


def write_cube(table: np.ndarray, path: Path, title: str, comment: str) -> bytes:
    """``table[r, g, b]`` -> Iridas .cube (red fastest), six decimals."""
    size = table.shape[0]
    lines = [f'TITLE "{title}"', f"# {comment}",
             f"# Input and output: {SPACE_IN}. Licence: {LICENCE}.",
             "# Generated by scripts/make_film_luts.py; do not edit by hand.",
             f"LUT_3D_SIZE {size}", "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    for b in range(size):
        for g in range(size):
            for r in range(size):
                v = table[r, g, b]
                lines.append(f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}")
    data = ("\n".join(lines) + "\n").encode("ascii")
    path.write_bytes(data)
    return data


def generate(name: str, size: int = SIZE) -> tuple:
    """(corrected table (size, size, size, 3) indexed [r, g, b], record)."""
    import colour
    import spectral_film_lut as sfl
    from spectral_film_lut.film_spectral import FilmSpectral
    from spectral_film_lut.utils import film_conversion

    spec = STOCKS[name]
    negative = FilmSpectral(getattr(sfl, spec["negative"]))
    print_film = FilmSpectral(getattr(sfl, spec["print"])) if spec["print"] else None
    # input_colorspace None: the generator takes CIE XYZ, the recovered
    # scene-linear light (scene_linear_xyz); the sRGB decode is ours.
    common = dict(input_colorspace=None, output_gamut="Rec. 709", gamma_func="sRGB")
    nodes = colour.LUT3D(size=size).table.astype(np.float64)
    raw = film_conversion(scene_linear_xyz(nodes), negative, print_film, **common,
                          **spec["params"])
    raw = np.asarray(raw, dtype=np.float64)
    ramp = np.linspace(0.0, 1.0, 257)
    greys = np.repeat(ramp[None, :, None], 3, axis=-1)
    film_grey = film_conversion(scene_linear_xyz(greys), negative, print_film, **common,
                                **spec["params"])
    film_grey = np.asarray(film_grey, dtype=np.float64)[0]
    table, correction = neutralise(raw, nodes, film_grey, ramp)
    record = {
        "stock": name,
        "description": spec["description"],
        "negative": negative.name,
        "print": print_film.name if print_film else None,
        "scene_recovery": SCENE_RECOVERY,
        "params": {**common, **spec["params"]},
        "size": size,
        "space_in": SPACE_IN,
        "space_out": SPACE_OUT,
        **correction,
    }
    return table, record


def versions() -> Dict[str, str]:
    out = {}
    for module in ("spectral_film_lut", "colour", "numpy", "numba", "scipy"):
        try:
            mod = __import__(module)
            out[module] = str(getattr(mod, "__version__", "?"))
        except Exception:  # pragma: no cover - a missing optional module
            out[module] = "missing"
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--size", type=int, default=SIZE)
    parser.add_argument("--only", nargs="*", default=None, help="stock names (default: all)")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    index_path = args.out / "film_luts.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else {}
    luts = {entry["stock"]: entry for entry in index.get("luts", [])}
    for name in (args.only or list(STOCKS)):
        table, record = generate(name, args.size)
        path = args.out / f"{name}.cube"
        data = write_cube(table, path, name, record["description"])
        record.update(file=path.name, sha256=hashlib.sha256(data).hexdigest(),
                      licence=LICENCE)
        luts[name] = record
        print(f"{path.name}: {record['sha256'][:12]} raw cast {record['raw_grey_cast_max_pct']}% "
              f"at {record['raw_grey_cast_max_at']}, white {record['tone_curve_normalised']['raw_white']}")
    index = {
        "generator": {**GENERATOR, "script": "scripts/make_film_luts.py", "versions": versions()},
        "note": ("display-referred sRGB in and out, applied after the tonemapper by "
                 "scripts/beauty_post.py (ffmpeg lut3d tetrahedral) or in-engine via "
                 "scripts/cube_to_ue_lut.py; the grey axis is neutralised and the tone "
                 "curve normalised to black 0 / white 1 (module doc)"),
        "luts": [luts[k] for k in sorted(luts)],
    }
    index_path.write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
