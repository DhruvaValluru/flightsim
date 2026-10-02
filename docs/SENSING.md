# Sensing (S1): radiometry, the sun in lux, the optics PSF, the motion blur

Written 2026-09-29 on `claude/relaxed-cori-gccjvx` (= `phase2`) against HEAD
`d0529c1` (ADVANCEMENTS_BLUEPRINT section 3, work item S1; gaps S1 and S2 of
docs/PHASE3_GAP_ANALYSIS.md). Every number below was measured in this container
unless it says `[unverified here]`; nothing engine-side was compiled or run.

## What is delivered, in one paragraph

A stated linear-radiance path for the frames the engine renders: what one unit of
the linear frame is worth in cd/m^2 under the manual EV100 exposure both hosts
share (core/capture/exposure.py), with the lens attenuation Unreal divides by, an
exposure compensation per camera, and a calibration status that is `predicted`
until the engine's grey card (S4, a Windows step) measures it; a band proxy that
turns the three photometric channels into a band radiance through two cached
published tables and NOTHING written in code; the scene's sun in lux from a
cited clear-sky model, so the render can be handed `-sun-lux=` instead of the
unitless 8.0 the visual scene sets today; a diffraction x Gaussian point-spread
kernel applied by the sensor post-pass and checked by a slanted-edge
measurement; a velocity-line motion blur over the shutter time; four optional
profile blocks in one pinned post-pass order; the records, the manifest blocks,
the verifier's three checks and the refusals by name.

## The chain (core/capture/radiometry.py)

    v = L_v / (1.2 x A x 2^(EV100 - EC))

* `1.2` = 78 / (0.65 x 100): ISO 12232's saturation speed over ISO 2720's
  exposure constant (Lagarde & de Rousiers 2014, section 5.1) [the standards
  unverified here].
* `A` = Unreal's `r.EyeAdaptation.LensAttenuation`, documented default 0.78
  [unverified here], replaced by the read-back in render.json's
  `render_settings.console` when a render exists (the skeptic's recomputation of
  Epic's worked example needs it; the research had omitted it).
* `EC` = `cameras[i].exposure_compensation_ev`, stops; +1 halves the luminance
  one unit stands for (the picture doubles).

Measured: the daylight triple (f/8, 1/500 s, ISO 100; EV100 14.966) gives
29 951.6 cd/m^2 per unit with A (38 399.5 without). An 18 % Lambertian card,
L = rho E / pi, under the engine's 8.0 sun reads 1.53e-5 of full scale (black);
under the clear-sky sun at 50 degrees (95 788 lx) it reads 0.183. That is the
defect `sensing.exposure_units` names: the visual scene sets the sun to 8.0
(FlightSimVisualScene.cpp L164) while `ApplyPhysicalExposure` runs whenever a
card carries `cameras[].exposure`. After a render the chain checks
`look_applied.sun.light_units` and records the refusal BY NAME in the camera's
block and every frame (`calibration_status: refused`) -- never a refusal of the
run.

`calibration_status`: `predicted` (no grey card has been rendered; the constant
carries no traceable chain to a reference luminance, a stated gap), `measured`
(S4's `calibration.json` beside the bundle carries a finite `ratio`), `refused`
(the sun is not in lux).

## The band proxy (assets/sensor_bands/rgb_proxy.json, `proxy: true`)

    L_e,band = L_v,ch / (683 K_band),   K_band = int(S V w_band) / int(S w_band)

`S` is the ASTM G173-03 direct + circumsolar spectrum, `V` the CIE 1924 V(lambda)
at 1 nm, `w_band` a rectangular window: blue 400-490, green 490-580, red 580-680
nm (declared, not measured). Measured K_band: blue 0.0596, green 0.7588, red
0.3412 (683 K: 40.7, 518.3, 233.0 lm/W). Identity weights reproduce the frame bit
for bit (the null). No spectral rendering, no BRDF spectra, no camera response:
a linear proxy over three sRGB / Rec.709 channels under a stated illuminant.

## The tables (scripts/fetch_sensing_tables.py; refused when absent)

* `assets/cie/vlambda_1nm.csv` -- CIE 1924 photopic V(lambda), 471 rows,
  360-830 nm, V(555) = 1; sha256 `642040f6...` in its sidecar.
* `assets/illuminants/astm_g173_direct.csv` -- ASTM G173-03, 2002 rows,
  280-4000 nm, four columns; sha256 `38ef0437...` in its sidecar.

Where the bytes came from, honestly: the primary hosts are unreachable through
this container's proxy (measured 2026-09-29: cie.co.at and files.cie.co.at
refuse the CONNECT, cvrl.org answers 403, nrel.gov refuses), so the script read
two MIRRORS that redistribute the tables verbatim under BSD-3-Clause
(colour-science `lefs.py`, pvlib `ASTMG173.csv`) and each `.provenance.json`
says so: `fetched_kind: mirror`, `primary_verified: false`, the primary URL named.
`--primary` on a networked machine fetches the primaries and records that. Every
loader checks the sidecar digest; an absent table, a missing sidecar or a digest
that is not the sidecar's refuses `sensing.radiometry` and no number is invented.

Measured from the cached tables: the direct spectrum's luminous efficacy 683 x
int(S V) / int(S) = 107.92 lm/W (the constant solar.py declares); global tilt
109.45; extraterrestrial 98.74 lm/W and 133 100 lx (the ceiling above which a
stated sun refuses `sensing.sun_lux`).

## The sun in lux (core/scenario/solar.py `illuminance_lux`)

Bird & Hulstrom's simplified clear-sky direct normal irradiance (SERI/TR-642-761,
1981; the coefficients transcribed from memory, [unverified here]) times the
declared efficacy 107.92 lm/W, provenance `model`. Defaults: ozone 0.3 atm-cm,
water 1.5 cm, aerosol optical depth 0.1 at 500 nm and 0.15 at 380 nm, the ISA
pressure at the scene's altitude. Measured: 943.0 W/m^2 and 101 769 lx at the
zenith; 95 788 lx at 50 degrees (the harness's noon look); 84 446 at 30; 49 326
at 10; 0 lx at or below the horizon with the reason (twilight not modelled, not
a refusal). `scene.sun_lux` states one instead (user); the capture's `--sun-lux
auto` hands the model's value to `-sun-lux=`. Not claimed: the diffuse sky, any
cloud, the air-mass dependence of the efficacy (a constant; the spread between
the three G173 columns is 98.7-109.5 lm/W), and that the engine's light unit is
lux until S4 reads back `light_units: physical`.

## The optics (core/capture/optics.py)

    MTF(nu) = (2/pi)[acos(nu/nu_c) - (nu/nu_c) sqrt(1 - (nu/nu_c)^2)] x exp(-2 pi^2 sigma^2 nu^2),  nu_c = 1/(lambda N)

The kernel is the inverse FFT of the MTF on the pixel grid's frequencies, on an
odd support, clipped at zero (the truncation's ringing, its energy recorded) and
normalised to energy 1; its sha256 and the analytic MTF50 (cycles per pixel) are
recorded. Measured by the module's own ISO 12233 e-SFR on a synthetic 5 degree
edge blurred by the kernel: sigma = 1 px at the default 28.125 um pitch,
analytic MTF50 0.1823, measured 0.1815 (0.45 %); diffraction alone at a 2 um
pitch, f/8, 550 nm, analytic 0.1836, measured 0.1812 (1.3 %). A kernel whose MTF
is still above 0.05 at Nyquist aliases on the grid (sigma = 0.5 px: 0.27, 4.7 %
off) and is flagged `aliased`, not claimed. At the default pitch the diffraction
cutoff is 6.39 cycles/px, far above Nyquist: the kernel there is the Gaussian
term alone (`sub_pixel_diffraction: true`). An absent block leaves the frame
bit-identical (the null). Shift-invariant; one wavelength; no pixel aperture in
the kernel; no flare.

## The motion blur (core/capture/blur.py)

The velocity-line integral over the exposure: N = max(3, ceil(2 |f| t_exp / dt))
equally weighted taps at the symmetric offsets L (k/(N-1) - 1/2) along the flow
(pixels per dt = 0.1 s, the telemetry interval), bilinear, edges clamped. The
flow is the engine's flow file when the frame has one (I6), else the camera's
own rotation (fx w_y dt, fy w_x dt): a stated frame-wide flow, not the scene's.
When the bundle says the engine accumulated k > 1 sub-exposures (S4's
`-accumulate=K`) the integral is NOT applied and the block records
`engine_accumulation`. Measured on a moving synthetic edge (the streak read off
the line spread function's variance with the tap factor (N+1)/(N-1) and the
edge's own variance removed): L 2.0 -> 2.19, 3.85 -> 4.04, 5.0 -> 5.17,
6.0 -> 6.13, 10.0 -> 10.09 px at three sub-pixel edge positions (largest error
0.19 px, inside the 0.25 px clause). Below 2 px the three bilinear taps are wider
than the streak (0.5 -> 1.0, 1.0 -> 1.41 px), flagged `sub_pixel_taps`, not
claimed. Exposure 0 returns the frame itself (the null). Linear motion, not
occlusion-aware, no rotation within the exposure.

## The profile (core/capture/profile.py)

Four optional blocks, each absent from both shipped profiles (their sha256s
unchanged and pinned): `optics` (`sensing.optics`), `motion_blur`
(`sensing.motion_blur`), `radiometry` (`sensing.radiometry`: a stated lens
attenuation and working colour space), `bands` (`sensing.band`). The post-pass
runs in ONE pinned order, `POST_PASS_ORDER`: radiance (band weights) -> psf ->
blur -> vignetting -> geometry -> exposure -> noise -> adc; a stage whose block
is absent passes the frame through bit for bit. `sensor.json` records the order
and each frame's `sensing {stages, radiance, psf, blur}`. Timing at 1280 x 720
x 3 in numpy: the PSF convolution 0.52 s (support 9), a 6 px streak 3.26 s (12
taps), the luminance scaling 4 ms.

## The spec, the card, the manifest, the records

* Spec (still 8): `cameras[i].exposure_compensation_ev` (EV, default 0) and
  `cameras[i].bands` (a band file name, default None), both absent-canonical
  like the exposure triple; `scene.sun_lux` (lx, default None), absent-canonical
  INSIDE the existing scene block (`SceneSpec.OPTIONAL_FIELDS`) because one
  committed example already states a scene block. Every committed example's
  digest is unchanged (pinned).
* Card: the camera entry carries `sensing {exposure_compensation_ev, bands}`
  when stated (nothing engine-side reads it yet: S4).
* Manifest (still 6): `cameras[i].sensing {requested_by, exposure, radiometry,
  bands, optics, motion_blur}` only when the camera, its profile or the scene
  asked; per-frame `radiometry {luminance_cd_m2_per_unit,
  exposure_compensation_ev, lens_attenuation, calibration_status,
  exposure_units}`; the first sensing camera's records in `applied_variables`.
* Records (record 2): `sensing.radiometry` (value the luminance per unit;
  readback A; null: EC +1 halves it, reached), `sensing.bands` (readback K_band
  recomputed; null: identity weights reproduce the frame, bounded 0),
  `sensing.optics` (readback the kernel energy 1; null: absent -> bit-identical,
  bounded 0; the e-SFR MTF50 beside the prediction), `sensing.motion_blur`
  (readback the tap count against the rule; null: exposure 0 -> identical,
  bounded 0). The registry claims the `scene` section (three entries) and
  registers the four sensing variables as observers: `cameras[i].<field>` is a
  list element the registry's section.leaf address cannot claim, so they are
  recorded through the manifest's per-camera block with producer-measured nulls.
  The scene.sun_lux null pair, run for real on a 1 s c172p flight: equal output
  digests, peak 0 on lat_deg and lon_deg, verdict silent.

## The render flags and the capture command

`-calibration`, `-sun-lux=<lux>`, `-accumulate=<K>`: emitted by the one builder
only when asked, after `-passes=`; the default list is byte-identical (pinned).
`flightsim.capture --calibration`, `--sun-lux LUX|auto`, `--accumulate K`; a sun
outside (0, 133 100] refuses `sensing.sun_lux` before any render. The web app
asks for none (parity pinned). S4 implements the flags in the commandlet: the
calibration frame (an emissive grey card at stated cd/m^2, a white Lambertian
quad under the sun alone, a 5 degree slanted-edge quad; `calibration.json`),
the sun in physical units, the AA-off accumulation capture.

## The verifier (core/capture/verify.py; imports nothing from the producers)

* `psf_slanted_edge`: the checker's OWN e-SFR (edge crossings at the half level
  between each row's 10th and 90th percentiles, a least-squares line, quarter-
  pixel binning along the normal, a Hamming-windowed LSF) on the sensor frame's
  calibration edge quad against the manifest's predicted MTF50 within 5 %; the
  kernel sensor.json says it applied must be the manifest's. FAIL
  `annotation.psf`; NOT RUN without a sensing.optics block or a calibration edge.
* `blur_vs_flow`: the recorded streak per frame against the flow file's 95th
  percentile over the capture interval times the exposure, within max(0.25 px,
  10 %). FAIL `annotation.blur`; NOT RUN without a flow pass (S2) or for a frame
  the engine accumulated (S4).
* `radiometry_grey_card`: `calibration.json`'s ratio against the manifest's
  predicted grey card, within 2 %, the status `measured`. FAIL
  `annotation.radiometry`; NOT RUN without the file (S4) or when the chain was
  refused `sensing.exposure_units`.

All three pass a clean synthetic bundle here and fail by name on each
corruption (tests/test_radiometry.py); on a real headless capture all three
report NOT RUN with their reasons.

## Refusal names

`sensing.radiometry`, `sensing.band`, `sensing.optics`, `sensing.motion_blur`,
`sensing.sun_lux`, `sensing.exposure_units`; `annotation.psf`, `annotation.blur`,
`annotation.radiometry`; `check.psf_slanted_edge`, `check.blur_vs_flow`,
`check.radiometry_grey_card`.

## Not claimed

No spectral rendering and no BRDF spectra. The radiometry is photometric
luminance per channel converted by a stated illuminant; the constant
1.2 x A x 2^EV100 is predicted until the grey card measures it and has no
traceable chain to a reference luminance (a gap, stated; a future clause ties it
to an ISO 12232 saturation exposure with u_D). The lens attenuation is the
console default until read back. The working colour space is the engine's. The
sun's lux is a broadband clear-sky model with a constant efficacy, no diffuse
sky, no cloud, no twilight; the engine's light unit is not lux until S4. The PSF
is shift-invariant, one wavelength, no pixel aperture, no flare. The blur is
linear motion, not occlusion-aware, the flow a stated one until S2's pass. The
tables are mirror copies whose primaries were not reached here. Nothing
engine-side was compiled or run; the three verifier checks have graded synthetic
bundles only. No version was bumped: every key is optional and absent-canonical.
