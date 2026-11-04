# Letter C audit (auditor, sonnet) -- verdict FAIL
Base for diff checks: 79d43a52 (98331123~3 omitted C2's a4_mdl_convert/importer/mdl_scene; merge-base of p3-C2 used).
1. Letter tests (11 files, `pytest -q -p no:cacheprovider`): exit 1; 194 tests, 1 failed, 1 skipped, 78.8 s. FAIL
   - FAILED tests/test_aircraft_assets.py::test_the_fail_safe_builds_a_missing_model_once (['B747','B747'] == ['B747'])
   - skipped: test_dataset_boxes::test_every_format_writes_the_mask_box_and_keeps_the_projected_one (pycocotools absent, env)
   - slowest: test_aircraft_assets A320 setup 32 s (none over 60 s). The first run was piped to tail and its exit hid the failure.
2. Touched-module tests (17 files: autoimport, binary_stale, camera_labels, camera_airframe, phase6b, aircraft_materials,
   camera_engine_parity, engine_bundle_golden, camera_verify, licence, buildings, landcover_labels, webapp_capture,
   camera_manifest, camera_cli, camera_verify_corruption, host_parity): 6 failed, rest passed. FAIL
   - tests/test_phase6b.py::test_every_aircraft_config_is_shippable_or_says_why_not
   - tests/test_engine_bundle_golden.py::test_verify_run_has_no_fail (mask_vs_geometry c172p hull 139x40 vs mask 129x30; geoid file absent)
   - tests/test_buildings.py::test_building_all_is_one_aggregate_object_after_the_terrain (ids now end in landing_gear:0, not terrain)
   - tests/test_landcover_labels.py::test_the_aggregates_are_one_id_each_after_the_terrain_and_stable (same cause)
   - tests/test_landcover_labels.py::test_the_manifest_builder_carries_land_cover_only_when_the_scene_has_it (same cause)
   - tests/test_camera_verify_corruption.py::test_placeholder_boxes_under_a_manifest_that_names_the_mesh_fail
   - tests/test_camera_cli.py two terrain-stem tests took 218 s each (over 60 s; passed).
   - Likely cause: C7 gives c172p a landing_gear component (c172p.json labels.components), so the c172p scene gains an
     object; tests written for the old object list were not updated. Base check (79d43a52) NOT valid: worktree run imported
     the main tree, so "not checked at base".
3. Mutation subset: 50 guards in letter-C files. --check-targets exit 0 (all 50 occur once); --no-suite exit 0:
   "All 50 guard(s) run are load-bearing" (332 s). PASS
4. Diff guard (code files of letter C): GOOGLE_TILES/WEATHER_BACKEND/subscribe empty; added skip/xfail/TODO none. PASS
   (whole-diff hits are only docs/PHASE3_LOG.md and scripts/phase3_integrate.sh text, not code.)
5. Sanity: COMPONENT_BAND (64, 127), component_mesh_name('A4','store_sta2') = SM_A4_store_sta2. PASS
   (card ids 64-69 test is test_card_components_lists_the_a4_loadout_in_the_band, in step 1, passed.)
