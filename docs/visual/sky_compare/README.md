# Sky compare: the owner's four frames against the old look

Sky step 8 of the X-Plane-12 brief (docs/visual/XPLANE_SKY_BRIEF.md; design
docs/visual/XPLANE_SKY_DESIGN.md §10). One scene, one camera, four fixed frames
(clear, scattered cumulus, broken stratocumulus, overcast), laid out against the
previous round's frame of the same scene so the owner can judge on the Windows
laptop. **Nothing under this folder exists until that laptop has run the command
below; every frame named here is UNMEASURED until then.** The Mac never renders.

## Which code the four frames render (read this first)

`scripts/visual_fix_round.ps1`, which the compare calls four times, checks out a
branch and fast-forwards it **from origin** before every round (its step 1;
default `claude/vibrant-gauss-olema4`, now its `-Branch` parameter). So the laptop
renders origin's copy of that branch, never the checkout you happen to stand on.
`sky_compare_round.ps1` passes `-Branch` (default: the branch of the current
checkout) and refuses by name, `compare.wrong_branch`, before round 1 unless
`origin/<branch>` carries `scripts/sky_contact_sheet.py` and `PLAN_CLOUD_SHAPES` in
`core/scene/world_beauty.py`. Without that check the command would have rendered
fbcbaa5d, the host before sky step 2, where `-cloud-type=` is not parsed and is
silently ignored: four frames of one look.

The four frames therefore show the sky steps **only after** claude/xplane-sky has
been pushed (run the command from that checkout), or merged into
`claude/vibrant-gauss-olema4` and pushed (run it from that checkout, or pass
`-Branch claude/vibrant-gauss-olema4`). Nothing was pushed when this was written.

## Where the frames land

```
docs/visual/round_<N>/      clear          (visual_fix_round.ps1's folder: NN_<slug>.jpg, ROUND.json, metrics.json)
docs/visual/round_<N+1>/    cumulus
docs/visual/round_<N+2>/    stratocumulus
docs/visual/round_<N+3>/    overcast
docs/visual/sky_compare/round_<N>/sheet.jpg      row 1 the old frame (round M), row 2 the four, captioned
docs/visual/sky_compare/round_<N>/compare.json   per tile: requested word, applied shape, source, MISMATCH,
                                                 switch_seen, pixel numbers vs the old frame, health flags,
                                                 commit, switches; the lists mismatches / unknown /
                                                 switch_not_seen / no_record / missing; the reading rule
```

Each of the four rounds is pushed to branch `vis-windows` by visual_fix_round.ps1
as usual; the compare folder is pushed there too (`-NoPush` keeps both local).
Round folders live on `vis-windows`, not on the code branch, so the sheet looks
for every round folder, round M included, under `docs\visual` first and then
`runs\vis-windows-wt\docs\visual` (visual_fix_round.ps1's worktree, the same two
places its step 4b reads, in the same order); compare.json records which root
each frame came from (`old_root`, per tile `root`). A round number that already
exists in either place is refused (`compare.round_exists`): visual_fix_round.ps1
would overwrite it in vis-windows.

## The exact commands (Windows, from C:\Users\kanth\flightsim)

Steps 2, 3 and 5 reserved rounds 98-105 for their own probes
(docs/VISUAL_FIDELITY_PLAN.md §8), so the sky compares start at 110 and 115.

```
$env:FLIGHTSIM_SKY = "physical"          # the script sets it when unset, and records it
# the primary camera: scene 3, the A320 over New York (600 m, 18 mm), vs round 95
.\scripts\sky_compare_round.ps1 -Round 110 -Scene 3 -CompareWith 95
# the secondary camera: scene 13, the 747 at 10 km over the ocean
.\scripts\sky_compare_round.ps1 -Round 115 -Scene 13 -CompareWith 95
# an A/B set carrying one more switch on all four frames is its own -Round
.\scripts\sky_compare_round.ps1 -Round 120 -Scene 3 -CompareWith 111 -Switches "-cloud-march=probe"
# from a checkout of another branch than the one to render
.\scripts\sky_compare_round.ps1 -Round 110 -Scene 3 -CompareWith 95 -Branch claude/vibrant-gauss-olema4
```

The sheet alone, for rounds that already exist:

```
.venv\Scripts\python.exe scripts\sky_contact_sheet.py --rounds 110,111,112,113 --scene 3 --old 95 --fallback-root runs\vis-windows-wt\docs\visual
```

## How to read the sheet

- Row 1 is the old look: round M's frame of the same scene (the design's "round
  95 #03" / "#13" are the frames the owner named). Round M may have rendered
  without `FLIGHTSIM_SKY=physical` (the earlier rounds relied on the shell), so
  the compare can change the sky path and the cloud word at once; compare.json
  records M's `commit` and `switches` from its ROUND.json (`old_commit`,
  `old_switches`) beside the new rounds' `flightsim_sky`.
- Row 2, left to right: `-cloud-type=clear`, `cumulus`, `stratocumulus`,
  `overcast`. The caption's first line is the round and the word REQUESTED; the
  second is the shape the host says it APPLIED
  (`look_applied.world_beauty.clouds.layers[0].cloud_type_applied` and its
  `cloud_type_source`; `clear` leaves the layer in `hidden_layers` and reads
  "no layer"), with `MISMATCH` when the two disagree, or `applied unknown` when
  the record names no shape at all (a host before sky step 2, `-beauty-clouds=engine`,
  a cloud material that did not load: the record's `clouds.drawn` string is shown);
  the third is the march tier (`clouds.march.tier`) and the sky's
  `multi_scattering_factor`, or, when the record does not carry the word asked in
  `clouds.plan.cloud_type_switch`, `host predates sky step 2: -cloud-type= not
  parsed` (or `host parsed -cloud-type=<other>, not <word>`). Alarm colour on
  every one of these.
- `MISSING` on a tile means no round folder in either root wrote a frame for the
  scene; the row is in compare.json with `found: false`. Nothing is dropped and
  nothing is a gate.
- **The reading rule** (compare.json `reading_rule`): `mismatches`, `unknown`,
  `switch_not_seen`, `no_record` and `missing` must ALL be empty, and every tile's
  `applied` must be a shape word or "no layer". A round in `unknown` or
  `switch_not_seen` is also in `mismatches`. Only then did each word draw its own
  shape on a host that saw the switch; the sheet cannot otherwise tell "switch
  honoured" from "switch never seen".
- Scene 13 (the 747 at 10 km): under `stratocumulus` and `overcast` the plan
  layer keeps its altitude (core/sky/plan.py: bottom = max(2 km, AGL + 1 km), so
  about 11 km), and those two tiles show a deck ABOVE the aircraft, not an
  overcast below it. Only an unstated cumulus layer is lowered below a high cruise
  (FlightSimClouds.cpp `CumulusLayerLowered`, c641a8c4; the camera stays clear
  either way). That is the rule, not a bug in the frame.
- The numbers in compare.json are scripts/visual_compare.py's (mean absolute
  luma change, share of pixels moved more than 8 levels, mean luma) and
  scripts/frame_metrics.py's health (blank / clipped / crushed) with its
  UNCALIBRATED thresholds. They say "darker" or "brighter" as a number; they do
  not say "better".

## What is not here yet

Steps 1 (wisps), 4 (atmosphere, sun bloom) and 6 (cirrus) of the brief are not on
branch claude/xplane-sky. Once the branch precondition above is met, the four
frames compare the step 2/3/5 host (the plan's cloud fields, `-cloud-type=`, the
tiered march) against round M; until it is met they measure nothing about the
sky steps, and the script refuses rather than render the old host. When steps
1/4/6 merge, the same command renders them: the compare is the verify path, not
the look.
