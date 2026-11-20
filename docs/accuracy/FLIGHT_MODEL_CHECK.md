# Flight model check: the numbers the 3-D pictures print vs published data

The detailed picture's forces and flight state are the JSBSim flight
model's own values at each frame. This page checks those models against
published performance figures, so a reader knows how far to trust them.
Reproduce with `python scripts/flight_model_check.py` (JSBSim 1.2.4,
2026-11-20).

| Aircraft | Quantity | Flight model | Published | Difference |
|---|---|---|---|---|
| Cessna 172P | stall, flaps up, power off, 2400 lb, sea level | **53.2 kt** (CLmax 1.44 at 16.1 deg) | **51 KCAS** (172P spec); 50-53 KCAS aft-forward CG (C172N POH) | +4 % (inside the CG band) |
| Cessna 172P | top level speed, sea level | **130-135 kt** (trims at 130 kt, 84 % throttle; no trim from 135 kt; model at 1880 lb) | **123 kt** | about +6-9 % (lighter test weight) |
| A-4 (A-4E) | top level speed, sea level | **~410 kt** (throttle 1.0 at 410 kt; no trim from 415 kt) | **585 kt** (673 mph) | **-30 %** |
| A-4 (A-4E) | stall, clean, 8295 kg | 144 kt (CLmax 1.00 at 14.9 deg) | not found in a citable source | -- |

## What it means

* **Cessna 172P: trustworthy.** Stall speed within 4 % and top speed
  within ~6-9 % of the handbook. The forces drawn for the Cessna are
  realistic.
* **A-4: the drag is too high.** At its top speed the model's drag
  coefficient is 0.059, about 2.5-3x what a clean A-4 should have, while
  its thrust (~8,600 lbf at 410 kt) is reasonable for a J52-P-8A (about
  9,300 lbf static). So at high speed the model needs far more thrust than
  the real aircraft, and the DRAG and THRUST the picture shows at cruise
  are both higher than a real A-4's would be. The model's own header says
  its aerodynamics come from Aeromatic (estimated from public data), not
  measured data. Lift, weight and load factor are not affected by this.
* **Not changed here.** Correcting the A-4's drag would change how every
  A-4 flight in the simulator behaves (speeds, climb, trimmed attitudes)
  and the validated tests built on them, so it is left as a recommendation:
  scale the A-4's zero-lift drag (CD0) so the model trims level at about
  585 kt at sea level on full throttle, then re-run the A-4 test scenarios.

## Sources

* Cessna 172P stall 51 KCAS, max 123 kt at sea level: https://172guide.com/models/172P-81.htm, https://172guide.com/models/172P-85.htm
* C172N POH stall band by CG (50-53 KCAS at 2,300 lb): https://aopa.org/news-and-media/all-news/2020/march/flight-training-magazine/aerodynamics-stall-speed
* A-4E maximum speed 673 mph at sea level: https://www.history.navy.mil/content/history/museums/nnam/explore/collections/aircraft/a/a-4-skyhawk.html
