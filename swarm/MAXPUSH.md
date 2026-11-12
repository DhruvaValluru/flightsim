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
