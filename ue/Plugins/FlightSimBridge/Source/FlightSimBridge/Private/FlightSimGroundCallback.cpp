#include "FlightSimGroundCallback.h"
#include "FlightSimHeightfield.h"
#include "GeoReferencingSystem.h"
#include "Templates/SharedPointer.h"
#include "UObject/WeakObjectPtr.h"
// JSBSim's FGGroundCallback, FGLocation and FGColumnVector3 behind the
// plugin's warning pragmas (the raw headers do not build under UE's
// warnings-as-errors).
#include "UEGroundCallback.h"

namespace
{
	constexpr double FeetToMetresGround = 0.3048;
	constexpr double MetresToFeetGround = 1.0 / 0.3048;
	// WGS84 semi-axes in feet, as the plugin's UEGroundCallback states them:
	// without them the contact FGLocation is not a valid location.
	constexpr double SemiMajorFeet = 20925646.32546;
	constexpr double SemiMinorFeet = 20855486.5951;

	class FFlightSimRasterGroundCallback : public JSBSim::FGGroundCallback
	{
	public:
		FFlightSimRasterGroundCallback(const TSharedRef<const FFlightSimHeightfield>& InTerrain,
		                               AGeoReferencingSystem* InGeoReferencing)
			: Terrain(InTerrain)
			, GeoReferencing(InGeoReferencing)
		{
		}

		// Height above the raster under `location`, in feet; contact point on
		// the raster (ECEF, feet); normal the geodetic up; the raster does not
		// move.
		double GetAGLevel(double /*t*/, const JSBSim::FGLocation& location,
		                  JSBSim::FGLocation& contact,
		                  JSBSim::FGColumnVector3& normal,
		                  JSBSim::FGColumnVector3& v,
		                  JSBSim::FGColumnVector3& w) const override
		{
			v.InitMatrix();
			w.InitMatrix();

			AGeoReferencingSystem* Geo = GeoReferencing.Get();
			if (Geo == nullptr)
			{
				// The world is gone (engine exit tears JSBSim down after the
				// commandlet's world object): answer the bare ellipsoid rather
				// than touch a destroyed actor. No flight is recorded from here.
				const double Lat = location.GetGeodLatitudeRad();
				const double Lon = location.GetLongitude();
				normal = JSBSim::FGColumnVector3(FMath::Cos(Lat) * FMath::Cos(Lon),
				                                 FMath::Cos(Lat) * FMath::Sin(Lon),
				                                 FMath::Sin(Lat));
				contact = location;
				return location.GetGeodAltitude();
			}

			// JSBSim's location is ECEF in feet. The raster is sampled in the
			// card's projected CRS through the same georeferencing transform
			// and the same lookup VerifyTrimmedCondition's AGL check uses, so
			// what the trim check expects and what the FDM is told are one
			// number.
			const FVector EcefMetres(location(1) * FeetToMetresGround,
			                         location(2) * FeetToMetresGround,
			                         location(3) * FeetToMetresGround);
			FVector Projected;
			Geo->ECEFToProjected(EcefMetres, Projected);
			const double GroundMetres = Terrain->ElevationAt(Projected.X, Projected.Y);

			FVector ContactEcef;
			Geo->ProjectedToECEF(FVector(Projected.X, Projected.Y, GroundMetres), ContactEcef);
			contact.SetEllipse(SemiMajorFeet, SemiMinorFeet);
			contact = JSBSim::FGColumnVector3(ContactEcef.X, ContactEcef.Y, ContactEcef.Z)
			          * MetresToFeetGround;

			// Normal up: the geodetic vertical at the query point, in ECEF.
			FGeographicCoordinates Geographic;
			Geo->ECEFToGeographic(EcefMetres, Geographic);
			const double Lat = FMath::DegreesToRadians(Geographic.Latitude);
			const double Lon = FMath::DegreesToRadians(Geographic.Longitude);
			normal = JSBSim::FGColumnVector3(FMath::Cos(Lat) * FMath::Cos(Lon),
			                                 FMath::Cos(Lat) * FMath::Sin(Lon),
			                                 FMath::Sin(Lat));

			return (Projected.Z - GroundMetres) * MetresToFeetGround;
		}

	private:
		// Owned: the scenario world's heightfield member dies with the
		// commandlet's stack frame, before the plugin deletes JSBSim.
		TSharedRef<const FFlightSimHeightfield> Terrain;
		TWeakObjectPtr<AGeoReferencingSystem> GeoReferencing;
	};
}

TFunction<JSBSim::FGGroundCallback*()> MakeFlightSimRasterGroundFactory(
	const FFlightSimHeightfield& Terrain, AGeoReferencingSystem* GeoReferencing)
{
	// One copy of the raster (about a megabyte for a 800 x 800 bake), shared
	// by every callback instance the plugin asks for.
	TSharedRef<const FFlightSimHeightfield> Owned =
		MakeShared<const FFlightSimHeightfield>(Terrain);
	return [Owned, GeoReferencing]() -> JSBSim::FGGroundCallback*
	{
		return new FFlightSimRasterGroundCallback(Owned, GeoReferencing);
	};
}
