"""One settings file (Phase 3 box E2).

``settings.json`` in the per-OS user data directory is the only source for
the items the settings panel (E3) shows; ``GET/PUT /settings`` in
webapp/server.py read and write it through this module. The environment
is a developer override: ``effective(key)`` resolves env > file > default
and ``env_overrides()`` lists every row the environment currently
overrides, so a run can record them as ``env override``.

The file may hold only E1's ``file_keys()`` (``core/config_surface.py``):
``google_tiles_key``, ``render_quality``, ``llm_key``, ``capture_passes``.
Every other row -- ``google_tiles``, ``weather_backend``, ``rain_gain``,
``rain_style``, ``llm_model``, ... -- is env-or-default only, so
``FLIGHTSIM_GOOGLE_TILES=off`` stays the only off switch for the tiles and
the storm defaults stay where they are (CLAUDE.md; neither
``google_tiles_requested`` nor ``weather_backend_flags`` is edited here).

Path rule (no environment variable chooses it; tests set the module
attribute ``SETTINGS_PATH``): mac
``~/Library/Application Support/flightsim/settings.json``; windows
``%APPDATA%\\flightsim\\settings.json``; other
``${XDG_CONFIG_HOME:-~/.config}/flightsim/settings.json``. A missing,
empty (0 bytes) or ``{}`` file means all defaults; unreadable JSON refuses
by name ``settings.unreadable: <path>: <why>`` and is never reset.

Secrets (``google_tiles_key``, ``llm_key``) are stored as typed (local
single-user app; the file is created mode 0600 off Windows), served to the
panel as stored, and never logged: ``env_overrides()`` records a secret
override's value as ``"<set>"``.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.config_surface import SETTINGS, Setting, by_key, file_keys, ui_keys  # noqa: F401
from core.util.platform import TOOLCHAIN, UE_ENGINE_PATCH, UE_ENGINE_VERSION, find_ue_root, os_name

#: The rows whose values are secrets: never logged, recorded as "<set>".
SECRET_KEYS: Tuple[str, ...] = ("google_tiles_key", "llm_key")

#: The render quality presets (webapp/runs.py RENDER_QUALITIES; stated here
#: so core/ does not import webapp/).
RENDER_QUALITY_CHOICES: Tuple[str, ...] = ("measure", "beauty")

#: The capture passes a web capture offers (webapp/capture.py).
CAPTURE_PASS_CHOICES: Tuple[str, ...] = ("normals", "flow", "amodal")

#: The environment words that mean "off" for a boolean row (the same words
#: core/scenario/card.py GOOGLE_TILES_OFF reads).
OFF_WORDS: Tuple[str, ...] = ("0", "off", "false", "no")

#: The environment name the render host reads for the tiles key.
TILES_ENV = "GOOGLE_MAPS_API_KEY"

#: The environment name the LLM compiler reads for the Claude key.
LLM_ENV = "ANTHROPIC_API_KEY"

#: The status-line text a run shows when the environment overrides a row.
ENV_OVERRIDE_STATUS = "env override"


class SettingsError(Exception):
    """A named settings refusal: ``settings.<key>: <why>`` or
    ``settings.unreadable: <path>: <why>``."""


def user_data_dir() -> Path:
    """The per-OS user data directory for flightsim (no env var picks it)."""
    name = os_name()
    if name == "mac":
        return Path.home() / "Library" / "Application Support" / "flightsim"
    if name == "windows":
        appdata = os.environ.get("APPDATA", "").strip()
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "flightsim"
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "flightsim"


#: The settings file. Tests monkeypatch this module attribute.
SETTINGS_PATH: Path = user_data_dir() / "settings.json"


def settings_path() -> Path:
    """The settings file in use (the module attribute, so a test's
    monkeypatch of ``SETTINGS_PATH`` is honoured by every reader)."""
    return Path(SETTINGS_PATH)


def defaults() -> Dict[str, Any]:
    """Every row's default, from the E1 table."""
    return {s.key: _copy(s.default) for s in SETTINGS}


def _copy(value: Any) -> Any:
    return list(value) if isinstance(value, list) else value


def _row(key: str) -> Setting:
    try:
        return by_key(key)
    except KeyError:
        raise SettingsError(f"settings.{key}: unknown key") from None


def validate_value(key: str, value: Any) -> Any:
    """``value`` checked against the row ``key``; SettingsError names the
    problem. Unknown, read-only and env-only rows are refused here too,
    so this is the whole PUT whitelist (``file_keys()``)."""
    row = _row(key)
    if row.readonly:
        raise SettingsError(f"settings.{key}: read-only (shown, never set)")
    if not row.file_writable:
        how = f"set {row.env} in the environment" if row.env else "it has no switch"
        raise SettingsError(f"settings.{key}: not a settings-file key ({how}); "
                            f"the file may hold only {list(file_keys())}")
    if key in SECRET_KEYS:
        if not isinstance(value, str):
            raise SettingsError(f"settings.{key}: must be a string")
        return value.strip()
    if key == "render_quality":
        if not isinstance(value, str) or value.strip().lower() not in RENDER_QUALITY_CHOICES:
            raise SettingsError(f"settings.{key}: {value!r} is not one of {list(RENDER_QUALITY_CHOICES)}")
        return value.strip().lower()
    if key == "capture_passes":
        if isinstance(value, str):
            value = [w for w in value.replace(";", ",").split(",") if w.strip()]
        if not isinstance(value, list) or not all(isinstance(w, str) for w in value):
            raise SettingsError(f"settings.{key}: must be a list of pass names")
        words = [w.strip().lower() for w in value if w.strip()]
        unknown = sorted(set(words) - set(CAPTURE_PASS_CHOICES))
        if unknown:
            raise SettingsError(f"settings.{key}: {unknown} not in {list(CAPTURE_PASS_CHOICES)}")
        return list(dict.fromkeys(words))
    if not isinstance(value, str):
        raise SettingsError(f"settings.{key}: must be a string")
    return value


def load_settings(path: Optional[Path] = None) -> Dict[str, Any]:
    """The file's stored values (only ``file_keys()``). Missing, empty or
    ``{}`` = ``{}``. Unreadable JSON, a non-object top level or a key the
    file may not hold refuses by name; nothing is ever reset."""
    path = Path(path) if path is not None else settings_path()
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return {}
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SettingsError(f"settings.unreadable: {path}: {exc}") from exc
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise SettingsError(f"settings.unreadable: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SettingsError(f"settings.unreadable: {path}: top level is "
                            f"{type(data).__name__}, not an object")
    stored: Dict[str, Any] = {}
    for key, value in data.items():
        stored[str(key)] = validate_value(str(key), value)
    return stored


def save_settings(update: Dict[str, Any], path: Optional[Path] = None) -> Dict[str, Any]:
    """Validate every key of ``update`` (whitelist ``file_keys()``), merge
    into the stored values, write atomically (tmp + os.replace, mode 0600
    off Windows) and return the merged values."""
    if not isinstance(update, dict):
        raise SettingsError("settings.update: must be an object of key -> value")
    path = Path(path) if path is not None else settings_path()
    checked = {str(k): validate_value(str(k), v) for k, v in update.items()}
    merged = load_settings(path)
    merged.update(checked)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(merged, indent=1, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if sys.platform != "win32":
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return merged


def _parse_env(row: Setting, raw: str) -> Any:
    """An environment string as the row's value type."""
    raw = raw.strip()
    if isinstance(row.default, bool):
        return raw.lower() not in OFF_WORDS
    if isinstance(row.default, float):
        try:
            return float(raw)
        except ValueError:
            return raw
    if isinstance(row.default, list):
        return [w.strip() for w in raw.replace(";", ",").split(",") if w.strip()]
    return raw


def effective(key: str, environ: Optional[Dict[str, str]] = None) -> Tuple[Any, str]:
    """``(value, source)`` for ``key``: env > file > default; ``source`` is
    ``"env"``, ``"file"`` or ``"default"``. The environment never mutates."""
    row = _row(key)
    env = os.environ if environ is None else environ
    if row.env:
        raw = env.get(row.env, "")
        if raw is not None and raw.strip():
            return _parse_env(row, raw), "env"
    if row.file_writable:
        stored = load_settings()
        if key in stored:
            return _copy(stored[key]), "file"
    return _copy(row.default), "default"


def _settings_value(row: Setting, stored: Dict[str, Any]) -> Any:
    """The value the settings file (or the default) would give; a stored
    secret is reported as ``"<set>"``, never by value."""
    value = _copy(stored[row.key]) if row.file_writable and row.key in stored else _copy(row.default)
    if row.key in SECRET_KEYS and str(value or "").strip():
        return "<set>"
    return value


def env_overrides(environ: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Every row the environment overrides right now: ``[{"key", "env",
    "value", "settings_value"}, ...]``. A secret's ``value`` is ``"<set>"``;
    the value itself is never returned or logged."""
    env = os.environ if environ is None else environ
    try:
        stored = load_settings()
    except SettingsError:
        stored = {}
    out: List[Dict[str, Any]] = []
    for row in SETTINGS:
        if not row.env:
            continue
        raw = env.get(row.env, "")
        if raw is None or not raw.strip():
            continue
        value: Any = "<set>" if row.key in SECRET_KEYS else _parse_env(row, raw)
        out.append({"key": row.key, "env": row.env, "value": value,
                    "settings_value": _settings_value(row, stored)})
    return out


def env_override_status(overrides: List[Dict[str, Any]]) -> str:
    """The status-line text for a run: ``env override: NAME=value, ...``
    (secrets stay ``<set>``)."""
    return ENV_OVERRIDE_STATUS + ": " + ", ".join(
        f"{o['env']}={o['value']}" for o in overrides)


def render_env(environ: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """The render child's environment: a copy of ``environ`` (default
    ``os.environ``) plus ``GOOGLE_MAPS_API_KEY`` from the stored
    ``google_tiles_key`` unless the environment already has one. Nothing
    else is added; ``ANTHROPIC_API_KEY`` is never exported."""
    env = dict(os.environ if environ is None else environ)
    if not env.get(TILES_ENV, "").strip():
        stored = load_settings()
        key = str(stored.get("google_tiles_key", "") or "").strip()
        if key:
            env[TILES_ENV] = key
    return env


def llm_api_key(environ: Optional[Dict[str, str]] = None) -> str:
    """The Claude API key: ``ANTHROPIC_API_KEY`` in the environment, else
    the stored ``llm_key``, else ``""``. Read in-process only."""
    env = os.environ if environ is None else environ
    from_env = (env.get(LLM_ENV, "") or "").strip()
    if from_env:
        return from_env
    try:
        stored = load_settings()
    except SettingsError:
        return ""
    return str(stored.get("llm_key", "") or "").strip()


def missing_required(environ: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
    """The keys a render or compile will refuse without, each with its
    message: the tiles key while the tiles are on; the LLM key."""
    env = os.environ if environ is None else environ
    out: List[Dict[str, str]] = []
    tiles_on, _ = effective("google_tiles", env)
    tiles_key, _ = effective("google_tiles_key", env)
    if tiles_on and not str(tiles_key or "").strip():
        out.append({"key": "google_tiles_key",
                    "message": "google_tiles_key: Google tiles are the ground of every terrain "
                               "render and no key is set; type it in Settings (or set "
                               f"{TILES_ENV} for a developer run)"})
    llm_key, _ = effective("llm_key", env)
    if not str(llm_key or "").strip() and not (env.get("FLIGHTSIM_LLM", "") or "").strip():
        out.append({"key": "llm_key",
                    "message": "llm_key: no Claude API key; the compiler uses the hosted relay "
                               "or the offline regex parser until one is typed in Settings"})
    return out


def cesium_status() -> Dict[str, Any]:
    """``{"ok", "name", "version", "message"}``: the pinned Cesium for Unreal
    version (toolchain.json) and whether the engine's Marketplace plugin
    folder is installed here (mac: usually not, named)."""
    pinned = TOOLCHAIN.get("cesium_for_unreal")
    version = str(pinned) if pinned else None
    root = find_ue_root()
    plugin = None
    if root is not None:
        # The Epic launcher installs under a hashed folder name
        # (Cesiumfo9eaf76ca58f3V10), so look for the .uplugin, not a folder name.
        marketplace = root / "Engine" / "Plugins" / "Marketplace"
        found = sorted(marketplace.glob("*/CesiumForUnreal.uplugin"))
        plugin = found[0].parent if found else None
    if version is None:
        return {"ok": False, "name": "cesium_for_unreal", "version": None,
                "message": "cesium_for_unreal: toolchain.json records no pin"}
    if plugin is None:
        where = str(root / "Engine" / "Plugins" / "Marketplace") if root is not None else "no engine root on this OS"
        return {"ok": False, "name": "cesium_for_unreal", "version": version,
                "message": f"cesium_for_unreal {version} is pinned but the engine plugin is not "
                           f"installed ({where})"}
    return {"ok": True, "name": "cesium_for_unreal", "version": version,
            "message": f"cesium_for_unreal {version} installed at {plugin}"}


def engine_label() -> str:
    """``UE_ENGINE_VERSION`` plus the toolchain patch, e.g. ``5.7.4``."""
    return f"{UE_ENGINE_VERSION}.{UE_ENGINE_PATCH}"


def settings_payload(environ: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """The GET /settings body (and PUT's reply): every key's effective
    value, the defaults, the read-only rows, the env overrides, the
    missing keys and the file path."""
    env = os.environ if environ is None else environ
    stored = load_settings()
    values: Dict[str, Any] = {}
    for row in SETTINGS:
        if row.readonly:
            continue
        value, _source = effective(row.key, env)
        values[row.key] = value
    values["engine"] = engine_label()
    values["cesium_status"] = cesium_status()
    return {
        "settings": values,
        "defaults": defaults(),
        "readonly": {"engine": engine_label(), "cesium_status": values["cesium_status"]},
        "env_override": {o["key"]: o["env"] for o in env_overrides(env)},
        "env_override_values": env_overrides(env),
        "missing": missing_required(env),
        "file_keys": list(file_keys()),
        "stored_keys": sorted(stored),
        "path": str(settings_path()),
    }
