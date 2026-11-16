// High-sky effects lane (2026-11-15): the beauty-only rainbow and in-cloud
// lightning flash. The pure laws below are core/sky/sky_fx.py's, compiled with
// g++ and compared by tests/test_sky_fx.py (the block between the markers uses
// only <cmath> and <cstdint>). BEAUTY ONLY: the rainbow sphere is built by
// FFlightSimVisualScene::ApplyBeautySkyFx (FlightSimSkyFx.cpp, called only from
// ApplyBeautyWeatherLook); the cloud flash only sets the storm cell's existing
// Flash / FlashRelCm parameters after FFlightSimWeather::ApplyBeautyStormVantage
// armed it (FlightSimWeather.cpp). No label, depth, mask or keypoint pass, no
// measure output and no physics reads either.
//
// -look-rainbow=on|off (on): off builds no sphere.
// -look-cloud-flash=off|schedule|on (schedule): off is the old storm; schedule
// lights an intracloud flash in the card rate's share of frames; on, every
// beauty frame (the A/B).
#pragma once

#include <cmath>
#include <cstdint>

// -- sky fx pure: begin --
namespace FlightSimSkyFxPure
{
	// Rain's visible extinction 0.25 R^0.63 km^-1 over a 2 km path (sky_fx.py).
	constexpr double RainExtinctionA = 0.25;
	constexpr double RainExtinctionB = 0.63;
	constexpr double RainbowPathKm = 2.0;
	constexpr double RainbowRadiusKm = 8.0;
	constexpr double RainbowTopFadeM = 300.0;
	constexpr double RainbowDefaultRainTopM = 1200.0;
	// The look (sky_fx.RAINBOW_LOOK; UNCALIBRATED, set by look-dev probe).
	constexpr double RainbowPrimaryPeak = 0.05;
	constexpr double RainbowInnerGlow = 0.25;
	constexpr double RainbowInnerFoldDeg = 6.0;

	// A return stroke's optical energy 8.7e5 J (Krider, Dawson & Uman 1968) at
	// the card's 80 lm/W, spread over max(shutter, 1 ms).
	constexpr double CloudFlashEnergyJ = 8.7e5;
	constexpr double CloudFlashEfficacyLmPerW = 80.0;
	constexpr double CloudFlashMinWindowS = 1.0e-3;
	// An IC flash's visible duration (0.2-0.5 s): the schedule's bin.
	constexpr double CloudFlashVisibleS = 0.3;
	constexpr double CloudFlashDefaultRatePerMin = 6.0;
	constexpr double CloudFlashDefaultIcCg = 3.0;
	constexpr double CloudFlashRadialShare = 0.6;
	constexpr double CloudFlashHeightShare = 0.3;
	constexpr int CloudFlashOff = 0;
	constexpr int CloudFlashSchedule = 1;
	constexpr int CloudFlashOn = 2;

	inline double RainOpticalDepth(double RateMmh)
	{
		return RateMmh <= 0.0 ? 0.0 : RainExtinctionA * std::pow(RateMmh, RainExtinctionB) * RainbowPathKm;
	}

	// 0 with the switch off, no rain or the sun at or below the horizon;
	// else 1 - exp(-tau).
	inline double RainbowStrength(bool bOn, double RateMmh, double SunElevationDeg)
	{
		if (!bOn || RateMmh <= 0.0 || SunElevationDeg <= 0.0)
		{
			return 0.0;
		}
		return 1.0 - std::exp(-RainOpticalDepth(RateMmh));
	}

	// Reviewer fix: the bow is lit by direct sun only; the clear share of the
	// sun's line of sight is prod(1 - N_i) over the card's layers (relative
	// sunshine ~ 1 - N, Kasten & Czeplak 1980; sky_fx.rainbow_sun_transmittance).
	inline double RainbowSunTransmittance(const double* Covers, int Count)
	{
		double T = 1.0;
		for (int I = 0; I < Count; ++I)
		{
			const double C = Covers[I] < 0.0 ? 0.0 : Covers[I] > 1.0 ? 1.0 : Covers[I];
			T *= 1.0 - C;
		}
		return T;
	}

	inline double CloudFlashCd(double ShutterS)
	{
		const double Window = ShutterS > CloudFlashMinWindowS ? ShutterS : CloudFlashMinWindowS;
		return CloudFlashEnergyJ * CloudFlashEfficacyLmPerW / (4.0 * 3.14159265358979323846 * Window);
	}

	inline uint64_t SplitMix64(uint64_t X)
	{
		X += 0x9E3779B97F4A7C15ull;
		X = (X ^ (X >> 30)) * 0xBF58476D1CE4E5B9ull;
		X = (X ^ (X >> 27)) * 0x94D049BB133111EBull;
		return X ^ (X >> 31);
	}

	inline double Unit(uint64_t Seed, uint64_t Index)
	{
		return static_cast<double>(SplitMix64(Seed * 0x100000001B3ull + Index) >> 11) * (1.0 / 9007199254740992.0);
	}

	inline double CloudFlashShare(double RatePerMin, double IcCg)
	{
		const double Rate = RatePerMin > 0.0 ? RatePerMin : CloudFlashDefaultRatePerMin;
		const double Ratio = IcCg >= 0.0 ? IcCg : CloudFlashDefaultIcCg;
		const double Share = Rate / 60.0 * (Ratio / (1.0 + Ratio)) * CloudFlashVisibleS;
		return Share < 1.0 ? Share : 1.0;
	}

	inline bool CloudFlashLit(int Mode, uint64_t Seed, double TimeS, double RatePerMin, double IcCg)
	{
		if (Mode == CloudFlashOn)
		{
			return true;
		}
		if (Mode != CloudFlashSchedule)
		{
			return false;
		}
		const uint64_t Bin = static_cast<uint64_t>(std::floor((TimeS > 0.0 ? TimeS : 0.0) / CloudFlashVisibleS));
		return Unit(Seed, Bin) < CloudFlashShare(RatePerMin, IcCg);
	}

	// The flash relative to the drawn cell centre (east, north, up), m: on the
	// camera's side of the tower, never past the camera.
	inline void CloudFlashRelM(double CameraEastM, double CameraNorthM, double TowerRadiusM, double BaseM,
	                           double TopM, double& OutEastM, double& OutNorthM, double& OutUpM)
	{
		const double D = std::sqrt(CameraEastM * CameraEastM + CameraNorthM * CameraNorthM);
		OutUpM = BaseM + CloudFlashHeightShare * (TopM > BaseM ? TopM - BaseM : 0.0);
		if (D <= 0.0)
		{
			OutEastM = 0.0;
			OutNorthM = 0.0;
			return;
		}
		const double A = CloudFlashRadialShare * TowerRadiusM;
		const double B = 0.9 * D;
		const double Reach = A < B ? A : B;
		OutEastM = CameraEastM / D * Reach;
		OutNorthM = CameraNorthM / D * Reach;
	}
}
// -- sky fx pure: end --

class FString;

namespace FlightSimSkyFx
{
	// The switches: the command line, then FLIGHTSIM_RENDER_SWITCHES. A word
	// the switch does not take returns false with Error naming it.
	bool ParseRainbow(bool& bOutOn, FString& Error);
	// -look-rainbow-shade=cover|off (cover): the direct-sun cloud gate.
	bool ParseRainbowShade(bool& bOutCover, FString& Error);
	bool ParseCloudFlash(int& OutMode, FString& Error);
}
