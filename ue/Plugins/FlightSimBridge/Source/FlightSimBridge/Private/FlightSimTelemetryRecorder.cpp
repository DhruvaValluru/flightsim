#include "FlightSimTelemetryRecorder.h"

#include "FlightSimScenarioWorld.h"
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
// P9: core/fdm/units.py's factors for the new rows.
constexpr double RecorderLbToKg = 0.45359237;
constexpr double RecorderRankineToKelvin = 5.0 / 9.0;
constexpr double RecorderInchToMetre = 0.3048 / 12.0;
constexpr double RecorderSlugFt2ToKgM2 = 515.378818393 * 0.3048 * 0.3048 * 0.3048 * 0.3048 * 0.3048;

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
	// -- P9: every REGISTRY.host_channels() column (core/registry.py), so the
	// two recorders carry one schema (pinned equal by
	// tests/test_ue_physics_source.py). Property rows read JSBSim through
	// the same verified names core/fdm/state.py reads; "host:" rows are
	// served by FFlightSimScenarioWorld::HostChannel -- the values the
	// headless recorder takes from its providers (Recorder extra), from a
	// property with a stock-airframe default, or from two properties.
	{TEXT("mach"), TEXT("velocities/mach"), 1.0, true},
	{TEXT("roll_rate_dps"), TEXT("velocities/p-rad_sec"), RecorderRadToDeg, true},
	{TEXT("weight_kg"), TEXT("inertia/weight-lbs"), RecorderLbToKg, true},
	{TEXT("wind_speed_mps"), TEXT("host:wind_speed_mps"), 1.0, true},
	// the atmosphere (gap P1)
	{TEXT("density_altitude_m"), TEXT("atmosphere/density-altitude"), RecorderFeetToMetres, true},
	{TEXT("pressure_altitude_m"), TEXT("atmosphere/pressure-altitude"), RecorderFeetToMetres, true},
	{TEXT("temperature_k"), TEXT("atmosphere/T-R"), RecorderRankineToKelvin, true},
	{TEXT("rh_pct"), TEXT("atmosphere/RH"), 1.0, true},
	{TEXT("vapour_pressure_pa"), TEXT("atmosphere/vapor-pressure-psf"), RecorderPsfToPa, true},
	// the icing (P5): 0 / 1.0 / 0 on a stock airframe, as state.py records
	{TEXT("icing_eta"), TEXT("host:icing_eta"), 1.0, true},
	{TEXT("icing_lift_factor"), TEXT("host:icing_lift_factor"), 1.0, true},
	{TEXT("icing_drag_factor"), TEXT("host:icing_drag_factor"), 1.0, true},
	{TEXT("icing_pitch_factor"), TEXT("host:icing_pitch_factor"), 1.0, true},
	{TEXT("icing_roll_factor"), TEXT("host:icing_roll_factor"), 1.0, true},
	{TEXT("icing_yaw_factor"), TEXT("host:icing_yaw_factor"), 1.0, true},
	{TEXT("icing_side_factor"), TEXT("host:icing_side_factor"), 1.0, true},
	{TEXT("icing_alpha_shift_deg"), TEXT("host:icing_alpha_shift_deg"), 1.0, true},
	// the gust channel and the wind profile (P6)
	{TEXT("gust_north_mps"), TEXT("atmosphere/gust-north-fps"), RecorderFeetToMetres, true},
	{TEXT("gust_east_mps"), TEXT("atmosphere/gust-east-fps"), RecorderFeetToMetres, true},
	{TEXT("gust_down_mps"), TEXT("atmosphere/gust-down-fps"), RecorderFeetToMetres, true},
	{TEXT("gust_p_equivalent_rad_s"), TEXT("host:gust_p_equivalent_rad_s"), 1.0, true},
	{TEXT("wind_profile_speed_mps"), TEXT("host:wind_profile_speed_mps"), 1.0, true},
	{TEXT("wind_layer_index"), TEXT("host:wind_layer_index"), 1.0, true},
	{TEXT("shear_dv_dz_per_s"), TEXT("host:shear_dv_dz_per_s"), 1.0, true},
	// the loading (P4)
	{TEXT("cg_x_m"), TEXT("inertia/cg-x-in"), RecorderInchToMetre, true},
	{TEXT("iyy_kgm2"), TEXT("inertia/iyy-slugs_ft2"), RecorderSlugFt2ToKgM2, true},
	// the vertical datum (P10): N at the origin, altitude + N
	{TEXT("undulation_m"), TEXT("host:undulation_m"), 1.0, true},
	{TEXT("hae_m"), TEXT("host:hae_m"), 1.0, true},
	// the failures (P3): the schedule's flag, the surfaces in degrees, the
	// engines the airframe has (optional: a spool it lacks records null)
	{TEXT("failure_state_flag"), TEXT("host:failure_state_flag"), 1.0, true},
	{TEXT("elevator_deg"), TEXT("fcs/elevator-pos-rad"), RecorderRadToDeg, true},
	{TEXT("aileron_deg"), TEXT("fcs/left-aileron-pos-rad"), RecorderRadToDeg, false},
	{TEXT("rudder_deg"), TEXT("fcs/rudder-pos-rad"), RecorderRadToDeg, false},
	{TEXT("engine0_thrust_n"), TEXT("propulsion/engine/thrust-lbs"), RecorderLbfToNewton, false},
	{TEXT("engine1_thrust_n"), TEXT("propulsion/engine[1]/thrust-lbs"), RecorderLbfToNewton, false},
	{TEXT("engine0_n1_pct"), TEXT("propulsion/engine/n1"), 1.0, false},
	{TEXT("engine1_n1_pct"), TEXT("propulsion/engine[1]/n1"), 1.0, false},
	{TEXT("engine0_rpm"), TEXT("propulsion/engine/engine-rpm"), 1.0, false},
	{TEXT("engine1_rpm"), TEXT("propulsion/engine[1]/engine-rpm"), 1.0, false},
	// the wake pair (P7): the host port's evaluation at the own CG (0
	// without a wake; the RCR is null where a wake is flown -- the card
	// carries no aileron term to form it from)
	{TEXT("wake_v_mps"), TEXT("host:wake_v_mps"), 1.0, true},
	{TEXT("wake_w_mps"), TEXT("host:wake_w_mps"), 1.0, true},
	{TEXT("wake_p_eq_rad_s"), TEXT("host:wake_p_eq_rad_s"), 1.0, true},
	{TEXT("wake_gamma_m2_s"), TEXT("host:wake_gamma_m2_s"), 1.0, true},
	{TEXT("wake_age_s"), TEXT("host:wake_age_s"), 1.0, true},
	{TEXT("wake_lateral_m"), TEXT("host:wake_lateral_m"), 1.0, true},
	{TEXT("wake_vertical_m"), TEXT("host:wake_vertical_m"), 1.0, true},
	{TEXT("wake_rcr"), TEXT("host:wake_rcr"), 1.0, false},
	// the limits (the exceedance flags): post-run annotations on BOTH
	// hosts -- core/telemetry/limits.py monitor() over the recorded n_z,
	// cas_kt, mach and alpha_deg columns -- so the host records them null
	// and the annotation fills them where the headless run's are filled.
	{TEXT("exceed_nz_pos"), TEXT("host:exceed_nz_pos"), 1.0, false},
	{TEXT("exceed_nz_neg"), TEXT("host:exceed_nz_neg"), 1.0, false},
	{TEXT("exceed_vne_or_vmo"), TEXT("host:exceed_vne_or_vmo"), 1.0, false},
	{TEXT("exceed_mmo"), TEXT("host:exceed_mmo"), 1.0, false},
	{TEXT("exceed_alpha_stall"), TEXT("host:exceed_alpha_stall"), 1.0, false},
	{TEXT("any_exceedance"), TEXT("host:any_exceedance"), 1.0, false},
};

// The prefix of a row served by the scenario world rather than JSBSim.
const TCHAR* const RecorderHostPrefix = TEXT("host:");
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
	if (Name.StartsWith(RecorderHostPrefix))
	{
		// P9: a host-computed channel, read from the scenario world that
		// drives this movement component -- still a read: nothing here
		// writes to the FDM or to the world.
		double HostValue = NAN;
		FFlightSimScenarioWorld::ReadHostChannel(
			Movement, Name.RightChop(FCString::Strlen(RecorderHostPrefix)), HostValue);
		return HostValue;
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
		else if (FString(Channel.Property).StartsWith(RecorderHostPrefix))
		{
			UE_LOG(LogTemp, Display,
			       TEXT("telemetry: host channel '%s' has no host-side value on ")
			       TEXT("this run; column '%s' records null"),
			       Channel.Property, Channel.Column);
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
