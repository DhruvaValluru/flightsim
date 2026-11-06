Cause: in the code, not the machine. No earlier green to diff (repro: E6-repro.md).

E6, fresh clone of 0c68db3e, launcher step 4/7 materials, commandlet exit 3.
Steps 1 to 3 passed; the engine build succeeded in 68 s.

`Assertion failed: CurrentApplication.IsValid()`, SlateApplication.h line 321,
after the first texture import (T_RolesValley). Stack: Python ImportAssetTasks,
AssetTools, InterchangeEngine, AssetTools, ContentBrowser, Slate.

Interchange's completion callback syncs the Content Browser. The CVar
`Interchange.FeatureFlags.Import.SyncToBrowser` overrides the task's setting and
defaults on (AssetTools.cpp 3872, InterchangeEditorModule.cpp 25). A commandlet
has no Slate application. An existing checkout never imports here because its
materials already exist, so only a fresh download reached it.

Fix: the CVar off in ue/Config/DefaultEngine.ini. It also covers
ue_build_scene.py, which imports the same way. On the failed clone the commandlet
then exits 0 with 49 assets (runs/p3/G/E6-materials-try1.log).

T_RolesValley, checked after: exported from the fresh clone, all 16 texels read
(255, 0, 0, 0), equal to the source. The engine fill touches only
(255, 255, 255, 0). The TextureFactory branch never ran, because this engine has
no fill_png_zero_alpha, and is removed (90d7f1f7).

Also found: the launcher's MATERIAL-FAILED match could never fire, because
Python prints did not reach stdout. Fixed with -FullStdOutLogOutput. A forced
materials rerun showed all 36 MATERIAL- lines in stdout (runs/p3/G/E6-tip2-stdout.log).
A real failed material has not been run through it.

## E6 is not closed

The launcher checks passed from a shell: fresh clone READY on cead67ba, second
launch up to date, a broken stamp reran only materials, hidden ffmpeg stopped at
preflight (runs/p3/G/E6-*-stdout.log). Limits on that:

- 90d7f1f7 was proved by updating the clone and forcing a materials rerun, not by
  a new clone from scratch. The from-scratch run is cead67ba.
- Run from a shell, not by double-clicking Launch FlightSim.cmd. Browser opening
  and "no prompt" were not observed. The owner's double-click is open.
- host.smart_app_control is not exercised: Smart App Control is off here.
- Engine, MSVC and ffmpeg were already installed on this laptop.
- A launcher update takes effect on the next launch: step 1 pulls, but the
  running PowerShell keeps the old script.

## Shell open by automation, 2026-11-05

Not the owner's double-click. `Launch FlightSim.cmd` in a new clone,
C:\Users\kanth\p3-open at ff491087, opened with Shell.Application InvokeVerb open,
the path a double-click takes, with Explorer's environment.

- launch.log ended READY after about 565 s, all seven steps, no failure.
- Browser: indirect but strong. New chrome processes started at 22:30:49, the
  second of READY, and recorded frames show the row of flightsim tabs.
- Prompt: none seen. No consent or credential process existed. A Windows Settings
  window was open, started the day before. Nobody watched the screen.
- Each launch leaves another server window and another browser tab open.

This narrows the double-click limit above and does not close it.

## Server windows, 2026-11-05, at 728dc15d

Launched from the installed folder, counting powershell windows hosting the server.
Launch 1 still ran the old script; it pulled the fix. Launches 2 and 3 logged
`closing its window` and the count held at 2, one of them a window from before
the fix (started 22:42). With that one closed, launches 4 and 5: count 1 each,
`closing its window` logged.

Known flaw, not fixed: each launch opens one more browser tab.

## Owner's double-click, 2026-11-06

The owner double-clicked `Launch FlightSim.cmd` in a fresh clone, `C:\Users\kanth\p3-final`, and reported: `logs\launch.log` ends with step 7/7 server, server started, READY; browser opened; no prompt. Both bakes ran from missing .r16 files and the p51d imported. The browser asked for /runs/49c73b3c38d8 and got a 404: a run id this laptop's browser remembered, per the owner, not a fresh-machine behaviour. These are the owner's words; the log stayed on the laptop.
