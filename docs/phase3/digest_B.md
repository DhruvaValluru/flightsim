# Digest B

Plan: tasks/phase3_todo.md · boxes: B1, B2, B3, B4

## B1

### plan (verbatim)

### B1 · Python dependencies locked with hashes — S
- **Files:** `requirements.lock` (new, `pip-compile --generate-hashes`), `.github/workflows/ci.yml`, `scripts/deploy_windows.ps1`
- **Do:** CI and the installer install from the lock. `requirements.txt` stays the
  human-edited source.
- **Verify:** in a fresh venv, `pip install --require-hashes -r requirements.lock && pytest -q`
  passes on all three CI operating systems.

### files
- `requirements.lock` [new]
- `.github/workflows/ci.yml` [exists]
- `scripts/deploy_windows.ps1` [exists]

### signatures
- `.github/workflows/ci.yml` (3 signatures)
    5:name: ci
    7:on:
    12:jobs:
- `scripts/deploy_windows.ps1` (6 signatures)
    34:param(
    50:function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
    52:function Refresh-Path {
    58:function Require-Winget {
    83:function Probe {
    94:function Find-Python {

## B2

### plan (verbatim)

### B2 · One manifest for every other tool — M
- **Files:** `toolchain.json` (new: engine `<PIN>` and patch, MSVC, Windows SDK,
  Cesium for Unreal, ffmpeg, Python), `scripts/ue_preflight.ps1`, `core/util/platform.py`
- **Do:** `platform.py` reads the pin from `toolchain.json`, replacing the A2
  literal. Preflight compares each installed tool and refuses by name with
  `toolchain.<tool>_mismatch`.
- **Verify:** Windows. Preflight prints one `OK <tool> <version>` per entry, and a
  wrong ffmpeg version in the file makes it exit non-zero.

### files
- `toolchain.json` [new]
- `scripts/ue_preflight.ps1` [exists]
- `core/util/platform.py` [exists]

### signatures
- `scripts/ue_preflight.ps1` (3 signatures)
    20:function Probe {
    29:function Say($label, $msg)  { "  {0,-34} {1}" -f $label, $msg | Write-Host }
    30:function Fail($label, $msg) { "  {0,-34} {1}" -f $label, $msg | Write-Host; $script:status = 1 }
- `core/util/platform.py` (17 signatures)
    33:class FfmpegMissingError(RuntimeError):
    39:def os_name() -> str:
    48:def is_mac() -> bool:
    68:def find_ffmpeg() -> Path:
    105:def find_mono_font() -> Optional[str]:
    121:def mono_fonts(sizes: Tuple[int, ...]) -> List:
    193:def ue_platform_refusal() -> str:
    212:def find_ue_root() -> Optional[Path]:
    228:def ue_editor_path() -> Optional[Path]:
    240:def ue_bridge_binary(repo: Path) -> Path:
    248:def ue_runner_command(repo: Path, script_stem: str) -> List[str]:
    261:def ue_available() -> bool:
    287:def plugin_source_hash(repo: Path) -> str:
    307:def read_build_stamp(repo: Path) -> Optional[dict]:
    316:def _major_minor(version: object) -> str:
    320:def binary_stale_check(repo: Path) -> Optional[dict]:
    350:def binary_stale_reason(repo: Path) -> Optional[str]:

## B3

### plan (verbatim)

### B3 · A test keeps the pins in one place — XS
- **Files:** `tests/test_toolchain_pins.py`
- **Do:** assert that `toolchain.json` == `EngineAssociation` == both
  `IncludeOrderVersion` == `UE_ENGINE_VERSION`, and that `requirements.lock`
  covers `requirements.txt`.
- **Verify:** it passes; changing one pin by hand fails with the file named.

### files
- `tests/test_toolchain_pins.py` [missing]

### signatures
(no existing source files)

## B4

### plan (verbatim)

### B4 · Picture quality re-measured on the pinned engine — M
- **Files:** `experiments/gate6_visual.py`, `ue/Config/DefaultEngine.ini`,
  `core/sky/plan.py`, `docs/VALIDITY.md`
- **Do:**
  - `<PIN>` is 5.7: re-derive the palette and exposure biases from probe
    renders; the existing 5.5 numbers are history, kept on lines marked measured.
  - Labels do not depend on the look, so this cannot break A11–A12.
- **Verify:** Windows. `gate6_visual.py` (measure and beauty) passes,
  `gate10_render_repro.py` gives a bounded verdict, and the A12 fixture still passes.

### files
- `experiments/gate6_visual.py` [exists]
- `ue/Config/DefaultEngine.ini` [exists]
- `core/sky/plan.py` [exists]
- `docs/VALIDITY.md` [exists]

### signatures
- `experiments/gate6_visual.py` (38 signatures, first 24 shown)
    196:def koschmieder_fog_density(visibility_km: float) -> float:
    234:def load_rgb(path: Path):
    242:def luminance(rgb):
    246:def write_png_rgb(path: Path, rgb) -> Path:
    255:    def chunk(tag: bytes, data: bytes) -> bytes:
    269:def patch_mean(image, px: float, py: float, half: int = 6) -> float:
    283:class Check:
    288:    def render(self) -> str:
    292:def measure_extinction(frames_dir: Path) -> Check:
    315:    def patch_rgb(px: float, py: float, half: int = 6):
    341:def darkened_mask(with_path: Path, without_path: Path):
    347:def measure_valley_shadow(still: Path, still_no_shadows: Path) -> Check:
    360:def measure_aircraft_shadow(shadow_still: Path, hidden_still: Path) -> Check:
    379:def measure_exposure(frames_dir: Path) -> Check:
    399:def sky_excursion(frames_dir: Path) -> float:
    409:def measure_exposure_control(control_dir: Path) -> Check:
    437:class LookClause:
    446:    def ran(self) -> bool:
    450:    def ok(self) -> bool:
    453:    def render(self) -> str:
    461:def _last_frame(frames_dir: Path) -> Path:
    466:def _look_applied(frames_dir: Path) -> dict:
    471:def changed_mask(a_path: Path, b_path: Path):
    480:def _band_count(mask, rows: Tuple[int, int]) -> int:
- `ue/Config/DefaultEngine.ini` (35 signatures, first 24 shown)
    1:[/Script/Engine.Engine]
    6:bUseFixedFrameRate=True
    7:FixedFrameRate=120.000000
    9:[/Script/Engine.RendererSettings]
    67:r.CustomDepth=3
    68:r.DynamicGlobalIlluminationMethod=1
    69:r.ReflectionMethod=1
    70:r.Lumen.HardwareRayTracing=False
    71:r.GenerateMeshDistanceFields=True
    72:r.Shadow.Virtual.Enable=1
    73:r.Nanite.ProjectEnabled=True
    74:r.AntiAliasingMethod=4
    75:r.DefaultFeature.AutoExposure.ExtendDefaultLuminanceRange=True
    76:r.Substrate=False
    93:r.VirtualTextures=True
    94:r.MegaLights.EnableForProject=False
    96:[SystemSettings]
    100:landscape.RenderNanite=1
    102:[/Script/WindowsTargetPlatform.WindowsTargetSettings]
    106:DefaultGraphicsRHI=DefaultGraphicsRHI_DX12
    110:[/Script/EngineSettings.GeneralProjectSettings]
    111:ProjectName=FlightSim
    113:[/Script/AndroidFileServerEditor.AndroidFileServerRuntimeSettings]
    114:bEnablePlugin=True
- `core/sky/plan.py` (16 signatures)
    105:class SkyError(ValueError):
    113:class Instant:
    119:def _date_for(time_value: str, weather_date: Optional[str]) -> Tuple[date, str]:
    128:def scene_date(time_value: str, weather_date: Optional[str]) -> Tuple[date, str]:
    138:def _solar_midnight_utc(day: date, lon_deg: float) -> datetime:
    144:def _elevations(start: datetime, lat: float, lon: float,
    153:def _bisect(a: datetime, b: datetime, fn) -> datetime:
    164:def resolve_instant(time_value: str, weather_date: Optional[str],
    235:def _twilight_lux(el: float) -> float:
    249:def sun_horizontal_lux(el: float) -> float:
    265:def ev100_for(horizontal_lux: float) -> float:
    284:def load_catalogue(path: Path = STAR_CATALOGUE):
    302:def star_batches(when: datetime, lat: float, lon: float,
    354:def post_process_for(preset: str) -> Dict:
    363:def _direction(body: astro.Body) -> Dict:
    370:def plan_sky(time_value: str, weather_date: Optional[str], lat: float,
- `docs/VALIDITY.md` (45 signatures, first 24 shown)
    1:# What this simulation can and cannot support
    17:## 1. What is currently supported
    178:### The two on-screen clauses
    228:### Breadth: the same comparison across the envelope, and in wind
    287:### A third upstream plugin bug, found by the achieved-condition check
    338:## 2. What is NOT supported, and must not be claimed
    340:### 2.1 No aircraft here has validated fidelity
    363:### 2.2 The trimmable envelope is a property of the tables, not the aircraft
    370:### 2.3 A mass-held run is not a realistic run
    382:### 2.4 Derived speeds describe the model, not the aircraft
    396:### 2.5 A rule-based parser is not language understanding
    408:### 2.6 Control gains are tuned for one airframe at one condition
    419:### 2.7 Settling criteria deviate from §6.5, deliberately
    431:### 2.8 The orographic model is the weakest thing in the repository
    463:### 2.9 Turbulence intensity words are a mapping, not a measurement
    474:### 2.9b Thermals are Allen's model, pinned to its own check case
    491:### 2.10 Terrain caveats
    534:### 2.10a Place names are looked up, not surveyed
    550:### 2.10b Surface classes are two documented couplings, not ground cover
    567:### 2.10c Severe weather: one composition and one kinematic vortex
    584:### 2.10d The physical sky is computed exactly and rendered unmeasured
    644:### 2.11 Validation is mostly inconclusive, and that is the finding
    655:### 2.12 The credibility scorecard is mostly below its own threshold
    667:### 2.13 Not yet built
