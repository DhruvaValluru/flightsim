"""Host side of the look-dev harness: the exact inputs a test scene's beauty
render would get, without rendering.

For a test scene id (scripts/run_test_scenarios.py numbering) this compiles
the scene's prompt through the web app's own /compile handler (in process),
applies the scene's lighting edits the way the batch does, then runs the web
app's own render flow (RunManager._render_flow) with the commandlet launch
replaced by a recorder. What the commandlet would have been given -- the run
card, sky.json, the beauty-look and hero-lighting sidecars and the ordered
argument list -- lands in <out>/<scene>/ with lookdev.json naming them.
Nothing is rendered and no engine process is started.

    .venv/bin/python scripts/lookdev/prepare.py 1 3 7 --out <dir> [--switches "..."]
"""
import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

SCENES = (1, 3, 7, 9, 10, 13, 15)


class _Recorded(Exception):
    """Raised by the recorder to stop the flow once the command is known."""


def _scenario(number: int):
    from run_test_scenarios import SCENARIOS
    name, prompt, edits = SCENARIOS[number - 1]
    return name, prompt, edits


def compile_spec(prompt: str, compiler: str, clip_seconds: float) -> dict:
    """The web app's /compile handler, in process (same planners, same
    clip-length edit as scripts/run_test_scenarios.py)."""
    from fastapi.testclient import TestClient
    from webapp.server import app
    client = TestClient(app)
    reply = client.post("/compile", json={"prompt": prompt, "compiler": compiler,
                                          "clip_seconds": clip_seconds})
    payload = reply.json()
    if reply.status_code != 200 or "spec" not in payload:
        raise SystemExit(f"compile refused: {json.dumps(payload)[:400]}")
    if not payload["validation"]["ok"]:
        raise SystemExit(f"spec invalid: {json.dumps(payload['validation'])[:400]}")
    return payload["spec"]["dict"]


def provision(spec) -> None:
    """What POST /run does to the spec before starting the run
    (webapp.server provision_flight), baking the place on a terrain.unbaked
    refusal the way scripts/run_test_scenarios.py does (POST /bake)."""
    from webapp.runs import PREFETCH, bake_on_demand, provision_flight
    provisioned = provision_flight(spec)
    if provisioned["refusal"] is not None:
        refusal = provisioned["refusal"]
        print(f"  baking terrain at {refusal['latitude']:.3f}, {refusal['longitude']:.3f}")
        PREFETCH.bake(refusal["latitude"], refusal["longitude"], bake_on_demand)
        provisioned = provision_flight(spec)
    for key in ("refusal", "weather_refusal"):
        if provisioned.get(key) is not None:
            raise SystemExit(f"/run would refuse: {json.dumps(provisioned[key])[:300]}")
    if provisioned.get("violations"):
        raise SystemExit(f"/run would refuse: {json.dumps(provisioned['violations'])[:300]}")


def prepare(number: int, out_root: Path, compiler: str, switches: str,
            clip_seconds: float, spec_dir) -> Path:
    from run_test_scenarios import apply_lighting
    from core.scenario.spec import ScenarioSpec
    import core.render.headless as headless
    from webapp import runs as webruns

    name, prompt, edits = _scenario(number)
    pinned = Path(spec_dir) / f"{number:02d}.json" if spec_dir else None
    if pinned is not None and pinned.is_file():
        spec_dict = json.loads(pinned.read_text(encoding="utf-8"))["spec"]
        compiler = f"pinned:{pinned}"
    else:
        spec_dict = compile_spec(prompt, compiler, clip_seconds)
    spec_dict = json.loads(json.dumps(spec_dict))
    apply_lighting(spec_dict, edits)
    spec = ScenarioSpec.from_dict(spec_dict)
    provision(spec)

    os.environ.setdefault("FLIGHTSIM_RENDER_QUALITY", "beauty")
    os.environ["FLIGHTSIM_RENDER_SWITCHES"] = switches
    recorded = {}

    def recorder(command, log, watch=()):
        if not any("FlightSimRender" in str(t) for t in command):
            raise SystemExit(f"scene {number}: an engine run other than the render "
                             f"was asked for: {[str(t) for t in command][:3]}")
        recorded["command"] = [str(token) for token in command]
        raise _Recorded()

    # The aircraft import is an editor run; here it is only recorded and the
    # look-dev build imports in the running editor (scripts/ue_import_aircraft.py).
    import assets_pipeline.importer as importer
    to_import = []
    original_import = importer.import_manifests
    importer.import_manifests = lambda manifests, report=print: to_import.extend(
        str(Path(m).resolve()) for m in manifests)
    # No engine process here: the host pre-flight (a FlightSimScenario
    # commandlet) is skipped as on an engine-less machine, so the camera
    # poses are solved over the Python flight instead of the host's.
    import core.util.platform as platform
    original_available = platform.ue_available
    platform.ue_available = lambda *a, **k: False
    original = headless.run_headless
    headless.run_headless = recorder
    try:
        manager = webruns.RunManager(out_root=out_root / f"{number:02d}_runs")
        run = webruns.RunState(run_id=f"lookdev{number:02d}", spec_digest=spec.digest())
        try:
            manager._render_flow(run, spec, {"compiler": compiler})
        except _Recorded:
            pass
    finally:
        headless.run_headless = original
        importer.import_manifests = original_import
        platform.ue_available = original_available
    if "command" not in recorded:
        events = [str(e)[:300] for e in getattr(run, "events", [])][-4:]
        raise SystemExit(f"scene {number}: the flow stopped before the render: {events}")

    command = recorded["command"]
    params = [t for t in command if t.startswith("-")]
    def flag(key):
        for token in params:
            if token.startswith(f"-{key}="):
                return token.split("=", 1)[1]
        return None
    scene_dir = out_root / f"{number:02d}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "scene": number, "name": name, "prompt": prompt, "lighting_edits": edits,
        "compiler": compiler, "switches": switches,
        "card": flag("scenario"), "sky": flag("sky"),
        "beauty_look": flag("beauty-look"), "hero_lighting": flag("hero-lighting"),
        "width": int(flag("width") or 1280), "height": int(flag("height") or 720),
        "params": " ".join(params),
        "import_manifests": to_import,
        "mesh_manifest": flag("mesh"),
        "command": command,
    }
    path = scene_dir / "lookdev.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("scenes", type=int, nargs="*", default=list(SCENES))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--compiler", choices=("regex", "llm"), default="regex")
    parser.add_argument("--spec-dir", default=None,
                        help="pinned specs (<NN>.json, as visual rounds pin them); used when present")
    parser.add_argument("--switches", default="",
                        help="FLIGHTSIM_RENDER_SWITCHES of the round being matched")
    parser.add_argument("--clip", type=float, default=3.0)
    args = parser.parse_args()
    for number in args.scenes:
        print(prepare(number, args.out.resolve(), args.compiler, args.switches,
                      args.clip, args.spec_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
