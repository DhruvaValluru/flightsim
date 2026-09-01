"""The Phase 6B condition matrix: one command, every clip, nothing faked.

    {calm, 25 kt crosswind, 15 kt gusty headwind, moderate turbulence w/ seed}
        x {clear, hazy} x {dawn, noon}
        on 2 airframes over the two REAL terrains plus one synthesised control.

Each cell is a 720p30, 22-second clip rendered by the same commandlet the
gates measure, encoded to mp4, and given a manifest row carrying the spec
digest, terrain tile IDs + sha256, mesh + license, conditions and seed. The
final products are ``runs/showcase/clips/*.mp4``, ``contact_sheet.png`` (one
frame per clip) and ``showcase_manifest.json``.

Honesty rules, enforced in code
--------------------------------
* Turbulent cells are labeled ``visual-only`` with their seed: the measured
  same-seed verdict (experiments/turbulence_ue.py) is that the two hosts draw
  different realisations, so no parity is claimed for them.
* Windy cells over any terrain carry the orographic coupling; its C++ port is
  cross-checked against the Python provider per render (the selftest block in
  every manifest) and this harness re-verifies a sample of them.
* Every clip's physics ground is the spec's flat slab; the manifest row says
  so (``scenery_only_terrain``), because visual mountains must not imply the
  gear model felt them.
* Gusts are precomputed by the headless providers and carried per-step in the
  card -- one gust model, not two.
* A cell that cannot be rendered honestly is SKIPPED with its reason printed
  and recorded, never approximated silently.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.environment.gust import DiscreteGust  # noqa: E402
from core.environment.wind import SteadyWind  # noqa: E402
from core.fdm import units as u  # noqa: E402
from core.terrain.glo30 import LOCATIONS, bake, orographic_card_block  # noqa: E402
from core.terrain.heightfield import Heightfield  # noqa: E402
from core.terrain.synthesis import TerrainStatistics, generate  # noqa: E402
from experiments.gate5_ue_parity import reference_spec, write_run_card  # noqa: E402
from experiments.orographic_ue import verify_port  # noqa: E402

from core.util.platform import ue_editor_path  # noqa: E402

RULE = "=" * 96
EDITOR = ue_editor_path()
try:
    from core.util.platform import find_ffmpeg as _find_ffmpeg

    FFMPEG = _find_ffmpeg()
except Exception:       # ffmpeg.missing: the startup check below states it
    FFMPEG = Path("ffmpeg")

DURATION_S = 22.0
WIDTH, HEIGHT, FPS = 1280, 720, 30

#: A gentle roll doublet so calm and steady-wind clips show the aircraft being
#: flown; hands off in gusty/turbulent cells, where the air does the flying.
SHOWCASE_DOUBLET = (
    {"t_s": 4.0, "aileron": 0.12},
    {"t_s": 9.0, "aileron": 0.0},
    {"t_s": 13.0, "aileron": -0.12},
    {"t_s": 18.0, "aileron": 0.0},
)

#: Wind conditions. Directions are chosen per terrain (crosswind = heading
#: +90, headwind = heading) so the words stay true whatever the flight path.
CONDITIONS = ("calm", "crosswind25", "gusty15", "turb_moderate")

#: Fog density per visibility word. Gate 6's 0.0025 suits its 300 m-altitude
#: scene; from showcase altitudes the slant paths are kilometres longer and
#: the same density reads as a blue veil over everything (measured on the
#: Yosemite noon cell), so "clear" is thinner here. Recorded per clip.

#: The complex cells: combined conditions, every constituent delivered by the
#: machinery already null-tested alone (steady wind + schedule + Dryden +
#: orographic coexist in one card). Rendered over a reduced visibility/time
#: sub-grid to keep the matrix's wall clock finite -- the reduction is a
#: stated plan, not a silent skip.
COMPLEX_CONDITIONS = ("turb_severe", "crosswind25_turb", "storm25",
                      "microburst")
COMPLEX_SUBGRID = (("clear", "dawn"), ("hazy", "noon"))

#: Microburst encounter parameters per airframe: the field is scaled so the
#: slower aircraft is not parked inside the core for the whole clip. AGL is
#: the classic low-level-encounter regime (Delta 191 was at ~250 m).
MICROBURST = {
    "agl_m": 300.0,
    "ambient_headwind_kt": 10.0,
    "encounter_t_s": 11.0,
    "B747": {"core_radius_m": 1000.0, "outflow_max_mps": 12.0,
             "outflow_height_m": 150.0},
    "c172p": {"core_radius_m": 600.0, "outflow_max_mps": 8.0,
              "outflow_height_m": 120.0},
}
VISIBILITY = {"clear": 0.0012, "hazy": 0.010}
#: Time of day as sun geometry plus an exposure bias for the §6.6 manual
#: exposure. Approximations, recorded as such in every manifest.
TIME_OF_DAY = {
    "dawn": {"sun_elev": 8.0, "sun_azim": 95.0, "exposure_bias": 10.5},
    "noon": {"sun_elev": 50.0, "sun_azim": 180.0, "exposure_bias": 9.5},
}

#: Per-airframe framing and altitudes (metres MSL per terrain).
AIRFRAMES = {
    "B747": {
        "prompt": "fly the 747 at {alt} m and 250 kt for 30 seconds",
        "manifest": "assets/generated/B747/mesh_manifest.json",
        "chase": "-170:0:16",
        # Control ridge tops out at 3299 m (measured from the bake); both
        # aircraft fly above every peak of every terrain they carry.
        "altitude": {"matterhorn": 5200.0, "yosemite": 3500.0, "control": 3900.0},
    },
    "c172p": {
        "prompt": "fly the c172 at {alt} m and 100 kt for 30 seconds",
        "manifest": "assets/generated/c172p/mesh_manifest.json",
        "chase": "-40:0:5",
        "altitude": {"matterhorn": 3600.0, "yosemite": 2600.0, "control": 3500.0},
    },
}

#: Turbulence seeds: one per cell, recorded in card, manifest and report.
TURBULENCE_SEED_BASE = 62000


def ensure_terrains(out_dir: Path) -> Dict[str, Dict]:
    """Bake (or reuse) the two real terrains and the synthesised control.

    Real bakes go through core.terrain.glo30.bake -- fetch, mosaic, ingest,
    verify -- and refuse to exist unverified. The control ridge goes through
    the same synthesis path Gate 6 uses, at a comparable relief, with its own
    (synthetic, clearly-labeled) georeference.
    """
    from pyproj import Transformer

    terrain_dir = Path("runs/terrain").resolve()
    terrains: Dict[str, Dict] = {}
    for key in ("matterhorn", "yosemite"):
        location = LOCATIONS[key]
        raw = terrain_dir / f"{key}.r16"
        if not raw.is_file():
            print(f"  baking {key} from GLO-30 (fetch + ingest + verify)")
            bake(location, "data/glo30", terrain_dir)
        baked = Heightfield.read(terrain_dir / key)
        transformer = Transformer.from_crs("EPSG:4326", baked.georeference.crs,
                                           always_xy=True)
        ox, oy = transformer.transform(location.origin_lon, location.origin_lat)
        heading = {"matterhorn": 236.0, "yosemite": 73.0}[key]
        terrains[key] = {
            "path": terrain_dir / key,
            "kind": "real (Copernicus GLO-30)",
            "lat": location.origin_lat, "lon": location.origin_lon,
            "heading": heading,
            "ground_m": round(baked.elevation_at(ox, oy), 1),
            "tiles": baked.provenance.get("tiles", {}),
            "sha256": baked.digest(),
            "title": location.title,
        }

    control_raw = terrain_dir / "control_ridge.r16"
    if not control_raw.is_file():
        print("  synthesising the control ridge (same pipeline as Gate 6)")
        field = generate(size=1024, pixel_size_m=30.0,
                         statistics=TerrainStatistics(rms_slope_deg=28.0),
                         seed=6, base_elevation_m=600.0, name="control_ridge")
        field.write(terrain_dir / "control_ridge")
    control = Heightfield.read(terrain_dir / "control_ridge")
    from pyproj import Transformer as T2
    inverse = T2.from_crs(control.georeference.crs, "EPSG:4326", always_xy=True)
    min_x, min_y, max_x, max_y = control.bounds_m()
    cx, cy = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0
    lon, lat = inverse.transform(cx, cy)
    terrains["control"] = {
        "path": terrain_dir / "control_ridge",
        "kind": "synthesised control (no real place)",
        "lat": round(float(lat), 6), "lon": round(float(lon), 6),
        "heading": 45.0,
        "ground_m": round(control.elevation_at(cx, cy), 1),
        "tiles": {},
        "sha256": control.digest(),
        "title": "synthesised control ridge (seed 6, 28 deg RMS slope)",
    }
    return terrains


def gust_schedule(from_deg: float, steady_kt: float, rate_hz: float,
                  duration_s: float, airspeed_mps: float,
                  surge_kt: Sequence[float] = (12.0, 8.0, 10.0),
                  down_peak_mps: float = 3.0) -> List[Dict[str, float]]:
    """Per-step NED wind for a gusty cell, from the real providers.

    The horizontal speed is the steady wind (blowing FROM ``from_deg``)
    modulated by 1-cosine gusts (DiscreteGust.magnitude_at -- the provider's
    own shape function), plus a vertical gust mid-run. The card carries the
    resulting floats; the UE host writes them verbatim, so the gust model
    exists exactly once. ``surge_kt`` scales the three surges so a storm cell
    can gust harder than a 15 kt afternoon.
    """
    steady = SteadyWind(u.kt_to_mps(steady_kt), from_deg)
    surges = [
        DiscreteGust(peak_mps=u.kt_to_mps(surge_kt[0]), start_s=3.0,
                     gradient_m=120.0, airspeed_mps=airspeed_mps, axis="north"),
        DiscreteGust(peak_mps=u.kt_to_mps(surge_kt[1]), start_s=9.0,
                     gradient_m=350.0, airspeed_mps=airspeed_mps, axis="north"),
        DiscreteGust(peak_mps=u.kt_to_mps(surge_kt[2]), start_s=16.0,
                     gradient_m=120.0, airspeed_mps=airspeed_mps, axis="north"),
    ]
    down_gust = DiscreteGust(peak_mps=down_peak_mps, start_s=12.0,
                             gradient_m=120.0, airspeed_mps=airspeed_mps,
                             axis="down")
    steps = int(round(duration_s * rate_hz))
    schedule = []
    for step in range(steps):
        t = step * (1.0 / rate_hz)
        # The surge magnitudes add to the steady speed ALONG the same
        # from-bearing; the vertical gust rides on top.
        surge = sum(g.magnitude_at(t) for g in surges)
        speed = steady.speed_mps + surge
        radians = math.radians(from_deg)
        schedule.append({
            "t_s": round(t, 6),
            "north_fps": u.mps_to_fps(-speed * math.cos(radians)),
            "east_fps": u.mps_to_fps(-speed * math.sin(radians)),
            "down_fps": u.mps_to_fps(down_gust.magnitude_at(t)),
        })
    return schedule


class CellUnrenderable(Exception):
    """This cell cannot be staged honestly; skip it loudly."""


def microburst_track(terrain: Dict, altitude_m: float,
                     airspeed_mps: float) -> float:
    """A heading whose nominal 300 m AGL track clears the visual terrain.

    The physics ground is the flat slab either way; this check is about the
    PICTURE -- a low-level run that visually tunnels through a mountainside
    would be nonsense on screen. Candidate headings are scanned and the one
    with the most clearance above the baked raster along the whole track
    wins; if none clears, the cell is refused rather than rendered wrong.
    """
    baked = Heightfield.read(terrain["path"])
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", baked.georeference.crs,
                                       always_xy=True)
    origin_x, origin_y = transformer.transform(terrain["lon"], terrain["lat"])
    track_length = airspeed_mps * (DURATION_S + 4.0) + 2000.0

    best_heading, best_clearance = None, -1e9
    candidates = [terrain["heading"]] + list(range(0, 360, 30))
    for heading in candidates:
        radians = math.radians(heading)
        clearance = 1e9
        for step in range(0, int(track_length), 300):
            x = origin_x + step * math.sin(radians)
            y = origin_y + step * math.cos(radians)
            clearance = min(clearance, altitude_m - baked.elevation_at(x, y))
        if clearance > best_clearance:
            best_heading, best_clearance = float(heading), clearance
    if best_clearance < 60.0:
        raise CellUnrenderable(
            f"no heading gives a {MICROBURST['agl_m']:.0f} m AGL track over "
            f"{terrain['title']} with 60 m of visual terrain clearance "
            f"(best {best_clearance:.0f} m); refusing to render an aircraft "
            f"tunnelling through a mountainside")
    return best_heading


def microburst_schedule(heading_deg: float, airspeed_mps: float,
                        rate_hz: float, airframe_key: str) -> List[Dict[str, float]]:
    """Ambient headwind + the downburst field along the nominal track.

    Like the discrete gusts, the field is evaluated as a function of time on
    the NOMINAL track (constant speed and heading from the origin). The
    field itself is spatial and divergence-free (core/environment/downburst);
    the along-track evaluation is the same approximation MIL-style discrete
    gusts use, and it is labeled on the clip.
    """
    from core.environment.downburst import Downburst

    parameters = MICROBURST[airframe_key]
    radians = math.radians(heading_deg)
    distance = airspeed_mps * MICROBURST["encounter_t_s"]
    burst = Downburst(
        centre_north_m=distance * math.cos(radians),
        centre_east_m=distance * math.sin(radians),
        **parameters)
    ambient = SteadyWind(u.kt_to_mps(MICROBURST["ambient_headwind_kt"]),
                         heading_deg)

    steps = int(round(DURATION_S * rate_hz))
    schedule = []
    for step in range(steps):
        t = step * (1.0 / rate_hz)
        north = airspeed_mps * t * math.cos(radians)
        east = airspeed_mps * t * math.sin(radians)
        wind = burst.wind_components(north, east, MICROBURST["agl_m"])
        base = ambient.wind_at(None, t)
        schedule.append({
            "t_s": round(t, 6),
            "north_fps": u.mps_to_fps(base.north + wind.north),
            "east_fps": u.mps_to_fps(base.east + wind.east),
            "down_fps": u.mps_to_fps(wind.down),
        })
    return schedule


def build_cell_card(out: Path, airframe_key: str, terrain_key: str,
                    terrain: Dict, condition: str, seed: int) -> Dict:
    """One cell's spec + run card, with every honesty label computed here."""
    airframe = AIRFRAMES[airframe_key]
    altitude = airframe["altitude"][terrain_key]
    flight_heading = terrain["heading"]
    airspeed_for_track = u.kt_to_mps(250.0 if airframe_key == "B747" else 100.0)
    if condition == "microburst":
        # The low-level encounter: altitude and heading are the condition's.
        altitude = terrain["ground_m"] + MICROBURST["agl_m"]
        flight_heading = microburst_track(terrain, altitude, airspeed_for_track)
    spec = reference_spec(airframe["prompt"].format(alt=int(altitude)))
    spec.set("latitude", terrain["lat"], frm=f"{terrain_key} scene origin")
    spec.set("longitude", terrain["lon"], frm=f"{terrain_key} scene origin")
    spec.set("heading", flight_heading, frm=f"{terrain_key} flight path")
    spec.set("terrain_elevation", terrain["ground_m"],
             frm="baked raster at origin (flat physics slab at this height)")

    heading = flight_heading
    airspeed_mps = u.kt_to_mps(float(spec.airspeed.value))
    control_inputs: Sequence[Dict[str, float]] = SHOWCASE_DOUBLET
    wind_schedule = None
    downburst = None
    orographic = None
    wind_note = "calm"

    def set_steady_wind(speed_kt: float, direction: float, why: str):
        spec.set("wind_speed", speed_kt, frm="condition matrix")
        spec.set("wind_direction", round(direction), frm=why)
        return orographic_card_block(terrain["path"], terrain["lat"],
                                     terrain["lon"], speed_kt, round(direction))

    def set_turbulence(intensity: str):
        spec.set("turbulence", intensity, frm="condition matrix")
        spec.set("seed", seed, frm="condition matrix")
        return (f"{intensity} Dryden turbulence, seed {seed} (visual-only: "
                f"measured same-seed realisations differ between hosts)")

    if condition == "crosswind25":
        direction = (heading + 90.0) % 360.0
        orographic = set_steady_wind(25.0, direction, "crosswind = heading + 90")
        wind_note = f"25 kt crosswind from {round(direction)}"
    elif condition == "gusty15":
        orographic = set_steady_wind(15.0, heading, "headwind = heading")
        wind_schedule = gust_schedule(round(heading), 15.0,
                                      float(spec.rate.value), DURATION_S,
                                      airspeed_mps)
        control_inputs = ()
        wind_note = f"15 kt gusty headwind from {round(heading)} (1-cosine gusts)"
    elif condition == "turb_moderate":
        wind_note = set_turbulence("moderate")
        control_inputs = ()
    elif condition == "turb_severe":
        wind_note = set_turbulence("severe")
        control_inputs = ()
    elif condition == "crosswind25_turb":
        direction = (heading + 90.0) % 360.0
        orographic = set_steady_wind(25.0, direction, "crosswind = heading + 90")
        turbulence_note = set_turbulence("moderate")
        control_inputs = ()
        wind_note = (f"25 kt crosswind from {round(direction)} + "
                     f"{turbulence_note}")
    elif condition == "storm25":
        # The kitchen sink, every constituent individually null-tested: a
        # 25 kt gusting crosswind (surges to ~+18 kt, 5 m/s vertical gust),
        # severe Dryden turbulence, and the ridge coupling.
        direction = (heading + 90.0) % 360.0
        orographic = set_steady_wind(25.0, direction, "storm crosswind")
        wind_schedule = gust_schedule(round(direction), 25.0,
                                      float(spec.rate.value), DURATION_S,
                                      airspeed_mps,
                                      surge_kt=(18.0, 12.0, 15.0),
                                      down_peak_mps=5.0)
        turbulence_note = set_turbulence("severe")
        control_inputs = ()
        wind_note = (f"storm: 25 kt gusting crosswind from {round(direction)} "
                     f"(surges to ~43 kt, 5 m/s vertical gust) + {turbulence_note}")
    elif condition == "microburst":
        # The low-level wind-shear encounter: headwind surge, downdraft core,
        # tailwind switch (core/environment/downburst -- Vicroy shaping,
        # divergence-free by construction). Ambient headwind keeps the
        # orographic coupling alive. Phase 7 2.3: the field is POSITION-
        # COUPLED -- the card carries the downburst block and the UE host's
        # cross-checked port evaluates it at the aircraft's actual position
        # each step, replacing the labeled nominal-track schedule.
        from core.environment.downburst import Downburst

        orographic = set_steady_wind(MICROBURST["ambient_headwind_kt"],
                                     heading, "ambient headwind")
        parameters = MICROBURST[airframe_key]
        radians = math.radians(heading)
        encounter_m = airspeed_for_track * MICROBURST["encounter_t_s"]
        burst = Downburst(
            centre_north_m=encounter_m * math.cos(radians),
            centre_east_m=encounter_m * math.sin(radians),
            **parameters)
        downburst = burst.card_block(orographic["origin_x_m"],
                                     orographic["origin_y_m"])
        control_inputs = ()
        wind_note = (
            f"microburst: {parameters['outflow_max_mps']:g} m/s outflow, core "
            f"R {parameters['core_radius_m']:g} m, crossed ~t="
            f"{MICROBURST['encounter_t_s']:g} s at {MICROBURST['agl_m']:g} m "
            f"AGL, + {MICROBURST['ambient_headwind_kt']:g} kt ambient "
            f"(position-coupled; port selftest in the manifest)")

    card_path = write_run_card(spec, out, control_inputs=control_inputs,
                               duration_s=DURATION_S,
                               wind_schedule=wind_schedule,
                               orographic=orographic,
                               downburst=downburst)
    return {
        "spec_digest": spec.digest(),
        "card": str(card_path),
        "wind_note": wind_note,
        "orographic": orographic is not None,
        "turbulence_seed": seed if condition == "turb_moderate" else None,
    }


def render_cell(card: Path, frames: Path, terrain_path: Path, mesh: Path,
                chase: str, fog: float, tod: Dict) -> bool:
    project = Path(__file__).resolve().parents[1] / "ue" / "FlightSim.uproject"
    frames.mkdir(parents=True, exist_ok=True)
    (frames / "render.json").unlink(missing_ok=True)
    command = [
        str(EDITOR), str(project), "-run=FlightSimBridge.FlightSimRender",
        f"-scenario={card}", f"-frames={frames}",
        "-Visual", "-GeorefTerrain", "-shot=showcase",
        f"-terrain={terrain_path}", f"-mesh={mesh}", f"-chase={chase}",
        f"-fps={FPS}", f"-width={WIDTH}", f"-height={HEIGHT}",
        f"-sun-elev={tod['sun_elev']}", f"-sun-azim={tod['sun_azim']}",
        f"-exposure-bias={tod['exposure_bias']}", f"-fog-density={fog}",
        "-unattended", "-nopause", "-nosplash",
        "-stdout", "-FullStdOutLogOutput",
        "-RenderOffScreen", "-AllowCommandletRendering",
    ]
    log = frames.parent / f"{frames.name}.log"
    with log.open("w") as sink:
        subprocess.run(command, stdout=sink, stderr=subprocess.STDOUT,
                       stdin=subprocess.DEVNULL)
    return (frames / "render.json").is_file()


def encode_clip(frames: Path, clip: Path) -> bool:
    clip.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([
        str(FFMPEG), "-y", "-framerate", str(FPS),
        "-i", str(frames / "frame_%04d.png"),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-pix_fmt", "yuv420p", str(clip),
    ], capture_output=True)
    ok = proc.returncode == 0 and clip.is_file()
    if ok:
        # The mp4 is the deliverable; ~600 MB of PNGs per cell is not. Keep
        # the manifest and the middle frame (the contact sheet's tile).
        frame_files = sorted(frames.glob("frame_*.png"))
        keep = frame_files[len(frame_files) // 2] if frame_files else None
        for frame_file in frame_files:
            if frame_file != keep:
                frame_file.unlink()
    return ok


def contact_sheet(rows: List[Dict], out_path: Path, columns: int = 8) -> Path:
    """One labeled frame per clip, tiled. Labels carry the honesty flags."""
    from PIL import Image, ImageDraw

    tile_w, tile_h, label_h = 320, 180, 34
    count = len(rows)
    if count == 0:
        # A zero-row sheet is a zero-height image PIL cannot even save;
        # deliver an explicit empty marker instead of a crash after the
        # skips were already reported.
        empty = Image.new("RGB", (columns * tile_w, tile_h), (12, 12, 16))
        ImageDraw.Draw(empty).text((16, tile_h // 2),
                                   "no clips were delivered", fill=(255, 80, 80))
        empty.save(out_path)
        return out_path
    grid_rows = (count + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_w, grid_rows * (tile_h + label_h)),
                      (12, 12, 16))
    draw = ImageDraw.Draw(sheet)
    for index, row in enumerate(rows):
        frames = sorted(Path(row["frames_dir"]).glob("frame_*.png"))
        cell_x = (index % columns) * tile_w
        cell_y = (index // columns) * (tile_h + label_h)
        if frames:
            image = Image.open(frames[len(frames) // 2]).resize(
                (tile_w, tile_h), Image.LANCZOS)
            sheet.paste(image, (cell_x, cell_y))
        else:
            draw.text((cell_x + 8, cell_y + tile_h // 2), "SKIPPED",
                      fill=(255, 80, 80))
        label = row["clip_id"]
        flags = []
        if row.get("turbulence_seed") is not None:
            flags.append(f"seed {row['turbulence_seed']}")
        if row.get("orographic"):
            flags.append("oro-wind")
        draw.text((cell_x + 4, cell_y + tile_h + 3), label, fill=(230, 230, 230))
        draw.text((cell_x + 4, cell_y + tile_h + 17),
                  " ".join(flags) if flags else "", fill=(150, 200, 150))
    sheet.save(out_path)
    return out_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 6B condition matrix")
    ap.add_argument("--out", default="runs/showcase")
    ap.add_argument("--airframes", default="B747,c172p")
    ap.add_argument("--terrains", default="matterhorn,yosemite,control")
    ap.add_argument("--conditions", default=",".join(CONDITIONS))
    ap.add_argument("--visibility", default="clear,hazy")
    ap.add_argument("--time-of-day", default="dawn,noon")
    ap.add_argument("--skip-existing", action="store_true", default=True)
    ap.add_argument("--no-skip-existing", dest="skip_existing",
                    action="store_false")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]

    if not FFMPEG.is_file():
        print(f"no ffmpeg at {FFMPEG}; clips cannot be encoded")
        return 2

    print(f"\n{RULE}\n1. terrains, baked and verified\n{RULE}")
    terrains = ensure_terrains(out)
    for key, terrain in terrains.items():
        print(f"  {key:11s} {terrain['title']}  sha {terrain['sha256'][:12]}")

    airframe_keys = [k for k in args.airframes.split(",") if k]
    terrain_keys = [k for k in args.terrains.split(",") if k]
    # An empty --conditions renders only the complex sub-grid cells; an
    # unknown condition name would silently fall through to calm, so refuse.
    condition_keys = [k for k in args.conditions.split(",") if k]
    known = set(CONDITIONS) | set(COMPLEX_CONDITIONS)
    unknown = [k for k in condition_keys if k not in known]
    if unknown:
        print(f"unknown conditions {unknown}; known: {sorted(known)}")
        return 2
    visibility_keys = [k for k in args.visibility.split(",") if k]
    tod_keys = [k for k in args.time_of_day.split(",") if k]

    cells = []
    for airframe_key in airframe_keys:
        for terrain_key in terrain_keys:
            for condition in condition_keys:
                for visibility in visibility_keys:
                    for tod in tod_keys:
                        cells.append((airframe_key, terrain_key, condition,
                                      visibility, tod))
            # The complex combined conditions, on their stated sub-grid.
            for condition in COMPLEX_CONDITIONS:
                for visibility, tod in COMPLEX_SUBGRID:
                    if visibility in visibility_keys and tod in tod_keys:
                        cells.append((airframe_key, terrain_key, condition,
                                      visibility, tod))
    print(f"\n{RULE}\n2. the matrix: {len(cells)} cells "
          f"({len(COMPLEX_CONDITIONS)} complex conditions on the "
          f"{len(COMPLEX_SUBGRID)}-combo sub-grid)\n{RULE}")

    rows: List[Dict] = []
    skipped: List[Dict] = []
    port_checked = 0
    for index, (airframe_key, terrain_key, condition, visibility, tod) in \
            enumerate(cells):
        clip_id = f"{airframe_key}_{terrain_key}_{condition}_{visibility}_{tod}"
        frames = out / "cells" / clip_id
        clip = out / "clips" / f"{clip_id}.mp4"
        seed = TURBULENCE_SEED_BASE + index
        terrain = terrains[terrain_key]

        if args.skip_existing and clip.is_file() and \
                (frames / "render.json").is_file():
            print(f"  [{index + 1:3d}/{len(cells)}] {clip_id}: kept")
        else:
            try:
                cell = build_cell_card(out / "cards" / f"{clip_id}.json",
                                       airframe_key, terrain_key, terrain,
                                       condition, seed)
            except CellUnrenderable as why:
                print(f"  [{index + 1:3d}/{len(cells)}] {clip_id}: "
                      f"SKIPPED -- {why}")
                skipped.append({"clip_id": clip_id, "reason": str(why)})
                continue
            ok = render_cell(
                Path(cell["card"]), frames, terrain["path"],
                (root / AIRFRAMES[airframe_key]["manifest"]).resolve(),
                AIRFRAMES[airframe_key]["chase"],
                VISIBILITY[visibility], TIME_OF_DAY[tod])
            if not ok:
                reason = f"render did not complete (see {frames}.log)"
                print(f"  [{index + 1:3d}/{len(cells)}] {clip_id}: "
                      f"SKIPPED -- {reason}")
                skipped.append({"clip_id": clip_id, "reason": reason})
                continue
            raw_clip = frames / "raw.mp4"
            if not encode_clip(frames, raw_clip):
                reason = "ffmpeg encode failed"
                print(f"  [{index + 1:3d}/{len(cells)}] {clip_id}: "
                      f"SKIPPED -- {reason}")
                skipped.append({"clip_id": clip_id, "reason": reason})
                continue
            # The deliverable clip carries the telemetry panel: the plan (the
            # card) against the FDM's recorded per-frame state.
            from experiments.showcase_panel import build_panel_clip
            if not build_panel_clip(Path(cell["card"]),
                                    frames / "render.json", cell,
                                    raw_clip, clip, fps=FPS):
                reason = "panel composite failed"
                print(f"  [{index + 1:3d}/{len(cells)}] {clip_id}: "
                      f"SKIPPED -- {reason}")
                skipped.append({"clip_id": clip_id, "reason": reason})
                continue
            print(f"  [{index + 1:3d}/{len(cells)}] {clip_id}: "
                  f"rendered + panel + encoded")

        manifest = json.loads((frames / "render.json").read_text(encoding="utf-8"))
        card = json.loads((out / "cards" / f"{clip_id}.json").read_text(encoding="utf-8")) \
            if (out / "cards" / f"{clip_id}.json").is_file() else {}

        # The render must be of the spec the row claims (§1.4, per clip).
        if card and manifest["spec_digest"] != card["spec_digest"]:
            reason = "manifest spec digest does not match the card"
            skipped.append({"clip_id": clip_id, "reason": reason})
            continue
        # And of the raster the row claims.
        if manifest.get("scene", {}).get("terrain_sha256") != terrain["sha256"]:
            reason = "rendered terrain sha does not match the bake"
            skipped.append({"clip_id": clip_id, "reason": reason})
            continue
        # Spot-verify the orographic port in a sample of coupled cells.
        if card.get("orographic") and port_checked < 4:
            check = verify_port(manifest, card)
            if not check["ok"]:
                skipped.append({"clip_id": clip_id,
                                "reason": f"orographic port drifted: {check}"})
                continue
            port_checked += 1

        rows.append({
            "clip_id": clip_id,
            "clip": str(clip.relative_to(out)),
            "frames_dir": str(frames),
            "airframe": airframe_key,
            "mesh": manifest.get("mesh", {}),
            "terrain": terrain_key,
            "terrain_kind": terrain["kind"],
            "terrain_tiles": terrain["tiles"],
            "terrain_sha256": terrain["sha256"],
            "conditions": {
                "wind": condition, "visibility": visibility,
                "time_of_day": tod,
                "sun": TIME_OF_DAY[tod], "fog_density": VISIBILITY[visibility],
            },
            "spec_digest": manifest["spec_digest"],
            "turbulence_seed": (seed if condition == "turb_moderate" else None),
            "turbulence_parity": ("visual-only (measured; see "
                                  "runs/turbulence_ue/report.json)"
                                  if condition == "turb_moderate" else None),
            "orographic": bool(manifest.get("environment", {}).get("orographic")),
            "scenery_only_terrain": (
                "visual terrain is the named raster at true position; the "
                "physics ground the gear model feels is the spec's flat slab "
                "at the stated elevation"),
            "resolution": f"{WIDTH}x{HEIGHT}@{FPS}",
            "panel": ("1280x300 telemetry strip composited below the frame: "
                      "the card's commanded values against the FDM's recorded "
                      "per-frame state (deltas, surfaces, wind, strip charts). "
                      "Drawn only from recorded evidence; nothing recomputed."),
            "duration_s": DURATION_S,
        })

    print(f"\n{RULE}\n3. deliverables\n{RULE}")
    sheet = contact_sheet(rows, out / "contact_sheet.png")
    manifest_path = out / "showcase_manifest.json"
    manifest_path.write_text(json.dumps({
        "clips": rows,
        "skipped": skipped,
        "cells_planned": len(cells),
        "cells_delivered": len(rows),
        "attribution": ("terrain: Copernicus GLO-30, produced using "
                        "Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 and "
                        "(c) Airbus Defence and Space GmbH 2014-2018; "
                        "aircraft models: GPL-2.0 (FlightGear community), "
                        "see per-clip mesh blocks"),
    }, indent=1), encoding="utf-8")
    print(f"  {len(rows)} clips in {out / 'clips'}")
    print(f"  contact sheet {sheet}")
    print(f"  manifest {manifest_path}")
    if skipped:
        print(f"\n  SKIPPED {len(skipped)} cells, loudly:")
        for entry in skipped:
            print(f"    {entry['clip_id']}: {entry['reason']}")
    return 0 if rows and not skipped else (1 if skipped else 2)


if __name__ == "__main__":
    raise SystemExit(main())
