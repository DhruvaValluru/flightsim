# A8 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T17:13:24Z

## A8 step 6: web-app run with host flight on (POST /run) on the merged 3dc6a5ec build

- log: `runs/p3/A-2/A8-web-post.log`
- exit: 0 (expected 0) -> PASS

```
status 200
{"run_id":"7274c62756ea","digest":"c5c75d19687cf6b521db3ad49b69a9e41226941a3ef21b714d80932df9238fb4"}
```

## A8 step 6: the run's record, determinism and flag check

- log: `runs/p3/A-2/A8-run-summary.log`
- exit: 0 (expected 0) -> PASS

```
run 7274c62756ea done: clip ready (host flight on by default, tiles on, storm on; Grand Canyon A-4 chase)
events: host flight 220 samples; every camera re-solved over the host's own flight; rendering 1 camera pass(es): chase; engine labels attached on 220 of 220 frame(s) (0 without a bundle); verification FAILED: mask_vs_geometry (A12's); clip: 220 frames of chase at 10.0 fps = 22.0 s
verify.json host_determinism PASS: 2 host flights of one card were byte-identical (6bc9dcc5e613, 220 samples): the host is reproducible
verify.json flight_agreement PASS; solve pass vs chase pass telemetry: 0 columns differ
host_flight/host_telemetry.log: LogFlightSimScenario: Display: ground: collision raster C:\Users\kanth\flightsim\runs\terrain\grand_canyon; LogInit: Display: Success - 0 error(s), 4 warning(s)
no-host-flight mentions in the run record and the web app log for this run: 0 / 0
```

## A8 step 6: pytest -q tests/test_host_parity.py (19 passed; the 1 failure is a Windows path-separator assertion in the Mac's d4fd0dfd test, not a parity result)

- log: `runs/p3/A-2/A8-pytest-host-parity.log`
- exit: 1 (expected 0) -> FAIL

```
..................F.                                                     [100%]
================================== FAILURES ===================================
_________________ test_preflight_on_mac_runs_ue_preflight_sh __________________

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x000001D35D811B80>

    def test_preflight_on_mac_runs_ue_preflight_sh(monkeypatch):
        argv, kwargs = _capture_preflight(monkeypatch, "mac")
>       assert len(argv) == 1 and argv[0].endswith("scripts/ue_preflight.sh")
E       AssertionError: assert (1 == 1 and False)
E        +  where 1 = len(['C:\\Users\\kanth\\flightsim\\scripts\\ue_preflight.sh'])
E        +  and   False = <built-in method endswith of str object at 0x000001D35E8F66D0>('scripts/ue_preflight.sh')
E        +    where <built-in method endswith of str object at 0x000001D35E8F66D0> = 'C:\\Users\\kanth\\flightsim\\scripts\\ue_preflight.sh'.endswith

tests\test_host_parity.py:475: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_host_parity.py::test_preflight_on_mac_runs_ue_preflight_sh
            [JSBSim-ML v2.0]

JSBSim startup beginning ...

```

note: run A-2: steps 1-2 in packet A8-1; cause 1 (commandlet exit 1, Water profile) fixed by the A5 builder 2b746352; cause 2 (agl_m from the streamed world) fixed by the A8 builder 3dc6a5ec (decision 12), merged 3a8c369f; the cross-check judges the sheet line PASS and names the failing test as the Mac's

## verdict

FAIL
