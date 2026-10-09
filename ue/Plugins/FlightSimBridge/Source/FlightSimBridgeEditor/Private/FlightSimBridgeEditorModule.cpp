#include "Modules/ModuleManager.h"

// W5: the editor module holds no state; its functions are the static
// UFlightSimLandscapeImporter library scripts/ue_build_scene.py calls.
IMPLEMENT_MODULE(FDefaultModuleImpl, FlightSimBridgeEditor);
