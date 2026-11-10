#!/usr/bin/env python3
"""Post-render beauty pipeline: denoise, film grade, halation, grain, vignette, 4K.

Visual round 5, lane L5. Runs on the Windows render machine after each
beauty frame when ``FLIGHTSIM_BEAUTY_POST=on`` (webapp/runs.py after the
render, scripts/visual_round.py for the round's gallery). For every
``frame_NNNN.png`` it writes ``frame_NNNN_beauty_post.png`` beside it (and
``frame_NNNN_beauty_4k.png`` when the upscale runs). The original beauty
frame and every label pass are never opened for writing: labels must match
pixels, and this pipeline moves and invents pixels, so its output is a
separate file and its record is in render.json under ``beauty_post``
(each step, its tool's version and sha256, its arguments).

The steps, in order (each has an off word, see :func:`parse_switch`):

1. ``denoise``  Intel Open Image Denoise ``oidnDenoise.exe`` on the frame as
   PFM (``--ldr``; ``--hdr`` when a ``_linear.exr`` sibling exists is a
   later round's work), the Intel GPU (``sycl``) first, the CPU as the
   fallback, which one ran recorded. Only frames the look flags noisy: the
   world presets in :data:`NOISY_PRESETS` (fog, rain, storm).
2. ``lut``      ffmpeg ``lut3d`` with the film stock the look chose
   (core/scene/beauty_look.py FILM_STOCKS, assets/looks/film/*.cube,
   tetrahedral), on 16-bit planar RGB.
3. ``halation`` the highlights (``colorlevels`` threshold), blurred
   (``gblur``), tinted warm (``colorchannelmixer``), screened back at a low
   opacity (``blend``): the red bloom of film around bright edges.
4. ``grain``    ffmpeg ``noise`` with a seed from the frame's name, so a
   frame is deterministic. Skipped when the engine's own film grain is on
   (core/scene/beauty_look.py FILM_GRAIN_IN_ENGINE and the look's
   FilmGrainIntensity); the record says which.
5. ``vignette`` ffmpeg ``vignette``, subtle (angle PI/8, corners at 73 %).
6. ``upscale``  Real-ESRGAN-ncnn-vulkan x4 then a Lanczos resize to
   3840 x 2160, written as ``frame_NNNN_beauty_4k.png``. A Vulkan failure on
   the Intel chip is recorded by name (``beauty_post.upscale_vulkan``) and
   the step skipped; the other steps' output stands.

Tools (:data:`TOOLS`) are pinned release zips with their sha256, fetched
once into ``%LOCALAPPDATA%\\flightsim\\tools`` (``~/.cache/flightsim/tools``
elsewhere), checked against the sha256 before extraction, never committed.
A tool that is missing and cannot be fetched is refused by name
(``beauty_post.tool_missing``); a download whose digest differs is deleted
and refused (``beauty_post.tool_checksum``). Nothing is skipped silently.

    python scripts/beauty_post.py <run dir or frames dir> [--look beauty_look.json]
        [--off halation,upscale] [--tool ffmpeg=/path/ffmpeg] [--no-fetch]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
import zlib
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Sequence

import numpy as np

REPO = Path(__file__).resolve().parents[1]

BEAUTY_POST_VERSION = 1
#: The environment switch (core/config_surface.py): ``on`` runs every step,
#: ``on,-halation,-upscale`` (or ``no-halation``) runs all but those, ``off``
#: or unset runs nothing.
ENV_SWITCH = "FLIGHTSIM_BEAUTY_POST"
STEPS = ("denoise", "lut", "halation", "grain", "vignette", "upscale")
#: World presets (core/scene/world_beauty.py PRESETS, recorded in the beauty
#: look as world_preset) whose frames are noisy enough to denoise: fog,
#: rain, storm. A clear or overcast frame keeps its pixels.
NOISY_PRESETS = ("storm", "rain", "hazy")
OUTPUT_SUFFIX = "_beauty_post.png"
UPSCALE_SUFFIX = "_beauty_4k.png"
_FRAME_RE = re.compile(r"frame_\d{4}\.png")

#: The pinned tools: release URL, the zip's sha256 (GitHub's own digest for
#: OIDN and ffmpeg; computed from the download for Real-ESRGAN, whose 2022
#: release predates digests), the executable's file name inside the zip
#: (found by name after extraction, so a top folder's spelling cannot break
#: it) and the licence (THIRD_PARTY_VISUAL.md).
TOOLS: Dict[str, Dict[str, Any]] = {
    "oidn": {
        "name": "Intel Open Image Denoise",
        "version": "2.5.1",
        "url": "https://github.com/RenderKit/oidn/releases/download/v2.5.1/oidn-2.5.1.x64.windows.zip",
        "sha256": "f11f91bc072a5e3a564515724cb72ab8fcfbc445c84a84c197ff9b16cc01396f",
        "exe": "oidnDenoise.exe",
        "licence": "Apache-2.0",
        "source": "https://github.com/RenderKit/oidn",
    },
    "ffmpeg": {
        "name": "ffmpeg (BtbN FFmpeg-Builds, win64 LGPL, release branch 8.1)",
        "version": "n8.1.3-34-ga35157abb9 (autobuild-2026-11-09-12-42)",
        "url": ("https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-11-09-12-42/"
                "ffmpeg-n8.1.3-34-ga35157abb9-win64-lgpl-8.1.zip"),
        "sha256": "7bdec3860d33145a7cd68146eb8e1414e8881cac76205401211fbdad38ef0ed3",
        "exe": "ffmpeg.exe",
        "licence": "LGPL-2.1-or-later",
        "source": "https://github.com/BtbN/FFmpeg-Builds",
    },
    "realesrgan": {
        # The Real-ESRGAN-ncnn-vulkan v0.2.0 binary (24 Apr 2022) as the
        # Real-ESRGAN v0.2.5.0 release ships it WITH its models: the
        # Real-ESRGAN-ncnn-vulkan repository's own v0.2.0 zip
        # (sha256 1bbbdb12d470af80b035c773682e144c6c2f6ece9210832a289af0a48ce3fa9a)
        # holds the same exe and no models.
        "name": "Real-ESRGAN-ncnn-vulkan",
        "version": "v0.2.0 binary, 20220424 release zip with models",
        "url": ("https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
                "realesrgan-ncnn-vulkan-20220424-windows.zip"),
        "sha256": "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d",
        "exe": "realesrgan-ncnn-vulkan.exe",
        "models": "models",
        "licence": "MIT (code), BSD-3-Clause (models)",
        "source": "https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan",
    },
}

#: The steps' parameters. UNCALIBRATED: set by the round-5 A/B pairs on the
#: render machine (docs/visual/PROBE_LOG.md); every value is in the record.
PARAMS: Dict[str, Dict[str, Any]] = {
    "denoise": {"devices": ["sycl", "cpu"], "quality": "high", "mode": "ldr"},
    "lut": {"interp": "tetrahedral"},
    # Keep pixels above the threshold (sRGB code), blur them 14 px, tint
    # them to film's red halo, screen them back at 12 %.
    "halation": {"threshold": 0.72, "sigma": 14.0, "tint": [1.0, 0.35, 0.12], "opacity": 0.12},
    # ffmpeg noise: all_strength 0..100, t+u = temporal + uniform.
    "grain": {"strength": 6, "flags": "t+u"},
    # ffmpeg's vignette darkens the corner by cos(angle)^4: PI/6 took the
    # corner to 56 % (measured), PI/8 keeps 73 %. The owner rejected edge
    # shading on 2026-10-11 (core/sky/plan.py POST_PROCESS), so subtle it is.
    "vignette": {"angle": "PI/8"},
    "upscale": {"model": "realesrgan-x4plus", "tile": 128, "gpu": 0, "size": [3840, 2160],
                "resize": "lanczos"},
}


class BeautyPostError(RuntimeError):
    """A named refusal of the post pipeline."""

    def __init__(self, constraint: str, message: str) -> None:
        super().__init__(message)
        self.constraint = constraint
        self.message = message


# -- the switch -----------------------------------------------------------------

def parse_switch(value: Optional[str]) -> Optional[FrozenSet[str]]:
    """``FLIGHTSIM_BEAUTY_POST`` -> the steps switched OFF (a frozenset) when
    the pipeline runs, None when it does not. ``on`` runs everything;
    ``on,-halation,no-upscale`` runs all but those; ``off`` or empty runs
    nothing. An unknown word is refused by name (beauty_post.switch)."""
    words = [w.strip().lower() for w in str(value or "").split(",") if w.strip()]
    if not words or words[0] in ("off", "0", "false", "no"):
        return None
    if words[0] not in ("on", "1", "true", "yes"):
        raise BeautyPostError("beauty_post.switch",
                              f"{ENV_SWITCH}={value!r}: the first word must be on or off")
    off = set()
    for word in words[1:]:
        step = word[1:] if word.startswith("-") else word[3:] if word.startswith("no-") else None
        if step not in STEPS:
            raise BeautyPostError("beauty_post.switch",
                                  f"{ENV_SWITCH}={value!r}: {word!r} is not -<step> or no-<step> "
                                  f"for a step in {list(STEPS)}")
        off.add(step)
    return frozenset(off)


def wanted(environ: Optional[Mapping[str, str]] = None) -> Optional[FrozenSet[str]]:
    """:func:`parse_switch` of the environment."""
    return parse_switch((environ if environ is not None else os.environ).get(ENV_SWITCH, ""))


# -- tools --------------------------------------------------------------------------

def default_tools_dir() -> Path:
    """``%LOCALAPPDATA%\\flightsim\\tools`` on Windows, ``~/.cache/flightsim/tools`` elsewhere."""
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        return Path(local) / "flightsim" / "tools"
    return Path.home() / ".cache" / "flightsim" / "tools"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, open(tmp, "wb") as out:
        shutil.copyfileobj(response, out)
    tmp.replace(target)


def _extract(archive: Path, into: Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            name = member.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                continue  # a planted path never leaves the tool's folder
            zipped.extract(member, into)


def _find(root: Path, name: str) -> Optional[Path]:
    hits = sorted(p for p in root.rglob(name) if p.is_file())
    return hits[0] if hits else None


def ensure_tool(name: str, tools_dir: Optional[Path] = None, *, fetch: bool = True,
                override: Optional[Mapping[str, Path]] = None,
                download: Callable[[str, Path], None] = _download) -> Dict[str, Any]:
    """The tool's record: ``exe`` (its path), ``version``, ``sha256``, ``url``.

    ``override`` maps a tool name to an executable already on this machine
    (tests' fake binaries, a developer's own build): recorded as such, no
    download. Otherwise the pinned zip in ``tools_dir`` is used, fetched
    first when ``fetch``; a missing tool or a wrong digest is refused by
    name, never skipped."""
    spec = TOOLS[name]
    if override and name in override:
        exe = Path(override[name])
        if not exe.is_file():
            raise BeautyPostError("beauty_post.tool_missing",
                                  f"{name}: the override {exe} is not a file")
        record = {"tool": name, "name": spec["name"], "version": f"override ({exe.name})",
                  "sha256": sha256_of(exe), "exe": str(exe), "url": None,
                  "licence": spec["licence"]}
        if spec.get("models"):
            record["models"] = str(exe.parent / spec["models"])
        return record
    tools_dir = Path(tools_dir or default_tools_dir())
    tools_dir.mkdir(parents=True, exist_ok=True)
    folder = tools_dir / f"{name}-{spec['sha256'][:12]}"
    archive = tools_dir / Path(spec["url"]).name
    exe = _find(folder, spec["exe"]) if folder.is_dir() else None
    if exe is None:
        if not archive.is_file():
            if not fetch:
                raise BeautyPostError(
                    "beauty_post.tool_missing",
                    f"{name} ({spec['name']} {spec['version']}) is not in {tools_dir} and "
                    f"fetching is off: download {spec['url']} there (sha256 {spec['sha256']})")
            try:
                download(spec["url"], archive)
            except Exception as exc:  # the network, the host: named, not silent
                raise BeautyPostError(
                    "beauty_post.tool_missing",
                    f"{name} ({spec['name']} {spec['version']}) could not be fetched from "
                    f"{spec['url']}: {exc}") from exc
        digest = sha256_of(archive)
        if digest != spec["sha256"]:
            archive.unlink(missing_ok=True)
            raise BeautyPostError(
                "beauty_post.tool_checksum",
                f"{name}: {archive.name} has sha256 {digest}, the pinned release has "
                f"{spec['sha256']}; the download was deleted")
        _extract(archive, folder)
        exe = _find(folder, spec["exe"])
        if exe is None:
            raise BeautyPostError("beauty_post.tool_missing",
                                  f"{name}: {spec['exe']} is not inside {archive.name}")
    record = {"tool": name, "name": spec["name"], "version": spec["version"],
              "sha256": spec["sha256"], "exe": str(exe), "url": spec["url"],
              "licence": spec["licence"]}
    if spec.get("models"):
        models = _find(exe.parent, "realesrgan-x4plus.param")
        record["models"] = str(models.parent if models else exe.parent / spec["models"])
    return record


# -- image files ---------------------------------------------------------------------

def read_png(path: Path) -> np.ndarray:
    from PIL import Image

    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"))


def write_pfm(rgb01: np.ndarray, path: Path) -> None:
    """``rgb01`` (H, W, 3) floats in [0, 1] -> PFM (little-endian, bottom row first)."""
    data = np.ascontiguousarray(rgb01[::-1].astype("<f4"))
    height, width = data.shape[:2]
    with open(path, "wb") as out:
        out.write(f"PF\n{width} {height}\n-1.0\n".encode("ascii"))
        out.write(data.tobytes())


def read_pfm(path: Path) -> np.ndarray:
    with open(path, "rb") as handle:
        kind = handle.readline().strip()
        if kind != b"PF":
            raise BeautyPostError("beauty_post.step", f"{path}: not a colour PFM")
        width, height = (int(v) for v in handle.readline().split())
        scale = float(handle.readline())
        data = np.frombuffer(handle.read(), dtype="<f4" if scale < 0 else ">f4")
    return data.reshape(height, width, 3)[::-1]


def write_ppm16(rgb01: np.ndarray, path: Path) -> None:
    """16-bit binary PPM (ffmpeg reads it as rgb48be): the denoise step's
    hand-over keeps 16 bits, not 8."""
    data = np.clip(np.round(rgb01 * 65535.0), 0, 65535).astype(">u2")
    height, width = data.shape[:2]
    with open(path, "wb") as out:
        out.write(f"P6\n{width} {height}\n65535\n".encode("ascii"))
        out.write(np.ascontiguousarray(data).tobytes())


# -- argument builders (pure) ----------------------------------------------------------

def denoise_args(exe: str, src: Path, dst: Path, device: str, *, mode: str = "ldr",
                 quality: str = "high", albedo: Optional[Path] = None,
                 normal: Optional[Path] = None) -> List[str]:
    args = [exe, f"--{mode}", str(src), "-o", str(dst), "-d", device, "-q", quality]
    if albedo is not None:
        args += ["--alb", str(albedo)]
    if normal is not None:
        args += ["--nrm", str(normal)]
    return args


def _filter_path(path: Path) -> str:
    """A file name inside a filter option: forward slashes, the drive colon escaped."""
    text = str(path).replace("\\", "/")
    return text.replace(":", "\\:").replace("'", "\\'")


def halation_graph(params: Mapping[str, Any]) -> str:
    """``split`` the frame, keep its highlights, blur and warm them, screen them back."""
    t = float(params["threshold"])
    tint = params["tint"]
    return (f"split[a][b];[b]colorlevels=rimin={t:g}:gimin={t:g}:bimin={t:g},"
            f"gblur=sigma={float(params['sigma']):g},"
            f"colorchannelmixer=rr={tint[0]:g}:gg={tint[1]:g}:bb={tint[2]:g}[h];"
            f"[a][h]blend=all_mode=screen:all_opacity={float(params['opacity']):g}")


def filter_graph(*, cube: Optional[Path], halation: bool, grain: bool, vignette: bool,
                 seed: int, params: Mapping[str, Mapping[str, Any]] = PARAMS) -> str:
    """The one ffmpeg -filter_complex of steps 2-5, 16-bit planar through the
    LUT and the halation, 8-bit for ffmpeg's noise and vignette (their only
    depth), rgb24 PNG out."""
    chain = ["[0:v]format=gbrp16le"]
    if cube is not None:
        chain.append(f"lut3d=file='{_filter_path(cube)}':interp={params['lut']['interp']}")
    graph = ",".join(chain)
    if halation:
        graph += "," + halation_graph(params["halation"])
    tail = []
    if grain or vignette:
        tail.append("format=gbrp")
    if grain:
        g = params["grain"]
        tail.append(f"noise=all_seed={int(seed)}:all_strength={int(g['strength'])}:"
                    f"all_flags={g['flags']}")
    if vignette:
        tail.append(f"vignette=angle={params['vignette']['angle']}")
    tail.append("format=rgb24")
    return graph + "," + ",".join(tail) + "[out]"


def ffmpeg_args(exe: str, src: Path, graph: str, dst: Path) -> List[str]:
    return [exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
            "-filter_complex", graph, "-map", "[out]", "-frames:v", "1", str(dst)]


def upscale_args(exe: str, src: Path, dst: Path, models: Optional[str],
                 params: Mapping[str, Any] = PARAMS["upscale"]) -> List[str]:
    args = [exe, "-i", str(src), "-o", str(dst), "-n", params["model"], "-t", str(params["tile"]),
            "-g", str(params["gpu"])]
    if models:
        args += ["-m", models]
    return args


def resize_args(exe: str, src: Path, dst: Path, params: Mapping[str, Any] = PARAMS["upscale"]) -> List[str]:
    width, height = params["size"]
    return [exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
            "-vf", f"scale={width}:{height}:flags={params['resize']}", "-frames:v", "1", str(dst)]


def frame_seed(frame: Path) -> int:
    """The grain seed: the frame's name, so a re-render of the same frame grains alike."""
    return zlib.crc32(frame.name.encode("utf-8")) & 0x7FFFFFFF


# -- running --------------------------------------------------------------------------

Runner = Callable[[List[str]], "subprocess.CompletedProcess[bytes]"]


def _run(args: List[str]) -> "subprocess.CompletedProcess[bytes]":
    return subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL, timeout=1800)


def _stderr(result: "subprocess.CompletedProcess[bytes]") -> str:
    return (result.stderr or b"").decode("utf-8", "replace").strip()[-600:]


def _step_record(step: str, tool: Mapping[str, Any], args: List[str], params: Mapping[str, Any],
                 started: float, **extra: Any) -> Dict[str, Any]:
    return {"step": step, "ran": True, "tool": tool["tool"], "tool_name": tool["name"],
            "version": tool["version"], "sha256": tool["sha256"], "exe": tool["exe"],
            "args": [str(a) for a in args], "params": dict(params),
            "seconds": round(time.monotonic() - started, 3), **extra}


def post_frame(frame: Path, *, cube: Optional[Path], noisy: bool, grain: bool, upscale: bool,
               off: FrozenSet[str] = frozenset(), tools_dir: Optional[Path] = None,
               fetch: bool = True, override: Optional[Mapping[str, Path]] = None,
               runner: Runner = _run, params: Mapping[str, Mapping[str, Any]] = PARAMS) -> Dict[str, Any]:
    """One ``frame_NNNN.png`` -> ``frame_NNNN_beauty_post.png`` (and ``_beauty_4k.png``).

    ``cube``: the stock's .cube (None: no grade). ``noisy``: the look flags
    the frame for the denoiser. ``grain``: the pipeline's grain (False when
    the engine's is on). ``off``: steps switched off by the environment.
    Returns the frame's record; the steps that did not run say why."""
    frame = Path(frame)
    if not frame.is_file() or frame.suffix.lower() != ".png":
        raise BeautyPostError("beauty_post.input", f"{frame} is not a PNG beauty frame")
    stem = frame.name[:-4]
    out = frame.with_name(stem + OUTPUT_SUFFIX)
    steps: List[Dict[str, Any]] = []
    work = Path(tempfile.mkdtemp(prefix=stem + "_beauty_post_", dir=str(frame.parent)))
    try:
        source = frame
        # 1. denoise
        if "denoise" in off:
            steps.append({"step": "denoise", "ran": False, "why": "switched off"})
        elif not noisy:
            steps.append({"step": "denoise", "ran": False,
                          "why": f"the look's world preset is not one of {list(NOISY_PRESETS)}"})
        else:
            tool = ensure_tool("oidn", tools_dir, fetch=fetch, override=override)
            p = params["denoise"]
            started = time.monotonic()
            pfm_in, pfm_out = work / "in.pfm", work / "denoised.pfm"
            write_pfm(read_png(frame).astype(np.float32) / 255.0, pfm_in)
            albedo = frame.with_name(stem + "_albedo.png")
            normal = frame.with_name(stem + "_normal.png")
            aov = {}
            for key, path in (("albedo", albedo), ("normal", normal)):
                if path.is_file():
                    aov_pfm = work / f"{key}.pfm"
                    write_pfm(read_png(path).astype(np.float32) / 255.0, aov_pfm)
                    aov[key] = aov_pfm
            ran_on, errors, args = None, [], []
            for device in p["devices"]:
                args = denoise_args(tool["exe"], pfm_in, pfm_out, device, mode=p["mode"],
                                    quality=p["quality"], albedo=aov.get("albedo"),
                                    normal=aov.get("normal"))
                result = runner(args)
                if result.returncode == 0 and pfm_out.is_file():
                    ran_on = device
                    break
                errors.append(f"{device}: exit {result.returncode}: {_stderr(result)}")
            if ran_on is None:
                raise BeautyPostError("beauty_post.step",
                                      "oidnDenoise failed on every device: " + " | ".join(errors))
            source = work / "denoised.ppm"
            write_ppm16(np.clip(read_pfm(pfm_out), 0.0, 1.0), source)
            steps.append(_step_record("denoise", tool, args, p, started, device_ran=ran_on,
                                      devices_failed=errors, aovs=sorted(aov),
                                      intermediate="16-bit PPM"))
        # 2-5. one ffmpeg pass
        use_lut = cube is not None and "lut" not in off
        use_halation = "halation" not in off
        use_grain = grain and "grain" not in off
        use_vignette = "vignette" not in off
        if cube is None:
            steps.append({"step": "lut", "ran": False, "why": "the look names no film stock"})
        elif "lut" in off:
            steps.append({"step": "lut", "ran": False, "why": "switched off"})
        for step, used in (("halation", use_halation), ("vignette", use_vignette)):
            if not used:
                steps.append({"step": step, "ran": False, "why": "switched off"})
        if not use_grain:
            steps.append({"step": "grain", "ran": False,
                          "why": "switched off" if "grain" in off else
                          "the engine's film grain is on (beauty_look FILM_GRAIN_IN_ENGINE)"})
        ffmpeg = ensure_tool("ffmpeg", tools_dir, fetch=fetch, override=override)
        seed = frame_seed(frame)
        graph = filter_graph(cube=cube if use_lut else None, halation=use_halation,
                             grain=use_grain, vignette=use_vignette, seed=seed, params=params)
        args = ffmpeg_args(ffmpeg["exe"], source, graph, out)
        started = time.monotonic()
        result = runner(args)
        if result.returncode != 0 or not out.is_file():
            raise BeautyPostError("beauty_post.step",
                                  f"ffmpeg exit {result.returncode} on {frame.name}: {_stderr(result)}")
        ffmpeg_params: Dict[str, Any] = {"filter_graph": graph, "intermediate": "gbrp16le"}
        if use_lut:
            ffmpeg_params["lut"] = {"cube": str(cube), "sha256": sha256_of(cube),
                                    **params["lut"]}
            steps.append(_step_record("lut", ffmpeg, args, ffmpeg_params["lut"], started,
                                      shared_pass=True))
        if use_halation:
            steps.append(_step_record("halation", ffmpeg, args, params["halation"], started,
                                      shared_pass=True))
        if use_grain:
            steps.append(_step_record("grain", ffmpeg, args, {**params["grain"], "seed": seed},
                                      started, shared_pass=True))
        if use_vignette:
            steps.append(_step_record("vignette", ffmpeg, args, params["vignette"], started,
                                      shared_pass=True))
        steps.append({"step": "ffmpeg_pass", "ran": True, "tool": "ffmpeg",
                      "version": ffmpeg["version"], "sha256": ffmpeg["sha256"],
                      "args": [str(a) for a in args], "params": ffmpeg_params,
                      "seconds": round(time.monotonic() - started, 3)})
        # 6. upscale
        if "upscale" in off or not upscale:
            steps.append({"step": "upscale", "ran": False,
                          "why": "switched off" if "upscale" in off else "not asked for"})
        else:
            tool = ensure_tool("realesrgan", tools_dir, fetch=fetch, override=override)
            p = params["upscale"]
            started = time.monotonic()
            x4 = work / "x4.png"
            args = upscale_args(tool["exe"], out, x4, tool.get("models"), p)
            result = runner(args)
            if result.returncode != 0 or not x4.is_file():
                steps.append({"step": "upscale", "ran": False,
                              "skipped": "beauty_post.upscale_vulkan",
                              "why": (f"realesrgan-ncnn-vulkan exit {result.returncode} "
                                      f"(Vulkan on this GPU?): {_stderr(result)}"),
                              "args": [str(a) for a in args], "tool": tool["tool"],
                              "version": tool["version"], "sha256": tool["sha256"]})
            else:
                big = frame.with_name(stem + UPSCALE_SUFFIX)
                rargs = resize_args(ffmpeg["exe"], x4, big, p)
                result = runner(rargs)
                if result.returncode != 0 or not big.is_file():
                    raise BeautyPostError("beauty_post.step",
                                          f"ffmpeg resize exit {result.returncode}: {_stderr(result)}")
                steps.append(_step_record("upscale", tool, args, p, started,
                                          resize_args=[str(a) for a in rargs],
                                          resize_tool={"tool": "ffmpeg", "version": ffmpeg["version"],
                                                       "sha256": ffmpeg["sha256"]},
                                          output=big.name))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"input": frame.name, "output": out.name, "steps": steps}


def frames_in(bundle: Path) -> List[Path]:
    return sorted(p for p in Path(bundle).glob("frame_*.png") if _FRAME_RE.fullmatch(p.name))


def apply_to_bundle(bundle_dir, *, cube: Optional[Path], noisy: bool, grain: bool,
                    upscale: bool, off: FrozenSet[str] = frozenset(),
                    tools_dir: Optional[Path] = None, fetch: bool = True,
                    override: Optional[Mapping[str, Path]] = None, runner: Runner = _run,
                    look: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Every ``frame_NNNN.png`` in a render directory through :func:`post_frame`,
    recorded in its render.json as ``beauty_post``. A refusal is recorded
    there too (``{"refused": name, "reason": ...}``) and raised: the frames
    stay as they are, and the record says why there is no output."""
    bundle = Path(bundle_dir)
    manifest = bundle / "render.json"
    record: Dict[str, Any] = {
        "beauty_post_version": BEAUTY_POST_VERSION,
        "output": "frame_NNNN" + OUTPUT_SUFFIX,
        "steps_off": sorted(off),
        "look": {"film_stock": str(cube) if cube else None, "noisy": bool(noisy),
                 "grain_in_pipeline": bool(grain), "upscale": bool(upscale),
                 **({"world_preset": look.get("world_preset"), "grade": look.get("grade")}
                    if look else {})},
        "note": ("VISUAL ONLY: the original beauty frame and every label pass are untouched; "
                 "this output moves and invents pixels (denoise, halation, grain, upscale)"),
    }
    error: Optional[BeautyPostError] = None
    try:
        frames = frames_in(bundle)
        if not frames:
            raise BeautyPostError("beauty_post.input", f"{bundle} holds no frame_NNNN.png")
        results = [post_frame(frame, cube=cube, noisy=noisy, grain=grain, upscale=upscale, off=off,
                              tools_dir=tools_dir, fetch=fetch, override=override, runner=runner)
                   for frame in frames]
        record["frames"] = [r["output"] for r in results]
        record["steps"] = results[0]["steps"]
        record["per_frame"] = [{"input": r["input"], "output": r["output"],
                                "grain_seed": next((s["params"]["seed"] for s in r["steps"]
                                                    if s["step"] == "grain" and s.get("ran")), None)}
                               for r in results]
    except BeautyPostError as exc:
        error = exc
        record.update(refused=exc.constraint, reason=exc.message)
    if manifest.is_file():
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["beauty_post"] = record
        # The UE-written manifest stays ASCII (gotcha 13).
        manifest.write_text(json.dumps(payload, indent=1, ensure_ascii=True), encoding="utf-8")
    else:
        (bundle / "beauty_post_record.json").write_text(
            json.dumps(record, indent=1, ensure_ascii=True), encoding="utf-8")
    if error is not None:
        raise error
    return record


# -- from the beauty look -----------------------------------------------------------------

def look_choices(plan: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """What the beauty look sidecar (core/scene/beauty_look.py plan) decides
    for this pipeline: the stock's cube, whether the frame is noisy and
    whether the grain is ours."""
    from core.scene.beauty_look import FILM_GRAIN_IN_ENGINE, film_stock_for

    plan = plan or {}
    stock = plan.get("film_stock") or (film_stock_for(plan["grade"]) if plan.get("grade") else None)
    cube = REPO / stock["cube"] if stock and stock.get("cube") else None
    engine_grain = float((plan.get("lens_post") or {}).get("FilmGrainIntensity", 0.0)) > 0.0
    return {
        "cube": cube,
        "stock": stock["stock"] if stock else None,
        "noisy": plan.get("world_preset") in NOISY_PRESETS,
        "grain": not (FILM_GRAIN_IN_ENGINE and engine_grain),
    }


def bundles_in(root: Path) -> List[Path]:
    """The render directories under a run: ``frames/`` itself when it holds
    frames, else every ``frames/<camera>/``; a frames directory given directly."""
    root = Path(root)
    frames = root / "frames" if (root / "frames").is_dir() else root
    if not frames.is_dir():
        return []
    if frames_in(frames):
        return [frames]
    return sorted(d for d in frames.iterdir() if d.is_dir() and frames_in(d))


def apply_to_run(run_dir, plan: Optional[Mapping[str, Any]] = None, *, off: FrozenSet[str] = frozenset(),
                 upscale: bool = True, tools_dir: Optional[Path] = None, fetch: bool = True,
                 override: Optional[Mapping[str, Path]] = None, runner: Runner = _run) -> List[Dict[str, Any]]:
    """Every render bundle of a run through :func:`apply_to_bundle` with the
    beauty look's choices (``plan``: the run's beauty_look.json, read from
    the run when None). Returns the records; the first refusal is raised
    after the record is written."""
    run_dir = Path(run_dir)
    if plan is None:
        sidecar = run_dir / "beauty_look.json"
        plan = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
    choice = look_choices(plan)
    records = []
    for bundle in bundles_in(run_dir):
        records.append(apply_to_bundle(
            bundle, cube=choice["cube"], noisy=choice["noisy"], grain=choice["grain"],
            upscale=upscale, off=off, tools_dir=tools_dir, fetch=fetch, override=override,
            runner=runner, look=plan))
    if not records:
        raise BeautyPostError("beauty_post.input", f"{run_dir} holds no render bundle with frames")
    return records


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run", type=Path, help="a run directory (beauty_look.json, frames/) or a frames directory")
    parser.add_argument("--look", type=Path, default=None, help="the beauty_look.json to read instead")
    parser.add_argument("--off", default="", help="steps to skip, comma-separated")
    parser.add_argument("--no-upscale", action="store_true")
    parser.add_argument("--no-fetch", action="store_true", help="refuse rather than download a missing tool")
    parser.add_argument("--tools-dir", type=Path, default=None)
    parser.add_argument("--tool", action="append", default=[], metavar="NAME=PATH",
                        help="an executable to use for a tool (ffmpeg, oidn, realesrgan)")
    args = parser.parse_args(argv)
    override = {}
    for item in args.tool:
        name, _, path = item.partition("=")
        if name not in TOOLS or not path:
            parser.error(f"--tool {item!r}: NAME must be one of {list(TOOLS)}")
        override[name] = Path(path)
    off = frozenset(w.strip() for w in args.off.split(",") if w.strip())
    unknown = sorted(off - set(STEPS))
    if unknown:
        parser.error(f"--off {unknown}: not steps in {list(STEPS)}")
    plan = json.loads(args.look.read_text(encoding="utf-8")) if args.look else None
    try:
        records = apply_to_run(args.run, plan, off=off, upscale=not args.no_upscale,
                               tools_dir=args.tools_dir, fetch=not args.no_fetch,
                               override=override or None)
    except BeautyPostError as exc:
        print(f"{exc.constraint}: {exc.message}", file=sys.stderr)
        return 2
    for record in records:
        print(f"{len(record['frames'])} frame(s) -> {record['output']}; steps ran: "
              + ", ".join(s["step"] for s in record["steps"] if s.get("ran")))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    sys.exit(main())
