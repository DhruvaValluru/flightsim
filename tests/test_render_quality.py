"""Render quality presets (visual-fidelity plan V0): opt-in, recorded, and
the measured configuration unchanged when not opted in."""

import pytest

from core.nl.compiler import compile_prompt


def _command(tmp_path, monkeypatch):
    import webapp.runs as runs

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = list(command)

    monkeypatch.setattr(runs.subprocess, "run", fake_run)
    spec = compile_prompt("fly the 747 at 280 kt")
    runs.RunManager._render(tmp_path / "card.json", tmp_path / "frames",
                            {"key": "flat", "terrain": None, "imagery": None},
                            tmp_path / "missing_mesh.json", "B747",
                            camera_flags=runs.camera_render_flags(spec))
    return captured["command"]


def test_measure_adds_no_flag(tmp_path, monkeypatch):
    from experiments.showcase_matrix import HEIGHT, WIDTH

    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "measure")
    command = _command(tmp_path, monkeypatch)
    assert not any(arg.startswith("-quality=") for arg in command)
    assert f"-width={WIDTH}" in command and f"-height={HEIGHT}" in command


def test_beauty_is_the_default(tmp_path, monkeypatch):
    monkeypatch.delenv("FLIGHTSIM_RENDER_QUALITY", raising=False)
    default = _command(tmp_path, monkeypatch)
    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "beauty")
    assert _command(tmp_path, monkeypatch) == default


def test_beauty_is_1080p(tmp_path, monkeypatch):
    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "beauty")
    command = _command(tmp_path, monkeypatch)
    assert "-quality=beauty" in command
    assert "-width=1920" in command and "-height=1080" in command


def test_unknown_quality_refuses_by_name(tmp_path, monkeypatch):
    from webapp.runs import RunManager

    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "ultra")
    result = RunManager(out_root=tmp_path).start(
        compile_prompt("fly the 747 at 280 kt"), {})
    assert result["constraint"] == "render.quality"
    assert "ultra" in result["refused"]


def test_gate6_beauty_keeps_the_measured_resolution(monkeypatch, tmp_path):
    """Gate 6's pixel thresholds were set at 960x540; the beauty re-run
    must render there too, or a pass is a resolution change's luck."""
    import experiments.gate6_visual as gate6

    seen = []

    def fake_render(editor, project, card, frames, terrain, shot, extra):
        seen.append(list(extra))
        return False   # stop after the first render; flags are the point

    monkeypatch.setattr(gate6, "render", fake_render)
    monkeypatch.setattr(gate6, "ue_editor_path",
                        lambda: tmp_path / "editor")
    (tmp_path / "editor").write_text("", encoding="utf-8")
    code = gate6.main(["--out", str(tmp_path / "out"), "--quality", "beauty"])
    assert code == 2
    assert seen and {"-quality=beauty", "-width=960", "-height=540"} \
        <= set(seen[0])


@pytest.mark.parametrize("quality", ["measure", "beauty"])
def test_commandlet_parses_every_quality_the_python_side_sends(quality):
    """The C++ commandlet refuses unknown -quality values; the Python
    presets must stay inside what it accepts."""
    from pathlib import Path

    from webapp.runs import RENDER_QUALITIES

    source = (Path(__file__).resolve().parents[1] / "ue" / "Plugins" /
              "FlightSimBridge" / "Source" / "FlightSimBridge" / "Private" /
              "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
    assert quality in RENDER_QUALITIES
    assert f'TEXT("{quality}")' in source
