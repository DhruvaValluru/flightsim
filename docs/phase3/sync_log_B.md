# Letter B sync log (Windows cross-check)

## B3 · PASS · run B-1 · 2026-11-04T17:40:16Z

verify line(s) from tasks/phase3_checklist.md:

```
100:   - Check: `pytest -q tests/test_toolchain_pins.py` passes.
```

output line(s) that satisfy it:

```
runs/p3/A-2/B3-pytest.log: .......                                                                  [100%]   (7 passed, exit 0)
```

note: run B-1 on 3e59358d; Python-only box, no Windows steps in the note; the pins the test guards (toolchain.json, EngineAssociation, IncludeOrderVersion, UE_ENGINE_VERSION, lock covers requirements.txt) are the ones this machine measured for decision 13

### synopsis

# B3 synopsis

run_id: B-1
machine: windows
written: 2026-11-04T17:40:15Z

## B3 verify: pytest -q tests/test_toolchain_pins.py

- log: `runs/p3/A-2/B3-pytest.log`
- exit: 0 (expected 0) -> PASS

```
.......                                                                  [100%]
```

note: run B-1 on 3e59358d (letter B push); 7 tests, all dots, exit 0

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
6e757d72 Phase 3 B3: integrated_commit stored as a string
73975501 Phase 3 B3/B4: builder notes and state restored from the integrator's stash
1fa0df0f B3: restore tests/test_toolchain_pins.py (a staged deletion slipped into the bookkeeping commit)
b3ed6a52 Phase 3 B3: integrated state and note; A6 and A8 PASS logged
69726238 Merge p3-B3: test_toolchain_pins keeps every pin in one place
679e9fb1 B3: the two engine-pin mutation guards also run tests/test_toolchain_pins.py
8f42b88d B3: tests/test_toolchain_pins.py keeps every pin in one place
af39a626 Merge branch 'p3-B1' into p3-B3

6e757d72 Phase 3 B3: integrated_commit stored as a string

 docs/phase3/state/B3.json | 4 ++--
 1 file changed, 2 insertions(+), 2 deletions(-)

73975501 Phase 3 B3/B4: builder notes and state restored from the integrator's stash

 docs/phase3/notes/B3.md   | 11 +++++++++++
 docs/phase3/notes/B4.md   | 11 +++++++++++
 docs/phase3/state/B3.json | 10 +++++++---
 docs/phase3/state/B4.json | 18 +++++++++++++++---
 4 files changed, 44 insertions(+), 6 deletions(-)

1fa0df0f B3: restore tests/test_toolchain_pins.py (a staged deletion slipped into the bookkeeping commit)

 tests/test_toolchain_pins.py | 238 +++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 238 insertions(+)

b3ed6a52 Phase 3 B3: integrated state and note; A6 and A8 PASS logged

 docs/phase3/events_mac.log   |   3 +
 docs/phase3/notes/B3.md      |   3 +
 docs/phase3/state/B3.json    |   5 +-
 tests/test_toolchain_pins.py | 238 -------------------------------------------
 4 files changed, 9 insertions(+), 240 deletions(-)

69726238 Merge p3-B3: test_toolchain_pins keeps every pin in one place

 docs/phase3/events_mac.log   |   6 ++
 scripts/mutation_check.sh    |   4 +-
 tests/test_toolchain_pins.py | 238 +++++++++++++++++++++++++++++++++++++++++++
 3 files changed, 246 insertions(+), 2 deletions(-)

679e9fb1 B3: the two engine-pin mutation guards also run tests/test_toolchain_pins.py

 scripts/mutation_check.sh | 4 ++--
 1 file changed, 2 insertions(+), 2 deletions(-)

8f42b88d B3: tests/test_toolchain_pins.py keeps every pin in one place

 tests/test_toolchain_pins.py | 238 +++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 238 insertions(+)

af39a626 Merge branch 'p3-B1' into p3-B3

 .github/workflows/ci.yml   |   8 +-
 requirements.lock          | 737 +++++++++++++++++++++++++++++++++++++++++++++
 scripts/deploy_windows.ps1 |   8 +-
 3 files changed, 748 insertions(+), 5 deletions(-)
```

