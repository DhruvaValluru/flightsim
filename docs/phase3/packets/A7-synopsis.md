# A7 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T18:06:34Z

## A7 step 8: delete the imported A-4 asset, Generate (import), then Generate again (render)

- log: `runs/p3/A-2/A7-summary.log`
- exit: 0 (expected 0) -> PASS

```
run 7bbda8c5a4c3 (ue/Content/Aircraft/A4 deleted, Generate): aircraft | the A4 model is not on this machine yet or is out of date; building it once (fetch at the pinned commit, convert, import) ; aircraft | importing 1 aircraft into the Unreal project ; aircraft | the A4 model is ready ; ue/Content/Aircraft/A4 recreated (body.uasset, TEX_A4E_1/2, mat_A4E_1/2); render crashed for memory (machine note)
run 57db7c98102f (Generate again, quiet machine): no import; host flight 220 samples; 220 frames rendered; labels 220 of 220; done: clip ready
run 9bf1e3e387a9 (A4.json touched, Generate): aircraft | the A4 mesh manifest is stale (the mesh manifest is older than A4.json); re-converting so the mesh is drawn where its label is ; aircraft | converting (license-verified, FDM-matched) ; aircraft | the A4 model is ready ; one re-convert, no second import line, no loop; 220 frames rendered; labels 220 of 220; done: clip ready (verification: only landmark_reprojection FAIL, the Mac's A12 follow-up; mask_vs_geometry now passes on MAIN)
```

## A7 step 9: touch A4.json, Generate: one re-convert, no import loop

- log: `runs/p3/A-2/A7-web-post-5.log`
- exit: 0 (expected 0) -> PASS

```
status 200
{"run_id":"9bf1e3e387a9","digest":"c5c75d19687cf6b521db3ad49b69a9e41226941a3ef21b714d80932df9238fb4"}
```

note: run A-2 on UE 5.7.4 (build 3b05ec5a after the A12 merge): the first render after the import crashed for memory (three crashes with AvailablePhysical 0, machine note), the same card rendered once the machine was quiet

## verdict

PASS
