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
#include "RHIGlobals.h"
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
			// rain
			{1.0, 0.65, 0.3, 0.8, 1.0, 4000.0, 0.3, 1.0, 0.85, 1.5, 0.6, 0.12, 0.0},
			// storm
			{1.8, 0.65, 0.3, 0.8, 1.0, 4000.0, 0.3, 1.0, 0.9, 1.5, 0.85, 0.12, 3.0},
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
			{0.045, 6.0, 0.6, 0.2, 0.1, 0.4, 1.2, 0.98},      // nimbostratus
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
	constexpr double FairCover = 0.35;
	constexpr double FairBaseM = 1500.0;
	constexpr double FairTopM = 2700.0;
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
	// both rows stay under the caps. An integrated GPU (GRHIDeviceIsIntegrated: the
	// render machine's Intel) keeps about the round-1 cost with the new noise.
	inline double CloudMarch(int March, int Field)
	{
		static const double Rows[MarchCount][MarchFieldCount] = {
			{6.0, 6.0, 50.0},   // discrete: 576 view, 60 shadow samples
			{4.0, 4.0, 40.0},   // integrated: 384 view, 40 shadow samples
		};
		return March >= 0 && March < MarchCount && Field >= 0 && Field < MarchFieldCount
			? Rows[March][Field] : 0.0;
	}
	// The shadow march spans the layer it lights (a cell's self-shadow and its
	// neighbour's), not 15 km: kilometres per kilometre of thickness, clamped.
	constexpr double CloudShadowKmPerKm = 1.0;
	constexpr double CloudShadowMinKm = 1.0;
	constexpr double CloudShadowMaxKm = 4.0;
	inline double CloudShadowTracingKm(double ThicknessM)
	{
		const double Km = (ThicknessM > 0.0 ? ThicknessM : 0.0) / 1000.0 * CloudShadowKmPerKm;
		return Km < CloudShadowMinKm ? CloudShadowMinKm : (Km > CloudShadowMaxKm ? CloudShadowMaxKm : Km);
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
	// Physical constants (not look values).
	constexpr double Koschmieder = 3.912;
	constexpr double RayleighGreenPerKm = 0.013558;
	constexpr double MieSingleScatterAlbedo = 0.9;
	constexpr double MinVisibilityKm = 0.05;

	inline int SelectPreset(bool bStorm, double RainRateMmh, bool bPrecipitationRain, double CloudCover,
	                        double VisibilityKm)
	{
		if (bStorm)
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
	inline double FogDirectionalExponentForG(double G)
	{
		const double Gc = G < 0.0 ? 0.0 : (G > 0.99 ? 0.99 : G);
		const double N = (2.0 * Gc - 1.0) / (1.0 - Gc);
		return N < FogExponentMin ? FogExponentMin : (N > FogExponentMax ? FogExponentMax : N);
	}

	// world_beauty.layer_cover_and_shape: the fair layer's cover, else the
	// card's (CardCover >= 0), else the default cover of the shape a cover-0
	// layer of this thickness would be; the shape then follows the cover.
	// CloudTable: the cloud rows in force (CloudCount x CloudFieldCount, the
	// overrides applied), or nullptr for the defaults.
	inline int LayerCoverAndShape(double CardCover, double ThicknessM, int Preset, bool bFair,
	                              const double* CloudTable, double* OutCover)
	{
		const bool bStated = CardCover >= 0.0;
		const int Guess = SelectCloud(bStated ? CardCover : 0.0, ThicknessM, Preset);
		const double GuessDefault = CloudTable != nullptr ? CloudTable[Guess * CloudFieldCount + CldDefaultCover]
		                                                  : CloudDefault(Guess, CldDefaultCover);
		const double Cover = bFair ? FairCover : (bStated ? CardCover : GuessDefault);
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
}
// FLIGHTSIM-WORLD-PURE-END

namespace
{
	const TCHAR* const WorldCloudMaterialPath =
		TEXT("/Game/FlightSim/M_FlightSimCloudLayers.M_FlightSimCloudLayers");
	const TCHAR* const WorldTilesMaterialPath =
		TEXT("/Game/FlightSim/M_FlightSimTilesBeauty.M_FlightSimTilesBeauty");
	const TCHAR* const WorldCollectionPath = TEXT("/Game/FlightSim/MPC_FlightSimWorld.MPC_FlightSimWorld");
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
	FColor WorldAlbedo(const FString& Surface, double Wetness)
	{
		// Function-local: unity builds merge anonymous namespaces (NEXT.md gotcha 3).
		using namespace FlightSimWorldPure;
		int Rgb[3] = {0, 0, 0};
		GroundAlbedoSrgb(GroundSurfaceIndex(TCHAR_TO_ANSI(*Surface)), Wetness, Rgb);
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
	Preset = SelectPreset(bStorm, RainRate, bRainWord, bCardLayer ? CardCover : 0.0, VisibilityKm);
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
	const FColor Albedo = WorldAlbedo(Surface, GroundWetness);
	Atmosphere->SetGroundAlbedo(Albedo);
	// clouds-sky round 2: the sky's multiple scattering (paler towards the
	// horizon from altitude; FlightSimWorldPure::SkyMultiScattering).
	Out->SetNumberField(TEXT("multi_scattering_factor_before"), Atmosphere->MultiScatteringFactor);
	Atmosphere->SetMultiScatteringFactor(static_cast<float>(SkyMultiScattering(Preset)));
	Out->SetNumberField(TEXT("multi_scattering_factor"), SkyMultiScattering(Preset));
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
	const bool bIntegratedGpu = GRHIDeviceIsIntegrated;
	const int32 March = bIntegratedGpu ? MarchIntegrated : MarchDiscrete;
	const float ViewScale = static_cast<float>(CloudMarch(March, MarchViewScale));
	const float ShadowScale = static_cast<float>(CloudMarch(March, MarchShadowScale));
	const float TracingMaxKm = static_cast<float>(CloudMarch(March, MarchTracingMaxKm));
	{
		TSharedPtr<FJsonObject> MarchOut = MakeShared<FJsonObject>();
		MarchOut->SetStringField(TEXT("path"), ANSI_TO_TCHAR(MarchName(March)));
		MarchOut->SetStringField(TEXT("path_basis"),
			TEXT("GRHIDeviceIsIntegrated (the RHI's adapter): integrated keeps about the round-1 cost"));
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
			     "captures; the shadow march spans the layer (CloudShadowTracingKm)"));
		MarchOut->SetStringField(TEXT("calibration"), TEXT("UNCALIBRATED: set by probe render on the render machine"));
		IConsoleVariable* FogAll = IConsoleManager::Get().FindConsoleVariable(WorldCloudFogAllPixelCvar);
		if (FogAll != nullptr)
		{
			if (CloudFogAllPixelBefore.IsEmpty())
			{
				CloudFogAllPixelBefore = FogAll->GetString();
			}
			FogAll->Set(1, ECVF_SetByCode);
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
		State.TopM = CloudCappedTopM(State.Shape, State.BaseM, State.TopM, bStatedLayer);
		if (State.TopM != BuiltTopM)
		{
			Cloud->SetLayerHeight(static_cast<float>((State.TopM - State.BaseM) / 1000.0));
		}
		const float ShadowTracingKm = static_cast<float>(CloudShadowTracingKm(State.TopM - State.BaseM));
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
		Cloud->SetGroundAlbedo(WorldAlbedo(Surface, GroundWetness));
		CloudLayers.Add(State);

		TSharedPtr<FJsonObject> Layer = MakeShared<FJsonObject>();
		Layer->SetStringField(TEXT("component"), Cloud->GetName());
		Layer->SetStringField(TEXT("shape"), ANSI_TO_TCHAR(CloudName(State.Shape)));
		Layer->SetNumberField(TEXT("cover"), State.Cover);
		Layer->SetStringField(TEXT("cover_basis"), bFair ? TEXT("the fair-weather layer (stated)")
			: (CardCover >= 0.0 ? TEXT("the card's look.clouds[0].cover") : TEXT("the shape's default (the card states none)")));
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
	Out->SetNumberField(TEXT("unmodelled_clouds"), UnmodelledClouds);
	Out->SetStringField(TEXT("coverage_law"),
		TEXT("cloud_layers.hlsl (round 2: Perlin-Worley shape, domed tops, in-cloud erosion) cuts the shape noise "
		     "at its (1 - cover) quantile: FBM_MEAN 0.779 + FBM_SIGMA 0.05 x probit(1 - cover) (the noise's own "
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
	if (DriftMps > 0.0)
	{
		const FVector Offset = FFlightSimVisualScene::CloudDriftOffsetMetres(DriftMps, DriftFromDeg, TimeSeconds);
		for (FCloudLayerState& Layer : CloudLayers)
		{
			if (Layer.Material != nullptr)
			{
				Layer.Material->SetVectorParameterValue(TEXT("WindOffsetM"),
					FLinearColor(static_cast<float>(Offset.X), static_cast<float>(Offset.Y), 0.0f, 0.0f));
			}
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
