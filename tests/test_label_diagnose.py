"""scripts/label_diagnose.py prints the tight-box counts per camera."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "label_diagnose.py"


def _module():
    spec = importlib.util.spec_from_file_location("label_diagnose", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(tmp_path, tights):
    camera = tmp_path / "frames" / "cam0"
    camera.mkdir(parents=True)
    Image.fromarray(np.zeros((4, 4), dtype=np.uint8)).save(camera / "frame_0000_mask.png")
    (camera / "render.json").write_text(json.dumps(
        {"objects": [{"int_id": 1}], "render_settings": {"rhi": "dx12"}}), encoding="utf-8")
    frames = [{"camera_id": "cam0", "labels": {"objects": [
        {"int_id": 1, "bbox_2d_tight": t}]}} for t in tights]
    (tmp_path / "capture_manifest.json").write_text(json.dumps({"frames": frames}), encoding="utf-8")
    return tmp_path


def test_diagnose_prints_tight_null_and_filled(tmp_path, capsys):
    module = _module()
    run = _run(tmp_path, [[1.0, 1.0, 3.0, 3.0], [0.0, 0.0, 2.0, 2.0]])
    assert module.main([str(run)]) == 0
    assert "tight null: 0, tight filled: 2" in capsys.readouterr().out


def test_diagnose_counts_a_null_tight_box(tmp_path, capsys):
    module = _module()
    run = _run(tmp_path, [[1.0, 1.0, 3.0, 3.0], None])
    assert module.main([str(run)]) == 0
    assert "tight null: 1, tight filled: 1" in capsys.readouterr().out


def test_tight_counts_reads_render_frame_records():
    module = _module()
    render = {"frames": 2, "frame_records": [
        {"labels": {"objects": [{"bbox_2d_tight": None}]}},
        {"labels": {"objects": [{"bbox_2d_tight": [0, 0, 1, 1]}]}}]}
    assert module.tight_counts(render) == (1, 1)
