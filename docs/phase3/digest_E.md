# Digest E

Plan: tasks/phase3_todo.md · boxes: E1, E2, E3, E4, E5, E6

## E1

### plan (verbatim)

### E1 · Inventory the configuration surface — S
- **Files:** `core/registry.py`, `docs/CONFIG_SURFACE.md` (new)
- **Do:** list every `FLIGHTSIM_*` variable (20 read today in core/webapp/flightsim:
  LLM, LLM_MODEL, SKY, WEATHER_BACKEND, RENDER_QUALITY, GOOGLE_TILES,
  RENDER_TIMEOUT_SECONDS, FFMPEG, STALL_SECONDS, RAIN_STYLE, FONT, CAPTURE_PASSES,
  XPLANE_TERRAIN/SKY/LIGHTING, TERRAIN_PREFETCH, RELAY_URL, RAIN_GAIN, GEOCODER,
  GEOCODE_CACHE), plus `UE_ROOT` and every CLI flag the user path reaches,
  including `--no-host-flight`. Each gets a decision:
  - **UI:** stays exposed, in the interface;
  - **default:** hidden, value fixed;
  - **dev-only:** tests and debugging scripts only;
  - **remove.**
- **Verify:** a registry test finds every `FLIGHTSIM_…` name registered with a
  decision.

### files
- `core/registry.py` [exists]
- `docs/CONFIG_SURFACE.md` [new]

### signatures
- `core/registry.py` (39 signatures)
    56:class RecordError(Exception):
    59:    def __init__(self, constraint: str, message: str) -> None:
    65:class _NoNull:
    70:    def __repr__(self) -> str:
    78:class EffectChannel:
    84:    def to_dict(self) -> Dict[str, str]:
    89:class ReadbackTolerance:
    98:    def __post_init__(self) -> None:
    106:    def to_dict(self) -> Dict[str, Any]:
    111:class UInputRule:
    122:    def __post_init__(self) -> None:
    128:    def to_dict(self) -> Dict[str, Any]:
    135:class VariableRecord:
    149:    def __post_init__(self) -> None:
    177:    def spec_section(self) -> Optional[str]:
    181:    def spec_leaf(self) -> Optional[str]:
    184:    def channel_units(self) -> Dict[str, str]:
    187:    def to_dict(self) -> Dict[str, Any]:
    208:def _suffix_unit(name: str) -> str:
    219:class Registry:
    222:    def __init__(self, entries: Tuple[VariableRecord, ...] = ()) -> None:
    227:    def register(self, entry: VariableRecord) -> VariableRecord:
    237:    def get(self, name: str) -> VariableRecord:
    246:    def __contains__(self, name: object) -> bool:
    249:    def __iter__(self) -> Iterator[VariableRecord]:
    252:    def __len__(self) -> int:
    255:    def names(self) -> Tuple[str, ...]:
    258:    def channel_units(self) -> Dict[str, str]:
    266:    def host_channels(self) -> Tuple[str, ...]:
    274:    def spec_fields(self) -> Dict[str, str]:
    278:    def sections(self) -> Tuple[str, ...]:
    284:    def unregistered_fields(self, data: Mapping[str, Any]) -> List[str]:
    299:    def require_registered(self, data: Mapping[str, Any]) -> None:
    309:    def stated_variables(self, data: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    320:    def to_dict(self) -> Dict[str, Any]:
    324:def unregistered_fields(data: Mapping[str, Any]) -> List[str]:
    383:def _icing_factor(axis: str, channels: Tuple[Tuple[str, str], ...], null_basis: str) -> VariableRecord:
    401:def _injected(name: str, prop: str, unit: str, null_basis: str,
    432:def _wake(leaf: str, spec_path: str, unit: str, null_value: Any, null_basis: str,

## E2

### plan (verbatim)

### E2 · One settings file — M
- **Files:** `core/registry.py`, `webapp/server.py`, `webapp/runs.py`, `tests/test_settings.py` (new)
- **Do:** `settings.json` in the user data directory is the only source for the UI
  items, behind `GET/PUT /settings`. Environment variables become developer
  overrides, recorded in the run as `env override`. The owner's defaults stay:
  tiles on, storm weather on.
- **Verify:** an empty file and an empty environment give the documented defaults,
  and `FLIGHTSIM_GOOGLE_TILES=off` is still honoured.

### files
- `core/registry.py` [exists]
- `webapp/server.py` [exists]
- `webapp/runs.py` [exists]
- `tests/test_settings.py` [new]

### signatures
- `core/registry.py` (39 signatures, first 33 shown)
    56:class RecordError(Exception):
    59:    def __init__(self, constraint: str, message: str) -> None:
    65:class _NoNull:
    70:    def __repr__(self) -> str:
    78:class EffectChannel:
    84:    def to_dict(self) -> Dict[str, str]:
    89:class ReadbackTolerance:
    98:    def __post_init__(self) -> None:
    106:    def to_dict(self) -> Dict[str, Any]:
    111:class UInputRule:
    122:    def __post_init__(self) -> None:
    128:    def to_dict(self) -> Dict[str, Any]:
    135:class VariableRecord:
    149:    def __post_init__(self) -> None:
    177:    def spec_section(self) -> Optional[str]:
    181:    def spec_leaf(self) -> Optional[str]:
    184:    def channel_units(self) -> Dict[str, str]:
    187:    def to_dict(self) -> Dict[str, Any]:
    208:def _suffix_unit(name: str) -> str:
    219:class Registry:
    222:    def __init__(self, entries: Tuple[VariableRecord, ...] = ()) -> None:
    227:    def register(self, entry: VariableRecord) -> VariableRecord:
    237:    def get(self, name: str) -> VariableRecord:
    246:    def __contains__(self, name: object) -> bool:
    249:    def __iter__(self) -> Iterator[VariableRecord]:
    252:    def __len__(self) -> int:
    255:    def names(self) -> Tuple[str, ...]:
    258:    def channel_units(self) -> Dict[str, str]:
    266:    def host_channels(self) -> Tuple[str, ...]:
    274:    def spec_fields(self) -> Dict[str, str]:
    278:    def sections(self) -> Tuple[str, ...]:
    284:    def unregistered_fields(self, data: Mapping[str, Any]) -> List[str]:
    299:    def require_registered(self, data: Mapping[str, Any]) -> None:
- `webapp/server.py` (81 signatures, first 33 shown)
    78:def _plain(refusal: Dict[str, Any]) -> Dict[str, Any]:
    96:async def plain_language_refusals(request, call_next):
    122:class CompileRequest(BaseModel):
    146:class RunRequest(BaseModel):
    151:class CameraRequest(BaseModel):
    167:def _spec_payload(spec: ScenarioSpec) -> Dict[str, Any]:
    283:def _lighting_presets() -> Dict[str, Any]:
    292:def _validation_payload(spec: ScenarioSpec) -> Dict[str, Any]:
    308:def index() -> str:
    313:def altitude_guide_endpoint(ground_m: float = 0.0) -> JSONResponse:
    327:def compile_endpoint(request: CompileRequest) -> JSONResponse:
    485:class AircraftPlacement(BaseModel):
    501:class AircraftRequest(BaseModel):
    510:def aircraft_endpoint(request: AircraftRequest) -> JSONResponse:
    557:class CameraPromptRequest(BaseModel):
    566:def camera_prompt_endpoint(request: CameraPromptRequest) -> JSONResponse:
    633:class RepairRequest(BaseModel):
    644:def _full_violations(spec: ScenarioSpec):
    665:def _repair_verdict(spec: ScenarioSpec) -> Dict[str, Any]:
    677:def repair_endpoint(request: RepairRequest) -> JSONResponse:
    708:def repair_options_endpoint(request: RepairRequest) -> JSONResponse:
    724:def cameras_endpoint(request: CameraRequest) -> JSONResponse:
    820:class PlacerTerrainRequest(BaseModel):
    827:def camera_terrain_endpoint(request: PlacerTerrainRequest) -> JSONResponse:
    845:class PlacerRequest(BaseModel):
    856:def camera_place_endpoint(request: PlacerRequest) -> JSONResponse:
    894:def camera_placer_script():
    900:class RouteTerrainRequest(BaseModel):
    907:def route_terrain_endpoint(request: RouteTerrainRequest) -> JSONResponse:
    933:class RouteCheckRequest(BaseModel):
    946:def route_check_endpoint(request: RouteCheckRequest) -> JSONResponse:
    976:def route_map_script():
    984:def run_endpoint(request: RunRequest) -> JSONResponse:
- `webapp/runs.py` (100 signatures, first 33 shown)
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
    746:def provision_place(spec: ScenarioSpec) -> Dict[str, Any]:
    772:def place_on_scene(spec: ScenarioSpec) -> None:
    826:def webapp_chase_flag(aircraft: str) -> str:

## E3

### plan (verbatim)

### E3 · Settings panel — S
- **Files:** `webapp/static/index.html`, `webapp/static/settings.js` (new)
- **Do:**
  - Show at most six fields: tiles key, Cesium status, engine (read-only, from
    preflight), render quality, LLM key, and the extra passes.
  - Everything else goes under "Advanced" or is removed.
  - A missing required item shows as a named, fixable message.
- **Verify:** a headless-Chromium page test sets the key, reloads, and finds it
  persisted.

### files
- `webapp/static/index.html` [exists]
- `webapp/static/settings.js` [new]

### signatures
- `webapp/static/index.html` (195 signatures, first 101 shown)
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
    153:<div id="environmentPicker"></div>
    154:<script src="/environment_picker.js"></script>
    155:<script>EnvironmentPicker.mount(document.getElementById("environmentPicker"), {});</script>
    156:<div id="lensPicker"></div>
    157:<script src="/camera3d.js"></script>
    158:<script src="/route_map.js"></script>
    159:<script src="/lens_picker.js"></script>
    160:<script>LensPicker.mount(document.getElementById("lensPicker"), document.getElementById("prompt"));</script>
    162:  <button id="compile">Interpret</button>
    164:    clip <select id="clipSeconds">
    175:  <span id="llmState" class="badge">compiler: checking&hellip;</span>
    176:  <span id="buildState" class="badge" title="the git branch and commit this server process was started from (GET /status build)">serving: checking&hellip;</span>
    177:  <span id="compileState" class="dim"></span>
    180:<details id="altGuide" class="card" open>
    185:      <input type="number" id="agGround" value="0" step="10" min="-500" max="9000"> m
    188:      <select id="agPreset">
    199:      <select id="agUnits"><option value="m">metres</option>
    202:  <div id="agGroundFrom" class="dim"></div>
    203:  <svg id="agSvg" viewBox="0 0 760 470" role="img"
    205:  <div id="agReadout"></div>
    206:  <table id="agTable">
    218:<div id="questionArea" style="display:none" class="card">
    222:  <div id="questionCards"></div>
    223:  <p><button id="answer">Answer &amp; re-interpret</button></p>
    226:<div id="specArea" style="display:none" class="card">
    227:  <div id="compilerLine"></div>
    228:  <div id="notes"></div>
    229:  <div id="terrainState" class="dim" style="display:none;margin:.3rem 0"></div>
    230:  <table id="specTable">
    235:  <div id="srcLegend" class="dim" style="margin:.4rem 0"></div>
    236:  <div id="lightingPanel" class="panel"></div>
    237:  <div id="viewPanel" class="panel"></div>
    238:  <div id="cameraPicker" style="margin:.6rem 0"></div>
    239:  <div id="cameraState" class="dim"></div>
    240:  <div id="cameraPlacer"></div>
    241:  <div id="routeState" class="dim"></div>
    242:  <div id="routeMap"></div>
    243:  <div id="verdict"></div>
    245:    <button id="run" class="run">Run</button>
    251:<div id="runArea" style="display:none" class="card">
    252:  <div id="status"></div>
    253:  <div id="clipArea"></div>
    256:<script>
    265:function sourceClass(s) { return "src-" + s; }
    270:function provenanceNote(f) {
    331:function buildFleetPanels() {
    373:function collectFleet() {
    389:async function applyFleet() {
    414:function renderQuestions(payload) {
    452:function collectAnswers() {
    463:function renderSpec(payload) {
    479:  const traffic = (spec.dict && spec.dict.traffic) || [];
    481:    const val = (e, k) => e[k] ? e[k].value : 0;
    607:function renderVerdict(v) {
    621:      `<div class="repair-row"><input id="repairWhat" maxlength="300" style="width:55%" ` +
    623:      ` <button id="repairOptions" class="opt">Show me 3 fixes</button>` +
    624:      ` <button id="repairGo" class="opt">Fix it for me</button>` +
    625:      `<div id="repairChoices"></div>` +
    626:      `<div id="repairState" class="dim"></div></div>`;
    634:async function repairOptions() {
    666:async function repairSpec(edits) {
    707:function showTerrainPrefetch(status) {
    755:const toLog = (v, lo, hi) => 1000 * Math.log(clamp(v, lo, hi) / lo) / Math.log(hi / lo);
    756:const fromLog = (t, lo, hi) => lo * Math.pow(hi / lo, t / 1000);
    767:const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
    771:const round = (v, digits) => +(+v).toFixed(digits);
    773:function rowInput(key) {
    777:function rowValue(key) {
    786:function setRow(key, value) {
    797:function kelvinColour(k) {
    808:function lightingKnob(name) {
    811:  const table = (lightingPresets.presets || {})[preset] || {};
    820:function renderLightingPanel() {
    829:  const autoNote = (knob, unit = "") => knob.auto
    846:  const slider = (name, label, min, max, step, unit, digits) => {
    873:    `<input type="number" min="0" max="360" step="0.1" id="lightAz" ` +
    884:    `<input type="number" min="2" max="90" step="0.1" id="lightEl" ` +
    975:function followingCamera() {
    990:function dialSky(svg, event, size, radius) {
    992:  const x = (event.clientX - box.left) * (size / box.width) - size / 2;
    993:  const y = (event.clientY - box.top) * (size / box.height) - size / 2;
    999:function attachSunDialDrag(svg) {
    1031:  const end = () => {
    1042:function sunDialSvg() {
    1043:  return `<svg id="sunDial" class="dial" viewBox="0 0 200 200" width="200" height="200" ` +
    1050:function sunDialInner() {
    1056:  const point = (az, el) => {
    1070:  const along = (d, side = 0) => [cx + d * Math.sin(rad(heading)) + side * Math.cos(rad(heading)),
    1107:function cameraOrbit(i) {
    1118:function setCameraOrbit(i, bearing, elevation, distance) {
    1126:function renderViewPanel() {

## E4

### plan (verbatim)

### E4 · Capture with nothing typed gives a working run — S · [OWNER: storm weather in the default]
- **Files:** `webapp/runs.py`, `webapp/server.py`
- **Do:** `/run {}` defaults to the A-4 with its loadout, Desert, the chase camera, a
  short clip and labels on. The Capture button submits it.
- **Verify:** headless `POST /run {}` reaches `done` with no FAIL. Windows: the same
  request renders and verifies.

### files
- `webapp/runs.py` [exists]
- `webapp/server.py` [exists]

### signatures
- `webapp/runs.py` (100 signatures, first 52 shown)
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
    746:def provision_place(spec: ScenarioSpec) -> Dict[str, Any]:
    772:def place_on_scene(spec: ScenarioSpec) -> None:
    826:def webapp_chase_flag(aircraft: str) -> str:
    845:def camera_render_flags(spec: ScenarioSpec):
    919:def _fly_clearance_track(spec: ScenarioSpec, ground, script,
    1002:    def project(lat_deg: float, lon_deg: float):
    1010:    def terrain_under(px: float, py: float):
    1082:def _orographic_provider(spec: ScenarioSpec, scene: Dict):
    1115:def _effect_report(spec: ScenarioSpec, scene: Dict, script, seconds: float,
    1184:    def stats(xs):
    1211:def _ridge_axis_deg(samples, scale_m: float) -> float:
    1240:def plan_terrain_environment(spec: ScenarioSpec) -> None:
    1316:def apply_environment_preset(spec: ScenarioSpec, name: str) -> None:
    1350:def renderable_aircraft() -> List[str]:
    1358:def refuse_placeholder_mesh(spec: ScenarioSpec) -> Optional[Dict]:
    1414:def ensure_aircraft_model(spec: ScenarioSpec, report) -> None:
    1454:def plan_scene_setting(spec: ScenarioSpec) -> None:
    1522:def _water_mask():
    1549:def terrain_triangle_budget(scene: Optional[Dict]) -> Optional[int]:
    1569:def drape_month(spec: ScenarioSpec) -> int:
    1580:def attach_xplane_drape(scene: Dict, report=None,
    1639:def xplane_sky_source(source: Optional[str] = None) -> str:
- `webapp/server.py` (81 signatures, first 52 shown)
    78:def _plain(refusal: Dict[str, Any]) -> Dict[str, Any]:
    96:async def plain_language_refusals(request, call_next):
    122:class CompileRequest(BaseModel):
    146:class RunRequest(BaseModel):
    151:class CameraRequest(BaseModel):
    167:def _spec_payload(spec: ScenarioSpec) -> Dict[str, Any]:
    283:def _lighting_presets() -> Dict[str, Any]:
    292:def _validation_payload(spec: ScenarioSpec) -> Dict[str, Any]:
    308:def index() -> str:
    313:def altitude_guide_endpoint(ground_m: float = 0.0) -> JSONResponse:
    327:def compile_endpoint(request: CompileRequest) -> JSONResponse:
    485:class AircraftPlacement(BaseModel):
    501:class AircraftRequest(BaseModel):
    510:def aircraft_endpoint(request: AircraftRequest) -> JSONResponse:
    557:class CameraPromptRequest(BaseModel):
    566:def camera_prompt_endpoint(request: CameraPromptRequest) -> JSONResponse:
    633:class RepairRequest(BaseModel):
    644:def _full_violations(spec: ScenarioSpec):
    665:def _repair_verdict(spec: ScenarioSpec) -> Dict[str, Any]:
    677:def repair_endpoint(request: RepairRequest) -> JSONResponse:
    708:def repair_options_endpoint(request: RepairRequest) -> JSONResponse:
    724:def cameras_endpoint(request: CameraRequest) -> JSONResponse:
    820:class PlacerTerrainRequest(BaseModel):
    827:def camera_terrain_endpoint(request: PlacerTerrainRequest) -> JSONResponse:
    845:class PlacerRequest(BaseModel):
    856:def camera_place_endpoint(request: PlacerRequest) -> JSONResponse:
    894:def camera_placer_script():
    900:class RouteTerrainRequest(BaseModel):
    907:def route_terrain_endpoint(request: RouteTerrainRequest) -> JSONResponse:
    933:class RouteCheckRequest(BaseModel):
    946:def route_check_endpoint(request: RouteCheckRequest) -> JSONResponse:
    976:def route_map_script():
    984:def run_endpoint(request: RunRequest) -> JSONResponse:
    1147:def build_info() -> Dict[str, str]:
    1174:def status_endpoint() -> JSONResponse:
    1201:def run_state(run_id: str) -> JSONResponse:
    1209:def run_clip(run_id: str):
    1217:def run_telemetry(run_id: str):
    1228:class BakeRequest(BaseModel):
    1233:def _prefetch(spec: ScenarioSpec) -> Optional[Dict[str, Any]]:
    1244:def bake_status(latitude: float, longitude: float) -> JSONResponse:
    1251:def bake_endpoint(request: BakeRequest) -> JSONResponse:
    1268:def run_card(run_id: str):
    1280:def run_effect(run_id: str):
    1310:def run_images(run_id: str):
    1328:def run_camera_manifest(run_id: str, camera_id: str):
    1372:def run_dataset_card(run_id: str, format: str = "coco",
    1388:def run_dataset_archive(run_id: str, format: str = "coco",
    1437:def run_camera_box3d_archive(run_id: str, camera_id: str):
    1457:def run_camera_archive(run_id: str, camera_id: str):
    1488:def frames_page() -> str:
    1494:def run_camera_clip(run_id: str, camera_id: str):

## E5

### plan (verbatim)

### E5 · Extra passes become checkboxes — S
- **Files:** `webapp/capture.py`, `webapp/static/index.html`
- **Do:** `FLIGHTSIM_CAPTURE_PASSES` (normals, flow, amodal) becomes checkboxes, and
  the dev-only variables are no longer read on the web path.
- **Verify:** `grep -n "FLIGHTSIM_CAPTURE_PASSES\|FLIGHTSIM_XPLANE" webapp/*.py` shows
  only the registry read.

### files
- `webapp/capture.py` [exists]
- `webapp/static/index.html` [exists]

### signatures
- `webapp/capture.py` (26 signatures)
    52:class CaptureError(RuntimeError):
    55:    def __init__(self, constraint: str, message: str) -> None:
    70:def requested_capture_passes(environ=None) -> List[str]:
    88:def apply_capture_passes(spec, environ=None) -> List[str]:
    103:def wants_capture(spec) -> bool:
    109:def clip_columns(columns: Dict, duration_s: Optional[float]) -> Dict:
    136:def solve(spec, scene: Dict, heightfield=None, terrain_ground=None,
    166:def _solve_cameras(spec, columns, frame, heightfield, tornado, datum):
    200:def resolve_over_host(spec, solved: Dict, host_telemetry, heightfield=None,
    244:def card_blocks(spec, solved: Dict) -> List[Dict]:
    252:def georeference(solved: Dict, heightfield=None) -> Dict:
    262:def landmarks(spec, solved: Dict, heightfield=None) -> List[Dict]:
    274:def render_passes(card: Path, frames_root: Path, camera_ids: List[str],
    311:def traffic_tracks(spec, solved: Dict) -> List:
    327:def card_scene_objects(spec, solved: Dict) -> Dict:
    354:def write_manifest(spec, solved: Dict, out: Path, scene: Dict,
    386:def apply_sensor(out: Path, run_seed: int) -> Dict[str, int]:
    403:def frames_archive(out: Path, camera_id: str) -> Optional[Path]:
    600:def box3d_archive(out: Path, camera_id: str) -> Optional[Path]:
    672:def dataset_archive(out: Path, fmt: str, cameras: Optional[List[str]] = None,
    758:def camera_view(manifest: Dict, camera_id: str,
    782:def headless_capture(spec, scene: Dict, out: Path, heightfield=None,
    829:def _check_sentence(name: str) -> Optional[str]:
    837:def finish(out: Path, max_overlays: Optional[int] = 24) -> Dict:
    883:def inventory(out: Path) -> Dict:
    890:    def listing(root: Path) -> Dict[str, List[str]]:
- `webapp/static/index.html` (195 signatures, first 52 shown)
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
    153:<div id="environmentPicker"></div>
    154:<script src="/environment_picker.js"></script>
    155:<script>EnvironmentPicker.mount(document.getElementById("environmentPicker"), {});</script>
    156:<div id="lensPicker"></div>
    157:<script src="/camera3d.js"></script>
    158:<script src="/route_map.js"></script>
    159:<script src="/lens_picker.js"></script>
    160:<script>LensPicker.mount(document.getElementById("lensPicker"), document.getElementById("prompt"));</script>
    162:  <button id="compile">Interpret</button>
    164:    clip <select id="clipSeconds">
    175:  <span id="llmState" class="badge">compiler: checking&hellip;</span>
    176:  <span id="buildState" class="badge" title="the git branch and commit this server process was started from (GET /status build)">serving: checking&hellip;</span>
    177:  <span id="compileState" class="dim"></span>
    180:<details id="altGuide" class="card" open>
    185:      <input type="number" id="agGround" value="0" step="10" min="-500" max="9000"> m
    188:      <select id="agPreset">
    199:      <select id="agUnits"><option value="m">metres</option>
    202:  <div id="agGroundFrom" class="dim"></div>
    203:  <svg id="agSvg" viewBox="0 0 760 470" role="img"
    205:  <div id="agReadout"></div>
    206:  <table id="agTable">
    218:<div id="questionArea" style="display:none" class="card">
    222:  <div id="questionCards"></div>
    223:  <p><button id="answer">Answer &amp; re-interpret</button></p>
    226:<div id="specArea" style="display:none" class="card">
    227:  <div id="compilerLine"></div>
    228:  <div id="notes"></div>
    229:  <div id="terrainState" class="dim" style="display:none;margin:.3rem 0"></div>
    230:  <table id="specTable">
    235:  <div id="srcLegend" class="dim" style="margin:.4rem 0"></div>
    236:  <div id="lightingPanel" class="panel"></div>
    237:  <div id="viewPanel" class="panel"></div>
    238:  <div id="cameraPicker" style="margin:.6rem 0"></div>
    239:  <div id="cameraState" class="dim"></div>
    240:  <div id="cameraPlacer"></div>
    241:  <div id="routeState" class="dim"></div>
    242:  <div id="routeMap"></div>
    243:  <div id="verdict"></div>
    245:    <button id="run" class="run">Run</button>
    251:<div id="runArea" style="display:none" class="card">
    252:  <div id="status"></div>
    253:  <div id="clipArea"></div>

## E6

### plan (verbatim)

### E6 · Double-click launcher — M
- **Files:** `Launch FlightSim.cmd` (new), `scripts/deploy_windows.ps1` (extended,
  not replaced), `scripts/ue_preflight.ps1`
- **Do:** in order, stopping at the first failure with a named reason in the window:
  1. Install or update from `requirements.lock` (what `deploy_windows.ps1` already does).
  2. Preflight against `toolchain.json`.
  3. Build, only if the A4 stamp does not match.
  4. Create materials, only if one is missing or stale.
  5. Import aircraft, only if stale (A7).
  6. Bake the two places (D5).
  7. Start the server and open the browser.
- **Verify:**
  - Windows, fresh clone: double-click, and `logs/launch.log` ends with `READY`.
  - A second launch logs `up to date` for the build, materials, aircraft and bakes.
  - Container: a source test asserts the step order and that no step prompts.

### files
- `Launch FlightSim.cmd` [new]
- `scripts/deploy_windows.ps1` [exists]
- `scripts/ue_preflight.ps1` [exists]

### signatures
- `scripts/deploy_windows.ps1` (7 signatures)
    38:param(
    54:function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
    62:function Require-Exit($stage, $tool, $cause) {
    68:function Refresh-Path {
    74:function Require-Winget {
    99:function Probe {
    110:function Find-Python {
- `scripts/ue_preflight.ps1` (7 signatures)
    20:function Probe {
    29:function Say($label, $msg)  { "  {0,-34} {1}" -f $label, $msg | Write-Host }
    30:function Fail($label, $msg) { "  {0,-34} {1}" -f $label, $msg | Write-Host; $script:status = 1 }
    209:function Get-Toolchain($repo) {
    224:function Select-VersionDir($parent, $pinned) {
    236:function Get-InstalledTools($repo, $ueRoot, $pins) {
    301:function Test-ToolVersion($tool, $found, $pinned) {
