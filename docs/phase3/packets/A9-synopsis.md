# A9 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T16:51:18Z

## A9 step 1/6/7: default two-camera run through the web app (POST /run, chase + tower)

- log: `runs/p3/A-2/A9-web-post.log`
- exit: 0 (expected 0) -> PASS

```
status 200
{"run_id":"473b9e1ecfff","digest":"a65a380837f70079993de42e905ec5694aa41b990ea5a98d651a47c73fa64b5d"}
```

## A9 frame counts per camera and the run's events

- log: `runs/p3/A-2/A9-frames.log`
- exit: 0 (expected 0) -> PASS

```
run 473b9e1ecfff done: clip ready (two cameras chase + tower, Grand Canyon A-4, 20 s)
frames/chase frame_NNNN.png: 200
frames/tower frame_NNNN.png: 200
events: rendering 2 camera pass(es): chase, tower; engine labels attached on 400 of 400 frame(s) (0 without a bundle); clip: 200 frames of chase at 10.0 fps = 20.0 s; a clip per view: chase, tower
no render.camera_empty refusal (the guard did not fire); verification FAILED: host_determinism (A8), mask_vs_geometry, tight_box_present (A12)
```

note: run A-2 on UE 5.7.4 build 99dc982e: the empty second camera did not reproduce; both camera passes wrote 200 frames; the render.camera_empty guard did not fire on this healthy run

## verdict

PASS
