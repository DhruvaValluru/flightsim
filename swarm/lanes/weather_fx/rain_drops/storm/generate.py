#!/usr/bin/env python3
"""weather_fx.rain_drops.storm: bake the storm's falling rain into layer textures.

VISUAL-ONLY. Nothing here reaches an equation of motion.

Why. The project's rain (core/scene/rain_field.py) draws up to 262,144 GPU
drops in a 20 x 20 x 16 m box. The Windows test laptop is an Intel integrated
GPU on D3D11 with a 491 MB pool and a history of device loss on the storm
scene, so tier 0 draws NO particles: the Mac bakes the same drops (the same
Marshall & Palmer sample, the same Atlas fall speed, the same Garg & Nayar
coverage, the project's own functions and hash) into three tileable textures
and the laptop samples them in one full-screen pass (RainLayers.ush).

Geometry. Drops move along one axis, a = (v_drop - v_camera) / |..| for the
median-volume drop D0. A drop at perpendicular distance rho from the line
through the camera along a keeps its azimuth phi about a and slides in z, so on
a cylinder about a its streak is a straight line of constant phi. A layer is
the shell rho0 <= rho < rho1 projected onto the cylinder rho_k = sqrt(rho0 rho1):

    u = phi / (2 pi / NREP)                texture repeats NREP times round
    v = (cot(theta) rho_k + Z) / H_k       theta from a, Z the drops' travel

A drop at rho is drawn scaled by rho_k / rho (perspective inside the shell).
One u texel is (2 pi / NREP) / NU = 1.02 mrad, about one pixel of a 1280 px
frame; a v texel is twice that (streaks run along v).

Bins. Each texture channel holds the layer at one sweep (|v_rel| x shutter of
the D0 drop), a named operating point. "fall": the camera is at rest, each
drop's streak is its own v_t(D) x shutter. "advected": the camera's speed
dominates, every streak has the D0 length. Between bins the host stretches v by
sweep / bin sweep: streaks are s times longer and 1/s as many, so the MEAN
light is conserved and the count of separate streaks is not (the project's own
wording for `weight`).

NOT claimed: parallax inside a layer (all its drops scroll at one speed, that
of D0); each drop's own slant when the camera moves (under 3 deg at 52 m/s);
drop oscillation; rain inside 0.5 m or beyond 10 m (beyond is the veil, the
shaft's Atlas extinction, owned elsewhere); the region within ~10-20 deg of
the axis, where the layers fade (cot(theta) diverges). No frame was rendered.

    .venv/bin/python swarm/lanes/weather_fx/rain_drops/storm/generate.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

LANE = Path(__file__).resolve().parent
REPO = LANE.parents[4]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.scene import precipitation as rain_model  # noqa: E402
from core.scene import rain_field  # noqa: E402
from core.scene import storm_cell  # noqa: E402

ITEM = "weather_fx.rain_drops.storm"
RATE_MMH = float(storm_cell.STORM_RAIN_RATE_MMH)
#: Scenario 9 (scripts/run_test_scenarios.py): the 747 at 2000 m.
ALTITUDE_M = 2000.0
SEED = 9

NU, NV = 512, 1024
NREP = 12
#: (rho0, rho1) metres from the axis through the camera.
LAYERS: Tuple[Tuple[float, float], ...] = ((0.5, 1.5), (1.5, 4.0), (4.0, 10.0))
#: The most drops one tile draws; above it each stands for `weight` drops.
DRAW_CAP = 60000

PHYSICAL_SHUTTER_S = 1.0 / 1000.0   # docs/WEATHER.md: the stated default
CINEMATIC_SHUTTER_S = 1.0 / 15.0    # docs/WEATHER.md: -rain-style=cinematic
CHASE_SPEED_MPS = 52.0              # docs/WEATHER.md's 100 kt chase example
#: The web app's default (webapp/runs.py weather_backend_flags): a stated exaggeration.
RAIN_GAIN = 4.0

#: Pole fade on sin(theta): the layers vanish toward the axis.
POLE_FADE = (0.15, 0.35)

# Per-particle bytes for the heavier tiers: an ESTIMATE (two GPU sim buffers of
# ~64 B of attributes each), not a measurement.
PARTICLE_BYTES_EST = 128.0
MIP_FACTOR = 4.0 / 3.0


def physics() -> Dict[str, Any]:
    numbers = rain_model.rain(RATE_MMH)
    lam = round(numbers["lambda_fitted_per_mm"], 9)
    factor = round(rain_field.fall_speed_factor(ALTITUDE_M), 9)
    d0 = float(numbers["d0_mm"])
    v0 = rain_model.terminal_velocity_mps(d0) * factor
    return {"rate_mmh": RATE_MMH, "lambda_per_mm": lam, "d0_mm": d0, "fall_speed_factor": factor,
            "v_t_d0_mps": v0, "altitude_m": ALTITUDE_M,
            "density_drawn_per_m3": rain_field.truncated_number_density(lam),
            "extinction_per_m": float(numbers["extinction_per_m"])}


def bins(v0: float) -> List[Dict[str, Any]]:
    """The four channels: the D0 drop's sweep (m) and the length regime."""
    rest_c = v0 * CINEMATIC_SHUTTER_S
    return [
        {"channel": "R", "name": "rest_physical", "regime": "fall", "sweep_m": v0 * PHYSICAL_SHUTTER_S},
        {"channel": "G", "name": "chase_physical", "regime": "advected",
         "sweep_m": math.hypot(CHASE_SPEED_MPS, v0) * PHYSICAL_SHUTTER_S},
        {"channel": "B", "name": "rest_cinematic", "regime": "fall", "sweep_m": rest_c},
        {"channel": "A", "name": "long_cinematic", "regime": "advected", "sweep_m": 4.0 * rest_c},
    ]


def layer_geometry(k: int) -> Dict[str, float]:
    rho0, rho1 = LAYERS[k]
    rho_k = math.sqrt(rho0 * rho1)
    dphi = 2.0 * math.pi / NREP
    width = dphi * rho_k                    # the tile's arc at rho_k (m)
    height = 2.0 * width * NV / NU          # v texels are twice u texels
    volume = 0.5 * dphi * (rho1 ** 2 - rho0 ** 2) * height
    return {"rho0_m": rho0, "rho1_m": rho1, "rho_k_m": rho_k, "tile_width_m": width,
            "tile_height_m": height, "shell_volume_m3": volume}


def v_t_np(d_mm: np.ndarray, factor: float) -> np.ndarray:
    """Atlas, Srivastava & Sekhon, as rain_model.terminal_velocity_mps (D >= 1 mm)."""
    return (rain_model.ATLAS_A - rain_model.ATLAS_B * np.exp(-rain_model.ATLAS_C * d_mm)) * factor


def width_np(d_mm: np.ndarray) -> np.ndarray:
    """Beard & Chuang's presented width, as rain_field.presented_width_mm."""
    d = d_mm / 10.0
    ratio = 1.0048 + 0.0057 * d - 2.628 * d ** 2 + 3.682 * d ** 3 - 1.677 * d ** 4
    return d_mm * ratio ** (-1.0 / 3.0)


def layer_drops(k: int, phys: Dict[str, Any], seed: int = SEED) -> Dict[str, Any]:
    """The layer's drops from the project's hash (rain_field.unit; channel 3 is
    the diameter, as in rain_field.drop)."""
    geo = layer_geometry(k)
    expected = phys["density_drawn_per_m3"] * geo["shell_volume_m3"]
    count = int(min(DRAW_CAP, max(1, round(expected))))
    layer_seed = rain_field.splitmix64((int(seed) << 8) + k) & rain_field.SEED_MASK
    lam = phys["lambda_per_mm"]
    u = np.array([[rain_field.unit(layer_seed, i, c) for c in range(3)] for i in range(count)])
    d = np.array([rain_field.sample_diameter_mm(rain_field.unit(layer_seed, i, 3), lam)
                  for i in range(count)])
    rho = np.sqrt(geo["rho0_m"] ** 2 + u[:, 2] * (geo["rho1_m"] ** 2 - geo["rho0_m"] ** 2))
    return {"count": count, "expected": expected, "weight": max(1.0, expected / count),
            "u_tx": u[:, 0] * NU, "v_tx": u[:, 1] * NV, "rho_m": rho, "d_mm": d, "seed": layer_seed}


def streaks(k: int, drops: Dict[str, Any], sweep_m: float, regime: str,
            phys: Dict[str, Any]) -> Dict[str, np.ndarray]:
    """Each drop's footprint in texels and its alpha (Garg & Nayar: D / (|v| t))."""
    geo = layer_geometry(k)
    d = drops["d_mm"]
    persp = geo["rho_k_m"] / drops["rho_m"]
    if regime == "fall":
        length_m = sweep_m * v_t_np(d, phys["fall_speed_factor"]) / phys["v_t_d0_mps"]
    else:
        length_m = np.full_like(d, sweep_m)
    w = width_np(d) / 1000.0 * persp / (geo["tile_width_m"] / NU)
    ln = length_m * persp / (geo["tile_height_m"] / NV)
    alpha = np.minimum(1.0, d / 1000.0 / length_m) * drops["weight"]
    # Sub-texel streaks are drawn one texel wide / long at the same total light.
    w_eff, ln_eff = np.maximum(w, 1.0), np.maximum(ln, 1.0)
    return {"w": w_eff, "ln": ln_eff, "alpha": alpha * (w / w_eff) * (ln / ln_eff),
            "length_m": length_m}


def splat(u0: np.ndarray, v0: np.ndarray, w: np.ndarray, ln: np.ndarray,
          alpha: np.ndarray) -> np.ndarray:
    """Exact box coverage of each streak, periodic in u and v. Sum of the
    result is sum(alpha w ln): the splat conserves light."""
    left, right = u0 - 0.5 * w, u0 + 0.5 * w
    base = np.floor(left).astype(np.int64)
    full = np.floor(ln / NV)
    end = v0 + (ln - full * NV)
    wrapped = end >= NV
    end = np.where(wrapped, end - NV, end)
    deriv = np.zeros((NV + 1, NU))
    const = np.zeros(NU)
    for step in range(int(math.ceil(float(w.max()))) + 1):
        col = base + step
        cov = np.clip(np.minimum(right, col + 1.0) - np.maximum(left, col), 0.0, 1.0) * alpha
        c = col % NU
        np.add.at(const, c, cov * (full + wrapped))
        for pos, sign in ((v0, 1.0), (end, -1.0)):
            i = np.floor(pos).astype(np.int64)
            f = pos - i
            np.add.at(deriv, (i, c), sign * cov * (1.0 - f))
            np.add.at(deriv, (i + 1, c), sign * cov * f)
    return np.cumsum(deriv[:NV], axis=0) + const[None, :]


def bake_layer(k: int, phys: Dict[str, Any], seed: int = SEED) -> Tuple[np.ndarray, Dict[str, Any]]:
    """(NV, NU, 4) uint8 and the layer's record."""
    drops = layer_drops(k, phys, seed)
    out = np.zeros((NV, NU, 4), dtype=np.uint8)
    record: Dict[str, Any] = {"layer": k, **{key: round(val, 6) for key, val in layer_geometry(k).items()},
                              "drops_expected": round(drops["expected"], 3), "drops_drawn": drops["count"],
                              "weight": round(drops["weight"], 6), "seed": drops["seed"], "bins": []}
    for b, spec in enumerate(bins(phys["v_t_d0_mps"])):
        s = streaks(k, drops, spec["sweep_m"], spec["regime"], phys)
        img = splat(drops["u_tx"], drops["v_tx"], s["w"], s["ln"], s["alpha"])
        analytic = float(np.sum(s["alpha"] * s["w"] * s["ln"])) / (NU * NV)
        clipped = np.minimum(img, 1.0)
        scale = float(min(1.0, max(1e-6, np.percentile(clipped, 99.9))))
        q = np.rint(np.clip(clipped / scale, 0.0, 1.0) * 255.0).astype(np.uint8)
        out[:, :, b] = q
        record["bins"].append({
            "name": spec["name"], "alpha_scale": round(scale, 9),
            "mean_alpha_analytic": round(analytic, 9),
            "mean_alpha_splat": round(float(img.mean()), 9),
            "mean_alpha_stored": round(float(q.mean()) / 255.0 * scale, 9),
            "mean_streak_length_m": round(float(s["length_m"].mean()), 9),
        })
    record["pixels_sha256"] = hashlib.sha256(out.tobytes()).hexdigest()
    return out, record


def tga_bytes(rgba: np.ndarray) -> bytes:
    """Uncompressed 32-bit TGA, top-left origin. TGA, not PNG: the four channels
    are independent data and must not be touched where alpha is zero."""
    h, w, _ = rgba.shape
    header = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, w, h, 32, 0x28)
    return header + rgba[:, :, [2, 1, 0, 3]].tobytes()


def tiers(phys: Dict[str, Any]) -> List[Dict[str, Any]]:
    n = phys["density_drawn_per_m3"]
    tex_mb = NU * NV * 4 * MIP_FACTOR / 2 ** 20

    def particles(half: Tuple[float, float, float], budget: int) -> Dict[str, Any]:
        expected = n * 8.0 * half[0] * half[1] * half[2]
        drawn = int(min(budget, round(expected)))
        return {"box_half_m": list(half), "particles": drawn, "expected_in_box": round(expected, 1),
                "weight": round(max(1.0, expected / drawn), 4),
                "est_mb": round(drawn * PARTICLE_BYTES_EST / 2 ** 20, 2)}

    t1, t2 = particles((1.5, 1.5, 1.5), 8192), particles((4.0, 4.0, 4.0), 65536)
    t3 = particles(tuple(rain_field.BOX_HALF_M), rain_field.PARTICLE_BUDGET)
    return [
        {"tier": 0, "layers": [0, 1, 2], "particles": None, "splash_budget": 512,
         "est_vram_mb": round(3 * tex_mb, 1),
         "summary": "no particles: three baked 512x1024 RGBA8 layers (0.5-10 m), one full-screen pass, "
                    "three SampleLevel taps and one scene-depth read per pixel"},
        {"tier": 1, "layers": [1, 2], "particles": t1, "splash_budget": 1024,
         "est_vram_mb": round(2 * tex_mb + t1["est_mb"], 1),
         "summary": "the project's drops in a 3 m box (8,192) for true near-field parallax; baked layers 1-2 beyond 1.5 m"},
        {"tier": 2, "layers": [2], "particles": t2, "splash_budget": 2048,
         "est_vram_mb": round(tex_mb + t2["est_mb"], 1),
         "summary": "the project's drops in an 8 m box (65,536); baked layer 2 from 4 to 10 m"},
        {"tier": 3, "layers": [], "particles": t3, "splash_budget": rain_field.SPLASH_BUDGET,
         "est_vram_mb": round(t3["est_mb"], 1),
         "summary": "the project's existing path unchanged: 262,144 drops in the 20 x 20 x 16 m box, no baked layers"},
    ]


def shared_params(phys: Dict[str, Any]) -> Dict[str, Any]:
    """What the scenario's other lanes must agree with. The light numbers are
    lighting_exposure.physical_light_units.storm's, read from its bake when present."""
    light = {"exposure_ev": 12.5, "sun_elevation_deg": 28.0, "colour_temperature_k": 6100.0,
             "ground_albedo": 0.085, "horizontal_illuminance_lux": 12548.4}
    plu = REPO / "swarm/lanes/lighting_exposure/physical_light_units/storm/baked/storm_plu.json"
    if plu.is_file():
        theirs = json.loads(plu.read_text())["shared_params"]
        light = {key: theirs[key] for key in light}
    ext = phys["extinction_per_m"]
    return {
        **light,
        "light_owner": "lighting_exposure.physical_light_units.storm",
        "rain_rate_mmh": phys["rate_mmh"],
        "rain_lambda_per_mm": phys["lambda_per_mm"],
        "rain_d0_mm": round(phys["d0_mm"], 6),
        "rain_fall_speed_d0_mps": round(phys["v_t_d0_mps"], 6),
        "rain_altitude_m": ALTITUDE_M,
        "rain_shutter_physical_s": PHYSICAL_SHUTTER_S,
        "rain_shutter_cinematic_s": round(CINEMATIC_SHUTTER_S, 9),
        "rain_gain": RAIN_GAIN,
        "rain_style": "cinematic",
        # A white diffuse surface under the deck: E / pi (docs/WEATHER.md's drop radiance).
        "rain_drop_luminance_cd_m2": round(light["horizontal_illuminance_lux"] / math.pi, 1),
        "rain_extinction_per_m": round(ext, 9),
        # Koschmieder, 3.912 / sigma, rain alone inside the shaft: the haze lanes'
        # visibility in the shaft cannot exceed this.
        "rain_meteorological_range_m": round(3.912 / ext, 1),
        "rain_layer_far_m": LAYERS[-1][1],
        "wet_ground": True,
    }


def build(write: bool = False, out_dir: Path = LANE / "baked") -> Dict[str, Any]:
    phys = physics()
    layers, files = [], []
    for k in range(len(LAYERS)):
        rgba, record = bake_layer(k, phys)
        name = f"rain_layer{k}_{NU}x{NV}.tga"
        record["file"] = name
        layers.append(record)
        if write:
            out_dir.mkdir(parents=True, exist_ok=True)
            data = tga_bytes(rgba)
            (out_dir / name).write_bytes(data)
            files.append({"path": f"baked/{name}", "sha256": hashlib.sha256(data).hexdigest()})
    lengths = [b["mean_streak_length_m"] for b in layers[0]["bins"]]
    sweeps = bins(phys["v_t_d0_mps"])
    plan = {
        "item": ITEM, "scenario": "storm", "visual_only": True,
        "status": "UNMEASURED: baked on the Mac; no frame rendered",
        "physics": {key: (round(val, 9) if isinstance(val, float) else val) for key, val in phys.items()},
        "texture": {"nu": NU, "nv": NV, "nrep": NREP, "format": "RGBA8 linear (sRGB off), channels = bins",
                    "u_texel_mrad": round(2000.0 * math.pi / NREP / NU, 6), "pole_fade_sin": list(POLE_FADE)},
        "bins": [{**b, "sweep_m": round(b["sweep_m"], 9)} for b in sweeps],
        "layers": layers,
        # WX.1 on the bake: the drawn streaks' mean length over v_t(D0) x shutter.
        "wx1_mean_length_ratio": {sweeps[i]["name"]: round(lengths[i] / sweeps[i]["sweep_m"], 6)
                                  for i in (0, 2)},
        "tiers": tiers(phys),
        "shared_params": shared_params(phys),
    }
    if write:
        text = json.dumps(plan, indent=1, sort_keys=True) + "\n"
        (out_dir / "rain_layers.json").write_text(text)
        files.append({"path": "baked/rain_layers.json", "sha256": hashlib.sha256(text.encode()).hexdigest()})
        plan["_files"] = files
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=LANE / "baked")
    args = parser.parse_args()
    plan = build(write=True, out_dir=args.out)
    for entry in plan["_files"]:
        print(f"{entry['sha256']}  {entry['path']}")
    print("wx1_mean_length_ratio", plan["wx1_mean_length_ratio"])
    for t in plan["tiers"]:
        print(f"tier {t['tier']}: est {t['est_vram_mb']} MB  {t['summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
