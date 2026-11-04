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
