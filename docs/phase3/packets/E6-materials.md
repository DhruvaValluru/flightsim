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
