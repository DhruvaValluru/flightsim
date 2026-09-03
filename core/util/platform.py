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
    "REFUSED ue.platform: rendered frames and clips require macOS, or\n"
    "Windows with Unreal Engine 5.5 and the FlightSimBridge built -- run\n"
    "scripts\\ue_preflight.ps1 for the exact missing piece. The compiler,\n"
    "headless physics, telemetry, the capture manifest, previews and\n"
    "verification, and the webapp run on this OS either way -- see README\n"
    "\"Platform support\".")

#: Default engine install roots, checked AFTER the UE_ROOT env override.
#: Windows scans for any UE_5.* so a 5.4/5.6 install is still found and
#: preflight can name the version mismatch instead of "not found".
_UE_ROOT_DEFAULTS = {
    "mac": ("/Users/Shared/Epic Games/UE_5.5",),
    "windows": (r"C:\Program Files\Epic Games\UE_5.5",),
    "linux": (),
}


def find_ue_root() -> Optional[Path]:
    """The engine install to use: UE_ROOT env override, the per-OS
    default, else (Windows) the newest Epic Games/UE_5.* present. When
    nothing exists the default path is still returned on mac/Windows so
    refusals can NAME the expected location; None only on Linux, which
    has no UE half at all."""
    override = os.environ.get("UE_ROOT", "").strip()
    if override:
        return Path(override)
    defaults = _UE_ROOT_DEFAULTS[os_name()]
    for candidate in defaults:
        if Path(candidate).is_dir():
            return Path(candidate)
    if os_name() == "windows":
        epic = Path(r"C:\Program Files\Epic Games")
        versions = sorted(epic.glob("UE_5.*"), reverse=True)
        if versions:
            return versions[0]
    return Path(defaults[0]) if defaults else None


def ue_editor_path() -> Optional[Path]:
    """The headless editor binary (UnrealEditor-Cmd) for this OS -- the
    path to run or to name in a refusal; check is_file() for presence.
    None only on Linux, where there is no UE half."""
    root = find_ue_root()
    if root is None:
        return None
    if os_name() == "windows":
        return root / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
    return root / "Engine" / "Binaries" / "Mac" / "UnrealEditor-Cmd"


def ue_bridge_binary(repo: Path) -> Path:
    """Where a built FlightSimBridge lands on this OS (existence = built)."""
    plugin = repo / "ue" / "Plugins" / "FlightSimBridge" / "Binaries"
    if os_name() == "windows":
        return plugin / "Win64" / "UnrealEditor-FlightSimBridge.dll"
    return plugin / "Mac" / "UnrealEditor-FlightSimBridge.dylib"


def ue_runner_command(repo: Path, script_stem: str) -> List[str]:
    """Command prefix for scripts/<stem>.sh (mac) or <stem>.ps1 (Windows)
    -- the experiments that drive the UE host through those wrappers call
    this instead of hardcoding the .sh path. Append the wrapper's own
    arguments to the returned list."""
    if os_name() == "windows":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(repo / "scripts" / f"{script_stem}.ps1")]
    return [str(repo / "scripts" / f"{script_stem}.sh")]


def ue_unavailable_reason() -> Optional[str]:
    """None where the UE render half can run; otherwise WHY it cannot, in
    one sentence the page shows beside the disabled render options and
    the CLI prints with its refusal. The same facts ue_available()
    decides on (pinned by test: available == reason is None)."""
    if is_mac():
        return None
    if os_name() == "windows":
        editor = ue_editor_path()
        if editor is None or not editor.is_file():
            return (f"no engine on this machine: set UE_ROOT to the Unreal "
                    f"Engine 5.5 install (looked for {editor})")
        repo = Path(__file__).resolve().parents[2]
        if not ue_bridge_binary(repo).is_file():
            return ("FlightSimBridge not built: run scripts\\ue_preflight.ps1 "
                    "then scripts\\build_ue.ps1")
        return None
    return ("no engine on this OS: the render half needs macOS, or Windows "
            "with Unreal Engine 5.5 and the FlightSimBridge built")


def ue_available() -> bool:
    """True where the UE render half can run: macOS (where every render
    gotcha was measured), or Windows with an engine install AND a built
    bridge -- the gate flips on only once scripts/build_ue.ps1 has
    produced the binary, so a bare clone still refuses by name with the
    build steps instead of failing mid-run. Windows render output is
    validated per machine by experiments/gate6_visual.py (the render
    calibrations were measured on Metal; Gate 6 measures them again from
    the pixels wherever it runs)."""
    if is_mac():
        return True
    if os_name() == "windows":
        editor = ue_editor_path()
        repo = Path(__file__).resolve().parents[2]
        return (editor is not None and editor.is_file()
                and ue_bridge_binary(repo).is_file())
    return False
