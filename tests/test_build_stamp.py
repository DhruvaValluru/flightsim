"""Phase 3 A3 and A4: the wrong engine and an outdated engine binary are
refused by name (tasks/phase3_todo.md; the review's R1 and R4).

Container half. The Windows half of each check (UE_ROOT at another
version stops the build; touching a .cpp without rebuilding stops the
next render) is run on the render machines and recorded in
docs/PHASE3_LOG.md."""

import json
import re
import sys
from pathlib import Path

import pytest

import core.util.build_stamp as bs
import core.util.platform as plat

REPO = Path(__file__).resolve().parents[1]


def _engine(root: Path, version: str = plat.UE_ENGINE_PATCH,
            changelist: str = "12345") -> Path:
    major, minor, patch = version.split(".")
    path = root / "Engine" / "Build" / "Build.version"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "MajorVersion": int(major), "MinorVersion": int(minor),
        "PatchVersion": int(patch), "Changelist": int(changelist),
        "BranchName": "++UE5+Release-" + major + "." + minor}),
        encoding="utf-8")
    return root


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for rel, text in (
            ("ue/Source/FlightSim/FlightSim.cpp", "int a = 1;\n"),
            ("ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/"
             "FlightSimRenderCommandlet.cpp", "int main() { return 0; }\n"),
            ("ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public/"
             "Bridge.h", "#pragma once\n"),
            ("ue/FlightSim.uproject", '{"EngineAssociation": "5.7"}\n')):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return repo


# --- A4: the source hash ---------------------------------------------------

def test_source_hash_is_stable_and_follows_every_compiled_file(tmp_path):
    repo = _repo(tmp_path)
    first = bs.source_hash(repo)
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert bs.source_hash(repo) == first

    cpp = (repo / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/"
                  "Private/FlightSimRenderCommandlet.cpp")
    cpp.write_text("int main() { return 1; }\n", encoding="utf-8")
    assert bs.source_hash(repo) != first

    cpp.write_text("int main() { return 0; }\n", encoding="utf-8")
    assert bs.source_hash(repo) == first
    # A new header counts, and so does the project file.
    (repo / "ue/Source/FlightSim/New.h").write_text("//\n", encoding="utf-8")
    assert bs.source_hash(repo) != first


def test_source_hash_ignores_line_endings_and_non_source_files(tmp_path):
    """git's autocrlf rewrites line endings on a Windows checkout; the
    compiler sees the same code, so the hash must not move. Built
    binaries and notes beside the source do not count either."""
    repo = _repo(tmp_path)
    first = bs.source_hash(repo)
    cpp = repo / "ue/Source/FlightSim/FlightSim.cpp"
    cpp.write_bytes(cpp.read_bytes().replace(b"\n", b"\r\n"))
    assert bs.source_hash(repo) == first
    (repo / "ue/Source/FlightSim/notes.txt").write_text("x", encoding="utf-8")
    (repo / "ue/Source/FlightSim/lib.dll").write_bytes(b"\0\1")
    assert bs.source_hash(repo) == first


def test_the_real_tree_hashes_every_bridge_translation_unit():
    files = {p.relative_to(REPO).as_posix() for p in bs._source_files(REPO)}
    assert ("ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/"
            "FlightSimRenderCommandlet.cpp") in files
    assert "ue/FlightSim.uproject" in files
    assert any(f.endswith(".Target.cs") for f in files)


# --- A4: the stamp and binary_stale ------------------------------------------

def test_binary_stale_without_a_stamp(tmp_path):
    repo = _repo(tmp_path)
    refusal = bs.stale_refusal(repo, _engine(tmp_path / "UE"))
    assert refusal["constraint"] == "engine.binary_stale"
    assert refusal["message"].startswith("engine.binary_stale: no build stamp")


def test_a_matching_stamp_passes_and_a_wrong_hash_refuses_naming_both(tmp_path):
    repo = _repo(tmp_path)
    ue = _engine(tmp_path / "UE")
    stamp = bs.write_stamp(repo, ue)
    assert stamp["engine_version"] == plat.UE_ENGINE_PATCH
    assert stamp["engine_changelist"] == "12345"
    assert bs.stamp_path(repo).is_file()
    assert bs.stale_refusal(repo, ue) is None
    assert bs.render_refusal(repo, ue) is None

    # A synthetic stamp with a wrong hash refuses, naming both hashes.
    data = json.loads(bs.stamp_path(repo).read_text(encoding="utf-8"))
    data["source_sha256"] = "0" * 64
    bs.stamp_path(repo).write_text(json.dumps(data), encoding="utf-8")
    refusal = bs.stale_refusal(repo, ue)
    assert refusal["constraint"] == "engine.binary_stale"
    assert "000000000000" in refusal["message"]
    assert bs.source_hash(repo)[:12] in refusal["message"]


def test_touching_a_cpp_without_rebuilding_refuses_the_next_render(tmp_path):
    """The container twin of the Windows check: edit one .cpp after the
    build, and the next render refuses binary_stale."""
    repo = _repo(tmp_path)
    ue = _engine(tmp_path / "UE")
    bs.write_stamp(repo, ue)
    cpp = repo / "ue/Source/FlightSim/FlightSim.cpp"
    cpp.write_text("int a = 2;\n", encoding="utf-8")
    refusal = bs.render_refusal(repo, ue)
    assert refusal["constraint"] == "engine.binary_stale"


def test_a_stamp_from_another_engine_is_stale(tmp_path):
    repo = _repo(tmp_path)
    bs.write_stamp(repo, _engine(tmp_path / "UE"))
    data = json.loads(bs.stamp_path(repo).read_text(encoding="utf-8"))
    data["engine_version"] = "5.7.1"
    bs.stamp_path(repo).write_text(json.dumps(data), encoding="utf-8")
    refusal = bs.stale_refusal(repo, tmp_path / "UE")
    assert refusal["constraint"] == "engine.binary_stale"
    assert "5.7.1" in refusal["message"]


# --- A3: the wrong engine ----------------------------------------------------

@pytest.mark.parametrize("version", ["5.5.4", "5.7.3", "5.8.0"])
def test_another_engine_is_refused_by_name(tmp_path, version):
    repo = _repo(tmp_path)
    ue = _engine(tmp_path / "UE", version)
    refusal = bs.render_refusal(repo, ue)
    assert refusal["constraint"] == "engine.version_mismatch"
    assert refusal["message"].startswith(
        f"engine.version_mismatch: found {version}, pinned "
        f"{plat.UE_ENGINE_PATCH}")
    with pytest.raises(ValueError, match="engine.version_mismatch"):
        bs.write_stamp(repo, ue)
    assert not bs.stamp_path(repo).exists()


def test_no_engine_at_all_is_a_version_mismatch_naming_the_path(tmp_path):
    refusal = bs.version_refusal(tmp_path / "nowhere")
    assert refusal["constraint"] == "engine.version_mismatch"
    assert "no readable Engine/Build/Build.version" in refusal["message"]
    assert str(tmp_path / "nowhere") in refusal["message"]


def test_cli_check_and_write(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    ue = _engine(tmp_path / "UE")
    monkeypatch.setattr(bs, "REPO", repo)
    assert bs.main(["check", "--ue-root", str(ue)]) == 2
    assert "REFUSED -- engine.binary_stale" in capsys.readouterr().out
    assert bs.main(["write", "--ue-root", str(ue)]) == 0
    assert bs.main(["check", "--ue-root", str(ue)]) == 0
    assert "OK build stamp current" in capsys.readouterr().out
    wrong = _engine(tmp_path / "UE55", "5.5.4")
    assert bs.main(["write", "--ue-root", str(wrong)]) == 2
    assert "engine.version_mismatch" in capsys.readouterr().out


def test_windows_resolves_only_ue_root_or_the_pinned_path(monkeypatch):
    """A3: no scan for "the newest UE_5.*" -- the pinned path or UE_ROOT."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("UE_ROOT", raising=False)
    assert plat.find_ue_root() == Path(
        rf"C:\Program Files\Epic Games\UE_{plat.UE_ENGINE_VERSION}")
    source = (REPO / "core" / "util" / "platform.py").read_text(encoding="utf-8")
    assert 'glob("UE_5' not in source


# --- A3: the build and preflight scripts (source-reading) ----------------

def _ps1(name: str) -> str:
    return (REPO / "scripts" / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["build_ue.ps1", "ue_preflight.ps1"])
def test_scripts_no_longer_fall_back_to_another_engine(name):
    text = _ps1(name)
    assert '-Filter "UE_5.*"' not in text, name
    pinned = re.findall(r'^\$pinned = "([0-9.]+)"', text, re.M)
    assert pinned == [plat.UE_ENGINE_PATCH], (
        f"scripts/{name} pins {pinned}, platform.py {plat.UE_ENGINE_PATCH}")
    assert "engine.version_mismatch: found $" in text, name


def test_build_refuses_before_build_bat_and_stamps_after_it():
    text = _ps1("build_ue.ps1")
    refuse = text.index("engine.version_mismatch")
    build = text.index("& $buildBat")
    stamp = text.index("core.util.build_stamp write")
    assert refuse < build < stamp
    assert "exit 2" in text[refuse:build]


def test_the_web_app_refuses_a_stale_binary_by_name(monkeypatch):
    """The web app on a machine WITH the engine refuses a stale binary by
    name, before any flight, never a 500."""
    from fastapi.testclient import TestClient

    from core.nl.compiler import compile_prompt
    import webapp.runs as runs_module
    import webapp.server as server_module
    from webapp.server import app

    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(runs_module, "pick_scene",
                        lambda spec: {"key": "flat", "kind": "flat",
                                      "terrain": None, "imagery": None,
                                      "label": "flat (test)"})
    monkeypatch.setattr(server_module, "refuse_placeholder_mesh",
                        lambda spec: None)
    monkeypatch.setattr(bs, "render_refusal", lambda *a, **k: {
        "constraint": "engine.binary_stale",
        "message": "engine.binary_stale: built from aaaa, source is bbbb"})
    spec = compile_prompt("fly the 747 at 3000 m and 250 kt")
    reply = TestClient(app).post("/run", json={"spec": spec.to_dict()})
    assert reply.status_code == 409, reply.text
    body = reply.json()
    assert body.get("constraint") == "engine.binary_stale"
    assert "built from aaaa" in body["refused"]
