# C1 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T15:59:05Z

## C1 verify (test names): pytest -v tests/test_airframe.py -k components

- log: `runs/p3/A-2/C1-pytest-v.log`
- exit: 0 (expected 0) -> PASS

```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.6.0
rootdir: C:\Users\kanth\flightsim
configfile: pytest.ini
plugins: anyio-4.14.2, timeout-2.3.1
timeout: 900.0s
timeout method: thread
timeout func_only: False
collected 6 items

tests\test_airframe.py ......                                            [100%]

============================== 6 passed in 1.80s ==============================
            [JSBSim-ML v2.0]

JSBSim startup beginning ...

```

note: run A-2 on the 5.7 pin sweep (23bad766); 6 passed incl. test_components_loadout_trims

## verdict

PASS
