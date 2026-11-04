// The card's collision raster as the ground JSBSim sees (Phase 3 decision 12).
//
// The vendored plugin answers JSBSim's ground queries with a line trace
// against whatever the world has loaded (UEGroundCallback ->
// UJSBSimMovementComponent::GetAGLevel: WorldStatic, WorldDynamic, Pawn,
// Visibility). A -nullrhi solve pass and a render pass stream the Cesium
// tiles differently, so the same card recorded different agl_m in the two
// passes while every other column stayed bit-identical (web run
// 4be692c3e9fe: 38 of 220 samples, max 27.6 m). When the card names a
// collision raster that raster IS the physics ground (the manifest's
// "physics ground is the heightfield raster"), so the callback made here
// answers from it -- the same bilinear, edge-clamped lookup
// VerifyTrimmedCondition's AGL check reads (FFlightSimHeightfield::ElevationAt)
// -- and every pass of the card sees one surface. A card without a raster
// keeps the plugin's trace (the query-only slab).
//
// The JSBSim headers stay inside FlightSimGroundCallback.cpp: this header
// only forward-declares the callback type the plugin's factory hook
// (GroundCallbackFactory, LOCAL PATCH 7) takes.

#pragma once

#include "CoreMinimal.h"
#include "Templates/Function.h"

namespace JSBSim
{
	class FGGroundCallback;
}
struct FFlightSimHeightfield;
class AGeoReferencingSystem;

// A factory for UJSBSimMovementComponent::GroundCallbackFactory: each call
// makes a fresh callback (JSBSim owns it) that answers height above ground,
// contact point and normal from a copy of `Terrain`, sampled in the card's
// projected CRS through `GeoReferencing`. The callback outlives the scenario
// world: the plugin tears JSBSim down in BeginDestroy at engine exit, after
// the commandlet's stack-local world object is gone, so the callback owns
// its raster and holds the georeferencing actor weakly (a dead actor makes
// it answer the bare ellipsoid instead of reading freed memory).
TFunction<JSBSim::FGGroundCallback*()> MakeFlightSimRasterGroundFactory(
	const FFlightSimHeightfield& Terrain, AGeoReferencingSystem* GeoReferencing);
