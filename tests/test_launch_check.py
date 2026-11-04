"""scripts/launch_check.py: the launcher's editor-free staleness oracle
(Phase 3 E6). Materials by the launcher-owned stamp, aircraft by A7's
importer functions, build by A4's binary_stale_reason."""
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "launch_check", REPO / "scripts" / "launch_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lc = _load()
ENGINE = "5.7"


def _fake_repo(tmp_path, script=b"# graph v1\n", materials=lc.EXPECTED_MATERIALS):
    (tmp_path / "scripts").mkdir()
    (tmp_path / lc.MATERIALS_SCRIPT_REL).write_bytes(script)
    folder = tmp_path / lc.MATERIALS_ASSET_DIR
    folder.mkdir(parents=True)
    for name in materials:
        (folder / f"{name}.uasset").write_bytes(b"\x00")
    return tmp_path


def test_materials_stale_without_stamp(tmp_path):
    repo = _fake_repo(tmp_path)
    reason = lc.check_materials(repo, ENGINE)
    assert reason is not None and "no stamp" in reason
    assert lc.main(["materials", "--repo", str(repo)]) == 1


def test_materials_stale_when_script_changes(tmp_path):
    repo = _fake_repo(tmp_path)
    lc.write_materials_stamp(repo, ENGINE)
    assert lc.check_materials(repo, ENGINE) is None
    (repo / lc.MATERIALS_SCRIPT_REL).write_bytes(b"# graph v2\n")
    reason = lc.check_materials(repo, ENGINE)
    assert reason is not None and "differs" in reason
    # a different engine with the same script is stale as well
    (repo / lc.MATERIALS_SCRIPT_REL).write_bytes(b"# graph v1\n")
    assert lc.check_materials(repo, ENGINE) is None
    assert lc.check_materials(repo, "5.8") is not None


def test_materials_stale_when_an_asset_is_missing(tmp_path):
    repo = _fake_repo(tmp_path)
    lc.write_materials_stamp(repo, ENGINE)
    (repo / lc.MATERIALS_ASSET_DIR / "M_Moon.uasset").unlink()
    reason = lc.check_materials(repo, ENGINE)
    assert reason == "missing M_Moon"


def test_materials_current_with_matching_stamp(tmp_path, capsys, monkeypatch):
    repo = _fake_repo(tmp_path)
    monkeypatch.setattr(lc, "_engine_version", lambda: ENGINE)
    assert lc.main(["materials", "--stamp", "--repo", str(repo)]) == 0
    stamp = json.loads((repo / lc.MATERIALS_STAMP_REL).read_text(encoding="utf-8"))
    assert stamp["fingerprint"] == lc.materials_fingerprint(repo, ENGINE)
    assert stamp["engine"] == ENGINE
    assert lc.main(["materials", "--repo", str(repo)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == ["materials stamp written", "materials up to date"]


def test_expected_materials_are_all_created_by_the_script():
    source = (REPO / lc.MATERIALS_SCRIPT_REL).read_text(encoding="utf-8")
    for name in lc.EXPECTED_MATERIALS:
        assert f'"{name}"' in source, f"{name} is not a material the script creates"
    assert "M_VertexColor" in lc.EXPECTED_MATERIALS
    assert "M_TerrainImagery" in lc.EXPECTED_MATERIALS


def test_aircraft_check_lists_only_stale_names(monkeypatch, capsys):
    from assets_pipeline import importer
    configs = {"c172p": Path("c172p.json"), "a320": Path("a320.json"),
               "old": Path("old.json"), "nolicence": Path("nolicence.json")}
    monkeypatch.setattr(importer, "configured_aircraft", lambda: configs)
    monkeypatch.setattr(importer, "unavailable_reason",
                        lambda n: "no license file" if n == "nolicence" else None)
    monkeypatch.setattr(importer, "is_imported", lambda n: n in ("c172p", "old"))
    monkeypatch.setattr(importer, "older_than_inputs_reason",
                        lambda n: "inputs newer" if n == "old" else None)
    assert lc.check_aircraft() == ["a320", "old"]
    assert lc.main(["aircraft"]) == 1
    assert capsys.readouterr().out.strip() == "aircraft stale (a320, old)"
    monkeypatch.setattr(importer, "is_imported", lambda n: True)
    monkeypatch.setattr(importer, "older_than_inputs_reason", lambda n: None)
    assert lc.main(["aircraft"]) == 0
    assert capsys.readouterr().out.strip() == "aircraft up to date"


def test_build_check_follows_binary_stale_reason(monkeypatch, capsys, tmp_path):
    import core.util.platform as platform
    seen = []
    monkeypatch.setattr(platform, "binary_stale_reason",
                        lambda repo: seen.append(repo) or "no stamp; source abc")
    assert lc.check_build(tmp_path) == "no stamp; source abc"
    assert seen == [tmp_path]
    assert lc.main(["build", "--repo", str(tmp_path)]) == 1
    assert capsys.readouterr().out.strip() == "build stale (no stamp; source abc)"
    monkeypatch.setattr(platform, "binary_stale_reason", lambda repo: None)
    assert lc.main(["build", "--repo", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "build up to date"


def test_unknown_step_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        lc.main(["bake"])
    assert exc.value.code == 2
