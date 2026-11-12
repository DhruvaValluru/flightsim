# Rounds 8-12 review (p3-mac): vis-windows 41d064a4..a78698d8

Sheet: sheet.jpg (latest frame of each scene, rounds 8-12).

## Verdict: not converging on the aircraft. Weather is mixed.
- **Aircraft still dark/brown** after lane A (SSAO world radius, cloud-AO auto-off, subject meter): #01, #04 A-4 brown and
  semi-transparent; #06 A320 near-black; 747s mid-grey. Three rounds of guesses: switch to a bisect (rounds 13-15).
- **#01 golden hour is now deep blue** over the whole frame (warm in r4/r5). Upstream of the meter (r11 meter off is bluer).
  Introduced between r5 and r10.
- #13 renders (697c4ca6), but the clouds are blocky/cubist, the ocean is a flat tile grid with light streaks, and the gear is down in cruise.
- #04/#13 clouds blocky; wing-tip lights are big white bloom dots.
- #10: the C172 is now visible (about 30 px), but the funnel is green and the dust a beige blob.
- #15: a white-grey whiteout with cartoon cumulus and regular rain dashes. It reads as fog, not a hurricane.
- #06 r9 beats r8 (SSGI off is paler), so keep SSGI. #07 heavy rain reads plausibly.
- #09 lost the device after about 15 min of first-time storm shader compiles.
- Labels: the store_sta2 manifest rows are fine (0.3 px), so the 3.4 px box shift is downstream (projection or hull).
