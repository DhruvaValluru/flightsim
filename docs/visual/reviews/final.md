# Final sweep review (round 44, code 7c017618)

Frames: vis-windows ef44ace6, docs/visual/final/ (round44_contact.jpg,
compare_head5_vs_head44.png, chase_clip.mp4, verify_round44.txt).
Reviewed by eye on the Mac (p3-mac); nothing rendered here.

## Result
14 of 15 rendered; #14 refuses by design (hurricane).

Head shots, round 5 vs round 44: **4 better, 0 same, 0 worse.** The J-11 is
no longer black (aircraft-look materials off by default), the rain-forest
shot is readable instead of crushed, and the cockpit clouds lost their banding.

## Scenes by eye
| # | verdict | note |
|---|---|---|
| 01 | good | golden hour reads cool in the shadows |
| 02 | **bad** | super_bright still blue/violet over the whole frame |
| 03 | good | New York wide |
| 04 | good | |
| 05 | good | backlit haze |
| 06 | ok | dark blue rain, aircraft clean |
| 07 | ok | flat grey heavy rain |
| 08 | good | Fuji sunrise |
| 09 | good | thunderstorm, clean 747 |
| 10 | **bad** | tornado green, veil on or off (funnel 25/35/25 on, 29/44/35 off); aircraft tiny |
| 11 | good | Matterhorn, A-4 trims at the new 270 kt default |
| 12 | **bad** | cockpit ~75 % black: regression |
| 13 | **bad** | straight light lines on the sea, still unexplained |
| 15 | ok | storm-dark 747, no ghosts; dark blotches on the deck at left |

## Verify (this is the honest count)
**0 of 14 runs pass verify.** Every run fails look.beauty_not_label_aligned.
Extra failures: #01/#02 annotation.component_box (the store_sta2 offset),
#10/#13 annotation.tight_box_null, #12 annotation.mask_offset and depth_range
(same scene as the black cockpit, likely one cause).
Ghost scores were reported below 0.6 (max #10 0.57), but verify_round44.txt
prints `ghost None` on every line, so the score is not reaching the verify
summary.

## Open for the PR
1. look.beauty_not_label_aligned on every run: either the check or the beauty
   frame is wrong; until it is settled no frame is certified training data.
2. #12 cockpit black plus mask/depth failures.
3. #10 green is not the rain veil; source still unknown.
4. #02 blue cast; #13 sea lines; #01/#02 store_sta2 box; gear down in cruise.
