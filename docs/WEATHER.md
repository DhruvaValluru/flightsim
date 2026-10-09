# Weather as weather: rain, the storm cell, lightning, thunder

A thunderstorm used to be physics only: the microburst, gust front and
severe turbulence the aircraft flies (`environment.weather_event`), plus a fog
colour and screen-space rain streaks on the render. This lane gives that storm
a body you can see and hear. The physics places and sizes everything, so the
cloud you fly into is the storm the aircraft is feeling.

| What | Drawn by | Driven by (card `weather`) | Python reference |
|---|---|---|---|
| Rain drops in the air, motion-blurred by the real shutter | `M_RainDrops` on a procedural mesh, or the Niagara system | `weather.rain` | `core/scene/rain_field.py` |
| Splash crowns on the ground near the camera | `M_RainSplash` | `weather.rain.splash` | same |
| Drops on a cockpit camera's glass | `M_WindshieldRain` (post-process, beauty only) | `weather.rain.windshield` | same |
| The cumulonimbus: tower, overshooting top, anvil, rain shaft | `M_StormCell` on the volumetric cloud | `weather.cell` (centred on the card's `downburst`) | `core/scene/storm_cell.py` |
| Lightning channels, branches, the stepped leader, return strokes | `M_LightningChannel` ribbons + one point light | `weather.lightning` | `core/scene/lightning.py` |
| The lightning lighting the cloud from inside | `M_StormCell` emissive (`storm_glow.hlsl`) | same | `storm_cell.glow_illuminance_lux` |
| Thunder and rain sound | **Off** (the owner's call, 2026-10-08): the code is kept but no host plays it | `weather.thunder` | `core/scene/thunder.py` |
| A storm soundtrack for rendered videos | `scripts/storm_soundtrack.py` | the whole block | `thunder.soundtrack` |

**Opt-in.** This is a second weather path, built in parallel with the
weather look (`core/scene/weather_look.py`, `FlightSimWeatherLook.cpp`: ground
surfaces, puddles, lens drops, storm shafts, lightning flashes, ice) and its
rain particles (`core/scene/rain_particles.py`, `FlightSimRainParticles.cpp`).
Those stay the default. This path draws only when a render asks for it with
`-weather-backend=procedural` or `niagara`. Its drops then replace the rain
particles (the scene's `bSkipRainParticles`), and its glass replaces the lens
drops on a cockpit camera. The weather look's storm shafts and flashes still
draw alongside it; which path to keep, or how to fold them together, is an
open decision.

The card block (`core/scene/storm_weather.py`) exists only when the spec states
`environment.precipitation_rate_mmh` or a `thunderstorm` weather event. Any other spec's card is unchanged, byte for
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

* `off` (the default): nothing here is drawn; the weather look and its rain
  particles render exactly as before.
* `procedural`: every drop's place is a pure function of its
  index, the card's seed and the run time, computed in the material. It is
  deterministic in the step (Gate 10-R) and needs no asset beyond the
  materials.
* `niagara`: the hand-built `NS_FlightSimRain`, fed the same numbers each
  frame. It is GPU-simulated, so a replay is **not** byte-identical, and
  `render.json` says so.
The cell, lightning, splashes and glass are the same for `procedural` and
`niagara`.

```
# a rendered clip
UnrealEditor-Cmd ue/FlightSim.uproject -run=FlightSimRender -scenario=<card.json> -Visual ... -weather-backend=procedural
# the web app: set this before starting it, and every prompt's render asks for the storm
#   (Windows PowerShell: $env:FLIGHTSIM_WEATHER_BACKEND="procedural"; unset or "off" = as before)
FLIGHTSIM_WEATHER_BACKEND=procedural
# the interactive window (no sound)
UnrealEditor ue/FlightSim.uproject -game -card=<card.json> -terrain=... [-weather-backend=niagara]
# the soundtrack for a rendered clip (sample 0 at run time 0, ready to mux)
python scripts/storm_soundtrack.py <card.json> storm.wav --listener 5000,0,2
```

When the drops are drawn, the screen-space streaks are not. `world_applied`
records `precipitation` as `drawn: false, superseded_by: weather.rain`, so there
is one rain, not two. The rain look's lens drops (rings over the whole
frame) are superseded the same way: a cockpit camera gets the windshield,
a camera not behind a windshield gets no glass (`look_applied.weather_look.
lens_drops` says so).

What the rain looks like, and why. A drop's streak covers a point of the
frame for D / (|v| t) of the exposure (Garg & Nayar): from a chase camera
at 100 kt the relative speed is 52 m/s, so at a daylight shutter of
1/1000 s a 2 mm drop is a 5 cm streak at 2 % coverage -- faint, visible
only within a metre or two of the camera at 1080p, as in real footage
from a moving aircraft, where the rain is seen on the glass and as the
veil (the shaft's Atlas extinction), not as drops. The shutter is the
card camera's exposure triple when it states one, else 1/1000 s (stated; 1/250 s showed a 747's rain only before the camera moved;
`look_applied.weather.shutter_s`), never the frame interval. A cockpit
camera (`... cockpit camera ...`) gets the windshield's drops and
rivulets. A clip that must SHOW the rain regardless sets
`FLIGHTSIM_RAIN_GAIN=4` for the web app (`-rain-gain=4` for the
commandlet): the drops' opacity times four, a stated exaggeration recorded
in `look_applied.weather.rain.gain`, never the physics. A cockpit
rivulets, the rain's most visible face from an aircraft. The drops are
lit translucent surfaces (a drop's radiance is the mean of its
surroundings, which is what the sky light and the cloud-shadowed sun
give a white diffuse surface at the drop); the first lit frame drew them
black because an unlit material's sky-light environment-map sample reads
nothing from a real-time-captured sky light.

What the ground is: the scene's bake (the Flint Hills: a Copernicus
GLO-30 heightfield at 30 m, coloured by its imagery sidecar when
`scripts/bake_terrain.py` fetched one, else by the land-cover material),
and, over it, Google's Photorealistic 3D Tiles as the visible ground of
every terrain render (the owner's rule, 2026-10-09: on by default, needs
`GOOGLE_MAPS_API_KEY` or `CESIUM_ION_TOKEN` and the Cesium plugin, refuses
by name without them; `FLIGHTSIM_GOOGLE_TILES=off` is the only way to the
baked ground). The web app's throw-away host flight passes
`-NoGoogleTiles`; the debug script streams the tiles unless
`--no-google-tiles`. Under the storm the ground is tinted by the look's fog and
the atmosphere's aerial perspective, and the dark patches on it are the
deck's cloud shadows.

Rain without a storm gets its sky too: a stated rate of 4 mm/h or more
with no cloud layer on the card adds a nimbostratus deck (cover 0.98,
800 m to 3000 m, stated) the way a thunderstorm adds its own, so the sun
is shadowed and the rain falls in the dim light it falls in (the first
747 over New York rendered 25 mm/h under a bright sky with thin clouds).

Where the cell stands: by default at the 45 %-of-the-run point of the
track, where the physics puts the microburst -- for a 3-second clip that
is 70 m ahead, so the camera starts INSIDE the rain shaft and sees grey
murk, as it would. To see the cumulonimbus from outside, place it:
`... towards a thunderstorm 5 km ahead ...` (core/nl/compiler.py
`event_ahead_m`; the distance rides in the event's detail, and the web
app, the headless runner and the debug script all place the cell there). Everything the weather draws is beauty-only: its actors
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
| `weather.backend` | `-weather-backend=` is not `procedural`, `niagara` or `off` (empty is `off`) |
| `weather.card` | the block lacks a number the host reads |
| `weather.selftest` | the port of the drop sampler, the stroke light curve or the thunder synthesis disagrees with the card's selftest (relative 1e-9) |
| `weather.frame` | no georeferencing to place the weather through |
| `weather.rain_material`, `weather.storm_material`, `weather.lightning_material` | a weather material did not load (run the material script) |
| `weather.windshield` | a cockpit camera in the rain without `M_WindshieldRain` |
| `weather.niagara_asset` | `-weather-backend=niagara` without `NS_FlightSimRain` |
| `clouds.material` | a registered volumetric cloud (any host, any cloud: the look's, the storm's, the sky's) carries a material that is not a compiled Volume material flagged "Used with Volumetric Cloud"; the engine would assert on it, so the host refuses before its first frame, with the component and material on the line |

A thunderstorm card without a `downburst` block draws its rain and records the
cell and lightning as not drawn (they have no place). That is not a refusal.

## Debugging a crash (what the first Windows runs taught)

The engine's volumetric cloud passes do not refuse a bad cloud material,
they assert: `Assertion failed: Material->GetMaterialDomain() == MD_Volume`
in `VolumetricCloudRendering.cpp`, from the cloud **shadow** mesh pass, which
walks the material's fallback chain and lands on the default *surface*
material when the cloud's own material has no cloud shaders. A material
compiles its cloud shaders only when flagged **Used with Volumetric Cloud**
(`used_with_volumetric_cloud`); a Volume material without the flag compiles
fine, draws nothing, and crashes the shadow pass. `M_StormCell` now carries
the flag (the script sets it on a new asset and in place on an old one),
`BuildCell` checks it, and both hosts run `VerifyCloudMaterials` before the
first frame: every cloud's material, domain, flag and compile errors on one
log line each, a bad one refused as `clouds.material`.

Two tools for the next time something only fails on the engine:

* `python scripts/debug_storm_render.py --backend off --backend procedural`
  writes the storm card and runs the render commandlet directly, a few
  seconds per backend, keeping each log under `runs/debug_storm/<backend>/`
  and printing the decisive lines (weather and cloud lines, materials that
  failed to compile, the assertion if any) and the frames' mean luma. The
  web app's page names the wrong log for a failed host flight and clears
  its frame scratch; this keeps everything.
* `FLIGHTSIM_REBUILD_MATERIALS=M_LensDrops,M_StormCell` (or `all`) before
  the material script deletes those assets and builds them again. The
  script otherwise skips what exists, so a material built by an older script
  keeps its old graph. The `If` node's pins are now connected under the
  name the engine accepts (or the script fails naming the node's real
  inputs): `M_LensDrops`, `M_GreyCard`, `M_LandcoverID` and `M_RainStreaks`
  were all built on a pin name the engine ignored and failed to compile
  ("Missing If AGreaterThanB input"); rebuild them once.

## Seeing nothing (what the second Windows run taught)

The first storm frame that did not crash was black: an aircraft silhouette,
a speckle, nothing else. Three causes, all physical in origin, all fixed:

1. **The cloud was lit by single scattering.** A volumetric cloud material
   without a `VolumetricAdvancedMaterialOutput` node gets no multiple
   scattering: the far side and the underside of a thick cloud receive
   nothing, and the cell is an 11 km tower of 0.19 /m water over the
   camera. `M_StormCell` now carries the node (`STORM_SCATTERING` in
   `scripts/ue_create_materials.py`): the dual-lobe Henyey-Greenstein phase
   of water droplets (g 0.8 forward, -0.5 back, blended half and half;
   Hillaire 2016), two octaves of the Wrenninge et al. 2013
   multiple-scattering approximation at the engine's 0.5 / 0.5 / 0.5, and
   the ground's albedo on the bottoms. Stated, not measured.
2. **The look's deck was 156 optical depths deep.** The storm look states a
   cloud layer from 1200 m to 9000 m; at a stratiform deck's 0.02 /m no
   light leaves it. `BuildCell` draws it as a nimbostratus at most 1500 m
   deep from its base (optical depth 30: dark grey, not black) and records
   the look's top beside the drawn one (`look_layer_top_drawn_m`).
3. **The exposure was the look's.** The storm look's manual bias was
   calibrated for a dim sun and fog; under the cell, with the sun shadowed
   out, the light is stops below that. A camera meters. Before frame 0 the
   render commandlet captures the beauty frame, reads it back, and opens
   `AutoExposureBias` until the bright end of the frame -- the 90th
   percentile of its sRGB luma: the cloud base and the horizon, not the
   dark ground, whose mean says little (the web app's own storm look is
   visible at a mean of 0.09; the black frame was 0.07) -- reaches
   `-storm-meter-target=` (0.40, a storm's grey base; up to five rounds),
   never closing below the look's exposure and never more than 8 stops
   open -- the two-stream transmittance of a column thousands of optical
   depths deep is under 1 %, eight stops, and darkness past that is the
   engine's cloud model, not the storm's. The exposure is then constant
   over the clip (no breathing), the linear and accumulation captures
   carry it too, and `render.json` records it in
   `look_applied.storm_exposure` (the p90 and mean luma before and after,
   the stops opened, the note). The interactive window adapts instead, on the
   engine's histogram metering. `-AutoExposure` meters itself and skips the
   storm meter.

`scripts/debug_storm_render.py` now prints the storm meter's line and the
first and last frame's luma (0..255, the mean and the 90th percentile); a
frame whose 90th percentile is under 32 is `RENDERED-DARK`, not a pass.

Measured on the owner's machine (2026-10-09, the storm look, 640x360): the
weather off renders at luma mean 24 / p90 48; the storm on, the meter read
p90 0.055 (mean 0.028) and opened 1.65 stops over three rounds to p90 0.365
(mean 0.304); the frames came out at mean 78 / p90 93. The first render of
the rebuilt `M_StormCell` compiled its cloud shaders for 14 minutes on a
machine with 1.5 GB free (single compile jobs of one to two minutes each);
the derived-data cache keeps them, so every later render skips that. A material built before this (`M_StormCell`
without the node) is rebuilt by the script on its own: every storm
material is stamped with `STORM_GENERATION` as asset metadata and an older
stamp is built again -- the old asset set aside as `<name>_prev` until the
new one is saved, and put back if the build fails (the first rebuild on the
owner's machine deleted first and failed on a property name the node does
not have, and every storm render was refused for the missing material).
The debug script also renders with the web app's look for the spec (the
storm look's dim sun and fog), clears the previous run's frames first, and
calls a crash a crash even when an older manifest is beside it.

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
| WX.6 | The host's thunder selftest equal to the card's at Build (no sound is played) |

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
