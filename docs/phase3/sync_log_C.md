# Letter C sync log (Windows cross-check)

## C2 · PASS · run C-1 · 2026-11-04T19:09:32Z

verify line(s) from tasks/phase3_checklist.md:

```
126:   - Check: the mesh manifest lists a `payload` piece per loaded station.
```

output line(s) that satisfy it:

```
runs/p3/A-2/C2-pytest.log: exit 0 (tests/test_a4_mesh.py, all dots; combined summary runs/p3/A-2/C23-summary.log: )
```

note: run C-1: Python-only, no Windows steps; the manifest's payload pieces per loaded station (decision 2 and 7: STA2, STA3, STA4) are what the test pins

### synopsis

# C2 synopsis

run_id: C-1
machine: windows
written: 2026-11-04T19:09:31Z

## C2 verify: pytest -q tests/test_a4_mesh.py

- log: `runs/p3/A-2/C2-pytest.log`
- exit: 0 (expected 0) -> PASS

```
...............                                                          [100%]
            [JSBSim-ML v2.0]

JSBSim startup beginning ...

```

note: run C-1 on 845f014d; Python-only box

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
e9f79c3c Letter C audit fixes: five stale test expectations updated; golden verify test is a pre-existing Windows-data gap
bd5aabec C7 fit: component_mesh_name from objects; gear row carries C2's row keys
98331123 Phase 3 letter D: notes for D1-D6, Align first run, build order; C2 integrated
9f29094f Phase 3: C2 integrated note
484a34df Merge p3-C2: C2
ca3a9619 Phase 3: bookkeeping before merging p3-C2
d783e8ff C3: compose the primary's components as card objects in the 64-127 band
c5bb4a39 C2: export each loaded A-4 station as its own mesh (manifest v4 components)
f2c69c6e C7: c172p landing gear as its own OBJ, one landing_gear component, gear-retracted basis
79d43a52 Phase 3 letter C: notes for C2, C3, C4, C7, Align first run, build order
2f779f34 Phase 3 letter C: digest and breakdown start (C2, C3, C4, C7)

e9f79c3c Letter C audit fixes: five stale test expectations updated; golden verify test is a pre-existing Windows-data gap

 tests/test_aircraft_assets.py          | 11 +++++++++++
 tests/test_buildings.py                | 12 ++++++++----
 tests/test_camera_verify_corruption.py |  9 ++++++---
 tests/test_landcover_labels.py         | 34 ++++++++++++++++++++++------------
 4 files changed, 47 insertions(+), 19 deletions(-)

bd5aabec C7 fit: component_mesh_name from objects; gear row carries C2's row keys

 assets_pipeline/convert.py    | 14 ++++++--------
 tests/test_aircraft_assets.py |  6 ++++--
 2 files changed, 10 insertions(+), 10 deletions(-)

98331123 Phase 3 letter D: notes for D1-D6, Align first run, build order; C2 integrated

 docs/phase3/events_mac.log | 7 +++++++
 docs/phase3/state/A10.json | 6 ++++--
 docs/phase3/state/C2.json  | 5 +++--
 3 files changed, 14 insertions(+), 4 deletions(-)

9f29094f Phase 3: C2 integrated note

 docs/phase3/notes/C2.md | 5 +++++
 1 file changed, 5 insertions(+)

484a34df Merge p3-C2: C2

 assets_pipeline/a4_mdl_convert.py | 243 ++++++++++++++++++++++++++++----------
 assets_pipeline/importer.py       |  30 +++++
 assets_pipeline/mdl_scene.py      |  17 +++
 tests/test_a4_mesh.py             | 163 ++++++++++++++++++++++++-
 4 files changed, 389 insertions(+), 64 deletions(-)

ca3a9619 Phase 3: bookkeeping before merging p3-C2

 docs/phase3/events_mac.log |  6 ++++++
 docs/phase3/notes/D2.md    | 24 ++++++++++++++++++------
 docs/phase3/notes/D4.md    | 22 +++++++++++++++-------
 docs/phase3/notes/D5.md    | 15 ++++++++++++---
 docs/phase3/state/A12.json |  6 +++---
 5 files changed, 54 insertions(+), 19 deletions(-)

d783e8ff C3: compose the primary's components as card objects in the 64-127 band

 core/capture/manifest.py                     |  14 +-
 core/capture/objects.py                      | 167 ++++++++++++++-
 core/scenario/card.py                        |  42 ++++
 docs/schemas/capture_manifest.v8.schema.json |  49 ++++-
 tests/test_card_components.py                | 300 +++++++++++++++++++++++++++
 5 files changed, 564 insertions(+), 8 deletions(-)

c5bb4a39 C2: export each loaded A-4 station as its own mesh (manifest v4 components)

 assets_pipeline/a4_mdl_convert.py | 243 ++++++++++++++++++++++++++++----------
 assets_pipeline/importer.py       |  30 +++++
 assets_pipeline/mdl_scene.py      |  17 +++
 tests/test_a4_mesh.py             | 163 ++++++++++++++++++++++++-
 4 files changed, 389 insertions(+), 64 deletions(-)

f2c69c6e C7: c172p landing gear as its own OBJ, one landing_gear component, gear-retracted basis

 assets/aircraft_config/c172p.json |  10 +++-
 assets_pipeline/convert.py        |  94 ++++++++++++++++++++++++++++++-
 core/capture/labels.py            |  45 ++++++++++++++-
 tests/test_aircraft_assets.py     |  91 ++++++++++++++++++++++++++++++
 tests/test_airframe.py            |  23 +++++++-
 tests/test_component_labels.py    | 114 +++++++++++++++++++++++++++++++++++++-
 6 files changed, 369 insertions(+), 8 deletions(-)

79d43a52 Phase 3 letter C: notes for C2, C3, C4, C7, Align first run, build order

 docs/phase3/events_mac.log | 39 +++++++++++++++++++++++++++++++++++++++
 docs/phase3/notes/C2.md    | 26 +++++++++++++++++++-------
 docs/phase3/notes/C3.md    | 39 +++++++++++++++++++++++++++------------
 docs/phase3/notes/C4.md    | 34 ++++++++++++++++++++--------------
 docs/phase3/notes/C7.md    | 31 ++++++++++++++++++++++---------
 docs/phase3/state/A11.json | 15 +++++++++++----
 docs/phase3/state/C.json   | 18 ++++++++++++++++--
 docs/phase3/state/C2.json  |  4 ++--
 docs/phase3/state/C3.json  |  4 ++--
 docs/phase3/state/C4.json  |  4 ++--
 docs/phase3/state/C7.json  |  4 ++--
 11 files changed, 162 insertions(+), 56 deletions(-)

2f779f34 Phase 3 letter C: digest and breakdown start (C2, C3, C4, C7)

 docs/phase3/digest_C.md    | 609 +++++++++++++++++++++++++++++++++++++++++++++
 docs/phase3/events_mac.log |  28 +++
 docs/phase3/state/C.json   |   4 +
 3 files changed, 641 insertions(+)
```

## C3 · PASS · run C-1 · 2026-11-04T19:09:32Z

verify line(s) from tasks/phase3_checklist.md:

```
128:   - Check: the IDs are unique and never clash with other aircraft.
```

output line(s) that satisfy it:

```
runs/p3/A-2/C3-pytest.log: exit 0 (tests/test_card_components.py, all dots; combined summary: )
```

note: run C-1: Python-only, no Windows steps

### synopsis

# C3 synopsis

run_id: C-1
machine: windows
written: 2026-11-04T19:09:32Z

## C3 verify: pytest -q tests/test_card_components.py

- log: `runs/p3/A-2/C3-pytest.log`
- exit: 0 (expected 0) -> PASS

```
...........                                                              [100%]
            [JSBSim-ML v2.0]

JSBSim startup beginning ...

```

note: run C-1 on 845f014d; Python-only box

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
e9f79c3c Letter C audit fixes: five stale test expectations updated; golden verify test is a pre-existing Windows-data gap
d0b6056c Phase 3: C3 integration logged
d0f43b29 Phase 3: C3 integrated note
4c243a8c Merge p3-C3: C3
ea9fcdb2 Phase 3: bookkeeping before merging p3-C3
ad43e122 C3 fit: a missing 3-D box is tolerated for component records only; assert it
d783e8ff C3: compose the primary's components as card objects in the 64-127 band
f2c69c6e C7: c172p landing gear as its own OBJ, one landing_gear component, gear-retracted basis
79d43a52 Phase 3 letter C: notes for C2, C3, C4, C7, Align first run, build order
2f779f34 Phase 3 letter C: digest and breakdown start (C2, C3, C4, C7)

e9f79c3c Letter C audit fixes: five stale test expectations updated; golden verify test is a pre-existing Windows-data gap

 tests/test_aircraft_assets.py          | 11 +++++++++++
 tests/test_buildings.py                | 12 ++++++++----
 tests/test_camera_verify_corruption.py |  9 ++++++---
 tests/test_landcover_labels.py         | 34 ++++++++++++++++++++++------------
 4 files changed, 47 insertions(+), 19 deletions(-)

d0b6056c Phase 3: C3 integration logged

 docs/phase3/events_mac.log | 2 ++
 1 file changed, 2 insertions(+)

d0f43b29 Phase 3: C3 integrated note

 docs/phase3/notes/C3.md | 8 ++++++++
 1 file changed, 8 insertions(+)

4c243a8c Merge p3-C3: C3

 core/capture/manifest.py                     |  16 +-
 core/capture/objects.py                      | 167 ++++++++++++++-
 core/scenario/card.py                        |  42 ++++
 docs/schemas/capture_manifest.v8.schema.json |  49 ++++-
 tests/test_card_components.py                | 303 +++++++++++++++++++++++++++
 5 files changed, 569 insertions(+), 8 deletions(-)

ea9fcdb2 Phase 3: bookkeeping before merging p3-C3

 docs/phase3/state/D2.json | 15 +++++++++++++--
 docs/phase3/state/D4.json | 12 ++++++++++--
 docs/phase3/state/D5.json |  9 +++++++--
 3 files changed, 30 insertions(+), 6 deletions(-)

ad43e122 C3 fit: a missing 3-D box is tolerated for component records only; assert it

 core/capture/manifest.py      | 8 +++++---
 tests/test_card_components.py | 3 +++
 2 files changed, 8 insertions(+), 3 deletions(-)

d783e8ff C3: compose the primary's components as card objects in the 64-127 band

 core/capture/manifest.py                     |  14 +-
 core/capture/objects.py                      | 167 ++++++++++++++-
 core/scenario/card.py                        |  42 ++++
 docs/schemas/capture_manifest.v8.schema.json |  49 ++++-
 tests/test_card_components.py                | 300 +++++++++++++++++++++++++++
 5 files changed, 564 insertions(+), 8 deletions(-)

f2c69c6e C7: c172p landing gear as its own OBJ, one landing_gear component, gear-retracted basis

 assets/aircraft_config/c172p.json |  10 +++-
 assets_pipeline/convert.py        |  94 ++++++++++++++++++++++++++++++-
 core/capture/labels.py            |  45 ++++++++++++++-
 tests/test_aircraft_assets.py     |  91 ++++++++++++++++++++++++++++++
 tests/test_airframe.py            |  23 +++++++-
 tests/test_component_labels.py    | 114 +++++++++++++++++++++++++++++++++++++-
 6 files changed, 369 insertions(+), 8 deletions(-)

79d43a52 Phase 3 letter C: notes for C2, C3, C4, C7, Align first run, build order

 docs/phase3/events_mac.log | 39 +++++++++++++++++++++++++++++++++++++++
 docs/phase3/notes/C2.md    | 26 +++++++++++++++++++-------
 docs/phase3/notes/C3.md    | 39 +++++++++++++++++++++++++++------------
 docs/phase3/notes/C4.md    | 34 ++++++++++++++++++++--------------
 docs/phase3/notes/C7.md    | 31 ++++++++++++++++++++++---------
 docs/phase3/state/A11.json | 15 +++++++++++----
 docs/phase3/state/C.json   | 18 ++++++++++++++++--
 docs/phase3/state/C2.json  |  4 ++--
 docs/phase3/state/C3.json  |  4 ++--
 docs/phase3/state/C4.json  |  4 ++--
 docs/phase3/state/C7.json  |  4 ++--
 11 files changed, 162 insertions(+), 56 deletions(-)

2f779f34 Phase 3 letter C: digest and breakdown start (C2, C3, C4, C7)

 docs/phase3/digest_C.md    | 609 +++++++++++++++++++++++++++++++++++++++++++++
 docs/phase3/events_mac.log |  28 +++
 docs/phase3/state/C.json   |   4 +
 3 files changed, 641 insertions(+)
```

## C4 · PASS · run C-1 · 2026-11-04T22:10:35Z

verify line(s) from tasks/phase3_checklist.md:

```
130:   - Check: the mask contains the payload's ID, and the aircraft's own tight box is
131:     still filled.
```

output line(s) that satisfy it:

```
runs/p3/A-2/C4-proof2-diagnose.log: frame_0000_mask.png: 0:9702, 1:462, 2:47385, 64:21, 65:8, 66:22 (payload ids 64/65/66 present with their own values); declared ids [1, 2, 64, 65, 66, 67, 68, 69]; tight null: 3 (the three meshless gear entries), tight filled: 5
runs/p3/A-2/C4-proof2-verify.log: [PASS] tight_box_present: bbox_2d_tight present and inside bbox_2d ; [PASS] component_boxes: 3 component records: tight box inside its own hull and its parent's tight box (tol 1 px) ; [PASS] component_coverage ; [PASS] label_geometry_3d ; [PASS] host_determinism (byte-identical) ; [PASS] mask_vs_geometry (0.4 px of 64 px span) ; verify exit 0
```

note: run C-1: packets C4-1 (mirrored OBJ import, decision 19; verifier recount; CLI host flights) and C4-2 (re-convert without re-import) both closed by the Mac; the engine side unchanged since 3ef2414e; C7 step 6 is recorded deferred: budget per the owner's rule

### synopsis

# C4 synopsis

run_id: C-1
machine: windows
written: 2026-11-04T22:10:34Z

## C4 re-prove 2 on the branch tip (e6e33c6e + 30945bf5): one A-4 labels still through the CLI, A7 re-converted and re-imported body + three stores

- log: `runs/p3/A-2/C4-proof2.log`
- exit: 0 (expected 0) -> PASS

```

[2026.11.04-22.09.20:072][  0]LogInit: Display: LogPython: Warning: C:/Users/kanth/flightsim/scripts/ue_import_aircraft.py:100: DeprecationWarning: EditorStaticMeshLibrary: Function 'set_lod_build_settings' on 'EditorStaticMeshLibrary' is deprecated: The Editor Scripting Utilities Plugin is deprecated - Use the function in Static Mesh Editor Subsystem
  unreal.EditorStaticMeshLibrary.set_lod_build_settings(mesh, 0, build)

[2026.11.04-22.09.20:074][  0]LogInit: Display: PIE: Warning: Calling GetSectionFromStaticMesh on body but 'Allow CPU Access' is not enabled. This is required for converting StaticMesh to ProceduralMeshComponent in cooked builds.
[2026.11.04-22.09.20:075][  0]LogInit: Display: PIE: Warning: Calling GetSectionFromStaticMesh on SM_A4_store_sta2 but 'Allow CPU Access' is not enabled. This is required for converting StaticMesh to ProceduralMeshComponent in cooked builds.
[2026.11.04-22.09.20:075][  0]LogInit: Display: PIE: Warning: Calling GetSectionFromStaticMesh on SM_A4_drop_tank_sta3 but 'Allow CPU Access' is not enabled. This is required for converting StaticMesh to ProceduralMeshComponent in cooked builds.
[2026.11.04-22.09.20:076][  0]LogInit: Display: PIE: Warning: Calling GetSectionFromStaticMesh on SM_A4_store_sta4 but 'Allow CPU Access' is not enabled. This is required for converting StaticMesh to ProceduralMeshComponent in cooked builds.
[2026.11.04-22.09.20:077][  0]LogInit: Display: 
[2026.11.04-22.09.20:078][  0]LogInit: Display: Success - 0 error(s), 7 warning(s)
[2026.11.04-22.09.20:078][  0]LogInit: Display: 

Execution of commandlet took:  9.16 seconds
[2026.11.04-22.09.20:330][  0]LogShaderCompilers: Display: Shaders left to compile 0
projected for the render host (no autopilot; calibrated airspeed only):
  mass_held: False -> True
  hold_state: True -> False
the A4 model is not current (not imported); building it once
importing 1 aircraft into the Unreal project
spec 243a42928a57e942 valid; running headlessly...
flying the card in the host first, so the labels describe the flight the pixels show ...
  engine pass logging to runs\p3\A-2\C4-proof2\host_flight\host_flight_pass.log (unattended; stalls are stopped)
    wrote C:\Users\kanth\flightsim\runs\p3\A-2\C4-proof2\host_flight\host_telemetry.json
  host flight: 200 samples, digest 88e63b976296bc9b -- poses re-solved over it
  instruments: ideal (the recorded channels are the measurement; no telemetry_measured.json written)
  card:     runs\p3\A-2\C4-proof2\card.json (consume-poses; one commandlet pass per camera via -camera-index=N)
captured: 1 frames across 1 camera(s)
  manifest: runs\p3\A-2\C4-proof2\capture_manifest.json
  previews: 1 geometry preview(s) under runs\p3\A-2\C4-proof2\previews
rendering 1 camera pass(es) into runs\p3\A-2\C4-proof2\frames in the visual scene ...
  engine pass logging to runs\p3\A-2\C4-proof2\render_pass.log (unattended; stalls are stopped)
    scene flags for every pass: -Visual -shot=showcase -fps=30 -width=1280 -height=720 -sun-elev=50.0 -sun-azim=180.0 -exposure-bias=9.5 -fog-density=0.0012 -labels -deterministic -GeorefTerrain -terrain=C:\Users\kanth\flightsim\runs\terrain\grand_canyon -mesh=C:\Users\kanth\flightsim\assets\generated\A4\mesh_manifest.json -NoSound -NoLoadingScreen
    camera 1/1: chase -> C:\Users\kanth\flightsim\runs\p3\A-2\C4-proof2\frames\chase
      wrote 8 frames
    wrote 8 frames across 1 camera(s) under C:\Users\kanth\flightsim\runs\p3\A-2\C4-proof2\frames
  frames:   1 rendered under runs\p3\A-2\C4-proof2\frames
  labels:   engine bundle attached on 1 of 1 frames (8 object records; 0 without a bundle)
  overlays: 1 under runs\p3\A-2\C4-proof2\overlays -- the recorded geometry drawn ON the rendered pixels; the circle (manifest) and the cross (engine) should coincide
  verify:   python -m flightsim.verify runs\p3\A-2\C4-proof2
  (with pixels present, verification exercises the landmark reprojection and two-view checks that report NOT RUN without them)
```

## C4: flightsim.verify on runs/p3/A-2/C4-proof2

- log: `runs/p3/A-2/C4-proof2-verify.log`
- exit: 0 (expected 0) -> PASS

```
  [NOT RUN] instruments: no telemetry_measured.json in the run (instruments profile ideal, or none stated)
  [PASS] datum: heights EGM2008 orthometric (GLO-30); EGM96 bilinear undulation -23.403 m at the origin (bilinear -23.403 m) agrees with the checker's own read of the grid to 0.0000 m; ellipsoidal origin 1316.8 m = orthometric 1340.2 m + N
  [PASS] datum_independent: PROJ +inv vgridshift on grand_canyon_geoid.gtx (5x5 nodes at 0.250000 deg, corner on whole nodes) reads -23.403 m at the origin (block -23.403 m) and agrees with the producer's full-grid values to 1.14e-06 m over 100 interior points; inf outside
  [NOT RUN] dis_roundtrip: no Entity State PDU log: the run was captured without --dis (no dis_entity_state.bin, no index, no dis.entity_state record)
  [PASS] georeference: 1 render.json georeference block(s) agree with the manifest: EPSG:32612 about the frame origin, the stated vertical convention, undulation at the origin -23.403 m
  [NOT RUN] wake_selftest: the card states no wake: nothing to re-evaluate
  [NOT RUN] host_physics: no render.json carries the engine's physics keys: the engine side is a Windows step
  [NOT RUN] building_vs_footprint: the manifest names no footprint set (no scene.buildings): nothing to carry the ID image back against
  [NOT RUN] runway_vs_geometry: the manifest names no runway (no scene.runway): nothing to grade
  [NOT RUN] landcover_vs_geometry: the manifest names no land cover (no landcover block): nothing to carry the frames onto
  [NOT RUN] normals_vs_depth: no render.json frame record declares normal_png (no -passes=normal, or no engine pass at all): render on Windows with -labels -passes=normal to exercise this
  [NOT RUN] flow_vs_motion: no render.json frame record declares flow_f32 (no -passes=velocity, or no engine pass at all): render on Windows with -labels -passes=velocity to exercise this
  [NOT RUN] albedo_range: no render.json frame record declares albedo_png (no -passes=albedo, or no engine pass at all): render on Windows with -labels -passes=albedo to exercise this
  [NOT RUN] psf_slanted_edge: no camera carries a sensing.optics block: no PSF was applied
  [NOT RUN] blur_vs_flow: no camera carries a sensing.motion_blur block: no blur was applied
  [NOT RUN] radiometry_grey_card: no camera carries a sensing.radiometry block
  [NOT RUN] engine_linear_passes: no render.json frame record declares labels.normal or labels.basecolor (render on Windows with -labels -passes=normal,albedo to exercise this)
  [NOT RUN] velocity_readback: no render.json frame record declares labels.velocity (render on Windows with -labels -velocity-check to exercise this)
  [PASS] engine_readbacks: 5 read-back(s): the console values parse, the lens attenuation is a fraction, the colour space is linear, a sun in lux says so and was set to it
  [NOT RUN] calibration_frame: no render.json carries a calibration record (render on Windows with -calibration -sun-lux= to exercise this)
  [NOT RUN] engine_accumulation: no render.json frame record carries an accumulation (render on Windows with -accumulate=K to exercise this)
  [NOT RUN] night_exposure: the manifest carries no look.night block: no night was asked for
  [NOT RUN] world_record: no scene.world record beside a card look and no render.json world_applied: the world engine side is a Windows step
  [NOT RUN] flow_vs_keypoints: no passes.json names a flow pass (no camera asks for it in cameras[i].passes, or no render): render on Windows with the pass asked for to exercise this
  [NOT RUN] flow_static_null: no passes.json names a flow pass (no camera asks for it in cameras[i].passes, or no render): render on Windows with the pass asked for to exercise this
  [NOT RUN] disparity_vs_right_depth: no camera block declares a stereo rig (cameras[i].stereo)
  [NOT RUN] points_vs_depth: no passes.json names a points pass (no camera asks for it in cameras[i].passes, or no render): render on Windows with the pass asked for to exercise this
  [NOT RUN] amodal_contains_visible: no object record carries an amodal box (no camera asks for amodal)
  [NOT RUN] ir_proxy_declared: no IR frame under frames/ (0 camera(s) declare sensing.ir; the proxy is written after a render's ID image and depth exist)
  [PASS] applied_readback: 1 readback(s) re-graded from their own numbers, every one within its stated tolerance
  [PASS] null_effect: 2 null test(s) re-graded from their own numbers; every verdict agrees
  [NOT RUN] instrument_allan: no instrument stated: the ideal set at the CG writes no instruments.npz and grades nothing
  [NOT RUN] instrument_lever_arm: no instrument stated: the ideal set at the CG writes no instruments.npz and grades nothing
  [NOT RUN] uncertainty_present: no uncertainty block: the capture did not run the dt/2 twin (--uncertainty or record.sensitivity_pairs)
  [NOT RUN] temporal_alignment: needs a second capture of the SAME simulation with a different camera set: run flightsim.capture again with other cameras and pass --against <that run dir>
verification PASSED (36 passed, 0 failed, 32 not run, 2 superseded)
  NOT RUN (no independent reference available for these; they are NOT counted as passes): cross_view_consistency, aircraft_state_consistency, sensor_files, instruments, dis_roundtrip, wake_selftest, host_physics, building_vs_footprint, runway_vs_geometry, landcover_vs_geometry, normals_vs_depth, flow_vs_motion, albedo_range, psf_slanted_edge, blur_vs_flow, radiometry_grey_card, engine_linear_passes, velocity_readback, calibration_frame, engine_accumulation, night_exposure, world_record, flow_vs_keypoints, flow_static_null, disparity_vs_right_depth, points_vs_depth, amodal_contains_visible, ir_proxy_declared, instrument_allan, instrument_lever_arm, uncertainty_present, temporal_alignment
  SUPERSEDED on this manifest (each names the check that replaced it above; not counted as passes, and not waiting for any evidence): mask_containment, depth_range
  recorded: runs\p3\A-2\C4-proof2\verification.json
  per frame: runs\p3\A-2\C4-proof2\frame_checks.json (0 frame(s) failing)
```

## C4: label_diagnose on runs/p3/A-2/C4-proof2

- log: `runs/p3/A-2/C4-proof2-diagnose.log`
- exit: 0 (expected 0) -> PASS

```

== runs\p3\A-2\C4-proof2\frames\chase
   rhi 'D3D11', declared ids [1, 2, 64, 65, 66, 67, 68, 69]
   tight null: 3, tight filled: 5
   frame_0000_mask.png: 0:9702, 1:462, 2:47385, 64:21, 65:8, 66:22
      frame_0000_alone_1.png: 0:57087, 1:513
      frame_0000_alone_64.png: 0:57568, 64:32
      frame_0000_alone_65.png: 0:57572, 65:28
      frame_0000_alone_66.png: 0:57567, 66:33
   1 mask(s); stray ids over the run: none
```

note: run C-1: engine side by the Windows builder 3ef2414e (merged 43c216fa); two Mac fixes (1e802859 obj_frame + verifier recount + CLI terrain flags; e6e33c6e re-import after re-convert); the proof is the one still after the re-import (uassets 17:09, import commandlet in the capture log)

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
30945bf5 C4: the stale-manifest test expects the re-import that now follows a re-convert
17cc43d5 Phase 3: C4 fix 2 pushed
fad9ca6d Phase 3: C4 fix 2 logged
8f62d43e C4: a re-converted manifest re-imports its assets (assets older than the manifest are stale)
0f19a9f0 Phase 3 run C-1: C4 FAIL packet 2 (re-convert without re-import)
590ea2fd Phase 3: C4 state; flags-parity order dependence noted
fc2abc38 Phase 3: C4 Mac retry pushed
1e802859 Merge p3-C4r: C4
44857b69 Phase 3 C4: retry 1 note
9c96fcb6 C4: right-handed OBJs from both converters (decision 19); occlusion recount matches the measure; CLI capture carries the web run's ground
4ff8faf4 Phase 3 run A-2: A10 FAIL packet 3 (campaign renders; verification blocked by the C4-1 Mac items; llm notes field)
f3973b24 Phase 3: C4 merge log
e7ce2454 C4: the engine attaches the card's store meshes under MeshOrigin, stencils each component with its own int_id, draws the parent's alone pass whole and gives each store its own alone pass
f4f85db6 Phase 3 run C-1: C4 FAIL packet 1 (engine side done; mirrored OBJ import, decision 19; two verifier items), shared value labels.objects.parent
22204386 Phase 3: release the merged Windows builders' claims (A5, A6, A8, B1, B2); C4 builder claim-busy logged
85a4b095 Phase 3 decision 16: C7 Mac steps now, Windows step after C4, cut without penalty otherwise
79d43a52 Phase 3 letter C: notes for C2, C3, C4, C7, Align first run, build order
2f779f34 Phase 3 letter C: digest and breakdown start (C2, C3, C4, C7)

30945bf5 C4: the stale-manifest test expects the re-import that now follows a re-convert

 tests/test_aircraft_assets.py | 4 +++-
 1 file changed, 3 insertions(+), 1 deletion(-)

17cc43d5 Phase 3: C4 fix 2 pushed

 docs/phase3/events_mac.log | 1 +
 docs/phase3/state/C4.json  | 4 ++--
 2 files changed, 3 insertions(+), 2 deletions(-)

fad9ca6d Phase 3: C4 fix 2 logged

 docs/phase3/events_mac.log | 11 +++++++++++
 1 file changed, 11 insertions(+)

8f62d43e C4: a re-converted manifest re-imports its assets (assets older than the manifest are stale)

 assets_pipeline/importer.py       | 35 +++++++++++++++++++++++++++++------
 tests/test_aircraft_autoimport.py | 20 +++++++++++++++++++-
 2 files changed, 48 insertions(+), 7 deletions(-)

0f19a9f0 Phase 3 run C-1: C4 FAIL packet 2 (re-convert without re-import)

 docs/PHASE3_LOG.md             |  1 +
 docs/phase3/events_windows.log | 20 +++++++++++++++++
 docs/phase3/packets/C4-2.md    | 51 ++++++++++++++++++++++++++++++++++++++++++
 docs/phase3/state/C4.json      |  5 +++--
 4 files changed, 75 insertions(+), 2 deletions(-)

590ea2fd Phase 3: C4 state; flags-parity order dependence noted

 docs/phase3/events_mac.log | 6 ++++++
 docs/phase3/notes/F3.md    | 6 ++++++
 docs/phase3/state/C4.json  | 7 ++++---
 docs/phase3/state/F3.json  | 8 ++++++--
 4 files changed, 22 insertions(+), 5 deletions(-)

fc2abc38 Phase 3: C4 Mac retry pushed

 docs/phase3/events_mac.log | 14 ++++++++++++++
 docs/phase3/state/E2.json  | 15 +++++++++++++--
 2 files changed, 27 insertions(+), 2 deletions(-)

1e802859 Merge p3-C4r: C4

 assets_pipeline/a4_mdl_convert.py |  30 ++++++++---
 assets_pipeline/convert.py        |  16 ++++--
 assets_pipeline/importer.py       |  12 +++++
 assets_pipeline/obj_frame.py      |  82 +++++++++++++++++++++++++++++
 core/capture/verify.py            |  29 +++++++++--
 core/render/flags.py              |  14 ++++-
 flightsim/capture.py              |  44 +++++++++++-----
 tests/test_a4_mesh.py             | 107 +++++++++++++++++++++++++++++++++++++-
 tests/test_aircraft_assets.py     |  62 +++++++++++++++++++++-
 tests/test_aircraft_autoimport.py |   1 +
 tests/test_camera_cli.py          |  37 +++++++++++++
 tests/test_component_labels.py    |  34 ++++++++++++
 webapp/runs.py                    |   4 +-
 13 files changed, 440 insertions(+), 32 deletions(-)

44857b69 Phase 3 C4: retry 1 note

 docs/phase3/events_mac.log |  8 ++++++++
 docs/phase3/notes/C4.md    |  9 +++++++++
 docs/phase3/notes/E6.md    |  7 +++++++
 docs/phase3/state/C4.json  |  8 ++++----
 docs/phase3/state/E6.json  | 25 +++++++++++++------------
 5 files changed, 41 insertions(+), 16 deletions(-)

9c96fcb6 C4: right-handed OBJs from both converters (decision 19); occlusion recount matches the measure; CLI capture carries the web run's ground

 assets_pipeline/a4_mdl_convert.py |  30 ++++++++---
 assets_pipeline/convert.py        |  16 ++++--
 assets_pipeline/importer.py       |  12 +++++
 assets_pipeline/obj_frame.py      |  82 +++++++++++++++++++++++++++++
 core/capture/verify.py            |  29 +++++++++--
 core/render/flags.py              |  14 ++++-
 flightsim/capture.py              |  44 +++++++++++-----
 tests/test_a4_mesh.py             | 107 +++++++++++++++++++++++++++++++++++++-
 tests/test_aircraft_assets.py     |  62 +++++++++++++++++++++-
 tests/test_aircraft_autoimport.py |   1 +
 tests/test_camera_cli.py          |  37 +++++++++++++
 tests/test_component_labels.py    |  34 ++++++++++++
 webapp/runs.py                    |   4 +-
 13 files changed, 440 insertions(+), 32 deletions(-)

4ff8faf4 Phase 3 run A-2: A10 FAIL packet 3 (campaign renders; verification blocked by the C4-1 Mac items; llm notes field)

 docs/PHASE3_LOG.md             |  1 +
 docs/phase3/events_windows.log | 10 +++++++++
 docs/phase3/packets/A10-3.md   | 47 ++++++++++++++++++++++++++++++++++++++++++
 docs/phase3/state/A10.json     |  5 +++--
 docs/phase3/state/B4.json      |  9 ++++++--
 5 files changed, 68 insertions(+), 4 deletions(-)

f3973b24 Phase 3: C4 merge log

 docs/phase3/events_windows.log | 3 +++
 1 file changed, 3 insertions(+)

e7ce2454 C4: the engine attaches the card's store meshes under MeshOrigin, stencils each component with its own int_id, draws the parent's alone pass whole and gives each store its own alone pass

 .../Private/FlightSimRenderCommandlet.cpp          | 209 ++++++++++++++++++++-
 .../Private/FlightSimScenarioWorld.cpp             |  35 ++++
 .../Public/FlightSimScenarioWorld.h                |  10 +-
 3 files changed, 247 insertions(+), 7 deletions(-)

f4f85db6 Phase 3 run C-1: C4 FAIL packet 1 (engine side done; mirrored OBJ import, decision 19; two verifier items), shared value labels.objects.parent

 docs/PHASE3_LOG.md             |  1 +
 docs/phase3/decisions.md       |  2 ++
 docs/phase3/events_windows.log | 10 ++++++
 docs/phase3/packets/C4-1.md    | 71 ++++++++++++++++++++++++++++++++++++++++++
 docs/phase3/state/B4.json      |  6 ++--
 docs/phase3/state/C4.json      | 16 ++++++++--
 6 files changed, 100 insertions(+), 6 deletions(-)

22204386 Phase 3: release the merged Windows builders' claims (A5, A6, A8, B1, B2); C4 builder claim-busy logged

 docs/phase3/events_windows.log | 21 +++++++++++++++++++++
 docs/phase3/state/A5.json      |  9 ++-------
 docs/phase3/state/A6.json      |  6 ++----
 docs/phase3/state/A8.json      | 12 ++----------
 docs/phase3/state/B1.json      |  6 ++----
 docs/phase3/state/B2.json      |  6 ++----
 docs/phase3/state/B4.json      | 12 ++++++++----
 docs/phase3/state/C4.json      |  4 ++--
 8 files changed, 41 insertions(+), 35 deletions(-)

85a4b095 Phase 3 decision 16: C7 Mac steps now, Windows step after C4, cut without penalty otherwise

 docs/phase3/decisions.md       | 2 ++
 docs/phase3/events_windows.log | 5 +++++
 2 files changed, 7 insertions(+)

79d43a52 Phase 3 letter C: notes for C2, C3, C4, C7, Align first run, build order

 docs/phase3/events_mac.log | 39 +++++++++++++++++++++++++++++++++++++++
 docs/phase3/notes/C2.md    | 26 +++++++++++++++++++-------
 docs/phase3/notes/C3.md    | 39 +++++++++++++++++++++++++++------------
 docs/phase3/notes/C4.md    | 34 ++++++++++++++++++++--------------
 docs/phase3/notes/C7.md    | 31 ++++++++++++++++++++++---------
 docs/phase3/state/A11.json | 15 +++++++++++----
 docs/phase3/state/C.json   | 18 ++++++++++++++++--
 docs/phase3/state/C2.json  |  4 ++--
 docs/phase3/state/C3.json  |  4 ++--
 docs/phase3/state/C4.json  |  4 ++--
 docs/phase3/state/C7.json  |  4 ++--
 11 files changed, 162 insertions(+), 56 deletions(-)

2f779f34 Phase 3 letter C: digest and breakdown start (C2, C3, C4, C7)

 docs/phase3/digest_C.md    | 609 +++++++++++++++++++++++++++++++++++++++++++++
 docs/phase3/events_mac.log |  28 +++
 docs/phase3/state/C.json   |   4 +
 3 files changed, 641 insertions(+)
```

