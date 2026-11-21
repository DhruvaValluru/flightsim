# Flight model check: the numbers the 3-D pictures print vs published data

The detailed picture's forces and flight state are the JSBSim flight
model's own values at each frame. This page checks those models against
published performance figures, so a reader knows how far to trust them.
Reproduce with `python scripts/flight_model_check.py` (JSBSim 1.2.4,
2026-11-20).

| Aircraft | Quantity | Flight model | Published | Difference |
|---|---|---|---|---|
| Cessna 172P | stall, flaps up, power off, 2400 lb, sea level | **53.2 kt** (CLmax 1.44 at 16.1 deg) | **51 KCAS** (172P spec); 50-53 KCAS aft-forward CG (C172N POH) | +4 % (inside the CG band) |
| Cessna 172P | top level speed, 1,500 ft | **130 kt** (model at 1,880 lb) | **123 kt** at sea level | about +6 % (lighter test weight) |
| A-4 (A-4E) | top level speed, 1,500 ft, clean | **600 kt** (Mach 0.91, throttle 0.99) | **585 kt** (673 mph) at sea level | about +3 % |
| A-4 (A-4E) | top level speed, 1,500 ft, default stores | **530 kt** (stores add CD 0.015) | -- (published figure is clean) | slower, as stores should make it |
| A-4 (A-4E) | stall, clean, 8295 kg | 144 kt (CLmax 1.00 at 14.9 deg) | not found in a citable source | -- |

## What it means

* **Both models are trustworthy for what the pictures show.** The Cessna's
  stall is within 4 % and its top speed within ~6 % of the handbook; the
  clean A-4 reaches 600 kt against 585 kt published (+3 %), and carrying
  its default stores it is slower (530 kt), as it should be.
* **Correction to the first version of this page.** It read the A-4 at
  ~410 kt (-30 %) and blamed its drag. That test flew at 100 ft, where
  the simulator (correctly) keeps retractable gear DOWN (core/fdm/gear.py,
  GEAR_UP_AGL_FT): the gear added CD 0.020 and the stores another 0.015.
  Every real run flies above that height with the gear up. The check now
  flies at 1,500 ft; nothing in the A-4 model needed changing.
* **What the pictures show at cruise.** On the default loadout the A-4's
  drag includes the stores (about 40 % of its zero-lift drag), so its
  DRAG and THRUST read higher than a clean A-4's at the same speed.

## Sources

* Cessna 172P stall 51 KCAS, max 123 kt at sea level: https://172guide.com/models/172P-81.htm, https://172guide.com/models/172P-85.htm
* C172N POH stall band by CG (50-53 KCAS at 2,300 lb): https://aopa.org/news-and-media/all-news/2020/march/flight-training-magazine/aerodynamics-stall-speed
* A-4E maximum speed 673 mph at sea level: https://www.history.navy.mil/content/history/museums/nnam/explore/collections/aircraft/a/a-4-skyhawk.html
