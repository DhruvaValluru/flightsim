// The applied-vs-solved parity tolerances, driven at their boundaries.
//
// AFlightSimCameraDirector::ApplyPoseAtTime refuses when the pose the
// engine ACTUALLY applied differs from the solved one -- 10 cm of
// position, 0.05 deg of rotation. The rotation half was the last
// tolerance in the camera phase with nothing behind it: no test drove
// it, so "0.05" was a number in a source file rather than a decision.
// A guard nobody has ever seen fire is indistinguishable from a guard
// that cannot fire.
//
// These are the first automation tests in this plugin. Run them with:
//
//   & "$env:UE_ROOT\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" `
//       <repo>\ue\FlightSim.uproject `
//       -ExecCmds="Automation RunTests FlightSim.CameraDirector; Quit" `
//       -unattended -nopause -nosplash -stdout -NullRHI
//
// scripts\test_ue.ps1 wraps exactly that.

#include "FlightSimCameraDirector.h"

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

namespace
{
	// A rotation of exactly DeltaDeg about an arbitrary, deliberately
	// non-axis-aligned axis. Off-axis because a tolerance that only
	// ever sees yaw would not catch a convention that mixes the axes
	// up, and AngularDistance is the quantity the guard uses.
	FQuat RotatedBy(const FQuat& Base, double DeltaDeg)
	{
		const FVector Axis = FVector(0.3, -0.7, 0.6).GetSafeNormal();
		return Base * FQuat(Axis, FMath::DegreesToRadians(DeltaDeg));
	}

	const FQuat BasePose =
		FRotator(-6.2258, 138.3665, 0.0).Quaternion();
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
	FFlightSimRotationParityMeasuresTheAngle,
	"FlightSim.CameraDirector.RotationParityMeasuresTheAngle",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FFlightSimRotationParityMeasuresTheAngle::RunTest(const FString&)
{
	// The guard's decision is an angle, so it has to BE the angle:
	// a helper that returned, say, the largest Euler component would
	// pass an identity test and mis-grade every off-axis divergence.
	//
	// A pose against ITSELF does not measure exactly zero, and the
	// reason is worth pinning rather than tolerating. AngularDistance
	// goes through acos, whose derivative is unbounded as its argument
	// approaches 1, so the float error in a normalised quaternion is
	// amplified into an angle. Measured here: 2e-6 deg for an identical
	// pose. That is the guard's noise FLOOR -- it can never resolve a
	// divergence finer than this -- and it sits four orders of
	// magnitude under the 0.05 deg tolerance, so the tolerance is
	// measuring displacement rather than its own arithmetic.
	const double Floor = AFlightSimCameraDirector::RotationErrorDegrees(
		BasePose, BasePose);
	TestTrue(FString::Printf(
		TEXT("a pose against itself measures %.3g deg, the acos noise "
		     "floor, well under the 0.05 deg tolerance"), Floor),
		Floor < 1.0e-4);
	for (const double Degrees : {0.01, 0.05, 0.5, 5.0, 30.0})
	{
		const double Measured = AFlightSimCameraDirector::RotationErrorDegrees(
			RotatedBy(BasePose, Degrees), BasePose);
		TestEqual(FString::Printf(
			TEXT("a %.2f deg rotation measures %.2f deg"), Degrees, Degrees),
			Measured, Degrees, 1.0e-6);
	}
	// Symmetric: which pose is "applied" cannot change the verdict.
	TestEqual(TEXT("the measure is symmetric"),
	          AFlightSimCameraDirector::RotationErrorDegrees(
	              BasePose, RotatedBy(BasePose, 0.2)),
	          AFlightSimCameraDirector::RotationErrorDegrees(
	              RotatedBy(BasePose, 0.2), BasePose), 1.0e-6);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
	FFlightSimRotationParityBoundary,
	"FlightSim.CameraDirector.RotationParityBoundary",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FFlightSimRotationParityBoundary::RunTest(const FString&)
{
	const double Tolerance = AFlightSimCameraDirector::RotationToleranceDeg;
	TestEqual(TEXT("the tolerance is the documented 0.05 deg"),
	          Tolerance, 0.05, 1.0e-12);

	// Just under: allowed. This is the side a real render lives on --
	// a measured run's applied and solved Euler angles agree to
	// 2.6e-14 deg, which through this comparison reads as the acos
	// floor above. The guard must not fire on round-trip noise.
	const double JustUnder = AFlightSimCameraDirector::RotationErrorDegrees(
		RotatedBy(BasePose, Tolerance * 0.9), BasePose);
	TestTrue(TEXT("0.045 deg of divergence is within tolerance"),
	         JustUnder <= Tolerance);

	// Just over: refused. 0.055 deg is 0.96 m of misplaced world at a
	// kilometre, which is the whole reason the rotation half of the
	// guard exists -- position parity alone let this through.
	const double JustOver = AFlightSimCameraDirector::RotationErrorDegrees(
		RotatedBy(BasePose, Tolerance * 1.1), BasePose);
	TestTrue(TEXT("0.055 deg of divergence exceeds tolerance"),
	         JustOver > Tolerance);

	// And the boundary is where it says it is, not a decade away: the
	// two cases above must straddle it by the margin they claim.
	TestTrue(TEXT("the two cases straddle the tolerance"),
	         JustUnder < Tolerance && Tolerance < JustOver);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
	FFlightSimPositionParityBoundary,
	"FlightSim.CameraDirector.PositionParityBoundary",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FFlightSimPositionParityBoundary::RunTest(const FString&)
{
	const double Tolerance = AFlightSimCameraDirector::PositionToleranceCm;
	TestEqual(TEXT("the tolerance is the documented 10 cm"),
	          Tolerance, 10.0, 1.0e-12);

	// FVector::Equals is per-component, which is what ApplyPoseAtTime
	// uses; pinning it here means a change to that call is a change to
	// a test rather than a silent widening along the diagonal.
	const FVector Solved(1200.0, -340.0, 30600.0);
	TestTrue(TEXT("9 cm on one axis is within tolerance"),
	         Solved.Equals(Solved + FVector(9.0, 0.0, 0.0), Tolerance));
	TestFalse(TEXT("11 cm on one axis is not"),
	          Solved.Equals(Solved + FVector(11.0, 0.0, 0.0), Tolerance));
	TestFalse(TEXT("11 cm on the last axis is not, either"),
	          Solved.Equals(Solved + FVector(0.0, 0.0, 11.0), Tolerance));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
	FFlightSimPoseTrackRefusals,
	"FlightSim.CameraDirector.PoseTrackRefusals",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FFlightSimPoseTrackRefusals::RunTest(const FString&)
{
	AFlightSimCameraDirector* Director =
		NewObject<AFlightSimCameraDirector>();
	FString Error;

	// A track nobody solved.
	TestFalse(TEXT("a one-sample track is refused"),
	          Director->SetPoseTrack({0.0}, {FVector::ZeroVector},
	                                 {FRotator::ZeroRotator}, {35.0}, Error));
	TestTrue(TEXT("and says why"), Error.Contains(TEXT("not a track")));

	// Misaligned arrays: the shape that would silently pair a time with
	// the wrong pose.
	TestFalse(TEXT("mismatched array lengths are refused"),
	          Director->SetPoseTrack({0.0, 0.1},
	                                 {FVector::ZeroVector},
	                                 {FRotator::ZeroRotator, FRotator::ZeroRotator},
	                                 {35.0, 35.0}, Error));
	TestTrue(TEXT("and says why"), Error.Contains(TEXT("misaligned")));

	// A lens that is not a lens; the field of view would be a guess.
	TestFalse(TEXT("a non-positive focal length is refused"),
	          Director->SetPoseTrack({0.0, 0.1},
	                                 {FVector::ZeroVector, FVector::ZeroVector},
	                                 {FRotator::ZeroRotator, FRotator::ZeroRotator},
	                                 {35.0, 0.0}, Error));
	TestTrue(TEXT("and says why"), Error.Contains(TEXT("is not a lens")));

	// Time must run forwards, or interpolation picks a bracket at random.
	TestFalse(TEXT("non-increasing times are refused"),
	          Director->SetPoseTrack({0.1, 0.1},
	                                 {FVector::ZeroVector, FVector::ZeroVector},
	                                 {FRotator::ZeroRotator, FRotator::ZeroRotator},
	                                 {35.0, 35.0}, Error));
	TestTrue(TEXT("and says why"),
	         Error.Contains(TEXT("strictly")));

	// A good track, and then the refusal that the first real render
	// actually hit: a time the track does not cover is never
	// extrapolated.
	TestTrue(TEXT("a well-formed track is accepted"),
	         Director->SetPoseTrack({0.5, 1.5},
	                                {FVector::ZeroVector, FVector(100.0, 0.0, 0.0)},
	                                {FRotator::ZeroRotator, FRotator::ZeroRotator},
	                                {35.0, 35.0}, Error));
	TestEqual(TEXT("the track starts where it starts"),
	          Director->TrackStartSeconds(), 0.5, 1.0e-9);
	TestFalse(TEXT("a time before the track is refused, not extrapolated"),
	          Director->ApplyPoseAtTime(0.0, Error));
	TestTrue(TEXT("and says so by name"),
	         Error.Contains(TEXT("lies outside the solved track")));
	TestFalse(TEXT("a time after the track is refused too"),
	          Director->ApplyPoseAtTime(2.0, Error));
	return true;
}

#endif  // WITH_DEV_AUTOMATION_TESTS
