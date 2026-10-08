"""Print what a finished run actually did, in one screen, to paste into a bug report.

    python scripts/inspect_run.py 87bd8f7dfe4c b4c3755a811a

For each run id (a folder under runs/webapp/): the camera (preset,
placement, lens) and its first frame's pose; where the aircraft is in
that frame (in frame or not, its 2-D box, its distance); and what the
renderer recorded it applied (render.json look_applied: sun, exposure,
fog, lighting, weather look, rain, Google tiles, post-process). Nothing
is changed. Only the standard library is used.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RUNS = Path(__file__).resolve().parents[1] / "runs" / "webapp"
LOOK_KEYS = ("sun", "exposure", "fog", "lighting", "xplane_lighting", "weather_look",
             "aerosol", "clouds", "night", "not_claimed")


def short(value, limit: int = 600) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + " ..."


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def report(run_id: str) -> None:
    out = RUNS / run_id
    print(f"===== run {run_id} =====")
    if not out.is_dir():
        print(f"  no folder {out}")
        return
    card = load(out / "card.json") or {}
    manifest = load(out / "capture_manifest.json") or {}
    print(f"  prompt: {card.get('prompt') or (manifest.get('spec') or {}).get('prompt')}")
    for camera in manifest.get("cameras") or []:
        spec = {k: (v.get("value") if isinstance(v, dict) else v)
                for k, v in (camera.get("spec") or {}).items()}
        keep = {k: spec.get(k, camera.get(k)) for k in (
            "camera_id", "preset", "position_mode", "offset_forward_m", "offset_right_m",
            "offset_up_m", "aim_mode", "focal_length_mm", "trigger", "capture_count")}
        keep["inherits_roll"] = camera.get("inherits_roll")
        print(f"  camera: {short(keep, 400)}")
    frames = manifest.get("frames") or []
    if frames:
        first = frames[0]
        pose = {k: first.get(k) for k in ("camera_id", "t_s", "position_north_m", "position_east_m",
                                          "position_alt_m", "yaw_deg", "pitch_deg", "roll_deg",
                                          "fov_deg", "focal_length_mm") if k in first}
        print(f"  first frame pose: {short(pose, 400)}")
        state = first.get("state") or first.get("aircraft_state") or {}
        if state:
            print(f"  aircraft state: {short({k: state.get(k) for k in ('altitude_m', 'agl_m', 'cas_kt', 'roll_deg', 'pitch_deg', 'heading_deg', 'climb_rate_mps') if k in state}, 300)}")
        labels = first.get("labels") or {}
        box3 = labels.get("bbox_3d_camera") or {}
        print(f"  aircraft in frame: {labels.get('in_frame')}  bbox_2d: {labels.get('bbox_2d')}  "
              f"range_m: {box3.get('range_m')}  cg_m: {box3.get('cg_m')}")
    for render_json in sorted((out / "frames").glob("*/render.json")) or [out / "frames" / "render.json"]:
        data = load(render_json)
        if data is None:
            continue
        print(f"  {render_json.relative_to(out)}:")
        look = data.get("look_applied") or {}
        for key in LOOK_KEYS:
            if key in look:
                print(f"    look_applied.{key}: {short(look[key])}")
        others = [k for k in look if k not in LOOK_KEYS]
        if others:
            print(f"    look_applied also has: {others}")
        for key in ("world_applied", "google_tiles", "render_settings", "quality"):
            if key in data:
                print(f"    {key}: {short(data[key])}")
    events = []
    state_file = out / "state.json"
    if state_file.is_file():
        events = (load(state_file) or {}).get("events") or []
    for event in events[-8:]:
        print(f"  event: {event.get('status')}: {str(event.get('detail'))[:200]}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for run_id in sys.argv[1:]:
        report(run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
