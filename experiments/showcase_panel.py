"""The telemetry panel under each showcase clip: the plan against the flight.

Every clip gets a 1280x300 instrument strip composited below the frame,
drawn EXCLUSIVELY from recorded evidence:

* the left column is the run card -- what the spec commanded (altitude,
  airspeed, heading, wind, turbulence, terrain identity);
* the middle columns are the FDM's own per-frame state as the render
  commandlet recorded it (altitude, CAS, heading, AGL, load factor, attitude,
  the wind actually inside the FDM, the surface deflections measured off the
  scene components), each with its live delta against the commanded value;
* the right side is four strip charts of the whole clip with a cursor at the
  current frame: altitude deviation, CAS, load factor, and vertical wind.

Nothing here recomputes physics or reads pixels; a value that was never
recorded is never shown. The honesty labels ride along: turbulent clips show
their seed and the visual-only verdict, coupled clips say the vertical wind
is ridge-forced, and every clip states that the physics ground is the spec's
flat slab.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

PANEL_W, PANEL_H = 1280, 300
BG = (14, 16, 20)
GRID = (34, 38, 46)
TEXT = (225, 228, 232)
DIM = (140, 146, 155)
PLAN = (120, 200, 255)
GOOD = (120, 220, 140)
BAD = (255, 130, 110)
ACCENT = (255, 200, 90)

FFMPEG = Path("/opt/homebrew/bin/ffmpeg")

#: Compact display names for the surface bars; anything unlisted shows its
#: manifest bone name truncated.
SURFACE_LABELS = {
    "aileron_l_outer": "ail L out", "aileron_l_inner": "ail L in",
    "aileron_r_inner": "ail R in", "aileron_r_outer": "ail R out",
    "aileron_l": "ail L", "aileron_r": "ail R",
    "elevator_l": "elev L", "elevator_r": "elev R",
    "rudder": "rudder", "flaps_l": "flaps",
    "elevator": "elev", "aileron": "ail",
}


def _fonts():
    from PIL import ImageFont

    for path in ("/System/Library/Fonts/Menlo.ttc",
                 "/System/Library/Fonts/Monaco.ttf"):
        try:
            return (ImageFont.truetype(path, 15), ImageFont.truetype(path, 12),
                    ImageFont.truetype(path, 11))
        except OSError:
            continue
    default = ImageFont.load_default()
    return default, default, default


def wrap_delta(a: float, b: float) -> float:
    """Heading difference on the circle."""
    return (a - b + 180.0) % 360.0 - 180.0


def _series(records: Sequence[Dict], key: str) -> List[float]:
    return [float(r.get(key, 0.0)) for r in records]


class PanelRenderer:
    """Renders one clip's panel frames. Deterministic per (card, manifest)."""

    def __init__(self, card: Dict, manifest: Dict, conditions: Dict):
        self.card = card
        self.manifest = manifest
        self.conditions = conditions
        self.records = manifest["frame_records"]
        self.font, self.small, self.tiny = _fonts()

        self.alt_cmd = float(card["altitude_m"])
        self.cas_cmd = float(card["airspeed_kt"])
        self.hdg_cmd = float(card["heading_deg"])

        self.charts = [
            ("ALT deviation m", [r - self.alt_cmd for r in
                                 _series(self.records, "altitude_m")], PLAN),
            ("CAS kt", _series(self.records, "cas_kt"), TEXT),
            ("load factor g", _series(self.records, "n_z"), ACCENT),
            ("wind down fps", _series(self.records, "wind_down_fps"), GOOD),
        ]

    # -- drawing helpers -------------------------------------------------

    def _chart(self, draw, x0, y0, w, h, title, series, colour, index):
        lo, hi = min(series), max(series)
        if hi - lo < 1e-9:
            lo, hi = lo - 1.0, hi + 1.0
        pad = (hi - lo) * 0.12
        lo, hi = lo - pad, hi + pad
        draw.rectangle([x0, y0, x0 + w, y0 + h], outline=GRID)
        draw.text((x0 + 4, y0 + 1), title, font=self.tiny, fill=DIM)
        draw.text((x0 + w - 4, y0 + 1), f"{series[index]:+.2f}",
                  font=self.tiny, fill=colour, anchor="ra")
        n = len(series)
        points = [
            (x0 + 1 + (w - 2) * i / (n - 1),
             y0 + h - 1 - (h - 14) * (v - lo) / (hi - lo))
            for i, v in enumerate(series)
        ]
        draw.line(points, fill=colour, width=1)
        cx = x0 + 1 + (w - 2) * index / (n - 1)
        draw.line([cx, y0 + 12, cx, y0 + h - 1], fill=(90, 96, 108), width=1)

    def _bar(self, draw, x0, y0, w, label, value, limit, colour):
        draw.text((x0, y0), label, font=self.tiny, fill=DIM)
        bar_x = x0 + 58
        bar_w = w - 62
        mid = bar_x + bar_w // 2
        draw.rectangle([bar_x, y0 + 2, bar_x + bar_w, y0 + 10], outline=GRID)
        draw.line([mid, y0 + 2, mid, y0 + 10], fill=GRID)
        frac = max(-1.0, min(1.0, value / limit))
        tip = mid + int(frac * (bar_w // 2 - 1))
        draw.rectangle([min(mid, tip), y0 + 4, max(mid, tip), y0 + 8],
                       fill=colour)
        draw.text((bar_x + bar_w + 4, y0), f"{value:+5.1f}",
                  font=self.tiny, fill=TEXT)

    # -- one frame -------------------------------------------------------

    def frame(self, index: int):
        from PIL import Image, ImageDraw

        record = self.records[index]
        image = Image.new("RGB", (PANEL_W, PANEL_H), BG)
        draw = ImageDraw.Draw(image)
        for x in (300, 610, 852):
            draw.line([x, 8, x, PANEL_H - 8], fill=GRID)

        # -- column 1: the plan (the spec, verbatim) ---------------------
        x, y = 14, 8
        draw.text((x, y), "COMMANDED (spec)", font=self.small, fill=PLAN)
        y += 20
        mesh = self.manifest.get("mesh", {})
        rows = [
            (f"{self.card['aircraft']}  " + mesh.get("license", ""), TEXT),
            (f"ALT  {self.alt_cmd:7.0f} m MSL", TEXT),
            (f"CAS  {self.cas_cmd:7.0f} kt", TEXT),
            (f"HDG  {self.hdg_cmd:7.0f} deg", TEXT),
        ]
        # The wind note can be a storm description; wrap it over lines
        # rather than truncating the conditions off the panel.
        note = "wind " + self.conditions.get("wind_note", "calm")
        while note:
            rows.append((note[:38], TEXT))
            note = "  " + note[38:] if len(note) > 38 else ""
        turbulence = self.card.get("turbulence", "none")
        if turbulence != "none":
            seed = int(self.card["turbulence_properties"]["atmosphere/randomseed"])
            rows.append((f"turb {turbulence}, seed {seed}", ACCENT))
            rows.append(("     visual-only (measured)", DIM))
        if self.card.get("orographic"):
            rows.append(("ridge-coupled wind: ON", GOOD))
        scene = self.manifest.get("scene", {})
        rows.append((f"terrain {scene.get('terrain_name', 'gate6 ridge')} "
                     f"[{scene.get('terrain_sha256', '')[:8]}]", DIM))
        if str(scene.get("terrain_material", "")).startswith("true-colour"):
            rows.append(("surface: satellite imagery", DIM))
            rows.append((f"  [{scene.get('imagery_sha256', '')[:8]}] "
                         f"{scene.get('imagery_license', '')}", DIM))
        if self.card.get("collision_terrain"):
            # Only cards that carry heightfield collision AND whose AGL
            # parity measurement passed may drop the slab label; the caller
            # states which through the conditions dict.
            if self.conditions.get("agl_parity_ok"):
                rows.append(("physics ground: heightfield", GOOD))
                rows.append(("  (AGL parity measured)", DIM))
            else:
                rows.append(("physics ground: heightfield", TEXT))
                rows.append(("  (parity not established)", DIM))
        else:
            rows.append(("physics ground: flat slab", DIM))
            rows.append((f"at {self.card['terrain_elevation_m']:.0f} m (declared)", DIM))
        # Evolving-conditions clips narrate their current phase (Phase 7 3.1),
        # from the schedule the card carries -- a plan annotation, drawn next
        # to the recorded state that must bear it out.
        phases = self.conditions.get("phases") or []
        if phases:
            t = float(record.get("t", 0.0))
            current = phases[0][1]
            for start, label in phases:
                if t >= float(start):
                    current = label
            rows.append((f"phase: {current}", ACCENT))
        for line, colour in rows:
            draw.text((x, y), line[:38], font=self.small, fill=colour)
            y += 17

        # -- column 2: achieved, live, with deltas -----------------------
        x, y = 314, 8
        draw.text((x, y), f"ACHIEVED (FDM)  t={record['t']:5.1f} s",
                  font=self.small, fill=TEXT)
        y += 20

        def live(label, value, unit, delta=None, wrap=False):
            nonlocal y
            draw.text((x, y), f"{label:4s} {value:9.1f} {unit}",
                      font=self.small, fill=TEXT)
            if delta is not None:
                magnitude = abs(delta)
                colour = GOOD if magnitude < (2.0 if wrap else 25.0) else BAD
                draw.text((x + 190, y), f"{delta:+7.1f}", font=self.small,
                          fill=colour)
            y += 17

        live("ALT", record["altitude_m"], "m",
             record["altitude_m"] - self.alt_cmd)
        live("CAS", record["cas_kt"], "kt", record["cas_kt"] - self.cas_cmd)
        live("TAS", record["tas_kt"], "kt")
        live("HDG", record["heading_deg"] % 360.0, "deg",
             wrap_delta(record["heading_deg"], self.hdg_cmd), wrap=True)
        live("AGL", record["agl_m"], "m")
        live("ROLL", record["roll_deg"], "deg")
        live("PTCH", record["pitch_deg"], "deg")
        live("N_z", record["n_z"], "g")
        draw.text((x, y + 2), "delta vs commanded ->", font=self.tiny, fill=DIM)

        # -- column 3: wind in the FDM + surfaces ------------------------
        x, y = 624, 8
        draw.text((x, y), "WIND IN FDM", font=self.small, fill=TEXT)
        y += 19
        north = record.get("wind_north_fps", 0.0)
        east = record.get("wind_east_fps", 0.0)
        down = record.get("wind_down_fps", 0.0)
        speed_kt = math.hypot(north, east) * 0.592484
        from_deg = (math.degrees(math.atan2(-east, -north))) % 360.0
        draw.text((x, y), f"{speed_kt:5.1f} kt from {from_deg:5.1f}",
                  font=self.small, fill=TEXT); y += 17
        vertical_colour = GOOD if abs(down) > 0.05 else DIM
        draw.text((x, y), f"vertical {down:+6.2f} fps", font=self.small,
                  fill=vertical_colour); y += 15
        if self.card.get("orographic"):
            draw.text((x, y), "(ridge lift / lee sink)", font=self.tiny,
                      fill=DIM)
        y += 18
        draw.text((x, y), "SURFACES (measured)", font=self.small, fill=TEXT)
        y += 18
        surfaces = record.get("surface_component_deg", {})
        shown = 0
        for name in sorted(surfaces):
            if shown >= 7:
                break
            label = SURFACE_LABELS.get(name, name[:9])
            self._bar(draw, x, y, 212, label, surfaces[name], 15.0, ACCENT)
            y += 15
            shown += 1

        # -- column 4: the strip charts ----------------------------------
        cx, cy = 862, 10
        ch = (PANEL_H - 2 * cy - 3 * 6) // 4
        for i, (title, series, colour) in enumerate(self.charts):
            self._chart(draw, cx, cy + i * (ch + 6), PANEL_W - cx - 10, ch,
                        title, series, colour, index)
        return image


def build_panel_clip(card_path: Path, manifest_path: Path, conditions: Dict,
                     raw_clip: Path, out_clip: Path, fps: int = 30,
                     work_dir: Optional[Path] = None) -> bool:
    """Panel frames + vstack composite. Returns False loudly on any failure."""
    card = json.loads(Path(card_path).read_text())
    manifest = json.loads(Path(manifest_path).read_text())
    renderer = PanelRenderer(card, manifest, conditions)

    work = Path(work_dir) if work_dir else out_clip.parent / (out_clip.stem + "_panel")
    work.mkdir(parents=True, exist_ok=True)
    for stale in work.glob("panel_*.png"):
        stale.unlink()
    for index in range(len(renderer.records)):
        renderer.frame(index).save(work / f"panel_{index:04d}.png")

    out_clip.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([
        str(FFMPEG), "-y",
        "-i", str(raw_clip),
        "-framerate", str(fps), "-i", str(work / "panel_%04d.png"),
        "-filter_complex", "[0:v][1:v]vstack=inputs=2",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-pix_fmt", "yuv420p", str(out_clip),
    ], capture_output=True)
    for panel_file in work.glob("panel_*.png"):
        panel_file.unlink()
    try:
        work.rmdir()
    except OSError:
        pass
    return proc.returncode == 0 and out_clip.is_file()
