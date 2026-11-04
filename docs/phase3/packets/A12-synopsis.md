# A12 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T18:16:51Z

## A12 step 5: flightsim.verify on run 7237db488652 (c172p, chase, 1 x 320x180) after eb9e5f30 (engine) and 968dcb60 (verifier)

- log: `runs/p3/A-2/A12-verify-main-2.log`
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
  [NOT RUN] applied_readback: 1 record(s), none carrying a readback
  [PASS] null_effect: 1 null test(s) re-graded from their own numbers; every verdict agrees
  [NOT RUN] instrument_allan: the manifest carries no instruments block (a run before the FDM-rate observer)
  [NOT RUN] instrument_lever_arm: the manifest carries no instruments block (a run before the FDM-rate observer)
  [NOT RUN] uncertainty_present: no uncertainty block: the capture did not run the dt/2 twin (--uncertainty or record.sensitivity_pairs)
  [NOT RUN] temporal_alignment: needs a second capture of the SAME simulation with a different camera set: run flightsim.capture again with other cameras and pass --against <that run dir>
verification PASSED (33 passed, 0 failed, 35 not run, 2 superseded)
  NOT RUN (no independent reference available for these; they are NOT counted as passes): cross_view_consistency, aircraft_state_consistency, component_coverage, component_boxes, sensor_files, instruments, dis_roundtrip, wake_selftest, host_physics, building_vs_footprint, runway_vs_geometry, landcover_vs_geometry, normals_vs_depth, flow_vs_motion, albedo_range, psf_slanted_edge, blur_vs_flow, radiometry_grey_card, engine_linear_passes, velocity_readback, calibration_frame, engine_accumulation, night_exposure, world_record, flow_vs_keypoints, flow_static_null, disparity_vs_right_depth, points_vs_depth, amodal_contains_visible, ir_proxy_declared, applied_readback, instrument_allan, instrument_lever_arm, uncertainty_present, temporal_alignment
  SUPERSEDED on this manifest (each names the check that replaced it above; not counted as passes, and not waiting for any evidence): mask_containment, depth_range
  recorded: runs\webapp\7237db488652\verification.json
  per frame: runs\webapp\7237db488652\frame_checks.json (0 frame(s) failing)
```

## A12 step 5: label_diagnose.py on 7237db488652

- log: `runs/p3/A-2/A12-diagnose-main.log`
- exit: 0 (expected 0) -> PASS

```

== runs\webapp\7237db488652\frames\chase
   rhi 'D3D11', declared ids [1, 2]
   tight null: 0, tight filled: 2
   frame_0000_mask.png: 0:9407, 1:1084, 2:47109
      frame_0000_alone_1.png: 0:56516, 1:1084
   1 mask(s); stray ids over the run: none
```

## A12 step 6/7: tests/test_engine_bundle_golden.py with the committed fixture (no skips)

- log: `runs/p3/A-2/A12-golden-pytest-2.log`
- exit: 0 (expected 0) -> PASS

```
.....                                                                    [100%]
```

note: run A-2: packet A12-1 (pixels 1.1 % of the width left of the projection) was the UTM grid convergence applied as a true heading, fixed in the render commandlet by the Windows builder (eb9e5f30); packet A12-2 (verifier landmark check) fixed by the Mac in 968dcb60; fixture tests/fixtures/engine_bundle_min committed in a72c8303 (807,894 bytes, RUN_ID 7237db488652)

## verdict

PASS
