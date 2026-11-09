"""The offline ACES 2.0 SDR display transform (visual overhaul, aces2-display).

WHY OFFLINE. The engine's ``r.HDR.Aces.Version`` only changes the HDR
output devices (3-6); the beauty capture is FinalColorLDR into an sRGB8
target and keeps UE's filmic curve whatever that cvar says. So the ACES
2.0 view is applied here, after the render, to the engine's linear frame:

    frame_NNNN_linear.exr  (the commandlet's -linear pass, SCS_FinalColorHDR)
      -> [optional show LUT, in ACEScct]
      -> OCIO 2.5 built-in config, display 'sRGB - Display',
         view 'ACES 2.0 - SDR 100 nits (Rec.709)'
      -> frame_NNNN_aces2.png  (beside the engine PNG, never over it)

A per-pixel colour transform: no pixel moves, so it is not a
``PIXEL_MOVING_KEYS`` effect and the labels are untouched. It never runs
on a measurement render (``look.display_on_measure``), never inverts the
8-bit filmic PNG back to "linear" (``look.display_input``), and never
falls back to anything when OpenColorIO or OpenEXR is absent
(``look.display_unavailable``; requirements-display.txt pins both).

INPUT COLOUR SPACE. The config's ``scene_linear`` role is ACEScg (AP1),
but UE's working colour space is linear Rec.709 / sRGB primaries unless a
project sets otherwise (ue/Config/DefaultEngine.ini sets none). Feeding
Rec.709 values through as ACEScg over-saturates every colour (measured
with the pinned wheel: an orange patch (0.5, 0.2, 0.05) lands at
(0.683, 0.343, 0.114) instead of (0.581, 0.375, 0.177)). So the source is
the config's ``Linear Rec.709 (sRGB)`` space by default, and the record
names it.

UNCALIBRATED (probe on the render machine; docs/visual/PROBE_LOG.md
"## aces2-display"): whether SCS_FinalColorHDR is exactly pre-tonemap
scene-linear (engine source says HDR_LinearNoToneCurve: graded, exposed
and bloomed, no filmic curve), and the exposure scale the EXR needs
before the view (1.0 until measured). The record says
``input_basis: 'UNVERIFIED pre-tonemap'`` until then.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
LOOKS_DIR = REPO / "assets" / "looks"

#: The versioned built-in config. Never ``ocio://default``: that alias
#: moves with the library, and the record must name what ran.
OCIO_CONFIG = "ocio://studio-config-v4.0.0_aces-v2.0_ocio-v2.5"
DISPLAY = "sRGB - Display"
VIEW = "ACES 2.0 - SDR 100 nits (Rec.709)"
#: UE's default working colour space (see the module docstring).
INPUT_COLORSPACE = "Linear Rec.709 (sRGB)"
#: Show LUTs are authored on ACEScct code values (domain 0..1 covers
#: linear 0 to ~222), the usual space for a show look.
LUT_SPACE = "ACEScct"
#: The oldest library that ships OCIO_CONFIG.
MIN_OCIO = (2, 5)
INPUT_BASIS = "UNVERIFIED pre-tonemap"
#: The look switch value that asks for this step (webapp/runs.py).
DISPLAY_WORD = "aces2"
#: Qualities this step runs on; anything else (measure, or none named)
#: refuses, because the label gates were measured on measure pixels.
DISPLAY_QUALITIES = ("beauty", "pathtrace")

_FRAME_RE = re.compile(r"frame_\d{4}\.png")


class DisplayError(Exception):
    """A named refusal of the display step (core/messages/catalog.yaml)."""

    def __init__(self, constraint: str, message: str) -> None:
        super().__init__(f"{constraint}: {message}")
        self.constraint = constraint
        self.message = message


# -- the look switch hooks (webapp) -------------------------------------------

#: The colour arguments of every clip encode (sRGB PNG -> H.264 yuv420p):
#: the BT.709 matrix in limited range, and the stream tagged so a player
#: decodes it with the same matrix. Without them swscale converts RGB with
#: its BT.601 default and leaves the stream untagged, which browsers read
#: as BT.709: the clip's colours drift from the PNG the grade was tuned on.
#: The transfer tag is sRGB's (iec61966-2-1), the PNG's own. Not a
#: calibration: the standard's numbers, stated once for every encoder.
CLIP_COLOUR_FILTER = "scale=out_color_matrix=bt709:out_range=tv"
CLIP_COLOUR_TAGS = ("-colorspace", "bt709", "-color_primaries", "bt709",
                    "-color_trc", "iec61966-2-1", "-color_range", "tv")


def clip_encode_args(crf: int = 19, *, filter_chain: Optional[str] = None) -> list:
    """The output arguments of a clip encode, colour included: libx264 at
    ``crf``, the BT.709 conversion (appended to ``filter_chain`` when the
    caller has one, else as ``-vf``), yuv420p and the colour tags. The ONE
    source for the web app's per-camera and capture clips and the showcase
    encoders, so a clip is always a tagged BT.709 copy of its PNGs."""
    chain = (f"{filter_chain},{CLIP_COLOUR_FILTER}" if filter_chain
             else CLIP_COLOUR_FILTER)
    return [("-filter_complex" if filter_chain else "-vf"), chain,
            "-c:v", "libx264", "-preset", "medium", "-crf", str(int(crf)),
            "-pix_fmt", "yuv420p", *CLIP_COLOUR_TAGS]


def wants_display(look: Optional[Dict[str, Any]]) -> bool:
    """Whether a run's look switch asks for the ACES 2.0 display step."""
    return bool(look) and str(look.get("display") or "").lower() == DISPLAY_WORD


def commandlet_tokens(look: Optional[Dict[str, Any]]) -> list:
    """The extra commandlet tokens the look needs: ``-linear`` for aces2."""
    return ["-linear"] if wants_display(look) else []


# -- the input -----------------------------------------------------------------

def _exr_modules():
    try:
        import OpenEXR  # type: ignore  # noqa: F401
        import Imath  # type: ignore  # noqa: F401
    except ImportError as exc:
        raise DisplayError(
            "look.display_unavailable",
            f"OpenEXR is not importable ({exc}); install requirements-display.txt")


def load_linear(path) -> np.ndarray:
    """The engine's linear frame as float32 (H, W, 3).

    ``path`` is ``frame_NNNN_linear.exr`` or the ``frame_NNNN.png`` it sits
    beside. Reuses profile.read_linear_frame's EXR reader; its PNG
    inversion is refused here (look.display_input): the PNG is the
    filmic, 8-bit, clipped picture, and inverting the sRGB transfer does
    not give scene-linear light back."""
    from core.capture.profile import read_linear_frame

    path = Path(path)
    if path.suffix.lower() == ".exr":
        exr = path
        png = path.with_name(path.name[: -len("_linear.exr")] + ".png") \
            if path.name.endswith("_linear.exr") else path.with_suffix(".png")
    else:
        png = path
        exr = path.with_name(path.stem + "_linear.exr")
    if not exr.is_file():
        raise DisplayError(
            "look.display_input",
            f"{exr.name} does not exist; only the 8-bit PNG {png.name} was "
            f"given, and inverting the filmic PNG is not scene-linear "
            f"(render with -linear)")
    _exr_modules()
    # read_linear_frame keys the EXR off the PNG's name; the PNG itself
    # need not exist for that branch to run.
    image, note = read_linear_frame(png)
    if note != "engine linear EXR":
        raise DisplayError(
            "look.display_input",
            f"{exr.name} could not be read as the engine's linear EXR "
            f"(the reader fell back to: {note})")
    return np.ascontiguousarray(image, dtype=np.float32)


# -- OpenColorIO ---------------------------------------------------------------

def _ocio():
    try:
        import PyOpenColorIO as ocio  # type: ignore
    except ImportError as exc:
        raise DisplayError(
            "look.display_unavailable",
            f"PyOpenColorIO is not importable ({exc}); install "
            f"requirements-display.txt (opencolorio 2.5.x)")
    version = tuple(int(p) for p in re.findall(r"\d+", ocio.__version__)[:2])
    if version < MIN_OCIO:
        raise DisplayError(
            "look.display_unavailable",
            f"OpenColorIO {ocio.__version__} predates 2.5 and does not ship "
            f"{OCIO_CONFIG}")
    return ocio


def ocio_version() -> str:
    return str(_ocio().__version__)


def _config(config: str):
    ocio = _ocio()
    try:
        return ocio, ocio.Config.CreateFromFile(config)
    except Exception as exc:  # OCIO raises its own Exception type
        raise DisplayError("look.display_unavailable",
                           f"OpenColorIO cannot open {config!r}: {exc}")


def _apply_processor(processor, img: np.ndarray) -> np.ndarray:
    out = np.ascontiguousarray(img, dtype=np.float32).copy()
    flat = out.reshape(-1, 3)
    processor.getDefaultCPUProcessor().applyRGB(flat)
    return flat.reshape(out.shape)


def ocio_convert(img: np.ndarray, src: str, dst: str,
                 config: str = OCIO_CONFIG) -> np.ndarray:
    """A colour-space conversion through the config (e.g. into ACEScct)."""
    _, cfg = _config(config)
    return _apply_processor(cfg.getProcessor(src, dst), img)


def ocio_view(img: np.ndarray, config: str = OCIO_CONFIG, display: str = DISPLAY,
              view: str = VIEW, look: Optional[str] = None,
              src: str = INPUT_COLORSPACE) -> np.ndarray:
    """``img`` (float, (..., 3), in ``src``) through display/view: the
    display-referred code values in [0, 1], float32."""
    ocio, cfg = _config(config)
    transform = ocio.DisplayViewTransform()
    transform.setSrc(src)
    transform.setDisplay(display)
    transform.setView(view)
    if look:
        # An OCIO look on top of the view (e.g. the config's gamut
        # compression); the show LUTs go through apply_cube instead.
        vt = ocio.LookTransform()
        vt.setSrc(src)
        vt.setDst(src)
        vt.setLooks(look)
        group = ocio.GroupTransform()
        group.appendTransform(vt)
        group.appendTransform(transform)
        transform = group
    try:
        processor = cfg.getProcessor(transform)
    except Exception as exc:
        raise DisplayError("look.display_unavailable",
                           f"OpenColorIO has no {display!r} / {view!r} "
                           f"from {src!r} in {config!r}: {exc}")
    return _apply_processor(processor, img)


# -- .cube show LUTs -------------------------------------------------------------

def read_cube(path) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(table (N, N, N, 3) indexed [b, g, r], domain_min, domain_max).

    The .cube order: red varies fastest, then green, then blue."""
    size = None
    lo = np.zeros(3)
    hi = np.ones(3)
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        word = line.split()[0].upper()
        if word == "LUT_3D_SIZE":
            size = int(line.split()[1])
        elif word == "DOMAIN_MIN":
            lo = np.array([float(v) for v in line.split()[1:4]])
        elif word == "DOMAIN_MAX":
            hi = np.array([float(v) for v in line.split()[1:4]])
        elif word in ("TITLE", "LUT_1D_SIZE", "LUT_1D_INPUT_RANGE",
                      "LUT_3D_INPUT_RANGE"):
            if word.startswith("LUT_1D"):
                raise ValueError(f"{path}: 1D LUTs are not supported")
        else:
            rows.append([float(v) for v in line.split()[:3]])
    if size is None or size < 2:
        raise ValueError(f"{path}: no LUT_3D_SIZE of at least 2")
    if len(rows) != size ** 3:
        raise ValueError(f"{path}: {len(rows)} rows for a {size}^3 LUT")
    table = np.asarray(rows, dtype=np.float64).reshape(size, size, size, 3)
    return table, lo, hi


def tetrahedral(img: np.ndarray, table: np.ndarray,
                lo: Sequence[float] = (0.0, 0.0, 0.0),
                hi: Sequence[float] = (1.0, 1.0, 1.0)) -> np.ndarray:
    """Tetrahedral interpolation of ``table`` ([b, g, r] indexed) at ``img``.

    Written as c000 + fx*(c_a - c000) + fy*(c_b - c_a) + fz*(c111 - c_b)
    so an identity table of 2^k + 1 points reproduces its in-domain inputs
    bit for bit (each product and sum is exact in binary floating point).
    Inputs outside the domain are clamped to it."""
    n = table.shape[0]
    shape = img.shape
    lo = np.asarray(lo, dtype=np.float64)
    hi = np.asarray(hi, dtype=np.float64)
    x = np.asarray(img, dtype=np.float64).reshape(-1, 3)
    x = (np.clip(x, lo, hi) - lo) / (hi - lo) * (n - 1)
    i = np.minimum(np.floor(x).astype(np.int64), n - 2)
    f = x - i
    r0, g0, b0 = i[:, 0], i[:, 1], i[:, 2]
    fr, fg, fb = f[:, 0:1], f[:, 1:2], f[:, 2:3]

    def at(dr, dg, db):
        return table[b0 + db, g0 + dg, r0 + dr]

    c000 = at(0, 0, 0)
    c111 = at(1, 1, 1)
    out = np.empty_like(c000)
    # The six tetrahedra of the cube, by the order of the fractions.
    cases = (
        ((fr >= fg) & (fg >= fb), (1, 0, 0), (1, 1, 0), fr, fg, fb),
        ((fr >= fb) & (fb > fg), (1, 0, 0), (1, 0, 1), fr, fb, fg),
        ((fb > fr) & (fr >= fg), (0, 0, 1), (1, 0, 1), fb, fr, fg),
        ((fg > fr) & (fr >= fb), (0, 1, 0), (1, 1, 0), fg, fr, fb),
        ((fg >= fb) & (fb > fr), (0, 1, 0), (0, 1, 1), fg, fb, fr),
        ((fb > fg) & (fg > fr), (0, 0, 1), (0, 1, 1), fb, fg, fr),
    )
    done = np.zeros(len(x), dtype=bool)
    for mask, a, b, t1, t2, t3 in cases:
        m = mask[:, 0] & ~done
        if not m.any():
            continue
        ca, cb = at(*a)[m], at(*b)[m]
        c0 = c000[m]
        out[m] = (c0 + t1[m] * (ca - c0) + t2[m] * (cb - ca)
                  + t3[m] * (c111[m] - cb))
        done |= m
    return out.reshape(shape).astype(np.asarray(img).dtype
                                      if np.asarray(img).dtype.kind == "f"
                                      else np.float64)


def apply_cube(img: np.ndarray, path) -> np.ndarray:
    """``img`` through the .cube LUT at ``path`` (tetrahedral)."""
    table, lo, hi = read_cube(path)
    return tetrahedral(img, table, lo, hi)


def show_luts() -> Dict[str, Dict[str, str]]:
    """{name: {name, file, sha256, licence, space}} from assets/looks/looks.json."""
    data = json.loads((LOOKS_DIR / "looks.json").read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in data["looks"]}


def _lut_entry(name: str) -> Dict[str, str]:
    luts = show_luts()
    if name not in luts:
        raise ValueError(f"show LUT {name!r} is not one of {sorted(luts)}")
    entry = luts[name]
    path = LOOKS_DIR / entry["file"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry["sha256"]:
        raise ValueError(f"{entry['file']} sha256 {digest} does not match "
                         f"looks.json {entry['sha256']}")
    return {**entry, "path": str(path)}


# -- the record and the frame --------------------------------------------------

def display_record(output: str, lut: Optional[Dict[str, str]] = None,
                   look: Optional[str] = None, exposure_scale: float = 1.0,
                   version: Optional[str] = None,
                   config: str = OCIO_CONFIG, display: str = DISPLAY,
                   view: str = VIEW, src: str = INPUT_COLORSPACE) -> Dict[str, Any]:
    """render.json ``beauty_look.display``."""
    return {
        "ocio_version": version if version is not None else ocio_version(),
        "ocio_config": config,
        "display": display,
        "view": view,
        "look": look,
        "lut": ({"name": lut["name"], "sha256": lut["sha256"],
                 "space": lut.get("space", LUT_SPACE)} if lut else None),
        "input": "linear_exr",
        "input_colorspace": src,
        "input_basis": INPUT_BASIS,
        "exposure_scale": float(exposure_scale),
        "exposure_scale_basis": "UNCALIBRATED (1.0 until probed)"
                                if exposure_scale == 1.0 else "stated",
        "output": output,
        "pixel_moving": False,
    }


def check_quality(payload: Dict) -> str:
    """The render's quality, refusing anything but a beauty render."""
    from core.capture.beauty_look import quality_of

    quality = quality_of(payload)
    if quality not in DISPLAY_QUALITIES:
        raise DisplayError(
            "look.display_on_measure",
            f"the render names quality {quality!r}; the display transform "
            f"runs on {list(DISPLAY_QUALITIES)} only")
    return quality


def _write_png(code: np.ndarray, path: Path) -> None:
    from PIL import Image

    rgb = np.clip(np.nan_to_num(code, nan=0.0), 0.0, 1.0)
    Image.fromarray(np.ascontiguousarray(np.round(rgb * 255.0).astype(np.uint8))).save(path)


def display_frame(exr_or_png, payload: Dict, lut: Optional[str] = None,
                  look: Optional[str] = None,
                  exposure_scale: float = 1.0) -> Dict[str, Any]:
    """One frame: writes ``frame_NNNN_aces2.png`` and returns its record."""
    check_quality(payload)
    img = load_linear(exr_or_png) * np.float32(exposure_scale)
    entry = _lut_entry(lut) if lut else None
    src = INPUT_COLORSPACE
    if entry:
        img = ocio_convert(img, INPUT_COLORSPACE, LUT_SPACE)
        img = apply_cube(img, entry["path"]).astype(np.float32)
        src = LUT_SPACE
    code = ocio_view(img, look=look, src=src)
    path = Path(exr_or_png)
    stem = path.name[: -len("_linear.exr")] if path.name.endswith("_linear.exr") \
        else path.stem
    out = path.with_name(stem + "_aces2.png")
    _write_png(code, out)
    return display_record(out.name, lut=entry, look=look,
                          exposure_scale=exposure_scale, src=INPUT_COLORSPACE)


def apply_to_bundle(bundle_dir, look: Optional[Dict[str, Any]] = None,
                    lut: Optional[str] = None,
                    exposure_scale: float = 1.0) -> Dict[str, Any]:
    """Every ``frame_NNNN.png`` in a render directory through the display
    step, recorded in its render.json as ``beauty_look.display``.

    A refusal is recorded too (``{"refused": name, "reason": ...}``) and
    returned, never swallowed: the engine PNGs stay as they are and the
    record says why no ``_aces2.png`` exists."""
    bundle = Path(bundle_dir)
    manifest = bundle / "render.json"
    payload = json.loads(manifest.read_text(encoding="utf-8")) \
        if manifest.is_file() else {}
    lut = lut or (look or {}).get("lut")
    try:
        check_quality(payload)
        frames = sorted(p for p in bundle.glob("frame_*.png")
                        if _FRAME_RE.fullmatch(p.name))
        if not frames:
            raise DisplayError("look.display_input",
                               f"{bundle} holds no frame_NNNN.png")
        records = [display_frame(frame, payload, lut=lut,
                                 exposure_scale=exposure_scale)
                   for frame in frames]
        record = {**records[0], "output": "frame_NNNN_aces2.png",
                  "frames": [r["output"] for r in records]}
    except DisplayError as exc:
        record = {"refused": exc.constraint, "reason": exc.message}
        if exc.constraint == "look.display_on_measure":
            # A measure (or quality-less) manifest is never written: a
            # beauty_look key there flips has_look_record and so changes
            # what the verifier grades (look_label_alignment) on the path
            # the label gates were measured on. The refusal is returned.
            return record
    if manifest.is_file():
        payload.setdefault("beauty_look", {})
        if isinstance(payload["beauty_look"], dict):
            payload["beauty_look"]["display"] = record
            # The UE-written manifest stays ASCII (gotcha 13).
            manifest.write_text(json.dumps(payload, indent=1, ensure_ascii=True),
                                encoding="utf-8")
    return record


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("bundle", help="a render directory (frames + render.json)")
    parser.add_argument("--lut", choices=None, default=None,
                        help="a show LUT name from assets/looks/looks.json")
    parser.add_argument("--exposure-scale", type=float, default=1.0)
    args = parser.parse_args(argv)
    record = apply_to_bundle(args.bundle, lut=args.lut,
                             exposure_scale=args.exposure_scale)
    print(json.dumps(record, indent=1))
    return 1 if "refused" in record else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
