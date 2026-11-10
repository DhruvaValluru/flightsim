"""The labels' body frame is about the CG the renderer places the mesh by.

UE places the actor so JSBSim's RUNTIME CG (CGLocalPosition, the FDM's
loaded CG) sits on the flown point, and the telemetry the labels project
from is that point. The keypoints were taken about the XML's EMPTY CG,
so on the J-11 they sat 0.35 m forward of the drawn aircraft (A320 0.39 m
forward, 0.11 m up). These pin the labels to the loaded CG, checked
against JSBSim itself, and pin that the mesh placement (an actor-frame
point, CG-independent) does not move.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from assets_pipeline.convert import _body_to_actor_cm
from core.capture.airframe import (
    CONFIG_DIR, INCH_M, _read_fdm, load_airframe, structural_to_body,
)
from core.capture.labels import hull_box_body_m
from core.scenario.camera import _fdm_loaded_cg, _fdm_locations

AIRCRAFT = ("J11", "c172p", "B747", "A320")


def _jsbsim_runtime_cg_m(xml_path: str, model: str):
    jsbsim = pytest.importorskip("jsbsim")
    root = Path(xml_path).parents[2]
    fdm = jsbsim.FGFDMExec(str(root))
    fdm.set_debug_level(0)
    assert fdm.load_model(model)
    fdm.run_ic()
    return tuple(fdm[f"inertia/cg-{axis}-in"] * INCH_M for axis in "xyz")


@pytest.mark.parametrize("aircraft", AIRCRAFT)
def test_label_cg_is_jsbsims_runtime_cg(aircraft):
    airframe = load_airframe(aircraft)
    label_cg_m = tuple(v * INCH_M for v in airframe.cg_structural_in)
    assert label_cg_m == pytest.approx(_fdm_loaded_cg(aircraft), abs=1e-9)
    runtime = _jsbsim_runtime_cg_m(airframe.fdm_xml_path, aircraft)
    assert label_cg_m == pytest.approx(runtime, abs=1e-3)
    assert "default loading" in airframe.cg_source
    assert airframe.to_dict()["cg_source"] == airframe.cg_source


def test_j11_keypoints_moved_by_the_loaded_minus_empty_cg():
    """Every J-11 keypoint is 0.348 m further aft (and 3 mm lower) in the
    body frame than it was about the empty CG: the half-tank fuel."""
    airframe = load_airframe("J11")
    empty_in = tuple(v / INCH_M for v in _fdm_locations("J11")["CG"])
    shift = structural_to_body(empty_in, airframe.cg_structural_in)
    assert shift[0] == pytest.approx(-0.348, abs=0.002)
    assert shift[2] == pytest.approx(0.003, abs=0.001)


@pytest.mark.parametrize("aircraft", AIRCRAFT)
def test_mesh_origin_is_unchanged_by_the_cg_the_labels_use(aircraft):
    """The converter measures the mesh origin in the actor frame (the
    structural datum) from the nose and main-gear keypoints mapped back
    through the SAME CG, so the CG cancels: mesh_origin_actor_cm, and so
    the imported mesh, does not move (no re-import). The contact keypoints
    land on the FDM's own contacts in the actor frame."""
    airframe = load_airframe(aircraft)
    contacts = _read_fdm(Path(airframe.fdm_xml_path))["contacts"]
    config = json.loads((CONFIG_DIR / f"{aircraft}.json").read_text(encoding="utf-8"))
    for name, definition in config["labels"]["keypoints"].items():
        if "fdm_contact" not in definition:
            continue
        x, y, z = contacts[definition["fdm_contact"]][1]
        actor = _body_to_actor_cm(airframe.keypoints[name].body_m, airframe.cg_structural_in)
        assert actor == pytest.approx((-x * 2.54, y * 2.54, z * 2.54), abs=1e-4), name
    mesh = {"version": 3, "mesh_origin_actor_cm": [0.0, 0.0, 0.0],
            "mesh_extent_actor_m": {"x": [-1.0, 1.0], "y": [-1.0, 1.0], "z": [-1.0, 1.0]}}
    box, _ = hull_box_body_m(mesh, airframe)
    cx, _, cz = airframe.cg_structural_in
    assert box["forward"] == pytest.approx((-1.0 + cx * INCH_M, 1.0 + cx * INCH_M))
    assert box["down"] == pytest.approx((-(1.0 - cz * INCH_M), 1.0 + cz * INCH_M))
