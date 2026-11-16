"""Each world material builder must stamp and save the asset it built, never a
loop variable's last value (r142: create_world_cloud_layers saved
'/Game/FlightSim/WindOffsetM' because `for i, name in enumerate(...)` rebound
`name`, so M_FlightSimCloudLayersLit never reached disk)."""
import ast
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ue_create_materials.py"


def test_stamp_and_finish_never_use_a_rebound_loop_name():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    bad = []
    for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("create_world_")):
        loop_names = set()
        for node in ast.walk(fn):
            if isinstance(node, (ast.For, ast.comprehension)):
                for t in ast.walk(node.target):
                    if isinstance(t, ast.Name):
                        loop_names.add(t.id)
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("world_stamp", "finish") and len(node.args) > 1
                    and isinstance(node.args[1], ast.Name) and node.args[1].id in loop_names):
                bad.append(f"{fn.name}: {node.func.id}(..., {node.args[1].id})")
    assert not bad, bad
