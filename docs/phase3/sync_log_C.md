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

