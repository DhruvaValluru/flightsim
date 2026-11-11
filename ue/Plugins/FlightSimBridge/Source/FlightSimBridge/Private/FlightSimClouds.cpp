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
		CloudCount = 4
	};

	inline const char* PresetName(int Preset)
	{
		static const char* const Names[PresetCount] = {"clear", "hazy", "overcast", "rain", "storm"};
		return Preset >= 0 && Preset < PresetCount ? Names[Preset] : "clear";
	}

	inline const char* CloudName(int Cloud)
	{
		static const char* const Names[CloudCount] = {"cumulus", "stratocumulus", "overcast", "nimbostratus"};
		return Cloud >= 0 && Cloud < CloudCount ? Names[Cloud] : "cumulus";
	}

	// core/scene/world_beauty.py ATMOSPHERE_FIELDS, in order.
	// Fix pass 2026-11-09: the ground albedo (GroundAlbedoSrgb: the card's
	// surface and wetness) and the tiles' dehaze and saturation (tileset
	// constants) left the per-weather rows.
	constexpr int AtmosphereFieldCount = 13;
	inline const char* AtmosphereFieldName(int Field)
	{
		static const char* const Names[AtmosphereFieldCount] = {
			"mie_scale_height_km", "mie_anisotropy", "mie_share", "mie_cap_per_km",
			"aerial_perspective_scale", "vfog_distance_m", "vfog_scattering_distribution",
			"vfog_extinction_scale", "cloud_bottom_occlusion", "rain_readability_gain", "wetness_floor",
			"tiles_detail_strength", "lightning_sky_gain"};
		return Field >= 0 && Field < AtmosphereFieldCount ? Names[Field] : "";
	}
	enum : int
	{
		AtmMieScaleHeightKm = 0, AtmMieAnisotropy, AtmMieShare, AtmMieCapPerKm, AtmAerialPerspectiveScale,
		AtmVFogDistanceM, AtmVFogScatteringDistribution, AtmVFogExtinctionScale, AtmCloudBottomOcclusion,
		AtmRainReadabilityGain, AtmWetnessFloor, AtmTilesDetailStrength, AtmLightningSkyGain
	};

	// UNCALIBRATED: set by probe render on the render machine (every number).
	inline double AtmosphereDefault(int Preset, int Field)
	{
		static const double Rows[PresetCount][AtmosphereFieldCount] = {
			// clear
			{1.2, 0.80, 0.6, 0.25, 1.0, 8000.0, 0.75, 1.0, 0.5, 1.0, 0.0, 0.12, 0.0},
			// hazy
			{1.6, 0.76, 0.7, 0.6, 1.0, 8000.0, 0.7, 1.0, 0.5, 1.0, 0.0, 0.12, 0.0},
			// overcast
			{1.4, 0.70, 0.4, 0.6, 1.0, 6000.0, 0.4, 1.0, 0.75, 1.0, 0.0, 0.12, 0.0},
			// rain (vfog_extinction_scale: world_beauty.WET_VFOG_EXTINCTION_SCALE, visual round 3)
			{1.0, 0.65, 0.3, 0.8, 1.0, 4000.0, 0.3, 0.48, 0.85, 1.5, 0.6, 0.12, 0.0},
			// storm
			{1.8, 0.65, 0.3, 0.8, 1.0, 4000.0, 0.3, 0.48, 0.9, 1.5, 0.85, 0.12, 3.0},
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
			{0.05, 2.5, 0.35, 0.35, 0.08, 0.6, 1.6, 0.35},    // cumulus
			{0.04, 4.0, 0.5, 0.25, 0.15, 0.3, 1.3, 0.6},      // stratocumulus
			{0.03, 8.0, 0.8, 0.15, 0.2, 0.15, 1.0, 0.95},     // overcast
			{0.045, 9.0, 0.6, 0.3, 0.1, 0.4, 0.8, 0.98},      // nimbostratus
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
	enum : int
	{
		MarchDiscrete = 0,
		MarchIntegrated = 1,
		MarchCount = 2
	};
	inline const char* MarchName(int March)
	{
		static const char* const Names[MarchCount] = {"discrete", "integrated"};
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
	// both rows stay under the caps. The CONSTRAINED row (an integrated GPU, or any
	// adapter below SM6, e.g. D3D11 SM5) is ef361bd6's march exactly: 192 view and 10
	// shadow samples, an 80 km trace and a 15 km shadow march, with no thinning of the
	// default layer, no multiple-scattering change and no fog on every pixel. Round 1
	// (2026-11-09): every beauty run on the render laptop's Intel iGPU (D3D11 SM5)
	// deadlocked in the sky light capture, and git bisect named the commit that
	// brought this lane's round-2 settings (a8c964fc); ef361bd6's code rendered.
	inline double CloudMarch(int March, int Field)
	{
		static const double Rows[MarchCount][MarchFieldCount] = {
			{6.0, 6.0, 50.0},   // discrete: 576 view, 60 shadow samples
			{2.0, 1.0, 80.0},   // constrained: 192 view, 10 shadow samples (ef361bd6)
		};
		return March >= 0 && March < MarchCount && Field >= 0 && Field < MarchFieldCount
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
	// The default layer (the -sky= plan's VISUAL ONLY 3 km slab, never a card's
	// stated layer) is thinned to the shape's depth: fair cumulus and a stratus
	// deck are 1-2 km deep; 0 keeps the layer as built.
	inline double CloudMaxThicknessM(int Cloud)
	{
		static const double Rows[CloudCount] = {2000.0, 0.0, 2000.0, 0.0};
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
		static const double Values[DistantLookCount] = {0.2, 0.9, 1.0, 0.3, 0.55, 0.15, 0.6, 8.0, 1.5};
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
	const TCHAR* const WorldTilesMaterialPath =
		TEXT("/Game/FlightSim/M_FlightSimTilesBeauty.M_FlightSimTilesBeauty");
	const TCHAR* const WorldCollectionPath = TEXT("/Game/FlightSim/MPC_FlightSimWorld.MPC_FlightSimWorld");
	// Visual round 5, lane L3: the distant sheet's material and the sky HDRI
	// probe's asset root (core/scene/sky_hdri.py HDRI_ASSET_DIR / HDRI_ASSET_PREFIX).
	const TCHAR* const WorldDistantMaterialPath =
		TEXT("/Game/FlightSim/M_FlightSimDistantClouds.M_FlightSimDistantClouds");
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
	constexpr double WorldCmPerMetre = 100.0;

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
                                  FFlightSimGoogleTiles& Tiles, FString& Error)
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

	ApplyAtmosphere(World, Scene, VisibilityKm);
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
	if (!ApplySkyHdri(Scene, SkyHdriName, Params, Error))
	{
		return false;
	}
	ApplyTiles(World, Tiles, CardWetness);
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
				// Round 12's #15 (a pale white fog under the storm deck): the fog's light
				// is the CLEAR sky's ambient above the deck and the sun's lobe; under a
				// drawn deck, the deck's diffuse transmission instead and no sun lobe
				// (rain_veil.STORM_FOG_AMBIENT_RGB).
				if (bDeckAbove)
				{
					const FLinearColor Ambient(0.20f, 0.21f, 0.23f);
					HazeRow->SetStringField(TEXT("sky_atmosphere_ambient_scale_before"),
						Fog->SkyAtmosphereAmbientContributionColorScale.ToString());
					Fog->SetSkyAtmosphereAmbientContributionColorScale(Ambient);
					Fog->SetDirectionalInscatteringColor(FLinearColor::Black);
					HazeRow->SetStringField(TEXT("sky_atmosphere_ambient_scale"), Ambient.ToString());
					HazeRow->SetBoolField(TEXT("directional_inscattering_off"), true);
				}
				HazeRows.Add(MakeShared<FJsonValueObject>(HazeRow));
			}
			Haze->SetArrayField(TEXT("height_fog"), HazeRows);
			Haze->SetNumberField(TEXT("rain_rate_mmh"), HazeRate);
			// The volumetric fog's sun light under the deck (rain_veil.STORM_SUN_FOG_SHARE).
			if (bDeckAbove && Scene.Sun != nullptr && Scene.Sun->GetLightComponent() != nullptr)
			{
				constexpr double StormSunFogShare = 0.15;
				ULightComponent* Beam = Scene.Sun->GetLightComponent();
				Haze->SetNumberField(TEXT("sun_volumetric_scattering_before"), Beam->VolumetricScatteringIntensity);
				Beam->SetVolumetricScatteringIntensity(
					static_cast<float>(Beam->VolumetricScatteringIntensity * StormSunFogShare));
				Haze->SetNumberField(TEXT("sun_volumetric_scattering"), Beam->VolumetricScatteringIntensity);
			}
		}
		Haze->SetStringField(TEXT("law"),
			TEXT("rain_veil.rain_haze_fog: in a storm preset with rain and no stated visibility, the fog's falloff "
			     "halves it once over the column under the deck and its density gives the camera's height the "
			     "rain's extinction (0.35 R^0.66 /km), never thinner than the scene's fog; -rain-veil=off keeps "
			     "the scene's fog. UNCALIBRATED"));
		Record->SetObjectField(TEXT("rain_haze"), Haze);
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
	// clouds-sky round 2: the fog-on-every-cloud-pixel cvar, as it was.
	if (!CloudFogAllPixelBefore.IsEmpty())
	{
		if (IConsoleVariable* Variable = IConsoleManager::Get().FindConsoleVariable(WorldCloudFogAllPixelCvar))
		{
			Variable->Set(*CloudFogAllPixelBefore, ECVF_SetByCode);
		}
		CloudFogAllPixelBefore.Empty();
	}
}

// Round 1 hang: the public face of CloudConstrainedGpu (the commandlet's
// constrained-GPU safeguards read the same class this lane's settings do).
bool FFlightSimWorldBeauty::ConstrainedGpu()
{
	return CloudConstrainedGpu();
}

void FFlightSimWorldBeauty::ApplyAtmosphere(UWorld* World, FFlightSimVisualScene& Scene, double VisibilityKm)
{
	// Function-local: unity builds merge anonymous namespaces (NEXT.md gotcha 3).
	using namespace FlightSimWorldPure;
	const double* Row = &AtmosphereValues[Preset * AtmosphereFieldCount];
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	double FogFactor = 1.0;
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
	// Not on a constrained GPU (CloudConstrainedGpu): ef361bd6 never set it.
	if (!CloudConstrainedGpu())
	{
		Atmosphere->SetMultiScatteringFactor(static_cast<float>(SkyMultiScattering(Preset)));
	}
	Out->SetNumberField(TEXT("multi_scattering_factor"), Atmosphere->MultiScatteringFactor);
	Out->SetStringField(TEXT("multi_scattering_basis"),
		TEXT("world_beauty.SKY_MULTI_SCATTERING (UNCALIBRATED): shot d's sky at 3.8 km rendered near-black navy; "
		     "more multiple scattering pales and lifts the clear sky towards the horizon"));
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

	// The height fog: the rest of the haze, and volumetric fog for the sun's
	// shafts through it.
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
	const int32 March = bIntegratedGpu ? MarchIntegrated : MarchDiscrete;
	const float ViewScale = static_cast<float>(CloudMarch(March, MarchViewScale));
	const float ShadowScale = static_cast<float>(CloudMarch(March, MarchShadowScale));
	const float TracingMaxKm = static_cast<float>(CloudMarch(March, MarchTracingMaxKm));
	{
		TSharedPtr<FJsonObject> MarchOut = MakeShared<FJsonObject>();
		MarchOut->SetStringField(TEXT("path"), ANSI_TO_TCHAR(MarchName(March)));
		MarchOut->SetStringField(TEXT("path_basis"),
			TEXT("CloudConstrainedGpu (GRHIDeviceIsIntegrated, or a feature level below SM6): the constrained row is ef361bd6's march"));
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
		MarchOut->SetStringField(TEXT("calibration"), TEXT("UNCALIBRATED: set by probe render on the render machine"));
		IConsoleVariable* FogAll = IConsoleManager::Get().FindConsoleVariable(WorldCloudFogAllPixelCvar);
		if (FogAll != nullptr)
		{
			if (CloudFogAllPixelBefore.IsEmpty())
			{
				CloudFogAllPixelBefore = FogAll->GetString();
			}
			// Fog on every cloud pixel costs a full-screen pass per capture:
			// discrete GPUs only (the round-1 hang on the Intel iGPU).
			if (!bIntegratedGpu)
			{
				FogAll->Set(1, ECVF_SetByCode);
			}
		}
		MarchOut->SetStringField(WorldCloudFogAllPixelCvar,
			FogAll != nullptr ? FogAll->GetString() : FString(TEXT("absent")));
		Out->SetObjectField(TEXT("march"), MarchOut);
	}
	TArray<TSharedPtr<FJsonValue>> Layers;
	for (UVolumetricCloudComponent* Cloud : Components)
	{
		FCloudLayerState State;
		State.Component = Cloud;
		State.BaseM = Cloud->LayerBottomAltitude * 1000.0;
		State.TopM = (Cloud->LayerBottomAltitude + Cloud->LayerHeight) * 1000.0;
		State.Shape = LayerCoverAndShape(CardCover, State.TopM - State.BaseM, Preset, bFair, CloudValues.GetData(),
		                                 &State.Cover);
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
		const float ShadowTracingKm =
			static_cast<float>(CloudShadowTracingKmFor(bIntegratedGpu, State.TopM - State.BaseM));
		const double* CloudRow = &CloudValues[State.Shape * CloudFieldCount];
		State.Material = UMaterialInstanceDynamic::Create(Base, Cloud);
		State.Material->SetScalarParameterValue(TEXT("Coverage"), static_cast<float>(State.Cover));
		State.Material->SetScalarParameterValue(TEXT("ExtinctionPerM"), static_cast<float>(CloudRow[CldExtinctionPerM]));
		State.Material->SetScalarParameterValue(TEXT("ExtinctionScale"), static_cast<float>(CloudExtinctionScale));
		State.Material->SetScalarParameterValue(TEXT("ShapeScaleKm"), static_cast<float>(CloudRow[CldShapeScaleKm]));
		State.Material->SetScalarParameterValue(TEXT("DetailScaleKm"), static_cast<float>(CloudRow[CldDetailScaleKm]));
		State.Material->SetScalarParameterValue(TEXT("DetailErosion"), static_cast<float>(CloudRow[CldDetailErosion]));
		State.Material->SetScalarParameterValue(TEXT("BottomSoftness"), static_cast<float>(CloudRow[CldBottomSoftness]));
		State.Material->SetScalarParameterValue(TEXT("TopRounding"), static_cast<float>(CloudRow[CldTopRounding]));
		State.Material->SetScalarParameterValue(TEXT("CoverageContrast"),
		                                        static_cast<float>(CloudRow[CldCoverageContrast]));
		State.Material->SetVectorParameterValue(TEXT("SeedOffsetKm"),
			FLinearColor(static_cast<float>(SeedKm[0]), static_cast<float>(SeedKm[1]),
			             static_cast<float>(SeedKm[2]), 0.0f));
		State.Material->SetVectorParameterValue(TEXT("WindOffsetM"), FLinearColor(0.0f, 0.0f, 0.0f, 0.0f));
		Cloud->SetMaterial(State.Material);
		Cloud->SetbUsePerSampleAtmosphericLightTransmittance(true);
		Cloud->SetSkyLightCloudBottomOcclusion(static_cast<float>(AtmRow[AtmCloudBottomOcclusion]));
		Cloud->SetViewSampleCountScale(ViewScale);
		Cloud->SetShadowViewSampleCountScale(ShadowScale);
		Cloud->SetShadowTracingDistance(ShadowTracingKm);
		Cloud->SetTracingMaxDistance(TracingMaxKm);
		Cloud->SetStopTracingTransmittanceThreshold(WorldCloudStopTransmittance);
		Cloud->SetGroundAlbedo(WorldAlbedo(Surface, GroundWetness, StormNeutralAlbedo()));
		CloudLayers.Add(State);

		TSharedPtr<FJsonObject> Layer = MakeShared<FJsonObject>();
		Layer->SetStringField(TEXT("component"), Cloud->GetName());
		Layer->SetStringField(TEXT("shape"), ANSI_TO_TCHAR(CloudName(State.Shape)));
		Layer->SetNumberField(TEXT("cover"), State.Cover);
		Layer->SetStringField(TEXT("cover_basis"), bFair ? TEXT("the fair-weather layer (stated)")
			: (CardCover >= 0.0 ? TEXT("the card's look.clouds[0].cover")
			   : (Preset == PresetRain ? TEXT("RainDefaultCover: a rain world, the card states none (broken, round 3)")
			                           : TEXT("the shape's default (the card states none)"))));
		Layer->SetNumberField(TEXT("base_m"), State.BaseM);
		Layer->SetNumberField(TEXT("top_m"), State.TopM);
		Layer->SetNumberField(TEXT("built_top_m"), BuiltTopM);
		Layer->SetStringField(TEXT("top_basis"), State.TopM != BuiltTopM
			? TEXT("the default layer thinned to the shape's depth (world_beauty.CLOUD_MAX_THICKNESS_M)")
			: (bStatedLayer ? TEXT("the stated layer, as built") : TEXT("as built (within the shape's depth)")));
		Layer->SetNumberField(TEXT("shadow_tracing_distance_km"), ShadowTracingKm);
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
		TEXT("cloud_layers.hlsl (round 7: a Nubis-style 2D weather field, flat bases, domed tops, in-cloud erosion) cuts the shape noise "
		     "at its (1 - cover) quantile: FBM_MEAN 0.535 + FBM_SIGMA 0.073 x probit(1 - cover) (the noise's own "
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
	Out->SetNumberField(TEXT("clearance_m"), AircraftLayerClearanceM);
	Out->SetBoolField(TEXT("rain_deck_goes_above"), bRainDeck);
	Out->SetStringField(TEXT("law"),
		TEXT("the law of world_beauty.aircraft_clear_layer, a deck whose slab widened by clearance_m holds the aircraft "
		     "moves clear of it with its thickness kept (a rain or storm deck above, others to the nearer side); "
		     "UNCALIBRATED"));
	TArray<TSharedPtr<FJsonValue>> Rows;
	for (FCloudLayerState& State : CloudLayers)
	{
		const FLayerClear Clear =
			AircraftClearLayer(State.BaseM, State.TopM, AircraftUpM, AircraftLayerClearanceM, bRainDeck);
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
		Cover = Layer.Cover;
		Shape = Layer.Shape;
		CoverBasis = TEXT("the first redrawn layer (its slab after the aircraft clearance, its cover and shape row)");
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
	const int32 March = bConstrained ? MarchIntegrated : MarchDiscrete;
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
	Trace->SetStringField(TEXT("basis"),
		TEXT("the distant tracing (world_beauty.distant_tracing_max_km), constrained and the sheet drawn -> min(row, DISTANT_NEAR_FIELD_KM). "
		     "VolumetricCloud.usf: StepCount = SampleCountMax x saturate(path x InvDistanceToSampleCountMax) "
		     "(r.VolumetricCloud.DistanceToSampleMaxCount, 15 km), non-decreasing in the path: a shorter trace never "
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

void FFlightSimWorldBeauty::ApplyTiles(UWorld* World, FFlightSimGoogleTiles& Tiles, double CardWetness)
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
	const bool bTilesMaterial = MaterialRoute == TEXT("UFunction SetMaterial") || MaterialRoute == TEXT("UPROPERTY Material");
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
		                                 CloudValues[Layer.Shape * CloudFieldCount + CldExtinctionPerM],
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
