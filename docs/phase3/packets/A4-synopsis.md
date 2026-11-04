# A4 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T16:20:54Z

## A4 step 6-7: PowerShell Get-PluginSourceHash fixture vs golden, repo vs python twin

- log: `runs/p3/A-2/A4-ps-hash.log`
- exit: 0 (expected 0) -> PASS

```
fixture  0141215eaa199cccb8b67a2acbdccecfcb70e4487506da5a93a326abcc05dc49
golden   0141215eaa199cccb8b67a2acbdccecfcb70e4487506da5a93a326abcc05dc49
repo-ps1 770fa283dc1b178644309885b1e7ed82fb9d321dd89eefdef516a0c21cf69ac5
```

## A4 step 8 first half (web path, 5.7 build): FlightSimSky.cpp edited, no rebuild, POST /run

- log: `runs/p3/A-2/A4-stale-web.log`
- exit: 0 (expected 0) -> PASS

```
status 409
{"refused":"the built bridge is from source 770fa283dc1b178644309885b1e7ed82fb9d321dd89eefdef516a0c21cf69ac5 but the source is now b714730baf8a102f94876c228334dc80fc21ea71f668d64f7ecbf916e5286ffc","constraint":"engine.binary_stale","sentence":"The request was refused.","hint":"","details":{"rule":"the built bridge is from source 770fa283dc1b178644309885b1e7ed82fb9d321dd89eefdef516a0c21cf69ac5 but the source is now b714730baf8a102f94876c228334dc80fc21ea71f668d64f7ecbf916e5286ffc","message":"","catalogued":false}}
```

## A4 step 8 second half: source reverted, POST /run accepted and the run completed

- log: `runs/p3/A-2/A4-fresh-web.log`
- exit: 0 (expected 0) -> PASS

```
status 200
{"run_id":"4be692c3e9fe","digest":"c5c75d19687cf6b521db3ad49b69a9e41226941a3ef21b714d80932df9238fb4"}
status 200 run 4be692c3e9fe done: clip ready (host flight 220 samples, 220 frames rendered, labels attached on 220 of 220)
```

note: run A-2 on 23bad766 / UE 5.7.4 build 770fa283 (build_stamp.json engine_version 5.7.4); the stale POST returned HTTP 409 engine.binary_stale naming both hashes; the reverted POST returned 200 run 4be692c3e9fe which finished 'done: clip ready'

## verdict

PASS
