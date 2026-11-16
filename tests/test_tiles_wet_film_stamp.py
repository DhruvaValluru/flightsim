"""The tiles build stamps the film wet model apart ("12-film-wet"), so the staleness check
must expect that stamp under FLIGHTSIM_WET_GROUND=film: otherwise a film run over a
default-built asset (stamp "12") skips the rebuild, and the reverse rebuilds every run."""
import ast
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")


def _namespace(stamped):
    tree = ast.parse(SCRIPT)
    wanted = {"world_stale", "expected_world_stamp", "wet_ground_model"}
    consts = {"WORLD_GENERATIONS", "WORLD_GENERATION_TAG", "WET_GROUND_ENV", "WET_FILM_STAMP_SUFFIX"}
    lib = types.SimpleNamespace(does_asset_exist=lambda full: True, load_asset=lambda full: object(),
                                get_metadata_tag=lambda asset, tag: stamped)
    ns = {"unreal": types.SimpleNamespace(EditorAssetLibrary=lib), "PATH": "/Game/FlightSim"}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            exec(ast.get_source_segment(SCRIPT, node), ns)
        elif isinstance(node, ast.Assign) and any(getattr(t, "id", None) in consts for t in node.targets):
            exec(ast.get_source_segment(SCRIPT, node), ns)
    return ns


def test_each_mode_rebuilds_what_the_other_built(monkeypatch):
    gen = _namespace("x")["WORLD_GENERATIONS"]["M_FlightSimTilesBeauty"]
    default, film = gen, gen + "-film-wet"
    monkeypatch.delenv("FLIGHTSIM_WET_GROUND", raising=False)
    assert _namespace(film)["world_stale"]("M_FlightSimTilesBeauty")
    assert not _namespace(default)["world_stale"]("M_FlightSimTilesBeauty")
    monkeypatch.setenv("FLIGHTSIM_WET_GROUND", "film")
    assert _namespace(default)["world_stale"]("M_FlightSimTilesBeauty")
    assert not _namespace(film)["world_stale"]("M_FlightSimTilesBeauty")
    # other world assets never take the suffix
    ns = _namespace(_namespace("x")["WORLD_GENERATIONS"]["M_FlightSimOceanBeauty"])
    assert not ns["world_stale"]("M_FlightSimOceanBeauty")


def test_build_and_check_share_the_suffix():
    assert '(WET_FILM_STAMP_SUFFIX if wet_model > 0.5 else "")' in SCRIPT
    assert "return str(stamped) != expected_world_stamp(name)" in SCRIPT
