# max-push

Branch `max-push` is a copy of `claude/vibrant-gauss-olema4` plus the swarm
scaffold. Goal: the most photorealistic frames the Windows laptop (Intel iGPU,
D3D11) can sustain, with visuals as the focus.

**Idea.** The laptop can't render heavy techniques, but the Mac (M1 Max, 64 GB)
can precompute them. Agents bake offline and ship tiers (0 = stable on the
laptop, 1-3 heavier). The stress ladder run on the laptop picks the real tier.

## Run on the Mac, in a Claude Code session in this repo, on `max-push`

```bash
python swarm/shard.py --prefix m --wave 0 --wave-size 150 --shards 8 \
  --domains terrain,vegetation_autogen,aircraft_exterior,atmosphere_clouds,weather_fx,water,airports_lighting,lighting_exposure,camera_lens,hardware_perf,validation
```

Then tell Claude: "launch swarm/maxpush.workflow.js for all 8 shards in one
turn", passing each `swarm/shards/m0_s<k>.json` as `items`, the output of
`budget_from_file()` as `budget`, and `m0_s<k>` as `wave`. Repeat with
`--wave 1`, `--wave 2` for the rest. Lanes write only under `swarm/lanes/`;
a domain integrator then wires verified lanes into the shared files, one
domain at a time, and commits.

Visual domains only: flight dynamics and audio are left out on purpose.

## Maximum load

Agents per item: 1 research + 1 build + 3 verify + (0-1 repair) + 2 rounds x
(1 improve + 2 verify) = 11 to 12. 395 items is about 4,400 agents in total.
`args.rounds` sets the deepen rounds (default 2; use 4 for roughly 6,200).

Concurrency is 8 per workflow on this Mac, and a run is capped at 1,000
agents (about 80 items at rounds=2). Run everything at once with 5 shards of
79 items (about 40 agents at a time), or split finer for more width:

```bash
python swarm/shard.py --prefix x --wave 0 --wave-size 400 --shards 5 \
  --domains terrain,vegetation_autogen,aircraft_exterior,atmosphere_clouds,weather_fx,water,airports_lighting,lighting_exposure,camera_lens,hardware_perf,validation
```

16 shards of 25 items is about 128 agents at a time.

The ceiling is your plan's rate limit, not the Mac. If you see 429s, drop
shards. To make the run last until credits are gone, add a token target to
your message (for example "+2M") and the `budget` hook lets loops keep going.
