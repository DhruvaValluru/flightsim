# Letter A audit (f27ef80a)
Verdict: FAIL audit A: 3 letter-A regressions (pass on bd68745b, fail now)
Suite: 3215 passed, 8 failed, 17 skipped (pytest exit 1; no summary line was printed, counted from progress dots)
Regressions:
- tests/test_capture_cli_words.py::test_the_help_names_the_engine_version_that_is_pinned (render --help text still contains "UE 5.5")
- tests/test_mutation_targets.py::test_every_mutation_target_occurs_exactly_once_in_its_file (targets not found: guards 123, 173, 218, 359)
- tests/test_platform.py::test_no_text_io_without_utf8_encoding (open/read_text without encoding='utf-8' in tests/engine_launch.py, tests/test_aircraft_autoimport.py, ...)
Baseline (fail on base too, recorded in state): test_ue_physics_source gauss_legendre; test_shear fixture refuses; test_traceability regeneration script; test_wake card block; test_weather soundtrack script.
Skips: 5 golden-fixture (windows: fixture engine_bundle_min not committed yet); pycocotools x3; EGM2008 grid x4; node not installed x3; real bakes absent x4 (surface_inference, terrain, weightmaps x2). No ue_host skip.
Mutation subset (--no-suite, because the baseline suite is red): all 7 caught: 346, 350, 351, 352 (preflight), 411, 412, 413 (components).
