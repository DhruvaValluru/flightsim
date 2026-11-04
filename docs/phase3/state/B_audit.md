# Letter B audit (auditor, sonnet) - verdict FAIL
1. Letter tests (8 files: pins, platform, powershell, toolchain_doc, gate6_visual, render_flags, render_quality, mutation_targets): exit 0, 197 passed, 0 failed. PASS
2. Touched-module tests (test_randomization, test_sky, test_host_parity, test_google_tiles_source, test_phase6b, test_ue_materials, test_ue_weather_source, test_ue_world_source, test_ue_passes_source, test_parity_matrix, test_sun): exit 1.
   FAILED tests/test_ue_weather_source.py::test_a_storm_material_built_by_an_older_script_is_built_again
   Cause: scripts/ue_create_materials.py (letter B, Windows run A-2 fix) replaced rename_asset(full, aside) with duplicate_asset + delete_asset in _storm_material; the source test still asserts "rename_asset(full, aside)" in maker. Test not updated. FAIL
3. Mutation subset (60 guards on gate6_visual, gate5_ue_parity, randomization, render/flags, ue_preflight, toolchain.json):
   --check-targets: exit 0, all 60 occur once. PASS
   --no-suite: exit 0 but "2 of 60 guard(s) not covered by a failing test". FAIL
   WEAK [36/780] heading compared on the circle (experiments/gate5_ue_parity.py)
   WEAK [242/780] a second planner pass lands on the same jitter (core/scenario/randomization.py)
   (No guards exist for platform.py, showcase, evolving, sky/plan, deploy_windows, requirements.lock; the toolchain.json pin guard 351 and preflight guard 352 are ok.)
4. Diff guard fc7aee06..HEAD (excl. docs/phase3): GOOGLE_TILES|WEATHER_BACKEND|subscribe empty; added pytest.skip|xfail|TODO lines: none. PASS
5. Sanity: UE_ENGINE_VERSION/PATCH prints "5.7 4"; toolchain.json parses (exit 0); requirements.lock header names --python 3.12.10. PASS
Overall: FAIL (check 2 failure, check 3 two WEAK guards).

## re-audit after p3-fixB (Mac session, 2026-11-04)
- Letter tests (10 files incl. test_ue_weather_source, test_host_parity): exit 0.
- Guards 36, 350, 351 --no-suite: all load-bearing. Guard 242 (randomization jitter) was WEAK already at fc7aee06: baseline, phase end.
- Verdict: PASS.
