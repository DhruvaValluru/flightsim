# Digest D

Plan: tasks/phase3_todo.md · boxes: D1, D2, D3, D4, D5, D6

## D1

### plan (verbatim)

### D1 · Source survey and go/no-go — XS · [OWNER]
- **Files:** `docs/PHASE3_AIRCRAFT_SOURCES.md` (new)
- **Do:** one row per candidate, giving the mesh source, licence and pinned
  commit, the JSBSim FDM source, whether payload and gear are separable parts, and
  the keypoint provenance.
- **What a first search found (2026-10-27):** no J-15, J-35 or standalone J-11 in
  FGAddon. An early-development Su-27SK project (github.com/yanes19/Su-27SK, v0.3,
  2017) lists a J-11A variant; its licence is unchecked.
- **Recommendation:** J-11A only, if its licence is clean. Otherwise **cut D2–D3**
  and say so now, per the brief.
- **Verify:** every column is filled or marked `none found`, with a dated owner
  decision line.

### files
- `docs/PHASE3_AIRCRAFT_SOURCES.md` [new]

### signatures
(no existing source files)

## D2

### plan (verbatim)

### D2 · First new aircraft — M
- **Files:** `assets/aircraft_config/J11.json`, `assets/fdm_root/aircraft/J11/…`, `tests/test_aircraft_configs.py`
- **Do:** the config carries dimensions, the seven `KEYPOINT_NAMES`, `components`
  (payload from day one, per Phase C), `limits`, `licence` and `gear_geometry`.
  The FDM must trim at the default run's altitude and speed.
- **Verify:** `pytest -q tests/test_aircraft_configs.py -k J11`. A headless default
  run trims and verifies. Windows: the A7 auto-import brings it in with no command.

### files
- `assets/aircraft_config/J11.json` [missing]
- `assets/fdm_root/aircraft/J11/…` [missing]
- `tests/test_aircraft_configs.py` [missing]

### signatures
(no existing source files)

## D3

### plan (verbatim)

### D3 · Second new aircraft (only if D1 chose two) — S
- **Do:** same as D2. A shared Su-27-family FDM or engine file is reused, not copied.

### files

### signatures
(no existing source files)

## D4

### plan (verbatim)

### D4 · Desert and Forest presets — S
- **Files:** `webapp/runs.py` (`SCENE_SETTING_BAKES` ~L1260), `webapp/static/index.html`
- **Do:** a two-option environment picker over the existing rule (desert →
  `grand_canyon`, forest → `yosemite`). A preset fixes location, surface, sun and
  season. Google tiles stay the ground (CLAUDE.md). Global terrain is out of scope.
- **Verify:** `pytest -q -k environment`. "Desert" gives `grand_canyon`/`desert` on
  the card, and "Forest" gives `yosemite`/`forest`.

### files
- `webapp/runs.py` [exists]
- `webapp/static/index.html` [exists]

### signatures
- `webapp/runs.py` (98 signatures, first 51 shown)
    50:def baked(stem: Path) -> bool:
    116:class RunState:
    138:    def push(self, status: str, detail: str = "") -> None:
    144:    def as_dict(self) -> Dict:
    153:def editor_running() -> bool:
    180:def _dynamic_scenes(dynamic_dir: Path) -> List[Dict]:
    196:def curated_key_at(lat: float, lon: float) -> Optional[str]:
    205:def named_place(spec: ScenarioSpec) -> bool:
    220:def looked_up_place(spec: ScenarioSpec) -> bool:
    230:def open_ocean_scene(spec: ScenarioSpec) -> bool:
    243:def _chosen_origin(spec: ScenarioSpec):
    252:def names_real_place(spec: ScenarioSpec) -> bool:
    261:def needs_dynamic_bake(spec: ScenarioSpec) -> Optional[Dict]:
    354:def terrain_prefetch_enabled() -> bool:
    359:class TerrainPrefetch:
    375:    def __init__(self):
    380:    def key(lat: float, lon: float) -> tuple:
    383:    def start(self, lat: float, lon: float, bake=None) -> Dict[str, Any]:
    398:    def _run(key: tuple, job: Dict[str, Any], bake) -> None:
    408:    def status(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
    423:    def bake(self, lat: float, lon: float, bake=None) -> Dict:
    438:def prefetch_terrain_for(spec: ScenarioSpec, bake=None) -> Optional[Dict[str, Any]]:
    456:def bake_on_demand(lat: float, lon: float) -> Dict:
    478:def bake_curated(key: str) -> Dict:
    511:def ensure_control_ridge() -> None:
    538:def scene_set(spec: ScenarioSpec) -> bool:
    549:def _stated_terrain_scene(spec: ScenarioSpec) -> Optional[Dict]:
    615:def pick_scene(spec: ScenarioSpec) -> Dict:
    628:def _earned_scene(spec: ScenarioSpec) -> Optional[Dict]:
    666:def _auto_scene(spec: ScenarioSpec) -> Dict:
    746:def place_on_scene(spec: ScenarioSpec) -> None:
    800:def webapp_chase_flag(aircraft: str) -> str:
    819:def camera_render_flags(spec: ScenarioSpec):
    893:def _fly_clearance_track(spec: ScenarioSpec, ground, script,
    976:    def project(lat_deg: float, lon_deg: float):
    984:    def terrain_under(px: float, py: float):
    1056:def _orographic_provider(spec: ScenarioSpec, scene: Dict):
    1089:def _effect_report(spec: ScenarioSpec, scene: Dict, script, seconds: float,
    1158:    def stats(xs):
    1185:def _ridge_axis_deg(samples, scale_m: float) -> float:
    1214:def plan_terrain_environment(spec: ScenarioSpec) -> None:
    1270:def renderable_aircraft() -> List[str]:
    1278:def refuse_placeholder_mesh(spec: ScenarioSpec) -> Optional[Dict]:
    1334:def ensure_aircraft_model(spec: ScenarioSpec, report) -> None:
    1374:def plan_scene_setting(spec: ScenarioSpec) -> None:
    1442:def _water_mask():
    1469:def terrain_triangle_budget(scene: Optional[Dict]) -> Optional[int]:
    1489:def drape_month(spec: ScenarioSpec) -> int:
    1500:def attach_xplane_drape(scene: Dict, report=None,
    1559:def xplane_sky_source(source: Optional[str] = None) -> str:
    1571:def xplane_lighting_flags(look: Optional[Dict],
- `webapp/static/index.html` (191 signatures, first 51 shown)
    132:<div id="taxonomyLine" class="dim"></div>
    134:<div id="fleetCard" class="card">
    136:    <select id="aircraftCount">
    141:  <span class="dim" id="fleetHint">The main aircraft is the one described in the prompt.</span>
    142:  <div id="fleetPanels"></div>
    143:  <div id="fleetState" class="dim"></div>
    147:  <textarea id="prompt"
    149:  <aside id="conditionsList"></aside>
    151:<script src="/conditions_list.js"></script>
    152:<script>ConditionsList.mount(document.getElementById("conditionsList"), document.getElementById("prompt"));</script>
    153:<div id="lensPicker"></div>
    154:<script src="/camera3d.js"></script>
    155:<script src="/route_map.js"></script>
    156:<script src="/lens_picker.js"></script>
    157:<script>LensPicker.mount(document.getElementById("lensPicker"), document.getElementById("prompt"));</script>
    159:  <button id="compile">Interpret</button>
    161:    clip <select id="clipSeconds">
    172:  <span id="llmState" class="badge">compiler: checking&hellip;</span>
    173:  <span id="buildState" class="badge" title="the git branch and commit this server process was started from (GET /status build)">serving: checking&hellip;</span>
    174:  <span id="compileState" class="dim"></span>
    177:<details id="altGuide" class="card" open>
    182:      <input type="number" id="agGround" value="0" step="10" min="-500" max="9000"> m
    185:      <select id="agPreset">
    196:      <select id="agUnits"><option value="m">metres</option>
    199:  <div id="agGroundFrom" class="dim"></div>
    200:  <svg id="agSvg" viewBox="0 0 760 470" role="img"
    202:  <div id="agReadout"></div>
    203:  <table id="agTable">
    215:<div id="questionArea" style="display:none" class="card">
    219:  <div id="questionCards"></div>
    220:  <p><button id="answer">Answer &amp; re-interpret</button></p>
    223:<div id="specArea" style="display:none" class="card">
    224:  <div id="compilerLine"></div>
    225:  <div id="notes"></div>
    226:  <div id="terrainState" class="dim" style="display:none;margin:.3rem 0"></div>
    227:  <table id="specTable">
    232:  <div id="srcLegend" class="dim" style="margin:.4rem 0"></div>
    233:  <div id="lightingPanel" class="panel"></div>
    234:  <div id="viewPanel" class="panel"></div>
    235:  <div id="cameraPicker" style="margin:.6rem 0"></div>
    236:  <div id="cameraState" class="dim"></div>
    237:  <div id="cameraPlacer"></div>
    238:  <div id="routeState" class="dim"></div>
    239:  <div id="routeMap"></div>
    240:  <div id="verdict"></div>
    242:    <button id="run" class="run">Run</button>
    248:<div id="runArea" style="display:none" class="card">
    249:  <div id="status"></div>
    250:  <div id="clipArea"></div>
    253:<script>
    262:function sourceClass(s) { return "src-" + s; }

## D5

### plan (verbatim)

### D5 · The two places are prepared once — S
- **Files:** `scripts/bake_terrain.py`, the launcher (E6)
- **Do:** pre-bake both GLO-30 tiles on first launch, check the sidecar sha256, and
  never re-stream after that.
- **[OWNER]** Google tiles still stream at render time with a key. Is entering it
  once acceptable as "no manual intervention"?
- **Verify:** a second launch logs `bake grand_canyon up to date` and
  `bake yosemite up to date`.

### files
- `scripts/bake_terrain.py` [exists]

### signatures
- `scripts/bake_terrain.py` (5 signatures)
    33:def ensure_imagery(key: str, terrain_dir: Path, args) -> None:
    57:def wants_other_source(raw: Path, source: str) -> bool:
    72:def has_datum(raw: Path) -> bool:
    83:def datum_line(key: str, raw: Path) -> str:
    105:def main(argv=None) -> int:

## D6

### plan (verbatim)

### D6 · The same pipeline, unchanged, across the matrix — M
- **Files:** `scripts/run_test_scenarios.py`, `tests/test_phase3_matrix.py` (new), `docs/PHASE3_LOG.md`
- **Do:** run {A-4, new aircraft} × {Desert, Forest} from the default run, changing
  only the aircraft and environment choice.
- **Verify:** every cell is `verify PASS` with `component_coverage` PASS, and the
  cells' cards differ only in `aircraft` and `scene`.

### files
- `scripts/run_test_scenarios.py` [exists]
- `tests/test_phase3_matrix.py` [new]
- `docs/PHASE3_LOG.md` [exists]

### signatures
- `scripts/run_test_scenarios.py` (8 signatures)
    81:def call(server: str, method: str, path: str, body=None, timeout: float = 3600.0):
    97:def why(payload) -> str:
    114:def apply_lighting(spec_dict, edits) -> None:
    120:def run_one(server, number, name, prompt, edits, args):
    178:def _slug(text: str) -> str:
    182:def _first(directory: Path, pattern: str):
    187:def collect(results) -> Path:
    247:def main() -> int:
- `docs/PHASE3_LOG.md` (4 signatures)
    1:# Phase 3 log
    15:## Letter A
    34:## Letter A, run A-2 (UE 5.7.4, decision 10)
    69:## Letter B, run B-1 (UE 5.7.4, push 3e59358d)
