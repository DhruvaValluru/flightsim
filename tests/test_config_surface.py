"""Phase 3 box E1: the configuration surface is complete, decided and current.

Every ``FLIGHTSIM_`` name read under core/, webapp/, flightsim/ and
scripts/*.py has a row with a bucket; every row is still read somewhere;
the generated docs/CONFIG_SURFACE.md matches the table; the Google tiles
and storm weather defaults stay on (CLAUDE.md).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from core import config_surface as cs
from core.config_surface import (
    BUCKETS, CLI_FLAGS, CLI_FLAGS_SOURCE, NON_PREFIXED_ENV, SETTINGS, Setting,
    by_key, default_scan_roots, env_names, file_keys, flightsim_env_names,
    render_markdown, scan_source_env_names, ui_keys,
)
from core.scenario.card import google_tiles_requested
from webapp.runs import weather_backend_flags

REPO = Path(__file__).resolve().parent.parent

#: The 23 names Align froze on 2026-11-04 (the plan said 20; three more in scripts/), plus the dev-only probe names added since.
FROZEN_NAMES = frozenset({
    "FLIGHTSIM_BRANCH", "FLIGHTSIM_CAPTURE_PASSES", "FLIGHTSIM_FFMPEG", "FLIGHTSIM_FONT",
    "FLIGHTSIM_GEOCODE_CACHE", "FLIGHTSIM_GEOCODER", "FLIGHTSIM_GOOGLE_TILES", "FLIGHTSIM_LLM",
    "FLIGHTSIM_LLM_MODEL", "FLIGHTSIM_MACHINE", "FLIGHTSIM_RAIN_GAIN", "FLIGHTSIM_RAIN_STYLE",
    "FLIGHTSIM_REBUILD_MATERIALS", "FLIGHTSIM_RELAY_URL", "FLIGHTSIM_RENDER_QUALITY",
    "FLIGHTSIM_RENDER_TIMEOUT_SECONDS", "FLIGHTSIM_SKY", "FLIGHTSIM_STALL_SECONDS",
    "FLIGHTSIM_TERRAIN_PREFETCH", "FLIGHTSIM_WEATHER_BACKEND", "FLIGHTSIM_XPLANE_LIGHTING",
    "FLIGHTSIM_WORLD_BEAUTY_OVERRIDES",  # visual overhaul, dev-only probe overrides
    "FLIGHTSIM_RENDER_SWITCHES",  # round 5 (2026-11-10), dev-only host A/B switches
    "FLIGHTSIM_BATCH_MIN_FREE_MB",  # round 6 (2026-11-10), the batch memory wait
    "FLIGHTSIM_RAIN_VEIL",          # round 7 lane D (2026-11-11), the beauty rain veil A/B
    "FLIGHTSIM_TERRAIN_DETAIL",     # round 7 lane B (2026-11-11), the terrain-detail fallback
    "FLIGHTSIM_BEAUTY_POST",  # round 5 L5 (2026-11-10), the post-render beauty pipeline
    "FLIGHTSIM_XPLANE_SKY", "FLIGHTSIM_XPLANE_TERRAIN",
    # visual round 5 lane L3 (2026-11-10): the distant sheet's switch, the sky HDRI probe and its cache
    "FLIGHTSIM_DISTANT_CLOUDS", "FLIGHTSIM_SKY_HDRI", "FLIGHTSIM_HDRI_CACHE",
})


def _real_scan() -> set:
    return scan_source_env_names(default_scan_roots(REPO))


def test_every_flightsim_name_in_source_is_registered_with_a_decision():
    found = _real_scan()
    assert found, "the scan found no FLIGHTSIM_ name at all; the roots are wrong"
    missing = sorted(found - flightsim_env_names())
    assert not missing, f"FLIGHTSIM_ names read in source without a row in core/config_surface.py: {missing}"
    for name in found:
        row = next(s for s in SETTINGS if s.env == name)
        assert row.bucket in BUCKETS


def test_the_scan_detects_an_unlisted_name(tmp_path):
    fake = tmp_path / "pkg"
    fake.mkdir()
    (fake / "mod.py").write_text('import os\nX = os.environ.get("FLIGHTSIM_ZZZ_TEST", "")\n', encoding="utf-8")
    found = scan_source_env_names([fake])
    assert found == {"FLIGHTSIM_ZZZ_TEST"}
    assert "FLIGHTSIM_ZZZ_TEST" not in flightsim_env_names()
    unlisted = found - flightsim_env_names()
    assert unlisted == {"FLIGHTSIM_ZZZ_TEST"}, "an unlisted name must be reported by name"
    # A file (not only a directory) and a dir/*.py glob are scanned too.
    assert scan_source_env_names([fake / "mod.py"]) == {"FLIGHTSIM_ZZZ_TEST"}
    assert scan_source_env_names([fake / "*.py"]) == {"FLIGHTSIM_ZZZ_TEST"}
    # The module's own table never counts as a read.
    assert scan_source_env_names([REPO / "core" / "config_surface.py"]) == set()
    # The real scan is exactly the 32 frozen names: a 33rd fails here by name.
    real = _real_scan()
    assert len(FROZEN_NAMES) == 32
    assert real == FROZEN_NAMES, (
        f"new: {sorted(real - FROZEN_NAMES)}; gone: {sorted(FROZEN_NAMES - real)}")
    assert flightsim_env_names() == FROZEN_NAMES


def test_every_registered_flightsim_name_is_still_read_somewhere():
    found = _real_scan()
    stale = sorted(s.env for s in SETTINGS
                   if s.env and s.env.startswith("FLIGHTSIM_") and s.bucket != "remove"
                   and s.env not in found)
    assert not stale, f"rows whose name is read nowhere under the scan roots: {stale}"
    # The non-prefixed names are read where the table says.
    for name in NON_PREFIXED_ENV:
        row = next(s for s in SETTINGS if s.env == name)
        assert row.where_read, name
        assert any(name in (REPO / f).read_text(encoding="utf-8", errors="replace") for f in row.read_files), name
    assert env_names() == FROZEN_NAMES | set(NON_PREFIXED_ENV)


def test_every_row_has_a_valid_bucket_and_an_existing_where_read_file():
    seen = set()
    for s in SETTINGS:
        assert s.bucket in BUCKETS, s.key
        assert s.key not in seen, f"duplicate key {s.key}"
        seen.add(s.key)
        if s.env:
            assert s.where_read, f"{s.key} names no read"
        for ref in s.where_read:
            path, line = ref.rsplit(":", 1)
            assert line.isdigit(), ref
            assert (REPO / path).is_file(), f"{s.key}: where_read {ref} names a missing file"
            if s.env:
                assert s.env in (REPO / path).read_text(encoding="utf-8", errors="replace"), (
                    f"{s.key}: {path} does not read {s.env}")
    assert not [s for s in SETTINGS if s.bucket == "remove"], "no row is marked remove today"
    with pytest.raises(ValueError, match="bucket"):
        Setting("bad", None, "sometimes", None, (), "")
    with pytest.raises(ValueError):
        Setting("google_tiles", "FLIGHTSIM_GOOGLE_TILES", "remove", True, (), "")
    with pytest.raises(ValueError):
        Setting("google_tiles", "FLIGHTSIM_GOOGLE_TILES", "ui", True, (), "", file_writable=True)
    with pytest.raises(ValueError):
        Setting("x", None, "dev-only", None, (), "", file_writable=True)
    with pytest.raises(KeyError):
        by_key("not_a_setting")
    assert by_key("rain_gain").default == 4.0


def test_every_capture_flag_is_listed():
    text = (REPO / CLI_FLAGS_SOURCE).read_text(encoding="utf-8")
    flags = set(re.findall(r'add_argument\(\s*"(--[a-z-]+)"', text))
    assert "--no-host-flight" in flags
    missing = sorted(flags - set(CLI_FLAGS))
    assert not missing, f"capture.py flags without a row in CLI_FLAGS: {missing}"
    gone = sorted(f for f in CLI_FLAGS if f.startswith("--") and f not in flags)
    assert not gone, f"CLI_FLAGS rows capture.py no longer declares: {gone}"
    assert CLI_FLAGS["--no-host-flight"] == "dev-only"
    assert "spec" in CLI_FLAGS
    assert set(CLI_FLAGS.values()) <= set(BUCKETS)


def test_google_tiles_is_never_removed_or_opt_in(monkeypatch):
    row = by_key("google_tiles")
    assert row.bucket in ("default", "dev-only")
    assert row.default is True
    assert not row.file_writable
    assert "google_tiles" not in file_keys()
    monkeypatch.delenv("FLIGHTSIM_GOOGLE_TILES", raising=False)
    assert google_tiles_requested() is True
    monkeypatch.setenv("FLIGHTSIM_GOOGLE_TILES", "off")
    assert google_tiles_requested() is False


def test_storm_weather_defaults_stay_on(monkeypatch):
    for name in ("FLIGHTSIM_WEATHER_BACKEND", "FLIGHTSIM_RAIN_GAIN", "FLIGHTSIM_RAIN_STYLE"):
        monkeypatch.delenv(name, raising=False)
    flags = weather_backend_flags()
    assert "-weather-backend=procedural" in flags
    assert "-rain-gain=4" in flags
    assert "-rain-style=cinematic" in flags
    assert by_key("weather_backend").default == "procedural"
    assert by_key("rain_gain").default == 4.0
    assert by_key("rain_style").default == "cinematic"
    for key in ("weather_backend", "rain_gain", "rain_style"):
        assert by_key(key).bucket == "default"


def test_ui_bucket_is_the_e3_set():
    assert ui_keys() == ("google_tiles_key", "cesium_status", "engine", "render_quality", "llm_key", "capture_passes")
    assert file_keys() == ("google_tiles_key", "render_quality", "llm_key", "capture_passes")
    assert "google_tiles" not in file_keys()
    assert by_key("cesium_status").readonly and by_key("engine").readonly
    assert by_key("google_tiles_key").env == "GOOGLE_MAPS_API_KEY"
    assert by_key("cesium_ion_token").env == "CESIUM_ION_TOKEN"
    assert not by_key("cesium_ion_token").file_writable
    assert by_key("llm_key").env == "ANTHROPIC_API_KEY"
    assert by_key("engine").env == "UE_ROOT"
    for key in ("llm", "llm_model", "relay_url", "google_tiles", "cesium_ion_token", "ffmpeg", "font", "geocoder", "geocode_cache",
                "rebuild_materials", "machine", "branch", "xplane_terrain", "xplane_sky", "xplane_lighting"):
        assert by_key(key).bucket == "dev-only", key
    for key in ("weather_backend", "rain_gain", "rain_style", "sky", "render_timeout_seconds",
                "stall_seconds", "terrain_prefetch"):
        assert by_key(key).bucket == "default", key


def test_config_surface_doc_matches_the_table():
    doc = (REPO / "docs" / "CONFIG_SURFACE.md").read_text(encoding="utf-8")
    assert doc == render_markdown(), "docs/CONFIG_SURFACE.md drifted: run python3 -m core.config_surface"
    for name in sorted(FROZEN_NAMES | set(NON_PREFIXED_ENV)):
        assert f"`{name}`" in doc, name
    for flag in CLI_FLAGS:
        assert f"`{flag}`" in doc, flag
    for heading in ("## Environment variables", "## Command-line flags", "## Keys not prefixed FLIGHTSIM_",
                    "## How to add a setting"):
        assert heading in doc
    assert cs.write_markdown.__doc__
