"""mask_vs_geometry / box_vs_mask grade the primary's silhouette against
its projected MESH VERTICES when the cited mesh manifest and its part
OBJs are on this machine, not against the projected extent box.

Measured on the owner's machine (UE 5.7.4, B747 chase camera, frame 0):
the rendered silhouette's tight box was 878x217 px inside a 1138x350 px
projected extent box -- the box's corners stand off the wing and tail
roots of an airliner seen obliquely, so a box-based 5 % extent gate
failed an exactly placed mesh.
"""

import hashlib
import json

import numpy as np

from core.capture import verify


def _write_mesh(root, vertices_cm, origin_cm=(0.0, 0.0, 0.0)):
    folder = root / "assets" / "generated" / "X"
    folder.mkdir(parents=True)
    (folder / "body.obj").write_text(
        "mtllib body.mtl\n" + "".join("v %.4f %.4f %.4f\n" % v for v in vertices_cm),
        encoding="utf-8")
    mesh = {"version": 3, "parts": ["body"],
            "mesh_origin_actor_cm": list(origin_cm)}
    path = folder / "mesh_manifest.json"
    path.write_text(json.dumps(mesh), encoding="utf-8")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"assets": {"mesh_manifest": {
        "path": "assets/generated/X/mesh_manifest.json", "sha256": sha}}}


def test_mesh_vertices_are_rebased_on_the_cg_in_body_axes(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "_REPO", tmp_path)
    verify._mesh_vertices_actor_m.cache_clear()
    manifest = _write_mesh(tmp_path, [(100.0, -200.0, 50.0), (-300.0, 400.0, -25.0)],
                           origin_cm=(10.0, 0.0, 0.0))
    # CG 1 inch aft of the datum: actor x = -0.0254 m.
    body, basis = verify._mesh_points_body(manifest, {"cg_structural_in": [1.0, 0.0, 0.0]})
    assert basis and "2 mesh vertices" in basis
    np.testing.assert_allclose(sorted(body.tolist()), sorted([
        [0.1 + 1.0 + 0.0254, -2.0, -0.5],
        [0.1 - 3.0 + 0.0254, 4.0, 0.25],
    ]), atol=1e-9)


def test_a_missing_part_or_digest_falls_back_to_the_box(tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "_REPO", tmp_path)
    verify._mesh_vertices_actor_m.cache_clear()
    manifest = _write_mesh(tmp_path, [(0.0, 0.0, 0.0)])
    airframe = {"cg_structural_in": [0.0, 0.0, 0.0]}
    wrong = {"assets": {"mesh_manifest": dict(manifest["assets"]["mesh_manifest"],
                                              sha256="00" * 32)}}
    assert verify._mesh_points_body(wrong, airframe) == (None, None)
    (tmp_path / "assets" / "generated" / "X" / "body.obj").unlink()
    verify._mesh_vertices_actor_m.cache_clear()
    assert verify._mesh_points_body(manifest, airframe) == (None, None)


def test_the_hull_is_the_projected_vertex_box_inside_the_corner_box():
    record = {"principal_point_px": [640.0, 360.0], "fx_px": 1000.0, "fy_px": 1000.0,
              "width_px": 1280, "height_px": 720}
    # A cross (fuselage along x, wing along y) 100 m in front: its corner
    # box projects wider and taller than the cross itself.
    points = np.array([[-30.0, 0.0, 100.0], [30.0, 0.0, 100.0],
                       [0.0, -10.0, 90.0], [0.0, 10.0, 110.0]])
    corners = [(x, y, z) for x in (-30.0, 30.0) for y in (-10.0, 10.0) for z in (90.0, 110.0)]
    with_points = verify._projected_hull(
        record, {"points": points, "corners": corners, "cg": (0.0, 0.0, 100.0)})
    box_only = verify._projected_hull(
        record, {"points": None, "corners": corners, "cg": (0.0, 0.0, 100.0)})
    u = 640.0 + 1000.0 * points[:, 0] / points[:, 2]
    v = 360.0 + 1000.0 * points[:, 1] / points[:, 2]
    assert with_points[0] == (u.min(), v.min(), u.max(), v.max())
    a, b = with_points[0], box_only[0]
    assert b[0] < a[0] and b[1] <= a[1] and b[2] > a[2] and b[3] > a[3]
    behind = verify._projected_hull(
        record, {"points": points - [0.0, 0.0, 95.0], "corners": corners, "cg": (0, 0, 1)})
    assert behind is None


def test_a_mesh_hull_allows_a_pixel_per_edge_and_a_box_half_of_one():
    """The tower frame that failed at 1.4 px on a 27 px vertex hull
    passes under the mesh floor; a box keeps the 1 px floor; above 40 px
    the 5 % fraction governs either way."""
    assert verify._extent_floor_px({"points": np.zeros((3, 3))}) == 2.0
    assert verify._extent_floor_px({"points": None}) == 1.0
    assert verify.MASK_EXTENT_TOL_FRACTION * 40 == verify.MASK_TOL_PX_MESH
