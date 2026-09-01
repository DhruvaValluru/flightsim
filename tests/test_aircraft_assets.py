"""The aircraft fail-safe: models the system builds for itself.

Placeholder airframes never render (owner's rule 2026-08-14, extended
2026-08-31). Until 2026-09-01 the cost of that rule was paid by the
USER: a missing model refused the render and handed back a command to
run, once per machine, per airframe ("i cant run commands for every
single mesh they should upload by themselves").

The rule is unchanged. What changed is who does the work: the render
flow provisions a buildable model itself, exactly as it already
synthesises the control ridge. These tests pin the three things that
must remain true afterwards, because they are the ways automation could
quietly become a downgrade:

* what CANNOT be built still refuses, by name, before any editor time;
* what MUST NOT be built (no upstream license, VALIDITY 3.3) is never
  fetched -- automation is not a back door to unattributed geometry;
* a build that FAILS fails the run by name and never reaches a render,
  so the placeholder can never appear as a fallback.
"""

import json
import subprocess
from pathlib import Path

import pytest

from assets_pipeline import importer
from core.nl.compiler import compile_prompt
from webapp.runs import (RunManager, RunState, ensure_aircraft_model,
                         refuse_placeholder_mesh)
import webapp.runs as runs_module


class FakeSubprocess:
    """Stands in for the subprocess module inside the importer, so a test
    can prove a step was never reached rather than merely being slow."""

    CalledProcessError = subprocess.CalledProcessError

    def __init__(self, handler=None) -> None:
        self.calls = []
        self._handler = handler or (lambda cmd, **kw: _Completed(0))

    def run(self, cmd, **kwargs):
        self.calls.append([str(part) for part in cmd])
        return self._handler(cmd, **kwargs)


class _Completed:
    def __init__(self, code: int, out: str = "") -> None:
        self.returncode = code
        self.stdout = out


def write_manifest(tmp_path: Path, name: str = "TEST") -> Path:
    manifest = tmp_path / "assets" / "generated" / name / "mesh_manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        "name": name, "asset_path_root": f"/Game/Aircraft/{name}",
        "parts": ["fuselage", "wing"]}), encoding="utf-8")
    return manifest


def place_assets(tmp_path: Path, name: str = "TEST", parts=("fuselage",
                                                            "wing")) -> None:
    root = tmp_path / "ue" / "Content" / "Aircraft" / name
    root.mkdir(parents=True, exist_ok=True)
    for part in parts:
        (root / f"{part}.uasset").write_bytes(b"asset")


# -- what automation may not do -----------------------------------------


def test_an_unlicensable_airframe_is_never_fetched(monkeypatch):
    """VALIDITY 3.3, the load-bearing case: the p51d's upstream ships no
    license file, so it may never render -- and the fail-safe must
    refuse it BEFORE the fetch, not discover it at the converter. If
    automation reached upstream first, an unattributed model would be on
    disk whatever happened next."""
    fake = FakeSubprocess()
    monkeypatch.setattr(importer, "subprocess", fake)

    with pytest.raises(importer.AircraftAssetError) as caught:
        importer.ensure_model("p51d", report=lambda line: None)
    assert caught.value.constraint == "aircraft.mesh"
    assert "license" in caught.value.message
    assert fake.calls == []             # nothing was fetched, converted, run


def test_an_unconfigured_airframe_refuses_with_nothing_to_build(monkeypatch):
    """No config means nothing to fetch: the refusal stands, and names
    only airframes that can ACTUALLY be built (never the p51d, whose
    refusal no command can fix)."""
    monkeypatch.setattr(runs_module, "renderable_aircraft", lambda: [])
    spec = compile_prompt("fly the f15 at 5000 m and 350 kt")
    refusal = refuse_placeholder_mesh(spec)
    assert refusal is not None
    assert refusal["constraint"] == "aircraft.mesh"
    assert "f15" in refusal["message"]
    assert "B747" in refusal["message"]
    assert "p51d" not in refusal["message"]

    with pytest.raises(importer.AircraftAssetError) as caught:
        importer.ensure_model("f15", report=lambda line: None)
    assert caught.value.constraint == "aircraft.mesh"


def test_an_unlicensable_airframe_refuses_at_the_webapp_too(monkeypatch):
    """The same rule at the other door: the run endpoint's refusal for
    the p51d states the license reason, not an import command that would
    never help."""
    monkeypatch.setattr(runs_module, "renderable_aircraft", lambda: [])
    spec = compile_prompt("fly the 747 at 3000 m and 250 kt")
    spec.set("aircraft", "p51d", frm="test: an airframe with no license")
    refusal = refuse_placeholder_mesh(spec)
    assert refusal is not None
    assert refusal["constraint"] == "aircraft.mesh"
    assert "never render" in refusal["message"]
    assert "import_aircraft" not in refusal["message"]


# -- what automation now does -------------------------------------------


def test_a_buildable_airframe_is_no_longer_a_refusal(monkeypatch):
    """The change the user asked for: a configured, licensable airframe
    with no model on this machine does NOT refuse -- the run builds it."""
    monkeypatch.setattr(runs_module, "renderable_aircraft", lambda: [])
    for name in ("c172p", "B747", "A320", "DHC6"):
        spec = compile_prompt("fly the 747 at 3000 m and 250 kt")
        spec.set("aircraft", name, frm="test: a buildable airframe")
        assert refuse_placeholder_mesh(spec) is None, name


def test_the_fail_safe_builds_a_missing_model_once(monkeypatch):
    """Missing -> built, with progress reported; present -> untouched.
    Idempotence is what makes this safe to put on the render path."""
    built = []
    monkeypatch.setattr(importer, "ensure_model",
                        lambda name, report: built.append(name))

    spec = compile_prompt("fly the 747 at 3000 m and 250 kt")
    lines = []
    monkeypatch.setattr(importer, "is_imported", lambda name: False)
    ensure_aircraft_model(spec, lines.append)
    assert built == ["B747"]
    assert any("B747" in line for line in lines)

    monkeypatch.setattr(importer, "is_imported", lambda name: True)
    ensure_aircraft_model(spec, lines.append)
    assert built == ["B747"]            # already there: no second build


def test_a_failed_build_fails_the_run_by_name_and_never_renders(
        tmp_path, monkeypatch):
    """The rule this fail-safe serves, not one it relaxes: when the model
    cannot be built the run FAILS, named, and the flow stops there. It
    must never continue into a render that would draw placeholders."""
    monkeypatch.setattr(runs_module, "REPO", tmp_path)
    monkeypatch.setattr(runs_module, "ensure_control_ridge", lambda: None)

    def refuse(spec, report):
        raise importer.AircraftAssetError(
            "aircraft.mesh_import", "converting the B747 model failed")

    monkeypatch.setattr(runs_module, "ensure_aircraft_model", refuse)

    def never(spec):
        raise AssertionError("the flow continued past a failed model build")

    monkeypatch.setattr(runs_module, "pick_scene", never)

    run = RunState(run_id="deadbeef")
    manager = RunManager(out_root=tmp_path / "runs")
    spec = compile_prompt("fly the 747 at 3000 m and 250 kt")
    manager._render_flow(run, spec, provenance={})

    assert run.status == "failed"
    assert "aircraft.mesh_import" in run.detail
    assert "B747" in run.detail


# -- verification of the build itself ------------------------------------


def test_missing_assets_reads_the_manifest_parts(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "REPO", tmp_path)
    manifest = write_manifest(tmp_path)
    assert importer.missing_assets(manifest) == ["TEST/fuselage", "TEST/wing"]
    place_assets(tmp_path, parts=("fuselage",))
    assert importer.missing_assets(manifest) == ["TEST/wing"]
    place_assets(tmp_path)
    assert importer.missing_assets(manifest) == []


def test_the_import_verifies_assets_not_the_editor_exit_code(
        tmp_path, monkeypatch):
    """Measured 2026-09-01: a cosmetic texture warning made a completely
    successful four-aircraft import report failure, and an editor that
    logs nothing can still import nothing. Both directions are pinned --
    exit 0 with no assets FAILS, non-zero with every asset PASSES."""
    import core.util.platform as platform_module

    monkeypatch.setattr(importer, "REPO", tmp_path)
    editor = tmp_path / "UnrealEditor-Cmd"
    editor.write_bytes(b"#!/bin/sh\n")
    monkeypatch.setattr(platform_module, "ue_editor_path", lambda: editor)
    manifest = write_manifest(tmp_path)

    monkeypatch.setattr(importer, "subprocess",
                        FakeSubprocess(lambda cmd, **kw: _Completed(0)))
    with pytest.raises(importer.AircraftAssetError) as caught:
        importer.import_manifests([manifest], report=lambda line: None)
    assert caught.value.constraint == "aircraft.mesh_import"
    assert "TEST/fuselage" in caught.value.message

    place_assets(tmp_path)
    monkeypatch.setattr(importer, "subprocess",
                        FakeSubprocess(lambda cmd, **kw: _Completed(3)))
    lines = []
    importer.import_manifests([manifest], report=lines.append)
    assert any("exited 3" in line for line in lines)


def test_the_import_refuses_without_an_engine(tmp_path, monkeypatch):
    """No editor is a named refusal, not a crash mid-flow."""
    import core.util.platform as platform_module

    monkeypatch.setattr(importer, "REPO", tmp_path)
    monkeypatch.setattr(platform_module, "ue_editor_path", lambda: None)
    with pytest.raises(importer.AircraftAssetError) as caught:
        importer.import_manifests([write_manifest(tmp_path)],
                                  report=lambda line: None)
    assert caught.value.constraint == "aircraft.mesh_import"
