# weather_fx.fog.alpine: valley fog under the Matterhorn frame

**VISUAL-ONLY. Every number here is a model value. Nothing in this lane has
been rendered: the look and the cost are UNMEASURED until the Windows command
in "Pixel gate" has run on the laptop. No tier is claimed as sustained.**

## What this is

A shallow fog layer filling the valley below the peaks (a "sea of fog"), seen
from above by scenario 11's 5000 m chase camera. The Google tiles stay the
ground: the fog is drawn over them and they show through where it thins.

| file | role |
|---|---|
| `bake_alpine_fog.py` | the Mac generator (standard library only, 1 s) |
| `alpine_fog.json` | the model, the engine numbers, per-tier settings, check tables |
| `alpine_fog_top.png` | 256x256 RGBA8 tileable fog-top relief for tiers 1-2 |
| `measure_fog.py` | the pixel gate, run on Windows on two frames |
| `PROVENANCE.json` | sources and sha256; nothing vendored |

The density is one exponential in height, the only profile
`ExponentialHeightFog` draws, so tier 0 adds no pass, no texture and no memory
to a frame that already pays for the height fog:

    sigma(z) = exp(-(z - 1900) / 200) / 200   [1/m]

| altitude | vertical optical depth above | visibility (Koschmieder) |
|---|---|---|
| 1600 m (valley floor) | 4.48 | 175 m |
| 1900 m (fog top) | 1.00 | 780 m |
| 2300 m | 0.135 | 5.8 km |
| 2700 m | 0.018 | 43 km |
| 4478 m (summit) | 2.5e-6 | none |

Above about 2700 m the layer adds nothing, so it does not double the haze the
aerial-perspective lane owns.

## Gate clauses

`docs/WEATHER.md` WX.1-WX.6 cover drops, streaks, splashes, the storm tower,
lightning and thunder. None of them measures fog, and this lane changes none
of what they measure. The one obligation they put on it: the card block of a
spec with no precipitation must stay byte-identical, so the fog must be a new
key that exists only when asked for (step 1). Fog's own check is the pixel
gate below.

## Proposed change (for the integrator; this lane edited no shared file)

1. **Asking for it.** Scenario 11's prompt does not mention fog. Add
   `environment.valley_fog` to the spec, in exactly this shape:
   `{"top_m": 1900.0, "scale_height_m": 200.0}`. It is compiled from "valley
   fog" / "sea of fog" in a prompt and accepted by `core/scenario/validate.py`
   (which today refuses it as an unknown key). Absent key: no fog, card
   unchanged byte for byte. No environment variable: the runner talks to an
   already running web app, so a variable set in the runner's shell would
   never reach the renderer. The gate's A/B is two pinned specs that differ
   in this one key.
2. **Tier 0, in `FlightSimDustHaze.cpp` or a small new `FlightSimValleyFog`,
   after the dust-haze overlay.** Read `alpine_fog.json` `engine`:
   - `SecondFogData.FogDensity = 0.104068`
   - `SecondFogData.FogHeightFalloff = 0.0721348`
   - `SecondFogData.FogHeightOffset` so the layer's reference height is
     1900 m AMSL: `(1900 m - fog actor Z in metres AMSL) * 100`.
   - `FogInscatteringColor` (today black under the physical sky,
     `FlightSimSky.cpp:252`) `= sun_tint_rgb * 0.46655 * sun_direct_normal_lux
     * sin(sun_elevation) / pi`, in cd/m2, from the run's own sun. Nominal
     (sun 30 deg, 86 830 lx): 6447 cd/m2, 0.43 of flat sunlit snow. Leave
     `SkyAtmosphereAmbientContributionColorScale` white: the sky's share
     stays the engine's.
   - `r.VolumetricFog 0`.
3. **Tier 1.** One horizontal quad (60 km, following the camera in x,y) at
   1900 m, unlit translucent, no shadow, no depth write. Material:
   `alpine_fog_top.png` tiled every 4000 m (import linear, mips on);
   colour = fog colour x A x (0.75 + 0.25 x saturate(N.L));
   opacity = saturate((scene depth - pixel depth) / 150 m) x saturate((camera
   Z - 1900 m) / 200 m). The first factor is the soft shoreline against the
   terrain, the second removes the card when the camera descends into the
   fog. Also `DirectionalInscatteringExponent 16` and
   `DirectionalInscatteringColor = 0.5 x FogInscatteringColor`.
4. **Tier 2.** Four such quads at 1900, 1870, 1840, 1810 m, opacity 0.4 each,
   UV offset by the height channel for parallax.
5. **Tier 3.** Tier 1 plus the cvars in `alpine_fog.json` `tiers[3].cvars`.
   Read the caveat below before spending a stress run on it.

## Conflicts the integrator must settle

- **The second fog slot is already used** by the dust-haze overlay's inversion
  layer (`FlightSimDustHaze.cpp:538`). The engine has one second slot. For a
  spec with both, the valley fog should win below 2700 m and the record say so.
- **The tiles' haze hold would undo the fog.** `FlightSimGoogleTiles.cpp`
  lines 690-742 scale both fog densities down until a 10 degree ray has an
  optical depth of at most 1.5. This layer has 25 on that ray by design. The
  hold must skip the valley-fog layer (compute its scale from the first layer
  alone), or the fog renders as thin mist and the gate fails.
- **One in-scatter colour serves both fog layers.** The sun term in step 2
  also lights the main haze layer. If the main layer keeps a non-zero density
  in this scenario, distant haze brightens too; `peak_delta` in the gate is
  the check for that.
- **`FogMaxOpacity` is 0.92** (`FlightSimVisualScene.cpp:731`), so the valley
  never drops below 8 % of the ground. The gate's reference includes that
  floor; if the integrator raises it, pass the new value through
  `bake_alpine_fog.MAX_OPACITY` and re-bake.
- **`FogDensity` 0.104 is above the editor slider's 0.05.** Whether the
  setter clamps was not read; read the value back after setting it.

## Tiers (estimates, not measurements)

| tier | extra VRAM (est.) | extra cost (est.) | what it adds |
|---|---|---|---|
| 0 | 0 MB | none: same height-fog pass | the layer and its sunlit colour |
| 1 | 0.1 MB | one translucent layer over the valley pixels, 1 texture sample | relief on the fog top, soft shoreline, sun-side glow |
| 2 | 0.1 MB | up to four translucent layers over the valley pixels | parallax in the relief |
| 3 | about 6 MB | froxel fog: compute and a temporal history every frame | peak shadows cast into the fog |

Tier 3 caveat: UE's volumetric fog covers the first few kilometres from the
camera (its range was not read here). From 5000 m the fog top is 3.1 km
straight down and further on every other ray, so the froxels would mostly
miss it. Tier 3 is worth trying only for a camera inside
the valley, and it is the tier most likely to cost a device loss on this GPU.

## Pixel gate (UNMEASURED; run on the Windows laptop)

From the repository root in cmd.exe, with the web app running on
127.0.0.1:8008. Nothing to fill in, no environment variable:

```bat
python scripts\run_test_scenarios.py --still --only 11 --spec-dir runs\alpine_fog\off
python swarm\lanes\weather_fx\fog\alpine\measure_fog.py keep baseline
python swarm\lanes\weather_fx\fog\alpine\measure_fog.py fog-spec
python scripts\run_test_scenarios.py --still --only 11 --spec-dir runs\alpine_fog\on
python swarm\lanes\weather_fx\fog\alpine\measure_fog.py keep candidate
python swarm\lanes\weather_fx\fog\alpine\measure_fog.py gate
```

The first run pins scenario 11's compiled spec as `runs\alpine_fog\off\11.json`;
`fog-spec` writes the same spec plus `environment.valley_fog` to
`runs\alpine_fog\on\11.json`; `keep` copies the frame straight from the run
directory named in `runs\test_scenarios.json`, with the runner's outcome
beside it. `gate` prints one JSON object and exits:

| exit | status | meaning |
|---|---|---|
| 0 | pass | both clauses met |
| 1 | fail | measured, a clause is not met |
| 3 | blocked | NOT MEASURED: no fog frame exists to judge |

**What it answers today.** Step 1 above is not integrated, so the validator
refuses the candidate spec (`unknown keys`, `core/scenario/validate.py:896`),
no candidate frame is written and `gate` exits 3 with that refusal as the
reason. That is read from the source, not run. It is the honest state: this
lane has no rendered fog and claims none. The gate can pass only after steps
1 and 2 are in.

- `fog_t_abs_error` = |T_valley - T_ref|. The frame is cut into 32 px blocks;
  each textured block is fitted `fogged = T x clear + S`; T_valley is the lower
  quartile of T over the fogged blocks (T <= 0.5); T_ref = 0.08, the
  valley-floor value under `FogMaxOpacity` 0.92. **Pass: <= 0.10.** With fewer
  than 4 fogged blocks the metric is 0.92 and the gate fails.
- `peak_delta` = median over the untouched blocks (T >= 0.9) of the mean
  absolute linear difference. **Pass: <= 0.02 and at least 4 such blocks.**
- Printed, not gated: the fog's own colour `S / (1 - T)`.

Not known until it runs: whether scenario 11's frame shows any terrain below
1900 m at all (if it does not, the gate fails for want of fogged blocks and
the shot, not the fog, is the finding); whether two stills of one pinned spec
are the same shot pixel for pixel under severe turbulence; how much
auto-exposure moves the untouched blocks. The block size and texture
threshold are choices, not calibrated values.

Also record from the same run, as the stability evidence for tier 0: the
process exit code, any "device lost" or `DXGI_ERROR_DEVICE_REMOVED` line in
the UE log, and the frame time. The Mac cannot produce any of them.

## What is not known

- Whether this depth of fog is the look the owner wants. The top height,
  the scale height and the valley albedo are choices, not measurements.
- The fog's brightness relative to the snow: a two-stream estimate, flagged
  UNCALIBRATED in the card.
- The sources for the formulas were typed from memory, not fetched
  (`PROVENANCE.json` says which).
- Tiers 1-3 are described, not built: no material asset exists yet.
