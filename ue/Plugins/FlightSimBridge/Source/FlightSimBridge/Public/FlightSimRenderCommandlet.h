// Render frames of a scenario, headlessly, and write them to disk.
//
// The two clauses of Gate 5 that FlightSimScenarioCommandlet cannot answer are
// about what a viewer sees: "control surfaces visibly articulate" and
// "commanded roll is visible on screen". Neither is a claim about the FDM. Both
// need pixels, and pixels need a real RHI -- which is why this is a separate
// commandlet from the telemetry one rather than a flag on it. UCommandlet::
// IsClient is read off the class default object before the engine initialises,
// so a commandlet either brings up the renderer or it does not.
//
// Run it with -RenderOffScreen (and NOT -nullrhi): scripts/render_ue_scenario.sh.
//
// S4 (the sensing engine side; UNCOMPILED here, pinned by
// tests/test_ue_passes_source.py, verified by the first Windows build):
//
//  * -passes=normal / -passes=albedo also write the LINEAR passes through
//    two more AA-free captures under ConfigureLabelCapture: SCS_Normal and
//    SCS_BaseColor into RTF_RGBA16f, written by WriteLinearF32 as
//    frame_NNNN_normal.f32 / frame_NNNN_basecolor.f32 (the byte layout is
//    stated once, beside WriteLinearF32 below). The I6 16-bit PNGs stay.
//    -normal-source=material takes the normal from M_WorldNormal instead
//    of SCS_Normal (the fallback when the box shows SCS_Normal in neither
//    encoding: refused labels.normal_encoding by name).
//  * -velocity-check: the engine's velocity through M_Velocity (signed,
//    unencoded) on its own capture with bAlwaysPersistRenderingState true,
//    frame_NNNN_velocity.f32 -- a READ-BACK beside the Python flow (S2),
//    never the truth; exclusive with -passes=velocity (one velocity
//    capture per step can see the motion).
//  * -calibration: after the run, one calibration frame -- an emissive
//    grey quad at a stated cd/m^2, a white Lambertian quad under the sun
//    alone (sky light, GI, atmosphere transmittance and shadows off), a
//    5 degree slanted-edge quad -- recorded in render.json calibration{}
//    and calibration.json (predicted from core/capture/radiometry.py's
//    chain, measured on the box).
//  * -sun-lux=<lux>: the directional light set in lux
//    (look_applied.sun.light_units 'physical'; FlightSimVisualScene).
//  * -accumulate=<K>: K AA-off sub-exposures over the exposure window per
//    frame on a dedicated capture, t0_s / t1_s recorded per frame; k = 1
//    when the predicted blur is under 0.25 px (core/capture/blur.py).

#pragma once

#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "FlightSimRenderCommandlet.generated.h"

DECLARE_LOG_CATEGORY_EXTERN(LogFlightSimRender, Log, All);

UCLASS()
class FLIGHTSIMBRIDGE_API UFlightSimRenderCommandlet : public UCommandlet
{
	GENERATED_BODY()

public:
	UFlightSimRenderCommandlet();

	virtual int32 Main(const FString& Params) override;

	// -- S4: the calibration chain and the writers, public so each is one
	// expression a source-reading test can pin against the Python side ----

	// core/capture/radiometry.py luminance_per_unit: the cd/m^2 one unit of
	// the linear frame stands for, 1.2 x A x 2^(EV100 - EC) (ISO 2720 /
	// ISO 12232 / Lagarde 2014 s5.1 with Unreal's lens attenuation A).
	static double LuminancePerUnit(double Ev100, double ExposureCompensationEv,
	                               double LensAttenuation);

	// core/capture/radiometry.py grey_card_luminance: a Lambertian surface's
	// luminance under an illuminance, rho x E / pi (cd/m^2).
	static double LambertianLuminance(double IlluminanceLux, double Reflectance);

	// The 0.25 px rule (core/capture/blur.py SUB_PIXEL_BLUR_PX): k = 1 when
	// the predicted blur over the exposure window is under a quarter pixel,
	// else the K asked for.
	static int32 AccumulationCount(double PredictedBlurPx, int32 RequestedK);

	// The linear .f32 writer. Byte layout, stated once: raw little-endian
	// IEEE-754 float32, NO header, row-major from the top-left pixel,
	// Channels values per pixel interleaved -- Width * Height * Channels
	// floats, 4 * Channels bytes a pixel. numpy reads it as
	// numpy.fromfile(path, '<f4').reshape(Height, Width, Channels)
	// (core/capture/passes.py read_normal_f32 / read_basecolor_f32 with
	// Channels = 3). Returns false (and writes nothing) when Values is not
	// Width * Height * Channels long.
	static bool WriteLinearF32(const FString& Path, const TArray<float>& Values,
	                           int32 Width, int32 Height, int32 Channels);

	// MTF50 in cycles per pixel of one near-vertical slanted edge inside the
	// crop [U0, U1) x [V0, V1) of a Width x Height luminance image, by an
	// e-SFR written from ISO 12233's definition (per-row half-level crossing,
	// a least-squares edge line, the edge spread binned at a quarter pixel
	// along the normal, its Hamming-windowed derivative, a DFT). A THIRD
	// implementation beside core/capture/optics.py esfr_mtf50 and the
	// verifier's own; it shares no code with either. Negative when no edge
	// is found.
	static double EsfrMtf50(const TArray<float>& Luminance, int32 Width, int32 Height,
	                        int32 U0, int32 V0, int32 U1, int32 V1);
};
