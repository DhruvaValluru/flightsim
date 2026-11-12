"""Split manifest.json into S shards (round-robin, so every shard mixes domains).

python swarm/shard.py --shards 4 --wave-size 200 --wave 0
Prints one JSON array per shard to swarm/shards/w<wave>_s<k>.json. Launch one
Workflow call per shard IN THE SAME TURN: each workflow has its own concurrency
cap (min(16, cores-2) = 8 on an M1 Max), so S shards run about 8*S agents at once.
"""
import argparse, json
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--shards", type=int, default=4)
ap.add_argument("--wave-size", type=int, default=200)
ap.add_argument("--wave", type=int, default=0)
a = ap.parse_args()
here = Path(__file__).parent
items = json.loads((here / "manifest.json").read_text())
wave = items[a.wave * a.wave_size:(a.wave + 1) * a.wave_size]
out = here / "shards"
out.mkdir(exist_ok=True)
for k in range(a.shards):
    part = wave[k::a.shards]
    (out / f"w{a.wave}_s{k}.json").write_text(json.dumps(part))
    print(f"w{a.wave}_s{k}: {len(part)} items")
