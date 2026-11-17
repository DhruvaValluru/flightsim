// The world's beauty look (FlightSimClouds.h). BEAUTY ONLY: the render
// commandlet constructs and calls this only under -quality=beauty.
//
// UNCOMPILED when written (2026-11-09, a Mac whose Xcode 27.2 is above UE
// 5.7's 26.9 cap, no Cesium): every engine symbol below was read in the UE
// 5.7.4 headers and is listed in scripts/check_bridge_api.sh ("world lane");
// the pure block is compiled and checked against core/scene/world_beauty.py by
// tests/test_world_beauty.py. Names in this file are file-unique (NEXT.md
// gotcha 3: unity builds merge anonymous namespaces).

#include "FlightSimClouds.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/ExponentialHeightFogComponent.h"
#include "Components/SkyAtmosphereComponent.h"
#include "Components/SkyLightComponent.h"
#include "Components/VolumetricCloudComponent.h"
#include "Dom/JsonValue.h"
#include "Engine/DirectionalLight.h"
#include "Engine/TextureCube.h"
#include "Engine/World.h"
#include "FlightSimGoogleTiles.h"
#include "FlightSimVisualScene.h"
#include "FlightSimWeather.h"
#include "GameFramework/Actor.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformMisc.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Materials/MaterialParameterCollection.h"
#include "Materials/MaterialParameterCollectionInstance.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "ProceduralMeshComponent.h"   // the distant cloud sheet (visual round 5, L3)
#include "RHIGlobals.h"
#include "RHI.h"   // GMaxRHIFeatureLevel (CloudConstrainedGpu)
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/MetaData.h"   // sky step 1: the cloud material's FlightSimGraphGeneration tag, recorded
#include "UObject/Package.h"
#include "UObject/UObjectIterator.h"

#include <cmath>
#include <cstdint>
#include <cstring>

DEFINE_LOG_CATEGORY_STATIC(LogFlightSimWorldBeauty, Log, All);

// The tables and laws, dependency-free C++17 so tests/test_world_beauty.py can
// compile this block alone and compare it with core/scene/world_beauty.py
// number for number. EVERY look value in it is UNCALIBRATED: set by probe
// render on the render machine (docs/visual/PROBE_LOG.md ## world).
// FLIGHTSIM-WORLD-PURE-BEGIN
namespace FlightSimWorldPure
{
	enum : int
	{
		PresetClear = 0,
		PresetHazy = 1,
		PresetOvercast = 2,
		PresetRain = 3,
		PresetStorm = 4,
		PresetCount = 5
	};
	enum : int
	{
		CloudCumulus = 0,
		CloudStratocumulus = 1,
		CloudOvercast = 2,
		CloudNimbostratus = 3,
		CloudAltocumulus = 4,   // sky step 5: appended, so every earlier index and overrides file stands
		CloudCount = 5
	};

	inline const char* PresetName(int Preset)
	{
		static const char* const Names[PresetCount] = {"clear", "hazy", "overcast", "rain", "storm"};
		return Preset >= 0 && Preset < PresetCount ? Names[Preset] : "clear";
	}

	inline const char* CloudName(int Cloud)
	{
		static const char* const Names[CloudCount] = {"cumulus", "stratocumulus", "overcast", "nimbostratus",
		                                              "altocumulus"};
		return Cloud >= 0 && Cloud < CloudCount ? Names[Cloud] : "cumulus";
	}

	// core/scene/world_beauty.py ATMOSPHERE_FIELDS, in order.
	// Fix pass 2026-11-09: the ground albedo (GroundAlbedoSrgb: the card's
	// surface and wetness) and the tiles' dehaze and saturation (tileset
	// constants) left the per-weather rows.
	// Sky step 4 (the owner's X-Plane-12 brief, 2026-11-15): three horizon-haze
	// fields appended (13 -> 16, the existing indices hold): the height fog's
	// vertical profile (fog_scale_height_km: the 1/e scale height the fog's haze
	// decays with above the scene's fog height; 0 keeps the scene's near-uniform
	// profile), its start distance and its max opacity (the scene's own values
	// unless a row or the overrides file says otherwise). FogHeightFalloffFor and
	// the rebase laws below are the profile's arithmetic.
	constexpr int AtmosphereFieldCount = 16;
	inline const char* AtmosphereFieldName(int Field)
	{
		static const char* const Names[AtmosphereFieldCount] = {
			"mie_scale_height_km", "mie_anisotropy", "mie_share", "mie_cap_per_km",
			"aerial_perspective_scale", "vfog_distance_m", "vfog_scattering_distribution",
			"vfog_extinction_scale", "cloud_bottom_occlusion", "rain_readability_gain", "wetness_floor",
			"tiles_detail_strength", "lightning_sky_gain",
			"fog_scale_height_km", "fog_start_distance_m", "fog_max_opacity"};
		return Field >= 0 && Field < AtmosphereFieldCount ? Names[Field] : "";
	}
	enum : int
	{
		AtmMieScaleHeightKm = 0, AtmMieAnisotropy, AtmMieShare, AtmMieCapPerKm, AtmAerialPerspectiveScale,
		AtmVFogDistanceM, AtmVFogScatteringDistribution, AtmVFogExtinctionScale, AtmCloudBottomOcclusion,
		AtmRainReadabilityGain, AtmWetnessFloor, AtmTilesDetailStrength, AtmLightningSkyGain,
		AtmFogScaleHeightKm, AtmFogStartDistanceM, AtmFogMaxOpacity
	};

	// UNCALIBRATED: set by probe render on the render machine (every number).
	// Sky step 4: the clear and hazy rows give the fog the Mie layer's own scale
	// height (the Koschmieder split put one aerosol in two renderers; this gives
	// both the same vertical profile); the weather rows keep the scene's uniform
	// fog (their haze is the column under a deck, which RainHazeFog shapes).
	inline double AtmosphereDefault(int Preset, int Field)
	{
		static const double Rows[PresetCount][AtmosphereFieldCount] = {
			// clear
			{1.2, 0.80, 0.6, 0.25, 1.0, 8000.0, 0.75, 1.0, 0.5, 1.0, 0.0, 0.12, 0.0, 1.2, 1500.0, 0.92},
			// hazy
			{1.6, 0.76, 0.7, 0.6, 1.0, 8000.0, 0.7, 1.0, 0.5, 1.0, 0.0, 0.12, 0.0, 1.6, 1500.0, 0.92},
			// overcast
			{1.4, 0.70, 0.4, 0.6, 1.0, 6000.0, 0.4, 1.0, 0.75, 1.0, 0.0, 0.12, 0.0, 0.0, 1500.0, 0.92},
			// rain (vfog_extinction_scale: world_beauty.WET_VFOG_EXTINCTION_SCALE, visual round 3)
			{1.0, 0.65, 0.3, 0.8, 1.0, 4000.0, 0.3, 0.48, 0.85, 1.5, 0.6, 0.12, 0.0, 0.0, 1500.0, 0.92},
			// storm
			{1.8, 0.65, 0.3, 0.8, 1.0, 4000.0, 0.3, 0.48, 0.9, 1.5, 0.85, 0.12, 3.0, 0.0, 1500.0, 0.92},
		};
		return Preset >= 0 && Preset < PresetCount && Field >= 0 && Field < AtmosphereFieldCount
			? Rows[Preset][Field] : 0.0;
	}

	// core/scene/world_beauty.py CLOUD_FIELDS, in order.
	constexpr int CloudFieldCount = 8;
	inline const char* CloudFieldName(int Field)
	{
		static const char* const Names[CloudFieldCount] = {
			"extinction_per_m", "shape_scale_km", "detail_scale_km", "detail_erosion",
			"bottom_softness", "top_rounding", "coverage_contrast", "default_cover"};
		return Field >= 0 && Field < CloudFieldCount ? Names[Field] : "";
	}
	enum : int
	{
		CldExtinctionPerM = 0, CldShapeScaleKm, CldDetailScaleKm, CldDetailErosion, CldBottomSoftness,
		CldTopRounding, CldCoverageContrast, CldDefaultCover
	};

	// UNCALIBRATED: set by probe render on the render machine (every number).
	inline double CloudDefault(int Cloud, int Field)
	{
		static const double Rows[CloudCount][CloudFieldCount] = {
			{0.05, 2.5, 0.35, 0.35, 0.08, 0.75, 0.9, 0.35},   // cumulus (round 10: domes from a quarter up, a wider soft edge)
			{0.04, 4.0, 0.5, 0.25, 0.15, 0.3, 1.3, 0.6},      // stratocumulus
			{0.03, 8.0, 0.8, 0.15, 0.2, 0.15, 1.0, 0.95},     // overcast
			{0.045, 9.0, 0.6, 0.3, 0.1, 0.4, 0.8, 0.98},      // nimbostratus
			{0.03, 1.2, 0.12, 0.4, 0.15, 0.5, 1.1, 0.5},      // altocumulus (sky step 5: the plan's mid-level sheet; never rendered)
		};
		return Cloud >= 0 && Cloud < CloudCount && Field >= 0 && Field < CloudFieldCount
			? Rows[Cloud][Field] : 0.0;
	}

	// Selection thresholds and stated constants (world_beauty.py, same names
	// in SCREAMING_SNAKE). UNCALIBRATED: set by probe render on the render machine.
	constexpr double HazyVisibilityKm = 15.0;
	constexpr double OvercastCover = 0.75;
	constexpr double CloudOvercastCover = 0.85;
	constexpr double StratocumulusMaxThicknessM = 900.0;
	constexpr double StratocumulusMinCover = 0.5;
	// Round 7 (lane E, world_beauty.FAIR_CLOUD_SHADOW_PRESETS / _MIN_COVER,
	// fair_cloud_shadows): a clear or hazy world whose drawn layer covers at
	// least this casts its cumulus shadows on the ground (round 4's clear
	// scenes drew clouds over unshadowed ground).
	constexpr double FairCloudShadowMinCover = 0.1;
	inline bool FairCloudShadows(int Preset, double Cover)
	{
		return (Preset == PresetClear || Preset == PresetHazy) && Cover >= FairCloudShadowMinCover;
	}
	// Visual round 6: the deck shadows the beam (world_beauty.DECK_SHADOW_PRESETS,
	// DECK_SHADOW_MIN_COVER, deck_shadows_beam): a deck preset with a drawn layer
	// of at least this cover turns the sun's cloud shadows on in beauty.
	constexpr double DeckShadowMinCover = 0.5;
	inline bool DeckShadowsBeam(int Preset, double Cover)
	{
		return (Preset == PresetStorm || Preset == PresetRain || Preset == PresetOvercast)
			&& Cover >= DeckShadowMinCover;
	}
	constexpr double FairCover = 0.35;
	constexpr double FairBaseM = 1500.0;
	constexpr double FairTopM = 2700.0;
	// Round 95 (r93/r94 #13, a 747 at 10 km over the ocean at noon): the sky plan puts
	// its default layer >= 1 km above the flight (core/sky/plan.py, so the camera stays
	// clear), which drew cumulus at 11-14 km, above the airliner; the sky light's cloud
	// AO under that slab darkened the whole sea (raw blue 131 -> 95 once the tiers
	// thickened it). Cumulus do not form there: a DEFAULT (unstated) cumulus layer
	// whose base is above CumulusMaxBaseM is drawn as the fair-weather slab instead,
	// below the flight. A card's or the fair layer's stated heights are kept. BEAUTY
	// ONLY. world_beauty.cumulus_layer_lowered is the twin. UNCALIBRATED.
	constexpr double CumulusMaxBaseM = 4000.0;
	inline bool CumulusLayerLowered(bool bCumulus, bool bStated, double BaseM)
	{
		return bCumulus && !bStated && BaseM > CumulusMaxBaseM;
	}
	// Sky step 2 (the owner's X-Plane-12 brief, 2026-11-14): the sky plan's cloud
	// fields (sky.json "clouds": cloud_type, coverage, density, detail, seed; step 5
	// writes them, FFlightSimSkyPlan::Load reads them) reach the BEAUTY host only.
	// The plan's type words (world_beauty.PLAN_CLOUD_TYPES, same order) and the
	// volumetric shape each draws (world_beauty.PLAN_CLOUD_SHAPES): clear and cirrus
	// draw NO volumetric layer (the layer is hidden; step 6 draws cirrus as a high
	// sheet); altocumulus draws its own row since sky step 5 (it drew stratocumulus
	// in step 2; recorded as cloud_type_applied). UNCALIBRATED: which row a word
	// draws is a look choice.
	constexpr int PlanCloudTypeCount = 7;
	constexpr int PlanCloudNoLayer = -1;
	constexpr int PlanCloudUnknown = -2;
	inline const char* PlanCloudTypeName(int Type)
	{
		static const char* const Names[PlanCloudTypeCount] = {
			"clear", "cumulus", "stratocumulus", "altocumulus", "cirrus", "overcast", "nimbostratus"};
		return Type >= 0 && Type < PlanCloudTypeCount ? Names[Type] : "";
	}
	// The index of a plan type word; PlanCloudUnknown for anything else (an
	// empty or unknown word is drawn as "not stated" and recorded).
	inline int PlanCloudTypeIndex(const char* Word)
	{
		for (int I = 0; Word != nullptr && I < PlanCloudTypeCount; ++I)
		{
			if (std::strcmp(Word, PlanCloudTypeName(I)) == 0)
			{
				return I;
			}
		}
		return PlanCloudUnknown;
	}
	inline int CloudShapeForPlanType(int Type)
	{
		switch (Type)
		{
		case 0: return PlanCloudNoLayer;        // clear: nothing
		case 1: return CloudCumulus;
		case 2: return CloudStratocumulus;
		case 3: return CloudAltocumulus;        // altocumulus: its own row (sky step 5)
		case 4: return PlanCloudNoLayer;        // cirrus: step 6's sheet, no volumetric layer
		case 5: return CloudOvercast;
		case 6: return CloudNimbostratus;
		default: return PlanCloudUnknown;
		}
	}
	// Where a layer's cover and shape came from, by precedence (world_beauty.layer_source):
	// the -cloud-type= switch (the owner's probe) > the card's look.clouds[0] or the
	// stated fair layer (dataset truth, never overridden by data) > the sky plan's
	// clouds block (ERA5 or a recorded default) > the shape's default. Under the rain
	// and storm presets the deck stands (SelectCloud's nimbostratus): the plan's type
	// never thins a rain world to fair cumulus; the switch still can.
	enum : int
	{
		LayerSourceSwitch = 0, LayerSourceCard = 1, LayerSourcePlan = 2, LayerSourceDefault = 3,
		LayerSourceCount = 4
	};
	inline const char* LayerSourceName(int Source)
	{
		static const char* const Names[LayerSourceCount] = {"switch", "card", "plan", "shape default"};
		return Source >= 0 && Source < LayerSourceCount ? Names[Source] : "shape default";
	}
	// SwitchShape / PlanShape: CloudShapeForPlanType of the switch word / the plan's
	// type, PlanCloudUnknown when not given. Cover and Shape hold LayerCoverAndShape's
	// result on entry and are replaced where the switch or the plan decides; a
	// PlanCloudNoLayer shape is a hidden layer (Cover 0).
	inline int LayerSource(int SwitchShape, double CardCover, bool bFair, int PlanShape, double PlanCover,
	                       int Preset, const double* CloudTable, double* Cover, int* Shape)
	{
		const bool bCardStated = CardCover >= 0.0 || bFair;
		if (SwitchShape != PlanCloudUnknown)
		{
			*Shape = SwitchShape;
			if (SwitchShape == PlanCloudNoLayer)
			{
				*Cover = 0.0;
			}
			else if (!bCardStated)
			{
				*Cover = CloudTable != nullptr ? CloudTable[SwitchShape * CloudFieldCount + CldDefaultCover]
				                               : CloudDefault(SwitchShape, CldDefaultCover);
			}
			return LayerSourceSwitch;
		}
		if (bCardStated)
		{
			return LayerSourceCard;
		}
		if (PlanShape != PlanCloudUnknown && Preset != PresetRain && Preset != PresetStorm)
		{
			*Shape = PlanShape;
			if (PlanShape == PlanCloudNoLayer)
			{
				*Cover = 0.0;
			}
			else if (PlanCover >= 0.0)
			{
				*Cover = PlanCover > 1.0 ? 1.0 : PlanCover;
			}
			else
			{
				*Cover = CloudTable != nullptr ? CloudTable[PlanShape * CloudFieldCount + CldDefaultCover]
				                               : CloudDefault(PlanShape, CldDefaultCover);
			}
			return LayerSourcePlan;
		}
		return LayerSourceDefault;
	}
	// The plan's density and detail are multipliers of the row (1 = the row; one
	// source of truth per type, the CLOUDS row): density clamped to
	// PlanDensityMin..Max on the row's extinction, detail on the row's erosion with
	// the product saturated (world_beauty.plan_density_scale / plan_detail_erosion).
	// UNCALIBRATED.
	constexpr double PlanDensityMin = 0.5;
	constexpr double PlanDensityMax = 1.5;
	inline double PlanDensityScale(double Density)
	{
		return Density < PlanDensityMin ? PlanDensityMin : (Density > PlanDensityMax ? PlanDensityMax : Density);
	}
	inline double PlanDetailErosion(double RowErosion, double Detail)
	{
		const double Scaled = RowErosion * (Detail < 0.0 ? 0.0 : Detail);
		return Scaled > 1.0 ? 1.0 : Scaled;
	}
	// Round 3: a rain world's layer when the card states no cover (broken, not
	// nimbostratus's 0.98 sheet: round 1's #06 showed no ground).
	constexpr double RainDefaultCover = 0.72;
	constexpr double CloudSeedSpanKm = 1000.0;
	constexpr double CloudExtinctionScaleDefault = 1.0;
	constexpr double OcclusionFlagTransmittanceDefault = 0.5;

	// -- clouds-sky round 2 (2026-11-09): the march, the default layer, the sky --
	// The first real renders (Intel iGPU, D3D11) banded shot d's clouds: 96 x 2
	// view samples over an 80 km trace (400 m steps through 0.05/m cloud) and
	// 10 UNJITTERED quadratic shadow samples over 15 km (the engine disables
	// the shadow jitter), so a cloud's light came in contours and most of it
	// went unlit. world_beauty.py CLOUD_MARCH and the laws below are the twin.
	// UNCALIBRATED: set by probe render on the render machine (every number).
	// Sky step 3 (the owner's X-Plane-12 brief, 2026-11-15): three tiers. The
	// discrete row is the offline quality (the engine's caps: 768 view and 80
	// shadow samples over a 50 km trace); the constrained row stays ef361bd6's
	// (rounds 5-95 rendered it); the PROBE row is the constrained class's opt-in
	// raise (288 view, 20 shadow samples; UNCALIBRATED), reached only by
	// -cloud-march=probe: one scene, one still, the Windows TDR (887a0006) is the
	// pass or fail. CloudMarchFor picks the row from the switch word; CloudCvar
	// below is each tier's renderer cvar table.
	enum : int
	{
		MarchDiscrete = 0,
		MarchIntegrated = 1,
		MarchProbe = 2,
		MarchCount = 3
	};
	inline const char* MarchName(int March)
	{
		static const char* const Names[MarchCount] = {"discrete", "integrated", "probe"};
		return March >= 0 && March < MarchCount ? Names[March] : "discrete";
	}
	constexpr int MarchFieldCount = 3;
	inline const char* MarchFieldName(int Field)
	{
		static const char* const Names[MarchFieldCount] = {
			"view_sample_count_scale", "shadow_sample_count_scale", "tracing_max_distance_km"};
		return Field >= 0 && Field < MarchFieldCount ? Names[Field] : "";
	}
	enum : int
	{
		MarchViewScale = 0, MarchShadowScale, MarchTracingMaxKm
	};
	// The engine's samples are 96 x view scale (cap r.VolumetricCloud.ViewRaySampleMaxCount,
	// 768) and 10 x shadow scale (cap r.VolumetricCloud.Shadow.ViewRaySampleMaxCount, 80);
	// every row stays under the caps. The CONSTRAINED row (an integrated GPU, or any
	// adapter below SM6, e.g. D3D11 SM5) is ef361bd6's march exactly: 192 view and 10
	// shadow samples, an 80 km trace and a 15 km shadow march, with no thinning of the
	// default layer, no multiple-scattering change and no fog on every pixel. Round 1
	// (2026-11-09): every beauty run on the render laptop's Intel iGPU (D3D11 SM5)
	// deadlocked in the sky light capture, and git bisect named the commit that
	// brought this lane's round-2 settings (a8c964fc); ef361bd6's code rendered.
	inline double CloudMarch(int March, int Field)
	{
		static const double Rows[MarchCount][MarchFieldCount] = {
			{8.0, 8.0, 50.0},   // discrete: 768 view, 80 shadow samples, the caps (sky step 3; round 2 drew 6, 6)
			{2.0, 1.0, 80.0},   // constrained: 192 view, 10 shadow samples (ef361bd6)
			{3.0, 2.0, 80.0},   // probe: 288 view, 20 shadow samples (sky step 3, -cloud-march=probe only)
		};
		return March >= 0 && March < MarchCount && Field >= 0 && Field < MarchFieldCount
			? Rows[March][Field] : 0.0;
	}
	// Sky step 3: -cloud-march=auto|constrained|discrete|probe. auto is the GPU class
	// (CloudConstrainedGpu, as before this step); a named word is the owner's
	// measurement on any GPU. An unknown word is -1 (Build refuses it by name).
	constexpr int MarchSwitchWordCount = 4;
	inline const char* MarchSwitchWord(int I)
	{
		static const char* const Words[MarchSwitchWordCount] = {"auto", "constrained", "discrete", "probe"};
		return I >= 0 && I < MarchSwitchWordCount ? Words[I] : "";
	}
	inline int CloudMarchFor(const char* Word, bool Constrained)
	{
		if (Word == nullptr || std::strcmp(Word, "auto") == 0)
		{
			return Constrained ? MarchIntegrated : MarchDiscrete;
		}
		if (std::strcmp(Word, "constrained") == 0) { return MarchIntegrated; }
		if (std::strcmp(Word, "discrete") == 0) { return MarchDiscrete; }
		if (std::strcmp(Word, "probe") == 0) { return MarchProbe; }
		return -1;
	}
	// Sky step 5: the march word in force and where it came from
	// (world_beauty.cloud_march_word / MARCH_WORD_SOURCES): a -cloud-march= word
	// other than auto is the owner's measurement and wins; else the sky plan's
	// "march_tier" when it is a known word (the plan writes "auto", so this is a
	// no-op by construction today); else auto, the GPU class. An unknown plan word
	// is ignored, never a refusal: clouds are VISUAL ONLY. Returns the source index
	// and writes the word (one of MarchSwitchWord's) to *Word.
	enum : int
	{
		MarchWordSwitch = 0, MarchWordPlan = 1, MarchWordDefault = 2, MarchWordSourceCount = 3
	};
	inline const char* MarchWordSourceName(int Source)
	{
		static const char* const Names[MarchWordSourceCount] = {"switch", "plan", "default auto"};
		return Source >= 0 && Source < MarchWordSourceCount ? Names[Source] : "default auto";
	}
	inline int CloudMarchWordInForce(const char* Switch, const char* PlanTier, const char** Word)
	{
		const char* SwitchWord = (Switch == nullptr || Switch[0] == '\0') ? "auto" : Switch;
		if (std::strcmp(SwitchWord, "auto") != 0)
		{
			*Word = SwitchWord;
			return MarchWordSwitch;
		}
		if (PlanTier != nullptr && PlanTier[0] != '\0' && std::strcmp(PlanTier, "auto") != 0
		    && CloudMarchFor(PlanTier, false) >= 0)
		{
			*Word = PlanTier;   // a plan "auto" chooses nothing: it is the default below
			return MarchWordPlan;
		}
		*Word = "auto";
		return MarchWordDefault;
	}
	// Sky step 3: the renderer cvars each tier sets (ApplyClouds SetWorldCvar, saved
	// once and put back by RestoreCvars, every value recorded before and after in
	// look_applied.world_beauty.clouds.march.cvars). world_beauty.py CLOUD_CVARS,
	// CLOUD_CVAR_NAMES and ENGINE_CLOUD_CVAR_DEFAULTS are the twin.
	// The CONSTRAINED row is exactly what the render laptop draws with today, so
	// setting it changes nothing there (the pinned r87 history stands): the
	// engine's registration default (UE 5.7 VolumetricCloudRendering.cpp,
	// SkyAtmosphereRendering.cpp) where the Cinematic scalability group is silent,
	// and the group's value where it speaks (BaseScalability.ini
	// [EffectsQuality@Cine], applied by the render path after this lane at
	// scalability priority, which cannot lower a code-priority set: AP
	// DepthResolution 32, TransmittanceLUT.SampleCount 30, MultiScatteringLUT.
	// SampleCount 20; the design doc's "engine defaults" 16/10/15 would have
	// LOWERED the laptop's sky). The DISCRETE row is the offline quality (no
	// discrete GPU in the project: set for one, never rendered). The PROBE row is
	// the constrained row with r.VolumetricCloud.DistanceToSampleMaxCount 8 km:
	// the engine spreads SampleCountMax over that distance (samples = max x
	// saturate(in-layer path / distance)), so a short in-layer path gets up to
	// twice the samples. That distance ALSO governs the sky-light capture's step
	// count: UE 5.7 VolumetricCloudRendering.cpp sets
	// CloudGlobalShaderParams.InvDistanceToSampleCountMax once, from this cvar,
	// for every trace, and its bIsReflectionRendering block re-derives only
	// SampleCountMax and ShadowSampleCountMax (from ReflectionViewSampleCountScale
	// and the commandlet's r.VolumetricCloud.ReflectionRaySampleMaxCount caps), so
	// the probe lengthens that capture's march too (up to 15/8 x per short
	// in-layer path, under those caps) in the submission that hung r87
	// (887a0006); the Windows TDR is its pass or fail (pinned by
	// test_sky_step3_cvars.py and check_bridge_api.sh against the engine source).
	// Cost per submission rises with the probe's march row as well, which is why
	// it is opt-in. The sky's SampleCountMax, the AP per-slice count,
	// FastSkyLUT, FastApplyOnOpaque, MultiScatteringLUT.HighQuality, LUT32,
	// r.VolumetricCloud, HighQualityAerialPerspective and VolumetricRenderTarget.
	// Mode are the render path's (one owner; never set here). UNCALIBRATED.
	constexpr int CloudCvarFieldCount = 13;
	enum : int
	{
		CvarViewRayMax = 0, CvarShadowRayMax, CvarDistanceToSampleMaxKm, CvarSampleMinCount,
		CvarShadowMapRayMax, CvarShadowMapMaxRes, CvarSkyAoTraceSamples, CvarApLutDepthKm,
		CvarApLutDepthRes, CvarApLutWidth, CvarTransmittanceLutSamples, CvarMultiScatterLutSamples,
		CvarSkyDistanceToSampleMaxKm
	};
	inline const char* CloudCvarFieldName(int Field)
	{
		static const char* const Names[CloudCvarFieldCount] = {
			"view_ray_sample_max", "shadow_ray_sample_max", "distance_to_sample_max_km", "sample_min_count",
			"shadowmap_ray_sample_max", "shadowmap_max_resolution", "skyao_trace_samples", "ap_lut_depth_km",
			"ap_lut_depth_resolution", "ap_lut_width", "transmittance_lut_samples", "multiscatter_lut_samples",
			"sky_distance_to_sample_max_km"};
		return Field >= 0 && Field < CloudCvarFieldCount ? Names[Field] : "";
	}
	inline const char* CloudCvarName(int Field)
	{
		static const char* const Names[CloudCvarFieldCount] = {
			"r.VolumetricCloud.ViewRaySampleMaxCount",
			"r.VolumetricCloud.Shadow.ViewRaySampleMaxCount",
			"r.VolumetricCloud.DistanceToSampleMaxCount",
			"r.VolumetricCloud.SampleMinCount",
			"r.VolumetricCloud.ShadowMap.RaySampleMaxCount",
			"r.VolumetricCloud.ShadowMap.MaxResolution",
			"r.VolumetricCloud.SkyAO.TraceSampleCount",
			"r.SkyAtmosphere.AerialPerspectiveLUT.Depth",
			"r.SkyAtmosphere.AerialPerspectiveLUT.DepthResolution",
			"r.SkyAtmosphere.AerialPerspectiveLUT.Width",
			"r.SkyAtmosphere.TransmittanceLUT.SampleCount",
			"r.SkyAtmosphere.MultiScatteringLUT.SampleCount",
			"r.SkyAtmosphere.DistanceToSampleCountMax"};
		return Field >= 0 && Field < CloudCvarFieldCount ? Names[Field] : "";
	}
	inline double CloudCvar(int March, int Field)
	{
		static const double Rows[MarchCount][CloudCvarFieldCount] = {
			{768.0, 80.0, 8.0, 2.0, 256.0, 4096.0, 20.0, 160.0, 64.0, 64.0, 40.0, 30.0, 100.0},   // discrete: offline
			{768.0, 80.0, 15.0, 2.0, 128.0, 2048.0, 10.0, 96.0, 32.0, 32.0, 30.0, 20.0, 150.0},   // constrained: in force today
			{768.0, 80.0, 8.0, 2.0, 128.0, 2048.0, 10.0, 96.0, 32.0, 32.0, 30.0, 20.0, 150.0},    // probe: constrained, 8 km
		};
		return March >= 0 && March < MarchCount && Field >= 0 && Field < CloudCvarFieldCount
			? Rows[March][Field] : 0.0;
	}
	// The shadow march spans the layer it lights (a cell's self-shadow and its
	// neighbour's), not 15 km: kilometres per kilometre of thickness, clamped.
	constexpr double CloudShadowKmPerKm = 1.0;
	constexpr double CloudShadowMinKm = 1.0;
	constexpr double CloudShadowMaxKm = 4.0;
	// The constrained row's shadow march. ef361bd6 marched a fixed 15 km (10 quadratic
	// samples: 150 m then 450 m steps, opaque or empty at cloud extinction, so a cell's
	// light came in contours and its base was lit like its top). Round 7 (lane E): 6 km,
	// the same 10 samples (60 m to 1.1 km steps), so a cell shadows itself and its base
	// darkens; the cheaper weather-field shape (cloud_layers.hlsl) pays for the extra
	// in-layer evaluations. The sample counts and the trace stay ef361bd6's.
	constexpr double CloudShadowConstrainedKm = 6.0;
	inline double CloudShadowTracingKm(double ThicknessM)
	{
		const double Km = (ThicknessM > 0.0 ? ThicknessM : 0.0) / 1000.0 * CloudShadowKmPerKm;
		return Km < CloudShadowMinKm ? CloudShadowMinKm : (Km > CloudShadowMaxKm ? CloudShadowMaxKm : Km);
	}
	// The shadow march for the GPU class: the constrained class a fixed CloudShadowConstrainedKm.
	inline double CloudShadowTracingKmFor(bool bConstrained, double ThicknessM)
	{
		return bConstrained ? CloudShadowConstrainedKm : CloudShadowTracingKm(ThicknessM);
	}
	// Round 52 (round 51's #04, #12, #13: cumulus sliced into flat horizontal tiers):
	// the engine's shadow march is unjittered (VolumetricCloud.usf ShadowJitterNorm =
	// 0.5), and on the constrained row its 10 quadratic segments (60 m to 1.1 km) are
	// each opaque at cloud extinction, so the sun's light is on/off steps at fixed
	// offsets: iso-altitude tiers no capture averages. M_FlightSimCloudLayers treats a
	// shadow sample as its segment's footprint (cloud_layers.hlsl: dithered, softened,
	// erosion noise at its mean past its size); this is the material's ShadowFootprintKm, the
	// quadratic march's segment 2 sqrt(L d) / N per sqrt(d): 2 sqrt(L) / N. 0 with
	// -look-cloud-tiers=off (round 51's march exactly). No sample is added.
	// world_beauty.cloud_shadow_footprint_per_sqrt_km is the twin.
	inline double CloudShadowFootprintPerSqrtKm(double ShadowKm, double ShadowSamples, bool bFilterOn)
	{
		if (!bFilterOn || !(ShadowSamples > 0.0) || !(ShadowKm > 0.0))
		{
			return 0.0;
		}
		return 2.0 * std::sqrt(ShadowKm) / ShadowSamples;
	}
	// Round 52, the second half of the tiers: the weather field is a plane pattern, so
	// a cell's outline was the same at every height (vertical walls). The material's
	// SideBulge (cells) grows the field's warp with height (cloud_layers.hlsl: x
	// sin(BULGE_TURN (h - 0.5)), 0 at mid-layer), so the sides lean and bulge; no hash
	// added. 0 with -look-cloud-tiers=off. UNCALIBRATED (world_beauty.CLOUD_SIDE_BULGE).
	// Round 61: the march fades out over the distant sheet's fade-in (a cross-fade,
	// not the sheet over the march's far walls); 0 with -look-cloud-tiers=off.
	inline double CloudFarFadeKmFor(bool bTiersOn, double SheetFadeKm)
	{
		return bTiersOn && SheetFadeKm > 0.0 ? SheetFadeKm : 0.0;
	}
	constexpr double CloudSideBulge = 0.35;
	inline double CloudSideBulgeFor(bool bTiersOn)
	{
		return bTiersOn ? CloudSideBulge : 0.0;
	}
	// Round 82 (the owner, 2026-11-13: "the clouds dont look that realistic"; r69's
	// #03/#13 cumulus flat and smeared, soft blobby edges, no lit tops or dark bases).
	// -look-cloud-billow=on|off (on by default; off is round 81 exactly), the CUMULUS
	// shape only: a sharper edge (the coverage contrast x CloudBillowContrastGain: the
	// soft edge FBM_SIGMA / contrast wide was over one sigma of the field, a blur at
	// every outline), finer billows that eat more of the edge (the erosion noise at
	// CloudBillowDetailScaleKm, eroding CloudBillowErosion), a thin ragged base under a
	// dense body (the material's HeightDensity, cloud_layers.hlsl) and the sky light
	// occluded harder at the base (SkyLightCloudBottomOcclusion at least
	// CloudBillowBottomOcclusion). No sample and no hash added: the erosion is the same
	// two Worley octaves at a smaller size. world_beauty.cloud_billow_row is the twin.
	// UNCALIBRATED: probe #03, #04, #13.
	constexpr double CloudBillowContrastGain = 2.5;
	constexpr double CloudBillowDetailScaleKm = 0.15;
	constexpr double CloudBillowErosion = 0.5;
	constexpr double CloudBillowHeightDensity = 0.6;
	constexpr double CloudBillowBottomOcclusion = 0.8;
	inline bool CloudBillowApplies(bool bBillowOn, int Shape)
	{
		return bBillowOn && Shape == CloudCumulus;
	}
	// The row in force for a layer: Row as given, or (billow on, cumulus) with the
	// contrast, detail size and erosion replaced. Out is CloudFieldCount long.
	inline void CloudBillowRow(const double* Row, bool bApplies, double* Out)
	{
		for (int F = 0; F < CloudFieldCount; ++F)
		{
			Out[F] = Row[F];
		}
		if (bApplies)
		{
			Out[CldCoverageContrast] = Row[CldCoverageContrast] * CloudBillowContrastGain;
			Out[CldDetailScaleKm] = CloudBillowDetailScaleKm;
			Out[CldDetailErosion] = CloudBillowErosion;
		}
	}
	inline double CloudHeightDensityFor(bool bApplies)
	{
		return bApplies ? CloudBillowHeightDensity : 0.0;
	}
	inline double CloudBottomOcclusionFor(bool bApplies, double RowOcclusion)
	{
		return bApplies && RowOcclusion < CloudBillowBottomOcclusion ? CloudBillowBottomOcclusion : RowOcclusion;
	}
	// Impostor A/B (0deddc6d's cloud cards): -cloud-volumetric-scale=<0..1> (1 by
	// default) multiplies every volumetric layer's drawn cover (the material's
	// Coverage) so a frame can carry the cards without doubled clouds; 0 hides the
	// layer. world_beauty.cloud_volumetric_coverage is the twin. UNMEASURED.
	constexpr double CloudVolumetricScaleDefault = 1.0;
	inline double CloudVolumetricCoverage(double Cover, double Scale)
	{
		return Cover * (Scale < 0.0 ? 0.0 : (Scale > 1.0 ? 1.0 : Scale));
	}
	inline bool CloudVolumetricHidden(double Scale)
	{
		return Scale <= 0.0;
	}
	inline bool CloudVolumetricScaleApplied(double Scale)
	{
		return Scale < CloudVolumetricScaleDefault;
	}
	// The cover the distant sheet continues: the layer's UNSCALED cover, whatever
	// the volumetric scale, so an impostor-only frame keeps its horizon
	// (world_beauty.cloud_distant_cover is the twin).
	inline double CloudDistantCover(double Cover, double Scale)
	{
		(void)Scale;
		return Cover;
	}
	// Sky step 1 (the owner's X-Plane-12 brief, 2026-11-14: "ragged, wispy edges and
	// fine cauliflower detail ... soft grey-blue bellies ... light bleeding through
	// thin edges"; r95's #03/#13 smooth rounded blobs with dark undersides).
	// -look-cloud-wisp=on|off (on by default; off is round 95 exactly), the CUMULUS
	// and STRATOCUMULUS shapes: the material's five wisp scalars (cloud_layers.hlsl:
	// WispAmount gates it all; CloudWispCurl cells of flow warp on a view sample's
	// detail point; a finer top octave weighted CloudWispTopDetail; the erosion x
	// (1 + CloudWispBoundaryErosion x (1 - density)); density^CloudWispEdgePower
	// after the erosion, so a thin edge is optically thin) and the sky light's
	// cloud-bottom occlusion CAPPED at CloudWispBottomOcclusion after
	// CloudBottomOcclusionFor (round 82's 0.8 left a belly a fifth of the sky). No
	// march sample added; shadow samples add no hash. world_beauty.cloud_wisp_row /
	// cloud_belly_occlusion are the twins. UNCALIBRATED: set by probe render on the
	// render machine (scene 3 with and without the switch).
	constexpr double CloudWispAmount = 1.0;
	constexpr double CloudWispCurl = 0.6;
	constexpr double CloudWispEdgePower = 1.6;
	constexpr double CloudWispTopDetail = 0.6;
	constexpr double CloudWispBoundaryErosion = 0.5;
	constexpr double CloudWispBottomOcclusion = 0.45;
	enum EWispField
	{
		WspAmount = 0,
		WspCurl = 1,
		WspEdgePower = 2,
		WspTopDetail = 3,
		WspBoundaryErosion = 4,
		WspFieldCount = 5
	};
	// The material's scalar names, in order (world_beauty.CLOUD_WISP_FIELDS).
	inline const char* CloudWispFieldName(int Field)
	{
		static const char* const Names[WspFieldCount] = {
			"WispAmount", "CurlStrength", "EdgeThinPower", "TopDetailGain", "BoundaryErosion"};
		return Field >= 0 && Field < WspFieldCount ? Names[Field] : "";
	}
	inline bool CloudWispApplies(bool bWispOn, int Shape)
	{
		return bWispOn && (Shape == CloudCumulus || Shape == CloudStratocumulus);
	}
	// The five scalars for a layer: the amounts where the wisp applies, the OFF
	// values (0, 0, 1, 0, 0: the material's defaults, round 95) where it does not.
	inline void CloudWispRow(bool bApplies, double* Out)
	{
		Out[WspAmount] = bApplies ? CloudWispAmount : 0.0;
		Out[WspCurl] = bApplies ? CloudWispCurl : 0.0;
		Out[WspEdgePower] = bApplies ? CloudWispEdgePower : 1.0;
		Out[WspTopDetail] = bApplies ? CloudWispTopDetail : 0.0;
		Out[WspBoundaryErosion] = bApplies ? CloudWispBoundaryErosion : 0.0;
	}
	// Applied AFTER CloudBottomOcclusionFor: capped, never raised.
	inline double CloudBellyOcclusion(bool bApplies, double Occlusion)
	{
		return bApplies && Occlusion > CloudWispBottomOcclusion ? CloudWispBottomOcclusion : Occlusion;
	}
	// Sky-clouds lane (2026-11-15): -look-cloud-light=on|off (OFF by default; off is
	// c9e13c53's clouds exactly). world_beauty.CLOUD_LIGHT_* is the twin (the why and
	// the real-world numbers are there): the scattering node's six inputs (dual-lobe
	// HG g 0.8 / -0.3, back share 0.2; Wrenninge 2013 octave a = b = c = 0.5), the
	// flat-base darkening of the SKY light (cloud_sky_ao.hlsl on the AO pin; lit 2,
	// 2026-11-16: round 1426's powder and base scaled the ALBEDO, so every light, and
	// darkened #3 0.227 -> 0.139; the why is at world_beauty.CLOUD_LIGHT_*). The bridge
	// also sets SkyBottomOcclusion (the AO pin replaces the engine's bottom gradient).
	// ON also stops round 82's billow row overriding the cumulus row
	// (CloudLightBillow). No sample and no march step: per-sample ALU only.
	// UNCALIBRATED (every look number).
	enum : int
	{
		LgtPhaseG = 0,
		LgtPhaseG2 = 1,
		LgtPhaseBlend = 2,
		LgtMsContribution = 3,
		LgtMsOcclusion = 4,
		LgtMsEccentricity = 5,
		LgtBaseDarkening = 6,
		LgtBaseRise = 7,
		LgtFieldCount = 8
	};
	inline const char* CloudLightFieldName(int Field)
	{
		static const char* const Names[LgtFieldCount] = {
			"PhaseG", "PhaseG2", "PhaseBlend", "MsContribution", "MsOcclusion",
			"MsEccentricity", "BaseDarkening", "BaseRise"};
		return Field >= 0 && Field < LgtFieldCount ? Names[Field] : "";
	}
	constexpr double CloudLightPhaseG = 0.8;
	constexpr double CloudLightPhaseG2 = -0.3;
	constexpr double CloudLightPhaseBlend = 0.2;
	constexpr double CloudLightOctave = 0.5;
	// The OFF row: the material's defaults (CloudScattering's six, no base).
	inline double CloudLightOff(int Field)
	{
		static const double Values[LgtFieldCount] = {0.85, -0.3, 0.3, 0.7, 0.25, 0.4, 0.0, 0.3};
		return Field >= 0 && Field < LgtFieldCount ? Values[Field] : 0.0;
	}
	// Per shape (cumulus, stratocumulus, overcast, nimbostratus, altocumulus).
	inline double CloudLightBaseDarkening(int Cloud)
	{
		static const double Rows[CloudCount] = {0.45, 0.35, 0.55, 0.7, 0.25};
		return Cloud >= 0 && Cloud < CloudCount ? Rows[Cloud] : 0.0;
	}
	inline double CloudLightBaseRise(int Cloud)
	{
		static const double Rows[CloudCount] = {0.25, 0.4, 0.5, 0.5, 0.4};
		return Cloud >= 0 && Cloud < CloudCount ? Rows[Cloud] : 0.3;
	}
	inline void CloudLightRow(bool bLightOn, int Cloud, double* Out)
	{
		for (int F = 0; F < LgtFieldCount; ++F)
		{
			Out[F] = CloudLightOff(F);
		}
		if (!bLightOn)
		{
			return;
		}
		Out[LgtPhaseG] = CloudLightPhaseG;
		Out[LgtPhaseG2] = CloudLightPhaseG2;
		Out[LgtPhaseBlend] = CloudLightPhaseBlend;
		Out[LgtMsContribution] = CloudLightOctave;
		Out[LgtMsOcclusion] = CloudLightOctave;
		Out[LgtMsEccentricity] = CloudLightOctave;
		Out[LgtBaseDarkening] = CloudLightBaseDarkening(Cloud);
		Out[LgtBaseRise] = CloudLightBaseRise(Cloud);
	}
	// -look-cloud-billow's row applies only with -look-cloud-light=off.
	inline bool CloudLightBillow(bool bBillowOn, bool bLightOn)
	{
		return bBillowOn && !bLightOn;
	}
	// Lane rain-grey (2026-11-16): -cloud-deck-scatter=round95|beauty (beauty by
	// default since round 147: Windows r146's #06 drew round95's deck near black,
	// luma 0.068 against beauty's 0.133 in r14622). Sky step 1 baked CloudScattering (contribution 0.7, occlusion 0.25,
	// eccentricity 0.4, g 0.85 / -0.3 / 0.3) into M_FlightSimCloudLayers for EVERY
	// shape. Those octave constants break Wrenninge 2013's energy condition
	// (contribution <= occlusion): octave 1 sees the sun through exp(-0.25 tau) and
	// scatters 0.7 x the single-scattered light. For a cumulus edge (tau ~ 1) that
	// is the wanted glow; under a 1-3 km rain or overcast DECK (tau 20-100) it
	// lights the underside as if the deck were a quarter as thick: Windows round
	// 144 drew #06's nimbostratus base at sRGB 0.36-0.44 (round 199: 0.11-0.17),
	// #07's heavy rain as a flat bright grey with the streaks lost against it, and
	// the brightened base stood off the distant sheet as a hard dark band. round95
	// gives the DECK shapes (overcast, nimbostratus) round 95's energy-conserving
	// node (the storm's STORM_SCATTERING: g 0.8 / -0.5 / 0.5, octaves 0.5 / 0.5 /
	// 0.5, as M_FlightSimCloudLayers drew at 40c95c10); cumulus, stratocumulus and
	// altocumulus keep step 1's. Graph 11 drives the node's six pins from these
	// parameters (defaults = CloudScattering). beauty = step 1's on every shape.
	// Only with -look-cloud-light=off (on has its own row). Beauty only.
	inline int CloudDeckScatterFor(const char* Word)
	{
		// Round 147: no word is the default, beauty (r146 #06: round95's deck drew near black).
		if (Word == nullptr || Word[0] == '\0' || std::strcmp(Word, "beauty") == 0) { return 0; }
		if (std::strcmp(Word, "round95") == 0) { return 1; }
		return -1;
	}
	inline bool CloudDeckScatterApplies(bool bRound95, bool bLightOn, int Cloud)
	{
		return bRound95 && !bLightOn && (Cloud == CloudOvercast || Cloud == CloudNimbostratus);
	}
	inline double CloudDeckScatter(int Field)
	{
		static const double Values[LgtMsEccentricity + 1] = {0.8, -0.5, 0.5, 0.5, 0.5, 0.5};
		return Field >= 0 && Field <= LgtMsEccentricity ? Values[Field] : 0.0;
	}
	// Overwrites the six scattering fields of a CloudLightRow where it applies.
	inline void CloudDeckScatterRow(bool bApplies, double* Out)
	{
		if (!bApplies)
		{
			return;
		}
		for (int F = LgtPhaseG; F <= LgtMsEccentricity; ++F)
		{
			Out[F] = CloudDeckScatter(F);
		}
	}
	// -cloud-material=ours|epic (A/B; world_beauty.CLOUD_MATERIAL_*): epic puts Epic's
	// Volumetrics plugin cloud material on the beauty layer instead of ours.
	constexpr int CloudMaterialWordCount = 3;
	inline const char* CloudMaterialWord(int I)
	{
		static const char* const Words[CloudMaterialWordCount] = {"ours", "epic", "engine"};
		return I >= 0 && I < CloudMaterialWordCount ? Words[I] : "";
	}
	// r150 (owner, 2026-11-16: "unreal engine's basic default clouds also look better"
	// than #13's): -cloud-material=engine draws the engine's own stock volumetric cloud
	// material, which always ships with UE (no plugin).
	inline const char* CloudMaterialEnginePath()
	{
		return "/Engine/EngineSky/VolumetricClouds/m_SimpleVolumetricCloud_Inst.m_SimpleVolumetricCloud_Inst";
	}
	inline const char* CloudMaterialEpicPath()
	{
		return "/Volumetrics/Sky/Materials/M_VolumetricCloud_02_Profiles_Soft.M_VolumetricCloud_02_Profiles_Soft";
	}
	// The beauty cloud's VolumetricAdvancedMaterialOutput constants, BAKED into
	// M_FlightSimCloudLayers by scripts/ue_create_materials.py CLOUD_SCATTERING at
	// graph generation CloudGraphGeneration (world_beauty.CLOUD_SCATTERING is the
	// twin; tests pin all three). Recorded here so render.json says what lit the
	// cloud; nothing here sets them. UNCALIBRATED.
	constexpr int CloudGraphGeneration = 11;   // rain-grey: the scattering pins from parameters (CloudDeckScatterRow)
	constexpr double CloudAlbedo = 0.98;
	// True when the asset's stamped generation is the one this bridge was written for.
	inline bool CloudGraphGenerationCurrent(int Stamped)
	{
		return Stamped == CloudGraphGeneration;
	}
	inline double CloudAlbedoBaked()
	{
		return CloudAlbedo;
	}
	constexpr int CloudScatteringCount = 7;
	inline const char* CloudScatteringName(int Field)
	{
		static const char* const Names[CloudScatteringCount] = {
			"phase_g", "phase_g2", "phase_blend", "octaves", "contribution", "occlusion", "eccentricity"};
		return Field >= 0 && Field < CloudScatteringCount ? Names[Field] : "";
	}
	inline double CloudScattering(int Field)
	{
		static const double Values[CloudScatteringCount] = {0.85, -0.3, 0.3, 2.0, 0.7, 0.25, 0.4};
		return Field >= 0 && Field < CloudScatteringCount ? Values[Field] : 0.0;
	}
	// The owner's parameter names and the material parameter each one IS
	// (world_beauty.CLOUD_OWNER_ALIASES): documented aliases, recorded, never a
	// second input.
	constexpr int CloudOwnerAliasCount = 5;
	inline const char* CloudOwnerAlias(int Field, bool bTarget)
	{
		static const char* const Owner[CloudOwnerAliasCount] = {
			"Coverage", "Density", "DetailStrength", "NoiseScale", "Wind"};
		static const char* const Target[CloudOwnerAliasCount] = {
			"Coverage", "ExtinctionPerM", "DetailErosion", "ShapeScaleKm", "WindOffsetM"};
		return Field >= 0 && Field < CloudOwnerAliasCount ? (bTarget ? Target[Field] : Owner[Field]) : "";
	}
	// The default layer (the -sky= plan's VISUAL ONLY 3 km slab, never a card's
	// stated layer) is thinned to the shape's depth: fair cumulus and a stratus
	// deck are 1-2 km deep; 0 keeps the layer as built.
	inline double CloudMaxThicknessM(int Cloud)
	{
		// sky step 5: altocumulus 900 m (a sheet a few hundred metres deep). UNCALIBRATED.
		static const double Rows[CloudCount] = {2000.0, 0.0, 2000.0, 0.0, 900.0};
		return Cloud >= 0 && Cloud < CloudCount ? Rows[Cloud] : 0.0;
	}
	inline double CloudCappedTopM(int Cloud, double BaseM, double TopM, bool bStated)
	{
		const double Cap = CloudMaxThicknessM(Cloud);
		if (bStated || Cap <= 0.0 || TopM - BaseM <= Cap)
		{
			return TopM;
		}
		return BaseM + Cap;
	}
	// USkyAtmosphereComponent::MultiScatteringFactor per preset: the engine's
	// LUT under-lights the sky seen from altitude (shot d's near-black navy at
	// 3.8 km); the clear and hazy skies take a little more multiple scattering
	// (paler, brighter towards the horizon). The weather presets keep 1.
	inline double SkyMultiScattering(int Preset)
	{
		static const double Rows[PresetCount] = {1.25, 1.15, 1.0, 1.0, 1.0};
		return Preset >= 0 && Preset < PresetCount ? Rows[Preset] : 1.0;
	}
	constexpr double LightningReferenceLuxDefault = 50.0;
	constexpr double DetailFadeMDefault = 400.0;
	constexpr double DetailScaleMDefault = 2.0;
	constexpr double PuddleShareDefault = 0.5;
	// The tileset's imagery correction (world_beauty.TILES_DEHAZE / TILES_SATURATION):
	// one value for every preset.
	constexpr double TilesDehazeDefault = 0.8;
	constexpr double TilesSaturationDefault = 1.05;
	// The wet law the tiles, the scatter and the planet's ground share
	// (world_beauty.WET_DARKENING).
	constexpr double WetDarkening = 0.30;
	// The sun's transmittance model this lane sets on a scene without a -sky=
	// plan (world_beauty.SUN_PER_PIXEL_TRANSMITTANCE, the one flag beauty_look
	// reads): the engine's atmosphere reddens and dims the beam per pixel.
	constexpr bool SunPerPixelTransmittance = true;

	// The storm words: core/scene/weather_look.py STORMS (world_beauty.STORM_WORDS).
	constexpr int StormWordCount = 2;
	inline const char* StormWord(int Index)
	{
		static const char* const Words[StormWordCount] = {"thunderstorm", "tornado"};
		return Index >= 0 && Index < StormWordCount ? Words[Index] : "";
	}
	inline bool IsStormWord(const char* Word)
	{
		for (int I = 0; Word != nullptr && I < StormWordCount; ++I)
		{
			if (std::strcmp(Word, StormWord(I)) == 0)
			{
				return true;
			}
		}
		return false;
	}

	// The planet's ground albedo by surface (world_beauty.GROUND_ALBEDO_SRGB, row
	// 0 the default), sRGB bytes, darkened in linear light by the wet law.
	// UNCALIBRATED: set by probe render on the render machine.
	constexpr int GroundSurfaceCount = 8;
	inline const char* GroundSurfaceName(int Surface)
	{
		static const char* const Names[GroundSurfaceCount] = {
			"default", "desert", "forest", "grassland", "snow", "bare", "city", "ocean"};
		return Surface >= 0 && Surface < GroundSurfaceCount ? Names[Surface] : "default";
	}
	inline int GroundSurfaceIndex(const char* Surface)
	{
		for (int I = 0; Surface != nullptr && I < GroundSurfaceCount; ++I)
		{
			if (std::strcmp(Surface, GroundSurfaceName(I)) == 0)
			{
				return I;
			}
		}
		return 0;
	}
	inline void GroundAlbedoSrgb(int Surface, double Wetness, int Out[3])
	{
		static const int Rows[GroundSurfaceCount][3] = {
			{92, 96, 78}, {156, 124, 92}, {62, 74, 52}, {96, 108, 70},
			{206, 210, 216}, {120, 110, 96}, {104, 104, 100}, {40, 52, 60}};
		const int Row = Surface >= 0 && Surface < GroundSurfaceCount ? Surface : 0;
		const double Wet = Wetness < 0.0 ? 0.0 : (Wetness > 1.0 ? 1.0 : Wetness);
		const double K = 1.0 - WetDarkening * Wet;
		for (int C = 0; C < 3; ++C)
		{
			double V = Rows[Row][C] / 255.0;
			V = V < 0.0 ? 0.0 : (V > 1.0 ? 1.0 : V);
			double Lin = V <= 0.04045 ? V / 12.92 : std::pow((V + 0.055) / 1.055, 2.4);
			Lin *= K;
			Lin = Lin < 0.0 ? 0.0 : (Lin > 1.0 ? 1.0 : Lin);
			const double S = Lin <= 0.0031308 ? Lin * 12.92 : 1.055 * std::pow(Lin, 1.0 / 2.4) - 0.055;
			Out[C] = static_cast<int>(std::floor(S * 255.0 + 0.5));
		}
	}
	// Visual push lane C (round 7's green #10): under the STORM preset the
	// sky's and the clouds' ground bounce is a grey of the surface row's own
	// linear luminance (Rec. 709 weights), not the row's hue
	// (world_beauty.neutral_albedo_srgb). A storm deck extinguishes the sun on
	// its underside, so the engine's ground-bounce term (lit by the sun, blind
	// to the deck's shadow on the ground) is nearly all the light it shows: the
	// grassland row's G/B 2.5 in linear light turned the deck, the sky light
	// that captures it and every lit surface under it green.
	inline void NeutralAlbedoSrgb(const int In[3], int Out[3])
	{
		double Lin[3];
		for (int C = 0; C < 3; ++C)
		{
			double V = In[C] / 255.0;
			V = V < 0.0 ? 0.0 : (V > 1.0 ? 1.0 : V);
			Lin[C] = V <= 0.04045 ? V / 12.92 : std::pow((V + 0.055) / 1.055, 2.4);
		}
		double Y = 0.2126 * Lin[0] + 0.7152 * Lin[1] + 0.0722 * Lin[2];
		Y = Y < 0.0 ? 0.0 : (Y > 1.0 ? 1.0 : Y);
		const double S = Y <= 0.0031308 ? Y * 12.92 : 1.055 * std::pow(Y, 1.0 / 2.4) - 0.055;
		const int G = static_cast<int>(std::floor(S * 255.0 + 0.5));
		Out[0] = G; Out[1] = G; Out[2] = G;
	}
	// Physical constants (not look values).
	constexpr double Koschmieder = 3.912;
	constexpr double RayleighGreenPerKm = 0.013558;
	constexpr double MieSingleScatterAlbedo = 0.9;
	constexpr double MinVisibilityKm = 0.05;

	// world_beauty.SEVERE_RAIN_MMH / SEVERE_WIND_MPS (lane D, 2026-11-11): heavy rain
	// in a strong wind is the storm look (#15, the hurricane's suggested weather).
	constexpr double SevereRainMmh = 8.0;
	constexpr double SevereWindMps = 10.0;
	inline bool IsSevereRain(double RainRateMmh, double WindMps)
	{
		return RainRateMmh >= SevereRainMmh && WindMps >= SevereWindMps;
	}

	inline int SelectPreset(bool bStorm, double RainRateMmh, bool bPrecipitationRain, double CloudCover,
	                        double VisibilityKm, double WindMps = 0.0)
	{
		if (bStorm || IsSevereRain(RainRateMmh, WindMps))
		{
			return PresetStorm;
		}
		if (RainRateMmh > 0.0 || bPrecipitationRain)
		{
			return PresetRain;
		}
		if (CloudCover >= OvercastCover)
		{
			return PresetOvercast;
		}
		if (VisibilityKm > 0.0 && VisibilityKm < HazyVisibilityKm)
		{
			return PresetHazy;
		}
		return PresetClear;
	}

	struct FMieSplit
	{
		double BetaPerKm;
		double MieExtinctionPerKm;
		double MieScatteringPerKm;
		double MieAbsorptionPerKm;
		double FogFactor;
	};

	inline FMieSplit MieSplit(double VisibilityKm, double Share, double CapPerKm)
	{
		const double Visibility = VisibilityKm > MinVisibilityKm ? VisibilityKm : MinVisibilityKm;
		const double Beta = Koschmieder / Visibility;
		const double Haze = Beta - RayleighGreenPerKm > 0.0 ? Beta - RayleighGreenPerKm : 0.0;
		const double ShareClamped = Share > 0.0 ? Share : 0.0;
		const double Cap = CapPerKm > 0.0 ? CapPerKm : 0.0;
		const double Mie = ShareClamped * Haze < Cap ? ShareClamped * Haze : Cap;
		FMieSplit Out;
		Out.BetaPerKm = Beta;
		Out.MieExtinctionPerKm = Mie;
		Out.MieScatteringPerKm = Mie * MieSingleScatterAlbedo;
		Out.MieAbsorptionPerKm = Mie * (1.0 - MieSingleScatterAlbedo);
		// The fog keeps the haze the Mie layer did not take: Rayleigh (the
		// atmosphere's own) + Mie + fog = Beta at the ground, counted once.
		Out.FogFactor = Beta > 0.0 ? (Haze - Mie > 0.0 ? Haze - Mie : 0.0) / Beta : 0.0;
		return Out;
	}
	// Round 7 (lane E, world_beauty.CLEAR_DEFAULT_VISIBILITY_KM): a CLEAR world
	// whose card states no visibility (an unsampled 0) gets the Mie layer of a
	// 40 km clear day instead of the engine's near-aerosol-free default, so the
	// horizon whitens, the sky desaturates towards it and far ridges take aerial
	// perspective (round 4's #01, #03, #12, #13). The height fog is left as the
	// scene built it (FogFactor 1): only the atmosphere's aerosol is added.
	constexpr double ClearDefaultVisibilityKm = 40.0;
	inline double AerosolVisibilityKm(int Preset, double VisibilityKm)
	{
		return VisibilityKm > 0.0 ? VisibilityKm : (Preset == PresetClear ? ClearDefaultVisibilityKm : 0.0);
	}

	// Sky step 4 (2026-11-15): THE HEIGHT FOG'S VERTICAL PROFILE. Read in the UE 5.7
	// source (SceneCore.cpp 403-404, FogRendering.cpp 237-271, HeightFogCommon.ush
	// 192-232, DeferredShadingRenderer.cpp 3455/3466): the engine draws the fog's
	// density as FogDensity/1000 per cm x 2^(-FogHeightFalloff/1000 x (z - FogHeight)
	// in cm), i.e. a 1/e scale height of 10 / (ln 2 x falloff) metres; it draws the
	// fog OVER the sky atmosphere (RenderSkyAtmosphere, then RenderFog), and a sky
	// pixel sits at the far plane, so its fog is the ray's whole line integral capped
	// at FogMaxOpacity. The scene's fog (FlightSimVisualScene.cpp: falloff 0.0002) has
	// a 72 km scale height: uniform to the top of the atmosphere, so EVERY sky pixel
	// from every camera takes the fog at its max opacity, 0.92 of the fog's one
	// in-scatter colour (under a -sky= plan: the sky light's average, FlightSimSky.cpp
	// 265-266), with 0.08 of the atmosphere under it. That is the owner's "flat navy
	// frame" and "no horizon haze" (round 95 #13, round 83 #03): the atmosphere's own
	// gradient never reaches the frame. A real boundary-layer haze decays with a
	// 1-2 km scale height; the clear and hazy rows give the fog the Mie layer's
	// (fog_scale_height_km), so the zenith ray carries ~D x H of fog, the horizon ray
	// saturates to the band, and far ridges take the atmosphere's aerial perspective
	// through a thinning haze. The density at the SCENE's fog height is kept
	// (FogDensityRebased), so the Koschmieder count at the ground (MieSplit, the fog
	// keeps the haze the Mie layer did not take) is unchanged: a redistribution in
	// height, not more extinction.
	//
	// The engine clamps the fog's observer to FogHeight + 65536 cm (FogRendering.cpp
	// MaxObserverHeightDifference, for precision) and shifts the whole ray down by the
	// excess (HeightFogCommon.ush 233/242): under a short scale height a cruise camera
	// 10 km up would be treated as 655 m up with the ground 9 km BELOW the fog's
	// reference height, where the exponential is 2^11 denser, and every surface would
	// saturate. So the fog's reference height follows the aircraft (FogReferenceZM:
	// the fog component is moved up to it, its density rebased so the profile in world
	// space is identical, and Advance re-bases it when the aircraft has climbed or
	// descended FogRebaseStepM). The dust haze's inversion and the storm's rain haze
	// read the fog's height live and compose on top. world_beauty.py
	// fog_height_falloff / fog_density_rebased / fog_reference_z_m are the twins.
	// UNCALIBRATED: the scale height is the row's Mie one by construction; the
	// outcome (a pale band, a blue zenith, layered ridges) is UNMEASURED until the
	// Windows round named in docs/VISUAL_FIDELITY_PLAN.md "Sky step 4".
	constexpr double SceneFogHeightFalloff = 0.0002;    // FlightSimVisualScene.cpp SetFogHeightFalloff
	constexpr double SceneFogStartDistanceM = 1500.0;   // FlightSimVisualScene.cpp SetStartDistance
	constexpr double SceneFogMaxOpacity = 0.92;         // FlightSimVisualScene.cpp SetFogMaxOpacity
	constexpr double FogObserverClampM = 655.36;        // FogRendering.cpp MaxObserverHeightDifference 65536 cm
	constexpr double FogRebaseStepM = 100.0;            // Advance re-bases past this climb or descent
	constexpr double FogFalloffPerScaleHeightKm = 0.01 / 0.69314718055994531;   // falloff x scale height (km)
	inline double FogHeightFalloffFor(double ScaleHeightKm)
	{
		return ScaleHeightKm > 0.0 ? FogFalloffPerScaleHeightKm / ScaleHeightKm : SceneFogHeightFalloff;
	}
	// FogDensity at a new reference height ToZM (metres) that draws the same density
	// everywhere as Density did at FromZM under Falloff: D x 2^(-falloff x dz / 10)
	// (falloff/1000 per cm x 100 cm per metre).
	inline double FogDensityRebased(double Density, double Falloff, double FromZM, double ToZM)
	{
		return Density * std::pow(2.0, -Falloff * (ToZM - FromZM) / 10.0);
	}
	// The fog's reference height: the aircraft's when the row states a profile and
	// the aircraft is above the scene's fog height (a camera at or under the
	// reference, or up to FogObserverClampM above it, is never clamped); else the
	// scene's.
	inline double FogReferenceZM(double SceneZM, double AircraftZM, bool bProfile)
	{
		return bProfile && AircraftZM > SceneZM ? AircraftZM : SceneZM;
	}

	// Sky step 4: -sky-multi-scatter=auto|on|off (world_beauty.SKY_MULTI_SCATTER_SWITCH).
	// Why ef361bd6's class gate is lifted: USkyAtmosphereComponent::MultiScatteringFactor
	// is one multiply in the multi-scattering LUT pass (SkyAtmosphere.usf 1309/1311,
	// a 32 x 32 compute dispatch the atmosphere runs every frame at the same sample
	// count whatever the factor; r.SkyAtmosphere.MultiScatteringLUT.HighQuality is
	// already 1 on every GPU from the render path); it is in no per-pixel sky, aerial
	// perspective or cloud shader and adds no submission. Round 1's bisect named
	// a8c964fc as a unit (march, shadow span, thinning, fog-on-all-pixel and this
	// factor together) and r87 then located the stall in the sky light's cloud
	// reflection march and capped it; nothing isolated the factor. claude/hl-sky keeps
	// ef361bd6's class gate under auto (the constrained class keeps the engine's 1.0
	// until a Windows round measures it); on applies the row on every GPU, which is
	// that round's A/B; off is ef361bd6's sky (1.0) everywhere. An
	// unknown word is -1 (Build refuses it by name). Whether 1.25 reads right on the
	// iGPU is UNMEASURED (round 97 is the A/B).
	constexpr int SkyMultiScatterWordCount = 3;
	inline const char* SkyMultiScatterWord(int I)
	{
		static const char* const Words[SkyMultiScatterWordCount] = {"auto", "on", "off"};
		return I >= 0 && I < SkyMultiScatterWordCount ? Words[I] : "";
	}
	inline int SkyMultiScatterFor(const char* Word, bool Constrained)
	{
		if (Word == nullptr || std::strcmp(Word, "auto") == 0)
		{
			return Constrained ? 0 : 1;   // ef361bd6's class gate (see above)
		}
		if (std::strcmp(Word, "on") == 0) { return 1; }
		if (std::strcmp(Word, "off") == 0) { return 0; }
		return -1;
	}

	// Lane sky-atmosphere: -look-sky-gradient=on|off (core/sky/gradient.py, the
	// physics and the engine reading). On (the default) the clear and hazy rows'
	// height fogs stop at FogCutoffDistance SkyGradientFogCutoffKm, so the sky
	// pixels (decoded at 1 / 1e-8 cm = 1000 km: SceneView.cpp
	// CreateInvDeviceZToWorldZTransform) show the physical atmosphere alone, and
	// the fog's sky-atmosphere ambient is scaled by HorizonAirlightGain (the CIE
	// clear sky's horizon over its upper-hemisphere mean) so a far surface fades
	// to the horizon's luminance, not to the dimmer sphere-mean distant sky light.
	// 1 = on, 0 = off, -1 = an unknown word (Build refuses it by name).
	inline int SkyGradientFor(const char* Word)
	{
		if (Word == nullptr || Word[0] == '\0' || std::strcmp(Word, "on") == 0) { return 1; }
		if (std::strcmp(Word, "off") == 0) { return 0; }
		return -1;
	}
	// Fix lane sun-color: -sky-capture-veil=on|off (core/sky/gradient.py
	// sky_capture_veil_mode). 1 = on, 0 = off, -1 = an unknown word.
	inline int SkyCaptureVeilFor(const char* Word)
	{
		if (Word == nullptr || Word[0] == '\0' || std::strcmp(Word, "on") == 0) { return 1; }
		if (std::strcmp(Word, "off") == 0) { return 0; }
		return -1;
	}
	[[maybe_unused]] constexpr double SkyGradientSkyPixelDepthKm = 1000.0;
	[[maybe_unused]] constexpr double SkyGradientFogCutoffKm = 950.0;
	constexpr int AirlightGainCount = 10;
	// CIE S 011 type 12 (a -1, b -0.32, c 10, d -3, e 0.45): horizon (2 deg up,
	// azimuth mean) / upper-hemisphere mean at sun elevation 0, 10, ... 90 deg.
	constexpr double AirlightGainTable[AirlightGainCount] = {
		2.313, 2.016, 1.717, 1.511, 1.371, 1.273, 1.204, 1.158, 1.131, 1.123};
	constexpr double AirlightGainMax = 2.0;
	constexpr double AirlightTwilightDeg = -6.0;
	inline double HorizonAirlightGain(double SunElevationDeg)
	{
		if (SunElevationDeg < 0.0)
		{
			const double Top = AirlightGainTable[0] < AirlightGainMax ? AirlightGainTable[0] : AirlightGainMax;
			double T = SunElevationDeg / AirlightTwilightDeg;
			T = T < 0.0 ? 0.0 : (T > 1.0 ? 1.0 : T);
			return Top + (1.0 - Top) * T;
		}
		const double X = (SunElevationDeg > 90.0 ? 90.0 : SunElevationDeg) / 10.0;
		int I = static_cast<int>(X);
		I = I > AirlightGainCount - 2 ? AirlightGainCount - 2 : I;
		const double F = X - I;
		const double G = AirlightGainTable[I] + (AirlightGainTable[I + 1] - AirlightGainTable[I]) * F;
		return G < AirlightGainMax ? G : AirlightGainMax;
	}
	// The engine's Earth atmosphere (SkyAtmosphereComponent.cpp defaults), per km.
	[[maybe_unused]] constexpr double EarthRayleighPerKm[3] = {0.005802, 0.013558, 0.033100};
	[[maybe_unused]] constexpr double EarthRayleighScaleHeightKm = 8.0;
	[[maybe_unused]] constexpr double EarthOzonePerKm[3] = {0.000650, 0.001881, 0.000085};

	inline int SelectCloud(double Cover, double ThicknessM, int Preset)
	{
		if (Preset == PresetStorm || Preset == PresetRain)
		{
			return CloudNimbostratus;
		}
		if (Cover >= CloudOvercastCover)
		{
			return CloudOvercast;
		}
		if (ThicknessM <= StratocumulusMaxThicknessM && Cover >= StratocumulusMinCover)
		{
			return CloudStratocumulus;
		}
		return CloudCumulus;
	}

	// world_beauty.fog_directional_exponent: the analytic fog's sun lobe
	// pow(cos, n) / 4 pi has mean cosine (n+1)/(n+2) over its hemisphere; n is
	// chosen so that equals the volumetric fog's Henyey-Greenstein g, clamped to
	// [FogExponentMin, FogExponentMax] (a lobe this shape cannot be flatter
	// than g = 0.5). Fitted, not a look value.
	constexpr double FogExponentMin = 1.0;
	constexpr double FogExponentMax = 64.0;
	// world_beauty.vfog_scattering_compensation (round 4): the volumetric fog
	// scatters Albedo x Extinction, so a row's extinction scale under 1 (the wet
	// rows' WET_VFOG_EXTINCTION_SCALE) also cut the haze's in-scatter (round 3's
	// #08 and head shot c went near black). The lights' volumetric scattering
	// takes the inverse: only the extinction is scaled. 1 on every other row.
	inline double VFogScatteringCompensation(double ExtinctionScale)
	{
		return ExtinctionScale > 0.0 && ExtinctionScale < 1.0 ? 1.0 / ExtinctionScale : 1.0;
	}
	inline double FogDirectionalExponentForG(double G)
	{
		const double Gc = G < 0.0 ? 0.0 : (G > 0.99 ? 0.99 : G);
		const double N = (2.0 * Gc - 1.0) / (1.0 - Gc);
		return N < FogExponentMin ? FogExponentMin : (N > FogExponentMax ? FogExponentMax : N);
	}

	// world_beauty.layer_cover_and_shape: the fair layer's cover, else the
	// card's (CardCover >= 0), else RainDefaultCover in a rain world, else the
	// default cover of the shape a cover-0 layer of this thickness would be; the
	// shape then follows the cover.
	// CloudTable: the cloud rows in force (CloudCount x CloudFieldCount, the
	// overrides applied), or nullptr for the defaults.
	inline int LayerCoverAndShape(double CardCover, double ThicknessM, int Preset, bool bFair,
	                              const double* CloudTable, double* OutCover)
	{
		const bool bStated = CardCover >= 0.0;
		const int Guess = SelectCloud(bStated ? CardCover : 0.0, ThicknessM, Preset);
		const double GuessDefault = CloudTable != nullptr ? CloudTable[Guess * CloudFieldCount + CldDefaultCover]
		                                                  : CloudDefault(Guess, CldDefaultCover);
		const double Cover = bFair ? FairCover
		                           : (bStated ? CardCover : (Preset == PresetRain ? RainDefaultCover : GuessDefault));
		if (OutCover != nullptr)
		{
			*OutCover = Cover;
		}
		return SelectCloud(Cover, ThicknessM, Preset);
	}

	// rain_field.splitmix64 / rain_field.unit (the weather's own law).
	inline uint64_t WorldSplitMix64(uint64_t X)
	{
		uint64_t Z = X + 0x9E3779B97F4A7C15ull;
		Z = (Z ^ (Z >> 30)) * 0xBF58476D1CE4E5B9ull;
		Z = (Z ^ (Z >> 27)) * 0x94D049BB133111EBull;
		return Z ^ (Z >> 31);
	}

	inline double WorldUnit(uint64_t Seed, uint64_t Index, uint64_t Channel)
	{
		const uint64_t Key = WorldSplitMix64(Index * 8ull + Channel);
		return static_cast<double>(WorldSplitMix64(Seed ^ Key) >> 11) * (1.0 / 9007199254740992.0);
	}

	inline void CloudSeedOffsetKm(uint64_t Seed, double Out[3])
	{
		for (int Channel = 0; Channel < 3; ++Channel)
		{
			Out[Channel] = WorldUnit(Seed, 0ull, static_cast<uint64_t>(Channel)) * CloudSeedSpanKm;
		}
	}

	inline double SlabPathM(double AZM, double BZM, double LengthM, double BaseM, double TopM)
	{
		if (!(TopM > BaseM) || LengthM <= 0.0)
		{
			return 0.0;
		}
		if (AZM == BZM)
		{
			return (BaseM <= AZM && AZM <= TopM) ? LengthM : 0.0;
		}
		const double T0 = (BaseM - AZM) / (BZM - AZM);
		const double T1 = (TopM - AZM) / (BZM - AZM);
		double Lo = T0 < T1 ? T0 : T1;
		double Hi = T0 < T1 ? T1 : T0;
		Lo = Lo > 0.0 ? Lo : 0.0;
		Hi = Hi < 1.0 ? Hi : 1.0;
		return Hi - Lo > 0.0 ? (Hi - Lo) * LengthM : 0.0;
	}

	struct FOcclusion
	{
		double PathM;
		double Tau;
		double Transmittance;
		bool bFlagged;
	};

	inline FOcclusion Occlusion(double AZM, double BZM, double LengthM, double BaseM, double TopM,
	                            double Cover, double ExtinctionPerM, double ExtinctionScale,
	                            double FlagTransmittance)
	{
		FOcclusion Out;
		Out.PathM = SlabPathM(AZM, BZM, LengthM, BaseM, TopM);
		Out.Tau = Out.PathM * (Cover > 0.0 ? Cover : 0.0) * (ExtinctionPerM > 0.0 ? ExtinctionPerM : 0.0) *
		          (ExtinctionScale > 0.0 ? ExtinctionScale : 0.0);
		Out.Transmittance = std::exp(-Out.Tau);
		Out.bFlagged = Out.Transmittance < FlagTransmittance;
		return Out;
	}

	inline double SkyPulseScale(double FlashNorm, double Gain)
	{
		const double Flash = FlashNorm < 0.0 ? 0.0 : (FlashNorm > 1.0 ? 1.0 : FlashNorm);
		return 1.0 + (Gain > 0.0 ? Gain : 0.0) * Flash;
	}

	inline double TilesWetness(double CardWetness, double Floor)
	{
		const double Wet = CardWetness < 0.0 ? 0.0 : (CardWetness > 1.0 ? 1.0 : CardWetness);
		return Wet > Floor ? Wet : Floor;
	}

	// -- visual round 5, lane L3 (2026-11-10): the distant 2D cloud sheet --
	// Round 3's frames drew thin, streaky volumetric clouds that stopped a few
	// tens of km out and an EMPTY horizon. UE 5.7 still ships
	// /Engine/EngineSky/BP_Sky_Sphere and its panning-cloud materials
	// (M_Sky_Panning_Clouds, M_Sky_Panning_Clouds2, T_Sky_Clouds_M), but a sky
	// sphere covers the SkyAtmosphere, so the far deck is our own sheet: one
	// large disc drooping with the earth's curvature at the deck's altitude,
	// unlit translucent (M_FlightSimDistantClouds, distant_clouds.hlsl: the same
	// Perlin-Worley shape as the volumetric layer at its mid slice, cheap fake
	// lighting), no depth, no custom depth, hidden on every label capture.
	// On the constrained GPU the volumetric march's trace shrinks to the near
	// field the sheet takes over (DistantTracingMaxKm): the engine's sample
	// count is SampleCountMax x saturate(path / r.VolumetricCloud.
	// DistanceToSampleMaxCount), non-decreasing in the path, so a shorter trace
	// never adds a sample, only shortens the step. world_beauty.py DISTANT_* is
	// the twin. UNCALIBRATED: set by probe render on the render machine (every number).
	constexpr double DistantRadiusKm = 300.0;
	constexpr int DistantRings = 48;
	constexpr int DistantSegments = 96;
	constexpr double DistantEarthRadiusKm = 6371.0;
	constexpr double DistantFadeKm = 8.0;
	constexpr double DistantNearFieldKm = 32.0;
	constexpr double DistantInsideRampM = 200.0;
	// world_beauty.DISTANT_LOOK, in order (the material's scalar parameters).
	constexpr int DistantLookCount = 9;
	inline const char* DistantLookName(int Field)
	{
		static const char* const Names[DistantLookCount] = {
			"RimFadeShare", "Albedo", "AmbientGain", "SunWrap", "BaseDarkening", "BaseSunShare",
			"SilverLining", "RimPower", "NormalStrength"};
		return Field >= 0 && Field < DistantLookCount ? Names[Field] : "";
	}
	inline double DistantLook(int Field)
	{
		// Sky step 1: BaseDarkening 0.55 -> 0.70, BaseSunShare 0.15 -> 0.25, SilverLining
		// 0.6 -> 0.8 (the brief's grey-blue bellies and paler far cumulus). UNCALIBRATED.
		static const double Values[DistantLookCount] = {0.2, 0.9, 1.0, 0.3, 0.70, 0.25, 0.8, 8.0, 1.5};
		return Field >= 0 && Field < DistantLookCount ? Values[Field] : 0.0;
	}
	// The cover the sheet takes under a drawn storm cell with no redrawn layer:
	// the nimbostratus row's default (world_beauty.DISTANT_STORM_SHAPE).
	constexpr int DistantStormShape = CloudNimbostratus;
	inline double DistantStormCover(const double* CloudTable)
	{
		return CloudTable != nullptr ? CloudTable[DistantStormShape * CloudFieldCount + CldDefaultCover]
		                             : CloudDefault(DistantStormShape, CldDefaultCover);
	}
	// The disc's size: a centre vertex, then Rings x Segments; a fan, then ring quads.
	inline int DistantDiscVertexCount()
	{
		return 1 + DistantRings * DistantSegments;
	}
	inline int DistantDiscTriangleCount()
	{
		return DistantSegments + 2 * (DistantRings - 1) * DistantSegments;
	}
	// Ring i of N at radius x (i / N)^2: metre-fine near the camera, km-coarse at the rim.
	inline double DistantRingRadiusKm(int Ring, int Rings, double RadiusKm)
	{
		const double Share = Rings > 0 ? (Ring < 0 ? 0.0 : (Ring > Rings ? 1.0 : static_cast<double>(Ring) / Rings)) : 0.0;
		return RadiusKm * Share * Share;
	}
	// The earth's curvature: d^2 / 2R below the sheet's altitude (metres, negative down).
	inline double DistantDroopM(double HorizontalKm)
	{
		return -(HorizontalKm * HorizontalKm / (2.0 * DistantEarthRadiusKm)) * 1000.0;
	}
	inline double DistantDroopAtRimM()
	{
		return DistantDroopM(DistantRadiusKm);
	}
	struct FDistantSheet
	{
		double AltitudeM;
		bool bFromAbove;
		double Fade;
	};
	// A camera below the slab's middle sees BASES (the sheet at the base), above
	// it TOPS (at the top); the fade is 0 inside the slab, 1 past the ramp outside.
	inline FDistantSheet DistantSheetAltitudeM(double CameraM, double BaseM, double TopM)
	{
		FDistantSheet Out;
		const double Mid = 0.5 * (BaseM + TopM);
		Out.bFromAbove = CameraM >= Mid;
		Out.AltitudeM = Out.bFromAbove ? TopM : BaseM;
		double Outside = 0.0;
		if (CameraM < BaseM)
		{
			Outside = BaseM - CameraM;
		}
		else if (CameraM > TopM)
		{
			Outside = CameraM - TopM;
		}
		const double Fade = Outside / DistantInsideRampM;
		Out.Fade = Fade < 0.0 ? 0.0 : (Fade > 1.0 ? 1.0 : Fade);
		return Out;
	}
	// The march's trace with the sheet: constrained and drawn -> the near field
	// (never above the row); every other case the row. Lowers cost, never raises it.
	inline double DistantTracingMaxKm(bool bConstrained, bool bSheetDrawn, double RowKm)
	{
		if (bConstrained && bSheetDrawn)
		{
			return RowKm < DistantNearFieldKm ? RowKm : DistantNearFieldKm;
		}
		return RowKm;
	}
	inline double DistantHandoverKm(double TraceKm)
	{
		return TraceKm - DistantFadeKm > 0.0 ? TraceKm - DistantFadeKm : 0.0;
	}

	// Round 147 (r146 #13, the 747 at 10 km over the ocean: the far deck flat white
	// cut-outs on a uniform navy sea). world_beauty.SHEET_TOPS_* / SEA_HORIZON_LIFT /
	// HIGH_AP_* are the twins. UNCALIBRATED: set by probe render on the render machine.
	// The sheet's tops seen from above (distant_clouds.hlsl TOPS_*): TopRelief under
	// -look-sheet-tops=on (0: round 146's sheet exactly); SeaShadow over the ocean only
	// (the shaded ground is the sea at world z 0); MidZKm the deck's mid height.
	constexpr double SheetTopsRelief = 1.0;
	constexpr double SheetSeaShadow = 0.35;
	inline double SheetTopRelief(bool bOn)
	{
		return bOn ? SheetTopsRelief : 0.0;
	}
	inline double SheetSeaShadowFor(bool bOn, bool bOcean)
	{
		return bOn && bOcean ? SheetSeaShadow : 0.0;
	}
	inline double SheetMidZKm(double BaseM, double TopM)
	{
		return 0.5 * (BaseM + TopM) / 1000.0;
	}
	// (M_FlightSimOceanBeauty generation 7's HorizonLift is FlightSimGoogleTiles.cpp's
	// SeaHorizonLift, set on the sea cap's instance under -look-sea-horizon=on.)
	// -look-high-ap=on: above HighApMinAltitudeM the aerial-perspective LUT (which the
	// translucent distant sheet reads; it clamps past its depth) reaches the camera's
	// horizon sqrt(2 R h), at most HighApMaxKm, never below the march row's depth.
	// The LUT's size is unchanged, so is its cost.
	constexpr double HighApMinAltitudeM = 5000.0;
	constexpr double HighApMaxKm = 360.0;
	inline double HighApLutDepthKm(bool bOn, double CameraM, double RowKm)
	{
		if (!bOn || !(CameraM > HighApMinAltitudeM))
		{
			return RowKm;
		}
		const double HorizonKm = std::sqrt(2.0 * DistantEarthRadiusKm * CameraM / 1000.0);
		const double Capped = HorizonKm < HighApMaxKm ? HorizonKm : HighApMaxKm;
		return Capped > RowKm ? Capped : RowKm;
	}

	// Sky step 6 (the owner's X-Plane-12 brief, 2026-11-15): the high cirrus sheet
	// (core/scene/cirrus.py is the twin). UE draws one volumetric layer; the
	// reference photograph's upper sky is thin cirrus (long translucent wisps with
	// feathered ends, the blue reading through), so a second earth-curved
	// translucent disc (M_FlightSimCirrus, cirrus.hlsl) sits ABOVE the flight at
	// max(CirrusBaseM, camera + CirrusClearanceM), capped at CirrusMaxM: never
	// below the camera, so the owner's clearance rule holds by construction; it
	// fades out over the clearance as the camera climbs into the cap. BEAUTY ONLY,
	// VISUAL ONLY. UNCALIBRATED: set by probe render on the render machine.
	constexpr double CirrusBaseM = 10000.0;
	constexpr double CirrusClearanceM = 1500.0;
	constexpr double CirrusMaxM = 13000.0;
	// The disc: the distant sheet's rings and segments at a larger radius (the
	// sheet is higher, so farther to its horizon); it draws before the distant
	// sheet (-100): farther from every camera it can overlap (design D13).
	constexpr double CirrusRadiusKm = 400.0;
	constexpr int CirrusSortPriority = -101;
	// The cover drawn with no data cover in the plan, or under -cloud-type=cirrus
	// when the data gives none: a stated stylisation (the photograph's upper half
	// is roughly a third veiled), recorded as such. Below CirrusMinDrawnCover
	// nothing is built. The sheet drifts at CirrusWindGain x the card's drift
	// (jet-level winds run faster than the boundary layer's; the plan carries no
	// wind at altitude). UNCALIBRATED.
	constexpr double CirrusDefaultCover = 0.35;
	constexpr double CirrusMinDrawnCover = 0.02;
	constexpr double CirrusWindGain = 2.0;
	// The invariants the host relies on: the higher sheet reaches farther than the
	// distant one and draws before it; the drawn floor is below the default cover.
	static_assert(CirrusRadiusKm > DistantRadiusKm, "the cirrus sheet is higher, so farther to its horizon");
	static_assert(CirrusSortPriority < -100, "the cirrus draws before the distant sheet (-100)");
	static_assert(CirrusMinDrawnCover < CirrusDefaultCover, "the default cover is drawn");
	// The look: the material's scalar parameters (cirrus.CIRRUS_LOOK, in order).
	// UNCALIBRATED: set by probe render on the render machine.
	constexpr int CirrusLookCount = 20;
	inline const char* CirrusLookName(int Field)
	{
		static const char* const Names[CirrusLookCount] = {
			"StreakScaleKm", "StreakAspect", "EdgeSigmas", "FibreStrength", "FibreSharpness", "PatchScaleKm",
			"FlowWarpKm", "FlowLenKm", "HookWarpKm", "HookLenKm", "DetailFade", "OpticalDepth", "MaxOpacity",
			"Albedo", "AmbientGain", "ForwardG", "ForwardShare", "ForwardCap", "RimFadeShare", "SunDirSign"};
		return Field >= 0 && Field < CirrusLookCount ? Names[Field] : "";
	}
	inline double CirrusLook(int Field)
	{
		static const double Values[CirrusLookCount] = {1.5, 6.0, 2.0, 0.92, 6.0, 25.0, 10.0, 30.0, 1.0, 4.0,
		                                               0.5, 0.4, 0.42, 0.95, 1.0, 0.7, 0.6, 8.0, 0.2, 1.0};
		return Field >= 0 && Field < CirrusLookCount ? Values[Field] : 0.0;
	}
	struct FCirrusSheet
	{
		double AltitudeM;
		double Fade;
	};
	// Where the sheet sits for a camera at CameraM (cirrus.cirrus_sheet): never
	// below the camera; fade 1 with the full clearance below it, 0 at the cap.
	inline FCirrusSheet CirrusSheetAltitudeM(double CameraM)
	{
		FCirrusSheet Out;
		const double Lifted = CameraM + CirrusClearanceM > CirrusBaseM ? CameraM + CirrusClearanceM : CirrusBaseM;
		Out.AltitudeM = Lifted < CirrusMaxM ? Lifted : CirrusMaxM;
		const double Fade = (Out.AltitudeM - CameraM) / CirrusClearanceM;
		Out.Fade = Fade < 0.0 ? 0.0 : (Fade > 1.0 ? 1.0 : Fade);
		return Out;
	}
	// Where the drawn cover came from (cirrus.CIRRUS_COVER_SOURCES, in this order).
	enum ECirrusSource
	{
		CirrusSourceOff = 0,
		CirrusSourcePreset = 1,
		CirrusSourceSwitch = 2,
		CirrusSourcePlan = 3,
		CirrusSourceDefault = 4,
	};
	inline const char* CirrusCoverSourceName(int Source)
	{
		static const char* const Names[5] = {"off", "preset", "switch", "plan", "default"};
		return Source >= 0 && Source < 5 ? Names[Source] : "";
	}
	// The cover the host draws (cirrus.cirrus_cover), in order: -look-cirrus=off ->
	// none; a rain or storm preset -> none (the deck covers the sky); -cloud-type=
	// cirrus with no data cover above 0 -> the default; a plan whose cover came
	// from data (cover_inputs present) -> its cirrus_coverage, 0 included (a clear
	// upper sky stays clear); else the default. Clamped 0..1.
	inline double CirrusCover(bool bOff, bool bSwitchCirrus, bool bCoverFromData, double PlanCirrus, int Preset,
	                          int* Source)
	{
		if (bOff)
		{
			*Source = CirrusSourceOff;
			return 0.0;
		}
		if (Preset == PresetRain || Preset == PresetStorm)
		{
			*Source = CirrusSourcePreset;
			return 0.0;
		}
		const double Plan = PlanCirrus < 0.0 ? 0.0 : (PlanCirrus > 1.0 ? 1.0 : PlanCirrus);
		if (bSwitchCirrus && !(bCoverFromData && Plan > 0.0))
		{
			*Source = CirrusSourceSwitch;
			return CirrusDefaultCover;
		}
		if (bCoverFromData)
		{
			*Source = CirrusSourcePlan;
			return Plan;
		}
		*Source = CirrusSourceDefault;
		return CirrusDefaultCover;
	}
	// The streaks' compass bearing (cirrus.cirrus_streak_dir_deg): the card's drift
	// bearing when it drifts (streaks run along the wind), else a seeded one
	// (WorldUnit index 1, channel 0: index 0 is the noise offset's). 0 <= b < 360.
	inline double CirrusStreakDirDeg(uint64_t Seed, double DriftMps, double DriftFromDeg)
	{
		if (DriftMps > 0.0)
		{
			const double Wrapped = std::fmod(DriftFromDeg, 360.0);
			return Wrapped < 0.0 ? Wrapped + 360.0 : Wrapped;
		}
		return WorldUnit(Seed, 1ull, 0ull) * 360.0;
	}
	inline double CirrusDriftMps(double DriftMps)
	{
		return (DriftMps > 0.0 ? DriftMps : 0.0) * CirrusWindGain;
	}

	// Visual round 2 (weather scenes, 2026-11-10), world_beauty.aircraft_clear_layer:
	// BEAUTY ONLY, the aircraft is never drawn INSIDE a deck. Round 1's tower view
	// in heavy rain (an A320 at 1000 m in the 800-3000 m rain deck) and its 747 in
	// a thunderstorm (2000 m in the storm deck) drew the airframe behind hundreds
	// of metres of cloud. A deck whose slab, widened by the clearance, holds the
	// aircraft moves clear of it with its thickness kept: a rain or storm deck goes
	// ABOVE (its rain falls onto the aircraft), any other to the nearer side.
	// UNCALIBRATED: set by probe render on the render machine.
	constexpr double AircraftLayerClearanceM = 400.0;
	struct FLayerClear
	{
		double BaseM;
		double TopM;
		bool bMoved;
		bool bAbove;
	};
	inline FLayerClear AircraftClearLayer(double BaseM, double TopM, double AircraftM, double ClearM,
	                                      bool bRainDeck)
	{
		const double Clear = ClearM > 0.0 ? ClearM : 0.0;
		const double Thick = TopM - BaseM;
		FLayerClear Out{BaseM, TopM, false, true};
		if (!(Thick > 0.0) || AircraftM < BaseM - Clear || AircraftM > TopM + Clear)
		{
			return Out;
		}
		const bool bAbove = bRainDeck || (AircraftM - BaseM) <= (TopM - AircraftM) || AircraftM - Clear <= 0.0;
		if (bAbove)
		{
			Out.BaseM = AircraftM + Clear;
			Out.TopM = Out.BaseM + Thick;
		}
		else
		{
			Out.TopM = AircraftM - Clear;
			Out.BaseM = Out.TopM - Thick > 0.0 ? Out.TopM - Thick : 0.0;
		}
		Out.bMoved = true;
		Out.bAbove = bAbove;
		return Out;
	}
}
// FLIGHTSIM-WORLD-PURE-END

namespace
{
	// The constrained GPU class (round 1 hang): an integrated adapter, or any
	// adapter below SM6 (D3D11 SM5 runs no Lumen, VSM or Nanite either). It takes
	// ef361bd6's cloud and sky settings (FlightSimWorldPure::CloudMarch's row).
	bool CloudConstrainedGpu()
	{
		return GRHIDeviceIsIntegrated || GMaxRHIFeatureLevel < ERHIFeatureLevel::SM6;
	}

	const TCHAR* const WorldCloudMaterialPath =
		TEXT("/Game/FlightSim/M_FlightSimCloudLayers.M_FlightSimCloudLayers");
	// Sky-clouds2 lane: -look-cloud-light=on draws this SEPARATE material (graph 8
	// plus the scattering inputs and cloud_sky_ao.hlsl), so the default
	// M_FlightSimCloudLayers keeps graph 8's shader cost (the light's parameters
	// raised its PS 161 -> 847 instructions, 0 -> 8 samplers, review of 42974c46).
	const TCHAR* const WorldCloudLitMaterialPath =
		TEXT("/Game/FlightSim/M_FlightSimCloudLayersLit.M_FlightSimCloudLayersLit");
	const TCHAR* const WorldTilesMaterialPath =
		TEXT("/Game/FlightSim/M_FlightSimTilesBeauty.M_FlightSimTilesBeauty");
	const TCHAR* const WorldCollectionPath = TEXT("/Game/FlightSim/MPC_FlightSimWorld.MPC_FlightSimWorld");
	// Visual round 5, lane L3: the distant sheet's material and the sky HDRI
	// probe's asset root (core/scene/sky_hdri.py HDRI_ASSET_DIR / HDRI_ASSET_PREFIX).
	const TCHAR* const WorldDistantMaterialPath =
		TEXT("/Game/FlightSim/M_FlightSimDistantClouds.M_FlightSimDistantClouds");
	// Sky step 6: the cirrus sheet's material (scripts/ue_create_materials.py create_world_cirrus).
	const TCHAR* const WorldCirrusMaterialPath =
		TEXT("/Game/FlightSim/M_FlightSimCirrus.M_FlightSimCirrus");
	// The HDRI asset is /Game/FlightSim/Sky/T_SkyHdri_<name> (ApplySkyHdri's Printf
	// literal: FString::Printf takes a literal format).
	// The HDRI fill as a share of the sun's illuminance (sky_hdri.HDRI_FILL_SHARE).
	// UNCALIBRATED: set by probe render on the render machine.
	constexpr double WorldSkyHdriFillShareDefault = 0.15;
	// The engine's simple cloud material, the one the look and the physical
	// sky draw with: only clouds on it are redrawn (never M_StormCell).
	const TCHAR* const WorldEngineCloudNeedle = TEXT("m_SimpleVolumetricCloud");
	// The cloud component's quality in beauty. UNCALIBRATED: set by probe
	// render on the render machine (render time against the clouds' noise).
	// Round 2: the sample counts, the trace and shadow distances are
	// FlightSimWorldPure::CloudMarch / CloudShadowTracingKm (by GPU class).
	constexpr float WorldCloudStopTransmittance = 0.005f;
	// Round 2 (clouds-sky): fog on every cloud-buffer pixel, not only where the
	// coverage is > 0 ("removes visual discontinuities when cloud coverage is
	// close to or flips to 0": VolumetricCloudRendering.cpp help text), so the
	// thin far cloud at the horizon fogs like the sky behind it.
	// UNCALIBRATED: set by probe render on the render machine.
	const TCHAR* const WorldCloudFogAllPixelCvar = TEXT("r.VolumetricCloud.ApplyFogOnAllPixel");
	// Sky step 3: the render commandlet's beauty-path cvars (FlightSimRenderCommandlet.cpp
	// SetBeautyCvar): one owner, so this lane names them in its record and never sets
	// them (world_beauty.RENDER_PATH_CVARS is the twin).
	const TCHAR* const WorldRenderPathCvars[] = {
		TEXT("r.SkyAtmosphere.FastSkyLUT"),
		TEXT("r.SkyAtmosphere.AerialPerspectiveLUT.FastApplyOnOpaque"),
		TEXT("r.SkyAtmosphere.MultiScatteringLUT.HighQuality"),
		TEXT("r.SkyAtmosphere.LUT32"),
		TEXT("r.SkyAtmosphere.SampleCountMax"),
		TEXT("r.SkyAtmosphere.AerialPerspectiveLUT.SampleCountMaxPerSlice"),
		TEXT("r.VolumetricCloud"),
		TEXT("r.VolumetricCloud.HighQualityAerialPerspective"),
		TEXT("r.VolumetricRenderTarget.Mode"),
	};
	constexpr double WorldCmPerMetre = 100.0;
	// world_beauty.STORM_DECK_CLEARANCE_M (lane D, round 26): a storm preset's deck
	// above the aircraft hangs this low over it, so a level chase frame's top is deck.
	constexpr double StormDeckClearanceM = 150.0;

	// Sky step 6: the distant sheet's earth-curved disc (ApplyDistantClouds builds
	// its own inline, pinned by tests/test_distant_clouds.py) as a helper for the
	// cirrus sheet: a fan about the centre, then ring quads, rings densifying
	// towards the centre (FlightSimWorldPure::DistantRingRadiusKm), each dropped by
	// the earth's curvature (DistantDroopM); two-sided material, so the winding is
	// not load-bearing. Section 0, no collision.
	void BuildCurvedDisc(UProceduralMeshComponent* Mesh, double RadiusKm)
	{
		// Function-local: unity builds merge anonymous namespaces (NEXT.md gotcha 3).
		using namespace FlightSimWorldPure;
		TArray<FVector> Vertices;
		TArray<int32> Triangles;
		TArray<FVector> Normals;
		TArray<FVector2D> UV0;
		Vertices.Add(FVector::ZeroVector);
		Normals.Add(FVector::UpVector);
		UV0.Add(FVector2D(0.0, 0.0));
		for (int32 Ring = 1; Ring <= DistantRings; ++Ring)
		{
			const double RingKm = DistantRingRadiusKm(Ring, DistantRings, RadiusKm);
			const double RingCm = RingKm * 1000.0 * WorldCmPerMetre;
			const double ZCm = DistantDroopM(RingKm) * WorldCmPerMetre;
			for (int32 Seg = 0; Seg < DistantSegments; ++Seg)
			{
				const double Angle = 2.0 * PI * Seg / DistantSegments;
				Vertices.Add(FVector(FMath::Cos(Angle) * RingCm, FMath::Sin(Angle) * RingCm, ZCm));
				Normals.Add(FVector::UpVector);
				UV0.Add(FVector2D(static_cast<double>(Ring) / DistantRings, static_cast<double>(Seg) / DistantSegments));
			}
		}
		auto VertexIndex = [](int32 Ring, int32 Seg)
		{
			return Ring <= 0 ? 0 : 1 + (Ring - 1) * DistantSegments + (Seg % DistantSegments);
		};
		for (int32 Seg = 0; Seg < DistantSegments; ++Seg)
		{
			Triangles.Append({VertexIndex(0, 0), VertexIndex(1, Seg), VertexIndex(1, Seg + 1)});
		}
		for (int32 Ring = 1; Ring < DistantRings; ++Ring)
		{
			for (int32 Seg = 0; Seg < DistantSegments; ++Seg)
			{
				const int32 A = VertexIndex(Ring, Seg), B = VertexIndex(Ring, Seg + 1);
				const int32 C = VertexIndex(Ring + 1, Seg), D = VertexIndex(Ring + 1, Seg + 1);
				Triangles.Append({A, C, B, B, C, D});
			}
		}
		check(Vertices.Num() == DistantDiscVertexCount() && Triangles.Num() == 3 * DistantDiscTriangleCount());
		Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0, {}, {}, false);
	}

	double WorldNumber(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, double Default)
	{
		double Value = Default;
		if (Object.IsValid())
		{
			Object->TryGetNumberField(Key, Value);
		}
		return Value;
	}

	FString WorldString(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key)
	{
		FString Value;
		if (Object.IsValid())
		{
			Object->TryGetStringField(Key, Value);
		}
		return Value;
	}

	TSharedPtr<FJsonObject> WorldObject(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key)
	{
		const TSharedPtr<FJsonObject>* Found = nullptr;
		if (Object.IsValid() && Object->TryGetObjectField(Key, Found) && Found != nullptr)
		{
			return *Found;
		}
		return nullptr;
	}

	// The planet's ground albedo: the card's surface, the ground's wetness
	// (FlightSimWorldPure::GroundAlbedoSrgb, world_beauty.ground_albedo_srgb).
	// bNeutral (lane C, the storm preset): the row's luminance as a grey
	// (FlightSimWorldPure::NeutralAlbedoSrgb).
	FColor WorldAlbedo(const FString& Surface, double Wetness, bool bNeutral = false)
	{
		// Function-local: unity builds merge anonymous namespaces (NEXT.md gotcha 3).
		using namespace FlightSimWorldPure;
		int Rgb[3] = {0, 0, 0};
		GroundAlbedoSrgb(GroundSurfaceIndex(TCHAR_TO_ANSI(*Surface)), Wetness, Rgb);
		if (bNeutral)
		{
			const int Row[3] = {Rgb[0], Rgb[1], Rgb[2]};
			NeutralAlbedoSrgb(Row, Rgb);
		}
		return FColor(static_cast<uint8>(FMath::Clamp(Rgb[0], 0, 255)), static_cast<uint8>(FMath::Clamp(Rgb[1], 0, 255)),
		              static_cast<uint8>(FMath::Clamp(Rgb[2], 0, 255)), 255);
	}

	// One look key, read key by key (world_beauty.card_inputs): the card's W3
	// look block when it states the key as a value of this JSON type (its
	// "precipitation" is an object there, never the word), else
	// randomization.look. A W3 look (night, precipitation, cloud_drift) must
	// never hide the sampled haze, cloud layer or wetness.
	TSharedPtr<FJsonValue> WorldLookValue(const TSharedPtr<FJsonObject>& Card, const TCHAR* Key, EJson Type)
	{
		const TSharedPtr<FJsonObject> Looks[2] = {
			WorldObject(Card, TEXT("look")), WorldObject(WorldObject(Card, TEXT("randomization")), TEXT("look"))};
		for (const TSharedPtr<FJsonObject>& Look : Looks)
		{
			const TSharedPtr<FJsonValue> Value = Look.IsValid() ? Look->TryGetField(Key) : nullptr;
			if (Value.IsValid() && Value->Type == Type)
			{
				return Value;
			}
		}
		return nullptr;
	}
}

bool FFlightSimWorldBeauty::LoadOverrides(const FString& Path, FString& Error)
{
	// Function-local: unity builds merge anonymous namespaces (NEXT.md gotcha 3).
	using namespace FlightSimWorldPure;
	FString Text;
	TSharedPtr<FJsonObject> Doc;
	if (!FFileHelper::LoadFileToString(Text, *Path) ||
	    !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Doc) || !Doc.IsValid())
	{
		Error = FString::Printf(TEXT("world_beauty.overrides: %s could not be read as JSON"), *Path);
		return false;
	}
	// The same refusals as core/scene/world_beauty.py validate_overrides: an
	// unknown or misspelt section, a section that is not an object, and a value
	// that is not a JSON number (a bool or a numeric string is refused, never
	// read as 1/0 or parsed) -- a probe file with a typo must not run silently
	// on the defaults.
	for (const TPair<FString, TSharedPtr<FJsonValue>>& Top : Doc->Values)
	{
		if (Top.Key != TEXT("atmosphere") && Top.Key != TEXT("clouds") && Top.Key != TEXT("constants"))
		{
			Error = FString::Printf(TEXT("world_beauty.overrides: unknown section '%s' (atmosphere, clouds, ")
			                        TEXT("constants) in %s"), *Top.Key, *Path);
			return false;
		}
		if (!Top.Value.IsValid() || Top.Value->Type != EJson::Object)
		{
			Error = FString::Printf(TEXT("world_beauty.overrides: %s is not an object (%s)"), *Top.Key, *Path);
			return false;
		}
	}
	auto Section = [&](const TCHAR* Name, int32 Rows, int32 Fields, const char* (*RowName)(int),
	                   const char* (*FieldName)(int), TArray<double>& Values) -> bool
	{
		const TSharedPtr<FJsonObject> Block = WorldObject(Doc, Name);
		if (!Block.IsValid())
		{
			return true;
		}
		for (const TPair<FString, TSharedPtr<FJsonValue>>& RowPair : Block->Values)
		{
			int32 Row = -1;
			for (int32 I = 0; I < Rows; ++I)
			{
				if (RowPair.Key == ANSI_TO_TCHAR(RowName(I)))
				{
					Row = I;
				}
			}
			const TSharedPtr<FJsonObject>* RowObject = nullptr;
			if (Row < 0 || !RowPair.Value.IsValid() || !RowPair.Value->TryGetObject(RowObject) ||
			    RowObject == nullptr)
			{
				Error = FString::Printf(TEXT("world_beauty.overrides: %s.%s is not a row (%s)"), Name,
				                        *RowPair.Key, *Path);
				return false;
			}
			for (const TPair<FString, TSharedPtr<FJsonValue>>& FieldPair : (*RowObject)->Values)
			{
				int32 Field = -1;
				for (int32 F = 0; F < Fields; ++F)
				{
					if (FieldPair.Key == ANSI_TO_TCHAR(FieldName(F)))
					{
						Field = F;
					}
				}
				double Value = 0.0;
				if (Field < 0 || !FieldPair.Value.IsValid() || FieldPair.Value->Type != EJson::Number ||
				    !FieldPair.Value->TryGetNumber(Value))
				{
					Error = FString::Printf(TEXT("world_beauty.overrides: %s.%s.%s is not a numeric field (%s)"),
					                        Name, *RowPair.Key, *FieldPair.Key, *Path);
					return false;
				}
				Values[Row * Fields + Field] = Value;
				Overridden.Add(FString::Printf(TEXT("%s.%s.%s=%g"), Name, *RowPair.Key, *FieldPair.Key, Value));
			}
		}
		return true;
	};
	if (!Section(TEXT("atmosphere"), PresetCount, AtmosphereFieldCount, &PresetName, &AtmosphereFieldName,
	             AtmosphereValues) ||
	    !Section(TEXT("clouds"), CloudCount, CloudFieldCount, &CloudName, &CloudFieldName, CloudValues))
	{
		return false;
	}
	const TSharedPtr<FJsonObject> Constants = WorldObject(Doc, TEXT("constants"));
	if (Constants.IsValid())
	{
		struct FConstantSlot
		{
			const TCHAR* Name;
			double* Slot;
		};
		const FConstantSlot Slots[] = {
			{TEXT("cloud_extinction_scale"), &CloudExtinctionScale},
			{TEXT("occlusion_flag_transmittance"), &OcclusionFlagTransmittance},
			{TEXT("lightning_reference_lux"), &LightningReferenceLux},
			{TEXT("detail_fade_m"), &DetailFadeM},
			{TEXT("detail_scale_m"), &DetailScaleM},
			{TEXT("puddle_share_of_wetness"), &PuddleShare},
			{TEXT("tiles_dehaze"), &TilesDehaze},
			{TEXT("tiles_saturation"), &TilesSaturation},
		};
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : Constants->Values)
		{
			double* Slot = nullptr;
			for (const FConstantSlot& Candidate : Slots)
			{
				if (Pair.Key == Candidate.Name)
				{
					Slot = Candidate.Slot;
				}
			}
			double Value = 0.0;
			if (Slot == nullptr || !Pair.Value.IsValid() || Pair.Value->Type != EJson::Number ||
			    !Pair.Value->TryGetNumber(Value))
			{
				Error = FString::Printf(TEXT("world_beauty.overrides: constants.%s is not a numeric constant (%s)"),
				                        *Pair.Key, *Path);
				return false;
			}
			*Slot = Value;
			Overridden.Add(FString::Printf(TEXT("constants.%s=%g"), *Pair.Key, Value));
		}
	}
	return true;
}

bool FFlightSimWorldBeauty::StormNeutralAlbedo() const
{
	return Preset == FlightSimWorldPure::PresetStorm && StormAlbedoSwitch != TEXT("surface");
}

bool FFlightSimWorldBeauty::Build(UWorld* World, const TCHAR* Params, const TSharedPtr<FJsonObject>& Card,
                                  AActor* Aircraft, AGeoReferencingSystem* GeoReferencing,
                                  FFlightSimVisualScene& Scene, FFlightSimWeather& Weather,
                                  FFlightSimGoogleTiles& Tiles, const FFlightSimSkyPlan* SkyPlan, FString& Error)
{
	// Function-local: unity builds merge anonymous namespaces (NEXT.md gotcha 3).
	using namespace FlightSimWorldPure;
	bBuilt = false;
	Record = MakeShared<FJsonObject>();
	Frames.Reset();
	MaxOccludedFraction = 0.0;
	OcclusionFrames = 0;
	OcclusionFlaggedFrames = 0;
	OcclusionIncompleteFrames = 0;
	CloudLayers.Reset();
	Overridden.Reset();
	WeatherRef = &Weather;
	{
		// The commandlet's own test for a physical sky (FlightSimRenderCommandlet.cpp
		// SkyPlanPath): -sky=<plan>.
		FString SkyPlanArg;
		bPhysicalSkyPlan = FParse::Value(Params, TEXT("sky="), SkyPlanArg) && !SkyPlanArg.IsEmpty();
		// Visual round 6: -deck-shadow=on|off, the command line or
		// FLIGHTSIM_RENDER_SWITCHES (the round 5 probes' channel); the
		// default is the planned render (on). Read in ApplyClouds.
		DeckShadowSwitch = TEXT("on");
		const FString Switches = FString(Params != nullptr ? Params : TEXT("")) + TEXT(" ")
			+ FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"));
		FParse::Value(*Switches, TEXT("deck-shadow="), DeckShadowSwitch);
		FairShadowSwitch = TEXT("off");
		FParse::Value(*Switches, TEXT("fair-cloud-shadows="), FairShadowSwitch);
		// Lane C (round 7's green #10): -storm-ground-albedo=neutral|surface,
		// neutral by default (StormNeutralAlbedo); surface is the A/B.
		StormAlbedoSwitch = TEXT("neutral");
		FParse::Value(*Switches, TEXT("storm-ground-albedo="), StormAlbedoSwitch);
		// #02 blue (2026-11-11): -tiles-shade-neutral=on|off, on by default
		// (FlightSimTilesShade; ApplyTiles sets ShadeNeutralAmount from it).
		TilesShadeSwitch = TEXT("on");
		FParse::Value(*Switches, TEXT("tiles-shade-neutral="), TilesShadeSwitch);
		// Round 147 (#06's quilted bay): -tiles-water-unify=on|off|<0..1>, on by default
		// (FlightSimTilesWater; ApplyTiles sets WaterUnifyAmount from it).
		TilesWaterSwitch = TEXT("on");
		FParse::Value(*Switches, TEXT("tiles-water-unify="), TilesWaterSwitch);
		// Round 52: -look-cloud-tiers=on|off (on by default): the cloud
		// material's shadow-sample footprint (CloudShadowFootprintPerSqrtKm) and
		// side bulge (CloudSideBulgeFor); off is round 51's clouds exactly.
		// Another word refuses by name.
		CloudTiersSwitch = TEXT("on");
		FParse::Value(*Switches, TEXT("look-cloud-tiers="), CloudTiersSwitch);
		// Round 82: -look-cloud-billow=on|off (on by default): the cumulus edge,
		// billows, base (CloudBillowRow, CloudHeightDensityFor, CloudBottomOcclusionFor);
		// off is round 81's clouds exactly. Another word refuses by name.
		CloudBillowSwitch = TEXT("on");
		FParse::Value(*Switches, TEXT("look-cloud-billow="), CloudBillowSwitch);
		// Sky step 2: -cloud-type=<word> (empty = not given): the owner's probe over
		// the plan's and the card's type (FlightSimWorldPure::LayerSource; the
		// existing -cloud-cover= probe builds a CARD layer, the wrong component for
		// this). Another word refuses by name.
		CloudTypeSwitch.Reset();
		FParse::Value(*Switches, TEXT("cloud-type="), CloudTypeSwitch);
		// Sky step 3: -cloud-march=auto|constrained|discrete|probe (auto by default:
		// the GPU class, as before). A named tier is the owner's measurement on any
		// GPU (FlightSimWorldPure::CloudMarchFor, CloudMarch, CloudCvar); another
		// word refuses by name.
		CloudMarchSwitch = TEXT("auto");
		FParse::Value(*Switches, TEXT("cloud-march="), CloudMarchSwitch);
		// Sky step 6: -look-cirrus=on|off (off by default since cirrus generation 2,
		// lane sky-cirrus2: off until it reads as a photograph by eye): the high
		// cirrus sheet (ApplyCirrus); off builds none (the round-95 upper sky).
		// Another word refuses by name.
		CirrusSwitch = TEXT("off");
		FParse::Value(*Switches, TEXT("look-cirrus="), CirrusSwitch);
		// Sky step 4: -sky-multi-scatter=auto|on|off (auto by default: the row's
		// MultiScatteringFactor on a discrete GPU, the class gate kept; on = every class; off is ef361bd6's sky for the
		// A/B). FlightSimWorldPure::SkyMultiScatterFor; another word refuses by name.
		SkyMultiScatterSwitch = TEXT("auto");
		FParse::Value(*Switches, TEXT("sky-multi-scatter="), SkyMultiScatterSwitch);
		// Lane sky-atmosphere: -look-sky-gradient=on|off (on by default; off is
		// claude/hl-sky's sky). FlightSimWorldPure::SkyGradientFor.
		SkyGradientSwitch = TEXT("on");
		FParse::Value(*Switches, TEXT("look-sky-gradient="), SkyGradientSwitch);
		// Fix lane sun-color: -sky-capture-veil=on|off (on by default; off is round
		// 144's sky light capture). FlightSimWorldPure::SkyCaptureVeilFor.
		SkyCaptureVeilSwitch = TEXT("on");
		FParse::Value(*Switches, TEXT("sky-capture-veil="), SkyCaptureVeilSwitch);
		// Sky step 1: -look-cloud-wisp=on|off (on by default): the cumulus and
		// stratocumulus wisp (CloudWispRow, CloudBellyOcclusion); off is round 95's
		// clouds exactly. Another word refuses by name.
		CloudWispSwitch = TEXT("on");
		FParse::Value(*Switches, TEXT("look-cloud-wisp="), CloudWispSwitch);
		// Sky-clouds lane: -look-cloud-light=on|off (OFF by default until Windows shows it; CloudLightRow,
		// CloudLightBillow; off is c9e13c53's clouds) and -cloud-material=ours|epic
		// (ours by default; epic is the Volumetrics plugin's cloud material for the A/B).
		CloudLightSwitch = TEXT("off");
		FParse::Value(*Switches, TEXT("look-cloud-light="), CloudLightSwitch);
		// Round 147 (r146 #13): -look-sheet-tops=on|off (the distant sheet's tops seen from
		// above, and their shadows on the sea) and -look-high-ap=on|off (the aerial-
		// perspective LUT to the horizon for a high camera). On by default; anything
		// but "off" draws as on.
		SheetTopsSwitch = TEXT("on");
		FParse::Value(*Switches, TEXT("look-sheet-tops="), SheetTopsSwitch);
		HighApSwitch = TEXT("on");
		FParse::Value(*Switches, TEXT("look-high-ap="), HighApSwitch);
		// Lane rain-grey: -cloud-deck-scatter=round95|beauty (CloudDeckScatterFor).
		CloudDeckScatterSwitch = TEXT("beauty");
		FParse::Value(*Switches, TEXT("cloud-deck-scatter="), CloudDeckScatterSwitch);
		CloudMaterialSwitch = TEXT("auto");   // r150
		FParse::Value(*Switches, TEXT("cloud-material="), CloudMaterialSwitch);
		// Impostor A/B (0deddc6d): -cloud-volumetric-scale=<0..1> (1 by default)
		// thins every volumetric layer's drawn cover; 0 hides the layer
		// (ApplyClouds, CloudVolumetricCoverage). Not a number, or outside
		// 0..1, refuses by name.
		CloudVolumetricScale = CloudVolumetricScaleDefault;
		CloudVolumetricScaleText.Reset();
		FParse::Value(*Switches, TEXT("cloud-volumetric-scale="), CloudVolumetricScaleText);
	}
	if (!CloudVolumetricScaleText.IsEmpty())
	{
		const bool bNumber = FCString::IsNumeric(*CloudVolumetricScaleText);
		const double Scale = bNumber ? FCString::Atod(*CloudVolumetricScaleText) : -1.0;
		if (!bNumber || !(Scale >= 0.0 && Scale <= 1.0))
		{
			Error = FString::Printf(TEXT("world_beauty.clouds: -cloud-volumetric-scale=%s is not a number in 0..1"),
			                        *CloudVolumetricScaleText);
			return false;
		}
		CloudVolumetricScale = Scale;
	}
	if (CloudTiersSwitch != TEXT("on") && CloudTiersSwitch != TEXT("off"))
	{
		Error = FString::Printf(TEXT("world_beauty.clouds: -look-cloud-tiers=%s is not on or off"),
		                        *CloudTiersSwitch);
		return false;
	}
	if (CloudBillowSwitch != TEXT("on") && CloudBillowSwitch != TEXT("off"))
	{
		Error = FString::Printf(TEXT("world_beauty.clouds: -look-cloud-billow=%s is not on or off"),
		                        *CloudBillowSwitch);
		return false;
	}
	if (!CloudTypeSwitch.IsEmpty() && PlanCloudTypeIndex(TCHAR_TO_ANSI(*CloudTypeSwitch)) == PlanCloudUnknown)
	{
		Error = FString::Printf(TEXT("world_beauty.clouds: -cloud-type=%s is not one of clear, cumulus, stratocumulus, "
		                             "altocumulus, cirrus, overcast, nimbostratus"), *CloudTypeSwitch);
		return false;
	}
	if (CloudMarchFor(TCHAR_TO_ANSI(*CloudMarchSwitch), false) < 0)
	{
		Error = FString::Printf(TEXT("world_beauty.clouds: -cloud-march=%s is not auto, constrained, discrete or probe"),
		                        *CloudMarchSwitch);
		return false;
	}
	if (SkyMultiScatterFor(TCHAR_TO_ANSI(*SkyMultiScatterSwitch), false) < 0)
	{
		Error = FString::Printf(TEXT("world_beauty.clouds: -sky-multi-scatter=%s is not auto, on or off"),
		                        *SkyMultiScatterSwitch);
		return false;
	}
	if (SkyGradientFor(TCHAR_TO_ANSI(*SkyGradientSwitch)) < 0)
	{
		Error = FString::Printf(TEXT("world_beauty.sky_gradient: -look-sky-gradient=%s is not on or off"),
		                        *SkyGradientSwitch);
		return false;
	}
	if (SkyCaptureVeilFor(TCHAR_TO_ANSI(*SkyCaptureVeilSwitch)) < 0)
	{
		Error = FString::Printf(TEXT("world_beauty.sky_capture_veil: -sky-capture-veil=%s is not on or off"),
		                        *SkyCaptureVeilSwitch);
		return false;
	}
	if (CirrusSwitch != TEXT("on") && CirrusSwitch != TEXT("off"))
	{
		Error = FString::Printf(TEXT("world_beauty.cirrus: -look-cirrus=%s is not on or off"), *CirrusSwitch);
		return false;
	}
	// Sky step 2: the -sky= plan's cloud fields, read in ApplyClouds (nullptr without a plan).
	SkyPlanRef = SkyPlan;
	// Sky step 5: the plan's march_tier (the step 3 cvar set it asks for) stands in
	// for an unstated -cloud-march= (FlightSimWorldPure::CloudMarchWordInForce):
	// switch (not auto) > plan (a known word) > auto. The word parsed is kept as
	// CloudMarchSwitchGiven; CloudMarchSwitch is the word in force from here on, so
	// ApplyClouds and ApplyDistantClouds resolve the same tier as before this step.
	CloudMarchSwitchGiven = CloudMarchSwitch;
	{
		const FString PlanTier = SkyPlan != nullptr ? SkyPlan->CloudMarchTier : FString();
		// (the out pointer aliases a TCHAR_TO_ANSI temporary: the word is taken from
		// the source index, never from the pointer)
		const char* WordInForce = "auto";
		const int32 WordSource = CloudMarchWordInForce(TCHAR_TO_ANSI(*CloudMarchSwitch),
		                                               TCHAR_TO_ANSI(*PlanTier), &WordInForce);
		CloudMarchSwitch = WordSource == MarchWordPlan ? PlanTier
			: (WordSource == MarchWordSwitch ? CloudMarchSwitchGiven : FString(TEXT("auto")));
		CloudMarchWordSource = ANSI_TO_TCHAR(MarchWordSourceName(WordSource));
		if (WordSource != MarchWordPlan && !PlanTier.IsEmpty() && PlanTier != TEXT("auto")
		    && CloudMarchFor(TCHAR_TO_ANSI(*PlanTier), false) < 0)
		{
			CloudMarchWordSource += TEXT(" (plan march_tier unknown, ignored)");
		}
	}
	if (CloudWispSwitch != TEXT("on") && CloudWispSwitch != TEXT("off"))
	{
		Error = FString::Printf(TEXT("world_beauty.clouds: -look-cloud-wisp=%s is not on or off"),
		                        *CloudWispSwitch);
		return false;
	}
	if (CloudLightSwitch != TEXT("on") && CloudLightSwitch != TEXT("off"))
	{
		Error = FString::Printf(TEXT("world_beauty.clouds: -look-cloud-light=%s is not on or off"),
		                        *CloudLightSwitch);
		return false;
	}
	if (CloudDeckScatterFor(TCHAR_TO_ANSI(*CloudDeckScatterSwitch)) < 0)
	{
		Error = FString::Printf(TEXT("world_beauty.clouds: -cloud-deck-scatter=%s is not round95 or beauty"),
		                        *CloudDeckScatterSwitch);
		return false;
	}
	if (CloudMaterialSwitch != TEXT("auto") && CloudMaterialSwitch != TEXT("ours") && CloudMaterialSwitch != TEXT("epic") &&
	    CloudMaterialSwitch != TEXT("engine"))
	{
		Error = FString::Printf(TEXT("world_beauty.clouds: -cloud-material=%s is not auto, ours, epic or engine"),
		                        *CloudMaterialSwitch);
		return false;
	}

	// The tables in force: the pure block's defaults, then any overrides.
	AtmosphereValues.SetNumZeroed(PresetCount * AtmosphereFieldCount);
	for (int32 P = 0; P < PresetCount; ++P)
	{
		for (int32 F = 0; F < AtmosphereFieldCount; ++F)
		{
			AtmosphereValues[P * AtmosphereFieldCount + F] = AtmosphereDefault(P, F);
		}
	}
	CloudValues.SetNumZeroed(CloudCount * CloudFieldCount);
	for (int32 C = 0; C < CloudCount; ++C)
	{
		for (int32 F = 0; F < CloudFieldCount; ++F)
		{
			CloudValues[C * CloudFieldCount + F] = CloudDefault(C, F);
		}
	}
	CloudExtinctionScale = CloudExtinctionScaleDefault;
	OcclusionFlagTransmittance = OcclusionFlagTransmittanceDefault;
	LightningReferenceLux = LightningReferenceLuxDefault;
	DetailFadeM = DetailFadeMDefault;
	DetailScaleM = DetailScaleMDefault;
	PuddleShare = PuddleShareDefault;
	TilesDehaze = TilesDehazeDefault;
	TilesSaturation = TilesSaturationDefault;
	GroundWetness = 0.0;
	Surface.Reset();

	FString CloudsMode = TEXT("card");
	// The flag, else the environment (the web app's renders reach these without
	// a webapp change: FLIGHTSIM_WORLD_BEAUTY_OVERRIDES, FLIGHTSIM_GROUND_SCATTER,
	// FLIGHTSIM_BEAUTY_CLOUDS).
	auto FlagOrEnv = [Params](const TCHAR* Flag, const TCHAR* Env)
	{
		FString Value;
		if (!FParse::Value(Params, Flag, Value) || Value.IsEmpty())
		{
			Value = FPlatformMisc::GetEnvironmentVariable(Env).TrimStartAndEnd();
		}
		return Value;
	};
	const FString CloudsFromEnv = FlagOrEnv(TEXT("beauty-clouds="), TEXT("FLIGHTSIM_BEAUTY_CLOUDS"));
	if (!CloudsFromEnv.IsEmpty())
	{
		CloudsMode = CloudsFromEnv;
	}
	if (CloudsMode != TEXT("card") && CloudsMode != TEXT("fair") && CloudsMode != TEXT("engine"))
	{
		Error = FString::Printf(TEXT("world_beauty.clouds: -beauty-clouds=%s is not one of card, fair, engine"),
		                        *CloudsMode);
		return false;
	}
	const FString OverridesPath = FlagOrEnv(TEXT("world-beauty-overrides="), TEXT("FLIGHTSIM_WORLD_BEAUTY_OVERRIDES"));
	if (!OverridesPath.IsEmpty() && !LoadOverrides(OverridesPath, Error))
	{
		return false;
	}
	const FString ScatterPath = FlagOrEnv(TEXT("ground-scatter="), TEXT("FLIGHTSIM_GROUND_SCATTER"));
	// Visual round 5, lane L3: the distant sheet (on unless asked off) and the
	// sky HDRI probe (off unless named): -distant-clouds= / FLIGHTSIM_DISTANT_CLOUDS,
	// -sky-hdri= / FLIGHTSIM_SKY_HDRI.
	FString DistantMode = TEXT("on");
	const FString DistantFromEnv = FlagOrEnv(TEXT("distant-clouds="), TEXT("FLIGHTSIM_DISTANT_CLOUDS"));
	if (!DistantFromEnv.IsEmpty())
	{
		DistantMode = DistantFromEnv;
	}
	if (DistantMode != TEXT("on") && DistantMode != TEXT("off"))
	{
		Error = FString::Printf(TEXT("world_beauty.distant_clouds: -distant-clouds=%s is not on or off"), *DistantMode);
		return false;
	}
	const FString SkyHdriName = FlagOrEnv(TEXT("sky-hdri="), TEXT("FLIGHTSIM_SKY_HDRI"));
	// Lane D (2026-11-11): the beauty rain veil (on unless asked off): -rain-veil= /
	// FLIGHTSIM_RAIN_VEIL (core/scene/rain_veil.py).
	FString RainVeilMode = TEXT("on");
	const FString RainVeilFromEnv = FlagOrEnv(TEXT("rain-veil="), TEXT("FLIGHTSIM_RAIN_VEIL"));
	if (!RainVeilFromEnv.IsEmpty())
	{
		RainVeilMode = RainVeilFromEnv;
	}
	if (RainVeilMode != TEXT("on") && RainVeilMode != TEXT("off"))
	{
		Error = FString::Printf(TEXT("world_beauty.rain_veil: -rain-veil=%s is not on or off"), *RainVeilMode);
		return false;
	}
	// Round 47 (#07's flat grey field through a 250 mm lens): the veil's falling
	// curtains shrink with the lens (on) or keep generation 5's cells (off), from the
	// command line or FLIGHTSIM_RENDER_SWITCHES like -deck-shadow=.
	FString VeilLensCellsSwitch = TEXT("on");
	{
		const FString Switches = FString(Params != nullptr ? Params : TEXT("")) + TEXT(" ")
			+ FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"));
		FParse::Value(*Switches, TEXT("veil-lens-cells="), VeilLensCellsSwitch);
	}
	if (VeilLensCellsSwitch != TEXT("on") && VeilLensCellsSwitch != TEXT("off"))
	{
		Error = FString::Printf(TEXT("world_beauty.rain_veil: -veil-lens-cells=%s is not on or off"),
		                        *VeilLensCellsSwitch);
		return false;
	}
	Weather.SetBeautyVeilLensCells(VeilLensCellsSwitch == TEXT("on"));
	// Round 147 (#07's flat grey wall): -rain-depth=on|off, on by default: each curtain
	// shell its own tone and contrast (FlightSimRainVeil::VeilDepthShade / VeilDepthVary).
	FString RainDepthSwitch = TEXT("on");
	{
		const FString Switches = FString(Params != nullptr ? Params : TEXT("")) + TEXT(" ")
			+ FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"));
		FParse::Value(*Switches, TEXT("rain-depth="), RainDepthSwitch);
	}
	if (RainDepthSwitch != TEXT("on") && RainDepthSwitch != TEXT("off"))
	{
		Error = FString::Printf(TEXT("world_beauty.rain_veil: -rain-depth=%s is not on or off"), *RainDepthSwitch);
		return false;
	}
	Weather.SetBeautyRainDepth(RainDepthSwitch == TEXT("on"));

	// -- what the card says --------------------------------------------------
	// Key by key (WorldLookValue; world_beauty.card_inputs is the Python twin):
	// card.look when it states the key, else card.randomization.look.
	auto LookNumber = [&Card](const TCHAR* Key)
	{
		const TSharedPtr<FJsonValue> Value = WorldLookValue(Card, Key, EJson::Number);
		return Value.IsValid() ? Value->AsNumber() : 0.0;
	};
	const TSharedPtr<FJsonObject> WeatherLook = WorldObject(Card, TEXT("weather_look"));
	const double VisibilityKm = LookNumber(TEXT("visibility_km"));
	const double RainRate = FMath::Max(LookNumber(TEXT("precipitation_rate_mmh")),
	                                   WorldNumber(WeatherLook, TEXT("rain_rate_mmh"), 0.0));
	const TSharedPtr<FJsonValue> RainWord = WorldLookValue(Card, TEXT("precipitation"), EJson::String);
	const bool bRainWord = RainWord.IsValid() && RainWord->AsString() == TEXT("rain");
	// The storm words are ONE list (FlightSimWorldPure::StormWord, weather_look.STORMS):
	// a tornado is a storm here exactly as it is for beauty_look's grade.
	const FString StormWordValue = WorldString(WeatherLook, TEXT("storm"));
	const bool bStorm = IsStormWord(TCHAR_TO_ANSI(*StormWordValue)) || Weather.DrawsCell();
	Surface = WorldString(WeatherLook, TEXT("surface"));
	double CardCover = 0.0, CardBaseM = 0.0, CardTopM = 0.0;
	bool bCardLayer = false;
	const TSharedPtr<FJsonValue> CloudsValue = WorldLookValue(Card, TEXT("clouds"), EJson::Array);
	if (CloudsValue.IsValid() && CloudsValue->AsArray().Num() > 0)
	{
		const TSharedPtr<FJsonObject>* LayerJson = nullptr;
		if (CloudsValue->AsArray()[0]->TryGetObject(LayerJson) && LayerJson != nullptr)
		{
			CardCover = WorldNumber(*LayerJson, TEXT("cover"), 0.0);
			CardBaseM = WorldNumber(*LayerJson, TEXT("base_m"), 0.0);
			CardTopM = WorldNumber(*LayerJson, TEXT("top_m"), 0.0);
			bCardLayer = CardTopM > CardBaseM;
		}
	}
	const double CardWetness = FMath::Max(LookNumber(TEXT("wetness")),
	                                      WorldNumber(WeatherLook, TEXT("wetness"), 0.0));
	const int32 Seed = static_cast<int32>(WorldNumber(WeatherLook, TEXT("seed"),
	                                                  WorldNumber(Card, TEXT("seed"), 0.0)));
	// Lane D: the card's wind (world_beauty.card_wind_mps): the larger of the storm
	// weather's wind at the camera and the wind at cloud base.
	double WindMps = 0.0;
	{
		const TSharedPtr<FJsonObject> WeatherBlock = WorldObject(Card, TEXT("weather"));
		const TSharedPtr<FJsonObject> RainBlock = WorldObject(WeatherBlock, TEXT("rain"));
		const TArray<TSharedPtr<FJsonValue>>* WindArray = nullptr;
		if (RainBlock.IsValid() && RainBlock->TryGetArrayField(TEXT("wind_enu_mps"), WindArray) &&
		    WindArray != nullptr && WindArray->Num() == 3)
		{
			double SumSquares = 0.0;
			for (const TSharedPtr<FJsonValue>& Component : *WindArray)
			{
				const double C = Component.IsValid() ? Component->AsNumber() : 0.0;
				SumSquares += C * C;
			}
			WindMps = FMath::Sqrt(SumSquares);
		}
		const TSharedPtr<FJsonValue> WindDrift = WorldLookValue(Card, TEXT("cloud_drift"), EJson::Object);
		double DriftWind = 0.0;
		if (WindDrift.IsValid() && WindDrift->AsObject()->TryGetNumberField(TEXT("mps"), DriftWind))
		{
			WindMps = FMath::Max(WindMps, DriftWind);
		}
		if (!FMath::IsFinite(WindMps))
		{
			WindMps = 0.0;
		}
	}
	const bool bSevereRain = IsSevereRain(RainRate, WindMps);
	Preset = SelectPreset(bStorm, RainRate, bRainWord, bCardLayer ? CardCover : 0.0, VisibilityKm, WindMps);
	GroundWetness = TilesWetness(CardWetness, AtmosphereValues[Preset * AtmosphereFieldCount + AtmWetnessFloor]);
	const TSharedPtr<FJsonValue> DriftValue = WorldLookValue(Card, TEXT("cloud_drift"), EJson::Object);
	if (DriftValue.IsValid())
	{
		DriftValue->AsObject()->TryGetNumberField(TEXT("mps"), DriftMps);
		DriftValue->AsObject()->TryGetNumberField(TEXT("from_deg"), DriftFromDeg);
	}
	else
	{
		DriftMps = LookNumber(TEXT("cloud_drift_mps"));
		DriftFromDeg = LookNumber(TEXT("cloud_drift_from_deg"));
	}

	Record->SetStringField(TEXT("quality"), TEXT("beauty"));
	Record->SetStringField(TEXT("preset"), ANSI_TO_TCHAR(PresetName(Preset)));
	{
		TSharedPtr<FJsonObject> Inputs = MakeShared<FJsonObject>();
		Inputs->SetNumberField(TEXT("visibility_km"), VisibilityKm);
		Inputs->SetNumberField(TEXT("rain_rate_mmh"), RainRate);
		Inputs->SetBoolField(TEXT("precipitation_rain"), bRainWord);
		Inputs->SetBoolField(TEXT("storm"), bStorm);
		Inputs->SetNumberField(TEXT("wind_mps"), WindMps);
		Inputs->SetBoolField(TEXT("severe_rain"), bSevereRain);
		Inputs->SetStringField(TEXT("severe_rain_basis"),
			TEXT("world_beauty.is_severe_rain: rain >= 8 mm/h in wind >= 10 m/s (the larger of weather.rain.wind_enu_mps "
			     "and look.cloud_drift.mps) draws the storm preset; visual only, UNCALIBRATED"));
		Inputs->SetStringField(TEXT("storm_word"), StormWordValue);
		Inputs->SetStringField(TEXT("storm_words"), TEXT("weather_look.STORMS (thunderstorm, tornado), or a drawn storm cell"));
		Inputs->SetStringField(TEXT("surface"), Surface);
		Inputs->SetNumberField(TEXT("ground_wetness"), GroundWetness);
		Inputs->SetStringField(TEXT("look_basis"),
			TEXT("per key: card.look when it states the key, else card.randomization.look (world_beauty.card_inputs)"));
		Inputs->SetNumberField(TEXT("card_cover"), bCardLayer ? CardCover : 0.0);
		Inputs->SetNumberField(TEXT("card_wetness"), CardWetness);
		Inputs->SetNumberField(TEXT("seed"), Seed);
		Record->SetObjectField(TEXT("inputs"), Inputs);
	}
	Record->SetStringField(TEXT("calibration"),
		TEXT("UNCALIBRATED: every look value is set by probe render on the render machine "
		     "(docs/visual/PROBE_LOG.md ## world; core/scene/world_beauty.py is the table)"));
	{
		TArray<TSharedPtr<FJsonValue>> Lines;
		for (const FString& Line : Overridden)
		{
			Lines.Add(MakeShared<FJsonValueString>(Line));
		}
		Record->SetArrayField(TEXT("overridden"), Lines);
		Record->SetStringField(TEXT("overrides_file"), OverridesPath);
	}
	Record->SetStringField(TEXT("visual_only"),
		TEXT("nothing here reaches the flight model; the measure quality never builds it"));

	ApplyAtmosphere(World, Scene, VisibilityKm, Aircraft);
	// dust-humidity-haze (FlightSimDustHaze.h): RH growth, dust tint, the boundary-layer cap.
	TSharedPtr<FJsonObject> DustOut;
	DustHaze.Apply(World, Scene, Params, Card, VisibilityKm, WorldObject(Record, TEXT("atmosphere")), DustOut);
	Record->SetObjectField(TEXT("dust_haze"), DustOut);
	ApplyClouds(World, Scene, Weather, CloudsMode, bCardLayer ? CardCover : -1.0, CardBaseM, CardTopM, Seed);
	// Visual round 2 (weather scenes): no deck, and no storm tower, drawn around the aircraft.
	KeepAircraftClearOfClouds(Card, Aircraft, Weather);
	// Visual round 5, lane L3: the far deck and the horizon (after the clearance:
	// the sheet follows the slab that is drawn), then the sky HDRI probe.
	ApplyDistantClouds(World, Scene, Weather, DistantMode, Seed);
	// Round 147 (r146 #13): the aerial-perspective LUT to the horizon for a high camera.
	ApplyHighAltitudeAerialPerspective(Aircraft);
	// Sky step 6: the high cirrus sheet, above everything the layers drew (its
	// cover is the plan's data or the stated default; -look-cirrus=off builds none).
	ApplyCirrus(World, Scene, Seed);
	if (!ApplySkyHdri(Scene, SkyHdriName, Params, Error))
	{
		return false;
	}
	// The sun's elevation scales the tiles' shade neutraliser (FlightSimTilesShade::SunScale):
	// the light travels along the light's forward vector, so the sun is up by -Forward.Z.
	double SunElevationDeg = 90.0;
	if (Scene.Sun != nullptr)
	{
		const FVector Forward = Scene.Sun->GetActorForwardVector();
		SunElevationDeg = FMath::RadiansToDegrees(FMath::Asin(FMath::Clamp(-Forward.Z, -1.0, 1.0)));
	}
	// Round 148 (FlightSimHdriSky.h): -look-hdri=auto|light|off (auto by default).
	// After the -sky-hdri= probe, which it leaves alone; the switch itself waits
	// for the commandlet's sky light capture (SwitchSkyLightToHdri).
	{
		const FString HdriSwitches = FString(Params != nullptr ? Params : TEXT("")) + TEXT(" ")
			+ FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"));
		if (!HdriSky.Build(World, Scene, Preset, SunElevationDeg, HdriSwitches, Error))
		{
			return false;
		}
		Record->SetObjectField(TEXT("hdri_sky"), HdriSky.Record);
	}
	ApplyTiles(World, Tiles, CardWetness, SunElevationDeg);
	// sun-shafts-sky-occlusion (FlightSimSunShafts.h): value-only, after the presets.
	TSharedPtr<FJsonObject> SunShaftsOut;
	SunShafts.Apply(World, Scene, Preset, SunShafts.ResolveStillTier(Params), SunShaftsOut);
	Record->SetObjectField(TEXT("sun_shafts"), SunShaftsOut);

	// -- rain readability and the lightning's pulse --------------------------
	const double* Row = &AtmosphereValues[Preset * AtmosphereFieldCount];
	{
		TSharedPtr<FJsonObject> RainRow = MakeShared<FJsonObject>();
		if (Weather.DrawsRain())
		{
			Weather.ApplyBeautyRainReadability(Row[AtmRainReadabilityGain]);
			RainRow->SetNumberField(TEXT("readability_gain"), Row[AtmRainReadabilityGain]);
			RainRow->SetStringField(TEXT("applied_to"), TEXT("the storm weather's drawn drops and splashes"));
		}
		else
		{
			RainRow->SetStringField(TEXT("applied_to"),
				TEXT("nothing: the storm weather draws no drops (-weather-backend=off or no rain); the weather "
				     "look's rain particles and streaks are unchanged"));
		}
		Record->SetObjectField(TEXT("rain"), RainRow);
	}
	// Lane D: the rain veil -- the curtain at depth and, in a storm or heavy rain,
	// the scud under the drawn deck (after the clearance: the deck it hangs under
	// is the one drawn). Heights above the scene datum (KeepAircraftClearOfClouds).
	{
		const double AircraftUpM = FMath::Max(0.0, WorldNumber(Card, TEXT("altitude_m"), 0.0) -
		                                               WorldNumber(Card, TEXT("terrain_elevation_m"), 0.0));
		bool bDeckAbove = false;
		double DeckBaseM = 0.0;
		for (const FCloudLayerState& State : CloudLayers)
		{
			if (State.Cover > 0.0 && State.BaseM > AircraftUpM && (!bDeckAbove || State.BaseM < DeckBaseM))
			{
				bDeckAbove = true;
				DeckBaseM = State.BaseM;
			}
		}
		double CellDeckBaseM = 0.0, CellDeckTopM = 0.0;
		if (Weather.BeautyStormLayer(CellDeckBaseM, CellDeckTopM) && CellDeckBaseM > AircraftUpM &&
		    (!bDeckAbove || CellDeckBaseM < DeckBaseM))
		{
			bDeckAbove = true;
			DeckBaseM = CellDeckBaseM;
		}
		if (!Weather.ApplyBeautyRainVeil(World, Aircraft != nullptr ? Aircraft->GetActorLocation() : FVector::ZeroVector,
		                                 AircraftUpM, Preset == PresetStorm, bDeckAbove, DeckBaseM, RainVeilMode, Error))
		{
			return false;
		}
		// Lane D follow-up (round 6's #15: a blue sky and a bright ground 2 km under
		// a rain deck): in a storm preset with drawn rain and no stated visibility,
		// the height fog carries the rain's own haze up to the camera
		// (FFlightSimWeather::RainHazeFog, rain_veil.rain_haze_fog). Off with the veil.
		TSharedPtr<FJsonObject> Haze = MakeShared<FJsonObject>();
		const double HazeRate = Weather.DrawnRainRateMmh();
		const bool bHaze = Preset == PresetStorm && HazeRate > 0.0 && VisibilityKm <= 0.0 &&
		                   RainVeilMode == TEXT("on") && Aircraft != nullptr;
		Haze->SetBoolField(TEXT("applied"), bHaze);
		if (bHaze)
		{
			TArray<TSharedPtr<FJsonValue>> HazeRows;
			for (TObjectIterator<UExponentialHeightFogComponent> It; It; ++It)
			{
				UExponentialHeightFogComponent* Fog = *It;
				if (Fog == nullptr || Fog->GetWorld() != World || !Fog->IsVisible())
				{
					continue;
				}
				const double FogZM = Fog->GetComponentLocation().Z / WorldCmPerMetre;
				const double AboveFogM = Aircraft->GetActorLocation().Z / WorldCmPerMetre - FogZM;
				const double ColumnM = bDeckAbove ? DeckBaseM : AircraftUpM + 1000.0;
				double Density = Fog->FogDensity, Falloff = Fog->FogHeightFalloff;
				FFlightSimWeather::RainHazeFog(HazeRate, AboveFogM, ColumnM, Fog->FogDensity, Fog->FogHeightFalloff,
				                               Density, Falloff);
				TSharedPtr<FJsonObject> HazeRow = MakeShared<FJsonObject>();
				HazeRow->SetNumberField(TEXT("fog_density_before"), Fog->FogDensity);
				HazeRow->SetNumberField(TEXT("fog_height_falloff_before"), Fog->FogHeightFalloff);
				Fog->SetFogDensity(static_cast<float>(Density));
				Fog->SetFogHeightFalloff(static_cast<float>(Falloff));
				HazeRow->SetNumberField(TEXT("fog_density"), Density);
				HazeRow->SetNumberField(TEXT("fog_height_falloff"), Falloff);
				HazeRow->SetNumberField(TEXT("camera_above_fog_m"), AboveFogM);
				HazeRow->SetNumberField(TEXT("column_m"), ColumnM);
				HazeRows.Add(MakeShared<FJsonValueObject>(HazeRow));
			}
			Haze->SetArrayField(TEXT("height_fog"), HazeRows);
			Haze->SetNumberField(TEXT("rain_rate_mmh"), HazeRate);
		}
		Haze->SetStringField(TEXT("law"),
			TEXT("rain_veil.rain_haze_fog: in a storm preset with rain and no stated visibility, the fog's falloff "
			     "halves it once over the column under the deck and its density gives the camera's height the "
			     "rain's extinction (0.35 R^0.66 /km), never thinner than the scene's fog; -rain-veil=off keeps "
			     "the scene's fog. UNCALIBRATED"));
		Record->SetObjectField(TEXT("rain_haze"), Haze);
		// Round 12 / round 26 (lane D): THE LIGHT UNDER A STORM DECK, with or without
		// rain (#10's tornado has none). The fog was lit by the CLEAR sky above the deck
		// (the SkyAtmosphere ambient at white, FlightSimSky.cpp) and by the sun's lobe;
		// the volumetric fog and the veil by the sun (1 / 0.48) and by the sky light,
		// whose captured lower hemisphere is the GROUND (SLS_CapturedScene: the tiles,
		// green over #10's prairie: r24 measured the funnel 73/94/81 with the fog and the
		// veil on, 68/70/79 off). Under a drawn storm deck: the fog's ambient is the
		// deck's diffuse transmission (rain_veil.STORM_FOG_AMBIENT_RGB), no sun lobe, the
		// sun's volumetric scattering x STORM_SUN_FOG_SHARE, and the sky light's lower
		// hemisphere a solid dark neutral (STORM_LOWER_HEMISPHERE: a wet ground under a
		// storm returns little light, and no colour of its own) unless the hero
		// lighting's sidecar states one. -rain-veil=off keeps the scene's.
		TSharedPtr<FJsonObject> DeckLight = MakeShared<FJsonObject>();
		const bool bDeckLight = Preset == PresetStorm && bDeckAbove && RainVeilMode == TEXT("on");
		DeckLight->SetBoolField(TEXT("applied"), bDeckLight);
		if (bDeckLight)
		{
			// Round 36 (#10 still green with the unlit veil: the HEIGHT FOG's inscatter,
			// the SkyAtmosphere ambient whose hue is the grassland's bounce under the deck;
			// scaling it kept the hue): the ambient contribution is OFF and the fog's own
			// inscattering is a neutral grey luminance (rain_veil.STORM_FOG_INSCATTER_NITS:
			// the light under a storm deck, a stated overcast-base luminance).
			const FLinearColor Ambient(0.0f, 0.0f, 0.0f);
			constexpr float StormFogInscatterNits = 1500.0f;
			const FLinearColor Inscatter(StormFogInscatterNits, StormFogInscatterNits, StormFogInscatterNits);
			TArray<TSharedPtr<FJsonValue>> FogRows;
			for (TObjectIterator<UExponentialHeightFogComponent> It; It; ++It)
			{
				UExponentialHeightFogComponent* Fog = *It;
				if (Fog == nullptr || Fog->GetWorld() != World || !Fog->IsVisible())
				{
					continue;
				}
				TSharedPtr<FJsonObject> FogRow = MakeShared<FJsonObject>();
				FogRow->SetStringField(TEXT("sky_atmosphere_ambient_scale_before"),
					Fog->SkyAtmosphereAmbientContributionColorScale.ToString());
				Fog->SetSkyAtmosphereAmbientContributionColorScale(Ambient);
				Fog->SetFogInscatteringColor(Inscatter);
				FogRow->SetStringField(TEXT("fog_inscattering_luminance"), Inscatter.ToString());
				Fog->SetDirectionalInscatteringColor(FLinearColor::Black);
				FogRow->SetStringField(TEXT("sky_atmosphere_ambient_scale"), Ambient.ToString());
				FogRow->SetBoolField(TEXT("directional_inscattering_off"), true);
				FogRows.Add(MakeShared<FJsonValueObject>(FogRow));
			}
			DeckLight->SetArrayField(TEXT("height_fog"), FogRows);
			if (Scene.Sun != nullptr && Scene.Sun->GetLightComponent() != nullptr)
			{
				constexpr double StormSunFogShare = 0.15;
				ULightComponent* Beam = Scene.Sun->GetLightComponent();
				DeckLight->SetNumberField(TEXT("sun_volumetric_scattering_before"), Beam->VolumetricScatteringIntensity);
				Beam->SetVolumetricScatteringIntensity(
					static_cast<float>(Beam->VolumetricScatteringIntensity * StormSunFogShare));
				DeckLight->SetNumberField(TEXT("sun_volumetric_scattering"), Beam->VolumetricScatteringIntensity);
			}
			USkyLightComponent* DeckSky = Scene.SkyLightComponent;
			if (DeckSky != nullptr && !DeckSky->bLowerHemisphereIsBlack)
			{
				const FLinearColor Lower(0.0f, 0.0f, 0.0f);
				DeckSky->bLowerHemisphereIsBlack = true;
				DeckSky->SetLowerHemisphereColor(Lower);
				DeckLight->SetStringField(TEXT("sky_light_lower_hemisphere"), Lower.ToString());
			}
			else
			{
				DeckLight->SetStringField(TEXT("sky_light_lower_hemisphere"),
					DeckSky == nullptr ? TEXT("no sky light") : TEXT("kept: already solid (the hero lighting's)"));
			}
		}
		Record->SetObjectField(TEXT("storm_deck_light"), DeckLight);
	}
	// round-2b weather-fx: the weather look's shafts and the tornado funnel (beauty only).
	Scene.ApplyBeautyWeatherLook(World);
	SkyLight = Scene.SkyLightComponent;
	SkyLightBaseIntensity = SkyLight != nullptr ? SkyLight->Intensity : 1.0f;
	LightningSkyGain = Row[AtmLightningSkyGain];
	// One lightning clock: when the storm weather draws its cell, its own flash
	// list (LastFlashLux) is the only source; the weather look's schedule (and
	// its bolt, SceneOptions.bSkipStormLook) stands down.
	bLookLightning = StormWordValue == TEXT("thunderstorm") && !Weather.DrawsCell();
	LookSeed = static_cast<int32>(WorldNumber(WeatherLook, TEXT("seed"), 0.0));
	{
		TSharedPtr<FJsonObject> Lightning = MakeShared<FJsonObject>();
		Lightning->SetNumberField(TEXT("sky_gain"), LightningSkyGain);
		Lightning->SetNumberField(TEXT("reference_lux"), LightningReferenceLux);
		Lightning->SetNumberField(TEXT("sky_light_base_intensity"), SkyLightBaseIntensity);
		Lightning->SetBoolField(TEXT("weather_look_schedule"), bLookLightning);
		Lightning->SetBoolField(TEXT("storm_weather_flashes"), Weather.IsBuilt());
		Lightning->SetStringField(TEXT("law"),
			TEXT("sky light x (1 + sky_gain x clamp(max(weather-look flash, storm flash lux / reference_lux), "
			     "0, 1)) per frame; each frame's values in frames[]"));
		Record->SetObjectField(TEXT("lightning"), Lightning);
	}

	// -- the ground scatter --------------------------------------------------
	if (!ScatterPath.IsEmpty())
	{
		if (!Scatter.Build(World, ScatterPath, Card, Aircraft, &Tiles, GeoReferencing, Error))
		{
			return false;
		}
		Record->SetObjectField(TEXT("ground_scatter"), Scatter.Record);
	}
	else
	{
		TSharedPtr<FJsonObject> ScatterRow = MakeShared<FJsonObject>();
		ScatterRow->SetStringField(TEXT("drawn"), TEXT("nothing: no -ground-scatter=<sidecar>"));
		Record->SetObjectField(TEXT("ground_scatter"), ScatterRow);
	}

	if (Scene.LookApplied.IsValid())
	{
		Scene.LookApplied->SetObjectField(TEXT("world_beauty"), Record);
	}
	bBuilt = true;
	UE_LOG(LogFlightSimWorldBeauty, Display,
	       TEXT("world beauty: preset %s, %d cloud layer(s) redrawn, %d override(s), scatter %s"),
	       ANSI_TO_TCHAR(PresetName(Preset)), CloudLayers.Num(), Overridden.Num(),
	       Scatter.IsBuilt() ? TEXT("on") : TEXT("off"));
	return true;
}

// -- tiles-delight (visual overhaul module, 2026-11-09) ------------------------
// The tiles' de-lighting (assets/shaders/world/tiles_delight.hlsl; Python twin
// core/scene/tiles_delight.py, whose DELIGHT_DEFAULTS, DELIGHT_* constants and
// CONTACT_* rows tests/test_tiles_delight.py pins to the numbers below) and the
// engine's contact shading that replaces the shadows it lifts. BEAUTY ONLY: only
// FFlightSimWorldBeauty calls these. A per-frame shader operation: nothing is
// stored (Google Map Tiles policy). UNCALIBRATED: every number (PROBE_LOG.md
// ## tiles-delight). Engine symbols: scripts/check_bridge_api.sh "tiles-delight".
namespace FlightSimTilesDelight
{
	// DelightAmount per FlightSimWorldPure preset: clear, hazy, overcast, rain, storm.
	constexpr double DelightAmounts[FlightSimWorldPure::PresetCount] = {0.5, 0.5, 0.2, 0.2, 0.2};
	constexpr double DelightMipBias = 5.0;
	constexpr double DelightRatioKnee = 0.6;
	constexpr double DelightBlueGate = 4.0;
	constexpr float ContactShadowLength = 0.05f;

	inline double AmountFor(int32 Preset)
	{
		return Preset >= 0 && Preset < FlightSimWorldPure::PresetCount ? DelightAmounts[Preset] : 0.0;
	}

	// render.json world_beauty.tiles.delight.
	TSharedPtr<FJsonObject> DelightRecord(int32 Preset)
	{
		TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
		Out->SetNumberField(TEXT("amount"), AmountFor(Preset));
		Out->SetNumberField(TEXT("mip_bias"), DelightMipBias);
		Out->SetNumberField(TEXT("ratio_knee"), DelightRatioKnee);
		Out->SetNumberField(TEXT("blue_gate"), DelightBlueGate);
		Out->SetStringField(TEXT("preset"), ANSI_TO_TCHAR(FlightSimWorldPure::PresetName(Preset)));
		Out->SetStringField(TEXT("basis"), TEXT("shader per frame, nothing stored (Google tile policy)"));
		Out->SetBoolField(TEXT("pixel_moving"), false);
		Out->SetStringField(TEXT("calibration"), TEXT("UNCALIBRATED"));
		Out->SetStringField(TEXT("contact_shading"), TEXT("world_beauty.atmosphere.contact_shading"));
		return Out;
	}

	// Lumen's short-range AO (pinned by code: both are ECVF_Scalability) and the
	// sun's screen-space contact shadows; read back for the record. Lighting only.
	TSharedPtr<FJsonObject> ApplyContactShading(UDirectionalLightComponent* SunLight)
	{
		TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
		const TCHAR* const Cvars[] = {
			TEXT("r.Lumen.ScreenProbeGather.ShortRangeAO"),
			TEXT("r.Lumen.ScreenProbeGather.ShortRangeAO.HorizonSearch"),
		};
		for (const TCHAR* Name : Cvars)
		{
			IConsoleVariable* Variable = IConsoleManager::Get().FindConsoleVariable(Name);
			if (Variable != nullptr)
			{
				Variable->Set(1, ECVF_SetByCode);
			}
			Out->SetStringField(Name, Variable != nullptr ? Variable->GetString() : FString(TEXT("absent")));
		}
		if (SunLight != nullptr)
		{
			SunLight->ContactShadowLength = ContactShadowLength;
			SunLight->ContactShadowLengthInWS = false;
			SunLight->MarkRenderStateDirty();
			Out->SetNumberField(TEXT("sun_contact_shadow_length"), SunLight->ContactShadowLength);
		}
		else
		{
			Out->SetStringField(TEXT("sun_contact_shadow_length"), TEXT("no sun light: not set"));
		}
		Out->SetBoolField(TEXT("pixel_moving"), false);
		Out->SetStringField(TEXT("calibration"), TEXT("UNCALIBRATED"));
		return Out;
	}
}

// sun-shafts-sky-occlusion: the commandlet's teardown forwards here.
void FFlightSimWorldBeauty::RestoreCvars()
{
	SunShafts.Restore();
	// Sky step 3: every cvar ApplyClouds wrote (the march tier's table and, since
	// clouds-sky round 2, the fog-on-every-cloud-pixel cvar), back to the value it
	// had before, in reverse order. Idempotent.
	for (int32 I = WorldCvarsBefore.Num() - 1; I >= 0; --I)
	{
		if (IConsoleVariable* Variable = IConsoleManager::Get().FindConsoleVariable(*WorldCvarsBefore[I].Name))
		{
			Variable->Set(*WorldCvarsBefore[I].Before, ECVF_SetByCode);
		}
	}
	WorldCvarsBefore.Reset();
}

// Sky step 3: a cvar's value before this lane touched it, saved once (the first
// save wins: a second call for the same name returns what was saved).
FString FFlightSimWorldBeauty::SaveWorldCvar(const TCHAR* Name, IConsoleVariable* Variable)
{
	for (const FSavedCvar& Entry : WorldCvarsBefore)
	{
		if (Entry.Name == Name)
		{
			return Entry.Before;
		}
	}
	WorldCvarsBefore.Add({FString(Name), Variable->GetString()});
	return WorldCvarsBefore.Last().Before;
}

// Sky step 3: set one renderer cvar at code priority, its value before saved for
// RestoreCvars, and record [before, read back] under Row (modelled on
// FFlightSimSunShafts::SetSunShaftsCvar). An unregistered name is listed in
// Skipped and nothing is set.
void FFlightSimWorldBeauty::SetWorldCvar(const TCHAR* Name, double Value, const TSharedPtr<FJsonObject>& Row,
                                         TArray<TSharedPtr<FJsonValue>>& Skipped)
{
	IConsoleVariable* Variable = IConsoleManager::Get().FindConsoleVariable(Name);
	if (Variable == nullptr)
	{
		Skipped.Add(MakeShared<FJsonValueString>(FString::Printf(TEXT("skipped: %s is not registered"), Name)));
		return;
	}
	const FString Before = SaveWorldCvar(Name, Variable);
	Variable->Set(*FString::SanitizeFloat(Value, 0), ECVF_SetByCode);
	TArray<TSharedPtr<FJsonValue>> Pair;
	Pair.Add(MakeShared<FJsonValueString>(Before));
	Pair.Add(MakeShared<FJsonValueString>(Variable->GetString()));
	Row->SetArrayField(Name, Pair);
}

// Round 1 hang: the public face of CloudConstrainedGpu (the commandlet's
// constrained-GPU safeguards read the same class this lane's settings do).
bool FFlightSimWorldBeauty::ConstrainedGpu()
{
	return CloudConstrainedGpu();
}

// Fix lane sun-color (2026-11-16): -sky-capture-veil (core/sky/gradient.py
// sky_capture_veil_fog, the twin). The sky light is captured once
// (USkyLightComponent::UpdateSkyCaptureContents, SLS_CapturedScene) and its cube
// faces draw the height fog over the sky with the view's FogCutoffDistance test,
// so the gradient's cutoff and step 4's profile took the fog veil out of the
// FILL: round 144 #01's shade is 3-5x round 199's in linear light, uniform with
// range (the fill, not the view's fog), the golden hour's warm key / cool fill
// ratio gone, and #02's stated x1.35 fill blue-white. For that capture only, each
// profiled fog is put back to its pre-gradient state: the profile's density at
// the scene's fog height (rebased from the CURRENT density, so the dust haze's
// later ratio is kept), the scene's falloff and height, the cutoff it had, the
// ambient over the airlight gain (the stated fill's later tint kept). Resume puts
// the view's fog back exactly.
TSharedPtr<FJsonObject> FFlightSimWorldBeauty::SuspendSkyGradientForCapture()
{
	using namespace FlightSimWorldPure;
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	Out->SetStringField(TEXT("switch"), SkyCaptureVeilSwitch);
	const bool bOn = bBuilt && SkyCaptureVeilFor(TCHAR_TO_ANSI(*SkyCaptureVeilSwitch)) == 1;
	int32 Held = 0;
	TArray<TSharedPtr<FJsonValue>> Rows;
	for (FSkyCaptureVeil& Veil : SkyCaptureVeils)
	{
		Veil.bHeld = false;
		UExponentialHeightFogComponent* Fog = Veil.Fog.Get();
		if (!bOn || Fog == nullptr)
		{
			continue;
		}
		Veil.HeldDensity = Fog->FogDensity;
		Veil.HeldFalloff = Fog->FogHeightFalloff;
		Veil.HeldCutoffCm = Fog->FogCutoffDistance;
		Veil.HeldLocation = Fog->GetComponentLocation();
		Veil.HeldAmbient = Fog->SkyAtmosphereAmbientContributionColorScale;
		Veil.bHeld = true;
		const double CurrentZM = Veil.HeldLocation.Z / WorldCmPerMetre;
		const double Density = FogDensityRebased(Fog->FogDensity, Fog->FogHeightFalloff, CurrentZM, Veil.SceneZM);
		const float G = static_cast<float>(Veil.AirlightGain > 0.0 ? Veil.AirlightGain : 1.0);
		Fog->SetFogDensity(static_cast<float>(Density));
		Fog->SetFogHeightFalloff(static_cast<float>(Veil.SceneFalloff));
		Fog->SetFogCutoffDistance(Veil.CutoffBeforeCm);
		Fog->SetSkyAtmosphereAmbientContributionColorScale(FLinearColor(
			Veil.HeldAmbient.R / G, Veil.HeldAmbient.G / G, Veil.HeldAmbient.B / G, Veil.HeldAmbient.A));
		Fog->SetWorldLocation(FVector(Veil.HeldLocation.X, Veil.HeldLocation.Y, Veil.SceneZM * WorldCmPerMetre));
		Fog->MarkRenderStateDirty();
		++Held;
		TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
		Row->SetStringField(TEXT("component"), Fog->GetName());
		Row->SetNumberField(TEXT("view_density"), Veil.HeldDensity);
		Row->SetNumberField(TEXT("view_falloff"), Veil.HeldFalloff);
		Row->SetNumberField(TEXT("view_z_m"), CurrentZM);
		Row->SetNumberField(TEXT("view_cutoff_km"), Veil.HeldCutoffCm / WorldCmPerMetre / 1000.0);
		Row->SetNumberField(TEXT("capture_density"), Fog->FogDensity);
		Row->SetNumberField(TEXT("capture_falloff"), Fog->FogHeightFalloff);
		Row->SetNumberField(TEXT("capture_z_m"), Veil.SceneZM);
		Row->SetNumberField(TEXT("capture_cutoff_km"), Fog->FogCutoffDistance / WorldCmPerMetre / 1000.0);
		Row->SetNumberField(TEXT("airlight_gain_undone"), G);
		Rows.Add(MakeShared<FJsonValueObject>(Row));
	}
	Out->SetBoolField(TEXT("applied"), Held > 0);
	Out->SetNumberField(TEXT("fogs_held"), Held);
	Out->SetArrayField(TEXT("fogs"), Rows);
	Out->SetStringField(TEXT("basis"),
		TEXT("fix lane sun-color (core/sky/gradient.py sky_capture_veil_fog): the sky light's one capture draws the "
		     "height fog over its sky with the view's cutoff test, so the gradient's FogCutoffDistance and step 4's "
		     "profile made the fill the bare physical sky (round 144 #01 shade 3-5x round 199's, #02 blue-white); for "
		     "that capture only the fog is the pre-gradient one, the view's put back after. -sky-capture-veil=off is "
		     "round 144's capture"));
	return Out;
}

void FFlightSimWorldBeauty::ResumeSkyGradientAfterCapture()
{
	for (FSkyCaptureVeil& Veil : SkyCaptureVeils)
	{
		UExponentialHeightFogComponent* Fog = Veil.Fog.Get();
		if (!Veil.bHeld || Fog == nullptr)
		{
			Veil.bHeld = false;
			continue;
		}
		Fog->SetFogDensity(Veil.HeldDensity);
		Fog->SetFogHeightFalloff(Veil.HeldFalloff);
		Fog->SetFogCutoffDistance(Veil.HeldCutoffCm);
		Fog->SetSkyAtmosphereAmbientContributionColorScale(Veil.HeldAmbient);
		Fog->SetWorldLocation(Veil.HeldLocation);
		Fog->MarkRenderStateDirty();
		Veil.bHeld = false;
	}
}

void FFlightSimWorldBeauty::ApplyAtmosphere(UWorld* World, FFlightSimVisualScene& Scene, double VisibilityKm,
                                            AActor* Aircraft)
{
	// Function-local: unity builds merge anonymous namespaces (NEXT.md gotcha 3).
	using namespace FlightSimWorldPure;
	const double* Row = &AtmosphereValues[Preset * AtmosphereFieldCount];
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	double FogFactor = 1.0;
	FogProfiles.Reset();
	SkyCaptureVeils.Reset();
	USkyAtmosphereComponent* Atmosphere = Scene.Atmosphere;
	// -NoAerialPerspective (Gate 6's extinction control) hides the atmosphere
	// and the fog: a hidden one is left exactly as the scene built it.
	if (Atmosphere == nullptr || !Atmosphere->IsVisible())
	{
		Out->SetStringField(TEXT("applied"), TEXT("nothing: no visible sky atmosphere (-NoAerialPerspective)"));
		Record->SetObjectField(TEXT("atmosphere"), Out);
		return;
	}
	bool bAerosolProbe = false;
	const TSharedPtr<FJsonObject> Aerosol = WorldObject(Scene.LookApplied, TEXT("aerosol"));
	if (Aerosol.IsValid())
	{
		Aerosol->TryGetBoolField(TEXT("applied"), bAerosolProbe);
	}
	Atmosphere->SetMieExponentialDistribution(static_cast<float>(Row[AtmMieScaleHeightKm]));
	Atmosphere->SetMieAnisotropy(static_cast<float>(Row[AtmMieAnisotropy]));
	Atmosphere->SetAerialPespectiveViewDistanceScale(static_cast<float>(Row[AtmAerialPerspectiveScale]));
	const FColor Albedo = WorldAlbedo(Surface, GroundWetness, StormNeutralAlbedo());
	Atmosphere->SetGroundAlbedo(Albedo);
	Out->SetStringField(TEXT("storm_ground_albedo"), StormAlbedoSwitch);
	Out->SetBoolField(TEXT("ground_albedo_neutral"), StormNeutralAlbedo());
	// clouds-sky round 2: the sky's multiple scattering (paler towards the
	// horizon from altitude; FlightSimWorldPure::SkyMultiScattering).
	Out->SetNumberField(TEXT("multi_scattering_factor_before"), Atmosphere->MultiScatteringFactor);
	// Sky step 4: the row under -sky-multi-scatter=on, or auto on a discrete GPU (ef361bd6's
	// class gate kept under auto: FlightSimWorldPure::SkyMultiScatterFor); off
	// keeps the scene's 1.0 for the A/B.
	const int32 MultiScatter = SkyMultiScatterFor(TCHAR_TO_ANSI(*SkyMultiScatterSwitch), CloudConstrainedGpu());
	if (MultiScatter == 1)
	{
		Atmosphere->SetMultiScatteringFactor(static_cast<float>(SkyMultiScattering(Preset)));
	}
	Out->SetNumberField(TEXT("multi_scattering_factor"), Atmosphere->MultiScatteringFactor);
	Out->SetStringField(TEXT("multi_scattering_switch"), SkyMultiScatterSwitch);
	Out->SetBoolField(TEXT("multi_scattering_applied"), MultiScatter == 1);
	Out->SetBoolField(TEXT("multi_scattering_constrained_gpu"), CloudConstrainedGpu());
	Out->SetStringField(TEXT("multi_scattering_basis"),
		TEXT("world_beauty.SKY_MULTI_SCATTERING (UNCALIBRATED): shot d's sky at 3.8 km rendered near-black navy; "
		     "more multiple scattering pales and lifts the clear sky towards the horizon"));
	Out->SetStringField(TEXT("multi_scattering_gate_basis"),
		TEXT("sky step 4: -sky-multi-scatter=auto|on|off, auto = on for a discrete GPU, the engine's 1.0 on the constrained class (ef361bd6's gate, kept); on = every class. The factor is one multiply "
		     "in the 32x32 multi-scattering LUT pass the atmosphere runs every frame at the same sample count "
		     "(SkyAtmosphere.usf MultiScatteredLuminanceLutUAV; the render path already sets "
		     "r.SkyAtmosphere.MultiScatteringLUT.HighQuality 1 on every GPU), in no per-pixel shader, so it adds "
		     "no submission on the iGPU. Round 1's bisect named a8c964fc as a unit and r87 located the stall in the "
		     "sky light's cloud reflection march; nothing isolated this factor. UNMEASURED on the iGPU until the "
		     "Windows A/B (docs/VISUAL_FIDELITY_PLAN.md Sky step 4); off is ef361bd6's sky."));
	Out->SetNumberField(TEXT("mie_scale_height_km"), Row[AtmMieScaleHeightKm]);
	Out->SetNumberField(TEXT("mie_anisotropy"), Row[AtmMieAnisotropy]);
	Out->SetNumberField(TEXT("aerial_perspective_view_distance_scale"), Row[AtmAerialPerspectiveScale]);
	Out->SetStringField(TEXT("ground_albedo_srgb"),
		FString::Printf(TEXT("%d,%d,%d"), Albedo.R, Albedo.G, Albedo.B));
	Out->SetStringField(TEXT("ground_albedo_basis"),
		TEXT("the atmosphere's multiple-scattering ground bounce (the only engine pass that reads it; the main "
		     "view draws no albedo-lit ground): the card's surface row (world_beauty.GROUND_ALBEDO_SRGB, "
		     "UNCALIBRATED) darkened by the tiles' wet law at the ground's wetness"));
	Out->SetStringField(TEXT("ground_albedo_surface"), Surface.IsEmpty() ? FString(TEXT("default")) : Surface);
	Out->SetNumberField(TEXT("ground_albedo_wetness"), GroundWetness);
	if (VisibilityKm > 0.0 && !bAerosolProbe)
	{
		const FMieSplit Split = MieSplit(VisibilityKm, Row[AtmMieShare], Row[AtmMieCapPerKm]);
		Atmosphere->SetMieScatteringScale(static_cast<float>(Split.MieScatteringPerKm));
		Atmosphere->SetMieAbsorptionScale(static_cast<float>(Split.MieAbsorptionPerKm));
		FogFactor = Split.FogFactor;
		Out->SetNumberField(TEXT("koschmieder_beta_per_km"), Split.BetaPerKm);
		Out->SetNumberField(TEXT("mie_scattering_scale_per_km"), Split.MieScatteringPerKm);
		Out->SetNumberField(TEXT("mie_absorption_scale_per_km"), Split.MieAbsorptionPerKm);
		Out->SetNumberField(TEXT("mie_share"), Row[AtmMieShare]);
		Out->SetNumberField(TEXT("mie_cap_per_km"), Row[AtmMieCapPerKm]);
		Out->SetNumberField(TEXT("fog_factor"), FogFactor);
		Out->SetStringField(TEXT("mie_basis"),
			TEXT("a share of the card's haze (3.912 / visibility less Rayleigh) moved from the height fog "
			     "into the atmosphere's Mie layer; the fog keeps the rest of the haze, so Rayleigh + Mie + fog "
			     "= the Koschmieder beta at the ground (extinction counted once)"));
	}
	else if (!bAerosolProbe && AerosolVisibilityKm(Preset, VisibilityKm) > 0.0)
	{
		// Round 7: the clear world's default aerosol; the fog keeps its density.
		const double DefaultKm = AerosolVisibilityKm(Preset, VisibilityKm);
		const FMieSplit Split = MieSplit(DefaultKm, Row[AtmMieShare], Row[AtmMieCapPerKm]);
		Atmosphere->SetMieScatteringScale(static_cast<float>(Split.MieScatteringPerKm));
		Atmosphere->SetMieAbsorptionScale(static_cast<float>(Split.MieAbsorptionPerKm));
		Out->SetNumberField(TEXT("default_visibility_km"), DefaultKm);
		Out->SetNumberField(TEXT("mie_scattering_scale_per_km"), Split.MieScatteringPerKm);
		Out->SetNumberField(TEXT("mie_absorption_scale_per_km"), Split.MieAbsorptionPerKm);
		Out->SetNumberField(TEXT("mie_share"), Row[AtmMieShare]);
		Out->SetNumberField(TEXT("mie_cap_per_km"), Row[AtmMieCapPerKm]);
		Out->SetNumberField(TEXT("fog_factor"), FogFactor);
		Out->SetStringField(TEXT("mie_basis"),
			TEXT("the card states no visibility_km: a clear world takes the Mie layer of a "
			     "ClearDefaultVisibilityKm day (world_beauty.CLEAR_DEFAULT_VISIBILITY_KM, UNCALIBRATED) for the "
			     "horizon haze and the aerial perspective; the height fog is kept as the scene built it"));
	}
	else
	{
		Out->SetStringField(TEXT("mie_basis"), bAerosolProbe
			? TEXT("kept: the -aerosol= probe set the Mie scale")
			: TEXT("kept: the card states no visibility_km"));
	}
	Out->SetBoolField(TEXT("applied"), true);

	// Sky step 4: the aerial perspective's record (the scale stays 1.0: world_beauty.py
	// says why; the LUT's depth and resolution are the march tier's cvars, recorded
	// under clouds.march.cvars by ApplyClouds).
	{
		TSharedPtr<FJsonObject> Aerial = MakeShared<FJsonObject>();
		Aerial->SetNumberField(TEXT("view_distance_scale"), Row[AtmAerialPerspectiveScale]);
		Aerial->SetStringField(TEXT("basis"),
			TEXT("SetAerialPespectiveViewDistanceScale 1.0 (fix pass 2026-11-09: a scale multiplies only the opaque "
			     "surfaces' haze and breaks the Koschmieder single count); the ridges' layering comes from the Mie "
			     "layer, the multiple scattering and the fog's vertical profile (horizon_haze); the AP LUT's depth, "
			     "resolution and sample counts are the march tier's cvars (clouds.march.cvars)"));
		Out->SetObjectField(TEXT("aerial_perspective"), Aerial);
	}

	// The height fog: the rest of the haze, and volumetric fog for the sun's
	// shafts through it. Sky step 4: its vertical profile, start distance and
	// max opacity (FlightSimWorldPure::FogHeightFalloffFor and the rebase laws:
	// the comment there is the physics and the engine reading).
	const double FogScaleHeightKm = Row[AtmFogScaleHeightKm];
	const bool bFogProfile = FogScaleHeightKm > 0.0;
	const double FogFalloff = FogHeightFalloffFor(FogScaleHeightKm);
	const bool bAircraftKnown = Aircraft != nullptr;
	const double AircraftZM = bAircraftKnown ? Aircraft->GetActorLocation().Z / WorldCmPerMetre : 0.0;
	TSharedPtr<FJsonObject> Haze = MakeShared<FJsonObject>();
	Haze->SetBoolField(TEXT("profile_applied"), bFogProfile);
	// Lane sky-atmosphere: -look-sky-gradient (core/sky/gradient.py). The clear and
	// hazy rows only (the fog's vertical profile): the sky pixels leave the fog (its
	// cutoff), the fog's atmosphere ambient takes the horizon's luminance, and the
	// atmosphere's Earth coefficients are stated rather than inherited.
	const bool bSkyGradient = SkyGradientFor(TCHAR_TO_ANSI(*SkyGradientSwitch)) == 1 && bFogProfile;
	double SunElevationDeg = 90.0;
	if (Scene.Sun != nullptr)
	{
		const FVector LightDir = Scene.Sun->GetActorForwardVector();
		SunElevationDeg = FMath::RadiansToDegrees(FMath::Asin(FMath::Clamp(-LightDir.Z, -1.0, 1.0)));
	}
	const double AirlightGain = HorizonAirlightGain(SunElevationDeg);
	{
		TSharedPtr<FJsonObject> Gradient = MakeShared<FJsonObject>();
		Gradient->SetStringField(TEXT("switch"), SkyGradientSwitch);
		Gradient->SetBoolField(TEXT("applied"), bSkyGradient);
		Gradient->SetNumberField(TEXT("sun_elevation_deg"), SunElevationDeg);
		Gradient->SetNumberField(TEXT("fog_cutoff_km"), bSkyGradient ? SkyGradientFogCutoffKm : 0.0);
		Gradient->SetNumberField(TEXT("sky_pixel_depth_km"), SkyGradientSkyPixelDepthKm);
		Gradient->SetNumberField(TEXT("horizon_airlight_gain"), bSkyGradient ? AirlightGain : 1.0);
		Gradient->SetStringField(TEXT("basis"),
			TEXT("core/sky/gradient.py: a sky pixel decodes to 1000 km (SceneView.cpp DeviceZ 0 -> 1/1e-8 cm), so the "
			     "height fog drawn over the sky took every sky pixel to 0.92 of the distant sky light's sphere mean "
			     "(the flat navy sky); FogCutoffDistance 950 km (past the 754 km farthest tile, short of the sky) shows "
			     "the atmosphere alone there. The fog's ambient x the CIE clear sky's horizon / upper-hemisphere mean "
			     "(ISO 15469 type 12) at the sun's elevation, so far ground fades to the horizon's luminance. "
			     "UNMEASURED on the iGPU until the Windows A/B"));
		if (bSkyGradient)
		{
			Atmosphere->SetRayleighScattering(FLinearColor(
				static_cast<float>(EarthRayleighPerKm[0] / EarthRayleighPerKm[2]),
				static_cast<float>(EarthRayleighPerKm[1] / EarthRayleighPerKm[2]), 1.0f));
			Atmosphere->SetRayleighScatteringScale(static_cast<float>(EarthRayleighPerKm[2]));
			Atmosphere->SetRayleighExponentialDistribution(static_cast<float>(EarthRayleighScaleHeightKm));
			Atmosphere->SetOtherAbsorption(FLinearColor(
				static_cast<float>(EarthOzonePerKm[0] / EarthOzonePerKm[1]), 1.0f,
				static_cast<float>(EarthOzonePerKm[2] / EarthOzonePerKm[1])));
			Atmosphere->SetOtherAbsorptionScale(static_cast<float>(EarthOzonePerKm[1]));
			Gradient->SetStringField(TEXT("rayleigh_per_mm"), TEXT("5.802,13.558,33.1 (scale height 8 km)"));
			Gradient->SetStringField(TEXT("ozone_per_mm"), TEXT("0.650,1.881,0.085 (tent 25 km, 15 km wide)"));
		}
		Out->SetObjectField(TEXT("sky_gradient"), Gradient);
	}
	Haze->SetNumberField(TEXT("fog_scale_height_km"), FogScaleHeightKm);
	Haze->SetNumberField(TEXT("fog_height_falloff"), FogFalloff);
	Haze->SetNumberField(TEXT("fog_height_falloff_scene"), SceneFogHeightFalloff);
	Haze->SetNumberField(TEXT("fog_start_distance_m"), Row[AtmFogStartDistanceM]);
	Haze->SetNumberField(TEXT("fog_max_opacity"), Row[AtmFogMaxOpacity]);
	Haze->SetNumberField(TEXT("observer_clamp_m"), FogObserverClampM);
	Haze->SetNumberField(TEXT("rebase_step_m"), FogRebaseStepM);
	Haze->SetBoolField(TEXT("aircraft_known"), bAircraftKnown);
	Haze->SetNumberField(TEXT("aircraft_z_m"), AircraftZM);
	Haze->SetStringField(TEXT("basis"),
		TEXT("sky step 4 (world_beauty.fog_height_falloff / fog_density_rebased / fog_reference_z_m): the engine "
		     "draws FogDensity x 2^(-falloff/1000 x cm above the fog's height) OVER the sky atmosphere, with a sky "
		     "pixel's fog capped at the max opacity; the scene's falloff 0.0002 (a 72 km scale height) gave every "
		     "sky pixel 0.92 of one flat in-scatter colour. The clear and hazy rows give the fog the Mie layer's "
		     "scale height, so the zenith clears, the horizon saturates to a pale band and ridges layer through a "
		     "thinning haze; the density at the scene's fog height is kept (the Koschmieder count at the ground "
		     "is unchanged). The fog's reference height follows the aircraft because the engine clamps the fog's "
		     "observer to 655.36 m above the fog height (FogRendering.cpp MaxObserverHeightDifference) and shifts "
		     "the ray by the excess; Advance re-bases it per 100 m of climb or descent. The weather rows keep the "
		     "scene's uniform fog (their haze is the column under a deck). UNCALIBRATED; UNMEASURED until the "
		     "Windows round in docs/VISUAL_FIDELITY_PLAN.md Sky step 4"));
	Haze->SetStringField(TEXT("calibration"), TEXT("UNCALIBRATED"));
	TArray<TSharedPtr<FJsonValue>> FogRows;
	for (TObjectIterator<UExponentialHeightFogComponent> It; It; ++It)
	{
		UExponentialHeightFogComponent* Fog = *It;
		if (Fog == nullptr || Fog->GetWorld() != World || !Fog->IsVisible())
		{
			continue;
		}
		TSharedPtr<FJsonObject> FogRow = MakeShared<FJsonObject>();
		FogRow->SetNumberField(TEXT("fog_density_before"), Fog->FogDensity);
		Fog->SetFogDensity(static_cast<float>(Fog->FogDensity * FogFactor));
		// Sky step 4: the vertical profile, re-based at the aircraft's height.
		{
			const FVector FogLocation = Fog->GetComponentLocation();
			const double SceneZM = FogLocation.Z / WorldCmPerMetre;
			const double ReferenceZM = FogReferenceZM(SceneZM, AircraftZM, bFogProfile && bAircraftKnown);
			FogRow->SetNumberField(TEXT("fog_height_falloff_before"), Fog->FogHeightFalloff);
			FogRow->SetNumberField(TEXT("fog_height_z_m_scene"), SceneZM);
			FogRow->SetNumberField(TEXT("fog_density_at_scene_height"), Fog->FogDensity);
			FSkyCaptureVeil Veil;
			Veil.Fog = Fog;
			Veil.SceneZM = SceneZM;
			Veil.SceneFalloff = Fog->FogHeightFalloff;
			Veil.ProfileFalloff = FogFalloff;
			Veil.CutoffBeforeCm = Fog->FogCutoffDistance;
			if (bFogProfile)
			{
				const double Rebased = FogDensityRebased(Fog->FogDensity, FogFalloff, SceneZM, ReferenceZM);
				Fog->SetFogHeightFalloff(static_cast<float>(FogFalloff));
				Fog->SetFogDensity(static_cast<float>(Rebased));
				if (ReferenceZM != SceneZM)
				{
					Fog->SetWorldLocation(FVector(FogLocation.X, FogLocation.Y, ReferenceZM * WorldCmPerMetre));
					Fog->MarkRenderStateDirty();
				}
				FBeautyFogProfile Profile;
				Profile.Fog = Fog;
				Profile.SceneZM = SceneZM;
				Profile.Falloff = FogFalloff;
				FogProfiles.Add(Profile);
			}
			FogRow->SetNumberField(TEXT("fog_height_falloff"), Fog->FogHeightFalloff);
			FogRow->SetNumberField(TEXT("fog_height_z_m"), Fog->GetComponentLocation().Z / WorldCmPerMetre);
			FogRow->SetNumberField(TEXT("fog_start_distance_m_before"), Fog->StartDistance / WorldCmPerMetre);
			FogRow->SetNumberField(TEXT("fog_max_opacity_before"), Fog->FogMaxOpacity);
			Fog->SetStartDistance(static_cast<float>(Row[AtmFogStartDistanceM] * WorldCmPerMetre));
			Fog->SetFogMaxOpacity(static_cast<float>(Row[AtmFogMaxOpacity]));
			FogRow->SetNumberField(TEXT("fog_start_distance_m"), Fog->StartDistance / WorldCmPerMetre);
			FogRow->SetNumberField(TEXT("fog_max_opacity"), Fog->FogMaxOpacity);
			if (bSkyGradient)
			{
				FogRow->SetNumberField(TEXT("fog_cutoff_distance_km_before"), Fog->FogCutoffDistance / WorldCmPerMetre / 1000.0);
				Fog->SetFogCutoffDistance(static_cast<float>(SkyGradientFogCutoffKm * 1000.0 * WorldCmPerMetre));
				FogRow->SetNumberField(TEXT("fog_cutoff_distance_km"), Fog->FogCutoffDistance / WorldCmPerMetre / 1000.0);
				// Only an atmosphere-lit fog (a -sky= plan sets the inscattering black):
				// a legacy constant colour is not the sky's and is left alone.
				if (Fog->FogInscatteringLuminance.Equals(FLinearColor::Black))
				{
					const FLinearColor Before = Fog->SkyAtmosphereAmbientContributionColorScale;
					const float G = static_cast<float>(AirlightGain);
					Fog->SetSkyAtmosphereAmbientContributionColorScale(
						FLinearColor(Before.R * G, Before.G * G, Before.B * G, Before.A));
					FogRow->SetNumberField(TEXT("horizon_airlight_gain"), AirlightGain);
					Veil.AirlightGain = AirlightGain;
				}
			}
			if (bFogProfile)
			{
				SkyCaptureVeils.Add(Veil);
			}
		}
		Fog->SetVolumetricFog(true);
		Fog->SetVolumetricFogDistance(static_cast<float>(Row[AtmVFogDistanceM] * WorldCmPerMetre));
		Fog->SetVolumetricFogScatteringDistribution(static_cast<float>(Row[AtmVFogScatteringDistribution]));
		Fog->SetVolumetricFogExtinctionScale(static_cast<float>(Row[AtmVFogExtinctionScale]));
		// One phase for one haze: beyond the volumetric fog's distance the
		// analytic fog lights its sun term by pow(cos, exponent) / 4 pi (the
		// project keeps r.SupportExpFogMatchesVolumetricFog at 0: the measure
		// renders' fog must not change); its exponent is fitted to the same g.
		const double FogExponent = FogDirectionalExponentForG(Row[AtmVFogScatteringDistribution]);
		Fog->SetDirectionalInscatteringExponent(static_cast<float>(FogExponent));
		FogRow->SetNumberField(TEXT("fog_density_after"), Fog->FogDensity);
		FogRow->SetNumberField(TEXT("directional_inscattering_exponent"), FogExponent);
		FogRow->SetStringField(TEXT("directional_inscattering_basis"),
			TEXT("the pow lobe whose mean cosine (n+1)/(n+2) is the volumetric fog's g, clamped "
			     "(FlightSimWorldPure::FogDirectionalExponentForG)"));
		FogRow->SetBoolField(TEXT("volumetric_fog"), true);
		FogRow->SetNumberField(TEXT("volumetric_fog_distance_m"), Row[AtmVFogDistanceM]);
		FogRow->SetNumberField(TEXT("volumetric_fog_scattering_distribution"), Row[AtmVFogScatteringDistribution]);
		FogRow->SetNumberField(TEXT("volumetric_fog_extinction_scale"), Row[AtmVFogExtinctionScale]);
		FogRows.Add(MakeShared<FJsonValueObject>(FogRow));
	}
	Out->SetArrayField(TEXT("height_fog"), FogRows);
	Haze->SetNumberField(TEXT("fog_components"), FogRows.Num());
	Out->SetObjectField(TEXT("horizon_haze"), Haze);
	// Round 4: only the extinction is scaled. The volumetric fog's in-scatter is
	// Albedo x Extinction (the albedo already white, an 8-bit colour), so the
	// wet rows' extinction scale is undone on the lights' volumetric scattering:
	// the sky light's here, the sun's here and in FFlightSimHeroLighting::Apply
	// (which sets the sun's after this; it reads Scene.VolumetricFogScatteringScale).
	{
		const double Compensation = VFogScatteringCompensation(Row[AtmVFogExtinctionScale]);
		Scene.VolumetricFogScatteringScale = Compensation;
		TSharedPtr<FJsonObject> Inscatter = MakeShared<FJsonObject>();
		Inscatter->SetNumberField(TEXT("lights_volumetric_scattering_scale"), Compensation);
		if (Compensation != 1.0)
		{
			if (USkyLightComponent* Sky = Scene.SkyLightComponent)
			{
				Inscatter->SetNumberField(TEXT("sky_light_before"), Sky->VolumetricScatteringIntensity);
				// The setter pushes the value to the proxy (no recapture).
				Sky->SetVolumetricScatteringIntensity(static_cast<float>(Sky->VolumetricScatteringIntensity * Compensation));
				Inscatter->SetNumberField(TEXT("sky_light"), Sky->VolumetricScatteringIntensity);
			}
			if (Scene.Sun != nullptr && Scene.Sun->GetLightComponent() != nullptr)
			{
				ULightComponent* Beam = Scene.Sun->GetLightComponent();
				Inscatter->SetNumberField(TEXT("sun_before"), Beam->VolumetricScatteringIntensity);
				Beam->SetVolumetricScatteringIntensity(static_cast<float>(Beam->VolumetricScatteringIntensity * Compensation));
				Inscatter->SetNumberField(TEXT("sun"), Beam->VolumetricScatteringIntensity);
			}
		}
		Inscatter->SetStringField(TEXT("basis"),
			TEXT("1 / the row's volumetric fog extinction scale (world_beauty.vfog_scattering_compensation), so the "
			     "wet rows scale the fog's extinction only, not its in-scatter (round 3's #08 and head shot c lost "
			     "the rain haze's veil); UNCALIBRATED"));
		Out->SetObjectField(TEXT("volumetric_fog_inscatter"), Inscatter);
	}

	// The sun: shadows on the atmosphere and the clouds, per-pixel
	// transmittance, volumetric shadow. The cloud SHADOW switch is the
	// scene's (Gate 6's cloud bracket turns it off): never touched here (only
	// the stated -beauty-clouds=fair layer turns it on, recorded in clouds).
	UDirectionalLightComponent* SunLight = Scene.Sun != nullptr
		? Cast<UDirectionalLightComponent>(Scene.Sun->GetLightComponent()) : nullptr;
	if (SunLight != nullptr)
	{
		SunLight->bCastShadowsOnClouds = true;
		SunLight->bCastShadowsOnAtmosphere = true;
		// Integration (2026-11-09): a -sky= plan states the sun's per-pixel
		// transmittance (FFlightSimSky::Build, plan sun.per_pixel_transmittance)
		// and owns it; this look sets it only on a scene without a plan.
		// The model is world_beauty.SUN_PER_PIXEL_TRANSMITTANCE (the flag beauty_look reads).
		static_assert(SunPerPixelTransmittance, "the world look sets the engine's per-pixel transmittance");
		if (!bPhysicalSkyPlan)
		{
			SunLight->bPerPixelAtmosphereTransmittance = true;
		}
		SunLight->bCastVolumetricShadow = true;
		SunLight->MarkRenderStateDirty();
		Out->SetStringField(TEXT("sun"), bPhysicalSkyPlan
			? TEXT("bCastShadowsOnClouds, bCastShadowsOnAtmosphere, bCastVolumetricShadow on; "
			       "bPerPixelAtmosphereTransmittance left as the -sky= plan set it; bCastCloudShadows left as the scene set it")
			: TEXT("bCastShadowsOnClouds, bCastShadowsOnAtmosphere, bPerPixelAtmosphereTransmittance, "
			       "bCastVolumetricShadow on; bCastCloudShadows left as the scene set it"));
		Out->SetBoolField(TEXT("sun_per_pixel_transmittance"), SunLight->bPerPixelAtmosphereTransmittance != 0);
		Out->SetStringField(TEXT("sun_transmittance_model"),
			TEXT("world_beauty.SUN_PER_PIXEL_TRANSMITTANCE: the engine's atmosphere alone reddens and dims the beam "
			     "along the true slant path; beauty_look reads the same flag for the light's lux and colour"));
		Out->SetBoolField(TEXT("sun_cast_cloud_shadows"), SunLight->bCastCloudShadows != 0);
	}
	// tiles-delight hook: contact shading stands in for the baked shadows it lifts.
	Out->SetObjectField(TEXT("contact_shading"), FlightSimTilesDelight::ApplyContactShading(SunLight));
	Record->SetObjectField(TEXT("atmosphere"), Out);
}

void FFlightSimWorldBeauty::ApplyClouds(UWorld* World, FFlightSimVisualScene& Scene, FFlightSimWeather& Weather,
                                        const FString& Mode, double CardCover, double CardBaseM,
                                        double CardTopM, int32 Seed)
{
	// Function-local: unity builds merge anonymous namespaces (NEXT.md gotcha 3).
	using namespace FlightSimWorldPure;
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	Out->SetStringField(TEXT("mode"), Mode);
	Out->SetStringField(TEXT("labels"),
		TEXT("volumetric clouds write no depth or stencil: the mask, class and depth never see them. Clouds "
		     "stay where the card puts them; each frame records the camera-to-aircraft path through every "
		     "layer, its estimated transmittance and cloud_occludes_aircraft (frames[]); the mask is not edited"));
	// The clouds the per-frame occlusion row cannot model (their shape is not
	// this table's): with any, frames[].cloud_occlusion_complete is false and a
	// consumer must not read cloud_occludes_aircraft = false as "clear".
	UnmodelledClouds = 0;
	auto CountWorldClouds = [World]()
	{
		int32 Count = 0;
		for (TObjectIterator<UVolumetricCloudComponent> It; It; ++It)
		{
			Count += (*It != nullptr && It->GetWorld() == World) ? 1 : 0;
		}
		return Count;
	};
	if (Mode == TEXT("engine"))
	{
		UnmodelledClouds = CountWorldClouds();
		Out->SetNumberField(TEXT("unmodelled_clouds"), UnmodelledClouds);
		Out->SetStringField(TEXT("drawn"), TEXT("as the scene built them (-beauty-clouds=engine)"));
		Record->SetObjectField(TEXT("clouds"), Out);
		return;
	}
	UMaterialInterface* Base = LoadObject<UMaterialInterface>(nullptr, WorldCloudMaterialPath);
	if (Base == nullptr)
	{
		UnmodelledClouds = CountWorldClouds();
		Out->SetNumberField(TEXT("unmodelled_clouds"), UnmodelledClouds);
		Out->SetStringField(TEXT("drawn"),
			TEXT("as the scene built them: M_FlightSimCloudLayers did not load (run scripts/ue_create_materials.py)"));
		Record->SetObjectField(TEXT("clouds"), Out);
		return;
	}
	// Sky step 1: what the loaded material was BUILT with (its lighting constants
	// are baked by scripts/ue_create_materials.py, not set here): the graph
	// generation this bridge expects, the one stamped on the asset (its
	// FlightSimGraphGeneration tag; an older number means Windows must run the
	// material script before the wisp inputs exist), the scattering constants,
	// the albedo and the owner's parameter aliases.
	{
		TSharedPtr<FJsonObject> MaterialOut = MakeShared<FJsonObject>();
		MaterialOut->SetStringField(TEXT("path"), WorldCloudMaterialPath);
		MaterialOut->SetNumberField(TEXT("graph_generation_expected"), CloudGraphGeneration);
		FString GraphGeneration = TEXT("unread: no metadata in this build");
#if WITH_METADATA
		if (UPackage* Package = Base->GetOutermost())
		{
			const FString& Tag = Package->GetMetaData().GetValue(Base, TEXT("FlightSimGraphGeneration"));
			GraphGeneration = Tag.IsEmpty() ? FString(TEXT("untagged")) : Tag;
		}
#endif
		MaterialOut->SetStringField(TEXT("graph_generation"), GraphGeneration);
		MaterialOut->SetBoolField(TEXT("graph_generation_current"),
			GraphGeneration.IsNumeric() && CloudGraphGenerationCurrent(FCString::Atoi(*GraphGeneration)));
		MaterialOut->SetNumberField(TEXT("albedo"), CloudAlbedoBaked());
		TSharedPtr<FJsonObject> Scattering = MakeShared<FJsonObject>();
		for (int32 F = 0; F < CloudScatteringCount; ++F)
		{
			Scattering->SetNumberField(ANSI_TO_TCHAR(CloudScatteringName(F)), CloudScattering(F));
		}
		Scattering->SetStringField(TEXT("source"),
			FString::Printf(TEXT("scripts/ue_create_materials.py CLOUD_SCATTERING, baked into the material at "
			                     "build (graph generation %d); the storm's M_StormCell keeps STORM_SCATTERING"),
			                CloudGraphGeneration));
		Scattering->SetStringField(TEXT("deck_shapes"),
			TEXT("graph 11: these are the six pins' parameter defaults; -cloud-deck-scatter=round95 (the A/B; beauty is "
			     "the default since round 147) sets overcast and nimbostratus layers to round 95's STORM_SCATTERING (layers[].cloud_light_row)"));
		MaterialOut->SetObjectField(TEXT("scattering"), Scattering);
		TSharedPtr<FJsonObject> Aliases = MakeShared<FJsonObject>();
		for (int32 F = 0; F < CloudOwnerAliasCount; ++F)
		{
			Aliases->SetStringField(ANSI_TO_TCHAR(CloudOwnerAlias(F, false)), ANSI_TO_TCHAR(CloudOwnerAlias(F, true)));
		}
		MaterialOut->SetObjectField(TEXT("owner_aliases"), Aliases);
		MaterialOut->SetStringField(TEXT("owner_aliases_basis"),
			TEXT("the X-Plane-12 brief's Coverage, Density, DetailStrength, NoiseScale, Wind are these "
			     "material parameters (set per layer below; WindOffsetM advances in Advance from the scene's drift law)"));
		MaterialOut->SetStringField(TEXT("calibration"), TEXT("UNCALIBRATED: set by probe render on the render machine"));
		Out->SetObjectField(TEXT("material"), MaterialOut);
	}
	TArray<UVolumetricCloudComponent*> Components;
	TArray<TSharedPtr<FJsonValue>> Kept;
	for (TObjectIterator<UVolumetricCloudComponent> It; It; ++It)
	{
		UVolumetricCloudComponent* Cloud = *It;
		if (Cloud == nullptr || Cloud->GetWorld() != World)
		{
			continue;
		}
		const FString MaterialPath = Cloud->Material.ToSoftObjectPath().ToString();
		if (MaterialPath.Contains(WorldEngineCloudNeedle, ESearchCase::IgnoreCase))
		{
			Components.Add(Cloud);
		}
		else
		{
			Kept.Add(MakeShared<FJsonValueString>(MaterialPath));
		}
	}
	Out->SetArrayField(TEXT("kept_other_material"), Kept);
	// The storm's M_StormCell and any other material's cloud: kept as drawn, and
	// outside the occlusion row's slab model.
	UnmodelledClouds = Kept.Num();
	bool bFair = false;
	if (Components.Num() == 0 && Mode == TEXT("fair") && CardCover < 0.0 && !Weather.DrawsCell())
	{
		// The fair-weather layer: a stated stylisation, never the default.
		AActor* CloudActor = World->SpawnActor<AActor>();
		UVolumetricCloudComponent* Cloud = NewObject<UVolumetricCloudComponent>(CloudActor, TEXT("FairCumulus"));
		CloudActor->SetRootComponent(Cloud);
		Cloud->SetMobility(EComponentMobility::Movable);
		CloudActor->SetActorLocation(FVector::ZeroVector);
		Cloud->SetLayerBottomAltitude(static_cast<float>(FairBaseM / 1000.0));
		Cloud->SetLayerHeight(static_cast<float>((FairTopM - FairBaseM) / 1000.0));
		Cloud->RegisterComponent();
		Scene.BeautyOnlyActors.Add(CloudActor);
		Components.Add(Cloud);
		bFair = true;
		UDirectionalLightComponent* SunLight = Scene.Sun != nullptr
			? Cast<UDirectionalLightComponent>(Scene.Sun->GetLightComponent()) : nullptr;
		if (SunLight != nullptr)
		{
			// The one place the beauty touches the sun's cloud SHADOW switch:
			// only the stated -beauty-clouds=fair stylisation, recorded.
			Out->SetBoolField(TEXT("fair_layer_sun_cast_cloud_shadows_before"), SunLight->bCastCloudShadows != 0);
			SunLight->bCastCloudShadows = true;
			SunLight->MarkRenderStateDirty();
			Out->SetBoolField(TEXT("fair_layer_sun_cast_cloud_shadows"), true);
		}
	}
	Out->SetBoolField(TEXT("fair_layer_added"), bFair);
	const double* AtmRow = &AtmosphereValues[Preset * AtmosphereFieldCount];
	double SeedKm[3] = {0.0, 0.0, 0.0};
	CloudSeedOffsetKm(static_cast<uint64_t>(static_cast<int64_t>(Seed)), SeedKm);
	// clouds-sky round 2: the march budget by GPU class (the render machine's
	// Intel iGPU under D3D11 must not time out; a discrete GPU takes more).
	const bool bIntegratedGpu = CloudConstrainedGpu();
	// Sky step 3: the tier is the -cloud-march= word, auto = the GPU class (as before;
	// Build refused an unknown word, so the fallback below is never taken).
	const int32 MarchChosen = CloudMarchFor(TCHAR_TO_ANSI(*CloudMarchSwitch), bIntegratedGpu);
	const int32 March = MarchChosen >= 0 ? MarchChosen : (bIntegratedGpu ? MarchIntegrated : MarchDiscrete);
	const float ViewScale = static_cast<float>(CloudMarch(March, MarchViewScale));
	const float ShadowScale = static_cast<float>(CloudMarch(March, MarchShadowScale));
	const float TracingMaxKm = static_cast<float>(CloudMarch(March, MarchTracingMaxKm));
	{
		TSharedPtr<FJsonObject> MarchOut = MakeShared<FJsonObject>();
		MarchOut->SetStringField(TEXT("path"), ANSI_TO_TCHAR(MarchName(March)));
		MarchOut->SetStringField(TEXT("path_basis"),
			TEXT("CloudConstrainedGpu (GRHIDeviceIsIntegrated, or a feature level below SM6): the constrained row is ef361bd6's march"));
		MarchOut->SetStringField(TEXT("tier"), ANSI_TO_TCHAR(MarchName(March)));
		MarchOut->SetStringField(TEXT("switch"), CloudMarchSwitch);
		// Sky step 5: the word parsed from the command line, the plan's march_tier and
		// which of them the word in force came from (CloudMarchWordInForce).
		MarchOut->SetStringField(TEXT("switch_given"), CloudMarchSwitchGiven);
		MarchOut->SetStringField(TEXT("plan_march_tier"), SkyPlanRef != nullptr ? SkyPlanRef->CloudMarchTier : FString());
		MarchOut->SetStringField(TEXT("word_source"), CloudMarchWordSource);
		MarchOut->SetStringField(TEXT("tier_basis"),
			TEXT("sky step 3: -cloud-march=auto|constrained|discrete|probe; auto is the GPU class (constrained: "
			     "ef361bd6's row, rounds 5-95; discrete: the engine's caps, 768 view / 80 shadow samples over 50 km, "
			     "set for a discrete GPU, never rendered); probe is the constrained class's opt-in raise (288 view / "
			     "20 shadow samples, DistanceToSampleMaxCount 8 km), one scene, one still, the Windows TDR 887a0006 "
			     "the pass or fail. UNMEASURED: no tier but constrained has rendered"));
		MarchOut->SetBoolField(TEXT("rhi_device_is_integrated"), GRHIDeviceIsIntegrated);
		MarchOut->SetBoolField(TEXT("feature_level_sm6"), GMaxRHIFeatureLevel >= ERHIFeatureLevel::SM6);
		MarchOut->SetStringField(TEXT("adapter"), GRHIAdapterName);
		for (int32 F = 0; F < MarchFieldCount; ++F)
		{
			MarchOut->SetNumberField(ANSI_TO_TCHAR(MarchFieldName(F)), CloudMarch(March, F));
		}
		MarchOut->SetNumberField(TEXT("view_samples_max"),
			FMath::Min(UVolumetricCloudComponent::BaseViewRaySampleCount * ViewScale, 768.0f));
		MarchOut->SetNumberField(TEXT("shadow_samples"),
			FMath::Min(UVolumetricCloudComponent::BaseShadowRaySampleCount * ShadowScale, 80.0f));
		MarchOut->SetStringField(TEXT("banding_basis"),
			TEXT("round 1 marched 192 view samples over up to 80 km (400 m steps through 0.05/m cloud) and 10 "
			     "unjittered quadratic shadow samples over 15 km: contour banding and unlit cloud. The view "
			     "march is blue-noise jittered by the engine (VolumetricCloud.usf) and averaged by the still's "
			     "captures ONLY once the commandlet has loaded and built the blue-noise textures before the "
			     "first capture (clouds round 6: render_settings.beauty_path.blue_noise; a commandlet otherwise "
			     "gets BlueNoise.cpp's constant dummy, the altitude-slice strata of round 3); the shadow march "
			     "spans the layer (CloudShadowTracingKm)"));
		MarchOut->SetStringField(TEXT("cloud_tiers"), CloudTiersSwitch);
		MarchOut->SetStringField(TEXT("cloud_tiers_basis"),
			TEXT("round 52: the engine's shadow march is unjittered (ShadowJitterNorm 0.5) and each quadratic "
			     "segment is opaque at cloud extinction, so the sun's light came in on/off iso-altitude tiers; "
			     "M_FlightSimCloudLayers dithers and softens a shadow sample over its segment's footprint "
			     "(ShadowFootprintKm = 2 sqrt(shadow km) / shadow samples, per layer), and the plane weather "
			     "field's vertical walls lean and bulge with height (SideBulge); no sample added. "
			     "-look-cloud-tiers=off sets both 0: round 51's clouds"));
		MarchOut->SetStringField(TEXT("calibration"), TEXT("UNCALIBRATED: set by probe render on the render machine"));
		IConsoleVariable* FogAll = IConsoleManager::Get().FindConsoleVariable(WorldCloudFogAllPixelCvar);
		if (FogAll != nullptr)
		{
			// Sky step 3: saved once beside the tier's cvars (RestoreCvars puts it back).
			SaveWorldCvar(WorldCloudFogAllPixelCvar, FogAll);
			// Fog on every cloud pixel costs a full-screen pass per capture:
			// discrete GPUs only (the round-1 hang on the Intel iGPU).
			if (!bIntegratedGpu)
			{
				FogAll->Set(1, ECVF_SetByCode);
			}
		}
		MarchOut->SetStringField(WorldCloudFogAllPixelCvar,
			FogAll != nullptr ? FogAll->GetString() : FString(TEXT("absent")));
		// Sky step 3: the tier's renderer cvars (FlightSimWorldPure::CloudCvar), each
		// set at code priority, saved once for RestoreCvars and recorded
		// [before, read back] by name. The render path's own cvars are named, never set.
		TSharedPtr<FJsonObject> CvarRow = MakeShared<FJsonObject>();
		TArray<TSharedPtr<FJsonValue>> CvarsSkipped;
		for (int32 F = 0; F < CloudCvarFieldCount; ++F)
		{
			const FString Name(ANSI_TO_TCHAR(CloudCvarName(F)));
			SetWorldCvar(*Name, CloudCvar(March, F), CvarRow, CvarsSkipped);
		}
		MarchOut->SetObjectField(TEXT("cvars"), CvarRow);
		MarchOut->SetArrayField(TEXT("cvars_skipped"), CvarsSkipped);
		TSharedPtr<FJsonObject> CvarFields = MakeShared<FJsonObject>();
		for (int32 F = 0; F < CloudCvarFieldCount; ++F)
		{
			CvarFields->SetStringField(ANSI_TO_TCHAR(CloudCvarFieldName(F)), ANSI_TO_TCHAR(CloudCvarName(F)));
		}
		MarchOut->SetObjectField(TEXT("cvar_fields"), CvarFields);
		MarchOut->SetStringField(TEXT("cvars_basis"),
			TEXT("sky step 3: each value is [before, read back]; before is read when this lane runs, ahead of the "
			     "render path's Cinematic scalability pass, which sets at scalability priority and cannot lower a "
			     "code-priority value, so what is read back here is what the captures draw with. The constrained "
			     "row repeats what the render laptop drew with before this step (the engine's registration default, "
			     "or the Cinematic group's value for AP DepthResolution 32, TransmittanceLUT.SampleCount 30, "
			     "MultiScatteringLUT.SampleCount 20): a recorded no-op. Every cvar is put back by RestoreCvars at "
			     "teardown. r.VolumetricCloud.DistanceToSampleMaxCount also governs the sky-light capture's step "
			     "count: the engine sets InvDistanceToSampleCountMax once, for every trace, and its reflection pass "
			     "re-derives only the two sample caps, so the probe's 8 km lengthens that capture's march too (up to "
			     "15/8 x per short in-layer path) in the submission that hung r87 (887a0006); the Windows TDR is its "
			     "pass or fail. UNCALIBRATED; the discrete and probe rows are UNMEASURED"));
		TArray<TSharedPtr<FJsonValue>> RenderPathOwned;
		for (const TCHAR* Name : WorldRenderPathCvars)
		{
			RenderPathOwned.Add(MakeShared<FJsonValueString>(Name));
		}
		MarchOut->SetArrayField(TEXT("render_path_owned"), RenderPathOwned);
		MarchOut->SetStringField(TEXT("render_path_owned_basis"),
			TEXT("one owner per cvar: these are the render commandlet's (render_settings.beauty_path.read_back "
			     "holds their final values); this lane never sets them. The sky-light capture's "
			     "SetReflectionViewSampleCountScale and r.VolumetricCloud.ReflectionRaySampleMaxCount / "
			     "Shadow.ReflectionRaySampleMaxCount are the commandlet's caps on that capture's SampleCountMax / "
			     "ShadowSampleCountMax; they do NOT isolate the capture from this table: "
			     "r.VolumetricCloud.DistanceToSampleMaxCount sets InvDistanceToSampleCountMax for every trace, the "
			     "capture's included, so the probe tier's 8 km raises the capture's per-ray step count (up to 15/8 x) "
			     "under those caps"));
		Out->SetObjectField(TEXT("march"), MarchOut);
	}
	// Sky step 2 (the owner's X-Plane-12 brief): the sky plan's cloud fields
	// (FFlightSimSkyPlan, read by FlightSimSky.cpp Load with the header's defaults)
	// and the -cloud-type= switch. LayerSource decides per layer (switch > card >
	// plan > the shape's default); the plan's density and detail scale the row
	// (PlanDensityScale, PlanDetailErosion). The exposure never sees any of this:
	// plan.py's ev100 is computed before its clouds block and never reads it.
	const bool bPlanFields = SkyPlanRef != nullptr && SkyPlanRef->bCloudPlanFields;
	const int32 PlanType = bPlanFields && !SkyPlanRef->CloudType.IsEmpty()
		? PlanCloudTypeIndex(TCHAR_TO_ANSI(*SkyPlanRef->CloudType)) : PlanCloudUnknown;
	const int32 PlanShape = PlanType == PlanCloudUnknown ? PlanCloudUnknown : CloudShapeForPlanType(PlanType);
	const double PlanCover = bPlanFields ? SkyPlanRef->CloudCoverage : -1.0;
	const double PlanDensity = bPlanFields ? SkyPlanRef->CloudDensity : 1.0;
	const double PlanDetail = bPlanFields ? SkyPlanRef->CloudDetail : 1.0;
	const int32 SwitchType = CloudTypeSwitch.IsEmpty()
		? PlanCloudUnknown : PlanCloudTypeIndex(TCHAR_TO_ANSI(*CloudTypeSwitch));
	const int32 SwitchShape = SwitchType == PlanCloudUnknown ? PlanCloudUnknown : CloudShapeForPlanType(SwitchType);
	{
		TSharedPtr<FJsonObject> PlanOut = MakeShared<FJsonObject>();
		PlanOut->SetStringField(TEXT("fields_source"), SkyPlanRef == nullptr
			? TEXT("none: no -sky= plan (the defaults below)")
			: (bPlanFields
				? TEXT("sky.json clouds (cloud_type, coverage, density, detail, cirrus_coverage, coverage_source, seed, march_tier; core/sky/clouds.py writes them)")
				: TEXT("none: a v1 plan without the cloud fields (the defaults below, FlightSimSky.h)")));
		PlanOut->SetStringField(TEXT("cloud_type"), SkyPlanRef != nullptr ? SkyPlanRef->CloudType : FString());
		PlanOut->SetBoolField(TEXT("cloud_type_known"), PlanType != PlanCloudUnknown);
		PlanOut->SetNumberField(TEXT("coverage"), PlanCover);
		PlanOut->SetNumberField(TEXT("density"), PlanDensity);
		PlanOut->SetNumberField(TEXT("detail"), PlanDetail);
		PlanOut->SetNumberField(TEXT("cirrus_coverage"), SkyPlanRef != nullptr ? SkyPlanRef->CloudCirrusCoverage : 0.0);
		PlanOut->SetStringField(TEXT("coverage_source"),
		                        SkyPlanRef != nullptr ? SkyPlanRef->CloudCoverageSource : FString());
		PlanOut->SetNumberField(TEXT("seed"), SkyPlanRef != nullptr ? static_cast<double>(SkyPlanRef->CloudSeed) : 0.0);
		PlanOut->SetBoolField(TEXT("seed_stated"), SkyPlanRef != nullptr && SkyPlanRef->bCloudSeedStated);
		PlanOut->SetStringField(TEXT("march_tier"), SkyPlanRef != nullptr ? SkyPlanRef->CloudMarchTier : FString());
		PlanOut->SetNumberField(TEXT("card_seed"), Seed);
		PlanOut->SetBoolField(TEXT("seed_matches_card"), SkyPlanRef != nullptr && SkyPlanRef->bCloudSeedStated
		                      && SkyPlanRef->CloudSeed == static_cast<int64>(Seed));
		PlanOut->SetStringField(TEXT("cloud_type_switch"), CloudTypeSwitch);
		PlanOut->SetStringField(TEXT("precedence"),
			TEXT("-cloud-type= > card look.clouds[0] / the fair layer > sky.json clouds (not under rain or storm: "
			     "the deck stands) > the shape's default (FlightSimWorldPure::LayerSource; per layer cloud_type_source)"));
		PlanOut->SetStringField(TEXT("owner_parameters"),
			TEXT("Coverage -> Coverage; Density -> ExtinctionPerM x plan density (0.5..1.5); DetailStrength -> "
			     "DetailErosion x plan detail (saturated); NoiseScale -> ShapeScaleKm (the row's); Wind -> "
			     "WindOffsetM (Advance, the card's drift)"));
		PlanOut->SetBoolField(TEXT("exposure_sees_plan_clouds"), false);
		PlanOut->SetStringField(TEXT("measure_path"),
			TEXT("FlightSimSky.cpp Build reads bottom_km/thickness_km only: byte-identical with or without these fields"));
		PlanOut->SetStringField(TEXT("calibration"),
			TEXT("UNCALIBRATED: which row a type word draws and the density/detail clamps are look values; "
			     "UNMEASURED until a Windows render"));
		Out->SetObjectField(TEXT("plan"), PlanOut);
	}
	// Sky step 2 (design §0.14 / D16): under a plan WITH a card layer two components
	// exist: FFlightSimSky::Build's AVolumetricCloud (registered first) and
	// BuildClouds' "VolumetricCloud" on a plain actor (registered later). FScene keeps
	// the LAST registered proxy (UE 5.7 VolumetricCloudRendering.cpp AddVolumetricCloud),
	// so the plan's draws nothing: it is re-materialled all the same (a wrong reading
	// would still show the beauty material), left out of the sky capture and of the
	// layer bookkeeping (the occlusion rows, the clearance and the distant sheet read
	// only the drawn slab) and recorded engine_stack_shadowed. UNMEASURED: the stack
	// rule is read in source, not witnessed.
	auto ComponentSource = [](const UVolumetricCloudComponent* Cloud) -> const TCHAR*
	{
		if (Cloud->GetOwner() != nullptr && Cloud->GetOwner()->IsA<AVolumetricCloud>())
		{
			return TEXT("sky plan");
		}
		return Cloud->GetName() == TEXT("FairCumulus") ? TEXT("fair") : TEXT("card look.clouds");
	};
	bool bPlanComponent = false, bCardComponent = false;
	for (const UVolumetricCloudComponent* Cloud : Components)
	{
		const FString Src = ComponentSource(Cloud);
		bPlanComponent = bPlanComponent || Src == TEXT("sky plan");
		bCardComponent = bCardComponent || Src == TEXT("card look.clouds");
	}
	TArray<TSharedPtr<FJsonValue>> HiddenLayers;
	TArray<TSharedPtr<FJsonValue>> Layers;
	for (UVolumetricCloudComponent* Cloud : Components)
	{
		FCloudLayerState State;
		State.Component = Cloud;
		State.BaseM = Cloud->LayerBottomAltitude * 1000.0;
		State.TopM = (Cloud->LayerBottomAltitude + Cloud->LayerHeight) * 1000.0;
		State.Shape = LayerCoverAndShape(CardCover, State.TopM - State.BaseM, Preset, bFair, CloudValues.GetData(),
		                                 &State.Cover);
		// Sky step 2: the -cloud-type= switch and the plan's type and cover, by
		// LayerSource's precedence (the card's layer stands above the plan).
		const int32 Source = LayerSource(SwitchShape, CardCover, bFair, PlanShape, PlanCover, Preset,
		                                 CloudValues.GetData(), &State.Cover, &State.Shape);
		const FString ComponentSrc = ComponentSource(Cloud);
		const bool bShadowed = bPlanComponent && bCardComponent && ComponentSrc == TEXT("sky plan");
		if (State.Shape == PlanCloudNoLayer)
		{
			// clear / cirrus: no volumetric layer. Hidden (the visible flag gates the
			// cloud proxy at render-state creation, VolumetricCloudComponent.cpp), not
			// destroyed; beauty only: the measure path never reaches ApplyClouds. Step 6
			// draws the cirrus sheet.
			Cloud->SetVisibility(false);
			TSharedPtr<FJsonObject> Hidden = MakeShared<FJsonObject>();
			Hidden->SetStringField(TEXT("component"), Cloud->GetName());
			Hidden->SetStringField(TEXT("component_source"), ComponentSrc);
			Hidden->SetStringField(TEXT("cloud_type_source"), ANSI_TO_TCHAR(LayerSourceName(Source)));
			Hidden->SetStringField(TEXT("reason"), FString::Printf(
				TEXT("%s cloud_type %s: no volumetric layer (beauty only; SetVisibility(false))"),
				ANSI_TO_TCHAR(LayerSourceName(Source)),
				Source == LayerSourceSwitch ? *CloudTypeSwitch : *SkyPlanRef->CloudType));
			HiddenLayers.Add(MakeShared<FJsonValueObject>(Hidden));
			continue;
		}
		// Impostor A/B: the drawn cover under -cloud-volumetric-scale (1 leaves it;
		// State.Cover is the value the material's Coverage, the deck shadow and the
		// occlusion rows read; the distant sheet reads DistantCover below).
		const double CoverBeforeScale = State.Cover;
		State.Cover = CloudVolumetricCoverage(CoverBeforeScale, CloudVolumetricScale);
		// The distant sheet ignores the scale (ApplyDistantClouds reads DistantCover):
		// the horizon stays under an impostor-only frame.
		State.DistantCover = CloudDistantCover(CoverBeforeScale, CloudVolumetricScale);
		const bool bVolumetricHidden = CloudVolumetricHidden(CloudVolumetricScale);
		// clouds-sky round 2: the default layer (no card layer, not the stated
		// fair one) thinned to the shape's depth; the occlusion row reads the
		// thinned slab, the one drawn.
		const double BuiltTopM = State.TopM;
		const bool bStatedLayer = CardCover >= 0.0 || bFair;
		State.TopM = CloudCappedTopM(State.Shape, State.BaseM, State.TopM, bStatedLayer || bIntegratedGpu);
		if (State.TopM != BuiltTopM)
		{
			Cloud->SetLayerHeight(static_cast<float>((State.TopM - State.BaseM) / 1000.0));
		}
		// Round 95: a default cumulus layer the sky plan lifted above where cumulus form.
		const double PlanBaseM = State.BaseM;
		const bool bLowered = CumulusLayerLowered(State.Shape == CloudCumulus, bStatedLayer, State.BaseM);
		if (bLowered)
		{
			State.BaseM = FairBaseM;
			State.TopM = FairTopM;
			Cloud->SetLayerBottomAltitude(static_cast<float>(FairBaseM / 1000.0));
			Cloud->SetLayerHeight(static_cast<float>((FairTopM - FairBaseM) / 1000.0));
		}
		const float ShadowTracingKm =
			static_cast<float>(CloudShadowTracingKmFor(bIntegratedGpu, State.TopM - State.BaseM));
		// Round 82: the cumulus row under -look-cloud-billow (CloudBillowRow).
		const bool bLight = CloudLightSwitch == TEXT("on");
		const bool bBillow = CloudBillowApplies(CloudLightBillow(CloudBillowSwitch == TEXT("on"), bLight), State.Shape);
		double BillowRow[CloudFieldCount];
		CloudBillowRow(&CloudValues[State.Shape * CloudFieldCount], bBillow, BillowRow);
		const double* CloudRow = BillowRow;
		// Sky step 2: the plan's density and detail scale the row (1 = the row); the
		// owner's Density and DetailStrength land here, Coverage above, NoiseScale is
		// the row's ShapeScaleKm and Wind is WindOffsetM (Advance).
		const double DensityScale = PlanDensityScale(PlanDensity);
		const double DetailErosion = PlanDetailErosion(CloudRow[CldDetailErosion], PlanDetail);
		State.DensityScale = DensityScale;
		// Sky-clouds2: the light ON parents the MID on M_FlightSimCloudLayersLit (same
		// parameters plus the light's); not loadable (material script not run) = ours.
		UMaterialInterface* Parent = Base;
		if (bLight)
		{
			if (UMaterialInterface* Lit = LoadObject<UMaterialInterface>(nullptr, WorldCloudLitMaterialPath))
			{
				Parent = Lit;
			}
		}
		const FString LightMaterialDrawn = Parent->GetPathName();
		State.Material = UMaterialInstanceDynamic::Create(Parent, Cloud);
		State.Material->SetScalarParameterValue(TEXT("Coverage"), static_cast<float>(State.Cover));
		State.Material->SetScalarParameterValue(TEXT("ExtinctionPerM"),
		                                        static_cast<float>(CloudRow[CldExtinctionPerM] * DensityScale));
		State.Material->SetScalarParameterValue(TEXT("ExtinctionScale"), static_cast<float>(CloudExtinctionScale));
		State.Material->SetScalarParameterValue(TEXT("ShapeScaleKm"), static_cast<float>(CloudRow[CldShapeScaleKm]));
		State.Material->SetScalarParameterValue(TEXT("DetailScaleKm"), static_cast<float>(CloudRow[CldDetailScaleKm]));
		State.Material->SetScalarParameterValue(TEXT("DetailErosion"), static_cast<float>(DetailErosion));
		State.Material->SetScalarParameterValue(TEXT("BottomSoftness"), static_cast<float>(CloudRow[CldBottomSoftness]));
		State.Material->SetScalarParameterValue(TEXT("TopRounding"), static_cast<float>(CloudRow[CldTopRounding]));
		State.Material->SetScalarParameterValue(TEXT("CoverageContrast"),
		                                        static_cast<float>(CloudRow[CldCoverageContrast]));
		State.Material->SetVectorParameterValue(TEXT("SeedOffsetKm"),
			FLinearColor(static_cast<float>(SeedKm[0]), static_cast<float>(SeedKm[1]),
			             static_cast<float>(SeedKm[2]), 0.0f));
		State.Material->SetVectorParameterValue(TEXT("WindOffsetM"), FLinearColor(0.0f, 0.0f, 0.0f, 0.0f));
		// Round 52: the shadow samples' footprint (0 = round 51's march) and the
		// layer's thickness the footprint's vertical share is read against.
		const double ShadowSamples = FMath::Min(UVolumetricCloudComponent::BaseShadowRaySampleCount * ShadowScale, 80.0f);
		const double ShadowFootprint =
			CloudShadowFootprintPerSqrtKm(ShadowTracingKm, ShadowSamples, CloudTiersSwitch == TEXT("on"));
		State.Material->SetScalarParameterValue(TEXT("ShadowFootprintKm"), static_cast<float>(ShadowFootprint));
		State.Material->SetScalarParameterValue(TEXT("LayerThicknessKm"),
		                                        static_cast<float>((State.TopM - State.BaseM) / 1000.0));
		const double SideBulge = CloudSideBulgeFor(CloudTiersSwitch == TEXT("on"));
		State.Material->SetScalarParameterValue(TEXT("SideBulge"), static_cast<float>(SideBulge));
		// Round 61: no far fade until ApplyDistantClouds draws the sheet (it sets both).
		State.Material->SetScalarParameterValue(TEXT("FarFadeStartKm"), 0.0f);
		State.Material->SetScalarParameterValue(TEXT("FarFadeKm"), 0.0f);
		const double HeightDensity = CloudHeightDensityFor(bBillow);
		State.Material->SetScalarParameterValue(TEXT("HeightDensity"), static_cast<float>(HeightDensity));
		// Sky step 1: the wisp under -look-cloud-wisp (CloudWispRow; the OFF row is
		// the material's defaults, round 95 exactly).
		const bool bWisp = CloudWispApplies(CloudWispSwitch == TEXT("on"), State.Shape);
		double WispRow[WspFieldCount];
		CloudWispRow(bWisp, WispRow);
		State.Material->SetScalarParameterValue(TEXT("WispAmount"), static_cast<float>(WispRow[WspAmount]));
		State.Material->SetScalarParameterValue(TEXT("CurlStrength"), static_cast<float>(WispRow[WspCurl]));
		State.Material->SetScalarParameterValue(TEXT("EdgeThinPower"), static_cast<float>(WispRow[WspEdgePower]));
		State.Material->SetScalarParameterValue(TEXT("TopDetailGain"), static_cast<float>(WispRow[WspTopDetail]));
		State.Material->SetScalarParameterValue(TEXT("BoundaryErosion"), static_cast<float>(WispRow[WspBoundaryErosion]));
		// Sky-clouds lane: the light row (CloudLightRow; OFF = the material's defaults).
		double LightRow[LgtFieldCount];
		CloudLightRow(bLight, State.Shape, LightRow);
		// Lane rain-grey: a deck keeps round 95's energy-conserving node (CloudDeckScatterRow).
		const bool bDeckScatter = CloudDeckScatterApplies(
			CloudDeckScatterFor(TCHAR_TO_ANSI(*CloudDeckScatterSwitch)) == 1, bLight, State.Shape);
		CloudDeckScatterRow(bDeckScatter, LightRow);
		for (int F = 0; F < LgtFieldCount; ++F)
		{
			State.Material->SetScalarParameterValue(FName(ANSI_TO_TCHAR(CloudLightFieldName(F))),
			                                        static_cast<float>(LightRow[F]));
		}
		Cloud->SetMaterial(State.Material);
		// -cloud-material=epic: the Volumetrics plugin's cloud material in place of
		// ours (the MID above stays as the bookkeeping's; it draws nothing). Not
		// loadable (plugin off): ours stays and the record says so.
		FString EpicMaterialDrawn = TEXT("not asked");
		// r150: auto = the engine's stock cloud on cumulus-family layers (the owner's
		// call: UE's default clouds read better than ours from above); decks keep ours.
		const bool bStockCumulus = State.Shape == CloudCumulus || State.Shape == CloudStratocumulus ||
		                           State.Shape == CloudAltocumulus;
		const FString MaterialWord = CloudMaterialSwitch == TEXT("auto")
		                                 ? FString(bStockCumulus ? TEXT("engine") : TEXT("ours"))
		                                 : CloudMaterialSwitch;
		if (MaterialWord == TEXT("epic") || MaterialWord == TEXT("engine"))
		{
			const char* StockPath = MaterialWord == TEXT("engine") ? CloudMaterialEnginePath() : CloudMaterialEpicPath();
			UMaterialInterface* Epic = LoadObject<UMaterialInterface>(nullptr, ANSI_TO_TCHAR(StockPath));
			if (Epic != nullptr)
			{
				Cloud->SetMaterial(Epic);
				EpicMaterialDrawn = Epic->GetPathName();
			}
			else
			{
				EpicMaterialDrawn = TEXT("unloadable (Volumetrics plugin not enabled?): ours drawn");
				UE_LOG(LogFlightSimWorldBeauty, Warning, TEXT("-cloud-material=%s: %s did not load; ours drawn"),
				       *CloudMaterialSwitch, ANSI_TO_TCHAR(StockPath));
			}
		}
		Cloud->SetbUsePerSampleAtmosphericLightTransmittance(true);
		// Round 82 raises the belly's occlusion; sky step 1 caps it where the wisp applies.
		const double BillowOcclusion = CloudBottomOcclusionFor(bBillow, AtmRow[AtmCloudBottomOcclusion]);
		const double BottomOcclusion = CloudBellyOcclusion(bWisp, BillowOcclusion);
		Cloud->SetSkyLightCloudBottomOcclusion(static_cast<float>(BottomOcclusion));
		if (bLight)
		{
			// Lit 2: the lit material's AO pin replaces the engine's bottom gradient,
			// so cloud_sky_ao.hlsl rebuilds it from this layer's occlusion.
			State.Material->SetScalarParameterValue(FName(TEXT("SkyBottomOcclusion")), static_cast<float>(BottomOcclusion));
		}
		Cloud->SetViewSampleCountScale(ViewScale);
		Cloud->SetShadowViewSampleCountScale(ShadowScale);
		Cloud->SetShadowTracingDistance(ShadowTracingKm);
		Cloud->SetTracingMaxDistance(TracingMaxKm);
		Cloud->SetStopTracingTransmittanceThreshold(WorldCloudStopTransmittance);
		Cloud->SetGroundAlbedo(WorldAlbedo(Surface, GroundWetness, StormNeutralAlbedo()));
		// -cloud-volumetric-scale=0: the component is hidden, not left at Coverage 0.
		// An invisible UVolumetricCloudComponent has no render state, so the scene
		// has no volumetric cloud: no per-pixel view march, no shadow map, no
		// cloud-on-fog pass. Coverage 0 keeps every one of those (the march still
		// walks the slab to find nothing), the one the iGPU can least afford.
		// Nothing is called at any other scale, so a default frame is unchanged.
		if (bVolumetricHidden)
		{
			Cloud->SetVisibility(false);
		}
		if (bShadowed)
		{
			// Sky step 2: the plan's component under a card layer draws nothing
			// (engine stack); keep it out of the sky light's capture and the bookkeeping.
			Cloud->SetVisibleInRealTimeSkyCaptures(false);
		}
		else
		{
			CloudLayers.Add(State);
		}

		TSharedPtr<FJsonObject> Layer = MakeShared<FJsonObject>();
		Layer->SetStringField(TEXT("component"), Cloud->GetName());
		Layer->SetStringField(TEXT("shape"), ANSI_TO_TCHAR(CloudName(State.Shape)));
		Layer->SetNumberField(TEXT("cover"), State.Cover);
		Layer->SetStringField(TEXT("cover_basis"), Source == LayerSourceSwitch
			? (CardCover >= 0.0 || bFair
				? TEXT("-cloud-type=: the switch's shape with the card's (or the fair layer's) cover")
				: TEXT("-cloud-type=: the switch's shape with its row's default cover (the card states none)"))
			: Source == LayerSourcePlan
			? (PlanCover >= 0.0
				? TEXT("the sky plan's clouds.coverage (clouds.plan.coverage_source says where it came from)")
				: TEXT("the sky plan's cloud_type with the shape's default cover (the plan states no coverage)"))
			: bFair ? TEXT("the fair-weather layer (stated)")
			: (CardCover >= 0.0 ? TEXT("the card's look.clouds[0].cover")
			   : (Preset == PresetRain ? TEXT("RainDefaultCover: a rain world, the card states none (broken, round 3)")
			                           : TEXT("the shape's default (the card states none)"))));
		// Sky step 2: where the type came from, what it drew, and the plan's scales.
		Layer->SetStringField(TEXT("component_source"), ComponentSrc);
		Layer->SetBoolField(TEXT("engine_stack_shadowed"), bShadowed);
		Layer->SetStringField(TEXT("cloud_type_source"), ANSI_TO_TCHAR(LayerSourceName(Source)));
		Layer->SetStringField(TEXT("cloud_type_applied"), ANSI_TO_TCHAR(CloudName(State.Shape)));
		Layer->SetStringField(TEXT("cloud_type_requested"), Source == LayerSourceSwitch ? CloudTypeSwitch
			: (Source == LayerSourcePlan ? SkyPlanRef->CloudType : FString()));
		Layer->SetNumberField(TEXT("plan_density"), PlanDensity);
		Layer->SetNumberField(TEXT("plan_density_scale"), DensityScale);
		Layer->SetNumberField(TEXT("plan_detail"), PlanDetail);
		Layer->SetNumberField(TEXT("extinction_per_m_applied"), CloudRow[CldExtinctionPerM] * DensityScale);
		Layer->SetNumberField(TEXT("detail_erosion_applied"), DetailErosion);
		Layer->SetNumberField(TEXT("base_m"), State.BaseM);
		Layer->SetNumberField(TEXT("top_m"), State.TopM);
		Layer->SetNumberField(TEXT("built_top_m"), BuiltTopM);
		Layer->SetBoolField(TEXT("lowered_below_cruise"), bLowered);
		Layer->SetNumberField(TEXT("plan_base_m"), PlanBaseM);
		Layer->SetStringField(TEXT("top_basis"), State.TopM != BuiltTopM
			? TEXT("the default layer thinned to the shape's depth (world_beauty.CLOUD_MAX_THICKNESS_M)")
			: (bStatedLayer ? TEXT("the stated layer, as built") : TEXT("as built (within the shape's depth)")));
		Layer->SetNumberField(TEXT("shadow_tracing_distance_km"), ShadowTracingKm);
		Layer->SetNumberField(TEXT("shadow_footprint_km_per_sqrt_km"), ShadowFootprint);
		Layer->SetStringField(TEXT("cloud_tiers"), CloudTiersSwitch);
		Layer->SetNumberField(TEXT("side_bulge_cells"), SideBulge);
		Layer->SetStringField(TEXT("cloud_billow"), CloudBillowSwitch);
		Layer->SetBoolField(TEXT("cloud_billow_applied"), bBillow);
		Layer->SetNumberField(TEXT("volumetric_scale"), CloudVolumetricScale);
		Layer->SetBoolField(TEXT("volumetric_scale_applied"), CloudVolumetricScaleApplied(CloudVolumetricScale));
		Layer->SetNumberField(TEXT("cover_before_volumetric_scale"), CoverBeforeScale);
		Layer->SetBoolField(TEXT("volumetric_hidden"), bVolumetricHidden);
		Layer->SetNumberField(TEXT("distant_sheet_cover"), State.DistantCover);
		Layer->SetStringField(TEXT("distant_sheet_cover_basis"),
			TEXT("the layer's unscaled cover: the distant sheet ignores -cloud-volumetric-scale"));
		Layer->SetNumberField(TEXT("height_density"), HeightDensity);
		Layer->SetNumberField(TEXT("sky_light_cloud_bottom_occlusion"), BottomOcclusion);
		// Sky step 1: the switch word, whether it applied to this shape, the five
		// scalars by their material names, and the belly cap (the occlusion before it).
		Layer->SetStringField(TEXT("cloud_wisp"), CloudWispSwitch);
		Layer->SetStringField(TEXT("cloud_light"), CloudLightSwitch);
		Layer->SetStringField(TEXT("cloud_light_material"), LightMaterialDrawn);
		Layer->SetStringField(TEXT("cloud_deck_scatter"), CloudDeckScatterSwitch);
		Layer->SetBoolField(TEXT("cloud_deck_scatter_applied"), bDeckScatter);
		{
			TSharedPtr<FJsonObject> LightOut = MakeShared<FJsonObject>();
			for (int F = 0; F < LgtFieldCount; ++F)
			{
				LightOut->SetNumberField(ANSI_TO_TCHAR(CloudLightFieldName(F)), LightRow[F]);
			}
			if (bLight)
			{
				LightOut->SetNumberField(TEXT("SkyBottomOcclusion"), BottomOcclusion);
			}
			Layer->SetObjectField(TEXT("cloud_light_row"), LightOut);
		}
		Layer->SetStringField(TEXT("cloud_material"), CloudMaterialSwitch);
		Layer->SetStringField(TEXT("cloud_material_drawn"), EpicMaterialDrawn);
		Layer->SetBoolField(TEXT("cloud_wisp_applied"), bWisp);
		for (int32 F = 0; F < WspFieldCount; ++F)
		{
			Layer->SetNumberField(ANSI_TO_TCHAR(CloudWispFieldName(F)), WispRow[F]);
		}
		Layer->SetNumberField(TEXT("sky_light_cloud_bottom_occlusion_before_belly_cap"), BillowOcclusion);
		Layer->SetNumberField(TEXT("belly_occlusion_cap"), CloudWispBottomOcclusion);
		Layer->SetStringField(TEXT("cloud_wisp_basis"),
			TEXT("sky step 1: flow-warped erosion, a finer top octave, boundary erosion and density^EdgeThinPower "
			     "(cloud_layers.hlsl); -look-cloud-wisp=off is round 95 exactly. UNCALIBRATED"));
		for (int32 F = 0; F < CloudFieldCount; ++F)
		{
			Layer->SetNumberField(ANSI_TO_TCHAR(CloudFieldName(F)), CloudRow[F]);
		}
		Layer->SetNumberField(TEXT("extinction_scale"), CloudExtinctionScale);
		Layer->SetStringField(TEXT("seed_offset_km"),
			FString::Printf(TEXT("%.6f,%.6f,%.6f"), SeedKm[0], SeedKm[1], SeedKm[2]));
		Layer->SetStringField(TEXT("material"), WorldCloudMaterialPath);
		Layers.Add(MakeShared<FJsonValueObject>(Layer));
	}
	Out->SetArrayField(TEXT("layers"), Layers);
	// Sky step 2: the layers a clear/cirrus type hid, and the engine-stack note.
	Out->SetArrayField(TEXT("hidden_layers"), HiddenLayers);
	Out->SetBoolField(TEXT("plan_component_shadowed_by_card"), bPlanComponent && bCardComponent);
	Out->SetStringField(TEXT("engine_stack_basis"),
		TEXT("FScene keeps the LAST registered volumetric cloud proxy (UE 5.7 VolumetricCloudRendering.cpp "
		     "AddVolumetricCloud); the card's component (FlightSimVisualScene.cpp BuildClouds) registers after the "
		     "plan's (FFlightSimSky::Build), so with both the plan's draws nothing: re-materialled all the same, out "
		     "of the sky capture and the layer bookkeeping. UNMEASURED: read in source, not witnessed"));
	// Visual round 6: the deck SHADOWS the beam. Round 4's #10 drew the Flint
	// Hills red: the storm look's 10 deg sun, reddened by the per-pixel
	// transmittance, lit the prairie at grazing incidence under a nimbostratus
	// deck that cast no shadow (the sun's switch was left as the scene set it:
	// off), while beauty_look.scene_light metered the frame as if the deck
	// shadowed the beam. Under a deck preset whose drawn layer covers at least
	// DeckShadowMinCover the sun casts the volumetric cloud's shadow (the
	// switch the stated fair layer turns on above), so the tiles, the fog and
	// the aircraft get the deck's grey diffuse light and its holes' beams, not
	// the clear-sky beam. The cost is the engine's cloud shadow map, one
	// low-resolution march per capture, not the per-pixel view march.
	// -deck-shadow=off keeps the scene's switch (an A/B). Recorded either way.
	{
		TSharedPtr<FJsonObject> DeckShadow = MakeShared<FJsonObject>();
		double TopCover = 0.0;
		for (const FCloudLayerState& State : CloudLayers)
		{
			TopCover = FMath::Max(TopCover, State.Cover);
		}
		const bool bWanted = DeckShadowsBeam(Preset, TopCover);
		const bool bFairShadows = FairCloudShadows(Preset, TopCover) && FairShadowSwitch == TEXT("on");
		const bool bSwitchOn = DeckShadowSwitch != TEXT("off");
		UDirectionalLightComponent* DeckSun = Scene.Sun != nullptr
			? Cast<UDirectionalLightComponent>(Scene.Sun->GetLightComponent()) : nullptr;
		DeckShadow->SetStringField(TEXT("switch"), DeckShadowSwitch);
		DeckShadow->SetStringField(TEXT("preset"), ANSI_TO_TCHAR(PresetName(Preset)));
		DeckShadow->SetNumberField(TEXT("top_cover"), TopCover);
		DeckShadow->SetNumberField(TEXT("min_cover"), DeckShadowMinCover);
		DeckShadow->SetBoolField(TEXT("deck_shadows_beam"), bWanted);
		DeckShadow->SetBoolField(TEXT("fair_cloud_shadows"), bFairShadows);
		DeckShadow->SetNumberField(TEXT("fair_min_cover"), FairCloudShadowMinCover);
		DeckShadow->SetStringField(TEXT("fair_switch"), FairShadowSwitch);
		if (DeckSun != nullptr)
		{
			DeckShadow->SetBoolField(TEXT("sun_cast_cloud_shadows_before"), DeckSun->bCastCloudShadows != 0);
			// Round 7 (lane E): a clear or hazy world's drawn fair cumulus casts
			// its shadows on the ground too (round 4's clear scenes had none):
			// the same switch, the same -deck-shadow=off A/B.
			if ((bWanted || bFairShadows) && bSwitchOn)
			{
				DeckSun->bCastCloudShadows = true;
				DeckSun->MarkRenderStateDirty();
			}
			DeckShadow->SetBoolField(TEXT("sun_cast_cloud_shadows"), DeckSun->bCastCloudShadows != 0);
		}
		DeckShadow->SetStringField(TEXT("applied"), DeckSun == nullptr ? TEXT("no sun light in the scene")
			: (!bWanted ? (bFairShadows && bSwitchOn
				? TEXT("a clear or hazy world's drawn cumulus (fair_min_cover) casts its cloud shadows (round 7)")
				: TEXT("not a deck preset with a drawn layer of min_cover: the scene's switch stands"))
			   : (bSwitchOn ? TEXT("the sun casts the drawn deck's cloud shadow (bCastCloudShadows)")
			                : TEXT("-deck-shadow=off: the scene's switch stands"))));
		DeckShadow->SetStringField(TEXT("basis"),
			TEXT("the law of world_beauty.deck_shadows_beam -- under an overcast the ground gets the deck's "
			     "diffuse transmission, not the clear-sky beam (round 4's #10: a 10 deg red beam on the Flint "
			     "Hills); beauty only; UNCALIBRATED"));
		Out->SetObjectField(TEXT("deck_shadow"), DeckShadow);
	}
	Out->SetNumberField(TEXT("unmodelled_clouds"), UnmodelledClouds);
	Out->SetStringField(TEXT("coverage_law"),
		TEXT("cloud_layers.hlsl (round 10: a rounded, domain-warped 2D weather field, flat bases, domed tops, a smoother far field) cuts the shape noise "
		     "at its (1 - cover) quantile: FBM_MEAN 0.55 + FBM_SIGMA 0.069 x probit(1 - cover) (the noise's own "
		     "moments, world_beauty.CLOUD_FBM_*), started early by half the erosion's share of the soft edge, so "
		     "the drawn share of sky at full profile is the stated cover"));
	Out->SetNumberField(TEXT("view_sample_count_scale"), ViewScale);
	Out->SetNumberField(TEXT("shadow_view_sample_count_scale"), ShadowScale);
	Out->SetStringField(TEXT("shadow_tracing_distance_km"), TEXT("per layer (layers[].shadow_tracing_distance_km)"));
	Out->SetNumberField(TEXT("tracing_max_distance_km"), TracingMaxKm);
	Out->SetNumberField(TEXT("drift_mps"), DriftMps);
	Out->SetNumberField(TEXT("drift_from_deg"), DriftFromDeg);
	Out->SetStringField(TEXT("drawn"), Layers.Num() > 0
		? TEXT("M_FlightSimCloudLayers on every engine-material cloud (the storm's M_StormCell kept)")
		: TEXT("no cloud on the engine material to redraw"));
	Record->SetObjectField(TEXT("clouds"), Out);
}

// Visual round 2 (weather scenes, 2026-11-10): BEAUTY ONLY. Round 1 drew the
// aircraft INSIDE cloud: #07 (an A320 at 1000 m in the commandlet's 800-3000 m
// rain deck, 0.045 /m nimbostratus) was a flat grey frame, and #09 (a 747 at
// 2000 m, 350 m behind the microburst the storm cell is centred on: inside the
// 0.19 /m tower and the 1200-2700 m storm deck) a flat blue one, the cloud's
// inside lit by the sky light alone and metered up, only the 747's translucent
// nav lights drawn over it. Every redrawn deck moves clear of the aircraft
// (FlightSimWorldPure::AircraftClearLayer, its thickness kept), the storm's own
// deck too, and the storm's tower is drawn ahead of the clip's track
// (FFlightSimWeather::ApplyBeautyStormVantage). The per-frame occlusion row reads
// the moved slabs (the ones drawn). Nothing here reaches the physics: the
// microburst stays where the card puts it.
void FFlightSimWorldBeauty::KeepAircraftClearOfClouds(const TSharedPtr<FJsonObject>& Card, AActor* Aircraft,
                                                      FFlightSimWeather& Weather)
{
	// Function-local: unity builds merge anonymous namespaces (NEXT.md gotcha 3).
	using namespace FlightSimWorldPure;
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	// Heights above the scene datum, the frame of the decks and of the cell (the
	// scenario world's own ExpectedAboveGround: altitude_m - terrain_elevation_m).
	const double AircraftUpM = FMath::Max(0.0, WorldNumber(Card, TEXT("altitude_m"), 0.0) -
	                                               WorldNumber(Card, TEXT("terrain_elevation_m"), 0.0));
	const bool bRainDeck = Preset == PresetRain || Preset == PresetStorm;
	Out->SetNumberField(TEXT("aircraft_above_datum_m"), AircraftUpM);
	Out->SetNumberField(TEXT("clearance_m"), Preset == PresetStorm ? StormDeckClearanceM : AircraftLayerClearanceM);
	Out->SetBoolField(TEXT("rain_deck_goes_above"), bRainDeck);
	Out->SetStringField(TEXT("law"),
		TEXT("the law of world_beauty.aircraft_clear_layer, a deck whose slab widened by clearance_m holds the aircraft "
		     "moves clear of it with its thickness kept (a rain or storm deck above, others to the nearer side); "
		     "UNCALIBRATED"));
	TArray<TSharedPtr<FJsonValue>> Rows;
	for (FCloudLayerState& State : CloudLayers)
	{
		const FLayerClear Clear =
			AircraftClearLayer(State.BaseM, State.TopM, AircraftUpM,
			                   Preset == PresetStorm ? StormDeckClearanceM : AircraftLayerClearanceM, bRainDeck);
		TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
		Row->SetStringField(TEXT("component"), State.Component != nullptr ? State.Component->GetName() : FString());
		Row->SetNumberField(TEXT("base_m_before"), State.BaseM);
		Row->SetNumberField(TEXT("top_m_before"), State.TopM);
		Row->SetBoolField(TEXT("moved"), Clear.bMoved);
		if (Clear.bMoved && State.Component != nullptr)
		{
			State.Component->SetLayerBottomAltitude(static_cast<float>(Clear.BaseM / 1000.0));
			State.Component->SetLayerHeight(static_cast<float>((Clear.TopM - Clear.BaseM) / 1000.0));
			State.BaseM = Clear.BaseM;
			State.TopM = Clear.TopM;
			Row->SetStringField(TEXT("side"), Clear.bAbove ? TEXT("above") : TEXT("below"));
		}
		Row->SetNumberField(TEXT("base_m"), State.BaseM);
		Row->SetNumberField(TEXT("top_m"), State.TopM);
		Rows.Add(MakeShared<FJsonValueObject>(Row));
	}
	Out->SetArrayField(TEXT("layers"), Rows);
	if (Weather.DrawsCell())
	{
		double LayerBaseM = 0.0, LayerTopM = 0.0;
		const bool bLayer = Weather.BeautyStormLayer(LayerBaseM, LayerTopM);
		const FLayerClear Clear = bLayer
			? AircraftClearLayer(LayerBaseM, LayerTopM, AircraftUpM, AircraftLayerClearanceM, true)
			: FLayerClear{LayerBaseM, LayerTopM, false, true};
		// The clip's track: the card's airspeed over its duration (a true airspeed
		// above the stated one stays inside the vantage's clearance).
		const double TravelM = FMath::Max(0.0, WorldNumber(Card, TEXT("airspeed_kt"), 0.0)) * (1852.0 / 3600.0)
			* FMath::Max(0.0, WorldNumber(Card, TEXT("duration_s"), 0.0));
		Weather.ApplyBeautyStormVantage(
			Aircraft != nullptr ? Aircraft->GetActorLocation() : FVector::ZeroVector,
			Aircraft != nullptr ? Aircraft->GetActorForwardVector() : FVector::ZeroVector,
			TravelM, Clear.BaseM, Clear.TopM, Clear.bMoved);
		TSharedPtr<FJsonObject> Storm = MakeShared<FJsonObject>();
		Storm->SetBoolField(TEXT("deck_drawn_in_cell"), bLayer);
		Storm->SetBoolField(TEXT("deck_moved"), Clear.bMoved);
		Storm->SetNumberField(TEXT("deck_base_m"), Clear.BaseM);
		Storm->SetNumberField(TEXT("deck_top_m"), Clear.TopM);
		Storm->SetNumberField(TEXT("track_m"), TravelM);
		Storm->SetStringField(TEXT("vantage"), TEXT("look_applied.weather.cell.beauty_vantage"));
		Out->SetObjectField(TEXT("storm"), Storm);
	}
	Record->SetObjectField(TEXT("aircraft_clearance"), Out);
}

// Visual round 5, lane L3 (2026-11-10): the distant 2D cloud sheet. BEAUTY ONLY.
// One UProceduralMeshComponent disc (FlightSimWorldPure::DistantRings x
// DistantSegments, radius DistantRadiusKm, each ring dropped by the earth's
// curvature) on M_FlightSimDistantClouds (unlit, translucent, two-sided; no
// depth write, no custom depth, fog per pixel), centred on the camera and put
// at the deck's base or top by Advance. It draws the SAME shape noise as the
// volumetric layer at the layer's mid slice, cut at the same cover quantile,
// so the far sheet continues the near cells; its light is faked in the shader
// (distant_clouds.hlsl). Labels: the actor is in BeautyOnlyActors, so every
// label capture hides it; the material writes no depth and no custom depth.
// On the constrained GPU the volumetric march's TracingMaxDistance shrinks to
// the near field the sheet fades in behind (never more samples: the engine's
// count is non-decreasing in the traced path, VolumetricCloud.usf).
void FFlightSimWorldBeauty::ApplyDistantClouds(UWorld* World, FFlightSimVisualScene& Scene,
                                               FFlightSimWeather& Weather, const FString& Mode, int32 Seed)
{
	// Function-local: unity builds merge anonymous namespaces (NEXT.md gotcha 3).
	using namespace FlightSimWorldPure;
	DistantSheet = FDistantSheetState();
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	Out->SetStringField(TEXT("mode"), Mode);
	Out->SetStringField(TEXT("engine_content"),
		TEXT("UE 5.7 still ships /Engine/EngineSky/BP_Sky_Sphere with M_Sky_Panning_Clouds, M_Sky_Panning_Clouds2(_Inst) "
		     "and T_Sky_Clouds_M (read in the engine content on 2026-11-10); not used: a sky sphere covers the SkyAtmosphere"));
	Out->SetStringField(TEXT("labels"),
		TEXT("a translucent unlit disc: no depth write, no custom depth, no shadow; in BeautyOnlyActors, so every label "
		     "capture hides it (mask, class, depth and boxes untouched); the measure quality never builds it"));
	Out->SetBoolField(TEXT("pixel_moving"), false);
	Out->SetStringField(TEXT("calibration"), TEXT("UNCALIBRATED: set by probe render on the render machine"));
	if (Mode == TEXT("off"))
	{
		Out->SetStringField(TEXT("drawn"), TEXT("nothing (-distant-clouds=off)"));
		Record->SetObjectField(TEXT("distant_clouds"), Out);
		return;
	}
	// The deck the sheet continues: the first redrawn layer (its slab after the
	// aircraft clearance), else the storm cell's own deck.
	double BaseM = 0.0, TopM = 0.0, Cover = 0.0;
	int32 Shape = CloudCumulus;
	FString CoverBasis;
	if (CloudLayers.Num() > 0)
	{
		const FCloudLayerState& Layer = CloudLayers[0];
		BaseM = Layer.BaseM;
		TopM = Layer.TopM;
		Cover = Layer.DistantCover;
		Shape = Layer.Shape;
		CoverBasis = TEXT("the first redrawn layer (its slab after the aircraft clearance, its cover and shape row); "
		                  "the sheet ignores -cloud-volumetric-scale (the unscaled cover, distant_sheet_cover)");
	}
	else if (Weather.DrawsCell() && Weather.BeautyStormLayer(BaseM, TopM))
	{
		Shape = DistantStormShape;
		Cover = DistantStormCover(CloudValues.GetData());
		CoverBasis = TEXT("the storm cell's deck (world_beauty.DISTANT_STORM_SHAPE: the nimbostratus row's default cover)");
	}
	else
	{
		Out->SetStringField(TEXT("drawn"), TEXT("nothing: no redrawn layer and no storm deck to continue"));
		Record->SetObjectField(TEXT("distant_clouds"), Out);
		return;
	}
	if (!(TopM > BaseM))
	{
		Out->SetStringField(TEXT("drawn"), TEXT("nothing: the deck's slab is empty"));
		Record->SetObjectField(TEXT("distant_clouds"), Out);
		return;
	}
	UMaterialInterface* Base = LoadObject<UMaterialInterface>(nullptr, WorldDistantMaterialPath);
	if (Base == nullptr)
	{
		Out->SetStringField(TEXT("drawn"),
			TEXT("nothing: M_FlightSimDistantClouds did not load (run scripts/ue_create_materials.py)"));
		Record->SetObjectField(TEXT("distant_clouds"), Out);
		return;
	}

	// The disc: a fan about the centre, then ring quads; two-sided material, so
	// the winding is not load-bearing.
	AActor* Actor = World->SpawnActor<AActor>();
	UProceduralMeshComponent* Mesh = NewObject<UProceduralMeshComponent>(Actor, TEXT("DistantCloudSheet"));
	Actor->SetRootComponent(Mesh);
	Mesh->SetMobility(EComponentMobility::Movable);
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Mesh->SetCastShadow(false);
	Mesh->SetRenderCustomDepth(false);
	Mesh->SetReceivesDecals(false);
	// Behind every other translucent (rain shafts, contrails): lower sorts first.
	Mesh->SetTranslucentSortPriority(-100);
	TArray<FVector> Vertices;
	TArray<int32> Triangles;
	TArray<FVector> Normals;
	TArray<FVector2D> UV0;
	Vertices.Add(FVector::ZeroVector);
	Normals.Add(FVector::UpVector);
	UV0.Add(FVector2D(0.0, 0.0));
	for (int32 Ring = 1; Ring <= DistantRings; ++Ring)
	{
		const double RadiusKm = DistantRingRadiusKm(Ring, DistantRings, DistantRadiusKm);
		const double RadiusCm = RadiusKm * 1000.0 * WorldCmPerMetre;
		const double ZCm = DistantDroopM(RadiusKm) * WorldCmPerMetre;
		for (int32 Seg = 0; Seg < DistantSegments; ++Seg)
		{
			const double Angle = 2.0 * PI * Seg / DistantSegments;
			Vertices.Add(FVector(FMath::Cos(Angle) * RadiusCm, FMath::Sin(Angle) * RadiusCm, ZCm));
			Normals.Add(FVector::UpVector);
			UV0.Add(FVector2D(static_cast<double>(Ring) / DistantRings, static_cast<double>(Seg) / DistantSegments));
		}
	}
	auto VertexIndex = [](int32 Ring, int32 Seg)
	{
		return Ring <= 0 ? 0 : 1 + (Ring - 1) * DistantSegments + (Seg % DistantSegments);
	};
	for (int32 Seg = 0; Seg < DistantSegments; ++Seg)
	{
		Triangles.Append({VertexIndex(0, 0), VertexIndex(1, Seg), VertexIndex(1, Seg + 1)});
	}
	for (int32 Ring = 1; Ring < DistantRings; ++Ring)
	{
		for (int32 Seg = 0; Seg < DistantSegments; ++Seg)
		{
			const int32 A = VertexIndex(Ring, Seg), B = VertexIndex(Ring, Seg + 1);
			const int32 C = VertexIndex(Ring + 1, Seg), D = VertexIndex(Ring + 1, Seg + 1);
			Triangles.Append({A, C, B, B, C, D});
		}
	}
	check(Vertices.Num() == DistantDiscVertexCount() && Triangles.Num() == 3 * DistantDiscTriangleCount());
	Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0, {}, {}, false);
	Mesh->RegisterComponent();
	Actor->SetActorLocation(FVector::ZeroVector);   // Advance centres it on the camera

	// The material: the layer's cover and shape row, the hand-over, the look.
	double SeedKm[3] = {0.0, 0.0, 0.0};
	CloudSeedOffsetKm(static_cast<uint64_t>(static_cast<int64_t>(Seed)), SeedKm);
	const double* CloudRow = &CloudValues[Shape * CloudFieldCount];
	const bool bConstrained = CloudConstrainedGpu();
	// Sky step 3: the same tier ApplyClouds resolved (-cloud-march=, auto = the GPU
	// class); the near-field shrink below still keys on the GPU class itself.
	const int32 MarchChosen = CloudMarchFor(TCHAR_TO_ANSI(*CloudMarchSwitch), bConstrained);
	const int32 March = MarchChosen >= 0 ? MarchChosen : (bConstrained ? MarchIntegrated : MarchDiscrete);
	const double RowKm = CloudMarch(March, MarchTracingMaxKm);
	const double TraceKm = DistantTracingMaxKm(bConstrained, true, RowKm);
	const double HandoverKm = DistantHandoverKm(TraceKm);
	const double SliceKm = 0.5 * (BaseM + TopM) / 1000.0 + SeedKm[2];
	UMaterialInstanceDynamic* Material = UMaterialInstanceDynamic::Create(Base, Actor);
	Material->SetScalarParameterValue(TEXT("Coverage"), static_cast<float>(Cover));
	Material->SetScalarParameterValue(TEXT("CoverageContrast"), static_cast<float>(CloudRow[CldCoverageContrast]));
	Material->SetScalarParameterValue(TEXT("ShapeScaleKm"), static_cast<float>(CloudRow[CldShapeScaleKm]));
	Material->SetScalarParameterValue(TEXT("SliceKm"), static_cast<float>(SliceKm));
	Material->SetScalarParameterValue(TEXT("ThicknessKm"), static_cast<float>((TopM - BaseM) / 1000.0));
	Material->SetScalarParameterValue(TEXT("HandoverKm"), static_cast<float>(HandoverKm));
	Material->SetScalarParameterValue(TEXT("FadeKm"), static_cast<float>(DistantFadeKm));
	Material->SetScalarParameterValue(TEXT("RadiusKm"), static_cast<float>(DistantRadiusKm));
	Material->SetScalarParameterValue(TEXT("SheetFade"), 1.0f);
	// Round 82: -look-cloud-billow flattens and softens the sheet at grazing views
	// (distant_clouds.hlsl GRAZE_*: r69's banded horizon); 0 = round 81.
	const float GrazingSoften = CloudBillowSwitch == TEXT("on") ? 1.0f : 0.0f;
	Material->SetScalarParameterValue(TEXT("GrazingSoften"), GrazingSoften);
	// Round 147 (r146 #13): the tops seen from above and their shadows on the sea.
	const bool bSheetTops = SheetTopsSwitch != TEXT("off");
	const double TopRelief = SheetTopRelief(bSheetTops);
	const double SeaShadow = SheetSeaShadowFor(bSheetTops, Surface == TEXT("ocean"));
	const double MidZKm = SheetMidZKm(BaseM, TopM);
	Material->SetScalarParameterValue(TEXT("TopRelief"), static_cast<float>(TopRelief));
	Material->SetScalarParameterValue(TEXT("SeaShadow"), static_cast<float>(SeaShadow));
	Material->SetScalarParameterValue(TEXT("GroundZKm"), 0.0f);
	Material->SetScalarParameterValue(TEXT("MidZKm"), static_cast<float>(MidZKm));
	{
		TSharedPtr<FJsonObject> Tops = MakeShared<FJsonObject>();
		Tops->SetStringField(TEXT("switch"), bSheetTops ? TEXT("on") : TEXT("off"));
		Tops->SetNumberField(TEXT("top_relief"), TopRelief);
		Tops->SetNumberField(TEXT("sea_shadow"), SeaShadow);
		Tops->SetNumberField(TEXT("ground_z_km"), 0.0);
		Tops->SetNumberField(TEXT("mid_z_km"), MidZKm);
		Tops->SetStringField(TEXT("surface"), Surface);
		Tops->SetStringField(TEXT("basis"),
			TEXT("round 147 (r146 #13): seen from above, past the hand-over, the top is a dome (km-frame normal, "
			     "self-shadow toward the sun, sky occlusion in thin margins, softer margins: distant_clouds.hlsl TOPS_*); "
			     "over the ocean the sea seen through a gap darkens where the deck at MidZKm shades it from the sun. "
			     "-look-sheet-tops=off is round 146's sheet exactly. UNCALIBRATED"));
		Out->SetObjectField(TEXT("tops"), Tops);
	}
	TSharedPtr<FJsonObject> Look = MakeShared<FJsonObject>();
	for (int32 F = 0; F < DistantLookCount; ++F)
	{
		Material->SetScalarParameterValue(ANSI_TO_TCHAR(DistantLookName(F)), static_cast<float>(DistantLook(F)));
		Look->SetNumberField(ANSI_TO_TCHAR(DistantLookName(F)), DistantLook(F));
	}
	Material->SetVectorParameterValue(TEXT("SeedOffsetKm"),
		FLinearColor(static_cast<float>(SeedKm[0]), static_cast<float>(SeedKm[1]), static_cast<float>(SeedKm[2]), 0.0f));
	Material->SetVectorParameterValue(TEXT("WindOffsetM"), FLinearColor(0.0f, 0.0f, 0.0f, 0.0f));
	Mesh->SetMaterial(0, Material);
	Scene.BeautyOnlyActors.Add(Actor);
	DistantSheet.Actor = Actor;
	DistantSheet.Mesh = Mesh;
	DistantSheet.Material = Material;
	DistantSheet.BaseM = BaseM;
	DistantSheet.TopM = TopM;
	DistantSheet.bDrawn = true;

	// The volumetric march hands over: on the constrained GPU its trace shrinks
	// to the near field (a shorter path never adds a sample).
	TSharedPtr<FJsonObject> Trace = MakeShared<FJsonObject>();
	Trace->SetBoolField(TEXT("constrained_gpu"), bConstrained);
	Trace->SetNumberField(TEXT("row_tracing_max_distance_km"), RowKm);
	Trace->SetNumberField(TEXT("tracing_max_distance_km"), TraceKm);
	Trace->SetBoolField(TEXT("shrunk"), TraceKm < RowKm);
	Trace->SetNumberField(TEXT("grazing_soften"), GrazingSoften);   // round 82
	int32 LayersSet = 0;
	if (TraceKm < RowKm)
	{
		for (FCloudLayerState& Layer : CloudLayers)
		{
			if (Layer.Component != nullptr)
			{
				Layer.Component->SetTracingMaxDistance(static_cast<float>(TraceKm));
				++LayersSet;
			}
		}
	}
	Trace->SetNumberField(TEXT("layers_set"), LayersSet);
	// Round 61 (r58's distant band of block columns): the sheet's fade-in overlaid the
	// march's far walls up to the trace's end; the march now fades out over the same
	// range (cloud_layers.hlsl FarFadeStartKm / FarFadeKm), a cross-fade.
	// -look-cloud-tiers=off keeps round 52's overlay (FarFadeKm 0).
	const double FarFadeKm = CloudFarFadeKmFor(CloudTiersSwitch == TEXT("on"), DistantFadeKm);
	int32 LayersFaded = 0;
	for (FCloudLayerState& Layer : CloudLayers)
	{
		if (Layer.Material != nullptr)
		{
			Layer.Material->SetScalarParameterValue(TEXT("FarFadeStartKm"), static_cast<float>(HandoverKm));
			Layer.Material->SetScalarParameterValue(TEXT("FarFadeKm"), static_cast<float>(FarFadeKm));
			++LayersFaded;
		}
	}
	Trace->SetNumberField(TEXT("march_fade_start_km"), HandoverKm);
	Trace->SetNumberField(TEXT("march_fade_km"), FarFadeKm);
	Trace->SetNumberField(TEXT("layers_faded"), LayersFaded);
	Trace->SetStringField(TEXT("march_tier"), ANSI_TO_TCHAR(MarchName(March)));
	Trace->SetNumberField(TEXT("distance_to_sample_max_km"), CloudCvar(March, CvarDistanceToSampleMaxKm));
	Trace->SetStringField(TEXT("basis"),
		TEXT("the distant tracing (world_beauty.distant_tracing_max_km), constrained and the sheet drawn -> min(row, DISTANT_NEAR_FIELD_KM). "
		     "VolumetricCloud.usf: StepCount = SampleCountMax x saturate(path x InvDistanceToSampleCountMax) "
		     "(r.VolumetricCloud.DistanceToSampleMaxCount: the march tier's distance_to_sample_max_km, 15 km on the "
		     "constrained tier, sky step 3), non-decreasing in the path: a shorter trace never "
		     "adds a sample, only shortens the step; the sheet fades in over FadeKm up to the trace's end"));
	Out->SetObjectField(TEXT("volumetric_trace"), Trace);

	Out->SetNumberField(TEXT("base_m"), BaseM);
	Out->SetNumberField(TEXT("top_m"), TopM);
	Out->SetNumberField(TEXT("cover"), Cover);
	Out->SetStringField(TEXT("shape"), ANSI_TO_TCHAR(CloudName(Shape)));
	Out->SetStringField(TEXT("cover_basis"), CoverBasis);
	Out->SetNumberField(TEXT("coverage_contrast"), CloudRow[CldCoverageContrast]);
	Out->SetNumberField(TEXT("shape_scale_km"), CloudRow[CldShapeScaleKm]);
	Out->SetNumberField(TEXT("slice_km"), SliceKm);
	Out->SetNumberField(TEXT("handover_km"), HandoverKm);
	Out->SetNumberField(TEXT("fade_km"), DistantFadeKm);
	Out->SetNumberField(TEXT("radius_km"), DistantRadiusKm);
	Out->SetNumberField(TEXT("rings"), DistantRings);
	Out->SetNumberField(TEXT("segments"), DistantSegments);
	Out->SetNumberField(TEXT("vertices"), DistantDiscVertexCount());
	Out->SetNumberField(TEXT("triangles"), DistantDiscTriangleCount());
	Out->SetNumberField(TEXT("droop_at_rim_m"), DistantDroopAtRimM());
	Out->SetNumberField(TEXT("inside_ramp_m"), DistantInsideRampM);
	Out->SetObjectField(TEXT("look"), Look);
	Out->SetStringField(TEXT("seed_offset_km"),
		FString::Printf(TEXT("%.6f,%.6f,%.6f"), SeedKm[0], SeedKm[1], SeedKm[2]));
	Out->SetStringField(TEXT("material"), WorldDistantMaterialPath);
	Out->SetStringField(TEXT("lighting"),
		TEXT("faked in distant_clouds.hlsl: N.L (wrapped) from the shape's screen-space gradient, the sun's illuminance "
		     "and direction and the sky's distant scattered luminance from the SkyAtmosphere material nodes (atmosphere "
		     "light 0), dark bases from below, a sun-coloured silver lining on backlit edges; height fog and aerial "
		     "perspective applied per pixel (Apply Fogging)"));
	Out->SetStringField(TEXT("sheet_altitude_law"),
		TEXT("per frame (frames[].distant_sheet_*): at the deck's base with the camera below the slab's middle (bases), "
		     "at its top above (tops); faded out inside the slab (world_beauty.distant_sheet_altitude_m)"));
	Out->SetStringField(TEXT("drawn"),
		TEXT("M_FlightSimDistantClouds on one earth-curved disc centred on the camera, re-centred and re-levelled per frame"));
	Record->SetObjectField(TEXT("distant_clouds"), Out);
}

// Round 148 (FlightSimHdriSky.h): right after the sky light's capture-once. The
// lightning pulse sets the sky light's intensity from SkyLightBaseIntensity every
// frame, so that base follows the switch's intensity change.
void FFlightSimWorldBeauty::SwitchSkyLightToHdri(UWorld* World, FFlightSimVisualScene& Scene)
{
	if (!bBuilt)
	{
		return;
	}
	const double Factor = HdriSky.SwitchSkyLight(World, Scene);
	SkyLightBaseIntensity = static_cast<float>(SkyLightBaseIntensity * Factor);
	if (HdriSky.Record.IsValid())
	{
		HdriSky.Record->SetNumberField(TEXT("lightning_base_intensity"), SkyLightBaseIntensity);
	}
}

// Round 147 (r146 #13, 2026-11-16): -look-high-ap=on|off (on by default). A camera
// above HighApMinAltitudeM sees the far deck out to its horizon, but the aerial-
// perspective LUT every translucent surface reads (the distant sheet among them) ends at
// the march row's depth (96 km constrained) and clamps beyond it, so the far cumulus
// stayed crisp white to the horizon. The LUT's depth becomes the camera's horizon
// (FlightSimWorldPure::HighApLutDepthKm); same LUT size and cost; RestoreCvars puts it back.
void FFlightSimWorldBeauty::ApplyHighAltitudeAerialPerspective(AActor* Aircraft)
{
	using namespace FlightSimWorldPure;
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	const bool bOn = HighApSwitch != TEXT("off");
	Out->SetStringField(TEXT("switch"), bOn ? TEXT("on") : TEXT("off"));
	const bool bKnown = Aircraft != nullptr;
	const double CameraM = bKnown ? Aircraft->GetActorLocation().Z / WorldCmPerMetre : 0.0;
	const bool bConstrained = CloudConstrainedGpu();
	const int32 MarchChosen = CloudMarchFor(TCHAR_TO_ANSI(*CloudMarchSwitch), bConstrained);
	const int32 March = MarchChosen >= 0 ? MarchChosen : (bConstrained ? MarchIntegrated : MarchDiscrete);
	const double RowKm = CloudCvar(March, CvarApLutDepthKm);
	const double DepthKm = HighApLutDepthKm(bOn && bKnown, CameraM, RowKm);
	Out->SetBoolField(TEXT("aircraft_known"), bKnown);
	Out->SetNumberField(TEXT("aircraft_z_m"), CameraM);
	Out->SetNumberField(TEXT("min_altitude_m"), HighApMinAltitudeM);
	Out->SetNumberField(TEXT("row_depth_km"), RowKm);
	Out->SetNumberField(TEXT("depth_km"), DepthKm);
	if (DepthKm > RowKm)
	{
		TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
		TArray<TSharedPtr<FJsonValue>> Skipped;
		const FString Name(ANSI_TO_TCHAR(CloudCvarName(CvarApLutDepthKm)));
		SetWorldCvar(*Name, DepthKm, Row, Skipped);
		Out->SetObjectField(TEXT("cvars"), Row);
		Out->SetArrayField(TEXT("cvars_skipped"), Skipped);
	}
	Out->SetStringField(TEXT("basis"),
		TEXT("the translucent sheet reads the AP LUT, which clamps past its depth: above min_altitude_m the depth is "
		     "the camera's horizon sqrt(2 R h), at most HighApMaxKm, never below the row (world_beauty.high_ap_lut_depth_km). "
		     "Opaque surfaces take the per-pixel AP (FastApplyOnOpaque 0) and are unchanged. UNCALIBRATED"));
	Record->SetObjectField(TEXT("high_altitude_ap"), Out);
}

// Visual round 5, lane L3 (2026-11-10, optional probe): the pinned, sun-clamped
// Poly Haven sky (core/scene/sky_hdri.py) as the sky light's SPECIFIED CUBEMAP
// on the clear and hazy presets, so the fill's colour can be compared against
// the captured sky's (the #02 blue). The sky light's intensity becomes
// fill_share x the sun's illuminance / pi (the prepared cubemap's upper
// hemisphere has mean luminance 1). Hero lighting (later) still sets the
// light's colour; the commandlet's capture-once picks all of this up.
bool FFlightSimWorldBeauty::ApplySkyHdri(FFlightSimVisualScene& Scene, const FString& Name, const TCHAR* Params,
                                         FString& Error)
{
	// Function-local: unity builds merge anonymous namespaces (NEXT.md gotcha 3).
	using namespace FlightSimWorldPure;
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	Out->SetStringField(TEXT("name"), Name);
	Out->SetStringField(TEXT("preset"), ANSI_TO_TCHAR(PresetName(Preset)));
	if (Name.IsEmpty() || Name == TEXT("off"))
	{
		Out->SetBoolField(TEXT("applied"), false);
		Out->SetStringField(TEXT("sky"), TEXT("the scene's captured sky (no -sky-hdri=)"));
		Record->SetObjectField(TEXT("sky_hdri"), Out);
		return true;
	}
	for (const TCHAR C : Name)
	{
		if (!FChar::IsAlnum(C) && C != TEXT('_'))
		{
			Error = FString::Printf(TEXT("world_beauty.sky_hdri: -sky-hdri=%s is not a pinned sky name "
			                             "(core/scene/sky_hdri.py HDRIS)"), *Name);
			return false;
		}
	}
	double FillShare = WorldSkyHdriFillShareDefault;
	FParse::Value(Params, TEXT("sky-hdri-fill="), FillShare);
	if (!(FillShare > 0.0) || !FMath::IsFinite(FillShare))
	{
		Error = FString::Printf(TEXT("world_beauty.sky_hdri: -sky-hdri-fill=%g is not a positive share"), FillShare);
		return false;
	}
	double YawDeg = 0.0;
	FParse::Value(Params, TEXT("sky-hdri-yaw="), YawDeg);
	Out->SetNumberField(TEXT("fill_share"), FillShare);
	Out->SetNumberField(TEXT("yaw_deg"), YawDeg);
	if (Preset != PresetClear && Preset != PresetHazy)
	{
		Out->SetBoolField(TEXT("applied"), false);
		Out->SetStringField(TEXT("sky"),
			TEXT("the scene's captured sky: the HDRI probe applies to the clear and hazy presets only"));
		Record->SetObjectField(TEXT("sky_hdri"), Out);
		return true;
	}
	USkyLightComponent* Sky = Scene.SkyLightComponent;
	if (Sky == nullptr)
	{
		Error = FString::Printf(TEXT("world_beauty.sky_hdri: the scene has no sky light to put %s on"), *Name);
		return false;
	}
	const FString AssetPath = FString::Printf(TEXT("/Game/FlightSim/Sky/T_SkyHdri_%s.T_SkyHdri_%s"), *Name, *Name);
	UTextureCube* Cube = LoadObject<UTextureCube>(nullptr, *AssetPath);
	if (Cube == nullptr)
	{
		Error = FString::Printf(TEXT("world_beauty.sky_hdri: %s did not load (prepare it: python -m core.scene.sky_hdri ")
		                        TEXT("prepare %s, then FLIGHTSIM_SKY_HDRI=%s scripts/ue_create_materials.py in the editor)"),
		                        *AssetPath, *Name, *Name);
		return false;
	}
	double SunLux = 0.0;
	if (Scene.Sun != nullptr && Scene.Sun->GetLightComponent() != nullptr)
	{
		SunLux = Scene.Sun->GetLightComponent()->Intensity;
	}
	Out->SetBoolField(TEXT("real_time_capture_before"), Sky->IsRealTimeCaptureEnabled());
	Out->SetNumberField(TEXT("source_type_before"), static_cast<int32>(Sky->SourceType));
	Out->SetNumberField(TEXT("intensity_before"), Sky->Intensity);
	// A real-time capture ignores the source type: off, as the capture-once expects.
	Sky->SetRealTimeCapture(false);
	Sky->SourceType = SLS_SpecifiedCubemap;
	Sky->SetCubemap(Cube);
	Sky->SetSourceCubemapAngle(static_cast<float>(YawDeg));
	if (SunLux > 0.0)
	{
		Sky->SetIntensity(static_cast<float>(FillShare * SunLux / PI));
	}
	Sky->SetCaptureIsDirty();
	Sky->MarkRenderStateDirty();
	Out->SetBoolField(TEXT("applied"), true);
	Out->SetStringField(TEXT("asset"), AssetPath);
	Out->SetNumberField(TEXT("sun_lux_at_build"), SunLux);
	Out->SetNumberField(TEXT("intensity"), Sky->Intensity);
	Out->SetStringField(TEXT("intensity_basis"), SunLux > 0.0
		? TEXT("fill_share x the sun light's illuminance / pi (the prepared cubemap's upper hemisphere has mean "
		       "luminance 1: core/scene/sky_hdri.py prepare); the sun light read as set before this call")
		: TEXT("kept: no sun light intensity to scale from"));
	Out->SetStringField(TEXT("cubemap"),
		TEXT("the pinned Poly Haven CC0 sky (core/scene/sky_hdri.py HDRIS, sha256-pinned, cached, never committed) with "
		     "its sun disk clamped and its upper hemisphere normalised; the sidecar beside the cached file records the "
		     "clamp and the sun's image longitude for -sky-hdri-yaw="));
	Out->SetStringField(TEXT("watch"),
		TEXT("the #02 blue: compare the shade's R/B against the captured-sky frame of the A/B pair; hero lighting's "
		     "SetLightColor still tints this fill"));
	Out->SetStringField(TEXT("calibration"), TEXT("UNCALIBRATED: set by probe render on the render machine"));
	Record->SetObjectField(TEXT("sky_hdri"), Out);
	return true;
}

// Sky step 6 (the owner's X-Plane-12 brief, 2026-11-15): the high cirrus sheet.
// BEAUTY ONLY, VISUAL ONLY. UE draws one volumetric cloud layer; the reference
// photograph's upper sky is thin cirrus. One UProceduralMeshComponent disc
// (BuildCurvedDisc at FlightSimWorldPure::CirrusRadiusKm) on M_FlightSimCirrus
// (unlit, translucent, two-sided; no depth write, no custom depth, no velocity,
// fog and aerial perspective per pixel), centred on the camera and put at
// CirrusSheetAltitudeM (above the camera by construction) by Advance. The
// shader (cirrus.hlsl) draws seeded streaks along the card's drift bearing with
// feathered ends, cut at the cover's quantile, lit by a forward lobe of the sun
// and the sky's distant luminance. Labels: the actor is in BeautyOnlyActors, so
// every label capture hides it; the material writes no depth and no custom
// depth. Cover: core/scene/cirrus.py cirrus_cover (the plan's data, the stated
// default, or none). UNMEASURED: nothing here has been rendered.
void FFlightSimWorldBeauty::ApplyCirrus(UWorld* World, FFlightSimVisualScene& Scene, int32 Seed)
{
	// Function-local: unity builds merge anonymous namespaces (NEXT.md gotcha 3).
	using namespace FlightSimWorldPure;
	CirrusSheet = FCirrusSheetState();
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	Out->SetStringField(TEXT("switch"), CirrusSwitch);
	Out->SetStringField(TEXT("labels"),
		TEXT("BeautyOnlyActors; unlit translucent, no depth write, no custom depth, no velocity, no shadow; "
		     "the measure quality never builds it"));
	Out->SetBoolField(TEXT("visual_only"), true);
	Out->SetStringField(TEXT("calibration"), TEXT("UNCALIBRATED: set by probe render on the render machine"));
	Out->SetStringField(TEXT("measured"),
		TEXT("UNMEASURED: never rendered; docs/VISUAL_FIDELITY_PLAN.md section 8 'Sky step 6' names the Windows command"));
	// The cover and where it came from (the plan's data, the switch, the default, or none).
	const bool bPlanFields = SkyPlanRef != nullptr && SkyPlanRef->bCloudPlanFields;
	const bool bFromData = bPlanFields && SkyPlanRef->bCloudCoverFromData;
	const double PlanCirrus = bPlanFields ? SkyPlanRef->CloudCirrusCoverage : 0.0;
	const bool bSwitchCirrus = CloudTypeSwitch == TEXT("cirrus");
	int32 Source = CirrusSourceDefault;
	const double Cover = CirrusCover(CirrusSwitch == TEXT("off"), bSwitchCirrus, bFromData, PlanCirrus, Preset, &Source);
	Out->SetNumberField(TEXT("coverage"), Cover);
	Out->SetStringField(TEXT("coverage_source"), ANSI_TO_TCHAR(CirrusCoverSourceName(Source)));
	Out->SetNumberField(TEXT("plan_cirrus_coverage"), PlanCirrus);
	Out->SetBoolField(TEXT("plan_cover_from_data"), bFromData);
	Out->SetStringField(TEXT("plan_coverage_source"), SkyPlanRef != nullptr ? SkyPlanRef->CloudCoverageSource : FString());
	Out->SetNumberField(TEXT("default_cover"), CirrusDefaultCover);
	Out->SetStringField(TEXT("cover_law"),
		TEXT("core/scene/cirrus.py cirrus_cover: -look-cirrus=off -> none; a rain or storm preset -> none (the deck "
		     "covers the sky); -cloud-type=cirrus with no data cover above 0 -> the default; a plan whose cover came "
		     "from data (cover_inputs) -> its cirrus_coverage, 0 included; else the default (a stated stylisation: "
		     "the reference photograph's upper sky)"));
	Out->SetStringField(TEXT("preset"), ANSI_TO_TCHAR(PresetName(Preset)));
	if (Cover < CirrusMinDrawnCover)
	{
		Out->SetStringField(TEXT("drawn"), FString::Printf(TEXT("nothing: cover %.3f below %.2f (%s)"), Cover,
		                                                   CirrusMinDrawnCover, ANSI_TO_TCHAR(CirrusCoverSourceName(Source))));
		Record->SetObjectField(TEXT("cirrus"), Out);
		return;
	}
	UMaterialInterface* Base = LoadObject<UMaterialInterface>(nullptr, WorldCirrusMaterialPath);
	if (Base == nullptr)
	{
		Out->SetStringField(TEXT("drawn"),
			TEXT("nothing: M_FlightSimCirrus did not load (run scripts/ue_create_materials.py)"));
		Record->SetObjectField(TEXT("cirrus"), Out);
		return;
	}

	AActor* Actor = World->SpawnActor<AActor>();
	UProceduralMeshComponent* Mesh = NewObject<UProceduralMeshComponent>(Actor, TEXT("CirrusSheet"));
	Actor->SetRootComponent(Mesh);
	Mesh->SetMobility(EComponentMobility::Movable);
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Mesh->SetCastShadow(false);
	Mesh->SetRenderCustomDepth(false);
	Mesh->SetReceivesDecals(false);
	// Behind the distant sheet (-100) and every other translucent: lower sorts first.
	Mesh->SetTranslucentSortPriority(CirrusSortPriority);
	BuildCurvedDisc(Mesh, CirrusRadiusKm);
	Mesh->RegisterComponent();
	Actor->SetActorLocation(FVector::ZeroVector);   // Advance centres it on the camera

	// The material: the cover, the streak bearing, the look; seeded like the layers.
	double SeedKm[3] = {0.0, 0.0, 0.0};
	CloudSeedOffsetKm(static_cast<uint64_t>(static_cast<int64_t>(Seed)), SeedKm);
	const double StreakDirDeg = CirrusStreakDirDeg(static_cast<uint64_t>(static_cast<int64_t>(Seed)), DriftMps, DriftFromDeg);
	UMaterialInstanceDynamic* Material = UMaterialInstanceDynamic::Create(Base, Actor);
	Material->SetScalarParameterValue(TEXT("Coverage"), static_cast<float>(Cover));
	Material->SetScalarParameterValue(TEXT("StreakDirDeg"), static_cast<float>(StreakDirDeg));
	Material->SetScalarParameterValue(TEXT("RadiusKm"), static_cast<float>(CirrusRadiusKm));
	Material->SetScalarParameterValue(TEXT("SheetFade"), 1.0f);
	TSharedPtr<FJsonObject> Look = MakeShared<FJsonObject>();
	for (int32 F = 0; F < CirrusLookCount; ++F)
	{
		Material->SetScalarParameterValue(ANSI_TO_TCHAR(CirrusLookName(F)), static_cast<float>(CirrusLook(F)));
		Look->SetNumberField(ANSI_TO_TCHAR(CirrusLookName(F)), CirrusLook(F));
	}
	Material->SetVectorParameterValue(TEXT("SeedOffsetKm"),
		FLinearColor(static_cast<float>(SeedKm[0]), static_cast<float>(SeedKm[1]), static_cast<float>(SeedKm[2]), 0.0f));
	Material->SetVectorParameterValue(TEXT("WindOffsetM"), FLinearColor(0.0f, 0.0f, 0.0f, 0.0f));
	Mesh->SetMaterial(0, Material);
	Scene.BeautyOnlyActors.Add(Actor);
	CirrusSheet.Actor = Actor;
	CirrusSheet.Mesh = Mesh;
	CirrusSheet.Material = Material;
	CirrusSheet.Cover = Cover;
	CirrusSheet.bDrawn = true;

	Out->SetNumberField(TEXT("base_m"), CirrusBaseM);
	Out->SetNumberField(TEXT("clearance_m"), CirrusClearanceM);
	Out->SetNumberField(TEXT("max_m"), CirrusMaxM);
	Out->SetStringField(TEXT("altitude_law"),
		TEXT("per frame (frames[].cirrus_altitude_m, cirrus_fade): min(max(base_m, camera + clearance_m), max_m), "
		     "never below the camera; faded out over the clearance as the camera reaches max_m (cirrus.cirrus_sheet)"));
	Out->SetNumberField(TEXT("radius_km"), CirrusRadiusKm);
	Out->SetNumberField(TEXT("rings"), DistantRings);
	Out->SetNumberField(TEXT("segments"), DistantSegments);
	Out->SetNumberField(TEXT("vertices"), DistantDiscVertexCount());
	Out->SetNumberField(TEXT("triangles"), DistantDiscTriangleCount());
	Out->SetNumberField(TEXT("droop_at_rim_m"), DistantDroopM(CirrusRadiusKm));
	Out->SetNumberField(TEXT("sort_priority"), CirrusSortPriority);
	Out->SetNumberField(TEXT("streak_dir_deg"), StreakDirDeg);
	Out->SetStringField(TEXT("streak_dir_source"),
		DriftMps > 0.0 ? TEXT("the card's cloud drift bearing (streaks run along the wind)") : TEXT("seeded (the card does not drift)"));
	Out->SetNumberField(TEXT("drift_mps"), CirrusDriftMps(DriftMps));
	Out->SetNumberField(TEXT("wind_gain"), CirrusWindGain);
	Out->SetObjectField(TEXT("look"), Look);
	Out->SetStringField(TEXT("seed_offset_km"),
		FString::Printf(TEXT("%.6f,%.6f,%.6f"), SeedKm[0], SeedKm[1], SeedKm[2]));
	Out->SetStringField(TEXT("material"), WorldCirrusMaterialPath);
	Out->SetStringField(TEXT("lighting"),
		TEXT("the cirrus shader draws a normalised Henyey-Greenstein forward lobe (ForwardG, capped) blended with an isotropic term "
		     "x the sun's illuminance through the atmosphere x albedo / pi, plus the sky's distant scattered luminance x "
		     "AmbientGain (SkyAtmosphere material nodes, light 0); opacity Beer's law on the slant path, capped at "
		     "MaxOpacity; height fog and aerial perspective per pixel"));
	Out->SetStringField(TEXT("drawn"),
		TEXT("M_FlightSimCirrus on one earth-curved disc centred on the camera above the flight, re-centred and re-levelled per frame"));
	Record->SetObjectField(TEXT("cirrus"), Out);
}

// #02 blue (2026-11-11): the tiles' baked sky-shade toward grey under a drawn sun
// (assets/shaders/world/tiles_shade_neutral.hlsl; Python twin
// core/scene/tiles_shade_neutral.py, whose SHADE_NEUTRAL_DEFAULTS and constants
// tests/test_tiles_shade_neutral.py pins to the numbers below). BEAUTY ONLY:
// only FFlightSimWorldBeauty::ApplyTiles sets ShadeNeutralAmount. No engine call
// beyond the collection's SetScalarParameterValue. UNCALIBRATED: every number.
namespace FlightSimTilesShade
{
	// ShadeNeutralAmount per FlightSimWorldPure preset: clear, hazy, overcast, rain, storm.
	constexpr double ShadeNeutralAmounts[FlightSimWorldPure::PresetCount] = {1.0, 1.0, 0.0, 0.0, 0.0};
	constexpr double ShadeLumaKnee = 0.30;
	constexpr double ShadeBlueGate = 4.0;

	// Round 75-78 (2026-11-12): a low sun's frame is warm already, so the bake's
	// blue is half the defect: x SunLowScale at or below SunLowDeg, x1 at or above
	// SunHighDeg, linear between (#01 at 6 deg: amount 1 amber B-R -77, 0.5 -42;
	// #02 at 72 deg: 1 is right). UNCALIBRATED.
	constexpr double SunLowDeg = 10.0;
	constexpr double SunHighDeg = 40.0;
	constexpr double SunLowScale = 0.5;

	inline double SunScale(double SunElevationDeg)
	{
		const double T = FMath::Clamp((SunElevationDeg - SunLowDeg) / (SunHighDeg - SunLowDeg), 0.0, 1.0);
		return SunLowScale + (1.0 - SunLowScale) * T;
	}

	inline double PresetAmount(int32 Preset)
	{
		return Preset >= 0 && Preset < FlightSimWorldPure::PresetCount ? ShadeNeutralAmounts[Preset] : 0.0;
	}

	// 0 over a city card (blue glass and roofs are colour) or with the switch off.
	inline double AmountFor(int32 Preset, const FString& Surface, const FString& Switch, double SunElevationDeg)
	{
		// Round 63 diagnostic: force = 2, the shader greys every texel.
		if (Switch == TEXT("force"))
		{
			return 2.0;
		}
		if (Switch == TEXT("off") || Surface == TEXT("city"))
		{
			return 0.0;
		}
		// Round 75 A/B: a number (-tiles-shade-neutral=0.5) is the amount itself, 0..1.
		if (!Switch.IsEmpty() && FCString::IsNumeric(*Switch))
		{
			return FMath::Clamp(FCString::Atod(*Switch), 0.0, 1.0);
		}
		return PresetAmount(Preset) * SunScale(SunElevationDeg);
	}

	// render.json world_beauty.tiles.shade_neutral.
	TSharedPtr<FJsonObject> ShadeRecord(int32 Preset, const FString& Surface, const FString& Switch,
	                                    double SunElevationDeg)
	{
		TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
		Out->SetNumberField(TEXT("amount"), AmountFor(Preset, Surface, Switch, SunElevationDeg));
		Out->SetNumberField(TEXT("sun_elevation_deg"), SunElevationDeg);
		Out->SetNumberField(TEXT("sun_scale"), SunScale(SunElevationDeg));
		Out->SetNumberField(TEXT("preset_amount"), PresetAmount(Preset));
		Out->SetStringField(TEXT("switch"), Switch == TEXT("off") ? FString(TEXT("off"))
			: (!Switch.IsEmpty() && FCString::IsNumeric(*Switch)) ? Switch : FString(TEXT("on")));
		Out->SetNumberField(TEXT("luma_knee"), ShadeLumaKnee);
		Out->SetNumberField(TEXT("blue_gate"), ShadeBlueGate);
		// Round 58/59: a vertex-normal level test never passed (Cesium's unlit
		// tiles carry the ellipsoid's up on every vertex); the shader takes the face's.
		Out->SetStringField(TEXT("level_basis"),
			TEXT("the triangle's face normal from the world position's screen derivatives; the tiles' vertex "
			     "normals are the ellipsoid's up (Cesium, KHR_materials_unlit)"));
		Out->SetStringField(TEXT("basis"),
			TEXT("the photogrammetry's baked sky-shade (violet-blue, darker than the knee, not level) moved toward "
			     "the grey of its own luma under a drawn sun; shader per frame, nothing stored (Google tile policy)"));
		Out->SetBoolField(TEXT("pixel_moving"), false);
		Out->SetStringField(TEXT("calibration"), TEXT("UNCALIBRATED"));
		return Out;
	}
}

// Round 147 (2026-11-16, #06's quilted bay): open water on the tiles moved from each
// tile's own mean colour to one WaterMean (assets/shaders/world/tiles_water_unify.hlsl;
// Python twin core/scene/tiles_water_unify.py, whose WATER_UNIFY_DEFAULTS
// tests/test_tiles_water_unify.py pins to the numbers below). BEAUTY ONLY: only
// FFlightSimWorldBeauty::ApplyTiles sets WaterUnifyAmount. UNCALIBRATED.
namespace FlightSimTilesWater
{
	// WaterUnifyAmount per FlightSimWorldPure preset: clear, hazy, overcast, rain, storm.
	constexpr double WaterUnifyAmounts[FlightSimWorldPure::PresetCount] = {0.0, 0.0, 1.0, 1.0, 1.0};
	// tiles_water_unify.hlsl WATER_MEAN (linear), for the record only.
	constexpr double WaterMean[3] = {0.020, 0.040, 0.055};

	inline double PresetAmount(int32 Preset)
	{
		return Preset >= 0 && Preset < FlightSimWorldPure::PresetCount ? WaterUnifyAmounts[Preset] : 0.0;
	}

	// -tiles-water-unify=off is 0; a number is the amount itself (0..1); else the preset's.
	inline double AmountFor(int32 Preset, const FString& Switch)
	{
		if (Switch == TEXT("off"))
		{
			return 0.0;
		}
		if (!Switch.IsEmpty() && FCString::IsNumeric(*Switch))
		{
			return FMath::Clamp(FCString::Atod(*Switch), 0.0, 1.0);
		}
		return PresetAmount(Preset);
	}

	// render.json world_beauty.tiles.water_unify.
	TSharedPtr<FJsonObject> WaterRecord(int32 Preset, const FString& Switch)
	{
		TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
		Out->SetNumberField(TEXT("amount"), AmountFor(Preset, Switch));
		Out->SetNumberField(TEXT("preset_amount"), PresetAmount(Preset));
		Out->SetStringField(TEXT("switch"), Switch == TEXT("off") ? FString(TEXT("off"))
			: (!Switch.IsEmpty() && FCString::IsNumeric(*Switch)) ? Switch : FString(TEXT("on")));
		Out->SetStringField(TEXT("basis"),
			TEXT("open water (a level face, dark blue-or-teal local mean, little texture contrast) moved from its "
			     "tile's own mean colour to one WATER_MEAN, keeping its luma ratio to that mean; shader per frame, "
			     "nothing stored (Google tile policy)"));
		TArray<TSharedPtr<FJsonValue>> Mean;
		for (const double V : WaterMean)
		{
			Mean.Add(MakeShared<FJsonValueNumber>(V));
		}
		Out->SetArrayField(TEXT("water_mean"), Mean);
		Out->SetBoolField(TEXT("pixel_moving"), false);
		Out->SetStringField(TEXT("calibration"), TEXT("UNCALIBRATED"));
		return Out;
	}
}

void FFlightSimWorldBeauty::ApplyTiles(UWorld* World, FFlightSimGoogleTiles& Tiles, double CardWetness,
                                       double SunElevationDeg)
{
	// Function-local: unity builds merge anonymous namespaces (NEXT.md gotcha 3).
	using namespace FlightSimWorldPure;
	TSharedPtr<FJsonObject> Out;
	if (!Tiles.IsEnabled())
	{
		Out = MakeShared<FJsonObject>();
		Out->SetStringField(TEXT("applied"),
			TEXT("nothing: the tiles are not drawn for this scene (google_tiles.declined, -NoGoogleTiles or "
			     "FLIGHTSIM_GOOGLE_TILES=off); the scene's ground keeps its own Wetness"));
		Record->SetObjectField(TEXT("tiles"), Out);
		return;
	}
	UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, WorldTilesMaterialPath);
	Out = Tiles.ApplyBeautyLook(Material);
	const double* Row = &AtmosphereValues[Preset * AtmosphereFieldCount];
	const double Wetness = TilesWetness(CardWetness, Row[AtmWetnessFloor]);
	// The collection is the ground's one wetness and grade (the tiles AND the
	// scatter read it): set only when the tiles really draw with the beauty
	// material, so the scatter can never go wet over tiles left at Cesium's
	// own dry material.
	FString MaterialRoute;
	Out->TryGetStringField(TEXT("material_route"), MaterialRoute);
	const bool bTilesMaterial = MaterialRoute == TEXT("ACesium3DTileset::SetMaterial (read back)")
		|| MaterialRoute == TEXT("UFunction SetMaterial") || MaterialRoute == TEXT("UPROPERTY Material");
	UMaterialParameterCollection* Collection =
		bTilesMaterial ? LoadObject<UMaterialParameterCollection>(nullptr, WorldCollectionPath) : nullptr;
	UMaterialParameterCollectionInstance* Instance =
		Collection != nullptr ? World->GetParameterCollectionInstance(Collection) : nullptr;
	TSharedPtr<FJsonObject> Parameters = MakeShared<FJsonObject>();
	if (Instance != nullptr)
	{
		struct FWorldScalar
		{
			const TCHAR* Name;
			double Value;
		};
		const FWorldScalar Scalars[] = {
			{TEXT("Wetness"), Wetness},
			{TEXT("PuddleAmount"), Wetness * PuddleShare},
			{TEXT("Dehaze"), TilesDehaze},
			{TEXT("Saturation"), TilesSaturation},
			{TEXT("DetailStrength"), Row[AtmTilesDetailStrength]},
			{TEXT("DetailFadeM"), DetailFadeM},
			{TEXT("DetailScaleM"), DetailScaleM},
			// tiles-delight hook (FlightSimTilesDelight above).
			{TEXT("DelightAmount"), FlightSimTilesDelight::AmountFor(Preset)},
			{TEXT("DelightBlueGate"), FlightSimTilesDelight::DelightBlueGate},
			// lane B terrain detail: the snowline is an altitude (engine Z 0 is
			// the origin's orthometric height; the tiles are enabled here).
			{TEXT("GroundAltitudeM"), Tiles.GetOriginOrthometricHeightM()},
			{TEXT("GroundAltitudeKnown"), 1.0},
			// lane B: no aerial rock / soil detail on a city's facades and roofs.
			{TEXT("TerrainDetailScale"), Surface == TEXT("city") ? 0.0 : 1.0},
			// #02 blue: the baked sky-shade neutraliser (FlightSimTilesShade above).
			{TEXT("ShadeNeutralAmount"), FlightSimTilesShade::AmountFor(Preset, Surface, TilesShadeSwitch, SunElevationDeg)},
			// Round 147: open water to one mean across tile edges (FlightSimTilesWater above).
			{TEXT("WaterUnifyAmount"), FlightSimTilesWater::AmountFor(Preset, TilesWaterSwitch)},
		};
		for (const FWorldScalar& Scalar : Scalars)
		{
			const bool bSet = Instance->SetScalarParameterValue(FName(Scalar.Name), static_cast<float>(Scalar.Value));
			Parameters->SetNumberField(Scalar.Name, Scalar.Value);
			if (!bSet)
			{
				Parameters->SetStringField(FString::Printf(TEXT("%s_set"), Scalar.Name),
				                           TEXT("NOT SET: the collection has no such scalar"));
			}
		}
		Out->SetStringField(TEXT("collection"), WorldCollectionPath);
	}
	else
	{
		Out->SetStringField(TEXT("collection"), bTilesMaterial
			? TEXT("absent: MPC_FlightSimWorld did not load (run scripts/ue_create_materials.py); the tiles "
			       "material reads its defaults (dry, ungraded)")
			: TEXT("not set: the tiles do not draw with M_FlightSimTilesBeauty (material_route), so the ground "
			       "and the scatter both stay at the collection's defaults (dry, ungraded)"));
	}
	Out->SetStringField(TEXT("dehaze_law"),
		TEXT("soft toe: removal Dehaze x HAZE_RGB (0.010, 0.015, 0.022) x a / (a + k), k = h / (1 - 0.5), white kept "
		     "white; a dark texel keeps at least half of itself (world_beauty.TILES_HAZE_RGB, TILES_DEHAZE_TOE, "
		     "UNCALIBRATED)"));
	Out->SetStringField(TEXT("grade_basis"),
		TEXT("Dehaze and Saturation are the tileset's imagery correction (world_beauty.TILES_DEHAZE, "
		     "TILES_SATURATION, UNCALIBRATED), one value for every weather; the weather's grade is beauty_look's "
		     "frame grade alone"));
	Out->SetObjectField(TEXT("parameters"), Parameters);
	Out->SetObjectField(TEXT("delight"), FlightSimTilesDelight::DelightRecord(Preset));   // tiles-delight hook
	Out->SetObjectField(TEXT("shade_neutral"),                                            // #02 blue
		FlightSimTilesShade::ShadeRecord(Preset, Surface, TilesShadeSwitch, SunElevationDeg));
	Out->SetObjectField(TEXT("water_unify"), FlightSimTilesWater::WaterRecord(Preset, TilesWaterSwitch));   // round 147
	Out->SetStringField(TEXT("wetness_basis"), TEXT("max(the card's wetness, the preset's wetness_floor)"));
	Out->SetStringField(TEXT("rule"),
		TEXT("the tiles stay the ground of every terrain render (the owner's rule); this changes their shading only"));
	Record->SetObjectField(TEXT("tiles"), Out);
}

void FFlightSimWorldBeauty::Advance(double TimeSeconds, const FVector& CameraCm, const FVector& AircraftCm,
                                    int32 FrameIndex)
{
	// Function-local: unity builds merge anonymous namespaces (NEXT.md gotcha 3).
	using namespace FlightSimWorldPure;
	if (!bBuilt)
	{
		return;
	}
	TSharedPtr<FJsonObject> Frame = MakeShared<FJsonObject>();
	Frame->SetNumberField(TEXT("frame"), FrameIndex);
	Frame->SetNumberField(TEXT("t_s"), TimeSeconds);

	// The clouds drift with the wind at their base, on the FDM's time (the
	// scene's own law, FFlightSimVisualScene::CloudDriftOffsetMetres).
	FVector DriftOffset = FVector::ZeroVector;
	if (DriftMps > 0.0)
	{
		DriftOffset = FFlightSimVisualScene::CloudDriftOffsetMetres(DriftMps, DriftFromDeg, TimeSeconds);
		for (FCloudLayerState& Layer : CloudLayers)
		{
			if (Layer.Material != nullptr)
			{
				Layer.Material->SetVectorParameterValue(TEXT("WindOffsetM"),
					FLinearColor(static_cast<float>(DriftOffset.X), static_cast<float>(DriftOffset.Y), 0.0f, 0.0f));
			}
		}
	}
	// Visual round 5, lane L3: the distant sheet follows the camera (its noise is
	// in world space, so the clouds stay put), sits at the deck's base or top,
	// fades out with the camera inside the slab, and drifts with the layer.
	if (DistantSheet.bDrawn && DistantSheet.Actor != nullptr && DistantSheet.Material != nullptr)
	{
		const FDistantSheet Sheet = DistantSheetAltitudeM(CameraCm.Z / WorldCmPerMetre, DistantSheet.BaseM, DistantSheet.TopM);
		DistantSheet.Actor->SetActorLocation(FVector(CameraCm.X, CameraCm.Y, Sheet.AltitudeM * WorldCmPerMetre));
		DistantSheet.Material->SetScalarParameterValue(TEXT("SheetFade"), static_cast<float>(Sheet.Fade));
		if (DriftMps > 0.0)
		{
			DistantSheet.Material->SetVectorParameterValue(TEXT("WindOffsetM"),
				FLinearColor(static_cast<float>(DriftOffset.X), static_cast<float>(DriftOffset.Y), 0.0f, 0.0f));
		}
		Frame->SetNumberField(TEXT("distant_sheet_altitude_m"), Sheet.AltitudeM);
		Frame->SetBoolField(TEXT("distant_sheet_from_above"), Sheet.bFromAbove);
		Frame->SetNumberField(TEXT("distant_sheet_fade"), Sheet.Fade);
	}
	// Sky step 6: the cirrus sheet follows the camera (its noise is in world space,
	// so the streaks stay put), sits at the altitude law's height above it, fades
	// as the camera reaches the cap, and drifts at CirrusWindGain x the card's drift.
	if (CirrusSheet.bDrawn && CirrusSheet.Actor != nullptr && CirrusSheet.Material != nullptr)
	{
		const FCirrusSheet Sheet = CirrusSheetAltitudeM(CameraCm.Z / WorldCmPerMetre);
		CirrusSheet.Actor->SetActorLocation(FVector(CameraCm.X, CameraCm.Y, Sheet.AltitudeM * WorldCmPerMetre));
		CirrusSheet.Material->SetScalarParameterValue(TEXT("SheetFade"), static_cast<float>(Sheet.Fade));
		if (DriftMps > 0.0)
		{
			const FVector CirrusDrift = FFlightSimVisualScene::CloudDriftOffsetMetres(
				CirrusDriftMps(DriftMps), DriftFromDeg, TimeSeconds);
			CirrusSheet.Material->SetVectorParameterValue(TEXT("WindOffsetM"),
				FLinearColor(static_cast<float>(CirrusDrift.X), static_cast<float>(CirrusDrift.Y), 0.0f, 0.0f));
		}
		Frame->SetNumberField(TEXT("cirrus_altitude_m"), Sheet.AltitudeM);
		Frame->SetNumberField(TEXT("cirrus_fade"), Sheet.Fade);
	}
	// Round 148: the HDRI backdrop follows the camera; its opacity is the camera's height law.
	HdriSky.Advance(CameraCm, Frame);

	// Sky step 4: the height fog's reference height follows the aircraft (the
	// engine's 655 m observer clamp: FlightSimWorldPure::FogReferenceZM), re-based
	// from the fog's CURRENT density (translation-invariant, so the dust haze's
	// later ratio on it is kept) once the aircraft has moved FogRebaseStepM.
	{
		const double AircraftZM = AircraftCm.Z / WorldCmPerMetre;
		int32 Rebased = 0;
		for (FBeautyFogProfile& Profile : FogProfiles)
		{
			UExponentialHeightFogComponent* Fog = Profile.Fog.Get();
			if (Fog == nullptr)
			{
				continue;
			}
			const FVector FogLocation = Fog->GetComponentLocation();
			const double CurrentZM = FogLocation.Z / WorldCmPerMetre;
			const double WantZM = FogReferenceZM(Profile.SceneZM, AircraftZM, true);
			if (FMath::Abs(WantZM - CurrentZM) >= FogRebaseStepM)
			{
				Fog->SetFogDensity(static_cast<float>(FogDensityRebased(Fog->FogDensity, Profile.Falloff, CurrentZM, WantZM)));
				Fog->SetWorldLocation(FVector(FogLocation.X, FogLocation.Y, WantZM * WorldCmPerMetre));
				Fog->MarkRenderStateDirty();
				++Rebased;
			}
			Frame->SetNumberField(TEXT("fog_reference_z_m"), Fog->GetComponentLocation().Z / WorldCmPerMetre);
		}
		if (FogProfiles.Num() > 0)
		{
			Frame->SetNumberField(TEXT("fog_rebased"), Rebased);
		}
	}

	// The lightning: both schedules, and the sky light's pulse.
	const double LookFlash = bLookLightning ? FFlightSimVisualScene::LightningFlash(TimeSeconds, LookSeed) : 0.0;
	const double StormLux = WeatherRef != nullptr ? WeatherRef->LastFlashLux() : 0.0;
	const double StormFlash = LightningReferenceLux > 0.0 ? StormLux / LightningReferenceLux : 0.0;
	const double Scale = SkyPulseScale(FMath::Max(LookFlash, StormFlash), LightningSkyGain);
	if (SkyLight != nullptr && LightningSkyGain > 0.0)
	{
		SkyLight->SetIntensity(static_cast<float>(SkyLightBaseIntensity * Scale));
	}
	Frame->SetNumberField(TEXT("flash_weather_look"), LookFlash);
	Frame->SetNumberField(TEXT("flash_storm_lux"), StormLux);
	Frame->SetNumberField(TEXT("sky_light_scale"), Scale);

	// The clouds between the camera and the aircraft (the labels' honesty row).
	TArray<TSharedPtr<FJsonValue>> Occlusions;
	bool bOccluded = false;
	double PathTransmittance = 1.0;
	const double LengthM = FVector::Distance(CameraCm, AircraftCm) / WorldCmPerMetre;
	for (const FCloudLayerState& Layer : CloudLayers)
	{
		const FOcclusion Occ = Occlusion(CameraCm.Z / WorldCmPerMetre, AircraftCm.Z / WorldCmPerMetre, LengthM,
		                                 Layer.BaseM, Layer.TopM, Layer.Cover,
		                                 // Sky step 2: the extinction drawn (the plan's density scale, 1 = the row)
		                                 CloudValues[Layer.Shape * CloudFieldCount + CldExtinctionPerM] * Layer.DensityScale,
		                                 CloudExtinctionScale, OcclusionFlagTransmittance);
		TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
		Row->SetNumberField(TEXT("path_m"), Occ.PathM);
		Row->SetNumberField(TEXT("tau"), Occ.Tau);
		Row->SetNumberField(TEXT("transmittance"), Occ.Transmittance);
		Occlusions.Add(MakeShared<FJsonValueObject>(Row));
		bOccluded = bOccluded || Occ.bFlagged;
		PathTransmittance *= FMath::Clamp(Occ.Transmittance, 0.0, 1.0);
	}
	// dust-humidity-haze: the second fog's camera-to-aircraft row, flagged like a cloud's.
	bool bDustFlagged = false;
	if (TSharedPtr<FJsonObject> DustRow = DustHaze.FrameRow(CameraCm, AircraftCm, OcclusionFlagTransmittance, bDustFlagged))
	{
		Occlusions.Add(MakeShared<FJsonValueObject>(DustRow));
		bOccluded = bOccluded || bDustFlagged;
	}
	Frame->SetArrayField(TEXT("cloud_path"), Occlusions);
	Frame->SetBoolField(TEXT("cloud_occludes_aircraft"), bOccluded);
	// False when a cloud is drawn that the slab model above does not cover (the
	// storm cell, another material's cloud, -beauty-clouds=engine, or the beauty
	// cloud material missing): cloud_occludes_aircraft is then only a lower bound.
	Frame->SetBoolField(TEXT("cloud_occlusion_complete"), UnmodelledClouds == 0);
	// Integration (render.json cloud_occlusion): the covered fraction along the
	// ray, summarised over the clip by CloudOcclusionRecord.
	const double CoveredFraction = 1.0 - PathTransmittance;
	Frame->SetNumberField(TEXT("cloud_covered_fraction_modelled"), CoveredFraction);
	++OcclusionFrames;
	OcclusionFlaggedFrames += bOccluded ? 1 : 0;
	OcclusionIncompleteFrames += UnmodelledClouds == 0 ? 0 : 1;
	MaxOccludedFraction = FMath::Max(MaxOccludedFraction, CoveredFraction);

	if (Scatter.IsBuilt())
	{
		Scatter.Resnap(CameraCm);
	}
	Frames.Add(MakeShared<FJsonValueObject>(Frame));
	Record->SetArrayField(TEXT("frames"), Frames);
}

TSharedPtr<FJsonObject> FFlightSimWorldBeauty::CloudOcclusionRecord() const
{
	// Integration (2026-11-09): the verifier's render.json "cloud_occlusion"
	// (docs/schemas/render_json_beauty_look.md), from this lane's own per-frame
	// rows. The decision is the one ApplyClouds records: clouds stay where the
	// card puts them and the mask is not edited -> "labels_unoccluded". The
	// covered fraction is the slab model's (UNCALIBRATED extinction), so its
	// basis is "modelled", never "measured".
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	Out->SetStringField(TEXT("policy"), TEXT("labels_unoccluded"));
	Out->SetStringField(TEXT("owner"), TEXT("world lane (FFlightSimWorldBeauty, look_applied.world_beauty.frames[])"));
	Out->SetNumberField(TEXT("frames"), OcclusionFrames);
	Out->SetNumberField(TEXT("frames_flagged_cloud_occludes_aircraft"), OcclusionFlaggedFrames);
	Out->SetNumberField(TEXT("frames_with_unmodelled_clouds"), OcclusionIncompleteFrames);
	Out->SetNumberField(TEXT("cloud_layers_modelled"), CloudLayers.Num());
	Out->SetNumberField(TEXT("unmodelled_clouds"), UnmodelledClouds);
	if (OcclusionIncompleteFrames > 0)
	{
		Out->SetField(TEXT("subject_occluded_fraction"), MakeShared<FJsonValueNull>());
		Out->SetStringField(TEXT("basis"),
			TEXT("not modelled: a drawn cloud is outside the slab model (the storm cell, another material's cloud, ")
			TEXT("-beauty-clouds=engine, or the beauty cloud material missing)"));
	}
	else
	{
		Out->SetNumberField(TEXT("subject_occluded_fraction"), MaxOccludedFraction);
		Out->SetStringField(TEXT("basis"), TEXT("modelled"));
	}
	Out->SetStringField(TEXT("method"),
		TEXT("max over frames of 1 - prod(layer transmittance) along the camera-to-aircraft-origin ray ")
		TEXT("(FlightSimWorldPure::Occlusion; per frame in look_applied.world_beauty.frames[].")
		TEXT("cloud_covered_fraction_modelled)"));
	Out->SetStringField(TEXT("not_modelled"),
		TEXT("rain, contrails, wingtip vapour and the afterburner plume (beauty-only translucent media) are not in ")
		TEXT("this fraction; experiments/look_label_check.py measures the covered fraction from the pixels"));
	return Out;
}
