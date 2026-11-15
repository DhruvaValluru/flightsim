# weather_fx.rain_drops.storm: integration

VISUAL-ONLY. Status: **UNMEASURED**. Baked and source-tested on the Mac; the
shader has never been compiled and no frame has been rendered. Nothing here
edits a shared file: the changes below are proposals for the integrator.

## What this lane gives

The storm's falling rain for a GPU that cannot hold 262,144 drops. The Mac
bakes the project's own drops (same hash, same Marshall & Palmer sample, same
Atlas fall speed, same Garg & Nayar coverage, 50 mm/h at 2000 m) into three
tileable 512 x 1024 RGBA8 textures. The laptop draws them in one full-screen
pass. Geometry, bins and what is not claimed: `generate.py`'s docstring.

| File | What |
|---|---|
| `generate.py` | The bake. `.venv/bin/python swarm/lanes/weather_fx/rain_drops/storm/generate.py` (0.7 s) |
| `baked/rain_layer{0,1,2}_512x1024.tga` | The layers: 0.5-1.5 m, 1.5-4 m, 4-10 m from the motion axis. Channels R, G, B, A = four sweeps |
| `baked/rain_layers.json` | Every number the host sets: bin sweeps, `rho_k_m`, `tile_height_m`, `alpha_scale`, tiers, shared parameters |
| `RainLayers.ush` | The tier 0 material function (D3D11 SM5, no loops, no derivatives) |
| `run_gate.py` | The pixel gate, one command (Windows): renders the pairs, picks the frames, judges |
| `measure_frame.py` | The gate's arithmetic (structure tensor of rain on minus rain off) |

## Tiers (VRAM figures are estimates, none is sustained)

| Tier | Est. VRAM | Draws |
|---|---|---|
| 0 | 8.0 MB | No particles. Three baked layers, one post-process pass: 3 `SampleLevel` + 1 scene depth per pixel. Splash budget 512 |
| 1 | 6.3 MB | 8,192 of the project's drops in a 3 m box (weight 2.28) + baked layers 1-2. Splash budget 1,024 |
| 2 | 10.7 MB | 65,536 drops in an 8 m box (weight 5.40) + baked layer 2. Splash budget 2,048 |
| 3 | 32.0 MB | The existing path unchanged: 262,144 drops, 20 x 20 x 16 m box (weight 16.88), no layers |

Particle memory assumes 128 B per drop; the real cost of tiers 1-3 on this GPU
is translucent overdraw, which only the laptop can measure.

## Proposed changes (integrator)

1. **Import** the three TGAs to `/Game/FlightSim/Weather/T_RainLayer{0,1,2}`:
   sRGB off, wrap, mips on, compression `VectorDisplacementmap (RGBA8)`
   (the four channels are independent data; BC7 would cut the estimate to
   about 2 MB and is worth trying after tier 0 holds).
2. **Material** `/Game/FlightSim/Weather/M_RainLayers`: post-process domain,
   Before Tonemapping, one Custom node whose body calls `RainLayers(...)`
   from `RainLayers.ush` (copy it to `ue/Plugins/FlightSimBridge/Shaders/`
   and include it). Inputs are listed at the top of the file.
3. **`FlightSimWeather.cpp`**, where `User.*` is set for `NS_FlightSimRain`:
   when the budget tier is `integrated`, do not spawn the Niagara rain or
   the procedural drop mesh; add `M_RainLayers` as a blendable and set per frame
   - `Axis` = normalize(drop velocity for D0 - camera velocity), the same
     vectors that already feed `User.WindVelCm` and `User.CamVelCm`
     (cinematic style: the same share of the camera's motion it uses today);
   - `AxisRight` = normalize(cross(Axis, world up)), or world east when
     Axis is within 1 deg of vertical;
   - `SweepM` = |that relative velocity| x `User.Shutter`;
   - `TravelM` += |relative velocity| x dt, accumulated from the sim clock
     (deterministic, so WX.2's replay stays byte-identical);
   - `Opacity` = `RainGain x BeautyRainGain x User.Active`;
   - `RainRadiance` = (horizontal illuminance + `User.FlashLux`) / pi,
     pre-exposed; `PixelAngle` as `User.PixelAngle`;
   - the constants from `baked/rain_layers.json`.
4. **`core/render/hardware_budget.py`**: add `rain_tier` to the budget
   (0 for `integrated`; the environment's `FLIGHTSIM_RAIN_TIER`, 0-3, wins
   when set, which is how `run_gate.py` asks for each side), and to `core/scene/rain_field.py card_block` an
   optional `particles` / `box_half_m` override so tiers 1-2 put their
   numbers on the card (`weight` = expected / particles as today).
5. **`world_applied`**: record `weather.rain.drawn_as: "baked_layers"` with
   the tier, so a card never claims particles that were not drawn.

The bake is for the storm's 50 mm/h at 2000 m. Another rate or altitude needs
another bake (the generator's constants `RATE_MMH`, `ALTITUDE_M`).

## For the other storm lanes

`shared_params` in `baked/rain_layers.json`. Two to act on:

- `rain_meteorological_range_m` = 968 m: Koschmieder on the project's own
  Atlas extinction at 50 mm/h. The lighting lane assumed 3000 m visibility
  and named the haze and rain lanes as its owner; inside the shaft the rain
  alone allows no more than 968 m.
- `rain_drop_luminance_cd_m2` = 3994: the lighting lane's 12,548 lux over
  pi. If that lane's illuminance moves, this moves with it.

## Measuring it on the Windows laptop

UNMEASURED: nothing below has run on the laptop. One command, from the repo
root, the engine built; it has no path or frame to fill in:

```
.venv\Scripts\python.exe swarm\lanes\weather_fx\rain_drops\storm\run_gate.py
```

It takes scenario 9's prompt from `scripts/run_test_scenarios.py`, renders it
four times through `scripts/debug_storm_render.py` (the commandlet directly;
the web app is not involved, so the rain gain is a flag of this process and
not a server's environment), and measures the last frame number present in
both legs of each pair:

| Leg | Flags | Frames land in |
|---|---|---|
| reference off | procedural backend, `-rain-gain=0`, `FLIGHTSIM_RAIN_TIER=3` | `runs\swarm_gate\weather_fx_rain_drops_storm\reference\off\procedural\frames\` |
| reference on | the same, `-rain-gain=4`, cinematic | `...\reference\on\procedural\frames\` |
| candidate off | `-rain-gain=0`, `FLIGHTSIM_RAIN_TIER=0` | `...\candidate\off\procedural\frames\` |
| candidate on | `-rain-gain=4`, `FLIGHTSIM_RAIN_TIER=0` | `...\candidate\on\procedural\frames\` |

The result is printed and written to `...\gate.json`. Exit 0 PASS, 1 FAIL,
3 not measurable. Only 0 is a pass.

Metric `orientation_error_deg` <= 10, with coherence >= 0.35 and rain_delta
in [0.004, 0.10], and coherence no more than 0.05 under the reference's. The
thresholds are stated, not measured.

What the gate does not assume, and what it cannot do yet:

- **No expected angle is assumed.** The expected streak angle is the one the
  gate measures on the reference pair (the build's particle rain, same card,
  same frame number), so scenario 9's camera roll and wind are whatever the
  build drew. With no reference pair and no `--expected-deg`, the verdict is
  NO EXPECTED ANGLE, exit 3.
- **The candidate cannot be measured before integration.** `FLIGHTSIM_RAIN_TIER`
  (step 4) and the `drawn_as: "baked_layers"` record (step 5) are proposals;
  the build has neither. Until the candidate's `render.json` records
  `drawn_as = baked_layers`, the gate says NOT INTEGRATED and exits 3 instead
  of judging particle frames as this lane's. Step 4 must therefore read
  `FLIGHTSIM_RAIN_TIER` (0-3) as an override of the budget's `rain_tier`.
  Run today, the command only records the baseline
  (`--only reference` does just that, in two renders).
- **The off frame is read from source, not seen.** The off leg is the same
  backend at gain 0: `FlightSimWeather.cpp` draws the procedural drops and
  splashes at `Weight x RainGain`, and the gate refuses an off leg whose
  `render.json` records a rain gain other than 0. Whether that frame is truly
  rain-free, and whether two runs of one card give the same pose (turbulence,
  lightning), is unverified: the output's `veil_delta` (the slow part of the
  difference, not gated) is where either would show.
- **The reference may not render.** 262,144 drops may lose the device on this
  GPU. `--reference-tier 1` or `2` asks for a lighter particle reference
  (once step 4 exists); failing that, `--expected-deg N` with the operator's
  own angle, said so in the report.

Also unmeasured, each needing the laptop: that `RainLayers.ush` compiles
under D3D11 SM5; frame time and device-loss count of each tier (the stress
ladder); WX.1's streak length on a frame (on the Mac it holds on the bake:
mean length 0.82 of v_t(D0) x shutter); WX.3 splashes at the reduced budgets.

## Tests on the Mac

```
.venv/bin/python -m pytest tests/test_swarm_weather_fx_rain_drops_storm.py -q
```

Thirteen tests, all pass: the drops are the project's sample, light is
conserved by the splat and across bins, the committed bake is reproduced byte
for byte, PROVENANCE hashes hold, the shader's constants match the bake, the
gate's arithmetic separates vertical streaks from sideways ones and from no
rain, and `run_gate.py` picks the common frame, refuses a candidate the build
did not record as baked layers, and never passes without an expected angle
(synthetic input and a stub renderer, not a render).
