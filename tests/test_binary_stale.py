"""A stale engine binary is refused (A4): the build stamp vs the plugin source."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from core.util import platform as plat

FIXTURE = Path(__file__).parent / "fixtures" / "stamp_tree"
GOLDEN = "0141215eaa199cccb8b67a2acbdccecfcb70e4487506da5a93a326abcc05dc49"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    binary = plat.ue_bridge_binary(repo)          # a built bridge exists
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"")
    return repo


def _stamp(repo: Path, sha: str, engine: str = None) -> None:
    path = repo / plat.STAMP_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "stamp_version": 1,
        "engine_version": engine or f"{plat.UE_ENGINE_VERSION}.{plat.UE_ENGINE_PATCH}",
        "source_sha256": sha, "built_utc": "2026-01-01T00:00:00Z"}), encoding="utf-8")


def test_binary_stale_golden_fixture_hash():
    assert plat.plugin_source_hash(FIXTURE) == GOLDEN


def test_binary_stale_matching_passes(tmp_path):
    repo = _repo(tmp_path)
    _stamp(repo, plat.plugin_source_hash(repo))
    assert plat.binary_stale_reason(repo) is None


def test_binary_stale_wrong_hash_refuses(tmp_path):
    repo = _repo(tmp_path)
    _stamp(repo, "0" * 64)
    assert plat.binary_stale_reason(repo) is not None


def test_binary_stale_missing_stamp_refuses(tmp_path):
    repo = _repo(tmp_path)
    reason = plat.binary_stale_reason(repo)
    assert reason and "no build stamp" in reason


def test_binary_stale_crlf_independent(tmp_path):
    repo = _repo(tmp_path)
    before = plat.plugin_source_hash(repo)
    a = repo / plat.PLUGIN_SOURCE_REL / "A.cpp"
    a.write_bytes(a.read_bytes().replace(b"\n", b"\r\n"))
    assert plat.plugin_source_hash(repo) == before
    a.write_bytes(b"int a = 2;\n")
    assert plat.plugin_source_hash(repo) != before


def test_binary_stale_engine_minor_mismatch(tmp_path):
    repo = _repo(tmp_path)
    _stamp(repo, plat.plugin_source_hash(repo), engine="4.27.2")
    reason = plat.binary_stale_reason(repo)
    assert reason and "4.27.2" in reason
    # a different patch of the pinned major.minor is fine
    _stamp(repo, plat.plugin_source_hash(repo),
           engine=f"{plat.UE_ENGINE_VERSION}.99")
    assert plat.binary_stale_reason(repo) is None


def test_binary_stale_message_names_both_hashes(tmp_path):
    repo = _repo(tmp_path)
    _stamp(repo, "ab" * 32)
    reason = plat.binary_stale_reason(repo)
    assert "ab" * 32 in reason and plat.plugin_source_hash(repo) in reason


def test_binary_stale_no_built_binary_is_not_this_refusal(tmp_path):
    repo = _repo(tmp_path)
    plat.ue_bridge_binary(repo).unlink()
    assert plat.binary_stale_reason(repo) is None


def test_binary_stale_capture_render_refuses_by_name(tmp_path, capsys, monkeypatch):
    """The real check, through flightsim.capture: a built bridge with no
    stamp refuses before any flight; headless (no --render) is untouched."""
    from flightsim.capture import main as capture_main

    built = tmp_path / "bridge.dylib"
    built.write_bytes(b"")
    import assets_pipeline.importer as importer_module

    monkeypatch.setattr(importer_module, "is_imported", lambda name: True)
    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(plat, "ue_bridge_binary", lambda repo: built)
    example = Path(__file__).resolve().parents[1] / "examples" / "cameras_multi.yaml"
    out = tmp_path / "refused"
    code = capture_main([str(example), "--out", str(out), "--max-previews", "0",
                         "--render", "--no-host-flight"])
    assert code == 2
    text = capsys.readouterr().out
    assert "REFUSED -- by name:" in text and "no build stamp" in text
    assert plat.plugin_source_hash(
        Path(__file__).resolve().parents[1]) in text
    assert not (out / "capture_manifest.json").exists()
