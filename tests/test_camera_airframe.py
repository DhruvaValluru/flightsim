"""The preview draws the airframe the ENGINE imports, when it can.

The engine-less preview used to draw a hand-written polygon airliner:
a shape nobody flies, sized by eye. The aircraft Unreal renders comes
from the FlightGear AC3D parts listed in
``assets/aircraft_config/<name>.json``, and this repo already reads
them (``assets_pipeline.acmodel``) to build the engine's meshes. So the
preview reads the same files, and the silhouette in a preview is the
silhouette in a render.

``assets/aircraft_src/`` is gitignored -- it exists only after
``assets_pipeline/convert.py`` has fetched the sources -- so these tests
build a tiny AC3D model of their own rather than depending on a machine
having run the pipeline. What they pin is the contract: real sources are
used when present, the parametric stand-in is used when absent, and the
caller can always tell which it got.
"""

import json

import pytest

from core.capture import aircraft_mesh
from core.capture.aircraft_model import AIRFRAMES, body_faces, dimensions

AC_SOURCE = """AC3Db
MATERIAL "white" rgb 0.8 0.82 0.85  amb 0.2 0.2 0.2  emis 0 0 0 \
spec 0 0 0  shi 0  trans 0
MATERIAL "glass" rgb 0.5 0.6 0.9  amb 0.2 0.2 0.2  emis 0 0 0 \
spec 0 0 0  shi 0  trans 0.95
OBJECT world
kids 1
OBJECT poly
name "wing"
numvert 4
0 0 0
10 0 0
10 0 4
0 0 4
numsurf 2
SURF 0x0
mat 0
refs 4
0 0 0
1 1 0
2 1 1
3 0 1
SURF 0x0
mat 1
refs 3
0 0 0
1 1 0
2 1 1
kids 0
"""


@pytest.fixture
def fake_airframe(tmp_path, monkeypatch):
    """An airframe whose source mesh is on disk."""
    config_dir = tmp_path / "aircraft_config"
    source_dir = tmp_path / "aircraft_src" / "toy"
    (source_dir / "Models").mkdir(parents=True)
    config_dir.mkdir()
    (source_dir / "Models" / "toy.ac").write_text(AC_SOURCE, encoding="utf-8")
    (config_dir / "TOY.json").write_text(json.dumps({
        "name": "TOY",
        "source_dir": "../aircraft_src/toy",
        "parts": [{"file": "Models/toy.ac", "offset_m": [1.0, 0.0, 0.0]}],
    }), encoding="utf-8")
    monkeypatch.setattr(aircraft_mesh, "CONFIG_DIR", config_dir)
    return "TOY"


def test_the_real_source_mesh_is_used_when_present(fake_airframe):
    assert aircraft_mesh.available(fake_airframe)
    triangles = aircraft_mesh.load_triangles(fake_airframe)
    assert triangles, "no triangles read from the source mesh"
    for vertices, rgb in triangles:
        assert len(vertices) == 3
        assert all(len(v) == 3 for v in vertices)
        assert len(rgb) == 3 and all(0 <= c <= 255 for c in rgb)


def test_transparent_surfaces_are_skipped_as_the_engine_skips_them(
        fake_airframe):
    """The .ac files carry glass shells at transparency >= 0.9;
    assets_pipeline/convert.py drops them for the engine, so a preview
    that kept them would draw a silhouette the render does not have."""
    triangles = aircraft_mesh.load_triangles(fake_airframe)
    # The quad contributes two triangles, the glass surface one. Only
    # the opaque quad survives.
    assert len(triangles) == 2


def test_a_missing_source_mesh_is_reported_not_guessed():
    """assets/aircraft_src/ is gitignored, so on a fresh clone there is
    no real mesh. That must be a None the caller can fall back on, never
    a partial model or an exception."""
    assert aircraft_mesh.load_triangles("NoSuchAirframe") is None


def test_a_partial_source_directory_is_refused(tmp_path, monkeypatch):
    """One missing part is not a model: drawing the remaining parts
    would show an aircraft with, say, no wings, and call it real."""
    config_dir = tmp_path / "aircraft_config"
    config_dir.mkdir()
    (config_dir / "GAP.json").write_text(json.dumps({
        "name": "GAP",
        "source_dir": "../aircraft_src/gap",
        "parts": [{"file": "Models/present.ac"}, {"file": "Models/absent.ac"}],
    }), encoding="utf-8")
    source = tmp_path / "aircraft_src" / "gap" / "Models"
    source.mkdir(parents=True)
    (source / "present.ac").write_text(AC_SOURCE, encoding="utf-8")
    monkeypatch.setattr(aircraft_mesh, "CONFIG_DIR", config_dir)
    assert aircraft_mesh.load_triangles("GAP") is None


def test_the_preview_says_which_airframe_it_drew():
    """A viewer must be able to tell 'that is the real 747' from 'that
    is a stand-in', so the source is reported, not implied."""
    from core.capture.preview import airframe_geometry

    faces, source = airframe_geometry("B747")
    assert faces
    assert source in ("source mesh", "parametric stand-in")


def test_the_stand_in_is_the_real_size_of_the_airframe():
    """The fallback is a stand-in for the SHAPE, never for the scale: a
    preview whose aircraft is the wrong size misjudges every camera
    framing decision made from it."""
    for name, spec in AIRFRAMES.items():
        faces = body_faces(name)
        xs = [v[0] for quad, _ in faces for v in quad]
        ys = [v[1] for quad, _ in faces for v in quad]
        length = max(xs) - min(xs)
        span = max(ys) - min(ys)
        assert length == pytest.approx(spec["length_m"], rel=0.12), name
        assert span == pytest.approx(spec["span_m"], rel=0.12), name


def test_a_cessna_is_not_a_747():
    """The regression this guards: one silhouette scaled by eye."""
    assert dimensions("c172p")["span_m"] < dimensions("B747")["span_m"] / 4
