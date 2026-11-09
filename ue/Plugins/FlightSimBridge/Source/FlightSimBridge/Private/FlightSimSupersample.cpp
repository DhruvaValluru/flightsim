#include "FlightSimSupersample.h"

#include "Dom/JsonObject.h"
#include "Misc/Parse.h"
#include "RHIGlobals.h"

#include <cmath>

// The pure part: no engine type, compiled and run by tests/test_supersample.py
// with the machine's C++ compiler against the Python mirror
// (core/capture/supersample.py), number for number. Keep it free of
// #include, FString and TEXT( between the markers.
// FLIGHTSIM-SUPERSAMPLE-PURE-BEGIN
namespace FlightSimSupersamplePure
{
	// The factors -supersample= accepts.
	constexpr int MinFactor = 1;
	constexpr int MaxFactor = 4;
	// The texture side the estimate assumes when the RHI reports none
	// (the D3D12 / Vulkan / Metal 2D limit).
	constexpr int FallbackMaxTextureSide = 16384;

	// VRAM model, UNCALIBRATED (set by probe render on the render machine:
	// stat GPU / "r.DumpRenderTargetPoolMemory" at -supersample=1 and 2 on
	// shot (a), the slope is the per-pixel cost). Bytes per INTERNAL pixel
	// of every render-resolution target in a deferred Lumen beauty frame:
	// scene colour RGBA16f 8, depth-stencil 8, GBuffer A-E + velocity 24,
	// custom depth 8, HZB 2, Lumen screen probes / reflections + history 24,
	// volumetric render target (mode 3, full res) 16, post chain (bloom,
	// DOF, local exposure) 18, the beauty RGBA8 target 4.
	constexpr double RenderBytesPerPixel = 112.0;
	// TSR history (colour RGBA16f x2 double-buffered + metadata) per HISTORY
	// pixel; the history is the internal size times
	// (r.TSR.History.ScreenPercentage / 100) per axis.
	constexpr double TsrHistoryBytesPerPixel = 24.0;
	// What the supersample-scaled targets may take, UNCALIBRATED: the render
	// box's RTX 5080 Laptop has 16 GiB, and the Google tiles, Nanite,
	// virtual shadow maps and Lumen's scene cache keep their own share
	// regardless of the output size. -supersample-vram-budget-mib= overrides.
	constexpr double VramBudgetMiBDefault = 7168.0;

	// Configure's verdicts.
	constexpr int CheckOk = 0;
	constexpr int CheckFactor = 1;
	constexpr int CheckSize = 2;
	constexpr int CheckVram = 3;

	inline double SrgbToLinear(double Encoded)
	{
		return Encoded <= 0.04045 ? Encoded / 12.92 : std::pow((Encoded + 0.055) / 1.055, 2.4);
	}

	// Decode[b] is byte b in linear light; Threshold[b] is the linear value
	// half-way (in the ENCODED domain) between bytes b and b + 1, so
	// encoding by threshold count is rounding to the nearest byte.
	inline void BuildTables(double Decode[256], double Threshold[255])
	{
		for (int B = 0; B < 256; ++B)
		{
			Decode[B] = SrgbToLinear(B / 255.0);
		}
		for (int B = 0; B < 255; ++B)
		{
			Threshold[B] = SrgbToLinear((B + 0.5) / 255.0);
		}
	}

	// The byte whose encoded value is nearest Linear: the number of
	// thresholds at or below it (binary search; a tie rounds up).
	inline unsigned char EncodeLinear(double Linear, const double Threshold[255])
	{
		int Low = 0;
		int High = 255;
		while (Low < High)
		{
			const int Mid = (Low + High) / 2;
			if (Linear < Threshold[Mid])
			{
				High = Mid;
			}
			else
			{
				Low = Mid + 1;
			}
		}
		return static_cast<unsigned char>(Low);
	}

	// In: (OutWidth*Factor) x (OutHeight*Factor) texels of Channels bytes,
	// row-major. Out: OutWidth x OutHeight texels. Each output channel is
	// the mean, in linear light, of the Factor x Factor block whose
	// internal pixel centres average to the output pixel's centre
	// ((x + 0.5) * Factor in internal pixels is the block's middle), summed
	// row by row, left to right, then divided by Factor^2 and encoded.
	// Every channel is treated alike (the commandlet sets alpha to 255
	// afterwards), so the byte order (BGRA or RGBA) does not matter.
	// Returns false on a bad argument.
	inline bool BoxDownsample(const unsigned char* In, int OutWidth, int OutHeight, int Factor,
	                          int Channels, unsigned char* Out)
	{
		if (In == nullptr || Out == nullptr || OutWidth < 1 || OutHeight < 1 || Factor < MinFactor
		    || Factor > MaxFactor || Channels < 1)
		{
			return false;
		}
		double Decode[256];
		double Threshold[255];
		BuildTables(Decode, Threshold);
		const long long InWidth = static_cast<long long>(OutWidth) * Factor;
		const double Count = static_cast<double>(Factor) * Factor;
		for (int Y = 0; Y < OutHeight; ++Y)
		{
			for (int X = 0; X < OutWidth; ++X)
			{
				for (int C = 0; C < Channels; ++C)
				{
					double Sum = 0.0;
					for (int J = 0; J < Factor; ++J)
					{
						const long long Row = static_cast<long long>(Y) * Factor + J;
						for (int I = 0; I < Factor; ++I)
						{
							const long long Column = static_cast<long long>(X) * Factor + I;
							Sum += Decode[In[(Row * InWidth + Column) * Channels + C]];
						}
					}
					Out[(static_cast<long long>(Y) * OutWidth + X) * Channels + C] =
						EncodeLinear(Sum / Count, Threshold);
				}
			}
		}
		return true;
	}

	// The VRAM the supersample-scaled targets take, in MiB.
	inline double EstimateVramMiB(int InternalWidth, int InternalHeight,
	                              double TsrHistoryScreenPercentage)
	{
		const double Pixels = static_cast<double>(InternalWidth) * InternalHeight;
		const double History = TsrHistoryScreenPercentage > 0.0 ? TsrHistoryScreenPercentage / 100.0 : 1.0;
		const double Bytes = Pixels * (RenderBytesPerPixel + TsrHistoryBytesPerPixel * History * History);
		return Bytes / (1024.0 * 1024.0);
	}

	inline int Check(int Factor, int OutWidth, int OutHeight, double TsrHistoryScreenPercentage,
	                 int MaxTextureSide, double BudgetMiB)
	{
		if (Factor < MinFactor || Factor > MaxFactor)
		{
			return CheckFactor;
		}
		if (static_cast<long long>(OutWidth) * Factor > MaxTextureSide
		    || static_cast<long long>(OutHeight) * Factor > MaxTextureSide)
		{
			return CheckSize;
		}
		if (EstimateVramMiB(OutWidth * Factor, OutHeight * Factor, TsrHistoryScreenPercentage) > BudgetMiB)
		{
			return CheckVram;
		}
		return CheckOk;
	}
}
// FLIGHTSIM-SUPERSAMPLE-PURE-END

namespace
{
	// What Configure decided, for Record (one render per process).
	struct FFlightSimSupersampleRunState
	{
		bool bStated = false;
		int32 Factor = 1;
		int32 OutputWidth = 0;
		int32 OutputHeight = 0;
		int32 MaxTextureSide = 0;
		FString MaxTextureSideBasis;
		double TsrHistoryScreenPercentage = 0.0;
		double VramEstimateMiB = 0.0;
		double VramBudgetMiB = 0.0;
		FString BudgetBasis;
	};

	FFlightSimSupersampleRunState& SupersampleRunState()
	{
		static FFlightSimSupersampleRunState State;
		return State;
	}
}

bool FFlightSimSupersample::Configure(const TCHAR* Params, const FString& Quality, int32 OutputWidth,
                                      int32 OutputHeight, float TsrHistoryScreenPercentage,
                                      int32& OutFactor, FString& OutError)
{
	namespace SSP = FlightSimSupersamplePure;
	FFlightSimSupersampleRunState& State = SupersampleRunState();
	State = FFlightSimSupersampleRunState();
	OutFactor = 1;
	int32 Factor = 1;
	if (!FParse::Value(Params, TEXT("supersample="), Factor))
	{
		return true;
	}
	if (Quality != TEXT("beauty"))
	{
		OutError = FString::Printf(TEXT("render.supersample: -supersample needs -quality=beauty, ")
		                           TEXT("not %s (measure is never supersampled; the path tracer ")
		                           TEXT("filters by r.PathTracing.FilterWidth)"), *Quality);
		return false;
	}
	double BudgetMiB = SSP::VramBudgetMiBDefault;
	State.BudgetBasis = TEXT("VramBudgetMiBDefault, UNCALIBRATED");
	int32 BudgetFlag = 0;
	if (FParse::Value(Params, TEXT("supersample-vram-budget-mib="), BudgetFlag))
	{
		if (BudgetFlag < 1)
		{
			OutError = FString::Printf(TEXT("render.supersample: -supersample-vram-budget-mib=%d ")
			                           TEXT("is not a positive whole number of MiB"), BudgetFlag);
			return false;
		}
		BudgetMiB = BudgetFlag;
		State.BudgetBasis = TEXT("-supersample-vram-budget-mib, stated");
	}
	// The RHI's 2D limit; its pre-init default (2048) or nothing means the
	// RHI has not said, and the common 16384 stands.
	int32 MaxSide = GMaxTextureDimensions;
	State.MaxTextureSideBasis = TEXT("GMaxTextureDimensions");
	if (MaxSide <= 2048)
	{
		MaxSide = SSP::FallbackMaxTextureSide;
		State.MaxTextureSideBasis = TEXT("FallbackMaxTextureSide (the RHI reported none)");
	}
	const int Verdict = SSP::Check(Factor, OutputWidth, OutputHeight, TsrHistoryScreenPercentage,
	                          MaxSide, BudgetMiB);
	if (Verdict == SSP::CheckFactor)
	{
		OutError = FString::Printf(TEXT("render.supersample: -supersample=%d is not a whole ")
		                           TEXT("number from %d to %d"), Factor, SSP::MinFactor, SSP::MaxFactor);
		return false;
	}
	if (Verdict == SSP::CheckSize)
	{
		OutError = FString::Printf(TEXT("render.supersample: -supersample=%d at %dx%d needs a ")
		                           TEXT("%lldx%lld beauty target, over the %d px texture limit"),
		                           Factor, OutputWidth, OutputHeight,
		                           static_cast<long long>(OutputWidth) * Factor,
		                           static_cast<long long>(OutputHeight) * Factor, MaxSide);
		return false;
	}
	const double EstimateMiB = SSP::EstimateVramMiB(OutputWidth * Factor, OutputHeight * Factor,
	                                           TsrHistoryScreenPercentage);
	if (Verdict == SSP::CheckVram)
	{
		OutError = FString::Printf(TEXT("render.supersample: -supersample=%d at %dx%d renders ")
		                           TEXT("%dx%d internally, an estimated %.0f MiB of render targets, ")
		                           TEXT("over the %.0f MiB budget"),
		                           Factor, OutputWidth, OutputHeight, OutputWidth * Factor,
		                           OutputHeight * Factor, EstimateMiB, BudgetMiB);
		return false;
	}
	State.bStated = true;
	State.Factor = Factor;
	State.OutputWidth = OutputWidth;
	State.OutputHeight = OutputHeight;
	State.MaxTextureSide = MaxSide;
	State.TsrHistoryScreenPercentage = TsrHistoryScreenPercentage;
	State.VramEstimateMiB = EstimateMiB;
	State.VramBudgetMiB = BudgetMiB;
	OutFactor = Factor;
	return true;
}

bool FFlightSimSupersample::Downsample(TArray<FColor>& Pixels, int32 OutputWidth, int32 OutputHeight,
                                       int32 Factor, FString& OutError)
{
	if (Factor <= 1)
	{
		return true;
	}
	const int64 Expected = static_cast<int64>(OutputWidth) * Factor * OutputHeight * Factor;
	if (Pixels.Num() != Expected)
	{
		OutError = FString::Printf(TEXT("render.supersample: read back %d texels from the beauty ")
		                           TEXT("target, expected %lld (%dx%d at -supersample=%d)"),
		                           Pixels.Num(), static_cast<long long>(Expected), OutputWidth,
		                           OutputHeight, Factor);
		return false;
	}
	static_assert(sizeof(FColor) == 4, "FColor is four bytes");
	TArray<FColor> Reduced;
	Reduced.SetNumUninitialized(OutputWidth * OutputHeight);
	if (!FlightSimSupersamplePure::BoxDownsample(reinterpret_cast<const unsigned char*>(Pixels.GetData()),
	                                             OutputWidth, OutputHeight, Factor, 4,
	                                             reinterpret_cast<unsigned char*>(Reduced.GetData())))
	{
		OutError = FString::Printf(TEXT("render.supersample: the box filter refused %dx%d at ")
		                           TEXT("-supersample=%d"), OutputWidth, OutputHeight, Factor);
		return false;
	}
	Pixels = MoveTemp(Reduced);
	return true;
}

void FFlightSimSupersample::Record(const TSharedPtr<FJsonObject>& Root)
{
	const FFlightSimSupersampleRunState& State = SupersampleRunState();
	if (!State.bStated || !Root.IsValid())
	{
		return;
	}
	const TSharedPtr<FJsonObject>* Existing = nullptr;
	TSharedPtr<FJsonObject> Samples = Root->TryGetObjectField(TEXT("beauty_samples"), Existing)
		&& Existing != nullptr && Existing->IsValid() ? *Existing : MakeShared<FJsonObject>();
	Samples->SetNumberField(TEXT("spatial"), State.Factor * State.Factor);
	Samples->SetNumberField(TEXT("supersample"), State.Factor);
	Samples->SetStringField(TEXT("supersample_filter"), State.Factor > 1 ? TEXT("box") : TEXT("none"));
	Samples->SetStringField(TEXT("supersample_filter_space"),
	                        TEXT("linear light: the tonemapped sRGB 8-bit beauty decoded, averaged, re-encoded"));
	Samples->SetBoolField(TEXT("supersample_pixel_moving"), false);
	Samples->SetStringField(TEXT("supersample_alignment"),
	                        TEXT("exact integer box: output pixel x is the mean of internal pixels ")
	                        TEXT("x*N .. x*N+N-1, whose centres average to the output centre"));
	Samples->SetNumberField(TEXT("internal_width_px"), State.OutputWidth * State.Factor);
	Samples->SetNumberField(TEXT("internal_height_px"), State.OutputHeight * State.Factor);
	Samples->SetNumberField(TEXT("output_width_px"), State.OutputWidth);
	Samples->SetNumberField(TEXT("output_height_px"), State.OutputHeight);
	Samples->SetNumberField(TEXT("supersample_tsr_history_screen_percentage"), State.TsrHistoryScreenPercentage);
	Samples->SetNumberField(TEXT("supersample_vram_estimate_mib"), State.VramEstimateMiB);
	Samples->SetNumberField(TEXT("supersample_vram_budget_mib"), State.VramBudgetMiB);
	Samples->SetStringField(TEXT("supersample_vram_budget_basis"), State.BudgetBasis);
	Samples->SetNumberField(TEXT("supersample_max_texture_side"), State.MaxTextureSide);
	Samples->SetStringField(TEXT("supersample_max_texture_side_basis"), State.MaxTextureSideBasis);
	Root->SetObjectField(TEXT("beauty_samples"), Samples);
}
