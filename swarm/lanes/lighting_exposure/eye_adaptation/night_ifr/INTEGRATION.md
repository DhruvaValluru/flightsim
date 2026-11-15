# lighting_exposure.eye_adaptation.night_ifr: integration

Status: **UNMEASURED**. Everything here was computed on the Mac. No frame was
rendered, no tier is known to hold on the laptop, and no visual claim is made.
The scenario numbers, the eye's timing and the 0.25 EV excursion are
**visual-only** choices. This lane edited no shared file.

## The idea

The calibrated night look is already a rule in `core/sky/plan.py`: one EV100
for the clip from the moon and night-sky lux, "night renders dark, not metered
to noon". The gate is +/-0.3 EV of it. An engine histogram meter left free
would break that on the first dark frame.

So the eye is a **bounded excursion of at most 0.25 EV** around the look,
stepped on the CPU and applied as manual exposure. It opens inside the cloud
deck. Tier 0 adds no GPU pass, no texture and no readback.

| Quantity | Value |
|---|---|
| Look: horizontal lux (full moon at 40 deg + night sky) | 0.174 lx |
| Look: EV100 | 1.739 |
| UE exposure bias at the look (camera EV100 9.907) | 8.168 |
| Eye band | EV100 1.489 to 1.989 |
| Saturation luminance at the look | 4.0 cd/m2 |
| In cloud | opens to -0.25 EV over about 16 s (tau 4 s) |

`baked/night_ifr_eye.json` has the parameters, the look for 16 moon states and
the tier settings. `baked/night_ifr_eye_curve.csv` is the canonical approach
(12 km to threshold, 0.5 s rows) with `offset_ev`, `ev100` and
`ue_exposure_bias` per row.

## What is NOT here: the eye closing on the runway lights

The eye should close after breakout as the approach and runway lights fill it.
That needs the lights' intensity, and the project has none:
`core/scene/runway.py` `PHOTOMETRY["candela"]` is `None` ("named as missing,
never invented"). An earlier version of this lane used intensities recalled
from memory and reported a distance at which the eye finished closing. Those
figures and that distance are **withdrawn**; the test fails if they return
while the project's photometry is still missing.

What remains is independent of any intensity:

- the formula (`generate.py eye_lux_from_lights`, Allard's law, takes the
  light list as an argument);
- the illuminance the lights must put at the eye, under the deck, for the eye
  to return to the look (0.131 lx) and to reach the close clamp (0.203 lx);
- the baked curve, which has **no light term**: under the deck it stays open
  at -0.25 EV.

When the runway lane has sourced photometry, pass its list to
`generate.curve(field)` and regenerate.

## Proposed changes (for the integrator)

1. **`core/sky/plan.py`, `build_plan` exposure block**: add an optional
   `"eye"` object next to `"bias"`, copied from the JSON's `eye` block
   (`max_excursion_ev`, `tau_close_s`, `tau_open_s`) plus the look's
   `horizontal_illuminance_lux`. Absent = today's behaviour. Update the
   `"basis"` string: it says "constant over the clip".
2. **`FlightSimSky.cpp` (where `Out.ExposureBias` is read, line 142) and the
   per-frame path in `FlightSimRenderCommandlet.cpp`**: when `eye` is present,
   keep `AEM_Manual` and each frame set

   ```
   eye_lux  = ambient_lux * (camera above the deck ? 1 : deck_transmittance)
              + sum over visible runway lights of  cd * exp(-sigma * d) / d^2
              (the sum is 0 until the runway document carries candela)
   target   = clamp(0.5 * log2(eye_lux / look_lux), -0.25, +0.25)
   tau      = target > offset ? tau_close_s : tau_open_s
   offset   = target + (offset - target) * exp(-dt / tau)
   AutoExposureBias = plan bias - offset
   ```

   Start `offset` at 0. For `--still`, set `offset = target` (no history).
3. **Record it**: write `offset_ev` and the resulting EV100 per frame into
   `look_applied` so the measure script's `--expected` has a source.
4. **Frame and subject meters** (`beauty_look.EXPOSURE_METER_TARGET_P90`,
   `SUBJECT_METER`): they must not run on this scenario, or must be clamped to
   the same band. Either would otherwise move a night frame by up to a stop.
5. **`scripts/run_test_scenarios.py`**: there is no night scenario. Add one,
   e.g. "night IFR approach" = `cockpit view of the a320 on final approach to
   sfo at midnight under overcast for 6 seconds`. Whether the compiler accepts
   "final approach" and "overcast" at night is untested.

## Tiers (VRAM figures are estimates)

| Tier | Est. VRAM | What |
|---|---|---|
| 0 | 0 MB | `AEM_Manual`; CPU eye sets the bias each frame |
| 1 | 0.1 MB | `AEM_Basic`, Min/MaxBrightness 1.489 / 1.989, SpeedUp 2, SpeedDown 0.25 |
| 2 | 0.5 MB | `AEM_Histogram` (compute shader), same clamp, 10-90 % window |
| 3 | 3 MB | tier 2 plus local exposure (highlight and shadow contrast 0.8) |

Tiers 1-3 hand the eye to the engine and rely on the Min/Max clamp to stay in
the gate. Unverified on UE 5.7: that Min/MaxBrightness are read as EV100
(extended luminance range on), that the engine's speeds are in stops per
second, and that the histogram pass is stable on this D3D11 driver. Tier 0
does not depend on any of the three.

## Measuring it on the Windows laptop

### The metric

Four frames, same camera and instant: the reference (the look), the candidate,
and two **brackets** rendered 0.3 EV darker and 0.3 EV brighter than the look.
The brackets are the gate's edges, rendered through the same tonemapper, so no
tone curve is modelled. `ev_offset` = median over usable pixels of the
candidate's place between the reference and the bracket on its side (log2 of
sRGB-decoded luma), scaled to 0.3. Pass: `|ev_offset| <= 0.3`, at least 0.5 %
usable pixels, sign agrees with `--expected` when that is 0.1 EV or more, and
the eye helped: closing adds no clipped pixels (luma >= 254), opening adds no
crushed ones (luma <= 1).

The earlier two-frame metric (log ratio of reference to candidate) is no
longer the gate: through a contrasty tone curve it reads a 0.25 EV change as
more than 0.3 (shown by test, on a stand-in curve). It is still printed, as
`display_ev_offset`, for information.

### Runnable today (no integration needed)

This uses only what exists: scenario 6 (`a320 over sfo heading south, moderate
rain`, a daytime scene), `--spec-dir` pinning, and the spec's own
`lighting.brightness_ev`. The candidate is the look moved by the eye's close
clamp (brightness_ev -0.25). The web app must be running on 127.0.0.1:8008.
Four stills, one at a time.

```
.venv\Scripts\python.exe scripts\run_test_scenarios.py --only 6 --still --spec-dir runs\eye_gate\reference
.venv\Scripts\python.exe swarm\lanes\lighting_exposure\eye_adaptation\night_ifr\gate_tool.py stash reference
.venv\Scripts\python.exe swarm\lanes\lighting_exposure\eye_adaptation\night_ifr\gate_tool.py specs --pinned runs\eye_gate\reference\06.json
.venv\Scripts\python.exe scripts\run_test_scenarios.py --only 6 --still --spec-dir runs\eye_gate\bracket_dark
.venv\Scripts\python.exe swarm\lanes\lighting_exposure\eye_adaptation\night_ifr\gate_tool.py stash bracket_dark
.venv\Scripts\python.exe scripts\run_test_scenarios.py --only 6 --still --spec-dir runs\eye_gate\bracket_bright
.venv\Scripts\python.exe swarm\lanes\lighting_exposure\eye_adaptation\night_ifr\gate_tool.py stash bracket_bright
.venv\Scripts\python.exe scripts\run_test_scenarios.py --only 6 --still --spec-dir runs\eye_gate\eye_closed
.venv\Scripts\python.exe swarm\lanes\lighting_exposure\eye_adaptation\night_ifr\gate_tool.py stash eye_closed
.venv\Scripts\python.exe swarm\lanes\lighting_exposure\eye_adaptation\night_ifr\measure_frame.py --frame runs\eye_gate\eye_closed.png --reference runs\eye_gate\reference.png --dark-bracket runs\eye_gate\bracket_dark.png --bright-bracket runs\eye_gate\bracket_bright.png --expected 0.25
```

What that run would and would not tell us:

- It would tell us whether an exposure step the size of the eye's clamp
  arrives on the rendered frame as that step, inside the gate, on this laptop:
  i.e. that nothing downstream (the frame meter, the subject meter, the tone
  curve, 8-bit output) eats it or doubles it, and that 0.25 EV can be told
  from the 0.30 EV edge at all.
- It is a **daytime rain scene**, not night, and the candidate is a constant
  offset, not the eye. It does not test the night look or the eye's timing.
- Unknown until run: whether four stills of the same pinned spec are identical
  apart from exposure (rain and TAA may differ between runs; the median should
  absorb some of that, not all).

### The night gate proper (BLOCKED on changes 1-5)

Not runnable today: there is no night scenario and no eye in the render path.
After the integration, pin the new scenario the same way; reference = eye off,
brackets from `gate_tool.py specs`, candidate = eye on, `--expected` =
`offset_ev` from `look_applied`. A night frame may have too few mid-range
pixels, in which case the script fails with that reason rather than guessing;
a short-final frame with lit pavement is the one to measure. The absolute
level of the reference (is the look itself right) is the physical_light_units
item's question, not this one.

## Tests

```
.venv/bin/python -m pytest tests/test_swarm_lighting_exposure_eye_adaptation_night_ifr.py
```

They need the repo venv (numpy, for `core.sky.plan`). The module imports
`core.sky.plan` at the top and fails to collect without it; nothing is
skipped. The look is checked against `plan_sky()` for three real nights. The
pixel-gate arithmetic is checked through two stand-in tone curves the metric
does not know; that is still arithmetic, not a rendered frame.

## Regenerate

```
.venv/bin/python swarm/lanes/lighting_exposure/eye_adaptation/night_ifr/generate.py
```

Deterministic; the test pins the bytes to PROVENANCE.json.
