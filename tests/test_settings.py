"""Phase 3 box E2: one settings file behind GET/PUT /settings.

Every test points ``core.util.settings.SETTINGS_PATH`` at a tmp file and
clears every FLIGHTSIM_* name of the configuration surface (plus the two
key names) so the documented defaults -- tiles on, storm on -- are
measured against the real functions, not the table.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.config_surface import file_keys, flightsim_env_names
from core.render import headless
from core.scenario.card import google_tiles_requested
from core.util import settings
from core.util.settings import (
    SettingsError, effective, env_overrides, llm_api_key, load_settings, missing_required, render_env,
    save_settings, settings_payload,
)
from webapp.runs import RunState, record_env_override, render_quality, weather_backend_flags
from webapp.server import app

CLEARED = sorted(flightsim_env_names() | {"GOOGLE_MAPS_API_KEY", "CESIUM_ION_TOKEN", "ANTHROPIC_API_KEY", "UE_ROOT"})

FAKE_ION = "eyJfake.token.value"


@pytest.fixture
def clean(monkeypatch, tmp_path):
    """Empty settings file (0 bytes) and an environment without any switch."""
    path = tmp_path / "settings.json"
    path.write_bytes(b"")
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    monkeypatch.setattr(settings, "compiled_ion_fallback", lambda: False)
    for name in CLEARED:
        monkeypatch.delenv(name, raising=False)
    return path


def test_empty_file_and_env_give_documented_defaults(clean):
    assert load_settings() == {}
    expect = {"google_tiles": True, "google_tiles_key": "", "llm_key": "",
              "render_quality": "measure", "capture_passes": [],
              "weather_backend": "procedural", "rain_gain": 4.0, "rain_style": "cinematic"}
    for key, value in expect.items():
        assert effective(key) == (value, "default"), key
    assert env_overrides() == []
    body = settings_payload()
    for key, value in expect.items():
        assert body["settings"][key] == value, key
    assert body["readonly"]["engine"] == body["settings"]["engine"]
    assert body["readonly"]["cesium_status"]["name"] == "cesium_for_unreal"
    assert body["env_override"] == {}
    assert body["path"] == str(clean)


def test_missing_file_gives_defaults(clean):
    clean.unlink()
    assert load_settings() == {}
    assert effective("render_quality") == ("measure", "default")
    assert settings_payload()["settings"]["google_tiles"] is True
    # {} is the same as missing.
    clean.write_text("{}", encoding="utf-8")
    assert load_settings() == {}


def test_tiles_default_on_storm_default_on(clean):
    # The real functions, not the table (step 7b).
    assert google_tiles_requested() is True
    assert weather_backend_flags() == ["-weather-backend=procedural", "-rain-gain=4",
                                       "-rain-style=cinematic"]
    assert render_quality() == "measure"


def test_google_tiles_off_env_still_honoured(clean, monkeypatch):
    monkeypatch.setenv("FLIGHTSIM_GOOGLE_TILES", "off")
    assert google_tiles_requested() is False
    assert effective("google_tiles") == (False, "env")
    listed = [o for o in env_overrides() if o["key"] == "google_tiles"]
    assert listed == [{"key": "google_tiles", "env": "FLIGHTSIM_GOOGLE_TILES",
                       "value": False, "settings_value": True}]
    assert settings_payload()["env_override"] == {"google_tiles": "FLIGHTSIM_GOOGLE_TILES"}


def test_env_wins_and_is_recorded_as_env_override(clean, monkeypatch):
    save_settings({"render_quality": "beauty"})
    assert effective("render_quality") == ("beauty", "file")
    assert render_quality() == "beauty"
    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "measure")
    assert effective("render_quality") == ("measure", "env")
    assert render_quality() == "measure"
    monkeypatch.setenv("FLIGHTSIM_RAIN_GAIN", "2")
    entries = env_overrides()
    assert [o for o in entries if o["key"] == "rain_gain"] == [
        {"key": "rain_gain", "env": "FLIGHTSIM_RAIN_GAIN", "value": 2.0, "settings_value": 4.0}]
    assert [o for o in entries if o["key"] == "render_quality"] == [
        {"key": "render_quality", "env": "FLIGHTSIM_RENDER_QUALITY", "value": "measure",
         "settings_value": "beauty"}]
    assert weather_backend_flags()[1] == "-rain-gain=2"
    # The run record (step 7): one entry per overridden row and the status line.
    run = RunState(run_id="abc123")
    recorded = record_env_override(run)
    assert [o["key"] for o in recorded] == ["render_quality", "rain_gain"]
    assert run.as_dict()["env_override"] == recorded
    assert run.events[-1]["detail"].startswith("env override: ")
    assert "FLIGHTSIM_RAIN_GAIN=2.0" in run.events[-1]["detail"]


def test_get_put_round_trip(clean):
    client = TestClient(app)
    first = client.get("/settings")
    assert first.status_code == 200
    assert first.json()["settings"]["render_quality"] == "measure"
    assert first.json()["file_keys"] == list(file_keys())
    put = client.put("/settings", json={"settings": {
        "render_quality": "beauty", "google_tiles_key": "AIza-test", "llm_key": "sk-test",
        "capture_passes": ["normals", "flow"]}})
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["settings"]["render_quality"] == "beauty"
    assert body["settings"]["google_tiles_key"] == "AIza-test"
    assert body["settings"]["llm_key"] == "sk-test"
    assert body["settings"]["capture_passes"] == ["normals", "flow"]
    assert body["settings"]["google_tiles"] is True
    assert body["settings"]["weather_backend"] == "procedural"
    on_disk = json.loads(clean.read_text(encoding="utf-8"))
    assert on_disk == {"render_quality": "beauty", "google_tiles_key": "AIza-test",
                       "llm_key": "sk-test", "capture_passes": ["normals", "flow"]}
    # A partial PUT merges; a second GET agrees.
    again = client.put("/settings", json={"settings": {"render_quality": "measure"}})
    assert again.status_code == 200
    assert again.json()["settings"]["google_tiles_key"] == "AIza-test"
    assert client.get("/settings").json()["settings"]["render_quality"] == "measure"
    if sys.platform != "win32":
        assert stat.S_IMODE(clean.stat().st_mode) == 0o600


def test_put_rejects_unknown_key_and_readonly(clean):
    client = TestClient(app)
    unknown = client.put("/settings", json={"settings": {"no_such_key": 1}})
    assert unknown.status_code == 422
    assert unknown.json()["detail"] == "settings.no_such_key: unknown key"
    for key in ("engine", "cesium_status"):
        ro = client.put("/settings", json={"settings": {key: "x"}})
        assert ro.status_code == 422, key
        assert ro.json()["detail"].startswith(f"settings.{key}: read-only")
    bad = client.put("/settings", json={"settings": {"render_quality": "ultra"}})
    assert bad.status_code == 422
    assert bad.json()["detail"].startswith("settings.render_quality:")
    passes = client.put("/settings", json={"settings": {"capture_passes": ["depth"]}})
    assert passes.status_code == 422
    assert passes.json()["detail"].startswith("settings.capture_passes:")
    assert load_settings() == {}     # nothing was written


def test_file_may_not_set_google_tiles(clean):
    client = TestClient(app)
    for value in (False, "off", 0):
        refused = client.put("/settings", json={"settings": {"google_tiles": value}})
        assert refused.status_code == 422, value
        assert refused.json()["detail"].startswith("settings.google_tiles: not a settings-file key")
        assert "FLIGHTSIM_GOOGLE_TILES" in refused.json()["detail"]
    for key in ("weather_backend", "rain_gain", "rain_style", "llm_model"):
        refused = client.put("/settings", json={"settings": {key: "off"}})
        assert refused.status_code == 422, key
    assert google_tiles_requested() is True
    assert load_settings() == {}
    with pytest.raises(SettingsError, match="settings.google_tiles: not a settings-file key"):
        save_settings({"google_tiles": False})
    # A hand-edited file that smuggles the row is refused by name too.
    clean.write_text(json.dumps({"google_tiles": False}), encoding="utf-8")
    with pytest.raises(SettingsError, match="settings.google_tiles"):
        load_settings()
    assert google_tiles_requested() is True


def test_unreadable_json_refuses_by_name(clean):
    clean.write_text("{not json", encoding="utf-8")
    with pytest.raises(SettingsError) as excinfo:
        load_settings()
    assert str(excinfo.value).startswith(f"settings.unreadable: {clean}: ")
    assert clean.read_text(encoding="utf-8") == "{not json"   # never reset
    response = TestClient(app).get("/settings")
    assert response.status_code == 422
    assert response.json()["detail"].startswith("settings.unreadable: ")
    clean.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(SettingsError, match="settings.unreadable: .*not an object"):
        load_settings()


def test_secret_values_never_in_logs_or_env_override(clean, monkeypatch, caplog):
    save_settings({"llm_key": "sk-file-secret", "google_tiles_key": "AIza-file-secret"})
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIza-env-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-secret")
    entries = env_overrides()
    by_key = {o["key"]: o for o in entries}
    assert by_key["google_tiles_key"]["value"] == "<set>"
    assert by_key["llm_key"]["value"] == "<set>"
    text = json.dumps(entries) + json.dumps(settings_payload()["env_override"]) \
        + json.dumps(settings_payload()["env_override_values"])
    for secret in ("AIza-env-secret", "sk-env-secret", "AIza-file-secret", "sk-file-secret"):
        assert secret not in text
    run = RunState(run_id="abc123")
    record_env_override(run)
    status = json.dumps(run.as_dict()) + json.dumps(run.events) + caplog.text
    for secret in ("AIza-env-secret", "sk-env-secret", "AIza-file-secret", "sk-file-secret"):
        assert secret not in status
    assert "GOOGLE_MAPS_API_KEY=<set>" in run.events[-1]["detail"]
    # The panel itself reads the stored values (password inputs, E3).
    assert settings_payload()["settings"]["llm_key"] == "sk-env-secret"


class _FakePopen:
    calls = []

    def __init__(self, command, **kwargs):
        self.command = list(command)
        self.kwargs = kwargs
        self.pid = 4242
        _FakePopen.calls.append(self)

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0


def test_render_env_carries_key_once(clean, monkeypatch, tmp_path):
    save_settings({"google_tiles_key": "AIza-from-settings", "llm_key": "sk-never-exported"})
    monkeypatch.setattr(headless.subprocess, "Popen", _FakePopen)
    _FakePopen.calls.clear()
    result = headless.run_headless(["render", "--x"], tmp_path / "render.log",
                                   stall=None, timeout=None, poll_seconds=0.01)
    assert result.returncode == 0
    assert len(_FakePopen.calls) == 1
    env = _FakePopen.calls[0].kwargs["env"]
    assert env["GOOGLE_MAPS_API_KEY"] == "AIza-from-settings"
    assert set(env) - set(os.environ) == {"GOOGLE_MAPS_API_KEY"}
    assert "ANTHROPIC_API_KEY" not in env
    assert sum(1 for k in env if k == "GOOGLE_MAPS_API_KEY") == 1
    assert "GOOGLE_MAPS_API_KEY" not in os.environ      # never mutated
    # An environment-set key wins over the stored one.
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "AIza-from-shell")
    _FakePopen.calls.clear()
    headless.run_headless(["render"], tmp_path / "render2.log", stall=None, timeout=None,
                          poll_seconds=0.01)
    env = _FakePopen.calls[0].kwargs["env"]
    assert env["GOOGLE_MAPS_API_KEY"] == "AIza-from-shell"
    assert set(env) == set(os.environ)
    assert render_env({"GOOGLE_MAPS_API_KEY": "  "})["GOOGLE_MAPS_API_KEY"] == "AIza-from-settings"
    assert render_env({"PATH": "/bin"}) == {"PATH": "/bin", "GOOGLE_MAPS_API_KEY": "AIza-from-settings"}


def test_an_ion_token_goes_to_the_ion_variable_and_a_plain_key_to_google(clean):
    assert settings.is_ion_token(FAKE_ION)
    for other in ("", "AIza-plain", "eyJ.only-two", "eyJa..c", "abc.def.ghi", "eyJa.b.c.d"):
        assert not settings.is_ion_token(other), other
    save_settings({"google_tiles_key": FAKE_ION})
    assert render_env({"PATH": "/bin"}) == {"PATH": "/bin", "CESIUM_ION_TOKEN": FAKE_ION}
    save_settings({"google_tiles_key": "AIza-plain"})
    assert render_env({"PATH": "/bin"}) == {"PATH": "/bin", "GOOGLE_MAPS_API_KEY": "AIza-plain"}


def test_a_credential_in_the_environment_wins_over_the_stored_one(clean):
    """Either kind, whichever kind is stored: the render host prefers a Google
    key, so exporting a stored one would beat an environment ion token."""
    env_ion = {"CESIUM_ION_TOKEN": "eyJenv.token.value"}
    env_google = {"GOOGLE_MAPS_API_KEY": "AIza-env"}
    for stored in (FAKE_ION, "AIza-plain"):
        save_settings({"google_tiles_key": stored})
        assert render_env(env_ion) == env_ion
        assert render_env(env_google) == env_google


def test_tiles_credential_names_the_type_in_the_render_hosts_order(clean, monkeypatch):
    assert settings.tiles_credential() is None
    monkeypatch.setattr(settings, "compiled_ion_fallback", lambda: True)
    assert settings.tiles_credential() == "cesium_ion"
    assert settings.tiles_credential({"GOOGLE_MAPS_API_KEY": "AIza-env"}) == "google_key"
    assert settings.tiles_credential({"CESIUM_ION_TOKEN": FAKE_ION}) == "cesium_ion"
    monkeypatch.setattr(settings, "compiled_ion_fallback", lambda: False)
    save_settings({"google_tiles_key": FAKE_ION})
    assert settings.tiles_credential() == "cesium_ion"
    save_settings({"google_tiles_key": "AIza-plain"})
    assert settings.tiles_credential() == "google_key"
    assert settings.tiles_credential({"FLIGHTSIM_GOOGLE_TILES": "off"}) is None


def test_a_run_records_the_credential_type_never_the_value(clean, monkeypatch, caplog):
    save_settings({"google_tiles_key": FAKE_ION})
    run = RunState(run_id="abc123")
    record_env_override(run)
    assert run.as_dict()["tiles_credential"] == "cesium_ion"
    monkeypatch.setenv("CESIUM_ION_TOKEN", "eyJenv.token.value")
    record_env_override(run)
    assert run.as_dict()["tiles_credential"] == "cesium_ion"
    assert "CESIUM_ION_TOKEN=<set>" in run.events[-1]["detail"]
    text = json.dumps(run.as_dict()) + json.dumps(run.events) + caplog.text
    assert FAKE_ION not in text and "eyJenv.token.value" not in text
    monkeypatch.delenv("CESIUM_ION_TOKEN")
    save_settings({"google_tiles_key": "AIza-plain"})
    record_env_override(run)
    assert run.as_dict()["tiles_credential"] == "google_key"


def test_no_missing_tiles_warning_with_the_ion_token_in_the_environment(clean, monkeypatch):
    assert "google_tiles_key" in [m["key"] for m in missing_required()]
    monkeypatch.setenv("CESIUM_ION_TOKEN", FAKE_ION)
    assert "google_tiles_key" not in [m["key"] for m in missing_required()]
    assert google_tiles_requested() is True


def test_the_compiled_fallback_is_read_as_a_fact(tmp_path, monkeypatch):
    settings.compiled_ion_fallback.cache_clear()
    try:
        assert settings.compiled_ion_fallback() is True     # this repository's bridge source
        settings.compiled_ion_fallback.cache_clear()
        bare = tmp_path / "tiles.cpp"
        bare.write_text('FString IonToken = GetEnv(TEXT("CESIUM_ION_TOKEN"));\n', encoding="utf-8")
        monkeypatch.setattr(settings, "BRIDGE_TILES_SOURCE", bare)
        assert settings.compiled_ion_fallback() is False
        settings.compiled_ion_fallback.cache_clear()
        monkeypatch.setattr(settings, "BRIDGE_TILES_SOURCE", tmp_path / "gone.cpp")
        assert settings.compiled_ion_fallback() is False
    finally:
        settings.compiled_ion_fallback.cache_clear()


def test_llm_api_key_env_wins_then_file(clean, monkeypatch):
    assert llm_api_key() == ""
    save_settings({"llm_key": "sk-from-file"})
    assert llm_api_key() == "sk-from-file"
    assert effective("llm_key") == ("sk-from-file", "file")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    assert llm_api_key() == "sk-from-env"
    assert effective("llm_key") == ("sk-from-env", "env")
    assert llm_api_key({"ANTHROPIC_API_KEY": ""}) == "sk-from-file"
    # The compiler's presence checks read it (core/nl), not os.environ.
    from core.nl.llm_compiler import llm_available
    from core.nl.providers import resolve_client
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("FLIGHTSIM_LLM", raising=False)
    assert resolve_client() is None          # a stored key keeps the SDK path
    assert isinstance(llm_available(), bool)


def test_atomic_write(clean, monkeypatch):
    save_settings({"render_quality": "beauty"})
    before = clean.read_text(encoding="utf-8")
    assert json.loads(before) == {"render_quality": "beauty"}
    assert [p.name for p in clean.parent.iterdir()] == [clean.name]   # no tmp left behind

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(settings.os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        save_settings({"render_quality": "measure"})
    assert clean.read_text(encoding="utf-8") == before      # the old file stands
    assert [p.name for p in clean.parent.iterdir()] == [clean.name]
    monkeypatch.undo()
    monkeypatch.setattr(settings, "SETTINGS_PATH", clean)
    assert save_settings({"render_quality": "measure"}) == {"render_quality": "measure"}
    assert clean.read_text(encoding="utf-8").endswith("\n")
    assert settings.user_data_dir().name == "flightsim"
    assert Path(settings.settings_path()) == clean
