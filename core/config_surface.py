"""The configuration surface: every switch the program reads, sorted once.

Phase 3 box E1. One row per environment name (the 23 ``FLIGHTSIM_*``
names read under core/, webapp/, flightsim/ and scripts/*.py, plus the
four names without the prefix: ``UE_ROOT``, ``GOOGLE_MAPS_API_KEY``,
``CESIUM_ION_TOKEN``, ``ANTHROPIC_API_KEY``) and one entry per flag of ``flightsim/capture.py``.
Each carries a decision, its *bucket*:

* ``ui``       -- stays exposed, in the interface (exactly what the E3
                  settings panel shows; ``ui_keys()``);
* ``default``  -- hidden, value fixed (the environment can still override
                  it for a developer, the app never asks);
* ``dev-only`` -- tests and debugging scripts only;
* ``remove``   -- to delete (no row today).

E2's ``core/util/settings.py`` imports ``SETTINGS``, ``Setting``,
``ui_keys()`` and ``file_keys()`` from here: the settings file may hold only
the four ``file_writable`` rows. ``google_tiles`` is never file-writable and
never ``remove``: ``FLIGHTSIM_GOOGLE_TILES=off`` stays the only off switch
(CLAUDE.md, owner's rule 2026-10-09), and the storm weather rows keep their
defaults (procedural, rain gain 4, cinematic).

``docs/CONFIG_SURFACE.md`` is ``render_markdown()`` written to disk;
``tests/test_config_surface.py`` fails on an unlisted name, a stale row or
a drifted document. This module imports nothing from the project.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, Optional, Sequence, Set, Tuple

#: The four decisions a setting can carry (the plan's wording).
BUCKETS: Tuple[str, ...] = ("ui", "default", "dev-only", "remove")

#: Environment names in the table that are not ``FLIGHTSIM_``-prefixed.
NON_PREFIXED_ENV: Tuple[str, ...] = ("UE_ROOT", "GOOGLE_MAPS_API_KEY", "CESIUM_ION_TOKEN", "ANTHROPIC_API_KEY")

#: The regex the scan and the test share.
ENV_NAME_PATTERN = re.compile(r"FLIGHTSIM_[A-Z0-9_]+")

#: The repository root (this file is core/config_surface.py).
REPO_ROOT = Path(__file__).resolve().parent.parent

#: Where the scan looks: the three packages, and the top-level scripts.
SCAN_ROOTS: Tuple[str, ...] = ("core", "webapp", "flightsim", "scripts/*.py")


@dataclass(frozen=True)
class Setting:
    """One row of the configuration surface.

    ``default`` is the JSON value the settings endpoint (E2) serves
    unchanged; ``where_read`` lists ``path:line`` of every read (paths
    relative to the repository root); ``file_writable`` marks the rows the
    settings file may hold (E2's PUT whitelist); ``readonly`` marks the
    derived rows the panel shows but nobody sets.
    """

    key: str
    env: Optional[str]
    bucket: str
    default: Any
    where_read: Tuple[str, ...]
    note: str
    file_writable: bool = False
    readonly: bool = False

    def __post_init__(self) -> None:
        if self.bucket not in BUCKETS:
            raise ValueError(f"setting {self.key!r}: bucket {self.bucket!r} is not one of {list(BUCKETS)}")
        if not self.key or self.key != self.key.lower() or self.key.startswith("flightsim_"):
            raise ValueError(f"setting key {self.key!r} must be lower_snake_case without the FLIGHTSIM_ prefix")
        if self.file_writable and self.bucket != "ui":
            raise ValueError(f"setting {self.key!r}: only a ui row may be file_writable")
        if self.readonly and self.file_writable:
            raise ValueError(f"setting {self.key!r}: a readonly row cannot be file_writable")
        if self.key == "google_tiles" and (self.file_writable or self.bucket == "remove"):
            raise ValueError("google_tiles: FLIGHTSIM_GOOGLE_TILES=off is the only off switch; never in the file, never removed")

    @property
    def read_files(self) -> Tuple[str, ...]:
        """The files of ``where_read`` without their line numbers."""
        return tuple(ref.rsplit(":", 1)[0] for ref in self.where_read)


SETTINGS: Tuple[Setting, ...] = (
    # --- the six the E3 panel shows, in E3's order -------------------------
    Setting("google_tiles_key", "GOOGLE_MAPS_API_KEY", "ui", "",
            ("ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimGoogleTiles.cpp:79",),
            "Google tiles key or Cesium ion token, read by the render host only; the render refuses by "
            "name without a credential. Typed once in Settings; E2 passes a Cesium ion token (a JWT) to the "
            "headless render as CESIUM_ION_TOKEN and anything else as GOOGLE_MAPS_API_KEY.",
            file_writable=True),
    Setting("cesium_status", None, "ui", "unknown", (),
            "Derived (E2 cesium_status() from toolchain.json plus the plugin probe); shown, never set.",
            readonly=True),
    Setting("engine", "UE_ROOT", "ui", "5.7.4",
            ("core/util/platform.py:278",),
            "Shows UE_ENGINE_VERSION plus the toolchain patch; UE_ROOT is the developer's engine-root "
            "override (default core/util/platform.py:265).",
            readonly=True),
    Setting("render_quality", "FLIGHTSIM_RENDER_QUALITY", "ui", "measure",
            ("webapp/runs.py:2290",),
            "Render quality preset (measure or beauty).",
            file_writable=True),
    Setting("llm_key", "ANTHROPIC_API_KEY", "ui", "",
            ("core/nl/providers.py:200", "core/nl/llm_compiler.py:162", "core/nl/llm_compiler.py:1536",
             "core/nl/camera_prompt.py:361"),
            "Without it only the regex parser runs.",
            file_writable=True),
    Setting("capture_passes", "FLIGHTSIM_CAPTURE_PASSES", "ui", [],
            ("webapp/capture.py:66",),
            "Checkboxes normals / flow / amodal (E5).",
            file_writable=True),
    # --- developers only ----------------------------------------------------
    Setting("llm", "FLIGHTSIM_LLM", "dev-only", None,
            ("core/nl/providers.py:193", "core/nl/llm_compiler.py:157", "scripts/llm_check.py:50"),
            "Provider override; anthropic when the key is present."),
    Setting("llm_model", "FLIGHTSIM_LLM_MODEL", "dev-only", None,
            ("core/nl/providers.py:210", "core/nl/providers.py:219", "core/nl/providers.py:254",
             "core/nl/providers.py:262"),
            "Model override; the default is per provider."),
    Setting("relay_url", "FLIGHTSIM_RELAY_URL", "dev-only", None,
            ("core/nl/providers.py:231",),
            "Relay endpoint for the llm7 provider."),
    Setting("google_tiles", "FLIGHTSIM_GOOGLE_TILES", "dev-only", True,
            ("core/scenario/card.py:385",),
            "ON in every render; only the value off turns it off (the test suite's conftest sets it). "
            "Never in the settings file."),
    Setting("cesium_ion_token", "CESIUM_ION_TOKEN", "dev-only", "",
            ("ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimGoogleTiles.cpp:81",
             "core/util/settings.py:67"),
            "The Cesium ion route to the same tiles, for a developer run; the panel takes the token in "
            "google_tiles_key, so this row is no seventh field. A secret: shown as <set>, never by value."),
    # --- hidden defaults ----------------------------------------------------
    Setting("weather_backend", "FLIGHTSIM_WEATHER_BACKEND", "default", "procedural",
            ("webapp/runs.py:2321",),
            "Storm weather (procedural) on by default."),
    Setting("rain_gain", "FLIGHTSIM_RAIN_GAIN", "default", 4.0,
            ("webapp/runs.py:2327", "scripts/debug_storm_render.py:106"),
            "Rain opacity gain."),
    Setting("rain_style", "FLIGHTSIM_RAIN_STYLE", "default", "cinematic",
            ("webapp/runs.py:2328",),
            "physical or cinematic."),
    Setting("sky", "FLIGHTSIM_SKY", "default", None,
            ("webapp/runs.py:2473", "core/registry.py:1317", "scripts/ue_create_materials.py:2183"),
            "physical selects the physical sky; unset keeps the sun flags (webapp/runs.py render_look_for)."),
    Setting("render_timeout_seconds", "FLIGHTSIM_RENDER_TIMEOUT_SECONDS", "default", None,
            ("core/render/headless.py:83",),
            "headless.py DEFAULT_TIMEOUT_SECONDS; 0 disables."),
    Setting("stall_seconds", "FLIGHTSIM_STALL_SECONDS", "default", None,
            ("core/render/headless.py:79",),
            "headless.py DEFAULT_STALL_SECONDS; 0 disables."),
    Setting("terrain_prefetch", "FLIGHTSIM_TERRAIN_PREFETCH", "default", True,
            ("webapp/runs.py:377",),
            "off stops /compile from prefetching terrain (the test suite sets it)."),
    # --- developers only, continued ----------------------------------------
    Setting("ffmpeg", "FLIGHTSIM_FFMPEG", "dev-only", None,
            ("core/util/platform.py:76",),
            "ffmpeg binary override; auto-detected."),
    Setting("font", "FLIGHTSIM_FONT", "dev-only", None,
            ("core/util/platform.py:113",),
            "Overlay font override; auto-detected."),
    Setting("geocoder", "FLIGHTSIM_GEOCODER", "dev-only", None,
            ("core/nl/geocode.py:54",),
            "Geocoder backend (core/nl/geocode.py:54)."),
    Setting("geocode_cache", "FLIGHTSIM_GEOCODE_CACHE", "dev-only", None,
            ("core/nl/geocode.py:55",),
            "Geocode cache path (core/nl/geocode.py:55)."),
    Setting("rebuild_materials", "FLIGHTSIM_REBUILD_MATERIALS", "dev-only", None,
            ("scripts/ue_create_materials.py:926",),
            "Forces the material rebuild in the editor script."),
    Setting("machine", "FLIGHTSIM_MACHINE", "dev-only", None,
            ("scripts/phase3_event.py:37",),
            "Phase 3 scripts: the machine label in the event log."),
    Setting("branch", "FLIGHTSIM_BRANCH", "dev-only", None,
            ("scripts/phase3_monitor.py:235",),
            "Phase 3 scripts: the branch the monitor watches."),
    Setting("xplane_terrain", "FLIGHTSIM_XPLANE_TERRAIN", "dev-only", None,
            ("core/xplane/devflags.py:38",),
            "X-Plane comparison flag for developers; read in core/xplane/devflags.py (E5), never on the web path."),
    Setting("xplane_sky", "FLIGHTSIM_XPLANE_SKY", "dev-only", None,
            ("core/xplane/devflags.py:50",),
            "X-Plane comparison flag for developers; read in core/xplane/devflags.py (E5), never on the web path."),
    Setting("xplane_lighting", "FLIGHTSIM_XPLANE_LIGHTING", "dev-only", None,
            ("core/xplane/devflags.py:43",),
            "X-Plane comparison flag for developers; read in core/xplane/devflags.py (E5), never on the web path."),
)

#: Every ``add_argument`` of flightsim/capture.py (the positional ``spec``
#: included) with its decision. ``--no-host-flight`` is for tests and
#: core/dataset/batch.py only.
CLI_FLAGS: Dict[str, str] = {
    "spec": "ui",
    "--out": "ui",
    "--terrain": "ui",
    "--clip-seconds": "ui",
    "--synth-terrain": "dev-only",
    "--max-previews": "ui",
    "--render": "ui",
    "--void": "dev-only",
    "--passes": "ui",
    "--scene": "ui",
    "--calibration": "dev-only",
    "--sun-lux": "dev-only",
    "--accumulate": "dev-only",
    "--no-host-flight": "dev-only",
    "--card": "ui",
    "--instruments": "ui",
    "--null-tests": "ui",
    "--uncertainty": "ui",
    "--dis": "dev-only",
    "--dis-udp": "dev-only",
    "--dis-entity-type": "dev-only",
    "--dis-epoch": "dev-only",
    "--dis-emitter": "dev-only",
    "--cigi": "dev-only",
    "--hla": "dev-only",
    "--verbose": "dev-only",
}

#: Where the flags are declared.
CLI_FLAGS_SOURCE = "flightsim/capture.py"


def _check_table() -> None:
    keys = [s.key for s in SETTINGS]
    if len(set(keys)) != len(keys):
        raise ValueError("config surface: duplicate setting key")
    envs = [s.env for s in SETTINGS if s.env]
    if len(set(envs)) != len(envs):
        raise ValueError("config surface: duplicate environment name")
    for bucket in CLI_FLAGS.values():
        if bucket not in BUCKETS:
            raise ValueError(f"config surface: CLI flag bucket {bucket!r} is not one of {list(BUCKETS)}")


_check_table()


def by_key(key: str) -> Setting:
    """The row named ``key``; KeyError names a missing one."""
    for setting in SETTINGS:
        if setting.key == key:
            return setting
    raise KeyError(f"no setting {key!r} in the configuration surface")


def ui_keys() -> Tuple[str, ...]:
    """The six rows the E3 settings panel shows, in E3's order."""
    return tuple(s.key for s in SETTINGS if s.bucket == "ui")


def file_keys() -> Tuple[str, ...]:
    """The rows the settings file may hold: E2's PUT whitelist."""
    return tuple(s.key for s in SETTINGS if s.file_writable)


def env_names() -> FrozenSet[str]:
    """Every environment name in the table, prefixed or not."""
    return frozenset(s.env for s in SETTINGS if s.env)


def flightsim_env_names() -> FrozenSet[str]:
    """The ``FLIGHTSIM_``-prefixed names in the table."""
    return frozenset(n for n in env_names() if n.startswith("FLIGHTSIM_"))


def _iter_source_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        root = Path(root)
        if root.is_file():
            yield root
        elif root.is_dir():
            yield from sorted(root.rglob("*.py"))
        elif "*" in root.name:
            yield from sorted(root.parent.glob(root.name))


def scan_source_env_names(roots: Sequence[Path], exclude: Sequence[Path] = ()) -> Set[str]:
    """Every ``FLIGHTSIM_[A-Z0-9_]+`` token in the ``*.py`` files under
    ``roots`` (a directory is walked, a file is read, a ``dir/*.py`` glob is
    expanded). This module is always skipped, so a row here never counts
    as a read of itself; ``exclude`` skips more files.
    """
    skip = {Path(__file__).resolve(), *(Path(p).resolve() for p in exclude)}
    names: Set[str] = set()
    for path in _iter_source_files(roots):
        if path.resolve() in skip:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        names.update(ENV_NAME_PATTERN.findall(text))
    return names


def default_scan_roots(repo: Path = REPO_ROOT) -> Tuple[Path, ...]:
    """``SCAN_ROOTS`` resolved against ``repo``."""
    return tuple(repo / r for r in SCAN_ROOTS)


def _cell(value: Any) -> str:
    if value is None:
        return "unset"
    if value is True:
        return "on"
    if value is False:
        return "off"
    if value == "":
        return "none"
    if value == []:
        return "none"
    return str(value)


def _md(text: str) -> str:
    return text.replace("|", "\\|")


def render_markdown() -> str:
    """docs/CONFIG_SURFACE.md, generated from the table above."""
    out = ["# Configuration surface", ""]
    out.append(
        "Every switch the program reads, each with one decision. "
        "**ui**: stays exposed, in the interface (exactly the six fields the settings panel shows). "
        "**default**: hidden, value fixed (the environment may still override it for a developer; the app never asks). "
        "**dev-only**: tests and debugging scripts only. "
        "**remove**: to delete. "
        "The table lives in `core/config_surface.py`; this file is `render_markdown()` written to disk and "
        "`tests/test_config_surface.py` fails when the two drift, when a source file reads a `FLIGHTSIM_` "
        "name that has no row, or when a row's name is read nowhere."
    )
    out += ["", "## Environment variables", "",
            "| name | settings key | bucket | default | where read (file:line) |",
            "|---|---|---|---|---|"]
    for s in SETTINGS:
        if s.env and s.env.startswith("FLIGHTSIM_"):
            out.append(f"| `{s.env}` | `{s.key}` | {s.bucket} | {_md(_cell(s.default))} | "
                       f"{', '.join(f'`{w}`' for w in s.where_read)} |")
    out += ["", "## Keys not prefixed FLIGHTSIM_", "",
            "| name | settings key | bucket | default | where read (file:line) |",
            "|---|---|---|---|---|"]
    for s in SETTINGS:
        if s.env and not s.env.startswith("FLIGHTSIM_"):
            out.append(f"| `{s.env}` | `{s.key}` | {s.bucket} | {_md(_cell(s.default))} | "
                       f"{', '.join(f'`{w}`' for w in s.where_read)} |")
    out += ["", "## Derived rows (shown, never set)", "",
            "| settings key | bucket | default | note |", "|---|---|---|---|"]
    for s in SETTINGS:
        if not s.env:
            out.append(f"| `{s.key}` | {s.bucket} | {_md(_cell(s.default))} | {_md(s.note)} |")
    out += ["", "## Command-line flags", "",
            "| flag | bucket | where read |", "|---|---|---|"]
    for flag, bucket in CLI_FLAGS.items():
        out.append(f"| `{flag}` | {bucket} | `{CLI_FLAGS_SOURCE}` |")
    out += ["", "## Settings file", "",
            "The settings file (E2, `GET/PUT /settings`) may hold only: "
            + ", ".join(f"`{k}`" for k in file_keys())
            + ". `google_tiles` is never in it: `FLIGHTSIM_GOOGLE_TILES=off` is the only off switch, "
              "and the storm weather rows (`weather_backend` procedural, `rain_gain` 4, `rain_style` "
              "cinematic) stay on by default.",
            "", "## How to add a setting", "",
            "1. Add a `Setting` row to `SETTINGS` in `core/config_surface.py` (or a flag to `CLI_FLAGS`) "
            "with its bucket, default and every `file:line` that reads it.",
            "2. Regenerate this file: `python3 -c \"from core.config_surface import render_markdown; "
            "open('docs/CONFIG_SURFACE.md', 'w', encoding='utf-8').write(render_markdown())\"`.",
            "3. Run `pytest -q tests/test_config_surface.py`: it fails by name on an unlisted "
            "`FLIGHTSIM_` name, a stale row, a bad bucket or a drifted document.",
            ""]
    return "\n".join(out)


def write_markdown(path: Path = REPO_ROOT / "docs" / "CONFIG_SURFACE.md") -> Path:
    """Write ``render_markdown()`` to ``path`` (utf-8) and return it."""
    path.write_text(render_markdown(), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_markdown())
