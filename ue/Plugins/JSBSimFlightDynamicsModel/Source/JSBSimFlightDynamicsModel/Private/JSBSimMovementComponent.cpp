// Fill out your copyright notice in the Description page of Project Settings.


#include "JSBSimMovementComponent.h"
#include "JSBSimModule.h"

// UE treats warning as errors. JSBSim has some warnings in its include files, so if we don't catch them inside this push/pop pragma, we won't be able to build...
// FGOutputType.h(151): warning C4263: 'bool JSBSim::FGOutputType::Run(void)': member function does not override any base class virtual member function
// FGOutputType.h(215): warning C4264: 'bool JSBSim::FGModel::Run(bool)': no override available for virtual member function from base 'JSBSim::FGModel'; function is hidden --- And others
// compiler.h(58): warning C4005: 'DEPRECATED': macro redefinition with UE_5.0\Engine\Source\Runtime\Core\Public\Windows\WindowsPlatformCompilerPreSetup.h(55): note: see previous definition of 'DEPRECATED'
// FGXMLElement.h(369): error C4458: declaration of 'name' hides class member
#ifdef _MSC_VER
#pragma warning( push )
#pragma warning( disable : 4263 )
#pragma warning( disable : 4264 )
#pragma warning( disable : 4005 )
#pragma warning( disable : 4458 )
#elif defined(__clang__)
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Woverloaded-virtual"
#pragma clang diagnostic ignored "-Wshadow"
#endif

#include "FGFDMExec.h"
#include "math/FGLocation.h"
#include "models/FGFCS.h"
#include "models/FGPropulsion.h"
#include "models/propulsion/FGEngine.h"
#include "models/atmosphere/FGWinds.h"
#include "models/FGAerodynamics.h"
#include "models/FGAircraft.h"
#include "models/FGAtmosphere.h"
#include "models/FGAuxiliary.h"
#include "models/FGLGear.h"
#include "models/FGMassBalance.h"
#include "models/propulsion/FGThruster.h"
#include "models/propulsion/FGPiston.h"
#include "models/propulsion/FGTurbine.h"
#include "models/propulsion/FGTurboProp.h"
#include "models/propulsion/FGTank.h"
#include "initialization/FGInitialCondition.h"
#include "initialization/FGTrim.h"
#include "Interfaces/IPluginManager.h"
#include "simgear/props/props.hxx"

#ifdef _MSC_VER
#pragma warning( pop )
#elif defined(__clang__)
#pragma clang diagnostic pop
#endif

#include "UEGroundCallback.h"

#include "DrawDebugHelpers.h"
#include "GeoReferencingSystem.h"
#include "Components/ActorComponent.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

// LOCAL PATCH 5 (VENDORED.json): FIPS 180-4 SHA-256 of the aircraft XML at
// the door, as lowercase hex -- self-contained because the platform
// SHA-256 asserts on Mac, and the hash must equal the one Python's hashlib
// recorded for the derived airframe (core/control/derive.py derived_sha256).
namespace JSBSimLocalPatch5
{
	static FString Sha256Hex(const uint8* Data, uint64 Length)
	{
		static const uint32 K[64] = {
			0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
			0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
			0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
			0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
			0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
			0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
			0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
			0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
		uint32 H[8] = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
		               0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
		const uint64 BitLength = Length * 8;
		const uint64 Padded = ((Length + 8) / 64 + 1) * 64;
		TArray<uint8> Buffer;
		Buffer.SetNumZeroed(static_cast<int32>(Padded));
		if (Length > 0)
		{
			FMemory::Memcpy(Buffer.GetData(), Data, Length);
		}
		Buffer[static_cast<int32>(Length)] = 0x80;
		for (int32 Byte = 0; Byte < 8; ++Byte)
		{
			Buffer[static_cast<int32>(Padded) - 1 - Byte] = static_cast<uint8>(BitLength >> (8 * Byte));
		}
		auto Rotr = [](uint32 X, uint32 N) { return (X >> N) | (X << (32 - N)); };
		for (uint64 Chunk = 0; Chunk < Padded; Chunk += 64)
		{
			uint32 W[64];
			for (int32 Word = 0; Word < 16; ++Word)
			{
				const uint8* P = Buffer.GetData() + Chunk + Word * 4;
				W[Word] = (uint32(P[0]) << 24) | (uint32(P[1]) << 16)
				        | (uint32(P[2]) << 8) | uint32(P[3]);
			}
			for (int32 Word = 16; Word < 64; ++Word)
			{
				const uint32 S0 = Rotr(W[Word-15], 7) ^ Rotr(W[Word-15], 18) ^ (W[Word-15] >> 3);
				const uint32 S1 = Rotr(W[Word-2], 17) ^ Rotr(W[Word-2], 19) ^ (W[Word-2] >> 10);
				W[Word] = W[Word-16] + S0 + W[Word-7] + S1;
			}
			uint32 A=H[0],B=H[1],C=H[2],D=H[3],E=H[4],F=H[5],G=H[6],Hh=H[7];
			for (int32 Round = 0; Round < 64; ++Round)
			{
				const uint32 S1 = Rotr(E,6) ^ Rotr(E,11) ^ Rotr(E,25);
				const uint32 Ch = (E & F) ^ (~E & G);
				const uint32 T1 = Hh + S1 + Ch + K[Round] + W[Round];
				const uint32 S0 = Rotr(A,2) ^ Rotr(A,13) ^ Rotr(A,22);
				const uint32 Maj = (A & B) ^ (A & C) ^ (B & C);
				const uint32 T2 = S0 + Maj;
				Hh=G; G=F; F=E; E=D+T1; D=C; C=B; B=A; A=T1+T2;
			}
			H[0]+=A; H[1]+=B; H[2]+=C; H[3]+=D; H[4]+=E; H[5]+=F; H[6]+=G; H[7]+=Hh;
		}
		FString Hex;
		for (int32 Index = 0; Index < 8; ++Index)
		{
			Hex += FString::Printf(TEXT("%08x"), H[Index]);
		}
		return Hex;
	}
}


// Utility class and static member to redirect cout to UE_LOG - see in UJSBSimMovementComponent::UJSBSimMovementComponent()
class LStream : public std::stringbuf {
protected:
  int sync() {
    UE_LOG(LogJSBSim, Log, TEXT("%s"), *FString(str().c_str()));
    str("");
    return std::stringbuf::sync();
  }
};
LStream Stream;


////// Constructor
UJSBSimMovementComponent::UJSBSimMovementComponent()
{
	// Set this component to be initialized when the game starts, and to be ticked every frame.  You can turn these features off to improve performance if you don't need them.
	PrimaryComponentTick.bCanEverTick = true;

	// Uncomment to Add a stream redirector in order to output JSBSim debug info to Log
	// std::cout.rdbuf(&Stream);
}


////// Public functions
FString UJSBSimMovementComponent::GetAircraftScreenName() const
{
	FString ScreenName;
	if (AircraftLoaded && Aircraft)
	{
		ScreenName = FString(Aircraft->GetAircraftName().c_str());
	}

	return ScreenName;
}


void UJSBSimMovementComponent::PropertyManagerNode(TArray<FString>& Catalog)
{
  auto newlist = Exec->GetPropertyCatalog();

  //convert list to array
  for (auto iterate : newlist)
  {
    Catalog.Add(iterate.c_str());
  }
}

//TODO, check if this is optimized, as we are using strings for convenience and we could probably cache the propertynode once we have it
void UJSBSimMovementComponent::CommandConsole(FString Property, FString InValue, FString& OutValue)
{
  SGPropertyNode* node = PropertyManager->GetNode(TCHAR_TO_UTF8(*Property),false);
  if (node != NULL)
  {    
    //we skip setting values by using blank InValue.
    if (InValue != "")
    {
      node->setStringValue(TCHAR_TO_UTF8(*InValue));
    }
    OutValue = node->getStringValue();
  }
  ////check if property has READ(1) attribute
  //auto attribute = SGPropertyNode::Attribute(1);
  //if (! node->getAttribute(attribute))
  //{
  //  return;
  //}

}

//TODO, check if this is optimized, as we are using strings for convenience and we could probably cache the propertynode once we have it
void UJSBSimMovementComponent::CommandConsoleBatch(TArray<FString> Property, TArray<FString> InValue, TArray<FString>& OutValue)
{
  OutValue.SetNum(Property.Num());
  for (int i = 0; i < Property.Num(); i++)
  {
    SGPropertyNode* node = PropertyManager->GetNode(TCHAR_TO_UTF8(*(Property[i])),false);
    if (node != NULL)
    {
      //we skip setting values by using blank InValue.
      if (InValue[i] != "")
      {
        node->setStringValue(TCHAR_TO_UTF8(*InValue[i]));
      }
      OutValue[i] = node->getStringValue();
    }
  }
  
  ////check if property has READ(1) attribute
  //auto attribute = SGPropertyNode::Attribute(1);
  //if (! node->getAttribute(attribute))
  //{
  //  return;
  //}
}



void UJSBSimMovementComponent::LoadAircraft(bool ResetToDefaultSettings)
{
	UE_LOG(LogJSBSim, Display, TEXT("UJSBSimMovementComponent::LoadAircraft %s"), *AircraftModel);

	// It seems like we can only load the model once after having been initialized - So we have to Reinit JSBSim when changing the model.
	DeInitializeJSBSim();
	InitializeJSBSim();

	// LOCAL PATCH 5 (VENDORED.json): the derived airframe's XML is hashed AT
	// THE DOOR -- before JSBSim reads a byte of it -- and the load refused
	// when it is unreadable or is not the file the bridge was told to
	// expect: the host counterpart of core/control/derive.py verify_hashes.
	// A stock load (no AircraftRootOverride) is upstream's, unchanged.
	LoadedAircraftXmlSha256.Empty();
	bAircraftXmlRefused = false;
	if (!AircraftRootOverride.IsEmpty())
	{
		// The same root InitializeJSBSim handed JSBSim, so the file hashed is
		// the file JSBSim then reads.
		FString DoorRoot = FPaths::ConvertRelativePathToFull(AircraftRootOverride);
		FPaths::NormalizeDirectoryName(DoorRoot);
		const FString XmlPath = FPaths::Combine(DoorRoot, AircraftModel,
		                                        AircraftModel + TEXT(".xml"));
		TArray<uint8> XmlBytes;
		if (!FFileHelper::LoadFileToArray(XmlBytes, *XmlPath))
		{
			bAircraftXmlRefused = true;
			AircraftLoaded = false;
			UE_LOG(LogJSBSim, Error, TEXT("derived airframe XML '%s' cannot be read; not loaded"), *XmlPath);
			return;
		}
		LoadedAircraftXmlSha256 = JSBSimLocalPatch5::Sha256Hex(XmlBytes.GetData(), XmlBytes.Num());
		UE_LOG(LogJSBSim, Display, TEXT("aircraft XML '%s': sha256 %s at the door (expected %s)"),
		       *XmlPath, *LoadedAircraftXmlSha256,
		       ExpectedAircraftXmlSha256.IsEmpty() ? TEXT("none stated") : *ExpectedAircraftXmlSha256);
		if (!ExpectedAircraftXmlSha256.IsEmpty() &&
		    !LoadedAircraftXmlSha256.Equals(ExpectedAircraftXmlSha256, ESearchCase::IgnoreCase))
		{
			bAircraftXmlRefused = true;
			AircraftLoaded = false;
			UE_LOG(LogJSBSim, Error, TEXT("aircraft XML '%s' hashes to %s, not the expected %s; not loaded"),
			       *XmlPath, *LoadedAircraftXmlSha256, *ExpectedAircraftXmlSha256);
			return;
		}
	}

	AircraftLoaded = Exec->LoadModel(std::string(TCHAR_TO_UTF8(*AircraftModel)));

	if (!AircraftLoaded)
	{
		UE_LOG(LogJSBSim, Error, TEXT("Error while loading Model %s - Please check for typo or your configurations files"), *AircraftModel);
		return;
	}
	{
		UE_LOG(LogJSBSim, Display, TEXT("Model %s Loaded successfully !"), *AircraftModel);
	}

	// Do basic sanity checks 
	if (GroundReactions->GetNumGearUnits() <= 0)
	{
		UE_LOG(LogJSBSim, Error, TEXT("Error - Num Gear Units = %d. This is a very bad thing because with 0 gear units, the ground trimming routine will core dump"), GroundReactions->GetNumGearUnits());
		AircraftLoaded = false;
		return;
	}

	UpdateLocalTransforms();

    // The Aircraft model has changed - Reset the Tank and Gear properties that can have been overriden by the user. 
	if (ResetToDefaultSettings)
	{
		InitTankDefaultProperties();
		InitGearDefaultProperties();
	}

	InitEnginesCommandAndStates();
}

double UJSBSimMovementComponent::GetAGLevel(const FVector& StartECEFLocation, FVector& ECEFContactPoint, FVector& ECEFNormal)
{
  if (!GeoReferencingSystem || !GetWorld())
  {
    return 0.0;
  }

  // Get local Up vector at the query ECEF Location
  FTransform TangentTransform = GeoReferencingSystem->GetTangentTransformAtECEFLocation(StartECEFLocation);
  FVector Up = TangentTransform.TransformVector(FVector::ZAxisVector);

  // Compute the raycast Origin point
  FVector StartEngineLocation;
  GeoReferencingSystem->ECEFToEngine(StartECEFLocation, StartEngineLocation);
  FVector LineCheckStart = StartEngineLocation + AGLThresholdMeters * 100 * Up; // slightly above the starting point

  // Compute the raycast end point
  // Estimate raycast length - Altitude + 5% of ellipsoid radius in case of negative altitudes
  FVector LineCheckEnd = StartEngineLocation - (AircraftState.AltitudeASLFt * FEET_TO_METER + 0.05 * GeoReferencingSystem->GetGeographicEllipsoidMaxRadius()) * 100.0 * Up; 

  // Prepare collision query  
  FHitResult HitResult = FHitResult();
  static const FName LineTraceSingleName(TEXT("AGLevelLineTrace"));
  FCollisionQueryParams CollisionParams(LineTraceSingleName);
  CollisionParams.bTraceComplex = true;
  CollisionParams.AddIgnoredActor(Parent);

  FCollisionObjectQueryParams ObjectParams = FCollisionObjectQueryParams(ECC_WorldStatic);
  ObjectParams.AddObjectTypesToQuery(ECC_WorldDynamic);
  ObjectParams.AddObjectTypesToQuery(ECC_Pawn);
  ObjectParams.AddObjectTypesToQuery(ECC_Visibility);

  //DrawDebugLine(GetWorld(), LineCheckStart, LineCheckEnd , FColor::Blue, false, -1, 0, 3);

  // Do Query
  double HAT = 0.0;
  if (GetWorld()->LineTraceSingleByObjectType(HitResult, LineCheckStart, LineCheckEnd, ObjectParams, CollisionParams))
  {
    //DrawDebugLine(GetWorld(), HitResult.ImpactPoint, HitResult.ImpactPoint + HitResult.ImpactNormal*100.0, FColor::Orange, false, -1, 0, 3);

    FVector DirectionToImpact = HitResult.ImpactPoint - StartEngineLocation;
    HAT = FVector::Dist(StartEngineLocation, HitResult.ImpactPoint) / 100.0 * -FMath::Sign(DirectionToImpact.Dot(Up)); // JSBSim expect a signed distance. Consider that! 
    GeoReferencingSystem->EngineToECEF(HitResult.ImpactPoint, ECEFContactPoint);

    // Georeferencing don't provide tools to transform a direction, or access the worldToECEF Matrix - Do it by hand
    FVector ECEFNormalEnd;
    GeoReferencingSystem->EngineToECEF(HitResult.ImpactPoint + HitResult.ImpactNormal * 100.0, ECEFNormalEnd);
    ECEFNormal = ECEFNormalEnd - ECEFContactPoint;
    ECEFNormal.Normalize();
  }
  else
  {
    ECEFContactPoint = FVector();
    ECEFNormal = FVector::ZAxisVector;
  }
  return HAT;
}

////// ActorComponent overridables
void UJSBSimMovementComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	double Start = FPlatformTime::Seconds();

	if (AircraftLoaded)
	{
		if (AircraftState.Crashed)
		{
			// TODO - Send event
			UE_LOG(LogJSBSim, Display, TEXT("Aircraft crashed..."));
		}
		else
		{

      //calculate sim rate to be 120hz independent of game tick rate(Pseudo fixed rate, dev/user needs to set game to a fixed rate too)
      simDtime = 120.f/(1.f / DeltaTime);
      remainder = remainder + fmodf(simDtime,1);
      simloops = truncf(simDtime) + truncf(remainder);
      remainder = fmodf(remainder,1);

      //jsbsim recommends to step sim at 120hz, eg 1/120 = 0.0083..
      Exec->Setdt(0.008333333333333333);

            // Send Commands and State to JSBSim
			CopyToJSBSim();
			
      //step sim x times per game tick
      for (int i = 0; i < simloops; i++)
      {
        Exec->Run();
      }

            // The CG location in the reference frame can vary over time, for instance when tanks get empty... 
            // Theoretically, we should update the local transforms. But maybe it's overkill to do it each frame...
            UpdateLocalTransforms(); 

            // Get the results from JSBSim
			CopyFromJSBSim();

            // Basic debugging string and symbols
			if (DrawDebug)
			{
				DrawDebugMessage();
				DrawDebugObjects();
			}

            // Transform the aircraft coordinates from ECEF Frame to UE Frame, using the georeferencing plugin.
			if (Parent)
			{
				// Computes Rotation in engine frame
				FTransform ENUTransform = GeoReferencingSystem->GetTangentTransformAtECEFLocation(AircraftState.ECEFLocation);
				FRotator LocalUERotation(AircraftState.LocalEulerAngles);
				LocalUERotation.Yaw = LocalUERotation.Yaw - 90.0; // JSBSim heading is aero heading (0 at north). We have to remove 90 because in UE, 0 is pointing east. 
				FQuat EngineRotationQuat = ENUTransform.TransformRotation(LocalUERotation.Quaternion());
				
				FMatrix EngineRotation;
				EngineRotationQuat.ToMatrix(EngineRotation);
				FVector CGOffsetWorld = EngineRotation.TransformPosition(CGLocalPosition);

				// Computes Location in engine frame
				FVector CGWorldPosition;
				GeoReferencingSystem->ECEFToEngine(AircraftState.ECEFLocation, CGWorldPosition);
				FVector EngineLocation = CGWorldPosition - CGOffsetWorld;

                // Update the ForwardHorizontal vector used for the PFD
				AircraftState.UEForwardHorizontal = ENUTransform.TransformVector(ECEFForwardHorizontal);

				// Apply the transform to the Parent actor			
				Parent->SetActorLocationAndRotation(EngineLocation, EngineRotationQuat);
			}
		}
	}

    // Get some stats - TODO - Use the UE Stats system
	double End = FPlatformTime::Seconds();
    TickTime = (End - Start) * 1000.0;
}

void UJSBSimMovementComponent::BeginDestroy()
{
	Super::BeginDestroy();

    // Make sure we destroy JSBSim too
	DeInitializeJSBSim();
}

void UJSBSimMovementComponent::BeginPlay()
{
	Super::BeginPlay();

    // Init local variables from Level Objects
	Parent = GetOwner();

    // A GeoReferencingSystem Actor is mandatory! 
	if (!GeoReferencingSystem)
	{
		GeoReferencingSystem = AGeoReferencingSystem::GetGeoReferencingSystem(GetWorld());

		if (!GeoReferencingSystem)
		{
			UE_LOG(LogJSBSim, Error, TEXT("Impossible to use a UJSBSimMovementComponent without a GeoReferencingSystem."));
		}
	}

	if (Parent)
	{
		Parent->GetRootComponent()->SetMobility(EComponentMobility::Movable);
		LoadAircraft(false); // Start with a Fresh JSBSim object, but potentially with overridden properties
		PrepareJSBSim();
	}
}

void UJSBSimMovementComponent::OnRegister()
{
	Super::OnRegister();

	if (!GeoReferencingSystem)
	{
		GeoReferencingSystem = AGeoReferencingSystem::GetGeoReferencingSystem(GetWorld());

		if (!GeoReferencingSystem)
		{
			UE_LOG(LogJSBSim, Error, TEXT("Impossible to use a UJSBSimMovementComponent without a GeoReferencingSystem."));
		}
	}
}

/////////// JSBSim Protected methods

void UJSBSimMovementComponent::InitializeJSBSim()
{
	if (!JSBSimInitialized)
	{
		// Construct the JSBSim FDM
		Exec = new JSBSim::FGFDMExec();

		// Get pointers to main components
		Atmosphere = Exec->GetAtmosphere();
		Winds = Exec->GetWinds();
		FCS = Exec->GetFCS();
		MassBalance = Exec->GetMassBalance();
		Propulsion = Exec->GetPropulsion();
		Aircraft = Exec->GetAircraft();
		Propagate = Exec->GetPropagate();
		Auxiliary = Exec->GetAuxiliary();
		Inertial = Exec->GetInertial();
		Inertial->SetGroundCallback(new UEGroundCallback(this)); // Register ground callback.
		Aerodynamics = Exec->GetAerodynamics();
		GroundReactions = Exec->GetGroundReactions();
		Accelerations = Exec->GetAccelerations();
		IC = Exec->GetIC();
		PropertyManager = Exec->GetPropertyManager();

        // Initialize the Models location, relatively to this plugin

		// Get the base directory of this plugin
		FString BaseDir = IPluginManager::Get().FindPlugin("JSBSimFlightDynamicsModel")->GetBaseDir();
		// Add on the relative location of the third party dll and load it
		FString RootDirRelative = FPaths::Combine(*BaseDir, TEXT("Resources/JSBSim"));
		const FString& RootDir = IFileManager::Get().ConvertToAbsolutePathForExternalAppForRead(*RootDirRelative);
		UE_LOG(LogJSBSim, Display, TEXT("Initializing JSBSimFlightDynamicsModel using Data in '%s'"), *RootDir);

		// Set data paths...
		FString AircraftPath(TEXT("aircraft"));
		FString EnginePath(TEXT("engine"));
		FString SystemPath(TEXT("systems"));

		Exec->SetRootDir(SGPath(TCHAR_TO_UTF8(*RootDir)));
		Exec->SetAircraftPath(SGPath(TCHAR_TO_UTF8(*AircraftPath)));
		// LOCAL PATCH 5 (VENDORED.json): upstream hard-codes the aircraft
		// root above; a derived airframe lives outside the plugin (the
		// repository's build/aircraft). An absolute path passes through
		// FGFDMExec::GetFullPath unchanged; engines and systems still
		// resolve from the plugin's staged data, as the headless host
		// resolves a derived airframe's from the stock root.
		if (!AircraftRootOverride.IsEmpty())
		{
			FString OverrideRoot = FPaths::ConvertRelativePathToFull(AircraftRootOverride);
			FPaths::NormalizeDirectoryName(OverrideRoot);
			Exec->SetAircraftPath(SGPath(TCHAR_TO_UTF8(*OverrideRoot)));
			UE_LOG(LogJSBSim, Display, TEXT("aircraft root overridden: '%s'"), *OverrideRoot);
		}
		Exec->SetEnginePath(SGPath(TCHAR_TO_UTF8(*EnginePath)));
		Exec->SetSystemsPath(SGPath(TCHAR_TO_UTF8(*SystemPath)));
		// Prepare Initial Conditions
		TrimNeeded = true;

		// Base setup done so far. The other part of initial setup will be done on begin play, in InitJSBSim. 
        JSBSimInitialized = true;
	}
}

void UJSBSimMovementComponent::PrepareJSBSim()
{
	UE_LOG(LogJSBSim, Display, TEXT("PrepareJSBSim - Setting Initial Conditiond and computing initial state"));

	// The Aircraft should have been loaded first
	if (!AircraftLoaded)
	{
		return;
	}

    // Reset the current Aircraft State
    AircraftState.Reset();

	// First, consider the aircraft Transform in UE to define the Location and Orientation in JSBSim
	FGeographicCoordinates GeographicCoordinates;
	if (Parent)
	{
		// Get CG location in Geographic
		FVector CGWorldPosition = Parent->GetTransform().TransformPosition(CGLocalPosition);
		GeoReferencingSystem->EngineToGeographic(CGWorldPosition, GeographicCoordinates);

		// Computes Rotation in engine frame
		FTransform ENUTransform = GeoReferencingSystem->GetTangentTransformAtGeographicLocation(GeographicCoordinates);
		FQuat LocalECEFRotation = ENUTransform.InverseTransformRotation(Parent->GetActorQuat());
		FRotator PsiThetaPhi = LocalECEFRotation.Rotator();

		// Set it as initial conditions
		IC->SetLongitudeDegIC(GeographicCoordinates.Longitude); 
		IC->SetGeodLatitudeDegIC(GeographicCoordinates.Latitude);
		IC->SetAltitudeASLFtIC(GeographicCoordinates.Altitude * METER_TO_FEET);
		IC->SetPhiDegIC(PsiThetaPhi.Roll);
		IC->SetPsiDegIC(PsiThetaPhi.Yaw + 90);
		IC->SetThetaDegIC(PsiThetaPhi.Pitch);
	}


	// Init our commands from the initial state
	Commands.Elevator = FCS->GetDeCmd();
	Commands.Aileron = FCS->GetDaCmd();
	Commands.Rudder = FCS->GetDrCmd();
	Commands.PitchTrim = FCS->GetPitchTrimCmd();
	Commands.YawTrim = FCS->GetYawTrimCmd();
	Commands.RollTrim = FCS->GetRollTrimCmd();
	// TODO - Others commands ?

	// Atmosphere
	if (ControlFDMAtmosphere)
	{
		Atmosphere->SetTemperature(TemperatureCelsius, GeographicCoordinates.Altitude * METER_TO_FEET, JSBSim::FGAtmosphere::eCelsius);
		Atmosphere->SetPressureSL(JSBSim::FGAtmosphere::ePascals, PressureSeaLevelhPa * 100.0);
		Winds->SetTurbType(JSBSim::FGWinds::ttNone);
		Winds->SetTurbGain(0.0);
		Winds->SetTurbRate(0.0);
		Winds->SetWindspeed20ft(0.0);
		Winds->SetProbabilityOfExceedence(0.0);
	}
	
	// Wind Speed
	IC->SetWindDirDegIC(WindHeading);
	IC->SetWindMagKtsIC(WindIntensityKts);
	
	// Aircraft Speed
	IC->SetVcalibratedKtsIC(InitialCalibratedAirSpeedKts);


	// Aircraft State
	// Flaps position
    Commands.Flap = FlapPositionAtStart;
	FCS->SetDfPos(ofNorm, FlapPositionAtStart);

	// Gear position
	if (bStartWithGearDown)
	{
		FCS->SetGearPos(1.0);
	}
	else
	{
		FCS->SetGearPos(0.0);
	}

    // Run IC to pre-initialize the JSBSim Initial Conditions for the model
	CopyToJSBSim();
	Exec->RunIC();
	UpdateLocalTransforms();

	if (bStartWithEngineRunning)
	{
		Propulsion->InitRunning(-1);

		int32 EngineCount = EngineCommands.Num();
		for (int32 i = 0; i < EngineCount; i++)
		{
			EngineCommands[i].Throttle = 0.0;
			// LOCAL PATCH (VENDORED.json): upstream's 1.0 kills a piston
			// engine at altitude; the card carries a sustainable mixture.
			// Written to the FCS HERE as well, because the trim below runs
			// before any EngineCommands application and would otherwise
			// solve with whatever mixture InitRunning left.
			EngineCommands[i].Mixture = InitialMixture;
			FCS->SetMixtureCmd(i, InitialMixture);
			FCS->SetMixturePos(i, InitialMixture);
            EngineCommands[i].Magnetos = EMagnetosMode::Both;
			EngineCommands[i].Running = true;
		}
	}

	// LOCAL PATCH 6 (VENDORED.json): the pre-trim batch, AFTER the RunIC
	// above and BEFORE the trim below -- the only place in upstream's
	// BeginPlay where the bridge's stated day, loading and icing neutral
	// values can reach the trim solver. Each write is followed by a
	// re-latch (RunIC: FGMassBalance and the atmosphere recompute at the ICs
	// without advancing time) where PreTrimRelatchAfter says so, exactly as
	// the headless providers re-latch; the read-back list is then sampled
	// (inertia/cg-x-in before the trim is the loading's contract). A
	// property the model does not declare is not written and is listed in
	// PreTrimMissing for the bridge to refuse by name. Empty: a no-op.
	PreTrimReadValues.Reset();
	PreTrimMissing.Reset();
	if (PreTrimProperties.Num() > 0)
	{
		for (int32 Write = 0; Write < PreTrimProperties.Num(); Write++)
		{
			SGPropertyNode* node = PropertyManager->GetNode(TCHAR_TO_UTF8(*PreTrimProperties[Write]), false);
			if (node == NULL || !PreTrimValues.IsValidIndex(Write))
			{
				PreTrimMissing.Add(PreTrimProperties[Write]);
				UE_LOG(LogJSBSim, Error, TEXT("pre-trim batch: '%s' is not declared by this model; not written"),
				       *PreTrimProperties[Write]);
				continue;
			}
			node->setStringValue(TCHAR_TO_UTF8(*PreTrimValues[Write]));
			if (PreTrimRelatchAfter.IsValidIndex(Write) && PreTrimRelatchAfter[Write])
			{
				// JSBSim keeps the initial speed as TRUE airspeed, converted
				// from the requested CAS with the atmosphere of the moment:
				// after a stated day the same TAS is another CAS (measured
				// headless: 100 kt asked at +30 degC flew 95.83 kt). The CAS
				// is re-stated in its own terms before every re-latch, as
				// core/fdm/fdm.py relatch_initial_conditions re-states
				// ic/vc-kts, so both hosts trim at the card's airspeed.
				IC->SetVcalibratedKtsIC(InitialCalibratedAirSpeedKts);
				Exec->RunIC();
			}
		}
		// The CG may have moved: keep the actor-frame CG the plugin places
		// the aircraft by in step with FGMassBalance.
		UpdateLocalTransforms();
		for (const FString& ReadName : PreTrimReadProperties)
		{
			FString ReadValue;
			SGPropertyNode* node = PropertyManager->GetNode(TCHAR_TO_UTF8(*ReadName), false);
			if (node != NULL)
			{
				ReadValue = node->getStringValue();
			}
			PreTrimReadValues.Add(ReadValue);
		}
		UE_LOG(LogJSBSim, Display, TEXT("pre-trim batch: %d writes after RunIC, before the trim (%d missing)"),
		       PreTrimProperties.Num(), PreTrimMissing.Num());
	}

	if (TrimNeeded)
	{
		const JSBSim::FGLocation& cart = IC->GetPosition();
		//double cart_pos[3], contact[3], d[3], vel[3], agl;
		// Make sure the ground below is loaded... Not needed in our case...
		//update_ground_cache(cart, cart_pos, 0.01);

		// Get Above Ground Level -- TODO
		//get_agl_ft(fdmex->GetSimTime(), cart_pos, SG_METER_TO_FEET * 2, contact, d, vel, d, &agl);
		double terrain_elevation = 0;
		//double terrain_alt = sqrt(contact[0] * contact[0] + contact[1] * contact[1] + contact[2] * contact[2]) - cart.GetSeaLevelRadius();

		//UE_LOG(LogJSBSim, Display, TEXT("Ready to trim, terrain elevation is: %f"), terrain_elevation);
		double vel[3] = {0,0,0};

		if (StartOnGround) {
			FGColumnVector3 gndVelNED = cart.GetTec2l() * FGColumnVector3(vel[0], vel[1], vel[2]);
			IC->SetVNorthFpsIC(gndVelNED(1));
			IC->SetVEastFpsIC(gndVelNED(2));
			IC->SetVDownFpsIC(gndVelNED(3));
		}
		DoTrim();
		TrimNeeded = false;
	}

    // Aircraft Trim done - Get result state
	CopyFromJSBSim();
}

void UJSBSimMovementComponent::DeInitializeJSBSim()
{
	if (JSBSimInitialized)
	{
		UE_LOG(LogJSBSim, Display, TEXT("DeInitializeJSBSim"));

		if (Exec)
		{
			delete Exec;
			Exec = nullptr;

			Atmosphere = nullptr;
			Winds = nullptr;
			FCS = nullptr;
			MassBalance = nullptr;
			Propulsion = nullptr;
			Aircraft = nullptr;
			Propagate = nullptr;
			Auxiliary = nullptr;
			Inertial = nullptr;
			Aerodynamics = nullptr;
			GroundReactions = nullptr;
			Accelerations = nullptr;
			IC = nullptr;
		}

		JSBSimInitialized = false;
	}
}

void UJSBSimMovementComponent::CopyToJSBSim()
{
	// Basic flight controls
	FCS->SetDaCmd(Commands.Aileron);
	FCS->SetRollTrimCmd(Commands.RollTrim);
	FCS->SetDeCmd(Commands.Elevator);
	FCS->SetPitchTrimCmd(Commands.PitchTrim);
	FCS->SetDrCmd(-Commands.Rudder); // Rudder
	FCS->SetDsCmd(Commands.Rudder); // Steering
	FCS->SetYawTrimCmd(-Commands.YawTrim);
	FCS->SetDfCmd(Commands.Flap);
	FCS->SetDsbCmd(Commands.SpeedBrake);
	FCS->SetDspCmd(Commands.Spoiler);
	  
	// Gears and Brake controls
	FCS->SetLBrake(FMath::Max(Commands.LeftBrake, Commands.ParkingBrake));
	FCS->SetRBrake(FMath::Max(Commands.RightBrake, Commands.ParkingBrake));
	FCS->SetCBrake(FMath::Max(Commands.CenterBrake, Commands.ParkingBrake));
	FCS->SetGearCmd(Commands.GearDown); 

	ApplyEnginesCommands(); 

	// TODO - Update atmosphere
/*	Atmosphere->SetTemperature(temperature->getDoubleValue(), get_Altitude(), FGAtmosphere::eCelsius);
	Atmosphere->SetPressureSL(FGAtmosphere::eInchesHg, pressureSL->getDoubleValue());

	Winds->SetTurbType((FGWinds::tType)TURBULENCE_TYPE_NAMES[turbulence_model->getStringValue()]);
	switch (Winds->GetTurbType()) {
	case FGWinds::ttStandard:
	case FGWinds::ttCulp: {
		double tmp = turbulence_gain->getDoubleValue();
		Winds->SetTurbGain(tmp * tmp * 100.0);
		Winds->SetTurbRate(turbulence_rate->getDoubleValue());
		break;
	}
	case FGWinds::ttMilspec:
	case FGWinds::ttTustin: {
		// milspec turbulence: 3=light, 4=moderate, 6=severe turbulence
		// turbulence_gain normalized: 0: none, 1/3: light, 2/3: moderate, 3/3: severe
		double tmp = turbulence_gain->getDoubleValue();
		Winds->SetProbabilityOfExceedence(
			SGMiscd::roundToInt(TurbulenceSeverityTable.GetValue(tmp))
		);
		Winds->SetWindspeed20ft(ground_wind->getDoubleValue());
		break;
	}

	default:
		break;
	}

	Winds->SetWindNED(-wind_from_north->getDoubleValue(),
		-wind_from_east->getDoubleValue(),
		-wind_from_down->getDoubleValue()); 
*/

	CopyTankPropertiesToJSBSim();
	CopyGearPropertiesToJSBSim();
}

void UJSBSimMovementComponent::CopyFromJSBSim()
{
	// Collect JSBSim data
	Propagate->DumpState();
	
	// Keep Former Location in ECEF
	FVector FormerECEFLocation = AircraftState.ECEFLocation;

	// Get Aircraft forward vector in local (ECEF tangent) space. 
	// TODO - IDK if for the horizon indicator I should use the forward vector or the aircraft speed. 
	// Maybe the aircraft speed would include some kind of lateral slip ---> May one expert fix it if needed...
	JSBSim::FGColumnVector3 ForwardLocal = Propagate->GetTb2l() * JSBSim::FGColumnVector3(1, 0, 0);
	ECEFForwardHorizontal = FVector(ForwardLocal(2), -ForwardLocal(1), 0);

	// Update Moving part state
	AircraftState.ElevatorPosition = FCS->GetDePos(JSBSim::ofDeg);
	AircraftState.LeftAileronPosition = FCS->GetDaLPos(JSBSim::ofDeg);
	AircraftState.RightAileronPosition = FCS->GetDaRPos(JSBSim::ofDeg);
	AircraftState.RudderPosition = -1 * FCS->GetDrPos(JSBSim::ofDeg);
	AircraftState.FlapPosition = FCS->GetDfPos(JSBSim::ofDeg);
	AircraftState.SpeedBrakePosition = FCS->GetDsbPos(JSBSim::ofDeg);
	AircraftState.SpoilersPosition = FCS->GetDspPos(JSBSim::ofDeg);

	// Speed
	AircraftState.CalibratedAirSpeedKts = Auxiliary->GetVcalibratedKTS();
	AircraftState.GroundSpeedKts = Auxiliary->GetVground() * FEET_PER_SEC_TO_KNOT;
	AircraftState.TotalVelocityKts = Auxiliary->GetVt() * FEET_PER_SEC_TO_KNOT;
	AircraftState.VelocityNEDfps.Set(Propagate->GetVel(JSBSim::FGJSBBase::eNorth), Propagate->GetVel(JSBSim::FGJSBBase::eEast), -Propagate->GetVel(JSBSim::FGJSBBase::eDown));
	AircraftState.AltitudeASLFt = Propagate->GetAltitudeASL();
	AircraftState.AltitudeRateFtps = Propagate->Gethdot();;
	AircraftState.StallWarning = Aerodynamics->GetStallWarn();

	// Transformation
	JSBSim::FGLocation LocationVRP = Propagate->GetLocation();
	AircraftState.ECEFLocation = FVector(LocationVRP(1), LocationVRP(2), LocationVRP(3)) * FEET_TO_METER;
	AircraftState.Latitude = LocationVRP.GetGeodLatitudeDeg();
	AircraftState.Longitude = LocationVRP.GetLongitudeDeg();
	AircraftState.LocalEulerAngles.Yaw = FMath::RadiansToDegrees(Propagate->GetEuler(JSBSim::FGJSBBase::ePsi));
	AircraftState.LocalEulerAngles.Pitch = FMath::RadiansToDegrees(Propagate->GetEuler(JSBSim::FGJSBBase::eTht));
	AircraftState.LocalEulerAngles.Roll = FMath::RadiansToDegrees(Propagate->GetEuler(JSBSim::FGJSBBase::ePhi));
	AircraftState.EulerRates.Set(Auxiliary->GetEulerRates(JSBSim::FGJSBBase::ePhi), Auxiliary->GetEulerRates(JSBSim::FGJSBBase::eTht), Auxiliary->GetEulerRates(JSBSim::FGJSBBase::ePsi));
	AircraftState.AltitudeAGLFt = Propagate->GetDistanceAGL();
	// force a sim crashed if crashed (altitude AGL < 0)
	if (AircraftState.AltitudeAGLFt < -10.0 || AircraftState.AltitudeASLFt < -10.0) {
		Exec->SuspendIntegration();
		AircraftState.Crashed = true;
	  AircraftCrashed.Broadcast();
	}
	
	// Copy the fuel levels from JSBSim if fuel
	// freeze not enabled.
	CopyTankPropertiesFromJSBSim();
	CopyGearPropertiesFromJSBSim();
	GetEnginesStates();
}

/////////// JSBSim Private methods
void UJSBSimMovementComponent::DoTrim()
{
	JSBSim::FGTrim* Trim;

	if (StartOnGround)
	{
		Trim = new JSBSim::FGTrim(Exec, JSBSim::tGround);
	}
	else {
		Trim = new JSBSim::FGTrim(Exec, JSBSim::tFull);
	}

	if (!Trim->DoTrim()) 
	{
		Trim->Report();
		Trim->TrimStats();

        UE_LOG(LogJSBSim, Error, TEXT("Trim Failed!!!"));
	}
	else 
	{
		Trimmed = true;
	}
	delete Trim;

	Commands.PitchTrim = FCS->GetPitchTrimCmd();
	Commands.Aileron = FCS->GetDaCmd();
	Commands.Rudder = -FCS->GetDrCmd(); // TODO - Why this minus sign? Is it from FlightGear logic ?

	UE_LOG(LogJSBSim, Display, TEXT("Trim Complete"));
}

void UJSBSimMovementComponent::UpdateLocalTransforms()
{
    if (MassBalance == nullptr || Aircraft == nullptr || GroundReactions == nullptr)
      return;

	// Structural Frame To Actor Frame
	FMatrix StructuralToActorMatrix(FMatrix::Identity);
	StructuralToActorMatrix.SetAxis(0, FVector(-1, 0, 0));
	StructuralToActorMatrix.SetAxis(1, FVector(0, 1, 0));
	StructuralToActorMatrix.SetAxis(2, FVector(0, 0, 1));
	StructuralToActorMatrix.SetOrigin(StructuralFrameOrigin);
	StructuralToActor.SetFromMatrix(StructuralToActorMatrix);

	// Get Gravity Center
	JSBSim::FGColumnVector3 CGLocationStructural = MassBalance->StructuralToBody(JSBSim::FGColumnVector3()) * FEET_TO_CENTIMETER;
	CGLocalPosition = StructuralToActor.TransformPosition(FVector(CGLocationStructural(1), CGLocationStructural(2), CGLocationStructural(3)));

	// Body Frame to Actor Frame
	FMatrix BodyToActorMatrix(FMatrix::Identity);
	BodyToActorMatrix.SetAxis(0, FVector(1, 0, 0));
	BodyToActorMatrix.SetAxis(1, FVector(0, 1, 0));
	BodyToActorMatrix.SetAxis(2, FVector(0, 0, -1));
	BodyToActorMatrix.SetOrigin(CGLocalPosition);
	BodyToActor.SetFromMatrix(BodyToActorMatrix);

	// Eye Position
	JSBSim::FGColumnVector3 EPLocationStructural = Aircraft->GetXYZep() * INCH_TO_CENTIMETER;
	EPLocalPosition = StructuralToActor.TransformPosition(FVector(EPLocationStructural(1), EPLocationStructural(2), EPLocationStructural(3)));

	// Visual Reference Position
	JSBSim::FGColumnVector3 VRPLocationStructural = Aircraft->GetXYZvrp() * INCH_TO_CENTIMETER;
	VRPLocalPosition = StructuralToActor.TransformPosition(FVector(VRPLocationStructural(1), VRPLocationStructural(2), VRPLocationStructural(3)));

    // Gear Locations
    for (int i = 0; i < GroundReactions->GetNumGearUnits(); i++)
    {
      std::shared_ptr<JSBSim::FGLGear> Gear = GroundReactions->GetGearUnit(i);
      if ((int32)i < Gears.Num())
      {
        JSBSim::FGColumnVector3 GearBodyLocation = Gear->GetBodyLocation() * FEET_TO_CENTIMETER;
        Gears[i].RelativeLocation = BodyToActor.TransformPosition(FVector(GearBodyLocation(1), GearBodyLocation(2), GearBodyLocation(3)));
      }
    }
}

// Gears
void UJSBSimMovementComponent::InitGearDefaultProperties()
{
	uint32 GearsCount = GroundReactions->GetNumGearUnits();
	Gears.Empty();
	if (GearsCount > 0)
	{
		Gears.AddZeroed(GearsCount);

		for (unsigned int i = 0; i < GearsCount; i++)
		{
			std::shared_ptr<JSBSim::FGLGear> Gear = GroundReactions->GetGearUnit(i); // TODO - Test indices

			Gears[i].NormalizedPosition = Gear->GetGearUnitPos();
			Gears[i].IsBogey = Gear->IsBogey();
			Gears[i].HasWeightOnWheel = Gear->GetWOW();
			Gears[i].WheelRollLinearVelocityMetersPerSec = Gear->GetWheelRollVel() * FEET_TO_METER;
			Gears[i].IsUp = Gear->GetGearUnitUp();
			Gears[i].IsDown = Gear->GetGearUnitDown();
			Gears[i].Name = FString(Gear->GetName().c_str());
		}
	}
}

void UJSBSimMovementComponent::CopyGearPropertiesToJSBSim()
{
	// TODO - What can be changed from the default values? 
    // Maybe the initial extension, but not sure it can be done...
}

void UJSBSimMovementComponent::CopyGearPropertiesFromJSBSim()
{
	for (int i = 0; i < GroundReactions->GetNumGearUnits(); i++)
	{
		std::shared_ptr<JSBSim::FGLGear> Gear = GroundReactions->GetGearUnit(i);
		if ((int32)i < Gears.Num())
		{
			Gears[i].NormalizedPosition = Gear->GetGearUnitPos();
			Gears[i].IsBogey = Gear->IsBogey();
			Gears[i].HasWeightOnWheel = Gear->GetWOW();
			Gears[i].WheelRollLinearVelocityMetersPerSec = Gear->GetWheelRollVel() * FEET_TO_METER;
			Gears[i].IsUp = Gear->GetGearUnitUp();
			Gears[i].IsDown = Gear->GetGearUnitDown();

			JSBSim::FGColumnVector3 GearBodyLocation = Gear->GetBodyLocation() * FEET_TO_CENTIMETER;
			Gears[i].RelativeLocation = BodyToActor.TransformPosition(FVector(GearBodyLocation(1), GearBodyLocation(2), GearBodyLocation(3)));

			JSBSim::FGColumnVector3 GearBodyForce = Gear->GetBodyForces() * FEET_TO_CENTIMETER;
			Gears[i].Force = BodyToActor.TransformPosition(FVector(GearBodyForce(1), GearBodyForce(2), GearBodyForce(3)));
		}
	}
}

// Tanks
void UJSBSimMovementComponent::InitTankDefaultProperties()
{
	// Set initial fuel levels if overridden by the user.
	uint32 TanksCount = Propulsion->GetNumTanks();
	Tanks.Empty();
	if (TanksCount > 0)
	{
		Tanks.AddZeroed(TanksCount);
		for (unsigned int i = 0; i < TanksCount; i++)
		{
			std::shared_ptr<JSBSim::FGTank> Tank = Propulsion->GetTank(i);

			Tanks[i].FuelDensityPoundsPerGallon = Tank->GetDensity();
			Tanks[i].ContentGallons = Tank->GetContentsGallons();
			Tanks[i].CapacityGallons = Tank->GetCapacityGallons();
			Tanks[i].FillPercentage = Tank->GetPctFull();
			Tanks[i].TemperatureCelcius = Tank->GetTemperature_degC();
		}
	}
}

void UJSBSimMovementComponent::CopyTankPropertiesToJSBSim()
{
	for (unsigned i = 0; i < Propulsion->GetNumTanks(); i++)
	{
		std::shared_ptr<JSBSim::FGTank> tank = Propulsion->GetTank(i);

		if ((int32)i < Tanks.Num())
		{
			FTank UETank = Tanks[i];
			double fuelDensity = UETank.FuelDensityPoundsPerGallon;

			if (fuelDensity < 0.1)
				fuelDensity = 6.0; // Use average fuel value

			// Only editable properties
			tank->SetDensity(fuelDensity);
			tank->SetContentsGallons(UETank.ContentGallons);
		}
	}
}

void UJSBSimMovementComponent::CopyTankPropertiesFromJSBSim()
{
	FuelFreeze = Propulsion->GetFuelFreeze();
	for (unsigned int i = 0; i < Propulsion->GetNumTanks(); i++)
	{
		std::shared_ptr<JSBSim::FGTank> Tank = Propulsion->GetTank(i);

		if ((int32)i < Tanks.Num())
		{
			Tanks[i].FuelDensityPoundsPerGallon = Tank->GetDensity();
			Tanks[i].ContentGallons = Tank->GetContentsGallons();
			Tanks[i].CapacityGallons = Tank->GetCapacityGallons();
			Tanks[i].FillPercentage = Tank->GetPctFull();
			Tanks[i].TemperatureCelcius = Tank->GetTemperature_degC();
		}
	}
}


// Engines
void UJSBSimMovementComponent::InitEnginesCommandAndStates()
{
	EngineCommands.Empty();
	EngineStates.Empty();

	uint32 EngineCount = Propulsion->GetNumEngines();
	if (EngineCount > 0)
	{
		// Allocate UE equivalent structures
		EngineCommands.AddZeroed(EngineCount);
		EngineStates.AddZeroed(EngineCount);

		// Apply default properties
		// TODO - Not sure there are to apply. it will be done by command/states
	}
}

void UJSBSimMovementComponent::ApplyEnginesCommands()
{
	// Global to all engines
	Propulsion->SetFuelFreeze(FuelFreeze);

	// For each engine
	int32 EngineCount = EngineCommands.Num();
	for (int32 i = 0; i < EngineCount; i++)
	{
		FEngineCommand EngineCommand = EngineCommands[i];

		// Global FCS Commands
		FCS->SetThrottleCmd(i, EngineCommand.Throttle);
		FCS->SetMixtureCmd(i, EngineCommand.Mixture);
		FCS->SetPropAdvanceCmd(i, EngineCommand.PropellerAdvance);
		FCS->SetFeatherCmd(i, EngineCommand.PropellerFeather);

		// Common FGEngine code block
		std::shared_ptr < JSBSim::FGEngine> CommonEngine = Propulsion->GetEngine(i);
		CommonEngine->SetStarter(EngineCommand.Starter);
		CommonEngine->SetRunning(EngineCommand.Running);

		switch (Propulsion->GetEngine(i)->GetType())
		{
		case JSBSim::FGEngine::etPiston:
		{
			// FGPiston code block
			std::shared_ptr < JSBSim::FGPiston> PistonEngine = std::static_pointer_cast<JSBSim::FGPiston>(Propulsion->GetEngine(i));
			PistonEngine->SetMagnetos((int)EngineCommand.Magnetos);
			break;
		}
		case JSBSim::FGEngine::etTurbine:
		{
			// FGTurbine code block
			std::shared_ptr < JSBSim::FGTurbine> TurbineEngine = std::static_pointer_cast<JSBSim::FGTurbine>(Propulsion->GetEngine(i));
			TurbineEngine->SetReverse(EngineCommand.Reverse);
			TurbineEngine->SetCutoff(EngineCommand.CutOff);
			TurbineEngine->SetIgnition(EngineCommand.Ignition);
			TurbineEngine->SetAugmentation(EngineCommand.Augmentation);
			TurbineEngine->SetInjection(EngineCommand.Injection);
			break;
		}
		case JSBSim::FGEngine::etRocket:
		{
			// FGRocket code block
			// FGRocket* RocketEngine = (FGRocket*)Propulsion->GetEngine(i);
			break;
		}
		case JSBSim::FGEngine::etTurboprop:
		{
			// FGTurboProp code block
			std::shared_ptr < JSBSim::FGTurboProp> TurboPropEngine = std::static_pointer_cast<JSBSim::FGTurboProp>(Propulsion->GetEngine(i));
			TurboPropEngine->SetReverse(EngineCommand.Reverse);
			TurboPropEngine->SetCutoff(EngineCommand.CutOff);
			TurboPropEngine->SetGeneratorPower(EngineCommand.GeneratorPower);
			TurboPropEngine->SetCondition(EngineCommand.Condition);
			break;
		}
		default:
			break;
		}
	}
}

void UJSBSimMovementComponent::GetEnginesStates()
{
	// For each engine
	int32 EngineCount = EngineStates.Num();
	for (int32 i = 0; i < EngineCount; i++)
	{
		std::shared_ptr < JSBSim::FGEngine> Engine = Propulsion->GetEngine(i);

		EngineStates[i].EngineType = (EEngineType) Engine->GetType();
		EngineStates[i].Starter = Engine->GetStarter();
		EngineStates[i].Running = Engine->GetRunning();
		EngineStates[i].Thrust = Engine->GetThrust();
		EngineStates[i].EngineRPM = Engine->GetThruster()->GetEngineRPM();

		switch (Engine->GetType())
		{
		case JSBSim::FGEngine::etPiston:
		{
			// TODO
			// FGPiston code block
            std::shared_ptr < JSBSim::FGPiston> PistonEngine = std::static_pointer_cast<JSBSim::FGPiston>(Engine);
            EngineStates[i].Magnetos = (EMagnetosMode) PistonEngine->GetMagnetos();
			break;
		}
		case JSBSim::FGEngine::etTurbine:
		{
			// TODO
			// FGTurbine code block
			std::shared_ptr < JSBSim::FGTurbine> TurbineEngine = std::static_pointer_cast<JSBSim::FGTurbine>(Engine);
			EngineStates[i].N1 = TurbineEngine->GetN1();
			EngineStates[i].N2 = TurbineEngine->GetN2();
			EngineStates[i].Augmentation = TurbineEngine->GetAugmentation();
			EngineStates[i].Reversed = TurbineEngine->GetReversed();
			EngineStates[i].Injection = TurbineEngine->GetInjection();
			EngineStates[i].CutOff = TurbineEngine->GetCutoff();
			EngineStates[i].Ignition = TurbineEngine->GetIgnition();
			break;
		}
		case JSBSim::FGEngine::etRocket:
		{
			// TODO
			// FGRocket code block
			// FGRocket* RocketEngine = (FGRocket*)Propulsion->GetEngine(i);
			break;
		}
		case JSBSim::FGEngine::etTurboprop:
		{
			// TODO
			//// FGTurboProp code block
			//JSBSim::FGTurboProp* TurboPropEngine = (JSBSim::FGTurboProp*)Propulsion->GetEngine(i);
			//TurboPropEngine->SetReverse(EngineCommand.Reverse);
			//TurboPropEngine->SetCutoff(EngineCommand.CutOff);
			//TurboPropEngine->SetGeneratorPower(EngineCommand.GeneratorPower);
			//TurboPropEngine->SetCondition(EngineCommand.Condition);
			break;
		}
		default:
			break;
		}
	}
}

/////////// Logging and Debugging Methods

void UJSBSimMovementComponent::LogInitialization()
{
	UE_LOG(LogJSBSim, Display, TEXT("Initialized JSB Sim with : "));

	// Speed
	switch (IC->GetSpeedSet())
	{
		//typedef enum { setvt, setve, setvg } speedset; ??? 
	case JSBSim::setned: // North East Down
		UE_LOG(LogJSBSim, Display, TEXT("  Vn,Ve,Vd= %f, $f, $f  ft/s"), Propagate->GetVel(JSBSim::FGJSBBase::eNorth), Propagate->GetVel(JSBSim::FGJSBBase::eEast), Propagate->GetVel(JSBSim::FGJSBBase::eDown));
		break;
	case JSBSim::setuvw:
		UE_LOG(LogJSBSim, Display, TEXT("  U,V,W= %f, $f, $f  ft/s"), Propagate->GetUVW(1), Propagate->GetUVW(2), Propagate->GetUVW(3));
		break;
	case JSBSim::setmach:
		UE_LOG(LogJSBSim, Display, TEXT("  Mach: %f, $f, $f  ft/s"), Auxiliary->GetMach());
		break;
	case JSBSim::setvc:
	default:
		UE_LOG(LogJSBSim, Display, TEXT("  Indicated Airspeed: %f knots"), Auxiliary->GetVcalibratedKTS());
		break;
	}
	
	// Angles
	UE_LOG(LogJSBSim, Display, TEXT("  Bank: %f, Pitch: %f, True Heading: %f"), 
		FMath::RadiansToDegrees(Propagate->GetEuler(JSBSim::FGJSBBase::ePhi)),
		FMath::RadiansToDegrees(Propagate->GetEuler(JSBSim::FGJSBBase::eTht)),
		FMath::RadiansToDegrees(Propagate->GetEuler(JSBSim::FGJSBBase::ePsi)));

	// Lat/Long
	UE_LOG(LogJSBSim, Display, TEXT("  Latitude: %f, Longitude: %f deg, Altitude: %f feet"), Propagate->GetLocation().GetGeodLatitudeDeg(),	Propagate->GetLocation().GetLongitudeDeg(),	Propagate->GetAltitudeASL());
}

void UJSBSimMovementComponent::DrawDebugMessage()
{
	// Build message string before displaying it at once
	FString DebugMessage;

	// Commands
	DebugMessage += Commands.GetDebugMessage();

	// Engines 
	int32 NumEngines = EngineCommands.Num();
	// Engine Commands
	DebugMessage += LINE_TERMINATOR;
	DebugMessage += FString::Printf(TEXT("Engines Commands (%d) : "), NumEngines) + LINE_TERMINATOR;
	for (int32 i = 0; i < NumEngines; i++)
	{
		DebugMessage += FString::Printf(TEXT("    #%d    "), i) + EngineCommands[i].GetDebugMessage();
	}
	// Engine States
	DebugMessage += LINE_TERMINATOR;
	DebugMessage += FString::Printf(TEXT("Engines States (%d) : "), NumEngines) + LINE_TERMINATOR;
	for (int32 i = 0; i < NumEngines; i++)
	{
		DebugMessage += FString::Printf(TEXT("    #%d    "), i) + EngineStates[i].GetDebugMessage();
	}

	// Tanks
	DebugMessage += LINE_TERMINATOR;
	int32 NumTanks = Tanks.Num();
	DebugMessage += FString::Printf(TEXT("Tanks (%d) : "), NumTanks) + LINE_TERMINATOR;
	for (int32 i = 0; i < NumTanks; i++)
	{
		DebugMessage += FString::Printf(TEXT("    #%d    "), i) + Tanks[i].GetDebugMessage();
	}

	// Gears
	DebugMessage += LINE_TERMINATOR;
	int32 NumGears = Gears.Num();
	DebugMessage += FString::Printf(TEXT("Landing Gears (%d) : "), NumGears) + LINE_TERMINATOR;
	for (int32 i = 0; i < NumGears; i++)
	{
		if (Gears[i].IsBogey)
		{
			DebugMessage += FString::Printf(TEXT("    #%d    "), i) + Gears[i].GetDebugMessage();
		}
	}

	// Aircraft State 
	DebugMessage += LINE_TERMINATOR;
	DebugMessage += AircraftState.GetDebugMessage();

	// Draw
    FVector2D TextScale = FVector2D::UnitVector;
	GEngine->AddOnScreenDebugMessage(1, 0, FColor::Green, *DebugMessage, false, TextScale);
}

void UJSBSimMovementComponent::DrawDebugObjects()
{
	for (FGear Gear : Gears)
	{
		FVector WorldPosition = GetOwner()->GetTransform().TransformPosition(Gear.RelativeLocation);
		
		if (Gear.IsBogey)
		{
			if (Gear.HasWeightOnWheel)
			{
				DrawDebugPoint(GetWorld(), WorldPosition, 8, FColor::Red, false);
				DrawDebugLine(GetWorld(), WorldPosition, WorldPosition + Gear.Force, FColor::Red, false, -1, 0, 3);
			}
			else
			{
				DrawDebugPoint(GetWorld(), WorldPosition, 8, FColor::Green, false);
				
			}
		}
		else
		{
			DrawDebugPoint(GetWorld(), WorldPosition, 8, FColor(128,128,128), false);
		}
	}


	//for (int i = 0; i < GroundReactions->GetNumGearUnits(); i++)
	//{
	//	JSBSim::FGLGear* Gear = GroundReactions->GetGearUnit(i);

	//	if (Gear->IsBogey())
	//	{
	//		JSBSim::FGColumnVector3 BodyLocation = Gear->GetBodyLocation();

	//		double XOffset = BodyLocation(1);
	//		double YOffset = BodyLocation(2);
	//		double ZOffset = -BodyLocation(3);

	//		FVector WorldPosition = GetOwner()->GetTransform().TransformPosition(FVector(XOffset, YOffset, ZOffset) * FEET_TO_METER * 100);
	//		DrawDebugPoint(GetWorld(), WorldPosition, 8, FColor::Red, false);
	//	}
	//	
	//}
}


/////////// In-Editor Specific
#if WITH_EDITOR

void UJSBSimMovementComponent::PostEditChangeProperty(FPropertyChangedEvent& PropertyChangedEvent)
{
	static const FName NAME_AircraftModel = GET_MEMBER_NAME_CHECKED(UJSBSimMovementComponent, AircraftModel);
	if (PropertyChangedEvent.Property != nullptr && PropertyChangedEvent.Property->GetFName() == NAME_AircraftModel)
	{
		// Load the aircraft, and make sure we recreate the Component properties for this new one. 
		LoadAircraft(true);
	}

	static const FName NAME_StructuralFrameOrigin = GET_MEMBER_NAME_CHECKED(UJSBSimMovementComponent, StructuralFrameOrigin);
	if (PropertyChangedEvent.Property != nullptr && PropertyChangedEvent.MemberProperty->GetFName() == NAME_StructuralFrameOrigin)
	{
		UpdateLocalTransforms();
	}

	Super::PostEditChangeProperty(PropertyChangedEvent);
}

void UJSBSimMovementComponent::PrepareModelForCompVisualizer()
{
	if (!IsReadyForCompVisualizer)
	{
		if (Exec == nullptr || !AircraftModel.Compare(FString(Exec->GetModelName().c_str()), ESearchCase::IgnoreCase))
		{
			LoadAircraft(false);
			PrepareJSBSim();
			IsReadyForCompVisualizer = true;
		}
	}
}

#endif
