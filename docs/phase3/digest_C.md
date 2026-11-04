# Digest C

Plan: tasks/phase3_todo.md · boxes: C1, C2, C3, C4, C5, C6, C7

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
- `core/capture/airframe.py` (19 signatures)
    69:class AirframeLabelError(Exception):
    74:    def __init__(self, message: str) -> None:
    79:class ComponentUnmatchedError(AirframeLabelError):
    84:    def __init__(self, message: str) -> None:
    96:class Component:
    107:    def to_dict(self) -> Dict:
    114:class Keypoint:
    121:    def to_dict(self) -> Dict:
    127:class Airframe:
    146:    def box_body_m(self) -> Dict[str, Tuple[float, float]]:
    167:    def box_corners_body_m(self) -> List[Tuple[float, float, float]]:
    174:    def to_dict(self) -> Dict:
    196:def _sha256(path: Path) -> str:
    200:def fdm_xml_path(fdm: str) -> Path:
    214:def _location_in(element) -> Tuple[float, float, float]:
    223:def _read_fdm(path: Path) -> Dict:
    263:def _read_components(config: Dict, path: Path, model: Dict,
    326:def structural_to_body(point_in: Tuple[float, float, float],
    336:def load_airframe(aircraft: str, config_dir: Optional[Path] = None
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
    97:  "limits": {
    120:  "loading": {
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

## C2

### plan (verbatim)

### C2 · The converter exports each loaded station as its own mesh — M
- **Files:** `assets_pipeline/a4_mdl_convert.py`, `assets_pipeline/mdl_scene.py`, `tests/test_a4_mesh.py`
- **Do:**
  - Evaluate the scene with `REST_ENV` plus each loaded station's
    `STAn_LOAD`/`RACK`/`RAIL`. The body keeps the rest-environment parts; each
    station's added parts become their own OBJ.
  - `mesh_manifest.json` gains `components[]` (id, class, extents, origin) and a
    version bump; a stale manifest is re-converted.
- **Verify:** `python -m assets_pipeline.a4_mdl_convert assets/aircraft_config/A4.json`,
  then the manifest has a `payload` component per loaded station whose triangle count
  matches the measured delta (STA3 load 1: +14,612 over rest).

### files
- `assets_pipeline/a4_mdl_convert.py` [exists]
- `assets_pipeline/mdl_scene.py` [exists]
- `tests/test_a4_mesh.py` [exists]

### signatures
- `assets_pipeline/a4_mdl_convert.py` (3 signatures)
    69:def _to_ue(v: np.ndarray) -> np.ndarray:
    73:def convert(config_path: Path, out_root: Path, repo_root: Path) -> Path:
    222:def main(argv=None) -> int:
- `assets_pipeline/mdl_scene.py` (12 signatures)
    60:class Part:
    70:def evaluate(expression: str, env: Dict[str, float]) -> Optional[bool]:
    97:class MdlScene:
    98:    def __init__(self, path: Path) -> None:
    142:    def _chunks(self, off: int, end: int):
    149:    def _blob(self, key: bytes) -> bytes:
    154:    def _read_conditions(blob: bytes) -> List[tuple]:
    167:    def part_count(self) -> int:
    170:    def node_visible(self, node: int, env: Dict[str, float]) -> bool:
    180:    def world_matrix(self, node: int) -> np.ndarray:
    189:    def part_local(self, index: int) -> tuple:
    197:    def parts(self, env: Optional[Dict[str, float]] = None,
- `tests/test_a4_mesh.py` (10 signatures)
    23:def scene():
    27:def test_scene_decodes_a_complete_visible_airframe(scene):
    38:def test_horizontal_tail_is_found_where_the_fdm_expects_it():
    45:def test_fdm_tail_metrics_and_pitch_terms_follow_the_mesh():
    60:def test_stores_are_hidden_and_gear_is_stowed_at_rest(scene):
    65:def test_visibility_expressions():
    75:def test_conversion_writes_a_valid_manifest_and_obj(tmp_path):
    106:def test_converted_bounds_agree_with_the_flight_models_geometry(tmp_path):
    120:def test_importer_builds_a_local_model_without_fetching(monkeypatch, tmp_path):
    141:def test_unreal_host_gear_list_matches_the_repo_owned_airframes():

## C3

### plan (verbatim)

### C3 · The card carries component objects — S
- **Files:** `core/scenario/card.py`, `core/capture/labels.py` (the annotation block)
- **Do:** each component is written to the card's object list with `int_id` (from
  the band), `parent`, `class` and its mesh name.
- **Verify:** `pytest -q -k card_components`. The A-4 card lists the components
  with unique IDs in the band, and a traffic aircraft's ID never collides with them.

### files
- `core/scenario/card.py` [exists]
- `core/capture/labels.py` [exists]

### signatures
- `core/scenario/card.py` (16 signatures)
    36:def discovered_engine_mixture(spec: ScenarioSpec) -> float:
    61:    def attempt(mixture: float):
    121:def atmosphere_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    137:def loading_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    162:def gust_table_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    190:def layered_wind_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    209:def failure_schedule_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    233:def icing_schedule_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    259:def wake_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    288:def weather_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    303:def world_look_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    335:def derived_aircraft_card_block(spec: ScenarioSpec) -> Optional[Dict[str, object]]:
    377:def google_tiles_requested() -> bool:
    393:def google_tiles_terrain_refusal(heightfield, latitude_deg: Optional[float] = None,
    432:def google_tiles_card_block(latitude_deg: float, longitude_deg: float) -> Dict[str, object]:
    449:def write_run_card(spec: ScenarioSpec, path: Path,
- `core/capture/labels.py` (64 signatures, first 52 shown)
    93:def camera_axes(q: Sequence[float]) -> Tuple[Vec, Vec, Vec]:
    107:def body_to_scene(body: Vec, state: Dict) -> Vec:
    126:def to_camera(record: Dict, point: Vec, axes=None) -> Vec:
    137:def to_pixel(record: Dict, cam: Vec) -> Optional[Tuple[float, float]]:
    146:def projection_matrices(record: Dict) -> Tuple[List[List[float]], List[List[float]]]:
    166:def project_with_matrix(P: Sequence[Sequence[float]], point: Vec
    177:def _clip_box(box, width: float, height: float):
    185:def _area(box) -> float:
    189:def _project_body_box(record: Dict, state: Dict, corners_body, axes):
    213:def _quaternion_wxyz(rows) -> List[float]:
    237:def _wrap_pi(angle: float) -> float:
    241:def box3d_extras(record: Dict, state: Dict, centre_body: Vec, centre_cam: Vec,
    260:    def pixel(c):
    295:def bbox_labels(record: Dict, state: Dict, airframe: Airframe, axes) -> Dict:
    343:def keypoint_labels(record: Dict, state: Dict, airframe: Airframe,
    364:def horizon_dip_deg(height_above_datum_m: float,
    370:def _clip_line_to_image(p, q, width, height):
    402:def _horizon_v_at(record: Dict, axes, u: float, dip_deg: float) -> Optional[float]:
    444:def horizon_labels(record: Dict, terrain_elevation_m: float, axes) -> Dict:
    489:def frame_labels(record: Dict, state: Dict, airframe: Airframe,
    499:def conventions() -> Dict:
    653:def aggregate_record(object_id: str) -> Optional[Dict]:
    665:def hull_box_body_m(mesh_manifest: Optional[Dict], airframe: Airframe
    712:def mesh_tight_box_body_m(aircraft: str) -> Optional[Dict[str, Tuple[float, float]]]:
    735:def box3d_camera(record: Dict, state: Dict, box: Dict[str, Tuple[float, float]],
    765:def _box_corners(box: Dict[str, Tuple[float, float]]) -> List[Vec]:
    770:def atmospheric_transmittance(range_m: float, randomization: Optional[Dict]
    796:def fraction_in_frame(clipped, unclipped) -> Optional[float]:
    813:def not_claimed_for(obj_class: str, alone_pass: bool) -> List[str]:
    824:def component_label_record(obj, parent_entry: Dict, record: Dict,
    871:def tight_box_basis(entry: Dict) -> Optional[str]:
    889:def object_label_record(obj, record: Dict, state: Optional[Dict],
    983:def _read_id_png(path: Path):
    997:def read_depth_f32(path: Path, width: int, height: int):
    1012:def read_depth_png(path: Path, scale_m: float, saturation_m: float):
    1066:def read_rgb16_png(path: Path):
    1088:def write_rgb16_png(path: Path, rgb) -> Path:
    1107:    def chunk(kind: bytes, body: bytes) -> bytes:
    1118:def encode_normals(normals):
    1128:def read_normal_png(path: Path):
    1139:def read_flow_f32(path: Path, width: int, height: int):
    1155:def read_albedo_png(path: Path):
    1163:def passes_declared(engine_record: Dict) -> Dict[str, Optional[str]]:
    1174:def passes_record(files_per_frame: Sequence[int], words: Sequence[str]):
    1225:def measure_object(mask, depth, int_id: int, alone=None,
    1304:def amodal_labels(alone, mask, int_id: int, alone_file: Optional[str]) -> Dict:
    1395:class LandcoverLabelError(Exception):
    1403:    def __init__(self, message: str) -> None:
    1408:def _sha256_file(path: Path) -> str:
    1414:def landcover_document_for(terrain) -> Optional[Path]:
    1425:def landcover_legend() -> List[Dict]:
    1437:def manifest_landcover_block(document) -> Optional[Dict]:

## C4

### plan (verbatim)

### C4 · The engine stencils components and draws the parent's alone pass whole — M · Windows
- **Files:** `scripts/ue_import_aircraft.py`, `FlightSimRenderCommandlet.cpp`,
  `FlightSimScenarioWorld.cpp`, `FlightSimScenarioWorld.h`
- **Do:**
  - Import one `SM_A4_<component>` per component and attach it under the
    aircraft's `MeshOrigin`.
  - Set each component's stencil from the card.
  - The aircraft's alone pass draws the aircraft and its components together, so the
    parent's amodal box includes its stores.
  - Each component gets its own alone pass.
- **Verify:** Windows. One A-4 still with `-labels`:
  - `render.json` `labels.objects[]` has at least one object with `parent` set and
    `class == "payload"`;
  - `numpy.unique(mask)` contains its `int_id`;
  - the aircraft's tight box is still filled (A12 unchanged).

### files
- `scripts/ue_import_aircraft.py` [exists]
- `FlightSimRenderCommandlet.cpp` -> ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp [exists]
- `FlightSimScenarioWorld.cpp` -> ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimScenarioWorld.cpp [exists]
- `FlightSimScenarioWorld.h` -> ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public/FlightSimScenarioWorld.h [exists]

### signatures
- `scripts/ue_import_aircraft.py` (4 signatures)
    29:def section_triangles(mesh):
    45:def _set_if_present(struct, name, value):
    53:def import_part(obj_path, destination, part, expected_triangles):
    115:def run():
- `ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp` (6 signatures)
    818:double UFlightSimRenderCommandlet::LuminancePerUnit(double Ev100, double ExposureCompensationEv,
    826:double UFlightSimRenderCommandlet::LambertianLuminance(double IlluminanceLux, double Reflectance)
    831:int32 UFlightSimRenderCommandlet::AccumulationCount(double PredictedBlurPx, int32 RequestedK)
    836:bool UFlightSimRenderCommandlet::WriteLinearF32(const FString& Path, const TArray<float>& Values,
    852:double UFlightSimRenderCommandlet::EsfrMtf50(const TArray<float>& Luminance, int32 Width, int32 Height,
    1040:int32 UFlightSimRenderCommandlet::Main(const FString& Params)
- `ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimScenarioWorld.cpp` (29 signatures, first 23 shown)
    294:double FFlightSimScenarioWorld::ReadProperty(const TCHAR* Name) const
    830:bool FFlightSimScenarioWorld::ReadCard(const FString& Path,
    1442:bool FFlightSimScenarioWorld::Build(const FFlightSimScenarioCard& Card, FString& Error)
    1466:bool FFlightSimScenarioWorld::BuildInto(UWorld* LiveWorld,
    1481:bool FFlightSimScenarioWorld::Populate(const FFlightSimScenarioCard& Card,
    2126:void FFlightSimScenarioWorld::ApplyTrafficPoses(double TimeSeconds)
    2191:void FFlightSimScenarioWorld::ConfigureTurbulence(const FFlightSimScenarioCard& Card)
    2209:bool FFlightSimScenarioWorld::BeginPlay(FString& Error)
    2228:bool FFlightSimScenarioWorld::TrimInWind(const FFlightSimScenarioCard& Card,
    2306:bool FFlightSimScenarioWorld::VerifyTrimmedCondition(const FFlightSimScenarioCard& Card,
    2395:void FFlightSimScenarioWorld::LatchTrimmedControls(bool bMassHeld)
    2431:bool FFlightSimScenarioWorld::BuildTerrainCollision(
    2502:void FFlightSimScenarioWorld::LocalSceneCoords(double OriginXMetres,
    2518:double FFlightSimScenarioWorld::RotorW20Fps(double NorthMetres,
    2534:double FFlightSimScenarioWorld::LogProfileSpeedMps(double AglMetres) const
    2549:double FFlightSimScenarioWorld::ThermalWMps(double NorthMetres,
    2649:void FFlightSimScenarioWorld::ApplyStepWrites(
    2899:void FFlightSimScenarioWorld::LayeredWindAt(const FFlightSimScenarioCard& Card,
    2958:bool FFlightSimScenarioWorld::BindPhysicsBlocks(const FFlightSimScenarioCard& Card,
    3086:void FFlightSimScenarioWorld::ApplyPhysicsStepWrites(const FFlightSimScenarioCard& Card)
    3237:double FFlightSimScenarioWorld::HostChannel(const FString& Name) const
    3313:void FFlightSimScenarioWorld::UnregisterHostChannels()
    3325:bool FFlightSimScenarioWorld::ReadHostChannel(const UJSBSimMovementComponent* InMovement,
- `ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public/FlightSimScenarioWorld.h` (30 signatures, first 23 shown)
    22:class AActor;
    23:class AGeoReferencingSystem;
    24:class FJsonObject;
    25:class UJSBSimMovementComponent;
    26:class UWorld;
    33:struct FFlightSimControlInput
    46:struct FFlightSimSceneObject
    63:struct FFlightSimTrafficTrack
    88:struct FFlightSimFailureEvent
    102:struct FFlightSimScenarioCard
    374:class FLIGHTSIMBRIDGE_API FFlightSimScenarioWorld
    377:	static bool ReadCard(const FString& Path, FFlightSimScenarioCard& Out, FString& Error);
    382:	bool Build(const FFlightSimScenarioCard& Card, FString& Error);
    406:	void ApplyStepWrites(const FFlightSimScenarioCard& Card, double TimeSeconds);
    411:	bool Crashed(double TimeSeconds, FString& Error) const;
    418:	bool AirframeImpact(double TimeSeconds, FString& Error) const;
    429:	bool BeginPlay(FString& Error);
    438:	bool TrimInWind(const FFlightSimScenarioCard& Card, FString& Error);
    445:	bool VerifyTrimmedCondition(const FFlightSimScenarioCard& Card, FString& Error);
    453:	void LatchTrimmedControls(bool bMassHeld);
    459:	void ConfigureTurbulence(const FFlightSimScenarioCard& Card);
    485:	double LogProfileSpeedMps(double AglMetres) const;
    499:	void Teardown();

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
- `docs/schemas/capture_manifest.v8.schema.json` [exists]
- `tests/test_component_labels.py` [exists]

### signatures
- `core/capture/labels.py` (64 signatures, first 17 shown)
    93:def camera_axes(q: Sequence[float]) -> Tuple[Vec, Vec, Vec]:
    107:def body_to_scene(body: Vec, state: Dict) -> Vec:
    126:def to_camera(record: Dict, point: Vec, axes=None) -> Vec:
    137:def to_pixel(record: Dict, cam: Vec) -> Optional[Tuple[float, float]]:
    146:def projection_matrices(record: Dict) -> Tuple[List[List[float]], List[List[float]]]:
    166:def project_with_matrix(P: Sequence[Sequence[float]], point: Vec
    177:def _clip_box(box, width: float, height: float):
    185:def _area(box) -> float:
    189:def _project_body_box(record: Dict, state: Dict, corners_body, axes):
    213:def _quaternion_wxyz(rows) -> List[float]:
    237:def _wrap_pi(angle: float) -> float:
    241:def box3d_extras(record: Dict, state: Dict, centre_body: Vec, centre_cam: Vec,
    260:    def pixel(c):
    295:def bbox_labels(record: Dict, state: Dict, airframe: Airframe, axes) -> Dict:
    343:def keypoint_labels(record: Dict, state: Dict, airframe: Airframe,
    364:def horizon_dip_deg(height_above_datum_m: float,
    370:def _clip_line_to_image(p, q, width, height):
- `core/capture/manifest.py` (32 signatures, first 17 shown)
    307:def software_revision(repo: Optional[Path] = None) -> str:
    322:def simulation_digest(spec) -> str:
    376:def suffix_unit(name: str) -> str:
    386:def channel_unit(name: str) -> str:
    415:def _registered_channel_units() -> Dict[str, str]:
    424:def frame_state(columns: Dict[str, Sequence[float]], index: int) -> Dict:
    435:def state_units(columns: Dict[str, Sequence[float]]) -> Dict[str, str]:
    439:def stated_conditions(spec) -> Dict[str, Dict]:
    459:def camera_angular_rate(track: PoseTrack, index: int) -> List[float]:
    491:def _file_sha256(path) -> Optional[str]:
    500:def asset_digests(spec, airframe, scene: Optional[Dict]) -> Dict:
    527:def scene_datum(heightfield, terrain_elevation_m: float) -> Dict:
    543:def georeference_card_block(frame, heightfield, terrain_elevation_m: float) -> Dict:
    560:def world_scene(scene: Optional[Dict]) -> tuple:
    589:def frame_filename(camera_id: str, index: int) -> str:
    600:def build_capture_manifest(spec, columns: Dict[str, Sequence[float]],
    703:    def mesh_manifest_for(name: str) -> Optional[Dict]:
- `core/capture/schema.py` (6 signatures)
    50:class SchemaError(ValueError):
    54:def schema_path(manifest: Dict[str, Any]) -> Path:
    59:def load_schema(path) -> Dict[str, Any]:
    68:def _check_keywords(node: Any, where: str) -> None:
    87:def validate(instance: Any, schema: Dict[str, Any],
    152:def validate_manifest(manifest: Dict[str, Any]) -> List[str]:
- `docs/schemas/capture_manifest.v8.schema.json` (68 signatures, first 17 shown)
    8:  "manifest_version",
    9:  "spec_digest",
    10:  "simulation_digest",
    11:  "output_digest",
    12:  "solve_source",
    13:  "seed",
    14:  "aircraft",
    15:  "scene",
    16:  "frame",
    17:  "software_revision",
    18:  "landmarks",
    19:  "conditions",
    20:  "state_units",
    21:  "airframe",
    22:  "label_conventions",
    23:  "assets",
    24:  "randomization",
- `tests/test_component_labels.py` (13 signatures)
    29:def _mask(h, w, blobs):
    38:def _hand_card_objects():
    48:def test_children_of_and_the_taxonomy_order():
    55:def test_payload_blob_gives_a_tight_box_equal_to_the_blob():
    62:def test_out_of_frame_payload_is_null_with_the_out_of_frame_basis():
    82:def test_payload_behind_the_fuselage_is_invisible_and_occluded_by_the_aircraft():
    92:def test_aircraft_tight_box_includes_its_payload_pixels():
    100:def test_children_are_never_in_the_parents_occluded_by():
    113:def test_old_calls_without_children_are_unchanged():
    121:def test_component_hull_equals_the_hand_projected_box():
    146:def test_conventions_document_payload_landing_gear_and_the_rollup():
    153:def test_validate_manifest_accepts_v8_and_v7():
    171:def test_read_capture_manifest_reads_3_to_8_and_refuses_9(tmp_path):

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
- `core/capture/verify.py` (209 signatures, first 24 shown)
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
    255:class ExportError(ValueError):
    256:    def __init__(self, constraint: str, message: str):
    265:class Run:
    277:    def name(self) -> str:
    281:    def verification_bound(self) -> bool:
    285:    def airframes(self) -> List[str]:
    300:def discover_runs(paths: Iterable) -> List[Path]:
    343:def manifest_digest(directory) -> str:
    349:def bind_verification(directory) -> Path:
    365:def render_provenance(directory) -> Dict[str, Dict[str, Any]]:
    390:def engine_label_evidence(directory, manifest: Dict[str, Any]) -> Optional[str]:
    417:def load_run(directory) -> Run:
    473:def run_taxonomy(manifest: Dict[str, Any]) -> Optional[List[str]]:
    514:def dataset_taxonomy(samples: Sequence["Sample"]) -> Tuple[List[str], str]:
    540:def refuse_classes_outside_taxonomy(samples: Sequence["Sample"],
    550:def class_index(obj: Dict[str, Any], names: Sequence[str]) -> int:
    571:class Sample:
    584:    def simulation_digest(self) -> str:
    588:    def width(self) -> int:
    592:    def height(self) -> int:
    596:    def aircraft(self) -> str:
    600:def image_path(run: Run, record: Dict[str, Any], image: str) -> Path:
    607:def label_file_path(run: Run, record: Dict[str, Any], suffix: str) -> Path:
    614:def sample_labels(record: Dict[str, Any], image: str) -> Dict[str, Any]:
- `tests/test_dataset_boxes.py` (24 signatures)
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
    257:def component_export_run(tmp_path_factory):
    270:def _payload_expected(run: Path):
    280:def test_payload_and_gear_are_their_own_coco_categories(
    311:def test_component_boxes_reread_in_yolo_and_voc(
    340:def test_the_sidecar_box_record_carries_the_parent(
    350:def test_the_sensor_image_keeps_the_projected_box(engine_run, tmp_path, no_mesh_licence):
    368:def test_a_headless_run_keeps_the_projected_box_and_the_card_says_so(engine_run, tmp_path):
    396:def test_engine_labels_whose_gates_did_not_run_refuse_by_name(engine_run, tmp_path):
    420:def test_a_verdict_without_the_gates_refuses_and_one_with_them_loads(engine_run, tmp_path):
    437:def test_a_render_json_bundle_counts_and_a_run_without_one_is_unaffected(engine_run, tmp_path):
    465:def test_every_object_record_carries_fraction_in_frame_beside_truncation(engine_run):
    486:def test_fraction_in_frame_is_the_area_ratio_and_null_with_the_unclipped_box():
    495:def test_the_v7_schema_takes_fraction_in_frame_and_refuses_one_out_of_range():
- `tests/test_annotation_gates.py` (102 signatures, first 24 shown)
    121:def fabricated_spec():
    136:def fabricated_manifest(spec, mesh=None, citation=None):
    162:def fabricated_mesh_manifest(airframe_block, taller=1.0):
    190:def _rotation_body_to_ned(roll_deg, pitch_deg, yaw_deg):
    207:def axes_enu(roll_deg, pitch_deg, yaw_deg):
    216:def box_in_world(state, box_body, offset_body=(0.0, 0.0, 0.0)):
    232:def pixel_rays(record):
    247:def box_depth(record, rays, centre, axes, half):
    273:def ground_depth(record, rays, terrain_alt_m=0.0):
    282:def _pinhole(record, point):
    300:def _add_payload(manifest):
    320:def fabricate_run(run_dir, offset_body=(0.0, 0.0, 0.0), attach=True,
    464:def clean_run(tmp_path_factory):
    471:def shifted_run(tmp_path_factory):
    480:def run(clean_run, tmp_path):
    487:def checks_of(run_dir, other=None):
    492:def manifest_of(run_dir):
    496:def _render_json(run_dir, camera):
    500:def _edit_render_json(run_dir, camera, edit):
    507:def _reattach(run_dir):
    546:def test_the_painted_primary_lands_on_the_producers_box(clean_run):
    566:def test_the_scene_has_an_occlusion_to_grade(clean_run):
    579:def test_the_clean_fabricated_run_passes_every_annotation_check(clean_run):
    605:def test_a_pass_carries_no_failure_name_and_a_fail_carries_its_own():

## C7

### plan (verbatim)

### C7 · Landing gear (optional; only if C1–C6 are green) — S
- **Files:** `assets/aircraft_config/c172p.json` (fixed gear, named `.ac` parts),
  `assets_pipeline/convert.py`
- **Do:** split the gear parts named by the existing `gear_geometry` into a
  `landing_gear` component. **Not on the A-4:** its gear is stowed and not
  articulated (`a4_mdl_convert.py` header). Retracted gear on any type is
  `not_claimed` with basis `gear retracted`, never a zero-size box.
- **Verify:** Windows. A c172p render gives a `landing_gear` tight box on every
  frame whose mask contains its ID.

### files
- `assets/aircraft_config/c172p.json` [exists]
- `.ac` [missing]
- `assets_pipeline/convert.py` [exists]

### signatures
- `assets/aircraft_config/c172p.json` (15 signatures)
    2:  "name": "c172p",
    3:  "fdm": "c172p",
    4:  "fdm_match": [
    8:  "mesh_airframe": "Cessna 172P Skyhawk (FlightGear c172p-team model)",
    9:  "source_dir": "../aircraft_src/c172p",
    10:  "license": {
    17:  "parts": [
    22:  "exclude": [
    33:  "gear_geometry": {
    40:  "surfaces": {
    186:  "labels": {
    216:  "limits": {
    245:  "loading": {
    387:  "icing": {
    419:  "rain": {
- `assets_pipeline/convert.py` (29 signatures)
    171:class ConvertError(Exception):
    176:    def __init__(self, message: str, constraint: Optional[str] = None) -> None:
    182:def _fdm_config_name(xml_path: Path) -> str:
    190:def _matches(name: str, patterns: Sequence[str]) -> bool:
    194:def _structural_to_actor_cm(point: Tuple[float, float, float],
    210:def _body_to_actor_cm(body_m: Tuple[float, float, float],
    230:def fdm_vrp_actor_cm(xml_path: Path) -> Tuple[float, float, float]:
    272:def _model_origin_offset_actor_cm(config: Dict) -> Tuple[float, float, float]:
    287:def _gear_patterns(config: Dict) -> Tuple[List[str], List[str]]:
    318:class MeshExtents:
    326:    def __init__(self) -> None:
    333:    def add(self, point_cm: Tuple[float, float, float], gear: bool) -> None:
    347:    def nose_cm(self) -> float:
    351:    def tail_cm(self) -> float:
    355:    def lowest_cm(self) -> float:
    359:    def length_m(self) -> float:
    362:    def to_manifest(self) -> Dict:
    379:def _labelled_airframe(config: Dict, config_path: Path):
    398:def _extent_disagreement_cause(extents: MeshExtents, labels_length_m: float
    421:def measure_mesh_origin(extents: MeshExtents, airframe,
    528:def power_of_two(n: int) -> int:
    534:def copy_texture(source: Path, destination: Path) -> Tuple[int, int]:
    556:class ObjWriter:
    559:    def __init__(self) -> None:
    565:    def material_key(self, texture: Optional[str], rgb, transparency: float) -> str:
    576:    def add_triangle(self, key: str, tri) -> None:
    584:    def write(self, obj_path: Path, texture_dir_relative: str = "") -> None:
    610:def convert(config_path: Path, out_root: Path, repo_root: Path) -> Path:
    820:def main(argv=None) -> int:
