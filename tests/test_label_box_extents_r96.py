"""Round 83's label failures, fixed at the source (2026-11-14).

#10 / #08: the C172's box came from its NOSE_SKID and TAIL_SKID contacts, 5.7 m
long against the type's 8.28 m; the tail keypoint is now the drawn rudder tip,
measured from the converted mesh (the render machine's manifest agrees: tail
-608.519 cm about an origin at -118.309 cm). #13: the B747's box stood the cited
19.41 m up from the extended gear contact; the drawn fin is 19.98 m up, so the
measured fin top bounds the box. #12: a cockpit camera sits inside its own hull;
mask_vs_geometry says so by name instead of failing, and a keypoint behind the
lens no longer bounds the nearest surface."""

from core.capture.airframe import load_airframe
from core.capture import verify


def test_c172_box_is_the_drawn_length():
    f = load_airframe("c172p")
    aft, fwd = f.box_body_m()["forward"]
    assert abs((fwd - aft) - 8.226) < 0.01          # the converted mesh, 8.22586 m
    assert abs((fwd - aft) - f.length_m) < 0.1      # the type's cited 8.28 m
    assert f.keypoints["tail"].body_m[0] < -6.0 and "measured" in f.keypoints["tail"].source


def test_b747_box_reaches_the_drawn_fin():
    f = load_airframe("B747")
    top, bottom = f.box_body_m()["down"]
    assert abs((bottom - top) - 19.98) < 0.02
    assert f.measured_top_body_m == top and "mesh_manifest" in f.measured_top_source
    # An aircraft with no measured top keeps the cited height exactly.
    c = load_airframe("c172p")
    ctop, cbottom = c.box_body_m()["down"]
    assert c.measured_top_body_m is None and abs((cbottom - ctop) - c.height_m) < 1e-9


def _geometry(centre):
    axes = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    return {"centre": centre, "axes": axes, "half": (4.0, 5.0, 1.5)}


def test_camera_inside_hull_is_a_cockpit_view_only():
    assert verify._camera_inside_hull(_geometry((0.5, 0.2, 1.0)))       # inside
    assert not verify._camera_inside_hull(_geometry((0.0, 0.0, 30.0)))  # chase, 30 m ahead
    assert not verify._camera_inside_hull(_geometry((4.5, 0.0, 0.0)))   # just outside x
    assert not verify._camera_inside_hull({"centre": None, "axes": None, "half": None})


def test_mask_and_depth_checks_name_the_cockpit_case():
    src = open(verify.__file__, encoding="utf-8").read()
    assert "if hull is None and _camera_inside_hull(geometry):" in src
    assert "the camera is inside this aircraft's hull (a cockpit view)" in src
    assert 'ahead = {k: v for k, v in geometry["keypoints"].items() if float(v[2]) > 0.0}' in src
