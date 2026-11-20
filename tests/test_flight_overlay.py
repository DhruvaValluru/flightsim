"""The 3-D box picture's physics readout (core/capture/flight_physics.py,
core/capture/flight_overlay.py) on the engine-bundle fixture: the forces
agree with the flight model's own numbers, the arrows sit where their
camera points project, the airflow shows downwash behind a lifting wing,
and the zip's JSON carries what the picture draws."""

from __future__ import annotations

import json
import math
import shutil
import zipfile
from pathlib import Path

import pytest

from core.capture.box3d import box3d_section, project
from core.capture.flight_overlay import (draw_flight_frame, draw_plain_frame, frame_sidecar,
                                         overlay_geometry)
from core.capture.flight_physics import G0, airflow_streamlines, frame_physics

BUNDLE = Path(__file__).parent / "fixtures" / "engine_bundle_min"


@pytest.fixture(scope="module")
def manifest():
    return json.loads((BUNDLE / "capture_manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def record(manifest):
    return manifest["frames"][0]


def _box(record):
    entry = record["labels"]["objects"][0]
    return entry.get("bbox_3d_camera_shape") or entry["bbox_3d_camera"]


def test_forces_agree_with_the_flight_model(manifest, record):
    p = frame_physics(manifest, record, _box(record))
    state = record["state"]
    f = p["forces"]
    assert f["lift"]["magnitude_n"] == pytest.approx(state["lift_n"], abs=0.01)
    assert f["drag"]["magnitude_n"] == pytest.approx(state["drag_n"], abs=0.01)
    assert f["thrust"]["magnitude_n"] == pytest.approx(state["engine0_thrust_n"], abs=0.01)
    assert f["weight"]["magnitude_n"] == pytest.approx(state["weight_kg"] * G0, abs=0.01)
    bal = p["force_balance"]
    # Lift/drag/side force rotated through alpha and beta rebuild the
    # model's own body-axis aerodynamic force, and the load factor
    # recomputed from the forces is the model's n_z.
    assert bal["aero_axes_check"]["max_component_error_n"] < 1.0
    assert bal["load_factor_nz_from_forces"] == pytest.approx(state["n_z"], abs=2e-3)
    # Air density from the dynamic pressure, ISA pressure at 2000 m.
    assert p["air"]["density_kg_m3"] == pytest.approx(1.0066, abs=1e-3)
    assert p["air"]["static_pressure_pa"] == pytest.approx(79495, rel=1e-3)


def test_lift_points_up_and_weight_down_in_the_picture(manifest, record):
    p = frame_physics(manifest, record, _box(record))
    lift = p["forces"]["lift"]["direction_camera"]
    weight = p["forces"]["weight"]["direction_camera"]
    assert lift[1] < -0.95                    # camera y is down
    assert weight[1] > 0.95
    assert sum(a * b for a, b in zip(lift, weight)) < -0.99


def test_arrows_are_their_camera_points_projected(manifest, record):
    geo = overlay_geometry(manifest, record)
    main = next(a for a in geo["aircraft"] if a["has_physics"])
    K = record["intrinsic_matrix"]
    names = [a["force"] for a in main["arrows"]]
    assert {"lift", "weight", "thrust", "drag", "velocity"} <= set(names)
    for arrow in main["arrows"]:
        px = project(K, arrow["to_camera_m"])
        assert arrow["to_px"] == pytest.approx(list(px), abs=0.05)
    # Lift and weight nearly balance, so their arrows are about as long.
    length = {a["force"]: a["length_m"] for a in main["arrows"]}
    assert length["lift"] == pytest.approx(length["weight"], rel=0.01)
    assert length["thrust"] < 0.5 * length["lift"]


def test_airflow_hugs_the_wing_faster_over_it_and_turned_down_behind(manifest, record):
    box = _box(record)
    p = frame_physics(manifest, record, box)
    flow = airflow_streamlines(p, box["extents_m"], (0.0, 0.0, 0.0), manifest["airframe"])
    assert flow is not None
    geo = flow["geometry"]
    assert geo["basis"]["wing"].startswith("wingtip keypoints")
    # The section incidence carries the frame's lift: a positive, small angle.
    assert 0.0 < flow["parameters"]["root_section_incidence_deg"] < 10.0
    wing = [ln for ln in flow["lines"] if ln["kind"] == "wing"]
    over = []
    for ln in wing:
        pts = ln["points_body_m"]
        start, end = pts[0], pts[-1]
        over.append(max(ln["speed_ratio"]))
        # Inboard of the tip vortices every wing line leaves lower (body z
        # larger) than it arrived: the downwash the lift implies. (Outboard
        # of them the air rises -- the upwash round the tips.)
        if abs(start[1]) < 0.6 * geo["span_m"] / 2:
            assert end[2] > start[2]
    assert max(over) > 1.05                    # the fast flow over the top
    again = airflow_streamlines(p, box["extents_m"], (0.0, 0.0, 0.0), manifest["airframe"])
    assert again["lines"][5]["points_body_m"] == flow["lines"][5]["points_body_m"]
    # Lines end a short way behind the tail, not far downstream.
    tail = geo["x_tail_m"]
    ref = max(box["extents_m"][0], box["extents_m"][1])
    assert all(ln["points_body_m"][-1][0] > tail - 0.15 * ref for ln in flow["lines"])


def test_the_picture_is_drawn_at_the_frame_size(manifest, record, tmp_path):
    from PIL import Image, ImageChops

    source = BUNDLE / "frames" / "chase" / "frame_0000.png"
    a = Image.open(source).convert("RGB")
    for draw in (draw_flight_frame, draw_plain_frame):
        target = draw(record, source, tmp_path / f"{draw.__name__}.png", manifest=manifest)
        b = Image.open(target).convert("RGB")
        assert a.size == b.size
        assert ImageChops.difference(a, b).getbbox() is not None


def test_the_zip_json_is_the_picture_in_numbers(tmp_path):
    from webapp.capture import box3d_archive

    run = tmp_path / "run"
    shutil.copytree(BUNDLE, run)
    archive = box3d_archive(run, "chase")
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        data = json.loads(zf.read("chase_3d/frame_0000_box3d.json"))
        readme = zf.read("chase_3d/README.txt").decode()
    assert "chase_3d/frame_0000_box3d.png" in names
    assert "chase_3d/frame_0000_box3d_detailed.png" in names
    for key in ("pictures", "panels", "flight_physics", "box_3d", "overlay", "camera"):
        assert key in data
    assert set(data["pictures"]) == {"plain", "detailed"}
    assert "arrows" not in data["overlay"]["plain"]["aircraft"][0]
    physics = data["flight_physics"]
    assert data["panels"]["forces"]["LIFT"] == (
        f"{physics['forces']['lift']['magnitude_kn']:,.2f} kN")
    main = data["overlay"]["detailed"]["aircraft"][0]
    assert main["airflow"]["lines"] and main["arrows"]
    assert data["box_3d"]["aircraft"][0]["rebuild_check"]["ok"]
    assert "LIFT" in readme and "flight_physics" in readme


def test_sidecar_without_state_still_carries_the_box(manifest, record):
    bare = {k: v for k, v in record.items() if k != "state"}
    data = frame_sidecar(manifest, bare, box3d_section(manifest, bare))
    assert data["flight_physics"] is None
    assert data["box_3d"]["aircraft"]
    assert math.isfinite(data["overlay"]["detailed"]["aircraft"][0]["range_m"])
