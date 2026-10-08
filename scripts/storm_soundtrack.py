"""Write a run's storm soundtrack (thunder + rain) from its run card.

    python scripts/storm_soundtrack.py RUN_CARD.json OUT.wav [--listener E,N,U]
        [--seconds S] [--sample-rate HZ] [--no-rain]

Every flash on the card's ``weather.lightning`` is synthesised as heard at
the listener (metres east / north / up of the storm cell's centre, the
card's downburst block; default 5 km east, 2 m up) at the flash's own run
time, plus the rain noise of ``weather.rain`` (core/scene/thunder.py). The
WAV is 16-bit mono at thunder.FULL_SCALE_PA full scale, sample 0 at run
time 0, so it lines up with the rendered frames for muxing. Prints a JSON
summary (clipped samples counted, never hidden).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.scene import thunder  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("card", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--listener", default="5000,0,2",
                        help="east,north,up metres from the cell centre")
    parser.add_argument("--seconds", type=float, default=None,
                        help="length (default: the card's duration_s)")
    parser.add_argument("--sample-rate", type=int, default=thunder.SAMPLE_RATE_HZ)
    parser.add_argument("--no-rain", action="store_true")
    args = parser.parse_args(argv)

    card = json.loads(args.card.read_text(encoding="utf-8"))
    weather = card.get("weather")
    if not weather:
        print(json.dumps({"error": "weather.absent: the card carries no weather block"}))
        return 2
    listener = tuple(float(v) for v in args.listener.split(","))
    if len(listener) != 3:
        parser.error("--listener takes east,north,up")
    seconds = args.seconds if args.seconds is not None else float(card.get("duration_s", 60.0))
    samples = thunder.soundtrack(weather, seconds, lambda _t: listener, args.sample_rate,
                                 rain=not args.no_rain)
    record = thunder.write_wav(str(args.out), samples, args.sample_rate)
    record["flashes"] = len((weather.get("lightning") or {}).get("flashes", []))
    record["listener_enu_m"] = list(listener)
    print(json.dumps(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
