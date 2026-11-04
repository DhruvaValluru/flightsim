# Digest A

Plan: tasks/phase3_todo.md · boxes: A1, A2, A3, A4, A5, A6, A7, A8, A9, A10, A11, A12, A13, C1, C5, C6

## A1

### plan (verbatim)

### A1 · Choose one engine and install it on all three machines — XS · [OWNER]
- **Files:** `docs/TOOLCHAIN.md` (new)
- **Decide:** the 2026-10-19 decision was 5.7, for render quality. The review
  shows 5.7 has not built on the reviewer's machines, and the brief says "if a
  newer engine cannot be relied on, pin back to what can".
  - **Recommended:** pin back to **5.5** for Phase 3. It is installed, and every
    measurement before October was taken on it.
  - **Alternative:** keep 5.7, but only if all three machines install the same 5.7
    patch before any other A-step.
  - **Not offered:** building on both versions at once, which doubles the test
    surface.
- **Do:** record per machine the exact engine build
  (`Engine/Build/Build.version` Major.Minor.Patch and Changelist), the MSVC
  toolset and the Windows SDK. All three rows show the same version.
- **Below,** `<PIN>` means the version chosen here.
- **Verify:** three rows in `docs/TOOLCHAIN.md` with an identical engine version,
  and a dated decision line naming who decided.

### files
- `docs/TOOLCHAIN.md` [exists]

### signatures
- `docs/TOOLCHAIN.md` (1 signatures)
    1:# Toolchain

## A2

### plan (verbatim)

### A2 · One pin, everywhere, tested — M
- **Files:** `ue/FlightSim.uproject`, `ue/Source/FlightSim.Target.cs`,
  `ue/Source/FlightSimEditor.Target.cs`, `core/util/platform.py`,
  `tests/test_platform.py`
- **Do:** set `EngineAssociation`, both `IncludeOrderVersion` constants and
  `UE_ENGINE_VERSION` to `<PIN>`. Add `UE_ENGINE_PATCH` for the A1 patch level.
- **If `<PIN>` is 5.5:** revert or version-guard the 5.7-only changes made in October:
  - the C4883 silencing on the commandlet's `Main`;
  - `GetMaterialResource(EShaderPlatform)`;
  - any other 5.7-only API call. Find them with `git log -S"5.7" -- ue/`.
- **Add a source test:** the `IncludeOrderVersion` constant names `<PIN>`. R1
  becomes a CI failure, not a Windows surprise.
- **Verify:** `pytest -q tests/test_platform.py` passes. Hand-editing one Target.cs
  to another version makes it fail with the file named.

### files
- `ue/FlightSim.uproject` [exists]
- `ue/Source/FlightSim.Target.cs` [exists]
- `ue/Source/FlightSimEditor.Target.cs` [exists]
- `core/util/platform.py` [exists]
- `tests/test_platform.py` [exists]

### signatures
- `ue/FlightSim.uproject` (0 signatures)
- `ue/Source/FlightSim.Target.cs` (2 signatures)
    3:public class FlightSimTarget : TargetRules
    5:	public FlightSimTarget(TargetInfo Target) : base(Target)
- `ue/Source/FlightSimEditor.Target.cs` (2 signatures)
    3:public class FlightSimEditorTarget : TargetRules
    5:	public FlightSimEditorTarget(TargetInfo Target) : base(Target)
- `core/util/platform.py` (12 signatures)
    31:class FfmpegMissingError(RuntimeError):
    37:def os_name() -> str:
    46:def is_mac() -> bool:
    66:def find_ffmpeg() -> Path:
    103:def find_mono_font() -> Optional[str]:
    119:def mono_fonts(sizes: Tuple[int, ...]) -> List:
    185:def ue_platform_refusal() -> str:
    204:def find_ue_root() -> Optional[Path]:
    225:def ue_editor_path() -> Optional[Path]:
    237:def ue_bridge_binary(repo: Path) -> Path:
    245:def ue_runner_command(repo: Path, script_stem: str) -> List[str]:
    258:def ue_available() -> bool:
- `tests/test_platform.py` (14 signatures)
    21:def test_os_name_dispatch(monkeypatch):
    30:def test_ue_dispatch_windows_needs_engine_and_bridge(monkeypatch, tmp_path):
    55:def test_ue_dispatch_mac_and_linux_unchanged(monkeypatch):
    71:def test_ffmpeg_env_override_wins(monkeypatch, tmp_path):
    77:def test_missing_ffmpeg_is_a_named_refusal(monkeypatch):
    93:def test_font_chain_and_honest_degradation(monkeypatch, tmp_path, capsys):
    110:def test_webapp_refuses_ue_platform_without_the_engine(monkeypatch):
    155:def test_no_shadowed_locals_in_the_bridge():
    169:    def without_comments(text):
    200:def test_no_text_io_without_utf8_encoding():
    215:    def args_of(text, start):
    292:def test_the_engine_pin_is_5_7_everywhere_it_is_stated():
    321:def _read_ue_ini(path: Path):
    360:def test_default_engine_ini_carries_the_look_lane_renderer_settings():

## A3

### plan (verbatim)

### A3 · The build refuses the wrong engine by name — S
- **Files:** `scripts/build_ue.ps1`, `scripts/ue_preflight.ps1`
- **Do:**
  - Remove the "newest `UE_5.*` found" fallback (`build_ue.ps1:13-17`).
  - Resolve only `UE_ROOT` or the pinned install path.
  - Read `Engine/Build/Build.version` and refuse with
    `engine.version_mismatch: found X, pinned Y` before calling `Build.bat`.
- **Verify:**
  - Windows: `UE_ROOT` at another version → non-zero exit and
    `engine.version_mismatch`.
  - Pinned engine → exit 0, and the version it built against is printed.
  - Container: a source-reading test asserts the glob is gone.

### files
- `scripts/build_ue.ps1` [exists]
- `scripts/ue_preflight.ps1` [exists]

### signatures
- `scripts/build_ue.ps1` (0 signatures)
- `scripts/ue_preflight.ps1` (3 signatures)
    20:function Probe {
    29:function Say($label, $msg)  { "  {0,-34} {1}" -f $label, $msg | Write-Host }
    30:function Fail($label, $msg) { "  {0,-34} {1}" -f $label, $msg | Write-Host; $script:status = 1 }

## A4

### plan (verbatim)

### A4 · A stale engine binary is refused (R4) — M
- **Files:** `scripts/build_ue.ps1`, `core/util/platform.py`,
  `flightsim/capture.py`, `webapp/runs.py`, `core/messages/catalog.yaml`
- **Do:**
  - After a successful build, write `ue/Plugins/FlightSimBridge/Binaries/build_stamp.json`
    with the engine version and a hash of the plugin's `Source/` tree.
  - Before any render, compare it with the current source. A missing or
    different stamp refuses with `engine.binary_stale`, naming both hashes.
  - The launcher (E6) uses the same stamp to decide whether to rebuild.
- **Verify:**
  - Container: `pytest -q -k binary_stale`. A synthetic stamp with a wrong hash
    refuses; a matching one passes.
  - Windows: touching one `.cpp` without rebuilding makes the next render refuse.

### files
- `scripts/build_ue.ps1` [exists]
- `core/util/platform.py` [exists]
- `flightsim/capture.py` [exists]
- `webapp/runs.py` [exists]
- `core/messages/catalog.yaml` [exists]

### signatures
- `scripts/build_ue.ps1` (0 signatures)
- `core/util/platform.py` (12 signatures)
    31:class FfmpegMissingError(RuntimeError):
    37:def os_name() -> str:
    46:def is_mac() -> bool:
    66:def find_ffmpeg() -> Path:
    103:def find_mono_font() -> Optional[str]:
    119:def mono_fonts(sizes: Tuple[int, ...]) -> List:
    185:def ue_platform_refusal() -> str:
    204:def find_ue_root() -> Optional[Path]:
    225:def ue_editor_path() -> Optional[Path]:
    237:def ue_bridge_binary(repo: Path) -> Path:
    245:def ue_runner_command(repo: Path, script_stem: str) -> List[str]:
    258:def ue_available() -> bool:
- `flightsim/capture.py` (25 signatures, first 18 shown)
    75:def _is_library_banner(line: bytes) -> bool:
    79:class _BannerFilter:
    87:    def __init__(self, out_fd: int) -> None:
    93:    def emit(self, line: bytes) -> None:
    106:    def feed(self, chunk: bytes) -> None:
    112:    def close(self) -> None:
    121:def _relay_without_banners(read_end: int, out_fd: int) -> None:
    138:def _tail_without_banners(path: str, out_fd: int, stop: threading.Event,
    166:def _flush_c_stdout() -> None:
    180:def quiet_library_banners(enabled: bool = True):
    277:def _tornado_hazard_block(spec):
    303:def _mesh_manifest_path(spec) -> Path:
    310:def _traffic_mesh_refusal(spec):
    344:def _after_name(exc: Exception) -> str:
    353:def _scene_members(scene_path, terrain_stem):
    381:def _with_scene(block, scene_members):
    389:def _world_documents(spec, terrain_stem, landcover_json=None):
    469:def _refuse(violations) -> int:
- `webapp/runs.py` (97 signatures, first 18 shown)
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
- `core/messages/catalog.yaml` (399 signatures, first 18 shown)
    32:aircraft.exists:
    35:altitude.terrain_clearance:
    38:airspeed.stall_margin:
    41:airspeed.approach_speed:
    43:run.duration:
    46:run.rate:
    48:environment.wind_speed:
    50:environment.wind_direction:
    52:environment.surface:
    55:environment.weather_event:
    57:envelope.trim_feasible:
    63:randomization.enabled:
    65:randomization.year:
    67:randomization.day_of_year_min:
    69:randomization.day_of_year_max:
    71:randomization.hour_utc_min:
    73:randomization.hour_utc_max:
    75:randomization.fog_density_min:

## A5

### plan (verbatim)

### A5 · The JSBSim plugin on the pinned engine — S
- **Files:** `scripts/vendor_ue_plugin.ps1`, `ue/Plugins/JSBSimFlightDynamicsModel/VENDORED.json`
- **Do:** vendor against `<PIN>`. For each of the six `local_patches` (four from
  `scripts/jsbsim_plugin_patches_5_6.diff` plus two bridge additions), record
  whether it is still needed, still applied, or no longer applies. Write
  `ue_engine_target: "<PIN>"`.
- **Verify:**
  - Windows: `bash scripts/check_bridge_api.sh` exits 0 and the build is clean.
  - `experiments/gate5_ue_parity.py`: a c172p hold agrees with the Python flight
    within the recorded bound.

### files
- `scripts/vendor_ue_plugin.ps1` [exists]
- `ue/Plugins/JSBSimFlightDynamicsModel/VENDORED.json` [exists]

### signatures
- `scripts/vendor_ue_plugin.ps1` (0 signatures)
- `ue/Plugins/JSBSimFlightDynamicsModel/VENDORED.json` (11 signatures)
    2:  "upstream": "https://github.com/JSBSim-Team/jsbsim.git",
    3:  "tag": "v1.2.4",
    4:  "commit": "e07a7d810d4f1048039d42545d008b8a998636fa",
    5:  "built_with": "upstream JSBSimForUnrealMac.sh (not a reimplementation)",
    6:  "jsbsim_matches_headless_core": true,
    7:  "ue_platform": "Mac",
    8:  "library": "Source/ThirdParty/JSBSim/Lib/Mac/libJSBSim.dylib",
    9:  "library_sha256": "b42d47cc3daee56d09ecb348203afb1b7d7e00efac90961ee5dc2fabdc0ae448",
    10:  "header_count": 126,
    11:  "aircraft_staged": 60,
    12:  "local_patches": [

## A6

### plan (verbatim)

### A6 · Label and look materials compile on the pinned engine — S
- **Files:** `scripts/ue_create_materials.py`
- **Do:** already partly done in b95e711e. Assets without the current
  `GRAPH_GENERATIONS` stamp rebuild themselves. Confirm the script runs unattended
  and is idempotent on `<PIN>`, and that `M_CustomStencilID` needs no editor step.
- **Verify:** Windows. The first run prints `MATERIAL-STALE` → `MATERIAL-CREATED` for
  M_LandcoverID, M_LensDrops, M_GreyCard, M_RainStreaks and M_Ground_City. The second
  run prints `MATERIAL-EXISTS` for all of them, and the editor log has no "Missing If"
  errors.

### files
- `scripts/ue_create_materials.py` [exists]

### signatures
- `scripts/ue_create_materials.py` (91 signatures)
    565:def add_wetness(material, lib, base_colour_node, base_output, x,
    613:def create_vertex_colour():
    634:def create_terrain_imagery():
    661:def create_vertex_colour_unlit():
    692:def create_custom_stencil_id():
    731:def create_pass_material(name, scene_texture_id, signed):
    787:def create_world_normal_pass():
    791:def create_velocity_pass():
    795:def create_base_colour_pass():
    799:def create_world_normal_fallback():
    805:def create_velocity_check():
    811:def create_grey_card():
    856:def after_tonemapping():
    870:def move_after_tonemapping(name):
    903:def graph_stale(name):
    916:def rebuild_requested(name):
    933:def new_material(name):
    950:def finish(material, name):
    959:def linear_default_texture():
    975:def scalar(material, lib, name, default, x, y):
    982:def vector(material, lib, name, default, x, y):
    989:def texture_parameter(material, lib, name, linear, x, y, default=None, normal_map=False):
    1009:def binary(material, lib, kind, a, b, x, y, a_out="", b_out=""):
    1016:def constant(material, lib, value, x, y):
    1022:def mask(material, lib, source, channel, x, y, source_out=""):
    1031:def unary(material, lib, kind, source, x, y, source_out=""):
    1038:def lerp(material, lib, a, b, alpha, x, y, a_out="", b_out="", alpha_out=""):
    1046:def constant3(material, lib, rgb, x, y):
    1063:def connect(lib, source, source_out, node, names):
    1080:def select_if(material, lib, a, b, greater, equal, less, x, y):
    1090:def in_unit_interval(material, lib, value, x, y):
    1101:def _flat_png(name, texel):
    1113:    def chunk(kind, data):
    1126:def _repo_file(relative):
    1144:def import_texture(source, name, srgb, normal_map, flat, zero_alpha=False):
    1193:def default_texture(name):
    1210:def terrain_texture(material, lib, name, x, y, default=None):
    1221:def terrain_scalar(material, lib, name, x, y):
    1225:def world_metres_uv(material, lib, world_xy, metres, x, y):
    1235:def detail_uv(material, lib, world_xy, metres, aspect, x, y):
    1252:def terrain_role_samples(material, lib, world_xy, x, y):
    1277:def weighted_sum(material, lib, terms, x, y):
    1288:def terrain_surface(material, lib, samples, base, base_out, imagery, imagery_out,
    1398:def terrain_imagery_graph(material, lib):
    1437:def create_landscape():
    1524:def create_landcover_id():
    1573:def create_starfield():
    1619:def create_rain_streaks():
    1704:def _storm_material(name):
    1737:def restore_storm_materials():
    1752:def storm_material_stale(name):
    1764:def finish_storm(material, name):
    1774:def storm_scattering(material, lib, x, y):
    1799:def weather_shader(name):
    1807:def custom(material, lib, name, output_type, inputs, x, y):
    1825:def weather_parameter(material, lib, name, x, y, default=0.0):
    1843:def uv_channel(material, lib, index, channel, x, y):
    1851:def relative_position(material, lib, x, y, exclude_offsets, minus):
    1872:def drop_lit(material, lib, x, y):
    1900:def _translucent_unlit(material, blend):
    1906:def _translucent_lit(material):
    1913:def create_rain_drops():
    1949:def create_rain_splash():
    1978:def create_lightning_channel():
    2006:def ensure_volumetric_cloud_usage(name):
    2026:def create_storm_cell():
    2068:def create_windshield_rain():
    2109:def create_airframe_paint():
    2125:    def material_property(*names):
    2146:def create_runway():
    2168:def _sky_material(name):
    2184:def _save(material, full):
    2190:def create_moon():
    2217:def create_star_emissive():
    2246:def create_terrain_imagery_night():
    2328:def _weather_material(name):
    2345:def _world_xy_metres(material, lib, metres, x, y):
    2353:def _noise(material, lib, feature_m, x, y, levels=4):
    2365:def _wave_normal(material, lib, waves, x, y):
    2407:def _ground_textures(surface):
    2422:def _sample(material, lib, texture, uv, sampler, x, y):
    2430:def add_wet_ground(material, lib, colour, roughness, normal, x, colour_out="", rough_out="",
    2468:def create_ground(surface, material):
    2527:def create_ground_surfaces():
    2538:def create_lens_drops():
    2603:def create_rain_shaft():
    2640:def create_lightning():
    2659:def create_rain_drop():
    2691:def create_ice_overlay():
    2729:def _guard(creator):
    2730:    def run():

## A7

### plan (verbatim)

### A7 · The aircraft mesh is imported automatically (R2) — M
- **Files:** `flightsim/capture.py` (~L337, ~L797), `webapp/generate.py` (~L137),
  `webapp/runs.py`, `scripts/import_aircraft.py`
- **Do:** where the code now refuses with "run `scripts/import_aircraft.py`", run
  the import itself, once, and log it. Import when:
  - the mesh is missing;
  - or its `mesh_manifest.json` is older than the aircraft config or converter.

  The refusal stays only for a real failure, such as a missing licence file or
  converter error.
- **Verify:**
  - Windows: delete the imported A-4 asset, press Generate, and the run imports it
    and renders.
  - Container: a test with a missing mesh and a fake importer shows the import is
    called, not the refusal.

### files
- `flightsim/capture.py` [exists]
- `webapp/generate.py` [exists]
- `webapp/runs.py` [exists]
- `scripts/import_aircraft.py` [exists]

### signatures
- `flightsim/capture.py` (25 signatures, first 23 shown)
    75:def _is_library_banner(line: bytes) -> bool:
    79:class _BannerFilter:
    87:    def __init__(self, out_fd: int) -> None:
    93:    def emit(self, line: bytes) -> None:
    106:    def feed(self, chunk: bytes) -> None:
    112:    def close(self) -> None:
    121:def _relay_without_banners(read_end: int, out_fd: int) -> None:
    138:def _tail_without_banners(path: str, out_fd: int, stop: threading.Event,
    166:def _flush_c_stdout() -> None:
    180:def quiet_library_banners(enabled: bool = True):
    277:def _tornado_hazard_block(spec):
    303:def _mesh_manifest_path(spec) -> Path:
    310:def _traffic_mesh_refusal(spec):
    344:def _after_name(exc: Exception) -> str:
    353:def _scene_members(scene_path, terrain_stem):
    381:def _with_scene(block, scene_members):
    389:def _world_documents(spec, terrain_stem, landcover_json=None):
    469:def _refuse(violations) -> int:
    476:def build_parser() -> argparse.ArgumentParser:
    634:def _run_unattended(command, log):
    657:def main(argv: Optional[Sequence[str]] = None) -> int:
    677:def _run(args: argparse.Namespace) -> int:
    1082:    def solve_traffic(flight):
- `webapp/generate.py` (49 signatures, first 23 shown)
    118:def render_here(spec) -> Tuple[bool, str]:
    142:class GenerateRefusal(Exception):
    146:    def __init__(self, payload: Dict[str, Any], status_code: int = 409):
    154:def words(obj: Any, **extra: Any) -> Dict[str, Any]:
    187:def state_words(name: str, **params: Any) -> str:
    192:def _jsonable(value: Any) -> Any:
    198:def compile_round(prompt: str, tier: str = "llm", questions=None, answers=None
    241:def _leaf_words(name: str, leaf: Any) -> str:
    265:def paragraph(spec: ScenarioSpec, images: int, fmt: str) -> str:
    343:def estimate(spec: ScenarioSpec, images: int, measured: Optional[Dict[str, Any]] = None,
    377:def _free_bytes(directory: Path) -> int:
    388:class GenerateService:
    392:    def __init__(self, root: Optional[Path] = None) -> None:
    400:    def _dir(self, campaign_id: str) -> Path:
    405:    def open(self, campaign_id: str) -> Campaign:
    411:    def list_campaigns(self, limit: int = 100) -> Dict[str, Any]:
    456:    def _running_id(self) -> Optional[str]:
    464:    def _spawn(self, campaign: Campaign, workers: Optional[int], resume: bool) -> None:
    483:    def wait(self, campaign_id: str, timeout: float = 60.0) -> None:
    491:    def plan(self, prompt: str, answers=None, questions=None,
    555:    def preview(self, spec_dict: Dict[str, Any], images: Optional[int] = None,
    652:    def preview_image(self, preview_id: str, kind: str, camera_id: str, name: str) -> Path:
    660:    def start(self, prompt: str, answers=None, images: Optional[int] = None,
- `webapp/runs.py` (97 signatures, first 23 shown)
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
- `scripts/import_aircraft.py` (2 signatures)
    45:def main(argv=None) -> int:
    98:    def summary() -> None:

## A8

### plan (verbatim)

### A8 · Host flight works, and `--no-host-flight` leaves the user path (R3) — M
- **Files:** `flightsim/capture.py` (~L1221, L1263), `core/capture/hostflight.py`,
  the host C++ named by the review
- **Do:**
  1. Reproduce the host-flight failure from the review document and fix its cause.
  2. Remove the flag from the refusal text, which must name the fault instead.
  3. Keep the flag as developer-only (E1).
- **Known related open item (NEXT.md):** `FlightSimScenarioWorld.cpp` ~2650
  `Commands.Elevator += Input.Elevator` accumulates across entries. Fix it here if
  the review's failure is this, or record it.
- **Verify:** Windows. A web-app run with host flight on completes, and the parity
  check against the Python flight passes. `grep -n "no-host-flight" webapp flightsim/capture.py`
  shows no user-facing text.

### files
- `flightsim/capture.py` [exists]
- `core/capture/hostflight.py` [exists]

### signatures
- `flightsim/capture.py` (25 signatures)
    75:def _is_library_banner(line: bytes) -> bool:
    79:class _BannerFilter:
    87:    def __init__(self, out_fd: int) -> None:
    93:    def emit(self, line: bytes) -> None:
    106:    def feed(self, chunk: bytes) -> None:
    112:    def close(self) -> None:
    121:def _relay_without_banners(read_end: int, out_fd: int) -> None:
    138:def _tail_without_banners(path: str, out_fd: int, stop: threading.Event,
    166:def _flush_c_stdout() -> None:
    180:def quiet_library_banners(enabled: bool = True):
    277:def _tornado_hazard_block(spec):
    303:def _mesh_manifest_path(spec) -> Path:
    310:def _traffic_mesh_refusal(spec):
    344:def _after_name(exc: Exception) -> str:
    353:def _scene_members(scene_path, terrain_stem):
    381:def _with_scene(block, scene_members):
    389:def _world_documents(spec, terrain_stem, landcover_json=None):
    469:def _refuse(violations) -> int:
    476:def build_parser() -> argparse.ArgumentParser:
    634:def _run_unattended(command, log):
    657:def main(argv: Optional[Sequence[str]] = None) -> int:
    677:def _run(args: argparse.Namespace) -> int:
    1082:    def solve_traffic(flight):
    1097:    def solve_over(flight):
    1138:    def write_card(path, tracks, schedules, landmarks, traffic_tracks=()):
- `core/capture/hostflight.py` (8 signatures)
    64:class HostFlightError(Exception):
    70:    def __init__(self, message: str) -> None:
    74:    def render(self) -> str:
    78:def host_telemetry_path(run_dir) -> Path:
    83:def read_host_columns(path) -> Dict[str, List[float]]:
    137:def read_all_host_columns(path) -> Dict[str, List[float]]:
    173:def read_host_record(path) -> Dict[str, List[float]]:
    196:def digest_columns(columns: Dict[str, Sequence[float]]) -> str:

## A9

### plan (verbatim)

### A9 · Every camera renders, or the run fails by name (R5) — S
- **Files:** `FlightSimRenderCommandlet.cpp`, `flightsim/capture.py`, `webapp/runs.py`
- **Do:**
  1. Reproduce the empty second camera from the review document and fix it.
  2. After the render, a camera with zero frames refuses with
     `render.camera_empty: <camera id>`.
- **Verify:** Windows. The default two-camera run writes the same frame count for
  both cameras. Container: a synthetic run with one empty camera directory refuses
  by name.

### files
- `FlightSimRenderCommandlet.cpp` -> ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp [exists]
- `flightsim/capture.py` [exists]
- `webapp/runs.py` [exists]

### signatures
- `ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp` (6 signatures)
    818:double UFlightSimRenderCommandlet::LuminancePerUnit(double Ev100, double ExposureCompensationEv,
    826:double UFlightSimRenderCommandlet::LambertianLuminance(double IlluminanceLux, double Reflectance)
    831:int32 UFlightSimRenderCommandlet::AccumulationCount(double PredictedBlurPx, int32 RequestedK)
    836:bool UFlightSimRenderCommandlet::WriteLinearF32(const FString& Path, const TArray<float>& Values,
    852:double UFlightSimRenderCommandlet::EsfrMtf50(const TArray<float>& Luminance, int32 Width, int32 Height,
    1040:int32 UFlightSimRenderCommandlet::Main(const FString& Params)
- `flightsim/capture.py` (25 signatures)
    75:def _is_library_banner(line: bytes) -> bool:
    79:class _BannerFilter:
    87:    def __init__(self, out_fd: int) -> None:
    93:    def emit(self, line: bytes) -> None:
    106:    def feed(self, chunk: bytes) -> None:
    112:    def close(self) -> None:
    121:def _relay_without_banners(read_end: int, out_fd: int) -> None:
    138:def _tail_without_banners(path: str, out_fd: int, stop: threading.Event,
    166:def _flush_c_stdout() -> None:
    180:def quiet_library_banners(enabled: bool = True):
    277:def _tornado_hazard_block(spec):
    303:def _mesh_manifest_path(spec) -> Path:
    310:def _traffic_mesh_refusal(spec):
    344:def _after_name(exc: Exception) -> str:
    353:def _scene_members(scene_path, terrain_stem):
    381:def _with_scene(block, scene_members):
    389:def _world_documents(spec, terrain_stem, landcover_json=None):
    469:def _refuse(violations) -> int:
    476:def build_parser() -> argparse.ArgumentParser:
    634:def _run_unattended(command, log):
    657:def main(argv: Optional[Sequence[str]] = None) -> int:
    677:def _run(args: argparse.Namespace) -> int:
    1082:    def solve_traffic(flight):
    1097:    def solve_over(flight):
    1138:    def write_card(path, tracks, schedules, landmarks, traffic_tracks=()):
- `webapp/runs.py` (97 signatures, first 33 shown)
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

## A10

### plan (verbatim)

### A10 · Generate works in the web app (R6) — S
- **Files:** `webapp/generate.py`, `webapp/server.py`, the cause the review names
- **Do:** reproduce the refusal from the review document and fix its cause. The
  likely chain is the A7/A8 refusals surfacing through `words()`, so confirm before
  changing anything.
- **Verify:**
  - Windows: `/generate.html` takes a one-line prompt to a finished campaign.
  - Container: `tests/test_generate*.py` gains a case reproducing the review's
    refusal, which now passes.

### files
- `webapp/generate.py` [exists]
- `webapp/server.py` [exists]

### signatures
- `webapp/generate.py` (49 signatures)
    118:def render_here(spec) -> Tuple[bool, str]:
    142:class GenerateRefusal(Exception):
    146:    def __init__(self, payload: Dict[str, Any], status_code: int = 409):
    154:def words(obj: Any, **extra: Any) -> Dict[str, Any]:
    187:def state_words(name: str, **params: Any) -> str:
    192:def _jsonable(value: Any) -> Any:
    198:def compile_round(prompt: str, tier: str = "llm", questions=None, answers=None
    241:def _leaf_words(name: str, leaf: Any) -> str:
    265:def paragraph(spec: ScenarioSpec, images: int, fmt: str) -> str:
    343:def estimate(spec: ScenarioSpec, images: int, measured: Optional[Dict[str, Any]] = None,
    377:def _free_bytes(directory: Path) -> int:
    388:class GenerateService:
    392:    def __init__(self, root: Optional[Path] = None) -> None:
    400:    def _dir(self, campaign_id: str) -> Path:
    405:    def open(self, campaign_id: str) -> Campaign:
    411:    def list_campaigns(self, limit: int = 100) -> Dict[str, Any]:
    456:    def _running_id(self) -> Optional[str]:
    464:    def _spawn(self, campaign: Campaign, workers: Optional[int], resume: bool) -> None:
    483:    def wait(self, campaign_id: str, timeout: float = 60.0) -> None:
    491:    def plan(self, prompt: str, answers=None, questions=None,
    555:    def preview(self, spec_dict: Dict[str, Any], images: Optional[int] = None,
    652:    def preview_image(self, preview_id: str, kind: str, camera_id: str, name: str) -> Path:
    660:    def start(self, prompt: str, answers=None, images: Optional[int] = None,
    710:    def control(self, campaign_id: str, request: str) -> Dict[str, Any]:
    738:    def progress(self, campaign_id: str) -> Dict[str, Any]:
    750:    def events(self, campaign_id: str, interval: float = 1.0,
    778:    def frames(self, campaign_id: str) -> Dict[str, Any]:
    822:    def frame_image(self, campaign_id: str, case_id: str, kind: str, camera_id: str,
    829:    def download(self, campaign_id: str, fmt: Optional[str] = None) -> Dict[str, Any]:
    854:    def card(self, campaign_id: str, fmt: Optional[str] = None) -> Dict[str, Any]:
    869:    def export_result(self, campaign_id: str, fmt: Optional[str] = None) -> Dict[str, Any]:
    874:    def _export(self, campaign_id: str, fmt: Optional[str]
    937:def _condition_name(name: str) -> str:
    945:def card_words(card: Dict[str, Any], labels_only: Optional[bool] = None) -> Dict[str, Any]:
    1088:def _images_arg(value: Any) -> Optional[int]:
    1104:def plan_refusals(spec: ScenarioSpec) -> List[Dict[str, Any]]:
    1127:def expert_campaign(prompt: str, images: Optional[int], fmt: str, seed: Optional[int],
    1150:def pictures(run_dir: Path, per_camera: int = 1) -> List[Dict[str, str]]:
    1172:def first_picture(run_dir: Path) -> Optional[Dict[str, str]]:
    1177:def _guarded_image(root: Path, case_id: Optional[str], kind: str, camera_id: str,
    1213:def capture_refusals(log: Path) -> List[Dict[str, Any]]:
    1248:def log_tail(log: Path, lines: int = 12) -> List[str]:
    1257:def camera_views(run_dir: Path) -> Dict[str, str]:
    1273:def _camera_id_words(camera_id: str) -> str:
    1280:def histograms(rows: List[Dict[str, Any]], bins: int = HISTOGRAM_BINS) -> Dict[str, Any]:
    1315:def _reason_words(reason: Optional[str], state: str = FAILED, **numbers: Any
    1339:def progress_from(record: Dict[str, Any], rows: List[Dict[str, Any]], directory: Path,
    1418:def live_coverage(directory: Path, run_dirs: Sequence, policy: Any) -> Optional[Dict[str, Any]]:
    1446:def _control_request(directory: Path) -> Optional[str]:
- `webapp/server.py` (80 signatures, first 50 shown)
    76:def _plain(refusal: Dict[str, Any]) -> Dict[str, Any]:
    94:async def plain_language_refusals(request, call_next):
    120:class CompileRequest(BaseModel):
    139:class RunRequest(BaseModel):
    144:class CameraRequest(BaseModel):
    160:def _spec_payload(spec: ScenarioSpec) -> Dict[str, Any]:
    276:def _lighting_presets() -> Dict[str, Any]:
    285:def _validation_payload(spec: ScenarioSpec) -> Dict[str, Any]:
    301:def index() -> str:
    306:def altitude_guide_endpoint(ground_m: float = 0.0) -> JSONResponse:
    320:def compile_endpoint(request: CompileRequest) -> JSONResponse:
    468:class AircraftPlacement(BaseModel):
    484:class AircraftRequest(BaseModel):
    493:def aircraft_endpoint(request: AircraftRequest) -> JSONResponse:
    540:class CameraPromptRequest(BaseModel):
    549:def camera_prompt_endpoint(request: CameraPromptRequest) -> JSONResponse:
    616:class RepairRequest(BaseModel):
    627:def _full_violations(spec: ScenarioSpec):
    648:def _repair_verdict(spec: ScenarioSpec) -> Dict[str, Any]:
    660:def repair_endpoint(request: RepairRequest) -> JSONResponse:
    691:def repair_options_endpoint(request: RepairRequest) -> JSONResponse:
    707:def cameras_endpoint(request: CameraRequest) -> JSONResponse:
    803:class PlacerTerrainRequest(BaseModel):
    810:def camera_terrain_endpoint(request: PlacerTerrainRequest) -> JSONResponse:
    828:class PlacerRequest(BaseModel):
    839:def camera_place_endpoint(request: PlacerRequest) -> JSONResponse:
    877:def camera_placer_script():
    883:class RouteTerrainRequest(BaseModel):
    890:def route_terrain_endpoint(request: RouteTerrainRequest) -> JSONResponse:
    916:class RouteCheckRequest(BaseModel):
    929:def route_check_endpoint(request: RouteCheckRequest) -> JSONResponse:
    959:def route_map_script():
    967:def run_endpoint(request: RunRequest) -> JSONResponse:
    1131:def build_info() -> Dict[str, str]:
    1158:def status_endpoint() -> JSONResponse:
    1185:def run_state(run_id: str) -> JSONResponse:
    1193:def run_clip(run_id: str):
    1201:def run_telemetry(run_id: str):
    1212:class BakeRequest(BaseModel):
    1217:def _prefetch(spec: ScenarioSpec) -> Optional[Dict[str, Any]]:
    1228:def bake_status(latitude: float, longitude: float) -> JSONResponse:
    1235:def bake_endpoint(request: BakeRequest) -> JSONResponse:
    1252:def run_card(run_id: str):
    1264:def run_effect(run_id: str):
    1294:def run_images(run_id: str):
    1312:def run_camera_manifest(run_id: str, camera_id: str):
    1356:def run_dataset_card(run_id: str, format: str = "coco",
    1372:def run_dataset_archive(run_id: str, format: str = "coco",
    1421:def run_camera_box3d_archive(run_id: str, camera_id: str):
    1441:def run_camera_archive(run_id: str, camera_id: str):

## A11

### plan (verbatim)

### A11 · The label bundle is written; no bundle is a failure (R7, R8) — M
- **Files:** `FlightSimRenderCommandlet.cpp` (stencil ~L2876, mask writer ~L4385,
  alone passes ~L4300–4365), `core/capture/labels.py`, `webapp/runs.py`,
  `flightsim/capture.py`, `core/messages/catalog.yaml`, `tests/test_camera_labels.py`
- **Do:**
  - Every `-labels` frame writes `frames/<camera>/render.json` with a `labels`
    block: `mask`, `depth_f32`, and `objects[].alone_png` for each aircraft.
  - After `attach_engine_labels`, a run that requested a render and got
    `attached == 0` or `without_bundle > 0` refuses with `labels.no_bundle`,
    naming the camera and the frame count.
  - A headless run keeps today's behaviour.
- **Verify:**
  - Container: `pytest -q tests/test_camera_labels.py -k no_bundle`.
  - Windows: one render. Every `render.json` has `mask`, `depth_f32` and `objects`,
    the mask is not all zeros, and an alone PNG exists per aircraft per frame.

### files
- `FlightSimRenderCommandlet.cpp` -> ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp [exists]
- `core/capture/labels.py` [exists]
- `webapp/runs.py` [exists]
- `flightsim/capture.py` [exists]
- `core/messages/catalog.yaml` [exists]
- `tests/test_camera_labels.py` [exists]

### signatures
- `ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp` (6 signatures)
    818:double UFlightSimRenderCommandlet::LuminancePerUnit(double Ev100, double ExposureCompensationEv,
    826:double UFlightSimRenderCommandlet::LambertianLuminance(double IlluminanceLux, double Reflectance)
    831:int32 UFlightSimRenderCommandlet::AccumulationCount(double PredictedBlurPx, int32 RequestedK)
    836:bool UFlightSimRenderCommandlet::WriteLinearF32(const FString& Path, const TArray<float>& Values,
    852:double UFlightSimRenderCommandlet::EsfrMtf50(const TArray<float>& Luminance, int32 Width, int32 Height,
    1040:int32 UFlightSimRenderCommandlet::Main(const FString& Params)
- `core/capture/labels.py` (61 signatures, first 15 shown)
    92:def camera_axes(q: Sequence[float]) -> Tuple[Vec, Vec, Vec]:
    106:def body_to_scene(body: Vec, state: Dict) -> Vec:
    125:def to_camera(record: Dict, point: Vec, axes=None) -> Vec:
    136:def to_pixel(record: Dict, cam: Vec) -> Optional[Tuple[float, float]]:
    145:def projection_matrices(record: Dict) -> Tuple[List[List[float]], List[List[float]]]:
    165:def project_with_matrix(P: Sequence[Sequence[float]], point: Vec
    176:def _clip_box(box, width: float, height: float):
    184:def _area(box) -> float:
    188:def _project_body_box(record: Dict, state: Dict, corners_body, axes):
    212:def _quaternion_wxyz(rows) -> List[float]:
    236:def _wrap_pi(angle: float) -> float:
    240:def box3d_extras(record: Dict, state: Dict, centre_body: Vec, centre_cam: Vec,
    259:    def pixel(c):
    294:def bbox_labels(record: Dict, state: Dict, airframe: Airframe, axes) -> Dict:
    342:def keypoint_labels(record: Dict, state: Dict, airframe: Airframe,
- `webapp/runs.py` (97 signatures, first 15 shown)
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
- `flightsim/capture.py` (25 signatures, first 15 shown)
    75:def _is_library_banner(line: bytes) -> bool:
    79:class _BannerFilter:
    87:    def __init__(self, out_fd: int) -> None:
    93:    def emit(self, line: bytes) -> None:
    106:    def feed(self, chunk: bytes) -> None:
    112:    def close(self) -> None:
    121:def _relay_without_banners(read_end: int, out_fd: int) -> None:
    138:def _tail_without_banners(path: str, out_fd: int, stop: threading.Event,
    166:def _flush_c_stdout() -> None:
    180:def quiet_library_banners(enabled: bool = True):
    277:def _tornado_hazard_block(spec):
    303:def _mesh_manifest_path(spec) -> Path:
    310:def _traffic_mesh_refusal(spec):
    344:def _after_name(exc: Exception) -> str:
    353:def _scene_members(scene_path, terrain_stem):
- `core/messages/catalog.yaml` (399 signatures, first 15 shown)
    32:aircraft.exists:
    35:altitude.terrain_clearance:
    38:airspeed.stall_margin:
    41:airspeed.approach_speed:
    43:run.duration:
    46:run.rate:
    48:environment.wind_speed:
    50:environment.wind_direction:
    52:environment.surface:
    55:environment.weather_event:
    57:envelope.trim_feasible:
    63:randomization.enabled:
    65:randomization.year:
    67:randomization.day_of_year_min:
    69:randomization.day_of_year_max:
- `tests/test_camera_labels.py` (36 signatures, first 15 shown)
    42:def test_structural_to_body_mapping_against_the_fdm_s_own_geometry():
    62:def test_structural_frame_conversion_is_the_documented_one():
    68:def test_every_keypoint_carries_a_source_and_a_basis():
    79:def test_the_b747_s_nose_and_tail_are_labelled_estimates():
    93:def test_an_airframe_with_no_stated_geometry_refuses_by_name():
    101:def test_a_keypoint_naming_a_contact_the_fdm_lacks_refuses(tmp_path):
    111:def test_a_stated_point_without_a_source_refuses(tmp_path):
    121:def test_the_box_is_the_overall_extents_from_the_gear_up():
    135:def level_camera_record():
    147:def test_labels_match_hand_arithmetic():
    183:def test_the_horizon_is_the_datum_plane_s_tangent_horizon():
    221:def test_truncation_and_out_of_frame():
    247:def test_a_banked_aircraft_s_wingtips_move_in_v():
    269:def test_camera_axes_agree_with_the_verifier_s_independent_expansion():
    280:def counted(preset, camera_id, aircraft="B747", count=8):

## A12

### plan (verbatim)

### A12 · All seven annotation gates pass; one real frame becomes a fixture — S
- **Files:** `core/capture/verify.py`, `scripts/label_diagnose.py`,
  `tests/fixtures/engine_bundle_min/` (new), `tests/test_engine_bundle_golden.py` (new)
- **Do:**
  - Add a verifier check: when the aircraft is in frame and a bundle exists,
    `bbox_2d_tight` is non-null and lies inside `bbox_2d`.
  - `label_diagnose.py` prints null and filled tight-box counts per camera.
  - Commit the smallest passing run (1 camera, 1 frame, low resolution) and pin its
    tight box, visible fraction and depth median.
- **Verify:**
  - Windows: `python -m flightsim.verify runs/<id>` gives all seven gates PASS, and
    `label_diagnose.py` prints `tight null: 0`.
  - Container: `pytest -q tests/test_engine_bundle_golden.py`, with the fixture
    under 2 MB.

### files
- `core/capture/verify.py` [exists]
- `scripts/label_diagnose.py` [exists]
- `tests/fixtures/engine_bundle_min` [new]
- `tests/test_engine_bundle_golden.py` [new]

### signatures
- `core/capture/verify.py` (202 signatures, first 47 shown)
    80:class Check:
    91:    def ok(self) -> bool:
    96:    def to_dict(self) -> Dict[str, str]:
    104:class VerificationReport:
    117:    def ok(self) -> bool:
    120:    def add(self, name: str, status_or_ok, detail: str,
    126:    def failures(self) -> List[Check]:
    131:    def to_dict(self) -> Dict:
    147:    def render(self) -> str:
    179:def axes_from_quat(q: Sequence[float]):
    199:def axes_from_euler(roll_deg: float, pitch_deg: float, yaw_deg: float):
    218:def scene_to_enu(manifest: Dict):
    275:    def convert(north_m, east_m, alt_m):
    291:def _record_in_enu(record: Dict, to_enu) -> Dict:
    313:def project_point(record: Dict, point, axes=None) -> Tuple[float, float, float]:
    333:def _ray_through_pixel(record: Dict, u: float, v: float):
    348:def _closest_point_between_rays(o1, d1, o2, d2):
    369:def _spec_value(spec: Optional[Dict], name: str, default=None):
    382:def _camera_specs(manifest: Dict) -> Dict[str, Dict]:
    387:def _presets(manifest: Dict) -> Dict[str, str]:
    392:def _aircraft_point(record: Dict):
    402:def _landmark_point(landmark: Dict):
    408:def _landmarks_by_name(landmarks) -> Dict[str, Dict]:
    412:def _heading_only_components(d, heading_deg: float):
    424:def verify_intrinsics(manifest: Dict) -> Check:
    510:def _keyframed_scalar(moves: Sequence[Dict], key: str, t: float,
    532:def verify_pose_matches_spec(manifest: Dict) -> Check:
    558:    def to_local(lat_deg, lon_deg):
    707:def verify_geometry(manifest: Dict,
    762:def _render_frame_records(payload: Dict) -> List[Dict]:
    784:def _engine_landmark_pixels(run_dir) -> Dict:
    835:def _engine_frame_times(run_dir) -> Dict[str, float]:
    866:def verify_capture_times(manifest: Dict, run_dir=None,
    909:def _landmark_coverage(manifest: Dict) -> Tuple[int, float]:
    935:def verify_landmark_reprojection(manifest: Dict, run_dir=None,
    1019:def verify_triangulation(manifest: Dict, run_dir=None,
    1106:def verify_counts(manifest: Dict) -> Check:
    1156:def verify_aircraft_consistency(manifest: Dict) -> Check:
    1200:def _host_telemetry_paths(run_dir) -> List[Path]:
    1232:def verify_flight_agreement(manifest: Dict, run_dir=None,
    1415:def verify_host_determinism(run_dir=None) -> Check:
    1510:def verify_alignment(manifest_a: Dict, manifest_b: Dict,
    1582:def _aircraft_axes_enu(state: Dict):
    1591:def _body_point_enu(body, state: Dict):
    1600:def _labelled_frames(manifest: Dict):
    1605:def verify_labels(manifest: Dict) -> Check:
    1680:def verify_keypoints_in_box(manifest: Dict) -> Check:
- `scripts/label_diagnose.py` (4 signatures)
    24:def histogram(path: Path) -> Counter:
    29:def describe(counts: Counter) -> str:
    33:def camera(render_json: Path, frames: int) -> None:
    61:def main(argv=None) -> int:

## A13

### plan (verbatim)

### A13 · NEXT.md says only what is measured — XS
- **Files:** `NEXT.md`
- **Do:**
  - Rewrite gotcha 32 and the October "FIRST WINDOWS RUNS" text with the review's
    findings and A1–A12's measured results.
  - Mark the 5.7 claims as measured on one machine only, unless A1 chose 5.7 and
    all three now pass.
  - Cite the A12 run id and the fixture path.
- **Verify:** no statement in NEXT.md contradicts `docs/TOOLCHAIN.md` or the review.

### files
- `NEXT.md` [exists]

### signatures
- `NEXT.md` (11 signatures)
    1:# Resume here
    636:### Simulator terrain, sky, and water port (2026-10-05)
    667:## State
    775:## Phase 7: what exists now and what was measured
    842:## Operational gotchas (each cost real time; do not rediscover)
    893:## Everything below is Phase 5 context that remains load-bearing
    912:## Phase 7 gotchas (continuing the numbering)
    930:## Phase 8 gotchas (continuing the numbering)
    1003:## Phase 10 gotchas (continuing the numbering)
    1048:## Camera Phase 2 gotchas (continuing the numbering)
    1118:## Phase 2 gotchas (continuing the numbering)

## C1

### plan (verbatim)

### C1 · `components` block and a default loadout — S · [OWNER: the loadout]
- **Files:** `core/capture/airframe.py`, `assets/aircraft_config/A4.json`, `assets/fdm_root/aircraft/A4/A4.xml`
- **Do:**
  - Add an optional `components: [{id, class: payload|landing_gear, station?, source}]`
    block, and an A-4 `loadout` (for example a centreline drop tank on STA3 and one
    store each on STA2/STA4).
  - **Physics and picture agree:** the loaded stations' FDM point-mass weights
    are set to the drawn stores (they are 0 lb today, `loadable: false`), and the
    run trims with them.
  - The loader refuses a component that names no part (`aircraft.component_unmatched`).
- **Verify:**
  - `pytest -q tests/test_airframe.py -k components` loads the A-4 with at least one
    payload, and a dead station is refused by name.
  - A headless A-4 run with the loadout trims and verifies with no FAIL.

### files
- `core/capture/airframe.py` [exists]
- `assets/aircraft_config/A4.json` [exists]
- `assets/fdm_root/aircraft/A4/A4.xml` [exists]

### signatures
- `core/capture/airframe.py` (14 signatures)
    69:class AirframeLabelError(Exception):
    74:    def __init__(self, message: str) -> None:
    80:class Keypoint:
    87:    def to_dict(self) -> Dict:
    93:class Airframe:
    109:    def box_body_m(self) -> Dict[str, Tuple[float, float]]:
    130:    def box_corners_body_m(self) -> List[Tuple[float, float, float]]:
    137:    def to_dict(self) -> Dict:
    157:def _sha256(path: Path) -> str:
    161:def fdm_xml_path(fdm: str) -> Path:
    175:def _location_in(element) -> Tuple[float, float, float]:
    184:def _read_fdm(path: Path) -> Dict:
    218:def structural_to_body(point_in: Tuple[float, float, float],
    228:def load_airframe(aircraft: str, config_dir: Optional[Path] = None
- `assets/aircraft_config/A4.json` (12 signatures)
    2:  "name": "A4",
    3:  "fdm": "A4",
    4:  "fdm_match": [
    9:  "mesh_airframe": "Douglas A-4E Skyhawk, VA-12 livery (P3D exterior model, one rigid body, gear stowed)",
    10:  "converter": "mdl",
    11:  "source_dir": "../aircraft_models/A4",
    12:  "license": {
    18:  "surfaces": {},
    19:  "note": "Local model: assets_pipeline/a4_mdl_convert.py, not a fetched FlightGear tree. Not articulated: control surfaces, gear and speed brakes do not move.",
    20:  "labels": {
    62:  "limits": {
    85:  "loading": {
- `assets/fdm_root/aircraft/A4/A4.xml` (20 signatures)
    51: <metrics>
    77: <mass_balance>
    91:   <pointmass name="PILOT">
    100:   <pointmass name="STA1">
    109:   <pointmass name="STA2">
    118:   <pointmass name="STA3">
    127:   <pointmass name="STA4">
    136:   <pointmass name="STA5">
    146: <ground_reactions>
    281: <propulsion>
    355: <flight_control name="FCS: A-4">
    360:  <channel name="Pitch">
    381:  <channel name="Roll">
    411:  <channel name="Yaw">
    483:  <channel name="Flaps">
    505:  <channel name="Landing Gear">
    523:  <channel name="Speedbrake">
    542:  <channel name="Stores">
    550:  <channel name="Tailhook">
    577: <aerodynamics>

## C5

### plan (verbatim)

### C5 · Component label records, parent rollup, manifest v8 — M
- **Files:** `core/capture/labels.py` (`object_label_record` ~L807, `measure_object`
  ~L1140, `attach_engine_labels` ~L1670), `core/capture/manifest.py`,
  `core/capture/schema.py`, `docs/schemas/capture_manifest.v8.schema.json` (new),
  `tests/test_component_labels.py` (new)
- **Do:**
  - Emit component entries. `bbox_2d_hull` and `fraction_in_frame` come from the
    component extents projected through the same camera; the engine keys come from
    its `int_id`.
  - `measure_object` for a parent treats the IDs {parent} ∪ children as its pixels,
    and drops children from `occluded_by`.
  - Set `MANIFEST_VERSION = 8`, keeping 3–7 readable. `conventions()` documents
    `payload`, `landing_gear` and the rollup.
- **Verify:** `pytest -q tests/test_component_labels.py` covers these cases:
  1. a payload blob gives a tight box equal to the blob;
  2. an out-of-frame payload gives `bbox_2d_tight: null` with the out-of-frame basis;
  3. a payload behind the fuselage gives `visible_fraction == 0` and
     `occluded_by == [<aircraft id>]`;
  4. the aircraft's tight box includes its payload pixels;
  5. `validate_manifest` accepts v8 and v7.

### files
- `core/capture/labels.py` [exists]
- `core/capture/manifest.py` [exists]
- `core/capture/schema.py` [exists]
- `docs/schemas/capture_manifest.v8.schema.json` [new]
- `tests/test_component_labels.py` [new]

### signatures
- `core/capture/labels.py` (61 signatures, first 29 shown)
    92:def camera_axes(q: Sequence[float]) -> Tuple[Vec, Vec, Vec]:
    106:def body_to_scene(body: Vec, state: Dict) -> Vec:
    125:def to_camera(record: Dict, point: Vec, axes=None) -> Vec:
    136:def to_pixel(record: Dict, cam: Vec) -> Optional[Tuple[float, float]]:
    145:def projection_matrices(record: Dict) -> Tuple[List[List[float]], List[List[float]]]:
    165:def project_with_matrix(P: Sequence[Sequence[float]], point: Vec
    176:def _clip_box(box, width: float, height: float):
    184:def _area(box) -> float:
    188:def _project_body_box(record: Dict, state: Dict, corners_body, axes):
    212:def _quaternion_wxyz(rows) -> List[float]:
    236:def _wrap_pi(angle: float) -> float:
    240:def box3d_extras(record: Dict, state: Dict, centre_body: Vec, centre_cam: Vec,
    259:    def pixel(c):
    294:def bbox_labels(record: Dict, state: Dict, airframe: Airframe, axes) -> Dict:
    342:def keypoint_labels(record: Dict, state: Dict, airframe: Airframe,
    363:def horizon_dip_deg(height_above_datum_m: float,
    369:def _clip_line_to_image(p, q, width, height):
    401:def _horizon_v_at(record: Dict, axes, u: float, dip_deg: float) -> Optional[float]:
    443:def horizon_labels(record: Dict, terrain_elevation_m: float, axes) -> Dict:
    488:def frame_labels(record: Dict, state: Dict, airframe: Airframe,
    498:def conventions() -> Dict:
    636:def aggregate_record(object_id: str) -> Optional[Dict]:
    648:def hull_box_body_m(mesh_manifest: Optional[Dict], airframe: Airframe
    695:def mesh_tight_box_body_m(aircraft: str) -> Optional[Dict[str, Tuple[float, float]]]:
    718:def box3d_camera(record: Dict, state: Dict, box: Dict[str, Tuple[float, float]],
    748:def _box_corners(box: Dict[str, Tuple[float, float]]) -> List[Vec]:
    753:def atmospheric_transmittance(range_m: float, randomization: Optional[Dict]
    779:def fraction_in_frame(clipped, unclipped) -> Optional[float]:
    796:def not_claimed_for(obj_class: str, alone_pass: bool) -> List[str]:
- `core/capture/manifest.py` (32 signatures, first 29 shown)
    300:def software_revision(repo: Optional[Path] = None) -> str:
    315:def simulation_digest(spec) -> str:
    369:def suffix_unit(name: str) -> str:
    379:def channel_unit(name: str) -> str:
    408:def _registered_channel_units() -> Dict[str, str]:
    417:def frame_state(columns: Dict[str, Sequence[float]], index: int) -> Dict:
    428:def state_units(columns: Dict[str, Sequence[float]]) -> Dict[str, str]:
    432:def stated_conditions(spec) -> Dict[str, Dict]:
    452:def camera_angular_rate(track: PoseTrack, index: int) -> List[float]:
    484:def _file_sha256(path) -> Optional[str]:
    493:def asset_digests(spec, airframe, scene: Optional[Dict]) -> Dict:
    520:def scene_datum(heightfield, terrain_elevation_m: float) -> Dict:
    536:def georeference_card_block(frame, heightfield, terrain_elevation_m: float) -> Dict:
    553:def world_scene(scene: Optional[Dict]) -> tuple:
    582:def frame_filename(camera_id: str, index: int) -> str:
    593:def build_capture_manifest(spec, columns: Dict[str, Sequence[float]],
    696:    def mesh_manifest_for(name: str) -> Optional[Dict]:
    1026:def _flag_records(objects, records: List[Dict]) -> List[Dict]:
    1037:def _object_records(objects, record, primary_state, primary_airframe, axes,
    1063:def write_capture_manifest(manifest: Dict, directory) -> Path:
    1101:def frame_sidecar_name(file: str) -> str:
    1108:def _cut_edges(full, width: float, height: float) -> List[str]:
    1121:def truncation_section(manifest: Dict, record: Dict) -> Dict:
    1184:def _range_m(entry: Dict) -> Optional[float]:
    1191:def _occlusion_entry(entry: Dict, class_of: Dict[str, str]) -> Dict:
    1229:def _previous_record(manifest: Dict, record: Dict) -> Optional[Dict]:
    1243:def _delta(now, before) -> Optional[float]:
    1249:def occlusion_section(manifest: Dict, record: Dict, previous="auto") -> Dict:
    1257:    def planes(rec):
- `core/capture/schema.py` (6 signatures)
    50:class SchemaError(ValueError):
    54:def schema_path(manifest: Dict[str, Any]) -> Path:
    59:def load_schema(path) -> Dict[str, Any]:
    68:def _check_keywords(node: Any, where: str) -> None:
    87:def validate(instance: Any, schema: Dict[str, Any],
    152:def validate_manifest(manifest: Dict[str, Any]) -> List[str]:

## C6

### plan (verbatim)

### C6 · Verifier and exporters know the components — M
- **Files:** `core/capture/verify.py`, `core/dataset/export.py`, `tests/test_dataset_boxes.py`, `tests/test_annotation_gates.py`
- **Do:**
  - The verifier checks that each component's tight box lies within its own hull
    and its parent's tight box.
  - **`component_coverage`:** every frame with payload pixels in the mask carries a
    payload record. This is acceptance criterion 3.
  - COCO, YOLO and VOC export `payload` (and `landing_gear`) as their own
    categories; the independent readers re-read them.
- **Verify:** `pytest -q -k component` passes, and a mutant that drops the payload
  record fails `component_coverage`.

### files
- `core/capture/verify.py` [exists]
- `core/dataset/export.py` [exists]
- `tests/test_dataset_boxes.py` [exists]
- `tests/test_annotation_gates.py` [exists]

### signatures
- `core/capture/verify.py` (202 signatures, first 24 shown)
    80:class Check:
    91:    def ok(self) -> bool:
    96:    def to_dict(self) -> Dict[str, str]:
    104:class VerificationReport:
    117:    def ok(self) -> bool:
    120:    def add(self, name: str, status_or_ok, detail: str,
    126:    def failures(self) -> List[Check]:
    131:    def to_dict(self) -> Dict:
    147:    def render(self) -> str:
    179:def axes_from_quat(q: Sequence[float]):
    199:def axes_from_euler(roll_deg: float, pitch_deg: float, yaw_deg: float):
    218:def scene_to_enu(manifest: Dict):
    275:    def convert(north_m, east_m, alt_m):
    291:def _record_in_enu(record: Dict, to_enu) -> Dict:
    313:def project_point(record: Dict, point, axes=None) -> Tuple[float, float, float]:
    333:def _ray_through_pixel(record: Dict, u: float, v: float):
    348:def _closest_point_between_rays(o1, d1, o2, d2):
    369:def _spec_value(spec: Optional[Dict], name: str, default=None):
    382:def _camera_specs(manifest: Dict) -> Dict[str, Dict]:
    387:def _presets(manifest: Dict) -> Dict[str, str]:
    392:def _aircraft_point(record: Dict):
    402:def _landmark_point(landmark: Dict):
    408:def _landmarks_by_name(landmarks) -> Dict[str, Dict]:
    412:def _heading_only_components(d, heading_deg: float):
- `core/dataset/export.py` (78 signatures, first 24 shown)
    254:class ExportError(ValueError):
    255:    def __init__(self, constraint: str, message: str):
    264:class Run:
    276:    def name(self) -> str:
    280:    def verification_bound(self) -> bool:
    284:    def airframes(self) -> List[str]:
    299:def discover_runs(paths: Iterable) -> List[Path]:
    342:def manifest_digest(directory) -> str:
    348:def bind_verification(directory) -> Path:
    364:def render_provenance(directory) -> Dict[str, Dict[str, Any]]:
    389:def engine_label_evidence(directory, manifest: Dict[str, Any]) -> Optional[str]:
    416:def load_run(directory) -> Run:
    472:def run_taxonomy(manifest: Dict[str, Any]) -> Optional[List[str]]:
    513:def dataset_taxonomy(samples: Sequence["Sample"]) -> Tuple[List[str], str]:
    539:def refuse_classes_outside_taxonomy(samples: Sequence["Sample"],
    549:def class_index(obj: Dict[str, Any], names: Sequence[str]) -> int:
    570:class Sample:
    583:    def simulation_digest(self) -> str:
    587:    def width(self) -> int:
    591:    def height(self) -> int:
    595:    def aircraft(self) -> str:
    599:def image_path(run: Run, record: Dict[str, Any], image: str) -> Path:
    606:def label_file_path(run: Run, record: Dict[str, Any], suffix: str) -> Path:
    613:def sample_labels(record: Dict[str, Any], image: str) -> Dict[str, Any]:
- `tests/test_dataset_boxes.py` (19 signatures)
    51:def engine_run(tmp_path_factory):
    66:def no_mesh_licence(monkeypatch):
    75:def _manifest(run: Path):
    79:def _area(box):
    83:def _expected(run: Path):
    110:def read_shards_with_webdataset(root: Path):
    129:def _yolo(root: Path):
    138:def _voc(root: Path):
    149:def _kitti(root: Path):
    156:def test_the_fixture_has_mask_boxes_that_differ_from_the_projected_ones(engine_run):
    167:def test_every_format_writes_the_mask_box_and_keeps_the_projected_one(
    256:def test_the_sensor_image_keeps_the_projected_box(engine_run, tmp_path, no_mesh_licence):
    274:def test_a_headless_run_keeps_the_projected_box_and_the_card_says_so(engine_run, tmp_path):
    302:def test_engine_labels_whose_gates_did_not_run_refuse_by_name(engine_run, tmp_path):
    326:def test_a_verdict_without_the_gates_refuses_and_one_with_them_loads(engine_run, tmp_path):
    343:def test_a_render_json_bundle_counts_and_a_run_without_one_is_unaffected(engine_run, tmp_path):
    371:def test_every_object_record_carries_fraction_in_frame_beside_truncation(engine_run):
    392:def test_fraction_in_frame_is_the_area_ratio_and_null_with_the_unclipped_box():
    401:def test_the_v7_schema_takes_fraction_in_frame_and_refuses_one_out_of_range():
- `tests/test_annotation_gates.py` (84 signatures, first 24 shown)
    120:def fabricated_spec():
    135:def fabricated_manifest(spec, mesh=None, citation=None):
    161:def fabricated_mesh_manifest(airframe_block, taller=1.0):
    189:def _rotation_body_to_ned(roll_deg, pitch_deg, yaw_deg):
    206:def axes_enu(roll_deg, pitch_deg, yaw_deg):
    215:def box_in_world(state, box_body, offset_body=(0.0, 0.0, 0.0)):
    231:def pixel_rays(record):
    246:def box_depth(record, rays, centre, axes, half):
    272:def ground_depth(record, rays, terrain_alt_m=0.0):
    281:def _pinhole(record, point):
    293:def fabricate_run(run_dir, offset_body=(0.0, 0.0, 0.0), attach=True,
    425:def clean_run(tmp_path_factory):
    432:def shifted_run(tmp_path_factory):
    441:def run(clean_run, tmp_path):
    448:def checks_of(run_dir, other=None):
    453:def manifest_of(run_dir):
    457:def _render_json(run_dir, camera):
    461:def _edit_render_json(run_dir, camera, edit):
    468:def _reattach(run_dir):
    507:def test_the_painted_primary_lands_on_the_producers_box(clean_run):
    527:def test_the_scene_has_an_occlusion_to_grade(clean_run):
    540:def test_the_clean_fabricated_run_passes_every_annotation_check(clean_run):
    566:def test_a_pass_carries_no_failure_name_and_a_fail_carries_its_own():
    574:def test_every_gate_is_not_run_without_a_bundle_or_objects(clean_run, tmp_path):
