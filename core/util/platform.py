"""One home for OS dispatch -- no scattered sys.platform checks.

The truthful platform story (README "Platform support"): the compiler,
headless physics, telemetry, terrain baking and the webapp run on
macOS / Linux / Windows; the UE render half is macOS-only for now and
REFUSES BY NAME everywhere else (every render gotcha was measured on
Metal/macOS only -- claiming more would be claiming what was never
measured). Everything that differs by OS routes through this module so
tests can pin the dispatch and future code has one obvious place to
look.

Tools are found, never assumed: ffmpeg by env override
(``FLIGHTSIM_FFMPEG``), then PATH, then the known per-OS locations --
and a missing ffmpeg is a NAMED refusal at the point of use, stating
the per-OS install command, because compiles and headless runs must
still work without it. Fonts degrade instead of refusing: a panel with
Pillow's bitmap font beats no clip, and the logged warning keeps the
degradation honest.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional, Tuple


class FfmpegMissingError(RuntimeError):
    """Named refusal: no ffmpeg on this machine (constraint ffmpeg.missing)."""

    constraint = "ffmpeg.missing"


def os_name() -> str:
    """"mac" | "linux" | "windows" -- the only three answers."""
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


def is_mac() -> bool:
    return os_name() == "mac"


#: Known install locations checked AFTER the env override and PATH.
_FFMPEG_FALLBACKS = {
    "mac": ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"),
    "linux": ("/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg",
              "/snap/bin/ffmpeg"),
    "windows": (r"C:\ffmpeg\bin\ffmpeg.exe",
                r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
}

_FFMPEG_INSTALL = {
    "mac": "brew install ffmpeg",
    "linux": "sudo apt install ffmpeg   (or your distro's equivalent)",
    "windows": "winget install ffmpeg   (or choco install ffmpeg)",
}


def find_ffmpeg() -> Path:
    """The ffmpeg to run, or a NAMED refusal (ffmpeg.missing).

    Resolution order: FLIGHTSIM_FFMPEG env override -> PATH -> the known
    per-OS locations. Raised at the point of use only: everything that
    does not encode video must keep working without ffmpeg.
    """
    override = os.environ.get("FLIGHTSIM_FFMPEG", "").strip()
    if override:
        return Path(override)
    which = shutil.which("ffmpeg")
    if which:
        return Path(which)
    for candidate in _FFMPEG_FALLBACKS[os_name()]:
        if Path(candidate).is_file():
            return Path(candidate)
    raise FfmpegMissingError(
        f"ffmpeg.missing: no ffmpeg found (checked FLIGHTSIM_FFMPEG, PATH, "
        f"and the usual {os_name()} locations). Install it with: "
        f"{_FFMPEG_INSTALL[os_name()]} -- compiling and headless runs work "
        f"without it; only video encoding needs it.")


#: Monospaced font chain per OS, best first. Env override FLIGHTSIM_FONT
#: wins everywhere.
_FONT_CHAINS = {
    "mac": ("/System/Library/Fonts/Menlo.ttc",
            "/System/Library/Fonts/Monaco.ttf"),
    "linux": ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
              "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
              "/usr/share/fonts/liberation/LiberationMono-Regular.ttf"),
    "windows": (r"C:\Windows\Fonts\consola.ttf",
                r"C:\Windows\Fonts\cour.ttf"),
}


def find_mono_font() -> Optional[str]:
    """Path of the best monospaced font on this OS, or None.

    None means the caller should fall back to Pillow's built-in bitmap
    font WITH a logged warning (mono_fonts() does both) -- an ugly panel
    beats no clip, and the warning keeps it honest.
    """
    override = os.environ.get("FLIGHTSIM_FONT", "").strip()
    if override:
        return override
    for candidate in _FONT_CHAINS[os_name()]:
        if Path(candidate).is_file():
            return candidate
    return None


def mono_fonts(sizes: Tuple[int, ...]) -> List:
    """Pillow fonts at the requested sizes, degrading honestly."""
    from PIL import ImageFont

    path = find_mono_font()
    if path:
        try:
            return [ImageFont.truetype(path, size) for size in sizes]
        except OSError:
            pass
    print(f"WARNING: no usable monospaced font on this {os_name()} machine "
          f"(set FLIGHTSIM_FONT to a .ttf); panels use Pillow's bitmap "
          f"font, which is legible but ugly.")
    default = ImageFont.load_default()
    return [default for _ in sizes]


UE_PLATFORM_REFUSAL = (
    "REFUSED ue.platform: rendered clips currently require macOS.\n"
    "The compiler, headless physics, telemetry and the webapp run on\n"
    "this OS -- see README \"Platform support\".")


def ue_available() -> bool:
    """True only where the UE render half is measured to work: macOS."""
    return is_mac()
