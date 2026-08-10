#include "FlightSimTelemetryRecorder.h"

#include "JSBSimMovementComponent.h"
#include "Misc/FileHelper.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace
{
// Unit conversions only -- a scale is never physics.
constexpr double RecorderFeetToMetres = 0.3048;
constexpr double RecorderRadToDeg = 57.295779513082323;
constexpr double RecorderPsfToPa = 47.880259;
constexpr double RecorderLbfToNewton = 4.4482216153;

// Column names match core/telemetry/recorder.py exactly. Every property
// name was verified against the live catalog of the pinned JSBSim on
// 2026-08-10 (hazard 1): aero/alpha-deg, aero/beta-deg, aero/qbar-psf,
// forces/fb{x,y,z}-aero-lbs (BODY-axis aero force), forces/fw{x,y,z}-aero-lbs
// (WIND-axis: fwx = drag, fwy = side force, fwz = lift -- recorded directly,
// so lift/drag on any panel are FDM outputs, not a transform someone did),
// and flight-path/gamma-deg all exist and read finite in trimmed flight.
const FFlightSimTelemetryChannel GFlightSimTelemetryChannels[] = {
	{TEXT("t"), TEXT("simulation/sim-time-sec"), 1.0, true},
	{TEXT("altitude_m"), TEXT("position/h-sl-meters"), 1.0, true},
	{TEXT("agl_m"), TEXT("position/h-agl-ft"), RecorderFeetToMetres, true},
	{TEXT("lat_deg"), TEXT("position/lat-geod-deg"), 1.0, true},
	{TEXT("lon_deg"), TEXT("position/long-gc-deg"), 1.0, true},
	{TEXT("tas_kt"), TEXT("velocities/vtrue-kts"), 1.0, true},
	{TEXT("cas_kt"), TEXT("velocities/vc-kts"), 1.0, true},
	{TEXT("roll_deg"), TEXT("attitude/phi-rad"), RecorderRadToDeg, true},
	{TEXT("pitch_deg"), TEXT("attitude/theta-rad"), RecorderRadToDeg, true},
	{TEXT("heading_deg"), TEXT("attitude/psi-rad"), RecorderRadToDeg, true},
	// Accelerometer, never finite-differenced (§1.3).
	{TEXT("n_z"), TEXT("accelerations/Nz"), 1.0, true},
	{TEXT("elevator_pos_rad"), TEXT("fcs/elevator-pos-rad"), 1.0, true},
	// Not every airframe defines every surface: optional, NaN when absent.
	{TEXT("aileron_pos_rad"), TEXT("fcs/left-aileron-pos-rad"), 1.0, false},
	{TEXT("rudder_pos_rad"), TEXT("fcs/rudder-pos-rad"), 1.0, false},
	// -- the aero block (Phase 8 panel): the FDM's own aerodynamic state --
	{TEXT("alpha_deg"), TEXT("aero/alpha-deg"), 1.0, true},
	{TEXT("beta_deg"), TEXT("aero/beta-deg"), 1.0, true},
	{TEXT("qbar_pa"), TEXT("aero/qbar-psf"), RecorderPsfToPa, true},
	{TEXT("f_aero_x_n"), TEXT("forces/fbx-aero-lbs"), RecorderLbfToNewton, true},
	{TEXT("f_aero_y_n"), TEXT("forces/fby-aero-lbs"), RecorderLbfToNewton, true},
	{TEXT("f_aero_z_n"), TEXT("forces/fbz-aero-lbs"), RecorderLbfToNewton, true},
	{TEXT("drag_n"), TEXT("forces/fwx-aero-lbs"), RecorderLbfToNewton, true},
	{TEXT("side_force_n"), TEXT("forces/fwy-aero-lbs"), RecorderLbfToNewton, true},
	{TEXT("lift_n"), TEXT("forces/fwz-aero-lbs"), RecorderLbfToNewton, true},
	{TEXT("flight_path_angle_deg"), TEXT("flight-path/gamma-deg"), 1.0, true},
	// The TOTAL wind reaching the FDM (steady + gust + turbulence) and the
	// NED velocity: what a wind-triangle plot draws from recorded values.
	{TEXT("wind_north_mps"), TEXT("atmosphere/total-wind-north-fps"), RecorderFeetToMetres, true},
	{TEXT("wind_east_mps"), TEXT("atmosphere/total-wind-east-fps"), RecorderFeetToMetres, true},
	{TEXT("wind_down_mps"), TEXT("atmosphere/total-wind-down-fps"), RecorderFeetToMetres, true},
	{TEXT("v_north_mps"), TEXT("velocities/v-north-fps"), RecorderFeetToMetres, true},
	{TEXT("v_east_mps"), TEXT("velocities/v-east-fps"), RecorderFeetToMetres, true},
	{TEXT("v_down_mps"), TEXT("velocities/v-down-fps"), RecorderFeetToMetres, true},
};
}

TArrayView<const FFlightSimTelemetryChannel>
UFlightSimTelemetryRecorder::ChannelTable()
{
	return MakeArrayView(GFlightSimTelemetryChannels,
	                     UE_ARRAY_COUNT(GFlightSimTelemetryChannels));
}

UFlightSimTelemetryRecorder::UFlightSimTelemetryRecorder()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.TickGroup = TG_PostPhysics;
}

void UFlightSimTelemetryRecorder::StartRecording(const FString& InOutputPath)
{
	OutputPath = InOutputPath;
	bRecording = true;
	TimeSinceLastSample = SampleIntervalSeconds;   // sample immediately
	Columns.Reset();
	Columns.SetNum(ChannelTable().Num());
}

double UFlightSimTelemetryRecorder::ReadProperty(const FString& Name)
{
	if (Movement == nullptr)
	{
		return 0.0;
	}
	FString Value;
	Movement->CommandConsole(Name, FString(), Value);
	// An empty result means the property does not exist. Returning NaN rather
	// than 0.0 keeps a missing channel visibly missing: a zero would compare
	// plausibly against the headless run and hide the gap.
	return Value.IsEmpty() ? NAN : FCString::Atod(*Value);
}

bool UFlightSimTelemetryRecorder::SelftestProperties(FString& Error)
{
	if (Movement == nullptr)
	{
		Error = TEXT("telemetry selftest: no movement component to read");
		return false;
	}
	TArray<FString> Missing;
	for (const FFlightSimTelemetryChannel& Channel : ChannelTable())
	{
		const double Value = ReadProperty(Channel.Property);
		if (FMath::IsFinite(Value))
		{
			continue;
		}
		if (Channel.bRequired)
		{
			Missing.Add(Channel.Property);
		}
		else
		{
			UE_LOG(LogTemp, Warning,
			       TEXT("telemetry: optional property '%s' absent on this ")
			       TEXT("airframe; column '%s' will record NaN"),
			       Channel.Property, Channel.Column);
		}
	}
	if (Missing.Num() > 0)
	{
		// hazard 1 (JSBSIM_CORRECTIONS §3): an unknown property reads as
		// empty, silently. This failure is the loud alternative.
		Error = FString::Printf(
			TEXT("telemetry selftest: %d required propert%s missing from the ")
			TEXT("loaded model: %s -- refusing to record NaN forever"),
			Missing.Num(), Missing.Num() == 1 ? TEXT("y") : TEXT("ies"),
			*FString::Join(Missing, TEXT(", ")));
		return false;
	}
	return true;
}

void UFlightSimTelemetryRecorder::TickComponent(
	float DeltaTime, ELevelTick TickType,
	FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	if (!bRecording || Movement == nullptr)
	{
		return;
	}

	TimeSinceLastSample += DeltaTime;
	if (TimeSinceLastSample < SampleIntervalSeconds)
	{
		return;
	}
	TimeSinceLastSample = 0.0f;

	const TArrayView<const FFlightSimTelemetryChannel> Channels = ChannelTable();
	for (int32 Index = 0; Index < Channels.Num(); ++Index)
	{
		Columns[Index].Add(
			ReadProperty(Channels[Index].Property) * Channels[Index].Scale);
	}
}

bool UFlightSimTelemetryRecorder::WriteToDisk()
{
	if (OutputPath.IsEmpty() || GetSampleCount() == 0)
	{
		return false;
	}

	const TArrayView<const FFlightSimTelemetryChannel> Channels = ChannelTable();
	TSharedPtr<FJsonObject> ColumnsObject = MakeShared<FJsonObject>();
	for (int32 Index = 0; Index < Channels.Num(); ++Index)
	{
		TArray<TSharedPtr<FJsonValue>> Array;
		Array.Reserve(Columns[Index].Num());
		for (double Value : Columns[Index])
		{
			// NaN is not JSON: an optional channel absent on this airframe
			// serializes as null, which parses back as visibly-missing.
			Array.Add(FMath::IsFinite(Value)
				? MakeShared<FJsonValueNumber>(Value)
				: StaticCastSharedRef<FJsonValue>(MakeShared<FJsonValueNull>()));
		}
		ColumnsObject->SetArrayField(Channels[Index].Column, Array);
	}

	TSharedPtr<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("host"), TEXT("unreal"));
	Root->SetNumberField(TEXT("samples"), GetSampleCount());
	Root->SetNumberField(TEXT("interval_s"), SampleIntervalSeconds);
	Root->SetObjectField(TEXT("columns"), ColumnsObject);

	FString Output;
	TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
	FJsonSerializer::Serialize(Root.ToSharedRef(), Writer);
	return FFileHelper::SaveStringToFile(Output, *OutputPath);
}
