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

Not proven: T_RolesValley goes through Interchange although
ue_create_materials.py sets a TextureFactory to keep its zero-alpha texels, so
those texels may not be as written.
