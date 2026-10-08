# Weather as weather: rain, the storm cell, lightning, thunder

A thunderstorm used to be physics only: the microburst, gust front and
severe turbulence the aircraft flies (`environment.weather_event`), plus a fog
colour and screen-space rain streaks on the render. This lane gives that storm
a body you can see and hear. The physics places and sizes everything, so the
cloud you fly into is the storm the aircraft is feeling.

| What | Drawn by | Driven by (card `weather`) | Python reference |
|---|---|---|---|
| Rain drops in the air, motion-blurred by the real shutter | `M_RainDrops` on a procedural mesh, or the Niagara system | `weather.rain` | `core/scene/rain_particles.py` |
| Splash crowns on the ground near the camera | `M_RainSplash` | `weather.rain.splash` | same |
| Drops on a cockpit camera's glass | `M_WindshieldRain` (post-process, beauty only) | `weather.rain.windshield` | same |
| The cumulonimbus: tower, overshooting top, anvil, rain shaft | `M_StormCell` on the volumetric cloud | `weather.cell` (centred on the card's `downburst`) | `core/scene/storm_cell.py` |
| Lightning channels, branches, the stepped leader, return strokes | `M_LightningChannel` ribbons + one point light | `weather.lightning` | `core/scene/lightning.py` |
| The lightning lighting the cloud from inside | `M_StormCell` emissive (`storm_glow.hlsl`) | same | `storm_cell.glow_illuminance_lux` |
| Thunder (interactive window) | `USoundWaveProcedural`, synthesised from the bolt's own channel | `weather.thunder` | `core/scene/thunder.py` |
| Rain hiss (interactive window) | `USoundWaveProcedural`, level from the rain rate | `weather.rain` | `thunder.rain_noise` |
| A storm soundtrack for rendered videos | `scripts/storm_soundtrack.py` | the whole block | `thunder.soundtrack` |

The block exists only when the spec states `environment.precipitation_rate_mmh`
or a `thunderstorm` weather event. Any other spec's card is unchanged, byte for
byte. None of it reaches an equation of motion.

## The physics in each piece

* **Drops.** Every drop is a sample of the same Marshall & Palmer distribution
  the streak probe and the fog row use (the same fitted Lambda, the Atlas fall
  speed). Drops fall faster in thin air (Foote & du Toit), and big drops
  flatten (Beard & Chuang). Each drop is fixed in the air. A camera flying
  at 60 m/s sees the drops rush past at 60 m/s, and the streak length is the
  drop's velocity relative to the camera times the shutter. The opacity is
  Garg & Nayar's coverage, D / (|v| t). The drops are drawn in a 20 x 20 x 16 m
  box that follows the camera. When the box holds more drops than the budget
  (262,144), each drawn streak stands for `weight` drops: the mean light is
  conserved, the count of separate streaks is not.
* **Splashes.** The number of splashes per second is the drop flux onto the
  ground, the integral of N(D) v(D) in closed form. The splash slots relight
  at hashed places that stay fixed on the ground as the camera moves.
* **The glass.** Drops hit the glass at n |V| cos(theta). They stick below a
  shedding airspeed and run off above it. Both constants (`V_SHED_MPS`,
  `RUNOFF_GAIN`) are stated, not measured, and the card says so.
* **The cell.** The tower is 2.5 downburst core radii wide and reaches the
  latitude's tropopause, with an overshooting dome. The anvil is 4 tower radii
  wide, displaced downwind of the stated wind. The rain shaft is the downdraft
  core. Extinction comes from physics, not art: sigma = 3 LWC / (2 rho r_e).
  That gives 0.19 /m in the tower and 0.0065 /m in the anvil's ice. The shaft
  uses the Atlas rain extinction for its own rain rate. The towers boil upward
  at the updraft speed and the anvil drifts with the wind.
* **Lightning.** Flashes come as a Poisson process at 6 per minute, a quarter of
  them cloud-to-ground. Each CG flash has a stepped leader (drawn growing
  downward), a geometric number of return strokes with log-normal gaps, and
  sometimes a continuing current. The channel is a tortuous walk in Hill's
  statistics that lands exactly on its strike point, with branches. Each
  frame draws the flash's mean optical power over its own exposure, so a
  shutter that misses a stroke shows no bolt, exactly as a real camera does.
  The light per metre goes into the channel's luminance and the cloud's glow.
  The flash also lights the scene as a point source at the channel's centroid.
* **Thunder.** Every heated segment of the bolt sends an N-wave to the
  listener, arriving at r / c. The waves are shaped by weak-shock lengthening,
  spread with distance, filtered by an absorption low-pass that falls with
  range, and loudest broadside (Few 1969). The thunder of a drawn bolt belongs
  to that bolt: its delay, its length, its claps. Past about 25 km it fades out.

Every literature constant is cited in its module and tagged
`[unverified here]` where the source was not re-read for this work.

## Building it (Windows, once)

1. Compile the plugin. `FlightSimBridge` now depends on `Niagara`, which is
   enabled in `FlightSimBridge.uplugin`.
2. Build the materials:
   `UnrealEditor-Cmd ue/FlightSim.uproject -run=pythonscript -script=scripts/ue_create_materials.py`.
   This creates `M_RainDrops`, `M_RainSplash`, `M_LightningChannel`,
   `M_StormCell` and `M_WindshieldRain`. Their Custom nodes are the committed
   `assets/shaders/weather/*.hlsl`, read from the checkout.
3. Optional, only for `-weather-backend=niagara`: build the Niagara system by
   hand (recipe below).

## Running it

Both hosts read the card's `weather` block. `-weather-backend=` picks the rain:

* `procedural` (the default): every drop's place is a pure function of its
  index, the card's seed and the run time, computed in the material. It is
  deterministic in the step (Gate 10-R) and needs no asset beyond the
  materials.
* `niagara`: the hand-built `NS_FlightSimRain`, fed the same numbers each
  frame. It is GPU-simulated, so a replay is **not** byte-identical, and
  `render.json` says so.
* `off`: nothing is drawn.

The cell, lightning, splashes and glass are the same in all three, except
`off`.

```
# a rendered clip
UnrealEditor-Cmd ue/FlightSim.uproject -run=FlightSimRender -scenario=<card.json> -Visual ... [-weather-backend=procedural]
# the interactive window (thunder and rain heard)
UnrealEditor ue/FlightSim.uproject -game -card=<card.json> -terrain=... [-weather-backend=niagara]
# the soundtrack for a rendered clip (sample 0 at run time 0, ready to mux)
python scripts/storm_soundtrack.py <card.json> storm.wav --listener 5000,0,2
```

When the drops are drawn, the screen-space streaks are not. `world_applied`
records `precipitation` as `drawn: false, superseded_by: weather.rain`, so there
is one rain, not two. Everything the weather draws is beauty-only: its actors
join `BeautyOnlyActors`, so the mask, class and depth passes are byte-identical
with the weather on and off. `render.json` `look_applied.weather` records what
was drawn, with what, and what was not and why.

## The Niagara recipe (`-weather-backend=niagara`)

Create `/Game/FlightSim/Weather/NS_FlightSimRain`: one GPU emitter, local
space off, deterministic on, fixed bounds of 2 x `User.BoxHalfCm`. Its user
parameters, all set by `FlightSimWeather.cpp` (by name, so the names are the
contract):

| Parameter | Type | Set | Meaning |
|---|---|---|---|
| `User.BoxHalfCm` | Vector | once | The rain box's half extent (engine cm) |
| `User.Particles` | Int | once | The drawn drop budget (`weather.rain.particles`) |
| `User.Lambda` | Float | once | The fitted Marshall & Palmer slope (1/mm) |
| `User.DMinMm`, `User.DMaxMm` | Float | once | The drawn size range |
| `User.FallSpeedFactor` | Float | once | Foote & du Toit's factor at the run's altitude |
| `User.Weight` | Float | once | Drops each drawn one stands for (opacity gain) |
| `User.WindVelCm` | Vector | per frame | The wind at the camera (engine cm/s), downburst included |
| `User.CamVelCm` | Vector | per frame | The camera's velocity (engine cm/s) |
| `User.Shutter` | Float | per frame | The exposure (s): streak length = relative speed x shutter |
| `User.Active` | Float | per frame | The share of drops falling here (the shaft's `ambient_fraction` .. 1) |
| `User.GroundZCm` | Float | per frame | The ground under the camera (engine Z) |
| `User.FlashLux` | Float | per frame | Lightning illuminance at the camera (lux) |
| `User.PixelAngle` | Float | per frame | One pixel's angle (rad): the streak width floor |

Modules: spawn `User.Particles` once in a box of `User.BoxHalfCm` about the
system. Sample each particle's diameter from the truncated exponential
`D = DMin - ln(1 - u (1 - e^(-Lambda (DMax - DMin)))) / Lambda` and set
`velocity = User.WindVelCm - (0, 0, 100 x (9.65 - 10.3 e^(-0.6 D)) x User.FallSpeedFactor)`.
Wrap positions into the box each tick. Kill particles below `User.GroundZCm`
into a collision event that spawns a splash emitter. Use a velocity-aligned
sprite renderer whose length is `|velocity - User.CamVelCm| x User.Shutter` and
whose width is the drop's diameter floored at `distance x User.PixelAngle`,
with alpha `D / length x User.Weight` clamped. Hide particles whose index
fraction exceeds `User.Active`.

## Refusals (by name)

| Name | When |
|---|---|
| `weather.backend` | `-weather-backend=` is not `procedural`, `niagara` or `off` |
| `weather.card` | the block lacks a number the host reads |
| `weather.selftest` | the port of the drop sampler, the stroke light curve or the thunder synthesis disagrees with the card's selftest (relative 1e-9) |
| `weather.frame` | no georeferencing to place the weather through |
| `weather.rain_material`, `weather.storm_material`, `weather.lightning_material` | a weather material did not load (run the material script) |
| `weather.windshield` | a cockpit camera in the rain without `M_WindshieldRain` |
| `weather.niagara_asset` | `-weather-backend=niagara` without `NS_FlightSimRain` |

A thunderstorm card without a `downburst` block draws its rain and records the
cell and lightning as not drawn (they have no place). That is not a refusal.

## What is verified where

In this container (`tests/test_weather.py`, `tests/test_ue_weather_source.py`):

* every Python closed form against quadrature or its defining law;
* the HLSL shaders' constants pinned to their Python twins;
* the shaders' PCG hash and noise lattice **compiled** and compared with
  Python;
* the C++ port's closed forms (SplitMix64, the drop sampler, the fall speed,
  the drop shape, the stroke light curve over an exposure, the flash
  intensity, the thunder synthesis) **compiled with g++** from
  `FlightSimWeather.cpp` itself, run, and matched to Python to 1e-9;
* the hooks, the parameter names and the card keys the C++ reads, by source.

On Windows (the first build), the clauses:

| Clause | What it measures |
|---|---|
| WX.1 | A ground camera at rest: drops on and off; the drawn streaks' mean length within 30 % of v_t x t_shutter for the card's D0; the label passes byte-identical |
| WX.2 | A chase camera at the spec's airspeed: streaks along the relative velocity; a replay byte-identical (procedural backend) |
| WX.3 | A ground camera: splash crowns in the near field, none above `max_agl_m` |
| WX.4 | The tower's base within 10 % of `base_m` in a level shot; the shaft's transmittance across its diameter against `storm_cell.transmittance`. This is also where `ExtinctionScale` is set if the engine's volumetric cloud does not read Extinction per metre |
| WX.5 | A frame whose exposure covers a return stroke shows the channel; a frame between strokes does not |
| WX.6 | The interactive window: the first clap of a flash after r_min / c; the host's thunder selftest equal to the card's |

## Not claimed

* Drops are advected by the wind at the camera, not their own. There are no
  collisions, coalescence or breakup.
* Splashes appear only on the ground plane under the camera (the scene datum).
* The windshield run-off law is stated, not measured.
* The cell does not grow or decay over a run. There is no mammatus, wall
  cloud, shelf cloud or hail. The anvil offset is stated, not the wind
  aloft's.
* The stepped leader is a smooth descent. There are no dart leaders,
  M-components, upward flashes or anvil crawlers. Intra-cloud flashes are
  drawn only as the cloud's glow.
* The optical power and thunder loudness are calibrations to the literature's
  order of magnitude (`FIRST_STROKE_PEAK_W_PER_M`, `PRESSURE_REF_PA_M`).
* The listener is fixed for the length of a thunder clip. There is no ground
  reflection, and no refraction beyond the audibility fade.
* The render records no audio. Thunder is heard in the interactive window, and
  `scripts/storm_soundtrack.py` writes it for a video.
* A tornado gets no cell. Its funnel stays the Phase 9.3 marker.
